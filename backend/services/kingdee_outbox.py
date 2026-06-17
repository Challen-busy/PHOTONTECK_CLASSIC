"""金蝶云星空 outbox 壳（段0b·3，07b）。

每张到触发态的业务单 → 适配器 effect 写一行 kingdee_outbox（业务单号=幂等键，
status=RUNNING），真实推送（金蝶 OpenAPI Save→Submit→Audit）留 TODO 占位、
开关默认 OFF/dry-run。失败可重推（repush 命令复用幂等键）、绝不静默丢单。

铁律遵从：推送实现为 @register_transition_effect（副作用注册器）+ @register_command（唯一写入路径）；
outbox 业务单号作幂等键映射到命令 idempotency_key（双层幂等）；不动 execute_transition / 命令框架。

★最大 ➕扩展点：真实 HTTP 接入待金蝶凭据（appid/appSecret/accesstoken）+ 6 公司组织码
（gap 7）+ 各账套固定字段编码到位（07b gap）。在此之前为已写就的设计契约。
"""

import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter
from services.workflow_extensions import register_transition_effect

# 推送总开关：默认 OFF（dry-run）—— 只写 outbox 行、不发真实 HTTP。
# 金蝶凭据 / 组织码 / 账套字段编码到位后置 ON 排真实对接（07b）。
KINGDEE_PUSH_ENABLED = os.environ.get("KINGDEE_PUSH_ENABLED", "0") == "1"

RUNNING, SUCCESS, FAILED = "RUNNING", "SUCCESS", "FAILED"

# 业务单据 → 金蝶 formId / 请求 URL 映射（07b 页面2 §2.1，10 行）。
# 真实推送时由本表带入 form_id / request_url；字段级映射在 07b §2.2（实施对接时落地）。
KINGDEE_FORM_MAP: dict[str, dict] = {
    "PURCHASE_ORDER":      {"form_id": "pm_purorderbill", "url": "/v2/pm/pm_purorderbill/add"},
    "GOODS_RECEIPT":       {"form_id": "im_purinbill",    "url": "/v2/im/im_purinbill/add"},
    "OTHER_INBOUND":       {"form_id": "im_otherinbill",  "url": "/v2/im/im_otherinbill/batchAdd"},
    "SALES_ORDER":         {"form_id": "sm_salorder",     "url": "/v2/sm/sm_salorder/batchAdd"},
    "SHIPMENT":            {"form_id": "im_saloutbill",   "url": "/v2/im/im_saloutbill/batchAdd"},
    "SALES_INVOICE":       {"form_id": "ar_finarbill",    "url": "/v2/ar/ar_finarbill/batchAdd"},
    "PURCHASE_INVOICE":    {"form_id": "ap_finapbill",    "url": "/v2/ap/ap_finapbill/batchAdd"},
    "INVENTORY_ADJUST":    {"form_id": "im_otherinbill",  "url": "/v2/im/im_otherinbill/batchAdd"},
    # 段1b-2：库存调整单（盘点差异落账）→ 金蝶其他入库/出库单（按差异正负，实施对接细化，07b）。
    "STOCK_ADJUSTMENT":    {"form_id": "im_otherinbill",  "url": "/v2/im/im_otherinbill/batchAdd"},
    "ADVANCE_RECEIPT":     {"form_id": "cas_recbill",     "url": "/v2/cas/cas_recbill/addSave"},
    "ADVANCE_PAYMENT":     {"form_id": "cas_paybill",     "url": "/v2/cas/cas_paybill/addSave"},
    # 段2c 04a-8：付款申请（货后付款执行）→ 金蝶付款单（应付付款执行源，幂等键 payment_number+company）。
    "PAYMENT_REQUEST":     {"form_id": "cas_paybill",     "url": "/v2/cas/cas_paybill/addSave"},
}


def _biz_no(doc) -> str:
    """业务单号（=幂等键）：取单上的 *_number 标识列。"""
    for f in ("order_number", "receipt_number", "shipment_number", "invoice_number",
              "receipt_number", "payment_number", "adjustment_number", "transfer_number", "number"):
        v = getattr(doc, f, None)
        if v:
            return str(v)
    return f"{doc.__tablename__}-{doc.id}"


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


async def _push_to_kingdee(outbox: m.KingdeeOutbox) -> tuple[str, dict, str, str]:
    """真实推送占位。

    返回 (status, receipt, kingdee_bill_no, error_message)。
    TODO（真实接入，07b 页面2 接口形态总则）:
      1. 换取 accesstoken（appid/appSecret）。
      2. 组织映射 company_id → org_number（gap 7）。
      3. 按 KINGDEE_FORM_MAP[doc_type] 拼请求体 {"data":[{...}]}（字段映射 07b §2.2）。
      4. POST request_url，请求头带 accesstoken / x-acgw-appid / Idempotency-Key=biz_no。
      5. 解析响应 {"status","errorCode","message","data.result[]"}：
         status=true & errorCode 空 → SUCCESS + 回填 data.result[] 的金蝶单据号；否则 FAILED。
      6. 视配置链式 Save→Submit→Audit（07b 触发态注，默认一条龙到已审核）。
    当前 dry-run：只标记为已入队，不发 HTTP，待真实接入。
    """
    if not KINGDEE_PUSH_ENABLED:
        return (
            RUNNING,
            {"dry_run": True, "note": "KINGDEE_PUSH_ENABLED=0，仅入 outbox，未发真实请求"},
            "",
            "",
        )
    # TODO: 真实 HTTP 接入（见上）。开关已开但接入未实现 → 明确标失败，不静默成功。
    return (FAILED, {"note": "real HTTP not implemented"}, "", "金蝶真实推送尚未接入（占位）")


async def enqueue_outbox(
    db: AsyncSession,
    *,
    doc,
    doc_type: str,
    trigger_state: str | None,
    user: m.UserAccount,
    command_log_id: int | None,
) -> m.KingdeeOutbox:
    """写一行 outbox（幂等：同 (company, doc_type, biz_no) 已 SUCCESS/RUNNING 则复用）。"""
    company_id = getattr(doc, "company_id", None) or user.company_id
    biz_no = _biz_no(doc)
    existing = (await db.execute(
        select(m.KingdeeOutbox).where(
            m.KingdeeOutbox.company_id == company_id,
            m.KingdeeOutbox.doc_type == doc_type,
            m.KingdeeOutbox.biz_no == biz_no,
            m.KingdeeOutbox.status.in_((SUCCESS, RUNNING)),
        ).order_by(m.KingdeeOutbox.id.desc())
    )).scalars().first()
    if existing:
        return existing

    mapping = KINGDEE_FORM_MAP.get(doc_type, {})
    row = m.KingdeeOutbox(
        company_id=company_id,
        doc_type=doc_type,
        biz_no=biz_no,
        business_doc_type=doc_type,
        business_doc_id=doc.id,
        trigger_state=trigger_state or "",
        form_id=mapping.get("form_id", ""),
        request_url=mapping.get("url", ""),
        status=RUNNING,
        payload={"biz_no": biz_no, "doc_type": doc_type, "doc_id": doc.id},
        receipt={},
        command_log_id=command_log_id,
        created_by_id=getattr(user, "id", None),
    )
    db.add(row)
    await db.flush()

    status, receipt, bill_no, err = await _push_to_kingdee(row)
    row.status = status
    row.receipt = receipt
    row.kingdee_bill_no = bill_no
    row.error_message = err
    if status in (SUCCESS, FAILED):
        row.completed_at = datetime.now()
    return row


@register_transition_effect("kingdee.enqueue_push", auto=False)
async def kingdee_enqueue_push(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """适配器 effect 骨架：推进到触发态时写一行 outbox。

    EXPLICIT 派发（auto=False）：在流程节点/边的 effects 列表里显式列 "kingdee.enqueue_push"
    才触发（适合跨系统推送这类与具体业务态强绑定的动作，总览 §4 effect 两种派发）。
    """
    row = await enqueue_outbox(
        db, doc=doc, doc_type=doc_type, trigger_state=to_state,
        user=user, command_log_id=command_log_id,
    )
    return [f"kingdee outbox#{row.id} {row.status} biz_no={row.biz_no}"]


@register_command(
    "repush_kingdee_outbox",
    module="FINANCE",
    title="重推金蝶",
    description="重推失败的金蝶 outbox 行（复用业务单号幂等键，已成功自动去重）",
    affected_tables=("kingdee_outbox",),
    supports_retry=True,
)
async def repush_kingdee_outbox(ctx: CommandContext, payload: dict) -> dict:
    """推送中心重推：仅 FAILED 行可重推；新建一行 RUNNING（retried_from_id 指向原行）。

    权限：本公司 FINANCE / ADMIN（财务总监 / BOSS 只读不可重推，07b 验收5）。
    """
    outbox_id = payload.get("outbox_id")
    if not outbox_id:
        raise CommandError("outbox_id 不能为空")
    row = (await ctx.db.execute(
        select(m.KingdeeOutbox).where(m.KingdeeOutbox.id == outbox_id).with_for_update()
    )).scalar_one_or_none()
    if not row:
        raise CommandError("推送记录不存在", 404)
    _assert_company_access(ctx.user, row.company_id)
    if not (ctx.user.is_admin or ctx.user.role == "FINANCE"):
        raise CommandError("仅本公司财务 / 管理员可重推", 403)

    if row.status == SUCCESS:
        # 已成功 → 幂等去重，回放原结果（07b 验收4）。
        return {"outbox_id": row.id, "status": SUCCESS, "kingdee_bill_no": row.kingdee_bill_no, "repushed": False}
    if row.status != FAILED:
        raise CommandError("仅失败行可重推")

    new_row = m.KingdeeOutbox(
        company_id=row.company_id,
        doc_type=row.doc_type,
        biz_no=row.biz_no,
        business_doc_type=row.business_doc_type,
        business_doc_id=row.business_doc_id,
        trigger_state=row.trigger_state,
        form_id=row.form_id,
        request_url=row.request_url,
        status=RUNNING,
        payload=row.payload,
        receipt={},
        command_log_id=ctx.command_log.id,
        retried_from_id=row.id,
        retry_count=(row.retry_count or 0) + 1,
        created_by_id=ctx.user.id,
    )
    ctx.db.add(new_row)
    await ctx.db.flush()

    status, receipt, bill_no, err = await _push_to_kingdee(new_row)
    new_row.status = status
    new_row.receipt = receipt
    new_row.kingdee_bill_no = bill_no
    new_row.error_message = err
    if status in (SUCCESS, FAILED):
        new_row.completed_at = datetime.now()

    ctx.add_event("kingdee_outbox_repushed", {"outbox_id": new_row.id, "retried_from_id": row.id, "status": status})
    return {"outbox_id": new_row.id, "retried_from_id": row.id, "status": status, "repushed": True}
