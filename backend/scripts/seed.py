"""
种子数据 — 一次性灌入演示数据

在 backend/ 下执行: python -m scripts.seed
"""

import asyncio
import calendar
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.auth import hash_password
from core.database import Base, get_async_engine, get_session_factory
from services.phase1_workflows import phase1_workflow_definitions
import models as m


async def seed():
    engine = get_async_engine()
    factory = get_session_factory()

    async with factory() as db:
        # 检查是否已有数据
        result = await db.execute(select(m.Company))
        if result.scalar_one_or_none():
            print("数据已存在，跳过。如需重新灌入请清空数据库。")
            return

        # === 公司 ===
        companies = {}
        for code, name, short, currency, tax, country in [
            ("HK_MAIN", "PHOTONTECK (HK) Limited", "香港主体", "USD", "NONE", "香港"),
            ("HK_02", "PHOTONTECK Trading (HK) Ltd", "香港二号", "USD", "NONE", "香港"),
            ("SZ_CN", "深圳光子科技有限公司", "深圳公司", "CNY", "VAT", "中国"),
            ("WH_CN", "武汉光子科技有限公司", "武汉公司", "CNY", "VAT", "中国"),
            ("SG_01", "PHOTONTECK (SG) Pte Ltd", "新加坡公司", "SGD", "NONE", "新加坡"),
            ("BVI_01", "PHOTONTECK Global Ltd", "BVI公司", "USD", "NONE", "BVI"),
        ]:
            c = m.Company(code=code, name=name, short_name=short, currency=currency, tax_type=tax, country=country)
            db.add(c)
            companies[code] = c
        await db.flush()

        hk = companies["HK_MAIN"]

        # === 用户 ===
        pwd = hash_password("demo1234")
        admin_pwd = hash_password("admin1234")

        users = {}
        for uname, full, role, comp, is_admin in [
            ("admin", "系统管理员", "ADMIN", hk, True),
            ("jerry", "Jerry毛总", "BOSS", hk, False),
            ("peyton", "Peyton", "OPERATIONS", hk, False),
            ("cathy", "Cathy", "FINANCE", hk, False),
            ("se_wang", "王工(销售)", "SALES_ENGINEER", hk, False),
            ("sa_li", "李助理(SA)", "SALES_ASSISTANT", hk, False),
            ("pm_zhang", "张经理(产品)", "PRODUCT_MANAGER", hk, False),
            ("pa_chen", "陈助理(PA)", "PRODUCT_ASSISTANT", hk, False),
            ("wh_liu", "刘师傅(物流)", "LOGISTICS", hk, False),
        ]:
            u = m.UserAccount(
                username=uname, password_hash=admin_pwd if uname == "admin" else pwd,
                full_name=full, role=role, company_id=comp.id, is_admin=is_admin,
            )
            db.add(u)
            users[uname] = u
        await db.flush()

        # Jerry和Cathy可看所有公司
        for comp in companies.values():
            for uname in ["jerry", "cathy"]:
                db.add(m.UserCompanyAccess(user_id=users[uname].id, company_id=comp.id))

        # === 物料分类 ===
        cats = {}
        for code, name in [
            ("LASER", "光源/激光器"), ("DETECTOR", "探测器"), ("MODULATOR", "光调制器"),
            ("FIBER", "光纤/跳线"), ("CAMERA", "相机"), ("OPTICS", "光学无源器件"),
            ("ELECTRONICS", "电子控制"), ("OPTCOMM", "光通信器件"),
        ]:
            c = m.MaterialCategory(code=code, name=name)
            db.add(c)
            cats[code] = c
        await db.flush()

        # === 供应商 ===
        suppliers = {}
        for code, name, country in [
            ("TOPTICA", "TOPTICA Photonics", "德国"), ("THORLABS", "Thorlabs", "美国"),
            ("HAMAMATSU", "Hamamatsu (滨松)", "日本"), ("NKT", "NKT Photonics", "丹麦"),
            ("IDQUAN", "ID Quantique", "瑞士"), ("ROHM", "ROHM (罗姆)", "日本"),
            ("MARUWA", "Maruwa (王和)", "日本"), ("XINDA", "信达贸易", "中国"),
            ("CONNET", "康耐特光电(国产)", "中国"), ("LUMENTUM", "Lumentum", "美国"),
        ]:
            s = m.Supplier(code=code, name=name, country=country, company_id=hk.id, created_by_id=users["admin"].id)
            db.add(s)
            suppliers[code] = s
        await db.flush()

        # === 物料 ===
        materials = {}
        for sku, name, sup, cat, domestic, specs in [
            ("TOP-DLC-PRO", "TOPTICA DL pro 可调谐二极管激光器", "TOPTICA", "LASER", False,
             {"wavelength_nm": "370-1770", "linewidth_khz": "<100", "power_mw": "50-120"}),
            ("HAM-C14900", "Hamamatsu sCMOS相机 C14900", "HAMAMATSU", "CAMERA", False,
             {"resolution": "2048x2048", "frame_rate_fps": 100}),
            ("NKT-SC480", "NKT SuperK EXTREME超连续谱光源", "NKT", "LASER", False,
             {"wavelength_nm": "400-2400", "power_w": 8}),
            ("IDQ-ID281", "ID Quantique ID281 超导单光子探测器", "IDQUAN", "DETECTOR", False,
             {"wavelength_nm": "900-1600", "efficiency_pct": ">90"}),
            ("TL-PM100D", "Thorlabs PM100D 光功率计", "THORLABS", "ELECTRONICS", False,
             {"wavelength_nm": "400-1100"}),
            ("CON-SOA1550", "康耐特 SOA 1550nm光放大器", "CONNET", "OPTCOMM", True,
             {"wavelength_nm": 1550, "gain_db": 25}),
            ("LUM-ITLA100", "Lumentum ITLA 可调谐激光器模块", "LUMENTUM", "OPTCOMM", False,
             {"wavelength_nm": "1527-1567", "power_dbm": 16}),
            ("ROHM-LD650", "ROHM 650nm半导体激光器", "ROHM", "LASER", False,
             {"wavelength_nm": 650, "power_mw": 10}),
        ]:
            mat = m.Material(sku=sku, name=name, supplier_id=suppliers[sup].id, category_id=cats[cat].id,
                           is_domestic=domestic, technical_specs=specs)
            db.add(mat)
            materials[sku] = mat
        await db.flush()

        # === 客户 ===
        customers = {}
        for code, name, currency, terms, shipping in [
            ("INTEL", "Intel Corporation", "USD", 60, "FOB"),
            ("TENCENT", "腾讯科技", "CNY", 30, "DAP"),
            ("HUAWEI", "华为技术有限公司", "CNY", 45, "DAP"),
            ("USTC", "中国科学技术大学", "CNY", 30, "DAP"),
            ("NTU_SG", "南洋理工大学", "SGD", 30, "CIF"),
        ]:
            c = m.Customer(code=code, name=name, default_currency=currency, payment_terms_days=terms,
                          default_shipping_method=shipping, company_id=hk.id, created_by_id=users["admin"].id)
            db.add(c)
            customers[code] = c
        await db.flush()

        # === 仓库 ===
        wh_hk = m.Warehouse(code="WH-HK", name="香港主仓", warehouse_type="MAIN", city="香港",
                           company_id=hk.id, created_by_id=users["admin"].id)
        wh_wh = m.Warehouse(code="WH-WH", name="武汉保税区仓", warehouse_type="BONDED", city="武汉",
                           company_id=companies["WH_CN"].id, created_by_id=users["admin"].id)
        wh_sz = m.Warehouse(code="WH-SZ", name="深圳仓", warehouse_type="BRANCH", city="深圳",
                           company_id=companies["SZ_CN"].id, created_by_id=users["admin"].id)
        db.add_all([wh_hk, wh_wh, wh_sz])
        await db.flush()

        # === 销售订单 ===
        today = date.today()
        so1 = m.SalesOrder(
            order_number="SO-2025-0001", customer_id=customers["INTEL"].id,
            sales_engineer_id=users["se_wang"].id, sales_assistant_id=users["sa_li"].id,
            currency="USD", total_amount=Decimal("185000"), payment_terms_days=60,
            status="APPROVED",
            company_id=hk.id, created_by_id=users["sa_li"].id,
        )
        so2 = m.SalesOrder(
            order_number="SO-2025-0002", customer_id=customers["TENCENT"].id,
            sales_engineer_id=users["se_wang"].id, sales_assistant_id=users["sa_li"].id,
            currency="CNY", total_amount=Decimal("580000"), payment_terms_days=30,
            status="DRAFT",
            company_id=hk.id, created_by_id=users["sa_li"].id,
        )
        db.add_all([so1, so2])
        await db.flush()

        db.add_all([
            m.SalesOrderLine(sales_order_id=so1.id, line_number=1, material_id=materials["TOP-DLC-PRO"].id,
                           quantity=5, unit_price=Decimal("25000"), total_price=Decimal("125000"),
                           requested_delivery_date=today + timedelta(days=30)),
            m.SalesOrderLine(sales_order_id=so1.id, line_number=2, material_id=materials["TL-PM100D"].id,
                           quantity=20, unit_price=Decimal("3000"), total_price=Decimal("60000"),
                           requested_delivery_date=today + timedelta(days=20)),
            m.SalesOrderLine(sales_order_id=so2.id, line_number=1, material_id=materials["LUM-ITLA100"].id,
                           quantity=10, unit_price=Decimal("38000"), total_price=Decimal("380000")),
            m.SalesOrderLine(sales_order_id=so2.id, line_number=2, material_id=materials["CON-SOA1550"].id,
                           quantity=40, unit_price=Decimal("5000"), total_price=Decimal("200000")),
        ])

        # === 采购订单 ===
        po1 = m.PurchaseOrder(
            order_number="PO-2025-0001", supplier_id=suppliers["TOPTICA"].id,
            purchase_assistant_id=users["pa_chen"].id, related_sales_order_id=so1.id,
            currency="USD", total_amount=Decimal("75000"),
            expected_delivery_date=today + timedelta(days=25), status="ORDERED",
            company_id=hk.id, created_by_id=users["pa_chen"].id,
        )
        db.add(po1)
        await db.flush()

        db.add(m.PurchaseOrderLine(
            purchase_order_id=po1.id, line_number=1, material_id=materials["TOP-DLC-PRO"].id,
            quantity=5, unit_price=Decimal("15000"), total_price=Decimal("75000"),
        ))

        # === 库存 ===
        for sku, wh, batch, qty, recv in [
            ("TL-PM100D", wh_hk, "B-20250301-001", 50, today - timedelta(days=30)),
            ("TL-PM100D", wh_hk, "B-20250315-002", 30, today - timedelta(days=15)),
            ("ROHM-LD650", wh_hk, "B-20250201-001", 200, today - timedelta(days=60)),
            ("CON-SOA1550", wh_sz, "B-20250310-001", 25, today - timedelta(days=20)),
            ("HAM-C14900", wh_hk, "B-20250220-001", 8, today - timedelta(days=45)),
            ("IDQ-ID281", wh_hk, "B-20250305-001", 3, today - timedelta(days=25)),
        ]:
            db.add(m.Inventory(
                material_id=materials[sku].id, warehouse_id=wh.id, batch_number=batch,
                quantity=qty, received_date=recv, company_id=wh.company_id,
                created_by_id=users["admin"].id,
            ))

        # === 应收应付 ===
        db.add(m.AccountsReceivable(
            customer_id=customers["INTEL"].id, sales_order_id=so1.id,
            invoice_number="INV-2025-0001", amount=Decimal("185000"), currency="USD",
            due_date=today + timedelta(days=50), company_id=hk.id, created_by_id=users["cathy"].id,
        ))
        db.add(m.AccountsPayable(
            supplier_id=suppliers["TOPTICA"].id, purchase_order_id=po1.id,
            invoice_number="TOPTICA-INV-88123", amount=Decimal("75000"), currency="USD",
            due_date=today + timedelta(days=30), company_id=hk.id, created_by_id=users["cathy"].id,
        ))

        # === 信用额度 ===
        db.add(m.SupplierCredit(supplier_id=suppliers["TOPTICA"].id, credit_limit=Decimal("500000"),
                               used_amount=Decimal("320000"), currency="USD", company_id=hk.id, created_by_id=users["admin"].id))
        db.add(m.CustomerCredit(customer_id=customers["INTEL"].id, credit_limit=Decimal("2000000"),
                               used_amount=Decimal("850000"), currency="USD", company_id=hk.id, created_by_id=users["admin"].id))

        # === 会计科目表 ===
        ACCOUNTS = [
            ("1", "资产", "ASSET", "DEBIT", None, False),
            ("1001", "库存现金", "ASSET", "DEBIT", "1", True),
            ("1002", "银行存款", "ASSET", "DEBIT", "1", True),
            ("1012", "其他货币资金", "ASSET", "DEBIT", "1", True),
            ("1122", "应收账款", "ASSET", "DEBIT", "1", True),
            ("1123", "预付账款", "ASSET", "DEBIT", "1", True),
            ("1221", "其他应收款", "ASSET", "DEBIT", "1", True),
            ("1405", "库存商品", "ASSET", "DEBIT", "1", True),
            ("1601", "固定资产", "ASSET", "DEBIT", "1", True),
            ("1602", "累计折旧", "ASSET", "CREDIT", "1", True),
            ("2", "负债", "LIABILITY", "CREDIT", None, False),
            ("2202", "应付账款", "LIABILITY", "CREDIT", "2", True),
            ("2203", "预收账款", "LIABILITY", "CREDIT", "2", True),
            ("2211", "应付职工薪酬", "LIABILITY", "CREDIT", "2", True),
            ("2221", "应交税费", "LIABILITY", "CREDIT", "2", True),
            ("2241", "其他应付款", "LIABILITY", "CREDIT", "2", True),
            ("3", "所有者权益", "EQUITY", "CREDIT", None, False),
            ("4001", "实收资本", "EQUITY", "CREDIT", "3", True),
            ("4103", "盈余公积", "EQUITY", "CREDIT", "3", True),
            ("4104", "本年利润", "EQUITY", "CREDIT", "3", True),
            ("4105", "利润分配", "EQUITY", "CREDIT", "3", True),
            ("5", "收入", "REVENUE", "CREDIT", None, False),
            ("6001", "主营业务收入", "REVENUE", "CREDIT", "5", True),
            ("6051", "其他业务收入", "REVENUE", "CREDIT", "5", True),
            ("6301", "营业外收入", "REVENUE", "CREDIT", "5", True),
            ("6", "成本费用", "EXPENSE", "DEBIT", None, False),
            ("6401", "主营业务成本", "COGS", "DEBIT", "6", True),
            ("6402", "其他业务成本", "COGS", "DEBIT", "6", True),
            ("6601", "销售费用", "EXPENSE", "DEBIT", "6", True),
            ("6602", "管理费用", "EXPENSE", "DEBIT", "6", True),
            ("6603", "财务费用", "EXPENSE", "DEBIT", "6", True),
            ("6801", "所得税费用", "EXPENSE", "DEBIT", "6", True),
        ]
        for comp in companies.values():
            parent_map = {}
            for code, name, atype, direction, parent_code, is_leaf in ACCOUNTS:
                parent_id = parent_map.get(parent_code)
                level = 1 if parent_code is None else 2
                acc = m.Account(company_id=comp.id, code=code, name=name, account_type=atype,
                              balance_direction=direction, parent_id=parent_id, level=level,
                              is_leaf=is_leaf, currency=comp.currency)
                db.add(acc)
                await db.flush()
                parent_map[code] = acc.id

        # === 汇率 ===
        for frm, to, rate in [("USD", "CNY", "7.2450"), ("USD", "HKD", "7.8100"), ("USD", "SGD", "1.3400")]:
            db.add(m.ExchangeRate(from_currency=frm, to_currency=to, rate=Decimal(rate), effective_date=today))

        # === 会计期间 ===
        year = today.year
        for comp in companies.values():
            fy = m.FiscalYear(company_id=comp.id, year=year, start_date=date(year, 1, 1), end_date=date(year, 12, 31))
            db.add(fy)
            await db.flush()
            for month in range(1, 13):
                last_day = calendar.monthrange(year, month)[1]
                db.add(m.AccountingPeriod(
                    fiscal_year_id=fy.id, period_number=month,
                    start_date=date(year, month, 1), end_date=date(year, month, last_day),
                ))

        # === 流程定义（基于K3截图+需求文档的真实流程）===
        # 格式: (doc_type, name, description, states, transitions)
        # transitions: (name, from, to, roles, editable, prompt, tools)
        T = ["query_data", "calculate", "compare", "aggregate"]
        workflows = [
            # ====== 总账流程-主流程（严格按K3总账流程图）======
            # K3: 科目→凭证录入→凭证审核→凭证过账→期末调汇→结转损益→期末结账
            # 分支: 凭证过账→往来管理→期末调汇; 凭证过账→账簿查询/财务报表查询(终态)
            # 右侧报表节点: 总分类账/明细分类账/多栏账/核算项目明细账/核算项目余额表/试算平衡表/科目余额表
            ("VOUCHER", "总账流程-主流程",
             "严格按K3总账流程图主流程：科目→凭证录入→凭证审核→凭证过账→期末调汇→结转损益→期末结账。"
             "分支：过账后可做往来管理；过账后可查询账簿和财务报表。"
             "支持手工录入和业务自动生成。",
             [
                # 核心流程节点（state）
                {"code": "ACCOUNT_READY", "name": "科目", "is_initial": True},
                {"code": "DRAFT", "name": "凭证录入"},
                {"code": "AUDITED", "name": "凭证审核"},
                {"code": "POSTED", "name": "凭证过账"},
                {"code": "RECONCILED", "name": "往来管理"},
                {"code": "FX_ADJUSTED", "name": "期末调汇"},
                {"code": "PL_TRANSFERRED", "name": "结转损益"},
                {"code": "CLOSED", "name": "期末结账", "is_terminal": True},
                # 查询分支（cross_module，终态）
                {"code": "LEDGER_QUERIED", "name": "账簿查询", "is_terminal": True, "node_type": "cross_module"},
                {"code": "REPORT_QUERIED", "name": "财务报表查询", "is_terminal": True, "node_type": "cross_module"},
                # 报表节点（report）
                {"code": "RPT_GENERAL_LEDGER", "name": "总分类账", "node_type": "report"},
                {"code": "RPT_DETAIL_LEDGER", "name": "明细分类账", "node_type": "report"},
                {"code": "RPT_MULTI_COL", "name": "多栏账", "node_type": "report"},
                {"code": "RPT_PROJECT_DETAIL", "name": "核算项目明细账", "node_type": "report"},
                {"code": "RPT_PROJECT_BALANCE", "name": "核算项目余额表", "node_type": "report"},
                {"code": "RPT_TRIAL_BALANCE", "name": "试算平衡表", "node_type": "report"},
                {"code": "RPT_ACCOUNT_BALANCE", "name": "科目余额表", "node_type": "report"},
             ], [
                # 前置：科目启用
                ("启用科目", "ACCOUNT_READY", "DRAFT", ["FINANCE"],
                 [], "会计科目已设置完成，可以开始录入凭证。", []),
                # 凭证生命周期
                ("提交审核", "DRAFT", "AUDITED", ["FINANCE"],
                 [], "检查借贷是否平衡、金额>0、科目是否为明细科目。", T),
                ("审核退回", "AUDITED", "DRAFT", ["FINANCE"],
                 [], "退回修改。说明退回原因。", []),
                ("审核过账", "AUDITED", "POSTED", ["FINANCE", "BOSS"],
                 [], "过账更新科目余额。过账后凭证不可修改。", T),
                # 往来管理分支
                ("往来核对", "POSTED", "RECONCILED", ["FINANCE"],
                 [], "往来管理：与客户/供应商对账，核对应收应付余额。", T),
                ("往来转调汇", "RECONCILED", "FX_ADJUSTED", ["FINANCE"],
                 [], "往来核对完成进入期末调汇。", T),
                # 查询分支（单向终态）
                ("查询账簿", "POSTED", "LEDGER_QUERIED", ["FINANCE", "BOSS"],
                 [], "查询总分类账/明细分类账/多栏账/核算项目账等账簿视图。", T),
                ("查询财报", "POSTED", "REPORT_QUERIED", ["FINANCE", "BOSS"],
                 [], "查询试算平衡表/科目余额表等财务报表。", T),
                # 期末主流程
                ("过账直接调汇", "POSTED", "FX_ADJUSTED", ["FINANCE"],
                 [], "凭证过账完成后进入期末调汇（多币种汇率调整，生成调汇差额凭证）。", T),
                ("结转损益", "FX_ADJUSTED", "PL_TRANSFERRED", ["FINANCE"],
                 [], "收入类和费用类科目余额结转到本年利润。收入费用科目清零。", T),
                ("期末结账", "PL_TRANSFERRED", "CLOSED", ["FINANCE", "BOSS"],
                 [], "关闭本会计期间。本期期末余额成为下期期初。结账后不可录入凭证。", T),
             ]),

            # ====== 总账流程-调整期间业务处理（K3左下角独立模块）======
            # 拓扑：调整期间业务处理 (中枢) ─┬→ 调整期间管理
            #                              ├→ 调整期间凭证录入
            #                              ├→ 调整期间凭证过账
            #                              └→ 调整期间凭证查询
            ("VOUCHER_ADJUSTMENT", "总账流程-调整期间业务处理",
             "参考K3总账流程图左下角调整期间模块。调整期间业务处理作为统一入口，"
             "分发到四个操作：调整期间管理、调整期间凭证录入、调整期间凭证过账、调整期间凭证查询。"
             "用于年末审计调整，在正常12个会计期间之外的第13期操作。",
             [
                {"code": "PROCESSING", "name": "调整期间业务处理", "is_initial": True},
                {"code": "PERIOD_MANAGED", "name": "调整期间管理", "is_terminal": True},
                {"code": "ENTRY", "name": "调整期间凭证录入", "is_terminal": True},
                {"code": "POSTED", "name": "调整期间凭证过账", "is_terminal": True},
                {"code": "QUERIED", "name": "调整期间凭证查询", "is_terminal": True},
             ], [
                ("调整期间管理", "PROCESSING", "PERIOD_MANAGED", ["FINANCE", "BOSS"],
                 [], "管理调整期间：开启/关闭第13期。", []),
                ("调整期间凭证录入", "PROCESSING", "ENTRY", ["FINANCE"],
                 [], "在调整期间内录入审计调整凭证。", T),
                ("调整期间凭证过账", "PROCESSING", "POSTED", ["FINANCE", "BOSS"],
                 [], "对已录入的调整凭证审核过账。", T),
                ("调整期间凭证查询", "PROCESSING", "QUERIED", ["FINANCE", "BOSS"],
                 [], "查询调整期间凭证及对科目余额的影响。", []),
             ]),

            # ====== 应收款管理流程（参考K3应收管理流程图，12节点）======
            # 矩形业务节点(8)：信用管理、合同、发票、坏账管理、收款、到款结算、凭证处理、期末处理
            # 云朵外部模块(4)：销售管理→发票、现金管理→收款、应收票据→收款、凭证处理→总账
            ("ACCOUNTS_RECEIVABLE", "应收款管理流程",
             "参考K3应收管理流程图。主路径：信用管理→合同→发票→收款→凭证处理→期末处理。"
             "外部联动：销售管理触发开票；现金管理/应收票据触发收款；凭证处理输出至总账。"
             "旁支：发票/收款 → 坏账管理；收款 → 到款结算（明细核销）。"
             "报表：应收款明细表/汇总表、账龄分析、往来对账单、到期债权列表、到期债权分析、回款分析、合同金额执行汇总表、合同到期欠款明细表、信用额度分析。",
             [
                # 核心流程节点（state）
                {"code": "CREDIT_MANAGED", "name": "信用管理", "is_initial": True},
                {"code": "CONTRACT_REGISTERED", "name": "合同", "is_initial": True},
                {"code": "INVOICED", "name": "发票"},
                {"code": "COLLECTING", "name": "收款"},
                {"code": "BAD_DEBT", "name": "坏账管理", "is_terminal": True},
                {"code": "NOTES_RECV", "name": "应收票据"},
                {"code": "SETTLED", "name": "到款结算", "is_terminal": True},
                {"code": "VOUCHER_PROCESSED", "name": "凭证处理"},
                {"code": "CLOSED", "name": "期末处理", "is_terminal": True},
                # 外部模块节点（cross_module）
                {"code": "SALES_MGMT", "name": "销售管理", "node_type": "cross_module"},
                {"code": "CASH_MGMT", "name": "现金管理", "node_type": "cross_module"},
                {"code": "GL_LINK", "name": "总账", "is_terminal": True, "node_type": "cross_module"},
                # 报表节点（report）
                {"code": "RPT_AR_DETAIL", "name": "应收款明细表", "node_type": "report"},
                {"code": "RPT_AR_SUMMARY", "name": "应收款汇总表", "node_type": "report"},
                {"code": "RPT_RECONCILIATION", "name": "往来对账单", "node_type": "report"},
                {"code": "RPT_AGING", "name": "账龄分析", "node_type": "report"},
                {"code": "RPT_DUE_LIST", "name": "到期债权列表", "node_type": "report"},
                {"code": "RPT_SALES_ANALYSIS", "name": "销售分析", "node_type": "report"},
                {"code": "RPT_COLLECTION", "name": "回款分析", "node_type": "report"},
                {"code": "RPT_CONTRACT_EXEC", "name": "合同金额执行汇总表", "node_type": "report"},
                {"code": "RPT_CONTRACT_DUE", "name": "合同到期款项列表", "node_type": "report"},
                {"code": "RPT_CREDIT_LIMIT", "name": "信用额度分析", "node_type": "report"},
             ], [
                # 信用管理 → 合同
                ("信用审核通过", "CREDIT_MANAGED", "CONTRACT_REGISTERED", ["FINANCE"],
                 ["customer_id"], "维护客户信用额度/账期/评级（在customer_credit表）。审核通过后允许签订合同。", T),
                # 合同 → 发票
                ("基于合同开票", "CONTRACT_REGISTERED", "INVOICED", ["FINANCE"],
                 ["contract_id", "invoice_number", "amount", "due_date"],
                 "根据销售合同开具发票。选合同、填发票号、金额、到期日。", T),
                # 销售管理 → 发票（外部触发）
                ("销售订单触发开票", "SALES_MGMT", "INVOICED", ["FINANCE", "SALES_ASSISTANT"],
                 ["sales_order_id", "invoice_number", "amount", "due_date"],
                 "销售管理模块联动：销售出库后生成发票。关联销售订单。", T),
                # 发票 → 收款 / 坏账
                ("登记收款", "INVOICED", "COLLECTING", ["FINANCE"],
                 [], "发票开具后进入收款流程。", []),
                ("发票转坏账", "INVOICED", "BAD_DEBT", ["FINANCE", "BOSS"],
                 [], "客户违约或破产，发票直接确认坏账。需老板审批。", []),
                # 现金管理 / 应收票据 → 收款（外部触发）
                ("现金到账", "CASH_MGMT", "COLLECTING", ["FINANCE"],
                 ["paid_amount", "paid_date"], "现金管理模块联动：银行/现金收到客户款项（bank_receipt表登记流水）。", T),
                ("票据到账", "NOTES_RECV", "COLLECTING", ["FINANCE"],
                 ["paid_amount", "paid_date"], "应收票据模块联动：商业汇票/银行承兑到期收款（notes_receivable表登记票据）。", T),
                # 收款 → 到款结算 / 凭证处理 / 坏账
                ("到款结算", "COLLECTING", "SETTLED", ["FINANCE"],
                 ["settlement_batch_no"], "针对收到的款项进行明细核销和结算处理（ar_settlement表生成核销明细）。填核销批号。", T),
                ("生成凭证", "COLLECTING", "VOUCHER_PROCESSED", ["FINANCE"],
                 [], "生成收款记账凭证（借银行存款，贷应收账款）。hook自动创建voucher+分录并关联。", T),
                # 凭证处理 → 总账 / 期末
                ("传入总账", "VOUCHER_PROCESSED", "GL_LINK", ["FINANCE"],
                 [], "凭证传入总账模块，更新应收科目余额（通过voucher.status=POSTED体现）。", T),
                ("期末处理", "VOUCHER_PROCESSED", "CLOSED", ["FINANCE", "BOSS"],
                 [], "月末/年末结账。应收科目余额结转下期。", T),
             ]),

            # ====== 应付款管理流程（参考K3应付管理流程图）======
            # 主流程: 合同→发票→付款→凭证处理→期末处理
            # 分支: 付款→付款结算
            # 外部模块: 采购管理→发票; 票据处理→发票; 现金管理→付款
            ("ACCOUNTS_PAYABLE", "应付款管理流程",
             "参考K3应付管理流程图。主流程：合同→发票→付款→凭证处理→期末处理。"
             "外部输入：采购管理（采购入库触发发票核对）、票据处理（商业汇票）、现金管理（资金支持）。"
             "分支：付款→付款结算（核销明细）。"
             "报表：应付款明细表/汇总表、往来对账单、到期债务列表、账龄分析、付款分析、合同到期款项。",
             [
                {"code": "CONTRACT_REGISTERED", "name": "合同", "is_initial": True},
                {"code": "INVOICED", "name": "发票"},
                {"code": "PENDING", "name": "付款"},
                {"code": "SETTLED", "name": "付款结算"},
                {"code": "VOUCHER_PROCESSED", "name": "凭证处理"},
                {"code": "PARTIAL", "name": "部分付款"},
                {"code": "PAID", "name": "全额付款"},
                {"code": "OVERDUE", "name": "逾期"},
                {"code": "CLOSED", "name": "期末处理", "is_terminal": True},
             ], [
                # 合同→发票
                ("采购触发发票", "CONTRACT_REGISTERED", "INVOICED", ["FINANCE"],
                 ["invoice_number", "amount", "due_date"],
                 "采购入库后收到供应商发票。填发票号、金额、到期日。核对发票与入库单。", T),
                ("票据处理转发票", "CONTRACT_REGISTERED", "INVOICED", ["FINANCE"],
                 ["invoice_number", "amount", "due_date"],
                 "商业汇票等票据关联到应付发票。填发票号、金额、到期日。", T),
                ("基于合同收发票", "CONTRACT_REGISTERED", "INVOICED", ["FINANCE"],
                 ["invoice_number", "amount", "due_date"],
                 "根据采购合同收到并登记发票。填发票号、金额、到期日。", T),
                # 发票→付款
                ("安排付款", "INVOICED", "PENDING", ["FINANCE"],
                 [], "发票确认后进入付款流程。现金管理提供资金支持。", T),
                ("标记逾期", "PENDING", "OVERDUE", ["FINANCE"],
                 [], "超过约定付款期。可能影响供应商信用。", []),
                # 付款
                ("部分付款", "PENDING", "PARTIAL", ["FINANCE"],
                 ["paid_amount", "paid_date"], "部分付款。现金管理记账。填实际付了多少、什么时候付的。", T),
                ("全额付款", "PENDING", "PAID", ["FINANCE"],
                 ["paid_amount", "paid_date"], "全额付款核销。paid_amount 应等于 amount。", T),
                ("付清尾款", "PARTIAL", "PAID", ["FINANCE"],
                 ["paid_amount", "paid_date"], "剩余款项付清。paid_amount = amount（总已付）。", T),
                ("逾期后付款", "OVERDUE", "PAID", ["FINANCE"],
                 ["paid_amount", "paid_date"], "逾期后付款。", T),
                # 付款→结算 + 凭证
                ("付款结算", "PAID", "SETTLED", ["FINANCE"],
                 [], "具体的付款结算操作，核销发票明细。", T),
                ("生成凭证", "SETTLED", "VOUCHER_PROCESSED", ["FINANCE"],
                 [], "生成付款记账凭证（借应付账款，贷银行存款）。", T),
                # 凭证→期末
                ("期末处理", "VOUCHER_PROCESSED", "CLOSED", ["FINANCE", "BOSS"],
                 [], "月末/年末结账。凭证过账到总账。", T),
             ]),

            # ====== 采购管理流程（参考K3采购管理流程图）======
            # 主流程: 物料需求计划→采购申请单→采购订单→收料通知/请检单→外购入库单→采购发票→应付款管理
            # 辅助输入: 供应商供货信息→采购申请单; 采购合同→采购订单; 采购价格管理→采购订单
            # 质量分支: 采购订单→质量管理; 收料通知→退料通知单; 质量管理→退料通知单或外购入库单
            ("PURCHASE_ORDER", "采购管理流程",
             "参考K3采购管理流程图。主流程：物料需求计划→采购申请单→采购订单→收料通知/请检单→外购入库单→采购发票→应付款管理。"
             "辅助输入：供应商供货信息（建议供应商）、采购合同（订单依据）、采购价格管理（价格控制）。"
             "质量分支：质量管理检验物料，合格入库，不合格生成退料通知单。"
             "报表：采购订单执行汇总/明细、采购汇总/明细、采购发票明细、供应商准时交货/价格趋势/供货质量分析。",
             [
                {"code": "MATERIAL_REQUEST", "name": "物料需求计划", "is_initial": True},
                {"code": "PURCHASE_REQUEST", "name": "采购申请单"},
                {"code": "DRAFT", "name": "采购订单"},
                {"code": "ORDERED", "name": "已下单给原厂"},
                {"code": "RECEIVING_NOTICE", "name": "收料通知/请检单"},
                {"code": "QUALITY_CHECK", "name": "质量管理"},
                {"code": "RETURN_NOTICE", "name": "退料通知单", "is_terminal": True},
                {"code": "STOCKED_IN", "name": "外购入库单"},
                {"code": "INVOICED", "name": "采购发票"},
                {"code": "TRANSFERRED_AP", "name": "应付款管理", "is_terminal": True},
                {"code": "CANCELLED", "name": "已取消", "is_terminal": True},
             ], [
                # 主流程
                ("生成采购申请", "MATERIAL_REQUEST", "PURCHASE_REQUEST", ["PRODUCT_ASSISTANT", "OPERATIONS"],
                 [], "基于物料需求计划和供应商供货信息，生成采购申请单。", T),
                ("生成采购订单", "PURCHASE_REQUEST", "DRAFT", ["PRODUCT_ASSISTANT", "OPERATIONS"],
                 [], "基于采购申请、采购合同、采购价格管理，生成采购订单。", T),
                ("下单给供应商", "DRAFT", "ORDERED", ["PRODUCT_ASSISTANT", "OPERATIONS"],
                 ["expected_delivery_date"], "发送采购订单给原厂。确认预计交期。信用额度内先货后款，超额先预付。", T),
                ("收到货物", "ORDERED", "RECEIVING_NOTICE", ["LOGISTICS"],
                 ["actual_delivery_date"], "供应商发货到达，生成收料通知/请检单。填实际到货日期。核对装箱单数量，注意信达等中间商包装问题。", T),
                # 质量分支
                ("送质检", "RECEIVING_NOTICE", "QUALITY_CHECK", ["LOGISTICS"],
                 [], "质量管理环节。按原厂标准抽检或全检。", []),
                ("收料即发现异常退料", "RECEIVING_NOTICE", "RETURN_NOTICE", ["LOGISTICS"],
                 [], "收料时直接发现明显异常（漏气、严重损坏），立即生成退料通知单。", []),
                ("质检不合格退料", "QUALITY_CHECK", "RETURN_NOTICE", ["LOGISTICS"],
                 [], "质检不合格，生成退料通知单，联系供应商退换。", []),
                ("质检合格入库", "QUALITY_CHECK", "STOCKED_IN", ["LOGISTICS", "OPERATIONS"],
                 [], "质检通过，生成外购入库单。扫码入库，按FIFO上架。", T),
                ("免检直接入库", "RECEIVING_NOTICE", "STOCKED_IN", ["LOGISTICS", "OPERATIONS"],
                 [], "免检物料（信任度高的原厂）直接入库。", []),
                # 发票和应付
                ("收到采购发票", "STOCKED_IN", "INVOICED", ["FINANCE"],
                 [], "收到供应商开来的发票，核对与入库单一致。", T),
                ("转应付款管理", "INVOICED", "TRANSFERRED_AP", ["FINANCE"],
                 [], "采购发票转入应付款管理模块，生成应付账款。", T),
                # 取消
                ("取消采购", "MATERIAL_REQUEST", "CANCELLED", ["PRODUCT_ASSISTANT", "OPERATIONS", "BOSS"],
                 [], "", []),
                ("申请阶段取消", "PURCHASE_REQUEST", "CANCELLED", ["PRODUCT_ASSISTANT", "OPERATIONS", "BOSS"],
                 [], "", []),
                ("订单阶段取消", "DRAFT", "CANCELLED", ["PRODUCT_ASSISTANT", "OPERATIONS", "BOSS"],
                 [], "", []),
             ]),

            # ====== 销售管理流程（参考K3销售管理流程图）======
            # 前序: 模拟报价单→报价单; 报价单/销售合同/价格政策→销售订单
            # 主流程: 销售订单→发货通知单→销售出库单→销售发票→应收款/存货核算
            # 分支: 销售订单→主生产计划; 发货通知单→退货通知单→销售出库单
            # 外部: 信用管理维护→销售发票
            ("SALES_ORDER", "销售管理流程",
             "参考K3销售管理流程图。前序：模拟报价单→报价单→销售订单（或销售合同/价格政策直接触发）。"
             "主流程：销售订单→发货通知单→销售出库单→销售发票→应收款管理/存货核算管理。"
             "分支：销售订单→主生产计划；发货通知单→退货通知单。"
             "辅助：价格政策维护、折扣政策维护、信用管理维护。"
             "报表：销售订单全程跟踪、销售订单执行汇总/明细、销售出库汇总/明细、销售收入统计、销售毛利润表。",
             [
                {"code": "SIMULATED_QUOTE", "name": "模拟报价单", "is_initial": True},
                {"code": "QUOTATION", "name": "报价单"},
                {"code": "CONTRACT", "name": "销售合同", "is_initial": True},
                {"code": "DRAFT", "name": "销售订单"},
                {"code": "PRODUCTION_PLAN", "name": "主生产计划", "node_type": "cross_module"},
                {"code": "SHIPPING_NOTICE", "name": "发货通知单"},
                {"code": "RETURN_NOTICE", "name": "退货通知单"},
                {"code": "SALES_OUTBOUND", "name": "销售出库单"},
                {"code": "INVOICE", "name": "销售发票"},
                {"code": "AR_MANAGED", "name": "应收款管理", "is_terminal": True, "node_type": "cross_module"},
                {"code": "INV_ACCOUNTED", "name": "存货核算管理", "is_terminal": True, "node_type": "cross_module"},
                {"code": "CANCELLED", "name": "已取消", "is_terminal": True},
                # 政策维护节点（辅助，不参与状态转换）
                {"code": "PRICE_POLICY", "name": "价格政策维护", "node_type": "policy"},
                {"code": "DISCOUNT_POLICY", "name": "折扣政策维护", "node_type": "policy"},
                {"code": "CREDIT_MGMT", "name": "信用管理维护", "node_type": "policy"},
                # 报表节点（展示用，不参与状态转换）
                {"code": "RPT_ORDER_TRACK", "name": "销售订单全程跟踪", "node_type": "report"},
                {"code": "RPT_ORDER_SUMMARY", "name": "销售订单执行汇总表", "node_type": "report"},
                {"code": "RPT_ORDER_DETAIL", "name": "销售订单执行明细表", "node_type": "report"},
                {"code": "RPT_OUTBOUND_SUMMARY", "name": "销售出库汇总表", "node_type": "report"},
                {"code": "RPT_OUTBOUND_DETAIL", "name": "销售出库明细表", "node_type": "report"},
                {"code": "RPT_REVENUE", "name": "销售收入统计表", "node_type": "report"},
                {"code": "RPT_GROSS_PROFIT", "name": "销售毛利润表", "node_type": "report"},
             ], [
                # 前序
                ("转正式报价", "SIMULATED_QUOTE", "QUOTATION", ["SALES_ASSISTANT", "OPERATIONS"],
                 [], "模拟报价测算后转为正式报价单发给客户。", []),
                ("报价确认转订单", "QUOTATION", "DRAFT", ["SALES_ASSISTANT", "OPERATIONS"],
                 [], "客户确认报价后生成销售订单。应用价格政策、折扣政策。", T),
                ("合同直接下单", "CONTRACT", "DRAFT", ["SALES_ASSISTANT", "OPERATIONS"],
                 [], "基于销售合同直接生成销售订单（框架合同滚动发货）。", T),
                # 订单分支
                ("转主生产计划", "DRAFT", "PRODUCTION_PLAN", ["PRODUCT_MANAGER", "OPERATIONS"],
                 [], "将销售需求转化为主生产计划（需要自产的情况）。", []),
                ("生成发货通知", "DRAFT", "SHIPPING_NOTICE", ["SALES_ASSISTANT", "OPERATIONS"],
                 [], "订单审批通过后生成发货通知单。检查客户信用额度。", T),
                # 发货分支
                ("正常发货出库", "SHIPPING_NOTICE", "SALES_OUTBOUND", ["LOGISTICS", "OPERATIONS"],
                 [], "按发货通知单执行FIFO拣货，生成销售出库单。贴客户标签。", T),
                ("生成退货通知", "SHIPPING_NOTICE", "RETURN_NOTICE", ["SALES_ASSISTANT", "OPERATIONS"],
                 [], "客户要求退货或发货有问题，生成退货通知单。", []),
                ("退货影响出库", "RETURN_NOTICE", "SALES_OUTBOUND", ["LOGISTICS", "OPERATIONS"],
                 [], "退货单据影响销售出库数据。", []),
                # 开票
                ("开具销售发票", "SALES_OUTBOUND", "INVOICE", ["FINANCE"],
                 [], "出库后开具销售发票。信用管理维护审核。", T),
                # 分流
                ("转应收款管理", "INVOICE", "AR_MANAGED", ["FINANCE"],
                 [], "销售发票转入应收款管理模块。", T),
                ("转存货核算", "INVOICE", "INV_ACCOUNTED", ["FINANCE"],
                 [], "销售出库数据同步到存货核算模块（结转主营业务成本）。", T),
                # 辅助连线（政策→流程，视觉参考）
                ("价格政策控制", "PRICE_POLICY", "DRAFT", [],
                 [], "价格政策维护影响销售订单定价。", []),
                ("信用管理控制", "CREDIT_MGMT", "INVOICE", [],
                 [], "信用管理维护影响开票审核。", []),
                # 取消
                ("取消订单", "DRAFT", "CANCELLED", ["SALES_ASSISTANT", "OPERATIONS", "BOSS"],
                 [], "", []),
             ]),

            # ====== 仓库管理流程-实仓 ======
            ("INVENTORY", "仓库管理流程-实仓",
             "参考K3仓存管理流程图实仓部分。实仓存放企业自有产权的实物库存。"
             "入库：外购入库单/产品入库单/其他入库单/委外加工入库单。"
             "出库：销售出库单/生产领料单/其他出库单/委外加工出库单。"
             "调拨：调拨单（实仓间移动）。"
             "报表：库存台账、物料收发汇总表/明细表/日报表。",
             [
                {"code": "PENDING_STOCK_IN", "name": "待入库", "is_initial": True},
                {"code": "REAL_WAREHOUSE", "name": "实仓"},
                {"code": "TRANSFERRED", "name": "调拨中"},
                {"code": "SHIPPED_OUT", "name": "已出库", "is_terminal": True},
             ], [
                ("外购入库", "PENDING_STOCK_IN", "REAL_WAREHOUSE", ["LOGISTICS", "OPERATIONS"],
                 [], "外购入库单：采购到货入实仓。扫码，生成批次号。", T),
                ("产品入库", "PENDING_STOCK_IN", "REAL_WAREHOUSE", ["LOGISTICS", "OPERATIONS"],
                 [], "产品入库单：自产产品入实仓。", []),
                ("其他入库", "PENDING_STOCK_IN", "REAL_WAREHOUSE", ["LOGISTICS", "OPERATIONS"],
                 [], "其他入库单：盘盈、借入等入实仓。", []),
                ("委外加工入库", "PENDING_STOCK_IN", "REAL_WAREHOUSE", ["LOGISTICS", "OPERATIONS"],
                 [], "委外加工入库单：委外加工完成品入实仓。", []),
                ("销售出库", "REAL_WAREHOUSE", "SHIPPED_OUT", ["LOGISTICS"],
                 [], "销售出库单：客户订单发货。按FIFO扣减。", T),
                ("生产领料", "REAL_WAREHOUSE", "SHIPPED_OUT", ["LOGISTICS"],
                 [], "生产领料单：自产领料出库。", []),
                ("其他出库", "REAL_WAREHOUSE", "SHIPPED_OUT", ["LOGISTICS"],
                 [], "其他出库单：盘亏、报废等。", []),
                ("委外加工出库", "REAL_WAREHOUSE", "SHIPPED_OUT", ["LOGISTICS"],
                 [], "委外加工出库单：发出委外加工原料。", []),
                ("调拨单", "REAL_WAREHOUSE", "TRANSFERRED", ["LOGISTICS", "OPERATIONS"],
                 [], "调拨单：实仓之间的库存移动（如香港仓→武汉保税区）。", []),
                ("调拨完成入实仓", "TRANSFERRED", "REAL_WAREHOUSE", ["LOGISTICS"],
                 [], "调拨到达目的仓，进入实仓。", []),
             ]),

            # ====== 仓库管理流程-虚仓 ======
            ("INVENTORY_VIRTUAL", "仓库管理流程-虚仓",
             "参考K3仓存管理流程图虚仓部分。虚仓存放非企业自有产权的物料（客户提供、寄售等）。"
             "入库：受托加工入库单/虚仓入库单。"
             "出库：受托加工领料单/虚仓出库单。"
             "调拨：虚仓调拨单。",
             [
                {"code": "PENDING_STOCK_IN", "name": "待入库", "is_initial": True},
                {"code": "VIRTUAL_WAREHOUSE", "name": "虚仓"},
                {"code": "TRANSFERRED", "name": "调拨中"},
                {"code": "SHIPPED_OUT", "name": "已出库", "is_terminal": True},
             ], [
                ("受托加工入库", "PENDING_STOCK_IN", "VIRTUAL_WAREHOUSE", ["LOGISTICS", "OPERATIONS"],
                 [], "受托加工入库单：客户提供的物料入虚仓（不属于我们产权）。", []),
                ("虚仓入库", "PENDING_STOCK_IN", "VIRTUAL_WAREHOUSE", ["LOGISTICS", "OPERATIONS"],
                 [], "虚仓入库单。", []),
                ("受托加工领料", "VIRTUAL_WAREHOUSE", "SHIPPED_OUT", ["LOGISTICS"],
                 [], "受托加工领料单：从虚仓领用客户物料加工。", []),
                ("虚仓出库", "VIRTUAL_WAREHOUSE", "SHIPPED_OUT", ["LOGISTICS"],
                 [], "虚仓出库单。", []),
                ("虚仓调拨单", "VIRTUAL_WAREHOUSE", "TRANSFERRED", ["LOGISTICS", "OPERATIONS"],
                 [], "虚仓调拨单：虚仓之间的库存移动。", []),
                ("调拨完成入虚仓", "TRANSFERRED", "VIRTUAL_WAREHOUSE", ["LOGISTICS"],
                 [], "调拨到达目的虚仓。", []),
             ]),

            # ====== 仓库管理流程-盘点 ======
            ("INVENTORY_COUNT", "仓库管理流程-盘点",
             "参考K3仓存管理流程图盘点部分。周期性实物盘点作业流程："
             "盘点方案新增→打印盘点表→盘点数据录入→编制盘点报告。",
             [
                {"code": "PLAN_CREATED", "name": "盘点方案新增", "is_initial": True},
                {"code": "SHEET_PRINTED", "name": "打印盘点表"},
                {"code": "DATA_ENTERED", "name": "盘点数据录入"},
                {"code": "REPORT_GENERATED", "name": "编制盘点报告", "is_terminal": True},
             ], [
                ("打印盘点表", "PLAN_CREATED", "SHEET_PRINTED", ["LOGISTICS", "OPERATIONS"],
                 [], "根据盘点方案打印盘点表，分发给盘点员。", []),
                ("录入盘点数据", "SHEET_PRINTED", "DATA_ENTERED", ["LOGISTICS"],
                 [], "盘点员完成实物清点，将数据录入系统。", T),
                ("编制盘点报告", "DATA_ENTERED", "REPORT_GENERATED", ["LOGISTICS", "OPERATIONS", "FINANCE"],
                 [], "对比账面与实物差异，生成盘点报告。差异做盘盈/盘亏处理。", T),
             ]),

            # ====== 存货核算流程（参考K3存货核算流程图）======
            # 主流程(纵向): 外购入库核算→存货估价入账→其他入库核算→材料出库核算→(自制入库核算/委外加工入库核算)
            # 产成品出库核算→生成凭证
            # 业务触发: 采购管理→外购入库核算/存货估价入账; 仓存管理→其他入库/材料出库/自制入库/产成品出库/生成凭证
            # 销售管理→产成品出库核算
            # 生成凭证→总账(左)→期末结账(下)
            ("INVENTORY_COSTING", "存货核算流程",
             "参考K3存货核算流程图。核算各项入库出库业务，生成存货凭证传入总账。"
             "数据源：采购管理（外购入库核算、存货估价入账）、仓存管理（各类核算）、销售管理（产成品出库核算）。"
             "主流程：外购入库核算→存货估价入账→其他入库核算→材料出库核算→自制/委外加工入库核算→产成品出库核算→生成凭证。"
             "生成凭证后：→总账、→期末结账。"
             "报表：销售毛利润汇总表、存货收发存汇总表、材料明细账、产成品明细账。",
             [
                {"code": "BUSINESS_TRIGGER", "name": "业务触发", "is_initial": True},
                {"code": "PURCHASE_IN_COST", "name": "外购入库核算"},
                {"code": "VALUATION", "name": "存货估价入账"},
                {"code": "OTHER_IN_COST", "name": "其他入库核算"},
                {"code": "MATERIAL_OUT_COST", "name": "材料出库核算"},
                {"code": "SELF_MADE_IN_COST", "name": "自制入库核算"},
                {"code": "OUTSOURCE_IN_COST", "name": "委外加工入库核算"},
                {"code": "FINISHED_OUT_COST", "name": "产成品出库核算"},
                {"code": "VOUCHER_GENERATED", "name": "生成凭证"},
                {"code": "TRANSFERRED_GL", "name": "总账", "is_terminal": True},
                {"code": "PERIOD_CLOSED", "name": "期末结账", "is_terminal": True},
             ], [
                # 业务触发进入核算
                ("采购触发外购核算", "BUSINESS_TRIGGER", "PURCHASE_IN_COST", ["FINANCE"],
                 [], "采购管理模块触发：外购入库核算。", T),
                # 核算链条
                ("外购转估价", "PURCHASE_IN_COST", "VALUATION", ["FINANCE"],
                 [], "外购入库后进行存货估价入账。计算单位成本（加权平均）。", T),
                ("估价转其他入库", "VALUATION", "OTHER_IN_COST", ["FINANCE"],
                 [], "其他入库核算（盘盈、借入等）。", T),
                ("其他入库转材料出库", "OTHER_IN_COST", "MATERIAL_OUT_COST", ["FINANCE"],
                 [], "材料出库核算（生产领料等）。", T),
                ("材料出库转自制入库", "MATERIAL_OUT_COST", "SELF_MADE_IN_COST", ["FINANCE"],
                 [], "自制入库核算（自产产品）。", T),
                ("材料出库转委外入库", "MATERIAL_OUT_COST", "OUTSOURCE_IN_COST", ["FINANCE"],
                 [], "委外加工入库核算。", T),
                # 销售触发
                ("销售触发产成品出库核算", "BUSINESS_TRIGGER", "FINISHED_OUT_COST", ["FINANCE"],
                 [], "销售管理模块触发：产成品出库核算。结转主营业务成本。", T),
                ("产成品出库转生成凭证", "FINISHED_OUT_COST", "VOUCHER_GENERATED", ["FINANCE"],
                 [], "产成品出库核算完成，生成存货核算凭证。", T),
                # 所有核算环节都能直接汇入生成凭证（右侧汇聚线）
                ("外购核算生成凭证", "PURCHASE_IN_COST", "VOUCHER_GENERATED", ["FINANCE"],
                 [], "外购入库核算单独生成凭证。", T),
                ("估价生成凭证", "VALUATION", "VOUCHER_GENERATED", ["FINANCE"],
                 [], "", T),
                ("其他入库生成凭证", "OTHER_IN_COST", "VOUCHER_GENERATED", ["FINANCE"],
                 [], "", T),
                ("材料出库生成凭证", "MATERIAL_OUT_COST", "VOUCHER_GENERATED", ["FINANCE"],
                 [], "", T),
                ("自制入库生成凭证", "SELF_MADE_IN_COST", "VOUCHER_GENERATED", ["FINANCE"],
                 [], "", T),
                ("委外入库生成凭证", "OUTSOURCE_IN_COST", "VOUCHER_GENERATED", ["FINANCE"],
                 [], "", T),
                # 生成凭证后
                ("转总账", "VOUCHER_GENERATED", "TRANSFERRED_GL", ["FINANCE"],
                 [], "凭证传入总账模块。", T),
                ("期末结账", "VOUCHER_GENERATED", "PERIOD_CLOSED", ["FINANCE", "BOSS"],
                 [], "月末结账。存货相关科目余额结转下期。", T),
             ]),

        ]

        # === 创建/编辑时可设的字段（按 doc_type 配） ===
        # 这些字段会合并进每个 is_initial 状态的 editable_fields，
        # 用户在创建或在初始状态编辑时可以填这些字段
        INITIAL_EDIT_FIELDS = {
            "VOUCHER": ["voucher_date", "voucher_type", "description", "period_id", "source_doc_type", "source_doc_id"],
            "VOUCHER_ADJUSTMENT": ["voucher_date", "voucher_type", "description", "period_id"],
            "ACCOUNTS_RECEIVABLE": ["customer_id", "sales_order_id", "contract_id", "invoice_number", "amount", "currency", "due_date"],
            "ACCOUNTS_PAYABLE": ["supplier_id", "purchase_order_id", "invoice_number", "amount", "currency", "due_date"],
            "PURCHASE_ORDER": ["supplier_id", "order_number", "currency", "total_amount", "expected_delivery_date", "related_sales_order_id", "purchase_assistant_id", "notes"],
            "SALES_ORDER": ["customer_id", "order_number", "currency", "total_amount", "payment_terms_days", "shipping_method", "order_type", "sales_engineer_id", "sales_assistant_id", "notes"],
            "INVENTORY": ["material_id", "warehouse_id", "location_id", "batch_number", "quantity", "received_date"],
            "INVENTORY_VIRTUAL": ["material_id", "warehouse_id", "batch_number", "quantity", "received_date"],
            "INVENTORY_COUNT": ["material_id", "warehouse_id", "batch_number", "quantity"],
            "INVENTORY_COSTING": ["material_id", "warehouse_id", "transaction_type", "quantity", "unit_cost", "total_cost", "transaction_date", "period_id"],
        }
        INITIAL_ROLES = {
            "VOUCHER": ["FINANCE"], "VOUCHER_ADJUSTMENT": ["FINANCE"],
            "ACCOUNTS_RECEIVABLE": ["FINANCE"], "ACCOUNTS_PAYABLE": ["FINANCE"],
            "PURCHASE_ORDER": ["PRODUCT_ASSISTANT", "OPERATIONS"],
            "SALES_ORDER": ["SALES_ASSISTANT", "OPERATIONS"],
            "INVENTORY": ["LOGISTICS", "OPERATIONS"],
            "INVENTORY_VIRTUAL": ["LOGISTICS", "OPERATIONS"],
            "INVENTORY_COUNT": ["LOGISTICS", "OPERATIONS"],
            "INVENTORY_COSTING": ["FINANCE"],
        }

        # === 把旧的 (states, transitions) 折叠成新的 states-only JSONB ===
        for doc_type, wf_name, wf_desc, raw_states, raw_transitions in workflows:
            # 按 from_state 聚合所有出边转换
            state_actions = {}  # {state_code: [(label, to, roles, editable_fields, prompt, tools), ...]}
            for tname, frm, to, t_roles, t_edit, t_prompt, t_tools in raw_transitions:
                state_actions.setdefault(frm, []).append((tname, to, t_roles, t_edit, t_prompt, t_tools))

            # 构造每个 state 的完整定义
            new_states = []
            # 这些字段将挂在"首个业务节点"上（原 is_initial 状态），供用户创建后录入
            initial_extra_fields = INITIAL_EDIT_FIELDS.get(doc_type, [])
            initial_extra_roles = INITIAL_ROLES.get(doc_type, [])

            for s_def in raw_states:
                code = s_def["code"]
                actions = state_actions.get(code, [])

                # 聚合：union of roles, tools（editable 现在挂在每条 next 上，不再聚合到 state）
                roles_union = set()
                tools_union = set()
                for _, _, t_roles, _, _, t_tools in actions:
                    roles_union.update(t_roles or [])
                    tools_union.update(t_tools or [])

                # "首个业务节点"（原 is_initial）：合并录入角色
                # B 模型中这些节点不再是起始节点，START 才是
                if s_def.get("is_initial"):
                    roles_union.update(initial_extra_roles)

                # 拼描述（每个动作一条）
                desc_lines = []
                if actions:
                    desc_lines.append(f"# {s_def.get('name', code)} 节点")
                    for tname, to, _, _, t_prompt, _ in actions:
                        if t_prompt:
                            desc_lines.append(f"- 【{tname} → {to}】{t_prompt}")
                        else:
                            desc_lines.append(f"- 【{tname} → {to}】")
                description = "\n".join(desc_lines)

                # next 列表：每条出边一项，editable_fields 挂在出边上
                # 首个业务节点的"主"出边（目标非终止状态）合并 INITIAL_EDIT_FIELDS
                # 取消/作废类出边（目标是终止态）不挂业务字段，保持干净
                terminal_codes = {s["code"] for s in raw_states if s.get("is_terminal")}
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
                # B 模型：原 is_initial 转成"首个业务节点"，不再标 is_initial（交给 START）
                if s_def.get("is_terminal"):
                    new_state["is_terminal"] = True
                if s_def.get("node_type"):
                    new_state["node_type"] = s_def["node_type"]
                new_states.append(new_state)

            # === 注入 START 状态（B 模型：所有流程的唯一起点）===
            old_initial_codes = [s_def["code"] for s_def in raw_states if s_def.get("is_initial")]
            if old_initial_codes:
                start_state = {
                    "code": "START",
                    "name": "开始",
                    "is_initial": True,
                    "allowed_roles": sorted(INITIAL_ROLES.get(doc_type, [])),
                    "description": f"# 开始节点\n点「开始」按钮创建空单据，进入首个业务节点录入数据。",
                    "custom_html": "",
                    "hard_rules": [],
                    "hooks": [],
                    "next": [
                        {"to": code, "label": "开始", "editable_fields": []} for code in old_initial_codes
                    ],
                }
                new_states.insert(0, start_state)

            # === 注入硬规则示例（演示判定式 DSL） ===
            HARD_RULES_DEMO = {
                ("VOUCHER", "DRAFT", "AUDITED"): [
                    "sum(e.debit for e in entries) == sum(e.credit for e in entries)",
                    "len(entries) >= 2",
                ],
                ("VOUCHER", "AUDITED", "POSTED"): [
                    "lookup('accounting_period', id=doc.period_id).status == 'OPEN'",
                ],
                ("SALES_ORDER", "DRAFT", "SHIPPING_NOTICE"): [
                    "doc.total_amount > 0",
                    "(lookup('customer_credit', customer_id=doc.customer_id) is None) or (lookup('customer_credit', customer_id=doc.customer_id).credit_limit - lookup('customer_credit', customer_id=doc.customer_id).used_amount >= doc.total_amount)",
                ],
                ("ACCOUNTS_PAYABLE", "PENDING", "PAID"): [
                    "doc.paid_amount == doc.amount",
                ],
            }
            for s in new_states:
                for n in (s.get("next") or []):
                    key = (doc_type, s["code"], n["to"])
                    if key in HARD_RULES_DEMO:
                        n["hard_rules"] = HARD_RULES_DEMO[key]

            # === 注入钩子示例（演示钩子 DSL，commit 前执行的副作用脚本） ===
            HOOKS_DEMO = {
                # 销售发货出库 → 回写已发数量
                ("SALES_ORDER", "SHIPPING_NOTICE", "SALES_OUTBOUND"): [
                    "for line in lines:\n"
                    "    update('sales_order_line', {'id': line.id}, {'shipped_quantity': line.quantity})"
                ],
                # 采购质检合格入库 → 为每行生成库存批次
                ("PURCHASE_ORDER", "QUALITY_CHECK", "STOCKED_IN"): [
                    "for line in lines:\n"
                    "    insert('inventory', {\n"
                    "        'material_id': line.material_id,\n"
                    "        'warehouse_id': 1,\n"
                    "        'batch_number': 'PO' + str(doc.id) + '-L' + str(line.line_number),\n"
                    "        'quantity': line.quantity,\n"
                    "        'received_date': today(),\n"
                    "        'purchase_order_line_id': line.id,\n"
                    "        'company_id': doc.company_id,\n"
                    "        'status': 'AVAILABLE',\n"
                    "    })"
                ],
                # 采购免检直接入库 → 同上
                ("PURCHASE_ORDER", "RECEIVING_NOTICE", "STOCKED_IN"): [
                    "for line in lines:\n"
                    "    insert('inventory', {\n"
                    "        'material_id': line.material_id,\n"
                    "        'warehouse_id': 1,\n"
                    "        'batch_number': 'PO' + str(doc.id) + '-L' + str(line.line_number),\n"
                    "        'quantity': line.quantity,\n"
                    "        'received_date': today(),\n"
                    "        'purchase_order_line_id': line.id,\n"
                    "        'company_id': doc.company_id,\n"
                    "        'status': 'AVAILABLE',\n"
                    "    })"
                ],
                # 销售转应收款管理 → 生成 AR 记录（状态=INVOICED，直接进入AR流程的发票节点）
                ("SALES_ORDER", "INVOICE", "AR_MANAGED"): [
                    "insert('accounts_receivable', {\n"
                    "    'customer_id': doc.customer_id,\n"
                    "    'sales_order_id': doc.id,\n"
                    "    'invoice_number': 'INV-' + str(doc.id),\n"
                    "    'amount': doc.total_amount,\n"
                    "    'currency': doc.currency,\n"
                    "    'due_date': today(),\n"
                    "    'company_id': doc.company_id,\n"
                    "    'status': 'INVOICED',\n"
                    "})"
                ],
                # 应收款生成凭证 → 自动创建 voucher + 分录（借银行存款，贷应收账款）
                ("ACCOUNTS_RECEIVABLE", "COLLECTING", "VOUCHER_PROCESSED"): [
                    "fy = lookup('fiscal_year', company_id=doc.company_id, status='OPEN')\n"
                    "period = lookup('accounting_period', fiscal_year_id=fy.id, period_number=today().month, status='OPEN')\n"
                    "bank_acct = lookup('account', code='1002', company_id=doc.company_id)\n"
                    "ar_acct = lookup('account', code='1122', company_id=doc.company_id)\n"
                    "v = insert('voucher', {\n"
                    "    'voucher_number': 'AR-RCV-' + str(doc.id),\n"
                    "    'voucher_date': today(),\n"
                    "    'period_id': period.id,\n"
                    "    'voucher_type': 'GENERAL',\n"
                    "    'description': 'AR收款 ' + str(doc.invoice_number),\n"
                    "    'total_debit': float(doc.amount),\n"
                    "    'total_credit': float(doc.amount),\n"
                    "    'status': 'DRAFT',\n"
                    "    'is_auto_generated': True,\n"
                    "    'source_doc_type': 'ACCOUNTS_RECEIVABLE',\n"
                    "    'source_doc_id': doc.id,\n"
                    "    'company_id': doc.company_id,\n"
                    "})\n"
                    "insert('voucher_entry', {\n"
                    "    'voucher_id': v.id,\n"
                    "    'line_number': 1,\n"
                    "    'account_id': bank_acct.id,\n"
                    "    'description': 'AR收款-银行存款',\n"
                    "    'debit': float(doc.amount),\n"
                    "    'credit': 0,\n"
                    "    'currency': doc.currency,\n"
                    "})\n"
                    "insert('voucher_entry', {\n"
                    "    'voucher_id': v.id,\n"
                    "    'line_number': 2,\n"
                    "    'account_id': ar_acct.id,\n"
                    "    'description': 'AR收款-冲应收',\n"
                    "    'debit': 0,\n"
                    "    'credit': float(doc.amount),\n"
                    "    'currency': doc.currency,\n"
                    "})\n"
                    "update('accounts_receivable', {'id': doc.id}, {'voucher_id': v.id})"
                ],
                # 采购转应付款管理 → 生成 AP 记录
                ("PURCHASE_ORDER", "INVOICED", "TRANSFERRED_AP"): [
                    "insert('accounts_payable', {\n"
                    "    'supplier_id': doc.supplier_id,\n"
                    "    'purchase_order_id': doc.id,\n"
                    "    'company_id': doc.company_id,\n"
                    "    'amount': doc.total_amount,\n"
                    "    'currency': doc.currency,\n"
                    "    'due_date': today(),\n"
                    "    'status': 'PENDING',\n"
                    "})"
                ],
                # 凭证过账 → 更新科目余额
                ("VOUCHER", "AUDITED", "POSTED"): [
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
            }
            for s in new_states:
                for n in (s.get("next") or []):
                    key = (doc_type, s["code"], n["to"])
                    if key in HOOKS_DEMO:
                        n["hooks"] = HOOKS_DEMO[key]

            # 按 doc_type 分组到三大类
            GROUP_MAP = {
                "VOUCHER": "财务", "VOUCHER_ADJUSTMENT": "财务",
                "ACCOUNTS_RECEIVABLE": "财务", "ACCOUNTS_PAYABLE": "财务",
                "SALES_ORDER": "业务", "PURCHASE_ORDER": "业务",
                "SHIPMENT": "业务", "GOODS_RECEIPT": "业务",
                "PROJECT": "业务", "FRAMEWORK_CONTRACT": "业务",
                "INVENTORY": "仓储", "INVENTORY_VIRTUAL": "仓储",
                "INVENTORY_COUNT": "仓储", "INVENTORY_COSTING": "仓储",
            }
            # 销售流程预设节点位置（匹配K3流程图布局）
            INITIAL_POSITIONS = {
                "SALES_ORDER": {
                    "START": {"x": 370, "y": 0},
                    "CONTRACT": {"x": 160, "y": 100},
                    "QUOTATION": {"x": 370, "y": 100},
                    "SIMULATED_QUOTE": {"x": 580, "y": 100},
                    "PRICE_POLICY": {"x": 30, "y": 230},
                    "DRAFT": {"x": 370, "y": 230},
                    "PRODUCTION_PLAN": {"x": 630, "y": 230},
                    "DISCOUNT_POLICY": {"x": 30, "y": 340},
                    "CREDIT_MGMT": {"x": 30, "y": 450},
                    "SHIPPING_NOTICE": {"x": 370, "y": 380},
                    "RETURN_NOTICE": {"x": 620, "y": 450},
                    "SALES_OUTBOUND": {"x": 370, "y": 530},
                    "INV_ACCOUNTED": {"x": 80, "y": 680},
                    "INVOICE": {"x": 370, "y": 680},
                    "AR_MANAGED": {"x": 370, "y": 830},
                    "CANCELLED": {"x": 630, "y": 680},
                    "RPT_ORDER_TRACK": {"x": 850, "y": 100},
                    "RPT_ORDER_SUMMARY": {"x": 850, "y": 190},
                    "RPT_ORDER_DETAIL": {"x": 850, "y": 280},
                    "RPT_OUTBOUND_SUMMARY": {"x": 850, "y": 380},
                    "RPT_OUTBOUND_DETAIL": {"x": 850, "y": 470},
                    "RPT_REVENUE": {"x": 850, "y": 580},
                    "RPT_GROSS_PROFIT": {"x": 850, "y": 670},
                },
                "VOUCHER": {
                    "START": {"x": 120, "y": 0},
                    # 主干（中间列）
                    "ACCOUNT_READY": {"x": 120, "y": 100},
                    "DRAFT": {"x": 300, "y": 100},
                    "AUDITED": {"x": 300, "y": 230},
                    "POSTED": {"x": 300, "y": 370},
                    "FX_ADJUSTED": {"x": 300, "y": 530},
                    "PL_TRANSFERRED": {"x": 300, "y": 660},
                    "CLOSED": {"x": 300, "y": 790},
                    # 左分支
                    "RECONCILED": {"x": 80, "y": 370},
                    # 右分支（cross_module）
                    "LEDGER_QUERIED": {"x": 550, "y": 330},
                    "REPORT_QUERIED": {"x": 550, "y": 430},
                    # 报表（最右列）
                    "RPT_GENERAL_LEDGER": {"x": 780, "y": 100},
                    "RPT_DETAIL_LEDGER": {"x": 780, "y": 190},
                    "RPT_MULTI_COL": {"x": 780, "y": 280},
                    "RPT_PROJECT_DETAIL": {"x": 780, "y": 370},
                    "RPT_PROJECT_BALANCE": {"x": 780, "y": 460},
                    "RPT_TRIAL_BALANCE": {"x": 780, "y": 550},
                    "RPT_ACCOUNT_BALANCE": {"x": 780, "y": 640},
                },
                "ACCOUNTS_RECEIVABLE": {
                    "START": {"x": 350, "y": 0},
                    # 核心流程（中间列）
                    "CONTRACT_REGISTERED": {"x": 250, "y": 120},
                    "INVOICED": {"x": 350, "y": 180},
                    "COLLECTING": {"x": 350, "y": 330},
                    "VOUCHER_PROCESSED": {"x": 350, "y": 480},
                    "CLOSED": {"x": 350, "y": 630},
                    # 左右分支
                    "CREDIT_MANAGED": {"x": 470, "y": 120},
                    "BAD_DEBT": {"x": 570, "y": 180},
                    "NOTES_RECV": {"x": 570, "y": 330},
                    "SETTLED": {"x": 570, "y": 480},
                    # 外部模块（左侧）
                    "SALES_MGMT": {"x": 120, "y": 180},
                    "CASH_MGMT": {"x": 120, "y": 330},
                    "GL_LINK": {"x": 120, "y": 480},
                    # 报表（右侧）
                    "RPT_AR_DETAIL": {"x": 800, "y": 30},
                    "RPT_AR_SUMMARY": {"x": 800, "y": 100},
                    "RPT_RECONCILIATION": {"x": 800, "y": 170},
                    "RPT_AGING": {"x": 800, "y": 240},
                    "RPT_DUE_LIST": {"x": 800, "y": 310},
                    "RPT_SALES_ANALYSIS": {"x": 800, "y": 380},
                    "RPT_COLLECTION": {"x": 800, "y": 450},
                    "RPT_CONTRACT_EXEC": {"x": 800, "y": 520},
                    "RPT_CONTRACT_DUE": {"x": 800, "y": 590},
                    "RPT_CREDIT_LIMIT": {"x": 800, "y": 660},
                },
            }
            wf = m.WorkflowDefinition(
                doc_type=doc_type, name=wf_name, description=wf_desc,
                states=new_states, created_by_id=users["admin"].id,
                group_name=GROUP_MAP.get(doc_type, "其他"),
                is_published=True, is_active=True,
                node_positions=INITIAL_POSITIONS.get(doc_type, {}),
            )
            db.add(wf)

        # === 第一期 CRM/WMS/ERP 打通流程 ===
        existing_workflow_doc_types = {doc_type for doc_type, *_ in workflows}
        for wf_def in phase1_workflow_definitions(users["admin"].id):
            # SALES_ORDER / PURCHASE_ORDER 等旧流程已经在上面创建，启动脚本会再运行
            # scripts.seed_phase1 做幂等更新，避免这里触发 (doc_type, version) 唯一冲突。
            if wf_def["doc_type"] not in existing_workflow_doc_types:
                db.add(m.WorkflowDefinition(**wf_def))

        # === 知识库 ===
        knowledge = [
            ("SYSTEM_PROMPT", "用户Agent公司介绍",
             "PHOTONTECK是一家高端光电/量子科技设备代理商（分销商），总部在香港，深圳和武汉也有运营。代理100+个原厂的产品，年收入4-5亿人民币。核心价值是帮客户从100+原厂的几百种产品中做技术选型。客户包括Intel、腾讯、华为等大型科技企业。公司有约7个法人主体（马甲公司），用于不同币种和地域的业务。",
             []),
            ("RULE", "信用额度检查", "查CustomerCredit表，获取客户的credit_limit和used_amount。计算剩余额度=credit_limit-used_amount。如果订单金额>剩余额度，不通过。",
             ["SALES_ORDER"]),
            ("RULE", "FIFO拣货规则", "查Inventory表，按received_date从早到晚排序。逐批扣减数量直到满足需求。最先入库的批次最先出。",
             ["SHIPMENT"]),
            ("RULE", "借贷平衡", "凭证所有分录的借方金额合计必须等于贷方金额合计。不等则不允许审核过账。",
             ["VOUCHER"]),
            ("RULE", "期末调汇", "多币种业务在期末按当期汇率重新计算外币科目余额。差额计入'财务费用-汇兑损益'。查exchange_rate表获取最新汇率。",
             ["ACCOUNTING_PERIOD"]),
            ("RULE", "结转损益", "月末将所有收入类科目(6001/6051/6301)和费用类科目(6401/6601/6602/6603/6801)余额结转到'4104本年利润'。结转后收入费用科目余额清零。",
             ["ACCOUNTING_PERIOD"]),
            ("RULE", "期末结账检查", "结账前检查：1.所有凭证已过账(无DRAFT/AUDITED状态凭证) 2.调汇已完成 3.损益已结转 4.试算平衡(借方合计=贷方合计)。",
             ["ACCOUNTING_PERIOD"]),
            ("RULE", "科目余额结转", "期末结账后，本期期末余额自动成为下期期初余额。资产/负债/权益类科目余额延续，收入/费用类清零。",
             ["ACCOUNTING_PERIOD"]),
            ("GUIDE", "总账报表说明", "过账后可查询的报表：总分类账（按一级科目汇总）、明细分类账（按明细科目逐笔）、多栏账（多科目并列）、核算项目明细账/余额表、试算平衡表（验证借=贷）、科目余额表。",
             ["VOUCHER", "ACCOUNTING_PERIOD"]),
            ("GUIDE", "调整期间说明", "调整期间用于年末审计调整。在12个正常会计期间之外的第13期录入。调整期间凭证录入、过账、查询流程与正常期间相同，但期间标记为调整期。",
             ["VOUCHER"]),
            ("ALERT", "信用额度预警", "供应商信用额度使用率超过80%时通知财务和运营。", []),
            ("ALERT", "应收逾期预警", "应收账款超过到期日未收款时通知财务和对应SA。", []),
            ("ALERT", "交期延误预警", "采购订单超过预计交期还未到货时通知PA和运营。", []),
            ("ALERT", "合同到期预警", "框架合同距到期日不足60天时通知SA和运营。", []),
        ]
        for etype, title, content, dtypes in knowledge:
            db.add(m.KnowledgeEntry(entry_type=etype, title=title, content=content, applicable_doc_types=dtypes))

        await db.commit()

        # 统计
        tables = [
            ("公司", m.Company), ("用户", m.UserAccount), ("供应商", m.Supplier),
            ("物料", m.Material), ("客户", m.Customer), ("仓库", m.Warehouse),
            ("销售订单", m.SalesOrder), ("采购订单", m.PurchaseOrder),
            ("库存批次", m.Inventory), ("流程定义", m.WorkflowDefinition),
            ("知识库条目", m.KnowledgeEntry),
        ]
        print("种子数据生成完成:")
        for label, model in tables:
            count = (await db.execute(select(func.count()).select_from(model))).scalar()
            print(f"  {label}: {count}")
        print(f"\n登录账号: jerry/demo1234  sa_li/demo1234  pa_chen/demo1234  admin/admin1234")


if __name__ == "__main__":
    from sqlalchemy import func
    asyncio.run(seed())
