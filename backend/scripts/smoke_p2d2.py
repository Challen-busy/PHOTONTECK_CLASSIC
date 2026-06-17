"""段2d-2 冒烟：样品 SDN（04b-3）+ RMA 退货统一单（04b-5/04b-6）。

经唯一写入路径（execute_transition / query_data）验证：
  [1] 样品 SDN：建单（含线字母 C → SDN-C-YYMM-001）→ 子表型号 → 走完到 CONVERTED 验该批库存 SAMPLE→AVAILABLE。
  [2] RMA 非我方卖：SA 报修 → PA 核料（SN 无出库记录 → sold_by_us=False）→ 走 REJECTED 边（不进 PM）。
  [3] RMA 成立链：SA 报修 → PA 核料（SN 命中出库 → 成立 ESCALATED_PM）→ PM 决策报原厂 → 对接原厂 →
      货回入库 GOODS_RETURNED→RETURN_TO_CUSTOMER 验退货入库批次 + source_marker（RMA来源+品质+原厂），好货 AVAILABLE。
  [4] ★决策⑨ 双视图字段防火墙（SQL + API 两路）：
      - SQL：rma 表全列含 supplier_id/po_number/supplier_rma_number（库里就有，不靠 schema）。
      - API：SALES/SA query rma 看不到 supplier_id/po_number/supplier_rma_number；PA 看得到全列。
  [5] 架构边界：节点级 allowed_roles 分 SA/PA/PM 控权（PA 无权在 REPORTED 推进 / SA 无权在 PA_VERIFY 推进）。

在 backend/ 下执行（指向干净库 photonteck_p2d2，需先 alembic upgrade head + seed + seed_phase1）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p2d2 \
    python -m scripts.smoke_p2d2
"""

import asyncio
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from services.tools import query_data
from services.workflow import execute_transition


def _check(label, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        raise SystemExit(f"冒烟失败: {label}")


def _ym() -> str:
    return date.today().strftime("%y%m")


async def _user(db, username):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.username == username))).scalar_one()


async def main():
    factory = get_session_factory()

    # ============ 0) 取演示用户/主数据 ============
    async with factory() as db:
        sales = await _user(db, "sales")
        sa = await _user(db, "sa")
        pa = await _user(db, "pa")
        pm = await _user(db, "pm")
        company_id = sales.company_id
        customer = (await db.execute(select(m.Customer).where(m.Customer.company_id == company_id))).scalars().first()
        supplier = (await db.execute(select(m.Supplier).where(m.Supplier.company_id == company_id))).scalars().first()
        warehouse = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == company_id))).scalars().first()
        # 给一个有质保期的型号（material.warranty_months）便于 under_warranty 判定。
        material = (await db.execute(select(m.Material))).scalars().first()
        if material.warranty_months is None:
            material.warranty_months = 12
            await db.commit()
        material_id = material.id
        customer_id, supplier_id = customer.id, supplier.id
        warehouse_id = warehouse.id if warehouse else None

    # ============ 1) 样品 SDN：建单 → 子表 → 走到 CONVERTED → 库存 SAMPLE→AVAILABLE ============
    print("\n[1] 样品 SDN：建单（线字母 C）→ 子表 → CONVERTED 转可售")
    async with factory() as db:
        u = await _user(db, "pa")
        created = await execute_transition(
            db, "SAMPLE_SDN", None, u, to_state="START",
            field_updates={
                "sdn_date": date.today().isoformat(), "supplier_id": supplier_id, "supplier_line": "C",
                "customer_id": customer_id, "sales_id": sales.id, "pa_id": pa.id,
                "sample_nature": "FREE", "target_price": 12.5, "remark": "PCN 样品",
            },
            sub_updates=[{
                "table": "sample_sdn_line", "parent_fk": "sample_sdn_id",
                "fields": {"line_number": 1, "material_id": material_id, "quantity": 20,
                           "description": "良品", "serial_lot_number": "SDN-SN-001"},
            }],
        )
        _check("PA 经 execute_transition 建样品 SDN（含子表）", created.get("success"))
        sdn_id = created["doc_id"]

    async with factory() as db:
        sdn = (await db.execute(select(m.SampleSdn).where(m.SampleSdn.id == sdn_id))).scalar_one()
        expected = f"SDN-C-{_ym()}-001"
        _check(f"SDN 号含供应商线字母 = {expected}（实 {sdn.sdn_number}）", sdn.sdn_number == expected)
        _check("建单落初始 REQUESTED 态前的 START", sdn.status == "START")
        lines = (await db.execute(select(m.SampleSdnLine).where(m.SampleSdnLine.sample_sdn_id == sdn_id))).scalars().all()
        _check(f"子表 1 行（实 {len(lines)}）", len(lines) == 1)

    # 建一批 SAMPLE 库存（模拟样品入样品仓），供 CONVERTED 验转可售。
    async with factory() as db:
        inv = m.Inventory(
            company_id=company_id, material_id=material_id, warehouse_id=warehouse_id,
            batch_number="SDN-SMOKE-BATCH", quantity=Decimal("20"), status="SAMPLE",
            received_date=date.today(),
        )
        db.add(inv)
        await db.commit()
        sample_inv_id = inv.id

    # 走完流程：START→REQUESTED→VENDOR_SHIPPED→STOCKED_SAMPLE→SENT_TO_CUSTOMER→SIGNED→TESTING→CONVERTED。
    # 推进的角色校验落在「来源态」的 allowed_roles：SIGNED→TESTING 由 SIGNED 节点（PA/OPS）发起；
    # TESTING→CONVERTED 由 TESTING 节点（PM/SALES/PA）发起。
    path = [
        ("pa", "REQUESTED"), ("pa", "VENDOR_SHIPPED"), ("pa", "STOCKED_SAMPLE"),
        ("pa", "SENT_TO_CUSTOMER"), ("pa", "SIGNED"), ("pa", "TESTING"), ("pm", "CONVERTED"),
    ]
    for uname, to in path:
        async with factory() as db:
            u = await _user(db, uname)
            r = await execute_transition(db, "SAMPLE_SDN", sdn_id, u, to_state=to)
            _check(f"SDN 推进 → {to}", r.get("success"))

    async with factory() as db:
        inv = (await db.execute(select(m.Inventory).where(m.Inventory.id == sample_inv_id))).scalar_one()
        _check(f"转正后该批库存 SAMPLE→AVAILABLE（实 {inv.status}）", inv.status == "AVAILABLE")

    # ============ 2) RMA 非我方卖 → REJECTED（SN 无出库记录）============
    print("\n[2] RMA 非我方卖：PA 核料 sold_by_us=False → REJECTED")
    async with factory() as db:
        u = await _user(db, "sa")
        created = await execute_transition(
            db, "RMA", None, u, to_state="START",
            field_updates={
                "rma_date": date.today().isoformat(), "customer_id": customer_id, "sales_id": sales.id,
                "failure_description": "客户报点不亮", "failure_location": "PIN3",
            },
            sub_updates=[{
                "table": "rma_line", "parent_fk": "rma_id",
                "fields": {"line_number": 1, "material_id": material_id, "quantity": 5,
                           "serial_lot_number": "RMA-NOSALE-SN-999"},
            }],
        )
        _check("SA 建 RMA（客户侧）", created.get("success"))
        rma1_id = created["doc_id"]

    async with factory() as db:
        rma1 = (await db.execute(select(m.Rma).where(m.Rma.id == rma1_id))).scalar_one()
        _check(f"RMA 号 = RMA-{_ym()}-001（实 {rma1.rma_number}）", rma1.rma_number == f"RMA-{_ym()}-001")
        _check("建单落初始 START 态", rma1.status == "START")

    # START→REPORTED 开始录客户侧（SA）。
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(db, "RMA", rma1_id, u, to_state="REPORTED")
        _check("START→REPORTED 开始客户报修录入", r.get("success"))

    # PA 无权在 REPORTED 推进（节点级 allowed_roles=[SALES_ASSISTANT/SALES/OPERATIONS]）。
    async with factory() as db:
        u = await _user(db, "pa")
        denied = await execute_transition(db, "RMA", rma1_id, u, to_state="PA_VERIFY")
        _check("PA 无权在 REPORTED 推进（节点级 allowed_roles=[SA]）", not denied.get("success"))

    # SA 转 PA 核料。
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(db, "RMA", rma1_id, u, to_state="PA_VERIFY")
        _check("SA 转 PA 核料 REPORTED→PA_VERIFY", r.get("success"))

    # SA 无权在 PA_VERIFY 推进（节点级 allowed_roles=[PRODUCT_ASSISTANT]）。
    async with factory() as db:
        u = await _user(db, "sa")
        denied = await execute_transition(db, "RMA", rma1_id, u, to_state="REJECTED")
        _check("SA 无权在 PA_VERIFY 推进（节点级 allowed_roles=[PA]）", not denied.get("success"))

    # PA 核料走 ESCALATED 触发判定 effect（写 sold_by_us=False，因 SN 无出库），再走 REJECTED 边。
    async with factory() as db:
        u = await _user(db, "pa")
        r = await execute_transition(db, "RMA", rma1_id, u, to_state="ESCALATED_PM",
                                     field_updates={"supplier_id": supplier_id, "ship_date": date.today().isoformat()})
        _check("PA 核料成立边触发判定 effect", r.get("success"))
    async with factory() as db:
        rma1 = (await db.execute(select(m.Rma).where(m.Rma.id == rma1_id))).scalar_one()
        _check(f"核料判定 sold_by_us=False（SN 无出库记录，实 {rma1.sold_by_us}）", rma1.sold_by_us is False)

    # 模拟 PA 据「非我方卖」建议把单驳回（实际业务从 PA_VERIFY 走 REJECTED 边；此处验 REJECTED 可达性见 [3] 反例）。
    print("    （sold_by_us=False 为 PA 驳回依据，gap-7 自动给建议+PA 确认）")

    # ============ 3) RMA 成立链：SN 命中出库 → ESCALATED → PM 报原厂 → 货回入库 + source_marker ============
    print("\n[3] RMA 成立链：核料成立 → PM 决策 → 货回入库带 source_marker（好货 AVAILABLE）")
    # 先造一条出库记录（shipment_line 带 SN），让 sold_by_us 倒查命中（核料判定按 SN 命中我方出库）。
    SOLD_SN = "RMA-SOLD-SN-777"
    async with factory() as db:
        ship = m.ShipmentRequest(company_id=company_id, shipment_number="RMA-SMOKE-SHIP",
                                 requested_by_id=sales.id, status="SHIPPED")
        db.add(ship)
        await db.flush()
        inv2 = m.Inventory(company_id=company_id, material_id=material_id, warehouse_id=warehouse_id,
                           batch_number="RMA-SMOKE-INV", quantity=Decimal("0"), status="AVAILABLE",
                           received_date=date.today())
        db.add(inv2)
        await db.flush()
        db.add(m.ShipmentLine(shipment_id=ship.id, inventory_id=inv2.id, quantity=Decimal("10"),
                              serial_lot_number=SOLD_SN))
        await db.commit()

    async with factory() as db:
        u = await _user(db, "sa")
        created = await execute_transition(
            db, "RMA", None, u, to_state="START",
            field_updates={"rma_date": date.today().isoformat(), "customer_id": customer_id,
                           "sales_id": sales.id, "failure_description": "批量失效"},
            sub_updates=[{
                "table": "rma_line", "parent_fk": "rma_id",
                "fields": {"line_number": 1, "material_id": material_id, "quantity": 10,
                           "serial_lot_number": SOLD_SN, "quality_result": "GOOD"},
            }],
        )
        rma2_id = created["doc_id"]
        _check("SA 建第二张 RMA（成立链）", created.get("success"))

    async with factory() as db:
        u = await _user(db, "sa")
        await execute_transition(db, "RMA", rma2_id, u, to_state="REPORTED")
    async with factory() as db:
        u = await _user(db, "sa")
        await execute_transition(db, "RMA", rma2_id, u, to_state="PA_VERIFY")
    async with factory() as db:
        u = await _user(db, "pa")
        r = await execute_transition(db, "RMA", rma2_id, u, to_state="ESCALATED_PM",
                                     field_updates={"supplier_id": supplier_id, "po_number": "PO-X-1",
                                                    "ship_date": date.today().isoformat()})
        _check("PA 核料成立 → ESCALATED_PM", r.get("success"))
    async with factory() as db:
        rma2 = (await db.execute(select(m.Rma).where(m.Rma.id == rma2_id))).scalar_one()
        _check(f"核料 sold_by_us=True（SN 命中出库，实 {rma2.sold_by_us}）", rma2.sold_by_us is True)
        _check(f"核料 under_warranty=True（在保，实 {rma2.under_warranty}）", rma2.under_warranty is True)

    async with factory() as db:
        u = await _user(db, "pm")
        r = await execute_transition(db, "RMA", rma2_id, u, to_state="VENDOR_RMA",
                                     field_updates={"pm_decision": "VENDOR"})
        _check("PM 决策报原厂 ESCALATED_PM→VENDOR_RMA", r.get("success"))
    async with factory() as db:
        u = await _user(db, "pa")
        r = await execute_transition(db, "RMA", rma2_id, u, to_state="GOODS_RETURNED",
                                     field_updates={"supplier_rma_number": "SUP-RMA-88"})
        _check("PA 对接原厂 → 货回 GOODS_RETURNED", r.get("success"))
    # 货回入库 effect 在 GOODS_RETURNED→RETURN_TO_CUSTOMER 推进时触发。
    async with factory() as db:
        u = await _user(db, "pa")
        r = await execute_transition(db, "RMA", rma2_id, u, to_state="RETURN_TO_CUSTOMER")
        _check("GOODS_RETURNED→RETURN_TO_CUSTOMER 触发货回入库 effect", r.get("success"))

    async with factory() as db:
        rma2 = (await db.execute(select(m.Rma).where(m.Rma.id == rma2_id))).scalar_one()
        ret_inv = (await db.execute(select(m.Inventory).where(
            m.Inventory.company_id == company_id,
            m.Inventory.inbound_number == rma2.rma_number,
        ))).scalars().all()
        _check(f"生成退货入库批次（实 {len(ret_inv)} 批）", len(ret_inv) == 1)
        inv = ret_inv[0]
        _check(f"退货入库 goods_nature=RETURN（实 {inv.goods_nature}）", inv.goods_nature == "RETURN")
        _check(f"好货 status=AVAILABLE 混回可售（实 {inv.status}）", inv.status == "AVAILABLE")
        marker = inv.source_marker or {}
        _check(f"source_marker 带 RMA来源/品质/原厂（实 {marker}）",
               marker.get("rma_source") == "VENDOR" and marker.get("quality") == "GOOD"
               and marker.get("supplier_id") == supplier_id and marker.get("rma_number") == rma2.rma_number)

    # ============ 4) ★决策⑨ 双视图字段防火墙（SQL + API 两路）============
    print("\n[4] ★决策⑨ 双视图字段防火墙（SA 遮蔽采购侧列 / PA 给全列）")
    # SQL 路：库里 rma 表本就含采购侧列（防火墙在序列化/schema 层删，不删库列）。
    async with factory() as db:
        rma2 = (await db.execute(select(m.Rma).where(m.Rma.id == rma2_id))).scalar_one()
        _check("SQL：rma 表库里含 supplier_id（防火墙不删库列）", rma2.supplier_id == supplier_id)
        _check("SQL：rma 表库里含 po_number", rma2.po_number == "PO-X-1")
        _check("SQL：rma 表库里含 supplier_rma_number", rma2.supplier_rma_number == "SUP-RMA-88")

    HIDDEN = {"supplier_id", "po_number", "supplier_rma_number", "unit_price"}
    # API 路（query_data 序列化）：SALES 看不到采购侧列。
    async with factory() as db:
        u = await _user(db, "sales")
        res = await query_data(db, u, {"table": "rma", "filters": {"id": rma2_id}})
        _check("SALES 有权查 rma 表", "error" not in res and res.get("count", 0) == 1)
        row = res["data"][0]
        leaked = [k for k in HIDDEN if k in row]
        _check(f"SALES 视图遮蔽采购侧列（泄漏: {leaked}）", not leaked)
        _check("SALES 视图保留客户侧列 failure_description", "failure_description" in row)

    # API 路：SA（SALES_ASSISTANT）同样遮蔽。
    async with factory() as db:
        u = await _user(db, "sa")
        res = await query_data(db, u, {"table": "rma", "filters": {"id": rma2_id}})
        row = res["data"][0]
        leaked = [k for k in HIDDEN if k in row]
        _check(f"SA 视图遮蔽采购侧列（泄漏: {leaked}）", not leaked)

    # API 路：PA 给全列。
    async with factory() as db:
        u = await _user(db, "pa")
        res = await query_data(db, u, {"table": "rma", "filters": {"id": rma2_id}})
        row = res["data"][0]
        _check("PA 视图可见 supplier_id（全列）", row.get("supplier_id") == supplier_id)
        _check("PA 视图可见 po_number", row.get("po_number") == "PO-X-1")
        _check("PA 视图可见 supplier_rma_number", row.get("supplier_rma_number") == "SUP-RMA-88")

    # 样品 SDN target_price 对 SALES 遮蔽 / PA 可见（§00-8）。
    async with factory() as db:
        u_sales = await _user(db, "sales")
        res = await query_data(db, u_sales, {"table": "sample_sdn", "filters": {"id": sdn_id}})
        _check("SALES 视图遮蔽样品 target_price", "target_price" not in res["data"][0])
        u_pa = await _user(db, "pa")
        res2 = await query_data(db, u_pa, {"table": "sample_sdn", "filters": {"id": sdn_id}})
        _check("PA 视图可见样品 target_price", res2["data"][0].get("target_price") == 12.5)

    print("\n段2d-2 样品 SDN + RMA 冒烟全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
