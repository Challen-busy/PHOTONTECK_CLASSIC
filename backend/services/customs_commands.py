"""段4a 报关域命令（PRD 06-5 顺丰物流框架壳 / 06-6 资料清单导出壳）。

唯一写入路径仍是 Command（@register_command）；不动 execute_transition、不给引擎加核心语义。

段5 边界（铁律）：
  - 顺丰物流 API：FeatureFlag SF_EXPRESS_SYNC 默认 OFF + 契约壳，body 直接 return 占位 dict，
    不真实调 HTTP（appKey/checkWord/customerCode/base_url 留空占位，等顺丰给配置即填即开）。
  - 资料清单导出：返回明细 JSON（不做 PDF / 不发邮件）。

本文件在 command_registry.load_commands() 中按 import 加载（已登记）。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.command_context import CommandContext
from services.command_registry import register_command
from services.commands import CommandError
from services.tools import _company_filter

# 顺丰物流同步功能开关键（FeatureFlag.flag_key，per-company，默认 OFF）。
SF_EXPRESS_SYNC_FLAG = "SF_EXPRESS_SYNC"


def _assert_company_access(user: m.UserAccount, company_id: int) -> None:
    company_ids = _company_filter(user)
    if company_ids and company_id not in company_ids:
        raise CommandError("无权访问该公司数据", 403)


async def _sf_sync_enabled(db: AsyncSession, company_id: int) -> bool:
    """读 FeatureFlag SF_EXPRESS_SYNC（per-company）。无行或未启用 → False（默认 OFF）。"""
    flag = (await db.execute(
        select(m.FeatureFlag).where(
            m.FeatureFlag.company_id == company_id,
            m.FeatureFlag.flag_key == SF_EXPRESS_SYNC_FLAG,
        )
    )).scalar_one_or_none()
    return bool(flag and flag.is_enabled)


# ============================================================
# 顺丰物流 API 框架壳（PRD 06-5，OFF，等配置）
# ============================================================

@register_command(
    "sf_query_tracking",
    module="CUSTOMS",
    title="顺丰查询轨迹（框架壳·待配置）",
    description="按运单号查顺丰全程轨迹（SF_EXPRESS_SYNC 默认 OFF；开启后接顺丰 OpenAPI，当前占位返回）",
    affected_tables=("shipment_tracking", "shipment_tracking_node"),
    supports_retry=True,
)
async def sf_query_tracking(ctx: CommandContext, payload: dict) -> dict:
    """顺丰路由查询契约壳（EXP_RECE_SEARCH_ROUTES）。

    段5 边界：不真实调 HTTP。开关 OFF → 返回「集成未启用」软结果（不报错，前端退化手填兜底）。
    开关 ON（顺丰配置到位后）→ TODO 真实签名 MD5(msgData+timestamp+checkWord)+Base64 + 解析 upsert 轨迹。
    """
    tracking_number = (payload.get("tracking_number") or "").strip()
    if not tracking_number:
        raise CommandError("tracking_number 不能为空")
    company_id = payload.get("company_id") or ctx.user.company_id
    _assert_company_access(ctx.user, company_id)

    if not await _sf_sync_enabled(ctx.db, company_id):
        return {
            "enabled": False,
            "tracking_number": tracking_number,
            "message": "顺丰集成未启用（SF_EXPRESS_SYNC=OFF）：功能已就绪，待顺丰 OpenAPI 配置开通；当前手填进度兜底。",
            "nodes": [],
        }
    # TODO（段5 真实接入）：读 8 配置域 SF_APP_KEY/SF_CHECK_WORD/SF_CUSTOMER_CODE/SF_BASE_URL，
    # 签名 + httpx POST EXP_RECE_SEARCH_ROUTES，解析节点 upsert shipment_tracking(+_node)。
    return {
        "enabled": True,
        "tracking_number": tracking_number,
        "message": "占位：顺丰接入已就绪，真实 HTTP 调用属段5（此处不实现）。",
        "nodes": [],
    }


@register_command(
    "sf_subscribe_tracking",
    module="CUSTOMS",
    title="顺丰订阅轨迹推送（框架壳·待配置）",
    description="注册我方回调登记顺丰路由推送订阅（SF_EXPRESS_SYNC 默认 OFF；占位返回）",
    affected_tables=("shipment_tracking",),
    supports_retry=True,
)
async def sf_subscribe_tracking(ctx: CommandContext, payload: dict) -> dict:
    """顺丰路由推送订阅契约壳（EXP_RECE_PUSH_ROUTES）。段5 边界：不真实调 HTTP。"""
    tracking_number = (payload.get("tracking_number") or "").strip()
    if not tracking_number:
        raise CommandError("tracking_number 不能为空")
    company_id = payload.get("company_id") or ctx.user.company_id
    _assert_company_access(ctx.user, company_id)

    if not await _sf_sync_enabled(ctx.db, company_id):
        return {
            "enabled": False,
            "tracking_number": tracking_number,
            "subscribed": False,
            "message": "顺丰集成未启用（SF_EXPRESS_SYNC=OFF）：订阅推送待配置开通。",
        }
    # TODO（段5）：注册回调 URL /integrations/sf/tracking-callback + 验签 token，置 is_subscribed=true。
    return {
        "enabled": True,
        "tracking_number": tracking_number,
        "subscribed": False,
        "message": "占位：订阅注册属段5（此处不实现真实 HTTP）。",
    }


# ============================================================
# 报关资料清单导出壳（PRD 06-6，返回明细 JSON，不做 PDF / 不发邮件）
# ============================================================

@register_command(
    "customs_export_manifest",
    module="CUSTOMS",
    title="报关资料清单导出",
    description="汇集报关单头+商品明细+许可证生成资料清单 JSON + 缺件提示（发货代/报关行；不做 PDF）",
    affected_tables=(),
    supports_preview=True,
)
async def customs_export_manifest(ctx: CommandContext, payload: dict) -> dict:
    """资料清单导出（PRD 06-6）：返回报关单号/方向/明细/许可证 + 缺件提示 JSON。

    缺件提示：出口缺发票号标「商业发票最致命」；明细缺合规五件套标缺项（调研证据 1-4/V-8）。
    """
    declaration_id = payload.get("declaration_id")
    if not declaration_id:
        raise CommandError("declaration_id 不能为空")
    doc = (await ctx.db.execute(
        select(m.CustomsDeclaration).where(m.CustomsDeclaration.id == declaration_id)
    )).scalar_one_or_none()
    if not doc:
        raise CommandError("报关单不存在", 404)
    _assert_company_access(ctx.user, doc.company_id)

    lines = (await ctx.db.execute(
        select(m.CustomsDeclarationLine)
        .where(m.CustomsDeclarationLine.customs_declaration_id == doc.id)
        .order_by(m.CustomsDeclarationLine.line_number)
    )).scalars().all()

    missing: list[str] = []
    line_items = []
    for line in lines:
        line_missing = []
        for field, cn in (("hs_code_cn", "HS中国码"), ("origin_country", "原产国"),
                          ("cn_name", "中文品名")):
            if not (getattr(line, field, None) or "").strip():
                line_missing.append(cn)
        if doc.direction != "RE_EXPORT" and not (getattr(line, "eccn", None) or "").strip():
            line_missing.append("ECCN")
        if line_missing:
            missing.append(f"第{line.line_number}行缺：{', '.join(line_missing)}")
        line_items.append({
            "line_number": line.line_number,
            "material_id": line.material_id,
            "cn_name": line.cn_name,
            "hs_code_cn": line.hs_code_cn,
            "origin_country": line.origin_country,
            "eccn": line.eccn,
            "quantity": float(line.quantity or 0),
            "declared_amount": float(line.declared_amount or 0) if line.declared_amount is not None else None,
            "license_id": line.license_id,
        })

    if doc.direction == "EXPORT" and not (doc.source_invoice_number or "").strip():
        missing.append("出口缺商业发票号（商业发票最致命）")

    license_ids = sorted({line.license_id for line in lines if line.license_id})
    licenses = []
    if license_ids:
        rows = (await ctx.db.execute(
            select(m.CustomsLicense).where(m.CustomsLicense.id.in_(license_ids))
        )).scalars().all()
        licenses = [{"id": r.id, "license_no": r.license_no, "license_type": r.license_type,
                     "valid_to": r.valid_to.isoformat() if r.valid_to else None} for r in rows]

    return {
        "declaration_number": doc.declaration_number,
        "direction": doc.direction,
        "customs_region": doc.customs_region,
        "broker_mode": doc.broker_mode,
        "status": doc.status,
        "lines": line_items,
        "licenses": licenses,
        "missing": missing,
        "complete": not missing,
    }
