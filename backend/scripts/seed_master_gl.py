"""总账·第三波（finance-gl wave-3）配账主数据种子（幂等，可重复跑）。

在 backend/ 下执行（须先 alembic upgrade head 到 s3t4u5v6，且先跑过 scripts.seed + scripts.seed_finance）:
    DATABASE_URL=postgresql+asyncpg://...:5433/... python -m scripts.seed_master_gl

本脚本两件事（均幂等 upsert，不删存量、已存在跳过/覆盖）:

A. 为「所有 GL 主数据 doc_type」各种一个最小 WorkflowDefinition（照 CUSTOMER 范式：单状态 ACTIVE
   自环编辑，复用 services.master_data_workflows._active_only_states），使前端 MasterDataPage 可建/改:
   - wave-1/2 既有类（已在 models.py 补 __doc_types__）: ACCOUNT / VOUCHER_WORD / AUX_DIMENSION /
     CASHFLOW_ITEM / EXCHANGE_RATE。
   - wave-3 新表: CURRENCY / SETTLEMENT_METHOD / ACCOUNTING_POLICY / ACCOUNTING_SYSTEM /
     SUMMARY_ENTRY / MODEL_VOUCHER / AUX_DIMENSION_VALUE。
   按 (doc_type, version=1) upsert。

B. 为 7 张新表种 6 公司基础数据（按 region 二分准则：HK→HKFRS/HKD、CN→CAS/CNY）:
   - 币别 currency: HKD/CNY/USD（本位币按公司本位币 is_base=True）。
   - 结算方式 settlement_method: 现金/银行转账/电汇/支票。
   - 会计政策 accounting_policy: 各公司一条主政策（按准则）。
   - 会计核算体系 accounting_system: 每公司一套主账簿。
   - 摘要库 summary_entry: 常用 20 条。
   - 模式凭证 model_voucher: 各公司 2 个常用模板（+ 分录模板子表）。
   - 核算维度数据 auxiliary_dimension_value: 按现有维度（部门/项目）种几条示例。

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


# ============================================================
# A. GL 主数据轻量建档状态机（doc_type → 中文名 / 维护角色 / 可建档字段 / 分组）
#    照 CUSTOMER 范式：单状态 ACTIVE 自环编辑（_active_only_states 构造 states）。
#    可建档字段严格对齐 models.py 列名（不含 id/company_id/审计列，由引擎/AuditMixin 维护）。
# ============================================================
_FIN_ROLES = ["ADMIN", "FINANCE", "FINANCE_DIRECTOR"]

GL_MASTER_SPECS = [
    # —— wave-1/2 既有类（已补 __doc_types__）——
    ("ACCOUNT", "会计科目", _FIN_ROLES, [
        "code", "name", "parent_id", "account_type", "balance_direction",
        "level", "is_leaf", "currency", "is_active",
    ], "财务基础资料"),
    ("VOUCHER_WORD", "凭证字", _FIN_ROLES, [
        "code", "name", "restrict_multi_dc", "is_active",
    ], "财务基础资料"),
    ("AUX_DIMENSION", "辅助核算维度", _FIN_ROLES, [
        "code", "name", "source_type", "is_active",
    ], "财务基础资料"),
    ("CASHFLOW_ITEM", "现金流量项目", _FIN_ROLES, [
        "code", "name", "direction", "parent_id", "is_active",
    ], "财务基础资料"),
    ("EXCHANGE_RATE", "汇率", _FIN_ROLES, [
        "from_currency", "to_currency", "rate", "effective_date",
    ], "财务基础资料"),
    # —— wave-3 新表 ——
    ("CURRENCY", "币别", _FIN_ROLES, [
        "code", "name", "symbol", "is_base", "decimal_places", "is_active",
    ], "财务基础资料"),
    ("SETTLEMENT_METHOD", "结算方式", _FIN_ROLES, [
        "code", "name", "method_type", "needs_settlement_no", "is_active",
    ], "财务基础资料"),
    ("ACCOUNTING_POLICY", "会计政策", _FIN_ROLES, [
        "code", "name", "standard", "measurement_basis", "depreciation_method",
        "inventory_valuation", "bad_debt_method", "fiscal_year_start_month", "is_active",
    ], "财务基础资料"),
    ("ACCOUNTING_SYSTEM", "会计核算体系", _FIN_ROLES, [
        "code", "name", "base_currency", "standard", "policy_id",
        "start_year", "start_period", "is_active",
    ], "财务基础资料"),
    ("SUMMARY_ENTRY", "摘要库", _FIN_ROLES, [
        "code", "category", "text", "sort_order", "is_active",
    ], "财务基础资料"),
    ("MODEL_VOUCHER", "模式凭证", _FIN_ROLES, [
        "code", "name", "voucher_word_id", "default_description", "notes", "is_active",
    ], "财务基础资料"),
    ("AUX_DIMENSION_VALUE", "核算维度数据", _FIN_ROLES, [
        "dimension_id", "code", "name", "parent_id", "is_active",
    ], "财务基础资料"),
]

# 模式凭证子表可编辑字段（MasterDataPage 内嵌网格随 sub_updates 提交）。
MODEL_VOUCHER_LINE_FIELDS = [
    "line_number", "account_id", "account_code", "dr_cr", "description", "amount",
]


def gl_master_workflow_definitions(created_by_id=None):
    """返回可直接传给 m.WorkflowDefinition(**kwargs) 的轻量建档流程列表（GL 主数据）。"""
    defs = []
    for doc_type, name, roles, fields, group in GL_MASTER_SPECS:
        defs.append({
            "doc_type": doc_type,
            "name": name,
            "description": f"# {name}\n配账主数据轻量建档状态机（单状态 ACTIVE，无审批/无财务关卡，自环编辑）。",
            "states": _active_only_states(roles, fields),
            "group_name": group,
            "version": 1,
            "is_published": True,
            "is_active": True,
            "created_by_id": created_by_id,
        })
    return defs


# ============================================================
# B. 7 新表 6 公司基础数据
# ============================================================
# 币别（全公司共用三种；本位币按公司本位币标 is_base）。(code, name, symbol, decimal_places)
CURRENCIES = [
    ("HKD", "港币",   "HK$", 2),
    ("CNY", "人民币", "¥",   2),
    ("USD", "美元",   "$",   2),
]

# 结算方式（现金/银行转账/电汇/支票）。(code, name, method_type, needs_settlement_no)
SETTLEMENT_METHODS = [
    ("XJ", "现金",     "CASH",     False),
    ("YHZZ", "银行转账", "TRANSFER", True),
    ("DH", "电汇",     "WIRE",     True),
    ("ZP", "支票",     "NOTE",     True),
]

# 摘要库常用 20 条。(code, category, text)
SUMMARY_ENTRIES = [
    ("S001", "收款", "收到客户货款"),
    ("S002", "收款", "收到预收账款"),
    ("S003", "收款", "收到票据"),
    ("S004", "付款", "支付供应商货款"),
    ("S005", "付款", "支付预付账款"),
    ("S006", "付款", "支付银行手续费"),
    ("S007", "费用", "报销差旅费"),
    ("S008", "费用", "报销业务招待费"),
    ("S009", "费用", "支付办公费"),
    ("S010", "费用", "支付租金"),
    ("S011", "费用", "支付水电费"),
    ("S012", "薪酬", "计提工资"),
    ("S013", "薪酬", "发放工资"),
    ("S014", "税费", "计提增值税"),
    ("S015", "税费", "缴纳税费"),
    ("S016", "结转", "结转主营业务成本"),
    ("S017", "结转", "结转本年利润"),
    ("S018", "折旧", "计提固定资产折旧"),
    ("S019", "汇兑", "期末汇兑损益调整"),
    ("S020", "其他", "其他业务"),
]


def _policy_for_region(region: str):
    """按区域返回会计政策键值（HK→HKFRS / CN→CAS）。"""
    if region == "HK":
        return {
            "code": "DEFAULT", "name": "香港会计政策（HKFRS）", "standard": "HKFRS",
            "measurement_basis": "HISTORICAL_COST", "depreciation_method": "STRAIGHT_LINE",
            "inventory_valuation": "WEIGHTED_AVG", "bad_debt_method": "ALLOWANCE",
            "fiscal_year_start_month": 4,  # 香港多以 4 月为会计年度起始（占位待甲方确认）
        }
    return {
        "code": "DEFAULT", "name": "内地会计政策（CAS）", "standard": "CAS",
        "measurement_basis": "HISTORICAL_COST", "depreciation_method": "STRAIGHT_LINE",
        "inventory_valuation": "WEIGHTED_AVG", "bad_debt_method": "ALLOWANCE",
        "fiscal_year_start_month": 1,
    }


def _model_vouchers_for_company(region="CN"):
    """两个常用模式凭证模板（+ 分录模板）。account_code 走弱引用，按准则取本区域真实存在的科目码
    （HK/HKFRS 与 CN/CAS 的费用·折旧·薪酬码不同，避免模板引用本公司不存在的科目）。
    返回 [(code, name, default_description, lines[(line_number, account_code, dr_cr, description)]), ...]。"""
    if region == "HK":
        return [
            ("MV-SALARY", "计提工资模板", "计提本月工资", [
                (1, "6502", "DR", "Staff costs 员工成本-工资"),
                (2, "2211", "CR", "Accruals 应计费用-应付工资"),
            ]),
            ("MV-DEPR", "计提折旧模板", "计提本月折旧", [
                (1, "6503", "DR", "Depreciation 折旧"),
                (2, "1602", "CR", "Accumulated depreciation 累计折旧"),
            ]),
        ]
    return [
        ("MV-SALARY", "计提工资模板", "计提本月工资", [
            (1, "6602", "DR", "管理费用-工资"),
            (2, "2211", "CR", "应付职工薪酬"),
        ]),
        ("MV-DEPR", "计提折旧模板", "计提本月折旧", [
            (1, "6602", "DR", "管理费用-折旧"),
            (2, "1602", "CR", "累计折旧"),
        ]),
    ]


# ============================================================
# 幂等 upsert 工具（对齐 seed_finance._get 风格）
# ============================================================
async def _get(db, model, **filters):
    stmt = select(model)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalars().first()


async def _seed_company_master(db, company, created_by_id):
    """为单家公司种 7 新表基础数据（幂等，已存在跳过）。返回新增计数 dict。"""
    cid = company.id
    region = company.region or "CN"
    base_ccy = company.currency or ("HKD" if region == "HK" else "CNY")
    standard = "HKFRS" if region == "HK" else "CAS"
    counts = {"currency": 0, "settle": 0, "policy": 0, "system": 0,
              "summary": 0, "model_v": 0, "model_l": 0, "aux_val": 0}

    # --- 1. 币别（本位币标 is_base）---
    for code, name, symbol, dp in CURRENCIES:
        if await _get(db, m.Currency, company_id=cid, code=code) is None:
            db.add(m.Currency(
                company_id=cid, code=code, name=name, symbol=symbol,
                is_base=(code == base_ccy), decimal_places=dp, is_active=True,
                created_by_id=created_by_id,
            ))
            counts["currency"] += 1
    await db.flush()

    # --- 2. 结算方式 ---
    for code, name, mtype, needs_no in SETTLEMENT_METHODS:
        if await _get(db, m.SettlementMethod, company_id=cid, code=code) is None:
            db.add(m.SettlementMethod(
                company_id=cid, code=code, name=name, method_type=mtype,
                needs_settlement_no=needs_no, is_active=True, created_by_id=created_by_id,
            ))
            counts["settle"] += 1
    await db.flush()

    # --- 3. 会计政策（按准则）---
    pol_kv = _policy_for_region(region)
    policy = await _get(db, m.AccountingPolicy, company_id=cid, code=pol_kv["code"])
    if policy is None:
        policy = m.AccountingPolicy(company_id=cid, is_active=True, created_by_id=created_by_id, **pol_kv)
        db.add(policy)
        await db.flush()
        counts["policy"] += 1

    # --- 4. 会计核算体系（主账簿，引用政策）---
    if await _get(db, m.AccountingSystem, company_id=cid, code="MAIN") is None:
        db.add(m.AccountingSystem(
            company_id=cid, code="MAIN", name=f"{company.short_name or company.code}主账簿",
            base_currency=base_ccy, standard=standard, policy_id=policy.id,
            start_year=None, start_period=1, is_active=True, created_by_id=created_by_id,
        ))
        counts["system"] += 1
    await db.flush()

    # --- 5. 摘要库（常用 20 条）---
    for code, category, txt in SUMMARY_ENTRIES:
        if await _get(db, m.SummaryEntry, company_id=cid, code=code) is None:
            db.add(m.SummaryEntry(
                company_id=cid, code=code, category=category, text=txt,
                sort_order=0, is_active=True, created_by_id=created_by_id,
            ))
            counts["summary"] += 1
    await db.flush()

    # --- 6. 模式凭证（+ 分录模板子表）。voucher_word 取本公司「记」字（若有）---
    rec_word = await _get(db, m.VoucherWord, company_id=cid, code="记")
    for code, name, default_desc, lines in _model_vouchers_for_company(region):
        mv = await _get(db, m.ModelVoucher, company_id=cid, code=code)
        if mv is None:
            mv = m.ModelVoucher(
                company_id=cid, code=code, name=name,
                voucher_word_id=rec_word.id if rec_word else None,
                default_description=default_desc, is_active=True, created_by_id=created_by_id,
            )
            db.add(mv)
            await db.flush()
            counts["model_v"] += 1
            for ln, acode, dr_cr, desc in lines:
                # 模板分录按 account_code 弱引用，并尽量回填 account_id（本公司同码科目）。
                acct = await _get(db, m.Account, company_id=cid, code=acode)
                db.add(m.ModelVoucherLine(
                    model_voucher_id=mv.id, line_number=ln,
                    account_id=acct.id if acct else None, account_code=acode,
                    dr_cr=dr_cr, description=desc, amount=None,
                ))
                counts["model_l"] += 1
    await db.flush()

    # --- 7. 核算维度数据（按现有维度种示例：部门 AUX_DEPT / 项目 AUX_PROJ）---
    dept_dim = await _get(db, m.AuxiliaryDimension, company_id=cid, code="AUX_DEPT")
    proj_dim = await _get(db, m.AuxiliaryDimension, company_id=cid, code="AUX_PROJ")
    aux_value_samples = []
    if dept_dim:
        aux_value_samples += [
            (dept_dim.id, "D01", "销售部"),
            (dept_dim.id, "D02", "采购部"),
            (dept_dim.id, "D03", "财务部"),
            (dept_dim.id, "D04", "仓储物流部"),
        ]
    if proj_dim:
        aux_value_samples += [
            (proj_dim.id, "P001", "光通信项目"),
            (proj_dim.id, "P002", "科研项目"),
        ]
    for dim_id, code, name in aux_value_samples:
        if await _get(db, m.AuxiliaryDimensionValue, company_id=cid, dimension_id=dim_id, code=code) is None:
            db.add(m.AuxiliaryDimensionValue(
                company_id=cid, dimension_id=dim_id, code=code, name=name,
                is_active=True, created_by_id=created_by_id,
            ))
            counts["aux_val"] += 1
    await db.flush()

    return counts


async def seed_master_gl():
    factory = get_session_factory()
    async with factory() as db:
        admin = await _get(db, m.UserAccount, username="admin")
        created_by_id = admin.id if admin else None

        # === A. GL 主数据轻量建档状态机（按 (doc_type, version) upsert）===
        wf_actions = {"new": 0, "updated": 0}
        for wf_def in gl_master_workflow_definitions(created_by_id):
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

        # === B. 7 新表 6 公司基础数据 ===
        companies = (await db.execute(select(m.Company).order_by(m.Company.id))).scalars().all()
        if not companies:
            print("未找到任何公司，请先跑 scripts.seed。")
            return

        per_company = []
        for company in companies:
            counts = await _seed_company_master(db, company, created_by_id)
            per_company.append((company, counts))

        await db.commit()

        print("总账·第三波配账主数据种子完成:")
        print(f"  A. GL 主数据建档状态机: 新建 {wf_actions['new']} / 覆盖 {wf_actions['updated']}"
              f"（共 {len(GL_MASTER_SPECS)} 个 doc_type）")
        for company, c in per_company:
            print(
                f"  [{company.code} #{company.id} region={company.region}] "
                f"币别+{c['currency']} 结算+{c['settle']} 政策+{c['policy']} 体系+{c['system']} "
                f"摘要+{c['summary']} 模式凭证+{c['model_v']}(行+{c['model_l']}) 维度数据+{c['aux_val']}"
            )


if __name__ == "__main__":
    asyncio.run(seed_master_gl())
