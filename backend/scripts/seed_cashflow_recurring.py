"""总账·第六波（finance-gl wave-6）现金流量归集规则 + 定期凭证方案种子（幂等，可重复跑）。

在 backend/ 下执行（须先 alembic upgrade head 到 t4u5v6w7，且先跑过 scripts.seed / seed_finance / seed_master_gl）:
    DATABASE_URL=postgresql+asyncpg://...:5433/... python -m scripts.seed_cashflow_recurring

为 6 公司（HK 3 + CN 3，按 region 二分准则科目码）种入:

A. 现金流量归集规则 cashflow_assign_rule（对手科目码区间 + 现金方向 → 现金流量项目）:
   把含现金类科目（1001/1002…）凭证的对手分录按科目码归集到现金流量项目，使现金流量表自动出数。
   - 应收账款收现 → 销售商品收到的现金（CF_OP_SALE，IN）
   - 应付账款付现 → 购买商品支付的现金（CF_OP_BUY，OUT）
   - 应付职工薪酬付现 → 支付给职工的现金（CF_OP_EMP，OUT）
   - 应交税费缴现 → 支付的各项税费（CF_OP_PTAX，OUT）

B. 定期凭证方案 recurring_voucher_scheme（+ 行模板）2-3 个示例:
   - 待摊费用摊销 12 期（AMORTIZATION）：DR 费用 / CR 预付款项，每期 total/periods。
   - 计提水电预提（ACCRUAL）：DR 费用 / CR 其他应付款（固定模板额）。
   - 月末自动转账（TRANSFER）：示例科目对转（固定模板额）。
   按准则取本区域真实存在的科目码（HK/HKFRS 与 CN/CAS 不同，参 seed_master_gl 模式凭证教训）。

引擎五条不破坏：纯数据，写仍走 execute_transition（MasterDataPage）；本脚本仅 db.add 种子。
"""

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory


# ============================================================
# 幂等 upsert 工具（对齐 seed_finance / seed_master_gl._get 风格）
# ============================================================
async def _get(db, model, **filters):
    stmt = select(model)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalars().first()


# ============================================================
# A. 现金流量归集规则（全公司共用一套；对手科目码两准则同段——应收 1122 / 应付 2202 /
#    应付职工薪酬 2211 / 应交税费 CN 2221、HK 2221）。cashflow_item 按现金流量项目 code 查本公司 id。
#    (code, name, acc_from, acc_to, cash_direction, cf_item_code, priority)
# ============================================================
CASHFLOW_ASSIGN_RULES = [
    ("CFR-SALE",  "销售收现（应收账款收现）",   "1122", "1122", "IN",  "CF_OP_SALE", 10),
    ("CFR-BUY",   "采购付现（应付账款付现）",   "2202", "2202", "OUT", "CF_OP_BUY",  10),
    ("CFR-EMP",   "支付职工薪酬",               "2211", "2211", "OUT", "CF_OP_EMP",  10),
    ("CFR-TAX",   "缴纳税费",                   "2221", "2221", "OUT", "CF_OP_PTAX", 10),
    # 直接现销/现购兜底（对手方直接计收入/费用，未走应收应付）：收入类→经营流入、费用成本类→经营流出。
    # priority=20 低于上面应收应付(10)，仅在未命中往来科目时兜底。两准则收入码段 6001~6051、费用/成本码段 6401~6701。
    ("CFR-SALE-CASH", "现销收现（贷记收入）",     "6001", "6051", "IN",  "CF_OP_SALE", 20),
    ("CFR-EXP-CASH",  "现付费用/成本（借记费用）", "6401", "6701", "OUT", "CF_OP_BUY",  20),
]


# ============================================================
# B. 定期凭证方案 + 行模板（按准则取本区域科目码）。
#    返回 [(code, name, scheme_type, description, total_amount, periods,
#           lines[(line_number, account_code, dr_cr, description, amount, formula)]), ...]
#    摊销行金额留空（amount=None）+ formula='total/periods' → 命令按每期额生成。
#    转账/预提行用固定 amount。
# ============================================================
def _recurring_schemes_for_region(region="CN"):
    if region == "HK":
        # HK/HKFRS：行政费用 6501 / 折旧及摊销 6503 / 预付款项 1123 / 应计费用 2211。
        return [
            ("RS-AMORT-INS", "待摊费用摊销（12 期）", "AMORTIZATION", "Amortisation of prepaid expenses 待摊费用摊销",
             Decimal("12000.00"), 12, [
                 (1, "6501", "DR", "Administrative expenses 摊销待摊费用", None, "total/periods"),
                 (2, "1123", "CR", "Prepayments 待摊费用转销", None, "total/periods"),
             ]),
            ("RS-ACCR-UTIL", "计提水电预提", "ACCRUAL", "Accrual of utilities 计提水电费",
             None, None, [
                 (1, "6501", "DR", "Administrative expenses 计提水电费", Decimal("3000.00"), ""),
                 (2, "2211", "CR", "Accruals 预提水电费", Decimal("3000.00"), ""),
             ]),
            ("RS-TRANSFER", "月末自动转账（示例）", "TRANSFER", "Month-end auto transfer 月末自动转账",
             None, None, [
                 (1, "6501", "DR", "Administrative expenses 月末结转", Decimal("1000.00"), ""),
                 (2, "6502", "CR", "Staff costs 月末结转", Decimal("1000.00"), ""),
             ]),
        ]
    # CN/CAS：管理费用 6602 / 预付账款 1123 / 其他应付款 2241。
    return [
        ("RS-AMORT-INS", "待摊费用摊销（12 期）", "AMORTIZATION", "待摊费用摊销",
         Decimal("12000.00"), 12, [
             (1, "6602", "DR", "管理费用-摊销待摊费用", None, "total/periods"),
             (2, "1123", "CR", "预付账款-待摊费用转销", None, "total/periods"),
         ]),
        ("RS-ACCR-UTIL", "计提水电预提", "ACCRUAL", "计提水电费",
         None, None, [
             (1, "6602", "DR", "管理费用-计提水电费", Decimal("3000.00"), ""),
             (2, "2241", "CR", "其他应付款-预提水电费", Decimal("3000.00"), ""),
         ]),
        ("RS-TRANSFER", "月末自动转账（示例）", "TRANSFER", "月末自动转账",
         None, None, [
             (1, "6602", "DR", "管理费用-月末结转", Decimal("1000.00"), ""),
             (2, "6601", "CR", "销售费用-月末结转", Decimal("1000.00"), ""),
         ]),
    ]


async def _seed_company_cashflow_recurring(db, company, created_by_id):
    """为单家公司种现金流量归集规则 + 定期凭证方案（幂等，已存在跳过）。返回新增计数 dict。"""
    cid = company.id
    region = company.region or "CN"
    counts = {"cf_rule": 0, "scheme": 0, "scheme_line": 0}

    # --- A. 现金流量归集规则（cashflow_item 按 code 查本公司 id；缺项跳过该规则）---
    for code, name, acc_from, acc_to, direction, cf_code, priority in CASHFLOW_ASSIGN_RULES:
        if await _get(db, m.CashflowAssignRule, company_id=cid, code=code) is not None:
            continue
        cf_item = await _get(db, m.CashflowItem, company_id=cid, code=cf_code)
        if cf_item is None:
            continue  # 本公司缺该现金流量项目（应先跑 seed_finance），跳过
        db.add(m.CashflowAssignRule(
            company_id=cid, code=code, name=name,
            account_code_from=acc_from, account_code_to=acc_to,
            cash_direction=direction, cashflow_item_id=cf_item.id,
            priority=priority, is_active=True, created_by_id=created_by_id,
        ))
        counts["cf_rule"] += 1
    await db.flush()

    # --- B. 定期凭证方案（+ 行模板）。voucher_word 取本公司「转」字（若有）---
    zhuan_word = await _get(db, m.VoucherWord, company_id=cid, code="转")
    for code, name, stype, desc, total, periods, lines in _recurring_schemes_for_region(region):
        scheme = await _get(db, m.RecurringVoucherScheme, company_id=cid, code=code)
        if scheme is not None:
            continue
        scheme = m.RecurringVoucherScheme(
            company_id=cid, code=code, name=name, scheme_type=stype,
            voucher_word_id=zhuan_word.id if zhuan_word else None,
            description=desc, total_amount=total, periods=periods,
            start_period_id=None, amortized_periods=0, is_active=True,
            created_by_id=created_by_id,
        )
        db.add(scheme)
        await db.flush()
        counts["scheme"] += 1
        for ln, acode, dr_cr, ldesc, amount, formula in lines:
            # 行模板按 account_code 弱引用，并尽量回填 account_id（本公司同码科目）。
            acct = await _get(db, m.Account, company_id=cid, code=acode)
            db.add(m.RecurringVoucherLine(
                scheme_id=scheme.id, line_number=ln,
                account_id=acct.id if acct else None, account_code=acode,
                dr_cr=dr_cr, description=ldesc, amount=amount, formula=formula or "",
            ))
            counts["scheme_line"] += 1
    await db.flush()

    return counts


async def seed_cashflow_recurring():
    factory = get_session_factory()
    async with factory() as db:
        admin = await _get(db, m.UserAccount, username="admin")
        created_by_id = admin.id if admin else None

        companies = (await db.execute(select(m.Company).order_by(m.Company.id))).scalars().all()
        if not companies:
            print("未找到任何公司，请先跑 scripts.seed。")
            return

        per_company = []
        for company in companies:
            counts = await _seed_company_cashflow_recurring(db, company, created_by_id)
            per_company.append((company, counts))

        await db.commit()

        print("总账·第六波 现金流量归集规则 + 定期凭证方案 种子完成:")
        for company, c in per_company:
            print(
                f"  [{company.code} #{company.id} region={company.region}] "
                f"现金流量归集规则+{c['cf_rule']} 定期凭证方案+{c['scheme']}(行+{c['scheme_line']})"
            )
        print("  ★定期凭证生成走 finance.generate_recurring_voucher；现金流量归集走 finance.assign_cashflow。")


if __name__ == "__main__":
    asyncio.run(seed_cashflow_recurring())
