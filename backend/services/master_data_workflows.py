"""段0c·主数据 + 模板的轻量建档状态机定义（PRD 02 主数据 + PRD 09 配置/模板）。

主数据/模板大多是引擎里的纯字典/可查实体；但「需可建档」的几类（客户/供应商/型号/产品代码/
产线 + 标签模板/单据模板）要让前端经引擎唯一写入路径 execute_transition 走「创建/编辑」两模式
（DocEditor + SubTableEditor），就需要一份**轻量 WorkflowDefinition**：

- 单状态 ACTIVE（is_initial + is_terminal）：建档即入此态，无审批流转、无财务关卡。
- 自环出边「编辑」：携带 editable_fields = 该实体可改字段（创建时可填、编辑时可改的并集）。
  （引擎编辑模式从「当前状态的 next 出边」收集可编辑字段，故单状态也要挂自环出边。）
- allowed_roles：ADMIN + 该实体维护角色（PA 建供应商/产品代码、SA 建客户、PM 建产线…）。

铁律遵从：这是纯「数据」（WorkflowDefinition.states JSONB），不动 execute_transition / 注册器 /
命令框架；主数据写仍走唯一写入路径。引擎五条不破坏。
"""


def _active_only_states(roles: list[str], editable_fields: list[str]) -> list[dict]:
    """构造「单状态 ACTIVE（is_initial+is_terminal）+ 自环编辑出边」的 states。

    自环出边携 editable_fields → 引擎编辑模式据此放行字段；创建模式入 ACTIVE 态可填这些字段。
    """
    return [
        {
            "code": "ACTIVE",
            "name": "启用",
            "is_initial": True,
            "is_terminal": True,
            "allowed_roles": roles,
            "editable_fields": editable_fields,  # 创建时可填字段（引擎兼容：出边亦带同集）
            "description": "# 启用\n主数据/模板建档即入此态（无审批流转、无财务关卡）。"
                           "点「编辑」自环改字段；联系人/字段映射等子表随主体一起改。",
            "custom_html": "",
            "hard_rules": [],
            "hooks": [],
            "next": [
                {"to": "ACTIVE", "label": "编辑", "editable_fields": editable_fields},
            ],
        }
    ]


def master_data_workflow_definitions(created_by_id=None):
    """返回可直接传给 models.WorkflowDefinition(**kwargs) 的轻量建档流程列表。

    每条 = 一个 doc_type 的单状态 ACTIVE 机。doc_type 与 models.__doc_types__ 对齐：
    CUSTOMER / SUPPLIER / MATERIAL / PRODUCT_CODE / PRODUCT_LINE / LABEL_TEMPLATE / DOC_TEMPLATE。
    """
    # —— 各实体可建档/可编辑字段（对齐 models.py 列名 + PRD 02/09 字段表）——
    customer_fields = [
        "code", "name", "short_name", "country", "city", "address",
        "contact_person", "contact_email", "contact_phone",
        "payment_terms_days", "default_currency", "default_shipping_method",
        "region", "business_unit", "grade", "default_payment_term", "credit_limit",
        "customer_vendor_code", "owner_sales_id", "label_template_ref", "status", "is_active",
    ]
    supplier_fields = [
        "code", "name", "short_name", "country",
        "contact_person", "contact_email", "contact_phone", "notes",
        "supplier_type", "payment_term", "responsible_pa_id", "backup_pa_id",
        "region", "status", "is_active",
    ]
    material_fields = [
        "sku", "name", "pn", "desc_cn", "desc_en", "product_name",
        "supplier_id", "category_id", "product_line", "is_domestic", "unit", "description",
        "control_mode", "uom_id", "min_pack_qty", "pack_qty_variable",
        "hs_code_origin_id", "hs_code_cn_id", "eccn", "country_of_origin",
        "moq", "mpq", "warranty_months", "has_battery", "date_code_rule", "pcn_flag",
        "product_line_id", "status", "is_active",
    ]
    product_code_fields = [
        "internal_code", "product_id", "supplier_id", "vendor_pn",
        "customer_material_no", "status", "notes",
    ]
    product_line_fields = [
        "code", "line_name", "supplier_id", "pm_id", "fae_id", "pa_id",
        "status", "is_active", "notes",
    ]
    label_template_fields = [
        "customer_id", "name", "label_type", "size_mm", "orientation",
        "qr_separator", "qr_field_order", "barcode_fields",
        "template_content", "fields_mapping", "is_default", "status", "is_active", "notes",
    ]
    doc_template_fields = [
        "customer_id", "name", "doc_kind", "region", "needs_stamp", "needs_countersign",
        "header_title", "bank_block", "render_html", "status", "is_active", "notes",
    ]
    # 段1b-2：库位建档字段（PRD 03b 页面5 调拨依赖库位主数据）。warehouse_id 建档时必选；
    #   zone/shelf/position 三级 = 货区/货架/货层；location_type 驱动 WMS 行为（NORMAL/TRANSIT/RMA/...）。
    warehouse_location_fields = [
        "warehouse_id", "code", "zone", "shelf", "position",
        "location_type", "capacity", "is_active",
    ]

    # (doc_type, 中文名, 维护角色, 可建档字段, 分组)
    specs = [
        ("CUSTOMER", "客户建档", ["ADMIN", "SALES_ASSISTANT"], customer_fields, "主数据"),
        ("SUPPLIER", "供应商建档", ["ADMIN", "PRODUCT_ASSISTANT"], supplier_fields, "主数据"),
        ("MATERIAL", "产品/型号建档",
         ["ADMIN", "PRODUCT_ASSISTANT", "SALES_ENGINEER", "PRODUCT_MANAGER"], material_fields, "主数据"),
        ("PRODUCT_CODE", "产品代码建档", ["ADMIN", "PRODUCT_ASSISTANT"], product_code_fields, "主数据"),
        ("PRODUCT_LINE", "产线建档", ["ADMIN", "PRODUCT_MANAGER"], product_line_fields, "主数据"),
        ("LABEL_TEMPLATE", "标签模板", ["ADMIN", "LOGISTICS"], label_template_fields, "配置模板"),
        ("DOC_TEMPLATE", "单据模板", ["ADMIN", "LOGISTICS"], doc_template_fields, "配置模板"),
        ("WAREHOUSE_LOCATION", "库位建档", ["ADMIN", "LOGISTICS_LEAD"], warehouse_location_fields, "主数据"),
    ]

    defs = []
    for doc_type, name, roles, fields, group in specs:
        defs.append({
            "doc_type": doc_type,
            "name": name,
            "description": f"# {name}\n轻量建档状态机（单状态 ACTIVE，无审批/无财务关卡）。",
            "states": _active_only_states(roles, fields),
            "group_name": group,
            "is_published": True,
            "is_active": True,
            "created_by_id": created_by_id,
        })
    return defs
