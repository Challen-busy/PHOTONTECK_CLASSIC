"""报表路由：试算平衡表 / 科目余额表 / 账龄分析"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import get_db
from services.tools import _company_filter

router = APIRouter(prefix="/api/reports")


def _dec(v) -> float:
    return float(v) if v else 0.0


@router.get("/trial_balance")
async def trial_balance(
    period_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """试算平衡表：按科目汇总 期初/本期/期末 借贷，末行验证借贷平衡"""
    company_ids = _company_filter(user)

    # 查 account_balance + account
    stmt = (
        select(m.AccountBalance, m.Account)
        .join(m.Account, m.AccountBalance.account_id == m.Account.id)
        .where(m.AccountBalance.period_id == period_id)
    )
    if company_ids:
        stmt = stmt.where(m.AccountBalance.company_id.in_(company_ids))

    result = await db.execute(stmt)
    rows = result.all()

    data = []
    totals = dict(
        opening_debit=0, opening_credit=0,
        period_debit=0, period_credit=0,
        closing_debit=0, closing_credit=0,
    )
    for bal, acct in rows:
        row = {
            "account_code": acct.code,
            "account_name": acct.name,
            "account_type": acct.account_type,
            "balance_direction": acct.balance_direction,
            "opening_debit": _dec(bal.opening_debit),
            "opening_credit": _dec(bal.opening_credit),
            "period_debit": _dec(bal.period_debit),
            "period_credit": _dec(bal.period_credit),
            "closing_debit": _dec(bal.closing_debit),
            "closing_credit": _dec(bal.closing_credit),
        }
        data.append(row)
        for k in totals:
            totals[k] += row[k]

    data.sort(key=lambda r: r["account_code"])

    return {
        "report": "trial_balance",
        "period_id": period_id,
        "data": data,
        "totals": totals,
        "balanced": abs(totals["closing_debit"] - totals["closing_credit"]) < 0.01,
    }


@router.get("/account_balance")
async def account_balance(
    period_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """科目余额表：与试算平衡表类似，增加余额方向净额列"""
    company_ids = _company_filter(user)

    stmt = (
        select(m.AccountBalance, m.Account)
        .join(m.Account, m.AccountBalance.account_id == m.Account.id)
        .where(m.AccountBalance.period_id == period_id)
    )
    if company_ids:
        stmt = stmt.where(m.AccountBalance.company_id.in_(company_ids))

    result = await db.execute(stmt)
    rows = result.all()

    data = []
    for bal, acct in rows:
        closing_d = _dec(bal.closing_debit)
        closing_c = _dec(bal.closing_credit)
        if acct.balance_direction == "DEBIT":
            net_balance = closing_d - closing_c
        else:
            net_balance = closing_c - closing_d

        data.append({
            "account_code": acct.code,
            "account_name": acct.name,
            "account_type": acct.account_type,
            "balance_direction": acct.balance_direction,
            "opening_debit": _dec(bal.opening_debit),
            "opening_credit": _dec(bal.opening_credit),
            "period_debit": _dec(bal.period_debit),
            "period_credit": _dec(bal.period_credit),
            "closing_debit": closing_d,
            "closing_credit": closing_c,
            "net_balance": net_balance,
            "direction_label": "借" if acct.balance_direction == "DEBIT" else "贷",
        })

    data.sort(key=lambda r: r["account_code"])
    return {"report": "account_balance", "period_id": period_id, "data": data}


@router.get("/aging_analysis")
async def aging_analysis(
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """账龄分析：未清应收款按到期日分桶"""
    company_ids = _company_filter(user)

    stmt = (
        select(m.AccountsReceivable, m.Customer)
        .join(m.Customer, m.AccountsReceivable.customer_id == m.Customer.id)
        .where(m.AccountsReceivable.status.notin_(["CLOSED", "SETTLED"]))
    )
    if company_ids:
        stmt = stmt.where(m.AccountsReceivable.company_id.in_(company_ids))

    result = await db.execute(stmt)
    rows = result.all()

    today = date.today()
    data = []
    bucket_totals = {"current": 0, "d1_30": 0, "d31_60": 0, "d61_90": 0, "d90_plus": 0}

    for ar, cust in rows:
        outstanding = _dec(ar.amount) - _dec(ar.paid_amount)
        if outstanding <= 0:
            continue

        overdue_days = (today - ar.due_date).days if ar.due_date else 0
        if overdue_days <= 0:
            bucket = "current"
        elif overdue_days <= 30:
            bucket = "d1_30"
        elif overdue_days <= 60:
            bucket = "d31_60"
        elif overdue_days <= 90:
            bucket = "d61_90"
        else:
            bucket = "d90_plus"

        row = {
            "customer_name": cust.name,
            "customer_code": cust.code,
            "invoice_number": ar.invoice_number,
            "amount": _dec(ar.amount),
            "paid_amount": _dec(ar.paid_amount),
            "outstanding": outstanding,
            "due_date": ar.due_date.isoformat() if ar.due_date else None,
            "overdue_days": max(overdue_days, 0),
            "bucket": bucket,
            "currency": ar.currency,
        }
        data.append(row)
        bucket_totals[bucket] += outstanding

    return {
        "report": "aging_analysis",
        "data": data,
        "bucket_totals": bucket_totals,
        "total_outstanding": sum(bucket_totals.values()),
    }


@router.get("/periods")
async def list_periods(
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """返回用户可见的会计期间列表（供前端报表选期间用）"""
    company_ids = _company_filter(user)

    stmt = (
        select(m.AccountingPeriod, m.FiscalYear)
        .join(m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id)
    )
    if company_ids:
        stmt = stmt.where(m.FiscalYear.company_id.in_(company_ids))
    stmt = stmt.order_by(m.FiscalYear.year.desc(), m.AccountingPeriod.period_number)

    result = await db.execute(stmt)
    rows = result.all()

    seen = {}
    data = []
    for period, fy in rows:
        key = (fy.year, period.period_number)
        if key in seen:
            continue
        seen[key] = True
        data.append({
            "id": period.id,
            "year": fy.year,
            "period_number": period.period_number,
            "start_date": period.start_date.isoformat(),
            "end_date": period.end_date.isoformat(),
            "status": period.status,
            "label": f"{fy.year}年第{period.period_number}期",
        })

    return {"periods": data}
