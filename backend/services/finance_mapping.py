"""总账·第二波（finance-gl wave-2）模块 C：业财映射引擎（业务单 → 凭证分录 → 自动建/过账）。

纯扩展、新文件。引擎核心三件（registry / execute_transition / execute_command）字节级零 diff；
写仍走唯一写入路径 execute_transition（doc_id=None 建空凭证 + sub_updates 分录 → 推 AUDITED → POSTED）。

一条端到端打通（销售开票 → 自动凭证）：
  1) map_to_voucher_entries(db, company_id, source_doc_type, trigger_action, doc)
     读 AccountMappingRule（按 company_id + source_doc_type + trigger_action + effective_date 取本家当前
     版本规则），把业务单字段按 amount_formula / tax_handling / account_source 解析成 VoucherEntry 草稿
     行列表（借贷由 f(account.balance_direction, dr_cr) 推导，原币 + 本位币双金额 base_* = 原币×汇率）。
  2) create_voucher_from_sales_invoice(db, invoice, user, auto_post=False)
     用 (1) 生成凭证草稿（借 应收 / 贷 主营收入 + 贷 销项税），经 execute_transition 建 VOUCHER（入 START
     取号 → DRAFT），sub_updates 写分录；回链 source_doc_type=SALES_INVOICE / source_doc_id=invoice.id。
     auto_post=True 时再走标准状态机审核 + 过账（finance.post_voucher 累加 AccountBalance）。
  3) 注册 effect finance.create_voucher_from_sales_invoice（auto=False），可挂在销项发票/应收确认的
     SALES_INVOICE 流程边 effects[] 上（与现有 finance.create_accounts_receivable_from_sales_invoice 并列）。

★科目码不在代码硬编码：按 company_id 取本家 AccountMappingRule.account_code。HK/CAS 准则差异
  （HK 6401=Selling expenses≠主营成本 / HK 5001=Cost of sales；CAS 6401=主营业务成本）落在各家规则行的
  account_code 上（见 scripts/seed_mapping.py 按 region 种码）。

account_source 取数（当前可解析口径，诚实降级）：
  · FIXED          → 直接用规则 account_code（应收/收入/销项税控制科目）。
  · CUSTOMER/SUPPLIER/MATERIAL_DEFAULT → 主数据上暂无「往来对象/物料默认 GL 科目」列（Customer/Material
    未建该字段），先回退到规则 account_code 作控制科目（与「往来对象走控制科目 + 辅助核算挂往来对象」的
    通行做法一致）；客户在 entry.aux_party_type=CUSTOMER / aux_party_id=customer_id 上挂辅助核算。
    待主数据补「客户/供应商默认科目」字段后，本函数按对象覆盖即可（留 TODO）。

副作用在 execute_transition 同事务内运行：只 db.add()/db.flush()，绝不 commit，失败 raise 由引擎回滚。
本模块若要让 effect 注册生效，需把 "services.finance_mapping" 加入 workflow_extensions._EXTENSION_MODULES
（非本波必须；smoke/seed 直接调用 create_voucher_from_sales_invoice，不依赖注册）。
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.workflow import execute_transition
from services.workflow_extensions import register_transition_effect


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


async def _one(db: AsyncSession, model, *where):
    stmt = select(model)
    for clause in where:
        stmt = stmt.where(clause)
    return (await db.execute(stmt.limit(1))).scalar_one_or_none()


# ============================================================
# 取数表达式：受限白名单求值（amount_formula）
#   只放行业务单字段名 + 四则 + 括号，不用裸 eval 全局（防注入）。
#   可用变量：amount（金额，含/不含税由 tax_handling 与公式共同决定）、tax_rate（小数，如 0.13）、
#            quantity / unit_price（若单上有）。变量缺则按 0 代入。
# ============================================================
_ALLOWED_VARS = ("amount", "tax_rate", "quantity", "unit_price", "qty", "price")


def _doc_value(doc, name: str) -> Decimal:
    """从业务单取一个数值字段（缺则 0）。tax_rate 上若是百分比口径（如 13）折算成小数 0.13。"""
    if name in ("qty",):
        name = "quantity"
    if name in ("price",):
        name = "unit_price"
    raw = getattr(doc, name, None)
    val = _num(raw)
    if name == "tax_rate" and val > 1:  # 单上税率存的是百分比（13 表 13%）→ 折小数
        val = val / Decimal("100")
    return val


def _eval_formula(formula: str, doc) -> Decimal:
    """对 amount_formula 求值（受限）。空公式默认取 amount。

    安全：编译后校验 AST 只含数字/名字（白名单）/四则运算/一元负号/括号，名字按业务单字段代入 Decimal。
    """
    import ast

    expr = (formula or "").strip()
    if not expr:
        return _doc_value(doc, "amount")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"取数表达式语法错误: {formula!r} ({exc})")

    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant):  # 数字常量
            if isinstance(node.value, (int, float)):
                return Decimal(str(node.value))
            raise ValueError(f"取数表达式不支持的常量: {node.value!r}")
        if isinstance(node, ast.Name):
            if node.id not in _ALLOWED_VARS:
                raise ValueError(f"取数表达式不允许的变量: {node.id!r}（白名单 {_ALLOWED_VARS}）")
            return _doc_value(doc, node.id)
        if isinstance(node, ast.BinOp):
            left, right = _ev(node.left), _ev(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("取数表达式除零")
                return left / right
            raise ValueError(f"取数表达式不支持的运算: {type(node.op).__name__}")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = _ev(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        raise ValueError(f"取数表达式不支持的节点: {type(node).__name__}")

    return _ev(tree)


def _apply_tax_handling(base_amount: Decimal, tax_handling: str, doc) -> Decimal:
    """按 tax_handling 在「公式算出的额」基础上再做含/不含税口径折算。

    公式已经能表达大部分口径（amount / amount/(1+tax_rate) / amount*tax_rate）；tax_handling 给
    「公式只写 amount、由 handling 折算」的便捷路径：
      · NONE      → 原样（公式说了算）。
      · INCLUSIVE → 价税合计原样（应收行常用，= 含税额）。
      · EXCLUSIVE → 不含税额 = amount / (1 + tax_rate)（收入行常用）。
      · TAX_ONLY  → 仅税额 = amount − amount/(1+tax_rate)（销项税行常用）。
    """
    handling = (tax_handling or "NONE").upper()
    if handling in ("NONE", "INCLUSIVE"):
        return base_amount
    tax_rate = _doc_value(doc, "tax_rate")
    if tax_rate <= 0:
        return base_amount if handling != "TAX_ONLY" else Decimal("0")
    net = base_amount / (Decimal("1") + tax_rate)
    if handling == "EXCLUSIVE":
        return net
    if handling == "TAX_ONLY":
        return base_amount - net
    return base_amount


async def _rules_for(
    db: AsyncSession, company_id: int, source_doc_type: str, trigger_action: str, as_of: date
) -> list[m.AccountMappingRule]:
    """取本公司该业务单 + 触发动作的生效规则（同 line_seq 多版本按 effective_date 取 ≤ as_of 最新）。"""
    rows = (await db.execute(
        select(m.AccountMappingRule).where(
            m.AccountMappingRule.company_id == company_id,
            m.AccountMappingRule.source_doc_type == source_doc_type,
            m.AccountMappingRule.trigger_action == trigger_action,
            m.AccountMappingRule.is_active == True,
            m.AccountMappingRule.effective_date <= as_of,
        ).order_by(m.AccountMappingRule.line_seq, m.AccountMappingRule.effective_date.desc())
    )).scalars().all()
    # 每个 line_seq 取生效日最新的一版（已按 effective_date desc 排，首见即最新）。
    by_seq: dict[int, m.AccountMappingRule] = {}
    for r in rows:
        by_seq.setdefault(r.line_seq, r)
    return [by_seq[k] for k in sorted(by_seq)]


def _resolve_account_code(rule: m.AccountMappingRule, doc) -> str:
    """按 account_source 解析目标科目码。

    当前 FIXED 直接用规则 account_code；CUSTOMER/SUPPLIER/MATERIAL_DEFAULT 主数据尚无默认 GL 科目列，
    诚实回退到规则 account_code 作控制科目（往来对象经辅助核算挂在分录上，见 map_to_voucher_entries）。
    """
    # TODO（主数据补字段后）：CUSTOMER→customer.receivable_account_code 等覆盖。
    return rule.account_code or ""


def _aux_for_source(account_source: str, doc) -> tuple[str | None, int | None]:
    """往来对象辅助核算：CUSTOMER → (CUSTOMER, doc.customer_id)；SUPPLIER → (SUPPLIER, doc.supplier_id)。"""
    src = (account_source or "").upper()
    if src == "CUSTOMER":
        return "CUSTOMER", getattr(doc, "customer_id", None)
    if src == "SUPPLIER":
        return "SUPPLIER", getattr(doc, "supplier_id", None)
    return None, None


async def map_to_voucher_entries(
    db: AsyncSession,
    company_id: int,
    source_doc_type: str,
    trigger_action: str,
    doc,
    *,
    base_currency: str = "",
    exchange_rate: Decimal | None = None,
    as_of: date | None = None,
) -> list[dict]:
    """业财映射核心 helper：业务单 → VoucherEntry 草稿行 dict 列表（供 sub_updates 提交）。

    返回每行 dict 字段对齐 VoucherEntry（line_number/account_id/debit/credit/base_debit/base_credit/
    currency/exchange_rate/description/aux_party_type/aux_party_id）。借贷方向由 dr_cr 直译（DR→借、CR→贷），
    金额由 amount_formula + tax_handling 解析；本位币 base_* = 原币 × exchange_rate（本币记账 rate=1 → base==原币）。
    无规则则返回空列表（调用方据此降级，不伪造分录）。
    """
    as_of = as_of or getattr(doc, "invoice_date", None) or date.today()
    rate = _num(exchange_rate if exchange_rate is not None else getattr(doc, "exchange_rate", None) or 1) or Decimal("1")
    rules = await _rules_for(db, company_id, source_doc_type, trigger_action, as_of)
    if not rules:
        return []

    entries: list[dict] = []
    line_number = 0
    for rule in rules:
        amount = _eval_formula(rule.amount_formula, doc)
        amount = _apply_tax_handling(amount, rule.tax_handling, doc)
        amount = _q2(amount)
        if amount == 0:
            continue  # 税额为 0 的销项税行等：跳过空行

        code = _resolve_account_code(rule, doc)
        account = await _one(
            db, m.Account,
            m.Account.company_id == company_id,
            m.Account.code == code,
        )
        if account is None:
            raise ValueError(
                f"业财映射 line_seq={rule.line_seq} 目标科目码 {code!r} 在公司#{company_id} 不存在"
            )

        line_number += 1
        is_debit = (rule.dr_cr or "").upper() == "DR"
        orig = amount
        base = _q2(orig * rate)
        aux_type, aux_id = _aux_for_source(rule.account_source, doc)
        memo = (rule.memo_template or "").strip()[:200]
        entries.append({
            "line_number": rule.line_seq or line_number,
            "account_id": account.id,
            "description": memo,
            "debit": orig if is_debit else Decimal("0"),
            "credit": Decimal("0") if is_debit else orig,
            "currency": base_currency or getattr(doc, "currency", None) or "CNY",
            "exchange_rate": rate,
            "base_debit": base if is_debit else Decimal("0"),
            "base_credit": Decimal("0") if is_debit else base,
            "aux_party_type": aux_type,
            "aux_party_id": aux_id,
        })
    return entries


async def _open_period(db: AsyncSession, company_id: int, on: date):
    """取该公司含 on 日的 OPEN 期间，缺则取该公司任一 OPEN 期间（兜底）。"""
    period = (await db.execute(
        select(m.AccountingPeriod)
        .join(m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id)
        .where(
            m.FiscalYear.company_id == company_id,
            m.AccountingPeriod.status == "OPEN",
            m.AccountingPeriod.start_date <= on,
            m.AccountingPeriod.end_date >= on,
        ).order_by(m.AccountingPeriod.id).limit(1)
    )).scalar_one_or_none()
    if period:
        return period
    return (await db.execute(
        select(m.AccountingPeriod)
        .join(m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id)
        .where(m.FiscalYear.company_id == company_id, m.AccountingPeriod.status == "OPEN")
        .order_by(m.AccountingPeriod.id).limit(1)
    )).scalar_one_or_none()


async def create_voucher_from_sales_invoice(
    db: AsyncSession,
    invoice: m.SalesInvoice,
    user: m.UserAccount,
    *,
    trigger_action: str = "POSTED",
    auto_post: bool = False,
    auditor: m.UserAccount | None = None,
    poster: m.UserAccount | None = None,
) -> dict:
    """★端到端：销售发票 → 自动凭证（借 应收 / 贷 主营收入 + 贷 销项税），走引擎唯一写入路径。

    - 幂等：同一发票已生成过凭证（voucher.source_doc_type=SALES_INVOICE + source_doc_id=invoice.id）则返回既有单。
    - 取规则：按 invoice.company_id + SALES_INVOICE + trigger_action 取本家 AccountMappingRule（HK/CAS 科目码各异）。
    - 建单：execute_transition(doc_id=None) 入 START 取号 → DRAFT；同次提交头字段 + sub_updates 分录。
    - auto_post：再 DRAFT→AUDITED（auditor）→POSTED（poster）；三校验（借贷平衡/期间锁/职责分离）自动跑。
      职责分离要求 制单≠审核≠过账，调用方应传不同 user（smoke 用 finance/fin_dir/boss）。

    返回 {"voucher_id", "created", "posted", "lines"}。无规则则 {"created": False, "reason": "no rule"}。
    """
    company_id = invoice.company_id
    company = await _one(db, m.Company, m.Company.id == company_id)
    base_ccy = (getattr(company, "currency", None) or invoice.currency or "CNY")

    # 幂等：该发票是否已生成凭证。
    existing = await _one(
        db, m.Voucher,
        m.Voucher.company_id == company_id,
        m.Voucher.source_doc_type == "SALES_INVOICE",
        m.Voucher.source_doc_id == invoice.id,
    )
    if existing:
        return {"voucher_id": existing.id, "created": False, "posted": existing.status == "POSTED",
                "reason": "voucher already exists"}

    inv_date = invoice.invoice_date or date.today()
    rate = _num(getattr(invoice, "exchange_rate", None) or 1) or Decimal("1")
    entries = await map_to_voucher_entries(
        db, company_id, "SALES_INVOICE", trigger_action, invoice,
        base_currency=invoice.currency or base_ccy, exchange_rate=rate, as_of=inv_date,
    )
    if not entries:
        return {"created": False, "reason": "no active AccountMappingRule for SALES_INVOICE"}

    period = await _open_period(db, company_id, inv_date)
    if period is None:
        return {"created": False, "reason": "no OPEN accounting period"}

    word = await _one(db, m.VoucherWord, m.VoucherWord.company_id == company_id, m.VoucherWord.code == "转")

    total_debit = _q2(sum((e["base_debit"] for e in entries), Decimal("0")))
    total_credit = _q2(sum((e["base_credit"] for e in entries), Decimal("0")))

    head = {
        "voucher_date": inv_date,
        "voucher_word_id": getattr(word, "id", None),
        "voucher_type": "GENERAL",
        "description": f"销售开票自动凭证：{invoice.invoice_number}"[:200],
        "period_id": period.id,
        "source_doc_type": "SALES_INVOICE",
        "source_doc_id": invoice.id,
        "total_debit": total_debit,
        "total_credit": total_credit,
    }
    # sub_updates 格式对齐 workflow._apply_sub_updates：{table, parent_fk, fields}。
    sub_updates = [
        {"table": "voucher_entry", "parent_fk": "voucher_id", "fields": e}
        for e in entries
    ]

    # 建空凭证：execute_transition(doc_id=None) 落初始 START 态（同事务跑取号 effect），头字段随建单写入。
    # 注：create 路径不卡 editable_fields，按 model 列接受 field_updates；to_state 在建单模式被忽略（恒入 START）。
    res = await execute_transition(
        db, "VOUCHER", None, user,
        field_updates=head, sub_updates=sub_updates,
        comment=f"销售发票 {invoice.invoice_number} → 自动凭证",
        manage_transaction=False,
    )
    if not res.get("success"):
        raise ValueError(f"自动建凭证失败: {res.get('error')}")
    voucher_id = res.get("doc_id") or res.get("id")

    # START → DRAFT（「开始录入」边，editable_fields=[]，不带字段）。
    r_draft = await execute_transition(
        db, "VOUCHER", voucher_id, user, to_state="DRAFT", manage_transaction=False,
    )
    if not r_draft.get("success"):
        raise ValueError(f"凭证入录入态失败: {r_draft.get('error')}")

    posted = False
    if auto_post:
        a = auditor or user
        p = poster or user
        r_aud = await execute_transition(
            db, "VOUCHER", voucher_id, a, to_state="AUDITED", manage_transaction=False,
        )
        if not r_aud.get("success"):
            raise ValueError(f"自动审核失败: {r_aud.get('error')}")
        r_post = await execute_transition(
            db, "VOUCHER", voucher_id, p, to_state="POSTED", manage_transaction=False,
        )
        if not r_post.get("success"):
            raise ValueError(f"自动过账失败: {r_post.get('error')}")
        posted = True

    # 回链：把生成的凭证回写到业务侧应收单 voucher_id（按发票号定位本公司应收），打通「应收单 ↔ 凭证」两侧。
    # 应收单由 finance.create_accounts_receivable_from_sales_invoice 先建（voucher_id 初为空），此处补链。
    ar = await _one(
        db, m.AccountsReceivable,
        m.AccountsReceivable.company_id == company_id,
        m.AccountsReceivable.invoice_number == invoice.invoice_number,
    )
    if ar is not None and getattr(ar, "voucher_id", None) is None:
        ar.voucher_id = voucher_id
        await db.flush()

    return {"voucher_id": voucher_id, "created": True, "posted": posted, "lines": len(entries)}


# ============================================================
# 流程 effect：销项发票 / 应收确认边上挂「自动生成凭证」
#   auto=False，须在 SALES_INVOICE 流程边 effects[] 显式点名（与 finance.create_accounts_receivable_from_sales_invoice 并列）。
#   要注册生效需把 "services.finance_mapping" 加入 workflow_extensions._EXTENSION_MODULES（见模块 docstring）。
# ============================================================

@register_transition_effect("finance.create_voucher_from_sales_invoice", auto=False)
async def create_voucher_from_sales_invoice_effect(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """销售开票 effect：按本公司业财映射规则自动生成凭证草稿（借应收/贷收入+贷销项税），回链发票。

    挂在 SALES_INVOICE 边上（如「确认/过账」边）。本 effect 只建草稿（auto_post=False），由财务在凭证录入屏
    复核后审核过账（保留职责分离 + 人工把关）；要自动过账可在配置里改 auto_post（须不同制单/审核/过账人）。
    幂等由 create_voucher_from_sales_invoice 内的 source_doc 守卫保证。
    """
    trigger = (to_state or "POSTED")
    result = await create_voucher_from_sales_invoice(
        db, doc, user, trigger_action=trigger, auto_post=False,
    )
    if not result.get("created"):
        return [f"销售发票#{doc.id} 未生成凭证：{result.get('reason')}"]
    return [f"销售发票#{doc.id} → 自动凭证#{result['voucher_id']}（{result['lines']} 行，草稿待审核过账）"]
