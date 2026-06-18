"""总账·第一波 smoke：凭证全生命周期 + 过账写 AccountBalance + 校验闸。
直连 dev库,用 execute_transition 推状态。不改库结构。可重复跑(每次新建凭证)。
跑法: cd backend && python -m scripts.smoke_finance

★目标公司=finance 用户 home 公司（PTK #1，香港，本位币 HKD，HKFRS 科目表）。
  锚点科目沿用 HKFRS 表里保留的同款 code：银行存款 1002（借方）/ 主营收入 6001（贷方）。
  原币/汇率随公司本位币（HK→HKD，rate=1，base==原币），不再硬编码 CNY。
"""
import asyncio
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from core.database import get_session_factory
import models as m
from services.workflow import execute_transition
import services.finance_posting  # noqa: F401  触发 @register 过账effect/validator/red_reversal


async def _u(db, name):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.username == name))).scalar_one_or_none()


async def _acc(db, company_id, code):
    return (await db.execute(
        select(m.Account).where(m.Account.company_id == company_id, m.Account.code == code)
    )).scalars().first()


async def _bal(db, company_id, account_id, period_id):
    return (await db.execute(select(m.AccountBalance).where(
        m.AccountBalance.company_id == company_id,
        m.AccountBalance.account_id == account_id,
        m.AccountBalance.period_id == period_id,
    ))).scalars().first()


async def main():
    factory = get_session_factory()
    ok = []
    fail = []

    async with factory() as db:
        finance = await _u(db, "finance")
        fin_dir = await _u(db, "fin_dir")
        boss = await _u(db, "boss")
        actor = finance
        company_id = actor.company_id  # finance home = PTK #1（香港，HKD 本位）
        company = (await db.execute(select(m.Company).where(m.Company.id == company_id))).scalar_one_or_none()
        base_ccy = (company.currency if company else "HKD") or "HKD"  # 本位币（HK→HKD）；rate=1 时 base==原币
        period = (await db.execute(select(m.AccountingPeriod).join(
            m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id).where(
            m.FiscalYear.company_id == company_id,
            m.AccountingPeriod.status == "OPEN",
        ).order_by(m.AccountingPeriod.id))).scalars().first()
        bank = await _acc(db, company_id, "1002")   # 银行存款(借方科目，HKFRS/CAS 同款 code)
        rev = await _acc(db, company_id, "6001")    # 营业收入(贷方科目，HKFRS/CAS 同款 code)
        word = (await db.execute(select(m.VoucherWord).where(m.VoucherWord.company_id == company_id))).scalars().first()
        print(f"前置: company={company_id}({getattr(company,'code',None)}/{base_ccy}) period={getattr(period,'id',None)} bank={getattr(bank,'code',None)}/{getattr(bank,'id',None)} "
              f"rev={getattr(rev,'code',None)}/{getattr(rev,'id',None)} word={getattr(word,'code',None)} 制单={getattr(finance,'username',None)} 审核={getattr(fin_dir,'username',None)} 过账={getattr(boss,'username',None)}")
        if not all([finance, fin_dir, boss, period, bank, rev]):
            print("❌ 前置数据缺失,无法 smoke"); return

        # 取过账前余额基线
        b0_bank = await _bal(db, company_id, bank.id, period.id)
        b0_rev = await _bal(db, company_id, rev.id, period.id)
        base_bank = Decimal(str(b0_bank.period_debit)) if b0_bank else Decimal("0")
        base_rev = Decimal(str(b0_rev.period_credit)) if b0_rev else Decimal("0")

        # ---- 建一张平衡凭证(直接入 DRAFT,绕过 START 取号,手工给号)----
        ts = datetime.now().strftime("%H%M%S%f")
        v = m.Voucher(
            company_id=company_id, voucher_number=f"SMOKE-{ts}", voucher_date=date.today(),
            period_id=period.id, voucher_type="GENERAL", description="smoke 借银行/贷收入 1000",
            total_debit=Decimal("1000"), total_credit=Decimal("1000"), status="DRAFT",
            created_by_id=finance.id,
        )
        db.add(v); await db.flush()
        db.add(m.VoucherEntry(voucher_id=v.id, line_number=1, account_id=bank.id, description="收款",
                              debit=Decimal("1000"), credit=Decimal("0"), base_debit=Decimal("1000"), base_credit=Decimal("0"),
                              currency=base_ccy, exchange_rate=Decimal("1")))
        db.add(m.VoucherEntry(voucher_id=v.id, line_number=2, account_id=rev.id, description="确认收入",
                              debit=Decimal("0"), credit=Decimal("1000"), base_debit=Decimal("0"), base_credit=Decimal("1000"),
                              currency=base_ccy, exchange_rate=Decimal("1")))
        await db.commit()
        vid = v.id
        print(f"建单: VOUCHER #{vid} DRAFT(借银行1000/贷收入1000)")

    # ---- 审核(fin_dir) → 过账(boss) ----
    async with factory() as db:
        r1 = await execute_transition(db, "VOUCHER", vid, fin_dir, to_state="AUDITED")
        print(f"审核 DRAFT→AUDITED: {r1.get('success')} {r1.get('error','')}")
        (ok if r1.get("success") else fail).append("审核")
    async with factory() as db:
        r2 = await execute_transition(db, "VOUCHER", vid, boss, to_state="POSTED")
        print(f"过账 AUDITED→POSTED: {r2.get('success')} 完整结果={r2}")
        (ok if r2.get("success") else fail).append("过账")

    # ---- 验 AccountBalance 真的变了 ----
    async with factory() as db:
        b1_bank = await _bal(db, company_id, bank.id, period.id)
        b1_rev = await _bal(db, company_id, rev.id, period.id)
        d_bank = (Decimal(str(b1_bank.period_debit)) - base_bank) if b1_bank else Decimal("0")
        d_rev = (Decimal(str(b1_rev.period_credit)) - base_rev) if b1_rev else Decimal("0")
        print(f"过账后: 银行存款 period_debit +{d_bank} (期望+1000) | 主营收入 period_credit +{d_rev} (期望+1000)")
        (ok if d_bank == Decimal("1000") else fail).append("AccountBalance.银行借方+1000")
        (ok if d_rev == Decimal("1000") else fail).append("AccountBalance.收入贷方+1000")

    # ---- 反例:借贷不平 → 过账应被 validate_balance 拦 ----
    async with factory() as db:
        finance = await _u(db, "finance"); fin_dir = await _u(db, "fin_dir"); boss = await _u(db, "boss")
        company_id = finance.company_id  # PTK #1（香港，HKD 本位）
        company = (await db.execute(select(m.Company).where(m.Company.id == company_id))).scalar_one_or_none()
        base_ccy = (company.currency if company else "HKD") or "HKD"
        period = (await db.execute(select(m.AccountingPeriod).join(m.FiscalYear, m.AccountingPeriod.fiscal_year_id==m.FiscalYear.id).where(m.FiscalYear.company_id==company_id, m.AccountingPeriod.status=="OPEN").order_by(m.AccountingPeriod.id))).scalars().first()
        bank = await _acc(db, company_id, "1002"); rev = await _acc(db, company_id, "6001")
        ts = datetime.now().strftime("%H%M%S%f")
        v2 = m.Voucher(company_id=company_id, voucher_number=f"SMOKEX-{ts}", voucher_date=date.today(), period_id=period.id,
                       voucher_type="GENERAL", description="不平凭证", total_debit=Decimal("1000"), total_credit=Decimal("900"),
                       status="DRAFT", created_by_id=finance.id)
        db.add(v2); await db.flush()
        db.add(m.VoucherEntry(voucher_id=v2.id, line_number=1, account_id=bank.id, debit=Decimal("1000"), credit=Decimal("0"), base_debit=Decimal("1000"), base_credit=Decimal("0"), currency=base_ccy, exchange_rate=Decimal("1")))
        db.add(m.VoucherEntry(voucher_id=v2.id, line_number=2, account_id=rev.id, debit=Decimal("0"), credit=Decimal("900"), base_debit=Decimal("0"), base_credit=Decimal("900"), currency=base_ccy, exchange_rate=Decimal("1")))
        await db.commit(); v2id = v2.id
    async with factory() as db:
        await execute_transition(db, "VOUCHER", v2id, fin_dir, to_state="AUDITED")
    async with factory() as db:
        rx = await execute_transition(db, "VOUCHER", v2id, boss, to_state="POSTED")
        blocked = not rx.get("success")
        print(f"借贷不平过账: success={rx.get('success')} (期望 False 被拦) err={rx.get('error','')[:80]}")
        (ok if blocked else fail).append("借贷不平被validate_balance拦截")

    print("\n==== SMOKE 结果 ====")
    print("✅ 通过:", ok)
    print("❌ 失败:", fail if fail else "无")


if __name__ == "__main__":
    asyncio.run(main())
