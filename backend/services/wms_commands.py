"""WMS commands executed through the shared command layer."""

import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter
from services.wms import (
    ACTIVE_RESERVATION,
    active_reserved_quantity,
    apply_inventory_adjustment_cost,
    available_quantity_for_customer,
    barcode_requirement_failures,
    validate_sn_lot_value,
)


def _parse_date(value: str | None):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


def _assert_same_company(left_company_id: int, right_company_id: int, message: str) -> None:
    if left_company_id != right_company_id:
        raise CommandError(message, 400)


def _movement(
    ctx: CommandContext,
    inventory: m.Inventory,
    movement_type: str,
    *,
    quantity_delta=0,
    reserved_delta=0,
    source_doc_type: str = "",
    source_doc_id: int | None = None,
    notes: str = "",
) -> None:
    ctx.db.add(m.InventoryMovement(
        company_id=inventory.company_id,
        command_log_id=ctx.command_log.id,
        movement_type=movement_type,
        material_id=inventory.material_id,
        warehouse_id=inventory.warehouse_id,
        inventory_id=inventory.id,
        quantity_delta=_num(quantity_delta),
        reserved_delta=_num(reserved_delta),
        unit_cost=inventory.unit_cost or 0,
        source_doc_type=source_doc_type,
        source_doc_id=source_doc_id,
        notes=notes,
        created_by_id=ctx.user.id,
    ))


@register_command(
    "reserve_inventory",
    module="WMS",
    title="库存预留",
    description="锁定包装级库存给客户、销售订单或发货单",
    affected_tables=("inventory", "inventory_reservation", "inventory_movement"),
)
async def reserve_inventory(ctx: CommandContext, payload: dict) -> dict:
    inventory_id = payload.get("inventory_id")
    customer_id = payload.get("customer_id")
    quantity = _num(payload.get("quantity"))

    inv = (await ctx.db.execute(
        select(m.Inventory).where(m.Inventory.id == inventory_id).with_for_update()
    )).scalar_one_or_none()
    if not inv:
        raise CommandError("库存不存在", 404)
    _assert_company_access(ctx.user, inv.company_id)
    if quantity <= 0:
        raise CommandError("预留数量必须大于 0")

    available = await available_quantity_for_customer(ctx.db, inv)
    if available < quantity:
        raise CommandError(f"可预留数量不足，当前可用 {available}")

    customer = (await ctx.db.execute(select(m.Customer).where(m.Customer.id == customer_id))).scalar_one_or_none()
    if not customer:
        raise CommandError("客户不存在", 404)
    _assert_company_access(ctx.user, customer.company_id)
    _assert_same_company(inv.company_id, customer.company_id, "库存和客户不属于同一家公司")

    sales_order_id = payload.get("sales_order_id")
    if sales_order_id:
        so = (await ctx.db.execute(select(m.SalesOrder).where(m.SalesOrder.id == sales_order_id))).scalar_one_or_none()
        if not so:
            raise CommandError("销售订单不存在", 404)
        _assert_same_company(inv.company_id, so.company_id, "库存和销售订单不属于同一家公司")
        if so.customer_id != customer_id:
            raise CommandError("销售订单客户和预留客户不一致")

    shipment_id = payload.get("shipment_id")
    if shipment_id:
        shipment = (await ctx.db.execute(select(m.ShipmentRequest).where(m.ShipmentRequest.id == shipment_id))).scalar_one_or_none()
        if not shipment:
            raise CommandError("发货单不存在", 404)
        _assert_same_company(inv.company_id, shipment.company_id, "库存和发货单不属于同一家公司")

    reservation = m.InventoryReservation(
        reservation_number=f"RSV-{date.today():%y%m%d}-{str(uuid.uuid4())[:6].upper()}",
        inventory_id=inv.id,
        customer_id=customer_id,
        sales_order_id=sales_order_id,
        shipment_id=shipment_id,
        quantity=quantity,
        reserved_by_id=ctx.user.id,
        company_id=inv.company_id,
        created_by_id=ctx.user.id,
        status=ACTIVE_RESERVATION,
        notes=payload.get("notes") or "",
    )
    ctx.db.add(reservation)
    await ctx.db.flush()

    inv.reserved_quantity = await active_reserved_quantity(ctx.db, inv.id)
    inv.status = "RESERVED" if _num(inv.reserved_quantity) >= _num(inv.quantity) else "AVAILABLE"
    _movement(
        ctx,
        inv,
        "RESERVE",
        reserved_delta=quantity,
        source_doc_type="INVENTORY_RESERVATION",
        source_doc_id=reservation.id,
        notes=f"预留给客户#{customer_id}",
    )
    ctx.add_event("inventory_reserved", {"reservation_id": reservation.id, "inventory_id": inv.id})
    return {"id": reservation.id, "reservation_number": reservation.reservation_number}


@register_command(
    "release_reservation",
    module="WMS",
    title="释放预留",
    description="释放有效库存预留并重算库存可用量",
    affected_tables=("inventory", "inventory_reservation", "inventory_movement"),
    supports_retry=True,
)
async def release_reservation(ctx: CommandContext, payload: dict) -> dict:
    reservation_id = payload.get("reservation_id")
    reservation = (await ctx.db.execute(
        select(m.InventoryReservation).where(m.InventoryReservation.id == reservation_id).with_for_update()
    )).scalar_one_or_none()
    if not reservation:
        raise CommandError("预留记录不存在", 404)
    _assert_company_access(ctx.user, reservation.company_id)
    if reservation.status != ACTIVE_RESERVATION:
        return {"message": "预留已释放"}

    released_quantity = _num(reservation.quantity)
    reservation.status = "RELEASED"
    reservation.released_at = datetime.now()
    reservation.updated_by_id = ctx.user.id
    notes = payload.get("notes") or ""
    if notes:
        reservation.notes = (reservation.notes or "") + f"\n释放备注: {notes}"

    inv = (await ctx.db.execute(
        select(m.Inventory).where(m.Inventory.id == reservation.inventory_id).with_for_update()
    )).scalar_one_or_none()
    if inv:
        await ctx.db.flush()
        inv.reserved_quantity = await active_reserved_quantity(ctx.db, inv.id)
        inv.status = "AVAILABLE" if _num(inv.reserved_quantity) <= 0 else "RESERVED"
        _movement(
            ctx,
            inv,
            "RELEASE_RESERVATION",
            reserved_delta=-released_quantity,
            source_doc_type="INVENTORY_RESERVATION",
            source_doc_id=reservation.id,
            notes="释放库存预留",
        )
    ctx.add_event("inventory_reservation_released", {"reservation_id": reservation.id})
    return {"released": True}


async def _shipment_allocations(ctx: CommandContext, shipment: m.ShipmentRequest, warehouse_id: int | None) -> list[dict]:
    so = (await ctx.db.execute(select(m.SalesOrder).where(m.SalesOrder.id == shipment.sales_order_id))).scalar_one_or_none()
    if not so:
        raise CommandError("销售订单不存在", 404)
    _assert_company_access(ctx.user, so.company_id)
    _assert_same_company(shipment.company_id, so.company_id, "发货单和销售订单不属于同一家公司")

    requirement_text = so.barcode_requirements or ""
    if shipment.barcode_requirements:
        requirement_text = f"{requirement_text}\n{shipment.barcode_requirements}"

    so_lines = (await ctx.db.execute(
        select(m.SalesOrderLine).where(m.SalesOrderLine.sales_order_id == so.id).order_by(m.SalesOrderLine.line_number)
    )).scalars().all()
    rows: list[dict] = []
    for line in so_lines:
        remaining = max(_num(line.quantity) - _num(line.shipped_quantity), Decimal("0"))
        inv_stmt = select(m.Inventory).where(
            m.Inventory.company_id == so.company_id,
            m.Inventory.material_id == line.material_id,
            m.Inventory.quantity > 0,
        )
        if warehouse_id:
            inv_stmt = inv_stmt.where(m.Inventory.warehouse_id == warehouse_id)
        inv_rows = (await ctx.db.execute(
            inv_stmt.order_by(m.Inventory.received_date.asc().nulls_last(), m.Inventory.id.asc())
        )).scalars().all()

        allocations = []
        for inv in inv_rows:
            available = await available_quantity_for_customer(ctx.db, inv, so.customer_id)
            if available <= 0 or barcode_requirement_failures(inv, requirement_text):
                continue
            take = min(available, remaining)
            if take <= 0:
                continue
            allocations.append({"inventory": inv, "quantity": take, "sales_order_line_id": line.id})
            remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            raise CommandError(f"库存不足，销售订单行#{line.id} 未配齐，缺 {remaining}")
        rows.extend(allocations)
    return rows


@register_command(
    "auto_allocate_shipment",
    module="WMS",
    title="自动分配发货库存",
    description="按销售订单需求和条码规则生成发货明细",
    affected_tables=("shipment_request", "shipment_line"),
    supports_retry=True,
)
async def auto_allocate_shipment(ctx: CommandContext, payload: dict) -> dict:
    shipment_id = payload.get("shipment_id")
    warehouse_id = payload.get("warehouse_id")
    shipment = (await ctx.db.execute(select(m.ShipmentRequest).where(m.ShipmentRequest.id == shipment_id))).scalar_one_or_none()
    if not shipment:
        raise CommandError("发货单不存在", 404)
    _assert_company_access(ctx.user, shipment.company_id)
    if warehouse_id:
        warehouse = (await ctx.db.execute(select(m.Warehouse).where(m.Warehouse.id == warehouse_id))).scalar_one_or_none()
        if not warehouse:
            raise CommandError("仓库不存在", 404)
        _assert_same_company(shipment.company_id, warehouse.company_id, "发货单和仓库不属于同一家公司")

    existing = (await ctx.db.execute(
        select(func.count()).select_from(m.ShipmentLine).where(m.ShipmentLine.shipment_id == shipment_id)
    )).scalar() or 0
    if existing:
        raise CommandError("发货单已有明细，请先人工处理后再自动分配")

    allocations = await _shipment_allocations(ctx, shipment, warehouse_id)
    created = 0
    for alloc in allocations:
        inv = alloc["inventory"]
        ctx.db.add(m.ShipmentLine(
            shipment_id=shipment.id,
            sales_order_line_id=alloc["sales_order_line_id"],
            inventory_id=inv.id,
            quantity=alloc["quantity"],
            uom=inv.uom,
            inbound_number=inv.inbound_number,
            serial_lot_number=inv.serial_lot_number,
            supplier_id=inv.supplier_id,
            goods_nature=inv.goods_nature,
            tracking_number=inv.tracking_number,
            delivery_method=inv.delivery_method,
            carton_number=inv.carton_number,
            origin_country=inv.origin_country,
            hs_code=inv.hs_code,
        ))
        created += 1
    if warehouse_id:
        shipment.warehouse_id = warehouse_id
    shipment.updated_by_id = ctx.user.id
    ctx.add_event("shipment_auto_allocated", {"shipment_id": shipment.id, "created": created})
    return {"created": created}


async def _get_or_create_supplier(ctx: CommandContext, name: str | None):
    name = (name or "").strip()
    if not name:
        return None
    stmt = select(m.Supplier).where(m.Supplier.company_id == ctx.user.company_id, m.Supplier.name == name)
    supplier = (await ctx.db.execute(stmt)).scalar_one_or_none()
    if supplier:
        return supplier
    count = (await ctx.db.execute(
        select(func.count()).select_from(m.Supplier).where(m.Supplier.company_id == ctx.user.company_id)
    )).scalar() or 0
    supplier = m.Supplier(
        company_id=ctx.user.company_id,
        created_by_id=ctx.user.id,
        code=f"SUP{count + 1:04d}",
        name=name,
        short_name=name[:50],
    )
    ctx.db.add(supplier)
    await ctx.db.flush()
    return supplier


async def _get_or_create_material(ctx: CommandContext, sku: str | None):
    sku = (sku or "").strip()
    if not sku:
        return None
    material = (await ctx.db.execute(select(m.Material).where(m.Material.sku == sku))).scalar_one_or_none()
    if material:
        return material
    material = m.Material(sku=sku, name=sku, unit="PCS")
    ctx.db.add(material)
    await ctx.db.flush()
    return material


async def _get_or_create_warehouse(ctx: CommandContext, code_or_name: str | None):
    value = (code_or_name or "MAIN").strip() or "MAIN"
    stmt = select(m.Warehouse).where(
        m.Warehouse.company_id == ctx.user.company_id,
        or_(m.Warehouse.code == value, m.Warehouse.name == value),
    )
    warehouse = (await ctx.db.execute(stmt)).scalar_one_or_none()
    if warehouse:
        return warehouse
    warehouse = m.Warehouse(
        company_id=ctx.user.company_id,
        created_by_id=ctx.user.id,
        code=value[:20],
        name=value,
    )
    ctx.db.add(warehouse)
    await ctx.db.flush()
    return warehouse


@register_command(
    "import_inventory_csv_rows",
    module="WMS",
    title="导入库存 CSV",
    description="批量导入包装级库存并生成库存成本和事实流水",
    affected_tables=("inventory", "inventory_valuation", "inventory_transaction", "inventory_movement"),
)
async def import_inventory_csv_rows(ctx: CommandContext, payload: dict) -> dict:
    inserted = 0
    errors = []
    rows = payload.get("rows") or []
    for fallback_idx, row in enumerate(rows, start=2):
        row_number = row.get("__row_number") or fallback_idx
        try:
            material = await _get_or_create_material(ctx, row.get("material"))
            supplier = await _get_or_create_supplier(ctx, row.get("supplier"))
            warehouse = await _get_or_create_warehouse(ctx, row.get("warehouse"))
            if not material:
                raise ValueError("型号不能为空")
            try:
                qty = Decimal(row.get("quantity") or "0")
            except InvalidOperation:
                raise ValueError("数量格式不正确")
            if qty <= 0:
                raise ValueError("数量必须大于 0")
            try:
                unit_cost = Decimal(row.get("unit_cost") or "0")
            except InvalidOperation:
                raise ValueError("单位成本格式不正确")
            failures = await validate_sn_lot_value(
                ctx.db,
                company_id=ctx.user.company_id,
                supplier_id=supplier.id if supplier else None,
                material_id=material.id,
                serial_lot_number=row.get("serial_lot_number"),
            )
            if failures:
                raise ValueError("; ".join(failures))
            inv = m.Inventory(
                company_id=ctx.user.company_id,
                created_by_id=ctx.user.id,
                material_id=material.id,
                supplier_id=supplier.id if supplier else None,
                warehouse_id=warehouse.id,
                batch_number=row.get("inbound_number") or row.get("serial_lot_number") or f"IMP-{row_number}",
                inbound_number=row.get("inbound_number") or f"IMP-{row_number}",
                serial_lot_number=row.get("serial_lot_number") or "",
                goods_nature=row.get("goods_nature") or "",
                quantity=qty,
                unit_cost=unit_cost,
                total_cost=qty * unit_cost,
                uom=row.get("uom") or material.unit or "PCS",
                tracking_number=row.get("tracking_number") or "",
                delivery_method=row.get("delivery_method") or "",
                source_doc_number=row.get("source_doc_number") or "",
                carton_number=row.get("carton_number") or "",
                origin_country=row.get("origin_country") or "",
                hs_code=row.get("hs_code") or "",
                location_code=row.get("location_code") or "",
                date_code=row.get("date_code") or "",
                production_date=_parse_date(row.get("production_date")),
                received_date=_parse_date(row.get("received_date")) or date.today(),
                status="AVAILABLE",
            )
            ctx.db.add(inv)
            await ctx.db.flush()
            await apply_inventory_adjustment_cost(
                ctx.db,
                inv,
                quantity_delta=qty,
                tx_date=inv.received_date or date.today(),
                reference_type="INVENTORY_IMPORT",
                reference_id=inv.id,
            )
            _movement(
                ctx,
                inv,
                "INVENTORY_IMPORT",
                quantity_delta=qty,
                source_doc_type="INVENTORY_IMPORT",
                source_doc_id=inv.id,
                notes=payload.get("file_name") or "",
            )
            inserted += 1
        except Exception as e:
            errors.append({"row": row_number, "error": str(e)})
    if errors:
        raise CommandError("导入失败", details={"inserted": 0, "errors": errors[:100]})
    ctx.add_event("inventory_csv_imported", {"inserted": inserted})
    return {"inserted": inserted}


@register_command(
    "print_inbound_labels",
    module="WMS",
    title="打印入仓编号标签",
    description="按选中批次行一键生成 62×29mm 入仓编号标签 payload（主文本+条码=inbound_number，真实打印留占位）",
    affected_tables=("label_template", "goods_receipt_line"),
)
async def print_inbound_labels(ctx: CommandContext, payload: dict) -> dict:
    """一键打标签（PRD 03a-6）：对选中批次行（goods_receipt_line）生成入仓编号标签 payload。

    payload: {goods_receipt_id?, line_ids?[]} —— 给单则取整单全部明细，给 line_ids 则只取选中行。
    复用 INTERNAL 标签模板（62×29mm，主文本+一维条码=inbound_number）。真实打印走 print_driver 占位。
    """
    from services.template_render import build_label_payload

    gr_id = payload.get("goods_receipt_id")
    line_ids = payload.get("line_ids") or []
    stmt = select(m.GoodsReceiptLine)
    if line_ids:
        stmt = stmt.where(m.GoodsReceiptLine.id.in_(line_ids))
    elif gr_id:
        stmt = stmt.where(m.GoodsReceiptLine.goods_receipt_id == gr_id)
    else:
        raise CommandError("需提供 goods_receipt_id 或 line_ids")
    lines = (await ctx.db.execute(stmt.order_by(m.GoodsReceiptLine.id))).scalars().all()
    if not lines:
        raise CommandError("无可打印的批次行", 404)

    # 定位 INTERNAL 入仓编号标签模板（本公司）。
    template = (await ctx.db.execute(
        select(m.LabelTemplate).where(
            m.LabelTemplate.company_id == ctx.user.company_id,
            m.LabelTemplate.label_type == "INTERNAL",
            m.LabelTemplate.is_active == True,
        ).order_by(m.LabelTemplate.id).limit(1)
    )).scalar_one_or_none()
    if not template:
        raise CommandError("未配置 INTERNAL 入仓编号标签模板", 404)

    labels = []
    for line in lines:
        result = await build_label_payload(ctx, {
            "template_id": template.id,
            "doc_type": "goods_receipt_line",
            "doc_id": line.id,
        })
        labels.append({
            "line_id": line.id,
            "inbound_number": line.inbound_number,
            "payload": result,
        })
    ctx.add_event("inbound_labels_printed", {"template_id": template.id, "count": len(labels)})
    return {"template_id": template.id, "size_mm": template.size_mm, "count": len(labels), "labels": labels}


@register_command(
    "create_wms_attachment",
    module="WMS",
    title="创建 WMS 附件",
    description="保存入库、库存或单据附件元数据",
    affected_tables=("wms_attachment",),
)
async def create_wms_attachment(ctx: CommandContext, payload: dict) -> dict:
    company_id = ctx.user.company_id
    inventory_id = payload.get("inventory_id")
    goods_receipt_id = payload.get("goods_receipt_id")
    goods_receipt_line_id = payload.get("goods_receipt_line_id")
    if inventory_id:
        inv = (await ctx.db.execute(select(m.Inventory).where(m.Inventory.id == inventory_id))).scalar_one_or_none()
        if not inv:
            raise CommandError("库存不存在", 404)
        _assert_company_access(ctx.user, inv.company_id)
        company_id = inv.company_id
    elif goods_receipt_id:
        receipt = (await ctx.db.execute(select(m.GoodsReceipt).where(m.GoodsReceipt.id == goods_receipt_id))).scalar_one_or_none()
        if not receipt:
            raise CommandError("入库单不存在", 404)
        _assert_company_access(ctx.user, receipt.company_id)
        company_id = receipt.company_id
    elif goods_receipt_line_id:
        line = (await ctx.db.execute(
            select(m.GoodsReceiptLine).where(m.GoodsReceiptLine.id == goods_receipt_line_id)
        )).scalar_one_or_none()
        if not line:
            raise CommandError("入库单明细不存在", 404)
        receipt = (await ctx.db.execute(
            select(m.GoodsReceipt).where(m.GoodsReceipt.id == line.goods_receipt_id)
        )).scalar_one_or_none()
        if not receipt:
            raise CommandError("入库单不存在", 404)
        _assert_company_access(ctx.user, receipt.company_id)
        company_id = receipt.company_id

    attachment = m.WmsAttachment(
        company_id=company_id,
        created_by_id=ctx.user.id,
        uploaded_by_id=ctx.user.id,
        doc_type=payload.get("doc_type") or "",
        doc_id=payload.get("doc_id"),
        goods_receipt_id=goods_receipt_id,
        goods_receipt_line_id=goods_receipt_line_id,
        inventory_id=inventory_id,
        attachment_type=payload.get("attachment_type") or "PHOTO",
        file_name=payload.get("file_name") or "",
        content_type=payload.get("content_type") or "",
        file_size=payload.get("file_size") or 0,
        storage_path=payload.get("storage_path") or "",
        notes=payload.get("notes") or "",
    )
    ctx.db.add(attachment)
    await ctx.db.flush()
    ctx.add_event("wms_attachment_created", {"attachment_id": attachment.id})
    return {"id": attachment.id, "file_name": attachment.file_name}


@register_command(
    "upsert_supplier_sn_rule",
    module="WMS",
    title="保存 SN/LOT 规则",
    description="新增或更新供应商物料条码校验规则",
    affected_tables=("supplier_sn_rule",),
)
async def upsert_supplier_sn_rule(ctx: CommandContext, payload: dict) -> dict:
    supplier_id = payload.get("supplier_id")
    supplier = (await ctx.db.execute(select(m.Supplier).where(m.Supplier.id == supplier_id))).scalar_one_or_none()
    if not supplier:
        raise CommandError("供应商不存在", 404)
    _assert_company_access(ctx.user, supplier.company_id)

    material_id = payload.get("material_id")
    if material_id:
        material = (await ctx.db.execute(select(m.Material).where(m.Material.id == material_id))).scalar_one_or_none()
        if not material:
            raise CommandError("物料不存在", 404)

    rule_id = payload.get("id")
    if rule_id:
        rule = (await ctx.db.execute(select(m.SupplierSnRule).where(m.SupplierSnRule.id == rule_id))).scalar_one_or_none()
        if not rule:
            raise CommandError("规则不存在", 404)
        _assert_company_access(ctx.user, rule.company_id)
        _assert_same_company(rule.company_id, supplier.company_id, "规则和供应商不属于同一家公司")
    else:
        rule = m.SupplierSnRule(company_id=supplier.company_id, created_by_id=ctx.user.id)
        ctx.db.add(rule)

    for field in (
        "supplier_id", "material_id", "rule_name", "exact_length", "min_length",
        "max_length", "pattern", "allow_duplicate", "unique_scope", "is_active", "notes",
    ):
        setattr(rule, field, payload.get(field))
    rule.updated_by_id = ctx.user.id
    await ctx.db.flush()
    ctx.add_event("supplier_sn_rule_upserted", {"rule_id": rule.id})
    return {"id": rule.id}


@register_command(
    "upsert_inventory_policy",
    module="WMS",
    title="保存库存策略",
    description="新增或更新物料仓库维度的库存预警策略",
    affected_tables=("inventory_policy",),
)
async def upsert_inventory_policy(ctx: CommandContext, payload: dict) -> dict:
    material_id = payload.get("material_id")
    material = (await ctx.db.execute(select(m.Material).where(m.Material.id == material_id))).scalar_one_or_none()
    if not material:
        raise CommandError("物料不存在", 404)

    warehouse_id = payload.get("warehouse_id")
    if warehouse_id:
        warehouse = (await ctx.db.execute(select(m.Warehouse).where(m.Warehouse.id == warehouse_id))).scalar_one_or_none()
        if not warehouse:
            raise CommandError("仓库不存在", 404)
        _assert_company_access(ctx.user, warehouse.company_id)
        company_id = warehouse.company_id
    else:
        company_id = ctx.user.company_id
    _assert_company_access(ctx.user, company_id)

    policy_id = payload.get("id")
    if policy_id:
        policy = (await ctx.db.execute(select(m.InventoryPolicy).where(m.InventoryPolicy.id == policy_id))).scalar_one_or_none()
        if not policy:
            raise CommandError("库存策略不存在", 404)
        _assert_company_access(ctx.user, policy.company_id)
    else:
        policy = (await ctx.db.execute(select(m.InventoryPolicy).where(
            m.InventoryPolicy.company_id == company_id,
            m.InventoryPolicy.material_id == material_id,
            m.InventoryPolicy.warehouse_id == warehouse_id,
        ))).scalar_one_or_none()
        if not policy:
            policy = m.InventoryPolicy(company_id=company_id, created_by_id=ctx.user.id)
            ctx.db.add(policy)

    for field in (
        "material_id", "warehouse_id", "safety_stock", "reorder_point",
        "max_stock", "lead_time_days", "is_active", "notes",
    ):
        setattr(policy, field, payload.get(field))
    policy.company_id = company_id
    policy.updated_by_id = ctx.user.id
    await ctx.db.flush()
    ctx.add_event("inventory_policy_upserted", {"policy_id": policy.id})
    return {"id": policy.id}


@register_command(
    "create_inventory_count",
    module="WMS",
    title="创建盘点任务",
    description="按仓库范围生成盘点任务和盘点明细快照",
    affected_tables=("inventory_count", "inventory_count_line"),
)
async def create_inventory_count(ctx: CommandContext, payload: dict) -> dict:
    warehouse_id = payload.get("warehouse_id")
    warehouse = None
    if warehouse_id:
        warehouse = (await ctx.db.execute(select(m.Warehouse).where(m.Warehouse.id == warehouse_id))).scalar_one_or_none()
        if not warehouse:
            raise CommandError("仓库不存在", 404)
        _assert_company_access(ctx.user, warehouse.company_id)

    company_id = warehouse.company_id if warehouse else ctx.user.company_id
    _assert_company_access(ctx.user, company_id)
    inv_stmt = select(m.Inventory).where(m.Inventory.company_id == company_id, m.Inventory.quantity > 0)
    if warehouse_id:
        inv_stmt = inv_stmt.where(m.Inventory.warehouse_id == warehouse_id)
    invs = (await ctx.db.execute(
        inv_stmt.order_by(m.Inventory.warehouse_id, m.Inventory.location_code, m.Inventory.id)
    )).scalars().all()
    if not invs:
        raise CommandError("当前范围没有可盘点库存")

    count = m.InventoryCount(
        company_id=company_id,
        created_by_id=ctx.user.id,
        count_number=f"CNT-{date.today():%y%m%d}-{str(uuid.uuid4())[:6].upper()}",
        warehouse_id=warehouse_id,
        planned_date=_parse_date(payload.get("planned_date")) or date.today(),
        counted_by_id=ctx.user.id,
        status="DRAFT",
        notes=payload.get("notes") or "",
    )
    ctx.db.add(count)
    await ctx.db.flush()
    for inv in invs:
        ctx.db.add(m.InventoryCountLine(
            inventory_count_id=count.id,
            inventory_id=inv.id,
            material_id=inv.material_id,
            warehouse_id=inv.warehouse_id,
            location_code=inv.location_code,
            batch_number=inv.batch_number,
            inbound_number=inv.inbound_number,
            serial_lot_number=inv.serial_lot_number,
            system_quantity=inv.quantity,
            counted_quantity=None,
            difference_quantity=0,
            status="PENDING",
        ))
    ctx.add_event("inventory_count_created", {"count_id": count.id, "line_count": len(invs)})
    return {"id": count.id, "count_number": count.count_number, "line_count": len(invs)}


@register_command(
    "update_inventory_count_line",
    module="WMS",
    title="更新盘点明细",
    description="录入盘点数量并计算差异",
    affected_tables=("inventory_count_line",),
)
async def update_inventory_count_line(ctx: CommandContext, payload: dict) -> dict:
    count_id = payload.get("count_id")
    line_id = payload.get("line_id")
    count = (await ctx.db.execute(select(m.InventoryCount).where(m.InventoryCount.id == count_id))).scalar_one_or_none()
    if not count:
        raise CommandError("盘点任务不存在", 404)
    _assert_company_access(ctx.user, count.company_id)
    if count.status not in {"DRAFT", "IN_PROGRESS"}:
        raise CommandError("当前盘点状态不能录入")

    line = (await ctx.db.execute(select(m.InventoryCountLine).where(
        m.InventoryCountLine.id == line_id,
        m.InventoryCountLine.inventory_count_id == count_id,
    ))).scalar_one_or_none()
    if not line:
        raise CommandError("盘点明细不存在", 404)

    counted_quantity = _num(payload.get("counted_quantity"))
    if counted_quantity < 0:
        raise CommandError("盘点数量不能小于 0")
    line.counted_quantity = counted_quantity
    line.difference_quantity = counted_quantity - _num(line.system_quantity)
    line.status = "MATCH" if line.difference_quantity == 0 else "DIFF"
    line.notes = payload.get("notes") or ""
    count.status = "IN_PROGRESS"
    count.updated_by_id = ctx.user.id
    ctx.add_event("inventory_count_line_updated", {"count_id": count.id, "line_id": line.id})
    return {"line_id": line.id, "difference_quantity": line.difference_quantity}


@register_command(
    "submit_inventory_count",
    module="WMS",
    title="提交盘点任务",
    description="校验盘点明细完整性并提交盘点任务",
    affected_tables=("inventory_count",),
)
async def submit_inventory_count(ctx: CommandContext, payload: dict) -> dict:
    count_id = payload.get("count_id")
    count = (await ctx.db.execute(select(m.InventoryCount).where(m.InventoryCount.id == count_id))).scalar_one_or_none()
    if not count:
        raise CommandError("盘点任务不存在", 404)
    _assert_company_access(ctx.user, count.company_id)

    pending = (await ctx.db.execute(select(func.count()).select_from(m.InventoryCountLine).where(
        m.InventoryCountLine.inventory_count_id == count_id,
        m.InventoryCountLine.counted_quantity.is_(None),
    ))).scalar() or 0
    if pending:
        raise CommandError(f"还有 {pending} 行未录入盘点数量")

    count.status = "SUBMITTED"
    count.submitted_at = datetime.now()
    count.updated_by_id = ctx.user.id
    ctx.add_event("inventory_count_submitted", {"count_id": count.id})
    return {"submitted": True}


@register_command(
    "adjust_inventory_count",
    module="WMS",
    title="盘点调整库存",
    description="按盘点差异调整库存、成本和事实流水",
    affected_tables=("inventory", "inventory_count", "inventory_count_line", "inventory_valuation", "inventory_transaction", "inventory_movement"),
    supports_retry=True,
)
async def adjust_inventory_count(ctx: CommandContext, payload: dict) -> dict:
    count_id = payload.get("count_id")
    count = (await ctx.db.execute(select(m.InventoryCount).where(m.InventoryCount.id == count_id))).scalar_one_or_none()
    if not count:
        raise CommandError("盘点任务不存在", 404)
    _assert_company_access(ctx.user, count.company_id)
    if count.status != "SUBMITTED":
        raise CommandError("只有已提交盘点可以调整库存")

    lines = (await ctx.db.execute(
        select(m.InventoryCountLine).where(m.InventoryCountLine.inventory_count_id == count_id)
    )).scalars().all()
    adjusted = 0
    for line in lines:
        if line.counted_quantity is None or _num(line.difference_quantity) == 0:
            continue
        inv = (await ctx.db.execute(
            select(m.Inventory).where(m.Inventory.id == line.inventory_id).with_for_update()
        )).scalar_one_or_none()
        if not inv:
            continue
        _assert_same_company(count.company_id, inv.company_id, "盘点任务和库存不属于同一家公司")
        diff = _num(line.difference_quantity)
        inv.quantity = line.counted_quantity
        if _num(inv.reserved_quantity) > _num(inv.quantity):
            inv.reserved_quantity = inv.quantity
        inv.status = "AVAILABLE" if _num(inv.quantity) > _num(inv.reserved_quantity) else "RESERVED"
        await apply_inventory_adjustment_cost(
            ctx.db,
            inv,
            quantity_delta=diff,
            tx_date=date.today(),
            reference_type="INVENTORY_COUNT_LINE",
            reference_id=line.id,
        )
        _movement(
            ctx,
            inv,
            "COUNT_ADJUST",
            quantity_delta=diff,
            source_doc_type="INVENTORY_COUNT_LINE",
            source_doc_id=line.id,
            notes=f"盘点调整 {count.count_number}",
        )
        line.status = "ADJUSTED"
        adjusted += 1
    count.status = "ADJUSTED"
    count.adjusted_at = datetime.now()
    count.adjusted_by_id = ctx.user.id
    count.updated_by_id = ctx.user.id
    ctx.add_event("inventory_count_adjusted", {"count_id": count.id, "adjusted": adjusted})
    return {"adjusted": adjusted}
