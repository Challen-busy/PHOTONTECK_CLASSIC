"""补种第一期 CRM/WMS/ERP 打通流程。

在 backend/ 下执行:
    python -m scripts.seed_phase1
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from services.phase1_workflows import phase1_workflow_definitions


async def seed_phase1():
    factory = get_session_factory()
    async with factory() as db:
        admin = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "admin"))).scalar_one_or_none()
        created_by_id = admin.id if admin else None

        for wf_def in phase1_workflow_definitions(created_by_id):
            existing = (
                await db.execute(
                    select(m.WorkflowDefinition).where(
                        m.WorkflowDefinition.doc_type == wf_def["doc_type"],
                        m.WorkflowDefinition.version == wf_def.get("version", 1),
                    )
                )
            ).scalar_one_or_none()
            if existing:
                existing.name = wf_def["name"]
                existing.description = wf_def["description"]
                existing.states = wf_def["states"]
                existing.group_name = wf_def["group_name"]
                existing.is_published = True
                existing.is_active = True
                existing.node_positions = wf_def.get("node_positions") or {}
            else:
                db.add(m.WorkflowDefinition(**wf_def))

        await db.commit()
        print("第一期 CRM/WMS/ERP 流程已补种。")


if __name__ == "__main__":
    asyncio.run(seed_phase1())
