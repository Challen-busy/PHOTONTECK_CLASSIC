"""WMS 一期专用接口：库存、预留、SN/LOT 校验、报表、导入和附件。"""

import csv
import io
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import get_db
from services.commands import execute_command
from services.tools import _company_filter
from services.wms import (
    ACTIVE_RESERVATION,
    available_quantity_for_customer,
    barcode_requirement_failures,
    validate_sn_lot_value,
)


router = APIRouter(prefix="/api/wms")


async def _run_command(db: AsyncSession, user: m.UserAccount, command_name: str, payload: dict,
                       idempotency_key: str | None = None) -> dict:
    result = await execute_command(db, user, command_name, payload, idempotency_key=idempotency_key)
    if not result.get("success"):
        raise HTTPException(status_code=result.get("status_code", 400), detail=result.get("error") or "操作失败")
    return result


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _company_ids(user: m.UserAccount):
    return _company_filter(user)


def _can_view_inventory_cost(user: m.UserAccount) -> bool:
    return user.role in {"BOSS", "OPERATIONS", "FINANCE", "PRODUCT_ASSISTANT", "PRODUCT_MANAGER"}


def _assert_company_access(user: m.UserAccount, company_id: int):
    ids = _company_ids(user)
    if ids and company_id not in ids:
        raise HTTPException(status_code=403, detail="无权访问该公司数据")


def _date_or_today(value: str | None) -> date:
    if not value:
        return date.today()
    return date.fromisoformat(value[:10])


def _csv_response(filename: str, rows: list[dict], headers: list[tuple[str, str]]):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([title for _, title in headers])
    for row in rows:
        writer.writerow([row.get(key, "") for key, _ in headers])
    data = "\ufeff" + buf.getvalue()
    return StreamingResponse(
        iter([data.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _row_label(db: AsyncSession, model, row_id: int | None, *fields: str) -> str:
    if not row_id:
        return ""
    row = (await db.execute(select(model).where(model.id == row_id))).scalar_one_or_none()
    if not row:
        return f"#{row_id}"
    for field in fields:
        value = getattr(row, field, None)
        if value:
            return str(value)
    return f"#{row_id}"


class ReservationRequest(BaseModel):
    inventory_id: int
    customer_id: int
    quantity: Decimal
    sales_order_id: int | None = None
    shipment_id: int | None = None
    notes: str = ""


class ReleaseReservationRequest(BaseModel):
    notes: str = ""


class SnRuleRequest(BaseModel):
    id: int | None = None
    supplier_id: int
    material_id: int | None = None
    rule_name: str = ""
    exact_length: int | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str = ""
    allow_duplicate: bool = True
    unique_scope: str = "SUPPLIER_MATERIAL"
    is_active: bool = True
    notes: str = ""


class SnValidateRequest(BaseModel):
    supplier_id: int
    material_id: int | None = None
    serial_lot_number: str
    inventory_id: int | None = None


class InventoryPolicyRequest(BaseModel):
    id: int | None = None
    material_id: int
    warehouse_id: int | None = None
    safety_stock: Decimal = Decimal("0")
    reorder_point: Decimal = Decimal("0")
    max_stock: Decimal = Decimal("0")
    lead_time_days: int = 0
    is_active: bool = True
    notes: str = ""


class CountCreateRequest(BaseModel):
    warehouse_id: int | None = None
    planned_date: str | None = None
    notes: str = ""


class CountLineUpdateRequest(BaseModel):
    counted_quantity: Decimal
    notes: str = ""


class StockMatchRequest(BaseModel):
    sales_order_id: int | None = None
    shipment_id: int | None = None
    warehouse_id: int | None = None


class AutoAllocateRequest(BaseModel):
    warehouse_id: int | None = None


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    company_ids = _company_ids(user)
    inv_stmt = select(
        func.count(m.Inventory.id),
        func.coalesce(func.sum(m.Inventory.quantity), 0),
        func.coalesce(func.sum(m.Inventory.reserved_quantity), 0),
    )
    if company_ids:
        inv_stmt = inv_stmt.where(m.Inventory.company_id.in_(company_ids))
    inv_count, qty, reserved = (await db.execute(inv_stmt)).one()

    today = date.today()
    inbound_stmt = select(func.coalesce(func.sum(m.GoodsReceiptLine.actual_quantity), 0)).join(
        m.GoodsReceipt, m.GoodsReceiptLine.goods_receipt_id == m.GoodsReceipt.id
    ).where(m.GoodsReceipt.received_date == today)
    outbound_stmt = select(func.coalesce(func.sum(m.ShipmentLine.quantity), 0)).join(
        m.ShipmentRequest, m.ShipmentLine.shipment_id == m.ShipmentRequest.id
    ).where(m.ShipmentRequest.shipped_date == today)
    if company_ids:
        inbound_stmt = inbound_stmt.where(m.GoodsReceipt.company_id.in_(company_ids))
        outbound_stmt = outbound_stmt.where(m.ShipmentRequest.company_id.in_(company_ids))

    inbound_today = (await db.execute(inbound_stmt)).scalar()
    outbound_today = (await db.execute(outbound_stmt)).scalar()
    return {
        "inventory_count": int(inv_count or 0),
        "total_quantity": float(qty or 0),
        "reserved_quantity": float(reserved or 0),
        "available_quantity": float(_num(qty) - _num(reserved)),
        "inbound_today": float(inbound_today or 0),
        "outbound_today": float(outbound_today or 0),
    }


@router.get("/inventory")
async def inventory_list(
    search: str = "",
    warehouse_id: int | None = None,
    material_id: int | None = None,
    limit: int = Query(200, le=500),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    stmt = select(m.Inventory).where(m.Inventory.quantity > 0)
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.Inventory.company_id.in_(company_ids))
    if warehouse_id:
        stmt = stmt.where(m.Inventory.warehouse_id == warehouse_id)
    if material_id:
        stmt = stmt.where(m.Inventory.material_id == material_id)
    if search:
        s = f"%{search}%"
        stmt = stmt.join(m.Material, m.Inventory.material_id == m.Material.id, isouter=True).where(
            or_(
                m.Inventory.inbound_number.ilike(s),
                m.Inventory.serial_lot_number.ilike(s),
                m.Inventory.batch_number.ilike(s),
                m.Inventory.tracking_number.ilike(s),
                m.Material.sku.ilike(s),
                m.Material.name.ilike(s),
            )
        )
    stmt = stmt.order_by(m.Inventory.received_date.desc().nullslast(), m.Inventory.id.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    data = []
    show_cost = _can_view_inventory_cost(user)
    for inv in rows:
        available = await available_quantity_for_customer(db, inv)
        row = {
            "id": inv.id,
            "inbound_number": inv.inbound_number,
            "batch_number": inv.batch_number,
            "material_id": inv.material_id,
            "material": await _row_label(db, m.Material, inv.material_id, "sku", "name"),
            "supplier_id": inv.supplier_id,
            "supplier": await _row_label(db, m.Supplier, inv.supplier_id, "short_name", "name", "code"),
            "warehouse_id": inv.warehouse_id,
            "warehouse": await _row_label(db, m.Warehouse, inv.warehouse_id, "name", "code"),
            "serial_lot_number": inv.serial_lot_number,
            "goods_nature": inv.goods_nature,
            "quantity": float(inv.quantity or 0),
            "reserved_quantity": float(inv.reserved_quantity or 0),
            "available_quantity": float(available),
            "uom": inv.uom,
            "location_code": inv.location_code,
            "carton_number": inv.carton_number,
            "date_code": inv.date_code,
            "production_date": inv.production_date.isoformat() if inv.production_date else None,
            "origin_country": inv.origin_country,
            "hs_code": inv.hs_code,
            "tracking_number": inv.tracking_number,
            "delivery_method": inv.delivery_method,
            "received_date": inv.received_date.isoformat() if inv.received_date else None,
            "status": inv.status,
        }
        if show_cost:
            row["unit_cost"] = float(inv.unit_cost or 0)
            row["total_cost"] = float(inv.total_cost or 0)
        data.append(row)
    return {"data": data, "count": len(data)}


@router.get("/reservations")
async def reservations(
    status: str = ACTIVE_RESERVATION,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    stmt = select(m.InventoryReservation).where(m.InventoryReservation.status == status).order_by(m.InventoryReservation.id.desc())
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.InventoryReservation.company_id.in_(company_ids))
    rows = (await db.execute(stmt.limit(300))).scalars().all()
    data = []
    for r in rows:
        inv = (await db.execute(select(m.Inventory).where(m.Inventory.id == r.inventory_id))).scalar_one_or_none()
        data.append({
            "id": r.id,
            "reservation_number": r.reservation_number,
            "inventory_id": r.inventory_id,
            "inbound_number": inv.inbound_number if inv else "",
            "serial_lot_number": inv.serial_lot_number if inv else "",
            "material": await _row_label(db, m.Material, inv.material_id if inv else None, "sku", "name"),
            "customer_id": r.customer_id,
            "customer": await _row_label(db, m.Customer, r.customer_id, "short_name", "name", "code"),
            "sales_order_id": r.sales_order_id,
            "sales_order": await _row_label(db, m.SalesOrder, r.sales_order_id, "order_number", "customer_po_number"),
            "quantity": float(r.quantity or 0),
            "reserved_at": r.reserved_at.isoformat() if r.reserved_at else None,
            "released_at": r.released_at.isoformat() if r.released_at else None,
            "status": r.status,
            "notes": r.notes,
        })
    return {"data": data, "count": len(data)}


@router.get("/audit/commands")
async def command_audit(
    command_name: str = "",
    status: str = "",
    limit: int = Query(100, le=300),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    stmt = select(m.CommandLog).order_by(m.CommandLog.created_at.desc(), m.CommandLog.id.desc())
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.CommandLog.company_id.in_(company_ids))
    if command_name:
        stmt = stmt.where(m.CommandLog.command_name.ilike(f"%{command_name}%"))
    if status:
        stmt = stmt.where(m.CommandLog.status == status)
    rows = (await db.execute(stmt.limit(limit))).scalars().all()
    return {"data": [
        {
            "id": row.id,
            "command_name": row.command_name,
            "status": row.status,
            "actor_id": row.actor_id,
            "actor": await _row_label(db, m.UserAccount, row.actor_id, "full_name", "username"),
            "company_id": row.company_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "error_message": row.error_message,
        }
        for row in rows
    ], "count": len(rows)}


@router.get("/audit/movements")
async def movement_audit(
    movement_type: str = "",
    material_id: int | None = None,
    inventory_id: int | None = None,
    command_log_id: int | None = None,
    limit: int = Query(200, le=500),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    stmt = select(m.InventoryMovement).order_by(m.InventoryMovement.created_at.desc(), m.InventoryMovement.id.desc())
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.InventoryMovement.company_id.in_(company_ids))
    if movement_type:
        stmt = stmt.where(m.InventoryMovement.movement_type == movement_type)
    if material_id:
        stmt = stmt.where(m.InventoryMovement.material_id == material_id)
    if inventory_id:
        stmt = stmt.where(m.InventoryMovement.inventory_id == inventory_id)
    if command_log_id:
        stmt = stmt.where(m.InventoryMovement.command_log_id == command_log_id)
    rows = (await db.execute(stmt.limit(limit))).scalars().all()
    show_cost = _can_view_inventory_cost(user)
    data = []
    for row in rows:
        inv = (await db.execute(select(m.Inventory).where(m.Inventory.id == row.inventory_id))).scalar_one_or_none() if row.inventory_id else None
        command = (await db.execute(select(m.CommandLog).where(m.CommandLog.id == row.command_log_id))).scalar_one_or_none() if row.command_log_id else None
        item = {
            "id": row.id,
            "command_log_id": row.command_log_id,
            "command_name": command.command_name if command else "",
            "movement_type": row.movement_type,
            "material_id": row.material_id,
            "material": await _row_label(db, m.Material, row.material_id, "sku", "name"),
            "warehouse_id": row.warehouse_id,
            "warehouse": await _row_label(db, m.Warehouse, row.warehouse_id, "name", "code"),
            "inventory_id": row.inventory_id,
            "inbound_number": inv.inbound_number if inv else "",
            "serial_lot_number": inv.serial_lot_number if inv else "",
            "quantity_delta": float(row.quantity_delta or 0),
            "reserved_delta": float(row.reserved_delta or 0),
            "source_doc_type": row.source_doc_type,
            "source_doc_id": row.source_doc_id,
            "notes": row.notes,
            "created_by_id": row.created_by_id,
            "created_by": await _row_label(db, m.UserAccount, row.created_by_id, "full_name", "username"),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        if show_cost:
            item["unit_cost"] = float(row.unit_cost or 0)
        data.append(item)
    return {"data": data, "count": len(data)}


@router.post("/reservations")
async def reserve_inventory(
    req: ReservationRequest,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    result = await _run_command(db, user, "reserve_inventory", req.model_dump())
    return {"success": True, "id": result["id"], "reservation_number": result["reservation_number"]}


@router.post("/reservations/{reservation_id}/release")
async def release_reservation(
    reservation_id: int,
    req: ReleaseReservationRequest,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    result = await _run_command(
        db,
        user,
        "release_reservation",
        {"reservation_id": reservation_id, **req.model_dump()},
        idempotency_key=f"release_reservation:{reservation_id}",
    )
    response = {"success": True}
    if result.get("message"):
        response["message"] = result["message"]
    return response


@router.get("/sn-rules")
async def list_sn_rules(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    stmt = select(m.SupplierSnRule).order_by(m.SupplierSnRule.id.desc())
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.SupplierSnRule.company_id.in_(company_ids))
    rows = (await db.execute(stmt.limit(300))).scalars().all()
    return {"data": [
        {
            "id": r.id,
            "supplier_id": r.supplier_id,
            "supplier": await _row_label(db, m.Supplier, r.supplier_id, "short_name", "name", "code"),
            "material_id": r.material_id,
            "material": await _row_label(db, m.Material, r.material_id, "sku", "name"),
            "rule_name": r.rule_name,
            "exact_length": r.exact_length,
            "min_length": r.min_length,
            "max_length": r.max_length,
            "pattern": r.pattern,
            "allow_duplicate": r.allow_duplicate,
            "unique_scope": r.unique_scope,
            "is_active": r.is_active,
            "notes": r.notes,
        }
        for r in rows
    ]}


@router.post("/sn-rules")
async def upsert_sn_rule(
    req: SnRuleRequest,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    result = await _run_command(db, user, "upsert_supplier_sn_rule", req.model_dump())
    return {"success": True, "id": result["id"]}


@router.post("/sn-rules/validate")
async def validate_sn_rule(
    req: SnValidateRequest,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    supplier = (await db.execute(select(m.Supplier).where(m.Supplier.id == req.supplier_id))).scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=404, detail="供应商不存在")
    _assert_company_access(user, supplier.company_id)
    failures = await validate_sn_lot_value(
        db,
        company_id=supplier.company_id,
        supplier_id=req.supplier_id,
        material_id=req.material_id,
        serial_lot_number=req.serial_lot_number,
        exclude_inventory_id=req.inventory_id,
    )
    return {"passed": not failures, "failures": failures}


@router.get("/policies")
async def list_inventory_policies(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    stmt = select(m.InventoryPolicy).order_by(m.InventoryPolicy.id.desc())
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.InventoryPolicy.company_id.in_(company_ids))
    rows = (await db.execute(stmt.limit(300))).scalars().all()
    return {"data": [
        {
            "id": row.id,
            "material_id": row.material_id,
            "material": await _row_label(db, m.Material, row.material_id, "sku", "name"),
            "warehouse_id": row.warehouse_id,
            "warehouse": await _row_label(db, m.Warehouse, row.warehouse_id, "name", "code") if row.warehouse_id else "全部仓库",
            "safety_stock": float(row.safety_stock or 0),
            "reorder_point": float(row.reorder_point or 0),
            "max_stock": float(row.max_stock or 0),
            "lead_time_days": row.lead_time_days or 0,
            "is_active": row.is_active,
            "notes": row.notes,
        }
        for row in rows
    ]}


@router.post("/policies")
async def upsert_inventory_policy(
    req: InventoryPolicyRequest,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    result = await _run_command(db, user, "upsert_inventory_policy", req.model_dump())
    return {"success": True, "id": result["id"]}


async def _policy_quantity(db: AsyncSession, policy: m.InventoryPolicy):
    stmt = select(
        func.coalesce(func.sum(m.Inventory.quantity), 0),
        func.coalesce(func.sum(m.Inventory.reserved_quantity), 0),
    ).where(
        m.Inventory.company_id == policy.company_id,
        m.Inventory.material_id == policy.material_id,
        m.Inventory.quantity > 0,
    )
    if policy.warehouse_id:
        stmt = stmt.where(m.Inventory.warehouse_id == policy.warehouse_id)
    qty, reserved = (await db.execute(stmt)).one()
    return _num(qty), _num(reserved)


@router.get("/alerts")
async def inventory_alerts(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    stmt = select(m.InventoryPolicy).where(m.InventoryPolicy.is_active == True).order_by(m.InventoryPolicy.id)
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.InventoryPolicy.company_id.in_(company_ids))
    policies = (await db.execute(stmt)).scalars().all()
    alerts = []
    for policy in policies:
        qty, reserved = await _policy_quantity(db, policy)
        available = qty - reserved
        status = "OK"
        level = "normal"
        if available <= 0:
            status = "OUT_OF_STOCK"
            level = "critical"
        elif policy.reorder_point and available <= _num(policy.reorder_point):
            status = "REORDER"
            level = "warning"
        elif policy.safety_stock and available <= _num(policy.safety_stock):
            status = "LOW_STOCK"
            level = "warning"
        elif policy.max_stock and _num(policy.max_stock) > 0 and available > _num(policy.max_stock):
            status = "OVERSTOCK"
            level = "info"
        if status != "OK":
            alerts.append({
                "policy_id": policy.id,
                "material_id": policy.material_id,
                "material": await _row_label(db, m.Material, policy.material_id, "sku", "name"),
                "warehouse_id": policy.warehouse_id,
                "warehouse": await _row_label(db, m.Warehouse, policy.warehouse_id, "name", "code") if policy.warehouse_id else "全部仓库",
                "quantity": float(qty),
                "reserved_quantity": float(reserved),
                "available_quantity": float(available),
                "safety_stock": float(policy.safety_stock or 0),
                "reorder_point": float(policy.reorder_point or 0),
                "max_stock": float(policy.max_stock or 0),
                "status": status,
                "level": level,
            })
    return {"data": alerts, "count": len(alerts)}


async def _stock_match_payload(
    db: AsyncSession,
    user: m.UserAccount,
    *,
    sales_order_id: int | None,
    shipment_id: int | None,
    warehouse_id: int | None,
):
    shipment = None
    if shipment_id:
        shipment = (await db.execute(select(m.ShipmentRequest).where(m.ShipmentRequest.id == shipment_id))).scalar_one_or_none()
        if not shipment:
            raise HTTPException(status_code=404, detail="发货单不存在")
        _assert_company_access(user, shipment.company_id)
        sales_order_id = shipment.sales_order_id
        warehouse_id = warehouse_id or shipment.warehouse_id
    if not sales_order_id:
        raise HTTPException(status_code=400, detail="必须提供销售订单或发货单")

    so = (await db.execute(select(m.SalesOrder).where(m.SalesOrder.id == sales_order_id))).scalar_one_or_none()
    if not so:
        raise HTTPException(status_code=404, detail="销售订单不存在")
    _assert_company_access(user, so.company_id)

    requirement_text = so.barcode_requirements or ""
    if shipment and shipment.barcode_requirements:
        requirement_text = f"{requirement_text}\n{shipment.barcode_requirements}"

    so_lines = (await db.execute(
        select(m.SalesOrderLine).where(m.SalesOrderLine.sales_order_id == so.id).order_by(m.SalesOrderLine.line_number)
    )).scalars().all()
    result_lines = []
    for line in so_lines:
        required_qty = max(_num(line.quantity) - _num(line.shipped_quantity), Decimal("0"))
        inv_stmt = select(m.Inventory).where(
            m.Inventory.company_id == so.company_id,
            m.Inventory.material_id == line.material_id,
            m.Inventory.quantity > 0,
        )
        if warehouse_id:
            inv_stmt = inv_stmt.where(m.Inventory.warehouse_id == warehouse_id)
        inv_rows = (await db.execute(
            inv_stmt.order_by(m.Inventory.received_date.asc().nulls_last(), m.Inventory.id.asc())
        )).scalars().all()

        remaining = required_qty
        allocations = []
        rejected = []
        for inv in inv_rows:
            available = await available_quantity_for_customer(db, inv, so.customer_id)
            if available <= 0:
                continue
            failures = barcode_requirement_failures(inv, requirement_text)
            if failures:
                rejected.append({
                    "inventory_id": inv.id,
                    "inbound_number": inv.inbound_number,
                    "serial_lot_number": inv.serial_lot_number,
                    "available_quantity": float(available),
                    "reason": "; ".join(failures),
                })
                continue
            take = min(available, remaining) if remaining > 0 else Decimal("0")
            candidate = {
                "inventory_id": inv.id,
                "inbound_number": inv.inbound_number,
                "batch_number": inv.batch_number,
                "serial_lot_number": inv.serial_lot_number,
                "warehouse_id": inv.warehouse_id,
                "warehouse": await _row_label(db, m.Warehouse, inv.warehouse_id, "name", "code"),
                "location_code": inv.location_code,
                "available_quantity": float(available),
                "allocated_quantity": float(take),
                "unit_cost": float(inv.unit_cost or 0),
            }
            if take > 0:
                allocations.append(candidate)
                remaining -= take
            if remaining <= 0:
                break
        result_lines.append({
            "sales_order_line_id": line.id,
            "line_number": line.line_number,
            "material_id": line.material_id,
            "material": await _row_label(db, m.Material, line.material_id, "sku", "name"),
            "required_quantity": float(required_qty),
            "allocated_quantity": float(required_qty - remaining),
            "missing_quantity": float(max(remaining, Decimal("0"))),
            "allocations": allocations,
            "rejected": rejected[:5],
        })

    return {
        "sales_order_id": so.id,
        "sales_order": so.order_number,
        "shipment_id": shipment.id if shipment else None,
        "shipment": shipment.shipment_number if shipment else "",
        "barcode_requirements": requirement_text,
        "lines": result_lines,
    }


@router.post("/stock-match")
async def stock_match(
    req: StockMatchRequest,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    return await _stock_match_payload(
        db,
        user,
        sales_order_id=req.sales_order_id,
        shipment_id=req.shipment_id,
        warehouse_id=req.warehouse_id,
    )


@router.post("/shipments/{shipment_id}/auto-allocate")
async def auto_allocate_shipment(
    shipment_id: int,
    req: AutoAllocateRequest,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    result = await _run_command(
        db,
        user,
        "auto_allocate_shipment",
        {"shipment_id": shipment_id, **req.model_dump()},
        idempotency_key=f"auto_allocate_shipment:{shipment_id}",
    )
    return {"success": True, "created": result["created"]}


@router.get("/counts")
async def list_counts(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    stmt = select(m.InventoryCount).order_by(m.InventoryCount.id.desc())
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.InventoryCount.company_id.in_(company_ids))
    rows = (await db.execute(stmt.limit(100))).scalars().all()
    data = []
    for row in rows:
        total = (await db.execute(select(func.count()).select_from(m.InventoryCountLine).where(m.InventoryCountLine.inventory_count_id == row.id))).scalar() or 0
        diff = (await db.execute(select(func.count()).select_from(m.InventoryCountLine).where(
            m.InventoryCountLine.inventory_count_id == row.id,
            m.InventoryCountLine.difference_quantity != 0,
        ))).scalar() or 0
        data.append({
            "id": row.id,
            "count_number": row.count_number,
            "warehouse_id": row.warehouse_id,
            "warehouse": await _row_label(db, m.Warehouse, row.warehouse_id, "name", "code") if row.warehouse_id else "全部仓库",
            "planned_date": row.planned_date.isoformat() if row.planned_date else "",
            "status": row.status,
            "line_count": int(total),
            "diff_count": int(diff),
            "notes": row.notes,
        })
    return {"data": data}


@router.post("/counts")
async def create_count(
    req: CountCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    result = await _run_command(db, user, "create_inventory_count", req.model_dump())
    return {
        "success": True,
        "id": result["id"],
        "count_number": result["count_number"],
        "line_count": result["line_count"],
    }


@router.get("/counts/{count_id}")
async def count_detail(
    count_id: int,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    count = (await db.execute(select(m.InventoryCount).where(m.InventoryCount.id == count_id))).scalar_one_or_none()
    if not count:
        raise HTTPException(status_code=404, detail="盘点任务不存在")
    _assert_company_access(user, count.company_id)
    lines = (await db.execute(
        select(m.InventoryCountLine).where(m.InventoryCountLine.inventory_count_id == count.id).order_by(m.InventoryCountLine.id)
    )).scalars().all()
    return {
        "id": count.id,
        "count_number": count.count_number,
        "warehouse_id": count.warehouse_id,
        "warehouse": await _row_label(db, m.Warehouse, count.warehouse_id, "name", "code") if count.warehouse_id else "全部仓库",
        "planned_date": count.planned_date.isoformat() if count.planned_date else "",
        "status": count.status,
        "notes": count.notes,
        "lines": [
            {
                "id": line.id,
                "inventory_id": line.inventory_id,
                "material": await _row_label(db, m.Material, line.material_id, "sku", "name"),
                "warehouse": await _row_label(db, m.Warehouse, line.warehouse_id, "name", "code"),
                "location_code": line.location_code,
                "inbound_number": line.inbound_number,
                "batch_number": line.batch_number,
                "serial_lot_number": line.serial_lot_number,
                "system_quantity": float(line.system_quantity or 0),
                "counted_quantity": float(line.counted_quantity) if line.counted_quantity is not None else None,
                "difference_quantity": float(line.difference_quantity or 0),
                "status": line.status,
                "notes": line.notes,
            }
            for line in lines
        ],
    }


@router.post("/counts/{count_id}/lines/{line_id}")
async def update_count_line(
    count_id: int,
    line_id: int,
    req: CountLineUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    await _run_command(
        db,
        user,
        "update_inventory_count_line",
        {"count_id": count_id, "line_id": line_id, **req.model_dump()},
    )
    return {"success": True}


@router.post("/counts/{count_id}/submit")
async def submit_count(
    count_id: int,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    await _run_command(db, user, "submit_inventory_count", {"count_id": count_id})
    return {"success": True}


@router.post("/counts/{count_id}/adjust")
async def adjust_count(
    count_id: int,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    result = await _run_command(
        db,
        user,
        "adjust_inventory_count",
        {"count_id": count_id},
        idempotency_key=f"adjust_inventory_count:{count_id}",
    )
    return {"success": True, "adjusted": result["adjusted"]}


@router.post("/counts/{count_id}/generate-adjustment")
async def generate_count_adjustment(
    count_id: int,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """盘点差异 → 生成库存调整单草稿（决策⑧：走 STOCK_ADJUSTMENT 状态机，
    财务核差异原因后 confirm→post 才调结存+推金蝶；不在此直接改库存）。"""
    result = await _run_command(
        db,
        user,
        "generate_stock_adjustment_from_count",
        {"count_id": count_id},
        idempotency_key=f"generate_stock_adjustment_from_count:{count_id}",
    )
    return {"success": True, **result}


async def _inbound_daily_rows(db: AsyncSession, user: m.UserAccount, day: date):
    stmt = (
        select(m.GoodsReceiptLine, m.GoodsReceipt)
        .join(m.GoodsReceipt, m.GoodsReceiptLine.goods_receipt_id == m.GoodsReceipt.id)
        .where(m.GoodsReceipt.received_date == day)
        .order_by(m.GoodsReceipt.receipt_number, m.GoodsReceiptLine.id)
    )
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.GoodsReceipt.company_id.in_(company_ids))
    rows = (await db.execute(stmt)).all()
    data = []
    for line, gr in rows:
        data.append({
            "receipt_number": gr.receipt_number,
            "received_date": gr.received_date.isoformat() if gr.received_date else "",
            "material": await _row_label(db, m.Material, line.material_id, "sku", "name"),
            "supplier": await _row_label(db, m.Supplier, line.supplier_id, "short_name", "name", "code"),
            "goods_nature": line.goods_nature,
            "quantity": float(line.actual_quantity or 0),
            "uom": line.uom,
            "tracking_number": line.tracking_number,
            "delivery_method": line.delivery_method,
            "source_doc_number": line.source_doc_number,
            "serial_lot_number": line.serial_lot_number,
            "inbound_number": line.inbound_number,
            "carton_number": line.carton_number,
            "origin_country": line.origin_country,
            "hs_code": line.hs_code,
            "location_code": line.location_code,
            "date_code": line.date_code,
            "production_date": line.production_date.isoformat() if line.production_date else "",
        })
    return data


async def _outbound_daily_rows(db: AsyncSession, user: m.UserAccount, day: date):
    stmt = (
        select(m.ShipmentLine, m.ShipmentRequest, m.Inventory, m.SalesOrder)
        .join(m.ShipmentRequest, m.ShipmentLine.shipment_id == m.ShipmentRequest.id)
        .join(m.Inventory, m.ShipmentLine.inventory_id == m.Inventory.id, isouter=True)
        .join(m.SalesOrder, m.ShipmentRequest.sales_order_id == m.SalesOrder.id, isouter=True)
        .where(m.ShipmentRequest.shipped_date == day)
        .order_by(m.ShipmentRequest.shipment_number, m.ShipmentLine.id)
    )
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.ShipmentRequest.company_id.in_(company_ids))
    rows = (await db.execute(stmt)).all()
    data = []
    for line, shipment, inv, so in rows:
        data.append({
            "shipment_number": shipment.shipment_number,
            "shipped_date": shipment.shipped_date.isoformat() if shipment.shipped_date else "",
            "inbound_number": line.inbound_number or (inv.inbound_number if inv else ""),
            "material": await _row_label(db, m.Material, inv.material_id if inv else None, "sku", "name"),
            "serial_lot_number": line.serial_lot_number or (inv.serial_lot_number if inv else ""),
            "supplier": await _row_label(db, m.Supplier, line.supplier_id or (inv.supplier_id if inv else None), "short_name", "name", "code"),
            "goods_nature": line.goods_nature,
            "quantity": float(line.quantity or 0),
            "uom": line.uom,
            "customer": await _row_label(db, m.Customer, so.customer_id if so else None, "short_name", "name", "code"),
            "tracking_number": line.tracking_number or shipment.tracking_number,
            "delivery_method": line.delivery_method or shipment.shipping_method,
            "invoice_number": line.invoice_number,
            "carton_number": line.carton_number,
            "origin_country": line.origin_country,
            "hs_code": line.hs_code,
        })
    return data


async def _inventory_summary_rows(db: AsyncSession, user: m.UserAccount):
    stmt = select(m.Inventory).where(m.Inventory.quantity > 0).order_by(m.Inventory.warehouse_id, m.Inventory.material_id, m.Inventory.id)
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.Inventory.company_id.in_(company_ids))
    rows = (await db.execute(stmt)).scalars().all()
    data = []
    show_cost = _can_view_inventory_cost(user)
    for inv in rows:
        available = await available_quantity_for_customer(db, inv)
        row = {
            "warehouse": await _row_label(db, m.Warehouse, inv.warehouse_id, "name", "code"),
            "location_code": inv.location_code,
            "inbound_number": inv.inbound_number,
            "material": await _row_label(db, m.Material, inv.material_id, "sku", "name"),
            "serial_lot_number": inv.serial_lot_number,
            "supplier": await _row_label(db, m.Supplier, inv.supplier_id, "short_name", "name", "code"),
            "goods_nature": inv.goods_nature,
            "quantity": float(inv.quantity or 0),
            "reserved_quantity": float(inv.reserved_quantity or 0),
            "available_quantity": float(available),
            "uom": inv.uom,
            "tracking_number": inv.tracking_number,
            "delivery_method": inv.delivery_method,
            "source_doc_number": inv.source_doc_number,
            "carton_number": inv.carton_number,
            "origin_country": inv.origin_country,
            "hs_code": inv.hs_code,
            "date_code": inv.date_code,
            "production_date": inv.production_date.isoformat() if inv.production_date else "",
            "received_date": inv.received_date.isoformat() if inv.received_date else "",
        }
        if show_cost:
            row["unit_cost"] = float(inv.unit_cost or 0)
            row["total_cost"] = float(inv.total_cost or 0)
        data.append(row)
    return data


def _summary_by(rows: list[dict], key: str) -> list[dict]:
    agg: dict[str, float] = {}
    for row in rows:
        k = row.get(key) or ""
        agg[k] = agg.get(k, 0) + float(row.get("quantity") or 0)
    return [{"group": k, "quantity": v} for k, v in sorted(agg.items())]


@router.get("/reports/inbound-daily")
async def inbound_daily_report(
    date_: str | None = Query(None, alias="date"),
    format: str = "json",
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    day = _date_or_today(date_)
    rows = await _inbound_daily_rows(db, user, day)
    if format == "csv":
        headers = [
            ("receipt_number", "进出库单号"), ("received_date", "进库日期"),
            ("material", "型号"), ("supplier", "供应商"), ("goods_nature", "性质"),
            ("quantity", "数量"), ("uom", "货物数量单位"), ("tracking_number", "运单号"),
            ("delivery_method", "送货形式"), ("source_doc_number", "PO#"),
        ]
        return _csv_response(f"inbound_daily_{day}.csv", rows, headers)
    return {"date": day.isoformat(), "summary": _summary_by(rows, "material"), "details": rows}


@router.get("/reports/outbound-daily")
async def outbound_daily_report(
    date_: str | None = Query(None, alias="date"),
    format: str = "json",
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    day = _date_or_today(date_)
    rows = await _outbound_daily_rows(db, user, day)
    if format == "csv":
        headers = [
            ("shipment_number", "出库单号"), ("shipped_date", "出库日期"),
            ("inbound_number", "入仓编号"), ("material", "型号"), ("serial_lot_number", "SN/LOT#"),
            ("supplier", "供应商"), ("goods_nature", "性质"), ("quantity", "数量"),
            ("uom", "货物数量单位"), ("customer", "客户"), ("tracking_number", "运单号"),
            ("delivery_method", "送货形式"), ("invoice_number", "INV#"), ("carton_number", "箱唛"),
        ]
        return _csv_response(f"outbound_daily_{day}.csv", rows, headers)
    return {"date": day.isoformat(), "summary": _summary_by(rows, "material"), "details": rows}


@router.get("/reports/inventory-summary")
async def inventory_summary_report(
    format: str = "json",
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    rows = await _inventory_summary_rows(db, user)
    if format == "csv":
        headers = [
            ("warehouse", "仓库"), ("location_code", "位置"), ("inbound_number", "入仓编号"),
            ("material", "型号"), ("serial_lot_number", "SN/LOT#"), ("supplier", "供应商"),
            ("goods_nature", "性质"), ("quantity", "数量"), ("reserved_quantity", "已预留数量"),
            ("available_quantity", "可用数量"),
        ]
        if _can_view_inventory_cost(user):
            headers.extend([("unit_cost", "单位成本"), ("total_cost", "库存成本")])
        headers.extend([
            ("uom", "货物数量单位"), ("tracking_number", "运单号"),
            ("delivery_method", "送货形式"), ("source_doc_number", "PO#/INV#"), ("carton_number", "箱唛"),
            ("origin_country", "原产地"), ("hs_code", "HS#"), ("date_code", "Date Code"),
            ("production_date", "生产日期"), ("received_date", "入库日期"),
        ])
        return _csv_response(f"inventory_summary_{date.today()}.csv", rows, headers)
    return {"summary": _summary_by(rows, "material"), "details": rows}


@router.get("/reports/count-sheet")
async def count_sheet_report(
    format: str = "json",
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    rows = await _inventory_summary_rows(db, user)
    count_rows = [{**r, "counted_quantity": "", "difference": "", "count_note": ""} for r in rows]
    if format == "csv":
        headers = [
            ("warehouse", "仓库"), ("location_code", "位置"), ("inbound_number", "入仓编号"),
            ("material", "型号"), ("serial_lot_number", "SN/LOT#"), ("supplier", "供应商"),
            ("quantity", "系统数量"), ("counted_quantity", "盘点数量"),
            ("difference", "差异"), ("count_note", "盘点备注"),
        ]
        return _csv_response(f"inventory_count_sheet_{date.today()}.csv", count_rows, headers)
    return {"details": count_rows}


HEADER_MAP = {
    "入仓编号": "inbound_number",
    "进出库日期": "received_date",
    "进库日期": "received_date",
    "型号": "material",
    "SN/LOT#": "serial_lot_number",
    "供应商": "supplier",
    "性质": "goods_nature",
    "数量": "quantity",
    "单位成本": "unit_cost",
    "库存成本": "total_cost",
    "货物数量单位": "uom",
    "运单号": "tracking_number",
    "送货形式": "delivery_method",
    "PO#/INV#": "source_doc_number",
    "PO#": "source_doc_number",
    "箱唛": "carton_number",
    "原产地": "origin_country",
    "HS#": "hs_code",
    "位置": "location_code",
    "Date Code": "date_code",
    "生产日期": "production_date",
    "仓库": "warehouse",
}


@router.post("/import/inventory-csv")
async def import_inventory_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    raw = await file.read()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for idx, raw_row in enumerate(reader, start=2):
        row = {HEADER_MAP.get(k, k): (v or "").strip() for k, v in raw_row.items() if k}
        row["__row_number"] = idx
        rows.append(row)
    result = await execute_command(
        db,
        user,
        "import_inventory_csv_rows",
        {"rows": rows, "file_name": file.filename or ""},
        log_payload={"file_name": file.filename or "", "row_count": len(rows)},
    )
    if not result.get("success"):
        details = result.get("details") or {}
        return {
            "success": False,
            "inserted": details.get("inserted", 0),
            "errors": details.get("errors") or [{"row": None, "error": result.get("error") or "导入失败"}],
        }
    return {"success": True, "inserted": result["inserted"]}


@router.post("/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    doc_type: str = "",
    doc_id: int | None = None,
    goods_receipt_id: int | None = None,
    goods_receipt_line_id: int | None = None,
    inventory_id: int | None = None,
    attachment_type: str = "PHOTO",
    notes: str = "",
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    upload_dir = Path(__file__).resolve().parent.parent / ".run" / "uploads" / "wms"
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix
    stored_name = f"{date.today():%Y%m%d}-{uuid.uuid4().hex}{suffix}"
    target = upload_dir / stored_name
    content = await file.read()
    target.write_bytes(content)
    result = await execute_command(
        db,
        user,
        "create_wms_attachment",
        {
            "doc_type": doc_type,
            "doc_id": doc_id,
            "goods_receipt_id": goods_receipt_id,
            "goods_receipt_line_id": goods_receipt_line_id,
            "inventory_id": inventory_id,
            "attachment_type": attachment_type,
            "file_name": file.filename or stored_name,
            "content_type": file.content_type or "",
            "file_size": len(content),
            "storage_path": str(target),
            "notes": notes,
        },
        log_payload={
            "doc_type": doc_type,
            "doc_id": doc_id,
            "goods_receipt_id": goods_receipt_id,
            "goods_receipt_line_id": goods_receipt_line_id,
            "inventory_id": inventory_id,
            "attachment_type": attachment_type,
            "file_name": file.filename or stored_name,
            "file_size": len(content),
        },
    )
    if not result.get("success"):
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=result.get("status_code", 400), detail=result.get("error") or "上传失败")
    return {"success": True, "id": result["id"], "file_name": result["file_name"]}
