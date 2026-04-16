"""
定向迁移：把总账主流程 (VOUCHER) 的流程定义更新为 K3 流程图对齐版本。
变更：删除冲销、账簿/财报查询改 cross_module 终态、新增 7 个报表节点、新增布局坐标。

只动 WorkflowDefinition.states / node_positions，不碰业务单据。幂等。

用法（在 backend/ 下）:
    python -m scripts.migrate_gl_workflows
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import get_session_factory
import models as m


T = ["query_data", "calculate", "compare", "aggregate"]


# ============================================================
# 原始流程定义（raw）—— 与 seed.py 保持同步
# ============================================================

RAW_VOUCHER = {
    "doc_type": "VOUCHER",
    "name": "总账流程-主流程",
    "description": (
        "严格按K3总账流程图主流程：科目→凭证录入→凭证审核→凭证过账→期末调汇→结转损益→期末结账。"
        "分支：过账后可做往来管理；过账后可查询账簿和财务报表。"
        "支持手工录入和业务自动生成。"
    ),
    "states": [
        {"code": "ACCOUNT_READY", "name": "科目", "is_initial": True},
        {"code": "DRAFT", "name": "凭证录入"},
        {"code": "AUDITED", "name": "凭证审核"},
        {"code": "POSTED", "name": "凭证过账"},
        {"code": "RECONCILED", "name": "往来管理"},
        {"code": "FX_ADJUSTED", "name": "期末调汇"},
        {"code": "PL_TRANSFERRED", "name": "结转损益"},
        {"code": "CLOSED", "name": "期末结账", "is_terminal": True},
        {"code": "LEDGER_QUERIED", "name": "账簿查询", "is_terminal": True, "node_type": "cross_module"},
        {"code": "REPORT_QUERIED", "name": "财务报表查询", "is_terminal": True, "node_type": "cross_module"},
        {"code": "RPT_GENERAL_LEDGER", "name": "总分类账", "node_type": "report"},
        {"code": "RPT_DETAIL_LEDGER", "name": "明细分类账", "node_type": "report"},
        {"code": "RPT_MULTI_COL", "name": "多栏账", "node_type": "report"},
        {"code": "RPT_PROJECT_DETAIL", "name": "核算项目明细账", "node_type": "report"},
        {"code": "RPT_PROJECT_BALANCE", "name": "核算项目余额表", "node_type": "report"},
        {"code": "RPT_TRIAL_BALANCE", "name": "试算平衡表", "node_type": "report"},
        {"code": "RPT_ACCOUNT_BALANCE", "name": "科目余额表", "node_type": "report"},
    ],
    "transitions": [
        ("启用科目", "ACCOUNT_READY", "DRAFT", ["FINANCE"], [], "会计科目已设置完成，可以开始录入凭证。", []),
        ("提交审核", "DRAFT", "AUDITED", ["FINANCE"], [], "检查借贷是否平衡、金额>0、科目是否为明细科目。", T),
        ("审核退回", "AUDITED", "DRAFT", ["FINANCE"], [], "退回修改。说明退回原因。", []),
        ("审核过账", "AUDITED", "POSTED", ["FINANCE", "BOSS"], [], "过账更新科目余额。过账后凭证不可修改。", T),
        ("往来核对", "POSTED", "RECONCILED", ["FINANCE"], [], "往来管理：与客户/供应商对账，核对应收应付余额。", T),
        ("往来转调汇", "RECONCILED", "FX_ADJUSTED", ["FINANCE"], [], "往来核对完成进入期末调汇。", T),
        ("查询账簿", "POSTED", "LEDGER_QUERIED", ["FINANCE", "BOSS"], [], "查询总分类账/明细分类账/多栏账/核算项目账等账簿视图。", T),
        ("查询财报", "POSTED", "REPORT_QUERIED", ["FINANCE", "BOSS"], [], "查询试算平衡表/科目余额表等财务报表。", T),
        ("过账直接调汇", "POSTED", "FX_ADJUSTED", ["FINANCE"], [], "凭证过账完成后进入期末调汇（多币种汇率调整，生成调汇差额凭证）。", T),
        ("结转损益", "FX_ADJUSTED", "PL_TRANSFERRED", ["FINANCE"], [], "收入类和费用类科目余额结转到本年利润。收入费用科目清零。", T),
        ("期末结账", "PL_TRANSFERRED", "CLOSED", ["FINANCE", "BOSS"], [], "关闭本会计期间。本期期末余额成为下期期初。结账后不可录入凭证。", T),
    ],
    "hard_rules": {
        ("DRAFT", "AUDITED"): [
            "sum(e.debit for e in entries) == sum(e.credit for e in entries)",
            "len(entries) >= 2",
        ],
        ("AUDITED", "POSTED"): [
            "lookup('accounting_period', id=doc.period_id).status == 'OPEN'",
        ],
    },
    "hooks": {
        ("AUDITED", "POSTED"): [
            "for e in entries:\n"
            "    bal = lookup('account_balance', account_id=e.account_id, period_id=doc.period_id, company_id=doc.company_id)\n"
            "    if bal:\n"
            "        update('account_balance', {'id': bal.id}, {\n"
            "            'period_debit': float(bal.period_debit) + float(e.debit),\n"
            "            'period_credit': float(bal.period_credit) + float(e.credit),\n"
            "            'closing_debit': float(bal.closing_debit) + float(e.debit),\n"
            "            'closing_credit': float(bal.closing_credit) + float(e.credit),\n"
            "        })\n"
            "    else:\n"
            "        insert('account_balance', {\n"
            "            'company_id': doc.company_id,\n"
            "            'account_id': e.account_id,\n"
            "            'period_id': doc.period_id,\n"
            "            'period_debit': e.debit,\n"
            "            'period_credit': e.credit,\n"
            "            'closing_debit': e.debit,\n"
            "            'closing_credit': e.credit,\n"
            "        })"
        ],
    },
    "node_positions": {
        "START": {"x": 120, "y": 0},
        "ACCOUNT_READY": {"x": 120, "y": 100},
        "DRAFT": {"x": 300, "y": 100},
        "AUDITED": {"x": 300, "y": 230},
        "POSTED": {"x": 300, "y": 370},
        "FX_ADJUSTED": {"x": 300, "y": 530},
        "PL_TRANSFERRED": {"x": 300, "y": 660},
        "CLOSED": {"x": 300, "y": 790},
        "RECONCILED": {"x": 80, "y": 370},
        "LEDGER_QUERIED": {"x": 550, "y": 330},
        "REPORT_QUERIED": {"x": 550, "y": 430},
        "RPT_GENERAL_LEDGER": {"x": 780, "y": 100},
        "RPT_DETAIL_LEDGER": {"x": 780, "y": 190},
        "RPT_MULTI_COL": {"x": 780, "y": 280},
        "RPT_PROJECT_DETAIL": {"x": 780, "y": 370},
        "RPT_PROJECT_BALANCE": {"x": 780, "y": 460},
        "RPT_TRIAL_BALANCE": {"x": 780, "y": 550},
        "RPT_ACCOUNT_BALANCE": {"x": 780, "y": 640},
    },
    "initial_roles": ["FINANCE"],
}

# ============================================================
# raw → states JSONB（对齐 seed.py 的 B 模型 START 注入）
# ============================================================

def build_states(raw: dict) -> list[dict]:
    """复刻 seed.py 的 raw_states->new_states 转换逻辑，支持 node_type。"""
    raw_states = raw["states"]
    transitions = raw["transitions"]
    hard_rules = raw.get("hard_rules", {})
    hooks = raw.get("hooks", {})
    initial_roles = raw.get("initial_roles", [])

    new_states = []
    for s_def in raw_states:
        code = s_def["code"]
        actions = [(t[0], t[2], t[3], t[4], t[5], t[6]) for t in transitions if t[1] == code]
        roles_union = set()
        for _, _, t_roles, _, _, _ in actions:
            roles_union.update(t_roles or [])
        if s_def.get("is_initial"):
            roles_union.update(initial_roles)

        desc_lines = []
        if actions:
            desc_lines.append(f"# {s_def.get('name', code)} 节点")
            for tname, to, _, _, prompt, _ in actions:
                desc_lines.append(f"- 【{tname} -> {to}】{prompt or ''}")
        description = "\n".join(desc_lines)

        next_list = []
        for tname, to, t_roles, t_edit, _, _ in actions:
            entry = {
                "to": to,
                "label": tname,
                "editable_fields": sorted(set(t_edit or [])),
            }
            if t_roles and set(t_roles) != roles_union:
                entry["roles"] = list(t_roles)
            if (code, to) in hard_rules:
                entry["hard_rules"] = hard_rules[(code, to)]
            if (code, to) in hooks:
                entry["hooks"] = hooks[(code, to)]
            next_list.append(entry)

        new_state = {
            "code": code,
            "name": s_def.get("name", code),
            "allowed_roles": sorted(roles_union),
            "description": description,
            "custom_html": "",
            "hard_rules": [],
            "next": next_list,
        }
        if s_def.get("is_terminal"):
            new_state["is_terminal"] = True
        if s_def.get("node_type"):
            new_state["node_type"] = s_def["node_type"]
        new_states.append(new_state)

    # 注入 START
    old_initial_codes = [s["code"] for s in raw_states if s.get("is_initial")]
    if old_initial_codes:
        start_state = {
            "code": "START",
            "name": "开始",
            "is_initial": True,
            "allowed_roles": sorted(initial_roles),
            "description": "# 开始节点\n点「开始」按钮创建空单据，进入首个业务节点录入数据。",
            "custom_html": "",
            "hard_rules": [],
            "hooks": [],
            "next": [{"to": c, "label": "开始", "editable_fields": []} for c in old_initial_codes],
        }
        new_states.insert(0, start_state)
    return new_states


async def migrate():
    factory = get_session_factory()
    async with factory() as db:
        raw = RAW_VOUCHER
        result = await db.execute(
            select(m.WorkflowDefinition).where(m.WorkflowDefinition.doc_type == raw["doc_type"])
        )
        wf = result.scalar_one_or_none()
        new_states = build_states(raw)
        positions = raw.get("node_positions", {})
        if wf is None:
            print(f"  [新建] {raw['doc_type']}")
            db.add(m.WorkflowDefinition(
                doc_type=raw["doc_type"], name=raw["name"], description=raw["description"],
                states=new_states, group_name="财务",
                is_published=True, is_active=True,
                node_positions=positions,
            ))
        else:
            print(f"  [更新] {raw['doc_type']} -- {raw['name']}")
            wf.name = raw["name"]
            wf.description = raw["description"]
            wf.states = new_states
            wf.node_positions = positions
            wf.is_published = True
            wf.is_active = True
        await db.commit()
        print("完成。")


if __name__ == "__main__":
    asyncio.run(migrate())
