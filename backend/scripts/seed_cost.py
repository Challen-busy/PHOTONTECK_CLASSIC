"""存货核算（finance-gl 成本波）种子：存货成本交易→凭证 的业财映射规则（幂等）。

在 backend/ 下:  DATABASE_URL=...:5433/... python -m scripts.seed_cost

存货成本引擎（移动平均 + 出入库成本交易）已在 WMS，本脚本只补「凭证生成」所需 AccountMappingRule
（source_doc_type=INVENTORY_COSTING，trigger_action=IN 入库 / OUT 出库，按公司准则取本家科目）:
  - 入库 IN：  CAS 借 1405 库存商品 / 贷 1402 在途物资（暂估）；HKFRS 借 1211 Inventories / 贷 1212 Goods in transit。
  - 出库 OUT： CAS 借 6401 主营业务成本 / 贷 1405 库存商品；HKFRS 借 5001 Cost of sales / 贷 1211 Inventories。

引擎五条不破坏：纯数据。核心三件零 diff。
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory

# (trigger_action, [(line_seq, dr_cr, code, memo)])
CAS_RULES = {
    "IN": [(1, "DR", "1405", "存货入库—库存商品"), (2, "CR", "1402", "暂估在途物资结转")],
    "OUT": [(1, "DR", "6401", "结转销售成本"), (2, "CR", "1405", "存货出库—库存商品")],
}
HKFRS_RULES = {
    "IN": [(1, "DR", "1211", "Inventory in"), (2, "CR", "1212", "Goods in transit cleared")],
    "OUT": [(1, "DR", "5001", "Cost of sales"), (2, "CR", "1211", "Inventory out")],
}


async def _get(db, model, **f):
    stmt = select(model)
    for k, v in f.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalars().first()


async def seed_cost():
    factory = get_session_factory()
    async with factory() as db:
        admin = await _get(db, m.UserAccount, username="admin")
        created_by_id = admin.id if admin else None
        companies = (await db.execute(select(m.Company))).scalars().all()
        eff = date(date.today().year, 1, 1)
        new = skip = 0
        for company in companies:
            cid = company.id
            rules = HKFRS_RULES if company.region == "HK" else CAS_RULES
            for trigger, specs in rules.items():
                for line_seq, dr_cr, code, memo in specs:
                    if await _get(db, m.Account, company_id=cid, code=code) is None:
                        print(f"  [警告] 公司#{cid}({company.code}) 缺科目 {code}，跳过 INVENTORY_COSTING/{trigger} line_seq={line_seq}")
                        continue
                    if await _get(db, m.AccountMappingRule, company_id=cid, source_doc_type="INVENTORY_COSTING",
                                  trigger_action=trigger, line_seq=line_seq, effective_date=eff) is not None:
                        skip += 1
                        continue
                    db.add(m.AccountMappingRule(
                        company_id=cid, source_doc_type="INVENTORY_COSTING", trigger_action=trigger,
                        line_seq=line_seq, dr_cr=dr_cr, account_code=code, account_source="FIXED",
                        amount_formula="", tax_handling="NONE", memo_template=memo,
                        date_source="BIZ", effective_date=eff, is_active=True, created_by_id=created_by_id,
                    ))
                    new += 1
        await db.commit()
        print(f"存货核算种子完成: 业财映射规则 新增 {new} / 已存在 {skip}"
              f"（{len(companies)} 公司 × IN/OUT × 2行，CAS 借1405/贷1402 + 借6401/贷1405；HK 借1211/贷1212 + 借5001/贷1211）")


if __name__ == "__main__":
    asyncio.run(seed_cost())
