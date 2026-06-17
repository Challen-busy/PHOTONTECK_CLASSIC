"""段2a 冒烟：采购主链询价端（内部询价 + 对原厂询价 + Q18 字段防火墙）。

经唯一写入路径（execute_transition）验证：
  1) 内部询价（SALES_INQUIRY）：SA 经 execute_transition 建单 → 验业务号 IQ-YYMM-001 +
     扩列 home_page/application/project_phase/competitor_price 落库。
  2) 对原厂询价（SUPPLIER_INQUIRY）：PA 据内部询价建单 + 多供应商报价行（SubTableEditor 子表）
     → 验业务号 SQ-YYMM-001 + 子表 unit_price/commission 落库。
  3) ★Q18 防火墙：以 SALES 和 SA 角色查 supplier_inquiry_line —— query 数据 + schema 两路
     都无 unit_price/commission（但行可见）；以 PA 查则两者皆可见。

在 backend/ 下执行（指向干净库 photonteck_p2a）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p2a \
    python -m scripts.smoke_p2a
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from routers.data import get_schema
from services.tools import query_data
from services.workflow import execute_transition


def _check(label, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        raise SystemExit(f"冒烟失败: {label}")


def _expected_number(prefix: str) -> str:
    """本期首单业务号：prefix-YYMM-001（与 NumberingRule MONTH/pad3/sep- 一致）。"""
    return f"{prefix}-{date.today().strftime('%y%m')}-001"


async def main():
    factory = get_session_factory()

    # ============ 0) 取演示用户/主数据 ============
    async with factory() as db:
        sa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sa"))).scalar_one()
        sales = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sales"))).scalar_one()
        pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "pa"))).scalar_one()
        customer = (await db.execute(select(m.Customer).where(m.Customer.company_id == sa.company_id))).scalars().first()
        material = (await db.execute(select(m.Material))).scalars().first()
        suppliers = (await db.execute(select(m.Supplier).where(m.Supplier.company_id == pa.company_id))).scalars().all()
        company_id = sa.company_id
        sa_id, sales_id, pa_id = sa.id, sales.id, pa.id
        customer_id, material_id = customer.id, material.id
        supplier_a_id, supplier_b_id = suppliers[0].id, suppliers[1].id

    # ============ 1) 内部询价（SALES_INQUIRY）经 execute_transition 建单 ============
    async with factory() as db:
        created = await execute_transition(
            db, "SALES_INQUIRY", None, sa, to_state="START",
            field_updates={
                "customer_id": customer_id, "sales_assistant_id": sa_id,
                "target_price": 12.5, "currency": "USD",
                # 04a-1 扩列
                "home_page": "https://acme.example.com", "application": "激光雷达测距",
                "project_phase": "样品", "demand_forecast": "200K/年",
                "competitor": "Hamamatsu", "competitor_price": 9.80,
            },
        )
        _check("经 execute_transition 建内部询价成功", created.get("success"))
        inq_id = created["doc_id"]
        await db.commit()

    async with factory() as db:
        inq = (await db.execute(select(m.SalesInquiry).where(m.SalesInquiry.id == inq_id))).scalar_one()
        _check(f"内部询价业务号 = {_expected_number('IQ')}（实得 {inq.inquiry_number}）",
               inq.inquiry_number == _expected_number("IQ"))
        _check("扩列 home_page/project_phase 落库", inq.home_page == "https://acme.example.com" and inq.project_phase == "样品")
        _check("扩列 competitor_price 落库", float(inq.competitor_price) == 9.80)

    # ============ 2) 对原厂询价（SUPPLIER_INQUIRY）：PA 据内部询价建多供应商报价行 ============
    async with factory() as db:
        created = await execute_transition(
            db, "SUPPLIER_INQUIRY", None, pa, to_state="START",
            field_updates={
                "supplier_id": supplier_a_id, "sales_inquiry_id": inq_id, "notes": "据内部询价 IQ 向 2 家原厂询价",
            },
            sub_updates=[
                {"table": "supplier_inquiry_line", "parent_fk": "supplier_inquiry_id",
                 "fields": {"line_number": 1, "material_id": material_id, "description": "LD 模块",
                            "unit_price": 8.20, "currency": "USD", "quantity": 1000, "uom": "pcs",
                            "lead_time": "16周", "shipment_terms": "FOB HK", "payment_terms": "T/T in advance",
                            "inquiry_date": date.today().isoformat(), "customer_id": customer_id,
                            "sales": "Olive", "mode": "Resell", "commission": "3%", "supplier_id": supplier_a_id}},
                {"table": "supplier_inquiry_line", "parent_fk": "supplier_inquiry_id",
                 "fields": {"line_number": 2, "material_id": material_id, "description": "LD 模块（备选原厂）",
                            "unit_price": 7.95, "currency": "USD", "quantity": 1000, "uom": "pcs",
                            "lead_time": "25周", "shipment_terms": "CIF SH", "payment_terms": "Net 30",
                            "inquiry_date": date.today().isoformat(), "customer_id": customer_id,
                            "sales": "Olive", "mode": "Resell", "commission": "2.5%", "supplier_id": supplier_b_id}},
            ],
        )
        _check("PA 经 execute_transition 建对原厂询价 + 多供应商报价行成功", created.get("success"))
        sq_id = created["doc_id"]
        await db.commit()

    # START→INQUIRING（引擎 START 注入模式：建单入 START，首个业务态 INQUIRING 经显式流转到达）。
    async with factory() as db:
        u_pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == pa_id))).scalar_one()
        adv = await execute_transition(db, "SUPPLIER_INQUIRY", sq_id, u_pa, to_state="INQUIRING")
        _check("对原厂询价 START→INQUIRING（PA 经 execute_transition 推进）", adv.get("success"))
        await db.commit()

    async with factory() as db:
        sq = (await db.execute(select(m.SupplierInquiry).where(m.SupplierInquiry.id == sq_id))).scalar_one()
        _check(f"对原厂询价业务号 = {_expected_number('SQ')}（实得 {sq.inquiry_number}）",
               sq.inquiry_number == _expected_number("SQ"))
        _check("进入业务态 = INQUIRING", sq.status == "INQUIRING")
        lines = (await db.execute(select(m.SupplierInquiryLine).where(
            m.SupplierInquiryLine.supplier_inquiry_id == sq_id).order_by(m.SupplierInquiryLine.line_number))).scalars().all()
        _check("2 行多供应商报价落库", len(lines) == 2)
        _check("子表 unit_price/commission 落库（PA 视角直查 ORM）",
               float(lines[0].unit_price) == 8.20 and lines[0].commission == "3%")

    # ============ 3) ★Q18 防火墙：SALES / SA 看不到进价，PA 可见 ============
    print("\n  --- Q18 字段防火墙（supplier_inquiry_line）---")
    HIDDEN = {"unit_price", "commission"}

    async with factory() as db:
        for label, role_user in (("SALES", sales), ("SA", sa)):
            # 每次重取（execute_transition/commit 后 ORM 对象 expire）。
            u = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == role_user.id))).scalar_one()

            # 3a) query_data 路：行可见、价格字段被剥。
            qr = await query_data(db, u, {"table": "supplier_inquiry_line", "limit": 50})
            _check(f"{label} 可查 supplier_inquiry_line（行可见，无 table-level 拒绝）",
                   "error" not in qr and qr.get("count", 0) >= 2)
            leaked_q = HIDDEN & set().union(*[set(row.keys()) for row in qr["data"]]) if qr["data"] else set()
            _check(f"{label} query 数据无 {sorted(HIDDEN)}（泄漏: {sorted(leaked_q)}）", not leaked_q)

            # 3b) schema 路：字段定义里也无价格列。
            sch = await get_schema("supplier_inquiry_line", user=u)
            schema_fields = {f["name"] for f in sch["fields"]}
            leaked_s = HIDDEN & schema_fields
            _check(f"{label} schema 无 {sorted(HIDDEN)}（泄漏: {sorted(leaked_s)}）", not leaked_s)

        # 3c) PA 两路都看得到进价。
        u_pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == pa_id))).scalar_one()
        qr_pa = await query_data(db, u_pa, {"table": "supplier_inquiry_line", "limit": 50})
        pa_keys = set().union(*[set(row.keys()) for row in qr_pa["data"]]) if qr_pa["data"] else set()
        _check("PA query 数据可见 unit_price + commission", HIDDEN <= pa_keys)
        sch_pa = await get_schema("supplier_inquiry_line", user=u_pa)
        _check("PA schema 可见 unit_price + commission", HIDDEN <= {f["name"] for f in sch_pa["fields"]})

    print("\n段2a 冒烟全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
