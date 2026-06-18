"""总账·期末结账路由（finance-gl wave-2，模块 B）。

只装配本模块自己的端点（main.py 仅 include 本 router，不动别处）。导入 services.finance_period_close
触发 @register_command 注册（命令经 services.commands.execute_command 调度，自管事务/留痕/幂等）。

端点（全部 POST，按 _company_filter 隔离；BOSS/FINANCE/FINANCE_DIRECTOR 可用）：
  POST /api/finance/period-close/fx-revaluation   期末调汇（preview=True 只算不落库）
  POST /api/finance/period-close/carry-forward-pl 结转损益（preview=True 只算不落库）
  POST /api/finance/period-close/precheck         结账前置校验清单（= close_period preview）
  POST /api/finance/period-close/close            期末结账（前置校验通过 → 锁期 CLOSED）
  POST /api/finance/period-close/reopen           反结账（CLOSED→OPEN，逐月）

回执：成功直接返回 command result（含 voucher_id/checks/message）；失败（如前置校验未过）
返回 200 + {success:false, error, details:{checks}}，前端据 checks 高亮未过项（不吞校验明细）。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import get_db
from services.commands import execute_command
import services.finance_period_close  # noqa: F401 触发 @register_command 注册


router = APIRouter(prefix="/api/finance/period-close")

# 期末结账放行角色（与凭证过账同口径：财务/财务总监/老板）。
_CLOSE_ROLES = {"FINANCE", "FINANCE_DIRECTOR", "BOSS", "ADMIN"}


class PeriodCloseRequest(BaseModel):
    period_id: int
    preview: bool = False
    # 调汇可选入参：期末汇率表 / 旧汇率 / 直接重估本位币（任一缺省时按 ExchangeRate 兜底，差额为 0 不臆造）。
    rate_date: str | None = None
    fx_rates: dict | None = None
    old_rates: dict | None = None
    revalued_base: dict | None = None


def _require_role(user: m.UserAccount) -> None:
    if user.role not in _CLOSE_ROLES:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail=f"角色 {user.role} 无权执行期末结账操作")


async def _run(db: AsyncSession, user: m.UserAccount, command: str, payload: dict) -> dict:
    """跑命令并原样回传（含失败时的 details.checks，供前端展示前置校验明细）。"""
    result = await execute_command(db, user, command, payload)
    return result


@router.post("/fx-revaluation")
async def fx_revaluation(req: PeriodCloseRequest, db: AsyncSession = Depends(get_db),
                         user: m.UserAccount = Depends(get_current_user)):
    _require_role(user)
    return await _run(db, user, "finance.fx_revaluation", req.model_dump(exclude_none=True))


@router.post("/carry-forward-pl")
async def carry_forward_pl(req: PeriodCloseRequest, db: AsyncSession = Depends(get_db),
                           user: m.UserAccount = Depends(get_current_user)):
    _require_role(user)
    return await _run(db, user, "finance.carry_forward_pl", req.model_dump(exclude_none=True))


@router.post("/precheck")
async def precheck(req: PeriodCloseRequest, db: AsyncSession = Depends(get_db),
                   user: m.UserAccount = Depends(get_current_user)):
    _require_role(user)
    payload = {"period_id": req.period_id, "preview": True}
    return await _run(db, user, "finance.close_period", payload)


@router.post("/close")
async def close(req: PeriodCloseRequest, db: AsyncSession = Depends(get_db),
                user: m.UserAccount = Depends(get_current_user)):
    _require_role(user)
    return await _run(db, user, "finance.close_period",
                      {"period_id": req.period_id, "preview": req.preview})


@router.post("/reopen")
async def reopen(req: PeriodCloseRequest, db: AsyncSession = Depends(get_db),
                 user: m.UserAccount = Depends(get_current_user)):
    _require_role(user)
    return await _run(db, user, "finance.reopen_period", {"period_id": req.period_id})
