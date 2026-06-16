"""标签 / 单据模板渲染引擎（段0c·标签模板引擎 + 单据模板引擎）。

PRD 09 §9.1（标签模板）+ §9.2（单据模板）+ 09-标签模板规格（逐客户）+ 09-单据模板规格。

引擎无原生标签/单据子系统，仅 custom_html 逃生舱。本模块用 @register_command 补两条渲染命令：
- build_label_payload(template_id, doc_id): 按 LabelTemplate + LabelFieldLine 把「一张单的数据」
  拼成标签字段 + 二维码串（按 qr_field_order 取值、qr_separator 连接），并标出要渲条码的字段。
- render_doc_template(template_id, doc_id): 按 DocTemplate + DocTemplateFieldLine 把单据字段拼好
  （含本地/出口切换、条码开关），输出占位 render_html / 字段值表。

铁律遵从：唯一写入路径仍是 Command（@register_command）；不动 execute_transition、不给引擎加
标签/单据语义；纯业务层积木。真实打印（BarTender/ZPL 驱动）留占位口子（_PLACEHOLDER_PRINT）。
"""

from html import escape

from sqlalchemy import select

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter

# 真实打印驱动集成占位（PRD §9.1/§9.2 gap：BarTender 类打印机集成方式待甲方）。
# 渲染命令只产出「拼好的字段值 + 二维码串 + 占位 render_html」，物理打印走仓库本地打印机。
_PLACEHOLDER_PRINT = "PRINT_DRIVER_PLACEHOLDER"


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id is not None and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


def _doc_field_value(doc, source_field: str):
    """从一张单（出库/发票等任意 ORM 行）按来源字段名取值，缺字段返回空串（兜底，不报错）。"""
    if not source_field:
        return ""
    val = getattr(doc, source_field, None)
    return "" if val is None else val


def _load_doc(db_sync, doc_type: str, doc_id: int):
    """按 doc_type 解析模型并加载单据行（容错：未注册/不存在返回 None）。"""
    from core.registry import doc_model_map, table_map

    model = doc_model_map().get(doc_type) or table_map().get(doc_type)
    if not model:
        return None
    return db_sync.get(model, doc_id)


def _build_qr_string(template: m.LabelTemplate, field_values: dict) -> str:
    """按 qr_field_order + qr_separator 拼二维码串。

    qr_field_order 是「标签字段标题」的有序数组（与 LabelFieldLine.label_field_title 对齐）；
    分隔符空串/「无」视为直接相连。所有值做转义后拼接（XSS 治理：值不含 HTML）。
    """
    order = template.qr_field_order or []
    sep = template.qr_separator or ""
    if sep == "无":
        sep = ""
    parts = []
    for key in order:
        v = field_values.get(key, "")
        parts.append("" if v is None else str(v))
    return sep.join(parts)


@register_command(
    "build_label_payload",
    module="CONFIG",
    title="渲染标签",
    description="按标签模板把一张单的数据拼成标签字段 + 二维码串（真实打印留占位）",
    affected_tables=("label_template", "label_field_line"),
)
async def build_label_payload(ctx: CommandContext, payload: dict) -> dict:
    """渲染一张标签。

    payload: {template_id, doc_type, doc_id}
      - template_id: LabelTemplate.id
      - doc_type/doc_id: 要灌数据的源单（出库单/批次等任意已注册单据）
    返回: {template_id, label_type, size_mm, fields:[{title,value,render_as_barcode}],
           qr_string, barcode_fields, render_html(占位), print_driver}
    """
    template_id = payload.get("template_id")
    if not template_id:
        raise CommandError("template_id 不能为空")

    template = (await ctx.db.execute(
        select(m.LabelTemplate).where(m.LabelTemplate.id == template_id)
    )).scalar_one_or_none()
    if not template:
        raise CommandError(f"标签模板不存在: {template_id}", 404)
    _assert_company_access(ctx.user, template.company_id)
    if template.status != "ACTIVE" or not template.is_active:
        raise CommandError("标签模板未启用")

    lines = (await ctx.db.execute(
        select(m.LabelFieldLine)
        .where(m.LabelFieldLine.label_template_id == template_id)
        .order_by(m.LabelFieldLine.line_number)
    )).scalars().all()

    # 加载源单（可选：无 doc 则只渲染常量/派生字段，留空兜底）
    doc = None
    doc_type = payload.get("doc_type")
    doc_id = payload.get("doc_id")
    if doc_type and doc_id:
        doc = await ctx.db.run_sync(lambda s: _load_doc(s, doc_type, doc_id))

    fields = []
    field_values: dict = {}
    for ln in lines:
        if ln.source_type == "CONST":
            value = ln.const_value or ""
        elif ln.source_type == "DERIVED":
            # 派生公式 DSL 待甲方/工程定义（PRD §9.1 gap）：先原样回显表达式，留占位。
            value = f"[DERIVED:{ln.derive_expr}]" if ln.derive_expr else ""
        elif ln.source_type in ("EMAIL", "CUSTOMER_SYS"):
            # 客户系统/邮件附件来源为手填兜底（PRD §9.1），渲染时取不到则空。
            value = _doc_field_value(doc, ln.source_field) if doc else ""
        else:  # OUTBOUND / INBOUND → 从源单直取
            value = _doc_field_value(doc, ln.source_field) if doc else ""
        value = str(value)
        field_values[ln.label_field_title] = value
        fields.append({
            "title": ln.label_field_title,
            "value": value,
            "in_qr": bool(ln.in_qr),
            "render_as_barcode": bool(ln.render_as_barcode),
        })

    qr_string = _build_qr_string(template, field_values)

    # 占位 render_html（custom_html 逃生舱）：仅后端按白名单字段拼装、值转义（XSS 治理，PRD §9.1）。
    rows_html = "".join(
        f"<tr><td>{escape(f['title'])}</td><td>{escape(f['value'])}</td></tr>"
        for f in fields
    )
    render_html = (
        f"<div class='label' data-size='{escape(template.size_mm or '')}'>"
        f"<table>{rows_html}</table>"
        f"<div class='qr' data-qr='{escape(qr_string)}'></div></div>"
    )

    barcode_fields = [f["title"] for f in fields if f["render_as_barcode"]]
    ctx.add_event("label_rendered", {
        "template_id": template_id, "label_type": template.label_type,
        "qr_string": qr_string, "field_count": len(fields),
    })
    return {
        "template_id": template_id,
        "label_type": template.label_type,
        "size_mm": template.size_mm,
        "fields": fields,
        "qr_string": qr_string,
        "qr_separator": template.qr_separator,
        "barcode_fields": barcode_fields,
        "render_html": render_html,
        "print_driver": _PLACEHOLDER_PRINT,  # 真实打印留口子
    }


@register_command(
    "render_doc_template",
    module="CONFIG",
    title="渲染单据",
    description="按单据模板把一张单的数据拼成 PL/INV/送货单字段（真实打印留占位）",
    affected_tables=("doc_template", "doc_template_field_line"),
)
async def render_doc_template(ctx: CommandContext, payload: dict) -> dict:
    """渲染一张对外单据（PL/INV/送货单）。

    payload: {template_id, doc_type, doc_id, mode?}
      - mode: LOCAL 本地 / EXPORT 出口（决定 is_variant 字段取 variant_local 还是 variant_export）
    返回: {template_id, doc_kind, region, header_title, needs_stamp, needs_countersign,
           fields:[{title,value,render_as_barcode}], render_html(占位), print_driver}
    """
    template_id = payload.get("template_id")
    if not template_id:
        raise CommandError("template_id 不能为空")
    mode = (payload.get("mode") or "LOCAL").upper()

    template = (await ctx.db.execute(
        select(m.DocTemplate).where(m.DocTemplate.id == template_id)
    )).scalar_one_or_none()
    if not template:
        raise CommandError(f"单据模板不存在: {template_id}", 404)
    _assert_company_access(ctx.user, template.company_id)
    if template.status != "ACTIVE" or not template.is_active:
        raise CommandError("单据模板未启用")

    lines = (await ctx.db.execute(
        select(m.DocTemplateFieldLine)
        .where(m.DocTemplateFieldLine.doc_template_id == template_id)
        .order_by(m.DocTemplateFieldLine.line_number)
    )).scalars().all()

    doc = None
    doc_type = payload.get("doc_type")
    doc_id = payload.get("doc_id")
    if doc_type and doc_id:
        doc = await ctx.db.run_sync(lambda s: _load_doc(s, doc_type, doc_id))

    fields = []
    for ln in lines:
        if ln.is_variant_field:
            src = ln.variant_export if mode == "EXPORT" else ln.variant_local
        else:
            src = ln.source_field
        if ln.const_value:
            value = ln.const_value
        else:
            value = _doc_field_value(doc, src) if doc else ""
        value = str(value)
        fields.append({
            "title": ln.doc_field_title,
            "value": value,
            "render_as_barcode": bool(ln.render_as_barcode),
        })

    rows_html = "".join(
        f"<tr><td>{escape(f['title'])}</td><td>{escape(f['value'])}</td></tr>"
        for f in fields
    )
    render_html = (
        f"<div class='doc' data-kind='{escape(template.doc_kind)}' data-region='{escape(template.region)}'>"
        f"<div class='header'>{escape(template.header_title or '')}</div>"
        f"<table>{rows_html}</table>"
        + (f"<div class='bank'>{escape(template.bank_block)}</div>" if template.bank_block else "")
        + "</div>"
    )

    barcode_fields = [f["title"] for f in fields if f["render_as_barcode"]]
    ctx.add_event("doc_rendered", {
        "template_id": template_id, "doc_kind": template.doc_kind,
        "mode": mode, "field_count": len(fields),
    })
    return {
        "template_id": template_id,
        "doc_kind": template.doc_kind,
        "region": template.region,
        "mode": mode,
        "header_title": template.header_title,
        "needs_stamp": bool(template.needs_stamp),
        "needs_countersign": bool(template.needs_countersign),
        "fields": fields,
        "barcode_fields": barcode_fields,
        "render_html": render_html,
        "print_driver": _PLACEHOLDER_PRINT,  # 真实打印留口子
    }
