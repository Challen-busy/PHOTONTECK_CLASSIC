"""Unified command executor for cross-module writes."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.command_context import CommandContext
from services.command_registry import get_command_handler


class CommandError(Exception):
    def __init__(self, message: str, status_code: int = 400, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


async def _failed_result(
    db: AsyncSession,
    actor_id: int,
    company_id: int | None,
    command_name: str,
    log_payload: dict,
    message: str,
    status_code: int,
    idempotency_key: str | None,
    details: dict | None = None,
) -> dict:
    failed = m.CommandLog(
        command_name=command_name,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        company_id=company_id,
        status="FAILED",
        request_payload=_json_safe(log_payload),
        result_payload=_json_safe(details or {}),
        error_message=message,
        completed_at=datetime.now(),
    )
    db.add(failed)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
    result = {"success": False, "command": command_name, "error": message, "status_code": status_code}
    if details:
        result["details"] = _json_safe(details)
    return result


async def _idempotency_result(db: AsyncSession, command_name: str, idempotency_key: str) -> dict | None:
    result = await db.execute(
        select(m.CommandLog)
        .where(
            m.CommandLog.command_name == command_name,
            m.CommandLog.idempotency_key == idempotency_key,
            m.CommandLog.status.in_(("SUCCESS", "RUNNING")),
        )
        .order_by(m.CommandLog.created_at.desc(), m.CommandLog.id.desc())
        .limit(10)
    )
    logs = result.scalars().all()
    success = next((row for row in logs if row.status == "SUCCESS"), None)
    if success:
        stored = success.result_payload or {}
        return {**stored, "idempotent": True, "command_log_id": success.id}

    running = next((row for row in logs if row.status == "RUNNING"), None)
    if running:
        return {
            "success": False,
            "command": command_name,
            "error": "相同幂等键的命令正在执行",
            "status_code": 409,
            "command_log_id": running.id,
        }
    return None


async def execute_command(
    db: AsyncSession,
    user: m.UserAccount,
    command_name: str,
    payload: dict | None = None,
    *,
    idempotency_key: str | None = None,
    log_payload: dict | None = None,
) -> dict:
    payload = payload or {}
    stored_payload = log_payload if log_payload is not None else payload
    actor_id = user.id
    company_id = getattr(user, "company_id", None)
    handler = get_command_handler(command_name)
    if not handler:
        return {"success": False, "command": command_name, "error": f"未注册命令: {command_name}", "status_code": 400}

    if idempotency_key:
        existing = await _idempotency_result(db, command_name, idempotency_key)
        if existing:
            return existing

    log = m.CommandLog(
        command_name=command_name,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        company_id=company_id,
        status="RUNNING",
        request_payload=_json_safe(stored_payload),
    )
    db.add(log)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        if idempotency_key:
            existing = await _idempotency_result(db, command_name, idempotency_key)
            if existing:
                return existing
        return await _failed_result(
            db,
            actor_id,
            company_id,
            command_name,
            stored_payload,
            "命令日志创建失败",
            409,
            idempotency_key,
        )

    ctx = CommandContext(db=db, user=user, command_log=log)
    try:
        result = await handler(ctx, payload)
        result = result or {}
        result.setdefault("success", True)
        result.setdefault("command", command_name)
        result.setdefault("events", ctx.events)
        result.setdefault("logs", ctx.logs)
        result["command_log_id"] = log.id

        log.status = "SUCCESS"
        log.result_payload = _json_safe(result)
        log.completed_at = datetime.now()
        await db.commit()
        return result
    except CommandError as e:
        await db.rollback()
        return await _failed_result(
            db,
            actor_id,
            company_id,
            command_name,
            stored_payload,
            e.message,
            e.status_code,
            idempotency_key,
            e.details,
        )
    except Exception as e:
        await db.rollback()
        return await _failed_result(
            db, actor_id, company_id, command_name, stored_payload, str(e), 500, idempotency_key
        )
