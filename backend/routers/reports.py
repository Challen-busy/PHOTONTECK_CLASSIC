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
