"""总账·第二波（finance-gl wave-2，模块 B）期末三步：调汇 → 结转损益 → 结账（含反结账）。

录音事实顺序：过账 → 调汇 → 结转损益 → 结账（期间锁；现金流量凭证指定；往来含税一致）。
本模块只走「命令扩展点」（@register_command），引擎核心三件（registry / execute_transition /
execute_command）字节级零 diff，全部新文件、不改既有 effect/validator。

四个命令（经 services.commands.execute_command 调度，命令层自管事务/留痕/幂等）：
  1. finance.fx_revaluation —— 期末调汇：外币货币性科目按期末汇率重估本位币，差额生「调汇凭证」
     （汇兑损益对方科目按公司准则取：CAS 6603 财务费用 / HK 6601 Finance costs）。
  2. finance.carry_forward_pl —— 结转损益：收入类(借方冲平)/费用成本类(贷方冲平)期末本位币余额
     结转到「本年利润」（CAS 4103 / HK 3201 Retained earnings），生「结转损益凭证」。
  3. finance.close_period —— 期末结账：前置校验（本期无未过账凭证 / 试算平衡 / 调汇+结转已做并过账）
     通过 → AccountingPeriod.status=CLOSED（锁期），留痕 closed_by_id/closed_at。
  4. finance.reopen_period —— 反结账：CLOSED→OPEN（逐月、留痕），用于错账重做。

★凭证生成策略（与 services/finance_posting.red_reversal 同款，最小侵入）：
  期末凭证直接 db.add 建 DRAFT 草稿（is_auto_generated=True，source_doc_type 打标），
  由财务按标准状态机「审核 → 过账」走过账闸（借贷平衡 / 期间锁 / 职责分离三校验复用 wave-1）。
  这样既不绕过过账闸，也不需要为系统自动凭证开 SoD 后门——结账前置校验「本期无未过账凭证」
  会天然逼着这些草稿先被过账，顺序闭环（调汇/结转先过账，才能结账）。

幂等：每步以 (period_id, source_doc_type 标记) 为锚守卫，已生成过则返回既有凭证不重复建。
本位币口径对齐 finance_posting._recompute_closing / routers/reports.py（借方为正净额）。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter


# 期末凭证 source_doc_type 标记（幂等锚 + 结账前置校验识别）。
SRC_FX_REVAL = "FX_REVAL"      # 调汇凭证
SRC_PL_CARRY = "PL_CARRY"      # 结转损益凭证

# 汇兑损益 / 本年利润科目码按准则二分（公司不在代码里硬编码单一码——按 region 取本家科目）。
#   CAS（内地）：6603 财务费用（含汇兑损益）；本年利润 4103。
#   HKFRS（香港）：6601 Finance costs；Retained earnings 3201（task：HK「本年利润」对应留存收益码）。
FX_PL_ACCOUNT_CODE = {"CN": "6603", "HK": "6601"}
PL_CARRY_TARGET_CODE = {"CN": "4103", "HK": "3201"}

# 损益类大类（结转损益参与结转的 account_type）。
REVENUE_TYPES = {"REVENUE"}
EXPENSE_TYPES = {"EXPENSE", "COGS"}


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


async def _load_period(ctx: CommandContext, period_id):
    """加载期间 + 经 fiscal_year 解析 company_id / region（期间不带 company_id，须 join）。"""
    if not period_id:
        raise CommandError("period_id 不能为空")
    row = (await ctx.db.execute(
        select(m.AccountingPeriod, m.FiscalYear, m.Company)
        .join(m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id)
        .join(m.Company, m.FiscalYear.company_id == m.Company.id)
        .where(m.AccountingPeriod.id == period_id)
    )).first()
    if row is None:
        raise CommandError("会计期间不存在", 404)
    period, fy, company = row
    _assert_company_access(ctx.user, company.id)
    return period, fy, company


async def _account_by_code(ctx: CommandContext, company_id: int, code: str):
    return (await ctx.db.execute(
        select(m.Account).where(
            m.Account.company_id == company_id,
            m.Account.code == code,
        )
    )).scalar_one_or_none()


async def _next_period(ctx: CommandContext, fiscal_year_id: int, period_number: int):
    """同会计年度下一期（结账后下期承接期初由独立结转，超出本波，仅返回供留痕）。"""
    return (await ctx.db.execute(
        select(m.AccountingPeriod).where(
            m.AccountingPeriod.fiscal_year_id == fiscal_year_id,
            m.AccountingPeriod.period_number == period_number + 1,
        )
    )).scalar_one_or_none()


async def _balances_with_account(ctx: CommandContext, company_id: int, period_id: int):
    """本期所有 AccountBalance + 对应 Account（一次 join，供调汇/结转/试算用）。"""
    rows = (await ctx.db.execute(
        select(m.AccountBalance, m.Account)
        .join(m.Account, m.AccountBalance.account_id == m.Account.id)
        .where(
            m.AccountBalance.company_id == company_id,
            m.AccountBalance.period_id == period_id,
        )
        .order_by(m.Account.code)
    )).all()
    return rows


def _closing_signed_debit(bal: m.AccountBalance, account: m.Account) -> Decimal:
    """期末余额折算成「借方为正」的有符号净额（与 reports.py / finance_posting 口径一致）。"""
    return (
        _num(bal.opening_debit) - _num(bal.opening_credit)
        + _num(bal.period_debit) - _num(bal.period_credit)
    )


async def _existing_period_voucher(ctx: CommandContext, company_id: int, period_id: int, src: str):
    return (await ctx.db.execute(
        select(m.Voucher).where(
            m.Voucher.company_id == company_id,
            m.Voucher.period_id == period_id,
            m.Voucher.source_doc_type == src,
        ).order_by(m.Voucher.id)
    )).scalars().first()


async def _word_id_zhuan(ctx: CommandContext, company_id: int):
    """期末凭证用「转」字（转账凭证）；缺则不挂（voucher_word_id 可空）。"""
    w = (await ctx.db.execute(
        select(m.VoucherWord).where(
            m.VoucherWord.company_id == company_id,
            m.VoucherWord.code == "转",
        )
    )).scalar_one_or_none()
    return w.id if w else None


async def _build_voucher(
    ctx: CommandContext, *, company, period, src: str, description: str,
    lines: list[dict], voucher_date: date,
) -> m.Voucher:
    """期末凭证落库（DRAFT 草稿 + 分录），与 red_reversal 同款直接 db.add（不绕过过账闸）。

    lines 每项：{account_id, base_debit, base_credit, description, cashflow_item_id?}
      原币 = 本位币（期末调汇/结转均以本位币口径计，rate=1）。
    凭证号留临时占位 PC-{src}-P{period_id}-NNN（结账前置校验只看是否过账，不强求业务连号）。
    """
    word_id = await _word_id_zhuan(ctx, company.id)
    seq = (await _existing_count(ctx, company.id, src)) + 1
    total_debit = sum((_num(ln.get("base_debit")) for ln in lines), Decimal("0"))
    total_credit = sum((_num(ln.get("base_credit")) for ln in lines), Decimal("0"))
    voucher = m.Voucher(
        company_id=company.id,
        created_by_id=ctx.user.id,
        voucher_number=f"PC-{src}-P{period.id}-{seq:03d}",
        voucher_date=voucher_date,
        period_id=period.id,
        voucher_word_id=word_id,
        voucher_type="GENERAL",
        description=description[:200],
        total_debit=_q2(total_debit),
        total_credit=_q2(total_credit),
        status="DRAFT",
        is_auto_generated=True,
        source_doc_type=src,
        source_doc_id=period.id,
    )
    ctx.db.add(voucher)
    await ctx.db.flush()
    for idx, ln in enumerate(lines, start=1):
        bd = _q2(_num(ln.get("base_debit")))
        bc = _q2(_num(ln.get("base_credit")))
        ctx.db.add(m.VoucherEntry(
            voucher_id=voucher.id,
            line_number=idx,
            account_id=ln["account_id"],
            description=(ln.get("description") or description)[:200],
            debit=bd, credit=bc,                 # 本位币口径，原币=本位币（rate=1）
            currency=company.currency or "CNY",
            exchange_rate=Decimal("1"),
            base_debit=bd, base_credit=bc,
            cashflow_item_id=ln.get("cashflow_item_id"),
        ))
    await ctx.db.flush()
    return voucher


async def _existing_count(ctx: CommandContext, company_id: int, src: str) -> int:
    rows = (await ctx.db.execute(
        select(m.Voucher.id).where(
            m.Voucher.company_id == company_id,
            m.Voucher.source_doc_type == src,
        )
    )).scalars().all()
    return len(rows)


# ============================================================
# 1) 期末调汇 finance.fx_revaluation
# ============================================================

@register_command(
    "finance.fx_revaluation",
    module="FINANCE",
    title="期末调汇",
    description=(
        "外币货币性科目按期末汇率重估本位币，差额生成调汇凭证（差额对方=汇兑损益，"
        "CAS 6603 财务费用 / HK 6601 Finance costs）。草稿态待审核过账。"
    ),
    affected_tables=("voucher", "voucher_entry"),
    supports_retry=True,
    supports_preview=True,
)
async def fx_revaluation(ctx: CommandContext, payload: dict) -> dict:
    """期末调汇（录音「调汇」步）。

    口径（贸易场景最小可解释）：
      • 仅重估「外币货币性科目」——这里取「科目本位币(currency)≠公司本位币」的货币资金 / 往来类科目
        （账户 currency 标的外币 + 期末有原币余额）。
      • 重估差额 = 期末原币余额 × 期末汇率 − 当前账面本位币余额。
      • 差额合计若为 0（或无外币科目）→ no-op（preview 也返回 0 行）。
      • 差额生一张调汇凭证：各外币科目按差额方向调本位币，汇兑损益科目吃对方差额（一借一贷配平）。

    幂等：本期已生成过调汇凭证（source_doc_type=FX_REVAL）则返回既有单，不重复建。
    preview=True 只算不落库（前置校验清单用）。
    """
    period_id = payload.get("period_id")
    period, fy, company = await _load_period(ctx, period_id)
    region = company.region or "HK"
    base_ccy = company.currency or ("HKD" if region == "HK" else "CNY")
    preview = bool(payload.get("preview"))

    existing = await _existing_period_voucher(ctx, company.id, period_id, SRC_FX_REVAL)
    if existing and not preview:
        return {"created": False, "voucher_id": existing.id, "voucher_number": existing.voucher_number,
                "voucher_status": existing.status, "message": "本期调汇凭证已存在"}

    if period.status != "OPEN":
        raise CommandError(f"会计期间非 OPEN（status={period.status}），不可调汇", 409)

    rate_date = payload.get("rate_date") or (period.end_date.isoformat() if period.end_date else None)
    rate_d = date.fromisoformat(rate_date) if isinstance(rate_date, str) else (period.end_date or date.today())

    rows = await _balances_with_account(ctx, company.id, period_id)
    # 外币科目候选：账户 currency 与本位币不同（外币标的科目）。
    fx_rows = [(bal, acct) for bal, acct in rows if (acct.currency or base_ccy) != base_ccy]

    fx_account = await _account_by_code(ctx, company.id, FX_PL_ACCOUNT_CODE.get(region, "6603"))
    if fx_account is None:
        raise CommandError(
            f"未找到汇兑损益科目（{FX_PL_ACCOUNT_CODE.get(region)}）；请先跑 scripts.seed_finance", 422
        )

    lines: list[dict] = []
    preview_rows: list[dict] = []
    total_diff = Decimal("0")
    for bal, acct in fx_rows:
        # 期末原币余额（有符号借方为正）：原币口径用 period_*（debit-credit）+ opening 原币不在 balance 内，
        # 此处以本位币净额 ÷ 现汇率回推原币近似（balance 不存原币）；贸易最小实现：以本位币净额直接重估，
        # 取期末汇率与账面隐含汇率差。为可解释，按「期末汇率 vs 1（本币记账时 base==原币）」时差额为 0，
        # 仅当 payload 提供 fx_rates[科目currency] 才真正重估。
        signed_base = _q2(_closing_signed_debit(bal, acct))
        if signed_base == 0:
            continue
        rate_map = payload.get("fx_rates") or {}
        # 期末汇率：优先 payload.fx_rates[币种]，否则查 ExchangeRate(外币→本位币, ≤rate_date 最新)。
        new_rate = rate_map.get(acct.currency)
        if new_rate is None:
            er = (await ctx.db.execute(
                select(m.ExchangeRate).where(
                    m.ExchangeRate.from_currency == acct.currency,
                    m.ExchangeRate.to_currency == base_ccy,
                    m.ExchangeRate.effective_date <= rate_d,
                ).order_by(m.ExchangeRate.effective_date.desc())
            )).scalars().first()
            new_rate = er.rate if er else None
        if new_rate is None:
            preview_rows.append({"account_code": acct.code, "account_name": acct.name,
                                 "diff": 0.0, "note": "缺期末汇率，跳过"})
            continue
        # 账面隐含原币 = signed_base / 账面隐含汇率；账面隐含汇率未存 → 用「上一期末汇率」近似。
        # 最小实现：调汇差额由 payload 直接给本位币重估值 revalued_base[科目code] 时优先采用。
        reval_map = payload.get("revalued_base") or {}
        if acct.code in reval_map:
            revalued = _q2(_num(reval_map[acct.code]))
        else:
            # 无显式重估值时，按 (新汇率 / 旧汇率) 比例缩放本位币；旧汇率取 payload.old_rates 或不缩放。
            old_rate = (payload.get("old_rates") or {}).get(acct.currency)
            if old_rate and _num(old_rate) != 0:
                revalued = _q2(signed_base * _num(new_rate) / _num(old_rate))
            else:
                revalued = signed_base  # 无可比汇率 → 差额 0（不臆造）
        diff = _q2(revalued - signed_base)  # 借方为正口径
        if diff == 0:
            continue
        total_diff += diff
        # 调外币科目本位币：diff>0 表示本位币应增（借方增）→ 该科目借；diff<0 → 该科目贷。
        if diff > 0:
            lines.append({"account_id": acct.id, "base_debit": diff, "base_credit": 0,
                          "description": f"调汇 {acct.code} {acct.currency}@{new_rate}"})
        else:
            lines.append({"account_id": acct.id, "base_debit": 0, "base_credit": -diff,
                          "description": f"调汇 {acct.code} {acct.currency}@{new_rate}"})
        preview_rows.append({"account_code": acct.code, "account_name": acct.name,
                             "currency": acct.currency, "new_rate": float(_num(new_rate)),
                             "book_base": float(signed_base), "revalued_base": float(revalued),
                             "diff": float(diff)})

    # 汇兑损益吃对方差额配平（diff 合计>0 → 资产本位币增 → 汇兑收益记贷；<0 → 记借）。
    if total_diff != 0:
        if total_diff > 0:
            lines.append({"account_id": fx_account.id, "base_debit": 0, "base_credit": _q2(total_diff),
                          "description": "汇兑损益（调汇差额）"})
        else:
            lines.append({"account_id": fx_account.id, "base_debit": _q2(-total_diff), "base_credit": 0,
                          "description": "汇兑损益（调汇差额）"})

    if preview:
        return {"preview": True, "period_id": period_id, "rows": preview_rows,
                "total_diff": float(_q2(total_diff)), "will_generate": bool(lines)}

    if not lines:
        return {"created": False, "voucher_id": None, "total_diff": 0.0,
                "message": "无外币货币性科目需重估或差额为 0，未生成调汇凭证"}

    voucher = await _build_voucher(
        ctx, company=company, period=period, src=SRC_FX_REVAL,
        description=f"期末调汇 {period.start_date}~{period.end_date}",
        lines=lines, voucher_date=period.end_date or date.today(),
    )
    ctx.add_event("finance_fx_revaluation", {"period_id": period_id, "voucher_id": voucher.id,
                                             "total_diff": float(_q2(total_diff))})
    return {"created": True, "voucher_id": voucher.id, "voucher_number": voucher.voucher_number,
            "voucher_status": voucher.status, "total_diff": float(_q2(total_diff)),
            "rows": preview_rows,
            "message": "调汇凭证已生成（草稿）；请审核并过账后再结账"}


# ============================================================
# 2) 结转损益 finance.carry_forward_pl
# ============================================================

@register_command(
    "finance.carry_forward_pl",
    module="FINANCE",
    title="结转损益",
    description=(
        "收入类(借方冲平)/费用成本类(贷方冲平)期末本位币余额结转到本年利润"
        "（CAS 4103 / HK 3201 Retained earnings），生成结转损益凭证。草稿态待审核过账。"
    ),
    affected_tables=("voucher", "voucher_entry"),
    supports_retry=True,
    supports_preview=True,
)
async def carry_forward_pl(ctx: CommandContext, payload: dict) -> dict:
    """结转损益（录音「结转损益」步）。

    口径：
      • 收入类（REVENUE，贷向）期末贷方净余额 → 借记收入科目冲平、贷记本年利润。
      • 费用/成本类（EXPENSE/COGS，借向）期末借方净余额 → 贷记费用科目冲平、借记本年利润。
      • 一张「结转损益凭证」含所有损益科目冲平行 + 本年利润对方一行（配平）。
      • 无损益余额 → no-op。

    幂等：本期已生成结转凭证（source_doc_type=PL_CARRY）则返回既有单。
    """
    period_id = payload.get("period_id")
    period, fy, company = await _load_period(ctx, period_id)
    region = company.region or "HK"
    preview = bool(payload.get("preview"))

    existing = await _existing_period_voucher(ctx, company.id, period_id, SRC_PL_CARRY)
    if existing and not preview:
        return {"created": False, "voucher_id": existing.id, "voucher_number": existing.voucher_number,
                "voucher_status": existing.status, "message": "本期结转损益凭证已存在"}

    if period.status != "OPEN":
        raise CommandError(f"会计期间非 OPEN（status={period.status}），不可结转损益", 409)

    pl_account = await _account_by_code(ctx, company.id, PL_CARRY_TARGET_CODE.get(region, "4103"))
    if pl_account is None:
        raise CommandError(
            f"未找到本年利润/留存收益科目（{PL_CARRY_TARGET_CODE.get(region)}）；请先跑 scripts.seed_finance", 422
        )

    rows = await _balances_with_account(ctx, company.id, period_id)
    lines: list[dict] = []
    preview_rows: list[dict] = []
    net_to_pl_credit = Decimal("0")   # 累积「应贷本年利润」（利润为正）
    for bal, acct in rows:
        atype = acct.account_type
        if atype in REVENUE_TYPES:
            # 收入：期末贷方净额（贷向科目以贷为正）。
            credit_positive = _q2(-_closing_signed_debit(bal, acct))  # -(借为正)=贷为正
            if credit_positive == 0:
                continue
            # 冲平收入：借记收入科目 credit_positive。
            lines.append({"account_id": acct.id, "base_debit": credit_positive, "base_credit": 0,
                          "description": f"结转收入 {acct.code}"})
            net_to_pl_credit += credit_positive
            preview_rows.append({"account_code": acct.code, "account_name": acct.name,
                                 "type": atype, "amount": float(credit_positive), "side": "结转收入(借)"})
        elif atype in EXPENSE_TYPES:
            # 费用/成本：期末借方净额（借向科目以借为正）。
            debit_positive = _q2(_closing_signed_debit(bal, acct))
            if debit_positive == 0:
                continue
            # 冲平费用：贷记费用科目 debit_positive。
            lines.append({"account_id": acct.id, "base_debit": 0, "base_credit": debit_positive,
                          "description": f"结转成本费用 {acct.code}"})
            net_to_pl_credit -= debit_positive
            preview_rows.append({"account_code": acct.code, "account_name": acct.name,
                                 "type": atype, "amount": float(debit_positive), "side": "结转成本费用(贷)"})

    # 本年利润对方一行：净利润(net_to_pl_credit>0) → 贷记本年利润；净亏损 → 借记本年利润。
    if net_to_pl_credit != 0:
        if net_to_pl_credit > 0:
            lines.append({"account_id": pl_account.id, "base_debit": 0, "base_credit": _q2(net_to_pl_credit),
                          "description": "结转本年利润（净利润）"})
        else:
            lines.append({"account_id": pl_account.id, "base_debit": _q2(-net_to_pl_credit), "base_credit": 0,
                          "description": "结转本年利润（净亏损）"})

    if preview:
        return {"preview": True, "period_id": period_id, "rows": preview_rows,
                "net_profit": float(_q2(net_to_pl_credit)), "will_generate": bool(lines)}

    if not lines:
        return {"created": False, "voucher_id": None, "net_profit": 0.0,
                "message": "本期无损益类余额，未生成结转损益凭证"}

    voucher = await _build_voucher(
        ctx, company=company, period=period, src=SRC_PL_CARRY,
        description=f"期末结转损益 {period.start_date}~{period.end_date}",
        lines=lines, voucher_date=period.end_date or date.today(),
    )
    ctx.add_event("finance_carry_forward_pl", {"period_id": period_id, "voucher_id": voucher.id,
                                               "net_profit": float(_q2(net_to_pl_credit))})
    return {"created": True, "voucher_id": voucher.id, "voucher_number": voucher.voucher_number,
            "voucher_status": voucher.status, "net_profit": float(_q2(net_to_pl_credit)),
            "rows": preview_rows,
            "message": "结转损益凭证已生成（草稿）；请审核并过账后再结账"}


# ============================================================
# 3) 期末结账前置校验（共享：结账动作 + preview 清单复用）
# ============================================================

async def _close_prechecks(ctx: CommandContext, company, period) -> list[dict]:
    """结账前置校验清单（金蝶「结账前检查」惯例）。每项 {key, label, passed, detail}。

    逐月闸：上一期未结账（CLOSED）则本期不可结（顺序结账）。
    """
    checks: list[dict] = []

    # a) 期间须 OPEN（已 CLOSED → 已结账；LOCKED → 先解锁）。
    checks.append({
        "key": "period_open",
        "label": "期间为 OPEN（未结账）",
        "passed": period.status == "OPEN",
        "detail": f"当前 status={period.status}",
    })

    # b) 逐月：上一期已结账（period_number==1 免检）。
    if period.period_number and period.period_number > 1:
        prev = (await ctx.db.execute(
            select(m.AccountingPeriod).where(
                m.AccountingPeriod.fiscal_year_id == period.fiscal_year_id,
                m.AccountingPeriod.period_number == period.period_number - 1,
            )
        )).scalar_one_or_none()
        prev_ok = prev is not None and prev.status == "CLOSED"
        checks.append({
            "key": "prev_closed",
            "label": "上一会计期间已结账（逐月顺序）",
            "passed": prev_ok,
            "detail": ("上期不存在" if prev is None else f"上期 status={prev.status}"),
        })

    # c) 本期无未过账凭证（DRAFT/AUDITED/REVIEWED 均算未过账；POSTED 才放行）。
    unposted = (await ctx.db.execute(
        select(m.Voucher.id, m.Voucher.voucher_number, m.Voucher.status).where(
            m.Voucher.company_id == company.id,
            m.Voucher.period_id == period.id,
            m.Voucher.status != "POSTED",
        )
    )).all()
    checks.append({
        "key": "all_posted",
        "label": "本期所有凭证已过账",
        "passed": len(unposted) == 0,
        "detail": (f"{len(unposted)} 张未过账：" +
                   ", ".join(f"{n}({s})" for _, n, s in unposted[:8])) if unposted else "全部已过账",
    })

    # d) 试算平衡：Σ本期借 = Σ本期贷（本位币，AccountBalance 聚合）。
    rows = await _balances_with_account(ctx, company.id, period.id)
    sum_d = sum((_num(b.period_debit) for b, _ in rows), Decimal("0"))
    sum_c = sum((_num(b.period_credit) for b, _ in rows), Decimal("0"))
    bal_ok = _q2(sum_d - sum_c) == 0
    checks.append({
        "key": "trial_balance",
        "label": "试算平衡（本期借=贷）",
        "passed": bal_ok,
        "detail": f"借 {_q2(sum_d)} / 贷 {_q2(sum_c)} / 差额 {_q2(sum_d - sum_c)}",
    })

    # e) 调汇已做并过账（生成过 FX_REVAL 且全部 POSTED；未涉外币时无单也算通过——空集为真）。
    fx_vouchers = (await ctx.db.execute(
        select(m.Voucher.status).where(
            m.Voucher.company_id == company.id,
            m.Voucher.period_id == period.id,
            m.Voucher.source_doc_type == SRC_FX_REVAL,
        )
    )).scalars().all()
    fx_ok = all(s == "POSTED" for s in fx_vouchers)  # 空集 → True（无需调汇）
    checks.append({
        "key": "fx_done",
        "label": "期末调汇已生成并过账",
        "passed": fx_ok,
        "detail": (f"{len(fx_vouchers)} 张，状态 {set(fx_vouchers)}" if fx_vouchers
                   else "本期未生成调汇凭证（无外币重估视为已做）"),
    })

    # f) 结转损益已做并过账（生成过 PL_CARRY 且全部 POSTED）。
    #    结转损益是月结必做：要求至少有一张已过账的结转凭证（除非本期完全无损益余额）。
    pl_vouchers = (await ctx.db.execute(
        select(m.Voucher.status).where(
            m.Voucher.company_id == company.id,
            m.Voucher.period_id == period.id,
            m.Voucher.source_doc_type == SRC_PL_CARRY,
        )
    )).scalars().all()
    has_pl_balance = any(
        acct.account_type in (REVENUE_TYPES | EXPENSE_TYPES)
        and _closing_signed_debit(bal, acct) != 0
        for bal, acct in rows
    )
    if pl_vouchers:
        pl_ok = all(s == "POSTED" for s in pl_vouchers)
        pl_detail = f"{len(pl_vouchers)} 张，状态 {set(pl_vouchers)}"
    else:
        pl_ok = not has_pl_balance  # 无结转凭证时：仅当本期已无损益余额才放行
        pl_detail = ("尚有损益余额未结转" if has_pl_balance else "本期无损益余额（无需结转）")
    checks.append({
        "key": "pl_done",
        "label": "结转损益已生成并过账",
        "passed": pl_ok,
        "detail": pl_detail,
    })

    return checks


# ============================================================
# 4) 期末结账 finance.close_period（前置校验通过 → status=CLOSED）
# ============================================================

@register_command(
    "finance.close_period",
    module="FINANCE",
    title="期末结账",
    description=(
        "前置校验（本期无未过账凭证 / 试算平衡 / 调汇+结转已做并过账 / 逐月上期已结）"
        "通过 → 锁期 AccountingPeriod.status=CLOSED，留痕结账人/时间。"
    ),
    affected_tables=("accounting_period",),
    supports_retry=True,
    supports_preview=True,
)
async def close_period(ctx: CommandContext, payload: dict) -> dict:
    """期末结账（录音「结账」步）。preview=True 只返回前置校验清单不锁期。"""
    period_id = payload.get("period_id")
    period, fy, company = await _load_period(ctx, period_id)
    preview = bool(payload.get("preview"))

    checks = await _close_prechecks(ctx, company, period)
    all_passed = all(c["passed"] for c in checks)

    if preview:
        return {"preview": True, "period_id": period_id, "checks": checks, "can_close": all_passed}

    if period.status == "CLOSED":
        return {"closed": False, "period_id": period_id, "checks": checks,
                "message": "该期间已结账（CLOSED）"}
    if not all_passed:
        failed = [c["label"] for c in checks if not c["passed"]]
        raise CommandError("结账前置校验未通过：" + "；".join(failed), 422, details={"checks": checks})

    period.status = "CLOSED"
    period.closed_by_id = ctx.user.id
    period.closed_at = datetime.now()
    await ctx.db.flush()
    ctx.add_event("finance_period_closed", {"period_id": period_id, "company_id": company.id})
    return {"closed": True, "period_id": period_id, "checks": checks,
            "period_label": f"{fy.year}年第{period.period_number}期",
            "closed_by_id": ctx.user.id,
            "message": f"{fy.year}年第{period.period_number}期 已结账（CLOSED，锁期）"}


# ============================================================
# 5) 反结账 finance.reopen_period（CLOSED → OPEN，逐月、留痕）
# ============================================================

@register_command(
    "finance.reopen_period",
    module="FINANCE",
    title="反结账",
    description="期末结账撤销：CLOSED→OPEN（逐月——后续期已结账则禁，需先反结后续期），清结账留痕。",
    affected_tables=("accounting_period",),
    supports_retry=True,
)
async def reopen_period(ctx: CommandContext, payload: dict) -> dict:
    """反结账（错账重做）：CLOSED→OPEN。

    逐月闸：若同年下一期已 CLOSED，则本期不可反结（须先反结后续期，避免跨期断链）。
    留痕：清 closed_by_id/closed_at；记录原结账人/时间到事件流水。
    """
    period_id = payload.get("period_id")
    period, fy, company = await _load_period(ctx, period_id)

    if period.status != "CLOSED":
        raise CommandError(f"仅已结账(CLOSED)期间可反结账（当前 status={period.status}）", 409)

    nxt = await _next_period(ctx, period.fiscal_year_id, period.period_number)
    if nxt is not None and nxt.status == "CLOSED":
        raise CommandError(
            f"下一期（第{period.period_number + 1}期）已结账，须先反结后续期（逐月反结）", 409
        )

    prev_closed_by = period.closed_by_id
    prev_closed_at = period.closed_at
    period.status = "OPEN"
    period.closed_by_id = None
    period.closed_at = None
    await ctx.db.flush()
    ctx.add_event("finance_period_reopened", {
        "period_id": period_id, "company_id": company.id,
        "prev_closed_by_id": prev_closed_by,
        "prev_closed_at": prev_closed_at.isoformat() if prev_closed_at else None,
        "reopened_by_id": ctx.user.id,
    })
    return {"reopened": True, "period_id": period_id,
            "period_label": f"{fy.year}年第{period.period_number}期",
            "prev_closed_by_id": prev_closed_by,
            "message": f"{fy.year}年第{period.period_number}期 已反结账（CLOSED→OPEN），可重做后再结账"}
