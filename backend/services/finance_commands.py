"""Finance and credit commands executed through the shared command layer."""

from decimal import Decimal

from sqlalchemy import select

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


@register_command(
    "create_accounts_receivable",
    module="FINANCE",
    title="生成应收账款",
    description="按销售发票或外部载荷生成应收账款，重复发票号保持幂等",
    affected_tables=("accounts_receivable",),
    supports_retry=True,
)
async def create_accounts_receivable(ctx: CommandContext, payload: dict) -> dict:
    company_id = payload.get("company_id") or ctx.user.company_id
    _assert_company_access(ctx.user, company_id)
    invoice_number = payload.get("invoice_number") or ""
    if not invoice_number:
        raise CommandError("invoice_number 不能为空")

    existing = (await ctx.db.execute(
        select(m.AccountsReceivable).where(
            m.AccountsReceivable.company_id == company_id,
            m.AccountsReceivable.invoice_number == invoice_number,
        )
    )).scalar_one_or_none()
    if existing:
        return {"id": existing.id, "invoice_number": existing.invoice_number, "created": False}

    row = m.AccountsReceivable(
        company_id=company_id,
        created_by_id=ctx.user.id,
        customer_id=payload.get("customer_id"),
        sales_order_id=payload.get("sales_order_id"),
        invoice_number=invoice_number,
        amount=_num(payload.get("amount")),
        currency=payload.get("currency") or "USD",
        due_date=payload.get("due_date"),
        status=payload.get("status") or "PENDING",
    )
    ctx.db.add(row)
    await ctx.db.flush()
    ctx.add_event("accounts_receivable_created", {"id": row.id})
    return {"id": row.id, "invoice_number": row.invoice_number, "created": True}


@register_command(
    "create_accounts_payable",
    module="FINANCE",
    title="生成应付账款",
    description="按采购发票或外部载荷生成应付账款，重复发票号保持幂等",
    affected_tables=("accounts_payable",),
    supports_retry=True,
)
async def create_accounts_payable(ctx: CommandContext, payload: dict) -> dict:
    company_id = payload.get("company_id") or ctx.user.company_id
    _assert_company_access(ctx.user, company_id)
    invoice_number = payload.get("invoice_number") or ""
    if not invoice_number:
        raise CommandError("invoice_number 不能为空")

    existing = (await ctx.db.execute(
        select(m.AccountsPayable).where(
            m.AccountsPayable.company_id == company_id,
            m.AccountsPayable.invoice_number == invoice_number,
        )
    )).scalar_one_or_none()
    if existing:
        return {"id": existing.id, "invoice_number": existing.invoice_number, "created": False}

    row = m.AccountsPayable(
        company_id=company_id,
        created_by_id=ctx.user.id,
        supplier_id=payload.get("supplier_id"),
        purchase_order_id=payload.get("purchase_order_id"),
        invoice_number=invoice_number,
        amount=_num(payload.get("amount")),
        currency=payload.get("currency") or "USD",
        due_date=payload.get("due_date"),
        status=payload.get("status") or "PENDING",
    )
    ctx.db.add(row)
    await ctx.db.flush()
    ctx.add_event("accounts_payable_created", {"id": row.id})
    return {"id": row.id, "invoice_number": row.invoice_number, "created": True}


@register_command(
    "upsert_customer_credit",
    module="FINANCE",
    title="保存客户信用额度",
    description="新增或更新客户信用额度，更新时锁定信用额度行",
    affected_tables=("customer_credit",),
    supports_retry=True,
)
async def upsert_customer_credit(ctx: CommandContext, payload: dict) -> dict:
    customer_id = payload.get("customer_id")
    customer = (await ctx.db.execute(select(m.Customer).where(m.Customer.id == customer_id))).scalar_one_or_none()
    if not customer:
        raise CommandError("客户不存在", 404)
    _assert_company_access(ctx.user, customer.company_id)

    credit = (await ctx.db.execute(
        select(m.CustomerCredit)
        .where(
            m.CustomerCredit.company_id == customer.company_id,
            m.CustomerCredit.customer_id == customer.id,
        )
        .with_for_update()
    )).scalar_one_or_none()
    if not credit:
        credit = m.CustomerCredit(
            company_id=customer.company_id,
            created_by_id=ctx.user.id,
            customer_id=customer.id,
        )
        ctx.db.add(credit)

    credit.credit_limit = _num(payload.get("credit_limit"))
    if "used_amount" in payload:
        credit.used_amount = _num(payload.get("used_amount"))
    credit.currency = payload.get("currency") or credit.currency or "USD"
    credit.warning_threshold_pct = payload.get("warning_threshold_pct") or credit.warning_threshold_pct or 80
    credit.credit_period_days = payload.get("credit_period_days") or credit.credit_period_days or 30
    credit.credit_rating = payload.get("credit_rating") or credit.credit_rating or ""
    credit.updated_by_id = ctx.user.id
    await ctx.db.flush()
    ctx.add_event("customer_credit_upserted", {"id": credit.id, "customer_id": customer.id})
    return {"id": credit.id, "customer_id": customer.id}
