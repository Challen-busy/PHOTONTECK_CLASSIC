"""数据路由：查询/聚合/schema/关联探索"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import Base, get_db
from services.labels import get_label, get_table_label
from services.tools import (
    TABLE_MAP, TOOLS, _company_filter, _serialize_row,
    BUY_TABLES, SELL_TABLES, BUY_PRICE_FIELDS, SELL_PRICE_FIELDS,
    _can_view_buy_price, _can_view_sell_price,
)

router = APIRouter()


class QueryRequest(BaseModel):
    table: str
    filters: dict = {}
    search: str = ""
    order_by: str = "id"
    limit: int = 20


@router.post("/api/query")
async def query(req: QueryRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    return await TOOLS["query_data"]["function"](db, user, req.model_dump())


class AggregateRequest(BaseModel):
    table: str
    field: str
    function: str = "COUNT"
    filters: dict = {}
    group_by: str = ""


@router.post("/api/aggregate")
async def agg(req: AggregateRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    return await TOOLS["aggregate"]["function"](db, user, req.model_dump())


@router.get("/api/schema/{table_name}")
async def get_schema(table_name: str, user: m.UserAccount = Depends(get_current_user)):
    model = TABLE_MAP.get(table_name)
    if not model:
        raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")

    fields = []
    for col in model.__table__.columns:
        # 价格防火墙：与 _serialize_row 保持一致
        if table_name in BUY_TABLES and col.name in BUY_PRICE_FIELDS and not _can_view_buy_price(user):
            continue
        if table_name in SELL_TABLES and col.name in SELL_PRICE_FIELDS and not _can_view_sell_price(user):
            continue
        field_type = str(col.type)
        if "INT" in field_type.upper(): type_name = "integer"
        elif "NUMERIC" in field_type.upper() or "FLOAT" in field_type.upper() or "DECIMAL" in field_type.upper():
            type_name = "number"
        elif "DATE" in field_type.upper() and "TIME" in field_type.upper(): type_name = "datetime"
        elif "DATE" in field_type.upper(): type_name = "date"
        elif "BOOL" in field_type.upper(): type_name = "boolean"
        elif "JSON" in field_type.upper(): type_name = "json"
        elif "TEXT" in field_type.upper(): type_name = "text"
        else: type_name = "string"

        fk_target = None
        if col.foreign_keys:
            fk = list(col.foreign_keys)[0]
            fk_target = {"table": fk.column.table.name, "column": fk.column.name}

        fields.append({
            "name": col.name,
            "label": get_label(table_name, col.name),
            "type": type_name,
            "nullable": col.nullable,
            "primary_key": col.primary_key,
            "fk": fk_target,
            "has_default": col.default is not None or col.server_default is not None,
        })

    sub_tables = []
    for t_name, t_model in TABLE_MAP.items():
        if t_name == table_name:
            continue
        for col in t_model.__table__.columns:
            if col.foreign_keys:
                fk = list(col.foreign_keys)[0]
                if fk.column.table.name == table_name:
                    if any(x in t_name for x in ["_line", "_entry"]):
                        sub_tables.append({
                            "table": t_name,
                            "table_label": get_table_label(t_name),
                            "parent_fk": col.name,
                        })
                    break

    return {
        "table": table_name,
        "table_label": get_table_label(table_name),
        "fields": fields,
        "sub_tables": sub_tables,
    }


SKIP_FK_FIELDS = {"created_by_id", "updated_by_id", "company_id"}
SUBTABLE_HINTS = ("_line", "_entry")


@router.get("/api/related/{table_name}/{doc_id}")
async def get_related(table_name: str, doc_id: int, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    """自动探索一张单据的关联数据 forward / reverse"""
    model = TABLE_MAP.get(table_name)
    if not model:
        return {"error": "表不存在"}
    r = await db.execute(select(model).where(model.id == doc_id))
    doc = r.scalar_one_or_none()
    if not doc:
        return {"error": "单据不存在"}

    forward = []
    for col in model.__table__.columns:
        if col.name in SKIP_FK_FIELDS or not col.foreign_keys:
            continue
        fk_val = getattr(doc, col.name, None)
        if fk_val is None:
            continue
        fk = list(col.foreign_keys)[0]
        target_table = fk.column.table.name
        target_model = TABLE_MAP.get(target_table)
        if not target_model:
            continue
        rr = await db.execute(select(target_model).where(target_model.id == fk_val))
        target_row = rr.scalar_one_or_none()
        if not target_row:
            continue
        try:
            row_data = _serialize_row(target_row, target_table, user)
        except Exception:
            continue
        forward.append({
            "field": col.name,
            "target_table": target_table,
            "target_table_label": get_table_label(target_table),
            "labels": {c.name: get_label(target_table, c.name) for c in target_model.__table__.columns},
            "row": row_data,
        })

    reverse = []
    for sub_name, sub_model in TABLE_MAP.items():
        if sub_name == table_name:
            continue
        for col in sub_model.__table__.columns:
            if not col.foreign_keys:
                continue
            fk = list(col.foreign_keys)[0]
            if fk.column.table.name != table_name:
                continue
            if any(h in sub_name for h in SUBTABLE_HINTS):
                break
            stmt = select(sub_model).where(getattr(sub_model, col.name) == doc_id)
            company_ids = _company_filter(user)
            if company_ids and hasattr(sub_model, "company_id"):
                stmt = stmt.where(sub_model.company_id.in_(company_ids))
            rr = await db.execute(stmt.limit(5))
            samples = []
            for row in rr.scalars().all():
                try:
                    samples.append(_serialize_row(row, sub_name, user))
                except Exception:
                    continue
            count_stmt = select(func.count()).select_from(sub_model).where(getattr(sub_model, col.name) == doc_id)
            if company_ids and hasattr(sub_model, "company_id"):
                count_stmt = count_stmt.where(sub_model.company_id.in_(company_ids))
            total = (await db.execute(count_stmt)).scalar()
            if total > 0 or samples:
                sub_labels = {c.name: get_label(sub_name, c.name) for c in sub_model.__table__.columns}
                resolved = {}
                for sc in sub_model.__table__.columns:
                    if sc.name in SKIP_FK_FIELDS or sc.name == col.name or not sc.foreign_keys:
                        continue
                    target = list(sc.foreign_keys)[0].column.table.name
                    target_m = TABLE_MAP.get(target)
                    if not target_m:
                        continue
                    ids = {s[sc.name] for s in samples if s.get(sc.name) is not None}
                    if not ids:
                        continue
                    rr2 = await db.execute(select(target_m).where(target_m.id.in_(ids)))
                    id_to_label = {}
                    for row in rr2.scalars().all():
                        for f in ("name", "full_name", "short_name", "code", "sku", "order_number",
                                  "voucher_number", "invoice_number", "batch_number"):
                            v = getattr(row, f, None)
                            if v:
                                id_to_label[row.id] = v
                                break
                        else:
                            id_to_label[row.id] = f"#{row.id}"
                    resolved[sc.name] = id_to_label
                reverse.append({
                    "table": sub_name,
                    "table_label": get_table_label(sub_name),
                    "fk_field": col.name,
                    "count": total,
                    "samples": samples,
                    "labels": sub_labels,
                    "fk_resolved": resolved,
                })
            break

    return {"forward": forward, "reverse": reverse}
