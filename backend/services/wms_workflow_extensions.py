"""WMS workflow validators and effects registered with the generic engine."""

from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services import wms
from services.workflow_extensions import (
    register_transition_effect,
    register_transition_validator,
)


@register_transition_validator(
    "wms.validate_goods_receipt",
    doc_type="GOODS_RECEIPT",
    to_state="PA_REVIEW",
)
@register_transition_validator(
    "wms.validate_goods_receipt",
    doc_type="GOODS_RECEIPT",
    to_state="STOCKED_IN",
)
async def validate_goods_receipt(
    db: AsyncSession,
    doc_type: str,
    doc,
    to_state: str | None,
    user: m.UserAccount,
) -> list[str]:
    return await wms.validate_goods_receipt_constraints(db, doc)


@register_transition_validator(
    "wms.validate_shipment",
    doc_type="SHIPMENT",
    to_state="PICKING_RECHECK",
)
@register_transition_validator(
    "wms.validate_shipment",
    doc_type="SHIPMENT",
    to_state="SALES_OUTBOUND",
)
async def validate_shipment(
    db: AsyncSession,
    doc_type: str,
    doc,
    to_state: str | None,
    user: m.UserAccount,
) -> list[str]:
    # 库存/预留/串货隔离校验：进互检（PICKING_RECHECK）与出库（SALES_OUTBOUND）两关均跑。
    return await wms.validate_shipment_constraints(db, doc)


@register_transition_validator(
    "wms.validate_shipment_outbound_date",
    doc_type="SHIPMENT",
    to_state="SALES_OUTBOUND",
)
async def validate_shipment_outbound_date(
    db: AsyncSession,
    doc_type: str,
    doc,
    to_state: str | None,
    user: m.UserAccount,
) -> list[str]:
    # 出库日期「27 号后算下月 1 号」（PRD 03b 页面2 第8点）。
    return wms.shipped_date_after_cutoff_failures(doc)


@register_transition_effect(
    "wms.apply_goods_receipt_costs",
    doc_type="GOODS_RECEIPT",
    to_state="STOCKED_IN",
)
async def apply_goods_receipt_costs(
    db: AsyncSession,
    doc_type: str,
    doc,
    to_state: str | None,
    user: m.UserAccount,
    command_log_id: int | None,
) -> list[str]:
    return await wms.apply_goods_receipt_costs(
        db,
        doc,
        command_log_id=command_log_id,
        created_by_id=user.id,
    )


@register_transition_effect(
    "wms.apply_shipment_costs",
    doc_type="SHIPMENT",
    to_state="SALES_OUTBOUND",
)
async def apply_shipment_costs(
    db: AsyncSession,
    doc_type: str,
    doc,
    to_state: str | None,
    user: m.UserAccount,
    command_log_id: int | None,
) -> list[str]:
    return await wms.apply_shipment_costs(
        db,
        doc,
        command_log_id=command_log_id,
        created_by_id=user.id,
    )
