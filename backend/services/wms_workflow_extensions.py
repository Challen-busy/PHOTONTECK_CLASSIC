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
    to_state="SALES_OUTBOUND",
)
async def validate_shipment(
    db: AsyncSession,
    doc_type: str,
    doc,
    to_state: str | None,
    user: m.UserAccount,
) -> list[str]:
    return await wms.validate_shipment_constraints(db, doc)


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
