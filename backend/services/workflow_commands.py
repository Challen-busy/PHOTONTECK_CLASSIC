"""Workflow commands executed through the shared command layer."""

from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services import workflow


def _raise_workflow_error(result: dict) -> None:
    raise CommandError(
        result.get("error") or "流程执行失败",
        status_code=400,
        details=result,
    )


@register_command(
    "workflow_transition",
    module="WORKFLOW",
    title="流程流转",
    description="执行单据状态流转和字段变更",
    affected_tables=("workflow_log",),
)
async def workflow_transition(ctx: CommandContext, payload: dict) -> dict:
    result = await workflow.execute_transition(
        db=ctx.db,
        doc_type=payload.get("doc_type", ""),
        doc_id=payload.get("doc_id"),
        user=ctx.user,
        to_state=payload.get("to_state"),
        action_label=payload.get("action_label") or "",
        field_updates=payload.get("field_updates") or {},
        sub_updates=payload.get("sub_updates") or [],
        comment=payload.get("comment") or "",
        ip_address=payload.get("ip_address"),
        manage_transaction=False,
        command_log_id=ctx.command_log.id,
    )
    if not result.get("success"):
        _raise_workflow_error(result)
    ctx.add_event("workflow_transition_executed", {
        "doc_type": result.get("doc_type"),
        "doc_id": result.get("doc_id"),
        "from_state": result.get("from_state"),
        "to_state": result.get("to_state"),
    })
    return result


@register_command(
    "workflow_commit_card",
    module="WORKFLOW",
    title="提交变更卡片",
    description="提交预览生成的流程变更卡片",
    affected_tables=("workflow_log",),
)
async def workflow_commit_card(ctx: CommandContext, payload: dict) -> dict:
    result = await workflow.commit_card(
        db=ctx.db,
        card=payload.get("card") or {},
        user=ctx.user,
        comment=payload.get("comment") or "",
        ip_address=payload.get("ip_address"),
        manage_transaction=False,
        command_log_id=ctx.command_log.id,
    )
    if not result.get("success"):
        _raise_workflow_error(result)
    ctx.add_event("workflow_card_committed", {
        "doc_type": result.get("doc_type"),
        "doc_id": result.get("doc_id"),
        "from_state": result.get("from_state"),
        "to_state": result.get("to_state"),
    })
    return result
