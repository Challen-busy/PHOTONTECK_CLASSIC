"""第一期 CRM/WMS/ERP 打通流程定义。

这些定义直接使用 WorkflowDefinition.states 的 states-only 结构，避免再走旧版
raw transitions 折叠逻辑。seed.py 和补种脚本都复用这里。
"""


def _start(roles, first_state="DRAFT", label="开始录入"):
    return {
        "code": "START",
        "name": "开始",
        "is_initial": True,
        "allowed_roles": roles,
        "description": "# 开始节点\n创建空单据后进入业务录入节点。",
        "custom_html": "",
        "hard_rules": [],
        "hooks": [],
        "next": [{"to": first_state, "label": label, "editable_fields": []}],
    }


def _state(code, name, roles, next_list=None, terminal=False, description="", hooks=None, effects=None):
    state = {
        "code": code,
        "name": name,
        "allowed_roles": roles,
        "description": description,
        "custom_html": "",
        "hard_rules": [],
        "hooks": hooks or [],
        "effects": effects or [],
        "next": next_list or [],
    }
    if terminal:
        state["is_terminal"] = True
    return state


def phase1_workflow_definitions(created_by_id=None):
    """返回可直接传给 models.WorkflowDefinition(**kwargs) 的定义列表。"""

    sales_inquiry_fields = [
        "customer_id", "sales_assistant_id", "product_manager_id", "source",
        "target_price", "currency", "required_delivery_date", "delivery_address",
        "packaging_requirements", "barcode_requirements", "payment_requirement", "notes",
    ]
    quotation_fields = [
        "inquiry_id", "customer_id", "sales_assistant_id", "product_manager_id",
        "currency", "total_amount", "tax_rate", "payment_terms_days", "shipping_method",
        "valid_until", "delivery_address", "packaging_requirements", "barcode_requirements", "notes",
    ]
    sales_order_fields = [
        "customer_id", "inquiry_id", "quotation_id", "order_number", "customer_po_number",
        "customer_po_date", "customer_vendor_no", "quotation_reference", "currency",
        "exchange_rate", "total_amount", "payment_terms_days", "payment_terms_text",
        "shipping_method", "shipment_terms", "requires_advance_receipt",
        "advance_receipt_amount", "delivery_address", "bill_to_name", "bill_to_address",
        "bill_to_contact", "bill_to_phone", "ship_to_name", "ship_to_address",
        "ship_to_contact", "ship_to_phone", "packaging_requirements",
        "barcode_requirements", "sales_engineer_id", "sales_assistant_id",
        "sales_assistant_names", "product_manager_id", "customer_region", "notes",
    ]
    purchase_notice_fields = [
        "sales_order_id", "requested_by_id", "purchase_assistant_id",
        "required_delivery_date", "notes",
    ]
    purchase_order_fields = [
        "supplier_id", "purchase_assistant_id", "related_sales_order_id", "purchase_notice_id",
        "po_date", "currency", "total_amount", "expected_delivery_date",
        "shipment_terms", "payment_terms_text", "ship_to_name", "ship_to_address",
        "ship_to_contact", "ship_to_phone", "bill_to_name", "bill_to_address",
        "bill_to_contact", "bill_to_phone", "end_user", "vendor_code", "ship_via",
        "supplier_contact", "buyer_name", "requires_advance_payment",
        "advance_payment_amount", "notes",
    ]
    shipment_fields = [
        "sales_order_id", "requested_by_id", "approved_by_id", "warehouse_id",
        "shipping_method", "tracking_number", "source_purchase_order_number",
        "product_line", "payment_terms_text", "document_status", "packaging_requirements",
        "barcode_requirements", "delivery_requirements", "label_status",
        "inspection_status", "shipped_date", "notes",
    ]
    goods_receipt_fields = [
        "purchase_order_id", "warehouse_id", "received_by_id", "received_date", "notes",
    ]

    inquiry_to_quote_effect = ["crm.create_quotation_from_inquiry"]
    quote_to_so_effect = ["crm.create_sales_order_from_quotation"]
    sales_order_to_purchase_notice_effect = ["erp.create_purchase_notice_from_sales_order"]
    sales_order_advance_receipt_effect = ["finance.create_advance_receipt_from_sales_order"]
    purchase_notice_sent_effect = ["erp.mark_sales_order_purchase_notice_sent"]
    purchase_notice_to_po_effect = ["erp.create_purchase_order_from_notice"]
    purchase_order_to_goods_receipt_effect = ["wms.create_goods_receipt_from_purchase_order"]
    purchase_order_advance_payment_effect = ["finance.create_advance_payment_from_purchase_order"]
    goods_receipt_stock_effect = ["wms.stock_goods_receipt"]
    goods_receipt_followup_effect = ["erp.complete_purchase_receipt_followup"]
    sales_order_to_shipment_effect = ["wms.create_shipment_from_sales_order"]
    shipment_stock_effect = ["wms.apply_shipment_stock_out"]
    shipment_sales_invoice_effect = ["finance.create_sales_invoice_from_shipment"]
    shipment_sales_return_effect = ["wms.create_sales_return_from_shipment"]
    purchase_invoice_ap_effect = ["finance.create_accounts_payable_from_purchase_invoice"]
    purchase_invoice_po_effect = ["erp.mark_purchase_order_invoice_matching"]
    sales_invoice_ar_effect = ["finance.create_accounts_receivable_from_sales_invoice"]

    defs = [
        {
            "doc_type": "SALES_INQUIRY",
            "name": "CRM-客户询价流程",
            "description": "客户询价 -> PM 授权 -> 生成报价单。",
            "group_name": "CRM",
            "states": [
                _start(["SALES_ASSISTANT", "SALES_ENGINEER", "OPERATIONS"]),
                _state("DRAFT", "客户询价", ["SALES_ASSISTANT", "SALES_ENGINEER", "OPERATIONS"], [
                    {"to": "PM_REVIEW", "label": "提交 PM 授权", "editable_fields": sales_inquiry_fields},
                    {"to": "CANCELLED", "label": "取消询价", "editable_fields": ["notes"]},
                ], description="# 客户询价\n录入客户需求、数量、目标价、交期、包装和条码要求。"),
                _state("PM_REVIEW", "PM 授权报价", ["PRODUCT_MANAGER", "OPERATIONS"], [
                    {"to": "AUTHORIZED", "label": "授权报价", "editable_fields": ["product_manager_id", "notes"]},
                    {"to": "REJECTED", "label": "拒绝报价", "editable_fields": ["notes"]},
                ]),
                _state("AUTHORIZED", "已授权", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "QUOTATION_CREATED", "label": "生成报价单", "editable_fields": [], "effects": inquiry_to_quote_effect},
                ]),
                _state("QUOTATION_CREATED", "已生成报价单", [], terminal=True),
                _state("REJECTED", "已拒绝", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "QUOTATION",
            "name": "CRM-报价单流程",
            "description": "报价单 -> 客户确认 -> 生成销售订单。",
            "group_name": "CRM",
            "states": [
                _start(["SALES_ASSISTANT", "OPERATIONS"]),
                _state("DRAFT", "制作报价单", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "PM_APPROVAL", "label": "提交 PM 审核", "editable_fields": quotation_fields},
                    {"to": "CANCELLED", "label": "取消报价", "editable_fields": ["notes"]},
                ]),
                _state("PM_APPROVAL", "PM 审核报价", ["PRODUCT_MANAGER", "OPERATIONS"], [
                    {"to": "SENT", "label": "审核通过并发送客户", "editable_fields": ["notes"]},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                _state("SENT", "已发客户", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "CUSTOMER_CONFIRMED", "label": "客户确认", "editable_fields": ["notes"]},
                    {"to": "CUSTOMER_REJECTED", "label": "客户拒绝", "editable_fields": ["notes"]},
                ]),
                _state("CUSTOMER_CONFIRMED", "客户已确认", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "SALES_ORDER_CREATED", "label": "生成销售订单", "editable_fields": [], "effects": quote_to_so_effect},
                ]),
                _state("SALES_ORDER_CREATED", "已生成销售订单", [], terminal=True),
                _state("CUSTOMER_REJECTED", "客户已拒绝", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "SALES_ORDER",
            "name": "ERP-销售订单履约流程",
            "description": "销售订单审核 -> 预收判断 -> 采购通知 -> 发货通知。",
            "group_name": "ERP",
            "states": [
                _start(["SALES_ASSISTANT", "OPERATIONS"]),
                _state("DRAFT", "SA 录入客户订单", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "SALES_MANAGER_REVIEW", "label": "提交销售经理审核", "editable_fields": sales_order_fields},
                    {"to": "CANCELLED", "label": "取消订单", "editable_fields": ["notes"]},
                ]),
                _state("SALES_MANAGER_REVIEW", "销售经理审核", ["OPERATIONS", "BOSS"], [
                    {"to": "ADVANCE_RECEIPT_REQUIRED", "label": "需要客户预收", "editable_fields": ["requires_advance_receipt", "advance_receipt_amount", "notes"], "effects": sales_order_advance_receipt_effect},
                    {"to": "READY_FOR_PURCHASE", "label": "无需预收/放行采购", "editable_fields": ["notes"]},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                _state("ADVANCE_RECEIPT_REQUIRED", "待客户预收", ["FINANCE", "SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "READY_FOR_PURCHASE", "label": "预收已确认", "editable_fields": ["notes"]},
                ]),
                _state("READY_FOR_PURCHASE", "可发起采购通知", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "PURCHASE_NOTICE_SENT", "label": "已发起采购通知", "editable_fields": ["notes"]},
                ], effects=sales_order_to_purchase_notice_effect),
                _state("PURCHASE_NOTICE_SENT", "采购处理中", ["SALES_ASSISTANT", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "READY_TO_SHIP", "label": "库存满足可发货", "editable_fields": ["notes"]},
                ]),
                _state("READY_TO_SHIP", "待发货通知", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "SHIPMENT_REQUESTED", "label": "已发布发货通知", "editable_fields": ["notes"], "effects": sales_order_to_shipment_effect},
                ]),
                _state("SHIPMENT_REQUESTED", "发货执行中", ["LOGISTICS", "FINANCE", "OPERATIONS"], [
                    {"to": "COMPLETED", "label": "订单完成", "editable_fields": ["notes"]},
                ]),
                _state("COMPLETED", "已完成", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "PURCHASE_NOTICE",
            "name": "ERP-采购通知流程",
            "description": "SA 发起采购通知 -> PA 接收 -> 生成采购订单。",
            "group_name": "ERP",
            "states": [
                _start(["SALES_ASSISTANT", "OPERATIONS"]),
                _state("DRAFT", "SA 发起采购通知", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "PA_ACCEPTED", "label": "提交 PA 接收", "editable_fields": purchase_notice_fields, "effects": purchase_notice_sent_effect},
                    {"to": "CANCELLED", "label": "取消通知", "editable_fields": ["notes"]},
                ]),
                _state("PA_ACCEPTED", "PA 已接收", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "PURCHASE_ORDER_CREATED", "label": "生成采购订单", "editable_fields": ["purchase_assistant_id", "notes"], "effects": purchase_notice_to_po_effect},
                ]),
                _state("PURCHASE_ORDER_CREATED", "已生成采购订单", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "PURCHASE_ORDER",
            "name": "ERP-采购订单履约流程",
            "description": "采购订单审核 -> 预付判断 -> 到货 -> 入库/发票。",
            "group_name": "ERP",
            "states": [
                _start(["PRODUCT_ASSISTANT", "OPERATIONS"]),
                _state("DRAFT", "PA 录入采购订单", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "SUPPLY_MANAGER_REVIEW", "label": "提交供应经理审核", "editable_fields": purchase_order_fields},
                    {"to": "CANCELLED", "label": "取消采购", "editable_fields": ["notes"]},
                ]),
                _state("SUPPLY_MANAGER_REVIEW", "供应经理审核", ["PRODUCT_MANAGER", "OPERATIONS", "BOSS"], [
                    {"to": "ADVANCE_PAYMENT_REQUIRED", "label": "需要预付款", "editable_fields": ["requires_advance_payment", "advance_payment_amount", "notes"], "effects": purchase_order_advance_payment_effect},
                    {"to": "ORDERED", "label": "审核通过并下单", "editable_fields": ["expected_delivery_date", "notes"]},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                _state("ADVANCE_PAYMENT_REQUIRED", "待供应商预付", ["PRODUCT_ASSISTANT", "FINANCE", "OPERATIONS"], [
                    {"to": "ORDERED", "label": "预付已完成并下单", "editable_fields": ["notes"]},
                ]),
                _state("ORDERED", "已下单待到货", ["LOGISTICS", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "GOODS_RECEIVED", "label": "仓库已收货", "editable_fields": ["actual_delivery_date", "notes"], "effects": purchase_order_to_goods_receipt_effect},
                ]),
                _state("GOODS_RECEIVED", "已到货待入库", ["LOGISTICS", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "STOCKED_IN", "label": "入库完成", "editable_fields": ["notes"]},
                ]),
                _state("STOCKED_IN", "已入库待发票", ["FINANCE", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "INVOICE_MATCHING", "label": "采购发票勾稽", "editable_fields": ["notes"]},
                ]),
                _state("INVOICE_MATCHING", "采购核算完成", ["FINANCE", "OPERATIONS"], [
                    {"to": "COMPLETED", "label": "采购完成", "editable_fields": ["notes"]},
                ]),
                _state("COMPLETED", "已完成", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "GOODS_RECEIPT",
            "name": "WMS-采购收货入库流程",
            "description": "仓库收货 -> PA 审核 -> 库存入库。",
            "group_name": "WMS",
            "states": [
                _start(["LOGISTICS", "OPERATIONS"], first_state="PENDING", label="开始收货录入"),
                _state("PENDING", "仓库收货录入", ["LOGISTICS", "OPERATIONS"], [
                    {"to": "PA_REVIEW", "label": "提交 PA 审核", "editable_fields": goods_receipt_fields},
                    {"to": "CANCELLED", "label": "取消入库", "editable_fields": ["notes"]},
                ]),
                _state("PA_REVIEW", "PA 审核入库单", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "STOCKED_IN", "label": "审核通过入库", "editable_fields": ["notes"], "effects": goods_receipt_stock_effect + goods_receipt_followup_effect},
                    {"to": "PENDING", "label": "退回仓库修改", "editable_fields": ["notes"]},
                ]),
                _state("STOCKED_IN", "已入库", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "SHIPMENT",
            "name": "WMS-发货出库流程",
            "description": "发货通知 -> 财务放行 -> 包装贴标 -> 复检出库 -> 客户签收。",
            "group_name": "WMS",
            "states": [
                _start(["SALES_ASSISTANT", "OPERATIONS"]),
                _state("DRAFT", "SA 发布发货通知", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "FINANCE_APPROVAL", "label": "提交财务审批", "editable_fields": shipment_fields},
                    {"to": "CANCELLED", "label": "取消发货", "editable_fields": ["notes"]},
                ]),
                _state("FINANCE_APPROVAL", "财务审批放行", ["FINANCE", "OPERATIONS", "BOSS"], [
                    {"to": "PACKING_LABELING", "label": "财务放行", "editable_fields": ["approved_by_id", "notes"]},
                    {"to": "EXCEPTION_APPROVAL", "label": "超额/超期审批", "editable_fields": ["notes"]},
                ]),
                _state("EXCEPTION_APPROVAL", "例外审批", ["BOSS", "OPERATIONS"], [
                    {"to": "PACKING_LABELING", "label": "特批放行", "editable_fields": ["notes"]},
                    {"to": "CANCELLED", "label": "驳回发货", "editable_fields": ["notes"]},
                ]),
                _state("PACKING_LABELING", "包装与制标", ["LOGISTICS", "OPERATIONS"], [
                    {"to": "PICKING_RECHECK", "label": "完成制标并拣货复检", "editable_fields": ["label_status", "inspection_status", "tracking_number", "notes"]},
                ]),
                _state("PICKING_RECHECK", "拣货复检", ["LOGISTICS", "OPERATIONS"], [
                    {"to": "SALES_OUTBOUND", "label": "确认出库", "editable_fields": ["shipped_date", "tracking_number", "notes"], "effects": shipment_stock_effect + shipment_sales_invoice_effect},
                ]),
                _state("SALES_OUTBOUND", "销售出库", ["FINANCE", "LOGISTICS", "OPERATIONS"], [
                    {"to": "CUSTOMER_RECEIVED", "label": "客户签收", "editable_fields": ["notes"]},
                    {"to": "RETURN_REQUESTED", "label": "客户退货", "editable_fields": ["notes"], "effects": shipment_sales_return_effect},
                ]),
                _state("CUSTOMER_RECEIVED", "客户已收货", [], terminal=True),
                _state("RETURN_REQUESTED", "客户退货处理中", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "ADVANCE_RECEIPT",
            "name": "ERP-预收款流程",
            "description": "财务登记客户预收款并关联销售订单。",
            "group_name": "ERP",
            "states": [
                _start(["FINANCE", "OPERATIONS"]),
                _state("DRAFT", "录入预收单", ["FINANCE", "OPERATIONS"], [
                    {"to": "CONFIRMED", "label": "确认到账", "editable_fields": ["customer_id", "sales_order_id", "receipt_number", "bank_account", "payer_name", "amount", "currency", "receipt_date", "notes"]},
                    {"to": "CANCELLED", "label": "取消预收", "editable_fields": ["notes"]},
                ]),
                _state("CONFIRMED", "已确认到账", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "ADVANCE_PAYMENT",
            "name": "ERP-预付款流程",
            "description": "PA/财务申请并支付供应商预付款。",
            "group_name": "ERP",
            "states": [
                _start(["PRODUCT_ASSISTANT", "FINANCE", "OPERATIONS"]),
                _state("DRAFT", "录入预付申请", ["PRODUCT_ASSISTANT", "FINANCE", "OPERATIONS"], [
                    {"to": "FINANCE_REVIEW", "label": "提交财务审核", "editable_fields": ["supplier_id", "purchase_order_id", "payment_number", "requested_by_id", "amount", "currency", "payee_name", "bank_account", "notes"]},
                    {"to": "CANCELLED", "label": "取消预付", "editable_fields": ["notes"]},
                ]),
                _state("FINANCE_REVIEW", "财务审核付款", ["FINANCE", "OPERATIONS"], [
                    {"to": "PAID", "label": "确认付款", "editable_fields": ["approved_by_id", "payment_date", "notes"]},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                _state("PAID", "已付款", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "PURCHASE_INVOICE",
            "name": "ERP-采购发票勾稽流程",
            "description": "采购发票 -> 外购入库勾稽 -> 应付账款。",
            "group_name": "ERP",
            "states": [
                _start(["FINANCE", "PRODUCT_ASSISTANT", "OPERATIONS"]),
                _state("DRAFT", "登记采购发票", ["FINANCE", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "MATCHING", "label": "提交勾稽", "editable_fields": ["invoice_number", "supplier_id", "purchase_order_id", "goods_receipt_id", "amount", "currency", "tax_rate", "invoice_date", "notes"]},
                    {"to": "CANCELLED", "label": "取消发票", "editable_fields": ["notes"]},
                ]),
                _state("MATCHING", "采购发票勾稽", ["FINANCE", "OPERATIONS"], [
                    {"to": "AP_CREATED", "label": "勾稽通过并生成应付", "editable_fields": ["notes"], "effects": purchase_invoice_ap_effect + purchase_invoice_po_effect},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                _state("AP_CREATED", "已生成应付", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "SALES_INVOICE",
            "name": "ERP-销售发票勾稽流程",
            "description": "销售发票 -> 销售出库勾稽 -> 应收账款/销售成本。",
            "group_name": "ERP",
            "states": [
                _start(["FINANCE", "OPERATIONS"]),
                _state("DRAFT", "登记销售发票", ["FINANCE", "OPERATIONS"], [
                    {"to": "MATCHING", "label": "提交勾稽", "editable_fields": ["invoice_number", "customer_id", "sales_order_id", "shipment_id", "amount", "currency", "tax_rate", "invoice_date", "notes"]},
                    {"to": "CANCELLED", "label": "取消发票", "editable_fields": ["notes"]},
                ]),
                _state("MATCHING", "销售发票勾稽", ["FINANCE", "OPERATIONS"], [
                    {"to": "AR_CREATED", "label": "勾稽通过并生成应收", "editable_fields": ["notes"], "effects": sales_invoice_ar_effect},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                _state("AR_CREATED", "已生成应收", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "SALES_RETURN",
            "name": "WMS-客户退货流程",
            "description": "客户退货通知 -> 物流收货 -> 退货入库/红字处理。",
            "group_name": "WMS",
            "states": [
                _start(["SALES_ASSISTANT", "OPERATIONS"]),
                _state("DRAFT", "SA 做退货通知", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "LOGISTICS_RECEIVING", "label": "通知物流收货", "editable_fields": ["return_number", "sales_order_id", "shipment_id", "customer_id", "warehouse_id", "return_reason", "logistics_tracking_number", "notes"]},
                    {"to": "CANCELLED", "label": "取消退货", "editable_fields": ["notes"]},
                ]),
                _state("LOGISTICS_RECEIVING", "物流收货", ["LOGISTICS", "OPERATIONS"], [
                    {"to": "RETURN_STOCKED", "label": "退货入库", "editable_fields": ["notes"]},
                ]),
                _state("RETURN_STOCKED", "退货已入库", ["FINANCE", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "CREDIT_PROCESSING", "label": "进入红字/退款处理", "editable_fields": ["notes"]},
                ]),
                _state("CREDIT_PROCESSING", "红字处理", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
    ]

    for d in defs:
        d.setdefault("version", 1)
        d.setdefault("is_published", True)
        d.setdefault("is_active", True)
        d.setdefault("node_positions", {})
        if created_by_id is not None:
            d["created_by_id"] = created_by_id
    return defs
