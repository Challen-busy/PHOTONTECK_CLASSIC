"""杂项路由：预警/页面模板"""

from pathlib import Path

from fastapi import APIRouter, Depends

import models as m
from core.auth import get_current_user
from services.alerts import run_all_alerts

router = APIRouter()


@router.get("/api/alerts")
async def alerts_check(user: m.UserAccount = Depends(get_current_user)):
    return await run_all_alerts()


@router.get("/api/templates/{name}")
async def get_template(name: str):
    path = Path(__file__).resolve().parent.parent / "templates" / f"{name}.html"
    if not path.exists():
        return {"html": ""}
    return {"html": path.read_text(encoding="utf-8")}
