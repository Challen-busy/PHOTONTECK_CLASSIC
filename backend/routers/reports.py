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
