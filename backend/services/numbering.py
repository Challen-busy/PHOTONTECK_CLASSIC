"""编号规则引擎（段0b·1，总览 §7）。

引擎原生 `*_number` 只给唯一前缀（_auto_fill_required_fields），不支持
「月度重置 + 连号」这层**业务**编号规则。本模块用 NumberingRule 表 +
`allocate_document_number` 命令补足：

- 公司×单据类型一条规则，前缀 + 重置周期（月/年/不重置）+ 当前序号。
- 取号 = SELECT FOR UPDATE 行锁 → 原子读改写，防并发撞号（引擎 03 幂等/单事务）。
- 跨期（current_period != 本期）→ 自动把序号重置回 0 再发号（月度重置）。
- 生成编号形如 `PR-2606-001`（prefix-period-seq），分隔符/补零/周期格式可配。

铁律遵从：唯一写入路径仍是 Command（@register_command）；不动 execute_transition、
不给引擎加编号语义；纯业务层积木。
"""

from datetime import date, datetime

from sqlalchemy import select

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


def _period_token(reset_period: str, period_format: str, today: date) -> str:
    """当前周期标识：MONTH→%y%m，YEAR→%Y，NEVER→空串。"""
    if reset_period == "NEVER":
        return ""
    fmt = period_format or ("%Y" if reset_period == "YEAR" else "%y%m")
    return today.strftime(fmt)


def format_document_number(rule: m.NumberingRule, seq: int, period_token: str) -> str:
    """按规则拼编号：prefix<sep>period<sep>seq(补零)。空段自动跳过。"""
    sep = rule.separator or "-"
    seq_str = str(seq).zfill(rule.seq_padding or 0)
    parts = [p for p in (rule.prefix or "", period_token, seq_str) if p != ""]
    return sep.join(parts)


async def allocate_next_number(
    db,
    company_id: int,
    doc_type: str,
    *,
    updated_by_id: int | None = None,
    require: bool = False,
) -> dict | None:
    """取下一个业务号（纯 async 共享函数，非命令包装）。

    `allocate_document_number` 命令与建单取号 effect 共用这一段：行锁该
    (company, doc_type) 规则行 → 跨期重置 → 原子自增 → format。

    无规则 / 规则停用：`require=False`（effect 路径）静默返回 None 让上层 no-op；
    `require=True`（命令路径）抛 CommandError 保留原 404/停用语义。
    返回 {number, seq, period} 或 None。
    """
    rule = (await db.execute(
        select(m.NumberingRule)
        .where(
            m.NumberingRule.company_id == company_id,
            m.NumberingRule.doc_type == doc_type,
        )
        .with_for_update()
    )).scalar_one_or_none()
    if not rule:
        if require:
            raise CommandError(f"未配置编号规则: company={company_id} doc_type={doc_type}", 404)
        return None
    if not rule.is_active:
        if require:
            raise CommandError(f"编号规则已停用: {doc_type}")
        return None

    today = date.today()
    period_token = _period_token(rule.reset_period, rule.period_format, today)

    # 跨期重置：当前周期与规则记录的周期不同 → 序号归 0 重新连号（月度重置）。
    if rule.current_period != period_token:
        rule.current_period = period_token
        rule.current_seq = 0

    rule.current_seq = (rule.current_seq or 0) + 1
    if updated_by_id is not None:
        rule.updated_by_id = updated_by_id
    number = format_document_number(rule, rule.current_seq, period_token)
    return {"number": number, "seq": rule.current_seq, "period": period_token}


@register_command(
    "allocate_document_number",
    module="CONFIG",
    title="取单据编号",
    description="按公司×单据类型的编号规则原子发号（行锁防撞号、月度/年度重置连号）",
    affected_tables=("numbering_rule",),
)
async def allocate_document_number(ctx: CommandContext, payload: dict) -> dict:
    """取号：原子自增 + 跨期重置。

    payload: {company_id?, doc_type}（company_id 缺省取当前用户公司）
    返回: {number, doc_type, company_id, seq, period}
    """
    company_id = payload.get("company_id") or ctx.user.company_id
    _assert_company_access(ctx.user, company_id)
    doc_type = (payload.get("doc_type") or "").strip()
    if not doc_type:
        raise CommandError("doc_type 不能为空")

    # 行锁 + 跨期重置 + 原子自增统一走共享函数（require=True 保留 404/停用语义）。
    result = await allocate_next_number(
        ctx.db, company_id, doc_type, updated_by_id=ctx.user.id, require=True,
    )

    ctx.add_event("document_number_allocated", {
        "doc_type": doc_type, "company_id": company_id,
        "number": result["number"], "seq": result["seq"], "period": result["period"],
    })
    return {
        "number": result["number"],
        "doc_type": doc_type,
        "company_id": company_id,
        "seq": result["seq"],
        "period": result["period"],
    }


@register_command(
    "upsert_numbering_rule",
    module="CONFIG",
    title="保存编号规则",
    description="新增或更新公司×单据类型的编号规则（前缀/重置周期/补零）",
    affected_tables=("numbering_rule",),
)
async def upsert_numbering_rule(ctx: CommandContext, payload: dict) -> dict:
    company_id = payload.get("company_id") or ctx.user.company_id
    _assert_company_access(ctx.user, company_id)
    doc_type = (payload.get("doc_type") or "").strip()
    if not doc_type:
        raise CommandError("doc_type 不能为空")

    rule = (await ctx.db.execute(
        select(m.NumberingRule)
        .where(
            m.NumberingRule.company_id == company_id,
            m.NumberingRule.doc_type == doc_type,
        )
        .with_for_update()
    )).scalar_one_or_none()
    if not rule:
        rule = m.NumberingRule(company_id=company_id, doc_type=doc_type, created_by_id=ctx.user.id)
        ctx.db.add(rule)

    if "prefix" in payload:
        rule.prefix = payload.get("prefix") or ""
    if "reset_period" in payload:
        reset = (payload.get("reset_period") or "MONTH").upper()
        if reset not in ("MONTH", "YEAR", "NEVER"):
            raise CommandError("reset_period 必须是 MONTH / YEAR / NEVER")
        rule.reset_period = reset
    if "seq_padding" in payload:
        rule.seq_padding = int(payload.get("seq_padding") or 0)
    if "separator" in payload:
        rule.separator = payload.get("separator") or "-"
    if "period_format" in payload:
        rule.period_format = payload.get("period_format") or "%y%m"
    if "is_active" in payload:
        rule.is_active = bool(payload.get("is_active"))
    if "notes" in payload:
        rule.notes = payload.get("notes") or ""
    rule.updated_by_id = ctx.user.id
    await ctx.db.flush()
    ctx.add_event("numbering_rule_upserted", {"id": rule.id, "doc_type": doc_type})
    return {"id": rule.id, "doc_type": doc_type, "company_id": company_id}
