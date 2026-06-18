"""总账·第二波（finance-gl wave-2）模块 C：业财映射规则种子（销售开票 → 凭证，幂等可重复跑）。

在 backend/ 下执行（须先 alembic upgrade head 到 r2s3t4u5，且已跑 scripts.seed + scripts.seed_finance）:
    python -m scripts.seed_mapping

种「销售开票 → 自动凭证」的 AccountMappingRule（6 家公司，按准则取本家科目码）：

  · CAS 内地（RJ/XGTC/TR，company 4/5/6，本位币 CNY，含增值税）→ 3 行：
      line_seq 1  DR 1122 应收账款        amount_formula=amount  tax_handling=INCLUSIVE  source=CUSTOMER   # 价税合计
      line_seq 2  CR 6001 主营业务收入    amount_formula=amount  tax_handling=EXCLUSIVE                    # 不含税
      line_seq 3  CR 222102 应交增值税(销项) amount_formula=amount tax_handling=TAX_ONLY                     # 仅税额
    ★CAS 6401=主营业务成本（结转成本规则下一波再种），收入用 6001。

  · HKFRS 香港（PTK/ADS/FTK，company 1/2/3，本位币 HKD，无销项增值税）→ 2 行：
      line_seq 1  DR 1122 Trade receivables  amount_formula=amount  tax_handling=NONE  source=CUSTOMER
      line_seq 2  CR 6001 Revenue            amount_formula=amount  tax_handling=NONE
    ★HK 6401=Selling expenses（销售费用），≠主营成本（HK 5001=Cost of sales）；本规则只碰收入 6001，
      不误用 6401（准则差异锚点：科目码落在各家规则 account_code 上，不在代码硬编码）。

trigger_action 统一用 POSTED（对齐销售发票流程「确认/过账」目标动作）；effective_date=本财年 1/1。
幂等键 = (company_id, source_doc_type=SALES_INVOICE, trigger_action, line_seq, effective_date)，已存在跳过。
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory


# (line_seq, dr_cr, account_code, account_source, amount_formula, tax_handling, memo_template)
CAS_SALES_INVOICE_RULES = [
    (1, "DR", "1122",   "CUSTOMER", "amount", "INCLUSIVE", "应收账款—{customer}（{invoice_number}）"),
    (2, "CR", "6001",   "FIXED",    "amount", "EXCLUSIVE", "确认主营业务收入（{invoice_number}）"),
    (3, "CR", "222102", "FIXED",    "amount", "TAX_ONLY",  "应交增值税（销项税额）（{invoice_number}）"),
]

HKFRS_SALES_INVOICE_RULES = [
    (1, "DR", "1122", "CUSTOMER", "amount", "NONE", "Trade receivables - {customer} ({invoice_number})"),
    (2, "CR", "6001", "FIXED",    "amount", "NONE", "Recognise revenue ({invoice_number})"),
]


def _rules_for_region(region: str):
    return HKFRS_SALES_INVOICE_RULES if region == "HK" else CAS_SALES_INVOICE_RULES


async def _get(db, model, **filters):
    stmt = select(model)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalars().first()


async def seed_mapping():
    factory = get_session_factory()
    async with factory() as db:
        admin = await _get(db, m.UserAccount, username="admin")
        created_by_id = admin.id if admin else None

        companies = (await db.execute(select(m.Company).order_by(m.Company.id))).scalars().all()
        if not companies:
            print("未找到任何公司，请先跑 scripts.seed + scripts.seed_finance。")
            return

        eff = date(date.today().year, 1, 1)  # 本财年生效日
        per_company = []
        for company in companies:
            cid = company.id
            rules = _rules_for_region(company.region)
            standard = "HKFRS" if company.region == "HK" else "CAS"
            new_cnt = 0
            skipped = 0
            for line_seq, dr_cr, code, source, formula, tax, memo in rules:
                # 守卫：目标科目须在本公司科目表存在（否则映射不可用，跳过并告警）。
                acct = await _get(db, m.Account, company_id=cid, code=code)
                if acct is None:
                    print(f"  [警告] 公司#{cid}({company.code}) 缺科目 {code}，跳过该映射行 line_seq={line_seq}")
                    continue
                existing = await _get(
                    db, m.AccountMappingRule,
                    company_id=cid, source_doc_type="SALES_INVOICE",
                    trigger_action="POSTED", line_seq=line_seq, effective_date=eff,
                )
                if existing is not None:
                    skipped += 1
                    continue
                db.add(m.AccountMappingRule(
                    company_id=cid,
                    source_doc_type="SALES_INVOICE",
                    trigger_action="POSTED",
                    line_seq=line_seq,
                    dr_cr=dr_cr,
                    account_code=code,
                    account_source=source,
                    amount_formula=formula,
                    tax_handling=tax,
                    memo_template=memo,
                    date_source="BIZ",
                    effective_date=eff,
                    is_active=True,
                    created_by_id=created_by_id,
                ))
                new_cnt += 1
            await db.flush()
            per_company.append((company, standard, new_cnt, skipped))

        await db.commit()

        print("总账·第二波业财映射种子完成（销售开票→凭证，按公司分准则）:")
        for company, standard, new_cnt, skipped in per_company:
            print(
                f"  [{company.code} #{company.id} region={company.region} 准则={standard}] "
                f"SALES_INVOICE→VOUCHER 规则 新增 {new_cnt} / 已存在 {skipped}"
            )
        print("  ★科目码取自各家科目表（HK 收入 6001 无销项税 2 行；CAS 应收/收入/销项 3 行）。")
        print("  下一步：建一张销售发票，由 finance_mapping.create_voucher_from_sales_invoice 自动生成并过账凭证。")


if __name__ == "__main__":
    asyncio.run(seed_mapping())
