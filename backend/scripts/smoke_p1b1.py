"""段1b-1 出库冒烟：经唯一写入路径建出库单→分箱拍照→互检→财务放行→SALES_OUTBOUND。

验证：① 客户发货全链路（批次结存递减 + InventoryMovement(OUT) + kingdee_outbox 入队）；
② 串货校验（报备客户≠本单客户）能拦；③ 缺照片引用进互检能拦；④ 委外发料绕过财务放行直发。

在 backend/ 下执行（指向干净库 photonteck_p1b1）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p1b1 \
    python -m scripts.smoke_p1b1
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from services.workflow import execute_transition


def _check(label, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        raise SystemExit(f"冒烟失败: {label}")


async def _fixture_inventory(db, *, company_id, material_id, warehouse_id, created_by_id,
                             inbound_number, qty, reported_customer_id=None):
    inv = m.Inventory(
        material_id=material_id, warehouse_id=warehouse_id, company_id=company_id,
        batch_number=inbound_number, inbound_number=inbound_number,
        serial_lot_number=f"SN-{inbound_number}", goods_nature="GOODS", uom="PCS",
        quantity=qty, reserved_quantity=0, unit_cost=100, total_cost=qty * 100,
        received_date=date.today(), status="AVAILABLE",
        reported_customer_id=reported_customer_id, created_by_id=created_by_id,
    )
    db.add(inv)
    await db.flush()
    return inv


async def _fixture_sales_order(db, *, company_id, customer_id, material_id, created_by_id, number):
    so = m.SalesOrder(
        order_number=number, customer_id=customer_id, company_id=company_id,
        currency="USD", created_by_id=created_by_id, status="CONFIRMED",
    )
    db.add(so)
    await db.flush()
    so_line = m.SalesOrderLine(
        sales_order_id=so.id, line_number=1, material_id=material_id,
        quantity=10, unit_price=200, total_price=2000, tax_rate=0,
    )
    db.add(so_line)
    await db.flush()
    return so, so_line


async def main():
    factory = get_session_factory()

    # ============ 1) 客户发货全链路（正向） ============
    async with factory() as db:
        logistics = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "logistics"))).scalar_one()
        finance = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "finance"))).scalar_one()
        sa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sa"))).scalar_one()
        material = (await db.execute(select(m.Material).where(m.Material.sku == "TOP-DLC-PRO"))).scalar_one()
        intel = (await db.execute(select(m.Customer).where(m.Customer.code == "INTEL"))).scalar_one()
        warehouse = (await db.execute(
            select(m.Warehouse).where(m.Warehouse.company_id == sa.company_id)
        )).scalars().first()
        company_id = sa.company_id
        material_id, warehouse_id, intel_id = material.id, warehouse.id, intel.id
        admin_id = sa.id

        # 库存批次（报备客户=INTEL，匹配本单）+ 销售订单（INTEL）。
        inv = await _fixture_inventory(
            db, company_id=company_id, material_id=material_id, warehouse_id=warehouse_id,
            created_by_id=admin_id, inbound_number="P1B1-OK-01", qty=50, reported_customer_id=intel_id,
        )
        inv_id, inv_qty0 = inv.id, inv.quantity
        so, so_line = await _fixture_sales_order(
            db, company_id=company_id, customer_id=intel_id, material_id=material_id,
            created_by_id=admin_id, number="SO-P1B1-OK",
        )
        so_id, so_line_id = so.id, so_line.id
        await db.commit()

        # 建出库单（START）+ 1 行明细（含每包照片引用，正向路径直通）。
        created = await execute_transition(
            db, "SHIPMENT", None, sa, to_state="START",
            field_updates={
                "sales_order_id": so_id, "warehouse_id": warehouse_id,
                "outbound_type": "CUSTOMER", "shipping_method": "DHL",
            },
            sub_updates=[{
                "table": "shipment_line", "parent_fk": "shipment_id",
                "fields": {
                    "sales_order_line_id": so_line_id, "inventory_id": inv_id,
                    "quantity": 10, "uom": "PCS", "inbound_number": "P1B1-OK-01",
                    "carton_number": "1-3", "photo_refs": ["wms_attachment#1", "wms_attachment#2"],
                },
            }],
        )
        _check("建客户发货出库单成功", created.get("success"))
        sh_id = created["doc_id"]

        # START → DRAFT → PACKING_LABELING（DRAFT 节点 allowed_roles=SA，SA 提交给物流）。
        _check("START→DRAFT", (await execute_transition(db, "SHIPMENT", sh_id, sa, to_state="DRAFT")).get("success"))
        _check("DRAFT→PACKING_LABELING", (await execute_transition(db, "SHIPMENT", sh_id, sa, to_state="PACKING_LABELING")).get("success"))

        # 有照片 → 进互检（PACKING_LABELING→PICKING_RECHECK，照片 hard_rule 通过）。
        _check("有照片进互检（PACKING_LABELING→PICKING_RECHECK）",
               (await execute_transition(db, "SHIPMENT", sh_id, logistics, to_state="PICKING_RECHECK")).get("success"))

        # 互检通过 → 财务放行节点。
        _check("互检→财务放行（PICKING_RECHECK→FINANCE_APPROVAL）",
               (await execute_transition(db, "SHIPMENT", sh_id, logistics, to_state="FINANCE_APPROVAL")).get("success"))

        # 财务放行 → SALES_OUTBOUND（扣库存 + 推金蝶）。
        out = await execute_transition(
            db, "SHIPMENT", sh_id, finance, to_state="SALES_OUTBOUND",
            field_updates={"shipped_date": date.today().replace(day=10).isoformat()},
        )
        _check("财务放行→SALES_OUTBOUND（FINANCE_APPROVAL→SALES_OUTBOUND）", out.get("success"))

        # 验证库存递减。
        inv_after = (await db.execute(select(m.Inventory).where(m.Inventory.id == inv_id))).scalar_one()
        _check(f"批次结存递减 {inv_qty0}→{inv_after.quantity}（-10）", float(inv_after.quantity) == float(inv_qty0) - 10)

        # 验证 InventoryMovement(OUT)。
        mv_out = (await db.execute(
            select(func.count()).select_from(m.InventoryMovement).where(
                m.InventoryMovement.movement_type == "SHIPMENT_OUT",
                m.InventoryMovement.source_doc_type == "SHIPMENT_LINE",
                m.InventoryMovement.inventory_id == inv_id,
            )
        )).scalar()
        _check("写 InventoryMovement(SHIPMENT_OUT)", mv_out >= 1)

        # 验证 kingdee_outbox 入队（幂等键 shipment_number）。
        sh = (await db.execute(select(m.ShipmentRequest).where(m.ShipmentRequest.id == sh_id))).scalar_one()
        outbox = (await db.execute(
            select(m.KingdeeOutbox).where(
                m.KingdeeOutbox.doc_type == "SHIPMENT",
                m.KingdeeOutbox.biz_no == sh.shipment_number,
                m.KingdeeOutbox.company_id == company_id,
            )
        )).scalars().all()
        _check("kingdee_outbox 入队 1 行（biz_no=出库号）", len(outbox) == 1)
        await db.commit()

    # ============ 2) 串货校验（报备客户≠本单客户）能拦 ============
    async with factory() as db:
        logistics = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "logistics"))).scalar_one()
        sa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sa"))).scalar_one()
        material = (await db.execute(select(m.Material).where(m.Material.sku == "TOP-DLC-PRO"))).scalar_one()
        intel = (await db.execute(select(m.Customer).where(m.Customer.code == "INTEL"))).scalar_one()
        ustc = (await db.execute(select(m.Customer).where(m.Customer.code == "USTC"))).scalar_one()
        warehouse = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == sa.company_id))).scalars().first()
        company_id, material_id, warehouse_id, admin_id = sa.company_id, material.id, warehouse.id, sa.id

        # 批次报备给 INTEL，但本单卖给 USTC → 串货。
        inv_intel = await _fixture_inventory(
            db, company_id=company_id, material_id=material_id, warehouse_id=warehouse_id,
            created_by_id=admin_id, inbound_number="P1B1-XGOODS-01", qty=30, reported_customer_id=intel.id,
        )
        so_ustc, so_ustc_line = await _fixture_sales_order(
            db, company_id=company_id, customer_id=ustc.id, material_id=material_id,
            created_by_id=admin_id, number="SO-P1B1-USTC",
        )
        inv_intel_id, so_ustc_id, so_ustc_line_id = inv_intel.id, so_ustc.id, so_ustc_line.id
        await db.commit()

        created = await execute_transition(
            db, "SHIPMENT", None, sa, to_state="START",
            field_updates={"sales_order_id": so_ustc_id, "warehouse_id": warehouse_id, "outbound_type": "CUSTOMER"},
            sub_updates=[{
                "table": "shipment_line", "parent_fk": "shipment_id",
                "fields": {
                    "sales_order_line_id": so_ustc_line_id, "inventory_id": inv_intel_id,
                    "quantity": 5, "uom": "PCS", "photo_refs": ["wms_attachment#9"],
                },
            }],
        )
        sh_id = created["doc_id"]
        await execute_transition(db, "SHIPMENT", sh_id, sa, to_state="DRAFT")
        await execute_transition(db, "SHIPMENT", sh_id, sa, to_state="PACKING_LABELING")
        blocked = await execute_transition(db, "SHIPMENT", sh_id, logistics, to_state="PICKING_RECHECK")
        _check("串货（报备客户≠本单客户）进互检被拦", not blocked.get("success"))
        _check("串货拦截信息指名批次", "P1B1-XGOODS-01" in str(blocked.get("failures") or blocked))
        await db.rollback()

    # ============ 3) 委外发料绕过财务放行直发 ============
    async with factory() as db:
        logistics = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "logistics"))).scalar_one()
        sa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sa"))).scalar_one()
        material = (await db.execute(select(m.Material).where(m.Material.sku == "TOP-DLC-PRO"))).scalar_one()
        supplier = (await db.execute(select(m.Supplier).where(m.Supplier.code == "TOPTICA"))).scalar_one()
        warehouse = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == sa.company_id))).scalars().first()
        company_id, material_id, warehouse_id, vendor_id, admin_id = sa.company_id, material.id, warehouse.id, supplier.id, sa.id

        inv_os = await _fixture_inventory(
            db, company_id=company_id, material_id=material_id, warehouse_id=warehouse_id,
            created_by_id=admin_id, inbound_number="P1B1-OS-01", qty=20, reported_customer_id=None,
        )
        inv_os_id, inv_os_qty0 = inv_os.id, inv_os.quantity
        await db.commit()

        # 委外发料：无 SO，outbound_type=OUTSOURCE，vendor=供应商。
        created = await execute_transition(
            db, "SHIPMENT", None, sa, to_state="START",
            field_updates={
                "warehouse_id": warehouse_id, "outbound_type": "OUTSOURCE",
                "vendor_id": vendor_id, "outsource_note": "发料给委外方加工",
            },
            sub_updates=[{
                "table": "shipment_line", "parent_fk": "shipment_id",
                "fields": {
                    "inventory_id": inv_os_id, "quantity": 8, "uom": "PCS",
                    "inbound_number": "P1B1-OS-01", "photo_refs": ["wms_attachment#7"],
                },
            }],
        )
        _check("建委外发料单成功（无 SO，sales_order_line_id 可空）", created.get("success"))
        sh_id = created["doc_id"]
        await execute_transition(db, "SHIPMENT", sh_id, sa, to_state="DRAFT")
        await execute_transition(db, "SHIPMENT", sh_id, sa, to_state="PACKING_LABELING")
        _check("委外 PACKING_LABELING→PICKING_RECHECK", (await execute_transition(db, "SHIPMENT", sh_id, logistics, to_state="PICKING_RECHECK")).get("success"))
        # 委外直发边：互检 → SALES_OUTBOUND（绕过财务放行）。
        direct = await execute_transition(
            db, "SHIPMENT", sh_id, logistics, to_state="SALES_OUTBOUND",
            field_updates={"shipped_date": date.today().replace(day=10).isoformat()},
        )
        _check("委外发料绕过财务放行直发（PICKING_RECHECK→SALES_OUTBOUND）", direct.get("success"))
        inv_os_after = (await db.execute(select(m.Inventory).where(m.Inventory.id == inv_os_id))).scalar_one()
        _check(f"委外批次结存递减 {inv_os_qty0}→{inv_os_after.quantity}（-8）", float(inv_os_after.quantity) == float(inv_os_qty0) - 8)
        await db.commit()

    # ============ 4) 委外直发边守卫：客户发货不能走直发边 ============
    async with factory() as db:
        logistics = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "logistics"))).scalar_one()
        sa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sa"))).scalar_one()
        material = (await db.execute(select(m.Material).where(m.Material.sku == "TOP-DLC-PRO"))).scalar_one()
        intel = (await db.execute(select(m.Customer).where(m.Customer.code == "INTEL"))).scalar_one()
        warehouse = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == sa.company_id))).scalars().first()
        company_id, material_id, warehouse_id, admin_id = sa.company_id, material.id, warehouse.id, sa.id

        inv2 = await _fixture_inventory(
            db, company_id=company_id, material_id=material_id, warehouse_id=warehouse_id,
            created_by_id=admin_id, inbound_number="P1B1-GUARD-01", qty=20, reported_customer_id=None,
        )
        so2, so2_line = await _fixture_sales_order(
            db, company_id=company_id, customer_id=intel.id, material_id=material_id,
            created_by_id=admin_id, number="SO-P1B1-GUARD",
        )
        inv2_id, so2_id, so2_line_id = inv2.id, so2.id, so2_line.id
        await db.commit()

        created = await execute_transition(
            db, "SHIPMENT", None, sa, to_state="START",
            field_updates={"sales_order_id": so2_id, "warehouse_id": warehouse_id, "outbound_type": "CUSTOMER"},
            sub_updates=[{
                "table": "shipment_line", "parent_fk": "shipment_id",
                "fields": {
                    "sales_order_line_id": so2_line_id, "inventory_id": inv2_id,
                    "quantity": 5, "uom": "PCS", "photo_refs": ["wms_attachment#5"],
                },
            }],
        )
        sh_id = created["doc_id"]
        await execute_transition(db, "SHIPMENT", sh_id, sa, to_state="DRAFT")
        await execute_transition(db, "SHIPMENT", sh_id, sa, to_state="PACKING_LABELING")
        await execute_transition(db, "SHIPMENT", sh_id, logistics, to_state="PICKING_RECHECK")
        guarded = await execute_transition(
            db, "SHIPMENT", sh_id, logistics, to_state="SALES_OUTBOUND",
            field_updates={"shipped_date": date.today().replace(day=10).isoformat()},
        )
        _check("客户发货走委外直发边被守卫拦（须经财务放行）", not guarded.get("success"))
        await db.rollback()

    # ============ 5) 缺照片引用进互检能拦 ============
    async with factory() as db:
        logistics = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "logistics"))).scalar_one()
        sa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sa"))).scalar_one()
        material = (await db.execute(select(m.Material).where(m.Material.sku == "TOP-DLC-PRO"))).scalar_one()
        intel = (await db.execute(select(m.Customer).where(m.Customer.code == "INTEL"))).scalar_one()
        warehouse = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == sa.company_id))).scalars().first()
        company_id, material_id, warehouse_id, admin_id = sa.company_id, material.id, warehouse.id, sa.id

        inv3 = await _fixture_inventory(
            db, company_id=company_id, material_id=material_id, warehouse_id=warehouse_id,
            created_by_id=admin_id, inbound_number="P1B1-NOPHOTO-01", qty=20, reported_customer_id=intel.id,
        )
        so3, so3_line = await _fixture_sales_order(
            db, company_id=company_id, customer_id=intel.id, material_id=material_id,
            created_by_id=admin_id, number="SO-P1B1-NOPHOTO",
        )
        inv3_id, so3_id, so3_line_id = inv3.id, so3.id, so3_line.id
        await db.commit()

        created = await execute_transition(
            db, "SHIPMENT", None, sa, to_state="START",
            field_updates={"sales_order_id": so3_id, "warehouse_id": warehouse_id, "outbound_type": "CUSTOMER"},
            sub_updates=[{
                "table": "shipment_line", "parent_fk": "shipment_id",
                "fields": {  # 故意不挂 photo_refs。
                    "sales_order_line_id": so3_line_id, "inventory_id": inv3_id,
                    "quantity": 5, "uom": "PCS",
                },
            }],
        )
        sh_id = created["doc_id"]
        await execute_transition(db, "SHIPMENT", sh_id, sa, to_state="DRAFT")
        await execute_transition(db, "SHIPMENT", sh_id, sa, to_state="PACKING_LABELING")
        blocked = await execute_transition(db, "SHIPMENT", sh_id, logistics, to_state="PICKING_RECHECK")
        _check("缺照片引用进互检被 hard_rule 拦", not blocked.get("success"))
        await db.rollback()

    print("\n段1b-1 出库冒烟全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
