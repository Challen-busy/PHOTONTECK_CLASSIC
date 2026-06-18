"""总账·第六波（finance-gl wave-6，A 部分）：现金流量归集命令。

现金流量表（reports.cash_flow_statement）靠 VoucherEntry.cashflow_item_id 归集，但日常记账多不手填
该字段（现 0 流量）。本模块按 CashflowAssignRule（对手科目码区间 + 现金方向 → 现金流量项目）规则，
对「含现金类科目（1001/1002…，balance_direction=DEBIT）」的凭证，把对手方分录的 cashflow_item_id
批量补标，让现金流量表自动出数。无规则命中的对手分录留空（入现金流量表 unclassified 桶）。

本模块只走「命令扩展点」（@register_command），引擎核心三件（registry / execute_transition /
execute_command）字节级零 diff，全部新文件、不改既有 effect/validator——补标只改 VoucherEntry.cashflow_item_id
这一非过账关键字段（不动借贷金额/状态），由 execute_command 外壳统一 commit/留痕/幂等。

一个命令（@register_command，module=FINANCE）：
  finance.assign_cashflow —— payload {voucher_id} 单张 或 {period_id} 批量（本期所有现金凭证）：
    对每张「含现金类科目」的凭证，按规则给对手方分录填 cashflow_item_id（已标的不覆盖，除非 overwrite=True）。
    返回标记数 marked / 扫描凭证数 / 未命中规则的对手分录数 unclassified。

T 型账 / 现金流量查询端点在 routers/reports.py 内另加（复用现有 reports 取数风格）。
"""

from sqlalchemy import select

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter


# 现金类科目识别：code 以这些前缀打头（库存现金/银行存款/其他货币资金）且为资产借向科目。
_CASH_CODE_PREFIXES = ("1001", "1002", "1012")


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


def _is_cash_account(account: m.Account) -> bool:
    """现金类科目：code 以现金前缀打头且余额方向 DEBIT（资产借向）。"""
    if account is None or not account.code:
        return False
    return account.code.startswith(_CASH_CODE_PREFIXES) and account.balance_direction == "DEBIT"


def _entry_amount(entry: m.VoucherEntry):
    """分录本位币发生额（取借/贷非零边）。返回 (amount, side)：side='DR' 借方增 / 'CR' 贷方增。"""
    bd = entry.base_debit or 0
    bc = entry.base_credit or 0
    if bd and bd != 0:
        return bd, "DR"
    return bc, "CR"


def _code_in_range(code: str, lo: str, hi: str) -> bool:
    """对手科目码是否落在规则区间 [lo, hi]（字符串比对；端为空视为开区间）。"""
    if lo and code < lo:
        return False
    if hi and code > hi:
        return False
    return True


def _match_rule(rules: list, counter_account: m.Account, cash_direction: str):
    """对手分录命中哪条规则。cash_direction = 本凭证的现金方向（IN 现金增/借 / OUT 现金减/贷）。
    规则按 priority 升序取第一条命中者：对手科目码落区间 + 规则方向 BOTH 或与本凭证现金方向一致。"""
    code = counter_account.code or ""
    for rule in rules:
        if not _code_in_range(code, rule.account_code_from or "", rule.account_code_to or ""):
            continue
        if rule.cash_direction != "BOTH" and rule.cash_direction != cash_direction:
            continue
        return rule
    return None


async def _assign_one_voucher(
    ctx: CommandContext, voucher: m.Voucher, rules: list, *, overwrite: bool,
) -> dict:
    """对单张凭证做现金流量归集：识别现金类分录定方向 → 对手分录按规则补标 cashflow_item_id。

    返回 {voucher_id, is_cash, marked, unclassified, lines:[{line_number, account_code, item_id?}]}。
    现金方向：现金类科目在借方 → IN（现金流入）；在贷方 → OUT（现金流出）。
    一张凭证可能多张现金分录方向不一（少见），按各现金分录净方向定整单 cash_direction：
    现金净借>净贷 → IN，否则 OUT。
    """
    entries = (await ctx.db.execute(
        select(m.VoucherEntry, m.Account)
        .join(m.Account, m.VoucherEntry.account_id == m.Account.id)
        .where(m.VoucherEntry.voucher_id == voucher.id)
        .order_by(m.VoucherEntry.line_number)
    )).all()

    cash_entries = [(e, a) for e, a in entries if _is_cash_account(a)]
    if not cash_entries:
        return {"voucher_id": voucher.id, "is_cash": False, "marked": 0, "unclassified": 0, "lines": []}

    # 整单现金方向：现金类分录净借 vs 净贷。
    cash_net_debit = sum((e.base_debit or 0) - (e.base_credit or 0) for e, _ in cash_entries)
    cash_direction = "IN" if cash_net_debit > 0 else "OUT"

    counter_entries = [(e, a) for e, a in entries if not _is_cash_account(a)]
    marked = 0
    unclassified = 0
    line_results: list[dict] = []
    for entry, acct in counter_entries:
        if entry.cashflow_item_id is not None and not overwrite:
            line_results.append({"line_number": entry.line_number, "account_code": acct.code,
                                 "item_id": entry.cashflow_item_id, "note": "已标，跳过"})
            continue
        rule = _match_rule(rules, acct, cash_direction)
        if rule is None:
            unclassified += 1
            line_results.append({"line_number": entry.line_number, "account_code": acct.code,
                                 "item_id": None, "note": "无规则命中（unclassified）"})
            continue
        entry.cashflow_item_id = rule.cashflow_item_id
        marked += 1
        line_results.append({"line_number": entry.line_number, "account_code": acct.code,
                             "item_id": rule.cashflow_item_id, "rule_code": rule.code})
    if marked:
        await ctx.db.flush()
    return {"voucher_id": voucher.id, "is_cash": True, "cash_direction": cash_direction,
            "marked": marked, "unclassified": unclassified, "lines": line_results}


@register_command(
    "finance.assign_cashflow",
    module="FINANCE",
    title="现金流量归集",
    description=(
        "对含现金类科目（1001/1002…）的凭证，按 CashflowAssignRule（对手科目码区间+现金方向→现金流量项目）"
        "给对手方分录补标 cashflow_item_id；无规则命中留空（入现金流量表未分类桶）。"
        "payload {voucher_id} 单张 或 {period_id} 批量本期现金凭证。"
    ),
    affected_tables=("voucher_entry",),
    supports_retry=True,
)
async def assign_cashflow(ctx: CommandContext, payload: dict) -> dict:
    """现金流量归集（按规则给现金凭证对手分录补标现金流量项目）。

    payload：
      voucher_id: int   —— 单张凭证补标（与 period_id 二选一）
      period_id: int    —— 批量：本公司本期所有含现金类科目的凭证（DRAFT/AUDITED/REVIEWED/POSTED 都补标）
      company_id: int   —— period_id 批量时定位规则/凭证所属公司（不传则按各凭证自带 company_id）
      overwrite: bool   —— 默认 False（已标 cashflow_item_id 的对手分录不覆盖）

    返回 {scope, scanned, cash_vouchers, marked, unclassified, results:[...]}。
    """
    voucher_id = payload.get("voucher_id")
    period_id = payload.get("period_id")
    overwrite = bool(payload.get("overwrite"))
    if not voucher_id and not period_id:
        raise CommandError("voucher_id 与 period_id 至少传一个")

    # 单张 vs 批量取凭证集。
    if voucher_id:
        vouchers = (await ctx.db.execute(
            select(m.Voucher).where(m.Voucher.id == voucher_id)
        )).scalars().all()
        if not vouchers:
            raise CommandError("凭证不存在", 404)
        company_id = vouchers[0].company_id
        scope = "voucher"
    else:
        company_id = payload.get("company_id")
        stmt = select(m.Voucher).where(m.Voucher.period_id == period_id)
        if company_id:
            stmt = stmt.where(m.Voucher.company_id == company_id)
        vouchers = (await ctx.db.execute(stmt.order_by(m.Voucher.id))).scalars().all()
        if vouchers and not company_id:
            company_id = vouchers[0].company_id
        scope = "period"
    if company_id:
        _assert_company_access(ctx.user, company_id)

    # 本公司归集规则（按 priority 升序，仅启用）。批量跨公司时按各凭证 company_id 取规则。
    async def _rules_for(cid: int) -> list:
        return (await ctx.db.execute(
            select(m.CashflowAssignRule)
            .where(m.CashflowAssignRule.company_id == cid)
            .where(m.CashflowAssignRule.is_active == True)  # noqa: E712
            .order_by(m.CashflowAssignRule.priority, m.CashflowAssignRule.id)
        )).scalars().all()

    rules_cache: dict[int, list] = {}
    scanned = 0
    cash_vouchers = 0
    marked = 0
    unclassified = 0
    results: list[dict] = []
    for voucher in vouchers:
        scanned += 1
        rules = rules_cache.get(voucher.company_id)
        if rules is None:
            rules = await _rules_for(voucher.company_id)
            rules_cache[voucher.company_id] = rules
        res = await _assign_one_voucher(ctx, voucher, rules, overwrite=overwrite)
        if res["is_cash"]:
            cash_vouchers += 1
            marked += res["marked"]
            unclassified += res["unclassified"]
            results.append(res)

    ctx.add_event("finance_assign_cashflow", {
        "scope": scope, "company_id": company_id, "scanned": scanned,
        "cash_vouchers": cash_vouchers, "marked": marked, "unclassified": unclassified,
    })
    return {
        "scope": scope,
        "company_id": company_id,
        "scanned": scanned,
        "cash_vouchers": cash_vouchers,
        "marked": marked,
        "unclassified": unclassified,
        "results": results,
        "message": (f"扫描 {scanned} 张，其中现金凭证 {cash_vouchers} 张，"
                    f"补标对手分录 {marked} 行，未命中规则 {unclassified} 行（入未分类）"),
    }
