"""总账·第六波（finance-gl wave-6，B 部分）：定期凭证生成命令（自动转账 / 摊销 / 预提 三合一）。

期末补全三类常见月结凭证由 RecurringVoucherScheme（方案头 + 行模板子表）模板化，按期一键生成 DRAFT：
  • TRANSFER  自动转账：固定/公式额的科目对转（如月末把待分配费用转入成本）。
  • AMORTIZATION 摊销：待摊费用按 total_amount/periods 每期均摊（最后一期吃尾差）；amortized_periods 累进，到期停。
  • ACCRUAL   预提：按模板固定/公式额计提（如预提水电、利息）。

本模块只走「命令扩展点」（@register_command），引擎核心三件（registry / execute_transition /
execute_command）字节级零 diff，全部新文件、不改既有 effect/validator。凭证生成策略与
services/finance_period_close._build_voucher 同款：直接 db.add 建 DRAFT 草稿（is_auto_generated=True，
source_doc_type=RECURRING_SCHEME 打标），由财务按标准状态机「审核 → 过账」走过账闸（借贷平衡/期间锁/
职责分离三校验复用 wave-1）。命令外壳统一 commit/留痕/幂等。

一个命令（@register_command，module=FINANCE）：
  finance.generate_recurring_voucher —— payload {scheme_id, period_id, voucher_date?}：
    按方案 + 行模板生成一张 DRAFT 凭证。摊销取每期额、累进 amortized_periods；
    幂等：同 (scheme, period) 已生成过（source_doc_type=RECURRING_SCHEME + source_doc_id=scheme_id +
    period_id）则返回既有单，不重复建（摊销进度也不重复累进）。
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter


SRC_RECURRING = "RECURRING_SCHEME"  # 定期凭证 source_doc_type 标记（幂等锚 + 回链）。


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


async def _account_for_line(ctx: CommandContext, company_id: int, line: m.RecurringVoucherLine):
    """解析行模板科目：优先 account_id，否则按 account_code 在本公司弱解析。"""
    account_id = line.account_id
    if account_id is None and line.account_code:
        acct = (await ctx.db.execute(
            select(m.Account).where(
                m.Account.company_id == company_id,
                m.Account.code == line.account_code,
            )
        )).scalar_one_or_none()
        account_id = acct.id if acct else None
    if account_id is None:
        raise CommandError(
            f"行#{line.line_number} 科目无法解析（account_id 空且 account_code={line.account_code!r} 在本公司无匹配）",
            422,
        )
    return account_id


def _line_amount(
    scheme: m.RecurringVoucherScheme, line: m.RecurringVoucherLine, per_period_amount: Decimal,
) -> Decimal:
    """单行金额：
    - formula="total/periods" → 摊销每期额（per_period_amount，已含尾差处理）；
    - formula 其它非空 → 当前最小实现仅支持 "total/periods"，其余未知公式回退到 amount；
    - formula 空 → 用模板固定 amount。
    摊销方案的行若 amount 与 formula 均空，默认用每期额（最常见：待摊费用一借一贷都用每期额）。
    """
    formula = (line.formula or "").strip().replace(" ", "")
    if formula in ("total/periods", "total_amount/periods"):
        return per_period_amount
    if line.amount is not None:
        return _q2(_num(line.amount))
    if scheme.scheme_type == "AMORTIZATION":
        return per_period_amount
    return Decimal("0")


async def _existing_recurring_voucher(ctx: CommandContext, scheme_id: int, period_id: int):
    """幂等锚：同方案同期间已生成的定期凭证（source_doc_type=RECURRING_SCHEME + source_doc_id=scheme + period）。"""
    return (await ctx.db.execute(
        select(m.Voucher).where(
            m.Voucher.source_doc_type == SRC_RECURRING,
            m.Voucher.source_doc_id == scheme_id,
            m.Voucher.period_id == period_id,
        ).order_by(m.Voucher.id)
    )).scalars().first()


async def _existing_scheme_count(ctx: CommandContext, company_id: int, scheme_id: int) -> int:
    rows = (await ctx.db.execute(
        select(m.Voucher.id).where(
            m.Voucher.company_id == company_id,
            m.Voucher.source_doc_type == SRC_RECURRING,
            m.Voucher.source_doc_id == scheme_id,
        )
    )).scalars().all()
    return len(rows)


@register_command(
    "finance.generate_recurring_voucher",
    module="FINANCE",
    title="生成定期凭证",
    description=(
        "按 RecurringVoucherScheme（自动转账/摊销/预提）+ 行模板生成一张 DRAFT 凭证。"
        "摊销取 total/periods 每期额并累进 amortized_periods；转账/预提取模板固定额或公式额。"
        "回链 RECURRING_SCHEME；同方案同期间已生成则幂等返回既有单。草稿态待审核过账。"
    ),
    affected_tables=("voucher", "voucher_entry", "recurring_voucher_scheme"),
    supports_retry=True,
)
async def generate_recurring_voucher(ctx: CommandContext, payload: dict) -> dict:
    """生成定期凭证（自动转账/摊销/预提）。

    payload：
      scheme_id: int          —— 定期凭证方案 id（必填）
      period_id: int          —— 目标会计期间 id（必填；凭证落此期）
      voucher_date: 'YYYY-MM-DD' —— 可选；不传取期间 end_date（缺则今日）

    口径：
      • 摊销 AMORTIZATION：每期额 = total_amount/periods（最后一期吃尾差）；amortized_periods 到达 periods 后
        不再生成（返回 created=False, 提示已摊完）。行模板（formula='total/periods' 或留空）取每期额，
        固定 amount 行按 amount。生成成功后 amortized_periods += 1。
      • 转账 TRANSFER / 预提 ACCRUAL：按模板行固定 amount 或公式额（不累进进度）。
      • 借贷不平（模板配错）→ 仍按模板落库（借贷平衡由过账闸 validator 拦），但金额合计 total_debit/credit 如实记。
    幂等：同 (scheme, period) 已有 RECURRING_SCHEME 凭证则返回既有单（摊销进度不重复累进）。
    """
    scheme_id = payload.get("scheme_id")
    period_id = payload.get("period_id")
    if not scheme_id:
        raise CommandError("scheme_id 不能为空")
    if not period_id:
        raise CommandError("period_id 不能为空")

    scheme = (await ctx.db.execute(
        select(m.RecurringVoucherScheme).where(m.RecurringVoucherScheme.id == scheme_id)
    )).scalar_one_or_none()
    if scheme is None:
        raise CommandError("定期凭证方案不存在", 404)
    _assert_company_access(ctx.user, scheme.company_id)
    company_id = scheme.company_id

    if not scheme.is_active:
        raise CommandError("该定期凭证方案已停用", 409)

    # 幂等：同方案同期间已生成 → 返回既有单。
    existing = await _existing_recurring_voucher(ctx, scheme_id, period_id)
    if existing:
        return {"created": False, "voucher_id": existing.id, "voucher_number": existing.voucher_number,
                "voucher_status": existing.status, "scheme_id": scheme_id, "period_id": period_id,
                "message": "本方案本期定期凭证已存在（幂等返回，未重复生成）"}

    # 目标期间（取 end_date 作凭证日期 default；校验期间存在且属本公司）。
    period_row = (await ctx.db.execute(
        select(m.AccountingPeriod, m.FiscalYear)
        .join(m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id)
        .where(m.AccountingPeriod.id == period_id)
    )).first()
    if period_row is None:
        raise CommandError("会计期间不存在", 404)
    period, fy = period_row
    if fy.company_id != company_id:
        raise CommandError("会计期间不属于方案所在公司", 422)

    voucher_date_raw = payload.get("voucher_date")
    if voucher_date_raw:
        voucher_date = (voucher_date_raw if isinstance(voucher_date_raw, date)
                        else date.fromisoformat(str(voucher_date_raw)[:10]))
    else:
        voucher_date = period.end_date or date.today()

    # 行模板（按 line_number）。
    lines = (await ctx.db.execute(
        select(m.RecurringVoucherLine)
        .where(m.RecurringVoucherLine.scheme_id == scheme_id)
        .order_by(m.RecurringVoucherLine.line_number)
    )).scalars().all()
    if not lines:
        raise CommandError("该方案无分录模板，无法生成", 422)

    # 摊销每期额（含到期判断 + 尾差）。
    per_period_amount = Decimal("0")
    is_amort = scheme.scheme_type == "AMORTIZATION"
    if is_amort:
        total = _num(scheme.total_amount)
        periods = int(scheme.periods or 0)
        done = int(scheme.amortized_periods or 0)
        if periods <= 0 or total == 0:
            raise CommandError("摊销方案缺 total_amount/periods，无法生成", 422)
        if done >= periods:
            return {"created": False, "voucher_id": None, "scheme_id": scheme_id, "period_id": period_id,
                    "message": f"该摊销方案已摊完（{done}/{periods} 期），不再生成"}
        base_each = _q2(total / Decimal(periods))
        if done == periods - 1:
            # 最后一期吃尾差：总额 - 已摊（前 periods-1 期均额）。
            per_period_amount = _q2(total - base_each * Decimal(periods - 1))
        else:
            per_period_amount = base_each

    # 模板行 → VoucherEntry 草稿行（本位币口径，原币=本位币 rate=1）。
    entries: list[dict] = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for ln in lines:
        account_id = await _account_for_line(ctx, company_id, ln)
        amt = _q2(_line_amount(scheme, ln, per_period_amount))
        is_debit = (ln.dr_cr or "DR").upper() == "DR"
        debit = amt if is_debit else Decimal("0")
        credit = Decimal("0") if is_debit else amt
        total_debit += debit
        total_credit += credit
        entries.append({
            "account_id": account_id,
            "description": (ln.description or scheme.description or scheme.name or "")[:200],
            "debit": debit, "credit": credit,
        })

    # 凭证字（方案默认；缺则取本公司「转」字）。
    word_id = scheme.voucher_word_id
    if word_id is None:
        w = (await ctx.db.execute(
            select(m.VoucherWord).where(
                m.VoucherWord.company_id == company_id, m.VoucherWord.code == "转",
            )
        )).scalar_one_or_none()
        word_id = w.id if w else None

    seq = (await _existing_scheme_count(ctx, company_id, scheme_id)) + 1
    voucher = m.Voucher(
        company_id=company_id,
        created_by_id=ctx.user.id,
        voucher_number=f"DQ-{scheme.code}-P{period.id}-{seq:03d}",
        voucher_date=voucher_date,
        period_id=period.id,
        voucher_word_id=word_id,
        voucher_type="GENERAL",
        description=(scheme.description or scheme.name or "定期凭证")[:200],
        total_debit=_q2(total_debit),
        total_credit=_q2(total_credit),
        status="DRAFT",
        is_auto_generated=True,
        source_doc_type=SRC_RECURRING,
        source_doc_id=scheme_id,
    )
    ctx.db.add(voucher)
    await ctx.db.flush()
    for idx, e in enumerate(entries, start=1):
        bd = _q2(_num(e["debit"]))
        bc = _q2(_num(e["credit"]))
        ctx.db.add(m.VoucherEntry(
            voucher_id=voucher.id,
            line_number=idx,
            account_id=e["account_id"],
            description=e["description"],
            debit=bd, credit=bc,
            currency="CNY",
            exchange_rate=Decimal("1"),
            base_debit=bd, base_credit=bc,
        ))
    await ctx.db.flush()

    # 摊销累进进度（生成成功才 +1）。
    if is_amort:
        scheme.amortized_periods = int(scheme.amortized_periods or 0) + 1
        await ctx.db.flush()

    ctx.add_event("finance_generate_recurring_voucher", {
        "scheme_id": scheme_id, "scheme_type": scheme.scheme_type, "period_id": period_id,
        "voucher_id": voucher.id, "per_period_amount": float(per_period_amount) if is_amort else None,
    })
    return {
        "created": True,
        "voucher_id": voucher.id,
        "voucher_number": voucher.voucher_number,
        "voucher_status": voucher.status,
        "scheme_id": scheme_id,
        "scheme_type": scheme.scheme_type,
        "period_id": period_id,
        "lines": len(entries),
        "total_debit": float(_q2(total_debit)),
        "total_credit": float(_q2(total_credit)),
        "per_period_amount": float(per_period_amount) if is_amort else None,
        "amortized_periods": int(scheme.amortized_periods or 0) if is_amort else None,
        "amort_periods": int(scheme.periods or 0) if is_amort else None,
        "message": "定期凭证已生成（草稿）；请审核并过账",
    }
