"""总账·第七波（finance-gl wave-7）合并报表种子（幂等，可重复跑）。

在 backend/ 下执行（须先 alembic upgrade head 到 u5v6w7x8，且先跑过 scripts.seed）:
    DATABASE_URL=postgresql+asyncpg://...:5433/... python -m scripts.seed_consolidation

本脚本两件事（均幂等 upsert，已存在跳过/覆盖）:

A. 为合并报表 2 个 doc_type 各种一个最小 WorkflowDefinition（照 CUSTOMER 范式：单状态 ACTIVE
   自环编辑，复用 services.master_data_workflows._active_only_states），使前端 MasterDataPage 可建/改:
   - CONSOLIDATION_GROUP 合并范围（+ 子表 consolidation_member 成员，随 sub_updates 提交）。
   - ELIMINATION_ENTRY 抵消分录。
   按 (doc_type, version=1) upsert。

B. 种 2 个示例合并范围（主导/创建公司=PTK；成员跨公司）:
   - CG-ALL 全集团：成员 = PTK/ADS/FTK/RJ/XGTC/TR（6 公司），列报币 CNY、准则 CAS。
   - CG-HK  香港组：成员 = PTK/ADS/FTK（HK 三家），列报币 HKD、准则 HKFRS。
   成员经子表 consolidation_member 跨公司挂入（ownership_pct 默认 100）。

引擎五条不破坏：纯数据 + WorkflowDefinition（JSONB），写仍走 execute_transition。核心三件零 diff。
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

# 合并报表 doc_type 轻量建档状态机（doc_type → 中文名 / 维护角色 / 可建档字段 / 分组）。
# 可建档字段严格对齐 models.py 列名（不含 id/company_id/审计列，由引擎/AuditMixin 维护）。
CONSOLIDATION_SPECS = [
    ("CONSOLIDATION_GROUP", "合并范围", _FIN_ROLES, [
        "code", "name", "presentation_currency", "standard", "description", "is_active",
    ], "财务基础资料"),
    ("ELIMINATION_ENTRY", "抵消分录", _FIN_ROLES, [
        "group_id", "period_year", "period_number", "statement", "line_key",
        "account_code", "debit", "credit", "memo", "is_active",
    ], "财务基础资料"),
]

# 合并范围成员子表可编辑字段（MasterDataPage 内嵌网格随 sub_updates 提交）。
CONSOLIDATION_MEMBER_FIELDS = [
    "member_company_id", "ownership_pct", "is_active",
]

# 2 个示例合并范围。(code, name, presentation_currency, standard, member_company_codes)
CONSOLIDATION_GROUPS = [
    ("CG-ALL", "全集团合并", "CNY", "CAS", ["PTK", "ADS", "FTK", "RJ", "XGTC", "TR"]),
    ("CG-HK", "香港组合并", "HKD", "HKFRS", ["PTK", "ADS", "FTK"]),
]


def consolidation_workflow_definitions(created_by_id=None):
    """返回可直接传给 m.WorkflowDefinition(**kwargs) 的轻量建档流程列表（合并报表 doc_type）。"""
    defs = []
    for doc_type, name, roles, fields, group in CONSOLIDATION_SPECS:
        defs.append({
            "doc_type": doc_type,
            "name": name,
            "description": f"# {name}\n合并报表配置主数据轻量建档状态机（单状态 ACTIVE，无审批/无财务关卡，自环编辑）。",
            "states": _active_only_states(roles, fields),
            "group_name": group,
            "version": 1,
            "is_published": True,
            "is_active": True,
            "created_by_id": created_by_id,
        })
    return defs


async def _get(db, model, **filters):
    stmt = select(model)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalars().first()


async def seed_consolidation():
    factory = get_session_factory()
    async with factory() as db:
        admin = await _get(db, m.UserAccount, username="admin")
        created_by_id = admin.id if admin else None

        # === A. 合并报表 doc_type 轻量建档状态机（按 (doc_type, version) upsert）===
        wf_actions = {"new": 0, "updated": 0}
        for wf_def in consolidation_workflow_definitions(created_by_id):
            existing = (await db.execute(
                select(m.WorkflowDefinition).where(
                    m.WorkflowDefinition.doc_type == wf_def["doc_type"],
                    m.WorkflowDefinition.version == wf_def["version"],
                )
            )).scalar_one_or_none()
            if existing:
                existing.name = wf_def["name"]
                existing.description = wf_def["description"]
                existing.states = wf_def["states"]
                existing.group_name = wf_def["group_name"]
                existing.is_published = True
                existing.is_active = True
                wf_actions["updated"] += 1
            else:
                db.add(m.WorkflowDefinition(**wf_def))
                wf_actions["new"] += 1
        await db.flush()

        # === B. 2 个示例合并范围（主导/创建公司 = PTK；成员跨公司）===
        companies = (await db.execute(select(m.Company))).scalars().all()
        by_code = {c.code: c for c in companies}
        host = by_code.get("PTK")
        if host is None:
            print("未找到 PTK 公司（主导/创建公司），请先跑 scripts.seed。")
            return

        group_counts = {"group_new": 0, "member_new": 0, "skipped": 0}
        for code, name, pres_ccy, standard, member_codes in CONSOLIDATION_GROUPS:
            grp = await _get(db, m.ConsolidationGroup, company_id=host.id, code=code)
            if grp is None:
                grp = m.ConsolidationGroup(
                    company_id=host.id, code=code, name=name,
                    presentation_currency=pres_ccy, standard=standard,
                    description=f"{name}（示例合并范围，半自动手工合并）",
                    is_active=True, created_by_id=created_by_id,
                )
                db.add(grp)
                await db.flush()
                group_counts["group_new"] += 1
            else:
                group_counts["skipped"] += 1
            # 成员（幂等：(group_id, member_company_id) 唯一）。
            for mcode in member_codes:
                mc = by_code.get(mcode)
                if mc is None:
                    continue
                existing_mem = await _get(
                    db, m.ConsolidationMember, group_id=grp.id, member_company_id=mc.id)
                if existing_mem is None:
                    db.add(m.ConsolidationMember(
                        group_id=grp.id, member_company_id=mc.id,
                        ownership_pct=100, is_active=True,
                    ))
                    group_counts["member_new"] += 1
        await db.flush()

        await db.commit()

        print("总账·第七波合并报表种子完成:")
        print(f"  A. 合并报表建档状态机: 新建 {wf_actions['new']} / 覆盖 {wf_actions['updated']}"
              f"（共 {len(CONSOLIDATION_SPECS)} 个 doc_type）")
        print(f"  B. 示例合并范围: 新建 {group_counts['group_new']} 个组（已存在跳过 {group_counts['skipped']}），"
              f"新增成员 {group_counts['member_new']} 条")


if __name__ == "__main__":
    asyncio.run(seed_consolidation())
