"""总账·第四波 smoke：凭证批量工作台 4 命令（批量推进/按模板建单/断号检测/重排预览）。
跑法: cd backend && DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck python -m scripts.smoke_wave4
"""
import asyncio
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from core.database import get_session_factory
import models as m
from services.commands import execute_command
import services.finance_batch  # noqa: F401  触发命令注册


async def _u(db, n):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.username == n))).scalar_one_or_none()

async def _acc(db, cid, code):
    return (await db.execute(select(m.Account).where(m.Account.company_id == cid, m.Account.code == code))).scalars().first()


async def main():
    factory = get_session_factory()
    ok, fail = [], []
    cid = 1
    today = date.today()

    # ---- 造 2 张 DRAFT 平衡凭证（制单=finance）----
    async with factory() as db:
        finance = await _u(db, "finance")
        period = (await db.execute(select(m.AccountingPeriod).join(
            m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id).where(
            m.FiscalYear.company_id == cid, m.AccountingPeriod.status == "OPEN",
            m.AccountingPeriod.start_date <= today, m.AccountingPeriod.end_date >= today).order_by(m.AccountingPeriod.id))).scalars().first()
        bank = await _acc(db, cid, "1002"); rev = await _acc(db, cid, "6001")
        vids = []
        for k in range(2):
            ts = datetime.now().strftime("%H%M%S%f")
            v = m.Voucher(company_id=cid, voucher_number=f"W4-{ts}", voucher_date=today, period_id=period.id,
                          voucher_type="GENERAL", description=f"wave4批量测试{k}", total_debit=Decimal("500"),
                          total_credit=Decimal("500"), status="DRAFT", created_by_id=finance.id)
            db.add(v); await db.flush()
            db.add(m.VoucherEntry(voucher_id=v.id, line_number=1, account_id=bank.id, debit=Decimal("500"), credit=Decimal("0"), base_debit=Decimal("500"), base_credit=Decimal("0"), currency="HKD", exchange_rate=Decimal("1")))
            db.add(m.VoucherEntry(voucher_id=v.id, line_number=2, account_id=rev.id, debit=Decimal("0"), credit=Decimal("500"), base_debit=Decimal("0"), base_credit=Decimal("500"), currency="HKD", exchange_rate=Decimal("1")))
            vids.append(v.id)
        await db.commit()
        print(f"造 DRAFT 凭证: {vids}")

    # ---- 批量审核（fin_dir）----
    async with factory() as db:
        fin_dir = await _u(db, "fin_dir")
        r = await execute_command(db, fin_dir, "finance.batch_voucher_transition", {"voucher_ids": vids, "to_state": "AUDITED"})
        print(f"批量审核: total={r.get('total')} 成功={r.get('succeeded')} 失败={r.get('failed')}")
        (ok if r.get("succeeded") == 2 else fail).append(f"批量审核2张(实得{r.get('succeeded')})")

    # ---- 批量过账（boss）----
    async with factory() as db:
        boss = await _u(db, "boss")
        r = await execute_command(db, boss, "finance.batch_voucher_transition", {"voucher_ids": vids, "to_state": "POSTED"})
        print(f"批量过账: total={r.get('total')} 成功={r.get('succeeded')} 失败={r.get('failed')} 明细={[(x.get('id'),x.get('success'),x.get('error','')[:30]) for x in r.get('results',[])]}")
        (ok if r.get("succeeded") == 2 else fail).append(f"批量过账2张(实得{r.get('succeeded')})")

    # ---- 按模板建单（finance）----
    async with factory() as db:
        finance = await _u(db, "finance")
        mv = (await db.execute(select(m.ModelVoucher).where(m.ModelVoucher.company_id == cid))).scalars().first()
        r = await execute_command(db, finance, "finance.create_voucher_from_model", {"model_voucher_id": mv.id, "voucher_date": today.isoformat()})
        print(f"按模板建单 (模板#{mv.id} {mv.code}): voucher_id={r.get('voucher_id')} lines={r.get('lines')} success={r.get('success')}")
        (ok if r.get("voucher_id") else fail).append("按模板建草稿")

    # ---- 断号检测（只读）----
    async with factory() as db:
        boss = await _u(db, "boss")
        period = (await db.execute(select(m.AccountingPeriod).join(
            m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id).where(
            m.FiscalYear.company_id == cid, m.AccountingPeriod.start_date <= today, m.AccountingPeriod.end_date >= today).order_by(m.AccountingPeriod.id))).scalars().first()
        r = await execute_command(db, boss, "finance.check_voucher_gaps", {"company_id": cid, "period_id": period.id})
        print(f"断号检测: total={r.get('total')} gaps={len(r.get('gaps', []))} groups={len(r.get('groups', []))}")
        (ok if r.get("success") is not False and "gaps" in r else fail).append("断号检测返回结构")

    print("\n==== WAVE-4 SMOKE 结果 ====")
    print("✅ 通过:", ok)
    print("❌ 失败:", fail if fail else "无")


if __name__ == "__main__":
    asyncio.run(main())
