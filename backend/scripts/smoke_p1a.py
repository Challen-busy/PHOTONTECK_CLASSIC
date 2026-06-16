"""段1a 冒烟：经唯一写入路径建入库单→提交→PA审核→入库，验证全链路。

在 backend/ 下执行（指向干净库 photonteck_p1a）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p1a \
    python -m scripts.smoke_p1a
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


async def main():
    factory = get_session_factory()
    async with factory() as db:
        logistics = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "logistics"))).scalar_one()
        pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "pa"))).scalar_one()
        supplier = (await db.execute(select(m.Supplier).where(m.Supplier.code == "TOPTICA"))).scalar_one()
        material = (await db.execute(select(m.Material).where(m.Material.sku == "TOP-DLC-PRO"))).scalar_one()
        warehouse = (await db.execute(
            select(m.Warehouse).where(m.Warehouse.company_id == logistics.company_id)
        )).scalars().first()
        # 固化为纯 int，避免 execute_command 的 expire_on_commit 让外层 ORM 对象失效后惰性加载触发 MissingGreenlet。
        supplier_id, supplier_pa_id = supplier.id, supplier.responsible_pa_id
        material_id, warehouse_id = material.id, warehouse.id

        # ---- 1) 创建入库单（START）+ 3 行明细 ----
        lines = []
        for i in range(1, 4):
            lines.append({
                "table": "goods_receipt_line",
                "parent_fk": "goods_receipt_id",
                "fields": {
                    "material_id": material_id,
                    "supplier_id": supplier_id,
                    "expected_quantity": 10,
                    "actual_quantity": 10,
                    "serial_lot_number": f"SMOKE-LOT-{i:02d}",
                    "goods_nature": "GOODS",
                    "inbound_number": f"SMOKE-PR-{i:02d}",
                    "batch_number": f"SMOKE-B-{i:02d}",
                    "uom": "PCS",
                    "origin_country": "JAPAN",
                },
            })
        created = await execute_transition(
            db, "GOODS_RECEIPT", None, logistics, to_state="START",
            field_updates={
                "warehouse_id": warehouse_id,
                "supplier_id": supplier_id,
                "inbound_type": "PURCHASE",
                "received_date": date.today().isoformat(),
            },
            sub_updates=lines,
        )
        _check("创建入库单成功", created.get("success"))
        gr_id = created["doc_id"]
        gr = (await db.execute(select(m.GoodsReceipt).where(m.GoodsReceipt.id == gr_id))).scalar_one()
        _check("初始态=START", gr.status == "START")
        _check("3 行明细", (await db.execute(
            select(func.count()).select_from(m.GoodsReceiptLine).where(m.GoodsReceiptLine.goods_receipt_id == gr_id)
        )).scalar() == 3)

        # ---- 2) START → PENDING ----
        r = await execute_transition(db, "GOODS_RECEIPT", gr_id, logistics, to_state="PENDING")
        _check("START→PENDING 成功", r.get("success"))

        # ---- 3) PENDING → PA_REVIEW（验进库通知 + 审核 PA 自动匹配）----
        r = await execute_transition(db, "GOODS_RECEIPT", gr_id, logistics, to_state="PA_REVIEW")
        _check("PENDING→PA_REVIEW 成功", r.get("success"))
        await db.refresh(gr)
        _check("审核 PA 自动匹配 reviewer_id", gr.reviewer_id == supplier_pa_id)
        notes = (await db.execute(
            select(m.Notification).where(
                m.Notification.source_doc_type == "GOODS_RECEIPT",
                m.Notification.source_doc_id == gr_id,
                m.Notification.category == "GOODS_RECEIPT_NOTICE",
            )
        )).scalars().all()
        _check("进库通知入 Notification（reviewer 直达 + CC PA）", len(notes) >= 2)
        _check("进库通知直达 reviewer", any(n.recipient_id == gr.reviewer_id for n in notes))

        # ---- 5) PA_REVIEW → STOCKED_IN（生成 3 批次 + 3 流水 IN + 推金蝶入队）----
        r = await execute_transition(db, "GOODS_RECEIPT", gr_id, pa, to_state="STOCKED_IN")
        _check("PA_REVIEW→STOCKED_IN 成功", r.get("success"))
        await db.refresh(gr)
        _check("终态=STOCKED_IN", gr.status == "STOCKED_IN")

        inv_rows = (await db.execute(
            select(m.Inventory).where(m.Inventory.inbound_number.like("SMOKE-PR-%"))
        )).scalars().all()
        _check("生成 3 条 Inventory 批次", len(inv_rows) == 3)
        _check("批次 status=AVAILABLE（GOODS 性质）", all(i.status == "AVAILABLE" for i in inv_rows))

        mv_in = (await db.execute(
            select(func.count()).select_from(m.InventoryMovement).where(
                m.InventoryMovement.movement_type == "GOODS_RECEIPT_IN",
                m.InventoryMovement.source_doc_type == "GOODS_RECEIPT_LINE",
            )
        )).scalar()
        _check("写 3 条 InventoryMovement(IN)", mv_in == 3)

        outbox = (await db.execute(
            select(m.KingdeeOutbox).where(
                m.KingdeeOutbox.doc_type == "GOODS_RECEIPT",
                m.KingdeeOutbox.biz_no == gr.receipt_number,
            )
        )).scalars().all()
        _check("kingdee_outbox 入队 1 行", len(outbox) == 1)

        await db.commit()

        # ---- 6) 标签命令：3 行 → 3 个 inbound_number payload ----
        from services.commands import execute_command
        label_res = await execute_command(
            db, logistics, "print_inbound_labels", {"goods_receipt_id": gr_id},
        )
        _check("标签命令成功", label_res.get("success"))
        labels = label_res.get("labels")
        _check("标签命令产出 3 个 payload", labels is not None and len(labels) == 3)
        _check("标签主字段=inbound_number 条码", all(
            any(f.get("title") == "入仓编号" and f.get("render_as_barcode") for f in lb["payload"]["fields"])
            for lb in labels
        ))

    # ---- 7) hard_rule 负向：另起一单，实收≠应收 → STOCKED_IN 被拦 ----
    # 用全新 session（前一 session 经多次 commit/run_sync，重开避免跨调用上下文污染）。
    async with factory() as db:
        logistics = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "logistics"))).scalar_one()
        pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "pa"))).scalar_one()
        bad = await execute_transition(
            db, "GOODS_RECEIPT", None, logistics, to_state="START",
            field_updates={"warehouse_id": warehouse_id, "supplier_id": supplier_id, "received_date": date.today().isoformat()},
            sub_updates=[{
                "table": "goods_receipt_line", "parent_fk": "goods_receipt_id",
                "fields": {
                    "material_id": material_id, "supplier_id": supplier_id,
                    "expected_quantity": 10, "actual_quantity": 7,  # 实收≠应收
                    "serial_lot_number": "SMOKE-BAD-01", "goods_nature": "GOODS",
                    "inbound_number": "SMOKE-BAD-01", "batch_number": "SMOKE-BAD-B01", "uom": "PCS",
                },
            }],
        )
        bad_id = bad["doc_id"]
        await execute_transition(db, "GOODS_RECEIPT", bad_id, logistics, to_state="PENDING")
        await execute_transition(db, "GOODS_RECEIPT", bad_id, logistics, to_state="PA_REVIEW")
        # 每次 commit 后 ORM 对象被 expire；重取 pa 再用（execute_transition 内会读 user.role）。
        pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "pa"))).scalar_one()
        blocked = await execute_transition(db, "GOODS_RECEIPT", bad_id, pa, to_state="STOCKED_IN")
        _check("Σ明细≠头总数 hard_rule 拦截", not blocked.get("success"))

    print("\n段1a 冒烟全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
