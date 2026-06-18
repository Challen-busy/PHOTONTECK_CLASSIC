"""总账·第六波 smoke：现金流量归集(assign_cashflow) + 定期凭证生成(generate_recurring_voucher) + T型账。
跑法: cd backend && DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck python -m scripts.smoke_wave6
"""
import asyncio
from datetime import date
from sqlalchemy import select

from core.database import get_session_factory
import models as m
from services.commands import execute_command
import services.finance_cashflow  # noqa: F401
import services.finance_recurring  # noqa: F401
from routers import reports as R


async def _u(db, n):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.username == n))).scalar_one_or_none()


async def main():
    f = get_session_factory()
    ok, fail = [], []
    cid = 1
    today = date.today()

    async with f() as db:
        period = (await db.execute(select(m.AccountingPeriod).join(
            m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id).where(
            m.FiscalYear.company_id == cid, m.AccountingPeriod.start_date <= today,
            m.AccountingPeriod.end_date >= today).order_by(m.AccountingPeriod.id))).scalars().first()
        pid = period.id

    # 1) 现金流量归集（批量本期，boss）
    async with f() as db:
        boss = await _u(db, "boss")
        r = await execute_command(db, boss, "finance.assign_cashflow", {"period_id": pid, "company_id": cid})
        print(f"现金流量归集: 扫描{r.get('scanned')} 现金凭证{r.get('cash_vouchers')} 标记{r.get('marked')} 未分类{r.get('unclassified')}")
        (ok if "marked" in r else fail).append("现金流量归集返回结构")

    # 2) 定期凭证生成（摊销方案，finance）+ 幂等
    async with f() as db:
        finance = await _u(db, "finance")
        scheme = (await db.execute(select(m.RecurringVoucherScheme).where(m.RecurringVoucherScheme.company_id == cid).order_by(m.RecurringVoucherScheme.id))).scalars().first()
        r = await execute_command(db, finance, "finance.generate_recurring_voucher", {"scheme_id": scheme.id, "period_id": pid, "voucher_date": today.isoformat()})
        print(f"定期凭证生成 (方案 {scheme.code}/{scheme.scheme_type}): created={r.get('created')} voucher_id={r.get('voucher_id')} lines={r.get('lines')} 每期额={r.get('per_period_amount')}")
        (ok if (r.get("voucher_id") or r.get("created") is False) else fail).append("定期凭证生成")
    async with f() as db:
        finance = await _u(db, "finance")
        scheme = (await db.execute(select(m.RecurringVoucherScheme).where(m.RecurringVoucherScheme.company_id == cid).order_by(m.RecurringVoucherScheme.id))).scalars().first()
        r2 = await execute_command(db, finance, "finance.generate_recurring_voucher", {"scheme_id": scheme.id, "period_id": pid, "voucher_date": today.isoformat()})
        print(f"定期凭证幂等重跑: created={r2.get('created')} (期望 False)")
        (ok if r2.get("created") is False else fail).append("定期凭证幂等")

    # 3) T型账 + 现金流量表读数
    async with f() as db:
        boss = await _u(db, "boss")
        tl = await R.cashflow_tlist(company_id=cid, period_id=pid, user=boss, db=db)
        net = tl.get("data", {}).get("net_cashflow", {})
        print(f"现金流量T型账: 流入合计={tl.get('data',{}).get('total_inflow',{}).get('period')} 流出合计={tl.get('data',{}).get('total_outflow',{}).get('period')} 净额={net.get('period')}")
        (ok if "data" in tl else fail).append("T型账返回结构")

    print("\n==== WAVE-6 SMOKE 结果 ====")
    print("✅ 通过:", ok)
    print("❌ 失败:", fail if fail else "无")


if __name__ == "__main__":
    asyncio.run(main())
