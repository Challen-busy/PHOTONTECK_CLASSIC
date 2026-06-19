"""总账·第八波（finance-gl wave-8）应收款管理种子（幂等，可重复跑）。

在 backend/ 下执行（须先 alembic upgrade head 到 v6w7x8y9，且先跑过 scripts.seed / seed_finance）:
    DATABASE_URL=postgresql+asyncpg://...:5433/... python -m scripts.seed_receivable

本脚本四件事（均幂等 upsert，已存在跳过/覆盖）:

A. 为应收款管理 3 个 doc_type 种 WorkflowDefinition:
   - ACCOUNTS_RECEIVABLE 应收单：DRAFT 暂存 → SUBMITTED 提交 → AUDITED 审核（多态状态机；
     版本升级到 version=2，覆盖既有扁平版本，旧版历史单不受影响）。
     ★Phase2：审核（SUBMITTED→AUDITED）边已挂 effects=["finance.create_voucher_from_ar_bill"]
       （services.ar_receivable 已注册该 named effect，故不再 raise）。
   - AR_RECEIPT 收款单：DRAFT 暂存 → AUDITED 审核（轻于凭证，无出纳复核段）。
     ★Phase2：审核（DRAFT→AUDITED）边已挂 effects=["finance.create_voucher_from_ar_receipt"]。
   - WRITEOFF_SCHEME 核销方案：单状态 ACTIVE 自环编辑（MasterDataPage，照 master_data 范式）。
   按 (doc_type, version) upsert。

B. 应收单/收款单编号规则 NumberingRule（应收单 AR-YYMM-NNN / 收款单 SK-YYMM-NNN，月度重置），
   逐公司种入（照 seed_finance VOUCHER 规则套路）。

C. 种几条核销方案 WriteoffScheme（FIFO 默认 + 同金额 + 按到期日；biz_type=AR），逐公司种入。
   biz_type=AP 同款方案 Phase（应付）再补——本表已通用化，无需改结构。

D. 业财映射规则 AccountMappingRule（应收单/收款单审核 → 凭证，6 家按准则取本家科目码）:
   - 应收单（ACCOUNTS_RECEIVABLE，trigger=AUDITED）：CAS 借1122/贷6001/贷222102；HKFRS 借1122/贷6001。
   - 收款单（AR_RECEIPT，trigger=AUDITED）：借1002 + 贷1122（应收冲减）/ 贷2203（预收），按 is_advance 选行。
   照 seed_mapping 套路（按公司 region 分准则，目标科目须在本公司科目表存在）。

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
from services.master_data_workflows import _active_only_states


_FIN_ROLES = ["ADMIN", "FINANCE", "FINANCE_DIRECTOR"]
NUMBERING_EFFECT = "numbering.assign_business_number"  # 已注册（services.numbering_effect）

# ============================================================
# A. WorkflowDefinition
# ============================================================

# --- 应收单 ACCOUNTS_RECEIVABLE（DRAFT→SUBMITTED→AUDITED）---
# 录入态可编辑字段（头）。明细 ar_bill_line / 收款计划 ar_receipt_plan_line 走 SubTableEditor，随 sub_updates 提交。
_AR_BILL_HEAD_FIELDS = [
    "bill_number", "bill_type", "bill_date", "due_date",
    "customer_id", "sales_order_id", "contract_id",
    "currency", "exchange_rate", "base_currency", "base_amount",
    "amount", "untaxed_amount", "tax_amount",
    "payment_terms_text", "sales_engineer_id", "sales_org_id", "sales_dept",
    "is_tax_included", "is_price_tax_inclusive",
    "invoice_number", "remark",
]


def _ar_bill_states():
    return [
        {
            "code": "START", "name": "开始", "is_initial": True,
            "allowed_roles": _FIN_ROLES,
            "description": "# 开始节点\n建空应收单后进入「暂存」节点；建单同事务取应收单号 AR-YYMM-NNN。",
            "custom_html": "", "hard_rules": [], "hooks": [],
            "effects": [NUMBERING_EFFECT],
            "next": [{"to": "DRAFT", "label": "新建", "editable_fields": []}],
        },
        {
            "code": "DRAFT", "name": "暂存",
            "allowed_roles": _FIN_ROLES,
            "description": (
                "# 暂存（应收单录入）\n录入应收单头（客户/币别/汇率/业务日期/到期日/立账类型/收款条件/"
                "销售员/销售组织）与明细（物料×计价数量×单价×税率组×不含税/税额/价税合计）、收款计划（分期："
                "到期日/比例/金额）。\n开关：价外税（is_tax_included）/ 按含税单价录入（is_price_tax_inclusive）。\n"
                "「提交」推进到已提交态。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "SUBMITTED", "label": "提交", "editable_fields": _AR_BILL_HEAD_FIELDS},
            ],
        },
        {
            "code": "SUBMITTED", "name": "已提交",
            "allowed_roles": _FIN_ROLES,
            "description": (
                "# 已提交\n等待财务审核。\n「审核」推进到已审核态——审核后业财映射生应收凭证"
                "（借 1122 应收账款 / 贷 6001 主营收入 / 贷 2221 应交税费-销项税；HK 准则无销项税则仅"
                "借应收/贷收入）。\n★该业财 effect（finance.create_voucher_from_ar_bill）由 Phase2 注册后挂在"
                "本边 effects[]，本波留空。\n「撤回」退回暂存态修改。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                # Phase2：审核边挂业财映射 effect（生应收凭证，services.ar_receivable 已注册）。
                {"to": "AUDITED", "label": "审核", "editable_fields": ["remark"],
                 "effects": ["finance.create_voucher_from_ar_bill"]},
                {"to": "DRAFT", "label": "撤回", "editable_fields": ["remark"]},
            ],
        },
        {
            "code": "AUDITED", "name": "已审核", "is_terminal": True,
            "allowed_roles": _FIN_ROLES,
            "description": (
                "# 已审核\n应收单成立（债权立账）。经通用核销引擎（WriteoffLink，biz_type=AR）与收款单勾稽，"
                "核销回写 written_off_amount / writeoff_status（UNVERIFIED/PARTIAL/VERIFIED）。\n"
                "「反审核」退回已提交态（Phase2：若已生凭证须先红冲/反核销）。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "SUBMITTED", "label": "反审核", "editable_fields": ["remark"]},
            ],
        },
    ]


# --- 收款单 AR_RECEIPT（DRAFT→AUDITED）---
_AR_RECEIPT_HEAD_FIELDS = [
    "receipt_number", "customer_id", "receipt_date",
    "currency", "exchange_rate", "base_currency", "base_amount", "amount",
    "settlement_method_id", "bank_account", "payer_name", "is_advance", "remark",
]


def _ar_receipt_states():
    return [
        {
            "code": "START", "name": "开始", "is_initial": True,
            "allowed_roles": _FIN_ROLES,
            "description": "# 开始节点\n建空收款单后进入「暂存」节点；建单同事务取收款单号 SK-YYMM-NNN。",
            "custom_html": "", "hard_rules": [], "hooks": [],
            "effects": [NUMBERING_EFFECT],
            "next": [{"to": "DRAFT", "label": "新建", "editable_fields": []}],
        },
        {
            "code": "DRAFT", "name": "暂存",
            "allowed_roles": _FIN_ROLES,
            "description": (
                "# 暂存（收款单录入）\n录入客户/币别/收款日期/结算方式/银行账户/金额/是否预收。\n"
                "「审核」推进到已审核态——审核后业财映射生凭证（借 1002 银行存款 / 贷 1122 应收<核销时冲减>"
                "或 2203 预收账款<is_advance 预收>）。★该 effect 由 Phase2 注册后再挂，本波留空。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                # Phase2：审核边挂业财映射 effect（生收款凭证，services.ar_receivable 已注册）。
                {"to": "AUDITED", "label": "审核", "editable_fields": _AR_RECEIPT_HEAD_FIELDS,
                 "effects": ["finance.create_voucher_from_ar_receipt"]},
            ],
        },
        {
            "code": "AUDITED", "name": "已审核", "is_terminal": True,
            "allowed_roles": _FIN_ROLES,
            "description": (
                "# 已审核\n收款单成立（已收款）。经通用核销引擎（WriteoffLink，biz_type=AR）与应收单勾稽，"
                "核销回写 written_off_amount / writeoff_status。\n「反审核」退回暂存态。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "DRAFT", "label": "反审核", "editable_fields": ["remark"]},
            ],
        },
    ]


# --- 核销方案 WRITEOFF_SCHEME（单态 ACTIVE 自环编辑，MasterDataPage）---
_WRITEOFF_SCHEME_FIELDS = [
    "code", "name", "biz_type", "match_rule", "priority", "is_default", "is_active", "remark",
]


def receivable_workflow_definitions(created_by_id=None):
    """返回可直接传给 m.WorkflowDefinition(**kwargs) 的流程列表（应收单/收款单/核销方案）。"""
    defs = [
        {
            "doc_type": "ACCOUNTS_RECEIVABLE",
            "name": "应收单",
            "description": (
                "总账·第八波（finance-gl）应收款管理：应收单（客户债权立账，完全替代金蝶应收单）。\n"
                "暂存 DRAFT → 提交 SUBMITTED → 审核 AUDITED；审核后业财映射生应收凭证（Phase2 挂 effect）；"
                "经通用核销引擎（WriteoffLink biz_type=AR）与收款单勾稽。"
            ),
            "group_name": "财务",
            "version": 2,  # 升级覆盖既有扁平版本（旧版历史单不受影响）
            "is_published": True, "is_active": True,
            "node_positions": {
                "START": {"x": 300, "y": 0}, "DRAFT": {"x": 300, "y": 120},
                "SUBMITTED": {"x": 300, "y": 250}, "AUDITED": {"x": 300, "y": 390},
            },
            "states": _ar_bill_states(),
        },
        {
            "doc_type": "AR_RECEIPT",
            "name": "收款单",
            "description": (
                "总账·第八波（finance-gl）应收款管理：收款单（客户实收款登记，完全替代金蝶收款单）。\n"
                "暂存 DRAFT → 审核 AUDITED；审核后业财映射生凭证（Phase2 挂 effect）；经通用核销引擎与应收单勾稽。"
            ),
            "group_name": "财务",
            "version": 1,
            "is_published": True, "is_active": True,
            "node_positions": {
                "START": {"x": 300, "y": 0}, "DRAFT": {"x": 300, "y": 120},
                "AUDITED": {"x": 300, "y": 250},
            },
            "states": _ar_receipt_states(),
        },
        {
            "doc_type": "WRITEOFF_SCHEME",
            "name": "核销方案",
            "description": (
                "# 核销方案\n通用核销方案配置主数据（biz_type=AR/AP 参数化；单状态 ACTIVE 自环编辑）。\n"
                "match_rule：FIFO 先进先出 / SAME_AMOUNT 同金额 / BY_DUEDATE 按到期日 / MANUAL 手工。"
            ),
            "group_name": "财务基础资料",
            "version": 1,
            "is_published": True, "is_active": True,
            "states": _active_only_states(_FIN_ROLES, _WRITEOFF_SCHEME_FIELDS),
        },
    ]
    if created_by_id is not None:
        for d in defs:
            d["created_by_id"] = created_by_id
    return defs


# ============================================================
# B. 编号规则（逐公司）
# ============================================================
# (doc_type, prefix)
NUMBERING_RULES = [
    ("ACCOUNTS_RECEIVABLE", "AR"),
    ("AR_RECEIPT", "SK"),
]

# ============================================================
# C. 核销方案种子（逐公司，biz_type=AR）
# ============================================================
# (code, name, match_rule, priority, is_default)
WRITEOFF_SCHEMES_AR = [
    ("AR-FIFO", "应收-先进先出", "FIFO", 10, True),
    ("AR-SAME", "应收-同金额匹配", "SAME_AMOUNT", 20, False),
    ("AR-DUE", "应收-按到期日", "BY_DUEDATE", 30, False),
    ("AR-MANUAL", "应收-手工核销", "MANUAL", 90, False),
]

# ============================================================
# D. 业财映射规则（应收单/收款单审核 → 凭证，按公司 region 分准则）
# ============================================================
# 应收单 ACCOUNTS_RECEIVABLE（trigger=AUDITED）。金额由应收单头字段供（services.ar_receivable 按 dr_cr+
# account_code 取本行科目；amount_formula/tax_handling 在应收映射里不参与求值，留空对齐）。
# (line_seq, dr_cr, account_code, account_source, memo_template)
CAS_AR_BILL_RULES = [
    (1, "DR", "1122",   "CUSTOMER", "应收账款—{customer}（{bill_number}）"),
    (2, "CR", "6001",   "FIXED",    "确认主营业务收入（{bill_number}）"),
    (3, "CR", "222102", "FIXED",    "应交增值税（销项税额）（{bill_number}）"),
]
HKFRS_AR_BILL_RULES = [
    (1, "DR", "1122", "CUSTOMER", "Trade receivables - {customer} ({bill_number})"),
    (2, "CR", "6001", "FIXED",    "Recognise revenue ({bill_number})"),
]
# 收款单 AR_RECEIPT（trigger=AUDITED）：借 1002 银行 + 贷 1122 应收（冲减）/ 贷 2203 预收
# （services.ar_receivable 按 is_advance 在两条贷方行里选一行；CAS/HKFRS 科目码同）。
AR_RECEIPT_RULES = [
    (1, "DR", "1002", "FIXED",    "收到客户款—{customer}（{receipt_number}）"),
    (2, "CR", "1122", "CUSTOMER", "冲减应收账款（{receipt_number}）"),
    (3, "CR", "2203", "CUSTOMER", "预收账款（{receipt_number}）"),
]


def _ar_bill_rules_for_region(region: str):
    return HKFRS_AR_BILL_RULES if region == "HK" else CAS_AR_BILL_RULES


async def _get(db, model, **filters):
    stmt = select(model)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalars().first()


async def seed_receivable():
    factory = get_session_factory()
    async with factory() as db:
        admin = await _get(db, m.UserAccount, username="admin")
        created_by_id = admin.id if admin else None

        # === A. WorkflowDefinition（按 (doc_type, version) upsert）===
        # ★引擎不变量：get_active_workflow 要求每个 doc_type 至多一条 is_active=True。
        #   ACCOUNTS_RECEIVABLE 升版到 v2（保留旧 v1 历史单），故 upsert 本版后须把同 doc_type
        #   其余版本一律置 is_active=False（旧定义留痕但不再激活），避免 MultipleResultsFound。
        wf_actions = {"new": 0, "updated": 0, "deactivated": 0}
        for wf_def in receivable_workflow_definitions(created_by_id):
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
            # 停用同 doc_type 的其余版本（保唯一 active）。
            others = (await db.execute(
                select(m.WorkflowDefinition).where(
                    m.WorkflowDefinition.doc_type == wf_def["doc_type"],
                    m.WorkflowDefinition.version != wf_def["version"],
                    m.WorkflowDefinition.is_active == True,
                )
            )).scalars().all()
            for o in others:
                o.is_active = False
                wf_actions["deactivated"] += 1
        await db.flush()

        # === B + C + D. 逐公司：编号规则 + 核销方案 + 业财映射规则 ===
        companies = (await db.execute(select(m.Company))).scalars().all()
        nr_new = 0
        ws_new = 0
        mr_new = 0
        mr_skip = 0
        eff = date(date.today().year, 1, 1)  # 业财映射规则生效日（本财年 1/1，对齐 seed_mapping）
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
            # C. 核销方案（biz_type=AR）
            for code, name, rule, prio, is_default in WRITEOFF_SCHEMES_AR:
                if await _get(db, m.WriteoffScheme, company_id=cid, biz_type="AR", code=code) is None:
                    db.add(m.WriteoffScheme(
                        company_id=cid, code=code, name=name, biz_type="AR",
                        match_rule=rule, priority=prio, is_default=is_default,
                        is_active=True, created_by_id=created_by_id,
                    ))
                    ws_new += 1
            # D. 业财映射规则（应收单 + 收款单，trigger=AUDITED；按 region 分准则；目标科目须存在）
            ar_rule_specs = [
                ("ACCOUNTS_RECEIVABLE", _ar_bill_rules_for_region(company.region)),
                ("AR_RECEIPT", AR_RECEIPT_RULES),
            ]
            for source_doc_type, specs in ar_rule_specs:
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

        print("总账·第八波应收款管理种子完成:")
        print(f"  A. WorkflowDefinition: 新建 {wf_actions['new']} / 覆盖 {wf_actions['updated']} / 停用旧版 {wf_actions['deactivated']}"
              f"（应收单/收款单/核销方案 3 个 doc_type；审核边已挂业财映射 effect；保唯一 active 不破坏 get_active_workflow）")
        print(f"  B. 编号规则: 新增 {nr_new} 条（{len(companies)} 公司 × {len(NUMBERING_RULES)} 类）")
        print(f"  C. 核销方案: 新增 {ws_new} 条（{len(companies)} 公司 × {len(WRITEOFF_SCHEMES_AR)} 方案）")
        print(f"  D. 业财映射规则: 新增 {mr_new} / 已存在 {mr_skip}"
              f"（应收单 CAS 3 行/HK 2 行 + 收款单 3 行，按公司准则取本家科目码）")


if __name__ == "__main__":
    asyncio.run(seed_receivable())
