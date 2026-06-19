"""存货核算（finance-gl 成本波）：存货成本交易 → 凭证（账务处理·凭证生成）。

★存货成本引擎已在 WMS（services.wms）:移动平均 InventoryValuation + 出入库成本交易 InventoryTransaction
（doc_type INVENTORY_COSTING，transaction_type=IN 入库 / OUT 出库，total_cost=移动平均成本×数量）。
本模块只补「业财桥」——把已算好成本的存货交易批量生成总账凭证（核心三件零 diff，纯扩展）：

  · 入库 IN：借 库存商品 / 贷 在途物资（暂估）——与应付单「借在途/贷应付」对接,净效果借库存/贷应付。
  · 出库 OUT：借 主营业务成本 / 贷 库存商品（结转销售成本）。
  科目码取本公司 AccountMappingRule（source_doc_type=INVENTORY_COSTING，trigger_action=IN/OUT），按 region 落本家科目。

命令 finance.generate_inventory_vouchers（DETAIL 一笔一凭证 / SUMMARY 按类型汇总，默认 SUMMARY 少凭证）:
  扫本公司未生凭证（voucher_id IS NULL）的存货成本交易 → 生成凭证 → 回填 voucher_id（幂等：已回填跳过）。

本模块由 command_registry.load_commands 双注册。副作用在命令外壳事务内,失败回滚。
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.ar_receivable import _account, _build_and_post_voucher, _rule_codes
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.finance_mapping import _num, _q2
from services.tools import _company_filter

SRC = "INVENTORY_COSTING"


def _entry(line_number, account_id, is_debit, amount, memo):
    """存货成本凭证分录（本位币记账，无往来辅助核算）。"""
    return {
        "line_number": line_number,
        "account_id": account_id,
        "description": (memo or "")[:200],
        "debit": amount if is_debit else Decimal("0"),
        "credit": Decimal("0") if is_debit else amount,
        "currency": "CNY",
        "exchange_rate": Decimal("1"),
        "base_debit": amount if is_debit else Decimal("0"),
        "base_credit": Decimal("0") if is_debit else amount,
        "aux_party_type": None,
        "aux_party_id": None,
    }


async def _build_costing_voucher(
    db: AsyncSession, user, *, company_id: int, txn_type: str, amount: Decimal,
    source_doc_id: int, voucher_date: date, label: str, auto_post: bool,
) -> int | None:
    """按 AccountMappingRule（INVENTORY_COSTING + trigger=txn_type）建一张存货成本凭证（借/贷各取全额）。"""
    rules = await _rule_codes(db, company_id, SRC, txn_type, voucher_date)
    if not rules:
        raise ValueError(f"公司#{company_id} 缺存货核算映射规则（INVENTORY_COSTING/{txn_type}），请先跑 seed_cost")
    entries: list[dict] = []
    ln = 0
    for rule in rules:
        account = await _account(db, company_id, rule.account_code)
        if account is None:
            raise ValueError(f"存货核算映射 line_seq={rule.line_seq} 科目码 {rule.account_code!r} 在公司#{company_id} 不存在")
        ln += 1
        is_debit = (rule.dr_cr or "").upper() == "DR"
        memo = (rule.memo_template or "").strip() or label
        entries.append(_entry(rule.line_seq or ln, account.id, is_debit, _q2(amount), memo))
    if not entries:
        return None
    return await _build_and_post_voucher(
        db, user, company_id=company_id, voucher_date=voucher_date,
        description=label[:200], word_code="转", entries=entries,
        source_doc_type=SRC, source_doc_id=source_doc_id,
        auto_post=auto_post, auditor=None, poster=None,
    )


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


@register_command(
    "finance.generate_inventory_vouchers",
    module="FINANCE",
    title="存货核算·凭证生成",
    description=(
        "把已算好成本的存货交易（InventoryTransaction，移动平均）批量生成总账凭证。"
        "入库 借库存/贷在途暂估；出库 借主营成本/贷库存。"
        "mode=SUMMARY 按交易类型汇总（默认，少凭证）/ DETAIL 一笔一凭证。已生凭证幂等跳过。"
    ),
    affected_tables=("voucher", "voucher_entry", "inventory_transaction"),
    supports_retry=True,
)
async def generate_inventory_vouchers(ctx: CommandContext, payload: dict) -> dict:
    """存货核算凭证生成。

    payload:
      company_id: int   —— 公司（必填）
      mode: 'SUMMARY'(默认) | 'DETAIL'
      auto_post: bool   —— 是否自动审核过账（默认 False，仅建草稿）
      period_id: int    —— 可选，限定会计期间
    """
    company_id = payload.get("company_id")
    if not company_id:
        raise CommandError("company_id 不能为空")
    _assert_company_access(ctx.user, company_id)
    db = ctx.db
    mode = (payload.get("mode") or "SUMMARY").upper()
    auto_post = bool(payload.get("auto_post", False))

    stmt = select(m.InventoryTransaction).where(
        m.InventoryTransaction.company_id == company_id,
        m.InventoryTransaction.voucher_id.is_(None),
    )
    if payload.get("period_id"):
        stmt = stmt.where(m.InventoryTransaction.period_id == payload["period_id"])
    txns = (await db.execute(stmt.order_by(m.InventoryTransaction.id))).scalars().all()
    if not txns:
        return {"company_id": company_id, "mode": mode, "created": [], "summary": {"vouchers": 0, "txns": 0}}

    created: list[dict] = []
    failed: list[dict] = []
    txn_done = 0

    async def _emit(txn_type: str, amount: Decimal, src_id: int, label: str, members: list):
        nonlocal txn_done
        if _q2(amount) <= 0:
            return
        try:
            vid = await _build_costing_voucher(
                db, ctx.user, company_id=company_id, txn_type=txn_type, amount=amount,
                source_doc_id=src_id, voucher_date=date.today(), label=label, auto_post=auto_post)
            if vid:
                for t in members:
                    t.voucher_id = vid
                await db.flush()
                created.append({"txn_type": txn_type, "voucher_id": vid, "amount": float(_q2(amount)), "txns": len(members)})
                txn_done += len(members)
        except Exception as exc:  # noqa: BLE001
            failed.append({"txn_type": txn_type, "error": str(exc)})

    if mode == "DETAIL":
        for t in txns:
            await _emit((t.transaction_type or "").upper(), _num(t.total_cost), t.id,
                        f"存货核算 {t.transaction_type} 物料#{t.material_id}", [t])
    else:  # SUMMARY：按交易类型汇总
        groups: dict[str, list] = {}
        for t in txns:
            groups.setdefault((t.transaction_type or "").upper(), []).append(t)
        for txn_type, members in groups.items():
            amount = sum((_num(t.total_cost) for t in members), Decimal("0"))
            label = f"存货核算汇总凭证 {txn_type}（{len(members)} 笔）"
            await _emit(txn_type, amount, members[0].id, label, members)

    ctx.add_event("finance_generate_inventory_vouchers", {
        "company_id": company_id, "mode": mode, "vouchers": len(created), "txns": txn_done, "failed": len(failed),
    })
    return {
        "company_id": company_id, "mode": mode, "auto_post": auto_post,
        "created": created, "failed": failed,
        "summary": {"vouchers": len(created), "txns": txn_done, "failed": len(failed)},
    }
