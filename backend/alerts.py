"""
定时巡检Agent — 按知识库预警规则扫描数据

两种方式调用:
1. 手动: python alerts.py
2. 定时: 接入APScheduler或cron
"""

import asyncio
import json
import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from database import get_session_factory

logger = logging.getLogger(__name__)


async def run_all_alerts():
    """运行所有预警检查"""
    factory = get_session_factory()
    async with factory() as db:
        # 加载预警规则
        result = await db.execute(
            select(m.KnowledgeEntry).where(
                m.KnowledgeEntry.entry_type == "ALERT",
                m.KnowledgeEntry.is_active == True,
            )
        )
        rules = result.scalars().all()

        alerts = []
        for rule in rules:
            title = rule.title
            if "信用额度" in title:
                alerts.extend(await check_credit_alerts(db))
            elif "应收" in title and "逾期" in title:
                alerts.extend(await check_ar_overdue(db))
            elif "交期" in title or "延误" in title:
                alerts.extend(await check_delivery_delay(db))
            elif "合同" in title and "到期" in title:
                alerts.extend(await check_contract_expiry(db))

        return alerts


async def check_credit_alerts(db: AsyncSession) -> list:
    """供应商信用额度预警"""
    result = await db.execute(select(m.SupplierCredit).where(m.SupplierCredit.warning_threshold_pct > 0))
    alerts = []
    for sc in result.scalars().all():
        if sc.credit_limit > 0:
            usage = float(sc.used_amount) / float(sc.credit_limit) * 100
            if usage >= sc.warning_threshold_pct:
                alerts.append({
                    "type": "CREDIT_WARNING",
                    "level": "HIGH" if usage >= 95 else "MEDIUM",
                    "message": f"供应商ID={sc.supplier_id} 信用额度使用率 {usage:.1f}%",
                    "data": {"supplier_id": sc.supplier_id, "usage_pct": round(usage, 1),
                            "limit": float(sc.credit_limit), "used": float(sc.used_amount)},
                })
    return alerts


async def check_ar_overdue(db: AsyncSession) -> list:
    """应收账款逾期预警"""
    today = date.today()
    result = await db.execute(
        select(m.AccountsReceivable).where(
            m.AccountsReceivable.status.in_(["PENDING", "PARTIAL"]),
            m.AccountsReceivable.due_date < today,
        )
    )
    alerts = []
    for ar in result.scalars().all():
        days_overdue = (today - ar.due_date).days
        alerts.append({
            "type": "AR_OVERDUE",
            "level": "HIGH" if days_overdue > 30 else "MEDIUM",
            "message": f"应收 {ar.invoice_number} 逾期 {days_overdue} 天，金额 {ar.amount} {ar.currency}",
            "data": {"ar_id": ar.id, "invoice": ar.invoice_number, "days_overdue": days_overdue,
                    "amount": float(ar.amount), "currency": ar.currency},
        })
    return alerts


async def check_delivery_delay(db: AsyncSession) -> list:
    """采购交期延误预警"""
    today = date.today()
    result = await db.execute(
        select(m.PurchaseOrder).where(
            m.PurchaseOrder.status == "ORDERED",
            m.PurchaseOrder.expected_delivery_date < today,
        )
    )
    alerts = []
    for po in result.scalars().all():
        days_late = (today - po.expected_delivery_date).days
        alerts.append({
            "type": "DELIVERY_DELAY",
            "level": "HIGH" if days_late > 14 else "MEDIUM",
            "message": f"采购 {po.order_number} 延迟 {days_late} 天未到货",
            "data": {"po_id": po.id, "order_number": po.order_number, "days_late": days_late},
        })
    return alerts


async def check_contract_expiry(db: AsyncSession) -> list:
    """框架合同到期预警"""
    today = date.today()
    threshold = today + timedelta(days=60)
    result = await db.execute(
        select(m.FrameworkContract).where(
            m.FrameworkContract.status == "ACTIVE",
            m.FrameworkContract.end_date <= threshold,
        )
    )
    alerts = []
    for fc in result.scalars().all():
        days_left = (fc.end_date - today).days
        alerts.append({
            "type": "CONTRACT_EXPIRY",
            "level": "HIGH" if days_left <= 14 else "MEDIUM",
            "message": f"框架合同 {fc.contract_number} 距到期还有 {days_left} 天",
            "data": {"contract_id": fc.id, "contract_number": fc.contract_number, "days_left": days_left},
        })
    return alerts


if __name__ == "__main__":
    alerts = asyncio.run(run_all_alerts())
    print(f"扫描完成，发现 {len(alerts)} 条预警:")
    for a in alerts:
        print(f"  [{a['level']}] {a['type']}: {a['message']}")
