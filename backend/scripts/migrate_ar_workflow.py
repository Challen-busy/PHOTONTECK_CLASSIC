"""
定向迁移：把"应收款管理流程" (ACCOUNTS_RECEIVABLE) 的流程定义更新为 12 节点版本，
并把存量单据的旧状态码迁移到新状态码。

只动 WorkflowDefinition.states 和 accounts_receivable.status，不破坏业务字段。幂等。

用法（在 backend/ 下）:
    python -m scripts.migrate_ar_workflow
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select, update

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import get_session_factory
import models as m


T = ["query_data", "calculate", "compare", "aggregate"]


RAW_AR = {
    "doc_type": "ACCOUNTS_RECEIVABLE",
    "name": "应收款管理流程",
    "description": (
        "参考K3应收管理流程图。主路径：信用管理→合同→发票→收款→凭证处理→期末处理。"
        "外部联动：销售管理触发开票；现金管理/应收票据触发收款；凭证处理输出至总账。"
        "旁支：发票/收款 → 坏账管理；收款 → 到款结算（明细核销）。"
        "报表：应收款明细表/汇总表、账龄分析、往来对账单、到期债权列表、到期债权分析、回款分析、合同金额执行汇总表、合同到期欠款明细表、信用额度分析。"
    ),
    "states": [
        {"code": "CREDIT_MANAGED", "name": "信用管理", "is_initial": True},
        {"code": "CONTRACT_REGISTERED", "name": "合同", "is_initial": True},
        {"code": "SALES_MGMT", "name": "销售管理", "is_initial": True},
        {"code": "CASH_MGMT", "name": "现金管理", "is_initial": True},
        {"code": "NOTES_RECV", "name": "应收票据", "is_initial": True},
        {"code": "INVOICED", "name": "发票"},
        {"code": "COLLECTING", "name": "收款"},
        {"code": "BAD_DEBT", "name": "坏账管理", "is_terminal": True},
        {"code": "SETTLED", "name": "到款结算", "is_terminal": True},
        {"code": "VOUCHER_PROCESSED", "name": "凭证处理"},
        {"code": "GL_LINK", "name": "总账", "is_terminal": True},
        {"code": "CLOSED", "name": "期末处理", "is_terminal": True},
    ],
    "transitions": [
        ("信用审核通过", "CREDIT_MANAGED", "CONTRACT_REGISTERED", ["FINANCE"], ["customer_id"], "维护客户信用额度/账期/评级（在customer_credit表）。审核通过后允许签订合同。", T),
        ("基于合同开票", "CONTRACT_REGISTERED", "INVOICED", ["FINANCE"], ["contract_id", "invoice_number", "amount", "due_date"], "根据销售合同开具发票。选合同、填发票号、金额、到期日。", T),
        ("销售订单触发开票", "SALES_MGMT", "INVOICED", ["FINANCE", "SALES_ASSISTANT"], ["sales_order_id", "invoice_number", "amount", "due_date"], "销售管理模块联动：销售出库后生成发票。关联销售订单。", T),
        ("登记收款", "INVOICED", "COLLECTING", ["FINANCE"], [], "发票开具后进入收款流程。", []),
        ("发票转坏账", "INVOICED", "BAD_DEBT", ["FINANCE", "BOSS"], [], "客户违约或破产，发票直接确认坏账。需老板审批。", []),
        ("现金到账", "CASH_MGMT", "COLLECTING", ["FINANCE"], ["paid_amount", "paid_date"], "现金管理模块联动：银行/现金收到客户款项（bank_receipt表登记流水）。", T),
        ("票据到账", "NOTES_RECV", "COLLECTING", ["FINANCE"], ["paid_amount", "paid_date"], "应收票据模块联动：商业汇票/银行承兑到期收款（notes_receivable表登记票据）。", T),
        ("到款结算", "COLLECTING", "SETTLED", ["FINANCE"], ["settlement_batch_no"], "针对收到的款项进行明细核销和结算处理（ar_settlement表生成核销明细）。填核销批号。", T),
        ("生成凭证", "COLLECTING", "VOUCHER_PROCESSED", ["FINANCE"], [], "生成收款记账凭证（借银行存款，贷应收账款）。hook自动创建voucher+分录并关联。", T),
        ("传入总账", "VOUCHER_PROCESSED", "GL_LINK", ["FINANCE"], [], "凭证传入总账模块，更新应收科目余额（通过voucher.status=POSTED体现）。", T),
        ("期末处理", "VOUCHER_PROCESSED", "CLOSED", ["FINANCE", "BOSS"], [], "月末/年末结账。应收科目余额结转下期。", T),
    ],
    "initial_roles": ["FINANCE"],
    "initial_extra_fields": ["customer_id", "sales_order_id", "contract_id", "invoice_number", "amount", "currency", "due_date"],
}


# 旧状态码 → 新状态码（保留单据存活）
STATUS_MIGRATION = {
    "PENDING": "COLLECTING",
    "PARTIAL": "COLLECTING",
    "PAID": "COLLECTING",
    "OVERDUE": "COLLECTING",
}


def build_states(raw: dict) -> list[dict]:
    """复刻 seed.py 的 raw_states→new_states 转换逻辑（含 START 注入和 initial 字段合并）。"""
    raw_states = raw["states"]
    transitions = raw["transitions"]
    initial_extra_fields = raw.get("initial_extra_fields", [])
    initial_roles = raw.get("initial_roles", [])

    terminal_codes = {s["code"] for s in raw_states if s.get("is_terminal")}

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
            for tname, to, _, _, t_prompt, _ in actions:
                desc_lines.append(f"- 【{tname} → {to}】{t_prompt or ''}")
        description = "\n".join(desc_lines)

        next_list = []
        for tname, to, t_roles, t_edit, _, _ in actions:
            edit_fields = set(t_edit or [])
            if s_def.get("is_initial") and to not in terminal_codes:
                edit_fields.update(initial_extra_fields)
            entry = {
                "to": to,
                "label": tname,
                "editable_fields": sorted(edit_fields),
            }
            if t_roles and set(t_roles) != roles_union:
                entry["roles"] = list(t_roles)
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
        # 1. 更新流程定义
        result = await db.execute(
            select(m.WorkflowDefinition).where(m.WorkflowDefinition.doc_type == RAW_AR["doc_type"])
        )
        wf = result.scalar_one_or_none()
        new_states = build_states(RAW_AR)
        if wf is None:
            print(f"  [新建] {RAW_AR['doc_type']}")
            db.add(m.WorkflowDefinition(
                doc_type=RAW_AR["doc_type"], name=RAW_AR["name"], description=RAW_AR["description"],
                states=new_states, group_name="财务",
                is_published=True, is_active=True,
            ))
        else:
            print(f"  [更新流程] {RAW_AR['doc_type']} — {RAW_AR['name']}")
            wf.name = RAW_AR["name"]
            wf.description = RAW_AR["description"]
            wf.states = new_states
            wf.is_published = True
            wf.is_active = True

        # 2. 迁移存量单据 status
        for old, new in STATUS_MIGRATION.items():
            res = await db.execute(
                update(m.AccountsReceivable)
                .where(m.AccountsReceivable.status == old)
                .values(status=new)
            )
            if res.rowcount:
                print(f"  [迁移单据] status: {old} -> {new}, {res.rowcount} 条")

        await db.commit()
        print("完成。")


if __name__ == "__main__":
    asyncio.run(migrate())
