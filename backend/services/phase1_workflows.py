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


def _state(code, name, roles, next_list=None, terminal=False, description="", hooks=None):
    state = {
        "code": code,
        "name": name,
        "allowed_roles": roles,
        "description": description,
        "custom_html": "",
        "hard_rules": [],
        "hooks": hooks or [],
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

    inquiry_to_quote_hook = [
        "q = insert('quotation', {\n"
        "    'quotation_number': 'QT-I' + str(doc.id),\n"
        "    'inquiry_id': doc.id,\n"
        "    'customer_id': doc.customer_id,\n"
        "    'sales_assistant_id': doc.sales_assistant_id,\n"
        "    'product_manager_id': doc.product_manager_id,\n"
        "    'currency': doc.currency,\n"
        "    'total_amount': sum(float(line.quantity) * float(line.target_unit_price or 0) for line in lines),\n"
        "    'payment_terms_days': 30,\n"
        "    'shipping_method': 'FOB',\n"
        "    'delivery_address': doc.delivery_address,\n"
        "    'packaging_requirements': doc.packaging_requirements,\n"
        "    'barcode_requirements': doc.barcode_requirements,\n"
        "    'company_id': doc.company_id,\n"
        "    'created_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "    'status': 'DRAFT',\n"
        "})\n"
        "for line in lines:\n"
        "    insert('quotation_line', {\n"
        "        'quotation_id': q.id,\n"
        "        'line_number': line.line_number,\n"
        "        'material_id': line.material_id,\n"
        "        'product_description': line.product_description,\n"
        "        'quantity': line.quantity,\n"
        "        'unit_price': float(line.target_unit_price or 0),\n"
        "        'total_price': float(line.quantity) * float(line.target_unit_price or 0),\n"
        "    })"
    ]

    quote_to_so_hook = [
        "so = insert('sales_order', {\n"
        "    'order_number': 'SO-Q' + str(doc.id),\n"
        "    'customer_id': doc.customer_id,\n"
        "    'inquiry_id': doc.inquiry_id,\n"
        "    'quotation_id': doc.id,\n"
        "    'sales_assistant_id': doc.sales_assistant_id,\n"
        "    'currency': doc.currency,\n"
        "    'total_amount': doc.total_amount,\n"
        "    'payment_terms_days': doc.payment_terms_days,\n"
        "    'shipping_method': doc.shipping_method,\n"
        "    'delivery_address': doc.delivery_address,\n"
        "    'packaging_requirements': doc.packaging_requirements,\n"
        "    'barcode_requirements': doc.barcode_requirements,\n"
        "    'company_id': doc.company_id,\n"
        "    'created_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "    'status': 'DRAFT',\n"
        "})\n"
        "for line in lines:\n"
        "    if line.material_id:\n"
        "        insert('sales_order_line', {\n"
        "            'sales_order_id': so.id,\n"
        "            'line_number': line.line_number,\n"
        "            'material_id': line.material_id,\n"
        "            'quantity': line.quantity,\n"
        "            'unit_price': line.unit_price,\n"
        "            'total_price': line.total_price,\n"
        "        })"
    ]

    sales_order_to_purchase_notice_hook = [
        "if lookup('purchase_notice', sales_order_id=doc.id, company_id=doc.company_id) is None:\n"
        "    pn = insert('purchase_notice', {\n"
        "        'notice_number': 'PN-SO' + str(doc.id),\n"
        "        'sales_order_id': doc.id,\n"
        "        'requested_by_id': doc.sales_assistant_id or doc.updated_by_id or doc.created_by_id,\n"
        "        'purchase_assistant_id': None,\n"
        "        'required_delivery_date': lines[0].requested_delivery_date if len(lines) > 0 else None,\n"
        "        'company_id': doc.company_id,\n"
        "        'created_by_id': doc.sales_assistant_id or doc.updated_by_id or doc.created_by_id,\n"
        "        'status': 'DRAFT',\n"
        "        'notes': '由销售订单 ' + str(doc.order_number) + ' 自动生成',\n"
        "    })\n"
        "    for line in lines:\n"
        "        insert('purchase_notice_line', {\n"
        "            'purchase_notice_id': pn.id,\n"
        "            'line_number': line.line_number,\n"
        "            'sales_order_line_id': line.id,\n"
        "            'material_id': line.material_id,\n"
        "            'quantity': line.quantity,\n"
        "            'required_delivery_date': line.requested_delivery_date,\n"
        "            'packaging_requirements': doc.packaging_requirements,\n"
        "            'barcode_requirements': doc.barcode_requirements,\n"
        "        })"
    ]

    sales_order_advance_receipt_hook = [
        "if lookup('advance_receipt', sales_order_id=doc.id, company_id=doc.company_id) is None:\n"
        "    insert('advance_receipt', {\n"
        "        'receipt_number': 'AREC-SO' + str(doc.id),\n"
        "        'customer_id': doc.customer_id,\n"
        "        'sales_order_id': doc.id,\n"
        "        'amount': doc.advance_receipt_amount or doc.total_amount,\n"
        "        'currency': doc.currency,\n"
        "        'receipt_date': None,\n"
        "        'company_id': doc.company_id,\n"
        "        'created_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "        'status': 'DRAFT',\n"
        "        'notes': '由销售订单 ' + str(doc.order_number) + ' 预收判断自动生成，待财务确认到账',\n"
        "    })"
    ]

    purchase_notice_sent_hook = [
        "so = lookup('sales_order', id=doc.sales_order_id) if doc.sales_order_id else None\n"
        "if so:\n"
        "    old_status = so.status\n"
        "    update('sales_order', {'id': so.id}, {'status': 'PURCHASE_NOTICE_SENT'})\n"
        "    insert('workflow_log', {\n"
        "        'doc_type': 'SALES_ORDER',\n"
        "        'doc_id': so.id,\n"
        "        'company_id': so.company_id,\n"
        "        'workflow_version': 1,\n"
        "        'transition_name': '采购通知已提交 PA',\n"
        "        'from_state': old_status,\n"
        "        'to_state': 'PURCHASE_NOTICE_SENT',\n"
        "        'triggered_by_id': doc.updated_by_id or doc.created_by_id or doc.requested_by_id,\n"
        "        'changed_fields': {'status': {'old': old_status, 'new': 'PURCHASE_NOTICE_SENT'}},\n"
        "        'data_snapshot': {},\n"
        "        'hooks_executed': [],\n"
        "        'comment': '由采购通知 ' + str(doc.notice_number) + ' 自动回写',\n"
        "    })"
    ]

    purchase_notice_to_po_hook = [
        "po = insert('purchase_order', {\n"
        "    'order_number': 'PO-N' + str(doc.id),\n"
        "    'supplier_id': lines[0].preferred_supplier_id if len(lines) > 0 else None,\n"
        "    'purchase_assistant_id': doc.purchase_assistant_id,\n"
        "    'related_sales_order_id': doc.sales_order_id,\n"
        "    'purchase_notice_id': doc.id,\n"
        "    'currency': 'USD',\n"
        "    'total_amount': 0,\n"
        "    'expected_delivery_date': doc.required_delivery_date,\n"
        "    'company_id': doc.company_id,\n"
        "    'created_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "    'status': 'DRAFT',\n"
        "})\n"
        "for line in lines:\n"
        "    insert('purchase_order_line', {\n"
        "        'purchase_order_id': po.id,\n"
        "        'line_number': line.line_number,\n"
        "        'material_id': line.material_id,\n"
        "        'quantity': line.quantity,\n"
        "        'unit_price': 0,\n"
        "        'total_price': 0,\n"
        "        'sales_order_line_id': line.sales_order_line_id,\n"
        "    })"
    ]

    purchase_order_to_goods_receipt_hook = [
        "if lookup('goods_receipt', purchase_order_id=doc.id, company_id=doc.company_id) is None:\n"
        "    wh = lookup('warehouse', company_id=doc.company_id)\n"
        "    gr = insert('goods_receipt', {\n"
        "        'receipt_number': 'GR-PO' + str(doc.id),\n"
        "        'purchase_order_id': doc.id,\n"
        "        'warehouse_id': wh.id if wh else None,\n"
        "        'received_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "        'received_date': doc.actual_delivery_date or today(),\n"
        "        'company_id': doc.company_id,\n"
        "        'created_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "        'status': 'PENDING',\n"
        "        'notes': '由采购订单 ' + str(doc.order_number) + ' 到货动作自动生成',\n"
        "    })\n"
        "    for line in lines:\n"
        "        insert('goods_receipt_line', {\n"
        "            'goods_receipt_id': gr.id,\n"
        "            'purchase_order_line_id': line.id,\n"
        "            'material_id': line.material_id,\n"
        "            'expected_quantity': line.quantity,\n"
        "            'actual_quantity': line.quantity,\n"
        "            'batch_number': 'PO' + str(doc.id) + '-L' + str(line.line_number),\n"
        "            'inbound_number': gr.receipt_number,\n"
        "            'supplier_id': doc.supplier_id,\n"
        "            'uom': line.uom,\n"
        "            'source_doc_number': doc.order_number,\n"
        "        })"
    ]

    purchase_order_advance_payment_hook = [
        "if lookup('advance_payment', purchase_order_id=doc.id, company_id=doc.company_id) is None:\n"
        "    insert('advance_payment', {\n"
        "        'payment_number': 'APAY-PO' + str(doc.id),\n"
        "        'supplier_id': doc.supplier_id,\n"
        "        'purchase_order_id': doc.id,\n"
        "        'requested_by_id': doc.purchase_assistant_id or doc.updated_by_id or doc.created_by_id,\n"
        "        'amount': doc.advance_payment_amount or doc.total_amount,\n"
        "        'currency': doc.currency,\n"
        "        'payment_date': None,\n"
        "        'company_id': doc.company_id,\n"
        "        'created_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "        'status': 'DRAFT',\n"
        "        'notes': '由采购订单 ' + str(doc.order_number) + ' 预付判断自动生成，待财务审核付款',\n"
        "    })"
    ]

    goods_receipt_stock_hook = [
        "for line in lines:\n"
        "    insert('inventory', {\n"
        "        'material_id': line.material_id,\n"
        "        'warehouse_id': doc.warehouse_id,\n"
        "        'batch_number': line.batch_number or ('GR' + str(doc.id) + '-L' + str(line.line_number)),\n"
        "        'inbound_number': line.inbound_number or doc.receipt_number,\n"
        "        'source_doc_number': line.source_doc_number,\n"
        "        'serial_lot_number': line.serial_lot_number or line.batch_number,\n"
        "        'supplier_id': line.supplier_id,\n"
        "        'goods_nature': line.goods_nature,\n"
        "        'uom': line.uom,\n"
        "        'tracking_number': line.tracking_number,\n"
        "        'delivery_method': line.delivery_method,\n"
        "        'carton_number': line.carton_number,\n"
        "        'origin_country': line.origin_country,\n"
        "        'hs_code': line.hs_code,\n"
        "        'location_code': line.location_code,\n"
        "        'date_code': line.date_code,\n"
        "        'production_date': line.production_date,\n"
        "        'quantity': line.actual_quantity,\n"
        "        'received_date': doc.received_date or today(),\n"
        "        'purchase_order_line_id': line.purchase_order_line_id,\n"
        "        'company_id': doc.company_id,\n"
        "        'status': 'AVAILABLE',\n"
        "    })\n"
        "update('purchase_order_line', {'id': line.purchase_order_line_id}, {'received_quantity': line.actual_quantity})"
    ]

    goods_receipt_followup_hook = [
        "po = lookup('purchase_order', id=doc.purchase_order_id) if doc.purchase_order_id else None\n"
        "if po:\n"
        "    old_status = po.status\n"
        "    update('purchase_order', {'id': po.id}, {'status': 'STOCKED_IN'})\n"
        "    insert('workflow_log', {\n"
        "        'doc_type': 'PURCHASE_ORDER',\n"
        "        'doc_id': po.id,\n"
        "        'company_id': po.company_id,\n"
        "        'workflow_version': 1,\n"
        "        'transition_name': '入库单审核通过',\n"
        "        'from_state': old_status,\n"
        "        'to_state': 'STOCKED_IN',\n"
        "        'triggered_by_id': doc.updated_by_id or doc.created_by_id or doc.received_by_id,\n"
        "        'changed_fields': {'status': {'old': old_status, 'new': 'STOCKED_IN'}},\n"
        "        'data_snapshot': {},\n"
        "        'hooks_executed': [],\n"
        "        'comment': '由入库单 ' + str(doc.receipt_number) + ' 自动回写',\n"
        "    })\n"
        "    if lookup('purchase_invoice', goods_receipt_id=doc.id, company_id=doc.company_id) is None:\n"
        "        pi = insert('purchase_invoice', {\n"
        "            'invoice_number': 'PI-GR' + str(doc.id),\n"
        "            'supplier_id': po.supplier_id,\n"
        "            'purchase_order_id': po.id,\n"
        "            'goods_receipt_id': doc.id,\n"
        "            'amount': sum(float(line.actual_quantity) * float(lookup('purchase_order_line', id=line.purchase_order_line_id).unit_price or 0) for line in lines),\n"
        "            'currency': po.currency,\n"
        "            'tax_rate': 0,\n"
        "            'invoice_date': None,\n"
        "            'company_id': doc.company_id,\n"
        "            'created_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "            'status': 'DRAFT',\n"
        "            'notes': '由入库单 ' + str(doc.receipt_number) + ' 自动生成，发票号待财务替换为供应商正式发票号',\n"
        "        })\n"
        "        for line in lines:\n"
        "            pol = lookup('purchase_order_line', id=line.purchase_order_line_id)\n"
        "            insert('purchase_invoice_line', {\n"
        "                'purchase_invoice_id': pi.id,\n"
        "                'line_number': line.line_number,\n"
        "                'purchase_order_line_id': line.purchase_order_line_id,\n"
        "                'goods_receipt_line_id': line.id,\n"
        "                'material_id': line.material_id,\n"
        "                'quantity': line.actual_quantity,\n"
        "                'unit_price': pol.unit_price,\n"
        "                'total_price': float(line.actual_quantity) * float(pol.unit_price or 0),\n"
        "                'tax_rate': 0,\n"
        "            })"
    ]

    sales_order_to_shipment_hook = [
        "if lookup('shipment_request', sales_order_id=doc.id, company_id=doc.company_id) is None:\n"
        "    insert('shipment_request', {\n"
        "        'shipment_number': 'SH-SO' + str(doc.id),\n"
        "        'sales_order_id': doc.id,\n"
        "        'requested_by_id': doc.sales_assistant_id or doc.updated_by_id or doc.created_by_id,\n"
        "        'approved_by_id': None,\n"
        "        'warehouse_id': None,\n"
        "        'shipping_method': doc.shipping_method,\n"
        "        'source_purchase_order_number': '',\n"
        "        'payment_terms_text': doc.payment_terms_text,\n"
        "        'packaging_requirements': doc.packaging_requirements,\n"
        "        'barcode_requirements': doc.barcode_requirements,\n"
        "        'delivery_requirements': doc.delivery_address,\n"
        "        'company_id': doc.company_id,\n"
        "        'created_by_id': doc.sales_assistant_id or doc.updated_by_id or doc.created_by_id,\n"
        "        'status': 'DRAFT',\n"
        "        'notes': '由销售订单 ' + str(doc.order_number) + ' 自动生成',\n"
        "    })"
    ]

    shipment_stock_hook = [
        "for line in lines:\n"
        "    inv = lookup('inventory', id=line.inventory_id)\n"
        "    if inv:\n"
        "        update('inventory', {'id': inv.id}, {\n"
        "            'quantity': float(inv.quantity) - float(line.quantity),\n"
        "            'reserved_quantity': max(float(inv.reserved_quantity or 0) - float(line.quantity), 0),\n"
        "        })\n"
        "    update('sales_order_line', {'id': line.sales_order_line_id}, {'shipped_quantity': line.quantity})"
    ]

    shipment_sales_invoice_hook = [
        "so = lookup('sales_order', id=doc.sales_order_id) if doc.sales_order_id else None\n"
        "if so and lookup('sales_invoice', shipment_id=doc.id, company_id=doc.company_id) is None:\n"
        "    si = insert('sales_invoice', {\n"
        "        'invoice_number': 'SI-SH' + str(doc.id),\n"
        "        'customer_id': so.customer_id,\n"
        "        'sales_order_id': so.id,\n"
        "        'shipment_id': doc.id,\n"
        "        'amount': sum(float(line.quantity) * float(lookup('sales_order_line', id=line.sales_order_line_id).unit_price or 0) for line in lines),\n"
        "        'currency': so.currency,\n"
        "        'tax_rate': 0,\n"
        "        'invoice_date': None,\n"
        "        'company_id': doc.company_id,\n"
        "        'created_by_id': doc.updated_by_id or doc.created_by_id or doc.requested_by_id,\n"
        "        'status': 'DRAFT',\n"
        "        'notes': '由发货单 ' + str(doc.shipment_number) + ' 自动生成，发票号待财务替换为正式销售发票号',\n"
        "    })\n"
        "    for line in lines:\n"
        "        sol = lookup('sales_order_line', id=line.sales_order_line_id)\n"
        "        insert('sales_invoice_line', {\n"
        "            'sales_invoice_id': si.id,\n"
        "            'line_number': line.id,\n"
        "            'sales_order_line_id': line.sales_order_line_id,\n"
        "            'shipment_line_id': line.id,\n"
        "            'material_id': sol.material_id,\n"
        "            'quantity': line.quantity,\n"
        "            'unit_price': sol.unit_price,\n"
        "            'total_price': float(line.quantity) * float(sol.unit_price or 0),\n"
        "            'tax_rate': 0,\n"
        "            'cost_amount': 0,\n"
        "        })"
    ]

    shipment_sales_return_hook = [
        "so = lookup('sales_order', id=doc.sales_order_id) if doc.sales_order_id else None\n"
        "if so and lookup('sales_return', shipment_id=doc.id, company_id=doc.company_id) is None:\n"
        "    sr = insert('sales_return', {\n"
        "        'return_number': 'SR-SH' + str(doc.id),\n"
        "        'sales_order_id': so.id,\n"
        "        'shipment_id': doc.id,\n"
        "        'customer_id': so.customer_id,\n"
        "        'warehouse_id': doc.warehouse_id,\n"
        "        'return_reason': '',\n"
        "        'logistics_tracking_number': doc.tracking_number,\n"
        "        'company_id': doc.company_id,\n"
        "        'created_by_id': doc.updated_by_id or doc.created_by_id or doc.requested_by_id,\n"
        "        'status': 'DRAFT',\n"
        "        'notes': '由发货单 ' + str(doc.shipment_number) + ' 客户退货动作自动生成',\n"
        "    })\n"
        "    for line in lines:\n"
        "        sol = lookup('sales_order_line', id=line.sales_order_line_id)\n"
        "        insert('sales_return_line', {\n"
        "            'sales_return_id': sr.id,\n"
        "            'line_number': line.id,\n"
        "            'sales_order_line_id': line.sales_order_line_id,\n"
        "            'shipment_line_id': line.id,\n"
        "            'material_id': sol.material_id,\n"
        "            'quantity': line.quantity,\n"
        "            'quality_status': 'PENDING',\n"
        "            'return_action': 'RESTOCK',\n"
        "        })"
    ]

    purchase_invoice_ap_hook = [
        "insert('accounts_payable', {\n"
        "    'supplier_id': doc.supplier_id,\n"
        "    'purchase_order_id': doc.purchase_order_id,\n"
        "    'invoice_number': doc.invoice_number,\n"
        "    'amount': doc.amount,\n"
        "    'currency': doc.currency,\n"
        "    'due_date': today(),\n"
        "    'company_id': doc.company_id,\n"
        "    'created_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "    'status': 'PENDING',\n"
        "})"
    ]

    purchase_invoice_po_hook = [
        "po = lookup('purchase_order', id=doc.purchase_order_id) if doc.purchase_order_id else None\n"
        "if po:\n"
        "    old_status = po.status\n"
        "    update('purchase_order', {'id': po.id}, {'status': 'INVOICE_MATCHING'})\n"
        "    insert('workflow_log', {\n"
        "        'doc_type': 'PURCHASE_ORDER',\n"
        "        'doc_id': po.id,\n"
        "        'company_id': po.company_id,\n"
        "        'workflow_version': 1,\n"
        "        'transition_name': '采购发票已勾稽',\n"
        "        'from_state': old_status,\n"
        "        'to_state': 'INVOICE_MATCHING',\n"
        "        'triggered_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "        'changed_fields': {'status': {'old': old_status, 'new': 'INVOICE_MATCHING'}},\n"
        "        'data_snapshot': {},\n"
        "        'hooks_executed': [],\n"
        "        'comment': '由采购发票 ' + str(doc.invoice_number) + ' 自动回写',\n"
        "    })"
    ]

    sales_invoice_ar_hook = [
        "insert('accounts_receivable', {\n"
        "    'customer_id': doc.customer_id,\n"
        "    'sales_order_id': doc.sales_order_id,\n"
        "    'invoice_number': doc.invoice_number,\n"
        "    'amount': doc.amount,\n"
        "    'currency': doc.currency,\n"
        "    'due_date': today(),\n"
        "    'company_id': doc.company_id,\n"
        "    'created_by_id': doc.updated_by_id or doc.created_by_id,\n"
        "    'status': 'PENDING',\n"
        "})"
    ]

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
                    {"to": "QUOTATION_CREATED", "label": "生成报价单", "editable_fields": [], "hooks": inquiry_to_quote_hook},
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
                    {"to": "SALES_ORDER_CREATED", "label": "生成销售订单", "editable_fields": [], "hooks": quote_to_so_hook},
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
                    {"to": "ADVANCE_RECEIPT_REQUIRED", "label": "需要客户预收", "editable_fields": ["requires_advance_receipt", "advance_receipt_amount", "notes"], "hooks": sales_order_advance_receipt_hook},
                    {"to": "READY_FOR_PURCHASE", "label": "无需预收/放行采购", "editable_fields": ["notes"]},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                _state("ADVANCE_RECEIPT_REQUIRED", "待客户预收", ["FINANCE", "SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "READY_FOR_PURCHASE", "label": "预收已确认", "editable_fields": ["notes"]},
                ]),
                _state("READY_FOR_PURCHASE", "可发起采购通知", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "PURCHASE_NOTICE_SENT", "label": "已发起采购通知", "editable_fields": ["notes"]},
                ], hooks=sales_order_to_purchase_notice_hook),
                _state("PURCHASE_NOTICE_SENT", "采购处理中", ["SALES_ASSISTANT", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "READY_TO_SHIP", "label": "库存满足可发货", "editable_fields": ["notes"]},
                ]),
                _state("READY_TO_SHIP", "待发货通知", ["SALES_ASSISTANT", "OPERATIONS"], [
                    {"to": "SHIPMENT_REQUESTED", "label": "已发布发货通知", "editable_fields": ["notes"], "hooks": sales_order_to_shipment_hook},
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
                    {"to": "PA_ACCEPTED", "label": "提交 PA 接收", "editable_fields": purchase_notice_fields, "hooks": purchase_notice_sent_hook},
                    {"to": "CANCELLED", "label": "取消通知", "editable_fields": ["notes"]},
                ]),
                _state("PA_ACCEPTED", "PA 已接收", ["PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "PURCHASE_ORDER_CREATED", "label": "生成采购订单", "editable_fields": ["purchase_assistant_id", "notes"], "hooks": purchase_notice_to_po_hook},
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
                    {"to": "ADVANCE_PAYMENT_REQUIRED", "label": "需要预付款", "editable_fields": ["requires_advance_payment", "advance_payment_amount", "notes"], "hooks": purchase_order_advance_payment_hook},
                    {"to": "ORDERED", "label": "审核通过并下单", "editable_fields": ["expected_delivery_date", "notes"]},
                    {"to": "DRAFT", "label": "退回修改", "editable_fields": ["notes"]},
                ]),
                _state("ADVANCE_PAYMENT_REQUIRED", "待供应商预付", ["PRODUCT_ASSISTANT", "FINANCE", "OPERATIONS"], [
                    {"to": "ORDERED", "label": "预付已完成并下单", "editable_fields": ["notes"]},
                ]),
                _state("ORDERED", "已下单待到货", ["LOGISTICS", "PRODUCT_ASSISTANT", "OPERATIONS"], [
                    {"to": "GOODS_RECEIVED", "label": "仓库已收货", "editable_fields": ["actual_delivery_date", "notes"], "hooks": purchase_order_to_goods_receipt_hook},
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
                    {"to": "STOCKED_IN", "label": "审核通过入库", "editable_fields": ["notes"], "hooks": goods_receipt_stock_hook + goods_receipt_followup_hook},
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
                    {"to": "SALES_OUTBOUND", "label": "确认出库", "editable_fields": ["shipped_date", "tracking_number", "notes"], "hooks": shipment_stock_hook + shipment_sales_invoice_hook},
                ]),
                _state("SALES_OUTBOUND", "销售出库", ["FINANCE", "LOGISTICS", "OPERATIONS"], [
                    {"to": "CUSTOMER_RECEIVED", "label": "客户签收", "editable_fields": ["notes"]},
                    {"to": "RETURN_REQUESTED", "label": "客户退货", "editable_fields": ["notes"], "hooks": shipment_sales_return_hook},
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
                    {"to": "AP_CREATED", "label": "勾稽通过并生成应付", "editable_fields": ["notes"], "hooks": purchase_invoice_ap_hook + purchase_invoice_po_hook},
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
                    {"to": "AR_CREATED", "label": "勾稽通过并生成应收", "editable_fields": ["notes"], "hooks": sales_invoice_ar_hook},
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
