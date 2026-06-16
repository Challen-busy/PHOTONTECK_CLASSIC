"""WMS domain helpers: reservations, SN/LOT validation and shipment checks."""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m


ACTIVE_RESERVATION = "ACTIVE"


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def barcode_requirement_failures(inventory: m.Inventory, requirement_text: str | None) -> list[str]:
    """用销售/发货的条码要求文本做基础匹配。

    这里先实现不依赖打印设备的可执行校验：要求里出现关键字段时，
    候选库存必须有对应库存字段，后续二期可把模板解析做得更细。
    """
    text = (requirement_text or "").lower()
    if not text:
        return []
    failures: list[str] = []
    checks = [
        (("sn", "s/n", "serial", "lot"), inventory.serial_lot_number, "SN/LOT#"),
        (("date code", "datecode", " d/c", "dc", "生产日期"), inventory.date_code or inventory.production_date, "Date Code/生产日期"),
        (("carton", "箱", "箱唛"), inventory.carton_number, "箱唛/箱号"),
        (("origin", "原产地"), inventory.origin_country, "原产地"),
        (("hs", "海关编码"), inventory.hs_code, "HS#"),
    ]
    for keys, value, label in checks:
        if any(key in text for key in keys) and not value:
            failures.append(f"缺少{label}")
    return failures


async def _period_id_for_date(db: AsyncSession, company_id: int, tx_date: date) -> int | None:
    stmt = (
        select(m.AccountingPeriod.id)
        .join(m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id)
        .where(
            m.FiscalYear.company_id == company_id,
            m.AccountingPeriod.start_date <= tx_date,
            m.AccountingPeriod.end_date >= tx_date,
        )
        .order_by((m.AccountingPeriod.status == "OPEN").desc(), m.AccountingPeriod.id.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _transaction_exists(db: AsyncSession, reference_type: str, reference_id: int) -> bool:
    stmt = select(func.count()).select_from(m.InventoryTransaction).where(
        m.InventoryTransaction.reference_type == reference_type,
        m.InventoryTransaction.reference_id == reference_id,
    )
    return bool((await db.execute(stmt)).scalar() or 0)


def _add_inventory_movement(
    db: AsyncSession,
    *,
    company_id: int,
    movement_type: str,
    material_id: int,
    warehouse_id: int | None,
    inventory_id: int | None,
    quantity_delta: Decimal,
    unit_cost: Decimal,
    source_doc_type: str,
    source_doc_id: int,
    command_log_id: int | None = None,
    created_by_id: int | None = None,
    notes: str = "",
) -> None:
    db.add(m.InventoryMovement(
        company_id=company_id,
        command_log_id=command_log_id,
        movement_type=movement_type,
        material_id=material_id,
        warehouse_id=warehouse_id,
        inventory_id=inventory_id,
        quantity_delta=quantity_delta,
        reserved_delta=0,
        unit_cost=unit_cost,
        source_doc_type=source_doc_type,
        source_doc_id=source_doc_id,
        notes=notes,
        created_by_id=created_by_id,
    ))


async def _valuation_row(db: AsyncSession, company_id: int, material_id: int) -> m.InventoryValuation:
    stmt = select(m.InventoryValuation).where(
        m.InventoryValuation.company_id == company_id,
        m.InventoryValuation.material_id == material_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row:
        return row
    row = m.InventoryValuation(
        company_id=company_id,
        material_id=material_id,
        cost_method="WEIGHTED_AVG",
        current_unit_cost=0,
        total_quantity=0,
        total_value=0,
    )
    db.add(row)
    await db.flush()
    return row


async def _apply_valuation_delta(
    db: AsyncSession,
    *,
    company_id: int,
    material_id: int,
    warehouse_id: int | None,
    quantity_delta: Decimal,
    value_delta: Decimal,
    tx_date: date,
    transaction_type: str,
    reference_type: str,
    reference_id: int,
) -> None:
    valuation = await _valuation_row(db, company_id, material_id)
    new_qty = _num(valuation.total_quantity) + quantity_delta
    new_value = _num(valuation.total_value) + value_delta
    if new_qty < 0:
        new_qty = Decimal("0")
    if new_value < 0:
        new_value = Decimal("0")
    valuation.total_quantity = new_qty
    valuation.total_value = new_value
    valuation.current_unit_cost = new_value / new_qty if new_qty else Decimal("0")

    period_id = await _period_id_for_date(db, company_id, tx_date)
    if period_id:
        qty_abs = abs(quantity_delta)
        value_abs = abs(value_delta)
        db.add(m.InventoryTransaction(
            company_id=company_id,
            material_id=material_id,
            warehouse_id=warehouse_id,
            transaction_type=transaction_type,
            transaction_date=tx_date,
            quantity=qty_abs,
            unit_cost=(value_abs / qty_abs) if qty_abs else Decimal("0"),
            total_cost=value_abs,
            reference_type=reference_type,
            reference_id=reference_id,
            period_id=period_id,
            status="START",
        ))


async def apply_goods_receipt_costs(
    db: AsyncSession,
    doc: m.GoodsReceipt,
    *,
    command_log_id: int | None = None,
    created_by_id: int | None = None,
) -> list[str]:
    """入库审核后：按采购订单行写入库存成本和加权平均成本。"""
    rows = (await db.execute(
        select(m.GoodsReceiptLine).where(m.GoodsReceiptLine.goods_receipt_id == doc.id)
    )).scalars().all()
    logs: list[str] = []
    for line in rows:
        if await _transaction_exists(db, "GOODS_RECEIPT_LINE", line.id):
            continue
        pol = (await db.execute(
            select(m.PurchaseOrderLine).where(m.PurchaseOrderLine.id == line.purchase_order_line_id)
        )).scalar_one_or_none()
        qty = _num(line.actual_quantity)
        unit_cost = _num(pol.unit_price if pol else 0)
        total_cost = qty * unit_cost

        inv_stmt = select(m.Inventory).where(
            m.Inventory.company_id == doc.company_id,
            m.Inventory.material_id == line.material_id,
            m.Inventory.purchase_order_line_id == line.purchase_order_line_id,
            m.Inventory.inbound_number == (line.inbound_number or doc.receipt_number),
        )
        if line.batch_number:
            inv_stmt = inv_stmt.where(m.Inventory.batch_number == line.batch_number)
        if line.serial_lot_number:
            inv_stmt = inv_stmt.where(m.Inventory.serial_lot_number == line.serial_lot_number)
        inv = (await db.execute(inv_stmt.order_by(m.Inventory.id.desc()).limit(1))).scalar_one_or_none()
        if inv:
            inv.unit_cost = unit_cost
            inv.total_cost = _num(inv.quantity) * unit_cost

        await _apply_valuation_delta(
            db,
            company_id=doc.company_id,
            material_id=line.material_id,
            warehouse_id=doc.warehouse_id,
            quantity_delta=qty,
            value_delta=total_cost,
            tx_date=doc.received_date or date.today(),
            transaction_type="IN",
            reference_type="GOODS_RECEIPT_LINE",
            reference_id=line.id,
        )
        _add_inventory_movement(
            db,
            company_id=doc.company_id,
            command_log_id=command_log_id,
            movement_type="GOODS_RECEIPT_IN",
            material_id=line.material_id,
            warehouse_id=doc.warehouse_id,
            inventory_id=inv.id if inv else None,
            quantity_delta=qty,
            unit_cost=unit_cost,
            source_doc_type="GOODS_RECEIPT_LINE",
            source_doc_id=line.id,
            created_by_id=created_by_id,
            notes=f"入库单 {doc.receipt_number}",
        )
        logs.append(f"入库成本更新: GR line {line.id} qty={qty} unit={unit_cost}")
    return logs


async def apply_shipment_costs(
    db: AsyncSession,
    doc: m.ShipmentRequest,
    *,
    command_log_id: int | None = None,
    created_by_id: int | None = None,
) -> list[str]:
    """出库确认后：按库存批次成本结转库存价值和销售发票成本。"""
    rows = (await db.execute(
        select(m.ShipmentLine).where(m.ShipmentLine.shipment_id == doc.id)
    )).scalars().all()
    logs: list[str] = []
    for line in rows:
        if await _transaction_exists(db, "SHIPMENT_LINE", line.id):
            continue
        inv = None
        if line.inventory_id:
            inv = (await db.execute(select(m.Inventory).where(m.Inventory.id == line.inventory_id))).scalar_one_or_none()
        if not inv:
            continue
        valuation = await _valuation_row(db, inv.company_id, inv.material_id)
        unit_cost = _num(inv.unit_cost) or _num(valuation.current_unit_cost)
        # 出库数量负数口径，结转/扣值取 abs（PRD 03b 第7点）。
        qty = abs(_num(line.quantity))
        total_cost = qty * unit_cost
        inv.unit_cost = unit_cost
        inv.total_cost = _num(inv.quantity) * unit_cost

        await _apply_valuation_delta(
            db,
            company_id=inv.company_id,
            material_id=inv.material_id,
            warehouse_id=inv.warehouse_id,
            quantity_delta=-qty,
            value_delta=-total_cost,
            tx_date=doc.shipped_date or date.today(),
            transaction_type="OUT",
            reference_type="SHIPMENT_LINE",
            reference_id=line.id,
        )
        _add_inventory_movement(
            db,
            company_id=inv.company_id,
            command_log_id=command_log_id,
            movement_type="SHIPMENT_OUT",
            material_id=inv.material_id,
            warehouse_id=inv.warehouse_id,
            inventory_id=inv.id,
            quantity_delta=-qty,
            unit_cost=unit_cost,
            source_doc_type="SHIPMENT_LINE",
            source_doc_id=line.id,
            created_by_id=created_by_id,
            notes=f"发货单 {doc.shipment_number}",
        )

        invoice_lines = (await db.execute(
            select(m.SalesInvoiceLine).where(m.SalesInvoiceLine.shipment_line_id == line.id)
        )).scalars().all()
        for invoice_line in invoice_lines:
            invoice_line.cost_amount = total_cost
        logs.append(f"出库成本更新: shipment line {line.id} qty={qty} unit={unit_cost}")
    return logs


async def apply_inventory_adjustment_cost(
    db: AsyncSession,
    inventory: m.Inventory,
    *,
    quantity_delta: Decimal,
    tx_date: date,
    reference_type: str,
    reference_id: int,
) -> None:
    """盘点/调整后同步库存价值和库存流水。"""
    valuation = await _valuation_row(db, inventory.company_id, inventory.material_id)
    unit_cost = _num(inventory.unit_cost) or _num(valuation.current_unit_cost)
    inventory.unit_cost = unit_cost
    inventory.total_cost = _num(inventory.quantity) * unit_cost
    value_delta = quantity_delta * unit_cost
    await _apply_valuation_delta(
        db,
        company_id=inventory.company_id,
        material_id=inventory.material_id,
        warehouse_id=inventory.warehouse_id,
        quantity_delta=quantity_delta,
        value_delta=value_delta,
        tx_date=tx_date,
        transaction_type="ADJUST",
        reference_type=reference_type,
        reference_id=reference_id,
    )


async def active_reserved_quantity(
    db: AsyncSession,
    inventory_id: int,
    *,
    customer_id: int | None = None,
    exclude_customer_id: int | None = None,
) -> Decimal:
    stmt = select(func.coalesce(func.sum(m.InventoryReservation.quantity), 0)).where(
        m.InventoryReservation.inventory_id == inventory_id,
        m.InventoryReservation.status == ACTIVE_RESERVATION,
    )
    if customer_id is not None:
        stmt = stmt.where(m.InventoryReservation.customer_id == customer_id)
    if exclude_customer_id is not None:
        stmt = stmt.where(m.InventoryReservation.customer_id != exclude_customer_id)
    return _num((await db.execute(stmt)).scalar())


async def available_quantity_for_customer(
    db: AsyncSession,
    inventory: m.Inventory,
    customer_id: int | None = None,
) -> Decimal:
    """库存对指定客户的可出数量。

    其他客户预留会占用库存；同客户预留允许出库。
    """
    quantity = _num(inventory.quantity)
    if customer_id is None:
        reserved = await active_reserved_quantity(db, inventory.id)
    else:
        reserved = await active_reserved_quantity(db, inventory.id, exclude_customer_id=customer_id)
    return quantity - reserved


async def validate_sn_lot_value(
    db: AsyncSession,
    *,
    company_id: int,
    supplier_id: int | None,
    material_id: int | None,
    serial_lot_number: str | None,
    exclude_inventory_id: int | None = None,
) -> list[str]:
    """按供应商 SN/LOT 规则校验一个值。"""
    value = (serial_lot_number or "").strip()
    if not supplier_id:
        return []

    stmt = select(m.SupplierSnRule).where(
        m.SupplierSnRule.company_id == company_id,
        m.SupplierSnRule.supplier_id == supplier_id,
        m.SupplierSnRule.is_active == True,
        or_(m.SupplierSnRule.material_id == None, m.SupplierSnRule.material_id == material_id),
    )
    rules = (await db.execute(stmt)).scalars().all()
    if not rules:
        return []

    failures: list[str] = []
    for rule in rules:
        label = rule.rule_name or f"供应商#{supplier_id} SN/LOT规则"
        if not value:
            failures.append(f"{label}: SN/LOT# 不能为空")
            continue
        if rule.exact_length and len(value) != int(rule.exact_length):
            failures.append(f"{label}: SN/LOT# 必须为 {rule.exact_length} 位，当前 {len(value)} 位")
        if rule.min_length and len(value) < int(rule.min_length):
            failures.append(f"{label}: SN/LOT# 至少 {rule.min_length} 位")
        if rule.max_length and len(value) > int(rule.max_length):
            failures.append(f"{label}: SN/LOT# 最多 {rule.max_length} 位")
        if rule.pattern:
            try:
                if not re.fullmatch(rule.pattern, value):
                    failures.append(f"{label}: SN/LOT# 不符合格式 {rule.pattern}")
            except re.error:
                failures.append(f"{label}: 正则规则无效 {rule.pattern}")

        if not rule.allow_duplicate:
            dup_stmt = select(func.count()).select_from(m.Inventory).where(
                m.Inventory.company_id == company_id,
                m.Inventory.serial_lot_number == value,
            )
            scope = rule.unique_scope or "SUPPLIER_MATERIAL"
            if scope in ("SUPPLIER", "SUPPLIER_MATERIAL"):
                dup_stmt = dup_stmt.where(m.Inventory.supplier_id == supplier_id)
            if scope in ("MATERIAL", "SUPPLIER_MATERIAL"):
                dup_stmt = dup_stmt.where(m.Inventory.material_id == material_id)
            if exclude_inventory_id:
                dup_stmt = dup_stmt.where(m.Inventory.id != exclude_inventory_id)
            dup_count = (await db.execute(dup_stmt)).scalar() or 0
            if dup_count:
                failures.append(f"{label}: SN/LOT# {value} 已存在，不允许重复")

    return failures


async def validate_goods_receipt_constraints(db: AsyncSession, doc: m.GoodsReceipt) -> list[str]:
    """入库单保存/审核时的 WMS 校验（PRD 03a-1 状态机 hard_rules）。

    硬规则：① 明细 Σactual_quantity = 头部应收总数（Σexpected_quantity）—— 数量对得上才放行；
    ② 每行 SN/LOT# 非空；③ 每行性质 goods_nature 非空；④ SN/LOT 唯一 + 按 supplier_sn_rule 校验。
    """
    result = await db.execute(
        select(m.GoodsReceiptLine).where(m.GoodsReceiptLine.goods_receipt_id == doc.id)
    )
    lines = result.scalars().all()
    failures: list[str] = []
    seen: set[tuple[int | None, int | None, str]] = set()

    if not lines:
        failures.append("入库单: 至少需要一条批次明细")

    total_expected = Decimal("0")
    total_actual = Decimal("0")
    for line in lines:
        total_expected += _num(line.expected_quantity)
        total_actual += _num(line.actual_quantity)

        if not (line.serial_lot_number or "").strip():
            failures.append(f"入库明细#{line.id}: SN/LOT# 不能为空")
        if not (line.goods_nature or "").strip():
            failures.append(f"入库明细#{line.id}: 货物性质不能为空")

        sn = (line.serial_lot_number or "").strip()
        if sn:
            key = (line.supplier_id, line.material_id, sn)
            if key in seen:
                failures.append(f"入库明细#{line.id}: 同一入库单内 SN/LOT# {sn} 重复")
            seen.add(key)
        failures.extend(
            f"入库明细#{line.id}: {msg}"
            for msg in await validate_sn_lot_value(
                db,
                company_id=doc.company_id,
                supplier_id=line.supplier_id,
                material_id=line.material_id,
                serial_lot_number=line.serial_lot_number,
            )
        )

    if lines and total_actual != total_expected:
        failures.append(
            f"入库单: 明细实收总数 {total_actual} 与应收总数 {total_expected} 不一致（须按 PO 核对/拆行）"
        )
    return failures


async def validate_shipment_constraints(db: AsyncSession, doc: m.ShipmentRequest) -> list[str]:
    """出库单保存/确认时的库存、预留、串货隔离校验。

    串货隔离（蓝图 §5.2，PRD 03b 页面2 hard_rule）：每行批次的原厂报备客户
    必须 ∈ {本单客户, 空}，否则阻断并指名批次（"报备给客户 A 的货不能出给客户 B"）。
    数量口径：出庫登記显示负数，校验/扣结存按 abs() 取绝对值（PRD 03b 第7点）。
    委外发料（outbound_type=OUTSOURCE）无销售订单/客户，跳过串货与客户预留校验，只验结存。
    """
    failures: list[str] = []
    customer_id = None
    is_outsource = (doc.outbound_type or "CUSTOMER") == "OUTSOURCE"
    barcode_requirements = doc.barcode_requirements or ""
    if doc.sales_order_id:
        so = (await db.execute(select(m.SalesOrder).where(m.SalesOrder.id == doc.sales_order_id))).scalar_one_or_none()
        customer_id = so.customer_id if so else None
        if so and so.barcode_requirements:
            barcode_requirements = f"{barcode_requirements}\n{so.barcode_requirements}"

    result = await db.execute(
        select(m.ShipmentLine).where(m.ShipmentLine.shipment_id == doc.id)
    )
    lines = result.scalars().all()

    for line in lines:
        inv = None
        if line.inventory_id:
            inv = (await db.execute(select(m.Inventory).where(m.Inventory.id == line.inventory_id))).scalar_one_or_none()
        if not inv:
            failures.append(f"发货明细#{line.id}: 库存批次不存在")
            continue
        qty = abs(_num(line.quantity))
        if qty <= 0:
            failures.append(f"发货明细#{line.id}: 出库数量不能为 0")
            continue
        if _num(inv.quantity) < qty:
            failures.append(f"发货明细#{line.id}: 库存 {inv.inbound_number or inv.batch_number} 数量不足")
            continue

        # 串货隔离：批次原厂报备客户 ∈ {本单客户, 空}，否则阻断（委外发料无客户，跳过）。
        if not is_outsource and customer_id and inv.reported_customer_id and inv.reported_customer_id != customer_id:
            failures.append(
                f"发货明细#{line.id}: 库存 {inv.inbound_number or inv.batch_number} "
                f"为原厂报备客户#{inv.reported_customer_id} 专属，不能出给本单客户#{customer_id}（串货隔离）"
            )
            continue

        if not is_outsource and customer_id:
            other_reserved = await active_reserved_quantity(db, inv.id, exclude_customer_id=customer_id)
            if other_reserved > 0:
                failures.append(
                    f"发货明细#{line.id}: 库存 {inv.inbound_number or inv.batch_number} "
                    f"已被其他客户预留 {other_reserved}，不能直接出库"
                )
                continue
        available = await available_quantity_for_customer(db, inv, customer_id)
        if available < qty:
            failures.append(
                f"发货明细#{line.id}: 库存 {inv.inbound_number or inv.batch_number} "
                f"可出数量 {available} 小于本次出库 {qty}"
            )
        barcode_failures = barcode_requirement_failures(inv, barcode_requirements)
        if barcode_failures:
            failures.append(
                f"发货明细#{line.id}: 库存 {inv.inbound_number or inv.batch_number} "
                f"不满足条码要求：{'; '.join(barcode_failures)}"
            )
    return failures


def shipped_date_after_cutoff_failures(doc: m.ShipmentRequest) -> list[str]:
    """出库日期「27 号后算下月 1 号」校验（PRD 03b 页面2 第8点、访谈 05 L1168-1192）。

    盘点截止日 = 每月 27 号；shipped_date 在 27 号之后（28~月末）须校正为下月 1 号。
    只判定不改写（引擎 04 §4：validator 只读），由前端/制单按提示改日期。
    """
    sd = doc.shipped_date
    if not sd:
        return []
    if sd.day <= 27:
        return []
    if sd.month == 12:
        expected = date(sd.year + 1, 1, 1)
    else:
        expected = date(sd.year, sd.month + 1, 1)
    return [
        f"出库日期 {sd.isoformat()} 在盘点截止 27 号之后，按规则应算下月 1 号（{expected.isoformat()}）"
    ]

