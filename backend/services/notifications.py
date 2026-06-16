"""通知子系统（段0b·4，总览 §2「通知中心」）。

到期 / 超额 / 退运 180 / 签收超期 / 盘点提醒等，分派给该看的角色。
- 态推进 effect 派发：进某态时显式列 "notify.dispatch" 触发（EXPLICIT，需配 payload）。
- 定时扫描骨架：引擎无 cron → scan_* 留可调度入口（手动/外部调度调命令），dedup_key 幂等防重复。
- 站内未读查询：unread_notifications。
- 邮件适配器：占位（email_status 字段标记，真实 SMTP 待接入）。

铁律遵从：通知是旁路提醒（不进唯一写入路径的业务真相），写库经命令/effect；不动引擎核心。
"""

from datetime import date, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.workflow_extensions import register_transition_effect

# 退运监控 180 天（总览 §2 退运监控、报关）。
RETURN_WATCH_DAYS = 180


async def create_notification(
    db: AsyncSession,
    *,
    company_id: int,
    category: str,
    title: str,
    body: str = "",
    severity: str = "INFO",
    recipient_id: int | None = None,
    recipient_role: str = "",
    source_doc_type: str = "",
    source_doc_id: int | None = None,
    dedup_key: str | None = None,
    queue_email: bool = False,
) -> m.Notification | None:
    """写一条通知。dedup_key 不空且已存在 → 跳过（幂等，定时扫描防重复刷屏）。"""
    if dedup_key:
        existing = (await db.execute(
            select(m.Notification.id).where(m.Notification.dedup_key == dedup_key)
        )).scalar_one_or_none()
        if existing:
            return None
    note = m.Notification(
        company_id=company_id,
        recipient_id=recipient_id,
        recipient_role=recipient_role,
        category=category,
        title=title,
        body=body,
        severity=severity,
        source_doc_type=source_doc_type,
        source_doc_id=source_doc_id,
        dedup_key=dedup_key,
        email_status="QUEUED" if queue_email else "NONE",
    )
    db.add(note)
    await db.flush()
    if queue_email:
        await _send_email_adapter(note)
    return note


async def _send_email_adapter(note: m.Notification) -> None:
    """邮件适配器骨架（占位）。

    TODO（真实接入）：解析收件人邮箱（recipient_id → UserAccount.contact / SMTP 配置），
    发邮件，成功置 email_status=SENT，失败置 FAILED。当前仅留 QUEUED 不真实发送。
    """
    # 占位：真实 SMTP / 邮件服务接入前不发送，保持 QUEUED。
    return None


@register_transition_effect("notify.dispatch", auto=False)
async def notify_dispatch(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """态推进 effect 派发骨架：进某态时生成一条通知。

    EXPLICIT（auto=False）：流程节点/边 effects 列 "notify.dispatch" 时触发。
    通知内容当前用通用模板（按 doc_type + to_state），细化文案/收件角色在配置层扩展。
    """
    company_id = getattr(doc, "company_id", None) or user.company_id
    note = await create_notification(
        db,
        company_id=company_id,
        category="STATE_CHANGE",
        title=f"{doc_type} 进入 {to_state}",
        body=f"{doc_type}#{doc.id} 已推进到 {to_state}",
        severity="INFO",
        source_doc_type=doc_type,
        source_doc_id=doc.id,
        dedup_key=f"state:{doc_type}:{doc.id}:{to_state}",
    )
    return [f"notification#{note.id} dispatched" if note else "notification deduped"]


# ============================================================
# 定时扫描骨架（引擎无 cron → 可调度入口：手动或外部调度调命令）
# ============================================================

async def scan_due_receivables(db: AsyncSession) -> int:
    """应收到期扫描：到期日已过且未结清 → 通知财务。返回新增通知数。"""
    today = date.today()
    rows = (await db.execute(
        select(m.AccountsReceivable).where(
            m.AccountsReceivable.due_date.is_not(None),
            m.AccountsReceivable.due_date < today,
            m.AccountsReceivable.status != "PAID",
        )
    )).scalars().all()
    created = 0
    for ar in rows:
        note = await create_notification(
            db,
            company_id=ar.company_id,
            category="DUE",
            title=f"应收逾期 {ar.invoice_number}",
            body=f"应收 {ar.invoice_number} 到期日 {ar.due_date} 已逾期，待收款。",
            severity="WARN",
            recipient_role="FINANCE",
            source_doc_type="ACCOUNTS_RECEIVABLE",
            source_doc_id=ar.id,
            dedup_key=f"due:AR:{ar.id}:{ar.due_date}",
        )
        if note:
            created += 1
    return created


async def scan_return_180(db: AsyncSession) -> int:
    """退运 180 天监控：退货距今 > 180 天仍未闭环 → 通知物流 / 报关。返回新增通知数。"""
    cutoff = date.today() - timedelta(days=RETURN_WATCH_DAYS)
    rows = (await db.execute(
        select(m.SalesReturn).where(
            m.SalesReturn.created_at.is_not(None),
            m.SalesReturn.created_at < datetime.combine(cutoff, datetime.min.time()),
            m.SalesReturn.status != "CLOSED",
        )
    )).scalars().all()
    created = 0
    for sr in rows:
        note = await create_notification(
            db,
            company_id=sr.company_id,
            category="RETURN_180",
            title=f"退运超 180 天 {sr.return_number}",
            body=f"退货单 {sr.return_number} 距今超过 {RETURN_WATCH_DAYS} 天仍未闭环，复出口期限预警。",
            severity="CRITICAL",
            recipient_role="LOGISTICS",
            source_doc_type="SALES_RETURN",
            source_doc_id=sr.id,
            dedup_key=f"return180:{sr.id}",
        )
        if note:
            created += 1
    return created


async def scan_overdue_payables(db: AsyncSession) -> int:
    """应付到期（超期）扫描：到期日已过且未付 → 通知财务。返回新增通知数。"""
    today = date.today()
    rows = (await db.execute(
        select(m.AccountsPayable).where(
            m.AccountsPayable.due_date.is_not(None),
            m.AccountsPayable.due_date < today,
            m.AccountsPayable.status != "PAID",
        )
    )).scalars().all()
    created = 0
    for ap in rows:
        note = await create_notification(
            db,
            company_id=ap.company_id,
            category="DUE",
            title=f"应付逾期 {ap.invoice_number}",
            body=f"应付 {ap.invoice_number} 到期日 {ap.due_date} 已逾期，待付款。",
            severity="WARN",
            recipient_role="FINANCE",
            source_doc_type="ACCOUNTS_PAYABLE",
            source_doc_id=ap.id,
            dedup_key=f"due:AP:{ap.id}:{ap.due_date}",
        )
        if note:
            created += 1
    return created


# ============================================================
# 站内未读查询
# ============================================================

async def unread_notifications(db: AsyncSession, user: m.UserAccount, limit: int = 100) -> list[m.Notification]:
    """当前用户的站内未读：本公司 + (直达本人 OR 广播给本人角色)。"""
    stmt = (
        select(m.Notification)
        .where(
            m.Notification.company_id == user.company_id,
            m.Notification.is_read == False,
            or_(
                m.Notification.recipient_id == user.id,
                and_(m.Notification.recipient_id.is_(None), m.Notification.recipient_role == user.role),
            ),
        )
        .order_by(m.Notification.created_at.desc())
        .limit(limit)
    )
    return (await db.execute(stmt)).scalars().all()


# ============================================================
# 命令层入口
# ============================================================

@register_command(
    "mark_notification_read",
    module="NOTIFY",
    title="标记已读",
    description="把站内通知标记为已读",
    affected_tables=("notification",),
)
async def mark_notification_read(ctx: CommandContext, payload: dict) -> dict:
    note_id = payload.get("notification_id")
    if not note_id:
        raise CommandError("notification_id 不能为空")
    note = (await ctx.db.execute(
        select(m.Notification).where(m.Notification.id == note_id)
    )).scalar_one_or_none()
    if not note:
        raise CommandError("通知不存在", 404)
    if note.company_id != ctx.user.company_id and not ctx.user.is_admin:
        raise CommandError("无权访问该通知", 403)
    note.is_read = True
    note.read_at = datetime.now()
    ctx.add_event("notification_read", {"notification_id": note.id})
    return {"notification_id": note.id, "is_read": True}


@register_command(
    "run_notification_scan",
    module="NOTIFY",
    title="跑通知扫描",
    description="可调度入口：扫描应收/应付到期、退运180天，生成通知（引擎无 cron）",
    affected_tables=("notification",),
    supports_retry=True,
)
async def run_notification_scan(ctx: CommandContext, payload: dict) -> dict:
    """可调度入口：手动或外部定时调度调本命令跑全部扫描器。dedup_key 幂等防重复。"""
    due_ar = await scan_due_receivables(ctx.db)
    due_ap = await scan_overdue_payables(ctx.db)
    return_180 = await scan_return_180(ctx.db)
    total = due_ar + due_ap + return_180
    ctx.add_event("notification_scan_done", {
        "due_receivables": due_ar, "due_payables": due_ap, "return_180": return_180, "total": total,
    })
    return {"due_receivables": due_ar, "due_payables": due_ap, "return_180": return_180, "total": total}
