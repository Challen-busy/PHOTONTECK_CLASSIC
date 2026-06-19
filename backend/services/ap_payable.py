"""应付款管理（finance-gl 应付波）业财映射 effect + 应付凭证批量命令。

★ar_receivable.py 的供应商侧镜像。本模块已由「命令双注册」占位（command_registry.load_commands +
workflow_extensions._EXTENSION_MODULES 均已登记 services.ap_payable），在此 @register_command /
@register_transition_effect 即自动生效，核心三件字节级零 diff。写仍走唯一写入路径 execute_transition。

业财映射（科目码取本公司 AccountMappingRule，按 region 落各家 account_code，不硬编码）:
  · create_voucher_from_ap_bill(应付单审核 → 凭证)（应收单的方向镜像：应付在贷方）
      CAS：借 在途物资/采购(不含税) + 借 222101 应交增值税(进项)(税额) / 贷 2202 应付账款(价税合计)
      HKFRS：借 采购/费用(全额) / 贷 2202 应付账款（无进项税行）
      暂估应付（bill_type=PROVISIONAL_AP）：贷方记暂估应付科目（规则按 source_doc_type 区分，或同 2202）。
  · create_voucher_from_ap_payment(付款单审核 → 凭证)
      借 2202 应付账款（核销冲减，is_advance=False）或 借 1123 预付账款（is_advance=True）/ 贷 1002 银行存款。
  两者均经 execute_transition(doc_id=None→START→DRAFT) 建草稿，回链 source_doc_*，幂等守卫。

effect（auto=False，挂在 seed_payable 的 AUDITED 边 effects[]）:
  · finance.create_voucher_from_ap_bill      （ACCOUNTS_PAYABLE，to_state=AUDITED）
  · finance.create_voucher_from_ap_payment   （AP_PAYMENT，to_state=AUDITED）

批量命令（@register_command，module=FINANCE）:
  · finance.generate_ap_vouchers   按公司批量生成应付/付款凭证（DETAIL 一单一凭证；SUMMARY TODO⚠️）。

副作用在 execute_transition 同事务内运行：只 db.add()/db.flush()，绝不 commit，失败 raise 由引擎回滚。
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.ar_receivable import (
    _account, _build_and_post_voucher, _rule_codes,
)
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.finance_mapping import _num, _one, _q2
from services.tools import _company_filter
from services.workflow_extensions import register_transition_effect


TRIGGER_AUDITED = "AUDITED"
SRC_AP_BILL = "ACCOUNTS_PAYABLE"   # 应付单 source_doc_type（幂等锚 + 回链）
SRC_AP_PAYMENT = "AP_PAYMENT"      # 付款单 source_doc_type

INPUT_TAX_CODE = "222101"          # 进项税科目码（CAS，借方）；HKFRS 无此规则行
PREPAY_CODE = "1123"               # 预付账款科目码（借方，is_advance=True 时选用）


def _entry(line_number, account_id, is_debit, orig, base, currency, rate, memo, aux_id):
    """组一条 VoucherEntry 草稿行 dict（对齐 workflow._apply_sub_updates）。往来辅助核算 = SUPPLIER。"""
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
        "aux_party_type": "SUPPLIER" if aux_id else None,
        "aux_party_id": aux_id,
    }


# ============================================================
# 应付单审核 → 凭证（借 采购/在途 + 借 222101 进项税 / 贷 2202 应付账款）
# ============================================================

async def create_voucher_from_ap_bill(
    db: AsyncSession,
    bill: m.AccountsPayable,
    user: m.UserAccount,
    *,
    trigger_action: str = TRIGGER_AUDITED,
    auto_post: bool = False,
    auditor: m.UserAccount | None = None,
    poster: m.UserAccount | None = None,
) -> dict:
    """应付单（债务立账）审核 → 自动凭证（应收单方向镜像：应付在贷方）。

    分录（科目码取本家 AccountMappingRule，金额取应付单头已算好字段）:
      · 借 采购/在途物资    = untaxed_amount（不含税；缺则回退 amount−tax_amount）
      · 借 222101 应交增值税(进项) = tax_amount（HK 准则 tax_amount=0 或无该科目规则则省此行）
      · 贷 2202 应付账款    = amount（价税合计）
    本位币双金额 base_* = 原币 × exchange_rate。
    幂等：同应付单已生成过凭证（source_doc_type=ACCOUNTS_PAYABLE + source_doc_id=bill.id）则返回既有单。
    """
    company_id = bill.company_id
    existing = await _one(
        db, m.Voucher,
        m.Voucher.company_id == company_id,
        m.Voucher.source_doc_type == SRC_AP_BILL,
        m.Voucher.source_doc_id == bill.id,
    )
    if existing:
        return {"voucher_id": existing.id, "created": False,
                "posted": existing.status == "POSTED", "reason": "voucher already exists"}

    biz_date = bill.bill_date or bill.due_date or date.today()
    rate = _num(getattr(bill, "exchange_rate", None) or 1) or Decimal("1")
    currency = bill.currency or bill.base_currency or "CNY"

    rules = await _rule_codes(db, company_id, SRC_AP_BILL, trigger_action, biz_date)
    if not rules:
        return {"created": False, "reason": "no active AccountMappingRule for ACCOUNTS_PAYABLE"}

    gross = _q2(_num(bill.amount))
    tax = _q2(_num(bill.tax_amount))
    net = _q2(_num(bill.untaxed_amount)) if _num(bill.untaxed_amount) != 0 else _q2(gross - tax)
    supplier_id = getattr(bill, "supplier_id", None)

    # 按规则 dr_cr 分配金额：贷方=价税合计（应付）；借方有两行时主行=采购(不含税)、进项税行=税额。
    # 规则行序（line_seq）：CAS 1=DR采购/在途 / 2=DR进项税 / 3=CR应付；HKFRS 1=DR采购 / 2=CR应付。
    entries: list[dict] = []
    line_number = 0
    debit_rules = [r for r in rules if (r.dr_cr or "").upper() == "DR"]
    for rule in rules:
        is_debit = (rule.dr_cr or "").upper() == "DR"
        if not is_debit:
            amt = gross  # 贷方=应付账款=价税合计。
        elif rule.account_code == INPUT_TAX_CODE or len(debit_rules) == 1:
            # 单借方行（HK 无税）→ 采购吃全额（=不含税，HK net==gross）；进项税行 → 税额。
            amt = tax if rule.account_code == INPUT_TAX_CODE else net
        else:
            amt = net  # 多借方行里的采购/在途行 = 不含税。
        amt = _q2(amt)
        if amt == 0:
            continue  # 税额为 0 的进项税行（HK 或免税）：跳过空行。
        account = await _account(db, company_id, rule.account_code)
        if account is None:
            raise ValueError(f"应付业财映射 line_seq={rule.line_seq} 科目码 {rule.account_code!r} 在公司#{company_id} 不存在")
        line_number += 1
        base = _q2(amt * rate)
        memo = (rule.memo_template or "").replace("{bill_number}", bill.bill_number or "").strip()
        entries.append(_entry(
            rule.line_seq or line_number, account.id, is_debit, amt, base, currency, rate,
            memo or f"应付单 {bill.bill_number or bill.invoice_number}",
            supplier_id if not is_debit else None,  # 往来辅助核算挂应付（贷方）侧。
        ))

    if not entries:
        return {"created": False, "reason": "no non-zero entries (check bill amounts)"}

    voucher_id = await _build_and_post_voucher(
        db, user, company_id=company_id, voucher_date=biz_date,
        description=f"应付单审核自动凭证：{bill.bill_number or bill.invoice_number}",
        word_code="转", entries=entries,
        source_doc_type=SRC_AP_BILL, source_doc_id=bill.id,
        auto_post=auto_post, auditor=auditor, poster=poster,
    )
    if getattr(bill, "voucher_id", None) is None:
        bill.voucher_id = voucher_id
        await db.flush()
    return {"voucher_id": voucher_id, "created": True, "posted": auto_post, "lines": len(entries)}


# ============================================================
# 付款单审核 → 凭证（借 2202 应付 或 借 1123 预付 / 贷 1002 银行）
# ============================================================

async def create_voucher_from_ap_payment(
    db: AsyncSession,
    payment: m.APPayment,
    user: m.UserAccount,
    *,
    trigger_action: str = TRIGGER_AUDITED,
    auto_post: bool = False,
    auditor: m.UserAccount | None = None,
    poster: m.UserAccount | None = None,
) -> dict:
    """付款单（已付款）审核 → 自动凭证。

    分录（科目码取本家 AccountMappingRule，贷方恒为银行存款，借方按是否预付切换）:
      · 借 2202 应付账款（核销冲减，is_advance=False）  或  借 1123 预付账款（is_advance=True）
      · 贷 1002 银行存款 = amount
    规则约定：credit 行 = 银行；debit 行种两条（应付冲减行 / 预付行），按 is_advance 选其一。
    本位币双金额 base_* = 原币 × exchange_rate。幂等同 create_voucher_from_ap_bill。
    """
    company_id = payment.company_id
    existing = await _one(
        db, m.Voucher,
        m.Voucher.company_id == company_id,
        m.Voucher.source_doc_type == SRC_AP_PAYMENT,
        m.Voucher.source_doc_id == payment.id,
    )
    if existing:
        return {"voucher_id": existing.id, "created": False,
                "posted": existing.status == "POSTED", "reason": "voucher already exists"}

    biz_date = payment.payment_date or date.today()
    rate = _num(getattr(payment, "exchange_rate", None) or 1) or Decimal("1")
    currency = payment.currency or payment.base_currency or "CNY"
    amount = _q2(_num(payment.amount))
    if amount == 0:
        return {"created": False, "reason": "payment amount is zero"}

    rules = await _rule_codes(db, company_id, SRC_AP_PAYMENT, trigger_action, biz_date)
    if not rules:
        return {"created": False, "reason": "no active AccountMappingRule for AP_PAYMENT"}

    supplier_id = getattr(payment, "supplier_id", None)
    entries: list[dict] = []
    line_number = 0
    for rule in rules:
        is_debit = (rule.dr_cr or "").upper() == "DR"
        is_prepay_rule = rule.account_code == PREPAY_CODE
        # 借方按 is_advance 选行：预付 → 只取预付行；非预付 → 只取应付冲减行。
        if is_debit:
            if payment.is_advance and not is_prepay_rule:
                continue
            if (not payment.is_advance) and is_prepay_rule:
                continue
        account = await _account(db, company_id, rule.account_code)
        if account is None:
            raise ValueError(f"付款业财映射 line_seq={rule.line_seq} 科目码 {rule.account_code!r} 在公司#{company_id} 不存在")
        line_number += 1
        base = _q2(amount * rate)
        memo = (rule.memo_template or "").replace("{payment_number}", payment.payment_number or "").strip()
        entries.append(_entry(
            rule.line_seq or line_number, account.id, is_debit, amount, base, currency, rate,
            memo or f"付款单 {payment.payment_number}",
            supplier_id if is_debit else None,  # 往来辅助核算挂应付/预付（借方）侧。
        ))

    if len(entries) < 2:
        return {"created": False, "reason": "AP_PAYMENT rules incomplete (need 借应付/预付 + 贷银行)"}

    voucher_id = await _build_and_post_voucher(
        db, user, company_id=company_id, voucher_date=biz_date,
        description=f"付款单审核自动凭证：{payment.payment_number}"
                    + ("（预付）" if payment.is_advance else ""),
        word_code="付", entries=entries,
        source_doc_type=SRC_AP_PAYMENT, source_doc_id=payment.id,
        auto_post=auto_post, auditor=auditor, poster=poster,
    )
    if getattr(payment, "voucher_id", None) is None:
        payment.voucher_id = voucher_id
        await db.flush()
    return {"voucher_id": voucher_id, "created": True, "posted": auto_post, "lines": len(entries)}


# ============================================================
# 流程 effect：应付单 / 付款单 审核（to_state=AUDITED）边上挂「自动生成凭证」
#   auto=False，须在 seed_payable 的 AUDITED 边 effects[] 显式点名。
# ============================================================

@register_transition_effect(
    "finance.create_voucher_from_ap_bill",
    doc_type="ACCOUNTS_PAYABLE", to_state="AUDITED", auto=False,
)
async def create_voucher_from_ap_bill_effect(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """应付单审核 effect：按本公司业财映射规则自动生成应付凭证草稿（借采购+进项税/贷应付），回链应付单。"""
    result = await create_voucher_from_ap_bill(db, doc, user, trigger_action=to_state or TRIGGER_AUDITED)
    if not result.get("created"):
        return [f"应付单#{doc.id} 未生成凭证：{result.get('reason')}"]
    return [f"应付单#{doc.id} → 自动凭证#{result['voucher_id']}（{result['lines']} 行，草稿待审核过账）"]


@register_transition_effect(
    "finance.create_voucher_from_ap_payment",
    doc_type="AP_PAYMENT", to_state="AUDITED", auto=False,
)
async def create_voucher_from_ap_payment_effect(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """付款单审核 effect：自动生成付款凭证草稿（借应付 或 借预付 / 贷银行），回链付款单。"""
    result = await create_voucher_from_ap_payment(db, doc, user, trigger_action=to_state or TRIGGER_AUDITED)
    if not result.get("created"):
        return [f"付款单#{doc.id} 未生成凭证：{result.get('reason')}"]
    return [f"付款单#{doc.id} → 自动凭证#{result['voucher_id']}（{result['lines']} 行，草稿待审核过账）"]


# ============================================================
# 批量命令：finance.generate_ap_vouchers（DETAIL 一单一凭证 / SUMMARY 汇总 TODO⚠️）
# ============================================================

def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


@register_command(
    "finance.generate_ap_vouchers",
    module="FINANCE",
    title="批量生成应付/付款凭证",
    description=(
        "按公司批量为已审核的应付单/付款单生成凭证草稿（业财映射）。"
        "mode=DETAIL 一单一凭证（默认）；SUMMARY 汇总 TODO⚠️待复核口径，暂不实现。"
        "source=AP_BILL/AP_PAYMENT/BOTH。已生成过凭证的单据幂等跳过。"
    ),
    affected_tables=("voucher", "voucher_entry", "accounts_payable", "ap_payment"),
    supports_retry=True,
)
async def generate_ap_vouchers(ctx: CommandContext, payload: dict) -> dict:
    """批量生成应付/付款凭证（= generate_ar_vouchers 镜像）。

    payload：
      company_id: int   —— 公司 id（必填）
      source: 'AP_BILL' | 'AP_PAYMENT' | 'BOTH'   —— 处理对象（默认 BOTH）
      mode: 'DETAIL' | 'SUMMARY'                  —— DETAIL 一单一凭证（默认）；SUMMARY TODO⚠️
      auto_post: bool   —— 是否自动审核过账（默认 False，仅建草稿）
      bill_ids / payment_ids: list[int]  —— 可选，限定范围；不传则取该公司全部已审核未生凭证的单
    """
    company_id = payload.get("company_id")
    if not company_id:
        raise CommandError("company_id 不能为空")
    _assert_company_access(ctx.user, company_id)

    source = (payload.get("source") or "BOTH").upper()
    mode = (payload.get("mode") or "DETAIL").upper()
    if mode == "SUMMARY":
        raise CommandError("SUMMARY 汇总模式 TODO⚠️（口径待复核），当前仅支持 mode=DETAIL", 422)
    auto_post = bool(payload.get("auto_post", False))

    created: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    async def _run_bills():
        stmt = select(m.AccountsPayable).where(
            m.AccountsPayable.company_id == company_id,
            m.AccountsPayable.status == "AUDITED",
        )
        if payload.get("bill_ids"):
            stmt = stmt.where(m.AccountsPayable.id.in_(payload["bill_ids"]))
        bills = (await ctx.db.execute(stmt.order_by(m.AccountsPayable.id))).scalars().all()
        for bill in bills:
            try:
                r = await create_voucher_from_ap_bill(ctx.db, bill, ctx.user, auto_post=auto_post)
                if r.get("created"):
                    created.append({"source": "AP_BILL", "doc_id": bill.id, "voucher_id": r["voucher_id"]})
                else:
                    skipped.append({"source": "AP_BILL", "doc_id": bill.id, "reason": r.get("reason")})
            except Exception as exc:  # noqa: BLE001 — 单失败不阻断批
                failed.append({"source": "AP_BILL", "doc_id": bill.id, "error": str(exc)})

    async def _run_payments():
        stmt = select(m.APPayment).where(
            m.APPayment.company_id == company_id,
            m.APPayment.status == "AUDITED",
        )
        if payload.get("payment_ids"):
            stmt = stmt.where(m.APPayment.id.in_(payload["payment_ids"]))
        payments = (await ctx.db.execute(stmt.order_by(m.APPayment.id))).scalars().all()
        for pay in payments:
            try:
                r = await create_voucher_from_ap_payment(ctx.db, pay, ctx.user, auto_post=auto_post)
                if r.get("created"):
                    created.append({"source": "AP_PAYMENT", "doc_id": pay.id, "voucher_id": r["voucher_id"]})
                else:
                    skipped.append({"source": "AP_PAYMENT", "doc_id": pay.id, "reason": r.get("reason")})
            except Exception as exc:  # noqa: BLE001
                failed.append({"source": "AP_PAYMENT", "doc_id": pay.id, "error": str(exc)})

    if source in ("AP_BILL", "BOTH"):
        await _run_bills()
    if source in ("AP_PAYMENT", "BOTH"):
        await _run_payments()

    ctx.add_event("finance_generate_ap_vouchers", {
        "company_id": company_id, "source": source, "mode": mode,
        "created": len(created), "skipped": len(skipped), "failed": len(failed),
    })
    return {
        "company_id": company_id, "source": source, "mode": mode, "auto_post": auto_post,
        "created": created, "skipped": skipped, "failed": failed,
        "summary": {"created": len(created), "skipped": len(skipped), "failed": len(failed)},
    }
