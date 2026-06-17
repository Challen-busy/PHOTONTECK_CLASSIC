"""自检：建单取号 effect 接线（段0b·1）。不进版本库，仅本地验证。

seed 的编号规则 separator='-'、period_format='%y%m'，故业务号形如 PR-2606-001。
引擎默认兜底号形如 GOOD-260616-A1B2C3（YYMMDD + 6位HEX），二者可区分。
全程 manage_transaction=False 单事务跑、结尾 rollback，可重复执行不污染库。
"""

import asyncio
import re
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from services.workflow import execute_transition

PASS = True
PER = date.today().strftime("%y%m")


def _check(label, ok):
    global PASS
    print(f"  [{'OK ' if ok else 'XX '}] {label}")
    if not ok:
        PASS = False


def _biz(prefix, seq):
    return rf"{re.escape(prefix)}-{PER}-{seq:03d}"


async def _create(db, doc_type, user, **field_updates):
    return await execute_transition(
        db, doc_type, None, user, to_state="START",
        manage_transaction=False, field_updates=field_updates,
    )


async def main():
    factory = get_session_factory()
    async with factory() as db:
        u = {name: (await db.execute(select(m.UserAccount).where(m.UserAccount.username == name))).scalar_one()
             for name in ("logistics", "finance", "sa", "admin")}
        ptk = (await db.execute(select(m.Company).where(m.Company.code == "PTK"))).scalar_one()
        ads = (await db.execute(select(m.Company).where(m.Company.code == "ADS"))).scalar_one()
        wh = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == ptk.id))).scalars().first()
        supplier = (await db.execute(select(m.Supplier))).scalars().first()
        locs = (await db.execute(select(m.WarehouseLocation).where(m.WarehouseLocation.warehouse_id == wh.id))).scalars().all()
        src_loc, tgt_loc = locs[0], (locs[1] if len(locs) > 1 else locs[0])

        # 1) GOODS_RECEIPT → PR-{YYMM}-001，同公司连建 001/002 递增
        async def mk_gr(user, w):
            r = await _create(db, "GOODS_RECEIPT", user, warehouse_id=w.id, supplier_id=supplier.id, inbound_type="PURCHASE")
            return (await db.execute(select(m.GoodsReceipt).where(m.GoodsReceipt.id == r["doc_id"]))).scalar_one()
        gr1 = await mk_gr(u["logistics"], wh)
        _check(f"GR1 receipt_number={gr1.receipt_number} == PR-{PER}-001",
               bool(re.fullmatch(_biz("PR", 1), gr1.receipt_number)))
        gr2 = await mk_gr(u["logistics"], wh)
        _check(f"GR2 receipt_number={gr2.receipt_number} == PR-{PER}-002 (同公司递增)",
               bool(re.fullmatch(_biz("PR", 2), gr2.receipt_number)))

        # 3) SHIPMENT（sa 角色）→ PD-{YYMM}-001
        rs = await _create(db, "SHIPMENT", u["sa"])
        sh = (await db.execute(select(m.ShipmentRequest).where(m.ShipmentRequest.id == rs["doc_id"]))).scalar_one()
        _check(f"SHIPMENT shipment_number={sh.shipment_number} == PD-{PER}-001",
               bool(re.fullmatch(_biz("PD", 1), sh.shipment_number)))

        # 4) STOCK_TRANSFER（TR）/ STOCK_ADJUSTMENT（AJ）/ SALES_RETURN（RMA）/ SALES_INVOICE（I）
        rt = await _create(db, "STOCK_TRANSFER", u["logistics"], source_location_id=src_loc.id, target_location_id=tgt_loc.id)
        tr = (await db.execute(select(m.StockTransfer).where(m.StockTransfer.id == rt["doc_id"]))).scalar_one()
        _check(f"STOCK_TRANSFER transfer_number={tr.transfer_number} == TR-{PER}-001",
               bool(re.fullmatch(_biz("TR", 1), tr.transfer_number)))

        # 2) 不同公司各自连号 —— 在「按公司唯一」的 STOCK_TRANSFER 上验证（PTK 已建 001，
        #    ADS 独立从 001 起，二者经 UniqueConstraint(company_id, transfer_number) 共存）。
        #    注：GOODS_RECEIPT/SHIPMENT/PURCHASE_ORDER 的单号列是「全局 unique」，跨公司同期同号
        #    会撞库——见 engineFlags 标注（需 schema 决策，本接线层不擅改）。
        admin = u["admin"]
        admin.company_id = ads.id
        await db.flush()
        ads_wh = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == ads.id))).scalars().first()
        ads_locs = (await db.execute(select(m.WarehouseLocation).where(m.WarehouseLocation.warehouse_id == (ads_wh.id if ads_wh else wh.id)))).scalars().all()
        a_src = ads_locs[0] if ads_locs else src_loc
        a_tgt = ads_locs[1] if len(ads_locs) > 1 else a_src
        rta = await _create(db, "STOCK_TRANSFER", admin, source_location_id=a_src.id, target_location_id=a_tgt.id)
        tra = (await db.execute(select(m.StockTransfer).where(m.StockTransfer.id == rta["doc_id"]))).scalar_one()
        _check(f"ADS 公司 STOCK_TRANSFER transfer_number={tra.transfer_number} == TR-{PER}-001 (跨公司各自连号)",
               bool(re.fullmatch(_biz("TR", 1), tra.transfer_number)))
        admin.company_id = ptk.id
        await db.flush()

        rj = await _create(db, "STOCK_ADJUSTMENT", u["finance"])
        aj = (await db.execute(select(m.StockAdjustment).where(m.StockAdjustment.id == rj["doc_id"]))).scalar_one()
        _check(f"STOCK_ADJUSTMENT adjustment_number={aj.adjustment_number} == AJ-{PER}-001",
               bool(re.fullmatch(_biz("AJ", 1), aj.adjustment_number)))

        rr = await _create(db, "SALES_RETURN", u["sa"])
        ret = (await db.execute(select(m.SalesReturn).where(m.SalesReturn.id == rr["doc_id"]))).scalar_one()
        _check(f"SALES_RETURN return_number={ret.return_number} == RMA-{PER}-001",
               bool(re.fullmatch(_biz("RMA", 1), ret.return_number)))

        ri = await _create(db, "SALES_INVOICE", u["finance"])
        si = (await db.execute(select(m.SalesInvoice).where(m.SalesInvoice.id == ri["doc_id"]))).scalar_one()
        _check(f"SALES_INVOICE invoice_number={si.invoice_number} == I-{PER}-001",
               bool(re.fullmatch(_biz("I", 1), si.invoice_number)))

        # 5) 无规则 doc_type（CUSTOMER 建档）仍走引擎默认不报错
        rc = await _create(db, "CUSTOMER", u["admin"], name="自检客户", code=f"CHK{gr1.id}")
        _check("无规则 CUSTOMER 建档不报错（走引擎默认 UUID 号）", rc.get("success"))

        # 6) 幂等：再触发 effect 不重号（防退回初态/再触发重号）
        from services.numbering_effect import assign_business_number
        before = gr1.receipt_number
        logs = await assign_business_number(db, "GOODS_RECEIPT", gr1, "START", u["logistics"], None)
        _check(f"幂等守卫：业务号已存在，再触发 effect no-op（仍={before}，logs={logs}）",
               gr1.receipt_number == before and logs == [])

        await db.rollback()  # 自检不落库

    print("\n建单取号接线自检完成 ✅" if PASS else "\n自检有失败 ❌")
    sys.exit(0 if PASS else 1)


if __name__ == "__main__":
    asyncio.run(main())
