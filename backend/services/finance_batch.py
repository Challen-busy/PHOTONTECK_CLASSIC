"""总账·第四波（finance-gl wave-4）：凭证批量工作台后端命令 + 凭证汇总表端点取数。

纯扩展、新文件。引擎核心三件（registry / execute_transition / execute_command）字节级零 diff；
写仍走唯一写入路径 execute_transition（批量推进/按模板建草稿都逐张调引擎），
批量幂等/日志由 execute_command 外壳负责。

四个命令（均 @register_command，module=FINANCE）：
  1) finance.batch_voucher_transition —— 批量审核/复核/过账：对一批凭证逐张 execute_transition
     推到目标态，逐张 try 收集结果，一张失败不阻断其余；职责分离/借贷平衡/期间锁等 validator
     自动生效（失败的进 failed）。批内每张走 manage_transaction=False（命令外壳统一 commit）。
  2) finance.create_voucher_from_model —— 按模式凭证模板建草稿：读 ModelVoucher + ModelVoucherLine
     模板，经 execute_transition(doc_id=None→START→DRAFT) 建一张草稿凭证，分录取模板行
     （account/dr_cr/description，金额取模板默认或留 0），回链 source_doc_type=MODEL_VOUCHER。
  3) finance.check_voucher_gaps —— 检测某公司+期间内 voucher_number 序列断号（缺口）。
     finance.renumber_vouchers —— 仅对**未过账**凭证按日期重排号（已过账不动；dry_run 仅预览）。

本模块在 workflow_extensions._EXTENSION_MODULES 中按模块名 "services.finance_batch" 登记（命令注册随
import 生效）；凭证汇总表端点在 routers/reports.py 内另加（复用现有 reports 取数风格）。
"""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.numbering import _period_token, allocate_next_number, format_document_number
from services.tools import _company_filter
from services.workflow import execute_transition


# 批量推进允许的目标态（与 VOUCHER 状态机一致：审核 / 出纳复核 / 过账）。
_BATCH_TARGET_STATES = ("AUDITED", "REVIEWED", "POSTED")


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


# ============================================================
# 1) 批量推进：审核 / 复核 / 过账
# ============================================================

@register_command(
    "finance.batch_voucher_transition",
    module="FINANCE",
    title="批量推进凭证",
    description="对一批凭证逐张推到目标态（审核/复核/过账），一张失败不阻断其余；职责分离/借贷平衡/期间锁 validator 自动生效",
    affected_tables=("voucher", "voucher_entry", "account_balance"),
    supports_retry=True,
)
async def batch_voucher_transition(ctx: CommandContext, payload: dict) -> dict:
    """批量把凭证推到目标态。

    payload:
      voucher_ids: [int]      —— 待处理凭证 id 列表（非空）
      to_state: 'AUDITED'|'REVIEWED'|'POSTED'

    逐张 execute_transition(manage_transaction=False)：成功/失败逐张收集，
    一张失败只记入 failed 不阻断后续。validator（职责分离需操作人≠制单人等）
    失败时 execute_transition 内部回滚自身 flush，但因 manage_transaction=False
    不影响其余张；命令外壳在全部处理完后由 execute_command 统一 commit 成功部分。

    返回 {total, succeeded, failed, results:[{id, success, error?, from_state?, to_state?}]}。
    """
    voucher_ids = payload.get("voucher_ids") or []
    to_state = payload.get("to_state")
    if not voucher_ids:
        raise CommandError("voucher_ids 不能为空")
    if to_state not in _BATCH_TARGET_STATES:
        raise CommandError(f"to_state 仅支持 {list(_BATCH_TARGET_STATES)}")

    results: list[dict] = []
    succeeded = 0
    failed = 0
    for vid in voucher_ids:
        try:
            voucher = (await ctx.db.execute(
                select(m.Voucher).where(m.Voucher.id == vid)
            )).scalar_one_or_none()
            if voucher is None:
                results.append({"id": vid, "success": False, "error": "凭证不存在"})
                failed += 1
                continue
            _assert_company_access(ctx.user, voucher.company_id)
            from_state = voucher.status
            res = await execute_transition(
                ctx.db, "VOUCHER", vid, ctx.user, to_state=to_state,
                manage_transaction=False,
                command_log_id=ctx.command_log.id,
            )
            if res.get("success"):
                results.append({
                    "id": vid, "success": True,
                    "from_state": from_state, "to_state": res.get("to_state"),
                })
                succeeded += 1
            else:
                err = res.get("error") or "推进失败"
                rule_failures = res.get("rule_failures")
                if rule_failures:
                    err = f"{err}: {'; '.join(rule_failures)}"
                results.append({"id": vid, "success": False, "from_state": from_state, "error": err})
                failed += 1
        except CommandError as e:
            results.append({"id": vid, "success": False, "error": e.message})
            failed += 1
        except Exception as e:  # noqa: BLE001 — 逐张兜底，单张异常不阻断其余
            results.append({"id": vid, "success": False, "error": str(e)})
            failed += 1

    ctx.add_event("voucher_batch_transition", {
        "to_state": to_state, "total": len(voucher_ids),
        "succeeded": succeeded, "failed": failed,
    })
    return {
        "total": len(voucher_ids),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


# ============================================================
# 2) 按模式凭证模板建草稿
# ============================================================

@register_command(
    "finance.create_voucher_from_model",
    module="FINANCE",
    title="按模板建凭证",
    description="读模式凭证 ModelVoucher + 分录模板 ModelVoucherLine，经引擎建一张草稿凭证（分录取模板行），回链 MODEL_VOUCHER",
    affected_tables=("voucher", "voucher_entry"),
    supports_retry=False,
)
async def create_voucher_from_model(ctx: CommandContext, payload: dict) -> dict:
    """按模式凭证模板新建一张草稿凭证。

    payload:
      model_voucher_id: int   —— 模板头 id（必填）
      voucher_date: 'YYYY-MM-DD'（必填）
      period_id: int          —— 可选；不传则按 voucher_date 落本公司 OPEN 期间

    分录取 ModelVoucherLine：account_id（缺时按 account_code 弱解析到本公司科目）、
    dr_cr（DR→debit / CR→credit）、description、amount（模板默认；空则 0）。
    经 execute_transition(doc_id=None) 入 START 取号 → DRAFT，回链 source_doc_type=MODEL_VOUCHER /
    source_doc_id=model_voucher_id。返回新 {voucher_id, lines}。
    """
    model_voucher_id = payload.get("model_voucher_id")
    voucher_date_raw = payload.get("voucher_date")
    if not model_voucher_id:
        raise CommandError("model_voucher_id 不能为空")
    if not voucher_date_raw:
        raise CommandError("voucher_date 不能为空")
    voucher_date = (
        voucher_date_raw if isinstance(voucher_date_raw, date)
        else date.fromisoformat(str(voucher_date_raw)[:10])
    )

    model = (await ctx.db.execute(
        select(m.ModelVoucher).where(m.ModelVoucher.id == model_voucher_id)
    )).scalar_one_or_none()
    if model is None:
        raise CommandError("模式凭证不存在", 404)
    _assert_company_access(ctx.user, model.company_id)
    company_id = model.company_id

    template_lines = (await ctx.db.execute(
        select(m.ModelVoucherLine)
        .where(m.ModelVoucherLine.model_voucher_id == model_voucher_id)
        .order_by(m.ModelVoucherLine.line_number)
    )).scalars().all()
    if not template_lines:
        raise CommandError("该模式凭证无分录模板，无法建单", 422)

    # 期间：优先入参 period_id；否则按 voucher_date 落本公司 OPEN 期间。
    period_id = payload.get("period_id")
    if not period_id:
        period = (await ctx.db.execute(
            select(m.AccountingPeriod)
            .join(m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id)
            .where(
                m.FiscalYear.company_id == company_id,
                m.AccountingPeriod.start_date <= voucher_date,
                m.AccountingPeriod.end_date >= voucher_date,
            )
            .order_by(m.AccountingPeriod.status == "OPEN")
        )).scalars().first()
        if period is None:
            raise CommandError("未找到该日期所属会计期间，请指定 period_id", 422)
        period_id = period.id

    # 模板行 → VoucherEntry 草稿行（金额留原币=本位币；汇率默认 1，录入时再调）。
    entries: list[dict] = []
    line_no = 0
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for tl in template_lines:
        account_id = tl.account_id
        if account_id is None and tl.account_code:
            acct = (await ctx.db.execute(
                select(m.Account).where(
                    m.Account.company_id == company_id,
                    m.Account.code == tl.account_code,
                )
            )).scalar_one_or_none()
            account_id = acct.id if acct else None
        if account_id is None:
            raise CommandError(
                f"模板行#{tl.line_number} 科目无法解析（account_id 空且 account_code={tl.account_code!r} 在本公司无匹配）",
                422,
            )
        line_no += 1
        amt = _num(tl.amount)
        is_debit = (tl.dr_cr or "DR").upper() == "DR"
        debit = amt if is_debit else Decimal("0")
        credit = Decimal("0") if is_debit else amt
        total_debit += debit
        total_credit += credit
        entries.append({
            "line_number": line_no,
            "account_id": account_id,
            "description": tl.description or model.default_description or "",
            "debit": debit,
            "credit": credit,
            "currency": "CNY",
            "exchange_rate": Decimal("1"),
            "base_debit": debit,
            "base_credit": credit,
        })

    head = {
        "voucher_date": voucher_date,
        "voucher_word_id": model.voucher_word_id,
        "voucher_type": "GENERAL",
        "description": (model.default_description or model.name or "")[:200],
        "period_id": period_id,
        "source_doc_type": "MODEL_VOUCHER",
        "source_doc_id": model_voucher_id,
        "total_debit": total_debit,
        "total_credit": total_credit,
    }
    sub_updates = [
        {"table": "voucher_entry", "parent_fk": "voucher_id", "fields": e}
        for e in entries
    ]

    # 建空凭证：execute_transition(doc_id=None) 入 START 态（同事务取号），头字段随建单写入。
    res = await execute_transition(
        ctx.db, "VOUCHER", None, ctx.user,
        field_updates=head, sub_updates=sub_updates,
        comment=f"按模板 {model.code} 建凭证",
        manage_transaction=False,
        command_log_id=ctx.command_log.id,
    )
    if not res.get("success"):
        raise CommandError(f"按模板建凭证失败: {res.get('error')}", 422)
    voucher_id = res.get("doc_id")

    # START → DRAFT（「开始录入」边，editable_fields=[]，不带字段）。
    r_draft = await execute_transition(
        ctx.db, "VOUCHER", voucher_id, ctx.user, to_state="DRAFT",
        manage_transaction=False, command_log_id=ctx.command_log.id,
    )
    if not r_draft.get("success"):
        raise CommandError(f"凭证入录入态失败: {r_draft.get('error')}", 422)

    ctx.add_event("voucher_created_from_model", {
        "model_voucher_id": model_voucher_id, "voucher_id": voucher_id, "lines": len(entries),
    })
    return {"voucher_id": voucher_id, "lines": len(entries), "model_voucher_id": model_voucher_id}


# ============================================================
# 3) 断号检测 / 重排号（仅未过账）
# ============================================================

# voucher_number 形如 PZ-YYMM-NNN：抓取末段连号数字 + 其前缀（前缀+周期段）做同组比对。
_VOUCHER_NUMBER_TAIL = re.compile(r"^(?P<prefix>.*?)(?P<seq>\d+)$")


def _split_voucher_number(number: str) -> tuple[str, int] | None:
    """拆 voucher_number → (前缀含周期段, 末段序号 int)。不含数字尾段则返回 None。"""
    if not number:
        return None
    match = _VOUCHER_NUMBER_TAIL.match(number)
    if not match or not match.group("seq"):
        return None
    return match.group("prefix"), int(match.group("seq"))


@register_command(
    "finance.check_voucher_gaps",
    module="FINANCE",
    title="凭证断号检测",
    description="检测某公司+期间内 voucher_number 序列缺口（按同前缀分组比对连号），返回缺口清单",
    affected_tables=(),
    supports_retry=True,
)
async def check_voucher_gaps(ctx: CommandContext, payload: dict) -> dict:
    """检测断号。

    payload: {company_id, period_id}
    按同「前缀+周期段」分组，组内序号若不连续则记缺口。
    返回 {company_id, period_id, total, gaps:[{prefix, missing_seq, missing_number}], groups:[...]}。
    """
    company_id = payload.get("company_id")
    period_id = payload.get("period_id")
    if not company_id or not period_id:
        raise CommandError("company_id / period_id 不能为空")
    _assert_company_access(ctx.user, company_id)

    vouchers = (await ctx.db.execute(
        select(m.Voucher)
        .where(m.Voucher.company_id == company_id, m.Voucher.period_id == period_id)
        .order_by(m.Voucher.voucher_number)
    )).scalars().all()

    # 按前缀分组收集序号。
    groups: dict[str, list[int]] = {}
    unparsable: list[str] = []
    for v in vouchers:
        parsed = _split_voucher_number(v.voucher_number)
        if parsed is None:
            unparsable.append(v.voucher_number)
            continue
        prefix, seq = parsed
        groups.setdefault(prefix, []).append(seq)

    gaps: list[dict] = []
    group_summaries: list[dict] = []
    pad = 3  # PZ-YYMM-NNN 默认补零 3；缺口号按现存最大序号宽度补零。
    MAX_SPAN = 100_000   # 单前缀连号扫描跨度上限：超出视为非连续编号(时间戳/混合号)，不枚举缺口防 OOM。
    MAX_GAPS = 2_000     # 缺口明细总封顶：超出只给计数，避免巨量返回。
    for prefix, seqs in sorted(groups.items()):
        seqs_sorted = sorted(set(seqs))
        width = max(pad, max(len(str(s)) for s in seqs_sorted))
        lo, hi = seqs_sorted[0], seqs_sorted[-1]
        present = set(seqs_sorted)
        span = hi - lo + 1
        if span > MAX_SPAN:
            # 号段跨度过大（疑似非连续编号，如时间戳号/手工号）→ 跳过缺口枚举，仅汇总，防内存爆。
            group_summaries.append({
                "prefix": prefix, "min_seq": lo, "max_seq": hi,
                "count": len(seqs_sorted), "missing_count": None,
                "note": f"号段跨度 {span} 过大（疑似非连续编号），已跳过缺口枚举",
            })
            continue
        missing = [s for s in range(lo, hi + 1) if s not in present]
        for ms in missing:
            if len(gaps) >= MAX_GAPS:
                break
            gaps.append({
                "prefix": prefix,
                "missing_seq": ms,
                "missing_number": f"{prefix}{str(ms).zfill(width)}",
            })
        group_summaries.append({
            "prefix": prefix,
            "min_seq": lo,
            "max_seq": hi,
            "count": len(seqs_sorted),
            "missing_count": len(missing),
        })

    return {
        "company_id": company_id,
        "period_id": period_id,
        "total": len(vouchers),
        "gaps": gaps,
        "groups": group_summaries,
        "unparsable": unparsable,
    }


@register_command(
    "finance.renumber_vouchers",
    module="FINANCE",
    title="凭证重排号",
    description="仅对未过账凭证按日期重排 voucher_number（已过账不动），dry_run 仅预览映射不写库",
    affected_tables=("voucher",),
    supports_retry=False,
)
async def renumber_vouchers(ctx: CommandContext, payload: dict) -> dict:
    """重排号（仅未过账）。

    payload: {company_id, period_id, dry_run}
    - 取本公司+期间全部凭证，已过账（POSTED 或 posted_at 非空）保持原号、占住其序号；
      未过账按 voucher_date → 原号 排序，从 1 起依次填入「未被已过账占用」的序号，
      用 NumberingRule(VOUCHER) 的 prefix/separator/period_format/padding 拼新号。
    - dry_run=True（默认）只返回 {old_number → new_number} 映射，不写库。
    - dry_run=False 实写未过账凭证的 voucher_number；为规避 (company,voucher_number) 唯一约束在
      重排过程中临时撞号，先两阶段：① 全部待改行置临时占位号 ② 再落最终号。
    返回 {company_id, period_id, dry_run, changed, mapping:[{id, old_number, new_number}], skipped_posted}。
    """
    company_id = payload.get("company_id")
    period_id = payload.get("period_id")
    dry_run = payload.get("dry_run", True)
    if not company_id or not period_id:
        raise CommandError("company_id / period_id 不能为空")
    _assert_company_access(ctx.user, company_id)

    vouchers = (await ctx.db.execute(
        select(m.Voucher)
        .where(m.Voucher.company_id == company_id, m.Voucher.period_id == period_id)
    )).scalars().all()

    posted = [v for v in vouchers if v.status == "POSTED" or getattr(v, "posted_at", None) is not None]
    unposted = [v for v in vouchers if v not in posted]
    # 未过账按日期 → 原号 稳定排序。
    unposted.sort(key=lambda v: (v.voucher_date or date.min, v.voucher_number or ""))

    # 取号规则（拼新号用其 prefix/sep/period_format/padding）。缺规则降级为纯序号补零 3。
    rule = (await ctx.db.execute(
        select(m.NumberingRule).where(
            m.NumberingRule.company_id == company_id,
            m.NumberingRule.doc_type == "VOUCHER",
        )
    )).scalar_one_or_none()

    # 周期段：按本期间 end_date（落到该会计月）生成，与建单口径一致（月度重置 %y%m）。
    period = (await ctx.db.execute(
        select(m.AccountingPeriod).where(m.AccountingPeriod.id == period_id)
    )).scalar_one_or_none()
    as_of = (period.end_date if period and period.end_date else date.today())
    if rule:
        period_token = _period_token(rule.reset_period, rule.period_format, as_of)
    else:
        period_token = as_of.strftime("%y%m")

    def _make_number(seq: int) -> str:
        if rule:
            return format_document_number(rule, seq, period_token)
        return f"PZ-{period_token}-{str(seq).zfill(3)}"

    # 已过账凭证占用的序号（同前缀+周期段下），避免重排撞到它们。
    occupied: set[int] = set()
    for v in posted:
        parsed = _split_voucher_number(v.voucher_number)
        if parsed is not None:
            occupied.add(parsed[1])

    mapping: list[dict] = []
    seq = 0
    for v in unposted:
        seq += 1
        while seq in occupied:
            seq += 1
        new_number = _make_number(seq)
        if new_number != v.voucher_number:
            mapping.append({"id": v.id, "old_number": v.voucher_number, "new_number": new_number})

    if not dry_run and mapping:
        # 两阶段防唯一约束撞号：① 临时占位号 ② 落最终号。
        for item in mapping:
            v = next(x for x in unposted if x.id == item["id"])
            v.voucher_number = f"__TMP-{v.id}"
        await ctx.db.flush()
        for item in mapping:
            v = next(x for x in unposted if x.id == item["id"])
            v.voucher_number = item["new_number"]
        await ctx.db.flush()
        ctx.add_event("vouchers_renumbered", {
            "company_id": company_id, "period_id": period_id, "changed": len(mapping),
        })

    return {
        "company_id": company_id,
        "period_id": period_id,
        "dry_run": bool(dry_run),
        "changed": len(mapping),
        "mapping": mapping,
        "skipped_posted": len(posted),
    }
