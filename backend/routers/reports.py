"""报表路由：试算平衡表 / 科目余额表 / 账龄分析"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import get_db
from services.tools import _company_filter

router = APIRouter(prefix="/api/reports")


def _dec(v) -> float:
    return float(v) if v else 0.0


@router.get("/trial_balance")
async def trial_balance(
    period_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """试算平衡表：按科目汇总 期初/本期/期末 借贷，末行验证借贷平衡"""
    company_ids = _company_filter(user)

    # 查 account_balance + account
    stmt = (
        select(m.AccountBalance, m.Account)
        .join(m.Account, m.AccountBalance.account_id == m.Account.id)
        .where(m.AccountBalance.period_id == period_id)
    )
    if company_ids:
        stmt = stmt.where(m.AccountBalance.company_id.in_(company_ids))

    result = await db.execute(stmt)
    rows = result.all()

    data = []
    totals = dict(
        opening_debit=0, opening_credit=0,
        period_debit=0, period_credit=0,
        closing_debit=0, closing_credit=0,
    )
    for bal, acct in rows:
        row = {
            "account_code": acct.code,
            "account_name": acct.name,
            "account_type": acct.account_type,
            "balance_direction": acct.balance_direction,
            "opening_debit": _dec(bal.opening_debit),
            "opening_credit": _dec(bal.opening_credit),
            "period_debit": _dec(bal.period_debit),
            "period_credit": _dec(bal.period_credit),
            "closing_debit": _dec(bal.closing_debit),
            "closing_credit": _dec(bal.closing_credit),
        }
        data.append(row)
        for k in totals:
            totals[k] += row[k]

    data.sort(key=lambda r: r["account_code"])

    # 平衡断言（试算平衡）：期初/本期/期末 三栏均须 Σ借=Σ贷。
    balance_checks = {
        "opening": abs(totals["opening_debit"] - totals["opening_credit"]) < 0.01,
        "period": abs(totals["period_debit"] - totals["period_credit"]) < 0.01,
        "closing": abs(totals["closing_debit"] - totals["closing_credit"]) < 0.01,
    }

    return {
        "report": "trial_balance",
        "period_id": period_id,
        "data": data,
        "totals": totals,
        "balance_checks": balance_checks,
        # 向后兼容：balanced 仍取期末断言；全平衡看 all_balanced。
        "balanced": balance_checks["closing"],
        "all_balanced": all(balance_checks.values()),
    }


@router.get("/account_balance")
async def account_balance(
    period_id: int = Query(...),
    account_code_from: str | None = Query(None, description="科目代码范围下界（含），按字符串字典序比较"),
    account_code_to: str | None = Query(None, description="科目代码范围上界（含），按字符串字典序比较"),
    include_unposted: bool = Query(False, description="含未过账（默认 False=只算已 POSTED；True=叠加 DRAFT/AUDITED/REVIEWED 凭证发生额）"),
    show_zero: bool = Query(False, description="零值显隐（默认 False=隐藏期初/发生/期末全为 0 的科目）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """科目余额表（金蝶逆向·账表壳）：按 company+期间+科目范围 出 期初/本期发生/期末（借贷双栏，本位币）。

    口径开关：
    - include_unposted=False（默认）：仅 AccountBalance（过账派生），与试算平衡表同源。
    - include_unposted=True：在过账余额之上叠加「未过账凭证」(status 非 POSTED) 的本位币发生额到本期/期末，
      供月底估算用；返回 unposted_period_debit/credit 单列展示叠加量。

    余额方向净额列 net_balance：DEBIT 科目=借-贷，CREDIT 科目=贷-借。
    """
    company_ids = _company_filter(user)

    stmt = (
        select(m.AccountBalance, m.Account)
        .join(m.Account, m.AccountBalance.account_id == m.Account.id)
        .where(m.AccountBalance.period_id == period_id)
    )
    if company_ids:
        stmt = stmt.where(m.AccountBalance.company_id.in_(company_ids))
    if account_code_from is not None:
        stmt = stmt.where(m.Account.code >= account_code_from)
    if account_code_to is not None:
        stmt = stmt.where(m.Account.code <= account_code_to)

    result = await db.execute(stmt)
    rows = result.all()

    # 含未过账：取本期间内 status != POSTED 的凭证分录本位币发生额，按 account_id 聚合。
    unposted_by_acct: dict[int, dict[str, float]] = {}
    if include_unposted:
        ustmt = (
            select(
                m.VoucherEntry.account_id,
                func.coalesce(func.sum(m.VoucherEntry.base_debit), 0),
                func.coalesce(func.sum(m.VoucherEntry.base_credit), 0),
            )
            .join(m.Voucher, m.VoucherEntry.voucher_id == m.Voucher.id)
            .where(m.Voucher.period_id == period_id)
            .where(m.Voucher.status != "POSTED")
            .group_by(m.VoucherEntry.account_id)
        )
        if company_ids:
            ustmt = ustmt.where(m.Voucher.company_id.in_(company_ids))
        for acct_id, ud, uc in (await db.execute(ustmt)).all():
            unposted_by_acct[acct_id] = {"debit": _dec(ud), "credit": _dec(uc)}

    data = []
    for bal, acct in rows:
        up = unposted_by_acct.get(acct.id, {"debit": 0.0, "credit": 0.0})
        period_d = _dec(bal.period_debit) + up["debit"]
        period_c = _dec(bal.period_credit) + up["credit"]
        # 期末 = 期初 + 本期（含未过账叠加），按余额方向规整到单边。
        if acct.balance_direction == "DEBIT":
            net = (_dec(bal.opening_debit) - _dec(bal.opening_credit)) + (period_d - period_c)
            closing_d = net if net >= 0 else 0.0
            closing_c = -net if net < 0 else 0.0
            net_balance = net
        else:
            net = (_dec(bal.opening_credit) - _dec(bal.opening_debit)) + (period_c - period_d)
            closing_c = net if net >= 0 else 0.0
            closing_d = -net if net < 0 else 0.0
            net_balance = net

        if not show_zero:
            allzero = all(abs(v) < 0.005 for v in (
                _dec(bal.opening_debit), _dec(bal.opening_credit),
                period_d, period_c, closing_d, closing_c,
            ))
            if allzero:
                continue

        data.append({
            "account_id": acct.id,
            "account_code": acct.code,
            "account_name": acct.name,
            "account_type": acct.account_type,
            "balance_direction": acct.balance_direction,
            "opening_debit": _dec(bal.opening_debit),
            "opening_credit": _dec(bal.opening_credit),
            "period_debit": period_d,
            "period_credit": period_c,
            "unposted_period_debit": up["debit"],
            "unposted_period_credit": up["credit"],
            "closing_debit": closing_d,
            "closing_credit": closing_c,
            "net_balance": net_balance,
            "direction_label": "借" if acct.balance_direction == "DEBIT" else "贷",
        })

    data.sort(key=lambda r: r["account_code"])
    return {
        "report": "account_balance",
        "period_id": period_id,
        "include_unposted": include_unposted,
        "show_zero": show_zero,
        "data": data,
    }


@router.get("/detail_ledger")
async def detail_ledger(
    period_id: int = Query(...),
    account_code_from: str | None = Query(None, description="科目代码范围下界（含）"),
    account_code_to: str | None = Query(None, description="科目代码范围上界（含）"),
    include_unposted: bool = Query(False, description="含未过账（默认 False=只列 POSTED 凭证分录）"),
    aux_party_type: str | None = Query(None, description="按辅助核算往来对象类型过滤 CUSTOMER/SUPPLIER/EMPLOYEE…"),
    aux_party_id: int | None = Query(None, description="按辅助核算往来对象主键过滤（配合 aux_party_type）"),
    aux_dept_id: int | None = Query(None, description="按辅助核算部门过滤"),
    aux_project_id: int | None = Query(None, description="按辅助核算项目过滤"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """明细分类账（金蝶逆向）：逐科目列凭证分录明细（日期/凭证字号/摘要/借/贷/方向/滚动余额）。

    - 默认只列已过账（POSTED）凭证；include_unposted=True 时一并列出未过账凭证（行带 posted=False 标记）。
    - 每科目以本期间 AccountBalance.opening 为期初行，按 voucher_date→voucher_number 顺序滚动累计余额（本位币）。
    - 滚动余额方向随科目 balance_direction：DEBIT 科目 余额=Σ借-Σ贷，CREDIT 科目 余额=Σ贷-Σ借。
    - 行内含 voucher_id 供前端下钻凭证。
    """
    company_ids = _company_filter(user)

    # 1) 选中科目（受公司+范围约束），建 account_id→account 索引并保期初。
    acct_stmt = select(m.Account)
    if company_ids:
        acct_stmt = acct_stmt.where(m.Account.company_id.in_(company_ids))
    if account_code_from is not None:
        acct_stmt = acct_stmt.where(m.Account.code >= account_code_from)
    if account_code_to is not None:
        acct_stmt = acct_stmt.where(m.Account.code <= account_code_to)
    accounts = (await db.execute(acct_stmt)).scalars().all()
    acct_index = {a.id: a for a in accounts}
    if not acct_index:
        return {"report": "detail_ledger", "period_id": period_id,
                "include_unposted": include_unposted, "accounts": []}

    # 2) 期初余额（本期间 AccountBalance.opening）。
    obal_stmt = (
        select(m.AccountBalance)
        .where(m.AccountBalance.period_id == period_id)
        .where(m.AccountBalance.account_id.in_(list(acct_index.keys())))
    )
    if company_ids:
        obal_stmt = obal_stmt.where(m.AccountBalance.company_id.in_(company_ids))
    opening = {
        b.account_id: (_dec(b.opening_debit), _dec(b.opening_credit))
        for b in (await db.execute(obal_stmt)).scalars().all()
    }

    # 3) 凭证分录明细（join voucher + voucher_word），本期间内、口径过滤、辅助核算过滤。
    stmt = (
        select(m.VoucherEntry, m.Voucher, m.VoucherWord)
        .join(m.Voucher, m.VoucherEntry.voucher_id == m.Voucher.id)
        .outerjoin(m.VoucherWord, m.Voucher.voucher_word_id == m.VoucherWord.id)
        .where(m.Voucher.period_id == period_id)
        .where(m.VoucherEntry.account_id.in_(list(acct_index.keys())))
        .order_by(m.Voucher.voucher_date, m.Voucher.voucher_number, m.VoucherEntry.line_number)
    )
    if company_ids:
        stmt = stmt.where(m.Voucher.company_id.in_(company_ids))
    if not include_unposted:
        stmt = stmt.where(m.Voucher.status == "POSTED")
    if aux_party_type is not None:
        stmt = stmt.where(m.VoucherEntry.aux_party_type == aux_party_type)
    if aux_party_id is not None:
        stmt = stmt.where(m.VoucherEntry.aux_party_id == aux_party_id)
    if aux_dept_id is not None:
        stmt = stmt.where(m.VoucherEntry.aux_dept_id == aux_dept_id)
    if aux_project_id is not None:
        stmt = stmt.where(m.VoucherEntry.aux_project_id == aux_project_id)

    rows = (await db.execute(stmt)).all()

    # 4) 按科目分组 + 滚动余额。
    grouped: dict[int, list] = {aid: [] for aid in acct_index}
    for entry, vch, word in rows:
        grouped[entry.account_id].append((entry, vch, word))

    accounts_out = []
    for aid, acct in sorted(acct_index.items(), key=lambda kv: kv[1].code):
        entries = grouped.get(aid, [])
        opn_d, opn_c = opening.get(aid, (0.0, 0.0))
        if acct.balance_direction == "DEBIT":
            running = opn_d - opn_c
        else:
            running = opn_c - opn_d
        opening_balance = running

        lines = []
        sum_debit = 0.0
        sum_credit = 0.0
        for entry, vch, word in entries:
            d = _dec(entry.base_debit)
            c = _dec(entry.base_credit)
            if acct.balance_direction == "DEBIT":
                running += d - c
            else:
                running += c - d
            sum_debit += d
            sum_credit += c
            word_code = word.code if word else (vch.voucher_type or "")
            lines.append({
                "voucher_id": vch.id,
                "voucher_date": vch.voucher_date.isoformat() if vch.voucher_date else None,
                "voucher_word": word_code,
                "voucher_number": vch.voucher_number,
                "voucher_label": f"{word_code}-{vch.voucher_number}" if word_code else vch.voucher_number,
                "line_number": entry.line_number,
                "description": entry.description or vch.description or "",
                "debit": d,
                "credit": c,
                "running_balance": round(running, 2),
                "direction_label": "借" if acct.balance_direction == "DEBIT" else "贷",
                "posted": vch.status == "POSTED",
                "voucher_status": vch.status,
                "aux_party_type": entry.aux_party_type,
                "aux_party_id": entry.aux_party_id,
                "currency": entry.currency,
            })

        # 无发生且期初为零的科目，默认不输出（避免空账页刷屏）。
        if not lines and abs(opening_balance) < 0.005:
            continue

        accounts_out.append({
            "account_id": acct.id,
            "account_code": acct.code,
            "account_name": acct.name,
            "balance_direction": acct.balance_direction,
            "direction_label": "借" if acct.balance_direction == "DEBIT" else "贷",
            "opening_balance": round(opening_balance, 2),
            "period_debit": round(sum_debit, 2),
            "period_credit": round(sum_credit, 2),
            "closing_balance": round(running, 2),
            "lines": lines,
        })

    return {
        "report": "detail_ledger",
        "period_id": period_id,
        "include_unposted": include_unposted,
        "accounts": accounts_out,
    }


@router.get("/general_ledger")
async def general_ledger(
    period_id: int = Query(...),
    account_code_from: str | None = Query(None, description="科目代码范围下界（含）"),
    account_code_to: str | None = Query(None, description="科目代码范围上界（含）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """总分类账（金蝶逆向）：按科目汇总 年初余额 / 本期合计（借贷）/ 本年累计（借贷）/ 期末余额。

    全部派生自 AccountBalance（已过账口径）：
    - 年初余额：取该 company+account 在本会计年度首期(period_number 最小)的 opening。
    - 本期合计：本期间 period_debit/period_credit。
    - 本年累计：该 company+account 从年初到本期间(含)各期 period_debit/credit 求和。
    - 期末余额：本期间 closing 按余额方向取净额。
    """
    company_ids = _company_filter(user)

    # 定位本期间所属会计年度 + period_number（用于「年初」「本年累计」窗口）。
    cur_period = (await db.execute(
        select(m.AccountingPeriod).where(m.AccountingPeriod.id == period_id)
    )).scalar_one_or_none()
    if cur_period is None:
        return {"report": "general_ledger", "period_id": period_id, "data": []}
    fiscal_year_id = cur_period.fiscal_year_id
    cur_pnum = cur_period.period_number

    # 本年度全部期间 id + period_number。
    year_periods = (await db.execute(
        select(m.AccountingPeriod.id, m.AccountingPeriod.period_number)
        .where(m.AccountingPeriod.fiscal_year_id == fiscal_year_id)
    )).all()
    period_num_map = {pid: pnum for pid, pnum in year_periods}
    ytd_period_ids = [pid for pid, pnum in year_periods if pnum <= cur_pnum]
    first_pnum = min((pnum for _, pnum in year_periods), default=cur_pnum)
    first_period_ids = [pid for pid, pnum in year_periods if pnum == first_pnum]

    # 选中科目。
    acct_stmt = select(m.Account)
    if company_ids:
        acct_stmt = acct_stmt.where(m.Account.company_id.in_(company_ids))
    if account_code_from is not None:
        acct_stmt = acct_stmt.where(m.Account.code >= account_code_from)
    if account_code_to is not None:
        acct_stmt = acct_stmt.where(m.Account.code <= account_code_to)
    accounts = (await db.execute(acct_stmt)).scalars().all()
    acct_index = {a.id: a for a in accounts}
    if not acct_index:
        return {"report": "general_ledger", "period_id": period_id, "data": []}

    # 拉本年度该科目集合的全部 AccountBalance 行，一次查内存聚合。
    bal_stmt = (
        select(m.AccountBalance)
        .where(m.AccountBalance.account_id.in_(list(acct_index.keys())))
        .where(m.AccountBalance.period_id.in_([pid for pid, _ in year_periods]))
    )
    if company_ids:
        bal_stmt = bal_stmt.where(m.AccountBalance.company_id.in_(company_ids))
    bals = (await db.execute(bal_stmt)).scalars().all()

    # account_id → 聚合容器。
    agg: dict[int, dict] = {}
    for b in bals:
        a = agg.setdefault(b.account_id, {
            "year_opening_debit": 0.0, "year_opening_credit": 0.0,
            "period_debit": 0.0, "period_credit": 0.0,
            "ytd_debit": 0.0, "ytd_credit": 0.0,
            "closing_debit": 0.0, "closing_credit": 0.0,
        })
        if b.period_id in first_period_ids:
            a["year_opening_debit"] += _dec(b.opening_debit)
            a["year_opening_credit"] += _dec(b.opening_credit)
        if b.period_id == period_id:
            a["period_debit"] += _dec(b.period_debit)
            a["period_credit"] += _dec(b.period_credit)
            a["closing_debit"] += _dec(b.closing_debit)
            a["closing_credit"] += _dec(b.closing_credit)
        if b.period_id in ytd_period_ids:
            a["ytd_debit"] += _dec(b.period_debit)
            a["ytd_credit"] += _dec(b.period_credit)

    data = []
    for aid, acct in sorted(acct_index.items(), key=lambda kv: kv[1].code):
        a = agg.get(aid)
        if a is None:
            continue
        if acct.balance_direction == "DEBIT":
            year_opening = a["year_opening_debit"] - a["year_opening_credit"]
            closing = a["closing_debit"] - a["closing_credit"]
        else:
            year_opening = a["year_opening_credit"] - a["year_opening_debit"]
            closing = a["closing_credit"] - a["closing_debit"]
        data.append({
            "account_id": acct.id,
            "account_code": acct.code,
            "account_name": acct.name,
            "account_type": acct.account_type,
            "balance_direction": acct.balance_direction,
            "direction_label": "借" if acct.balance_direction == "DEBIT" else "贷",
            "year_opening_balance": round(year_opening, 2),
            "period_debit": round(a["period_debit"], 2),
            "period_credit": round(a["period_credit"], 2),
            "ytd_debit": round(a["ytd_debit"], 2),
            "ytd_credit": round(a["ytd_credit"], 2),
            "closing_balance": round(closing, 2),
        })

    return {
        "report": "general_ledger",
        "period_id": period_id,
        "fiscal_year_id": fiscal_year_id,
        "period_number": cur_pnum,
        "data": data,
    }


@router.get("/voucher-summary")
async def voucher_summary(
    company_id: int | None = Query(None, description="按公司过滤；不传则取用户可见公司范围"),
    period_from: int = Query(..., description="起始会计期间 id（含）"),
    period_to: int | None = Query(None, description="结束会计期间 id（含）；不传=单期，等于 period_from"),
    include_unposted: bool = Query(False, description="含未过账（默认 False=只汇总已 POSTED 凭证分录；True=全状态凭证分录）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """凭证汇总表（科目发生额汇总）：按科目 sum 区间内本期借/贷（本位币），供批量工作台核对用。

    口径（复用明细分类账取数风格，直接对 VoucherEntry 聚合）：
    - 区间：voucher 所属 period_id 在 [period_from, period_to] 之间（period_to 缺省=period_from 单期）。
    - 默认只汇总已过账（POSTED）凭证分录；include_unposted=True 时纳入全状态凭证分录。
    - 公司：company_id 指定则单公司（须在用户可见范围）；否则取 _company_filter(user) 范围。
    - 每行：科目 + 借方合计 + 贷方合计 + 净额（按余额方向：DEBIT 科目=借-贷，CREDIT=贷-借）。
    - 末尾 totals 给区间 Σ借/Σ贷 与平衡断言。
    """
    company_ids = _company_filter(user)
    if company_id is not None:
        if company_ids and company_id not in company_ids:
            return {"report": "voucher_summary", "period_from": period_from,
                    "period_to": period_to or period_from, "data": [], "totals": {},
                    "balanced": True, "error": "无权访问该公司"}
        company_ids = [company_id]

    p_to = period_to or period_from
    lo, hi = (period_from, p_to) if period_from <= p_to else (p_to, period_from)

    stmt = (
        select(
            m.VoucherEntry.account_id,
            func.coalesce(func.sum(m.VoucherEntry.base_debit), 0),
            func.coalesce(func.sum(m.VoucherEntry.base_credit), 0),
            func.count(func.distinct(m.Voucher.id)),
        )
        .join(m.Voucher, m.VoucherEntry.voucher_id == m.Voucher.id)
        .where(m.Voucher.period_id >= lo, m.Voucher.period_id <= hi)
        .group_by(m.VoucherEntry.account_id)
    )
    if company_ids:
        stmt = stmt.where(m.Voucher.company_id.in_(company_ids))
    if not include_unposted:
        stmt = stmt.where(m.Voucher.status == "POSTED")

    rows = (await db.execute(stmt)).all()

    # 一次取齐相关科目（代码/名称/方向）。
    acct_ids = [aid for aid, _, _, _ in rows]
    acct_index: dict[int, m.Account] = {}
    if acct_ids:
        accts = (await db.execute(
            select(m.Account).where(m.Account.id.in_(acct_ids))
        )).scalars().all()
        acct_index = {a.id: a for a in accts}

    data = []
    total_debit = 0.0
    total_credit = 0.0
    for acct_id, dr, cr, vcount in rows:
        acct = acct_index.get(acct_id)
        d = _dec(dr)
        c = _dec(cr)
        direction = getattr(acct, "balance_direction", "DEBIT") if acct else "DEBIT"
        net = (d - c) if direction == "DEBIT" else (c - d)
        data.append({
            "account_id": acct_id,
            "account_code": acct.code if acct else "",
            "account_name": acct.name if acct else "",
            "account_type": acct.account_type if acct else "",
            "balance_direction": direction,
            "direction_label": "借" if direction == "DEBIT" else "贷",
            "period_debit": round(d, 2),
            "period_credit": round(c, 2),
            "net_balance": round(net, 2),
            "voucher_count": int(vcount),
        })
        total_debit += d
        total_credit += c

    data.sort(key=lambda r: r["account_code"])
    return {
        "report": "voucher_summary",
        "period_from": lo,
        "period_to": hi,
        "include_unposted": include_unposted,
        "data": data,
        "totals": {
            "period_debit": round(total_debit, 2),
            "period_credit": round(total_credit, 2),
        },
        "balanced": abs(total_debit - total_credit) < 0.01,
    }


@router.get("/aging_analysis")
async def aging_analysis(
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """账龄分析：未清应收款按到期日分桶"""
    company_ids = _company_filter(user)

    stmt = (
        select(m.AccountsReceivable, m.Customer)
        .join(m.Customer, m.AccountsReceivable.customer_id == m.Customer.id)
        .where(m.AccountsReceivable.status.notin_(["CLOSED", "SETTLED"]))
    )
    if company_ids:
        stmt = stmt.where(m.AccountsReceivable.company_id.in_(company_ids))

    result = await db.execute(stmt)
    rows = result.all()

    today = date.today()
    data = []
    bucket_totals = {"current": 0, "d1_30": 0, "d31_60": 0, "d61_90": 0, "d90_plus": 0}

    for ar, cust in rows:
        outstanding = _dec(ar.amount) - _dec(ar.paid_amount)
        if outstanding <= 0:
            continue

        overdue_days = (today - ar.due_date).days if ar.due_date else 0
        if overdue_days <= 0:
            bucket = "current"
        elif overdue_days <= 30:
            bucket = "d1_30"
        elif overdue_days <= 60:
            bucket = "d31_60"
        elif overdue_days <= 90:
            bucket = "d61_90"
        else:
            bucket = "d90_plus"

        row = {
            "customer_name": cust.name,
            "customer_code": cust.code,
            "invoice_number": ar.invoice_number,
            "amount": _dec(ar.amount),
            "paid_amount": _dec(ar.paid_amount),
            "outstanding": outstanding,
            "due_date": ar.due_date.isoformat() if ar.due_date else None,
            "overdue_days": max(overdue_days, 0),
            "bucket": bucket,
            "currency": ar.currency,
        }
        data.append(row)
        bucket_totals[bucket] += outstanding

    return {
        "report": "aging_analysis",
        "data": data,
        "bucket_totals": bucket_totals,
        "total_outstanding": sum(bucket_totals.values()),
    }


@router.get("/ar-open-items")
async def ar_open_items(
    company_id: int | None = Query(None, description="公司 id（缺则取用户可见公司范围首个）"),
    party_id: int | None = Query(None, description="客户 id（核销界面按客户筛选）"),
    currency: str | None = Query(None, description="币别（核销须同币种，按币别筛选）"),
    biz_type: str = Query("AR", description="业务类型 AR 应收 / AP 应付（通用核销引擎）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """待核销项（核销界面取数）：左栏未核销应收（债权）+ 右栏未核销收款（已收）两栏。

    供前端通用核销界面（biz_type=AR/AP）一次取齐两侧未核销单据（写off_status != VERIFIED，须 AUDITED），
    每项带 open_amount（未核销原币额）/ exchange_rate / 已核销额 / 核销状态，前端据此勾选配对后调
    finance.writeoff（手工 links）或 auto=True（按方案自动）。
    """
    from services.finance_writeoff import _config, _doc_brief, list_open_ar, list_open_receipts

    company_ids = _company_filter(user)
    if company_id is None:
        company_id = company_ids[0] if company_ids else user.company_id
    elif company_ids and company_id not in company_ids:
        return {"report": "ar_open_items", "company_id": company_id, "biz_type": biz_type,
                "debit_items": [], "credit_items": [], "error": "无权访问该公司"}

    cfg = _config(biz_type)
    debits = await list_open_ar(
        db, company_id=company_id, party_id=party_id, currency=currency, biz_type=biz_type)
    credits = await list_open_receipts(
        db, company_id=company_id, party_id=party_id, currency=currency, biz_type=biz_type)

    debit_items = [_doc_brief(d, cfg.debit) for d in debits]
    credit_items = [_doc_brief(c, cfg.credit) for c in credits]
    return {
        "report": "ar_open_items",
        "company_id": company_id,
        "biz_type": biz_type,
        "party_id": party_id,
        "currency": currency,
        "debit_items": debit_items,    # 未核销应收（债权侧）
        "credit_items": credit_items,  # 未核销收款（已收侧）
        "total_open_debit": round(sum(i["open_amount"] for i in debit_items), 2),
        "total_open_credit": round(sum(i["open_amount"] for i in credit_items), 2),
    }


# ============================================================
# 三大财务报表（finance-gl wave-5）：资产负债表 / 利润表 / 现金流量表 / 核算维度余额表
# 只读端点，取数底座：AccountBalance（余额/发生额真相）+ VoucherEntry（现金流量项目归集）。
# 准则二分由 Company.region 决定（HK→HKFRS / CN→CAS），行项目映射用文件内常量表
# （科目码集合/account_type → 报表行），不在业务代码里硬编码单条科目。
# ============================================================

# --- 报表行项目映射常量（科目码 → 报表行）。code 集按 seed_finance 的 CAS/HKFRS 科目表锚定。 ---
# 资产负债表行：每行 = (line_key, 中文标题, 英文标题, 取数 account_type 约束, 科目码集合 或 None=全归该类型)。
# 「科目码集合」非空时按 code 精确归集；为 None 时该行兜底吃掉本 account_type 下未被上面行认领的余科目。

# CAS 资产负债表（流动资产/非流动资产/流动负债/非流动负债/所有者权益）。
_CAS_BS_ASSET_CURRENT = [
    ("monetary_funds", "货币资金", "Monetary funds", {"1001", "1002", "1012"}),
    ("trade_receivables", "应收账款", "Trade receivables", {"1122", "1231"}),
    ("prepayments", "预付账款", "Prepayments", {"1123"}),
    ("other_receivables", "其他应收款", "Other receivables", {"1221"}),
    ("inventories", "存货", "Inventories", {"1401", "1402", "1403", "1405", "1408", "1471"}),
]
_CAS_BS_ASSET_NONCURRENT = [
    ("fixed_assets", "固定资产", "Fixed assets", {"1601", "1602"}),
    ("intangible_assets", "无形资产", "Intangible assets", {"1701", "1702"}),
]
_CAS_BS_LIAB_CURRENT = [
    ("short_term_loans", "短期借款", "Short-term loans", {"2001"}),
    ("trade_payables", "应付账款", "Trade payables", {"2202"}),
    ("advances_from_customers", "预收账款", "Advances from customers", {"2203"}),
    ("payroll_payable", "应付职工薪酬", "Payroll payable", {"2211"}),
    ("taxes_payable", "应交税费", "Taxes payable", {"2221", "222101", "222102", "222106"}),
    ("other_payables", "其他应付款", "Other payables", {"2241"}),
]
_CAS_BS_LIAB_NONCURRENT = [
    ("long_term_loans", "长期借款", "Long-term loans", {"2501"}),
]
_CAS_BS_EQUITY = [
    ("paid_in_capital", "实收资本", "Paid-in capital", {"4001"}),
    ("capital_reserve", "资本公积", "Capital reserve", {"4002"}),
    ("surplus_reserve", "盈余公积", "Surplus reserve", {"4101"}),
    ("retained_earnings", "未分配利润", "Retained earnings", {"4103", "4104"}),
]

# HKFRS 资产负债表（Non-current/Current assets · liabilities · Equity）。
_HKFRS_BS_ASSET_NONCURRENT = [
    ("ppe", "物业、厂房及设备", "Property, plant and equipment", {"1601", "1602"}),
    ("intangible_assets", "无形资产", "Intangible assets", {"1701", "1702"}),
]
_HKFRS_BS_ASSET_CURRENT = [
    ("inventories", "存货", "Inventories", {"1211", "1212", "1291"}),
    ("trade_receivables", "应收账款", "Trade receivables", {"1122", "1191"}),
    ("prepayments", "预付款项", "Prepayments and other receivables", {"1123", "1131", "1141"}),
    ("cash_and_equivalents", "现金及现金等价物", "Cash and cash equivalents", {"1001", "1002", "1012"}),
]
_HKFRS_BS_LIAB_CURRENT = [
    ("trade_payables", "应付账款", "Trade payables", {"2202"}),
    ("accruals_other_payables", "应计费用及其他应付款", "Accruals and other payables", {"2211", "2231"}),
    ("advances_from_customers", "预收款项", "Receipts in advance", {"2203"}),
    ("bank_borrowings", "银行借款", "Bank borrowings", {"2101"}),
    ("tax_payable", "应交税项", "Tax payable", {"2221"}),
]
_HKFRS_BS_LIAB_NONCURRENT = [
    ("deferred_tax", "递延税项负债", "Deferred tax liabilities", {"2401"}),
]
_HKFRS_BS_EQUITY = [
    ("share_capital", "股本", "Share capital", {"3001"}),
    ("share_premium", "股份溢价", "Share premium", {"3002"}),
    ("reserves", "储备", "Reserves", {"3101"}),
    ("retained_earnings", "留存收益", "Retained earnings", {"3201", "3301"}),
]

# 利润表行：每行 = (line_key, 中文, 英文, sign, 科目码集合)。sign=+1 计入收入侧/-1 计入扣减侧，净利润累加。
# CAS 利润表（营业收入-营业成本-税金-费用 + 营业外 = 利润总额-所得税=净利润）。
_CAS_IS_LINES = [
    ("operating_revenue", "营业收入", "Operating revenue", +1, {"6001", "6051"}),
    ("operating_cost", "营业成本", "Operating cost", -1, {"6401", "6402"}),
    ("taxes_surcharges", "税金及附加", "Taxes and surcharges", -1, {"6403"}),
    ("selling_expenses", "销售费用", "Selling expenses", -1, {"6601"}),
    ("admin_expenses", "管理费用", "Administrative expenses", -1, {"6602"}),
    ("finance_expenses", "财务费用", "Finance expenses", -1, {"6603"}),
    ("investment_income", "投资收益", "Investment income", +1, {"6111"}),
    ("non_operating_income", "营业外收入", "Non-operating income", +1, {"6301"}),
    ("non_operating_expense", "营业外支出", "Non-operating expense", -1, {"6711"}),
    ("income_tax", "所得税费用", "Income tax expense", -1, {"6801"}),
]
# HKFRS 利润表（Revenue - Cost of sales = Gross profit; + Other income - opex - finance - tax）。
_HKFRS_IS_LINES = [
    ("revenue", "营业收入", "Revenue", +1, {"6001"}),
    ("cost_of_sales", "销售成本", "Cost of sales", -1, {"5001"}),
    ("other_income", "其他收入", "Other income", +1, {"6051", "6061", "6071"}),
    ("selling_distribution", "销售及分销费用", "Selling and distribution expenses", -1, {"6401"}),
    ("administrative_expenses", "行政费用", "Administrative expenses", -1, {"6501", "6502", "6503"}),
    ("finance_costs", "财务费用", "Finance costs", -1, {"6601"}),
    ("other_expenses", "其他费用", "Other expenses", -1, {"6701"}),
    ("income_tax", "所得税费用", "Income tax expense", -1, {"6801"}),
]


def _resolve_report_company(user, company_id):
    """三大报表强制单公司口径：解析并鉴权 company_id。

    返回 (company_id, error)。company_id 必传（报表按公司+准则出，不混算）。
    privileged 只读（_company_filter→None）放行任意公司；普通用户须在可见集内。
    """
    if company_id is None:
        return None, "company_id 必传（财务报表按单公司+准则口径出具）"
    company_ids = _company_filter(user)
    if company_ids is not None and company_id not in company_ids:
        return None, "无权访问该公司"
    return company_id, None


async def _get_company(db, company_id):
    return (await db.execute(
        select(m.Company).where(m.Company.id == company_id)
    )).scalar_one_or_none()


async def _period_year_window(db, period_id):
    """定位 period 所属会计年度，返回 (cur_period, fiscal_year_id, cur_pnum,
    ytd_period_ids, first_period_ids)。period 不存在返回全 None。"""
    cur = (await db.execute(
        select(m.AccountingPeriod).where(m.AccountingPeriod.id == period_id)
    )).scalar_one_or_none()
    if cur is None:
        return None, None, None, [], []
    year_periods = (await db.execute(
        select(m.AccountingPeriod.id, m.AccountingPeriod.period_number)
        .where(m.AccountingPeriod.fiscal_year_id == cur.fiscal_year_id)
    )).all()
    cur_pnum = cur.period_number
    ytd_ids = [pid for pid, pnum in year_periods if pnum <= cur_pnum]
    first_pnum = min((pnum for _, pnum in year_periods), default=cur_pnum)
    first_ids = [pid for pid, pnum in year_periods if pnum == first_pnum]
    return cur, cur.fiscal_year_id, cur_pnum, ytd_ids, first_ids


def _signed_net(acct_type, balance_direction, debit, credit):
    """按余额方向返回净额（DEBIT 科目=借-贷；CREDIT 科目=贷-借）。备抵科目方向已独立标，直接用 balance_direction。"""
    if balance_direction == "DEBIT":
        return debit - credit
    return credit - debit


@router.get("/balance-sheet")
async def balance_sheet(
    company_id: int = Query(..., description="公司 id（必传，报表按单公司+准则口径出具）"),
    period_id: int = Query(..., description="会计期间 id（出期末数；年初数取同会计年度首期 opening）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """资产负债表（Balance Sheet）：按 company 准则（HKFRS/CAS）归集科目期末数+年初数。

    取数（全部 AccountBalance 已过账口径，本位币）：
    - 期末数 closing：本期间各科目 closing 按余额方向取净额。
    - 年初数 opening：本会计年度首期(period_number 最小)的 opening 按余额方向取净额。
    - 资产/负债/权益分组与流动/非流动拆分按准则常量表（_CAS_BS_* / _HKFRS_BS_*）。
    - 损益结平差额（本年利润未结转部分）并入「未分配利润/留存收益」行，保证 资产=负债+权益 恒等。
    校验：assets_total == liabilities_total + equity_total（误差 < 0.01 视为平衡）。
    """
    cid, err = _resolve_report_company(user, company_id)
    if err:
        return {"report": "balance_sheet", "company_id": company_id, "period_id": period_id,
                "data": {}, "error": err}
    company = await _get_company(db, cid)
    if company is None:
        return {"report": "balance_sheet", "company_id": company_id, "period_id": period_id,
                "data": {}, "error": "公司不存在"}
    standard = "HKFRS" if company.region == "HK" else "CAS"

    _, fiscal_year_id, _, _, first_period_ids = await _period_year_window(db, period_id)
    if fiscal_year_id is None:
        return {"report": "balance_sheet", "company_id": cid, "period_id": period_id,
                "standard": standard, "data": {}, "error": "会计期间不存在"}

    # 一次取本公司全部科目 + 本期 closing / 首期 opening。
    accts = (await db.execute(
        select(m.Account).where(m.Account.company_id == cid)
    )).scalars().all()
    acct_index = {a.id: a for a in accts}

    bal_period_ids = list({period_id, *first_period_ids})
    bals = (await db.execute(
        select(m.AccountBalance)
        .where(m.AccountBalance.company_id == cid)
        .where(m.AccountBalance.period_id.in_(bal_period_ids))
        .where(m.AccountBalance.account_id.in_(list(acct_index.keys())) if acct_index else False)
    )).scalars().all()

    # account_id → (closing_net, opening_net)（按余额方向）。
    by_acct: dict[int, dict] = {}
    for b in bals:
        acct = acct_index.get(b.account_id)
        if acct is None:
            continue
        slot = by_acct.setdefault(b.account_id, {"closing": 0.0, "opening": 0.0})
        if b.period_id == period_id:
            slot["closing"] += _signed_net(
                acct.account_type, acct.balance_direction,
                _dec(b.closing_debit), _dec(b.closing_credit))
        if b.period_id in first_period_ids:
            slot["opening"] += _signed_net(
                acct.account_type, acct.balance_direction,
                _dec(b.opening_debit), _dec(b.opening_credit))

    # code → (closing, opening)，供行映射查。
    code_amt: dict[str, dict] = {}
    for aid, slot in by_acct.items():
        acct = acct_index[aid]
        code_amt[acct.code] = {"closing": slot["closing"], "opening": slot["opening"]}

    def _section(rows):
        out, tot_c, tot_o = [], 0.0, 0.0
        for line_key, cn, en, codes in rows:
            c = sum(code_amt.get(code, {}).get("closing", 0.0) for code in codes)
            o = sum(code_amt.get(code, {}).get("opening", 0.0) for code in codes)
            tot_c += c
            tot_o += o
            out.append({
                "line_key": line_key, "label": cn, "label_en": en,
                "closing": round(c, 2), "opening": round(o, 2),
            })
        return out, round(tot_c, 2), round(tot_o, 2)

    if standard == "CAS":
        ac, ac_c, ac_o = _section(_CAS_BS_ASSET_CURRENT)
        anc, anc_c, anc_o = _section(_CAS_BS_ASSET_NONCURRENT)
        lc, lc_c, lc_o = _section(_CAS_BS_LIAB_CURRENT)
        lnc, lnc_c, lnc_o = _section(_CAS_BS_LIAB_NONCURRENT)
        eq, eq_c, eq_o = _section(_CAS_BS_EQUITY)
        asset_groups = [
            {"group_key": "current_assets", "label": "流动资产", "label_en": "Current assets",
             "lines": ac, "subtotal_closing": ac_c, "subtotal_opening": ac_o},
            {"group_key": "non_current_assets", "label": "非流动资产", "label_en": "Non-current assets",
             "lines": anc, "subtotal_closing": anc_c, "subtotal_opening": anc_o},
        ]
        liab_groups = [
            {"group_key": "current_liabilities", "label": "流动负债", "label_en": "Current liabilities",
             "lines": lc, "subtotal_closing": lc_c, "subtotal_opening": lc_o},
            {"group_key": "non_current_liabilities", "label": "非流动负债", "label_en": "Non-current liabilities",
             "lines": lnc, "subtotal_closing": lnc_c, "subtotal_opening": lnc_o},
        ]
        equity_label, equity_label_en = "所有者权益", "Owner's equity"
        retained_key = "retained_earnings"
    else:
        anc, anc_c, anc_o = _section(_HKFRS_BS_ASSET_NONCURRENT)
        ac, ac_c, ac_o = _section(_HKFRS_BS_ASSET_CURRENT)
        lc, lc_c, lc_o = _section(_HKFRS_BS_LIAB_CURRENT)
        lnc, lnc_c, lnc_o = _section(_HKFRS_BS_LIAB_NONCURRENT)
        eq, eq_c, eq_o = _section(_HKFRS_BS_EQUITY)
        asset_groups = [
            {"group_key": "non_current_assets", "label": "非流动资产", "label_en": "Non-current assets",
             "lines": anc, "subtotal_closing": anc_c, "subtotal_opening": anc_o},
            {"group_key": "current_assets", "label": "流动资产", "label_en": "Current assets",
             "lines": ac, "subtotal_closing": ac_c, "subtotal_opening": ac_o},
        ]
        liab_groups = [
            {"group_key": "current_liabilities", "label": "流动负债", "label_en": "Current liabilities",
             "lines": lc, "subtotal_closing": lc_c, "subtotal_opening": lc_o},
            {"group_key": "non_current_liabilities", "label": "非流动负债", "label_en": "Non-current liabilities",
             "lines": lnc, "subtotal_closing": lnc_c, "subtotal_opening": lnc_o},
        ]
        equity_label, equity_label_en = "权益", "Equity"
        retained_key = "retained_earnings"

    assets_total_c = round(ac_c + anc_c, 2)
    assets_total_o = round(ac_o + anc_o, 2)
    liab_total_c = round(lc_c + lnc_c, 2)
    liab_total_o = round(lc_o + lnc_o, 2)

    # 损益未结转差额并入留存收益：BS 不列损益类，但 P&L 净额须落权益才平。
    # 差额 = 资产 -（负债+权益已列科目），加到 retained_earnings 行（期末/年初分别算）。
    eq_listed_c, eq_listed_o = eq_c, eq_o
    plug_c = round(assets_total_c - liab_total_c - eq_listed_c, 2)
    plug_o = round(assets_total_o - liab_total_o - eq_listed_o, 2)
    for row in eq:
        if row["line_key"] == retained_key:
            row["closing"] = round(row["closing"] + plug_c, 2)
            row["opening"] = round(row["opening"] + plug_o, 2)
            row["includes_unposted_profit"] = True
            break
    equity_total_c = round(eq_listed_c + plug_c, 2)
    equity_total_o = round(eq_listed_o + plug_o, 2)

    return {
        "report": "balance_sheet",
        "company_id": cid,
        "company_code": company.code,
        "period_id": period_id,
        "standard": standard,
        "currency": company.currency,
        "data": {
            "assets": {
                "groups": asset_groups,
                "total_closing": assets_total_c,
                "total_opening": assets_total_o,
            },
            "liabilities": {
                "groups": liab_groups,
                "total_closing": liab_total_c,
                "total_opening": liab_total_o,
            },
            "equity": {
                "label": equity_label,
                "label_en": equity_label_en,
                "lines": eq,
                "total_closing": equity_total_c,
                "total_opening": equity_total_o,
            },
        },
        "check": {
            "assets_total": assets_total_c,
            "liabilities_plus_equity": round(liab_total_c + equity_total_c, 2),
            "balanced": abs(assets_total_c - (liab_total_c + equity_total_c)) < 0.01,
        },
    }


@router.get("/income-statement")
async def income_statement(
    company_id: int = Query(..., description="公司 id（必传，报表按单公司+准则口径出具）"),
    period_id: int = Query(..., description="会计期间 id（出本期数；本年累计=同年度 period_number≤当期 累加）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """利润表（Income Statement）：营业收入-营业成本-费用=净利润，本期数 + 本年累计。

    取数（AccountBalance 已过账口径，本位币）：
    - 本期数 period：本期间各损益科目 period_debit/period_credit 取发生净额（按 sign 计入收入/扣减）。
    - 本年累计 ytd：本会计年度 period_number≤当期 的各期发生额累加。
    - 行项目 + 符号按准则常量表（_CAS_IS_LINES / _HKFRS_IS_LINES）；net_profit=逐行 sign 累加。
    """
    cid, err = _resolve_report_company(user, company_id)
    if err:
        return {"report": "income_statement", "company_id": company_id, "period_id": period_id,
                "data": {}, "error": err}
    company = await _get_company(db, cid)
    if company is None:
        return {"report": "income_statement", "company_id": company_id, "period_id": period_id,
                "data": {}, "error": "公司不存在"}
    standard = "HKFRS" if company.region == "HK" else "CAS"

    _, fiscal_year_id, cur_pnum, ytd_period_ids, _ = await _period_year_window(db, period_id)
    if fiscal_year_id is None:
        return {"report": "income_statement", "company_id": cid, "period_id": period_id,
                "standard": standard, "data": {}, "error": "会计期间不存在"}

    accts = (await db.execute(
        select(m.Account).where(m.Account.company_id == cid)
    )).scalars().all()
    acct_index = {a.id: a for a in accts}

    bals = (await db.execute(
        select(m.AccountBalance)
        .where(m.AccountBalance.company_id == cid)
        .where(m.AccountBalance.period_id.in_(ytd_period_ids) if ytd_period_ids else False)
        .where(m.AccountBalance.account_id.in_(list(acct_index.keys())) if acct_index else False)
    )).scalars().all()

    # code → {period_net, ytd_net}，损益发生额按余额方向取净（收入类 CREDIT=贷-借；费用/成本 DEBIT=借-贷）。
    code_amt: dict[str, dict] = {}
    for b in bals:
        acct = acct_index.get(b.account_id)
        if acct is None:
            continue
        net = _signed_net(acct.account_type, acct.balance_direction,
                          _dec(b.period_debit), _dec(b.period_credit))
        slot = code_amt.setdefault(acct.code, {"period": 0.0, "ytd": 0.0})
        slot["ytd"] += net
        if b.period_id == period_id:
            slot["period"] += net

    lines_def = _CAS_IS_LINES if standard == "CAS" else _HKFRS_IS_LINES
    lines = []
    net_period = 0.0
    net_ytd = 0.0
    for line_key, cn, en, sign, codes in lines_def:
        # 收入类科目净额已是「贷方正」，费用/成本类已是「借方正」。
        # 行展示值取该类科目净额的绝对额（正常方向为正）；sign 标记其对净利润的加减。
        p = sum(code_amt.get(code, {}).get("period", 0.0) for code in codes)
        y = sum(code_amt.get(code, {}).get("ytd", 0.0) for code in codes)
        net_period += sign * p
        net_ytd += sign * y
        lines.append({
            "line_key": line_key, "label": cn, "label_en": en,
            "sign": sign,
            "period": round(p, 2), "ytd": round(y, 2),
        })

    return {
        "report": "income_statement",
        "company_id": cid,
        "company_code": company.code,
        "period_id": period_id,
        "period_number": cur_pnum,
        "standard": standard,
        "currency": company.currency,
        "data": {
            "lines": lines,
            "net_profit": {
                "label": "净利润",
                "label_en": "Net profit",
                "period": round(net_period, 2),
                "ytd": round(net_ytd, 2),
            },
        },
    }


@router.get("/cash-flow-statement")
async def cash_flow_statement(
    company_id: int = Query(..., description="公司 id（必传，报表按单公司口径出具）"),
    period_id: int = Query(..., description="会计期间 id（出本期数；本年累计=同年度 period_number≤当期 累加）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """现金流量表（Cash Flow Statement）：从已过账凭证分录的 cashflow_item 归集本期/本年累计。

    取数（已过账 VoucherEntry，本位币）：
    - 按 VoucherEntry.cashflow_item_id → CashflowItem 树（经营/投资/筹资，父项为分类锚点）归集。
    - 流量金额 = 该分录本位币发生额（base_debit/base_credit 取非零边的绝对值）；direction=IN/OUT 由 CashflowItem 标。
    - 经营/投资/筹资三大类 = 各自子项 (IN 之和 - OUT 之和)；现金净增加额 = 三类合计。
    - 现金类分录未标 cashflow_item 的（cashflow_item_id 为空）归「未分类」桶（unclassified），供财务补标。
    - 本期数 = 本期间凭证；本年累计 = 同会计年度 period_number≤当期 各期凭证累加。
    """
    cid, err = _resolve_report_company(user, company_id)
    if err:
        return {"report": "cash_flow_statement", "company_id": company_id, "period_id": period_id,
                "data": {}, "error": err}
    company = await _get_company(db, cid)
    if company is None:
        return {"report": "cash_flow_statement", "company_id": company_id, "period_id": period_id,
                "data": {}, "error": "公司不存在"}

    _, fiscal_year_id, cur_pnum, ytd_period_ids, _ = await _period_year_window(db, period_id)
    if fiscal_year_id is None:
        return {"report": "cash_flow_statement", "company_id": cid, "period_id": period_id,
                "data": {}, "error": "会计期间不存在"}

    # 现金流量项目树（本公司）。
    cf_items = (await db.execute(
        select(m.CashflowItem).where(m.CashflowItem.company_id == cid)
    )).scalars().all()
    cf_index = {c.id: c for c in cf_items}

    # 已过账凭证分录（本年度截至当期），按 cashflow_item_id 聚合本位币发生额（period / ytd）。
    rows = (await db.execute(
        select(
            m.VoucherEntry.cashflow_item_id,
            m.Voucher.period_id,
            func.coalesce(func.sum(m.VoucherEntry.base_debit), 0),
            func.coalesce(func.sum(m.VoucherEntry.base_credit), 0),
        )
        .join(m.Voucher, m.VoucherEntry.voucher_id == m.Voucher.id)
        .where(m.Voucher.company_id == cid)
        .where(m.Voucher.status == "POSTED")
        .where(m.Voucher.period_id.in_(ytd_period_ids) if ytd_period_ids else False)
        .group_by(m.VoucherEntry.cashflow_item_id, m.Voucher.period_id)
    )).all()

    # item_id → {period_amount, ytd_amount}。现金流量项目标在「对手分录」(行业惯例，如金蝶/用友)，
    # 故现金流入/出 = -(对手发生额) = base_credit - base_debit（贷方对手=现金流入为正、借方对手=现金流出为负）；
    # IN/OUT 仅作分类标签，net 统一 c-d，与 cashflow-tlist(T型账) 口径一致。
    # 未标项目（None）单列未分类，金额取 |debit-credit| 仅作提示，不并入三大类。
    item_amt: dict = {}
    unclassified = {"period": 0.0, "ytd": 0.0}
    for item_id, pid, dr, cr in rows:
        d, c = _dec(dr), _dec(cr)
        if item_id is None:
            net = abs(d - c)
            unclassified["ytd"] += net
            if pid == period_id:
                unclassified["period"] += net
            continue
        item = cf_index.get(item_id)
        if item is None:
            continue
        net = c - d  # 对手分录:贷(收现)→正流入、借(付现)→负流出；与 direction 标签无关
        slot = item_amt.setdefault(item_id, {"period": 0.0, "ytd": 0.0})
        slot["ytd"] += net
        if pid == period_id:
            slot["period"] += net

    # 树结构：父项（parent_id 为空）为三大类锚点，子项挂下面。无父则自成顶层。
    children: dict[int, list] = {}
    roots = []
    for item in sorted(cf_items, key=lambda x: x.code):
        if item.parent_id is None:
            roots.append(item)
        else:
            children.setdefault(item.parent_id, []).append(item)

    def _line(item):
        a = item_amt.get(item.id, {"period": 0.0, "ytd": 0.0})
        return {
            "item_id": item.id, "code": item.code, "name": item.name,
            "direction": item.direction,
            "period": round(a["period"], 2), "ytd": round(a["ytd"], 2),
        }

    activities = []
    for root in roots:
        kids = sorted(children.get(root.id, []), key=lambda x: x.code)
        child_lines = [_line(k) for k in kids]
        # 大类小计 = 自身分录(若有) + 各子项。
        own = item_amt.get(root.id, {"period": 0.0, "ytd": 0.0})
        sub_p = round(own["period"] + sum(l["period"] for l in child_lines), 2)
        sub_y = round(own["ytd"] + sum(l["ytd"] for l in child_lines), 2)
        activities.append({
            "item_id": root.id, "code": root.code, "name": root.name,
            "direction": root.direction,
            "lines": child_lines,
            "subtotal_period": sub_p,
            "subtotal_ytd": sub_y,
        })

    net_increase_period = round(sum(a["subtotal_period"] for a in activities), 2)
    net_increase_ytd = round(sum(a["subtotal_ytd"] for a in activities), 2)

    return {
        "report": "cash_flow_statement",
        "company_id": cid,
        "company_code": company.code,
        "period_id": period_id,
        "period_number": cur_pnum,
        "currency": company.currency,
        "data": {
            "activities": activities,
            "unclassified": {
                "label": "未分类现金流量（凭证未标现金流量项目）",
                "period": round(unclassified["period"], 2),
                "ytd": round(unclassified["ytd"], 2),
            },
            "net_increase": {
                "label": "现金及现金等价物净增加额",
                "period": net_increase_period,
                "ytd": net_increase_ytd,
            },
        },
    }


# ============================================================
# 总账·第六波（finance-gl wave-6）：现金流量 T 型账 + 现金流量查询。
# 取数复用 cash_flow_statement 同口径（已过账 VoucherEntry.cashflow_item_id 归集，本位币），
# 但 T 型账拆「流入/流出」两栏明细、查询按项目/期间列已标现金分录。
# ============================================================

@router.get("/cashflow-tlist")
async def cashflow_tlist(
    company_id: int = Query(..., description="公司 id（必传，单公司口径）"),
    period_id: int = Query(..., description="会计期间 id（出本期数；本年累计=同年度 period_number≤当期 累加）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """现金流量 T 型账（Cashflow T-list）：各现金流量项目的流入/流出两栏明细 + 本期/本年累计。

    取数（已过账 VoucherEntry，本位币，与 cash_flow_statement 同口径）：
    - 按 VoucherEntry.cashflow_item_id → CashflowItem 归集已过账凭证分录的本位币发生额。
    - 每个现金流量项目按其 direction（IN/OUT）落「流入栏」或「流出栏」；金额取 |base_debit-base_credit|（绝对值）。
    - 树结构：父项（parent_id 空）= 经营/投资/筹资 三大类锚点；子项挂下。
    - 合计：净现金流量 = Σ流入 - Σ流出（本期/本年累计各一）。
    """
    cid, err = _resolve_report_company(user, company_id)
    if err:
        return {"report": "cashflow_tlist", "company_id": company_id, "period_id": period_id,
                "data": {}, "error": err}
    company = await _get_company(db, cid)
    if company is None:
        return {"report": "cashflow_tlist", "company_id": company_id, "period_id": period_id,
                "data": {}, "error": "公司不存在"}

    _, fiscal_year_id, cur_pnum, ytd_period_ids, _ = await _period_year_window(db, period_id)
    if fiscal_year_id is None:
        return {"report": "cashflow_tlist", "company_id": cid, "period_id": period_id,
                "data": {}, "error": "会计期间不存在"}

    cf_items = (await db.execute(
        select(m.CashflowItem).where(m.CashflowItem.company_id == cid)
    )).scalars().all()
    cf_index = {c.id: c for c in cf_items}

    rows = (await db.execute(
        select(
            m.VoucherEntry.cashflow_item_id,
            m.Voucher.period_id,
            func.coalesce(func.sum(m.VoucherEntry.base_debit), 0),
            func.coalesce(func.sum(m.VoucherEntry.base_credit), 0),
        )
        .join(m.Voucher, m.VoucherEntry.voucher_id == m.Voucher.id)
        .where(m.Voucher.company_id == cid)
        .where(m.Voucher.status == "POSTED")
        .where(m.VoucherEntry.cashflow_item_id.isnot(None))
        .where(m.Voucher.period_id.in_(ytd_period_ids) if ytd_period_ids else False)
        .group_by(m.VoucherEntry.cashflow_item_id, m.Voucher.period_id)
    )).all()

    # item_id → {inflow:{period,ytd}, outflow:{period,ytd}}，按项目 direction 分流入/流出栏。
    item_amt: dict = {}
    for item_id, pid, dr, cr in rows:
        item = cf_index.get(item_id)
        if item is None:
            continue
        amount = abs(_dec(dr) - _dec(cr))
        slot = item_amt.setdefault(item_id, {
            "inflow": {"period": 0.0, "ytd": 0.0}, "outflow": {"period": 0.0, "ytd": 0.0}})
        bucket = "inflow" if item.direction == "IN" else "outflow"
        slot[bucket]["ytd"] += amount
        if pid == period_id:
            slot[bucket]["period"] += amount

    children: dict[int, list] = {}
    roots = []
    for item in sorted(cf_items, key=lambda x: x.code):
        if item.parent_id is None:
            roots.append(item)
        else:
            children.setdefault(item.parent_id, []).append(item)

    def _zero():
        return {"inflow": {"period": 0.0, "ytd": 0.0}, "outflow": {"period": 0.0, "ytd": 0.0}}

    def _line(item):
        a = item_amt.get(item.id, _zero())
        return {
            "item_id": item.id, "code": item.code, "name": item.name, "direction": item.direction,
            "inflow_period": round(a["inflow"]["period"], 2), "inflow_ytd": round(a["inflow"]["ytd"], 2),
            "outflow_period": round(a["outflow"]["period"], 2), "outflow_ytd": round(a["outflow"]["ytd"], 2),
        }

    activities = []
    tot_in_p = tot_in_y = tot_out_p = tot_out_y = 0.0
    for root in roots:
        kids = sorted(children.get(root.id, []), key=lambda x: x.code)
        child_lines = [_line(k) for k in kids]
        own = item_amt.get(root.id, _zero())
        sub = {
            "inflow_period": round(own["inflow"]["period"] + sum(l["inflow_period"] for l in child_lines), 2),
            "inflow_ytd": round(own["inflow"]["ytd"] + sum(l["inflow_ytd"] for l in child_lines), 2),
            "outflow_period": round(own["outflow"]["period"] + sum(l["outflow_period"] for l in child_lines), 2),
            "outflow_ytd": round(own["outflow"]["ytd"] + sum(l["outflow_ytd"] for l in child_lines), 2),
        }
        tot_in_p += sub["inflow_period"]; tot_in_y += sub["inflow_ytd"]
        tot_out_p += sub["outflow_period"]; tot_out_y += sub["outflow_ytd"]
        activities.append({
            "item_id": root.id, "code": root.code, "name": root.name, "direction": root.direction,
            "lines": child_lines, "subtotal": sub,
        })

    return {
        "report": "cashflow_tlist",
        "company_id": cid,
        "company_code": company.code,
        "period_id": period_id,
        "period_number": cur_pnum,
        "currency": company.currency,
        "data": {
            "activities": activities,
            "total_inflow": {"period": round(tot_in_p, 2), "ytd": round(tot_in_y, 2)},
            "total_outflow": {"period": round(tot_out_p, 2), "ytd": round(tot_out_y, 2)},
            "net_cashflow": {
                "period": round(tot_in_p - tot_out_p, 2),
                "ytd": round(tot_in_y - tot_out_y, 2),
            },
        },
    }


@router.get("/cashflow-query")
async def cashflow_query(
    company_id: int = Query(..., description="公司 id（必传，单公司口径）"),
    period_id: int = Query(None, description="会计期间 id（不传则查本公司所有期间已标现金分录）"),
    cashflow_item_id: int = Query(None, description="现金流量项目 id（不传则列全部已标项目）"),
    status: str = Query("POSTED", description="凭证状态过滤（默认 POSTED；传 ALL 含草稿）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """现金流量查询（Cashflow Query）：按项目/期间列出已标 cashflow_item_id 的现金分录明细。

    取数（VoucherEntry 已标 cashflow_item_id）：
    - 过滤本公司 + 可选 period_id + 可选 cashflow_item_id + 凭证状态（默认仅 POSTED）。
    - 每行 = 凭证号/日期/科目/摘要/借贷本位币额/现金流量项目（code+name+direction）。
    - 供财务核对归集结果、补标后复查。
    """
    cid, err = _resolve_report_company(user, company_id)
    if err:
        return {"report": "cashflow_query", "company_id": company_id, "rows": [], "error": err}

    cf_items = (await db.execute(
        select(m.CashflowItem).where(m.CashflowItem.company_id == cid)
    )).scalars().all()
    cf_index = {c.id: c for c in cf_items}

    stmt = (
        select(m.VoucherEntry, m.Voucher, m.Account)
        .join(m.Voucher, m.VoucherEntry.voucher_id == m.Voucher.id)
        .join(m.Account, m.VoucherEntry.account_id == m.Account.id)
        .where(m.Voucher.company_id == cid)
        .where(m.VoucherEntry.cashflow_item_id.isnot(None))
    )
    if period_id:
        stmt = stmt.where(m.Voucher.period_id == period_id)
    if cashflow_item_id:
        stmt = stmt.where(m.VoucherEntry.cashflow_item_id == cashflow_item_id)
    if status and status.upper() != "ALL":
        stmt = stmt.where(m.Voucher.status == status.upper())
    stmt = stmt.order_by(m.Voucher.voucher_date, m.Voucher.voucher_number, m.VoucherEntry.line_number)

    records = (await db.execute(stmt)).all()
    out = []
    total_debit = total_credit = 0.0
    for entry, voucher, acct in records:
        item = cf_index.get(entry.cashflow_item_id)
        bd, bc = _dec(entry.base_debit), _dec(entry.base_credit)
        total_debit += bd
        total_credit += bc
        out.append({
            "voucher_id": voucher.id,
            "voucher_number": voucher.voucher_number,
            "voucher_date": voucher.voucher_date.isoformat() if voucher.voucher_date else None,
            "voucher_status": voucher.status,
            "period_id": voucher.period_id,
            "line_number": entry.line_number,
            "account_code": acct.code,
            "account_name": acct.name,
            "description": entry.description,
            "base_debit": round(bd, 2),
            "base_credit": round(bc, 2),
            "cashflow_item_id": entry.cashflow_item_id,
            "cashflow_item_code": item.code if item else None,
            "cashflow_item_name": item.name if item else None,
            "cashflow_direction": item.direction if item else None,
        })

    return {
        "report": "cashflow_query",
        "company_id": cid,
        "period_id": period_id,
        "cashflow_item_id": cashflow_item_id,
        "status": status,
        "total": len(out),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "rows": out,
    }


@router.get("/aux-balance")
async def aux_balance(
    company_id: int = Query(..., description="公司 id（必传，单公司口径）"),
    period_id: int = Query(..., description="会计期间 id（按已过账凭证聚合本期/本年累计发生额）"),
    dimension_id: int = Query(..., description="辅助核算维度 id（AuxiliaryDimension）；其 source_type 决定按哪根轴分组"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """核算维度余额表（Auxiliary Balance）：按某辅助核算维度分组的科目发生额。

    取数（已过账 VoucherEntry，本位币）：
    - dimension_id → AuxiliaryDimension.source_type 决定分组轴：
      CUSTOMER/SUPPLIER/EMPLOYEE → aux_party_type==source_type 时按 aux_party_id 分组；
      DEPT → 按 aux_dept_id 分组；PROJECT → 按 aux_project_id 分组。
    - 每组（维度值 × 科目）出 本期借/贷 + 本年累计借/贷 + 净额（按科目余额方向）。
    - 本期 = 本期间凭证；本年累计 = 同会计年度 period_number≤当期 各期凭证。
    - 项目轴附带 project 名称；客户/供应商轴附带其 code/name 供前端显示。
    """
    cid, err = _resolve_report_company(user, company_id)
    if err:
        return {"report": "aux_balance", "company_id": company_id, "period_id": period_id,
                "dimension_id": dimension_id, "data": [], "error": err}

    dim = (await db.execute(
        select(m.AuxiliaryDimension)
        .where(m.AuxiliaryDimension.id == dimension_id)
        .where(m.AuxiliaryDimension.company_id == cid)
    )).scalar_one_or_none()
    if dim is None:
        return {"report": "aux_balance", "company_id": cid, "period_id": period_id,
                "dimension_id": dimension_id, "data": [], "error": "辅助核算维度不存在或不属本公司"}
    source_type = dim.source_type

    _, fiscal_year_id, cur_pnum, ytd_period_ids, _ = await _period_year_window(db, period_id)
    if fiscal_year_id is None:
        return {"report": "aux_balance", "company_id": cid, "period_id": period_id,
                "dimension_id": dimension_id, "source_type": source_type, "data": [],
                "error": "会计期间不存在"}

    # 选定分组列。
    if source_type == "DEPT":
        group_col = m.VoucherEntry.aux_dept_id
        axis_filter = m.VoucherEntry.aux_dept_id.isnot(None)
    elif source_type == "PROJECT":
        group_col = m.VoucherEntry.aux_project_id
        axis_filter = m.VoucherEntry.aux_project_id.isnot(None)
    else:  # CUSTOMER/SUPPLIER/EMPLOYEE → aux_party_*
        group_col = m.VoucherEntry.aux_party_id
        axis_filter = m.VoucherEntry.aux_party_type == source_type

    rows = (await db.execute(
        select(
            group_col,
            m.VoucherEntry.account_id,
            m.Voucher.period_id,
            func.coalesce(func.sum(m.VoucherEntry.base_debit), 0),
            func.coalesce(func.sum(m.VoucherEntry.base_credit), 0),
        )
        .join(m.Voucher, m.VoucherEntry.voucher_id == m.Voucher.id)
        .where(m.Voucher.company_id == cid)
        .where(m.Voucher.status == "POSTED")
        .where(m.Voucher.period_id.in_(ytd_period_ids) if ytd_period_ids else False)
        .where(axis_filter)
        .group_by(group_col, m.VoucherEntry.account_id, m.Voucher.period_id)
    )).all()

    # 取齐相关科目方向 + 维度值名称解析。
    acct_ids = {aid for _, aid, _, _, _ in rows}
    acct_index: dict[int, m.Account] = {}
    if acct_ids:
        accts = (await db.execute(
            select(m.Account).where(m.Account.id.in_(list(acct_ids)))
        )).scalars().all()
        acct_index = {a.id: a for a in accts}

    group_ids = {gid for gid, _, _, _, _ in rows if gid is not None}
    name_map: dict[int, dict] = {}
    if group_ids:
        gids = list(group_ids)
        if source_type == "PROJECT":
            for p in (await db.execute(select(m.Project).where(m.Project.id.in_(gids)))).scalars().all():
                name_map[p.id] = {"code": "", "name": p.name}
        elif source_type == "CUSTOMER":
            for c in (await db.execute(select(m.Customer).where(m.Customer.id.in_(gids)))).scalars().all():
                name_map[c.id] = {"code": c.code, "name": c.name}
        elif source_type == "SUPPLIER":
            for s in (await db.execute(select(m.Supplier).where(m.Supplier.id.in_(gids)))).scalars().all():
                name_map[s.id] = {"code": s.code, "name": s.name}
        # DEPT/EMPLOYEE 无独立主数据表，仅以 id 标识（弱引用，前端可显示 id）。

    # (group_id, account_id) → {period_d, period_c, ytd_d, ytd_c}。
    cell: dict = {}
    for gid, aid, pid, dr, cr in rows:
        d, c = _dec(dr), _dec(cr)
        slot = cell.setdefault((gid, aid), {"pd": 0.0, "pc": 0.0, "yd": 0.0, "yc": 0.0})
        slot["yd"] += d
        slot["yc"] += c
        if pid == period_id:
            slot["pd"] += d
            slot["pc"] += c

    # 按维度值分组聚合。
    grouped: dict = {}
    for (gid, aid), s in cell.items():
        acct = acct_index.get(aid)
        direction = acct.balance_direction if acct else "DEBIT"
        period_net = _signed_net(None, direction, s["pd"], s["pc"])
        ytd_net = _signed_net(None, direction, s["yd"], s["yc"])
        g = grouped.setdefault(gid, {"accounts": [], "total_period_net": 0.0, "total_ytd_net": 0.0})
        g["accounts"].append({
            "account_id": aid,
            "account_code": acct.code if acct else "",
            "account_name": acct.name if acct else "",
            "balance_direction": direction,
            "direction_label": "借" if direction == "DEBIT" else "贷",
            "period_debit": round(s["pd"], 2),
            "period_credit": round(s["pc"], 2),
            "ytd_debit": round(s["yd"], 2),
            "ytd_credit": round(s["yc"], 2),
            "period_net": round(period_net, 2),
            "ytd_net": round(ytd_net, 2),
        })
        g["total_period_net"] += period_net
        g["total_ytd_net"] += ytd_net

    data = []
    for gid, g in grouped.items():
        nm = name_map.get(gid, {})
        g["accounts"].sort(key=lambda r: r["account_code"])
        data.append({
            "group_id": gid,
            "group_code": nm.get("code", ""),
            "group_name": nm.get("name", "") or (f"#{gid}" if gid is not None else "（未标维度）"),
            "accounts": g["accounts"],
            "total_period_net": round(g["total_period_net"], 2),
            "total_ytd_net": round(g["total_ytd_net"], 2),
        })
    data.sort(key=lambda r: (r["group_code"], r["group_id"] or 0))

    return {
        "report": "aux_balance",
        "company_id": cid,
        "period_id": period_id,
        "period_number": cur_pnum,
        "dimension_id": dimension_id,
        "dimension_code": dim.code,
        "dimension_name": dim.name,
        "source_type": source_type,
        "data": data,
    }


# ============================================================
# 总账·第七波（finance-gl wave-7）合并报表（多账簿合并）：合并资产负债表 / 合并利润表。
# 会计专家定调「可手工合」→ 半自动：各成员公司单体报表汇总 + 折算 + 手工抵消分录调整。
# 取数底座复用 wave-5 的 balance_sheet / income_statement（对每个成员公司算单体准则-aware 行树），
# 再按 line_key 汇总各成员（折算 presentation 货币）→列 [各成员公司列, 抵消列(EliminationEntry), 合并列]。
# 折算：成员本位币→presentation 货币用 ExchangeRate（≤期末日最新），同币 rate=1；查不到标 warning 用 1 兜底。
# ============================================================


async def _resolve_consolidation_group(db, user, group_id):
    """解析并鉴权合并范围；返回 (group, active_member_companies, error)。

    active_member_companies = [Company,...]（成员子表 is_active 的成员公司，按 code 排序）。
    company_id（主导/创建公司）须在用户可见集内（privileged 只读放行任意）。
    """
    group = (await db.execute(
        select(m.ConsolidationGroup).where(m.ConsolidationGroup.id == group_id)
    )).scalar_one_or_none()
    if group is None:
        return None, [], "合并范围不存在"
    company_ids = _company_filter(user)
    if company_ids is not None and group.company_id not in company_ids:
        return None, [], "无权访问该合并范围"

    members = (await db.execute(
        select(m.ConsolidationMember)
        .where(m.ConsolidationMember.group_id == group_id)
        .where(m.ConsolidationMember.is_active == True)  # noqa: E712
    )).scalars().all()
    member_cids = [mb.member_company_id for mb in members]
    companies = []
    if member_cids:
        companies = (await db.execute(
            select(m.Company).where(m.Company.id.in_(member_cids))
        )).scalars().all()
        companies.sort(key=lambda c: c.code)
    return group, companies, None


async def _member_period_id(db, company_id, period_year, period_number):
    """按「同年同期号」对齐成员期间：找该公司 fiscal_year.year==period_year 下 period_number==N 的 AccountingPeriod.id。
    找不到返回 None（端点据此对该成员标 missing_period，不并入合计）。"""
    pid = (await db.execute(
        select(m.AccountingPeriod.id)
        .join(m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id)
        .where(m.FiscalYear.company_id == company_id)
        .where(m.FiscalYear.year == period_year)
        .where(m.AccountingPeriod.period_number == period_number)
    )).scalar_one_or_none()
    return pid


async def _fx_rate_to_presentation(db, from_ccy, to_ccy, on_or_before):
    """成员本位币 from_ccy → 列报币 to_ccy 的折算率（取 effective_date ≤ on_or_before 的最新一条）。

    返回 (rate: float, warning: str|None)。同币 rate=1.0 无 warning；查不到汇率 rate=1.0 并带 warning（兜底不崩）。
    on_or_before 为期末日（成员 period.end_date）；缺省用今天。
    """
    if not from_ccy or not to_ccy or from_ccy == to_ccy:
        return 1.0, None
    stmt = (
        select(m.ExchangeRate)
        .where(m.ExchangeRate.from_currency == from_ccy)
        .where(m.ExchangeRate.to_currency == to_ccy)
    )
    if on_or_before is not None:
        stmt = stmt.where(m.ExchangeRate.effective_date <= on_or_before)
    stmt = stmt.order_by(m.ExchangeRate.effective_date.desc())
    rate_row = (await db.execute(stmt)).scalars().first()
    if rate_row is None:
        return 1.0, f"未找到 {from_ccy}→{to_ccy} 汇率（≤期末日），以 1.0 兜底折算"
    return float(rate_row.rate), None


def _eliminations_by_line(elim_rows, statement):
    """把 EliminationEntry 行按 line_key（无则 account_code）聚合成 {key: net}（净额=debit-credit，presentation 币）。
    statement 过滤 BS/IS。返回 (by_line: dict, rows_out: list 明细)。"""
    by_line: dict[str, float] = {}
    rows_out = []
    for e in elim_rows:
        if e.statement != statement:
            continue
        key = e.line_key or e.account_code or ""
        net = _dec(e.debit) - _dec(e.credit)
        by_line[key] = by_line.get(key, 0.0) + net
        rows_out.append({
            "id": e.id, "line_key": e.line_key, "account_code": e.account_code,
            "debit": _dec(e.debit), "credit": _dec(e.credit), "net": round(net, 2),
            "memo": e.memo,
        })
    return by_line, rows_out


async def _load_eliminations(db, group_id, period_year, period_number, statement):
    rows = (await db.execute(
        select(m.EliminationEntry)
        .where(m.EliminationEntry.group_id == group_id)
        .where(m.EliminationEntry.period_year == period_year)
        .where(m.EliminationEntry.period_number == period_number)
        .where(m.EliminationEntry.is_active == True)  # noqa: E712
        .where(m.EliminationEntry.statement == statement)
    )).scalars().all()
    return _eliminations_by_line(rows, statement)


@router.get("/consolidated-balance-sheet")
async def consolidated_balance_sheet(
    group_id: int = Query(..., description="合并范围 id（ConsolidationGroup）"),
    period_year: int = Query(..., description="合并期间年份（按同年同期号对齐各成员期间）"),
    period_number: int = Query(..., description="合并期间期号（如 6=第6期）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """合并资产负债表（Consolidated Balance Sheet）：各成员单体 BS 汇总 + 折算 + 手工抵消。

    口径（半自动手工合并，复用 wave-5 balance_sheet 单体取数）：
    - 对合并范围每个成员公司，按「同年同期号」找其 AccountingPeriod → 调 balance_sheet 算单体准则-aware 行树。
    - 各成员单体行 closing 按其本位币→列报币 ExchangeRate（≤成员期末日最新）折算；同币 rate=1；查不到标 warning 用 1。
    - 按 line_key 汇总：每行列出 [各成员公司列(折算后), 抵消列(EliminationEntry statement=BS), 合并列]。
      合并列 = Σ成员折算后 closing + 抵消净额(debit-credit)。
    - 行树结构沿用单体 BS 的 assets/liabilities/equity 分组与 line_key（取各成员行树的并集，按出现顺序）。
    - 勾稽：合并 资产合计 == 负债合计 + 权益合计（误差 < 0.01 视为平衡；含抵消列影响）。
    """
    group, companies, err = await _resolve_consolidation_group(db, user, group_id)
    if err:
        return {"report": "consolidated_balance_sheet", "group_id": group_id,
                "period_year": period_year, "period_number": period_number,
                "data": {}, "error": err}
    presentation = group.presentation_currency or "CNY"
    warnings: list[str] = []

    # 1) 逐成员算单体 BS + 折算率。member_results: [{company, period_id|None, statement, rate, bs|None}]
    member_results = []
    for company in companies:
        pid = await _member_period_id(db, company.id, period_year, period_number)
        member_meta = {
            "company_id": company.id, "company_code": company.code,
            "company_name": company.short_name or company.name,
            "currency": company.currency,
        }
        if pid is None:
            warnings.append(f"成员 {company.code} 无 {period_year}年第{period_number}期，未并入")
            member_results.append({**member_meta, "period_id": None, "rate": None, "bs": None})
            continue
        period = (await db.execute(
            select(m.AccountingPeriod).where(m.AccountingPeriod.id == pid)
        )).scalar_one_or_none()
        end_date = period.end_date if period else None
        rate, w = await _fx_rate_to_presentation(db, company.currency, presentation, end_date)
        if w:
            warnings.append(f"成员 {company.code}：{w}")
        bs = await balance_sheet(company_id=company.id, period_id=pid, db=db, user=user)
        member_results.append({**member_meta, "period_id": pid, "rate": rate,
                               "standard": bs.get("standard"), "bs": bs})

    # 2) 抵消列（BS）。
    elim_by_line, elim_rows = await _load_eliminations(db, group_id, period_year, period_number, "BS")

    # 3) 汇总：把各成员单体 BS 行树「拍平」为 {line_key: {label, group_key, section, per_company:{cid:closing}}}，
    #    保出现顺序（沿用首个有数成员的行树骨架，缺失行按出现补）。
    # section ∈ assets / liabilities / equity；用于合计与勾稽。
    line_order: list[str] = []
    line_meta: dict[str, dict] = {}
    line_amounts: dict[str, dict[int, float]] = {}  # line_key → {company_id: 折算后 closing}

    def _ingest_section(section, groups_or_lines, cid, rate):
        # groups_or_lines: BS assets/liabilities = {"groups":[{group_key,label,lines:[...]}]}；equity = {"lines":[...]}
        groups = groups_or_lines.get("groups")
        if groups is not None:
            for g in groups:
                for ln in g.get("lines", []):
                    _ingest_line(section, g.get("group_key"), g.get("label"), ln, cid, rate)
        else:
            for ln in groups_or_lines.get("lines", []):
                _ingest_line(section, "equity", groups_or_lines.get("label", "权益"), ln, cid, rate)

    def _ingest_line(section, group_key, group_label, ln, cid, rate):
        lk = ln["line_key"]
        if lk not in line_meta:
            line_order.append(lk)
            line_meta[lk] = {
                "line_key": lk, "label": ln.get("label"), "label_en": ln.get("label_en"),
                "section": section, "group_key": group_key, "group_label": group_label,
            }
            line_amounts[lk] = {}
        line_amounts[lk][cid] = round(line_amounts[lk].get(cid, 0.0) + _dec(ln.get("closing")) * rate, 2)

    for mr in member_results:
        if mr["bs"] is None or mr["bs"].get("error"):
            if mr["bs"] and mr["bs"].get("error"):
                warnings.append(f"成员 {mr['company_code']} 单体BS异常：{mr['bs']['error']}")
            continue
        data = mr["bs"].get("data", {})
        rate = mr["rate"] or 1.0
        cid = mr["company_id"]
        if "assets" in data:
            _ingest_section("assets", data["assets"], cid, rate)
        if "liabilities" in data:
            _ingest_section("liabilities", data["liabilities"], cid, rate)
        if "equity" in data:
            _ingest_section("equity", data["equity"], cid, rate)

    # 4) 组装行：每行 per_company 列 + elimination + consolidated。
    member_cols = [
        {"company_id": mr["company_id"], "company_code": mr["company_code"],
         "company_name": mr["company_name"], "currency": mr["currency"],
         "rate": mr["rate"], "period_id": mr["period_id"], "included": mr["bs"] is not None}
        for mr in member_results
    ]
    included_cids = [mr["company_id"] for mr in member_results if mr["bs"] is not None]

    def _build_rows(section):
        out = []
        sec_member_tot = {cid: 0.0 for cid in included_cids}
        sec_elim_tot = 0.0
        sec_consol_tot = 0.0
        for lk in line_order:
            meta = line_meta[lk]
            if meta["section"] != section:
                continue
            per_company = {cid: round(line_amounts[lk].get(cid, 0.0), 2) for cid in included_cids}
            members_sum = round(sum(per_company.values()), 2)
            elim = round(elim_by_line.get(lk, 0.0), 2)
            consolidated = round(members_sum + elim, 2)
            for cid in included_cids:
                sec_member_tot[cid] = round(sec_member_tot[cid] + per_company[cid], 2)
            sec_elim_tot = round(sec_elim_tot + elim, 2)
            sec_consol_tot = round(sec_consol_tot + consolidated, 2)
            out.append({
                "line_key": lk, "label": meta["label"], "label_en": meta["label_en"],
                "group_key": meta["group_key"], "group_label": meta["group_label"],
                "per_company": per_company, "members_subtotal": members_sum,
                "elimination": elim, "consolidated": consolidated,
            })
        return out, sec_member_tot, sec_elim_tot, sec_consol_tot

    asset_rows, asset_mt, asset_et, asset_ct = _build_rows("assets")
    liab_rows, liab_mt, liab_et, liab_ct = _build_rows("liabilities")
    eq_rows, eq_mt, eq_et, eq_ct = _build_rows("equity")

    return {
        "report": "consolidated_balance_sheet",
        "group_id": group_id,
        "group_code": group.code,
        "group_name": group.name,
        "presentation_currency": presentation,
        "standard": group.standard,
        "period_year": period_year,
        "period_number": period_number,
        "members": member_cols,
        "data": {
            "assets": {"rows": asset_rows, "member_totals": asset_mt,
                       "elimination_total": asset_et, "consolidated_total": asset_ct},
            "liabilities": {"rows": liab_rows, "member_totals": liab_mt,
                            "elimination_total": liab_et, "consolidated_total": liab_ct},
            "equity": {"rows": eq_rows, "member_totals": eq_mt,
                       "elimination_total": eq_et, "consolidated_total": eq_ct},
        },
        "eliminations": elim_rows,
        "check": {
            "assets_total": asset_ct,
            "liabilities_plus_equity": round(liab_ct + eq_ct, 2),
            "balanced": abs(asset_ct - (liab_ct + eq_ct)) < 0.01,
        },
        "warnings": warnings,
    }


@router.get("/consolidated-income-statement")
async def consolidated_income_statement(
    group_id: int = Query(..., description="合并范围 id（ConsolidationGroup）"),
    period_year: int = Query(..., description="合并期间年份（按同年同期号对齐各成员期间）"),
    period_number: int = Query(..., description="合并期间期号（如 6=第6期）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """合并利润表（Consolidated Income Statement）：各成员单体 IS 汇总 + 折算 + 手工抵消。

    口径（半自动手工合并，复用 wave-5 income_statement 单体取数）：
    - 对合并范围每个成员公司，按「同年同期号」找其 AccountingPeriod → 调 income_statement 算单体准则-aware 行项目。
    - 各成员单体行 period/ytd 按其本位币→列报币 ExchangeRate（≤成员期末日最新）折算；同币 rate=1；查不到标 warning 用 1。
    - 按 line_key 汇总：每行列出 [各成员公司列(折算后 period), 抵消列(EliminationEntry statement=IS), 合并列]。
      合并列 = Σ成员折算后 period + 抵消净额(debit-credit)。同时给 ytd 口径汇总。
    - 净利润：逐行 sign 累加（沿用单体 IS 行 sign）；合并净利润 = 各成员折算后净利润之和 + 抵消对净利润影响。
    """
    group, companies, err = await _resolve_consolidation_group(db, user, group_id)
    if err:
        return {"report": "consolidated_income_statement", "group_id": group_id,
                "period_year": period_year, "period_number": period_number,
                "data": {}, "error": err}
    presentation = group.presentation_currency or "CNY"
    warnings: list[str] = []

    member_results = []
    for company in companies:
        pid = await _member_period_id(db, company.id, period_year, period_number)
        member_meta = {
            "company_id": company.id, "company_code": company.code,
            "company_name": company.short_name or company.name,
            "currency": company.currency,
        }
        if pid is None:
            warnings.append(f"成员 {company.code} 无 {period_year}年第{period_number}期，未并入")
            member_results.append({**member_meta, "period_id": None, "rate": None, "is": None})
            continue
        period = (await db.execute(
            select(m.AccountingPeriod).where(m.AccountingPeriod.id == pid)
        )).scalar_one_or_none()
        end_date = period.end_date if period else None
        rate, w = await _fx_rate_to_presentation(db, company.currency, presentation, end_date)
        if w:
            warnings.append(f"成员 {company.code}：{w}")
        inc = await income_statement(company_id=company.id, period_id=pid, db=db, user=user)
        member_results.append({**member_meta, "period_id": pid, "rate": rate,
                               "standard": inc.get("standard"), "is": inc})

    elim_by_line, elim_rows = await _load_eliminations(db, group_id, period_year, period_number, "IS")

    line_order: list[str] = []
    line_meta: dict[str, dict] = {}
    line_period: dict[str, dict[int, float]] = {}
    line_ytd: dict[str, dict[int, float]] = {}

    for mr in member_results:
        if mr["is"] is None or mr["is"].get("error"):
            if mr["is"] and mr["is"].get("error"):
                warnings.append(f"成员 {mr['company_code']} 单体IS异常：{mr['is']['error']}")
            continue
        rate = mr["rate"] or 1.0
        cid = mr["company_id"]
        for ln in mr["is"].get("data", {}).get("lines", []):
            lk = ln["line_key"]
            if lk not in line_meta:
                line_order.append(lk)
                line_meta[lk] = {"line_key": lk, "label": ln.get("label"),
                                 "label_en": ln.get("label_en"), "sign": ln.get("sign", 1)}
                line_period[lk] = {}
                line_ytd[lk] = {}
            line_period[lk][cid] = round(line_period[lk].get(cid, 0.0) + _dec(ln.get("period")) * rate, 2)
            line_ytd[lk][cid] = round(line_ytd[lk].get(cid, 0.0) + _dec(ln.get("ytd")) * rate, 2)

    member_cols = [
        {"company_id": mr["company_id"], "company_code": mr["company_code"],
         "company_name": mr["company_name"], "currency": mr["currency"],
         "rate": mr["rate"], "period_id": mr["period_id"], "included": mr["is"] is not None}
        for mr in member_results
    ]
    included_cids = [mr["company_id"] for mr in member_results if mr["is"] is not None]

    rows = []
    net_period_member = {cid: 0.0 for cid in included_cids}
    net_ytd_member = {cid: 0.0 for cid in included_cids}
    net_period_elim = 0.0
    net_period_consol = 0.0
    net_ytd_consol = 0.0
    for lk in line_order:
        meta = line_meta[lk]
        sign = meta["sign"]
        per_company_p = {cid: round(line_period[lk].get(cid, 0.0), 2) for cid in included_cids}
        per_company_y = {cid: round(line_ytd[lk].get(cid, 0.0), 2) for cid in included_cids}
        members_p = round(sum(per_company_p.values()), 2)
        members_y = round(sum(per_company_y.values()), 2)
        elim = round(elim_by_line.get(lk, 0.0), 2)
        consol_p = round(members_p + elim, 2)
        consol_y = round(members_y + elim, 2)
        for cid in included_cids:
            net_period_member[cid] = round(net_period_member[cid] + sign * per_company_p[cid], 2)
            net_ytd_member[cid] = round(net_ytd_member[cid] + sign * per_company_y[cid], 2)
        net_period_elim = round(net_period_elim + sign * elim, 2)
        net_period_consol = round(net_period_consol + sign * consol_p, 2)
        net_ytd_consol = round(net_ytd_consol + sign * consol_y, 2)
        rows.append({
            "line_key": lk, "label": meta["label"], "label_en": meta["label_en"], "sign": sign,
            "per_company_period": per_company_p, "per_company_ytd": per_company_y,
            "members_period": members_p, "members_ytd": members_y,
            "elimination": elim, "consolidated_period": consol_p, "consolidated_ytd": consol_y,
        })

    return {
        "report": "consolidated_income_statement",
        "group_id": group_id,
        "group_code": group.code,
        "group_name": group.name,
        "presentation_currency": presentation,
        "standard": group.standard,
        "period_year": period_year,
        "period_number": period_number,
        "members": member_cols,
        "data": {
            "lines": rows,
            "net_profit": {
                "label": "净利润", "label_en": "Net profit",
                "per_company_period": net_period_member,
                "per_company_ytd": net_ytd_member,
                "elimination": net_period_elim,
                "consolidated_period": net_period_consol,
                "consolidated_ytd": net_ytd_consol,
            },
        },
        "eliminations": elim_rows,
        "warnings": warnings,
    }


@router.get("/periods")
async def list_periods(
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """返回用户可见的会计期间列表（供前端报表选期间用）

    按 user.company_id 过滤（BOSS/FINANCE 也只看自己主公司），
    避免多公司场景下 (year, period_number) 去重选中错误 period_id。
    """
    stmt = (
        select(m.AccountingPeriod, m.FiscalYear)
        .join(m.FiscalYear, m.AccountingPeriod.fiscal_year_id == m.FiscalYear.id)
        .where(m.FiscalYear.company_id == user.company_id)
        .order_by(m.FiscalYear.year.desc(), m.AccountingPeriod.period_number)
    )

    result = await db.execute(stmt)
    data = [
        {
            "id": period.id,
            "year": fy.year,
            "period_number": period.period_number,
            "start_date": period.start_date.isoformat(),
            "end_date": period.end_date.isoformat(),
            "status": period.status,
            "label": f"{fy.year}年第{period.period_number}期",
        }
        for period, fy in result.all()
    ]

    return {"periods": data}


# ============================================================
# 应收款管理报表（finance-gl wave-8）：应收款汇总表 / 明细表 / 客户对账单
# 取数底座：AccountsReceivable（应收单/债权）+ ARReceipt（收款单/已收）+ WriteoffLink（核销关系，
# 用于「已核销额」口径校验，但回写后的 written_off_amount 即为当前口径，报表直接取单上回写值）。
# 未清额 outstanding = amount − paid_amount − written_off_amount（兼容旧扁平 paid_amount 与新核销口径）。
# 多公司：company_id 选传则单公司（须可见）；不传取 _company_filter(user) 可见范围。
# ============================================================

# 应收单「未清」状态集（排除已关闭/已结算/已全额核销的扁平历史口径；新流程审核态 AUDITED 视为成立未清）。
_AR_CLOSED_STATUSES = ("CLOSED", "SETTLED")


def _ar_outstanding(ar) -> float:
    """应收单未清额 = 价税合计 − 已收(扁平) − 已核销(新口径)，下限 0。"""
    return max(
        _dec(ar.amount) - _dec(ar.paid_amount) - _dec(getattr(ar, "written_off_amount", 0)),
        0.0,
    )


def _ar_company_scope(user, company_id):
    """返回 (company_ids_filter, single_company_id, error)。

    company_id 选传 → 校验可见后单公司；不传 → 取 _company_filter（privileged=None 表全部可见）。
    """
    company_ids = _company_filter(user)
    if company_id is not None:
        if company_ids is not None and company_id not in company_ids:
            return None, None, "无权访问该公司"
        return None, company_id, None
    return company_ids, None, None


@router.get("/ar-summary")
async def ar_summary(
    company_id: int | None = Query(None, description="公司 id（选传；不传取可见范围全部）"),
    as_of: str | None = Query(None, description="截止业务日期（YYYY-MM-DD，选传；只算 bill_date≤此日的应收单）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """应收款汇总表：按客户汇总期末未清应收（价税合计/已收/已核销/未清）。

    未清额 = Σ(amount − paid_amount − written_off_amount)，仅算未关闭/未结算的应收单。
    as_of 选传则只纳入 bill_date≤as_of（缺 bill_date 回退 due_date）的应收单。
    """
    company_ids, single_cid, err = _ar_company_scope(user, company_id)
    if err:
        return {"report": "ar_summary", "error": err, "data": []}

    stmt = (
        select(m.AccountsReceivable, m.Customer)
        .join(m.Customer, m.AccountsReceivable.customer_id == m.Customer.id, isouter=True)
        .where(m.AccountsReceivable.status.notin_(_AR_CLOSED_STATUSES))
    )
    if single_cid is not None:
        stmt = stmt.where(m.AccountsReceivable.company_id == single_cid)
    elif company_ids:
        stmt = stmt.where(m.AccountsReceivable.company_id.in_(company_ids))

    as_of_date = date.fromisoformat(as_of[:10]) if as_of else None
    rows = (await db.execute(stmt)).all()

    by_cust: dict[int, dict] = {}
    for ar, cust in rows:
        biz_date = ar.bill_date or ar.due_date
        if as_of_date and biz_date and biz_date > as_of_date:
            continue
        outstanding = _ar_outstanding(ar)
        if outstanding <= 0:
            continue
        key = ar.customer_id or 0
        agg = by_cust.setdefault(key, {
            "customer_id": ar.customer_id,
            "customer_name": getattr(cust, "name", None) or "(未指定客户)",
            "customer_code": getattr(cust, "code", None) or "",
            "currency": ar.currency,
            "total_amount": 0.0, "paid_amount": 0.0, "written_off_amount": 0.0,
            "outstanding": 0.0, "bill_count": 0,
        })
        agg["total_amount"] += _dec(ar.amount)
        agg["paid_amount"] += _dec(ar.paid_amount)
        agg["written_off_amount"] += _dec(getattr(ar, "written_off_amount", 0))
        agg["outstanding"] += outstanding
        agg["bill_count"] += 1

    data = sorted(by_cust.values(), key=lambda r: r["outstanding"], reverse=True)
    for r in data:
        for k in ("total_amount", "paid_amount", "written_off_amount", "outstanding"):
            r[k] = round(r[k], 2)
    return {
        "report": "ar_summary",
        "company_id": single_cid,
        "as_of": as_of_date.isoformat() if as_of_date else None,
        "data": data,
        "total_outstanding": round(sum(r["outstanding"] for r in data), 2),
    }


@router.get("/ar-detail")
async def ar_detail(
    company_id: int | None = Query(None, description="公司 id（选传）"),
    customer_id: int | None = Query(None, description="客户 id（选传，单客户明细）"),
    as_of: str | None = Query(None, description="截止业务日期（YYYY-MM-DD，选传）"),
    include_settled: bool = Query(False, description="含已结清单据（默认 False=仅未清）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """应收款明细表：逐应收单列 单号/客户/业务日/到期日/价税合计/已收/已核销/未清/状态。"""
    company_ids, single_cid, err = _ar_company_scope(user, company_id)
    if err:
        return {"report": "ar_detail", "error": err, "data": []}

    stmt = (
        select(m.AccountsReceivable, m.Customer)
        .join(m.Customer, m.AccountsReceivable.customer_id == m.Customer.id, isouter=True)
    )
    if not include_settled:
        stmt = stmt.where(m.AccountsReceivable.status.notin_(_AR_CLOSED_STATUSES))
    if single_cid is not None:
        stmt = stmt.where(m.AccountsReceivable.company_id == single_cid)
    elif company_ids:
        stmt = stmt.where(m.AccountsReceivable.company_id.in_(company_ids))
    if customer_id is not None:
        stmt = stmt.where(m.AccountsReceivable.customer_id == customer_id)
    stmt = stmt.order_by(m.AccountsReceivable.customer_id, m.AccountsReceivable.id)

    as_of_date = date.fromisoformat(as_of[:10]) if as_of else None
    rows = (await db.execute(stmt)).all()

    data = []
    for ar, cust in rows:
        biz_date = ar.bill_date or ar.due_date
        if as_of_date and biz_date and biz_date > as_of_date:
            continue
        outstanding = _ar_outstanding(ar)
        if not include_settled and outstanding <= 0:
            continue
        data.append({
            "id": ar.id,
            "bill_number": ar.bill_number or "",
            "invoice_number": ar.invoice_number or "",
            "customer_id": ar.customer_id,
            "customer_name": getattr(cust, "name", None) or "(未指定客户)",
            "customer_code": getattr(cust, "code", None) or "",
            "bill_date": ar.bill_date.isoformat() if ar.bill_date else None,
            "due_date": ar.due_date.isoformat() if ar.due_date else None,
            "currency": ar.currency,
            "amount": _dec(ar.amount),
            "untaxed_amount": _dec(getattr(ar, "untaxed_amount", 0)),
            "tax_amount": _dec(getattr(ar, "tax_amount", 0)),
            "paid_amount": _dec(ar.paid_amount),
            "written_off_amount": _dec(getattr(ar, "written_off_amount", 0)),
            "outstanding": round(outstanding, 2),
            "status": ar.status,
            "writeoff_status": getattr(ar, "writeoff_status", None),
        })
    return {
        "report": "ar_detail",
        "company_id": single_cid,
        "customer_id": customer_id,
        "as_of": as_of_date.isoformat() if as_of_date else None,
        "data": data,
        "total_outstanding": round(sum(r["outstanding"] for r in data), 2),
    }


@router.get("/customer-statement")
async def customer_statement(
    customer_id: int = Query(..., description="客户 id（必传，单客户对账）"),
    company_id: int | None = Query(None, description="公司 id（选传；不传取可见范围）"),
    date_from: str | None = Query(None, description="期间起（YYYY-MM-DD，选传）"),
    date_to: str | None = Query(None, description="期间止（YYYY-MM-DD，选传）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """客户对账单：某客户期间内 应收（债权+）/ 收款（已收−）时序流水 + 期初/期末余额对账。

    余额口径（原币）：应收单按 amount 增加应收余额（debit 方向）；收款单按 amount 冲减（credit 方向）。
    期初余额 = date_from 之前的 Σ应收 − Σ收款；逐笔累计出 running_balance。多币种不混算（按单据原币逐笔列示）。
    """
    company_ids, single_cid, err = _ar_company_scope(user, company_id)
    if err:
        return {"report": "customer_statement", "error": err, "transactions": []}

    # ★多租户隔离:客户必须落在调用者可见公司内,否则视为不存在(防 IDOR 跨公司客户信息泄露)。
    cust_stmt = select(m.Customer).where(m.Customer.id == customer_id)
    if single_cid is not None:
        cust_stmt = cust_stmt.where(m.Customer.company_id == single_cid)
    elif company_ids:
        cust_stmt = cust_stmt.where(m.Customer.company_id.in_(company_ids))
    cust = (await db.execute(cust_stmt)).scalar_one_or_none()
    if cust is None:
        return {"report": "customer_statement", "error": "客户不存在或无权访问", "transactions": []}

    d_from = date.fromisoformat(date_from[:10]) if date_from else None
    d_to = date.fromisoformat(date_to[:10]) if date_to else None

    def _apply_company(stmt, col):
        if single_cid is not None:
            return stmt.where(col == single_cid)
        if company_ids:
            return stmt.where(col.in_(company_ids))
        return stmt

    # 应收单（债权，按 bill_date 落期；缺则回退 due_date）。仅取已成立（非草稿/非关闭）。
    ar_stmt = _apply_company(
        select(m.AccountsReceivable).where(
            m.AccountsReceivable.customer_id == customer_id,
            m.AccountsReceivable.status.notin_(("DRAFT",) + _AR_CLOSED_STATUSES),
        ),
        m.AccountsReceivable.company_id,
    )
    bills = (await db.execute(ar_stmt)).scalars().all()

    # 收款单（已收，按 receipt_date 落期）。仅取已审核（成立）。
    rcpt_stmt = _apply_company(
        select(m.ARReceipt).where(
            m.ARReceipt.customer_id == customer_id,
            m.ARReceipt.status == "AUDITED",
        ),
        m.ARReceipt.company_id,
    )
    receipts = (await db.execute(rcpt_stmt)).scalars().all()

    # 统一事件流：(business_date, type, doc_no, debit应收, credit收款, currency, doc_id)。
    events = []
    for b in bills:
        bd = b.bill_date or b.due_date
        events.append({
            "date": bd, "type": "AR_BILL", "doc_no": b.bill_number or b.invoice_number or f"AR#{b.id}",
            "debit": _dec(b.amount), "credit": 0.0, "currency": b.currency, "doc_id": b.id,
            "due_date": b.due_date.isoformat() if b.due_date else None,
        })
    for r in receipts:
        events.append({
            "date": r.receipt_date, "type": "AR_RECEIPT", "doc_no": r.receipt_number or f"SK#{r.id}",
            "debit": 0.0, "credit": _dec(r.amount), "currency": r.currency, "doc_id": r.id,
            "is_advance": bool(r.is_advance),
        })

    # 期初余额（date_from 之前的净额）= Σ应收(debit) − Σ收款(credit)。
    opening = 0.0
    for e in events:
        if d_from and e["date"] and e["date"] < d_from:
            opening += e["debit"] - e["credit"]

    # 期间内事件（date_from≤date≤date_to；无日期的单据按落入期间处理，列在最后）。
    def _in_window(ev):
        ed = ev["date"]
        if ed is None:
            return True
        if d_from and ed < d_from:
            return False
        if d_to and ed > d_to:
            return False
        return True

    window = [e for e in events if _in_window(e)]
    window.sort(key=lambda e: (e["date"] or date.max, 0 if e["type"] == "AR_BILL" else 1))

    running = round(opening, 2)
    txns = []
    total_debit = 0.0
    total_credit = 0.0
    for e in window:
        running = round(running + e["debit"] - e["credit"], 2)
        total_debit += e["debit"]
        total_credit += e["credit"]
        txns.append({
            "date": e["date"].isoformat() if e["date"] else None,
            "type": e["type"],
            "doc_no": e["doc_no"],
            "currency": e["currency"],
            "debit": round(e["debit"], 2),
            "credit": round(e["credit"], 2),
            "running_balance": running,
            "due_date": e.get("due_date"),
            "is_advance": e.get("is_advance"),
            "doc_id": e["doc_id"],
        })

    return {
        "report": "customer_statement",
        "company_id": single_cid,
        "customer_id": customer_id,
        "customer_name": getattr(cust, "name", None),
        "customer_code": getattr(cust, "code", None),
        "date_from": d_from.isoformat() if d_from else None,
        "date_to": d_to.isoformat() if d_to else None,
        "opening_balance": round(opening, 2),
        "closing_balance": running,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "transactions": txns,
    }


# ============================================================
# 应付款管理报表（finance-gl 应付波）= 应收报表的供应商侧镜像。
# _ar_company_scope 通用（按公司隔离，AR/AP 共用）；待核销项走 /ar-open-items?biz_type=AP。
# ★均带与 customer_statement 同款多租户隔离（防 IDOR 跨公司供应商信息泄露）。
# ============================================================

def _ap_outstanding(ap) -> float:
    """应付单未付额 = 价税合计 − 已付(扁平) − 已核销(新口径)，下限 0。"""
    return max(
        _dec(ap.amount) - _dec(ap.paid_amount) - _dec(getattr(ap, "written_off_amount", 0)),
        0.0,
    )


@router.get("/ap-summary")
async def ap_summary(
    company_id: int | None = Query(None, description="公司 id（选传；不传取可见范围全部）"),
    as_of: str | None = Query(None, description="截止业务日期（YYYY-MM-DD，选传；只算 bill_date≤此日的应付单）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """应付款汇总表：按供应商汇总期末未清应付（价税合计/已付/已核销/未清）。= ar_summary 镜像。"""
    company_ids, single_cid, err = _ar_company_scope(user, company_id)
    if err:
        return {"report": "ap_summary", "error": err, "data": []}

    stmt = (
        select(m.AccountsPayable, m.Supplier)
        .join(m.Supplier, m.AccountsPayable.supplier_id == m.Supplier.id, isouter=True)
        .where(m.AccountsPayable.status.notin_(_AR_CLOSED_STATUSES))
    )
    if single_cid is not None:
        stmt = stmt.where(m.AccountsPayable.company_id == single_cid)
    elif company_ids:
        stmt = stmt.where(m.AccountsPayable.company_id.in_(company_ids))

    as_of_date = date.fromisoformat(as_of[:10]) if as_of else None
    rows = (await db.execute(stmt)).all()

    by_sup: dict[int, dict] = {}
    for ap, sup in rows:
        biz_date = ap.bill_date or ap.due_date
        if as_of_date and biz_date and biz_date > as_of_date:
            continue
        outstanding = _ap_outstanding(ap)
        if outstanding <= 0:
            continue
        key = ap.supplier_id or 0
        agg = by_sup.setdefault(key, {
            "supplier_id": ap.supplier_id,
            "supplier_name": getattr(sup, "name", None) or "(未指定供应商)",
            "supplier_code": getattr(sup, "code", None) or "",
            "currency": ap.currency,
            "total_amount": 0.0, "paid_amount": 0.0, "written_off_amount": 0.0,
            "outstanding": 0.0, "bill_count": 0,
        })
        agg["total_amount"] += _dec(ap.amount)
        agg["paid_amount"] += _dec(ap.paid_amount)
        agg["written_off_amount"] += _dec(getattr(ap, "written_off_amount", 0))
        agg["outstanding"] += outstanding
        agg["bill_count"] += 1

    data = sorted(by_sup.values(), key=lambda r: r["outstanding"], reverse=True)
    for r in data:
        for k in ("total_amount", "paid_amount", "written_off_amount", "outstanding"):
            r[k] = round(r[k], 2)
    return {
        "report": "ap_summary",
        "company_id": single_cid,
        "as_of": as_of_date.isoformat() if as_of_date else None,
        "data": data,
        "total_outstanding": round(sum(r["outstanding"] for r in data), 2),
    }


@router.get("/ap-detail")
async def ap_detail(
    company_id: int | None = Query(None, description="公司 id（选传）"),
    supplier_id: int | None = Query(None, description="供应商 id（选传，单供应商明细）"),
    as_of: str | None = Query(None, description="截止业务日期（YYYY-MM-DD，选传）"),
    include_settled: bool = Query(False, description="含已结清单据（默认 False=仅未清）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """应付款明细表：逐应付单列 单号/供应商/业务日/到期日/价税合计/已付/已核销/未清/状态。= ar_detail 镜像。"""
    company_ids, single_cid, err = _ar_company_scope(user, company_id)
    if err:
        return {"report": "ap_detail", "error": err, "data": []}

    stmt = (
        select(m.AccountsPayable, m.Supplier)
        .join(m.Supplier, m.AccountsPayable.supplier_id == m.Supplier.id, isouter=True)
    )
    if not include_settled:
        stmt = stmt.where(m.AccountsPayable.status.notin_(_AR_CLOSED_STATUSES))
    if single_cid is not None:
        stmt = stmt.where(m.AccountsPayable.company_id == single_cid)
    elif company_ids:
        stmt = stmt.where(m.AccountsPayable.company_id.in_(company_ids))
    if supplier_id is not None:
        stmt = stmt.where(m.AccountsPayable.supplier_id == supplier_id)
    stmt = stmt.order_by(m.AccountsPayable.supplier_id, m.AccountsPayable.id)

    as_of_date = date.fromisoformat(as_of[:10]) if as_of else None
    rows = (await db.execute(stmt)).all()

    data = []
    for ap, sup in rows:
        biz_date = ap.bill_date or ap.due_date
        if as_of_date and biz_date and biz_date > as_of_date:
            continue
        outstanding = _ap_outstanding(ap)
        if not include_settled and outstanding <= 0:
            continue
        data.append({
            "id": ap.id,
            "bill_number": ap.bill_number or "",
            "invoice_number": ap.invoice_number or "",
            "supplier_id": ap.supplier_id,
            "supplier_name": getattr(sup, "name", None) or "(未指定供应商)",
            "supplier_code": getattr(sup, "code", None) or "",
            "bill_type": ap.bill_type,
            "bill_date": ap.bill_date.isoformat() if ap.bill_date else None,
            "due_date": ap.due_date.isoformat() if ap.due_date else None,
            "currency": ap.currency,
            "amount": _dec(ap.amount),
            "untaxed_amount": _dec(getattr(ap, "untaxed_amount", 0)),
            "tax_amount": _dec(getattr(ap, "tax_amount", 0)),
            "paid_amount": _dec(ap.paid_amount),
            "written_off_amount": _dec(getattr(ap, "written_off_amount", 0)),
            "outstanding": round(outstanding, 2),
            "status": ap.status,
            "writeoff_status": getattr(ap, "writeoff_status", None),
        })
    return {
        "report": "ap_detail",
        "company_id": single_cid,
        "supplier_id": supplier_id,
        "as_of": as_of_date.isoformat() if as_of_date else None,
        "data": data,
        "total_outstanding": round(sum(r["outstanding"] for r in data), 2),
    }


@router.get("/supplier-statement")
async def supplier_statement(
    supplier_id: int = Query(..., description="供应商 id（必传，单供应商对账）"),
    company_id: int | None = Query(None, description="公司 id（选传；不传取可见范围）"),
    date_from: str | None = Query(None, description="期间起（YYYY-MM-DD，选传）"),
    date_to: str | None = Query(None, description="期间止（YYYY-MM-DD，选传）"),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """供应商对账单：某供应商期间内 应付（债务+）/ 付款（已付−）时序流水 + 期初/期末余额对账。

    余额口径（原币，应付账款贷增借减）：应付单 credit 方向增加应付余额；付款单 debit 方向冲减。
    期初余额 = date_from 之前的 Σ应付 − Σ付款；逐笔累计出 running_balance（我方欠款）。= customer_statement 镜像。
    """
    company_ids, single_cid, err = _ar_company_scope(user, company_id)
    if err:
        return {"report": "supplier_statement", "error": err, "transactions": []}

    # ★多租户隔离:供应商必须落在调用者可见公司内,否则视为不存在(防 IDOR 跨公司供应商信息泄露)。
    sup_stmt = select(m.Supplier).where(m.Supplier.id == supplier_id)
    if single_cid is not None:
        sup_stmt = sup_stmt.where(m.Supplier.company_id == single_cid)
    elif company_ids:
        sup_stmt = sup_stmt.where(m.Supplier.company_id.in_(company_ids))
    sup = (await db.execute(sup_stmt)).scalar_one_or_none()
    if sup is None:
        return {"report": "supplier_statement", "error": "供应商不存在或无权访问", "transactions": []}

    d_from = date.fromisoformat(date_from[:10]) if date_from else None
    d_to = date.fromisoformat(date_to[:10]) if date_to else None

    def _apply_company(stmt, col):
        if single_cid is not None:
            return stmt.where(col == single_cid)
        if company_ids:
            return stmt.where(col.in_(company_ids))
        return stmt

    # 应付单（债务，按 bill_date 落期；缺则回退 due_date）。仅取已成立（非草稿/非关闭）。
    ap_stmt = _apply_company(
        select(m.AccountsPayable).where(
            m.AccountsPayable.supplier_id == supplier_id,
            m.AccountsPayable.status.notin_(("DRAFT",) + _AR_CLOSED_STATUSES),
        ),
        m.AccountsPayable.company_id,
    )
    bills = (await db.execute(ap_stmt)).scalars().all()

    # 付款单（已付，按 payment_date 落期）。仅取已审核（成立）。
    pay_stmt = _apply_company(
        select(m.APPayment).where(
            m.APPayment.supplier_id == supplier_id,
            m.APPayment.status == "AUDITED",
        ),
        m.APPayment.company_id,
    )
    payments = (await db.execute(pay_stmt)).scalars().all()

    # 统一事件流：应付单 credit(+应付)，付款单 debit(−应付)。
    events = []
    for b in bills:
        bd = b.bill_date or b.due_date
        events.append({
            "date": bd, "type": "AP_BILL", "doc_no": b.bill_number or b.invoice_number or f"AP#{b.id}",
            "debit": 0.0, "credit": _dec(b.amount), "currency": b.currency, "doc_id": b.id,
            "due_date": b.due_date.isoformat() if b.due_date else None,
        })
    for p in payments:
        events.append({
            "date": p.payment_date, "type": "AP_PAYMENT", "doc_no": p.payment_number or f"FK#{p.id}",
            "debit": _dec(p.amount), "credit": 0.0, "currency": p.currency, "doc_id": p.id,
            "is_advance": bool(p.is_advance),
        })

    # 期初余额（date_from 之前的净额）= Σ应付(credit) − Σ付款(debit)。
    opening = 0.0
    for e in events:
        if d_from and e["date"] and e["date"] < d_from:
            opening += e["credit"] - e["debit"]

    def _in_window(ev):
        ed = ev["date"]
        if ed is None:
            return True
        if d_from and ed < d_from:
            return False
        if d_to and ed > d_to:
            return False
        return True

    window = [e for e in events if _in_window(e)]
    window.sort(key=lambda e: (e["date"] or date.max, 0 if e["type"] == "AP_BILL" else 1))

    running = round(opening, 2)
    txns = []
    total_debit = 0.0
    total_credit = 0.0
    for e in window:
        running = round(running + e["credit"] - e["debit"], 2)
        total_debit += e["debit"]
        total_credit += e["credit"]
        txns.append({
            "date": e["date"].isoformat() if e["date"] else None,
            "type": e["type"],
            "doc_no": e["doc_no"],
            "currency": e["currency"],
            "debit": round(e["debit"], 2),
            "credit": round(e["credit"], 2),
            "running_balance": running,
            "due_date": e.get("due_date"),
            "is_advance": e.get("is_advance"),
            "doc_id": e["doc_id"],
        })

    return {
        "report": "supplier_statement",
        "company_id": single_cid,
        "supplier_id": supplier_id,
        "supplier_name": getattr(sup, "name", None),
        "supplier_code": getattr(sup, "code", None),
        "date_from": d_from.isoformat() if d_from else None,
        "date_to": d_to.isoformat() if d_to else None,
        "opening_balance": round(opening, 2),
        "closing_balance": running,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "transactions": txns,
    }

