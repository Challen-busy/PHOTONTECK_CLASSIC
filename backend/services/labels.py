"""
字段中文标签映射

分两层：
  GLOBAL_LABELS: 全局默认（大部分字段直接用）
  TABLE_LABELS:  表级覆盖（少数情况字段含义在不同表需要特殊标签）

前端取标签: TABLE_LABELS[table][field] or GLOBAL_LABELS[field] or field
"""

# ============================================================
# 全局默认标签
# ============================================================

GLOBAL_LABELS = {
    # 通用
    "id": "ID",
    "created_at": "创建时间",
    "updated_at": "更新时间",
    "created_by_id": "创建人",
    "updated_by_id": "最后修改人",
    "company_id": "所属公司",
    "is_active": "启用",
    "status": "状态",
    "notes": "备注",
    "description": "描述",
    "comment": "意见",

    # 名称/编码
    "name": "名称",
    "short_name": "简称",
    "code": "代码",
    "username": "用户名",
    "full_name": "姓名",

    # 数字通用
    "quantity": "数量",
    "amount": "金额",
    "total_amount": "总金额",
    "unit_price": "单价",
    "total_price": "小计金额",
    "unit_cost": "单位成本",
    "total_cost": "总成本",
    "paid_amount": "已付/已收金额",
    "shipped_quantity": "已发数量",
    "received_quantity": "已收数量",
    "picked_quantity": "已拣数量",
    "expected_quantity": "预期数量",
    "actual_quantity": "实际数量",
    "reserved_quantity": "已预留数量",
    "available_quantity": "可用数量",
    "safety_stock": "安全库存",
    "reorder_point": "补货点",
    "max_stock": "最高库存",
    "lead_time_days": "采购提前期",
    "system_quantity": "系统数量",
    "counted_quantity": "盘点数量",
    "difference_quantity": "差异数量",
    "quantity_estimate": "预估数量",
    "line_number": "行号",

    # 币种/汇率
    "currency": "币种",
    "exchange_rate": "汇率",
    "from_currency": "原币种",
    "to_currency": "目标币种",
    "rate": "汇率值",
    "default_currency": "默认币种",

    # 日期
    "start_date": "开始日期",
    "end_date": "结束日期",
    "effective_date": "生效日期",
    "received_date": "收货日期",
    "shipped_date": "发货日期",
    "paid_date": "收/付款日期",
    "due_date": "到期日",
    "date": "日期",
    "expected_delivery_date": "预计交期",
    "actual_delivery_date": "实际交期",
    "requested_delivery_date": "要求交期",
    "expected_mass_production_date": "预计量产日期",
    "transaction_date": "业务日期",
    "voucher_date": "凭证日期",
    "invoice_date": "发票日期",
    "receipt_date": "收款日期",
    "payment_date": "付款日期",
    "required_delivery_date": "要求交期",
    "valid_until": "有效期至",
    "customer_po_date": "客户PO日期",
    "po_date": "采购订单日期",
    "delivery_date": "交期",
    "production_date": "生产日期",
    "matched_at": "勾稽时间",
    "closed_at": "关闭时间",
    "posted_at": "过账时间",
    "completed_at": "完成时间",
    "planned_date": "计划日期",
    "submitted_at": "提交时间",
    "adjusted_at": "调整时间",
    "last_updated": "最后更新时间",
    "timestamp": "时间戳",

    # 外键 - 指向的都是同一张表，含义一致
    "customer_id": "客户",
    "supplier_id": "供应商",
    "material_id": "物料",
    "warehouse_id": "仓库",
    "location_id": "库位",
    "user_id": "用户",
    "parent_id": "上级",
    "category_id": "分类",
    "account_id": "会计科目",
    "period_id": "会计期间",
    "fiscal_year_id": "会计年度",
    "voucher_id": "凭证",
    "sales_order_id": "销售订单",
    "sales_order_line_id": "销售订单行",
    "purchase_order_id": "采购订单",
    "purchase_order_line_id": "采购订单行",
    "shipment_id": "发货单",
    "goods_receipt_id": "入库单",
    "picking_list_id": "拣货单",
    "inventory_id": "库存批次",
    "reservation_number": "预留单号",
    "reserved_by_id": "预留人",
    "uploaded_by_id": "上传人",
    "project_id": "选型项目",
    "inquiry_id": "询价单",
    "quotation_id": "报价单",
    "purchase_notice_id": "采购通知",
    "preferred_supplier_id": "建议供应商",
    "purchase_invoice_id": "采购发票",
    "sales_invoice_id": "销售发票",
    "goods_receipt_line_id": "入库单行",
    "shipment_line_id": "发货行",
    "workflow_id": "流程",
    "framework_contract_id": "框架合同",
    "related_sales_order_id": "关联销售订单",
    "closed_by_id": "结账人",
    "posted_by_id": "过账人",
    "received_by_id": "收货人",
    "requested_by_id": "申请人",
    "approved_by_id": "审批人",
    "assigned_to_id": "拣货员",
    "counted_by_id": "盘点人",
    "adjusted_by_id": "调整人",
    "sales_engineer_id": "销售工程师",
    "sales_assistant_id": "销售助理",
    "product_manager_id": "PM",
    "purchase_assistant_id": "产品助理",
    "product_engineer_id": "产品工程师",
    "triggered_by_id": "操作人",

    # 联系人/地址
    "contact_person": "联系人",
    "contact_email": "邮箱",
    "contact_phone": "电话",
    "country": "国家/地区",
    "city": "城市",
    "address": "地址",
    "phone": "电话",
    "department": "部门",

    # 地理/分类
    "tax_type": "税务类型",
    "warehouse_type": "仓库类型",
    "zone": "区域",
    "shelf": "货架",
    "position": "层位",
    "batch_number": "批次号",
    "inbound_number": "入仓编号",
    "serial_lot_number": "SN/LOT#",
    "source_doc_number": "来源单号",
    "location_code": "位置",
    "rule_name": "规则名称",
    "exact_length": "固定长度",
    "min_length": "最小长度",
    "max_length": "最大长度",
    "pattern": "正则规则",
    "allow_duplicate": "允许重复",
    "unique_scope": "唯一性范围",
    "reserved_at": "预留时间",
    "released_at": "释放时间",
    "doc_type": "单据类型",
    "doc_id": "单据ID",
    "attachment_type": "附件类型",
    "file_name": "文件名",
    "content_type": "文件类型",
    "file_size": "文件大小",
    "storage_path": "存储路径",
    "uploaded_at": "上传时间",

    # 业务
    "role": "角色",
    "is_admin": "超级管理员",
    "product_line": "产品线",
    "is_domestic": "国产",
    "unit": "单位",
    "uom": "数量单位",
    "sku": "料号",
    "part_revision": "版本",
    "technical_specs": "技术参数",
    "quality_score": "质量评分",
    "quality_status": "质量状态",
    "discrepancy_note": "差异说明",
    "shipping_method": "发货方式",
    "default_shipping_method": "默认发货方式",
    "shipment_terms": "贸易/运输条款",
    "ship_via": "承运方式",
    "tracking_number": "物流单号",
    "logistics_tracking_number": "退货物流单号",
    "payment_terms_days": "账期(天)",
    "payment_terms_text": "付款方式",
    "payment_requirement": "付款要求",
    "requires_advance_receipt": "需要客户预收",
    "advance_receipt_amount": "预收金额",
    "requires_advance_payment": "需要供应商预付",
    "advance_payment_amount": "预付金额",
    "delivery_address": "收货地址",
    "bill_to_name": "账单方名称",
    "bill_to_address": "账单地址",
    "bill_to_contact": "账单联系人",
    "bill_to_phone": "账单电话",
    "ship_to_name": "收货方名称",
    "ship_to_address": "收货地址",
    "ship_to_contact": "收货联系人",
    "ship_to_phone": "收货电话",
    "customer_region": "区域",
    "packaging_requirements": "包装要求",
    "barcode_requirements": "条码要求",
    "delivery_requirements": "发货要求",
    "label_status": "标签状态",
    "inspection_status": "复检状态",
    "document_status": "交单/开票状态",
    "source_purchase_order_number": "采购PO号",
    "end_user": "最终用户",
    "vendor_code": "供应商代码",
    "supplier_contact": "供应商联系人",
    "buyer_name": "采购员",
    "sales_assistant_names": "销售助理名单",
    "goods_nature": "货物性质",
    "delivery_method": "送货形式",
    "carton_number": "箱号",
    "origin_country": "原产地",
    "hs_code": "HS编码",
    "date_code": "Date Code",

    # 订单/单据号
    "order_number": "订单编号",
    "customer_po_number": "客户PO号",
    "customer_vendor_no": "客户侧供应商号",
    "quotation_reference": "报价参考号",
    "customer_line_number": "客户行号",
    "customer_pr_number": "客户PR号",
    "customer_part_number": "客户料号",
    "supplier_part_number": "供应商料号",
    "order_type": "订单类型",
    "invoice_number": "发票号",
    "inquiry_number": "询价单号",
    "quotation_number": "报价单号",
    "notice_number": "通知单号",
    "return_number": "退货单号",
    "payment_number": "付款单号",
    "receipt_number": "入库单号",
    "shipment_number": "发货单号",
    "voucher_number": "凭证号",
    "voucher_type": "凭证类型",
    "contract_number": "合同编号",

    # 信用额度
    "credit_limit": "信用额度",
    "used_amount": "已用额度",
    "warning_threshold_pct": "预警阈值(%)",

    # 会计
    "debit": "借方",
    "credit": "贷方",
    "total_debit": "借方合计",
    "total_credit": "贷方合计",
    "opening_debit": "期初借方",
    "opening_credit": "期初贷方",
    "period_debit": "本期借方",
    "period_credit": "本期贷方",
    "closing_debit": "期末借方",
    "closing_credit": "期末贷方",
    "account_type": "科目类型",
    "balance_direction": "余额方向",
    "level": "级次",
    "is_leaf": "明细科目",
    "attachment_count": "附件数",
    "is_auto_generated": "系统生成",
    "source_doc_type": "来源单据类型",
    "source_doc_id": "来源单据ID",
    "tax_rate": "税率",
    "cost_amount": "成本金额",

    # 库存
    "transaction_type": "业务类型",
    "reference_type": "来源类型",
    "reference_id": "来源ID",
    "cost_method": "计价方法",
    "current_unit_cost": "当前单位成本",
    "total_quantity": "总数量",
    "total_value": "总价值",

    # 其他
    "year": "年度",
    "period_number": "期间号",
    "expected_annual_revenue": "预计年收入",
    "source": "来源",
    "target_price": "目标价",
    "target_unit_price": "目标单价",
    "product_description": "产品描述",
    "delivery_days": "交期(天)",
    "return_reason": "退货原因",
    "return_action": "退货处理",
    "payer_name": "付款方",
    "payee_name": "收款方",
    "bank_account": "银行账户",
    "stage": "阶段",
    "rolling_forecast": "滚动预测",
    "is_stock_order": "自主备货",
    "is_verified": "已核验",
    "is_default": "默认",
    "template_content": "模板内容",
    "fields_mapping": "字段映射",
    "activity_type": "活动类型",
    "entry_type": "条目类型",
    "title": "标题",
    "content": "内容",
    "applicable_doc_types": "适用单据类型",

    # 流程引擎
    "doc_type": "单据类型",
    "doc_id": "单据ID",
    "version": "版本",
    "states": "状态列表",
    "node_positions": "节点坐标",
    "is_frozen": "已冻结",
    "transition_name": "操作名称",
    "from_state": "起始状态",
    "to_state": "目标状态",
    "allowed_roles": "允许角色",
    "editable_fields": "可编辑字段",
    "conditions": "前置条件",
    "auto_actions": "自动动作",
    "related_data": "关联数据",
    "custom_html": "自定义页面",
    "agent_tools": "节点Agent工具",
    "state_code": "节点状态",
    "doc_type": "单据类型",
    "applicable_doc_types": "适用单据类型",
    "sort_order": "排序",
    "workflow_version": "流程版本",
    "changed_fields": "变更字段",
    "data_snapshot": "数据快照",
    "hooks_executed": "已执行钩子",
    "ip_address": "IP地址",
    "password_hash": "密码哈希",

    # Agent
    "agent_type": "Agent类型",
    "user_query": "用户问题",
    "tools_called": "调用的工具",
    "response": "回复内容",
    "tokens_used": "Token消耗",
    "duration_ms": "耗时(ms)",

    # 客户/供应商
    "code_type": "编码类型",
}


# ============================================================
# 表级覆盖（含义需要特殊化时用）
# ============================================================

TABLE_LABELS = {
    "company": {
        "_table": "公司",
        "name": "公司全称", "short_name": "公司简称", "code": "公司代码",
    },
    "user_account": {
        "_table": "用户",
        "is_active": "账号启用",
    },
    "customer": {
        "_table": "客户",
        "status": "客户状态",
        "name": "客户名称", "short_name": "客户简称", "code": "客户代码",
    },
    "supplier": {
        "_table": "供应商",
        "status": "供应商状态",
        "name": "供应商名称", "short_name": "供应商简称", "code": "供应商代码",
    },
    "material": {
        "_table": "物料",
        "name": "物料名称", "description": "物料描述",
    },
    "material_category": {
        "_table": "物料分类",
        "name": "分类名称", "code": "分类代码",
    },
    "warehouse": {
        "_table": "仓库",
        "name": "仓库名称", "code": "仓库代码",
    },
    "warehouse_location": {
        "_table": "库位",
        "code": "库位编码",
    },
    "inventory": {
        "_table": "库存",
        "status": "库存状态",
    },
    "inventory_reservation": {
        "_table": "库存预留",
        "status": "预留状态",
    },
    "inventory_policy": {
        "_table": "库存策略",
    },
    "inventory_count": {
        "_table": "库存盘点任务",
        "status": "盘点状态",
    },
    "inventory_count_line": {
        "_table": "库存盘点明细",
        "status": "盘点行状态",
    },
    "supplier_sn_rule": {
        "_table": "SN/LOT规则",
        "status": "规则状态",
    },
    "wms_attachment": {
        "_table": "WMS附件",
    },
    "inventory_transaction": {"_table": "库存流水"},
    "inventory_movement": {"_table": "库存事实流水"},
    "inventory_valuation": {"_table": "存货计价"},
    "sales_order": {
        "_table": "销售订单",
        "status": "订单状态", "notes": "订单备注",
    },
    "sales_order_line": {"_table": "销售订单行"},
    "sales_inquiry": {
        "_table": "客户询价",
        "status": "询价状态", "notes": "询价备注",
    },
    "sales_inquiry_line": {"_table": "询价明细"},
    "quotation": {
        "_table": "报价单",
        "status": "报价状态", "notes": "报价备注",
    },
    "quotation_line": {"_table": "报价明细"},
    "purchase_order": {
        "_table": "采购订单",
        "status": "订单状态", "notes": "订单备注",
    },
    "purchase_order_line": {"_table": "采购订单行"},
    "purchase_notice": {
        "_table": "采购通知",
        "status": "通知状态", "notes": "采购备注",
    },
    "purchase_notice_line": {"_table": "采购通知行"},
    "goods_receipt": {
        "_table": "收料单",
        "status": "入库状态",
    },
    "goods_receipt_line": {"_table": "收料单行"},
    "shipment_request": {
        "_table": "发货请求",
        "status": "发货状态",
    },
    "shipment_line": {"_table": "发货行"},
    "sales_return": {
        "_table": "销售退货",
        "status": "退货状态",
    },
    "sales_return_line": {"_table": "销售退货行"},
    "picking_list": {"_table": "拣货单"},
    "picking_list_line": {"_table": "拣货单行"},
    "voucher": {
        "_table": "凭证",
        "status": "凭证状态", "description": "摘要",
    },
    "voucher_entry": {
        "_table": "凭证分录",
        "description": "分录摘要",
    },
    "account": {
        "_table": "会计科目",
        "name": "科目名称", "code": "科目编码",
    },
    "account_balance": {"_table": "科目余额"},
    "accounts_receivable": {
        "_table": "应收账款",
        "status": "应收状态",
    },
    "accounts_payable": {
        "_table": "应付账款",
        "status": "应付状态",
    },
    "advance_receipt": {
        "_table": "预收单",
        "status": "预收状态",
    },
    "advance_payment": {
        "_table": "预付单",
        "status": "预付状态",
    },
    "purchase_invoice": {
        "_table": "采购发票",
        "status": "发票状态",
    },
    "purchase_invoice_line": {"_table": "采购发票行"},
    "sales_invoice": {
        "_table": "销售发票",
        "status": "发票状态",
    },
    "sales_invoice_line": {"_table": "销售发票行"},
    "supplier_credit": {"_table": "供应商信用额度"},
    "customer_credit": {"_table": "客户信用额度"},
    "framework_contract": {
        "_table": "框架合同",
        "notes": "合同备注",
    },
    "project": {
        "_table": "项目",
        "name": "项目名称", "description": "项目描述",
        "stage": "项目阶段", "is_active": "进行中",
    },
    "project_material": {"_table": "项目物料"},
    "project_activity": {"_table": "项目活动"},
    "fiscal_year": {
        "_table": "会计年度",
        "status": "年度状态",
    },
    "accounting_period": {
        "_table": "会计期间",
        "status": "期间状态",
    },
    "exchange_rate": {"_table": "汇率"},
    "workflow_log": {"_table": "流程日志"},
    "workflow_definition": {"_table": "流程定义"},
    "knowledge_entry": {"_table": "知识库条目"},
    "label_template": {
        "_table": "标签模板",
        "name": "模板名称",
    },
}


def get_label(table: str, field: str) -> str:
    """取字段的中文标签"""
    return TABLE_LABELS.get(table, {}).get(field) or GLOBAL_LABELS.get(field) or field


def get_table_label(table: str) -> str:
    """取表自身的中文名（存在 TABLE_LABELS[table]["_table"] 里）"""
    return TABLE_LABELS.get(table, {}).get("_table") or table


# ============================================================
# 枚举值翻译
# ============================================================

VALUE_LABELS = {
    # 凭证类型
    "voucher_type": {
        "GENERAL": "记账凭证", "CASH": "收款凭证",
        "PAYMENT": "付款凭证", "TRANSFER": "转账凭证",
    },
    # 科目类型
    "account_type": {
        "ASSET": "资产", "LIABILITY": "负债", "EQUITY": "所有者权益",
        "REVENUE": "收入", "EXPENSE": "费用", "COGS": "营业成本", "OTHER": "其他",
    },
    # 方向
    "balance_direction": {"DEBIT": "借", "CREDIT": "贷"},
    # 编码类型
    "code_type": {"LONG_TERM": "长期代码", "TEMPORARY": "临时代码"},
    # 仓库类型
    "warehouse_type": {"MAIN": "主仓", "BONDED": "保税区", "BRANCH": "分仓"},
    # 税务
    "tax_type": {"NONE": "无税", "VAT": "增值税"},
    # 产品线
    "product_line": {
        "QUANTUM": "量子", "OPTICAL_COMM": "光通信",
        "SENSING": "传感", "INDUSTRIAL": "工业", "OTHER": "其他",
    },
    # 订单类型
    "order_type": {"STANDARD": "标准", "TRADE": "贸易(背靠背)"},
    # 角色
    "role": {
        "BOSS": "老板", "OPERATIONS": "运营", "FINANCE": "财务",
        "SALES_ENGINEER": "销售工程师", "SALES_ASSISTANT": "销售助理",
        "PRODUCT_MANAGER": "产品经理", "PRODUCT_ASSISTANT": "产品助理",
        "LOGISTICS": "物流", "ADMIN": "管理员", "FAE": "现场应用工程师",
    },
    # 发货方式
    "shipping_method": {"FOB": "FOB离岸", "CIF": "CIF到岸", "DAP": "送货到厂", "EXW": "工厂交货"},
    "default_shipping_method": {"FOB": "FOB离岸", "CIF": "CIF到岸", "DAP": "送货到厂", "EXW": "工厂交货"},
    # 计价方法
    "cost_method": {
        "WEIGHTED_AVG": "全月加权平均", "MOVING_AVG": "移动加权平均", "FIFO": "先进先出",
    },
    # 质量状态
    "quality_status": {"OK": "合格", "DAMAGED": "损坏", "SHORT": "短缺", "EXCESS": "多发"},
    # 交易类型
    "transaction_type": {
        "PURCHASE_IN": "采购入库", "SALES_OUT": "销售出库",
        "STOCK_IN": "其他入库", "STOCK_OUT": "其他出库",
        "TRANSFER": "调拨", "ADJUST_PLUS": "盘盈", "ADJUST_MINUS": "盘亏",
        "RETURN_IN": "退货入库", "RETURN_OUT": "退货出库",
    },
    # 通用是/否
    "is_active": {True: "启用", False: "停用"},
    "is_admin": {True: "是", False: "否"},
    "is_domestic": {True: "国产", False: "进口"},
    "is_stock_order": {True: "自主备货", False: "订单驱动"},
    "is_leaf": {True: "明细科目", False: "父级科目"},
    "is_auto_generated": {True: "系统生成", False: "手工录入"},
    "is_frozen": {True: "已冻结", False: "未冻结"},
    "is_default": {True: "默认", False: "非默认"},
    "is_verified": {True: "已核验", False: "待核验"},
}


def get_value_label(field: str, value) -> str:
    """取字段值的中文（布尔/枚举）"""
    if value is None:
        return ""
    mapping = VALUE_LABELS.get(field)
    if mapping and value in mapping:
        return mapping[value]
    return str(value)
