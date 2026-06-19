"""信用管理（finance-gl 信用波）：信用检查 validator + 信用占用 effect + 重算命令。

★引擎契合:信用检查=@register_transition_validator(单据流转时校验可用额度,返回非空=阻断);
信用占用=@register_transition_effect(auto,流转后写占用流水+刷新已占用缓存)。核心三件零 diff。
本模块已由 command_registry.load_commands + workflow_extensions._EXTENSION_MODULES 双注册。

P0 范围:hook「应收单」(ACCOUNTS_RECEIVABLE) 审核(SUBMITTED→AUDITED, 时点=AUDIT)。
  - validator finance.check_credit:读 company.credit_control_enabled(关→全 pass)→ 客户信用档案 CustomerCredit →
    适用检查规则行(check_rule_id 或公司默认规则, 匹配 doc_type+check_point=AUDIT)→ 按 control_strategy:
      NONE 不控 / WARN 提示(超标写 credit_overlimit_log 但放行) / STRICT 严格(超标阻断,返回失败信息)。
    检查项:信用状态冻结 / 单笔限额 / 信用额度(可用=额度−已占用)。
    已占用 = Σ(本客户 AUDITED 未关闭应收单 未清额)，动态实算(不依赖缓存,天然随核销/收款释放)。
  - effect finance.occupy_credit(auto, AR AUDITED):写 credit_occupation 流水 + 刷新 CustomerCredit.used_amount 缓存。
  - command finance.recompute_credit:按本公司重算所有客户 used_amount(= Σ open AR 未清)。

销售链单据(销售订单/发货/出库)hook 待段3销售建好后,在检查规则加行 + 给本 validator/effect 注册新 doc_type 即生效。
副作用在 execute_transition 同事务内运行:只 db.add()/db.flush(),失败 raise 由引擎回滚。
⚠️ STRICT 阻断时整事务回滚,超标日志随之回滚(仅 WARN 放行的超标会落库)；BLOCK 留痕属 P1。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter
from services.workflow_extensions import register_transition_effect, register_transition_validator


_AR_CLOSED = ("CLOSED", "SETTLED")
# 流转目标态 → 检查规则时点。P0 只挂 AUDITED。
_STATE_TO_CHECKPOINT = {"AUDITED": "AUDIT", "SUBMITTED": "SUBMIT", "DRAFT": "SAVE"}


def _num(v) -> Decimal:
    if v is None:
        return Decimal("0")
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def _ar_outstanding(ar) -> Decimal:
    return max(_num(ar.amount) - _num(ar.paid_amount) - _num(getattr(ar, "written_off_amount", 0)), Decimal("0"))


async def _customer_used(db: AsyncSession, company_id: int, customer_id: int, exclude_id: int | None = None) -> Decimal:
    """已占用额度 = Σ(本客户 AUDITED 未关闭应收单 未清额)。exclude_id 排除正在审核的本单。"""
    stmt = select(m.AccountsReceivable).where(
        m.AccountsReceivable.company_id == company_id,
        m.AccountsReceivable.customer_id == customer_id,
        m.AccountsReceivable.status == "AUDITED",
    )
    rows = (await db.execute(stmt)).scalars().all()
    total = Decimal("0")
    for ar in rows:
        if exclude_id is not None and ar.id == exclude_id:
            continue
        total += _ar_outstanding(ar)
    return _q2(total)


async def _customer_profile(db: AsyncSession, company_id: int, customer_id: int):
    return (await db.execute(
        select(m.CustomerCredit).where(
            m.CustomerCredit.company_id == company_id,
            m.CustomerCredit.customer_id == customer_id,
        )
    )).scalar_one_or_none()


async def _applicable_line(db: AsyncSession, profile, company_id: int, doc_type: str, check_point: str):
    """取适用的检查规则行：优先客户档案指定规则，缺则公司默认规则；匹配 doc_type + check_point。"""
    rule_id = getattr(profile, "check_rule_id", None)
    if rule_id is None:
        default_rule = (await db.execute(
            select(m.CreditCheckRule).where(
                m.CreditCheckRule.company_id == company_id,
                m.CreditCheckRule.is_active == True,  # noqa: E712
            ).order_by(m.CreditCheckRule.is_default.desc(), m.CreditCheckRule.id)
        )).scalars().first()
        if default_rule is None:
            return None
        rule_id = default_rule.id
    line = (await db.execute(
        select(m.CreditCheckRuleLine).where(
            m.CreditCheckRuleLine.credit_check_rule_id == rule_id,
            m.CreditCheckRuleLine.doc_type == doc_type,
            m.CreditCheckRuleLine.check_point == check_point,
        ).order_by(m.CreditCheckRuleLine.line_number)
    )).scalars().first()
    return line


# ============================================================
# validator：信用检查（应收单审核 SUBMITTED→AUDITED）
# ============================================================

@register_transition_validator(
    "finance.check_credit",
    doc_type="ACCOUNTS_RECEIVABLE",
    to_state="AUDITED",
)
async def check_credit(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount,
) -> list[str]:
    """信用检查：返回非空 = 阻断（STRICT 超标）；空 = 放行（含 WARN 提示，已落超标日志）。"""
    company = await db.get(m.Company, doc.company_id)
    if company is None or not getattr(company, "credit_control_enabled", False):
        return []  # 信用控制总开关关闭 → 全 pass
    customer_id = getattr(doc, "customer_id", None)
    if not customer_id:
        return []
    profile = await _customer_profile(db, doc.company_id, customer_id)
    if profile is None:
        return []  # 无信用档案 = 不控

    check_point = _STATE_TO_CHECKPOINT.get(to_state or "AUDITED", "AUDIT")
    line = await _applicable_line(db, profile, doc.company_id, doc_type, check_point)
    if line is None or (line.control_strategy or "").upper() == "NONE":
        return []

    strategy = (line.control_strategy or "WARN").upper()
    this_amount = _q2(_num(doc.amount))
    credit_limit = _q2(_num(profile.credit_limit))
    used = await _customer_used(db, doc.company_id, customer_id, exclude_id=doc.id)
    available = _q2(credit_limit - used)
    failures: list[str] = []

    async def _log(over_type: str, over_amount: Decimal):
        db.add(m.CreditOverlimitLog(
            company_id=doc.company_id, party_type="CUSTOMER", party_id=customer_id,
            doc_type=doc_type, doc_id=doc.id, doc_no=getattr(doc, "bill_number", "") or "",
            biz_date=getattr(doc, "bill_date", None) or date.today(),
            occupy_amount=this_amount, credit_limit=credit_limit, available_before=available,
            over_amount=_q2(over_amount), over_type=over_type, control_strategy=strategy,
            action=("BLOCK" if strategy == "STRICT" else "WARN"), handled_by_id=user.id,
        ))
        await db.flush()

    # 1. 信用状态冻结
    if (profile.credit_status or "NORMAL").upper() == "FROZEN":
        await _log("FROZEN", this_amount)
        msg = f"客户信用状态为「冻结」，不允许新增应收单（{getattr(doc, 'bill_number', '') or doc.id}）"
        if strategy == "STRICT":
            return [msg]
        failures  # WARN 不阻断

    # 2. 单笔限额
    single = _q2(_num(profile.single_limit))
    if line.check_single_limit and single > 0 and this_amount > single:
        over = this_amount - single
        await _log("SINGLE_LIMIT", over)
        if strategy == "STRICT":
            return [f"超单笔限额：本单 {this_amount} > 单笔限额 {single}（超 {over}）"]

    # 3. 信用额度
    if line.check_credit_limit and this_amount > available:
        over = this_amount - available
        await _log("CREDIT_LIMIT", over)
        if strategy == "STRICT":
            return [f"超信用额度：本单 {this_amount} > 可用额度 {available}"
                    f"（额度 {credit_limit} − 已占用 {used}），超 {over}"]

    return failures


# ============================================================
# effect：信用占用（应收单审核后，auto，写占用流水 + 刷新已占用缓存）
# ============================================================

@register_transition_effect(
    "finance.occupy_credit",
    doc_type="ACCOUNTS_RECEIVABLE", to_state="AUDITED", auto=True,
)
async def occupy_credit(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None,
) -> list[str]:
    """应收单审核 → 写信用占用流水 + 刷新客户已占用额度缓存（仅当本公司开信用控制且客户有档案）。"""
    company = await db.get(m.Company, doc.company_id)
    if company is None or not getattr(company, "credit_control_enabled", False):
        return []
    customer_id = getattr(doc, "customer_id", None)
    if not customer_id:
        return []
    profile = await _customer_profile(db, doc.company_id, customer_id)
    if profile is None:
        return []

    amount = _q2(_num(doc.amount))
    # 幂等：同单已有未释放占用则不重复写。
    existing = (await db.execute(
        select(m.CreditOccupation).where(
            m.CreditOccupation.company_id == doc.company_id,
            m.CreditOccupation.doc_type == doc_type,
            m.CreditOccupation.doc_id == doc.id,
            m.CreditOccupation.is_released == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if existing is None and amount > 0:
        db.add(m.CreditOccupation(
            company_id=doc.company_id, party_type="CUSTOMER", party_id=customer_id,
            currency=getattr(doc, "currency", "") or "", doc_type=doc_type, doc_id=doc.id,
            occupy_amount=amount, occupy_date=getattr(doc, "bill_date", None) or date.today(),
            is_released=False, created_by_id=user.id,
        ))
    # 刷新已占用缓存 = Σ open AR（含本单，本单此刻已 AUDITED）。
    profile.used_amount = await _customer_used(db, doc.company_id, customer_id)
    await db.flush()
    return [f"信用占用 客户#{customer_id} +{amount}（已占用 {profile.used_amount} / 额度 {_q2(_num(profile.credit_limit))}）"]


# ============================================================
# 命令：finance.recompute_credit（重算已占用 + 占用流水）
# ============================================================

def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


@register_command(
    "finance.recompute_credit",
    module="FINANCE",
    title="重算客户信用占用",
    description="按公司重算所有客户已占用额度（= Σ 未清应收单）+ 重建占用流水（释放已结清/已核销单的占用）。",
    affected_tables=("customer_credit", "credit_occupation"),
    supports_retry=True,
)
async def recompute_credit(ctx: CommandContext, payload: dict) -> dict:
    """重算信用占用。payload: company_id（必填）。"""
    company_id = payload.get("company_id")
    if not company_id:
        raise CommandError("company_id 不能为空")
    _assert_company_access(ctx.user, company_id)
    db = ctx.db

    profiles = (await db.execute(
        select(m.CustomerCredit).where(m.CustomerCredit.company_id == company_id)
    )).scalars().all()
    # 当前各客户 open AR 未清额。
    ar_rows = (await db.execute(
        select(m.AccountsReceivable).where(
            m.AccountsReceivable.company_id == company_id,
            m.AccountsReceivable.status == "AUDITED",
        )
    )).scalars().all()
    used_by_cust: dict[int, Decimal] = {}
    open_doc_ids_by_cust: dict[int, set] = {}
    for ar in ar_rows:
        out = _ar_outstanding(ar)
        if out > 0:
            used_by_cust[ar.customer_id] = used_by_cust.get(ar.customer_id, Decimal("0")) + out
            open_doc_ids_by_cust.setdefault(ar.customer_id, set()).add(ar.id)

    updated = 0
    for p in profiles:
        new_used = _q2(used_by_cust.get(p.customer_id, Decimal("0")))
        if _q2(_num(p.used_amount)) != new_used:
            p.used_amount = new_used
            updated += 1

    # 释放占用流水中对应单据已不在 open 集合的行。
    occs = (await db.execute(
        select(m.CreditOccupation).where(
            m.CreditOccupation.company_id == company_id,
            m.CreditOccupation.party_type == "CUSTOMER",
            m.CreditOccupation.is_released == False,  # noqa: E712
        )
    )).scalars().all()
    released = 0
    now = datetime.now()
    for occ in occs:
        open_ids = open_doc_ids_by_cust.get(occ.party_id, set())
        if occ.doc_id not in open_ids:
            occ.is_released = True
            occ.released_at = now
            released += 1
    await db.flush()

    ctx.add_event("finance_recompute_credit", {
        "company_id": company_id, "profiles_updated": updated, "occupations_released": released,
    })
    return {"company_id": company_id, "profiles": len(profiles),
            "profiles_updated": updated, "occupations_released": released}
