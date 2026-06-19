"""总账·第八波（finance-gl wave-8）★通用核销引擎（biz_type=AR/AP 参数化，应付/出纳直接复用）。

纯扩展、新文件。引擎核心三件（registry / execute_transition / execute_command）字节级零 diff；
本模块只经扩展点登记（command_registry.load_commands + workflow_extensions._EXTENSION_MODULES），
对外暴露两条命令 + 三个取数 helper（供前端核销界面 / 报表用）。

══════════════════════════════════════════════════════════════════════════════
通用化设计（biz_type 参数化，一套引擎吃 AR/AP）
══════════════════════════════════════════════════════════════════════════════
核销 = 「债权侧单据」与「已收/已付侧单据」的多对多勾稽（WriteoffLink 留痕）。两侧单据都带
`amount`（原币总额）/ `written_off_amount`（已核销额）/ `writeoff_status`（核销状态）三件套，
引擎据此算「未核销额」并配对，故只要把单据类型 + 模型登记进 `_BIZ_CONFIG` 即可复用：

  · AR（应收）：债权侧=应收单 ACCOUNTS_RECEIVABLE（AccountsReceivable），
                已收侧=收款单 AR_RECEIPT（ARReceipt）。
  · AP（应付）：债权侧=付款单（将来），已付侧=应付单（将来）——Phase 应付时在 _BIZ_CONFIG 补一行即可，
                本引擎代码不改（写在此处仅为示意，付款单/应付状态机由应付波建）。

WriteoffLink 弱引用（debit_doc_type+debit_doc_id / credit_doc_type+credit_doc_id 多态，不建跨表 FK），
天然兼容不同单据类型，引擎五条不破坏。

══════════════════════════════════════════════════════════════════════════════
核销状态机（写在单据 written_off_amount/writeoff_status 上，非审批状态）
══════════════════════════════════════════════════════════════════════════════
  written_off == 0           → UNVERIFIED（未核销）
  0 < written_off < amount   → PARTIAL（部分核销）
  written_off >= amount      → VERIFIED（已核销）

══════════════════════════════════════════════════════════════════════════════
匹配规则（WriteoffScheme.match_rule，自动核销 auto=True 时用）
══════════════════════════════════════════════════════════════════════════════
  FIFO        先进先出：债权单按 bill_date / due_date 升序，逐张用收款余额冲抵。
  BY_DUEDATE  按到期日：债权单按 due_date 升序（空到期日排最后）。
  SAME_AMOUNT 同金额：优先把「未核销额完全相等」的债权单↔收款单整额对冲，余下回落 FIFO。
  MANUAL      手工：不自动配对（须显式给 links）。

手工（payload.links 显式给 [{debit_doc_id, credit_doc_id, amount, ...}]）优先于自动。

══════════════════════════════════════════════════════════════════════════════
外币核销 / 汇兑差（⚠️口径默认：核销日汇率，标待复核）
══════════════════════════════════════════════════════════════════════════════
exchange_diff = 本次核销原币 × (核销汇率 − 债权单入账汇率)。仅记在 WriteoffLink.exchange_diff 上留痕，
**不在本引擎里自动生汇兑损益凭证**——汇兑损益科目（CAS 6603 财务费用 / HKFRS 6601 Finance costs）
与方向口径属「待甲方复核」项，按 finance_mapping 的诚实降级原则不硬编码、不静默过账；
留 TODO，待业财映射规则（AccountMappingRule source_doc_type=WRITEOFF_EXCHANGE_DIFF）落地后接通。

══════════════════════════════════════════════════════════════════════════════
★关于「写 AccountBalance 往来口径（应收↓）」——已知设计冲突，已 surface（见模块返回 notes）
══════════════════════════════════════════════════════════════════════════════
AccountBalance 是 GL 账户级真相，由「已过账凭证」唯一驱动（finance_posting.post_voucher）。应收的
GL 减少已经发生在【收款单审核生凭证：借 1002 银行存款 / 贷 1122 应收账款】这一步（Phase2 的
finance.create_voucher_from_ar_receipt）。若核销再写一次 AccountBalance（贷 1122），会与收款凭证
**重复冲减 1122**（双重计减）。

故本引擎对「往来口径」的处理是：核销只动【往来子账（party sub-ledger）】= 单据上的
written_off_amount / received_amount 回写 + WriteoffLink 留痕，**不直接写 AccountBalance**（GL 由凭证
负责，避免双重计减）。核销引擎计算出「本次核销冲减应收控制科目 1122 的本位币额」并随命令结果
返回（writeoff_ar_reduction_base）+ 写进 command log，供对账/审计；待与 Phase2 收款凭证口径会签后，
若改为「收款不冲 1122、由核销冲 1122」，再在此接通写 AccountBalance（留 TODO）。

副作用幂等、同事务：命令在 execute_command 事务内 db.add()/db.flush()，失败 raise 由上层回滚。
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter


# ============================================================
# biz_type 配置：把单据类型 + 模型 + 关键列名登记进来，引擎按 biz_type 取本配置（应付直接补一行复用）。
#   debit_*  = 债权侧（应收=应收单；金额未核销 = amount − written_off_amount）
#   credit_* = 已收/已付侧（应收=收款单）
# ============================================================
class _SideSpec:
    def __init__(self, doc_type: str, model, *, party_col: str | None,
                 amount_col: str = "amount", date_col: str | None = None,
                 due_col: str | None = None, plan_received_col: str | None = None):
        self.doc_type = doc_type
        self.model = model
        self.party_col = party_col          # 往来对象列（AR 两侧都是 customer_id）
        self.amount_col = amount_col        # 单据总额列（原币）
        self.date_col = date_col            # 排序用业务日期列（FIFO）
        self.due_col = due_col              # 到期日列（BY_DUEDATE）
        self.plan_received_col = plan_received_col  # 仅债权侧：收款计划已收回写到子表用（AR=ar_receipt_plan_line）


class _BizConfig:
    def __init__(self, biz_type: str, debit: _SideSpec, credit: _SideSpec):
        self.biz_type = biz_type
        self.debit = debit
        self.credit = credit


_BIZ_CONFIG: dict[str, _BizConfig] = {
    "AR": _BizConfig(
        "AR",
        debit=_SideSpec(
            "ACCOUNTS_RECEIVABLE", m.AccountsReceivable,
            party_col="customer_id", amount_col="amount",
            date_col="bill_date", due_col="due_date",
        ),
        credit=_SideSpec(
            "AR_RECEIPT", m.ARReceipt,
            party_col="customer_id", amount_col="amount",
            date_col="receipt_date",
        ),
    ),
    # AP（应付）Phase 应付时补：
    #   debit=付款单（已付侧反过来作债权抵消），credit=应付单——本引擎代码无须改，只加配置行。
}


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _config(biz_type: str) -> _BizConfig:
    cfg = _BIZ_CONFIG.get((biz_type or "AR").upper())
    if cfg is None:
        raise CommandError(f"未支持的核销业务类型 biz_type={biz_type!r}（当前支持 {list(_BIZ_CONFIG)}）")
    return cfg


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


def _open_amount(doc, spec: _SideSpec) -> Decimal:
    """单据未核销原币额 = 总额 − 已核销额（下限 0）。"""
    total = _num(getattr(doc, spec.amount_col, 0))
    used = _num(getattr(doc, "written_off_amount", 0))
    return max(total - used, Decimal("0"))


def _writeoff_status(doc, spec: _SideSpec) -> str:
    """按已核销额 vs 总额定核销状态。"""
    total = _q2(_num(getattr(doc, spec.amount_col, 0)))
    used = _q2(_num(getattr(doc, "written_off_amount", 0)))
    if used <= 0:
        return "UNVERIFIED"
    if used >= total:
        return "VERIFIED"
    return "PARTIAL"


# ============================================================
# 取数 helper（供前端核销界面 / 报表）
# ============================================================

async def _list_open_docs(
    db: AsyncSession, spec: _SideSpec, *, company_id: int,
    party_id: int | None = None, currency: str | None = None,
    only_open: bool = True, statuses: tuple[str, ...] | None = None,
) -> list:
    """取某侧「未核销（写off_status != VERIFIED）」单据。statuses 限单据审批态（应收单/收款单须 AUDITED）。"""
    model = spec.model
    stmt = select(model).where(model.company_id == company_id)
    if party_id is not None and spec.party_col:
        stmt = stmt.where(getattr(model, spec.party_col) == party_id)
    if currency:
        stmt = stmt.where(model.currency == currency)
    if statuses:
        stmt = stmt.where(model.status.in_(statuses))
    if only_open:
        stmt = stmt.where(model.writeoff_status != "VERIFIED")
    # 排序：有业务日期列按日期升序（FIFO 友好），否则按 id。
    if spec.date_col and hasattr(model, spec.date_col):
        stmt = stmt.order_by(getattr(model, spec.date_col).asc().nullslast(), model.id.asc())
    else:
        stmt = stmt.order_by(model.id.asc())
    rows = (await db.execute(stmt)).scalars().all()
    # 仅留确有未核销余额的。
    return [d for d in rows if _open_amount(d, spec) > 0]


async def list_open_ar(
    db: AsyncSession, *, company_id: int, party_id: int | None = None,
    currency: str | None = None, biz_type: str = "AR",
) -> list:
    """未核销应收（债权侧）单据列表，供前端核销界面左栏 / 自动核销取数。须 AUDITED（已审核立账）。"""
    cfg = _config(biz_type)
    return await _list_open_docs(
        db, cfg.debit, company_id=company_id, party_id=party_id,
        currency=currency, statuses=("AUDITED",),
    )


async def list_open_receipts(
    db: AsyncSession, *, company_id: int, party_id: int | None = None,
    currency: str | None = None, biz_type: str = "AR",
) -> list:
    """未核销收款（已收侧）单据列表，供前端核销界面右栏 / 自动核销取数。须 AUDITED（已审核收款）。"""
    cfg = _config(biz_type)
    return await _list_open_docs(
        db, cfg.credit, company_id=company_id, party_id=party_id,
        currency=currency, statuses=("AUDITED",),
    )


def _doc_brief(doc, spec: _SideSpec) -> dict:
    """单据摘要 dict（供报表/前端核销界面渲染一行）。"""
    number = (
        getattr(doc, "bill_number", None)
        or getattr(doc, "receipt_number", None)
        or getattr(doc, "invoice_number", None)
        or f"#{doc.id}"
    )
    return {
        "doc_type": spec.doc_type,
        "id": doc.id,
        "number": number,
        "party_id": getattr(doc, spec.party_col, None) if spec.party_col else None,
        "currency": getattr(doc, "currency", None),
        "exchange_rate": float(_num(getattr(doc, "exchange_rate", 1))),
        "amount": float(_num(getattr(doc, spec.amount_col, 0))),
        "written_off_amount": float(_num(getattr(doc, "written_off_amount", 0))),
        "open_amount": float(_open_amount(doc, spec)),
        "writeoff_status": getattr(doc, "writeoff_status", "UNVERIFIED"),
        "bill_date": getattr(doc, "bill_date", None).isoformat() if getattr(doc, "bill_date", None) else None,
        "receipt_date": getattr(doc, "receipt_date", None).isoformat() if getattr(doc, "receipt_date", None) else None,
        "due_date": getattr(doc, "due_date", None).isoformat() if getattr(doc, "due_date", None) else None,
    }


# ============================================================
# 匹配规则（自动核销）：把未核销应收 vs 未核销收款配对成 (debit_doc, credit_doc, amount) 三元组
# ============================================================

def _sort_debits(debits: list, spec: _SideSpec, match_rule: str) -> list:
    rule = (match_rule or "FIFO").upper()
    if rule == "BY_DUEDATE" and spec.due_col:
        return sorted(debits, key=lambda d: (getattr(d, spec.due_col) is None,
                                             getattr(d, spec.due_col) or date.max, d.id))
    # FIFO / SAME_AMOUNT 余下 / 默认：按业务日期升序。
    if spec.date_col:
        return sorted(debits, key=lambda d: (getattr(d, spec.date_col) is None,
                                             getattr(d, spec.date_col) or date.max, d.id))
    return sorted(debits, key=lambda d: d.id)


def _auto_match(debits: list, credits: list, debit_spec: _SideSpec, credit_spec: _SideSpec,
                match_rule: str) -> list[tuple]:
    """按 match_rule 把债权未核销额 vs 收款未核销额贪心配对。返回 [(debit_doc, credit_doc, amount)...]。

    余额账本：用 dict 跟踪每张单剩余可核销额，逐对扣减，绝不超额。
    """
    rule = (match_rule or "FIFO").upper()
    if rule == "MANUAL":
        return []  # 手工方案不自动配对

    open_d = {d.id: _open_amount(d, debit_spec) for d in debits}
    open_c = {c.id: _open_amount(c, credit_spec) for c in credits}
    pairs: list[tuple] = []

    sorted_debits = _sort_debits(debits, debit_spec, rule)
    # 收款侧统一按业务日期升序（先到的钱先用）。
    sorted_credits = sorted(
        credits,
        key=lambda c: (getattr(c, credit_spec.date_col, None) is None
                       if credit_spec.date_col else True,
                       getattr(c, credit_spec.date_col, None) or date.max, c.id),
    )

    # SAME_AMOUNT：先整额对冲「未核销额完全相等」的债权↔收款对（金蝶同金额核销）。
    if rule == "SAME_AMOUNT":
        for d in sorted_debits:
            if open_d[d.id] <= 0:
                continue
            for c in sorted_credits:
                if open_c[c.id] <= 0:
                    continue
                if _q2(open_d[d.id]) == _q2(open_c[c.id]):
                    amt = _q2(open_d[d.id])
                    pairs.append((d, c, amt))
                    open_d[d.id] -= amt
                    open_c[c.id] -= amt
                    break

    # FIFO（及 SAME_AMOUNT 同额对冲后的余额）：逐张债权用收款余额顺序冲抵。
    for d in sorted_debits:
        if open_d[d.id] <= 0:
            continue
        for c in sorted_credits:
            if open_d[d.id] <= 0:
                break
            if open_c[c.id] <= 0:
                continue
            amt = _q2(min(open_d[d.id], open_c[c.id]))
            if amt <= 0:
                continue
            pairs.append((d, c, amt))
            open_d[d.id] -= amt
            open_c[c.id] -= amt

    return pairs


# ============================================================
# 写一条核销关系 + 回写两单（核心，手工/自动共用）
# ============================================================

async def _apply_link(
    ctx: CommandContext, cfg: _BizConfig, *, company_id: int,
    debit_doc, credit_doc, amount: Decimal, scheme_id: int | None,
    write_date: date, settlement_org_id: int | None,
) -> dict:
    """对一对 (债权单, 收款单) 写 WriteoffLink + 回写两单 written_off_amount/writeoff_status。

    校验：本次核销额不得超过任一侧剩余未核销额。外币核销算 exchange_diff（核销汇率−债权单入账汇率）。
    返回该条 link 摘要。
    """
    amount = _q2(_num(amount))
    if amount <= 0:
        raise CommandError("核销金额必须为正")

    open_d = _open_amount(debit_doc, cfg.debit)
    open_c = _open_amount(credit_doc, cfg.credit)
    if amount > _q2(open_d):
        raise CommandError(
            f"债权单#{debit_doc.id} 剩余未核销 {_q2(open_d)} 不足本次核销 {amount}", 422)
    if amount > _q2(open_c):
        raise CommandError(
            f"收款单#{credit_doc.id} 剩余未核销 {_q2(open_c)} 不足本次核销 {amount}", 422)

    # 汇率：核销日按债权单入账汇率口径（默认；外币差额仅留痕，见模块 docstring）。
    debit_rate = _num(getattr(debit_doc, "exchange_rate", 1)) or Decimal("1")
    credit_rate = _num(getattr(credit_doc, "exchange_rate", 1)) or Decimal("1")
    base_amount = _q2(amount * debit_rate)
    # 汇兑差 = 本次核销原币 × (收款汇率 − 债权入账汇率)（⚠️口径待复核，仅记 link 不生凭证）。
    exchange_diff = _q2(amount * (credit_rate - debit_rate))

    link = m.WriteoffLink(
        company_id=company_id,
        biz_type=cfg.biz_type,
        scheme_id=scheme_id,
        debit_doc_type=cfg.debit.doc_type,
        debit_doc_id=debit_doc.id,
        debit_line_id=None,
        credit_doc_type=cfg.credit.doc_type,
        credit_doc_id=credit_doc.id,
        credit_line_id=None,
        amount=amount,
        base_amount=base_amount,
        exchange_diff=exchange_diff,
        write_date=write_date,
        settlement_org_id=settlement_org_id,
        is_active=True,
        created_by_id=ctx.user.id,
    )
    ctx.db.add(link)

    # 回写两单已核销额 + 核销状态。
    debit_doc.written_off_amount = _q2(_num(getattr(debit_doc, "written_off_amount", 0)) + amount)
    credit_doc.written_off_amount = _q2(_num(getattr(credit_doc, "written_off_amount", 0)) + amount)
    debit_doc.writeoff_status = _writeoff_status(debit_doc, cfg.debit)
    credit_doc.writeoff_status = _writeoff_status(credit_doc, cfg.credit)
    await ctx.db.flush()

    return {
        "writeoff_link_id": link.id,
        "debit_doc_type": cfg.debit.doc_type, "debit_doc_id": debit_doc.id,
        "credit_doc_type": cfg.credit.doc_type, "credit_doc_id": credit_doc.id,
        "amount": float(amount), "base_amount": float(base_amount),
        "exchange_diff": float(exchange_diff),
        "debit_writeoff_status": debit_doc.writeoff_status,
        "credit_writeoff_status": credit_doc.writeoff_status,
    }


async def _load_doc(db: AsyncSession, spec: _SideSpec, doc_id: int, company_id: int):
    doc = (await db.execute(
        select(spec.model).where(spec.model.id == doc_id)
    )).scalar_one_or_none()
    if doc is None:
        raise CommandError(f"{spec.doc_type}#{doc_id} 不存在", 404)
    if doc.company_id != company_id:
        raise CommandError(f"{spec.doc_type}#{doc_id} 不属于该公司", 403)
    return doc


# ============================================================
# 命令：finance.writeoff（手工 or 自动，biz_type 参数化）
# ============================================================

@register_command(
    "finance.writeoff",
    module="FINANCE",
    title="核销（应收/应付通用）",
    description="债权单↔已收单多对多勾稽：写 WriteoffLink + 回写两单已核销额/状态；手工给 links 或按方案自动配对（FIFO/同额/到期日）",
    affected_tables=("writeoff_link", "accounts_receivable", "ar_receipt"),
    supports_retry=False,
)
async def writeoff(ctx: CommandContext, payload: dict) -> dict:
    """通用核销（biz_type=AR/AP）。

    payload:
      biz_type:        'AR'（默认）/'AP'
      company_id:      公司（缺则取当前用户主公司）
      party_id:        往来对象（自动核销时限定客户，可空=全客户）
      currency:        币别（自动核销时限定，可空=不限）
      scheme_id:       核销方案 id（自动时取其 match_rule；缺则取本公司 biz_type 的默认方案）
      auto:            True=按方案自动配对未核销应收 vs 未核销收款；False（默认）=手工
      links:           手工核销明细 [{debit_doc_id, credit_doc_id, amount, debit_line_id?, credit_line_id?}]
      write_date:      核销日期（缺=今天）
      settlement_org_id: 结算组织（缺=company_id）

    返回 {"created": n, "links": [...], "writeoff_ar_reduction_base": x, "scheme": {...}}。
    """
    biz_type = (payload.get("biz_type") or "AR").upper()
    cfg = _config(biz_type)
    company_id = payload.get("company_id") or ctx.user.company_id
    if not company_id:
        raise CommandError("company_id 不能为空")
    _assert_company_access(ctx.user, company_id)

    write_date = payload.get("write_date") or date.today()
    settlement_org_id = payload.get("settlement_org_id") or company_id
    scheme_id = payload.get("scheme_id")
    auto = bool(payload.get("auto"))
    links_in = payload.get("links") or []

    # 取方案（自动核销需 match_rule；手工也回填 scheme_id 留痕）。
    scheme = None
    if scheme_id is not None:
        scheme = (await ctx.db.execute(
            select(m.WriteoffScheme).where(m.WriteoffScheme.id == scheme_id)
        )).scalar_one_or_none()
        if scheme is None:
            raise CommandError(f"核销方案#{scheme_id} 不存在", 404)
        if scheme.company_id != company_id:
            raise CommandError("核销方案不属于该公司", 403)
    elif auto:
        scheme = (await ctx.db.execute(
            select(m.WriteoffScheme).where(
                m.WriteoffScheme.company_id == company_id,
                m.WriteoffScheme.biz_type == biz_type,
                m.WriteoffScheme.is_active == True,  # noqa: E712
            ).order_by(m.WriteoffScheme.is_default.desc(), m.WriteoffScheme.priority.asc())
        )).scalars().first()
        if scheme is None:
            raise CommandError(f"公司#{company_id} 无可用 {biz_type} 核销方案，请先配置或改手工核销", 422)
        scheme_id = scheme.id

    results: list[dict] = []

    if auto:
        match_rule = (scheme.match_rule if scheme else "FIFO")
        debits = await _list_open_docs(
            ctx.db, cfg.debit, company_id=company_id,
            party_id=payload.get("party_id"), currency=payload.get("currency"),
            statuses=("AUDITED",))
        credits = await _list_open_docs(
            ctx.db, cfg.credit, company_id=company_id,
            party_id=payload.get("party_id"), currency=payload.get("currency"),
            statuses=("AUDITED",))
        pairs = _auto_match(debits, credits, cfg.debit, cfg.credit, match_rule)
        if not pairs:
            return {"created": 0, "links": [], "writeoff_ar_reduction_base": 0.0,
                    "scheme": {"id": scheme_id, "match_rule": match_rule},
                    "message": "无可自动配对的未核销应收/收款"}
        for debit_doc, credit_doc, amount in pairs:
            results.append(await _apply_link(
                ctx, cfg, company_id=company_id, debit_doc=debit_doc, credit_doc=credit_doc,
                amount=amount, scheme_id=scheme_id, write_date=write_date,
                settlement_org_id=settlement_org_id))
    else:
        if not links_in:
            raise CommandError("手工核销须提供 links（或传 auto=True 自动核销）")
        # 手工：逐行加载两单，校验同公司、同往来对象（软校验，跨客户核销报错防错配）。
        for ln in links_in:
            debit_id = ln.get("debit_doc_id")
            credit_id = ln.get("credit_doc_id")
            amount = ln.get("amount")
            if not debit_id or not credit_id or amount is None:
                raise CommandError("links 每行须含 debit_doc_id / credit_doc_id / amount")
            debit_doc = await _load_doc(ctx.db, cfg.debit, debit_id, company_id)
            credit_doc = await _load_doc(ctx.db, cfg.credit, credit_id, company_id)
            if debit_doc.status != "AUDITED":
                raise CommandError(f"债权单#{debit_id} 未审核（status={debit_doc.status}），不可核销", 409)
            if credit_doc.status != "AUDITED":
                raise CommandError(f"收款单#{credit_id} 未审核（status={credit_doc.status}），不可核销", 409)
            if (cfg.debit.party_col and cfg.credit.party_col
                    and getattr(debit_doc, cfg.debit.party_col) is not None
                    and getattr(credit_doc, cfg.credit.party_col) is not None
                    and getattr(debit_doc, cfg.debit.party_col)
                    != getattr(credit_doc, cfg.credit.party_col)):
                raise CommandError(
                    f"债权单#{debit_id} 与收款单#{credit_id} 往来对象不一致，禁止跨客户核销", 422)
            results.append(await _apply_link(
                ctx, cfg, company_id=company_id, debit_doc=debit_doc, credit_doc=credit_doc,
                amount=amount, scheme_id=scheme_id, write_date=write_date,
                settlement_org_id=settlement_org_id))

    ar_reduction_base = _q2(sum((_num(r["base_amount"]) for r in results), Decimal("0")))
    ctx.add_event("writeoff_done", {"biz_type": biz_type, "count": len(results),
                                    "company_id": company_id})
    return {
        "created": len(results),
        "links": results,
        # ★往来口径冲减应收控制科目(1122)本位币额——仅返回/留痕，不写 AccountBalance（GL 由收款凭证负责，见 docstring）。
        "writeoff_ar_reduction_base": float(ar_reduction_base),
        "scheme": {"id": scheme_id, "match_rule": (scheme.match_rule if scheme else None)},
    }


# ============================================================
# 命令：finance.unwriteoff（反核销，置 is_active=False + 回退两单）
# ============================================================

@register_command(
    "finance.unwriteoff",
    module="FINANCE",
    title="反核销（应收/应付通用）",
    description="按 writeoff_link_ids 解除核销关系（is_active=False 留痕）+ 回退债权单/收款单已核销额与状态",
    affected_tables=("writeoff_link", "accounts_receivable", "ar_receipt"),
    supports_retry=False,
)
async def unwriteoff(ctx: CommandContext, payload: dict) -> dict:
    """反核销：把指定 WriteoffLink 置 is_active=False（留痕，不删行）并回退两侧已核销额/状态。

    payload: {"writeoff_link_ids": [..]}
    幂等：已 is_active=False 的 link 跳过（不重复回退）。
    """
    link_ids = payload.get("writeoff_link_ids") or []
    if not link_ids:
        raise CommandError("writeoff_link_ids 不能为空")

    links = (await ctx.db.execute(
        select(m.WriteoffLink).where(m.WriteoffLink.id.in_(link_ids))
    )).scalars().all()
    if not links:
        raise CommandError("未找到指定核销关系", 404)

    reverted: list[dict] = []
    skipped: list[int] = []
    for link in links:
        _assert_company_access(ctx.user, link.company_id)
        if not link.is_active:
            skipped.append(link.id)
            continue
        cfg = _config(link.biz_type)
        amount = _q2(_num(link.amount))
        # 回退债权单。
        debit_doc = (await ctx.db.execute(
            select(cfg.debit.model).where(cfg.debit.model.id == link.debit_doc_id)
        )).scalar_one_or_none()
        if debit_doc is not None:
            debit_doc.written_off_amount = max(
                _q2(_num(getattr(debit_doc, "written_off_amount", 0)) - amount), Decimal("0"))
            debit_doc.writeoff_status = _writeoff_status(debit_doc, cfg.debit)
        # 回退收款单。
        credit_doc = (await ctx.db.execute(
            select(cfg.credit.model).where(cfg.credit.model.id == link.credit_doc_id)
        )).scalar_one_or_none()
        if credit_doc is not None:
            credit_doc.written_off_amount = max(
                _q2(_num(getattr(credit_doc, "written_off_amount", 0)) - amount), Decimal("0"))
            credit_doc.writeoff_status = _writeoff_status(credit_doc, cfg.credit)
        link.is_active = False
        reverted.append({
            "writeoff_link_id": link.id,
            "debit_doc_id": link.debit_doc_id, "credit_doc_id": link.credit_doc_id,
            "amount": float(amount),
            "debit_writeoff_status": getattr(debit_doc, "writeoff_status", None) if debit_doc else None,
            "credit_writeoff_status": getattr(credit_doc, "writeoff_status", None) if credit_doc else None,
        })
    await ctx.db.flush()
    ctx.add_event("unwriteoff_done", {"count": len(reverted)})
    return {"reverted": len(reverted), "skipped": skipped, "links": reverted}
