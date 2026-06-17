"""段4a 报关域注册扩展（PRD 06-报关）。

全靠引擎注册扩展点实现，引擎核心零 diff：
  - @register_transition_validator：合规五件套申报硬拦（DRAFT/REJECTED → SUBMITTED）、
    香港退香港公司一致性硬校验（退运原进口单限本公司）。
  - @register_transition_effect：派 PA 补录待办、报关单号回写出入库、报关费分摊回写到岸成本 + 金蝶增量 enqueue。
  - @register_command（在 services.customs_commands）：顺丰物流 API 框架壳（OFF）、资料清单导出壳。

这些 effect/validator 在 workflow_extensions._EXTENSION_MODULES 中按模块名加载（本文件名已登记）。
副作用须幂等（在 execute_transition 同事务内运行）。
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.kingdee_outbox import enqueue_outbox
from services.notifications import create_notification
from services.workflow_extensions import (
    register_transition_effect,
    register_transition_validator,
)

# 退运 180 天大限（PRD 06-2）+ 临期预警阈值。
RE_EXPORT_WINDOW_DAYS = 180
RE_EXPORT_WARN_DAYS = 30


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


async def _lines(db: AsyncSession, declaration_id: int):
    rows = (await db.execute(
        select(m.CustomsDeclarationLine)
        .where(m.CustomsDeclarationLine.customs_declaration_id == declaration_id)
        .order_by(m.CustomsDeclarationLine.line_number)
    )).scalars().all()
    return rows


# ============================================================
# 合规五件套申报硬拦（PRD 06-1 申报闸，调研证据 V-1/V-9，SOP §四-3）
# ============================================================

# 合规五件套（按方向）。退运方向 ECCN 放宽（PRD §06-1 字段表 * 注 + 任务 3）。
_COMPLIANCE_FIELDS = [
    ("hs_code_cn", "HS中国码"),
    ("origin_country", "原产国"),
    ("cn_name", "中文品名"),
    ("eccn", "ECCN"),
]


@register_transition_validator(
    "customs.validate_compliance_pack",
    doc_type="CUSTOMS_DECLARATION",
    to_state="SUBMITTED",
)
async def validate_compliance_pack(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount
) -> list[str]:
    """申报闸：明细非空 + 逐行合规五件套必填（退运放宽 ECCN）。

    任一行缺任一项 → 返回 rule_failures 明确指出哪行缺哪项（阻断推进）。
    退运另校 return_deadline 必填（180 天倒排基准，PRD 06-2）。
    """
    failures: list[str] = []
    lines = await _lines(db, doc.id)
    if not lines:
        failures.append("报关明细为空：申报前至少需一条商品明细行")
        return failures

    is_re_export = getattr(doc, "direction", "") == "RE_EXPORT"
    for line in lines:
        line_label = f"第{line.line_number}行"
        for field, cn in _COMPLIANCE_FIELDS:
            # 退运方向 ECCN 放宽（不强制），其余四件套始终硬拦。
            if field == "eccn" and is_re_export:
                continue
            value = getattr(line, field, None)
            if value is None or str(value).strip() == "":
                failures.append(f"{line_label} 缺合规项「{cn}」（{field}）：申报前须补齐")
        amount = getattr(line, "declared_amount", None)
        if amount is None or _num(amount) == 0:
            failures.append(f"{line_label} 缺申报金额（declared_amount）：申报前须补齐")

    if is_re_export and getattr(doc, "return_deadline", None) is None:
        failures.append("退运方向须填退运截止日期（return_deadline，180 天倒排基准）")
    return failures


@register_transition_validator(
    "customs.validate_re_export_company",
    doc_type="CUSTOMS_DECLARATION",
    to_state="SUBMITTED",
)
async def validate_re_export_company(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount
) -> list[str]:
    """香港卖退香港硬校验（PRD 06-2，调研证据 V-4）：退运单原进口报关单限本公司、已放行进口单。

    跨公司退运拒绝（双保险：下拉 _company_filter 已天然限本公司，这里再硬校）。
    """
    if getattr(doc, "direction", "") != "RE_EXPORT":
        return []
    failures: list[str] = []
    origin_id = getattr(doc, "origin_declaration_id", None)
    if not origin_id:
        failures.append("退运方向须挂原进口报关单（origin_declaration_id 必填）")
        return failures
    origin = (await db.execute(
        select(m.CustomsDeclaration).where(m.CustomsDeclaration.id == origin_id)
    )).scalar_one_or_none()
    if not origin:
        failures.append("原进口报关单不存在")
        return failures
    if origin.company_id != doc.company_id:
        failures.append("跨公司退运被拒：原进口报关单须为本公司（香港卖的退香港，红线3）")
    if getattr(origin, "direction", "") != "IMPORT":
        failures.append("退运挂接的原单方向须为进口（IMPORT）")
    if getattr(origin, "status", "") not in ("RELEASED", "CLOSED"):
        failures.append("退运挂接的原进口报关单须为已放行/已关闭")
    return failures


# ============================================================
# 派 PA 补录待办（PRD 06-1 申报阻断时自动按产品线路由派单）
# ============================================================

@register_transition_effect("customs.dispatch_pa_compliance_todo", auto=False)
async def dispatch_pa_compliance_todo(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """申报推进 effect：对仍缺合规五件套的行，按型号→供应商→responsible_pa 派一条补录待办。

    幂等：dedup_key 含 declaration_id + line_id；无对应 PA 则广播 PRODUCT_ASSISTANT 角色。
    （此 effect 在 validator 全过后才会触发；通常已无缺口，留作申报留痕 + 兜底补录入口。）
    """
    logs: list[str] = []
    is_re_export = getattr(doc, "direction", "") == "RE_EXPORT"
    lines = await _lines(db, doc.id)
    for line in lines:
        missing = []
        for field, cn in _COMPLIANCE_FIELDS:
            if field == "eccn" and is_re_export:
                continue
            value = getattr(line, field, None)
            if value is None or str(value).strip() == "":
                missing.append(cn)
        if not missing:
            continue
        pa_id = None
        if line.material_id:
            material = (await db.execute(
                select(m.Material).where(m.Material.id == line.material_id)
            )).scalar_one_or_none()
            supplier_id = getattr(material, "supplier_id", None) if material else None
            if supplier_id:
                supplier = (await db.execute(
                    select(m.Supplier).where(m.Supplier.id == supplier_id)
                )).scalar_one_or_none()
                pa_id = getattr(supplier, "responsible_pa_id", None) if supplier else None
        await create_notification(
            db,
            company_id=doc.company_id,
            category="CUSTOMS_COMPLIANCE",
            title=f"报关合规补录：{doc.declaration_number} 第{line.line_number}行",
            body=f"型号#{line.material_id} 缺合规项：{', '.join(missing)}，请补主数据五件套。",
            severity="WARN",
            recipient_id=pa_id,
            recipient_role="" if pa_id else "PRODUCT_ASSISTANT",
            source_doc_type=doc_type,
            source_doc_id=doc.id,
            dedup_key=f"customs_compliance:{doc.id}:{line.id}",
        )
        logs.append(f"派 PA 补录待办 line#{line.id} 缺={missing} pa={pa_id or 'PA角色广播'}")
    return logs or ["合规五件套齐备，无补录待办"]


# ============================================================
# 报关单号回写出入库 + 进口放行日回填（PRD 06-1 RELEASED，调研证据 W-5）
# ============================================================

@register_transition_effect(
    "customs.writeback_declaration_number",
    doc_type="CUSTOMS_DECLARATION",
    to_state="RELEASED",
)
async def writeback_declaration_number(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """放行 effect：报关单号回写来源出库单装箱单（换发票号）；进口放行回填放行日（供退运 180 倒排）。

    幂等：再次进入 RELEASED 不重复写（值已等于报关单号则跳过）。
    """
    logs: list[str] = []
    today = date.today()
    direction = getattr(doc, "direction", "")

    if direction == "IMPORT" and getattr(doc, "import_release_date", None) is None:
        doc.import_release_date = today
        logs.append(f"进口放行日回填 {today}")

    # 出口：报关单号回写关联出库单行 invoice_number（把发票号 I… 换成报关单号 CD…）。
    if direction == "EXPORT" and getattr(doc, "shipment_id", None):
        ship_lines = (await db.execute(
            select(m.ShipmentLine).where(m.ShipmentLine.shipment_id == doc.shipment_id)
        )).scalars().all()
        changed = 0
        for sl in ship_lines:
            if sl.invoice_number != doc.declaration_number:
                sl.invoice_number = doc.declaration_number
                changed += 1
        if changed:
            logs.append(f"出库单#{doc.shipment_id} {changed} 行回写报关单号={doc.declaration_number}")

    return logs or ["放行回写无变更（幂等跳过）"]


# ============================================================
# 报关费分摊回写到岸成本 + 金蝶增量 enqueue（PRD 06-3，仅进口，auto=False）
# ============================================================

@register_transition_effect("customs.allocate_fee_to_landed_cost", auto=False)
async def allocate_fee_to_landed_cost(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """登记费用 effect（仅进口已放行单）：按占比把报关费分摊回写关联入库批次到岸成本。

    分摊口径（PRD 06-3）：allocation_basis=AMOUNT 按申报金额占比 / QUANTITY 按数量占比。
    回写目标：关联入库单各行 goods_receipt_line.customs_fee（与 03 入库 E4 同源列）。
    段5 边界：金蝶只 enqueue 增量到 kingdee_outbox（不写真实 HTTP）。
    """
    if getattr(doc, "direction", "") != "IMPORT":
        return ["非进口方向，跳过报关费分摊（出口/退运无登记费用动作）"]

    fee_lines = (await db.execute(
        select(m.CustomsFeeLine)
        .where(m.CustomsFeeLine.customs_declaration_id == doc.id)
        .order_by(m.CustomsFeeLine.line_number)
    )).scalars().all()
    if not fee_lines:
        return ["无报关费行，跳过分摊"]

    # 取关联入库单的入库行（分摊承载单元）。头部主关联入库单为承载（多张合并见 source_line_ref，首期按头）。
    gr_id = getattr(doc, "goods_receipt_id", None)
    gr_lines = []
    if gr_id:
        gr_lines = (await db.execute(
            select(m.GoodsReceiptLine).where(m.GoodsReceiptLine.goods_receipt_id == gr_id)
        )).scalars().all()
    if not gr_lines:
        return ["无关联入库行，报关费无法分摊回写（请先关联入库单）"]

    logs: list[str] = []
    for fee in fee_lines:
        total_fee = _num(fee.amount)
        if total_fee == 0:
            continue
        basis = (fee.allocation_basis or "AMOUNT").upper()
        # 权重：按申报金额或数量占比（落在入库行上）。金额优先取行 actual_quantity*成本无现成 → 用数量兜底。
        weights = []
        for grl in gr_lines:
            if basis == "QUANTITY":
                weights.append(_num(grl.actual_quantity))
            else:
                # 金额占比：入库行无申报金额列，用 actual_quantity 作权重兜底（PRD 默认按金额，缺价时退数量）。
                weights.append(_num(grl.actual_quantity))
        total_weight = sum(weights, Decimal("0"))
        if total_weight == 0:
            logs.append(f"费用行#{fee.line_number} 权重合计为0，跳过分摊")
            continue
        detail = {}
        allocated_sum = Decimal("0")
        for idx, grl in enumerate(gr_lines):
            share = (total_fee * weights[idx] / total_weight).quantize(Decimal("0.01"))
            grl.customs_fee = _num(grl.customs_fee) + share
            allocated_sum += share
            detail[str(grl.id)] = float(share)
        # 尾差归到末行（分摊合计=费用合计，调研证据 V-13）。
        diff = total_fee - allocated_sum
        if diff != 0 and gr_lines:
            last = gr_lines[-1]
            last.customs_fee = _num(last.customs_fee) + diff
            detail[str(last.id)] = float(_num(detail.get(str(last.id), 0)) + diff)
        fee.allocation_detail = detail
        logs.append(f"费用行#{fee.line_number} {basis} 分摊 {total_fee} → 入库单#{gr_id} {len(gr_lines)}行")

    # 金蝶增量 enqueue（随入库单做账，段5 壳：只写 outbox 行，不真实 HTTP）。
    if gr_id:
        gr = (await db.execute(
            select(m.GoodsReceipt).where(m.GoodsReceipt.id == gr_id)
        )).scalar_one_or_none()
        if gr is not None:
            row = await enqueue_outbox(
                db, doc=gr, doc_type="GOODS_RECEIPT", trigger_state="CUSTOMS_FEE_INCREMENT",
                user=user, command_log_id=command_log_id,
            )
            logs.append(f"金蝶增量 enqueue outbox#{row.id} {row.status}（报关费随入库单，dry-run）")

    return logs or ["报关费分摊无变更"]
