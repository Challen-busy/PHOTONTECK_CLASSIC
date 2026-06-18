"""总账·第一波（finance-gl）记账核心闭环：过账 / 反过账 / 借贷平衡 / 期间锁 / 职责分离 / 红冲。

全靠引擎扩展点实现，引擎核心三件（registry / execute_transition / execute_command）字节级零 diff：
  - @register_transition_effect("finance.post_voucher", auto=False)：过账时逐行把本位币借贷累加进
    AccountBalance（同 company+account+period），按 Account.balance_direction 重算 closing；写
    posted_by_id/posted_at；status=POSTED；幂等（已 POSTED 不重复累加）。
  - @register_transition_effect("finance.unpost_voucher", auto=False)：反过账，AccountBalance 增量取反。
  - @register_transition_validator("finance.validate_balance", to_state="POSTED")：
    Σ本位币借 = Σ本位币贷 才放行，否则精确报差额（过账闸）。
  - @register_transition_validator("finance.period_open", to_state="POSTED")：该凭证 period.status==OPEN
    才放行（LOCKED/CLOSED 拒，提示用红冲/调整期）。
  - @register_transition_validator("finance.segregation_of_duties", to_state="POSTED")：制单≠审核≠过账
    （读公司 FeatureFlag 开关，默认 ON）。
  - @register_command("finance.red_reversal")：对已 POSTED 凭证生成红字反向凭证（分录金额取负、同科目同方向），
    回填 reversed_voucher_id/reversal_type=RED，草稿态待审核过账（无「蓝冲」）。

副作用须幂等（在 execute_transition 同事务内运行）：只 db.add()/db.flush()，绝不 commit，失败 raise 由引擎回滚。
本模块在 workflow_extensions._EXTENSION_MODULES 中按模块名 "services.finance_posting" 加载（已登记）；
red_reversal 命令在 command_registry.load_commands() 中按 import 加载（已登记）。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter
from services.workflow_extensions import (
    register_transition_effect,
    register_transition_validator,
)


# 职责分离开关（per-company FeatureFlag）。默认 ON（缺行即开）——与一般 FeatureFlag「缺行=OFF」相反，
# 财务铁律默认严控；要放宽须显式建一行 is_enabled=False 关掉。
SEGREGATION_FLAG = "FINANCE_SEGREGATION_OF_DUTIES"


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


async def _entries(db: AsyncSession, voucher_id: int):
    return (await db.execute(
        select(m.VoucherEntry)
        .where(m.VoucherEntry.voucher_id == voucher_id)
        .order_by(m.VoucherEntry.line_number)
    )).scalars().all()


async def _period(db: AsyncSession, period_id: int):
    return (await db.execute(
        select(m.AccountingPeriod).where(m.AccountingPeriod.id == period_id)
    )).scalar_one_or_none()


def _recompute_closing(balance: m.AccountBalance, direction: str) -> None:
    """按科目余额方向重算期末（借/贷净额落在自然方向上，对齐 routers/reports.py 试算/科目余额口径）。

    净额 = (opening_debit - opening_credit) + (period_debit - period_credit)，以借方为正。
    DEBIT 科目：净>=0 → closing_debit=净 / closing_credit=0；净<0 → closing_credit=-净。
    CREDIT 科目：以贷方为正镜像处理。
    """
    net_debit_positive = (
        _num(balance.opening_debit) - _num(balance.opening_credit)
        + _num(balance.period_debit) - _num(balance.period_credit)
    )
    if direction == "DEBIT":
        if net_debit_positive >= 0:
            balance.closing_debit = _q2(net_debit_positive)
            balance.closing_credit = Decimal("0.00")
        else:
            balance.closing_debit = Decimal("0.00")
            balance.closing_credit = _q2(-net_debit_positive)
    else:  # CREDIT 科目：贷方为正
        net_credit_positive = -net_debit_positive
        if net_credit_positive >= 0:
            balance.closing_credit = _q2(net_credit_positive)
            balance.closing_debit = Decimal("0.00")
        else:
            balance.closing_credit = Decimal("0.00")
            balance.closing_debit = _q2(-net_credit_positive)


async def _apply_to_balances(
    db: AsyncSession, doc, sign: Decimal
) -> list[str]:
    """把凭证各行本位币借贷以 sign(+1 过账 / -1 反过账) 增量累加进 AccountBalance 并重算 closing。

    AccountBalance 行不存在则按 (company,account,period) 新建（opening 全 0）。
    """
    logs: list[str] = []
    entries = await _entries(db, doc.id)
    # 缓存 account 余额方向，避免逐行重复查。
    direction_cache: dict[int, str] = {}
    for entry in entries:
        d = _num(entry.base_debit) * sign
        c = _num(entry.base_credit) * sign
        if d == 0 and c == 0:
            continue
        balance = (await db.execute(
            select(m.AccountBalance).where(
                m.AccountBalance.company_id == doc.company_id,
                m.AccountBalance.account_id == entry.account_id,
                m.AccountBalance.period_id == doc.period_id,
            )
        )).scalar_one_or_none()
        if balance is None:
            balance = m.AccountBalance(
                company_id=doc.company_id,
                account_id=entry.account_id,
                period_id=doc.period_id,
                opening_debit=Decimal("0"), opening_credit=Decimal("0"),
                period_debit=Decimal("0"), period_credit=Decimal("0"),
                closing_debit=Decimal("0"), closing_credit=Decimal("0"),
            )
            db.add(balance)
            await db.flush()
        balance.period_debit = _q2(_num(balance.period_debit) + d)
        balance.period_credit = _q2(_num(balance.period_credit) + c)
        if entry.account_id not in direction_cache:
            account = (await db.execute(
                select(m.Account).where(m.Account.id == entry.account_id)
            )).scalar_one_or_none()
            direction_cache[entry.account_id] = getattr(account, "balance_direction", "DEBIT") or "DEBIT"
        _recompute_closing(balance, direction_cache[entry.account_id])
        logs.append(
            f"科目#{entry.account_id} 累加 借{d}/贷{c} → 期间#{doc.period_id} 余额"
            f"借{balance.period_debit}/贷{balance.period_credit}"
        )
    return logs


# ============================================================
# 过账 / 反过账（auto=False，须被 next 边 effects[] 显式点名）
# ============================================================

@register_transition_effect("finance.post_voucher", doc_type="VOUCHER", to_state="POSTED", auto=False)
async def post_voucher(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """过账 effect：逐行本位币借贷累加进 AccountBalance + 写过账留痕。

    幂等：已写过 posted_at 则跳过（防退回再触发重复累加）。
    """
    if getattr(doc, "posted_at", None) is not None:
        return [f"voucher#{doc.id} 已过账（posted_at={doc.posted_at}），跳过重复累加"]
    logs = await _apply_to_balances(db, doc, Decimal("1"))
    doc.posted_by_id = getattr(doc, "updated_by_id", None) or user.id
    doc.posted_at = datetime.now()
    await db.flush()
    return logs + [f"voucher#{doc.id} 过账完成 posted_by={doc.posted_by_id}"]


@register_transition_effect("finance.unpost_voucher", doc_type="VOUCHER", to_state="AUDITED", auto=False)
async def unpost_voucher(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """反过账 effect：AccountBalance 增量取反 + 清过账留痕（逐月、期间须 OPEN 由 validator 先拦）。

    幂等：未过账（posted_at 为空）则跳过。
    """
    if getattr(doc, "posted_at", None) is None:
        return [f"voucher#{doc.id} 未过账，反过账跳过"]
    logs = await _apply_to_balances(db, doc, Decimal("-1"))
    doc.posted_by_id = None
    doc.posted_at = None
    await db.flush()
    return logs + [f"voucher#{doc.id} 反过账完成（余额增量已取反）"]


@register_transition_effect("finance.mark_audited", doc_type="VOUCHER", to_state="AUDITED", auto=False)
async def mark_audited(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """审核 effect：自动记审核人/时间（audited_by_id 供职责分离 SoD：制单≠审核≠过账）。"""
    doc.audited_by_id = user.id
    doc.audited_at = datetime.now()
    await db.flush()
    return [f"voucher#{doc.id} 审核 audited_by={user.id}"]


@register_transition_effect("finance.mark_reviewed", doc_type="VOUCHER", to_state="REVIEWED", auto=False)
async def mark_reviewed(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """出纳复核 effect（资金类）：自动记复核人/时间。"""
    doc.reviewed_by_id = user.id
    doc.reviewed_at = datetime.now()
    await db.flush()
    return [f"voucher#{doc.id} 出纳复核 reviewed_by={user.id}"]


# ============================================================
# 校验器：借贷平衡 / 期间锁 / 职责分离
# ============================================================

@register_transition_validator("finance.validate_balance", doc_type="VOUCHER", to_state="POSTED")
async def validate_balance(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount
) -> list[str]:
    """借贷平衡：Σ本位币借 = Σ本位币贷 才放行，否则精确报差额（本位币，过账前）。"""
    entries = await _entries(db, doc.id)
    if not entries:
        return ["凭证分录为空：过账前至少需一条分录"]
    total_debit = sum((_num(e.base_debit) for e in entries), Decimal("0"))
    total_credit = sum((_num(e.base_credit) for e in entries), Decimal("0"))
    diff = _q2(total_debit - total_credit)
    if diff != 0:
        return [
            f"借贷不平衡：本位币借方合计 {_q2(total_debit)} ≠ 贷方合计 {_q2(total_credit)}，"
            f"差额 {diff}（须 Σ借=Σ贷 方可过账）"
        ]
    return []


@register_transition_validator("finance.period_open", doc_type="VOUCHER", to_state="POSTED")
async def period_open(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount
) -> list[str]:
    """期间锁：凭证所属会计期间 status 须为 OPEN 才可过账（LOCKED/CLOSED 拒）。"""
    period = await _period(db, doc.period_id)
    if period is None:
        return ["凭证所属会计期间不存在，无法过账"]
    if period.status != "OPEN":
        return [
            f"会计期间已{('关账' if period.status == 'CLOSED' else '锁定')}（status={period.status}），"
            f"禁止过账；请改用红冲或在调整期处理"
        ]
    return []


async def _segregation_on(db: AsyncSession, company_id: int) -> bool:
    """读 FeatureFlag FINANCE_SEGREGATION_OF_DUTIES（per-company）。缺行=默认 ON（财务严控）。"""
    flag = (await db.execute(
        select(m.FeatureFlag).where(
            m.FeatureFlag.company_id == company_id,
            m.FeatureFlag.flag_key == SEGREGATION_FLAG,
        )
    )).scalar_one_or_none()
    if flag is None:
        return True  # 缺行默认开
    return bool(flag.is_enabled)


@register_transition_validator("finance.segregation_of_duties", doc_type="VOUCHER", to_state="POSTED")
async def segregation_of_duties(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount
) -> list[str]:
    """职责分离：制单(created_by_id)≠审核(audited_by_id)≠过账(当前操作人) 三人互异。

    读公司开关，默认 ON。ADMIN/BOSS 在引擎层绕过 allowed_roles，但职责分离是财务铁律，
    这里仍按实际三个 id 比对（要放宽须关 FeatureFlag）。过账人取当前 user。
    """
    if not await _segregation_on(db, doc.company_id):
        return []
    creator = getattr(doc, "created_by_id", None)
    auditor = getattr(doc, "audited_by_id", None)
    poster = user.id
    failures: list[str] = []
    if auditor is None:
        failures.append("凭证尚未审核（audited_by_id 为空），不能过账")
        return failures
    if creator is not None and creator == auditor:
        failures.append("职责分离：制单人与审核人不能为同一人")
    if creator is not None and creator == poster:
        failures.append("职责分离：制单人与过账人不能为同一人")
    if auditor == poster:
        failures.append("职责分离：审核人与过账人不能为同一人")
    return failures


# ============================================================
# 红冲命令：对已 POSTED 凭证生成红字反向凭证（无蓝冲）
# ============================================================

def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


@register_command(
    "finance.red_reversal",
    module="FINANCE",
    title="红冲凭证",
    description="对已过账凭证生成红字反向凭证（分录金额取负、同科目同方向），原单回链，草稿态待审核过账",
    affected_tables=("voucher", "voucher_entry"),
    supports_retry=True,
)
async def red_reversal(ctx: CommandContext, payload: dict) -> dict:
    """红冲（PRD：原单不删、生反向负数凭证、回链）。

    - 仅对 status==POSTED 的原单红冲；红字单为草稿 DRAFT，分录借贷各取负（同科目同方向），
      回填 reversed_voucher_id=原单 / reversal_type=RED；原单标 is_reversed=True（防重复红冲）。
    - 幂等：原单已 is_reversed 则返回既有红字单（不重复生成）。
    - 红字单号留空，由其 START 取号 effect 在后续流转时分配（与建单同链路）；本命令不直接走流转引擎，
      仅建草稿数据，故先给临时号占位，审核过账走标准状态机。
    """
    voucher_id = payload.get("voucher_id")
    if not voucher_id:
        raise CommandError("voucher_id 不能为空")
    origin = (await ctx.db.execute(
        select(m.Voucher).where(m.Voucher.id == voucher_id)
    )).scalar_one_or_none()
    if origin is None:
        raise CommandError("原凭证不存在", 404)
    _assert_company_access(ctx.user, origin.company_id)

    if origin.status != "POSTED":
        raise CommandError("仅已过账(POSTED)凭证可红冲", 409)

    # 幂等：已红冲过则返回既有红字单。
    if getattr(origin, "is_reversed", False):
        existing = (await ctx.db.execute(
            select(m.Voucher).where(
                m.Voucher.reversed_voucher_id == origin.id,
                m.Voucher.reversal_type == "RED",
            )
        )).scalar_one_or_none()
        if existing:
            return {"id": existing.id, "voucher_number": existing.voucher_number,
                    "reversed_voucher_id": origin.id, "created": False}

    origin_entries = await _entries(ctx.db, origin.id)
    if not origin_entries:
        raise CommandError("原凭证无分录，无法红冲", 422)

    red = m.Voucher(
        company_id=origin.company_id,
        created_by_id=ctx.user.id,
        voucher_number=f"RED-{origin.voucher_number}",  # 临时号占位；走状态机审核过账时不重发业务号
        voucher_date=payload.get("voucher_date") or origin.voucher_date,
        period_id=payload.get("period_id") or origin.period_id,
        voucher_word_id=origin.voucher_word_id,
        voucher_type=origin.voucher_type,
        description=(payload.get("description") or f"红冲：{origin.voucher_number}")[:200],
        total_debit=-_num(origin.total_debit),
        total_credit=-_num(origin.total_credit),
        status="DRAFT",
        reversed_voucher_id=origin.id,
        reversal_type="RED",
    )
    ctx.db.add(red)
    await ctx.db.flush()

    for e in origin_entries:
        ctx.db.add(m.VoucherEntry(
            voucher_id=red.id,
            line_number=e.line_number,
            account_id=e.account_id,
            description=(f"红冲：{e.description}")[:200] if e.description else "红冲",
            # 同科目同方向、金额取负（红字）。
            debit=-_num(e.debit),
            credit=-_num(e.credit),
            currency=e.currency,
            exchange_rate=e.exchange_rate,
            base_debit=-_num(e.base_debit),
            base_credit=-_num(e.base_credit),
            aux_party_type=e.aux_party_type,
            aux_party_id=e.aux_party_id,
            aux_dept_id=e.aux_dept_id,
            aux_project_id=e.aux_project_id,
            cashflow_item_id=e.cashflow_item_id,
            settlement_method=e.settlement_method,
            settlement_no=e.settlement_no,
        ))
    origin.is_reversed = True
    await ctx.db.flush()
    ctx.add_event("voucher_red_reversed", {"origin_id": origin.id, "red_id": red.id})
    return {"id": red.id, "voucher_number": red.voucher_number,
            "reversed_voucher_id": origin.id, "created": True}


# ============================================================
# 业财映射骨架（下一波：单据自动生成凭证分录）
# ============================================================

def map_to_voucher_entries(source_doc_type: str, source_doc, company_id: int) -> list[dict]:
    """业财映射 helper（最小骨架，下一波实现）。

    TODO（finance-gl 第二波）：按 source_doc_type（SALES_INVOICE/PURCHASE_INVOICE/GOODS_RECEIPT…）
    + 记账规则映射表（科目/方向/辅助核算/现金流量项目）把业务单据折算成 VoucherEntry 草稿行列表，
    供「单据 → 自动生成凭证」effect 调用（本位币 base_debit/base_credit = 原币 × 当期 ExchangeRate）。
    本波仅占位，返回空列表，不参与任何流转/写库。
    """
    return []
