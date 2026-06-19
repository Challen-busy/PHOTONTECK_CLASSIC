"""应付款管理（finance-gl 应付波）种子（幂等，可重复跑）。= seed_receivable 的供应商侧镜像。

在 backend/ 下执行（须先 alembic upgrade head 到 w7x8y9z0，且先跑过 scripts.seed / seed_finance / seed_receivable）:
    DATABASE_URL=postgresql+asyncpg://...:5433/... python -m scripts.seed_payable

四件事（均幂等 upsert）:

A. 为应付款管理 2 个 doc_type 种 WorkflowDefinition:
   - ACCOUNTS_PAYABLE 应付单：START → DRAFT 暂存 → SUBMITTED 提交 → AUDITED 审核。
     ★审核（SUBMITTED→AUDITED）边挂 effects=["finance.create_voucher_from_ap_bill"]（services.ap_payable 已注册）。
     version=2 升级覆盖既有存根 v1（旧版历史单不受影响，保唯一 active）。
   - AP_PAYMENT 付款单：START → DRAFT → AUDITED；审核边挂 ["finance.create_voucher_from_ap_payment"]。
   核销方案 WRITEOFF_SCHEME 的 WFD 已由 seed_receivable 种好（biz_type 通用），此处不再建。

B. 编号规则 NumberingRule（应付单 AP-YYMM-NNN / 付款单 FK-YYMM-NNN，月度重置），逐公司种入。

C. 核销方案 WriteoffScheme（biz_type=AP：FIFO 默认 + 同金额 + 按到期日 + 手工），逐公司种入。

D. 业财映射规则 AccountMappingRule（应付单/付款单审核 → 凭证，6 家按准则取本家科目码）:
   - 应付单（ACCOUNTS_PAYABLE，trigger=AUDITED）:
       CAS：借 1402 在途物资 / 借 222101 进项税 / 贷 2202 应付账款。
       HKFRS：借 1212 在途存货 / 贷 2202 应付账款（无进项税）。
   - 付款单（AP_PAYMENT，trigger=AUDITED）：贷 1002 银行 + 借 2202 应付（冲减）/ 借 1123 预付（预付，按 is_advance 选行）。

引擎五条不破坏：纯数据 + WorkflowDefinition（JSONB），写仍走 execute_transition。核心三件零 diff。
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory

_FIN_ROLES = ["ADMIN", "FINANCE", "FINANCE_DIRECTOR"]
NUMBERING_EFFECT = "numbering.assign_business_number"

# ============================================================
# A. WorkflowDefinition
# ============================================================

# --- 应付单 ACCOUNTS_PAYABLE（START→DRAFT→SUBMITTED→AUDITED）---
_AP_BILL_HEAD_FIELDS = [
    "bill_number", "bill_type", "bill_date", "due_date",
    "supplier_id", "purchase_order_id",
    "currency", "exchange_rate", "base_currency", "base_amount",
    "amount", "untaxed_amount", "tax_amount",
    "payment_terms_text", "purchaser_id", "purchase_org_id", "settle_org_id", "purchase_dept",
    "is_tax_included", "is_price_tax_inclusive", "is_goods_first",
    "invoice_number", "remark",
]


def _ap_bill_states():
    return [
        {
            "code": "START", "name": "开始", "is_initial": True,
            "allowed_roles": _FIN_ROLES,
            "description": "# 开始节点\n建空应付单后进入「暂存」节点；建单同事务取应付单号 AP-YYMM-NNN。",
            "custom_html": "", "hard_rules": [], "hooks": [],
            "effects": [NUMBERING_EFFECT],
            "next": [{"to": "DRAFT", "label": "新建", "editable_fields": []}],
        },
        {
            "code": "DRAFT", "name": "暂存",
            "allowed_roles": _FIN_ROLES,
            "description": (
                "# 暂存（应付单录入）\n录入应付单头（供应商/币别/汇率/业务日期/到期日/立账类型[暂估/业务应付]/"
                "付款条件/采购员/采购组织/结算组织）与明细（物料×计价数量×单价×税率组×不含税/税额/价税合计）、"
                "付款计划（分期：到期日/比例/金额）。\n开关：价外税 / 按含税单价录入 / 先到票后入库。\n"
                "「提交」推进到已提交态。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "SUBMITTED", "label": "提交", "editable_fields": _AP_BILL_HEAD_FIELDS},
            ],
        },
        {
            "code": "SUBMITTED", "name": "已提交",
            "allowed_roles": _FIN_ROLES,
            "description": (
                "# 已提交\n等待财务审核。\n「审核」推进到已审核态——审核后业财映射生应付凭证"
                "（CAS 借 1402 在途物资 / 借 222101 进项税 / 贷 2202 应付账款；HK 准则无进项税则仅借在途/贷应付）。\n"
                "「撤回」退回暂存态修改。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "AUDITED", "label": "审核", "editable_fields": ["remark"],
                 "effects": ["finance.create_voucher_from_ap_bill"]},
                {"to": "DRAFT", "label": "撤回", "editable_fields": ["remark"]},
            ],
        },
        {
            "code": "AUDITED", "name": "已审核", "is_terminal": True,
            "allowed_roles": _FIN_ROLES,
            "description": (
                "# 已审核\n应付单成立（债务立账）。经通用核销引擎（WriteoffLink，biz_type=AP）与付款单勾稽，"
                "核销回写 written_off_amount / writeoff_status（UNVERIFIED/PARTIAL/VERIFIED）。\n"
                "「反审核」退回已提交态（若已生凭证须先红冲/反核销）。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "SUBMITTED", "label": "反审核", "editable_fields": ["remark"]},
            ],
        },
    ]


# --- 付款单 AP_PAYMENT（START→DRAFT→AUDITED）---
_AP_PAYMENT_HEAD_FIELDS = [
    "payment_number", "supplier_id", "payment_date",
    "currency", "exchange_rate", "base_currency", "base_amount", "amount",
    "settlement_method_id", "bank_account", "payee_name", "payment_purpose", "is_advance", "remark",
]


def _ap_payment_states():
    return [
        {
            "code": "START", "name": "开始", "is_initial": True,
            "allowed_roles": _FIN_ROLES,
            "description": "# 开始节点\n建空付款单后进入「暂存」节点；建单同事务取付款单号 FK-YYMM-NNN。",
            "custom_html": "", "hard_rules": [], "hooks": [],
            "effects": [NUMBERING_EFFECT],
            "next": [{"to": "DRAFT", "label": "新建", "editable_fields": []}],
        },
        {
            "code": "DRAFT", "name": "暂存",
            "allowed_roles": _FIN_ROLES,
            "description": (
                "# 暂存（付款单录入）\n录入供应商/币别/付款日期/结算方式/银行账户/金额/付款用途/是否预付。\n"
                "「审核」推进到已审核态——审核后业财映射生凭证（借 2202 应付<核销冲减>或 1123 预付<is_advance>"
                " / 贷 1002 银行存款）。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "AUDITED", "label": "审核", "editable_fields": _AP_PAYMENT_HEAD_FIELDS,
                 "effects": ["finance.create_voucher_from_ap_payment"]},
            ],
        },
        {
            "code": "AUDITED", "name": "已审核", "is_terminal": True,
            "allowed_roles": _FIN_ROLES,
            "description": (
                "# 已审核\n付款单成立（已付款）。经通用核销引擎（WriteoffLink，biz_type=AP）与应付单勾稽，"
                "核销回写 written_off_amount / writeoff_status。\n「反审核」退回暂存态。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "DRAFT", "label": "反审核", "editable_fields": ["remark"]},
            ],
        },
    ]


def payable_workflow_definitions(created_by_id=None):
    """返回可直接传给 m.WorkflowDefinition(**kwargs) 的流程列表（应付单/付款单）。"""
    defs = [
        {
            "doc_type": "ACCOUNTS_PAYABLE",
            "name": "应付单",
            "description": (
                "总账·应付波（finance-gl）应付款管理：应付单（供应商债务立账，完全替代金蝶应付单）。\n"
                "暂存 DRAFT → 提交 SUBMITTED → 审核 AUDITED；审核后业财映射生应付凭证；"
                "经通用核销引擎（WriteoffLink biz_type=AP）与付款单勾稽。= 应收单的供应商侧镜像。"
            ),
            "group_name": "财务",
            "version": 2,  # 升级覆盖既有存根 v1（旧版历史单不受影响）
            "is_published": True, "is_active": True,
            "node_positions": {
                "START": {"x": 300, "y": 0}, "DRAFT": {"x": 300, "y": 120},
                "SUBMITTED": {"x": 300, "y": 250}, "AUDITED": {"x": 300, "y": 390},
            },
            "states": _ap_bill_states(),
        },
        {
            "doc_type": "AP_PAYMENT",
            "name": "付款单",
            "description": (
                "总账·应付波（finance-gl）应付款管理：付款单（供应商实付款登记，完全替代金蝶付款单）。\n"
                "暂存 DRAFT → 审核 AUDITED；审核后业财映射生凭证；经通用核销引擎与应付单勾稽。= 收款单的供应商侧镜像。"
            ),
            "group_name": "财务",
            "version": 1,
            "is_published": True, "is_active": True,
            "node_positions": {
                "START": {"x": 300, "y": 0}, "DRAFT": {"x": 300, "y": 120},
                "AUDITED": {"x": 300, "y": 250},
            },
            "states": _ap_payment_states(),
        },
    ]
    if created_by_id is not None:
        for d in defs:
            d["created_by_id"] = created_by_id
    return defs


# ============================================================
# B. 编号规则（逐公司）
# ============================================================
NUMBERING_RULES = [
    ("ACCOUNTS_PAYABLE", "AP"),
    ("AP_PAYMENT", "FK"),
]

# ============================================================
# C. 核销方案种子（逐公司，biz_type=AP）
# ============================================================
WRITEOFF_SCHEMES_AP = [
    ("AP-FIFO", "应付-先进先出", "FIFO", 10, True),
    ("AP-SAME", "应付-同金额匹配", "SAME_AMOUNT", 20, False),
    ("AP-DUE", "应付-按到期日", "BY_DUEDATE", 30, False),
    ("AP-MANUAL", "应付-手工核销", "MANUAL", 90, False),
]

# ============================================================
# D. 业财映射规则（应付单/付款单审核 → 凭证，按公司 region 分准则）
# ============================================================
# 应付单 ACCOUNTS_PAYABLE（trigger=AUDITED）。services.ap_payable 按 dr_cr + account_code 取本行科目：
#   贷方=价税合计（应付）；借方=不含税（在途/采购）+ 税额（进项税，account_code==222101 识别）。
# (line_seq, dr_cr, account_code, account_source, memo_template)
CAS_AP_BILL_RULES = [
    (1, "DR", "1402",   "FIXED",    "采购入库—在途物资（{bill_number}）"),
    (2, "DR", "222101", "FIXED",    "应交增值税（进项税额）（{bill_number}）"),
    (3, "CR", "2202",   "SUPPLIER", "应付账款—{supplier}（{bill_number}）"),
]
HKFRS_AP_BILL_RULES = [
    (1, "DR", "1212", "FIXED",    "Goods in transit ({bill_number})"),
    (2, "CR", "2202", "SUPPLIER", "Trade payables - {supplier} ({bill_number})"),
]
# 付款单 AP_PAYMENT（trigger=AUDITED）：贷 1002 银行 + 借 2202 应付（冲减）/ 借 1123 预付
# （services.ap_payable 按 is_advance 在两条借方行里选一行；CAS/HKFRS 科目码同）。
AP_PAYMENT_RULES = [
    (1, "CR", "1002", "FIXED",    "付供应商款—{supplier}（{payment_number}）"),
    (2, "DR", "2202", "SUPPLIER", "冲减应付账款（{payment_number}）"),
    (3, "DR", "1123", "SUPPLIER", "预付账款（{payment_number}）"),
]


def _ap_bill_rules_for_region(region: str):
    return HKFRS_AP_BILL_RULES if region == "HK" else CAS_AP_BILL_RULES


async def _get(db, model, **filters):
    stmt = select(model)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalars().first()


async def seed_payable():
    factory = get_session_factory()
    async with factory() as db:
        admin = await _get(db, m.UserAccount, username="admin")
        created_by_id = admin.id if admin else None

        # === A. WorkflowDefinition（按 (doc_type, version) upsert，停用同 doc_type 其余版本保唯一 active）===
        wf_actions = {"new": 0, "updated": 0, "deactivated": 0}
        for wf_def in payable_workflow_definitions(created_by_id):
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
                existing.node_positions = wf_def.get("node_positions", {})
                existing.is_published = True
                existing.is_active = True
                wf_actions["updated"] += 1
            else:
                db.add(m.WorkflowDefinition(**wf_def))
                wf_actions["new"] += 1
            others = (await db.execute(
                select(m.WorkflowDefinition).where(
                    m.WorkflowDefinition.doc_type == wf_def["doc_type"],
                    m.WorkflowDefinition.version != wf_def["version"],
                    m.WorkflowDefinition.is_active == True,  # noqa: E712
                )
            )).scalars().all()
            for o in others:
                o.is_active = False
                wf_actions["deactivated"] += 1
        await db.flush()

        # === B + C + D. 逐公司：编号规则 + 核销方案 + 业财映射规则 ===
        companies = (await db.execute(select(m.Company))).scalars().all()
        nr_new = ws_new = mr_new = mr_skip = 0
        eff = date(date.today().year, 1, 1)
        for company in companies:
            cid = company.id
            # B. 编号规则
            for doc_type, prefix in NUMBERING_RULES:
                if await _get(db, m.NumberingRule, company_id=cid, doc_type=doc_type) is None:
                    db.add(m.NumberingRule(
                        company_id=cid, doc_type=doc_type, prefix=prefix,
                        reset_period="MONTH", seq_padding=3, separator="-", period_format="%y%m",
                        current_period="", current_seq=0, is_active=True,
                    ))
                    nr_new += 1
            # C. 核销方案（biz_type=AP）
            for code, name, rule, prio, is_default in WRITEOFF_SCHEMES_AP:
                if await _get(db, m.WriteoffScheme, company_id=cid, biz_type="AP", code=code) is None:
                    db.add(m.WriteoffScheme(
                        company_id=cid, code=code, name=name, biz_type="AP",
                        match_rule=rule, priority=prio, is_default=is_default,
                        is_active=True, created_by_id=created_by_id,
                    ))
                    ws_new += 1
            # D. 业财映射规则（应付单 + 付款单，trigger=AUDITED；按 region 分准则；目标科目须存在）
            ap_rule_specs = [
                ("ACCOUNTS_PAYABLE", _ap_bill_rules_for_region(company.region)),
                ("AP_PAYMENT", AP_PAYMENT_RULES),
            ]
            for source_doc_type, specs in ap_rule_specs:
                for line_seq, dr_cr, code, source, memo in specs:
                    if await _get(db, m.Account, company_id=cid, code=code) is None:
                        print(f"  [警告] 公司#{cid}({company.code}) 缺科目 {code}，跳过 {source_doc_type} 映射行 line_seq={line_seq}")
                        continue
                    if await _get(
                        db, m.AccountMappingRule,
                        company_id=cid, source_doc_type=source_doc_type,
                        trigger_action="AUDITED", line_seq=line_seq, effective_date=eff,
                    ) is not None:
                        mr_skip += 1
                        continue
                    db.add(m.AccountMappingRule(
                        company_id=cid, source_doc_type=source_doc_type, trigger_action="AUDITED",
                        line_seq=line_seq, dr_cr=dr_cr, account_code=code, account_source=source,
                        amount_formula="", tax_handling="NONE", memo_template=memo,
                        date_source="BIZ", effective_date=eff, is_active=True, created_by_id=created_by_id,
                    ))
                    mr_new += 1
        await db.flush()
        await db.commit()

        print("总账·应付波 应付款管理种子完成:")
        print(f"  A. WorkflowDefinition: 新建 {wf_actions['new']} / 覆盖 {wf_actions['updated']} / 停用旧版 {wf_actions['deactivated']}"
              f"（应付单 v2 / 付款单 v1；审核边已挂业财映射 effect；保唯一 active）")
        print(f"  B. 编号规则: 新增 {nr_new} 条（{len(companies)} 公司 × {len(NUMBERING_RULES)} 类）")
        print(f"  C. 核销方案: 新增 {ws_new} 条（biz_type=AP，{len(companies)} 公司 × {len(WRITEOFF_SCHEMES_AP)} 方案）")
        print(f"  D. 业财映射规则: 新增 {mr_new} / 已存在 {mr_skip}"
              f"（应付单 CAS 3 行/HK 2 行 + 付款单 3 行，按公司准则取本家科目码）")


if __name__ == "__main__":
    asyncio.run(seed_payable())
