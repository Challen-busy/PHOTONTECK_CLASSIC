"""总账·第八波（finance-gl wave-8）应收款管理 Phase2：业财映射 effect + 通用核销引擎命令骨架。

★本模块已由 Phase1 双注册占位（见 command_registry.load_commands + workflow_extensions._EXTENSION_MODULES），
在此 @register_command / @register_transition_effect 即自动生效，核心三件（registry / execute_transition /
execute_command）字节级零 diff。写仍走唯一写入路径 execute_transition（建空凭证 → DRAFT → 分录 sub_updates）。

本文件（应收业财映射 + 报表 PM 职责）实现：

  业财映射（按公司 region 取本家 AccountMappingRule，科目码不硬编码）:
    · create_voucher_from_ar_bill(应收单审核 → 凭证)
        CAS：借 1122 应收账款 / 贷 6001 主营业务收入 / 贷 222102 应交增值税(销项)（tax_amount=0 则省此行）
        HKFRS：借 1122 Trade receivables / 贷 6001 Revenue（无销项税）
        金额取应收单头已算好的 amount(价税合计) / untaxed_amount(不含税) / tax_amount(税额)，本位币双金额。
    · create_voucher_from_ar_receipt(收款单审核 → 凭证)
        借 1002 银行存款 / 贷 1122 应收账款（核销冲减）或 2203 预收账款（is_advance 预收）。
    两者均经 execute_transition(doc_id=None→START→DRAFT) 建草稿，回链 source_doc_*，幂等守卫。

  effect（auto=False，挂在 seed_receivable 的 AUDITED 边 effects[]）:
    · finance.create_voucher_from_ar_bill      （ACCOUNTS_RECEIVABLE，to_state=AUDITED）
    · finance.create_voucher_from_ar_receipt   （AR_RECEIPT，to_state=AUDITED）

  批量命令（@register_command，module=FINANCE）:
    · finance.generate_ar_vouchers   按方案批量生成应收/收款凭证（DETAIL 一单一凭证；SUMMARY 汇总 TODO⚠️）。

★通用化：科目码 + 取数走 AccountMappingRule（source_doc_type=ACCOUNTS_RECEIVABLE / AR_RECEIPT，
  trigger_action=AUDITED），按 company_id 取本家规则（HKFRS/CAS 差异落各家 account_code）。应付款管理
  后续按 biz_type=AP 复用同套 effect 骨架（建 PURCHASE/付款单的 AccountMappingRule + 仿写两个 create_*）。

副作用在 execute_transition 同事务内运行：只 db.add()/db.flush()，绝不 commit，失败 raise 由引擎回滚。
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.finance_mapping import _num, _one, _open_period, _q2
from services.tools import _company_filter
from services.workflow import execute_transition
from services.workflow_extensions import register_transition_effect


# 业财映射触发动作（应收单/收款单审核生凭证）：对齐流程目标态 AUDITED。
TRIGGER_AUDITED = "AUDITED"
SRC_AR_BILL = "ACCOUNTS_RECEIVABLE"   # 应收单 source_doc_type（幂等锚 + 回链）
SRC_AR_RECEIPT = "AR_RECEIPT"         # 收款单 source_doc_type


# ============================================================
# 共用：取本公司科目 / 取业财映射规则的科目码（按 dr_cr + account_code 取，金额由业务单头字段供）
# ============================================================

async def _account(db: AsyncSession, company_id: int, code: str):
    return await _one(db, m.Account, m.Account.company_id == company_id, m.Account.code == code)


async def _rule_codes(
    db: AsyncSession, company_id: int, source_doc_type: str, trigger_action: str, as_of: date
) -> list[m.AccountMappingRule]:
    """取本公司该业务单 + 触发动作的生效规则（同 line_seq 多版本取 effective_date≤as_of 最新一版）。

    应收/收款凭证的金额由业务单头已算好的字段（价税合计/不含税/税额；银行/应收/预收）直接供，
    规则只提供「每行的科目码 + 借贷方向 + 摘要模板」——故此处只读 dr_cr/account_code/memo，
    不走 finance_mapping 的 amount_formula/tax_handling 求值（应收单头无 tax_rate 可逆推单行税）。
    """
    rows = (await db.execute(
        select(m.AccountMappingRule).where(
            m.AccountMappingRule.company_id == company_id,
            m.AccountMappingRule.source_doc_type == source_doc_type,
            m.AccountMappingRule.trigger_action == trigger_action,
            m.AccountMappingRule.is_active == True,
            m.AccountMappingRule.effective_date <= as_of,
        ).order_by(m.AccountMappingRule.line_seq, m.AccountMappingRule.effective_date.desc())
    )).scalars().all()
    by_seq: dict[int, m.AccountMappingRule] = {}
    for r in rows:
        by_seq.setdefault(r.line_seq, r)
    return [by_seq[k] for k in sorted(by_seq)]


def _entry(line_number, account_id, is_debit, orig, base, currency, rate, memo, aux_id):
    """组一条 VoucherEntry 草稿行 dict（对齐 workflow._apply_sub_updates 字段）。"""
    return {
        "line_number": line_number,
        "account_id": account_id,
        "description": (memo or "")[:200],
        "debit": orig if is_debit else Decimal("0"),
        "credit": Decimal("0") if is_debit else orig,
        "currency": currency or "CNY",
        "exchange_rate": rate,
        "base_debit": base if is_debit else Decimal("0"),
        "base_credit": Decimal("0") if is_debit else base,
        "aux_party_type": "CUSTOMER" if aux_id else None,
        "aux_party_id": aux_id,
    }


async def _voucher_word(db: AsyncSession, company_id: int, code: str):
    return await _one(db, m.VoucherWord, m.VoucherWord.company_id == company_id, m.VoucherWord.code == code)


async def _build_and_post_voucher(
    db: AsyncSession,
    user: m.UserAccount,
    *,
    company_id: int,
    voucher_date: date,
    description: str,
    word_code: str,
    entries: list[dict],
    source_doc_type: str,
    source_doc_id: int,
    auto_post: bool,
    auditor: m.UserAccount | None,
    poster: m.UserAccount | None,
) -> int:
    """共用建单：execute_transition(doc_id=None→START→DRAFT) 建凭证 + 分录；auto_post 时再审核过账。

    返回 voucher_id。借贷平衡/期间锁/职责分离三校验在过账时由引擎 validator 自动跑。
    """
    period = await _open_period(db, company_id, voucher_date)
    if period is None:
        raise ValueError(f"公司#{company_id} 在 {voucher_date} 无 OPEN 会计期间，无法生成凭证")

    word = await _voucher_word(db, company_id, word_code)
    total_debit = _q2(sum((e["base_debit"] for e in entries), Decimal("0")))
    total_credit = _q2(sum((e["base_credit"] for e in entries), Decimal("0")))

    head = {
        "voucher_date": voucher_date,
        "voucher_word_id": getattr(word, "id", None),
        "voucher_type": "GENERAL",
        "description": description[:200],
        "period_id": period.id,
        "source_doc_type": source_doc_type,
        "source_doc_id": source_doc_id,
        "total_debit": total_debit,
        "total_credit": total_credit,
    }
    sub_updates = [
        {"table": "voucher_entry", "parent_fk": "voucher_id", "fields": e} for e in entries
    ]

    res = await execute_transition(
        db, "VOUCHER", None, user,
        field_updates=head, sub_updates=sub_updates,
        comment=f"{source_doc_type}#{source_doc_id} → 自动凭证",
        manage_transaction=False,
    )
    if not res.get("success"):
        raise ValueError(f"自动建凭证失败: {res.get('error')}")
    voucher_id = res.get("doc_id") or res.get("id")

    r_draft = await execute_transition(
        db, "VOUCHER", voucher_id, user, to_state="DRAFT", manage_transaction=False,
    )
    if not r_draft.get("success"):
        raise ValueError(f"凭证入录入态失败: {r_draft.get('error')}")

    if auto_post:
        a = auditor or user
        p = poster or user
        r_aud = await execute_transition(db, "VOUCHER", voucher_id, a, to_state="AUDITED", manage_transaction=False)
        if not r_aud.get("success"):
            raise ValueError(f"自动审核失败: {r_aud.get('error')}")
        r_post = await execute_transition(db, "VOUCHER", voucher_id, p, to_state="POSTED", manage_transaction=False)
        if not r_post.get("success"):
            raise ValueError(f"自动过账失败: {r_post.get('error')}")

    return voucher_id


# ============================================================
# 应收单审核 → 凭证（借 1122 应收 / 贷 6001 收入 / 贷 222102 销项税）
# ============================================================

async def create_voucher_from_ar_bill(
    db: AsyncSession,
    bill: m.AccountsReceivable,
    user: m.UserAccount,
    *,
    trigger_action: str = TRIGGER_AUDITED,
    auto_post: bool = False,
    auditor: m.UserAccount | None = None,
    poster: m.UserAccount | None = None,
) -> dict:
    """应收单（债权立账）审核 → 自动凭证。

    分录（科目码取本家 AccountMappingRule，金额取应收单头已算好字段）:
      · 借 1122 应收账款       = amount（价税合计）
      · 贷 6001 主营业务收入   = untaxed_amount（不含税；缺则回退 amount−tax_amount）
      · 贷 222102 应交增值税(销项) = tax_amount（HK 准则 tax_amount=0 或无该科目规则则省此行）
    本位币双金额 base_* = 原币 × exchange_rate（本币记账 rate=1 → base==原币）。
    幂等：同应收单已生成过凭证（source_doc_type=ACCOUNTS_RECEIVABLE + source_doc_id=bill.id）则返回既有单。
    """
    company_id = bill.company_id
    existing = await _one(
        db, m.Voucher,
        m.Voucher.company_id == company_id,
        m.Voucher.source_doc_type == SRC_AR_BILL,
        m.Voucher.source_doc_id == bill.id,
    )
    if existing:
        return {"voucher_id": existing.id, "created": False,
                "posted": existing.status == "POSTED", "reason": "voucher already exists"}

    biz_date = bill.bill_date or bill.due_date or date.today()
    rate = _num(getattr(bill, "exchange_rate", None) or 1) or Decimal("1")
    currency = bill.currency or bill.base_currency or "CNY"

    rules = await _rule_codes(db, company_id, SRC_AR_BILL, trigger_action, biz_date)
    if not rules:
        return {"created": False, "reason": "no active AccountMappingRule for ACCOUNTS_RECEIVABLE"}

    gross = _q2(_num(bill.amount))
    tax = _q2(_num(bill.tax_amount))
    net = _q2(_num(bill.untaxed_amount)) if _num(bill.untaxed_amount) != 0 else _q2(gross - tax)
    customer_id = getattr(bill, "customer_id", None)

    # 按规则 dr_cr 分配金额：借方=价税合计（应收）；贷方有两行时第一行=收入(不含税)、销项税行=税额。
    # 规则行序（line_seq）：CAS 1=DR应收 / 2=CR收入 / 3=CR销项；HKFRS 1=DR应收 / 2=CR收入。
    entries: list[dict] = []
    line_number = 0
    credit_rules = [r for r in rules if (r.dr_cr or "").upper() == "CR"]
    tax_code = "222102"  # 销项税科目码（CAS）；HKFRS 无此规则行
    for rule in rules:
        is_debit = (rule.dr_cr or "").upper() == "DR"
        if is_debit:
            amt = gross
        elif rule.account_code == tax_code or len(credit_rules) == 1:
            # 单贷方行（HK 无税）→ 收入吃全额（=不含税，HK net==gross）；销项税行 → 税额。
            amt = tax if rule.account_code == tax_code else net
        else:
            amt = net  # 多贷方行里的收入行 = 不含税。
        amt = _q2(amt)
        if amt == 0:
            continue  # 税额为 0 的销项税行（HK 或免税）：跳过空行。
        account = await _account(db, company_id, rule.account_code)
        if account is None:
            raise ValueError(f"应收业财映射 line_seq={rule.line_seq} 科目码 {rule.account_code!r} 在公司#{company_id} 不存在")
        line_number += 1
        base = _q2(amt * rate)
        memo = (rule.memo_template or "").replace("{bill_number}", bill.bill_number or "").strip()
        entries.append(_entry(
            rule.line_seq or line_number, account.id, is_debit, amt, base, currency, rate,
            memo or f"应收单 {bill.bill_number or bill.invoice_number}",
            customer_id if is_debit else None,
        ))

    if not entries:
        return {"created": False, "reason": "no non-zero entries (check bill amounts)"}

    voucher_id = await _build_and_post_voucher(
        db, user, company_id=company_id, voucher_date=biz_date,
        description=f"应收单审核自动凭证：{bill.bill_number or bill.invoice_number}",
        word_code="转", entries=entries,
        source_doc_type=SRC_AR_BILL, source_doc_id=bill.id,
        auto_post=auto_post, auditor=auditor, poster=poster,
    )
    if getattr(bill, "voucher_id", None) is None:
        bill.voucher_id = voucher_id
        await db.flush()
    return {"voucher_id": voucher_id, "created": True, "posted": auto_post, "lines": len(entries)}


# ============================================================
# 收款单审核 → 凭证（借 1002 银行 / 贷 1122 应收 或 贷 2203 预收）
# ============================================================

async def create_voucher_from_ar_receipt(
    db: AsyncSession,
    receipt: m.ARReceipt,
    user: m.UserAccount,
    *,
    trigger_action: str = TRIGGER_AUDITED,
    auto_post: bool = False,
    auditor: m.UserAccount | None = None,
    poster: m.UserAccount | None = None,
) -> dict:
    """收款单（已收款）审核 → 自动凭证。

    分录（科目码取本家 AccountMappingRule，借方恒为银行存款，贷方按是否预收切换）:
      · 借 1002 银行存款 = amount
      · 贷 1122 应收账款（核销冲减，is_advance=False）  或  贷 2203 预收账款（is_advance=True）
    规则约定：debit 行 = 银行；credit 行种两条（应收冲减行 / 预收行），按 is_advance 选其一。
    本位币双金额 base_* = 原币 × exchange_rate。幂等同 create_voucher_from_ar_bill。
    """
    company_id = receipt.company_id
    existing = await _one(
        db, m.Voucher,
        m.Voucher.company_id == company_id,
        m.Voucher.source_doc_type == SRC_AR_RECEIPT,
        m.Voucher.source_doc_id == receipt.id,
    )
    if existing:
        return {"voucher_id": existing.id, "created": False,
                "posted": existing.status == "POSTED", "reason": "voucher already exists"}

    biz_date = receipt.receipt_date or date.today()
    rate = _num(getattr(receipt, "exchange_rate", None) or 1) or Decimal("1")
    currency = receipt.currency or receipt.base_currency or "CNY"
    amount = _q2(_num(receipt.amount))
    if amount == 0:
        return {"created": False, "reason": "receipt amount is zero"}

    rules = await _rule_codes(db, company_id, SRC_AR_RECEIPT, trigger_action, biz_date)
    if not rules:
        return {"created": False, "reason": "no active AccountMappingRule for AR_RECEIPT"}

    advance_code = "2203"  # 预收账款科目码（贷方，is_advance=True 时选用）。
    customer_id = getattr(receipt, "customer_id", None)
    entries: list[dict] = []
    line_number = 0
    for rule in rules:
        is_debit = (rule.dr_cr or "").upper() == "DR"
        is_advance_rule = rule.account_code == advance_code
        # 贷方按 is_advance 选行：预收 → 只取预收行；非预收 → 只取应收冲减行。
        if not is_debit:
            if receipt.is_advance and not is_advance_rule:
                continue
            if (not receipt.is_advance) and is_advance_rule:
                continue
        account = await _account(db, company_id, rule.account_code)
        if account is None:
            raise ValueError(f"收款业财映射 line_seq={rule.line_seq} 科目码 {rule.account_code!r} 在公司#{company_id} 不存在")
        line_number += 1
        base = _q2(amount * rate)
        memo = (rule.memo_template or "").replace("{receipt_number}", receipt.receipt_number or "").strip()
        entries.append(_entry(
            rule.line_seq or line_number, account.id, is_debit, amount, base, currency, rate,
            memo or f"收款单 {receipt.receipt_number}",
            customer_id if not is_debit else None,  # 往来辅助核算挂在应收/预收（贷方）侧。
        ))

    if len(entries) < 2:
        return {"created": False, "reason": "AR_RECEIPT rules incomplete (need 借银行 + 贷应收/预收)"}

    voucher_id = await _build_and_post_voucher(
        db, user, company_id=company_id, voucher_date=biz_date,
        description=f"收款单审核自动凭证：{receipt.receipt_number}"
                    + ("（预收）" if receipt.is_advance else ""),
        word_code="收", entries=entries,
        source_doc_type=SRC_AR_RECEIPT, source_doc_id=receipt.id,
        auto_post=auto_post, auditor=auditor, poster=poster,
    )
    if getattr(receipt, "voucher_id", None) is None:
        receipt.voucher_id = voucher_id
        await db.flush()
    return {"voucher_id": voucher_id, "created": True, "posted": auto_post, "lines": len(entries)}


# ============================================================
# 流程 effect：应收单 / 收款单 审核（to_state=AUDITED）边上挂「自动生成凭证」
#   auto=False，须在 seed_receivable 的 AUDITED 边 effects[] 显式点名。
# ============================================================

@register_transition_effect(
    "finance.create_voucher_from_ar_bill",
    doc_type="ACCOUNTS_RECEIVABLE", to_state="AUDITED", auto=False,
)
async def create_voucher_from_ar_bill_effect(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """应收单审核 effect：按本公司业财映射规则自动生成应收凭证草稿（借应收/贷收入+贷销项税），回链应收单。

    只建草稿（auto_post=False），由财务在凭证录入屏复核后审核过账（职责分离 + 人工把关）。
    幂等由 create_voucher_from_ar_bill 内的 source_doc 守卫保证。
    """
    result = await create_voucher_from_ar_bill(db, doc, user, trigger_action=to_state or TRIGGER_AUDITED)
    if not result.get("created"):
        return [f"应收单#{doc.id} 未生成凭证：{result.get('reason')}"]
    return [f"应收单#{doc.id} → 自动凭证#{result['voucher_id']}（{result['lines']} 行，草稿待审核过账）"]


@register_transition_effect(
    "finance.create_voucher_from_ar_receipt",
    doc_type="AR_RECEIPT", to_state="AUDITED", auto=False,
)
async def create_voucher_from_ar_receipt_effect(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """收款单审核 effect：自动生成收款凭证草稿（借银行/贷应收 或 贷预收），回链收款单。"""
    result = await create_voucher_from_ar_receipt(db, doc, user, trigger_action=to_state or TRIGGER_AUDITED)
    if not result.get("created"):
        return [f"收款单#{doc.id} 未生成凭证：{result.get('reason')}"]
    return [f"收款单#{doc.id} → 自动凭证#{result['voucher_id']}（{result['lines']} 行，草稿待审核过账）"]


# ============================================================
# 批量命令：finance.generate_ar_vouchers（DETAIL 一单一凭证 / SUMMARY 汇总 TODO⚠️）
# ============================================================

def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


@register_command(
    "finance.generate_ar_vouchers",
    module="FINANCE",
    title="批量生成应收/收款凭证",
    description=(
        "按公司批量为已审核的应收单/收款单生成凭证草稿（业财映射）。"
        "mode=DETAIL 一单一凭证（默认）；SUMMARY 汇总模式（按科目合并，TODO⚠️待复核口径，暂不实现）。"
        "source=AR_BILL/AR_RECEIPT/BOTH。已生成过凭证的单据幂等跳过。"
    ),
    affected_tables=("voucher", "voucher_entry", "accounts_receivable", "ar_receipt"),
    supports_retry=True,
)
async def generate_ar_vouchers(ctx: CommandContext, payload: dict) -> dict:
    """批量生成应收/收款凭证。

    payload：
      company_id: int   —— 公司 id（必填）
      source: 'AR_BILL' | 'AR_RECEIPT' | 'BOTH'   —— 处理对象（默认 BOTH）
      mode: 'DETAIL' | 'SUMMARY'                  —— DETAIL 一单一凭证（默认）；SUMMARY 汇总 TODO⚠️
      auto_post: bool   —— 是否自动审核过账（默认 False，仅建草稿；自动过账须制单≠审核≠过账，慎用）
      bill_ids / receipt_ids: list[int]  —— 可选，限定范围；不传则取该公司全部已审核未生凭证的单

    逐单 execute_transition 风格：一单失败不阻断其余（收进 failed），命令外壳统一 commit/留痕/幂等。
    """
    company_id = payload.get("company_id")
    if not company_id:
        raise CommandError("company_id 不能为空")
    _assert_company_access(ctx.user, company_id)

    source = (payload.get("source") or "BOTH").upper()
    mode = (payload.get("mode") or "DETAIL").upper()
    if mode == "SUMMARY":
        # SUMMARY 汇总模式（按科目/客户合并多单成一张凭证）口径未定（合并维度、回链多源、反核销拆分），
        # 标 ⚠️待复核，本波不实现，显式拒绝避免静默走 DETAIL。
        raise CommandError("SUMMARY 汇总模式 TODO⚠️（口径待复核），当前仅支持 mode=DETAIL", 422)
    auto_post = bool(payload.get("auto_post", False))

    created: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    async def _run_bills():
        stmt = select(m.AccountsReceivable).where(
            m.AccountsReceivable.company_id == company_id,
            m.AccountsReceivable.status == "AUDITED",
        )
        if payload.get("bill_ids"):
            stmt = stmt.where(m.AccountsReceivable.id.in_(payload["bill_ids"]))
        bills = (await ctx.db.execute(stmt.order_by(m.AccountsReceivable.id))).scalars().all()
        for bill in bills:
            try:
                r = await create_voucher_from_ar_bill(ctx.db, bill, ctx.user, auto_post=auto_post)
                if r.get("created"):
                    created.append({"source": "AR_BILL", "doc_id": bill.id, "voucher_id": r["voucher_id"]})
                else:
                    skipped.append({"source": "AR_BILL", "doc_id": bill.id, "reason": r.get("reason")})
            except Exception as exc:  # noqa: BLE001 — 单失败不阻断批
                failed.append({"source": "AR_BILL", "doc_id": bill.id, "error": str(exc)})

    async def _run_receipts():
        stmt = select(m.ARReceipt).where(
            m.ARReceipt.company_id == company_id,
            m.ARReceipt.status == "AUDITED",
        )
        if payload.get("receipt_ids"):
            stmt = stmt.where(m.ARReceipt.id.in_(payload["receipt_ids"]))
        receipts = (await ctx.db.execute(stmt.order_by(m.ARReceipt.id))).scalars().all()
        for rcpt in receipts:
            try:
                r = await create_voucher_from_ar_receipt(ctx.db, rcpt, ctx.user, auto_post=auto_post)
                if r.get("created"):
                    created.append({"source": "AR_RECEIPT", "doc_id": rcpt.id, "voucher_id": r["voucher_id"]})
                else:
                    skipped.append({"source": "AR_RECEIPT", "doc_id": rcpt.id, "reason": r.get("reason")})
            except Exception as exc:  # noqa: BLE001
                failed.append({"source": "AR_RECEIPT", "doc_id": rcpt.id, "error": str(exc)})

    if source in ("AR_BILL", "BOTH"):
        await _run_bills()
    if source in ("AR_RECEIPT", "BOTH"):
        await _run_receipts()

    ctx.add_event("finance_generate_ar_vouchers", {
        "company_id": company_id, "source": source, "mode": mode,
        "created": len(created), "skipped": len(skipped), "failed": len(failed),
    })
    return {
        "company_id": company_id, "source": source, "mode": mode, "auto_post": auto_post,
        "created": created, "skipped": skipped, "failed": failed,
        "summary": {"created": len(created), "skipped": len(skipped), "failed": len(failed)},
    }
