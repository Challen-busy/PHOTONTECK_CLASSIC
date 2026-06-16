"""段1b-2 冒烟：盘点→库存调整单 / 调拨单 / 库位建档 / 委外加工入库。

经唯一写入路径（execute_command / execute_transition）验证：
  1) 盘点：建盘点单→录实际数(造差异)→提交复核(差异行须备注)→生成库存调整单草稿→
     填差异原因→confirm→posted；验 inventory.quantity 调整 + COUNT_ADJUST 流水 + outbox 入队。
  2) 调拨：同公司 done 验库位变更 + 两条 TRANSFER 流水；跨公司被 hard_rule 拦。
  3) 库位：经 execute_transition 建库位成功。
  4) 委外加工入库：inbound_type=OUTSOURCE_IN 走完 GOODS_RECEIPT 入库链（STOCKED_IN 生成库存）。

在 backend/ 下执行（指向干净库 photonteck_p1b2）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p1b2 \
    python -m scripts.smoke_p1b2
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from services.commands import execute_command
from services.workflow import execute_transition


def _check(label, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        raise SystemExit(f"冒烟失败: {label}")


async def _inv(db, *, company_id, material_id, warehouse_id, location_id, created_by_id,
               inbound_number, qty):
    inv = m.Inventory(
        material_id=material_id, warehouse_id=warehouse_id, company_id=company_id,
        location_id=location_id, location_code="",
        batch_number=inbound_number, inbound_number=inbound_number,
        serial_lot_number=f"SN-{inbound_number}", goods_nature="GOODS", uom="PCS",
        quantity=qty, reserved_quantity=0, unit_cost=100, total_cost=qty * 100,
        received_date=date.today(), status="AVAILABLE", created_by_id=created_by_id,
    )
    db.add(inv)
    await db.flush()
    return inv


async def main():
    factory = get_session_factory()

    # ============ 1) 盘点 → 库存调整单全链路 ============
    async with factory() as db:
        logistics = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "logistics"))).scalar_one()
        finance = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "finance"))).scalar_one()
        material = (await db.execute(select(m.Material).where(m.Material.sku == "TOP-DLC-PRO"))).scalar_one()
        warehouse = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == logistics.company_id))).scalars().first()
        company_id = logistics.company_id
        loc = (await db.execute(select(m.WarehouseLocation).where(m.WarehouseLocation.warehouse_id == warehouse.id))).scalars().first()

        inv = await _inv(db, company_id=company_id, material_id=material.id, warehouse_id=warehouse.id,
                         location_id=loc.id, created_by_id=logistics.id, inbound_number="P1B2-CNT-01", qty=100)
        inv_id, inv_qty0 = inv.id, float(inv.quantity)
        await db.commit()

        # 建盘点单（命令路径，按库存生成盘点行）。
        r = await execute_command(db, logistics, "create_inventory_count", {"warehouse_id": warehouse.id})
        _check("建盘点单成功", r.get("success"))
        count_id = r["id"]

        # 取该批次的盘点行，录实际数=90（造差异 -10）。
        async with factory() as db2:
            line = (await db2.execute(select(m.InventoryCountLine).where(
                m.InventoryCountLine.inventory_count_id == count_id,
                m.InventoryCountLine.inventory_id == inv_id,
            ))).scalar_one()
            line_id = line.id
            _check("盘点行带出 goods_nature 快照", (line.goods_nature or "") == "GOODS")

        # 先不填备注录实际数 → 提交复核应被差异备注 hard_rule 拦。
        async with factory() as db3:
            await execute_command(db3, logistics, "update_inventory_count_line",
                                  {"count_id": count_id, "line_id": line_id, "counted_quantity": 90})
        async with factory() as db4:
            # 其余行可能未录（仅本批次造差异）；先把其它行按系统数补平以隔离差异备注校验。
            others = (await db4.execute(select(m.InventoryCountLine).where(
                m.InventoryCountLine.inventory_count_id == count_id,
                m.InventoryCountLine.id != line_id,
            ))).scalars().all()
            for o in others:
                await execute_command(db4, logistics, "update_inventory_count_line",
                                      {"count_id": count_id, "line_id": o.id,
                                       "counted_quantity": float(o.system_quantity)})

        async with factory() as db5:
            blocked = await execute_command(db5, logistics, "submit_inventory_count", {"count_id": count_id})
            _check("差异行无调查备注 → 提交复核被拦", not blocked.get("success"))

        # 补差异行调查备注后再提交复核。
        async with factory() as db6:
            await execute_command(db6, logistics, "update_inventory_count_line",
                                  {"count_id": count_id, "line_id": line_id, "counted_quantity": 90,
                                   "notes": "查出库登记：实际发货没错，登记表填错10"})
        async with factory() as db7:
            ok = await execute_command(db7, logistics, "submit_inventory_count", {"count_id": count_id})
            _check("差异行有调查备注 → 提交复核成功", ok.get("success"))

        # 生成库存调整单草稿（盘点 review → 派生）。
        async with factory() as db8:
            gen = await execute_command(db8, logistics, "generate_stock_adjustment_from_count", {"count_id": count_id})
            _check("盘点差异生成库存调整单草稿成功", gen.get("success") and gen.get("generated"))
            adj_id = gen["id"]
            # 幂等：再生成一次回放（不重复建单）。
            gen2 = await execute_command(db8, logistics, "generate_stock_adjustment_from_count", {"count_id": count_id})
            _check("再次生成 → 幂等回放（不重复建单）", gen2.get("id") == adj_id and gen2.get("generated") is False)

        # 调整单走 START→DRAFT→CONFIRM→POSTED。先把差异行原因填上（confirm hard_rule 必填）。
        async with factory() as db9:
            adj = (await db9.execute(select(m.StockAdjustment).where(m.StockAdjustment.id == adj_id))).scalar_one()
            _check("调整单初态=DRAFT", adj.status == "DRAFT")
            adj_lines = (await db9.execute(select(m.StockAdjustmentLine).where(
                m.StockAdjustmentLine.stock_adjustment_id == adj_id))).scalars().all()
            _check("调整单 1 行差异明细", len(adj_lines) == 1)
            adj_line_id = adj_lines[0].id

        # 不填原因直接 confirm→posted 应被 hard_rule 拦。
        async with factory() as dbA:
            blocked2 = await execute_transition(dbA, "STOCK_ADJUSTMENT", adj_id, finance, to_state="POSTED")
            # 当前在 DRAFT，POSTED 非合法跳转 → 先到 CONFIRM 再试。
        async with factory() as dbB:
            r = await execute_transition(dbB, "STOCK_ADJUSTMENT", adj_id, finance, to_state="CONFIRM")
            _check("DRAFT→CONFIRM", r.get("success"))
        async with factory() as dbC:
            blocked3 = await execute_transition(dbC, "STOCK_ADJUSTMENT", adj_id, finance, to_state="POSTED")
            _check("差异原因未填 → CONFIRM→POSTED 被 hard_rule 拦", not blocked3.get("success"))

        # 填差异原因（子表行）后再 posted。
        async with factory() as dbD:
            await execute_transition(dbD, "STOCK_ADJUSTMENT", adj_id, finance, to_state="CONFIRM",
                                     sub_updates=[{"table": "stock_adjustment_line", "id": adj_line_id,
                                                   "fields": {"reason": "OUT_ERR"}}])
        async with factory() as dbE:
            posted = await execute_transition(dbE, "STOCK_ADJUSTMENT", adj_id, finance, to_state="POSTED")
            _check("差异原因已填 → CONFIRM→POSTED 成功", posted.get("success"))

        # 验证库存调整 + 流水 + outbox。
        async with factory() as dbF:
            inv_after = (await dbF.execute(select(m.Inventory).where(m.Inventory.id == inv_id))).scalar_one()
            _check(f"inventory.quantity 调整 {inv_qty0}→{inv_after.quantity}（=实际盘点 90）", float(inv_after.quantity) == 90)
            mv = (await dbF.execute(select(func.count()).select_from(m.InventoryMovement).where(
                m.InventoryMovement.movement_type == "COUNT_ADJUST",
                m.InventoryMovement.source_doc_type == "STOCK_ADJUSTMENT",
                m.InventoryMovement.inventory_id == inv_id,
            ))).scalar()
            _check("写 InventoryMovement(COUNT_ADJUST)", mv >= 1)
            adj = (await dbF.execute(select(m.StockAdjustment).where(m.StockAdjustment.id == adj_id))).scalar_one()
            outbox = (await dbF.execute(select(m.KingdeeOutbox).where(
                m.KingdeeOutbox.doc_type == "STOCK_ADJUSTMENT",
                m.KingdeeOutbox.biz_no == adj.adjustment_number,
                m.KingdeeOutbox.company_id == company_id,
            ))).scalars().all()
            _check("kingdee_outbox 入队 1 行（biz_no=调整单号）", len(outbox) == 1)

    # ============ 2) 调拨单：同公司 done + 跨公司被拦 ============
    async with factory() as db:
        logistics = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "logistics"))).scalar_one()
        # REVIEW/DONE 由物流主任做（PRD 页面5）；seed 无 logistics_lead，用 ops(OPERATIONS) 代（在 allowed_roles）。
        lead = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "ops"))).scalar_one()
        material = (await db.execute(select(m.Material).where(m.Material.sku == "TOP-DLC-PRO"))).scalar_one()
        company_id = logistics.company_id
        wh = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == company_id))).scalars().first()
        locs = (await db.execute(select(m.WarehouseLocation).where(m.WarehouseLocation.warehouse_id == wh.id)
                                 .order_by(m.WarehouseLocation.id))).scalars().all()
        src_loc, tgt_loc = locs[0], locs[1]
        # 跨公司目标库位（另一家公司的仓库库位）。
        other_wh = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id != company_id))).scalars().first()
        other_loc = (await db.execute(select(m.WarehouseLocation).where(m.WarehouseLocation.warehouse_id == other_wh.id))).scalars().first()

        inv = await _inv(db, company_id=company_id, material_id=material.id, warehouse_id=wh.id,
                         location_id=src_loc.id, created_by_id=logistics.id, inbound_number="P1B2-TRF-01", qty=40)
        inv_id = inv.id
        src_loc_id, tgt_loc_id, other_loc_id = src_loc.id, tgt_loc.id, other_loc.id
        await db.commit()

        # 同公司调拨：START→DRAFT(选源/目标库位+明细)→REVIEW→DONE。
        created = await execute_transition(
            db, "STOCK_TRANSFER", None, logistics, to_state="START",
            field_updates={"source_location_id": src_loc_id, "target_location_id": tgt_loc_id},
            sub_updates=[{"table": "stock_transfer_line", "parent_fk": "stock_transfer_id",
                          "fields": {"inventory_id": inv_id, "inbound_number": "P1B2-TRF-01", "quantity": 40}}],
        )
        _check("建调拨单成功", created.get("success"))
        trf_id = created["doc_id"]
        await db.commit()

        async with factory() as dba:
            r = await execute_transition(dba, "STOCK_TRANSFER", trf_id, logistics, to_state="DRAFT")
            _check("调拨 START→DRAFT", r.get("success"))
        async with factory() as dbb:
            r = await execute_transition(dbb, "STOCK_TRANSFER", trf_id, logistics, to_state="REVIEW")
            _check("调拨 DRAFT→REVIEW", r.get("success"))
        async with factory() as dbc:
            done = await execute_transition(dbc, "STOCK_TRANSFER", trf_id, lead, to_state="DONE")
            _check("调拨 REVIEW→DONE（同公司）", done.get("success"))
        async with factory() as dbd:
            inv_after = (await dbd.execute(select(m.Inventory).where(m.Inventory.id == inv_id))).scalar_one()
            _check(f"库位变更 → {tgt_loc_id}", inv_after.location_id == tgt_loc_id)
            mv_out = (await dbd.execute(select(func.count()).select_from(m.InventoryMovement).where(
                m.InventoryMovement.movement_type == "TRANSFER_OUT",
                m.InventoryMovement.source_doc_type == "STOCK_TRANSFER",
                m.InventoryMovement.inventory_id == inv_id))).scalar()
            mv_in = (await dbd.execute(select(func.count()).select_from(m.InventoryMovement).where(
                m.InventoryMovement.movement_type == "TRANSFER_IN",
                m.InventoryMovement.source_doc_type == "STOCK_TRANSFER",
                m.InventoryMovement.inventory_id == inv_id))).scalar()
            _check("写两条流水 TRANSFER_OUT + TRANSFER_IN", mv_out >= 1 and mv_in >= 1)

        # 跨公司调拨：目标库位属另一家公司 → REVIEW→DONE 被 hard_rule + validator 拦。
        async with factory() as dbe:
            inv2 = await _inv(dbe, company_id=company_id, material_id=material.id, warehouse_id=wh.id,
                              location_id=src_loc_id, created_by_id=logistics.id, inbound_number="P1B2-TRF-XCO", qty=10)
            inv2_id = inv2.id
            await dbe.commit()
        async with factory() as dbf:
            created2 = await execute_transition(
                dbf, "STOCK_TRANSFER", None, logistics, to_state="START",
                field_updates={"source_location_id": src_loc_id, "target_location_id": other_loc_id},
                sub_updates=[{"table": "stock_transfer_line", "parent_fk": "stock_transfer_id",
                              "fields": {"inventory_id": inv2_id, "inbound_number": "P1B2-TRF-XCO", "quantity": 10}}],
            )
            trf2_id = created2["doc_id"]
            await dbf.commit()
        async with factory() as dbg:
            await execute_transition(dbg, "STOCK_TRANSFER", trf2_id, logistics, to_state="DRAFT")
        async with factory() as dbh:
            await execute_transition(dbh, "STOCK_TRANSFER", trf2_id, logistics, to_state="REVIEW")
        async with factory() as dbi:
            blocked = await execute_transition(dbi, "STOCK_TRANSFER", trf2_id, lead, to_state="DONE")
            _check("跨公司调拨 REVIEW→DONE 被拦", not blocked.get("success"))

    # ============ 3) 库位经 execute_transition 建档 ============
    async with factory() as db:
        admin = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "admin"))).scalar_one()
        wh = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == admin.company_id))).scalars().first()
        created = await execute_transition(
            db, "WAREHOUSE_LOCATION", None, admin, to_state="ACTIVE",
            field_updates={"warehouse_id": wh.id, "code": "P1B2-NEWLOC", "zone": "Z",
                           "shelf": "01", "position": "A", "location_type": "NORMAL"},
        )
        _check("经 execute_transition 建库位成功", created.get("success"))
        new_loc_id = created["doc_id"]
        await db.commit()
        async with factory() as dba:
            loc = (await dba.execute(select(m.WarehouseLocation).where(m.WarehouseLocation.id == new_loc_id))).scalar_one()
            _check("新库位入 ACTIVE 态", loc.status == "ACTIVE" and loc.code == "P1B2-NEWLOC")
            # 自环编辑：改容量。
            edited = await execute_transition(dba, "WAREHOUSE_LOCATION", new_loc_id, admin,
                                              to_state="ACTIVE", field_updates={"capacity": 500})
            _check("库位自环编辑改字段成功", edited.get("success"))

    # ============ 4) 委外加工入库：inbound_type=OUTSOURCE_IN 走完入库链 ============
    async with factory() as db:
        logistics = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "logistics"))).scalar_one()
        pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "pa"))).scalar_one()
        material = (await db.execute(select(m.Material).where(m.Material.sku == "TOP-DLC-PRO"))).scalar_one()
        supplier = (await db.execute(select(m.Supplier).where(m.Supplier.code == "TOPTICA"))).scalar_one()
        wh = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == logistics.company_id))).scalars().first()
        company_id, material_id, supplier_id, wh_id = logistics.company_id, material.id, supplier.id, wh.id

        # 建委外加工入库单（GOODS_RECEIPT，inbound_type=OUTSOURCE_IN + source_issue_number 弱关联）。
        created = await execute_transition(
            db, "GOODS_RECEIPT", None, logistics, to_state="START",
            field_updates={
                "warehouse_id": wh_id, "inbound_type": "OUTSOURCE_IN",
                "supplier_id": supplier_id, "reviewer_id": pa.id,
                "received_date": date.today().isoformat(),
                "source_issue_number": "ISS-OS-0001",
            },
            sub_updates=[{"table": "goods_receipt_line", "parent_fk": "goods_receipt_id",
                          "fields": {"material_id": material_id, "expected_quantity": 12, "actual_quantity": 12,
                                     "goods_nature": "GOODS", "serial_lot_number": "SN-OS-12",
                                     "inbound_number": "OSIN-0001", "supplier_id": supplier_id}}],
        )
        _check("建委外加工入库单成功（inbound_type=OUTSOURCE_IN）", created.get("success"))
        gr_id = created["doc_id"]
        await db.commit()

        async with factory() as dba:
            gr = (await dba.execute(select(m.GoodsReceipt).where(m.GoodsReceipt.id == gr_id))).scalar_one()
            _check("source_issue_number 弱关联留痕", gr.source_issue_number == "ISS-OS-0001")
            _check("inbound_type=OUTSOURCE_IN", gr.inbound_type == "OUTSOURCE_IN")

        # START→PENDING→PA_REVIEW→STOCKED_IN（复用整套 GOODS_RECEIPT 流程）。
        async with factory() as dbb:
            r = await execute_transition(dbb, "GOODS_RECEIPT", gr_id, logistics, to_state="PENDING")
            _check("入库 START→PENDING", r.get("success"))
        async with factory() as dbc:
            r = await execute_transition(dbc, "GOODS_RECEIPT", gr_id, logistics, to_state="PA_REVIEW")
            _check("入库 PENDING→PA_REVIEW", r.get("success"))
        async with factory() as dbd:
            r = await execute_transition(dbd, "GOODS_RECEIPT", gr_id, pa, to_state="STOCKED_IN")
            _check("入库 PA_REVIEW→STOCKED_IN（委外复用 STOCKED_IN effect）", r.get("success"))
        async with factory() as dbe:
            inv_new = (await dbe.execute(select(m.Inventory).where(
                m.Inventory.company_id == company_id,
                m.Inventory.inbound_number == "OSIN-0001",
            ))).scalars().all()
            _check("委外加工入库生成库存批次（quantity=12）",
                   len(inv_new) == 1 and float(inv_new[0].quantity) == 12)

    print("\n段1b-2 冒烟全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
