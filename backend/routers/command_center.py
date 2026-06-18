"""统一命令中心：跨 ERP/WMS/CRM 查看命令执行和事实流水。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import get_db
from pydantic import BaseModel, Field
from services.command_registry import get_command_handler, get_command_metadata, list_command_metadata
from services.commands import execute_command
from services.tools import _company_filter


router = APIRouter(prefix="/api/commands")

# 财务前端（凭证工作台 / 期末 / 模板调用）统一命令入口。
# 安全：仅放行 finance.* 命令 + 财务角色门；命令内部仍走 execute_transition + validator（职责分离/借贷平衡/期间锁），
# 不绕唯一写入边界。其它模块命令不从此通用口暴露（各有专用路由）。
_UI_COMMAND_PREFIXES = ("finance.",)
_FINANCE_COMMAND_ROLES = {"FINANCE", "FINANCE_DIRECTOR", "BOSS", "ADMIN"}


class CommandExecuteIn(BaseModel):
    command: str
    payload: dict = Field(default_factory=dict)
    idempotency_key: str | None = None


@router.post("/execute")
async def execute_command_endpoint(
    body: CommandExecuteIn,
    user: m.UserAccount = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    name = body.command
    if not any(name.startswith(p) for p in _UI_COMMAND_PREFIXES):
        raise HTTPException(status_code=403, detail=f"命令 {name} 不允许从通用命令入口调用")
    if get_command_handler(name) is None:
        raise HTTPException(status_code=404, detail=f"未注册命令: {name}")
    if user.role not in _FINANCE_COMMAND_ROLES:
        raise HTTPException(status_code=403, detail=f"角色 {user.role} 无权执行财务命令")
    return await execute_command(db, user, name, body.payload, idempotency_key=body.idempotency_key)


REDACTED_KEYS = {
    "password",
    "password_hash",
    "token",
    "secret",
    "api_key",
    "storage_path",
    "content",
    "raw",
}


def _company_ids(user: m.UserAccount):
    return _company_filter(user)


def _can_view_inventory_cost(user: m.UserAccount) -> bool:
    return user.role in {"BOSS", "OPERATIONS", "FINANCE", "PRODUCT_ASSISTANT", "PRODUCT_MANAGER"}


def _parse_dt(value: str | None):
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        try:
            return datetime.fromisoformat(text[:10])
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式不正确")


def _redact_payload(value, depth: int = 0):
    if depth >= 5:
        return "..."
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if any(part in str(key).lower() for part in REDACTED_KEYS):
                result[key] = "***"
            else:
                result[key] = _redact_payload(item, depth + 1)
        return result
    if isinstance(value, list):
        rows = [_redact_payload(item, depth + 1) for item in value[:50]]
        if len(value) > 50:
            rows.append(f"... {len(value) - 50} more")
        return rows
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "..."
    return value


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


async def _command_row(db: AsyncSession, row: m.CommandLog) -> dict:
    meta = get_command_metadata(row.command_name).as_dict()
    return {
        "id": row.id,
        "command_name": row.command_name,
        "command_title": meta["title"],
        "command_module": meta["module"],
        "command_description": meta["description"],
        "affected_tables": meta["affected_tables"],
        "supports_retry": meta["supports_retry"],
        "supports_rollback": meta["supports_rollback"],
        "supports_preview": meta["supports_preview"],
        "idempotency_key": row.idempotency_key,
        "status": row.status,
        "actor_id": row.actor_id,
        "actor": await _row_label(db, m.UserAccount, row.actor_id, "full_name", "username"),
        "company_id": row.company_id,
        "company": await _row_label(db, m.Company, row.company_id, "short_name", "name", "code"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "error_message": row.error_message,
    }


def _assert_command_access(user: m.UserAccount, row: m.CommandLog) -> None:
    company_ids = _company_ids(user)
    if company_ids and row.company_id not in company_ids:
        raise HTTPException(status_code=403, detail="无权访问该公司数据")


@router.get("/catalog")
async def command_catalog(user: m.UserAccount = Depends(get_current_user)):
    return {"data": list_command_metadata()}


@router.get("/failures/summary")
async def failure_summary(
    command_module: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(1000, le=5000),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    stmt = (
        select(m.CommandLog)
        .where(m.CommandLog.status == "FAILED")
        .order_by(m.CommandLog.created_at.desc(), m.CommandLog.id.desc())
        .limit(limit)
    )
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.CommandLog.company_id.in_(company_ids))
    start = _parse_dt(date_from)
    end = _parse_dt(date_to)
    if start:
        stmt = stmt.where(m.CommandLog.created_at >= start)
    if end:
        stmt = stmt.where(m.CommandLog.created_at <= end)

    rows = (await db.execute(stmt)).scalars().all()
    summary: dict[tuple[str, str], dict] = {}
    for row in rows:
        meta = get_command_metadata(row.command_name).as_dict()
        if command_module and meta["module"] != command_module:
            continue
        key = (meta["module"], row.command_name)
        item = summary.setdefault(key, {
            "command_module": meta["module"],
            "command_name": row.command_name,
            "command_title": meta["title"],
            "supports_retry": meta["supports_retry"],
            "failed_count": 0,
            "last_failed_at": None,
            "last_error_message": "",
            "last_command_log_id": None,
        })
        item["failed_count"] += 1
        if not item["last_failed_at"] or (row.created_at and row.created_at.isoformat() > item["last_failed_at"]):
            item["last_failed_at"] = row.created_at.isoformat() if row.created_at else None
            item["last_error_message"] = row.error_message
            item["last_command_log_id"] = row.id
    data = sorted(summary.values(), key=lambda item: (item["failed_count"], item["last_failed_at"] or ""), reverse=True)
    return {"data": data, "count": len(data)}


@router.get("/logs")
async def command_logs(
    command_name: str = "",
    command_module: str = "",
    status: str = "",
    actor_id: int | None = None,
    company_id: int | None = None,
    idempotency_key: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(100, le=300),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    stmt = select(m.CommandLog).order_by(m.CommandLog.created_at.desc(), m.CommandLog.id.desc())
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.CommandLog.company_id.in_(company_ids))
    if company_id:
        if company_ids and company_id not in company_ids:
            raise HTTPException(status_code=403, detail="无权访问该公司数据")
        stmt = stmt.where(m.CommandLog.company_id == company_id)
    if command_name:
        stmt = stmt.where(m.CommandLog.command_name.ilike(f"%{command_name}%"))
    if command_module:
        names = [
            item["name"]
            for item in list_command_metadata()
            if item["module"] == command_module
        ]
        if not names:
            return {"data": [], "count": 0}
        stmt = stmt.where(m.CommandLog.command_name.in_(names))
    if status:
        stmt = stmt.where(m.CommandLog.status == status)
    if actor_id:
        stmt = stmt.where(m.CommandLog.actor_id == actor_id)
    if idempotency_key:
        stmt = stmt.where(m.CommandLog.idempotency_key.ilike(f"%{idempotency_key}%"))
    start = _parse_dt(date_from)
    end = _parse_dt(date_to)
    if start:
        stmt = stmt.where(m.CommandLog.created_at >= start)
    if end:
        stmt = stmt.where(m.CommandLog.created_at <= end)

    rows = (await db.execute(stmt.limit(limit))).scalars().all()
    return {"data": [await _command_row(db, row) for row in rows], "count": len(rows)}


@router.get("/logs/{command_log_id}")
async def command_detail(
    command_log_id: int,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    row = (await db.execute(select(m.CommandLog).where(m.CommandLog.id == command_log_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="命令日志不存在")
    _assert_command_access(user, row)
    data = await _command_row(db, row)
    data["request_payload"] = _redact_payload(row.request_payload or {})
    data["result_payload"] = _redact_payload(row.result_payload or {})
    return data


@router.post("/logs/{command_log_id}/retry")
async def retry_command(
    command_log_id: int,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    row = (await db.execute(select(m.CommandLog).where(m.CommandLog.id == command_log_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="命令日志不存在")
    _assert_command_access(user, row)
    if row.status != "FAILED":
        raise HTTPException(status_code=400, detail="只有失败命令可以重试")
    meta = get_command_metadata(row.command_name)
    if not meta.supports_retry:
        raise HTTPException(status_code=400, detail="该命令未开放重试")
    payload = row.request_payload or {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="原命令载荷不可重试")

    result = await execute_command(
        db,
        user,
        row.command_name,
        payload,
        idempotency_key=row.idempotency_key,
    )
    result["retried_from_id"] = command_log_id
    return result


@router.get("/logs/{command_log_id}/inventory-movements")
async def command_inventory_movements(
    command_log_id: int,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    command = (await db.execute(select(m.CommandLog).where(m.CommandLog.id == command_log_id))).scalar_one_or_none()
    if not command:
        raise HTTPException(status_code=404, detail="命令日志不存在")
    _assert_command_access(user, command)

    stmt = (
        select(m.InventoryMovement)
        .where(m.InventoryMovement.command_log_id == command_log_id)
        .order_by(m.InventoryMovement.created_at.desc(), m.InventoryMovement.id.desc())
    )
    company_ids = _company_ids(user)
    if company_ids:
        stmt = stmt.where(m.InventoryMovement.company_id.in_(company_ids))
    rows = (await db.execute(stmt.limit(500))).scalars().all()
    show_cost = _can_view_inventory_cost(user)
    data = []
    for row in rows:
        inv = (await db.execute(select(m.Inventory).where(m.Inventory.id == row.inventory_id))).scalar_one_or_none() if row.inventory_id else None
        item = {
            "id": row.id,
            "command_log_id": row.command_log_id,
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
