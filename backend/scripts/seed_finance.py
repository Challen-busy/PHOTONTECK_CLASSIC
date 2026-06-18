"""总账·第一波（finance-gl）财务主数据 + 凭证状态机种子（幂等，可重复跑）。

在 backend/ 下执行（须先 alembic upgrade head 到 q1r2s3t4）:
    python -m scripts.seed_finance

★按公司分准则种全部运营公司（决策：6 家独立公司，准则二分）:
  • 内地 RJ/XGTC/TR（company 4/5/6，本位币 CNY）→ CAS 标准会计科目表。
  • 香港 PTK/ADS/FTK（company 1/2/3，本位币 HKD）→ HKFRS 科目表（中英双语名）。
每家公司各种一套：科目表 / 凭证字 / 辅助核算维度 / 现金流量项目 / 会计年度+12 自然月期间（OPEN）/ 凭证编号规则。
★关键：用户 home 公司 PTK（company 1）有完整 HKFRS 财务数据，finance/fin_dir/boss 能直接在 company 1 记账。

种入内容（全部按 (company_id, code) / (doc_type, version) 唯一键幂等 upsert，不删存量，已存在跳过）:
  1. 会计科目表（五大类常用贸易科目，分级 parent_id；备抵科目方向独立标）。CAS=中文、HKFRS=中英。
  2. 凭证字 VoucherWord（记/收/付/转；收付字 restrict_multi_dc=True）。
  3. 辅助核算维度 AuxiliaryDimension（客户/供应商/职员/部门/项目）。
  4. 现金流量项目 CashflowItem（经营/投资/筹资 三类 + 常用子项，带 direction）。
  5. 会计年度 FiscalYear + 12 个自然月会计期间 AccountingPeriod（status=OPEN）。
  6. 凭证号编号规则 NumberingRule（VOUCHER → PZ-YYMM-NNN，月度重置）。
  7. VOUCHER WorkflowDefinition（DRAFT→AUDITED→[REVIEWED 资金类]→POSTED + 反过账/反审核逆向边）,
     按 (doc_type=VOUCHER, version=1) upsert——覆盖 seed.py 里旧的 K3 参考流程（对齐本波记账规格）。

幂等说明：本脚本只种数据、不跑流转。已种过的 company 4（RJ）重复跑不破坏。引擎核心三件零 diff。
所有过账/反过账/借贷平衡/期间锁/职责分离/红冲扩展点已在 services/finance_posting.py 注册并加载。
"""

import asyncio
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory


# ============================================================
# 1a. CAS 标准会计科目表（内地公司 RJ/XGTC/TR，本位币 CNY）
#     (code, name, account_type, balance_direction, parent_code)
#     account_type ∈ ASSET/LIABILITY/EQUITY/REVENUE/EXPENSE/COGS（对齐 Account 注释）。
#     备抵科目（累计折旧/坏账准备）方向独立标 CREDIT（虽属资产类大类）。
# ============================================================
CAS_ACCOUNTS = [
    # ---- 资产类 ASSET（借方）----
    ("1001", "库存现金",        "ASSET", "DEBIT",  None),
    ("1002", "银行存款",        "ASSET", "DEBIT",  None),
    ("1012", "其他货币资金",    "ASSET", "DEBIT",  None),
    ("1122", "应收账款",        "ASSET", "DEBIT",  None),
    ("1123", "预付账款",        "ASSET", "DEBIT",  None),
    ("1221", "其他应收款",      "ASSET", "DEBIT",  None),
    ("1231", "坏账准备",        "ASSET", "CREDIT", "1122"),   # 备抵：贷方
    ("1401", "材料采购",        "ASSET", "DEBIT",  None),
    ("1402", "在途物资",        "ASSET", "DEBIT",  None),
    ("1403", "原材料",          "ASSET", "DEBIT",  None),
    ("1405", "库存商品",        "ASSET", "DEBIT",  None),
    ("1408", "委托加工物资",    "ASSET", "DEBIT",  None),
    ("1471", "存货跌价准备",    "ASSET", "CREDIT", "1405"),   # 备抵：贷方
    ("1601", "固定资产",        "ASSET", "DEBIT",  None),
    ("1602", "累计折旧",        "ASSET", "CREDIT", "1601"),   # 备抵：贷方
    ("1701", "无形资产",        "ASSET", "DEBIT",  None),
    ("1702", "累计摊销",        "ASSET", "CREDIT", "1701"),   # 备抵：贷方

    # ---- 负债类 LIABILITY（贷方）----
    ("2001", "短期借款",        "LIABILITY", "CREDIT", None),
    ("2202", "应付账款",        "LIABILITY", "CREDIT", None),
    ("2203", "预收账款",        "LIABILITY", "CREDIT", None),
    ("2211", "应付职工薪酬",    "LIABILITY", "CREDIT", None),
    ("2221", "应交税费",        "LIABILITY", "CREDIT", None),
    ("222101", "应交税费—应交增值税（进项税额）", "LIABILITY", "CREDIT", "2221"),
    ("222102", "应交税费—应交增值税（销项税额）", "LIABILITY", "CREDIT", "2221"),
    ("222106", "应交税费—应交所得税",            "LIABILITY", "CREDIT", "2221"),
    ("2241", "其他应付款",      "LIABILITY", "CREDIT", None),
    ("2501", "长期借款",        "LIABILITY", "CREDIT", None),

    # ---- 权益类 EQUITY（贷方）----
    ("4001", "实收资本",        "EQUITY", "CREDIT", None),
    ("4002", "资本公积",        "EQUITY", "CREDIT", None),
    ("4101", "盈余公积",        "EQUITY", "CREDIT", None),
    ("4103", "本年利润",        "EQUITY", "CREDIT", None),
    ("4104", "利润分配",        "EQUITY", "CREDIT", None),

    # ---- 成本类 COGS（借方）----
    ("5001", "生产成本",        "COGS", "DEBIT", None),
    ("5101", "制造费用",        "COGS", "DEBIT", None),

    # ---- 损益类（收入 REVENUE 贷方 / 费用 EXPENSE 借方）----
    ("6001", "主营业务收入",    "REVENUE", "CREDIT", None),
    ("6051", "其他业务收入",    "REVENUE", "CREDIT", None),
    ("6111", "投资收益",        "REVENUE", "CREDIT", None),
    ("6301", "营业外收入",      "REVENUE", "CREDIT", None),
    ("6401", "主营业务成本",    "EXPENSE", "DEBIT",  None),
    ("6402", "其他业务成本",    "EXPENSE", "DEBIT",  None),
    ("6403", "税金及附加",      "EXPENSE", "DEBIT",  None),
    ("6601", "销售费用",        "EXPENSE", "DEBIT",  None),
    ("6602", "管理费用",        "EXPENSE", "DEBIT",  None),
    ("6603", "财务费用",        "EXPENSE", "DEBIT",  None),
    ("6711", "营业外支出",      "EXPENSE", "DEBIT",  None),
    ("6801", "所得税费用",      "EXPENSE", "DEBIT",  None),
]


# ============================================================
# 1b. HKFRS 科目表（香港公司 PTK/ADS/FTK，本位币 HKD）
#     按香港财务报告准则常用列报科目，中英双语命名（英文为主、括注中文）。
#     code 用 HKFRS 风格的四位分段编码（1xxx 资产 / 2xxx 负债 / 3xxx 权益 / 4xxx 收入 / 5xxx 成本 / 6xxx 费用）。
#     ★为兼容 smoke/seed 里硬编码的「银行 1002 / 应收 1122 / 收入 6001」锚点，关键科目保留同款 code
#       （1001 现金、1002 银行、1122 应收账款、6001 收入；见各处 lookup('account', code=...)）。
#     account_type 五大类同 CAS 口径；备抵科目（累计折旧/减值准备）方向独立标 CREDIT。
# ============================================================
HKFRS_ACCOUNTS = [
    # ---- 资产 ASSET（借方）----
    ("1001", "Cash on hand 库存现金",                 "ASSET", "DEBIT",  None),
    ("1002", "Cash at bank 银行存款",                 "ASSET", "DEBIT",  None),
    ("1012", "Other cash and cash equivalents 其他货币资金", "ASSET", "DEBIT", None),
    ("1122", "Trade receivables 应收账款",            "ASSET", "DEBIT",  None),
    ("1123", "Prepayments 预付款项",                  "ASSET", "DEBIT",  None),
    ("1131", "Deposits and other receivables 押金及其他应收款", "ASSET", "DEBIT", None),
    ("1141", "Amounts due from related parties 关联方应收款", "ASSET", "DEBIT", None),
    ("1191", "Allowance for impairment of receivables 应收款减值准备", "ASSET", "CREDIT", "1122"),  # 备抵：贷方
    ("1211", "Inventories 存货",                      "ASSET", "DEBIT",  None),
    ("1212", "Goods in transit 在途存货",             "ASSET", "DEBIT",  None),
    ("1291", "Allowance for inventory write-down 存货跌价准备", "ASSET", "CREDIT", "1211"),  # 备抵：贷方
    ("1601", "Property, plant and equipment 物业、厂房及设备", "ASSET", "DEBIT", None),
    ("1602", "Accumulated depreciation 累计折旧",     "ASSET", "CREDIT", "1601"),  # 备抵：贷方
    ("1701", "Intangible assets 无形资产",            "ASSET", "DEBIT",  None),
    ("1702", "Accumulated amortisation 累计摊销",     "ASSET", "CREDIT", "1701"),  # 备抵：贷方

    # ---- 负债 LIABILITY（贷方）----
    ("2101", "Bank borrowings 银行借款",              "LIABILITY", "CREDIT", None),
    ("2202", "Trade payables 应付账款",               "LIABILITY", "CREDIT", None),
    ("2203", "Receipts in advance 预收款项",          "LIABILITY", "CREDIT", None),
    ("2211", "Accruals and other payables 应计费用及其他应付款", "LIABILITY", "CREDIT", None),
    ("2221", "Provision for taxation 应交税项",       "LIABILITY", "CREDIT", None),
    ("2231", "Amounts due to related parties 关联方应付款", "LIABILITY", "CREDIT", None),
    ("2401", "Deferred tax liabilities 递延税项负债", "LIABILITY", "CREDIT", None),

    # ---- 权益 EQUITY（贷方）----
    ("3001", "Share capital 股本",                    "EQUITY", "CREDIT", None),
    ("3002", "Share premium 股份溢价",                "EQUITY", "CREDIT", None),
    ("3101", "Reserves 储备",                         "EQUITY", "CREDIT", None),
    ("3201", "Retained earnings 留存收益",            "EQUITY", "CREDIT", None),
    ("3301", "Profit for the year 本年利润",          "EQUITY", "CREDIT", None),

    # ---- 成本 COGS（借方）----
    ("5001", "Cost of sales 销售成本",                "COGS", "DEBIT", None),

    # ---- 收入 REVENUE（贷方）----
    ("6001", "Revenue 营业收入",                      "REVENUE", "CREDIT", None),
    ("6051", "Other income 其他收入",                 "REVENUE", "CREDIT", None),
    ("6061", "Finance income 财务收益",               "REVENUE", "CREDIT", None),
    ("6071", "Gain on disposal 处置收益",             "REVENUE", "CREDIT", None),

    # ---- 费用 EXPENSE（借方）----
    ("6401", "Selling and distribution expenses 销售及分销费用", "EXPENSE", "DEBIT", None),
    ("6501", "Administrative expenses 行政费用",      "EXPENSE", "DEBIT", None),
    ("6502", "Staff costs 员工成本",                  "EXPENSE", "DEBIT", None),
    ("6503", "Depreciation and amortisation 折旧及摊销", "EXPENSE", "DEBIT", None),
    ("6601", "Finance costs 财务费用",                "EXPENSE", "DEBIT", None),
    ("6701", "Other expenses 其他费用",               "EXPENSE", "DEBIT", None),
    ("6801", "Income tax expense 所得税费用",         "EXPENSE", "DEBIT", None),
]


# 2. 凭证字（记/收/付/转）。收/付字限借贷只一方（restrict_multi_dc=True）。
VOUCHER_WORDS = [
    ("记", "记账凭证", False),
    ("收", "收款凭证", True),
    ("付", "付款凭证", True),
    ("转", "转账凭证", False),
]


# 3. 辅助核算维度（往来对象/部门/项目）。source_type ∈ CUSTOMER/SUPPLIER/EMPLOYEE/DEPT/PROJECT。
AUX_DIMENSIONS = [
    ("AUX_CUST",  "客户",   "CUSTOMER"),
    ("AUX_SUPP",  "供应商", "SUPPLIER"),
    ("AUX_EMP",   "职员",   "EMPLOYEE"),
    ("AUX_DEPT",  "部门",   "DEPT"),
    ("AUX_PROJ",  "项目",   "PROJECT"),
]


# 4. 现金流量项目（经营/投资/筹资三类 + 常用子项）。direction ∈ IN 流入 / OUT 流出。
#    (code, name, direction, parent_code)。父项做分类锚点（direction 取主流向）。
CASHFLOW_ITEMS = [
    # 经营活动
    ("CF_OP",      "经营活动现金流量",          "IN",  None),
    ("CF_OP_SALE", "销售商品、提供劳务收到的现金", "IN",  "CF_OP"),
    ("CF_OP_TAX",  "收到的税费返还",            "IN",  "CF_OP"),
    ("CF_OP_BUY",  "购买商品、接受劳务支付的现金", "OUT", "CF_OP"),
    ("CF_OP_EMP",  "支付给职工以及为职工支付的现金", "OUT", "CF_OP"),
    ("CF_OP_PTAX", "支付的各项税费",            "OUT", "CF_OP"),
    # 投资活动
    ("CF_INV",     "投资活动现金流量",          "OUT", None),
    ("CF_INV_FA",  "购建固定资产、无形资产支付的现金", "OUT", "CF_INV"),
    ("CF_INV_RET", "收回投资收到的现金",        "IN",  "CF_INV"),
    # 筹资活动
    ("CF_FIN",     "筹资活动现金流量",          "IN",  None),
    ("CF_FIN_LOAN", "取得借款收到的现金",       "IN",  "CF_FIN"),
    ("CF_FIN_REPAY", "偿还债务支付的现金",      "OUT", "CF_FIN"),
]


# ============================================================
# 运营公司 × 准则映射。
#   • 内地 CNY 本位 → CAS 中文科目表。
#   • 香港 HKD 本位 → HKFRS 中英科目表。
# 选公司用 Company.region（HK/CN）判准则，公司不存在则跳过（容错：种子顺序无依赖）。
# ============================================================
def _accounts_for_region(region: str):
    """按公司区域返回对应准则科目表（HK→HKFRS / CN→CAS）。"""
    return HKFRS_ACCOUNTS if region == "HK" else CAS_ACCOUNTS


def _month_periods(year: int):
    """生成 12 个自然月期间 (period_number, start_date, end_date)。"""
    out = []
    for mth in range(1, 13):
        last = monthrange(year, mth)[1]
        out.append((mth, date(year, mth, 1), date(year, mth, last)))
    return out


# ============================================================
# 7. VOUCHER 工作流定义（states-only JSONB，与 phase1_workflows 同构）
#    DRAFT 录入 → AUDITED 审核 →（资金类）REVIEWED 出纳复核 → POSTED 过账；
#    逆向：POSTED→AUDITED 反过账、AUDITED→DRAFT 反审核。
#    校验器 finance.validate_balance / finance.period_open / finance.segregation_of_duties
#    均 auto=True 按 (VOUCHER, POSTED) 自动触发，无需在边里点名。
#    过账/反过账 effect auto=False，须在边 effects[] 显式点名。
#    取号 NUMBERING_EFFECT 挂 START（已在 numbering_effect 注册到 (VOUCHER, START)）。
#    红冲走 command finance.red_reversal（非状态机边）。
# ============================================================
NUMBERING_EFFECT = "numbering.assign_business_number"

# 录入态可编辑字段（头 + 走子表编辑器的分录）。
_VOUCHER_HEAD_FIELDS = [
    "voucher_date", "voucher_word_id", "voucher_type", "description",
    "period_id", "source_doc_type", "source_doc_id",
]
# 审核/复核/过账留痕字段（审核人在 DRAFT→AUDITED 边写 audited_by_id/audited_at；
# 出纳复核人在 AUDITED→REVIEWED 边写 reviewed_by_id/reviewed_at；本波由前端/seed 写值，未做自动 effect）。
_VOUCHER_AUDIT_FIELDS = ["audited_by_id", "audited_at", "notes"]
_VOUCHER_REVIEW_FIELDS = ["reviewed_by_id", "reviewed_at", "notes"]


def _voucher_states():
    return [
        {
            "code": "START", "name": "开始", "is_initial": True,
            "allowed_roles": ["FINANCE", "FINANCE_DIRECTOR"],
            "description": "# 开始节点\n建空凭证后进入「凭证录入」节点；建单同事务取业务凭证号 PZ-YYMM-NNN。",
            "custom_html": "", "hard_rules": [], "hooks": [],
            "effects": [NUMBERING_EFFECT],
            "next": [{"to": "DRAFT", "label": "开始录入", "editable_fields": []}],
        },
        {
            "code": "DRAFT", "name": "凭证录入",
            "allowed_roles": ["FINANCE", "FINANCE_DIRECTOR"],
            "description": (
                "# 凭证录入\n录入凭证头（凭证字/日期/期间/摘要）与借贷分录（原币 debit/credit + 本位币 "
                "base_debit/base_credit = 原币×汇率；本币记账 rate=1 时 base==原币）。\n"
                "可挂辅助核算（往来对象/部门/项目）、现金流量项目、结算方式/结算号（资金类）。\n"
                "「审核」推进到已审核态；审核人请在本边填 audited_by_id（职责分离要求制单≠审核）。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "AUDITED", "label": "审核",
                 "effects": ["finance.mark_audited"],
                 "editable_fields": _VOUCHER_HEAD_FIELDS + _VOUCHER_AUDIT_FIELDS},
            ],
        },
        {
            "code": "AUDITED", "name": "已审核",
            "allowed_roles": ["FINANCE", "FINANCE_DIRECTOR"],
            "description": (
                "# 已审核\n借贷平衡（finance.validate_balance）、期间须 OPEN（finance.period_open）、"
                "职责分离（finance.segregation_of_duties 制单≠审核≠过账，默认 ON）三校验在「过账」边自动触发。\n"
                "• 普通凭证：「过账」直达 POSTED（触发 finance.post_voucher 累加 AccountBalance）。\n"
                "• 资金类凭证（收/付字，含货币资金科目）：先「出纳复核」到 REVIEWED 再过账。\n"
                "• 「反审核」退回录入态修改（逐月、期间须 OPEN）。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                # 普通凭证：直接过账。三 validator (auto=True) 自动触发。
                {"to": "POSTED", "label": "过账", "editable_fields": ["notes"],
                 "effects": ["finance.post_voucher"]},
                # 资金类：出纳复核后再过账。TODO（下一波）：按「含货币资金科目」判定是否强制经 REVIEWED。
                {"to": "REVIEWED", "label": "出纳复核（资金类）",
                 "effects": ["finance.mark_reviewed"],
                 "editable_fields": _VOUCHER_REVIEW_FIELDS},
                # 反审核：退回录入态。
                {"to": "DRAFT", "label": "反审核", "editable_fields": ["notes"]},
            ],
        },
        {
            "code": "REVIEWED", "name": "出纳已复核",
            # 出纳角色当前不存在（见 scout §6），暂用 FINANCE/FINANCE_DIRECTOR 承载；
            # TODO（下一波）：seed.py 增 CASHIER 角色后改本节点 allowed_roles 为 ["CASHIER"]。
            "allowed_roles": ["FINANCE", "FINANCE_DIRECTOR"],
            "description": (
                "# 出纳已复核（资金类）\n资金类凭证经出纳复核结算方式/结算号/金额后过账。\n"
                "「过账」触发同样三校验 + finance.post_voucher；「退回审核」回 AUDITED。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "POSTED", "label": "过账", "editable_fields": ["notes"],
                 "effects": ["finance.post_voucher"]},
                {"to": "AUDITED", "label": "退回审核", "editable_fields": ["notes"]},
            ],
        },
        {
            "code": "POSTED", "name": "已过账",
            "allowed_roles": ["FINANCE", "FINANCE_DIRECTOR"],
            "description": (
                "# 已过账\n本位币借贷已累加进 AccountBalance（period_debit/period_credit，按科目方向刷 closing）。\n"
                "「反过账」取反余额增量回到已审核态（finance.unpost_voucher；逐月、期间须 OPEN）。\n"
                "已过账凭证如需更正：用红冲命令 finance.red_reversal（原单不删、生反向负数凭证、回链），无「蓝冲」。"
            ),
            "custom_html": "", "hard_rules": [], "hooks": [], "effects": [],
            "next": [
                {"to": "AUDITED", "label": "反过账", "editable_fields": ["notes"],
                 "effects": ["finance.unpost_voucher"]},
            ],
        },
    ]


def voucher_workflow_definition(created_by_id=None):
    d = {
        "doc_type": "VOUCHER",
        "name": "总账-记账凭证",
        "description": (
            "总账·第一波（finance-gl）记账核心闭环：录入 DRAFT → 审核 AUDITED →（资金类）出纳复核 REVIEWED "
            "→ 过账 POSTED。\n过账前三校验（借贷平衡/期间锁/职责分离）；逆操作含反过账（POSTED→AUDITED）、"
            "反审核（AUDITED→DRAFT）；更正走红冲命令 finance.red_reversal（无蓝冲）。"
        ),
        "group_name": "财务",
        "version": 1,
        "is_published": True,
        "is_active": True,
        "node_positions": {
            "START": {"x": 300, "y": 0},
            "DRAFT": {"x": 300, "y": 120},
            "AUDITED": {"x": 300, "y": 250},
            "REVIEWED": {"x": 540, "y": 250},
            "POSTED": {"x": 300, "y": 390},
        },
        "states": _voucher_states(),
    }
    if created_by_id is not None:
        d["created_by_id"] = created_by_id
    return d


# ============================================================
# 幂等 upsert 工具
# ============================================================
async def _get(db, model, **filters):
    stmt = select(model)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalars().first()


async def _seed_company_master_data(db, company):
    """为单家公司种入科目表/凭证字/辅助核算/现金流量/会计期间（幂等，已存在跳过）。

    返回本次各项新增计数 dict，供汇总打印。准则按 company.region 二分（HK→HKFRS / CN→CAS）。
    """
    cid = company.id
    accounts = _accounts_for_region(company.region)
    standard = "HKFRS" if company.region == "HK" else "CAS"

    # --- 1. 科目表（两遍：先建/纳入映射，再回填 parent_id + 标父节点 is_leaf=False）---
    code_to_id: dict[str, int] = {}
    acct_new = 0
    for code, name, atype, bdir, parent_code in accounts:
        acct = await _get(db, m.Account, company_id=cid, code=code)
        if acct is None:
            acct = m.Account(
                company_id=cid, code=code, name=name,
                account_type=atype, balance_direction=bdir,
                level=2 if parent_code else 1,
                is_leaf=True,  # 第二遍据 parent 出现情况修正
                currency=company.currency or "CNY", is_active=True,
            )
            db.add(acct)
            await db.flush()
            acct_new += 1
        code_to_id[code] = acct.id
    for code, name, atype, bdir, parent_code in accounts:
        if parent_code and parent_code in code_to_id:
            child = await _get(db, m.Account, company_id=cid, code=code)
            if child is not None and child.parent_id is None:
                child.parent_id = code_to_id[parent_code]
                child.level = 2
            parent = await _get(db, m.Account, company_id=cid, code=parent_code)
            if parent is not None:
                parent.is_leaf = False
    await db.flush()

    # --- 2. 凭证字 ---
    vw_new = 0
    for code, name, restrict in VOUCHER_WORDS:
        if await _get(db, m.VoucherWord, company_id=cid, code=code) is None:
            db.add(m.VoucherWord(
                company_id=cid, code=code, name=name,
                restrict_multi_dc=restrict, is_active=True,
            ))
            vw_new += 1
    await db.flush()

    # --- 3. 辅助核算维度 ---
    aux_new = 0
    for code, name, stype in AUX_DIMENSIONS:
        if await _get(db, m.AuxiliaryDimension, company_id=cid, code=code) is None:
            db.add(m.AuxiliaryDimension(
                company_id=cid, code=code, name=name,
                source_type=stype, is_active=True,
            ))
            aux_new += 1
    await db.flush()

    # --- 4. 现金流量项目（两遍：父→子回填 parent_id）---
    cf_code_to_id: dict[str, int] = {}
    cf_new = 0
    for code, name, direction, parent_code in CASHFLOW_ITEMS:
        item = await _get(db, m.CashflowItem, company_id=cid, code=code)
        if item is None:
            item = m.CashflowItem(
                company_id=cid, code=code, name=name,
                direction=direction, is_active=True,
            )
            db.add(item)
            await db.flush()
            cf_new += 1
        cf_code_to_id[code] = item.id
    for code, name, direction, parent_code in CASHFLOW_ITEMS:
        if parent_code and parent_code in cf_code_to_id:
            child = await _get(db, m.CashflowItem, company_id=cid, code=code)
            if child is not None and child.parent_id is None:
                child.parent_id = cf_code_to_id[parent_code]
    await db.flush()

    # --- 5. 会计年度 + 12 自然月期间（当前年，OPEN）---
    year = date.today().year
    fy = await _get(db, m.FiscalYear, company_id=cid, year=year)
    if fy is None:
        fy = m.FiscalYear(
            company_id=cid, year=year,
            start_date=date(year, 1, 1), end_date=date(year, 12, 31),
            status="OPEN",
        )
        db.add(fy)
        await db.flush()
    period_new = 0
    for pnum, sd, ed in _month_periods(year):
        if await _get(db, m.AccountingPeriod, fiscal_year_id=fy.id, period_number=pnum) is None:
            db.add(m.AccountingPeriod(
                fiscal_year_id=fy.id, period_number=pnum,
                start_date=sd, end_date=ed, status="OPEN",
            ))
            period_new += 1
    await db.flush()

    # --- 6. 凭证号编号规则 PZ-YYMM-NNN（月度重置，补零3）---
    nr_new = 0
    if await _get(db, m.NumberingRule, company_id=cid, doc_type="VOUCHER") is None:
        db.add(m.NumberingRule(
            company_id=cid, doc_type="VOUCHER", prefix="PZ",
            reset_period="MONTH", seq_padding=3, separator="-", period_format="%y%m",
            current_period="", current_seq=0, is_active=True,
        ))
        nr_new = 1
    await db.flush()

    return {
        "standard": standard, "accounts_total": len(code_to_id),
        "accounts_new": acct_new, "vw_new": vw_new, "aux_new": aux_new,
        "cf_new": cf_new, "period_new": period_new, "nr_new": nr_new,
    }


# ============================================================
# 期末段（finance-gl wave-2 模块 B 追加）：期末汇率种子。
#   期末调汇 finance.fx_revaluation 按「外币→本位币」ExchangeRate 取期末汇率重估。
#   为可 smoke 调汇，按各家本位币种入常用外币对当前年各期末日(月末)的参考汇率（幂等 upsert）。
#   仅当公司本位币为 HKD/CNY 时种入；汇率为占位参考值，正式值由财务维护。
# ============================================================
# (from_currency, to_currency) → 参考汇率（月末统一值，足够 smoke 验调汇差额；正式值财务维护）。
_FX_REFERENCE = {
    ("USD", "HKD"): "7.800000",
    ("CNY", "HKD"): "1.080000",
    ("EUR", "HKD"): "8.500000",
    ("USD", "CNY"): "7.200000",
    ("HKD", "CNY"): "0.925000",
    ("EUR", "CNY"): "7.850000",
}


async def _seed_period_end_exchange_rates(db, companies):
    """按各公司本位币种入「外币→本位币」期末参考汇率（当前年每个月末日，幂等）。

    唯一键 (from_currency, to_currency, effective_date)，已存在跳过。返回新增条数。
    """
    base_ccys = {(c.currency or ("HKD" if c.region == "HK" else "CNY")) for c in companies}
    year = date.today().year
    month_ends = [date(year, mth, monthrange(year, mth)[1]) for mth in range(1, 13)]
    new = 0
    for (frm, to), rate in _FX_REFERENCE.items():
        if to not in base_ccys:
            continue
        for eff in month_ends:
            exists = (await db.execute(
                select(m.ExchangeRate).where(
                    m.ExchangeRate.from_currency == frm,
                    m.ExchangeRate.to_currency == to,
                    m.ExchangeRate.effective_date == eff,
                )
            )).scalars().first()
            if exists is None:
                db.add(m.ExchangeRate(
                    from_currency=frm, to_currency=to,
                    rate=rate, effective_date=eff,
                ))
                new += 1
    await db.flush()
    return new


async def seed_finance():
    factory = get_session_factory()
    async with factory() as db:
        admin = await _get(db, m.UserAccount, username="admin")
        created_by_id = admin.id if admin else None

        # 全部运营公司（6 家：HK 3 + CN 3）。按 region 选准则；公司不存在则整体跳过（先跑 scripts.seed）。
        companies = (await db.execute(select(m.Company).order_by(m.Company.id))).scalars().all()
        if not companies:
            print("未找到任何公司，请先跑 scripts.seed。")
            return

        per_company = []
        for company in companies:
            stats = await _seed_company_master_data(db, company)
            per_company.append((company, stats))

        # 期末段：期末参考汇率（供期末调汇 finance.fx_revaluation smoke）。
        fx_new = await _seed_period_end_exchange_rates(db, companies)

        # === VOUCHER 工作流（全局一份，按 (doc_type, version) upsert：覆盖 seed.py 旧 K3 参考流程）===
        wf_def = voucher_workflow_definition(created_by_id)
        existing_wf = (await db.execute(
            select(m.WorkflowDefinition).where(
                m.WorkflowDefinition.doc_type == "VOUCHER",
                m.WorkflowDefinition.version == wf_def["version"],
            )
        )).scalar_one_or_none()
        if existing_wf:
            existing_wf.name = wf_def["name"]
            existing_wf.description = wf_def["description"]
            existing_wf.states = wf_def["states"]
            existing_wf.group_name = wf_def["group_name"]
            existing_wf.is_published = True
            existing_wf.is_active = True
            existing_wf.node_positions = wf_def["node_positions"]
            wf_action = "已覆盖（对齐记账规格）"
        else:
            db.add(m.WorkflowDefinition(**wf_def))
            wf_action = "已新建"

        await db.commit()

        print("总账·第一波财务种子完成（按公司分准则，全部运营公司）:")
        for company, s in per_company:
            print(
                f"  [{company.code} #{company.id} region={company.region} 本位币={company.currency} 准则={s['standard']}] "
                f"科目 {s['accounts_total']}（新增 {s['accounts_new']}）/ 凭证字+{s['vw_new']} / "
                f"辅助核算+{s['aux_new']} / 现金流量+{s['cf_new']} / 期间+{s['period_new']} / 编号规则+{s['nr_new']}"
            )
        print(f"  VOUCHER 工作流: {wf_action}")
        print(f"  期末参考汇率（外币→本位币，月末日）: 新增 {fx_new} 条（供期末调汇 finance.fx_revaluation）")
        print("  ★用户 home 公司（PTK #1，HK/HKFRS/HKD）已具备完整财务数据，可直接记账。")


if __name__ == "__main__":
    asyncio.run(seed_finance())
