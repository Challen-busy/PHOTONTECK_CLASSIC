"""第一期 CRM/WMS/ERP 打通流程定义。

这些定义直接使用 WorkflowDefinition.states 的 states-only 结构，避免再走旧版
raw transitions 折叠逻辑。seed.py 和补种脚本都复用这里。
"""


# 建单取号 effect 名（在 services.numbering_effect 注册）。挂进有编号规则的流程
# START 状态的 effects，使 execute_transition 建单后同事务内把引擎默认 UUID 号换成业务连号。
NUMBERING_EFFECT = "numbering.assign_business_number"


def _start(roles, first_state="DRAFT", label="开始录入", effects=None):
    return {
        "code": "START",
        "name": "开始",
        "is_initial": True,
        "allowed_roles": roles,
        "description": "# 开始节点\n创建空单据后进入业务录入节点。",
        "custom_html": "",
        "hard_rules": [],
        "hooks": [],
        "effects": effects or [],
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
        # 04a-1 内部询价扩列（销售提供 end-customer 决策上下文）。
        "home_page", "application", "project_phase", "demand_forecast",
        "competitor", "competitor_price",
    ]
    # 04a-2 对原厂询价：头可编辑字段（子表 supplier_inquiry_line 走 SubTableEditor）。
    supplier_inquiry_fields = [
        "supplier_id", "sales_inquiry_id", "product_manager_id", "notes",
    ]
    # 已回价边 PA 可改的报价字段（QUOTED 收原厂回价）。
    supplier_inquiry_quote_fields = [
        "supplier_id", "product_manager_id", "notes",
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
        # 段3b 决策①（合同即 SO）：编号(客户订单号)/合同签章字段组/事业部分类（PRD 05 页面1/2）。
        "external_order_no", "contract_attachment_ref", "signature_status",
        "signature_party", "business_unit", "research_sub_market",
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
        # 段2b 04a-3：PO 头扩列（原厂 SO# / PM / PD / 采购通知日期 / 备货金额组 / 是否备货 / 实际发货日）。
        "factory_so_number", "product_manager_id", "pd_id", "notice_date",
        "is_stock_order", "stock_amount_original", "stock_amount_latest",
        "stock_quantity", "stock_reason", "actual_delivery_date",
    ]
    shipment_fields = [
        "sales_order_id", "requested_by_id", "approved_by_id", "warehouse_id",
        "shipping_method", "tracking_number", "source_purchase_order_number",
        "product_line", "payment_terms_text", "document_status", "packaging_requirements",
        "barcode_requirements", "delivery_requirements", "label_status",
        "inspection_status", "shipped_date", "notes",
        # 段1b-1：出库类型 + 委外发料字段（DRAFT 录入；CUSTOMER 默认走两道关，OUTSOURCE 委外直发）。
        "outbound_type", "vendor_id", "outsource_note",
    ]
    goods_receipt_fields = [
        "purchase_order_id", "warehouse_id", "received_by_id", "received_date",
        "inbound_type", "supplier_id", "customer_id", "reviewer_id", "notes",
        # 段1b-2：委外加工入库弱关联委外发料单号（03a-9b 做薄，仅留痕）。
        "source_issue_number",
    ]
    # 段1b-2 调拨单 / 库存调整单可建档/可改字段（DRAFT 录入；子表走 SubTableEditor）。
    stock_transfer_fields = [
        "transfer_number", "source_location_id", "target_location_id", "notes",
    ]
    stock_adjustment_fields = [
        "adjustment_number", "inventory_count_id", "notes",
    ]
    # 段2d-1 备货申请（04b-1）：DRAFT 可录业务字段（库存/在途快照为只读列，由 START effect 拍，
    # 不进 editable；已消数量为 SO 派生列，不进 editable；request_number 由建单取号 effect 给）。
    stock_up_request_fields = [
        "requested_by_id", "requester_role", "material_id", "stockup_quantity",
        "intended_customer_id", "signing_company_id", "customer_arrears",
        "reason", "risk_notes", "amount", "currency", "draft_po_id", "notes",
    ]
    # 金额阈值分流（决策⑤，04b-1）：DRAFT 两条出边带边级 hard_rules（rules DSL 算术比较，引擎 04 §4.B；
    # next_entry.hard_rules 在 execute_transition 推进路径被校验，已勘）。<20万→PENDING_PM，≥20万→PENDING_REVIEW。
    stock_up_under_threshold_rule = "doc.amount < 200000"
    stock_up_over_threshold_rule = "doc.amount >= 200000"
    # 段2d-2 样品 SDN（04b-3）：REQUESTED 可录申请字段（sdn_number 由建单取号 effect 给，
    # overdue_days 计算字段不入库列，子表 sample_sdn_line 走 SubTableEditor）。supplier_line 录线字母（C/L）。
    sample_sdn_request_fields = [
        "sdn_date", "supplier_id", "supplier_line", "pa_id", "pa_names", "customer_id", "sales_id",
        "sample_nature", "paid_disposition", "application", "competitor", "demand",
        "target_price", "pd_dept", "remark",
    ]
    # SDN 转正 effect（CONVERTED 推进）：该批库存 SAMPLE→AVAILABLE（§5.4，对接 03 库存）。
    sample_sdn_convert_effect = ["sample.convert_to_available"]
    # 段2d-2 RMA（04b-5）：各节点 editable_fields（节点级 allowed_roles 分 SA/PA/PM 控权，规避 D-02e 边级坑）。
    # REPORTED(SA) 录客户侧；PA_VERIFY(PA) 录采购侧 + 核料；ESCALATED_PM(PM) 填决策；VENDOR_RMA(PA) 回填原厂号。
    rma_reported_fields = [
        "rma_date", "customer_id", "sales_id", "failure_description", "failure_location", "remark",
    ]
    rma_verify_fields = [
        "supplier_id", "po_number", "ship_date", "invoice_number", "pa_id", "pe_id", "pm_id", "pd_dept", "remark",
    ]
    rma_pm_fields = ["pm_decision", "remark"]
    rma_vendor_fields = ["supplier_rma_number", "tracking", "return_customs_status", "remark"]
    rma_return_fields = ["tracking", "remark"]
    # RMA 核料 effect（PA_VERIFY 推进，gap-7 自动倒查给建议）：写 sold_by_us（倒查 SN/LOT+PO+出库）
    # + under_warranty（ship_date+质保期 vs today）。判定为建议，PA 据此走成立(ESCALATED)/驳回(REJECTED)。
    rma_verify_effect = ["rma.assess_warranty_and_origin"]
    # RMA 货回入库 effect（GOODS_RETURNED 推进）：生成退货入库 inbound_type=RETURN + inventory.source_marker
    # （RMA来源+品质好坏+原厂），好货 status=AVAILABLE 混回可售（§5.4 / 03 库存，04b-6）。
    rma_goods_returned_effect = ["rma.create_return_inbound"]
    # 调拨完成边 effect：移库位 + 写两条 TRANSFER_OUT/IN 流水（同公司 hard_rule 兜底）。
    stock_transfer_done_effect = ["wms.apply_stock_transfer"]
    # 同公司硬规则（lookup DSL，引擎 04 §4.B）：源/目标库位经各自仓库 company_id 比对相等。
    stock_transfer_same_company_hard_rule = (
        "lookup('warehouse', id=lookup('warehouse_location', id=doc.source_location_id).warehouse_id).company_id"
        " == lookup('warehouse', id=lookup('warehouse_location', id=doc.target_location_id).warehouse_id).company_id"
    )
    # 库存调整过账边 effect：调结存 + COUNT_ADJUST 流水 + 推金蝶（EXPLICIT，默认 OFF 只入 outbox）。
    stock_adjustment_post_effect = ["wms.apply_stock_adjustment", "kingdee.enqueue_push"]
    # 库存调整确认 hard_rule（引擎 04 §4.B）：每行差异原因必填。
    stock_adjustment_reason_hard_rule = "all((line.reason or '') != '' for line in lines)"

    inquiry_to_quote_effect = ["crm.create_quotation_from_inquiry"]
    quote_to_so_effect = ["crm.create_sales_order_from_quotation"]

    # 段3a CRM 前段（PRD 05 页面3/4/6）。
    # 线索可编辑字段（DRAFT 录入；lead_number 由建单取号 effect 给）。
    lead_fields = [
        "source", "content", "customer_id", "customer_name_raw", "product_line_id",
        "region", "next_step", "notes",
    ]
    # 线索「转商机」EXPLICIT 派生 effect：建 opportunity 草稿回填客户/产线/干系人（PRD 页面3 状态机）。
    lead_to_opportunity_effect = ["crm.create_opportunity_from_lead"]
    # 商机可编辑字段（前期沟通 EARLY 录全部基础字段；子表 opportunity_followup_line 走 SubTableEditor）。
    opportunity_fields = [
        "customer_id", "product_line_id", "project_name", "product_model", "business_unit",
        "research_sub_market", "grade", "owner_sales_id", "fae_id", "expected_amount",
        "expected_close_date", "next_step", "remark",
    ]
    # ★科研分流 hard_rule（rules DSL，引擎 04 §4.B）：非科研放行；科研（business_unit=RESEARCH）
    # 推进阶段时 research_sub_market 必填（PRD 页面4 送样关卡「科研需 research_sub_market」）。
    opportunity_research_sub_market_rule = (
        "doc.business_unit != 'RESEARCH' or (doc.research_sub_market or '') != ''"
    )
    # 商机推进到送样后 customer_id 必填（PRD 页面4 送样关卡）。
    opportunity_customer_required_rule = "doc.customer_id != None"
    # 报价对齐扩字段（PRD 页面6）：草稿录基础字段 + 阶梯子表 quote_tier_line。
    quote_draft_fields = quotation_fields + [
        "opportunity_id", "business_unit", "report_header", "lead_time", "trade_term",
    ]
    sales_order_to_purchase_notice_effect = ["erp.create_purchase_notice_from_sales_order"]
    sales_order_advance_receipt_effect = ["finance.create_advance_receipt_from_sales_order"]
    # 段3b 决策①：SO 审核通过（销售经理/SA leader 下级审核 + 签章后）→ 推金蝶销售订单
    #   （销售/应收源，总览 §6.2「SO 审核通过」；EXPLICIT effect，开关默认 OFF 只入 outbox；
    #    幂等键 order_number + company_id）。同步累加备货消单（SO 成交匹配备货型号+意向客户）。
    sales_order_reviewed_kingdee_effect = ["kingdee.enqueue_push", "stockup.consume_on_sales_order"]
    # ★预付到账闸（PRD 05 页面2 验收4）：付款方式=预付（requires_advance_receipt=True）时，
    #   预付到账（advance_receipt_confirmed=True）才放行采购；非预付单直接放行（边级 hard_rule，引擎 04 §4.B）。
    #   到账确认单在财务域 ADVANCE_RECEIPT（confirm effect 回写本标志，TODO：财务确认到账时回写 SO.advance_receipt_confirmed）。
    sales_order_advance_gate_rule = "(not doc.requires_advance_receipt) or doc.advance_receipt_confirmed"
    purchase_notice_sent_effect = ["erp.mark_sales_order_purchase_notice_sent"]
    purchase_notice_to_po_effect = ["erp.create_purchase_order_from_notice"]
    purchase_order_to_goods_receipt_effect = ["wms.create_goods_receipt_from_purchase_order"]
    purchase_order_advance_payment_effect = ["finance.create_advance_payment_from_purchase_order"]
    # 段2b 04a-3：PO 采购审批通过到 ORDERED → 推金蝶采购订单（应付源，07b·EXPLICIT effect，
    # 开关默认 OFF 只入 outbox；幂等键 order_number + company_id）。
    purchase_order_kingdee_effect = ["kingdee.enqueue_push"]
    # 需预付分支：审批通过下单 + 推金蝶 + 派生预付款申请（requires_advance_payment 时走此边）。
    purchase_order_ordered_advance_effect = ["kingdee.enqueue_push", "finance.create_advance_payment_from_purchase_order"]
    goods_receipt_stock_effect = ["wms.stock_goods_receipt"]
    goods_receipt_followup_effect = ["erp.complete_purchase_receipt_followup"]
    # 入库审核通过推金蝶外购/其他入库单（07b·EXPLICIT effect，开关默认 OFF 只入 outbox）。
    goods_receipt_kingdee_effect = ["kingdee.enqueue_push"]
    sales_order_to_shipment_effect = ["wms.create_shipment_from_sales_order"]
    shipment_stock_effect = ["wms.apply_shipment_stock_out"]
    shipment_sales_invoice_effect = ["finance.create_sales_invoice_from_shipment"]
    shipment_sales_return_effect = ["wms.create_sales_return_from_shipment"]
    # 出库扣库存后推金蝶销售出库单（07b·EXPLICIT effect，开关默认 OFF 只入 outbox；幂等键 shipment_number + company_id）。
    shipment_kingdee_effect = ["kingdee.enqueue_push"]
    # 进互检前 hard_rule（DSL，引擎 04 §4.B）：每行须有照片引用（每包拍照留证，PRD 03b 页面2 第5点）。
    # lines = shipment_line 子表行；photo_refs 非空（JSONB 列表）即过。
    shipment_photo_hard_rule = "all(line.photo_refs for line in lines)"
    # 委外直发边守卫（DSL，引擎 04 §4.B）：互检→出库直发边仅限委外发料（绕过财务放行，PRD 03a-9）；
    # 客户发货/调拨出库必须经财务放行边（蓝图 §5.1）。挂在边上（hard_rules 是 next_entry 边级）。
    shipment_outsource_only_hard_rule = 'doc.outbound_type == "OUTSOURCE"'
    # 段2c 04a-7：进项发票 ★FINANCE 审核通过 → 形成应付 + 回写 PO + 推金蝶（应付/进项源，EXPLICIT，
    # 默认 OFF 只入 outbox；幂等键 invoice_number + company_id）。
    purchase_invoice_ap_effect = ["finance.create_accounts_payable_from_purchase_invoice"]
    purchase_invoice_po_effect = ["erp.mark_purchase_order_invoice_matching"]
    purchase_invoice_kingdee_effect = ["kingdee.enqueue_push"]
    # 段2c 04a-8：付款申请到账确认 → 应付余额递减（accounts_payable.paid_amount）+ 推金蝶（应付付款执行源，
    # EXPLICIT，默认 OFF 只入 outbox；幂等键 payment_number + company_id）。本系统只记到账确认，做账在金蝶。
    payment_request_confirm_effect = ["finance.confirm_payment_request_settlement"]
    payment_request_kingdee_effect = ["kingdee.enqueue_push"]
    # 段3b 决策③：销项发票勾稽通过 → 形成应收（accounts_receivable）+ 推金蝶销项/应收
    #   （总览 §6.2；EXPLICIT effect，开关默认 OFF 只入 outbox；幂等键 invoice_number + company_id）。
    sales_invoice_ar_effect = ["finance.create_accounts_receivable_from_sales_invoice", "kingdee.enqueue_push"]

    defs = [
        {
            "doc_type": "SALES_INQUIRY",
            "name": "CRM-客户询价流程",
            "description": "客户询价 -> PM 授权 -> 生成报价单。",
            "group_name": "CRM",
            "states": [
                _start(["SALES_ASSISTANT", "SALES_ENGINEER", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
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
            "description": (
                "段3a 对齐扩（PRD 05 页面6）：报价三方协作定价 + ★PM 门控关卡。\n"
                "草稿 → 待成本（PM/PA 录成本，对销售隐藏）→ ★待报价决策（PM 选报价/不报价）→\n"
                "★待定价（PM 设利润点 profit_point 定卖价 unit_price）→ 已报价 → 客户接受（转 SO）/拒绝/过期。\n"
                "★两个 PM 专属关卡（节点 allowed_roles=[PRODUCT_MANAGER]）：不点报价进不了已报价、没定价进不了已报价。\n"
                "🔒Q18 防火墙：cost/cost_unit（采购成本）对 SALES+SA 隐藏；profit_point/unit_profit_point（利润点）"
                "对 SALES+SA 可见（services/tools.py query+schema 两路，非 schema 层）。"
            ),
            "group_name": "CRM",
            "states": [
                _start(["SALES_ASSISTANT", "SALES", "OPERATIONS"]),
                _state("DRAFT", "制作报价单", ["SALES_ASSISTANT", "SALES", "OPERATIONS"], [
                    {"to": "PENDING_COST", "label": "提交产品部录成本", "editable_fields": quote_draft_fields},
                    {"to": "CANCELLED", "label": "取消报价", "editable_fields": ["notes"]},
                ], description="# 制作报价单\n选客户/型号/币种/有效期/货期/条款 + 阶梯量子表（quote_tier_line）。"),
                # 待成本：PM/PA（产品部）录采购成本（cost/cost_unit，对销售端隐藏，字段防火墙）。
                _state("PENDING_COST", "待成本（产品部录入）", ["PRODUCT_MANAGER", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "PENDING_QUOTE_DECISION", "label": "成本已录提交 PM 决策", "editable_fields": ["cost", "notes"]},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ], description="# 待成本\n产品部/PA 录采购成本（cost / 子表 cost_unit，🔒对销售端隐藏）→ 提交 PM 报价决策。"),
                # ★PM 门控关卡 1：是否报价（节点级 allowed_roles=[PRODUCT_MANAGER]）。不点报价进不了已报价。
                _state("PENDING_QUOTE_DECISION", "★待报价决策（PM 门控）", ["PRODUCT_MANAGER"], [
                    {"to": "PENDING_PRICING", "label": "报价（继续定价）", "editable_fields": ["quote_decision", "report_header", "notes"]},
                    {"to": "CLOSED_NO_QUOTE", "label": "不报价（直接关闭）", "editable_fields": ["quote_decision", "notes"]},
                ], description=(
                    "# ★待报价决策（PM 门控）\nPM 判断是否值得报、用哪个抬头报备（report_header）。\n"
                    "选「报价」→ 进待定价；选「不报价」→ 关闭未报，不流转给销售。"
                )),
                # ★PM 门控关卡 2：定价（节点级 allowed_roles=[PRODUCT_MANAGER]）。没定价进不了已报价。
                _state("PENDING_PRICING", "★待定价（PM 设利润点）", ["PRODUCT_MANAGER"], [
                    {"to": "SENT", "label": "定价完成发送客户", "editable_fields": ["profit_point", "total_amount", "notes"]},
                    {"to": "PENDING_QUOTE_DECISION", "label": "退回重新决策", "editable_fields": ["notes"]},
                ], description=(
                    "# ★待定价（PM）\nPM 据成本+利润点（profit_point / 子表 unit_profit_point）定卖价（unit_price）。\n"
                    "✅利润点对 SALES+SA 可见（Q18，报价决策用）；定完 → 已报价推给销售对客户。"
                )),
                _state("SENT", "已报价（已发客户）", ["SALES_ASSISTANT", "SALES", "OPERATIONS"], [
                    {"to": "CUSTOMER_CONFIRMED", "label": "客户确认", "editable_fields": ["valid_until", "notes"]},
                    {"to": "CUSTOMER_REJECTED", "label": "客户拒绝", "editable_fields": ["notes"]},
                    {"to": "EXPIRED", "label": "报价过期", "editable_fields": ["notes"]},
                ], description="# 已报价\n卖价/利润点锁定（销售看含税卖价 + 利润点，🔒看不到采购成本）→ 报客户。"),
                _state("CUSTOMER_CONFIRMED", "客户已确认", ["SALES_ASSISTANT", "SALES", "OPERATIONS"], [
                    {"to": "SALES_ORDER_CREATED", "label": "生成销售订单", "editable_fields": [], "effects": quote_to_so_effect},
                ]),
                _state("SALES_ORDER_CREATED", "已生成销售订单", [], terminal=True),
                _state("CUSTOMER_REJECTED", "客户已拒绝", [], terminal=True),
                _state("CLOSED_NO_QUOTE", "关闭未报（PM 不报价）", [], terminal=True),
                _state("EXPIRED", "已过期", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "DRAFT", "label": "重新报价", "editable_fields": ["valid_until", "notes"]},
                ], description="# 已过期\nvalid_until 过期 → 可重开回草稿重新报价。"),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            # 段3a 线索（PRD 05 页面3）：售前漏斗第一级。承接「飞书群分派」现状。
            "doc_type": "LEAD",
            "name": "CRM-线索流程",
            "description": (
                "段3a CRM 前段（PRD 05 页面3）：网络/电话咨询登记 → 销售经理分派给销售 → 销售+FAE 跟进 →\n"
                "转商机（EXPLICIT 派生 opportunity 草稿回填客户/产线/干系人）/ 关闭丢失。\n"
                "客户可空（询价先于建档）。★无财务关卡（前段不涉钱货）。LD-YYMM-NNN 月度连号。\n"
                "纯前段不推金蝶。"
            ),
            "group_name": "CRM",
            "states": [
                # 建单取号 LD-YYMM-001（NumberingRule，月度连号）。
                _start(["SALES", "SALES_ASSISTANT", "OPERATIONS"], label="开始登记线索", effects=[NUMBERING_EFFECT]),
                _state("DRAFT", "新建（线索登记）", ["SALES", "SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "ASSIGNED", "label": "提交分派", "editable_fields": lead_fields},
                    {"to": "CLOSED_LOST", "label": "关闭丢失", "editable_fields": ["close_reason", "notes"]},
                ], description="# 新建\n录来源/内容（允许一句话）/客户（可空）/产线/区域。content 非空。"),
                _state("ASSIGNED", "已分派", ["SALES", "SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "FOLLOWING", "label": "开始跟进", "editable_fields": ["assigned_sales_id", "assigned_fae_id", "next_step"]},
                    {"to": "CLOSED_LOST", "label": "关闭丢失", "editable_fields": ["close_reason", "notes"]},
                ], description="# 已分派\n销售经理 @ 分派给某销售（assigned_sales_id 必填）+ 配合 FAE。"),
                _state("FOLLOWING", "跟进中", ["SALES", "SALES_ENGINEER", "OPERATIONS"], [
                    {"to": "CONVERTED", "label": "转商机", "editable_fields": ["next_step", "notes"], "effects": lead_to_opportunity_effect},
                    {"to": "CLOSED_LOST", "label": "关闭丢失", "editable_fields": ["close_reason", "notes"]},
                ], description="# 跟进中\n销售+FAE 跟进、更新下一步。判定可转商机或关闭丢失。"),
                _state("CONVERTED", "已转商机", [], terminal=True),
                _state("CLOSED_LOST", "已关闭丢失", [], terminal=True),
            ],
        },
        {
            # 段3a 商机/项目（PRD 05 页面4）：售前漏斗第二级，核心阶段状态机（科研 vs 光通信分流）。
            "doc_type": "OPPORTUNITY",
            "name": "CRM-商机流程",
            "description": (
                "段3a CRM 前段（PRD 05 页面4）：核心阶段状态机——\n"
                "前期沟通 → 送样 → 小批量 → 批量 → 关闭赢/关闭丢/无进展（可回退前期沟通）。\n"
                "★科研分流：business_unit=RESEARCH 时推进阶段 research_sub_market 必填（hard_rule）；\n"
                "送样推进时 customer_id 必填。干系人=销售(owner_sales_id)+FAE(fae_id)。\n"
                "跟进记录子表 opportunity_followup_line（SubTableEditor 网格）。\n"
                "OPP-YYMM-NNN 月度连号。纯前段不推金蝶（关闭赢仅软信号，SO 在 05b 录）。"
            ),
            "group_name": "CRM",
            "states": [
                # 建单取号 OPP-YYMM-001（NumberingRule，月度连号）。转商机派生时由 effect 经 execute_transition 建。
                _start(["SALES", "SALES_ENGINEER", "OPERATIONS"], first_state="EARLY",
                       label="开始（前期沟通）", effects=[NUMBERING_EFFECT]),
                _state("EARLY", "前期沟通", ["SALES", "SALES_ENGINEER", "OPERATIONS"], [
                    {"to": "SAMPLING", "label": "进入送样",
                     "editable_fields": opportunity_fields,
                     "hard_rules": [opportunity_customer_required_rule, opportunity_research_sub_market_rule]},
                    {"to": "CLOSED_LOST", "label": "关闭丢失", "editable_fields": ["close_reason", "remark"]},
                    {"to": "STALLED", "label": "标记无进展", "editable_fields": ["remark"]},
                ], description="# 前期沟通\n录客户/产线/项目名/型号/事业部/干系人。project_name 非空；进送样需客户+（科研）细分市场。"),
                _state("SAMPLING", "送样", ["SALES", "SALES_ENGINEER", "OPERATIONS"], [
                    {"to": "SMALL_BATCH", "label": "进入小批量",
                     "editable_fields": ["product_model", "research_sub_market", "next_step", "remark"],
                     "hard_rules": [opportunity_research_sub_market_rule]},
                    {"to": "CLOSED_LOST", "label": "关闭丢失", "editable_fields": ["close_reason", "remark"]},
                ], description="# 送样\n科研在此停留更久（FAE 确认规格 → 问供应商 → PM 报价）；可关联样品 SDN（采购模块）。"),
                _state("SMALL_BATCH", "小批量", ["SALES", "SALES_ENGINEER", "OPERATIONS"], [
                    {"to": "MASS", "label": "进入批量", "editable_fields": ["expected_amount", "expected_close_date", "next_step", "remark"]},
                    {"to": "CLOSED_LOST", "label": "关闭丢失", "editable_fields": ["close_reason", "remark"]},
                ], description="# 小批量\n小批量验证；录预期金额/成交日。"),
                _state("MASS", "批量", ["SALES", "OPERATIONS"], [
                    {"to": "CLOSED_WON", "label": "关闭赢", "editable_fields": ["expected_amount", "remark"]},
                    {"to": "CLOSED_LOST", "label": "关闭丢失", "editable_fields": ["close_reason", "remark"]},
                ], description="# 批量\n批量阶段；成交→关闭赢（提示可录 SO，SO 在 05b）。"),
                # 无进展（可回退前期沟通）：解决「没成交也不关闭、忘记了」的烂尾线索。
                _state("STALLED", "无进展", ["SALES", "OPERATIONS"], [
                    {"to": "EARLY", "label": "重新激活", "editable_fields": ["next_step", "remark"]},
                    {"to": "CLOSED_LOST", "label": "关闭丢失", "editable_fields": ["close_reason", "remark"]},
                ], description="# 无进展\n长期无进展 → 可回退前期沟通重新激活，或关闭丢失。"),
                _state("CLOSED_WON", "关闭赢", [], terminal=True),
                _state("CLOSED_LOST", "关闭丢失", [], terminal=True),
            ],
        },
        {
            "doc_type": "SALES_ORDER",
            "name": "ERP-销售订单履约流程",
            "description": "决策①（合同即 SO）：SA 录单 → SA leader 下级审核（签章 + 推金蝶销售订单）"
                           "→ ★预付到账闸（付款方式=预付时须到账才放行采购）→ 采购通知 → 发货通知 → 完成。"
                           "SA leader 下级审核 allowed_roles：现无 SALES_ASSISTANT_LEADER 角色 → 用 OPERATIONS 兜底"
                           "（TODO：甲方确认 SA leader 角色后改 allowed_roles=[SALES_ASSISTANT_LEADER]）。",
            "group_name": "ERP",
            "states": [
                # 建单取号：START 挂 numbering effect → SO 内部订单号月度连号 SO-YYMM-001（决策①）。
                _start(["SALES_ASSISTANT", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
                _state("DRAFT", "SA 录入客户订单", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "SALES_MANAGER_REVIEW", "label": "提交 SA leader 下级审核", "editable_fields": sales_order_fields},
                    {"to": "CANCELLED", "label": "取消订单", "editable_fields": ["notes"]},
                ]),
                # SA leader 下级审核（业务审核关，非财务关）：审核通过签章 + 推金蝶销售订单（决策①/③）。
                # allowed_roles 兜底 OPERATIONS（无 SALES_ASSISTANT_LEADER 角色，TODO 上述）。
                _state("SALES_MANAGER_REVIEW", "SA leader 下级审核（签章）", ["OPERATIONS", "BOSS"], [
                    {"to": "ADVANCE_RECEIPT_REQUIRED", "label": "需要客户预收（签章后）", "editable_fields": ["requires_advance_receipt", "advance_receipt_amount", "signature_status", "signature_party", "contract_attachment_ref", "notes"], "effects": sales_order_advance_receipt_effect + sales_order_reviewed_kingdee_effect},
                    {"to": "READY_FOR_PURCHASE", "label": "无需预收/签章放行采购", "editable_fields": ["signature_status", "signature_party", "contract_attachment_ref", "notes"], "effects": sales_order_reviewed_kingdee_effect},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                # ★预付到账闸：付款方式=预付（requires_advance_receipt）时，advance_receipt_confirmed 才放行采购
                #   （边级 hard_rule）；非预付单不受阻。到账确认在财务域 ADVANCE_RECEIPT。
                _state("ADVANCE_RECEIPT_REQUIRED", "待客户预收（★到账闸）", ["FINANCE", "SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "READY_FOR_PURCHASE", "label": "预收已到账放行采购", "editable_fields": ["advance_receipt_confirmed", "notes"], "hard_rules": [sales_order_advance_gate_rule]},
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
            "description": "SA 发起采购通知（或 PA 手建）-> PA 接收 -> 生成采购订单。"
                           "SO 审核派生 effect 待段3 SO 就绪后接（register_transition_effect SALES_ORDER 审核→本单）。",
            "group_name": "ERP",
            "states": [
                # 04a-5：PA/SA 均可经 execute_transition 手建采购通知（PA 缺 SO 时直接录需求）。
                _start(["SALES_ASSISTANT", "PRODUCT_ASSISTANT", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
                _state("DRAFT", "SA/PA 发起采购通知", ["SALES_ASSISTANT", "PRODUCT_ASSISTANT", "OPERATIONS"], [
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
            # 04a-2 对原厂询价登记：PA 据内部询价向 1~N 家原厂询价，记录原厂报价。
            # 子表 supplier_inquiry_line 自动渲为 SubTableEditor 网格（一单多供应商报价行）。
            "doc_type": "SUPPLIER_INQUIRY",
            "name": "采购-对原厂询价流程",
            "description": "PA 据内部询价向原厂询价 -> 已回价 -> 已采用 -> 关闭。"
                           "🔒进价（unit_price/commission）对销售端 SALES+SA 隐藏（Q18 字段防火墙）。",
            "group_name": "采购",
            "states": [
                _start(["PRODUCT_ASSISTANT", "PRODUCT_MANAGER", "OPERATIONS"], first_state="INQUIRING",
                       label="开始对原厂询价", effects=[NUMBERING_EFFECT]),
                _state("INQUIRING", "询价中", ["PRODUCT_ASSISTANT", "PRODUCT_MANAGER", "OPERATIONS"], [
                    {"to": "QUOTED", "label": "原厂已回价", "editable_fields": supplier_inquiry_fields},
                    {"to": "CLOSED", "label": "关闭询价", "editable_fields": ["notes"]},
                ], description="# 询价中\n录原厂/供应商、关联内部询价；子表逐行录型号/对原厂单价/数量/货期/条款。"),
                _state("QUOTED", "已回价", ["PRODUCT_ASSISTANT", "PRODUCT_MANAGER", "OPERATIONS"], [
                    {"to": "ADOPTED", "label": "采用此报价", "editable_fields": supplier_inquiry_quote_fields},
                    {"to": "CLOSED", "label": "关闭询价", "editable_fields": ["notes"]},
                ], description="# 已回价\n原厂回价后逐行补 unit_price/lead_time/terms（子表）；可采用或关闭。"),
                _state("ADOPTED", "已采用", ["PRODUCT_ASSISTANT", "PRODUCT_MANAGER", "OPERATIONS"], [
                    {"to": "CLOSED", "label": "关闭", "editable_fields": ["notes"]},
                ], description="# 已采用\n被 PO 或对客户报价引用后置位；供报价单引用最低价/采用价。"),
                _state("CLOSED", "已关闭", [], terminal=True),
            ],
        },
        {
            "doc_type": "PURCHASE_ORDER",
            "name": "采购-采购订单主链流程",
            "description": "段2b 04a-3 聚焦主链（重构自 K3 镜像大流程，蓝图 §5.1 ★财务采购审批）："
                           "PA 录单 DRAFT → PA 提交 PENDING_APPROVAL → ★财务采购审批 FINANCE_APPROVAL"
                           "（allowed_roles=[FINANCE]，凡涉钱货出公司必财务审）→ 已下单 ORDERED"
                           "（推金蝶采购订单+导出发原厂；requires_advance_payment 时派生预付款申请）"
                           "→ 部分到货 PARTIAL / 已到货 RECEIVED（入库 effect 回填 received_quantity 消在途）→ 关闭 CLOSED。"
                           "入库/质检/发票/应付已移出本流程：入库=GOODS_RECEIPT（经 purchase_order_id 关联回填）、"
                           "发票=PURCHASE_INVOICE（04a-7 独立流程）。"
                           "🔒Q18：PO 头买价（total_amount/advance_payment_amount/stock_amount_*）+ 行（unit_price/total_price）"
                           "对销售端 SALES+SA 隐藏（字段防火墙）。",
            "group_name": "采购",
            "states": [
                # 建单取号：START 挂 numbering effect，建单后同事务内取 PO 月度连号（PO-YYMM-001）。
                _start(["PRODUCT_ASSISTANT", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
                _state("DRAFT", "PA 录入采购订单", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "PENDING_APPROVAL", "label": "提交采购审批", "editable_fields": purchase_order_fields},
                    {"to": "CANCELLED", "label": "取消采购", "editable_fields": ["notes"]},
                ], description="# PA 录入采购订单\n"
                               "选供应商、按该供应商维度产品代码逐行录型号/数量/单价（手录可改）；"
                               "填报备 end-customer（PM 定可≠销售客户）、原厂 SO#、是否备货、是否预付。行数量≠0。"),
                # 待采购审批：PA 提交后在此等待，由 PA/运营正式递交财务审批（进入 ★FINANCE 节点）。
                _state("PENDING_APPROVAL", "待采购审批", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "FINANCE_APPROVAL", "label": "递交财务采购审批", "editable_fields": ["notes"]},
                    {"to": "DRAFT", "label": "撤回修改", "editable_fields": ["notes"]},
                    {"to": "CANCELLED", "label": "取消采购", "editable_fields": ["notes"]},
                ], description="# 待采购审批\n提交即冻结金额，递交财务采购审批（蓝图 §5.1 ★）。"),
                # ★财务采购审批（蓝图 §5.1）：FINANCE 审，凡涉钱货出公司必经此关。
                _state("FINANCE_APPROVAL", "★财务采购审批", ["FINANCE"], [
                    {"to": "ORDERED", "label": "审核通过并下单", "editable_fields": ["expected_delivery_date", "notes"], "effects": purchase_order_kingdee_effect},
                    {"to": "ORDERED", "label": "审核通过并下单（需预付）", "editable_fields": ["expected_delivery_date", "requires_advance_payment", "advance_payment_amount", "notes"], "effects": purchase_order_ordered_advance_effect},
                    {"to": "REJECTED", "label": "驳回", "editable_fields": ["notes"]},
                ], description="# ★财务采购审批（FINANCE）\n"
                               "财务采购审批（蓝图 §5.1）。通过→已下单 ORDERED：推金蝶采购订单（应付源，默认 OFF 只入 outbox）+ 导出发原厂；"
                               "requires_advance_payment 时走「需预付」边派生预付款申请。驳回→退回改单。"),
                _state("ORDERED", "已下单待到货", ["LOGISTICS", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    # 入库派生（PO→GOODS_RECEIPT，经 purchase_order_id 关联，入库审核后回填 received_quantity 消在途）。
                    {"to": "PARTIAL", "label": "部分到货", "editable_fields": ["actual_delivery_date", "notes"], "effects": purchase_order_to_goods_receipt_effect},
                    {"to": "RECEIVED", "label": "已全部到货", "editable_fields": ["actual_delivery_date", "notes"], "effects": purchase_order_to_goods_receipt_effect},
                    {"to": "CANCELLED", "label": "取消采购", "editable_fields": ["notes"]},
                ], description="# 已下单待到货\n已推金蝶（应付源）+ 导出发原厂。货期跟踪进采购在途台账（04a-6，段2c）。"),
                _state("PARTIAL", "部分到货", ["LOGISTICS", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "RECEIVED", "label": "剩余到货", "editable_fields": ["actual_delivery_date", "notes"]},
                ], description="# 部分到货\n入库审核回填 received_quantity 消在途；全部行 received≥订单后转已到货。"),
                _state("RECEIVED", "已到货", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "CLOSED", "label": "关闭采购订单", "editable_fields": ["notes"]},
                ], description="# 已到货\n全部行 received≥订单数量；进项发票走 PURCHASE_INVOICE 独立流程（04a-7）。"),
                _state("CLOSED", "已关闭", [], terminal=True),
                _state("REJECTED", "已驳回", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "DRAFT", "label": "退回改单", "editable_fields": ["notes"]},
                ], description="# 已驳回\n财务驳回，退回 DRAFT 改单。"),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "GOODS_RECEIPT",
            "name": "WMS-采购收货入库流程",
            "description": "仓库收货 -> PA 审核 -> 库存入库。",
            "group_name": "WMS",
            "states": [
                _start(["LOGISTICS", "OPERATIONS"], first_state="PENDING", label="开始收货录入", effects=[NUMBERING_EFFECT]),
                _state("PENDING", "仓库收货录入", ["LOGISTICS", "OPERATIONS"], [
                    {"to": "PA_REVIEW", "label": "提交 PA 审核", "editable_fields": goods_receipt_fields},
                    {"to": "CANCELLED", "label": "取消入库", "editable_fields": ["notes"]},
                ]),
                _state("PA_REVIEW", "PA 审核入库单", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "STOCKED_IN", "label": "审核通过入库", "editable_fields": ["notes"], "effects": goods_receipt_stock_effect + goods_receipt_followup_effect + goods_receipt_kingdee_effect},
                    {"to": "PENDING", "label": "退回仓库修改", "editable_fields": ["notes"]},
                ]),
                _state("STOCKED_IN", "已入库", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "SHIPMENT",
            "name": "WMS-发货出库流程",
            "description": "发货通知 -> 分箱拣货拍照 -> 仓库互检★ -> 财务放行★ -> 出库扣库存推金蝶 -> 客户签收。"
                           "（业务序：拣货→互检→财务放行→出库；委外发料绕过财务放行直发，03a-9）",
            "group_name": "WMS",
            "states": [
                _start(["SALES_ASSISTANT", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
                _state("DRAFT", "SA 发布发货通知", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "PACKING_LABELING", "label": "提交物流分箱拣货", "editable_fields": shipment_fields},
                    {"to": "CANCELLED", "label": "取消发货", "editable_fields": ["notes"]},
                ]),
                _state("PACKING_LABELING", "包装与制标", ["LOGISTICS", "OPERATIONS"], [
                    # 进互检前 hard_rule：每行须有照片引用（每包拍照留证，PRD 03b 页面2 验收④）。
                    {"to": "PICKING_RECHECK", "label": "完成制标提交互检", "editable_fields": ["label_status", "inspection_status", "tracking_number", "carton_number", "photo_refs", "notes"], "hard_rules": [shipment_photo_hard_rule]},  # noqa: E501
                ]),
                _state("PICKING_RECHECK", "仓库互检（出库复核）★", ["LOGISTICS", "OPERATIONS"], [
                    # 互检可同一人复核（甲方 Q7，效率优先）：不校验复核人≠制单人，仅留痕。通过→财务放行。
                    {"to": "FINANCE_APPROVAL", "label": "互检通过提交财务放行", "editable_fields": ["inspection_status", "notes"]},
                    {"to": "PACKING_LABELING", "label": "互检退回重做", "editable_fields": ["notes"]},
                    # 委外发料绕过客户发货财务放行边：发料对象=委外方非客户，直发出库（03a-9）；边 hard_rule 限 outbound_type=OUTSOURCE。
                    {"to": "SALES_OUTBOUND", "label": "委外发料直接发出", "editable_fields": ["shipped_date", "tracking_number", "notes"], "effects": shipment_stock_effect + shipment_kingdee_effect, "hard_rules": [shipment_outsource_only_hard_rule]},
                ]),
                _state("FINANCE_APPROVAL", "财务放行★", ["FINANCE", "OPERATIONS", "BOSS"], [
                    # 财务未放行货坚决不出仓（蓝图 §5.1）。放行→出库扣库存+生成销售发票+推金蝶。
                    {"to": "SALES_OUTBOUND", "label": "财务放行出库", "editable_fields": ["approved_by_id", "shipped_date", "tracking_number", "notes"], "effects": shipment_stock_effect + shipment_sales_invoice_effect + shipment_kingdee_effect},
                    {"to": "EXCEPTION_APPROVAL", "label": "超额/超期审批", "editable_fields": ["notes"]},
                ]),
                _state("EXCEPTION_APPROVAL", "例外审批", ["BOSS", "OPERATIONS"], [
                    {"to": "SALES_OUTBOUND", "label": "特批放行出库", "editable_fields": ["approved_by_id", "shipped_date", "notes"], "effects": shipment_stock_effect + shipment_sales_invoice_effect + shipment_kingdee_effect},
                    {"to": "CANCELLED", "label": "驳回发货", "editable_fields": ["notes"]},
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
            "name": "ERP-进项发票审核流程",
            "description": (
                "04a-7 进项发票录入 → ★FINANCE 审核 → 形成应付：\n"
                "PA 收到原厂 invoice 录单（必关联 PO + 入库单，无入库不能录）→ 提交 PENDING_REVIEW\n"
                "→ ★进项发票审核（allowed_roles=[FINANCE]，财务核发票号/金额/与入库一致）→ AP_CREATED\n"
                "（形成应付 + 回写 PO + 推金蝶应付/进项源）。这是 PA 在采购端的最后一步。"
            ),
            "group_name": "ERP",
            "states": [
                # 建单取号 PI-YYMM-001（NumberingRule，月度连号）。
                _start(["FINANCE", "PRODUCT_ASSISTANT", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
                _state("DRAFT", "登记采购发票", ["FINANCE", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "PENDING_REVIEW", "label": "提交财务审核", "editable_fields": ["invoice_number", "supplier_id", "purchase_order_id", "goods_receipt_id", "amount", "currency", "tax_rate", "invoice_date", "due_date", "notes"]},
                    {"to": "CANCELLED", "label": "取消发票", "editable_fields": ["notes"]},
                ]),
                # ★进项发票审核硬关卡（蓝图 §5.1 五关卡之一）：仅 FINANCE 可推进（节点级 allowed_roles）。
                _state("PENDING_REVIEW", "★进项发票审核（财务）", ["FINANCE"], [
                    {"to": "AP_CREATED", "label": "审核通过并生成应付", "editable_fields": ["reviewed_by_id", "reviewed_at", "notes"], "effects": purchase_invoice_ap_effect + purchase_invoice_po_effect + purchase_invoice_kingdee_effect},
                    {"to": "DRAFT", "label": "驳回退回修改", "editable_fields": ["notes"]},
                ], description="# ★进项发票审核\n财务核对发票号/金额/与入库实收一致 → 形成应付 + 推金蝶；驳回退 DRAFT。"),
                _state("AP_CREATED", "已生成应付", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "PAYMENT_REQUEST",
            "name": "ERP-付款申请流程",
            "description": (
                "04a-8 付款申请（货后付款，决策④：发起在采购、执行在财务）：\n"
                "PA 发起（关联已审进项发票 / PO，金额≤应付余额）→ 提交 PENDING_FINANCE\n"
                "→ ★FINANCE 执行（做账/打款在金蝶）→ PAID → 到账确认 CONFIRMED\n"
                "（confirmed 标记 + 应付余额递减；本系统只记到账确认，做账在金蝶）。"
            ),
            "group_name": "ERP",
            "states": [
                # 建单取号 PAY-YYMM-001（NumberingRule，月度连号）。
                _start(["PRODUCT_ASSISTANT", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
                _state("DRAFT", "PA 发起付款申请", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "PENDING_FINANCE", "label": "提交财务执行", "editable_fields": ["payment_number", "payment_type", "supplier_id", "purchase_order_id", "purchase_invoice_id", "requested_by_id", "payee_name", "bank_account", "amount", "currency", "due_date", "notes"]},
                    {"to": "CANCELLED", "label": "取消申请", "editable_fields": ["notes"]},
                ]),
                # ★财务执行硬关卡：仅 FINANCE 可推进（节点级 allowed_roles）；执行=打款做账在金蝶。
                _state("PENDING_FINANCE", "★财务执行付款（财务）", ["FINANCE"], [
                    {"to": "PAID", "label": "财务执行付款", "editable_fields": ["approved_by_id", "payment_date", "notes"], "effects": payment_request_kingdee_effect},
                    {"to": "DRAFT", "label": "驳回退回修改", "editable_fields": ["notes"]},
                ], description="# ★财务执行付款\n财务执行打款（做账在金蝶）+ 推金蝶应付付款执行源；驳回退 DRAFT。"),
                _state("PAID", "已付款待确认", ["FINANCE", "OPERATIONS"], [
                    # confirmed 标记由 confirm effect 置（不放进 editable_fields）：effect 守卫 confirmed 幂等，
                    # 同事务内置标记 + 递减应付（field_updates 先于 effects 执行，放白名单会让守卫误判已确认）。
                    {"to": "CONFIRMED", "label": "确认到账", "editable_fields": ["payment_date", "notes"], "effects": payment_request_confirm_effect},
                ], description="# 已付款\n财务打款后等到账回单 → 确认到账 + 台账应付递减（决策④只记到账确认）。"),
                _state("CONFIRMED", "已确认到账", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "SALES_INVOICE",
            "name": "ERP-销售发票勾稽流程",
            "description": "销售发票 -> 销售出库勾稽 -> 应收账款/销售成本。",
            "group_name": "ERP",
            "states": [
                _start(["FINANCE", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
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
                _start(["SALES_ASSISTANT", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
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
        {
            "doc_type": "STOCK_TRANSFER",
            "name": "WMS-调拨单流程（仅同公司内仓间）",
            "description": "选源批次+目标库位 -> ★主任复核 -> 调拨完成（源库位减、目标库位加，写两条流水）。"
                           "绝不跨公司（源/目标库位 company 必须相同，hard_rule + validator 双保险）；默认不推金蝶。",
            "group_name": "WMS",
            "states": [
                _start(["LOGISTICS", "LOGISTICS_LEAD", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
                _state("DRAFT", "录入调拨单", ["LOGISTICS", "LOGISTICS_LEAD", "OPERATIONS"], [
                    {"to": "REVIEW", "label": "提交主任复核", "editable_fields": stock_transfer_fields},
                    {"to": "CANCELLED", "label": "取消调拨", "editable_fields": ["notes"]},
                ], description="# 录入调拨单\n选源批次（入仓编号）+ 目标库位，填调拨数量（≤结存）。调拨不改 SN/LOT/原厂报备客户，仅改库位。"),
                _state("REVIEW", "主任复核", ["LOGISTICS_LEAD", "OPERATIONS"], [
                    # 同公司 hard_rule（lookup DSL）+ 完成 AUTO effect（移库位 + 两条 TRANSFER 流水）。
                    {"to": "DONE", "label": "复核通过完成调拨", "editable_fields": ["notes"], "effects": stock_transfer_done_effect, "hard_rules": [stock_transfer_same_company_hard_rule]},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                _state("DONE", "调拨完成", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "STOCK_ADJUSTMENT",
            "name": "WMS-库存调整单流程（盘点差异→推金蝶）",
            "description": "盘点差异落账单：由盘点 review 派生草稿 -> 财务核差异原因（每行必填）-> 过账"
                           "（按差异调 inventory.quantity + 写 COUNT_ADJUST 流水 + 推金蝶库存调整单，默认 OFF）。",
            "group_name": "WMS",
            "states": [
                _start(["LOGISTICS_LEAD", "FINANCE", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
                _state("DRAFT", "录入库存调整单", ["LOGISTICS_LEAD", "FINANCE", "OPERATIONS"], [
                    {"to": "CONFIRM", "label": "提交财务确认", "editable_fields": stock_adjustment_fields},
                    {"to": "CANCELLED", "label": "取消调整", "editable_fields": ["notes"]},
                ], description="# 录入库存调整单\n一般由盘点 review 派生（generate_stock_adjustment_from_count）；逐行核差异原因。"),
                _state("CONFIRM", "财务确认差异原因", ["FINANCE", "OPERATIONS"], [
                    # 每行差异原因必填（hard_rule）；确认过账 → 调结存 + COUNT_ADJUST 流水 + 推金蝶。
                    {"to": "POSTED", "label": "确认过账并推金蝶", "editable_fields": ["notes"], "effects": stock_adjustment_post_effect, "hard_rules": [stock_adjustment_reason_hard_rule]},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                _state("POSTED", "已过账", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "STOCK_UP_REQUEST",
            "name": "采购-备货申请流程",
            "description": (
                "04b-1 备货申请（StockUpRequest，销售/PM 提议囤货，谁提议谁担风险）：\n"
                "DRAFT 录型号/备货数量/意向客户/欠款/风险/金额（建单 START 取号 SU-YYMM-001\n"
                "+ 拍当时库存/在途快照）→ 金额阈值分流（边级 hard_rules）：\n"
                "  <20万 → PENDING_PM（PM/PD 单批）→ APPROVED；\n"
                "  ★≥20万 → PENDING_REVIEW（PM+FINANCE 并行会签，集齐 AGREE 才放行，任一驳回打回）→ APPROVED。\n"
                "APPROVED → PA 据此下正式 PO → TRACKING（消单中，原始数量不变、consumed 随 SO 累加）→ CLOSED。\n"
                "未通过 → REJECTED；可 CANCELLED。备货申请单本身不推金蝶（内部决策单），批后下的 PO 才推。"
            ),
            "group_name": "ERP",
            "states": [
                # 建单取号 SU-YYMM-001（NumberingRule）；snapshot 快照 effect 自动在 START 触发（auto=True）。
                _start(["SALES", "PRODUCT_MANAGER", "OPERATIONS"], effects=[NUMBERING_EFFECT]),
                _state("DRAFT", "备货申请录入", ["SALES", "PRODUCT_MANAGER", "OPERATIONS"], [
                    # 金额阈值分流：边级 hard_rules 自动选边（<20万 PM 单批 / ≥20万会审）。
                    {"to": "PENDING_PM", "label": "提交 PM 单批（<20万）", "editable_fields": stock_up_request_fields,
                     "hard_rules": [stock_up_under_threshold_rule]},
                    {"to": "PENDING_REVIEW", "label": "提交备货会审（≥20万）", "editable_fields": stock_up_request_fields,
                     "hard_rules": [stock_up_over_threshold_rule]},
                    {"to": "CANCELLED", "label": "取消申请", "editable_fields": ["notes"]},
                ], description=(
                    "# 备货申请录入\n填型号/备货数量/意向客户/签单公司/欠款/原因/风险点/金额；"
                    "风险点/金额/意向客户必填才能提交。系统自动带当时库存+在途快照。\n"
                    "金额 <20万 走 PM/PD 单批；★≥20万 走备货会审（PM+FINANCE 都签）。"
                )),
                # <20万 单批：仅 PM/PD（节点级 allowed_roles=[PRODUCT_MANAGER]）。
                _state("PENDING_PM", "PM 单批（<20万）", ["PRODUCT_MANAGER"], [
                    {"to": "APPROVED", "label": "PM 批准", "editable_fields": ["notes"]},
                    {"to": "REJECTED", "label": "驳回", "editable_fields": ["notes"]},
                ], description="# PM/PD 单批\n金额<20万由直属领导单批；批了即可下单（访谈 07:2196）。"),
                # ★≥20万会审：PM+FINANCE 并行会签（cosign 标准件）。节点 allowed_roles 含两方都能进来推进，
                # 但「放行」由 cosign.stock_up_review 校验器把关：集齐 PM+FINANCE AGREE 才过 APPROVED，
                # 任一 REJECT 打回（cosign_failures）。进态时 stockup.open_review_cosign 预生成两行待签。
                _state("PENDING_REVIEW", "★备货会审（PM+FINANCE 会签）", ["PRODUCT_MANAGER", "FINANCE"], [
                    {"to": "APPROVED", "label": "会审通过（集齐 PM+FINANCE 签）", "editable_fields": ["draft_po_id", "notes"]},
                    {"to": "REJECTED", "label": "会审驳回", "editable_fields": ["notes"]},
                ], description=(
                    "# ★备货会审（≥20万）\nPM+FINANCE 并行会签（各往自己那行 sign_cosign 填同意/驳回）；"
                    "集齐两方同意才放行 APPROVED，任一驳回整单打回（财务关注欠款/资金占用）。"
                )),
                # 批准 → PA 据此下正式 PO（PO 主流程在 04a），进消单跟踪。
                _state("APPROVED", "已批准待下单", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "TRACKING", "label": "已下 PO 进入消单跟踪", "editable_fields": ["draft_po_id", "notes"]},
                ], description="# 已批准\nPA 据此下正式 PO（是否备货=是、关联销售订单空）→ 进入消单跟踪。"),
                # 消单中：consumed_quantity 由 SO 成交消单派生（段3 自动 effect，本段留接口；PA 可手动录）。
                _state("TRACKING", "消单跟踪中", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "CLOSED", "label": "已消化完毕关闭", "editable_fields": ["notes"]},
                    {"to": "CANCELLED", "label": "撤销备货", "editable_fields": ["notes"]},
                ], description=(
                    "# 消单跟踪\n原始备货数量不变，consumed_quantity 随匹配 SO 累加（段3 派生）；"
                    "剩余=备货数量-已消，挂太久持续提醒。已消=备货数量 → 关闭。"
                )),
                _state("CLOSED", "已关闭", [], terminal=True),
                _state("REJECTED", "已驳回", [], terminal=True),
                _state("CANCELLED", "已取消", [], terminal=True),
            ],
        },
        {
            "doc_type": "SAMPLE_SDN",
            "name": "采购-样品 SDN 流程",
            "description": (
                "04b-3 样品 SDN（向原厂申请免费/收费样品，走其他入库进样品仓，跟回签/超期/转正）：\n"
                "REQUESTED 录申请（建单 START 取号 SDN-{C/L}-YYMM-NNN，supplier_line 拼线字母）→\n"
                "VENDOR_SHIPPED（原厂发货，录 tracking）→ STOCKED_SAMPLE（其他入库进样品仓，库存=SAMPLE）→\n"
                "SENT_TO_CUSTOMER（寄客户，超期未签触发提醒）→ SIGNED（回签）→ TESTING（PM/销售跟测试）→\n"
                "  CONVERTED（测试通过转正：该批库存 SAMPLE→AVAILABLE，code 建好可下正式单）→ CLOSED；\n"
                "  RETURNED（需归还已还）/ CLOSED 终态。target_price 对 SALES 遮蔽（字段防火墙 §00-8）。"
            ),
            "group_name": "ERP",
            "states": [
                # 建单取号 SDN-{C/L}-YYMM-NNN（sample.assign_sdn_number 在 START 拼线字母，见 phase1_effects）。
                _start(["SALES", "PRODUCT_MANAGER", "PRODUCT_ASSISTANT", "OPERATIONS"], first_state="REQUESTED",
                       effects=["sample.assign_sdn_number"]),
                _state("REQUESTED", "样品申请录入", ["SALES", "PRODUCT_MANAGER", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "VENDOR_SHIPPED", "label": "原厂已发货", "editable_fields": sample_sdn_request_fields},
                    {"to": "CLOSED", "label": "作废", "editable_fields": ["remark"]},
                ], description=(
                    "# 样品申请录入\n销售发起→PM 定用哪个客户身份申请→PA 向原厂申请（数量少、多免费）。\n"
                    "录供应商/线字母(C/L)/客户/样品性质/目标价/子表型号数量；建单自动取 SDN 号。"
                )),
                _state("VENDOR_SHIPPED", "原厂已发货", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "STOCKED_SAMPLE", "label": "已入样品仓", "editable_fields": ["tracking", "remark"]},
                ], description="# 原厂已发货\n原厂随其他货发来、无 PO 号；物流按「无 PO+量少」判为样品。"),
                _state("STOCKED_SAMPLE", "样品仓在库", ["PRODUCT_ASSISTANT", "LOGISTICS", "OPERATIONS"], [
                    {"to": "SENT_TO_CUSTOMER", "label": "已寄客户", "editable_fields": ["tracking", "remark"]},
                ], description="# 样品仓在库\n走其他入库[样品] 进样品仓，库存状态=SAMPLE（不可售，§5.4 / 03）。"),
                _state("SENT_TO_CUSTOMER", "已寄客户", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "SIGNED", "label": "客户已回签", "editable_fields": ["signed_return", "tracking", "remark"]},
                ], description=(
                    "# 已寄客户\nPA 寄样品给客户、记 tracking；跟回签（signed_return）。\n"
                    "超期未签（overdue_basis_date 起算）触发催归还提醒（list_user_todos + 定时任务）。"
                )),
                _state("SIGNED", "已回签", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "TESTING", "label": "进入测试跟进", "editable_fields": ["signed_return", "remark"]},
                ], description="# 已回签\n记客户侧 SN/LOT（原厂也要管控）；进测试跟进。"),
                _state("TESTING", "测试跟进中", ["PRODUCT_MANAGER", "SALES", "PRODUCT_ASSISTANT"], [
                    {"to": "CONVERTED", "label": "测试通过转正", "editable_fields": ["project_status", "remark"],
                     "effects": sample_sdn_convert_effect},
                    {"to": "RETURNED", "label": "需归还已还", "editable_fields": ["paid_disposition", "signed_return", "remark"]},
                    {"to": "CLOSED", "label": "测试失败/作废", "editable_fields": ["project_status", "remark"]},
                ], description=(
                    "# 测试跟进\nPM 跟销售沟通测试情况（在测/通过/失败）。\n"
                    "通过→转正（该批库存 SAMPLE→AVAILABLE，可下正式单）；需归还→已还；失败→作废。"
                )),
                _state("CONVERTED", "已转正", ["PRODUCT_MANAGER", "OPERATIONS"], [
                    {"to": "CLOSED", "label": "关闭", "editable_fields": ["remark"]},
                ], description="# 已转正\ncode 建好→客户可下正式单；该批库存已转 AVAILABLE 可售（§5.4）。"),
                _state("RETURNED", "已归还", [], terminal=True),
                _state("CLOSED", "已关闭", [], terminal=True),
            ],
        },
        {
            "doc_type": "RMA",
            "name": "采购-RMA 退货统一单",
            "description": (
                "04b-5/04b-6 RMA 退货统一单（一张统一单共用 RMA 号，SA/PA 双视图，决策⑨ 字段防火墙）：\n"
                "REPORTED(SA 录客户报修)→ PA_VERIFY(PA 核料：sold_by_us 倒查 SN/PO/出库 + under_warranty 算过保，\n"
                "  非我方卖/过保→REJECTED；成立→上报)→ ESCALATED_PM(PM 决策：报原厂 VENDOR / 内部消化 INTERNAL)→\n"
                "  VENDOR_RMA(PA 对接原厂，回填原厂 RMA 号，跨境走退关 180 天)/ INTERNAL(商务停富泰)→\n"
                "  GOODS_RETURNED(货回入库带 source_marker，好货 AVAILABLE 混回可售)→ RETURN_TO_CUSTOMER(SA 退客户)→\n"
                "  CLOSED；REJECTED 终态。节点级 allowed_roles 分 SA/PA/PM 控权（规避 D-02e 边级坑）。\n"
                "★对 SA(SALES_ASSISTANT)+SALES 遮蔽采购侧列（supplier_id/po_number/unit_price/supplier_rma_number，"
                "tools.py query+schema 两路）。"
            ),
            "group_name": "ERP",
            "states": [
                # 建单取号 RMA-YYMM-NNN（标准 numbering effect）。SA 报修即建。
                _start(["SALES_ASSISTANT", "SALES", "OPERATIONS"], first_state="REPORTED",
                       effects=[NUMBERING_EFFECT]),
                _state("REPORTED", "客户报修", ["SALES_ASSISTANT", "SALES", "OPERATIONS"], [
                    {"to": "PA_VERIFY", "label": "转 PA 核料", "editable_fields": rma_reported_fields},
                ], description=(
                    "# 客户报修（SA 视图）\n客户先联系 CC/销售报某批货有问题；SA 录客户/型号/SN/失效描述/失效位置。\n"
                    "销售对客户、不对原厂（采购侧列对 SA 遮蔽，决策⑨）。"
                )),
                # PA 核料（节点级 allowed_roles=[PRODUCT_ASSISTANT]）：核 SN/LOT+PO+出库 + 算过保。
                _state("PA_VERIFY", "PA 核料判定", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "ESCALATED_PM", "label": "成立上报 PM", "editable_fields": rma_verify_fields,
                     "effects": rma_verify_effect},
                    {"to": "REJECTED", "label": "非我方卖/过保→驳回", "editable_fields": rma_verify_fields},
                ], description=(
                    "# PA 核料（PA 视图）\n凭 SN/LOT+PO+入库倒查「是否我方卖、哪个供应商、是否过保」（core 料判定 effect 自动给建议）。\n"
                    "非我方卖（客户多渠道拿货）/ 过保 → 不收不成立（REJECTED）；成立 → 上报 PM。"
                )),
                # PM 决策（节点级 allowed_roles=[PRODUCT_MANAGER]）。
                _state("ESCALATED_PM", "上报 PM 决策", ["PRODUCT_MANAGER", "OPERATIONS"], [
                    {"to": "VENDOR_RMA", "label": "报原厂（换/退/修）", "editable_fields": rma_pm_fields},
                    {"to": "INTERNAL", "label": "内部消化", "editable_fields": rma_pm_fields},
                ], description=(
                    "# 上报 PM 决策（决策⑨核心）\nPM 决定报原厂（原厂确认接受→换/退/修）或内部消化（商务停富泰）。"
                )),
                _state("VENDOR_RMA", "对接原厂", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "GOODS_RETURNED", "label": "货已回到仓", "editable_fields": rma_vendor_fields},
                ], description=(
                    "# 对接原厂（PA 视图）\n原厂发商务邮件确认接受→回填原厂 RMA 号；跨境走退关（海关审批后 180 天内回）。"
                )),
                _state("INTERNAL", "内部消化", ["PRODUCT_ASSISTANT", "SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "GOODS_RETURNED", "label": "货已回到仓", "editable_fields": ["remark"]},
                    {"to": "RETURN_TO_CUSTOMER", "label": "直接退换客户", "editable_fields": ["remark"]},
                ], description="# 内部消化\n公司内部跟客户做退换，商务流程停留富泰。"),
                # 货回入库（PA/LOGISTICS）：走退货入库带 source_marker，好货 AVAILABLE 混回可售。
                _state("GOODS_RETURNED", "货回入库", ["PRODUCT_ASSISTANT", "LOGISTICS", "OPERATIONS"], [
                    {"to": "RETURN_TO_CUSTOMER", "label": "退客户", "editable_fields": ["remark"],
                     "effects": rma_goods_returned_effect},
                ], description=(
                    "# 货回入库\n原厂换回/客户退回的货回仓，走退货入库（inbound_type=RETURN）带 source_marker\n"
                    "（RMA来源+品质好坏+原厂，§5.4）；好货 status=AVAILABLE 混回可售、坏货报废/返原厂。"
                )),
                # 退客户（节点级 allowed_roles=[SALES_ASSISTANT]，回到 SA 客户侧）。
                _state("RETURN_TO_CUSTOMER", "退客户", ["SALES_ASSISTANT", "SALES", "OPERATIONS"], [
                    {"to": "CLOSED", "label": "已退客户关闭", "editable_fields": ["tracking", "remark"]},
                ], description="# 退客户（SA 视图）\n货回来后告诉对应 SA 退/换给客户；退完 PA/SA 关闭 RMA。"),
                _state("CLOSED", "已关闭", [], terminal=True),
                _state("REJECTED", "已驳回", [], terminal=True),
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
