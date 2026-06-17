"""里程碑演示 · 入库全链 + 字段防火墙（走真实引擎写入路径，落 dev 库，UI 可见）。

出库两道关 / 串货隔离 / 盘点→调整 / 调拨 / 委外 由 smoke 验证套件实证
（scripts.smoke_p1a / smoke_p1b1 / smoke_p1b2，每条业务规则带断言）。
  cd backend && python -m scripts.demo_milestone
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

F = get_session_factory()


def hr(t): print("\n" + "─" * 72 + f"\n▌ {t}\n" + "─" * 72)
def ok(msg): print(f"  ✅ {msg}")
def info(msg): print(f"     {msg}")


async def U(db, name):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.username == name))).scalar_one()


async def main():
    async with F() as db:
        co = (await U(db, "logistics")).company_id
        supplier_id = (await db.execute(select(m.Supplier.id).where(m.Supplier.company_id == co))).scalars().first()
        mat_ids = (await db.execute(select(m.Material.id).order_by(m.Material.id))).scalars().all()
        mat1, mat2 = mat_ids[0], (mat_ids[1] if len(mat_ids) > 1 else mat_ids[0])
        wh_id = (await db.execute(select(m.Warehouse.id).where(m.Warehouse.company_id == co))).scalars().first()
        cust = (await db.execute(select(m.Customer.id, m.Customer.name).where(m.Customer.company_id == co))).all()
        intel_id, intel_name = cust[0]

    print("\n" + "═" * 72)
    print("  PHOTONTECK CRM+WMS · 里程碑「底座 + WMS」实景演示")
    print("  公司 PTK(香港) · 全程走引擎唯一写入路径 execute_transition")
    print("═" * 72)

    # ===================== 1. 入库收货全链 =====================
    hr("① 入库收货全链：物流建单 → 取业务号 → 进库通知 → PA审核 → 库存生效 → 推金蝶")
    async with F() as db:
        logistics, pa = await U(db, "logistics"), await U(db, "pa")
        lines = [{"table": "goods_receipt_line", "parent_fk": "goods_receipt_id", "fields": {
            "material_id": mat, "expected_quantity": qty, "actual_quantity": qty,
            "serial_lot_number": f"LOT-{i:02d}", "goods_nature": "GOODS", "uom": "PCS",
            "supplier_id": supplier_id, "origin_country": "JAPAN", "hs_code": "8541.40",
            "batch_number": f"B{i:02d}", "unit_cost": 120, "inbound_number": f"PR-2606-001-{i:02d}"}}
            for i, (mat, qty) in enumerate([(mat1, 50), (mat2, 30)], start=1)]
        gr = await execute_transition(db, "GOODS_RECEIPT", None, logistics, to_state="START",
            field_updates={"warehouse_id": wh_id, "supplier_id": supplier_id, "inbound_type": "PURCHASE",
                           "reviewer_id": pa.id, "received_date": date.today().isoformat()}, sub_updates=lines)
        gr_id = gr["doc_id"]
        receipt = (await db.execute(select(m.GoodsReceipt.receipt_number).where(m.GoodsReceipt.id == gr_id))).scalar()
        ok("物流(logistics)建入库单，2 行批次明细（共 80 PCS）")
        info(f"业务单号 = {receipt}  ← 编号引擎月度连号、按公司隔离（非 uuid 兜底号）")
        assert (await execute_transition(db, "GOODS_RECEIPT", gr_id, logistics, to_state="PENDING")).get("success")
        assert (await execute_transition(db, "GOODS_RECEIPT", gr_id, logistics, to_state="PA_REVIEW")).get("success")
        notif = (await db.execute(select(func.count()).select_from(m.Notification).where(m.Notification.source_doc_id == gr_id))).scalar()
        ok(f"物流提交审核 → 自动生成进库通知 {notif} 条，直达审核 PA 收件箱")
        assert (await execute_transition(db, "GOODS_RECEIPT", gr_id, pa, to_state="STOCKED_IN")).get("success")
        ok("PA(pa)审核通过 → 入库生效（★唯一审核关卡，财务做账随推金蝶在金蝶侧）")
        invs = (await db.execute(select(m.Inventory).where(m.Inventory.inbound_number.like("PR-2606-001%")).order_by(m.Inventory.id))).scalars().all()
        movn = (await db.execute(select(func.count()).select_from(m.InventoryMovement).where(m.InventoryMovement.source_doc_id == gr_id))).scalar()
        obrow = (await db.execute(select(m.KingdeeOutbox.form_id).where(m.KingdeeOutbox.biz_no == receipt))).scalars().all()
        info(f"→ 生成 {len(invs)} 个库存批次：{', '.join(i.inbound_number for i in invs)}")
        info(f"→ 写 {movn} 条库存流水（IN，事件溯源，库存=流水累加） | 推金蝶 outbox 1 行（{obrow[0] if obrow else '-'}，开关默认 OFF 只入队）")
        invs[0].reported_customer_id = intel_id
        await db.flush()
        ok(f"批次 {invs[0].inbound_number} 标记原厂报备客户 = {intel_name[:18]}（串货隔离锚点，出库时校验）")
        b1_id = invs[0].id
        await db.commit()

    # ===================== 2. 字段防火墙 =====================
    hr("② 字段防火墙：同一条库存，BOSS 看得到成本，SALES 看不到（进价对销售隐藏）")
    async with F() as db:
        from services.tools import _can_view_buy_price, BUY_PRICE_FIELDS, BUY_TABLES
        boss, sales = await U(db, "boss"), await U(db, "sales")
        b = (await db.execute(select(m.Inventory).where(m.Inventory.id == b1_id))).scalar_one()

        def view_as(user):
            row = {"入仓编号": b.inbound_number, "数量": float(b.quantity),
                   "unit_cost": float(b.unit_cost or 0), "total_cost": float(b.total_cost or 0)}
            if "inventory" in BUY_TABLES and not _can_view_buy_price(user):
                for f in BUY_PRICE_FIELDS:
                    row.pop(f, None)
            return row
        ok(f"BOSS  视角 : {view_as(boss)}")
        ok(f"SALES 视角 : {view_as(sales)}  ← 成本列被剔除")
        info("→ unit_cost/total_cost 对 SALES 在 query+schema 两路遮蔽（inventory ∈ BUY_TABLES）")

    # ===================== 审计 + 业务号 =====================
    hr("③ 全程留痕（审计四本）+ 业务号")
    async with F() as db:
        cl_n = (await db.execute(select(func.count()).select_from(m.CommandLog))).scalar()
        wl_n = (await db.execute(select(func.count()).select_from(m.WorkflowLog))).scalar()
        ok(f"命令日志 CommandLog {cl_n} 条 | 工作流日志 WorkflowLog {wl_n} 条（每个写动作可追溯到人/时/前后值）")
        info("金蝶推送队列：")
        for o in (await db.execute(select(m.KingdeeOutbox).order_by(m.KingdeeOutbox.id))).scalars().all():
            print(f"        · {o.biz_no:18} → {o.form_id or '-':14} [{o.status}]（待真实接入按 6 公司组织码推送）")

    print("\n" + "═" * 72)
    print("  入库全链 + 字段防火墙 已落 dev 库 → http://localhost:6328 可在 UI 查看入库单/库存")
    print("  登录 admin/admin1234，或 logistics/pa/finance/sales（demo1234）体验角色裁剪")
    print("═" * 72 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
