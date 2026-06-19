"""
枚举值中文字典（finance-gl 主数据台账显示用）

主数据台账（MasterDataPage 等）此前直接显内部枚举码（ASSET/DEBIT/ACTIVE/CASH/...）。
本模块集中管理「枚举码 → 中文」映射，由 schema 接口随每个字段下发 value_labels，
前端 renderCell / StatusPill 据此显中文。只改显示，不改存储码、不碰业务逻辑。

三层：
  ENUM_VALUE_LABELS: 通用枚举（按列名）—— 大部分枚举列直接命中
  TABLE_OVERRIDES:   表级覆盖（同一列名在不同表需要不同中文，如 method_type/direction）
  STATUS_LABELS:     status 列统一字典（跨业务域聚合所有状态码）

查找顺序（value_labels_for）：
  1. 该表该列有表级覆盖 -> 返回覆盖
  2. 列名为 status -> 返回 STATUS_LABELS
  3. 通用枚举命中列名 -> 返回通用
  4. 否则 None（非枚举列，schema 不下发 value_labels）
"""

# ============================================================
# 通用枚举：列名 -> {码: 中文}
# ============================================================

ENUM_VALUE_LABELS = {
    "account_type": {
        "ASSET": "资产", "LIABILITY": "负债", "EQUITY": "权益",
        "REVENUE": "收入", "EXPENSE": "费用", "COGS": "成本",
    },
    "balance_direction": {"DEBIT": "借方", "CREDIT": "贷方"},
    "dr_cr": {"DR": "借", "CR": "贷"},
    "voucher_type": {
        "GENERAL": "普通凭证", "RECEIPT": "收款凭证",
        "PAYMENT": "付款凭证", "TRANSFER": "转账凭证",
    },
    "reversal_type": {"NORMAL": "普通(蓝字)", "RED": "红字反向"},
    "source_type": {
        "CUSTOMER": "客户", "SUPPLIER": "供应商", "EMPLOYEE": "员工",
        "DEPT": "部门", "PROJECT": "项目",
    },
    "direction": {"IN": "流入", "OUT": "流出"},
    "cash_direction": {"IN": "现金流入", "OUT": "现金流出", "BOTH": "不限方向"},
    "method_type": {"CASH": "现金", "TRANSFER": "转账", "NOTE": "票据", "WIRE": "电汇"},
    "account_source": {
        "FIXED": "固定科目", "CUSTOMER": "客户对应科目",
        "SUPPLIER": "供应商对应科目", "MATERIAL_DEFAULT": "物料默认科目",
    },
    "tax_handling": {
        "NONE": "不涉税", "INCLUSIVE": "价税合计",
        "EXCLUSIVE": "价外不含税", "TAX_ONLY": "仅税额",
    },
    "date_source": {"CREATE": "建单日", "BIZ": "业务日"},
    "standard": {"CAS": "企业会计准则(内地)", "HKFRS": "香港财务报告准则"},
    "measurement_basis": {"HISTORICAL_COST": "历史成本", "FAIR_VALUE": "公允价值"},
    "depreciation_method": {"STRAIGHT_LINE": "直线法", "DOUBLE_DECLINING": "双倍余额递减法"},
    "inventory_valuation": {"WEIGHTED_AVG": "加权平均", "FIFO": "先进先出"},
    "cost_method": {"WEIGHTED_AVG": "加权平均", "FIFO": "先进先出"},
    "bad_debt_method": {"ALLOWANCE": "备抵法", "DIRECT": "直接转销法"},
    "scheme_type": {"TRANSFER": "自动转账", "AMORTIZATION": "摊销", "ACCRUAL": "预提"},
    "statement": {"BS": "资产负债表", "IS": "利润表"},
    "note_type": {"COMMERCIAL": "商业承兑汇票", "BANK": "银行承兑汇票"},
    "payment_type": {"ADVANCE": "预付", "POST_DELIVERY": "货后付款"},
    "track_status": {
        "PENDING_ACCEPT": "待接单", "ACCEPTED": "已接单待货期", "ETA_GIVEN": "已给货期",
        "SHIPPED": "已发货", "PARTIAL": "部分到货", "RECEIVED": "已到货",
    },
    "transaction_type": {"IN": "入库", "OUT": "出库", "ADJUST": "调整"},
}


# ============================================================
# status 列统一字典（跨业务域聚合）
# ============================================================

STATUS_LABELS = {
    "DRAFT": "草稿/录入",
    "AUDITED": "已审核",
    "REVIEWED": "出纳已复核",
    "POSTED": "已过账",
    "ACTIVE": "启用",
    "INACTIVE": "停用",
    "OPEN": "未结账(开启)",
    "LOCKED": "已锁定",
    "CLOSED": "已结账",
    "PENDING": "待处理/待付款",
    "PARTIAL": "部分付款",
    "PARTIAL_PAID": "部分付款",
    "PAID": "已付清",
    "OVERDUE": "逾期",
    "SETTLED": "已结算",
    "BAD_DEBT": "坏账",
    "COLLECTING": "收款中",
    "INVOICED": "已开票",
    "CONTRACT_REGISTERED": "已登记合同",
    "CREDIT_MANAGED": "信用已管理",
    "VOUCHER_PROCESSED": "凭证已处理",
    "NOTES_RECV": "应收票据",
    "CONFIRMED": "已确认到账",
    "CANCELLED": "已取消",
    "FINANCE_REVIEW": "财务审核中",
    "PENDING_REVIEW": "待财务审核",
    "PENDING_FINANCE": "待财务执行",
    "AP_CREATED": "已生成应付",
    "AR_CREATED": "已生成应收",
    "MATCHING": "勾稽中",
    "HELD": "持有中",
    "UNALLOCATED": "未核销",
    "ALLOCATED": "已核销",
    "START": "开始",
    "VOID": "作废",
    "REVERSED": "已红冲",
}


# ============================================================
# 表级覆盖：(表, 列) -> {码: 中文}
#   含两类：① 同名列在该表含义不同（method_type/direction/cash_direction/...）
#          ② 该表 status 列有更贴合该单据生命周期的细化说法（覆盖 STATUS_LABELS）
# ============================================================

TABLE_OVERRIDES = {
    ("settlement_method", "method_type"): {
        "CASH": "现金", "TRANSFER": "银行转账", "NOTE": "商业票据", "WIRE": "电汇",
    },
    ("auxiliary_dimension", "source_type"): {
        "CUSTOMER": "客户", "SUPPLIER": "供应商", "EMPLOYEE": "员工",
        "DEPT": "部门", "PROJECT": "项目",
    },
    ("cashflow_item", "direction"): {"IN": "流入", "OUT": "流出"},
    ("cashflow_assign_rule", "cash_direction"): {
        "IN": "现金流入", "OUT": "现金流出", "BOTH": "不限方向",
    },
    ("inventory_transaction", "transaction_type"): {
        "IN": "入库", "OUT": "出库", "ADJUST": "调整",
    },
    ("elimination_entry", "statement"): {"BS": "资产负债表", "IS": "利润表"},
    ("fiscal_year", "status"): {"OPEN": "未结账", "LOCKED": "已锁定", "CLOSED": "已结账"},
    ("accounting_period", "status"): {"OPEN": "未结账", "LOCKED": "已锁定", "CLOSED": "已结账"},
    ("voucher", "status"): {
        "DRAFT": "录入", "AUDITED": "已审核", "REVIEWED": "出纳已复核", "POSTED": "已过账",
    },
    ("accounts_receivable", "status"): {
        "PENDING": "待收款", "COLLECTING": "收款中", "PARTIAL": "部分收款",
        "PAID": "已收清", "SETTLED": "已核销", "OVERDUE": "逾期",
        "BAD_DEBT": "坏账", "CLOSED": "已结账",
    },
    ("accounts_payable", "status"): {
        "PENDING": "待付款", "PARTIAL": "部分付款", "PAID": "已付清",
        "OVERDUE": "逾期", "SETTLED": "已结算", "CLOSED": "已结账",
    },
    ("advance_receipt", "status"): {
        "DRAFT": "录入预收单", "CONFIRMED": "已确认到账", "CANCELLED": "已取消",
    },
    ("advance_payment", "status"): {
        "DRAFT": "录入预付申请", "FINANCE_REVIEW": "财务审核中",
        "PAID": "已付款", "CANCELLED": "已取消",
    },
    ("payment_request", "status"): {
        "DRAFT": "PA发起", "PENDING_FINANCE": "待财务执行", "PAID": "已付款待确认",
        "CONFIRMED": "已确认到账", "CANCELLED": "已取消",
    },
    ("purchase_invoice", "status"): {
        "DRAFT": "登记发票", "PENDING_REVIEW": "待财务审核",
        "AP_CREATED": "已生成应付", "CANCELLED": "已取消",
    },
    ("sales_invoice", "status"): {
        "DRAFT": "登记发票", "MATCHING": "勾稽中",
        "AR_CREATED": "已生成应收", "CANCELLED": "已取消",
    },
    ("notes_receivable", "status"): {
        "HELD": "持有中", "ENDORSED": "已背书", "DISCOUNTED": "已贴现",
        "COLLECTED": "已托收", "DISHONORED": "已退票",
    },
    ("bank_receipt", "status"): {
        "UNALLOCATED": "未核销", "PARTIAL": "部分核销", "ALLOCATED": "已核销",
    },
    ("account", "status"): {"ACTIVE": "启用", "INACTIVE": "停用"},
}


def value_labels_for(table_name: str, column_name: str):
    """取某表某列的「枚举码 -> 中文」字典；非枚举列返回 None。

    查找顺序：表级覆盖 -> status 统一字典 -> 通用枚举 -> None
    """
    override = TABLE_OVERRIDES.get((table_name, column_name))
    if override is not None:
        return override
    if column_name == "status":
        return STATUS_LABELS
    return ENUM_VALUE_LABELS.get(column_name)
