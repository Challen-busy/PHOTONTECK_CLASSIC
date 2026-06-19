"""信用管理（finance-gl 信用波）种子（幂等，可重复跑）。

在 backend/ 下执行（须先 alembic upgrade head 到 x8y9z0a1）:
    DATABASE_URL=postgresql+asyncpg://...:5433/... python -m scripts.seed_credit

两件事:
A. CREDIT_CHECK_RULE 信用检查规则：单状态 ACTIVE 自环编辑 WorkflowDefinition（MasterDataPage，照 master_data 范式）。
B. 逐公司种一条默认信用检查规则（DEFAULT，应收单·审核时点·提示策略·检查信用额度）+ 明细行。
   ★信用控制总开关 company.credit_control_enabled 默认关（金蝶口径「需先启用信用控制」），不在此自动开。

引擎五条不破坏：纯数据 + WorkflowDefinition（JSONB）。核心三件零 diff。
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from services.master_data_workflows import _active_only_states

_FIN_ROLES = ["ADMIN", "FINANCE", "FINANCE_DIRECTOR"]
_CHECK_RULE_FIELDS = ["code", "name", "is_default", "is_active", "remark"]


async def _get(db, model, **filters):
    stmt = select(model)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalars().first()


async def seed_credit():
    factory = get_session_factory()
    async with factory() as db:
        admin = await _get(db, m.UserAccount, username="admin")
        created_by_id = admin.id if admin else None

        # === A. WorkflowDefinition CREDIT_CHECK_RULE（单态 ACTIVE）===
        wf_def = {
            "doc_type": "CREDIT_CHECK_RULE",
            "name": "信用检查规则",
            "description": (
                "# 信用检查规则\n金蝶信用政策：定义哪些单据在哪个时点占用/检查信用额度、用什么控制策略"
                "（不控/提示/严格控制）。信用档案引用本规则；应收单审核时由 finance_credit validator 据此校验可用额度。"
            ),
            "group_name": "财务基础资料",
            "version": 1,
            "is_published": True, "is_active": True,
            "states": _active_only_states(_FIN_ROLES, _CHECK_RULE_FIELDS),
        }
        if created_by_id is not None:
            wf_def["created_by_id"] = created_by_id
        existing = (await db.execute(
            select(m.WorkflowDefinition).where(
                m.WorkflowDefinition.doc_type == "CREDIT_CHECK_RULE",
                m.WorkflowDefinition.version == 1,
            )
        )).scalar_one_or_none()
        wf_new = wf_upd = 0
        if existing:
            existing.name = wf_def["name"]; existing.description = wf_def["description"]
            existing.states = wf_def["states"]; existing.group_name = wf_def["group_name"]
            existing.is_published = True; existing.is_active = True
            wf_upd += 1
        else:
            db.add(m.WorkflowDefinition(**wf_def)); wf_new += 1
        await db.flush()

        # === B. 逐公司默认检查规则 + 明细行 ===
        companies = (await db.execute(select(m.Company))).scalars().all()
        rule_new = line_new = 0
        for company in companies:
            cid = company.id
            rule = await _get(db, m.CreditCheckRule, company_id=cid, code="DEFAULT")
            if rule is None:
                rule = m.CreditCheckRule(
                    company_id=cid, code="DEFAULT", name="默认信用检查规则",
                    is_default=True, is_active=True, created_by_id=created_by_id,
                    remark="应收单审核时检查信用额度（提示策略）。可改严格控制 STRICT 阻断。",
                )
                db.add(rule)
                await db.flush()
                rule_new += 1
            # 明细行：应收单·审核·提示·检查信用额度（占用）
            line = await _get(db, m.CreditCheckRuleLine, credit_check_rule_id=rule.id, doc_type="ACCOUNTS_RECEIVABLE")
            if line is None:
                db.add(m.CreditCheckRuleLine(
                    credit_check_rule_id=rule.id, line_number=1,
                    doc_name="应收单", doc_type="ACCOUNTS_RECEIVABLE",
                    check_point="AUDIT", control_strategy="WARN",
                    update_credit=True, check_credit_limit=True,
                    check_single_limit=False, check_overdue=False,
                ))
                line_new += 1
        await db.flush()
        await db.commit()

        print("信用管理种子完成:")
        print(f"  A. WorkflowDefinition CREDIT_CHECK_RULE: 新建 {wf_new} / 覆盖 {wf_upd}")
        print(f"  B. 默认检查规则: 新增 {rule_new} 条 + 明细 {line_new} 行（{len(companies)} 公司）")
        print(f"     ★信用控制总开关默认关（company.credit_control_enabled=false），需逐公司启用后 validator 才生效。")


if __name__ == "__main__":
    asyncio.run(seed_credit())
