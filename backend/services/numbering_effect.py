"""建单取号 effect（段0b·1 接线层）。

引擎建单时只给 `*_number` 一个 UUID 兜底前缀（_auto_fill_required_fields）。
本模块在「建单进初始态」这一刻把那个兜底值换成**业务连号**（PR2606-001…），
取号复用 numbering.allocate_next_number（行锁 + 月度重置 + format）。

接线方式（不动引擎核心）：
  - 处理器经 @register_transition_effect 注册到各 doc_type 的初始态 START；
  - 该 effect 名字被填进各流程 START 状态的 `effects` 数组（seed/定义层），
    使 execute_transition._create_blank 在建单后同事务内触发它。

幂等守卫：仅当目标列当前为空，或仍是引擎默认 `{PREFIX}-{YYMMDD}-{6位HEX}`
兜底值时才覆盖；已是业务号则跳过 —— 防退回初态/再触发时重号。
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.numbering import allocate_next_number
from services.workflow_extensions import register_transition_effect


# doc_type → 该单据的「业务单号」列名。显式映射而非「找唯一 *_number 列」：
# 多数主单据有不止一个 *_number 列（如 goods_receipt 另有 source_issue_number、
# shipment_request 另有 tracking_number），盲扫会写错列。
NUMBER_COLUMN_BY_DOC_TYPE: dict[str, str] = {
    # 段3b 决策①：销售订单内部订单号（合同号）月度连号 SO-YYMM-001。
    "SALES_ORDER": "order_number",
    "PURCHASE_ORDER": "order_number",
    "GOODS_RECEIPT": "receipt_number",
    "SHIPMENT": "shipment_number",
    "SALES_INVOICE": "invoice_number",
    "SALES_RETURN": "return_number",
    "STOCK_TRANSFER": "transfer_number",
    "STOCK_ADJUSTMENT": "adjustment_number",
    "INVENTORY_COUNT": "count_number",
    # 段2a 采购主链：内部询价 / 采购通知 / 对原厂询价业务连号（IQ/PN/SQ，月度重置）。
    "SALES_INQUIRY": "inquiry_number",
    "PURCHASE_NOTICE": "notice_number",
    "SUPPLIER_INQUIRY": "inquiry_number",
    # 段2c 采购收尾：进项发票 PI / 付款申请 PAY 业务连号（月度重置补零3）。
    "PURCHASE_INVOICE": "invoice_number",
    "PAYMENT_REQUEST": "payment_number",
    # 段2d-1 备货申请：备货单号 SU-YYMM-001（月度连号，04b-1）。
    "STOCK_UP_REQUEST": "request_number",
    # 段2d-2 RMA：RMA-YYMM-NNN（月度连号，04b-5）。样品 SDN 走专属 effect
    # sample.assign_sdn_number（号中含供应商线字母 C/L，§00-7），不在此通用映射。
    "RMA": "rma_number",
    # 段3a CRM 前段：线索 LD / 商机 OPP 月度连号（PRD 05 页面3/4）。商机派生时由
    # crm.create_opportunity_from_lead 直接取号（同 util），手建商机走此 START 取号。
    "LEAD": "lead_number",
    "OPPORTUNITY": "opportunity_number",
    # 段3c 客户/销售收尾：认证 QUAL / 售后工单 ST / Forecast FC / 特批发货 SS（月度连号，PRD 05）。
    "CUSTOMER_QUALIFICATION": "qualification_number",
    "SERVICE_TICKET": "ticket_number",
    "CUSTOMER_FORECAST": "forecast_number",
    "SPECIAL_SHIPMENT": "shipment_number",
    # 段4a 报关：报关单 CD-YYMM-NNN（月度连号）。建单进 DRAFT 取号。
    # 注：CUSTOMS_LICENSE 进出口证为 __queryable__ 主数据台账（无 START 流程），
    #     其 LIC-YYMM-NNN 取号在主数据写路径调 allocate_next_number，不挂此 START effect。
    "CUSTOMS_DECLARATION": "declaration_number",
    # 总账·第一波（finance-gl）：凭证号 PZ-YYMM-NNN（记账凭证连号）。建单进 START 取号。
    # 红字单走 finance.red_reversal 命令直接建草稿（临时号 RED-<原号>），不经此 START effect。
    "VOUCHER": "voucher_number",
    # 总账·第八波（finance-gl）应收款管理：应收单 AR-YYMM-NNN / 收款单 SK-YYMM-NNN（月度连号）。
    # 建单进 START 取号（seed_receivable 已建 NumberingRule + 在 START.effects 挂本 effect）。
    "ACCOUNTS_RECEIVABLE": "bill_number",
    "AR_RECEIPT": "receipt_number",
    # 应付款管理（finance-gl 应付波）：应付单 AP-YYMM-NNN / 付款单 FK-YYMM-NNN（月度连号）。
    # 建单进 START 取号（seed_payable 已建 NumberingRule + 在 START.effects 挂本 effect）。
    "ACCOUNTS_PAYABLE": "bill_number",
    "AP_PAYMENT": "payment_number",
}

# 引擎默认兜底号形态：{PREFIX}-{YYMMDD}-{6位HEX}（_auto_fill_required_fields）。
# PREFIX = doc_type.replace("_","")[:4].upper() → [A-Z0-9]{1,4}。
_ENGINE_DEFAULT_RE = re.compile(r"^[A-Z0-9]{1,4}-\d{6}-[0-9A-F]{6}$")


def _is_overwritable(value) -> bool:
    """仅空值或引擎默认兜底号可被业务号覆盖（已是业务号则保号、不重发）。"""
    if value is None or value == "":
        return True
    return bool(_ENGINE_DEFAULT_RE.match(str(value)))


async def assign_business_number(
    db: AsyncSession,
    doc_type: str,
    doc,
    to_state: str | None,
    user: m.UserAccount,
    command_log_id: int | None,
) -> list[str]:
    column = NUMBER_COLUMN_BY_DOC_TYPE.get(doc_type)
    if not column or not hasattr(doc, column):
        return []  # 该流程主模型无业务号列（如 INVENTORY_COUNT 落在 Inventory 上）→ no-op
    if not _is_overwritable(getattr(doc, column)):
        return []  # 幂等守卫：已是业务号，跳过

    company_id = getattr(doc, "company_id", None)
    if company_id is None:
        return []

    allocated = await allocate_next_number(
        db, company_id, doc_type, updated_by_id=user.id,
    )
    if not allocated:
        return []  # 无规则 → 留引擎默认 UUID 号，不报错

    setattr(doc, column, allocated["number"])
    await db.flush()
    return [f"分配业务单号 {doc_type}.{column}={allocated['number']}"]


# 给有编号规则的 doc_type 逐一注册到其初始态 START（所有 phase1/seed 流程初始态码均为 START）。
for _doc_type in NUMBER_COLUMN_BY_DOC_TYPE:
    register_transition_effect(
        "numbering.assign_business_number",
        doc_type=_doc_type,
        to_state="START",
    )(assign_business_number)
