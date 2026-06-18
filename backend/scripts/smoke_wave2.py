"""总账·第二波 smoke：业财映射(销售开票→自动凭证→AccountBalance) + 期末(结转损益预览/结账前置校验闸)。
跑法: cd backend && DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck python -m scripts.smoke_wave2
目标公司=PTK#1（HK/HKFRS/HKD）：销售开票 HK 规则=借 1122 应收 / 贷 6001 收入（无销项税，2 行）。
"""
import asyncio
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from core.database import get_session_factory
import models as m
import services.finance_mapping as fmap
from services.commands import execute_command
import services.finance_period_close  # noqa: F401  触发命令注册


async def _u(db, name):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.username == name))).scalar_one_or_none()

async def _acc(db, cid, code):
    return (await db.execute(select(m.Account).where(m.Account.company_id == cid, m.Account.code == code))).scalars().first()

async def _bal(db, cid, aid, pid):
    return (await db.execute(select(m.AccountBalance).where(
        m.AccountBalance.company_id == cid, m.AccountBalance.account_id == aid,
        m.AccountBalance.period_id == pid))).scalars().first()


async def main():
    factory = get_session_factory()
    ok, fail = [], []
    cid = 1  # PTK HK

    # ===== A. 业财映射：销售开票 → 自动生成并过账凭证 =====
    async with factory() as db:
        finance, fin_dir, boss = await _u(db, "finance"), await _u(db, "fin_dir"), await _u(db, "boss")
        _today = date.today()
        period = (await db.execute(select(m.AccountingPeriod).join(
            m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id).where(
            m.FiscalYear.company_id == cid, m.AccountingPeriod.status == "OPEN",
            m.AccountingPeriod.start_date <= _today, m.AccountingPeriod.end_date >= _today).order_by(m.AccountingPeriod.id))).scalars().first()
        ar_acc, rev_acc = await _acc(db, cid, "1122"), await _acc(db, cid, "6001")
        cust = (await db.execute(select(m.Customer).where(m.Customer.company_id == cid))).scalars().first()
        if not all([finance, fin_dir, boss, period, ar_acc, rev_acc]):
            print(f"❌ 前置缺失 finance={bool(finance)} period={bool(period)} 1122={bool(ar_acc)} 6001={bool(rev_acc)}"); return
        b0_ar = await _bal(db, cid, ar_acc.id, period.id); b0_rev = await _bal(db, cid, rev_acc.id, period.id)
        base_ar = Decimal(str(b0_ar.period_debit)) if b0_ar else Decimal("0")
        base_rev = Decimal(str(b0_rev.period_credit)) if b0_rev else Decimal("0")

        ts = datetime.now().strftime("%H%M%S%f")
        inv = m.SalesInvoice(company_id=cid, invoice_number=f"SI-SMK-{ts}",
                             customer_id=(cust.id if cust else None), amount=Decimal("1000"),
                             currency="HKD", tax_rate=Decimal("0"), invoice_date=date.today(),
                             status="CONFIRMED", created_by_id=finance.id)
        db.add(inv); await db.flush()
        inv_id = inv.id
        print(f"建销售发票 #{inv_id} 公司{cid}/HKD amount=1000 客户={getattr(cust,'id',None)}")
        res = await fmap.create_voucher_from_sales_invoice(db, inv, finance, auto_post=True, auditor=fin_dir, poster=boss)
        await db.commit()
        print(f"业财生成: {res}")
        (ok if res.get("created") else fail).append("业财:销售开票生成凭证")
        (ok if res.get("posted") else fail).append("业财:凭证已自动过账")
        (ok if res.get("lines") == 2 else fail).append(f"业财:HK 2行分录(实得{res.get('lines')})")

    async with factory() as db:
        b1_ar = await _bal(db, cid, ar_acc.id, period.id); b1_rev = await _bal(db, cid, rev_acc.id, period.id)
        d_ar = (Decimal(str(b1_ar.period_debit)) - base_ar) if b1_ar else Decimal("0")
        d_rev = (Decimal(str(b1_rev.period_credit)) - base_rev) if b1_rev else Decimal("0")
        print(f"过账后: 1122应收 借+{d_ar}(期望+1000) | 6001收入 贷+{d_rev}(期望+1000)")
        (ok if d_ar == Decimal("1000") else fail).append("业财:AccountBalance 应收借+1000")
        (ok if d_rev == Decimal("1000") else fail).append("业财:AccountBalance 收入贷+1000")
        # 幂等
        inv2 = (await db.execute(select(m.SalesInvoice).where(m.SalesInvoice.id == inv_id))).scalar_one()
        finance = await _u(db, "finance"); fin_dir = await _u(db, "fin_dir"); boss = await _u(db, "boss")
        res2 = await fmap.create_voucher_from_sales_invoice(db, inv2, finance, auto_post=True, auditor=fin_dir, poster=boss)
        (ok if not res2.get("created") else fail).append("业财:同发票二次调用幂等(created=False)")

    # ===== B. 期末：结转损益预览 + 结账前置校验闸 =====
    async with factory() as db:
        boss = await _u(db, "boss")
        _today = date.today()
        period = (await db.execute(select(m.AccountingPeriod).join(
            m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id).where(
            m.FiscalYear.company_id == cid, m.AccountingPeriod.status == "OPEN",
            m.AccountingPeriod.start_date <= _today, m.AccountingPeriod.end_date >= _today).order_by(m.AccountingPeriod.id))).scalars().first()
        try:
            r_pl = await execute_command(db, boss, "finance.carry_forward_pl", {"period_id": period.id, "preview": True})
            print(f"结转损益预览: net_profit={r_pl.get('net_profit')} 行数={len(r_pl.get('lines', []))}")
            (ok if "net_profit" in r_pl else fail).append("期末:结转损益预览出净利润")
        except Exception as e:
            print(f"结转损益预览异常: {e}"); fail.append(f"期末:结转损益预览({str(e)[:50]})")
        try:
            r_pre = await execute_command(db, boss, "finance.close_period", {"period_id": period.id, "preview": True}) \
                if False else None
            # precheck 走 close 的前置；直接调 precheck 命令若存在
            r_chk = await execute_command(db, boss, "finance.close_period", {"period_id": period.id, "precheck_only": True})
            checks = r_chk.get("checks") or r_chk.get("details", {}).get("checks")
            print(f"结账前置校验: {[(c.get('label'), c.get('passed')) for c in (checks or [])]}")
            (ok if checks else fail).append("期末:结账前置校验返回明细")
        except Exception as e:
            # close_period 在有未过账凭证/不平时应抛 CommandError(422)，这本身就是闸生效
            msg = str(e)[:80]
            print(f"结账被拦(预期,闸生效): {msg}")
            (ok if ("校验" in msg or "未过账" in msg or "422" in str(e) or "precheck" in msg.lower()) else fail).append("期末:结账前置校验闸生效")

    print("\n==== WAVE-2 SMOKE 结果 ====")
    print("✅ 通过:", ok)
    print("❌ 失败:", fail if fail else "无")


if __name__ == "__main__":
    asyncio.run(main())
