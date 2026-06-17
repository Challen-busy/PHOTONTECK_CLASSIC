"""并行会签标准件（段0b·2，05 §3）—— 可复用，不动引擎核心。

用现有积木拼出「多人全签才过」：
  1. 子表 cosign_line：挂在要会签的单据上，按关卡 required_roles 预生成 N 行待签。
  2. 「我签字」= 自循环编辑动作（execute_transition 编辑模式，editable_fields 限 cosign_line
     自己那行）—— 每个签票方往自己那行填 decision=AGREE/REJECT + comment。并行任意顺序。
  3. 「集齐放行」= 推进动作挂校验器（@register_transition_validator 工厂）：
     放行条件 = 所有 required_role 行 decision='AGREE'；任一 'REJECT' → 校验失败打回；
     未集齐 → 失败留在会签态。

对照引擎原生：节点 allowed_roles 语义是「任一角色可推进」；本件用「子表攒票 + 集齐校验」
升级成「全签才过」，纯业务层组合，**不改 execute_transition、不给引擎加会签原生语义**
（开发铁律：引擎不认业务术语）。

复用方式（认证审核 / 备货 ≥20 万会审 / 任何会签关卡）：
  register_cosign_checkpoint(doc_type=..., trigger_state=..., required_roles=[...], cosign_group=...)
一次声明即生成一个 @register_transition_validator，进会签态预生成签字行用 generate_cosign_lines()。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter
from services.workflow_extensions import register_transition_validator

AGREE = "AGREE"
REJECT = "REJECT"
PENDING = "PENDING"


async def generate_cosign_lines(
    db: AsyncSession,
    *,
    doc_type: str,
    doc_id: int,
    company_id: int,
    required_roles: list[str],
    cosign_group: str = "DEFAULT",
    created_by_id: int | None = None,
) -> list[int]:
    """进入会签态时预生成待签行（每个 required_role 一行）。幂等：已存在的角色行跳过。

    供「提交进入会签态」的 effect 或命令调用。返回新建行 id 列表。
    """
    existing = (await db.execute(
        select(m.CosignLine.required_role).where(
            m.CosignLine.doc_type == doc_type,
            m.CosignLine.doc_id == doc_id,
            m.CosignLine.cosign_group == cosign_group,
        )
    )).scalars().all()
    have = set(existing)
    created: list[int] = []
    for role in required_roles:
        if role in have:
            continue
        line = m.CosignLine(
            company_id=company_id,
            doc_type=doc_type,
            doc_id=doc_id,
            cosign_group=cosign_group,
            required_role=role,
            decision=PENDING,
            created_by_id=created_by_id,
        )
        db.add(line)
        await db.flush()
        created.append(line.id)
    return created


async def sign_cosign_line(
    db: AsyncSession,
    *,
    line_id: int,
    user: m.UserAccount,
    decision: str,
    comment: str = "",
) -> m.CosignLine:
    """「我签字」落库：签票方填自己那行。

    自循环编辑动作的服务实现（也可直接走 execute_transition 编辑模式改 cosign_line 子表）。
    角色校验：ADMIN/BOSS 豁免外，签票人角色须等于该行 required_role。
    """
    line = (await db.execute(
        select(m.CosignLine).where(m.CosignLine.id == line_id).with_for_update()
    )).scalar_one_or_none()
    if not line:
        raise ValueError("会签行不存在")
    decision = (decision or "").upper()
    if decision not in (AGREE, REJECT):
        raise ValueError("decision 必须是 AGREE 或 REJECT")
    if user.role not in ("ADMIN", "BOSS") and user.role != line.required_role:
        raise ValueError(f"角色 {user.role} 无权签 {line.required_role} 那一行")
    line.decision = decision
    line.signed_by_id = user.id
    line.comment = comment or ""
    line.signed_at = datetime.now()
    line.updated_by_id = user.id
    return line


async def cosign_failures(
    db: AsyncSession,
    *,
    doc_type: str,
    doc_id: int,
    required_roles: list[str],
    cosign_group: str = "DEFAULT",
) -> list[str]:
    """集齐校验（纯只读判定，返回失败原因列表，空=放行）。

    放行条件 = 每个 required_role 都有一行 decision=AGREE。
    任一 REJECT → 一票否决；缺角色行或仍 PENDING → 未集齐。
    """
    lines = (await db.execute(
        select(m.CosignLine).where(
            m.CosignLine.doc_type == doc_type,
            m.CosignLine.doc_id == doc_id,
            m.CosignLine.cosign_group == cosign_group,
        )
    )).scalars().all()
    by_role = {ln.required_role: ln for ln in lines}
    failures: list[str] = []
    rejected = [ln.required_role for ln in lines if ln.decision == REJECT]
    if rejected:
        failures.append(f"会签被驳回（{', '.join(rejected)}），打回整改")
        return failures
    missing = [r for r in required_roles if r not in by_role]
    if missing:
        failures.append(f"会签角色未就位: {', '.join(missing)}")
    pending = [r for r in required_roles if r in by_role and by_role[r].decision != AGREE]
    if pending:
        failures.append(f"会签未集齐同意，待签: {', '.join(pending)}")
    return failures


def register_cosign_checkpoint(
    *,
    doc_type: str,
    trigger_state: str,
    required_roles: list[str],
    cosign_group: str = "DEFAULT",
    name: str | None = None,
) -> None:
    """会签关卡工厂：声明一个「集齐放行」校验器并注册到引擎扩展点。

    引擎在推进到 trigger_state（通过态）前自动跑该校验器（auto=True，匹配 doc_type+to_state）；
    集齐 AGREE 才放行，否则 execute_transition 返回「领域校验未通过」。

    复用：每个会签关卡（认证审核→APPROVED、备货 ≥20 万会审→通过）各调一次本工厂。
    """
    validator_name = name or f"cosign.{doc_type}.{trigger_state}.{cosign_group}"

    @register_transition_validator(
        validator_name,
        doc_type=doc_type,
        to_state=trigger_state,
        auto=True,
    )
    async def _validator(db, _doc_type, doc, _to_state, _user) -> list[str]:
        return await cosign_failures(
            db,
            doc_type=doc_type,
            doc_id=doc.id,
            required_roles=required_roles,
            cosign_group=cosign_group,
        )

    return None


# ============================================================
# 命令层入口（前端经统一命令执行器调用）
# ============================================================

def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


@register_command(
    "open_cosign",
    module="COSIGN",
    title="发起会签",
    description="进入会签态时按 required_roles 预生成待签行（并行会签标准件）",
    affected_tables=("cosign_line",),
)
async def open_cosign(ctx: CommandContext, payload: dict) -> dict:
    doc_type = (payload.get("doc_type") or "").strip()
    doc_id = payload.get("doc_id")
    required_roles = payload.get("required_roles") or []
    cosign_group = payload.get("cosign_group") or "DEFAULT"
    company_id = payload.get("company_id") or ctx.user.company_id
    if not doc_type or not doc_id:
        raise CommandError("doc_type / doc_id 不能为空")
    if not required_roles:
        raise CommandError("required_roles 不能为空")
    _assert_company_access(ctx.user, company_id)
    created = await generate_cosign_lines(
        ctx.db,
        doc_type=doc_type,
        doc_id=doc_id,
        company_id=company_id,
        required_roles=required_roles,
        cosign_group=cosign_group,
        created_by_id=ctx.user.id,
    )
    ctx.add_event("cosign_opened", {"doc_type": doc_type, "doc_id": doc_id, "created": len(created)})
    return {"created_line_ids": created, "count": len(created)}


@register_command(
    "sign_cosign",
    module="COSIGN",
    title="我签字",
    description="签票方往自己那行填同意/驳回（自循环签字动作，并行任意顺序）",
    affected_tables=("cosign_line",),
)
async def sign_cosign(ctx: CommandContext, payload: dict) -> dict:
    line_id = payload.get("line_id")
    if not line_id:
        raise CommandError("line_id 不能为空")
    try:
        line = await sign_cosign_line(
            ctx.db,
            line_id=line_id,
            user=ctx.user,
            decision=payload.get("decision") or "",
            comment=payload.get("comment") or "",
        )
    except ValueError as e:
        raise CommandError(str(e))
    _assert_company_access(ctx.user, line.company_id)
    ctx.add_event("cosign_signed", {"line_id": line.id, "decision": line.decision})
    return {"line_id": line.id, "decision": line.decision}


# ============================================================
# 标准件实例（05 §3）：客户认证审核 = PA + FINANCE + BOSS 三方全签
# 备货 ≥20 万会审等关卡复用 register_cosign_checkpoint，角色待甲方（05 gap）。
# ============================================================

# 客户认证（段3c CUSTOMER_QUALIFICATION）：进入 APPROVED（通过）态前，集齐 PA+财务+BOSS 三方同意；
# 任一驳回走 REJECTED（自循环签字态 UNDER_COSIGN→APPROVED 边前跑本校验器）。
# required_roles 用引擎角色码 PRODUCT_ASSISTANT/FINANCE/BOSS（与 user_account.role 一致，sign_cosign 比对）。
# 进 UNDER_COSIGN 时预生成三行待签的 effect 见 phase1_effects.qualification.open_certification_cosign。
register_cosign_checkpoint(
    doc_type="CUSTOMER_QUALIFICATION",
    trigger_state="APPROVED",
    required_roles=["PRODUCT_ASSISTANT", "FINANCE", "BOSS"],
    cosign_group="CERTIFICATION",
    name="cosign.customer_certification",
)


# ============================================================
# 段2d-1 备货 ≥20 万会审（04b-1）：PM + FINANCE 都签才放行。
#
# 备货 APPROVED 有两条来源边：PENDING_PM（<20万 PM 单批，无会签）/ PENDING_REVIEW（≥20万会审）。
# 通用 register_cosign_checkpoint 的校验器对「进 APPROVED」一律跑集齐校验，会误伤 <20万 单批边
# （那条没有签字行 → 报「角色未就位」拦住）。故这里**手写一个 scoped 校验器**，复用标准件的
# cosign_failures() 积木，仅当单据当前态 = PENDING_REVIEW 时才强制集齐（验证器跑在状态推进前，
# doc.status 仍是来源态 → 可据此判来源边）。<20万 经 PENDING_PM 进 APPROVED 不受影响。
# 进 PENDING_REVIEW 时预生成 PM+FINANCE 待签行的 effect 见 phase1_effects.stockup.open_review_cosign。
# ============================================================

STOCK_REVIEW_ROLES = ["PRODUCT_MANAGER", "FINANCE"]


@register_transition_validator(
    "cosign.stock_up_review",
    doc_type="STOCK_UP_REQUEST",
    to_state="APPROVED",
    auto=True,
)
async def _stock_up_review_cosign(db, _doc_type, doc, _to_state, _user) -> list[str]:
    # 仅 ≥20万会审来源边（当前态 PENDING_REVIEW）强制集齐；<20万 PM 单批边放行。
    if getattr(doc, "status", None) != "PENDING_REVIEW":
        return []
    return await cosign_failures(
        db,
        doc_type="STOCK_UP_REQUEST",
        doc_id=doc.id,
        required_roles=STOCK_REVIEW_ROLES,
        cosign_group="STOCK_REVIEW",
    )
