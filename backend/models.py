"""
第一层：数据模型

所有30+张表定义在一个文件里。
字段是纯数据结构，不含业务逻辑。
状态字段是普通字符串，不用枚举——状态由流程引擎管理。
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from core.database import Base


# ============================================================
# 公共Mixin
# ============================================================

class AuditMixin:
    """所有业务表的公共字段"""
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ============================================================
# 核心：公司 & 用户
# ============================================================

class Company(Base):
    __tablename__ = "company"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    short_name = Column(String(50))
    currency = Column(String(3), default="USD")
    tax_type = Column(String(10), default="NONE")
    country = Column(String(50), default="香港")
    city = Column(String(50), default="")
    address = Column(Text, default="")
    # 区域配置（EXT-01-D）：HK/内地二分 + 抬头/编号前缀/金蝶组织映射
    region = Column(String(10), default="HK")  # HK / CN
    invoice_title = Column(Text, default="")  # 发票抬头（占位待甲方签字）
    numbering_prefix = Column(String(20), default="")  # 单据编号前缀
    kingdee_org_code = Column(String(40), default="")  # 金蝶组织映射码（占位）
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class UserAccount(Base):
    __tablename__ = "user_account"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    full_name = Column(String(100), default="")
    role = Column(String(30), nullable=False)  # BOSS/OPERATIONS/SALES_ASSISTANT/PRODUCT_ASSISTANT/FINANCE/LOGISTICS/...
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False)
    department = Column(String(50), default="")
    phone = Column(String(30), default="")
    is_admin = Column(Boolean, default=False)  # 超级管理员（不参与业务流程）
    is_active = Column(Boolean, default=True)
    # 服务端会话吊销（D-05f 升级）：强制下线/封号时 +1，鉴权校验会话里的 session_version
    session_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, server_default=func.now())

    company = relationship("Company")


class UserCompanyAccess(Base):
    """用户×公司授权（决策B）：一人多公司、各家角色相同（角色取 UserAccount.role）。

    _company_filter 读「已开通公司集 ∩ active_company_id」；is_primary=默认登录公司；
    valid_until=临时代管软到期（EXT-01-C，空=永久）。
    """
    __tablename__ = "user_company_access"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user_account.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False)
    is_primary = Column(Boolean, nullable=False, default=False, server_default="false")
    valid_until = Column(Date, nullable=True)  # 空=永久授权
    __table_args__ = (UniqueConstraint("user_id", "company_id"),)


# ============================================================
# 主数据：客户 / 供应商 / 物料
# ============================================================

class Customer(AuditMixin, Base):
    __tablename__ = "customer"
    __doc_types__ = ("CUSTOMER",)
    id = Column(Integer, primary_key=True)
    code = Column(String(30), index=True)
    code_type = Column(String(15), default="LONG_TERM")
    name = Column(String(200))
    short_name = Column(String(50), default="")
    country = Column(String(50), default="")
    city = Column(String(50), default="")
    address = Column(Text, default="")
    contact_person = Column(String(50), default="")
    contact_email = Column(String(100), default="")
    contact_phone = Column(String(30), default="")
    payment_terms_days = Column(Integer, default=30)
    default_currency = Column(String(3), default="USD")
    default_shipping_method = Column(String(5), default="FOB")
    is_active = Column(Boolean, default=True)
    status = Column(String(30), default="ACTIVE")
    # --- 段0b 主数据扩充（PRD 02 页面1）---
    # name=全称 full_name，short_name=简称（显示名优先列）。
    region = Column(String(10), default="")            # HK / CN（内地）（跟随当前公司）
    business_unit = Column(String(40), default="")     # 事业部（光通信/科研/…）
    grade = Column(String(20), default="SMALL")        # 大客户 LARGE / 小客户 SMALL
    default_payment_term = Column(String(60), default="")  # 付款条件（财务/对账引用）
    credit_limit = Column(Numeric(16, 2), nullable=True)   # 信用额度（仅展示不硬拦，蓝图 §3.6）
    customer_vendor_code = Column(String(50), default="")  # 在客户系统的我方供应商码（蓝图 §3.1）
    owner_sales_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 负责销售（行级看本人客户）
    qualified_code = Column(String(50), default="")    # 客户认证码（VendorQualification 回填，01 模块）
    label_template_ref = Column(Integer, ForeignKey("label_template.id"), nullable=True)  # ➕指向 08 标签模板
    __table_args__ = (UniqueConstraint("company_id", "code"),)


class Supplier(AuditMixin, Base):
    __tablename__ = "supplier"
    __doc_types__ = ("SUPPLIER",)
    id = Column(Integer, primary_key=True)
    code = Column(String(30), index=True)
    name = Column(String(200))
    short_name = Column(String(50), default="")
    country = Column(String(50), default="")
    contact_person = Column(String(50), default="")
    contact_email = Column(String(100), default="")
    contact_phone = Column(String(30), default="")
    quality_score = Column(Numeric(3, 1), nullable=True)
    is_active = Column(Boolean, default=True)
    status = Column(String(30), default="ACTIVE")
    notes = Column(Text, default="")
    # --- 段0b 主数据扩充（PRD 02 页面2）---
    supplier_type = Column(String(10), default="OEM")   # 原厂 OEM / 代理 AGENT（蓝图 §3.1）
    payment_term = Column(String(60), default="")       # 付款条件（财务/付款申请引用）
    responsible_pa_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 负责 PA（一供应商绑一 PA，default_pa）
    backup_pa_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)       # 备份 PA（GAP-2 *Betty/Chloe）
    region = Column(String(10), default="")             # HK / CN / OVERSEAS（海外走 ECCN/进出口管控）
    __table_args__ = (UniqueConstraint("company_id", "code"),)


class MaterialCategory(Base):
    __tablename__ = "material_category"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey("material_category.id"), nullable=True)


class Material(Base):
    __tablename__ = "material"
    # 段0c：型号需可建档（PA 询价即建档），挂轻量单状态机 MATERIAL（ACTIVE，纯字典型）。
    # 仍保留 __queryable__ 语义（has __doc_types__ → exposed），下游按 doc_type 走 execute_transition 建/改。
    __doc_types__ = ("MATERIAL",)
    id = Column(Integer, primary_key=True)
    sku = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(300), nullable=False)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("material_category.id"), nullable=True)
    product_line = Column(String(20), default="OTHER")
    is_domestic = Column(Boolean, default=False)
    unit = Column(String(10), default="pcs")
    description = Column(Text, default="")
    technical_specs = Column(JSONB, default={})
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    # --- 段0b 主数据扩充（PRD 02 页面3 产品/型号 ⭐）---
    # Material = 型号（P/N）。sku=型号料号，name=描述。全系统最核心主数据。
    # 注：Material 现为全局表（无 company_id / 无 AuditMixin）；本段不改其租户语义，
    #     新增列均 nullable，company_id 隔离留 TODO（GAP：型号是否按公司隔离待甲方确认）。
    pn = Column(String(100), default="")               # 型号 P/N（材料 進庫詳細資料.型號），与 sku 并存
    desc_cn = Column(String(300), default="")          # 中文描述
    desc_en = Column(String(300), default="")          # 英文描述
    product_name = Column(String(200), default="")     # 品名（报关用）
    control_mode = Column(String(5), default="LOT")    # ⭐SN / LOT（决定 WMS 行为，蓝图 §5.3，无第三态）
    uom_id = Column(Integer, ForeignKey("unit_of_measure.id"), nullable=True)  # 计量单位（包/盘/PCS）
    min_pack_qty = Column(Numeric(12, 2), nullable=True)  # 最小包装数=存储单位
    pack_qty_variable = Column(Boolean, default=False)    # 每包数量受良率浮动（实际数量存批次）
    hs_code_origin_id = Column(Integer, ForeignKey("hs_code.id"), nullable=True)  # ⭐原产 HS
    hs_code_cn_id = Column(Integer, ForeignKey("hs_code.id"), nullable=True)      # ⭐中国 HS（双码）
    eccn = Column(String(30), default="")              # 出口管制号（海外原厂必问）
    country_of_origin = Column(String(50), default="")  # 原产地（材料 原產地=JAPAN）
    moq = Column(Numeric(12, 2), nullable=True)        # 最小起订量
    mpq = Column(Numeric(12, 2), nullable=True)        # 最小包装量 MPQ/MPP
    warranty_months = Column(Integer, nullable=True)   # 对原厂质保期（从原厂发货日起算）
    has_battery = Column(Boolean, default=False)       # 是否含电池（物流合规）
    date_code_rule = Column(String(100), default="")   # Date Code 规则
    pcn_flag = Column(Boolean, default=False)          # PCN 标记（可能限定销售对象，蓝图 §5.4）
    product_line_id = Column(Integer, ForeignKey("product_line.id"), nullable=True)  # 归属产线
    status = Column(String(15), default="ACTIVE")

    supplier = relationship("Supplier")
    category = relationship("MaterialCategory")


# ============================================================
# 销售
# ============================================================

class FrameworkContract(AuditMixin, Base):
    __tablename__ = "framework_contract"
    __doc_types__ = ("FRAMEWORK_CONTRACT",)
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id"))
    contract_number = Column(String(50), index=True, nullable=False)
    start_date = Column(Date)
    end_date = Column(Date)
    total_amount = Column(Numeric(16, 2), default=0)
    currency = Column(String(3), default="USD")
    status = Column(String(30), default="DRAFT")
    rolling_forecast = Column(JSONB, default={})
    notes = Column(Text, default="")
    __table_args__ = (UniqueConstraint("company_id", "contract_number"),)

    customer = relationship("Customer")


class SalesOrder(AuditMixin, Base):
    __tablename__ = "sales_order"
    __doc_types__ = ("SALES_ORDER",)
    id = Column(Integer, primary_key=True)
    order_number = Column(String(30), index=True, nullable=False)
    __table_args__ = (UniqueConstraint("company_id", "order_number"),)
    customer_po_number = Column(String(50), index=True, default="")
    customer_po_date = Column(Date, nullable=True)
    customer_vendor_no = Column(String(50), default="")
    quotation_reference = Column(String(100), default="")
    customer_id = Column(Integer, ForeignKey("customer.id"))
    inquiry_id = Column(Integer, ForeignKey("sales_inquiry.id"), nullable=True)
    quotation_id = Column(Integer, ForeignKey("quotation.id"), nullable=True)
    framework_contract_id = Column(Integer, ForeignKey("framework_contract.id"), nullable=True)
    sales_engineer_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    sales_assistant_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    sales_assistant_names = Column(Text, default="")
    product_manager_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    customer_region = Column(String(50), default="")
    order_type = Column(String(20), default="STANDARD")  # STANDARD / TRADE(背靠背贸易)
    currency = Column(String(3), default="USD")
    exchange_rate = Column(Numeric(12, 6), default=1)
    total_amount = Column(Numeric(16, 2), default=0)
    payment_terms_days = Column(Integer, default=30)
    payment_terms_text = Column(String(100), default="")
    shipping_method = Column(String(10), default="FOB")
    shipment_terms = Column(String(100), default="")
    requires_advance_receipt = Column(Boolean, default=False)
    advance_receipt_amount = Column(Numeric(16, 2), default=0)
    delivery_address = Column(Text, default="")
    bill_to_name = Column(String(200), default="")
    bill_to_address = Column(Text, default="")
    bill_to_contact = Column(String(100), default="")
    bill_to_phone = Column(String(50), default="")
    ship_to_name = Column(String(200), default="")
    ship_to_address = Column(Text, default="")
    ship_to_contact = Column(String(100), default="")
    ship_to_phone = Column(String(50), default="")
    packaging_requirements = Column(Text, default="")
    barcode_requirements = Column(Text, default="")
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")
    # --- 段3b 决策①（合同即 SO）：PRD 05 页面1/2 合同信息字段组 + 签章 + 事业部分类 ---
    # 编号（客户订单号，主单号，全链只读不可改）。customer_po_number 偏「客户 PO 号」语义，
    # PRD 页面2 字段表把「编号/客户订单号」单列映射 external_order_no，故新增对齐 PRD 列名。
    external_order_no = Column(String(50), default="", index=True)
    # 合同/电子签章（一签宝占位，PRD 页面1 兼容性：引擎无对象存储/签章原生支持 → 字段 + 占位集成）。
    contract_attachment_ref = Column(Text, default="")          # 双签合同附件引用（本地上传/共享盘引用字符串）
    signature_status = Column(String(20), default="PENDING")    # 待申请/已申请/已盖章/已回传（一签宝状态占位）
    signature_party = Column(String(20), default="")            # 我方带章 OUR / 客户带章 CUSTOMER（谁做合同谁带章）
    signed_at = Column(DateTime, nullable=True)                 # 合同成立（双签回传）时间戳
    # 事业部分类（Memo）+ 科研细分市场（科研单条件维度，PRD 页面2/签单大表筛选维度）。
    business_unit = Column(String(40), default="")              # 事业部（光通信/科研SIO/…），签单大表筛选维度
    research_sub_market = Column(String(60), default="")        # 科研细分市场（Memo=科研时用，签单大表筛选维度）
    # ★预付到账闸标志（PRD 页面2 验收4）：付款方式=预付时 signed→executing 前须置 True
    #   （到账确认单在财务域 ADVANCE_RECEIPT，本字段为本流程消费的放行标志；hard_rule 校验）。
    advance_receipt_confirmed = Column(Boolean, default=False)

    customer = relationship("Customer")


class SalesOrderLine(Base):
    __tablename__ = "sales_order_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    customer_line_number = Column(String(30), default="")
    customer_pr_number = Column(String(50), default="")
    customer_part_number = Column(String(100), default="")
    part_revision = Column(String(30), default="")
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    product_description = Column(Text, default="")
    quantity = Column(Numeric(12, 2), nullable=False)
    uom = Column(String(20), default="")
    unit_price = Column(Numeric(12, 4), nullable=False)
    total_price = Column(Numeric(16, 2), nullable=False)
    tax_rate = Column(Numeric(5, 2), default=0)
    requested_delivery_date = Column(Date, nullable=True)
    shipped_quantity = Column(Numeric(12, 2), default=0)
    status = Column(String(30), default="PENDING")
    __table_args__ = (UniqueConstraint("sales_order_id", "line_number"),)

    material = relationship("Material")


class SalesInquiry(AuditMixin, Base):
    """CRM: 客户询价需求，后续可转报价单。"""
    __tablename__ = "sales_inquiry"
    __doc_types__ = ("SALES_INQUIRY",)
    id = Column(Integer, primary_key=True)
    inquiry_number = Column(String(30), index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customer.id"))
    sales_assistant_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    product_manager_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    source = Column(String(30), default="")
    target_price = Column(Numeric(16, 2), nullable=True)
    currency = Column(String(3), default="USD")
    required_delivery_date = Column(Date, nullable=True)
    delivery_address = Column(Text, default="")
    packaging_requirements = Column(Text, default="")
    barcode_requirements = Column(Text, default="")
    payment_requirement = Column(String(100), default="")
    # 04a-1 内部询价扩列（源《内部询价表.doc》：销售提供 end-customer 决策上下文）。
    home_page = Column(String(200), default="")          # 客户主页 Home Page
    application = Column(String(200), default="")         # 应用 Application
    # 项目阶段：预算评估/项目切换/研发/样品/小批量验证/批量（阶梯价 vs 样品报价区分）。
    project_phase = Column(String(20), default="")
    demand_forecast = Column(String(200), default="")     # 需求用量 Demand/Forecast
    competitor = Column(String(200), default="")          # 竞争对手 Competitor
    competitor_price = Column(Numeric(16, 2), nullable=True)  # 竞品价格（对原厂可见，对外报价由防火墙处理）
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    customer = relationship("Customer")
    __table_args__ = (UniqueConstraint("company_id", "inquiry_number"),)


class SalesInquiryLine(Base):
    __tablename__ = "sales_inquiry_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    inquiry_id = Column(Integer, ForeignKey("sales_inquiry.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=True)
    product_description = Column(Text, default="")
    quantity = Column(Numeric(12, 2), nullable=False)
    target_unit_price = Column(Numeric(12, 4), nullable=True)
    requested_delivery_date = Column(Date, nullable=True)
    notes = Column(Text, default="")
    __table_args__ = (UniqueConstraint("inquiry_id", "line_number"),)

    material = relationship("Material")


class Quotation(AuditMixin, Base):
    """CRM/ERP: 报价单，客户确认后转销售订单。"""
    __tablename__ = "quotation"
    __doc_types__ = ("QUOTATION",)
    id = Column(Integer, primary_key=True)
    quotation_number = Column(String(30), index=True, nullable=False)
    inquiry_id = Column(Integer, ForeignKey("sales_inquiry.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customer.id"))
    sales_assistant_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    product_manager_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    currency = Column(String(3), default="USD")
    total_amount = Column(Numeric(16, 2), default=0)
    tax_rate = Column(Numeric(5, 2), default=0)
    payment_terms_days = Column(Integer, default=30)
    shipping_method = Column(String(10), default="FOB")
    valid_until = Column(Date, nullable=True)
    delivery_address = Column(Text, default="")
    packaging_requirements = Column(Text, default="")
    barcode_requirements = Column(Text, default="")
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")
    # --- 段3a CRM 前段：报价单 PM 门控 + 字段防火墙扩列（PRD 05 页面6）---
    # 商机勾稽（报价由商机派生回填，前段漏斗第三级）。
    opportunity_id = Column(Integer, ForeignKey("opportunity.id"), nullable=True)
    business_unit = Column(String(40), default="")      # 事业部（光通信/科研SIO）——驱动分流
    # 🔒Q18 采购成本（产品部/PA 给）：对销售端 SALES+SA 隐藏（入 BUY_PRICE_FIELDS/BUY_TABLES）。
    cost = Column(Numeric(16, 4), nullable=True)
    # ✅Q18 利润点（PM 设定）：对 SALES+SA 可见（不入隐藏集，引擎现状本就未覆盖 profit_point）。
    profit_point = Column(Numeric(8, 4), nullable=True)
    # PM「是否报价」门控决策（待定 PENDING / 报价 QUOTE / 不报价 NO_QUOTE）。
    quote_decision = Column(String(12), default="PENDING")
    report_header = Column(String(120), default="")     # PM 报备抬头（决定签单公司，蓝图 §2）
    lead_time = Column(String(60), default="")          # 货期（产线带出/手填）
    trade_term = Column(String(10), default="")         # 贸易条件（EXW/FCA/CFR/…）

    customer = relationship("Customer")
    __table_args__ = (UniqueConstraint("company_id", "quotation_number"),)


class QuotationLine(Base):
    __tablename__ = "quotation_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    quotation_id = Column(Integer, ForeignKey("quotation.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=True)
    product_description = Column(Text, default="")
    quantity = Column(Numeric(12, 2), nullable=False)
    unit_price = Column(Numeric(12, 4), nullable=False)
    total_price = Column(Numeric(16, 2), nullable=False)
    tax_rate = Column(Numeric(5, 2), default=0)
    delivery_days = Column(Integer, nullable=True)
    packaging_requirements = Column(Text, default="")
    barcode_requirements = Column(Text, default="")
    __table_args__ = (UniqueConstraint("quotation_id", "line_number"),)

    material = relationship("Material")


class QuoteTierLine(Base):
    """报价单阶梯价子表（PRD 05 页面6 quote_tier_line）：阶梯起订量 × 单价。

    名含 `_line` + 指向 quotation 的 FK → 引擎自动识别为子表，DocEditor 渲 SubTableEditor 网格。
    🔒Q18 字段防火墙（query+schema 两路，services/tools.py）：
      - cost_unit（该阶梯采购成本）入 BUY_PRICE_FIELDS/BUY_TABLES → 对 SALES+SA 隐藏；
      - unit_profit_point（该阶梯利润点）不入隐藏集 → 对 SALES+SA 可见（PM 设定，销售端据此报价）。
    """
    __tablename__ = "quote_tier_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    quotation_id = Column(Integer, ForeignKey("quotation.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    min_quantity = Column(Integer, nullable=False, default=1)  # 阶梯起订量
    unit_price = Column(Numeric(12, 4), nullable=True)         # 该阶梯卖价（PM 定价后），对客户/销售可见
    cost_unit = Column(Numeric(12, 4), nullable=True)          # 🔒该阶梯采购成本，对 SALES+SA 隐藏
    unit_profit_point = Column(Numeric(8, 4), nullable=True)   # ✅该阶梯利润点，对 SALES+SA 可见
    remark = Column(String(200), default="")
    __table_args__ = (UniqueConstraint("quotation_id", "line_number"),)


# ============================================================
# 采购
# ============================================================

class PurchaseOrder(AuditMixin, Base):
    __tablename__ = "purchase_order"
    __doc_types__ = ("PURCHASE_ORDER",)
    id = Column(Integer, primary_key=True)
    order_number = Column(String(30), index=True, nullable=False)
    __table_args__ = (UniqueConstraint("company_id", "order_number"),)
    po_date = Column(Date, nullable=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"))
    purchase_assistant_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    # 段2b 04a-3：PO 头扩列（源 PO total sheet）。
    factory_so_number = Column(String(50), default="")  # 原厂 SO#（原厂回的销售单号）
    product_manager_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 产品经理（按产线带出）
    pd_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # PD（四大板块 PD）
    notice_date = Column(Date, nullable=True)  # 采购通知日期
    related_sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=True)
    purchase_notice_id = Column(Integer, ForeignKey("purchase_notice.id"), nullable=True)
    is_stock_order = Column(Boolean, default=False)
    # 备货金额组（🔒Q18 对销售端隐藏）：original 备货时定永不变；latest 随消单递减。
    stock_amount_original = Column(Numeric(16, 2), nullable=True)
    stock_amount_latest = Column(Numeric(16, 2), nullable=True)
    stock_quantity = Column(Numeric(12, 2), nullable=True)
    stock_reason = Column(Text, default="")  # 备货原因及待跟进
    currency = Column(String(3), default="USD")
    total_amount = Column(Numeric(16, 2), default=0)
    expected_delivery_date = Column(Date, nullable=True)
    actual_delivery_date = Column(Date, nullable=True)
    shipment_terms = Column(String(100), default="")
    payment_terms_text = Column(String(100), default="")
    ship_to_name = Column(String(200), default="")
    ship_to_address = Column(Text, default="")
    ship_to_contact = Column(String(100), default="")
    ship_to_phone = Column(String(50), default="")
    bill_to_name = Column(String(200), default="")
    bill_to_address = Column(Text, default="")
    bill_to_contact = Column(String(100), default="")
    bill_to_phone = Column(String(50), default="")
    end_user = Column(String(100), default="")
    vendor_code = Column(String(50), default="")
    ship_via = Column(String(100), default="")
    supplier_contact = Column(String(100), default="")
    buyer_name = Column(String(100), default="")
    requires_advance_payment = Column(Boolean, default=False)
    advance_payment_amount = Column(Numeric(16, 2), default=0)
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    supplier = relationship("Supplier")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_order.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    supplier_part_number = Column(String(100), default="")
    product_description = Column(Text, default="")
    quantity = Column(Numeric(12, 2), nullable=False)
    uom = Column(String(20), default="")
    unit_price = Column(Numeric(12, 4), nullable=False)
    total_price = Column(Numeric(16, 2), nullable=False)
    delivery_date = Column(Date, nullable=True)
    sales_order_line_id = Column(Integer, ForeignKey("sales_order_line.id"), nullable=True)
    received_quantity = Column(Numeric(12, 2), default=0)
    __table_args__ = (UniqueConstraint("purchase_order_id", "line_number"),)

    material = relationship("Material")


class PurchaseNotice(AuditMixin, Base):
    """销售订单审核后给采购侧的采购通知。"""
    __tablename__ = "purchase_notice"
    __doc_types__ = ("PURCHASE_NOTICE",)
    id = Column(Integer, primary_key=True)
    notice_number = Column(String(30), index=True, nullable=False)
    sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=True)
    requested_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    purchase_assistant_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    required_delivery_date = Column(Date, nullable=True)
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    __table_args__ = (UniqueConstraint("company_id", "notice_number"),)


class PurchaseNoticeLine(Base):
    __tablename__ = "purchase_notice_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    purchase_notice_id = Column(Integer, ForeignKey("purchase_notice.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    sales_order_line_id = Column(Integer, ForeignKey("sales_order_line.id"), nullable=True)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    quantity = Column(Numeric(12, 2), nullable=False)
    preferred_supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    required_delivery_date = Column(Date, nullable=True)
    packaging_requirements = Column(Text, default="")
    barcode_requirements = Column(Text, default="")
    notes = Column(Text, default="")
    __table_args__ = (UniqueConstraint("purchase_notice_id", "line_number"),)

    material = relationship("Material")


class SupplierInquiry(AuditMixin, Base):
    """对原厂询价登记（04a-2）：PA 据内部询价/销售邮件向 1~N 家原厂询价并记录报价。

    引擎此前无对原厂询价模型（只有 CRM 侧 SALES_INQUIRY）。子表 supplier_inquiry_line
    自动渲为 SubTableEditor 网格。轻量状态机 INQUIRING→QUOTED→ADOPTED→CLOSED。
    🔒Q18 防火墙：line.unit_price/commission 属采购进价，对销售端 SALES+SA 隐藏
    （services/tools.py BUY_TABLES + BUY_PRICE_FIELDS + _can_view_buy_price）。
    """
    __tablename__ = "supplier_inquiry"
    __doc_types__ = ("SUPPLIER_INQUIRY",)
    id = Column(Integer, primary_key=True)
    inquiry_number = Column(String(30), index=True, nullable=False)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    sales_inquiry_id = Column(Integer, ForeignKey("sales_inquiry.id"), nullable=True)  # 关联内部询价（04a-1）
    product_manager_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    status = Column(String(30), default="INQUIRING")
    notes = Column(Text, default="")

    supplier = relationship("Supplier")
    sales_inquiry = relationship("SalesInquiry")
    __table_args__ = (UniqueConstraint("company_id", "inquiry_number"),)


class SupplierInquiryLine(Base):
    """对原厂询价明细（04a-2 字段表，源《（找原厂）询价登记表.xls》OSI sheet 15 列）。

    🔒unit_price（对原厂单价）/commission（佣金）= 采购进价，对销售端 SALES+SA 隐藏。
    """
    __tablename__ = "supplier_inquiry_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    supplier_inquiry_id = Column(Integer, ForeignKey("supplier_inquiry.id"), nullable=False, index=True)
    line_number = Column(SmallInteger, nullable=False, default=1)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=True)   # 型号 P/N
    description = Column(Text, default="")                # 描述 Description
    unit_price = Column(Numeric(12, 4), nullable=True)    # 对原厂单价 U/P 🔒对 SALES/SA 隐藏
    currency = Column(String(3), default="USD")           # 货币
    quantity = Column(Numeric(12, 2), nullable=True)      # 数量 QTY
    uom = Column(String(20), default="pcs")               # 计量单位
    lead_time = Column(String(50), default="")            # 货期 Lead time（如 25周/n.a.）
    shipment_terms = Column(String(100), default="")      # 贸易条件（FOB HK / CIF…）
    payment_terms = Column(String(100), default="")       # 付款条件（T/T in advance / Net 30…）
    inquiry_date = Column(Date, nullable=True)            # 询价日期 Date
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)  # 此价为哪个客户问的
    sales = Column(String(100), default="")               # 负责销售
    remarks = Column(Text, default="")                    # 备注（MOQ=MPQ=680 等）
    mode = Column(String(30), default="Resell")           # 业务模式 Resell/Sample…
    commission = Column(String(50), default="")           # 佣金 Commission 🔒对 SALES/SA 隐藏
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)  # 原厂（显式化 Excel 隐含的 sheet/文件夹）

    material = relationship("Material")
    customer = relationship("Customer")
    supplier = relationship("Supplier")
    __table_args__ = (UniqueConstraint("supplier_inquiry_id", "line_number"),)


# ============================================================
# 仓库 & 库存
# ============================================================

class Warehouse(AuditMixin, Base):
    __tablename__ = "warehouse"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    warehouse_type = Column(String(10), default="MAIN")  # MAIN/BONDED/BRANCH
    city = Column(String(50), default="")
    address = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("company_id", "code"),)


class WarehouseLocation(Base):
    __tablename__ = "warehouse_location"
    # 段1b-2：库位需可建档/改档（PRD 03b 页面5 调拨依赖库位主数据），挂轻量单状态机
    #   WAREHOUSE_LOCATION（单态 ACTIVE，照段0c master_data_workflows 套路）。仍 __queryable__
    #   语义（has __doc_types__ → exposed），前端经 execute_transition 建/改库位。
    __doc_types__ = ("WAREHOUSE_LOCATION",)
    id = Column(Integer, primary_key=True)
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"), nullable=False)
    code = Column(String(30), nullable=False)
    zone = Column(String(20), default="")      # 货区（一级）
    shelf = Column(String(20), default="")     # 货架（二级）
    position = Column(String(20), default="")  # 货层（三级）
    is_active = Column(Boolean, default=True)
    # --- 段0b 主数据扩充（PRD 02 页面6 库位）---
    location_type = Column(String(15), default="NORMAL")  # 普通/流转仓/RMA/样品/待处理/NG（驱动 WMS 行为，本页只存）
    capacity = Column(Numeric(12, 2), nullable=True)      # 容量（蓝图 §3.4）
    # 段1b-2：轻量单状态机 WAREHOUSE_LOCATION（单态 ACTIVE）。execute_transition 编辑路径读 doc.status，
    #   故纯字典库位也需一个 status 列；建档即 ACTIVE，自环编辑（照段0c master_data 套路）。
    status = Column(String(15), default="ACTIVE")
    __table_args__ = (UniqueConstraint("warehouse_id", "code"),)


class Inventory(AuditMixin, Base):
    __tablename__ = "inventory"
    __doc_types__ = ("INVENTORY", "INVENTORY_VIRTUAL", "INVENTORY_COUNT")
    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey("material.id"))
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"))
    location_id = Column(Integer, ForeignKey("warehouse_location.id"), nullable=True)
    batch_number = Column(String(50), index=True, nullable=False)
    inbound_number = Column(String(50), index=True, default="")
    source_doc_number = Column(String(50), default="")
    serial_lot_number = Column(String(100), index=True, default="")
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    goods_nature = Column(String(30), default="")
    uom = Column(String(20), default="")
    tracking_number = Column(String(100), default="")
    delivery_method = Column(String(50), default="")
    carton_number = Column(String(50), default="")
    origin_country = Column(String(50), default="")
    hs_code = Column(String(50), default="")
    location_code = Column(String(50), default="")
    date_code = Column(String(50), default="")
    production_date = Column(Date, nullable=True)
    quantity = Column(Numeric(12, 2), nullable=False)
    reserved_quantity = Column(Numeric(12, 2), default=0)
    unit_cost = Column(Numeric(16, 4), default=0)
    total_cost = Column(Numeric(16, 2), default=0)
    received_date = Column(Date, index=True)
    purchase_order_line_id = Column(Integer, ForeignKey("purchase_order_line.id"), nullable=True)
    # 库存状态 7 态值集（PRD 03a-3 §「货物状态模型」蓝图 §5.4）：可售性纯值集 + 规则，
    # 不加 DB 约束破坏底座。AVAILABLE 可售 / RESERVED 已预留 / QUARANTINE 待处理待检 /
    # NG 不良 / SAMPLE 样品 / VENDOR_HOLD 原厂暂存 / SCRAP 报废(终态)。出库占用读它。
    status = Column(String(15), default="AVAILABLE")
    # --- 段1a 库存标记扩充（PRD 03a-3）---
    source_marker = Column(JSONB, default=dict)            # 来源/品质标记（RMA来源+品质好坏+原厂+PCN，可叠加筛选）
    reported_customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)  # 原厂报备客户（串货隔离，蓝图 §5.2）

    material = relationship("Material")
    warehouse = relationship("Warehouse")
    supplier = relationship("Supplier")

    __table_args__ = (Index("ix_inventory_fifo", "material_id", "warehouse_id", "received_date"),)


class InventoryReservation(AuditMixin, Base):
    """WMS: 锁定某个包装级库存给客户/销售订单。"""
    __tablename__ = "inventory_reservation"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    reservation_number = Column(String(40), nullable=False, index=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=False)
    sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=True)
    shipment_id = Column(Integer, ForeignKey("shipment_request.id"), nullable=True)
    quantity = Column(Numeric(12, 2), nullable=False)
    reserved_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    reserved_at = Column(DateTime, server_default=func.now())
    released_at = Column(DateTime, nullable=True)
    status = Column(String(15), default="ACTIVE")
    notes = Column(Text, default="")

    inventory = relationship("Inventory")
    customer = relationship("Customer")

    __table_args__ = (
        UniqueConstraint("company_id", "reservation_number"),
        Index("ix_inventory_reservation_active", "inventory_id", "status"),
    )


class InventoryPolicy(AuditMixin, Base):
    """WMS: 物料/仓库库存策略，用于预警和补货判断。"""
    __tablename__ = "inventory_policy"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"), nullable=True)
    safety_stock = Column(Numeric(12, 2), default=0)
    reorder_point = Column(Numeric(12, 2), default=0)
    max_stock = Column(Numeric(12, 2), default=0)
    lead_time_days = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    notes = Column(Text, default="")

    material = relationship("Material")
    warehouse = relationship("Warehouse")

    __table_args__ = (
        UniqueConstraint("company_id", "material_id", "warehouse_id"),
        Index("ix_inventory_policy_material_warehouse", "material_id", "warehouse_id"),
    )


class InventoryCount(AuditMixin, Base):
    """WMS: 库存盘点任务。"""
    __tablename__ = "inventory_count"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    count_number = Column(String(40), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"), nullable=True)
    planned_date = Column(Date, nullable=True)
    counted_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    adjusted_at = Column(DateTime, nullable=True)
    adjusted_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    status = Column(String(20), default="DRAFT")
    notes = Column(Text, default="")

    warehouse = relationship("Warehouse")

    __table_args__ = (UniqueConstraint("company_id", "count_number"),)


class InventoryCountLine(Base):
    """WMS: 盘点明细，保留盘点时的系统库存快照。"""
    __tablename__ = "inventory_count_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    inventory_count_id = Column(Integer, ForeignKey("inventory_count.id"), nullable=False)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"), nullable=True)
    location_code = Column(String(50), default="")
    batch_number = Column(String(50), default="")
    inbound_number = Column(String(50), default="")
    serial_lot_number = Column(String(100), default="")
    # 段1b-2：盘点表「分性质视图」（走流程/待處理/貨/樣品/帶貨/RMA/NG品，PRD 03b 页面6）所需性质列。
    # 建盘点行时从 inventory.goods_nature 快照带入，供前端按性质分 sheet 呈现。
    goods_nature = Column(String(30), default="")
    system_quantity = Column(Numeric(12, 2), nullable=False)
    counted_quantity = Column(Numeric(12, 2), nullable=True)
    difference_quantity = Column(Numeric(12, 2), default=0)
    status = Column(String(20), default="PENDING")
    notes = Column(Text, default="")

    inventory = relationship("Inventory")
    material = relationship("Material")
    warehouse = relationship("Warehouse")

    __table_args__ = (
        UniqueConstraint("inventory_count_id", "inventory_id"),
        Index("ix_inventory_count_line_count", "inventory_count_id"),
    )


# ============================================================
# 段1b-2 · 调拨单 / 库存调整单（PRD 03b 页面5 调拨 · 页面7 库存调整单）
#
# 两类新单据（引擎当前无 doc_type，照段0c/段1 套路 ➕ 新建模型 + __doc_types__ +
# 轻量 WorkflowDefinition）。调拨=同公司内仓/库位间移库（绝不跨公司）；库存调整单=
# 盘点差异落账（差异原因必填 → posted 调 inventory.quantity + COUNT_ADJUST 流水 + 推金蝶）。
# 引擎五条不破坏：均为引擎扩展点（新实体不动核心），写仍走 execute_transition / @register_command。
# ============================================================

class StockTransfer(AuditMixin, Base):
    """WMS: 调拨单（仅同公司内仓/库位间移库，PRD 03b 页面5）。

    源库位.company_id == 目标库位.company_id（同公司 hard_rule + _company_filter 双保险）。
    done AUTO effect：改 inventory.location_id + 写两条 InventoryMovement(TRANSFER_OUT/TRANSFER_IN)。
    调拨为公司内移库，不改财务存货总量，默认不推金蝶（PRD 页面5 推送默认否）。
    """
    __tablename__ = "stock_transfer"
    __doc_types__ = ("STOCK_TRANSFER",)
    id = Column(Integer, primary_key=True)
    transfer_number = Column(String(40), nullable=False, index=True)
    source_location_id = Column(Integer, ForeignKey("warehouse_location.id"), nullable=False)
    target_location_id = Column(Integer, ForeignKey("warehouse_location.id"), nullable=False)
    status = Column(String(20), default="DRAFT")
    notes = Column(Text, default="")

    __table_args__ = (UniqueConstraint("company_id", "transfer_number"),)


class StockTransferLine(Base):
    """WMS: 调拨明细（发出哪些批次 / 数量），PRD 03b 页面5 子表。"""
    __tablename__ = "stock_transfer_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    stock_transfer_id = Column(Integer, ForeignKey("stock_transfer.id"), nullable=False, index=True)
    line_number = Column(SmallInteger, nullable=False, default=1)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    inbound_number = Column(String(50), default="")   # 入仓编号（批次定位，串货隔离用，不改 SN/LOT）
    quantity = Column(Numeric(12, 2), nullable=False)
    notes = Column(Text, default="")

    inventory = relationship("Inventory")
    __table_args__ = (UniqueConstraint("stock_transfer_id", "line_number"),)


class StockAdjustment(AuditMixin, Base):
    """WMS: 库存调整单（盘点差异 → 推金蝶，PRD 03b 页面7）。

    一张 = 一次盘点的一批差异行；关联盘点单 inventory_count_id。
    draft → confirm[FINANCE]（每行差异原因必填 hard_rule）→ posted（AUTO effect：
    按差异调 inventory.quantity + 写 InventoryMovement(COUNT_ADJUST) + 推金蝶库存调整单，默认 OFF）。
    """
    __tablename__ = "stock_adjustment"
    __doc_types__ = ("STOCK_ADJUSTMENT",)
    id = Column(Integer, primary_key=True)
    adjustment_number = Column(String(40), nullable=False, index=True)
    inventory_count_id = Column(Integer, ForeignKey("inventory_count.id"), nullable=True, index=True)
    status = Column(String(20), default="DRAFT")
    notes = Column(Text, default="")

    inventory_count = relationship("InventoryCount")
    __table_args__ = (UniqueConstraint("company_id", "adjustment_number"),)


class StockAdjustmentLine(Base):
    """WMS: 库存调整明细（盘点带出系统/实际/差异 + 差异原因），PRD 03b 页面7 子表。

    reason 值集：出库录错 OUT_ERR / 入库录错 IN_ERR / 实物损 PHYS_LOSS / 实物溢 PHYS_GAIN / 其他 OTHER。
    差异原因必填（confirm hard_rule，引擎 04 §4.B）。difference = actual_quantity − system_quantity。
    """
    __tablename__ = "stock_adjustment_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    stock_adjustment_id = Column(Integer, ForeignKey("stock_adjustment.id"), nullable=False, index=True)
    line_number = Column(SmallInteger, nullable=False, default=1)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    inbound_number = Column(String(50), default="")
    system_quantity = Column(Numeric(12, 2), nullable=False)
    actual_quantity = Column(Numeric(12, 2), nullable=False)
    difference = Column(Numeric(12, 2), default=0)
    reason = Column(String(20), default="")   # OUT_ERR / IN_ERR / PHYS_LOSS / PHYS_GAIN / OTHER
    notes = Column(Text, default="")

    inventory = relationship("Inventory")
    __table_args__ = (UniqueConstraint("stock_adjustment_id", "line_number"),)


class SupplierSnRule(AuditMixin, Base):
    """WMS: 按供应商/物料配置 SN/LOT 校验规则。"""
    __tablename__ = "supplier_sn_rule"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=True)
    rule_name = Column(String(100), default="")
    exact_length = Column(SmallInteger, nullable=True)
    min_length = Column(SmallInteger, nullable=True)
    max_length = Column(SmallInteger, nullable=True)
    pattern = Column(String(200), default="")
    allow_duplicate = Column(Boolean, default=True)
    unique_scope = Column(String(30), default="SUPPLIER_MATERIAL")
    is_active = Column(Boolean, default=True)
    notes = Column(Text, default="")

    supplier = relationship("Supplier")
    material = relationship("Material")


class WmsAttachment(AuditMixin, Base):
    """WMS: 入库照片、标签照片和单据附件的元数据。"""
    __tablename__ = "wms_attachment"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    doc_type = Column(String(30), default="", index=True)
    doc_id = Column(BigInteger, nullable=True, index=True)
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipt.id"), nullable=True)
    goods_receipt_line_id = Column(Integer, ForeignKey("goods_receipt_line.id"), nullable=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=True)
    attachment_type = Column(String(30), default="PHOTO")
    file_name = Column(String(200), nullable=False)
    content_type = Column(String(100), default="")
    file_size = Column(Integer, default=0)
    storage_path = Column(Text, nullable=False)
    uploaded_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    uploaded_at = Column(DateTime, server_default=func.now())
    notes = Column(Text, default="")


class GoodsReceipt(AuditMixin, Base):
    __tablename__ = "goods_receipt"
    __doc_types__ = ("GOODS_RECEIPT",)
    id = Column(Integer, primary_key=True)
    receipt_number = Column(String(30), nullable=False)
    __table_args__ = (UniqueConstraint("company_id", "receipt_number"),)
    purchase_order_id = Column(Integer, ForeignKey("purchase_order.id"))
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"))
    received_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    received_date = Column(Date, nullable=True)
    status = Column(String(15), default="PENDING")
    notes = Column(Text, default="")
    # --- 段1a 入库头部扩充（PRD 03a-1 表头「基本進庫」）---
    # inbound_type：外购入库 PURCHASE / 其他入库[样品] OTHER / 退货入库 RETURN / 调拨入库 TRANSFER /
    #   委外加工入库 SUBCONTRACT（访谈 02:37、03a-9 委外做薄）。纯值集，默认外购入库。
    # inbound_type 值集（段1b-2 追加 OUTSOURCE_IN 委外加工入库，03a-9b 做薄）：
    #   PURCHASE 外购入库 / OTHER 其他入库[样品] / RETURN 退货入库 / TRANSFER 调拨入库 / OUTSOURCE_IN 委外加工入库。
    #   委外加工入库复用整套 GOODS_RECEIPT 流程/PA 审核/STOCKED_IN effect，不新增 doc_type/状态机。
    inbound_type = Column(String(20), default="PURCHASE")
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)   # 头部供应商（外箱识别后选，行级亦带）；委外加工入库时语义=委外方
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)   # 客户（可后补，蓝图 §3.4）
    reviewer_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 审核 PA（按供应商自动带出）
    # 段1b-2：委外加工入库弱关联对应委外发料单号（仅留痕，不做数量勾稽强校验，03a-9b 做薄）。
    source_issue_number = Column(String(50), default="")


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipt.id"), nullable=False)
    # 样品/无 PO 入库放宽：purchase_order_line_id 可空（PRD 03a-1 PO# 须问 PA / 样品无 PO）。
    purchase_order_line_id = Column(Integer, ForeignKey("purchase_order_line.id"), nullable=True)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    expected_quantity = Column(Numeric(12, 2), nullable=False)
    actual_quantity = Column(Numeric(12, 2), nullable=False)
    quality_status = Column(String(10), default="OK")
    discrepancy_note = Column(Text, default="")
    batch_number = Column(String(50), default="")
    inbound_number = Column(String(50), default="")
    serial_lot_number = Column(String(100), default="")
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    goods_nature = Column(String(30), default="")
    uom = Column(String(20), default="")
    tracking_number = Column(String(100), default="")
    delivery_method = Column(String(50), default="")
    source_doc_number = Column(String(50), default="")
    carton_number = Column(String(50), default="")
    origin_country = Column(String(50), default="")
    hs_code = Column(String(50), default="")
    location_code = Column(String(50), default="")
    date_code = Column(String(50), default="")
    production_date = Column(Date, nullable=True)
    # --- 段1a 明细补列（PRD 03a-1 進庫詳細資料 6 列）---
    remark = Column(Text, default="")                       # REMARK（尾码/版本/漏气/统一包装红字标）
    customs_fee = Column(Numeric(16, 2), nullable=True)     # 报关费（多由报关模块回填）
    freight_fee = Column(Numeric(16, 2), nullable=True)     # 运费（后补）
    import_export_cert = Column(String(50), default="")     # 进出口证（可 #N/A）
    bag_seal_date = Column(Date, nullable=True)             # BAG SEAL DATE（部分供应商封袋日）
    ba_hold = Column(String(20), default="")               # BA留货（内部留货标记）


class ShipmentRequest(AuditMixin, Base):
    __tablename__ = "shipment_request"
    __doc_types__ = ("SHIPMENT",)
    id = Column(Integer, primary_key=True)
    shipment_number = Column(String(30), nullable=False)
    __table_args__ = (UniqueConstraint("company_id", "shipment_number"),)
    sales_order_id = Column(Integer, ForeignKey("sales_order.id"))
    requested_by_id = Column(Integer, ForeignKey("user_account.id"))
    approved_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"), nullable=True)
    shipping_method = Column(String(10), default="")
    tracking_number = Column(String(100), default="")
    source_purchase_order_number = Column(String(50), default="")
    product_line = Column(String(50), default="")
    payment_terms_text = Column(String(100), default="")
    document_status = Column(String(50), default="")
    packaging_requirements = Column(Text, default="")
    barcode_requirements = Column(Text, default="")
    delivery_requirements = Column(Text, default="")
    label_status = Column(String(20), default="PENDING")
    inspection_status = Column(String(20), default="PENDING")
    status = Column(String(20), default="DRAFT")
    shipped_date = Column(Date, nullable=True)
    notes = Column(Text, default="")
    # --- 段1b-1 出库头部扩充（PRD 03b 页面2 + 03a-9 委外发料）---
    # outbound_type：出库类型纯值集。CUSTOMER 客户发货（默认，走互检+财务放行两道关）/
    #   TRANSFER 调拨出库 / OUTSOURCE 委外发料（发料对象=委外方非客户，绕过客户发货财务放行关，03a-9）。
    outbound_type = Column(String(20), default="CUSTOMER")
    vendor_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)   # 委外方=供应商主数据（仅委外发料用，03a-9）
    outsource_note = Column(Text, default="")                               # 加工/采买说明（自由文本，不建工序/BOM，03a-9）


class ShipmentLine(Base):
    __tablename__ = "shipment_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    shipment_id = Column(Integer, ForeignKey("shipment_request.id"), nullable=False)
    # 委外发料无销售订单（发料对象=委外方），放宽为可空（PRD 03a-9）；客户发货仍由 validator 兜底。
    sales_order_line_id = Column(Integer, ForeignKey("sales_order_line.id"), nullable=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    quantity = Column(Numeric(12, 2), nullable=False)
    uom = Column(String(20), default="")
    inbound_number = Column(String(50), default="")
    serial_lot_number = Column(String(100), default="")
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    goods_nature = Column(String(30), default="")
    tracking_number = Column(String(100), default="")
    delivery_method = Column(String(50), default="")
    invoice_number = Column(String(50), default="")
    carton_number = Column(String(50), default="")
    origin_country = Column(String(50), default="")
    hs_code = Column(String(50), default="")
    # --- 段1b-1 每包照片留证（PRD 03b 页面2 第4/5点：规定每一包都要拍照）---
    # photo_refs：多图引用（wms_attachment.id 或外部共享文档引用字符串），进互检前 hard_rule 须非空。
    photo_refs = Column(JSONB, default=list)


class SalesReturn(AuditMixin, Base):
    """WMS/ERP: 客户退货通知和退货入库源单。"""
    __tablename__ = "sales_return"
    __doc_types__ = ("SALES_RETURN",)
    id = Column(Integer, primary_key=True)
    return_number = Column(String(30), index=True, nullable=False)
    sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=True)
    shipment_id = Column(Integer, ForeignKey("shipment_request.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customer.id"))
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"), nullable=True)
    return_reason = Column(Text, default="")
    logistics_tracking_number = Column(String(100), default="")
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    __table_args__ = (UniqueConstraint("company_id", "return_number"),)


class SalesReturnLine(Base):
    __tablename__ = "sales_return_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    sales_return_id = Column(Integer, ForeignKey("sales_return.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    sales_order_line_id = Column(Integer, ForeignKey("sales_order_line.id"), nullable=True)
    shipment_line_id = Column(Integer, ForeignKey("shipment_line.id"), nullable=True)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    quantity = Column(Numeric(12, 2), nullable=False)
    quality_status = Column(String(10), default="PENDING")
    return_action = Column(String(20), default="RESTOCK")
    notes = Column(Text, default="")
    __table_args__ = (UniqueConstraint("sales_return_id", "line_number"),)


class PickingList(Base):
    __tablename__ = "picking_list"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    shipment_id = Column(Integer, ForeignKey("shipment_request.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"), nullable=False)
    assigned_to_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    status = Column(String(15), default="PENDING")
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)


class PickingListLine(Base):
    __tablename__ = "picking_list_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    picking_list_id = Column(Integer, ForeignKey("picking_list.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("warehouse_location.id"), nullable=True)
    quantity = Column(Numeric(12, 2), nullable=False)
    picked_quantity = Column(Numeric(12, 2), default=0)
    is_verified = Column(Boolean, default=False)


class LabelTemplate(AuditMixin, Base):
    """标签模板（段0c·标签模板引擎，PRD 09 §9.1 + 09-标签模板规格逐客户）。

    一条 = 一种客户标签（按 客户×公司×标签类型 粒度，不按客户整体建）。引擎无原生
    标签子系统（仅 custom_html 逃生舱），本表 + LabelFieldLine 子表 + build_label_payload
    命令补足：模板头存尺寸/二维码拼接规则（分隔符 + 字段序），子表存字段映射（标签字段→
    数据来源字段、顺序、是否渲条码/进二维码）。出库时由命令按模板把一张单的数据拼成标签
    字段 + 二维码串。引擎五条不破坏：纯业务积木，写仍走 execute_transition / @register_command。
    """
    __tablename__ = "label_template"
    __doc_types__ = ("LABEL_TEMPLATE",)
    id = Column(Integer, primary_key=True)
    # 段1a：放宽为可空——内部入仓编号标签（INTERNAL）不绑客户（PRD 03a-6）；客户标签仍带 customer_id。
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)  # 显示名
    label_type = Column(String(20), default="PKG1")   # 标签类型：PKG1 包装1 / PKG2 包装2 / OUTER 外箱 / COMPANY_OUTER 公司外箱 / INTERNAL 内部入仓编号
    size_mm = Column(String(20), default="")          # 尺寸（如 62x29）
    orientation = Column(String(10), default="PORTRAIT")  # 朝向（占位）
    # 二维码拼接规则（核心）：分隔符 + 进二维码的字段顺序（字段码有序数组）
    qr_separator = Column(String(10), default="")     # & ; + , _ 无/自定义（各客户唯一，PRD §12）
    qr_field_order = Column(JSONB, default=list)       # ["型号","物料编码",...] 有序字段码
    barcode_fields = Column(JSONB, default=list)       # 哪些字段额外渲条码（如 数量列、发货日期）
    # 兼容旧字段（保留，避免破坏既有引用）
    template_content = Column(Text, default="")        # 渲染骨架/产物（custom_html 逃生舱落点）
    fields_mapping = Column(JSONB, default=dict)        # 旧版字段映射（保留）
    is_default = Column(Boolean, default=False)
    status = Column(String(15), default="ACTIVE")      # 轻量单状态机 ACTIVE（建档/编辑）
    is_active = Column(Boolean, default=True)
    notes = Column(Text, default="")

    __table_args__ = (
        UniqueConstraint("company_id", "customer_id", "label_type", name="ux_label_template_company_cust_type"),
    )


class LabelFieldLine(Base):
    """标签字段映射子表（段0c·标签模板引擎，PRD 09 §9.1 字段子表）。

    每行 = 标签上一个字段：标签字段名 → 数据来源字段 + 顺序号 + 是否渲条码 + 是否进二维码。
    source_type：OUTBOUND 出库登记 / INBOUND 入库批次 / EMAIL 邮件附件手填 / CUSTOMER_SYS 客户系统 /
    DERIVED 派生公式 / CONST 常量（PRD §9.1 source_type 枚举）。__queryable__ 子表，SubTableEditor 网格录入。
    """
    __tablename__ = "label_field_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    label_template_id = Column(Integer, ForeignKey("label_template.id"), nullable=False, index=True)
    line_number = Column(SmallInteger, nullable=False, default=1)  # 顺序号
    label_field_title = Column(String(100), nullable=False)  # 标签上的字段显示名（如 "型號"/"LOT NO"/"COO"）
    source_type = Column(String(20), default="OUTBOUND")     # 数据来源类型
    source_field = Column(String(80), default="")            # 来源字段名（如 型號 / SN/LOT# / 數量 / 原產地）
    derive_expr = Column(String(200), default="")            # 派生公式（source_type=DERIVED，如 "合同号前5位"）
    const_value = Column(String(200), default="")            # 常量值（source_type=CONST，如供货单位预设抬头）
    in_qr = Column(Boolean, default=False)                   # 是否进二维码
    qr_order = Column(SmallInteger, nullable=True)           # 在二维码里的顺序（in_qr=True 时）
    render_as_barcode = Column(Boolean, default=False)       # 该字段额外渲条码
    __table_args__ = (UniqueConstraint("label_template_id", "line_number"),)


class DocTemplate(AuditMixin, Base):
    """单据模板（段0c·单据模板引擎，PRD 09 §9.2 + 09-单据模板规格 PL/INV/送货单）。

    一条 = 一种客户×公司的对外单据模板（PL 装箱单 / INV 商业发票 / 送货单）。引擎无原生
    单据模板子系统（仅 custom_html 逃生舱），本表 + DocTemplateFieldLine 子表 + render_doc_template
    命令补足：模板头存抬头/区域/盖章·回签标志，子表存字段集（字段→来源 + 本地/出口切换 + 渲条码）。
    customer_id 空=公司通用模板。引擎五条不破坏：纯业务积木。
    """
    __tablename__ = "doc_template"
    __doc_types__ = ("DOC_TEMPLATE",)
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True, index=True)  # 空=公司通用
    name = Column(String(100), nullable=False)  # 显示名
    doc_kind = Column(String(20), default="PL")  # PL 装箱单 / INV 商业发票 / DN_CUST 客户送货单 / DN_FWD 货代托运单
    region = Column(String(10), default="HK")    # HK / CN（区域差异：抬头/税率/币种，随 company）
    needs_stamp = Column(Boolean, default=False)        # 盖章版（导出→打印盖章→扫描回传）
    needs_countersign = Column(Boolean, default=False)  # 回签流转（客户签回）
    header_title = Column(Text, default="")             # 发货公司抬头（随 company）
    bank_block = Column(Text, default="")               # 银行块（保理/OSA 账户块，Innolight/Eoptolink）
    render_html = Column(Text, default="")              # 渲染产物（custom_html 逃生舱落点）
    status = Column(String(15), default="ACTIVE")       # 轻量单状态机 ACTIVE
    is_active = Column(Boolean, default=True)
    notes = Column(Text, default="")

    __table_args__ = (
        Index("ix_doc_template_company_kind", "company_id", "doc_kind", "customer_id"),
    )


class DocTemplateFieldLine(Base):
    """单据模板字段子表（段0c·单据模板引擎，PRD 09 §9.2 字段子表）。

    每行 = 单据上一个字段：字段标题 → 来源字段 + 本地/出口切换（is_variant，如发票号↔报关单号）+
    是否渲条码（旭创/智禾数量列、外箱发货日期）。__queryable__ 子表，SubTableEditor 网格录入。
    """
    __tablename__ = "doc_template_field_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    doc_template_id = Column(Integer, ForeignKey("doc_template.id"), nullable=False, index=True)
    line_number = Column(SmallInteger, nullable=False, default=1)
    doc_field_title = Column(String(100), nullable=False)  # 单据上字段显示名（如 DESCRIPTION OF GOODS / QUANTITY）
    source_field = Column(String(80), default="")          # 来源字段（出库/发票/合同字段）
    const_value = Column(String(200), default="")          # 常量值（抬头/固定文案）
    is_variant_field = Column(Boolean, default=False)      # 本地/出口切换字段
    variant_local = Column(String(80), default="")         # 本地取值来源（如发票号）
    variant_export = Column(String(80), default="")        # 出口取值来源（如报关单号）
    render_as_barcode = Column(Boolean, default=False)     # 渲条码（数量列/外箱发货日期）
    __table_args__ = (UniqueConstraint("doc_template_id", "line_number"),)


# ============================================================
# 财务
# ============================================================

class FiscalYear(Base):
    __tablename__ = "fiscal_year"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False)
    year = Column(Integer, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(10), default="OPEN")
    __table_args__ = (UniqueConstraint("company_id", "year"),)


class AccountingPeriod(Base):
    __tablename__ = "accounting_period"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    fiscal_year_id = Column(Integer, ForeignKey("fiscal_year.id"), nullable=False)
    period_number = Column(SmallInteger, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(10), default="OPEN")
    closed_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("fiscal_year_id", "period_number"),)


class Account(Base):
    __tablename__ = "account"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False)
    code = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey("account.id"), nullable=True)
    account_type = Column(String(15), nullable=False)  # ASSET/LIABILITY/EQUITY/REVENUE/EXPENSE/COGS
    balance_direction = Column(String(10), nullable=False)  # DEBIT/CREDIT
    level = Column(SmallInteger, default=1)
    is_leaf = Column(Boolean, default=True)
    currency = Column(String(3), default="CNY")
    is_active = Column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("company_id", "code"),)


class Voucher(AuditMixin, Base):
    __tablename__ = "voucher"
    __doc_types__ = ("VOUCHER", "VOUCHER_ADJUSTMENT")
    id = Column(Integer, primary_key=True)
    voucher_number = Column(String(30), index=True, nullable=False)
    voucher_date = Column(Date, nullable=False)
    period_id = Column(Integer, ForeignKey("accounting_period.id"), nullable=False)
    voucher_type = Column(String(10), default="GENERAL")
    description = Column(String(200), default="")
    total_debit = Column(Numeric(16, 2), default=0)
    total_credit = Column(Numeric(16, 2), default=0)
    status = Column(String(30), default="DRAFT")
    is_auto_generated = Column(Boolean, default=False)
    source_doc_type = Column(String(30), default="")
    source_doc_id = Column(BigInteger, nullable=True)
    posted_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("company_id", "voucher_number"),)


class VoucherEntry(Base):
    __tablename__ = "voucher_entry"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    voucher_id = Column(Integer, ForeignKey("voucher.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    account_id = Column(Integer, ForeignKey("account.id"), nullable=False)
    description = Column(String(200), default="")
    debit = Column(Numeric(16, 2), default=0)
    credit = Column(Numeric(16, 2), default=0)
    currency = Column(String(3), default="CNY")
    exchange_rate = Column(Numeric(12, 6), default=1)
    __table_args__ = (UniqueConstraint("voucher_id", "line_number"),)

    account = relationship("Account")


class AccountBalance(Base):
    __tablename__ = "account_balance"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("account.id"), nullable=False)
    period_id = Column(Integer, ForeignKey("accounting_period.id"), nullable=False)
    opening_debit = Column(Numeric(16, 2), default=0)
    opening_credit = Column(Numeric(16, 2), default=0)
    period_debit = Column(Numeric(16, 2), default=0)
    period_credit = Column(Numeric(16, 2), default=0)
    closing_debit = Column(Numeric(16, 2), default=0)
    closing_credit = Column(Numeric(16, 2), default=0)
    __table_args__ = (UniqueConstraint("company_id", "account_id", "period_id"),)


class ExchangeRate(Base):
    __tablename__ = "exchange_rate"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    from_currency = Column(String(3), nullable=False)
    to_currency = Column(String(3), nullable=False)
    rate = Column(Numeric(12, 6), nullable=False)
    effective_date = Column(Date, nullable=False, index=True)
    __table_args__ = (UniqueConstraint("from_currency", "to_currency", "effective_date"),)


class AccountsReceivable(AuditMixin, Base):
    __tablename__ = "accounts_receivable"
    __doc_types__ = ("ACCOUNTS_RECEIVABLE",)
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id"))
    sales_order_id = Column(Integer, ForeignKey("sales_order.id"))
    contract_id = Column(Integer, ForeignKey("framework_contract.id"), nullable=True)
    voucher_id = Column(Integer, ForeignKey("voucher.id"), nullable=True)
    settlement_batch_no = Column(String(50), default="", index=True)
    invoice_number = Column(String(50), default="", index=True)
    amount = Column(Numeric(16, 2))
    currency = Column(String(3))
    exchange_rate = Column(Numeric(12, 6), default=1)
    due_date = Column(Date)
    paid_amount = Column(Numeric(16, 2), default=0)
    paid_date = Column(Date, nullable=True)
    status = Column(String(30), default="PENDING")


class AccountsPayable(AuditMixin, Base):
    __tablename__ = "accounts_payable"
    __doc_types__ = ("ACCOUNTS_PAYABLE",)
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"))
    purchase_order_id = Column(Integer, ForeignKey("purchase_order.id"))
    invoice_number = Column(String(50), default="", index=True)
    amount = Column(Numeric(16, 2))
    currency = Column(String(3))
    exchange_rate = Column(Numeric(12, 6), default=1)
    due_date = Column(Date)
    paid_amount = Column(Numeric(16, 2), default=0)
    paid_date = Column(Date, nullable=True)
    status = Column(String(30), default="PENDING")


class SupplierCredit(AuditMixin, Base):
    __tablename__ = "supplier_credit"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=False)
    credit_limit = Column(Numeric(16, 2), nullable=False)
    currency = Column(String(3), default="USD")
    used_amount = Column(Numeric(16, 2), default=0)
    warning_threshold_pct = Column(Integer, default=80)
    __table_args__ = (UniqueConstraint("company_id", "supplier_id"),)


class CustomerCredit(AuditMixin, Base):
    __tablename__ = "customer_credit"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=False)
    credit_limit = Column(Numeric(16, 2), nullable=False)
    currency = Column(String(3), default="USD")
    used_amount = Column(Numeric(16, 2), default=0)
    warning_threshold_pct = Column(Integer, default=80)
    credit_period_days = Column(Integer, default=30)
    credit_rating = Column(String(10), default="")
    __table_args__ = (UniqueConstraint("company_id", "customer_id"),)


class NotesReceivable(AuditMixin, Base):
    """应收票据：商业汇票/银行承兑等"""
    __tablename__ = "notes_receivable"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id"))
    note_number = Column(String(50), default="", index=True)
    note_type = Column(String(20), default="COMMERCIAL")
    amount = Column(Numeric(16, 2), nullable=False)
    currency = Column(String(3), default="CNY")
    issue_date = Column(Date)
    maturity_date = Column(Date)
    drawer = Column(String(100), default="")
    acceptor = Column(String(100), default="")
    status = Column(String(20), default="HELD")


class BankReceipt(AuditMixin, Base):
    """银行收款流水：现金管理模块联动"""
    __tablename__ = "bank_receipt"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    receipt_number = Column(String(50), default="", index=True)
    bank_account = Column(String(50), default="")
    amount = Column(Numeric(16, 2), nullable=False)
    currency = Column(String(3), default="CNY")
    receipt_date = Column(Date, index=True)
    payer_name = Column(String(100), default="")
    remark = Column(Text, default="")
    status = Column(String(20), default="UNALLOCATED")


class ARSettlement(AuditMixin, Base):
    """应收款核销明细：一笔款核销多张发票"""
    __tablename__ = "ar_settlement"
    id = Column(Integer, primary_key=True)
    batch_no = Column(String(50), default="", index=True)
    ar_id = Column(Integer, ForeignKey("accounts_receivable.id"), nullable=False)
    bank_receipt_id = Column(Integer, ForeignKey("bank_receipt.id"), nullable=True)
    note_id = Column(Integer, ForeignKey("notes_receivable.id"), nullable=True)
    settle_amount = Column(Numeric(16, 2), nullable=False)
    settle_date = Column(Date)
    remark = Column(Text, default="")


class AdvanceReceipt(AuditMixin, Base):
    """销售侧预收款：客户未发货前付款，关联销售订单。"""
    __tablename__ = "advance_receipt"
    __doc_types__ = ("ADVANCE_RECEIPT",)
    id = Column(Integer, primary_key=True)
    receipt_number = Column(String(50), index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=True)
    bank_account = Column(String(50), default="")
    payer_name = Column(String(100), default="")
    amount = Column(Numeric(16, 2), nullable=False)
    currency = Column(String(3), default="CNY")
    receipt_date = Column(Date, nullable=True)
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    __table_args__ = (UniqueConstraint("company_id", "receipt_number"),)


class AdvancePayment(AuditMixin, Base):
    """采购侧预付款：公司未收货前付款给供应商，关联采购订单。"""
    __tablename__ = "advance_payment"
    __doc_types__ = ("ADVANCE_PAYMENT",)
    id = Column(Integer, primary_key=True)
    payment_number = Column(String(50), index=True, nullable=False)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_order.id"), nullable=True)
    requested_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    bank_account = Column(String(50), default="")
    payee_name = Column(String(100), default="")
    amount = Column(Numeric(16, 2), nullable=False)
    currency = Column(String(3), default="CNY")
    payment_date = Column(Date, nullable=True)
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    __table_args__ = (UniqueConstraint("company_id", "payment_number"),)


class PaymentRequest(AuditMixin, Base):
    """付款申请（04a-8 货后付款，决策④：发起在采购、执行在财务）。

    预付用 ADVANCE_PAYMENT（PO 下单即付，本无发票）；货后付款用本模型——关联已审进项发票，
    PA 发起 → ★FINANCE 执行（做账/打款在金蝶）→ 到账确认（confirmed），本系统只记到账确认 + 台账。
    应付余额递减落在 accounts_payable.paid_amount（confirm effect）。
    """
    __tablename__ = "payment_request"
    __doc_types__ = ("PAYMENT_REQUEST",)
    id = Column(Integer, primary_key=True)
    payment_number = Column(String(50), index=True, nullable=False)
    payment_type = Column(String(20), default="POST_DELIVERY")  # ADVANCE / POST_DELIVERY（货后）
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_order.id"), nullable=True)
    purchase_invoice_id = Column(Integer, ForeignKey("purchase_invoice.id"), nullable=True)  # 货后必填：关联已审进项发票
    requested_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    bank_account = Column(String(50), default="")
    payee_name = Column(String(100), default="")
    amount = Column(Numeric(16, 2), nullable=False)
    currency = Column(String(3), default="CNY")
    due_date = Column(Date, nullable=True)       # 付款到期日（货款到期日期）
    payment_date = Column(Date, nullable=True)   # 财务执行回填
    confirmed = Column(Boolean, default=False)   # 决策④：到账确认标记（财务执行后置）
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    __table_args__ = (UniqueConstraint("company_id", "payment_number"),)


class PurchaseInTransit(AuditMixin, Base):
    """采购在途跟踪（04a-6，原厂→我方，PA 人工跟踪货期）。

    引擎无在途模型/无定时器。本表存 PA 线下催来的承诺货期/最新预计/跟踪状态（一 PO 一行）；
    订单/已收/在途数量由 /api/purchase/intransit 聚合 purchase_order_line 实时算（不冗存）。
    提醒由 notifications.scan_purchase_in_transit_alerts 扫「超期未给货期/未发货」生成（手动/外部调度）。
    __queryable__：PA 可在台账查看/录入承诺货期。
    """
    __tablename__ = "purchase_in_transit"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_order.id"), nullable=False)
    promised_eta = Column(Date, nullable=True)   # 原厂承诺货期（PA 线下催来录入）
    latest_eta = Column(Date, nullable=True)     # 最新预计到货（PA 更新）
    # 跟踪状态：PENDING_ACCEPT 待确认接单 / ACCEPTED 已接单待货期 / ETA_GIVEN 已给货期 /
    # SHIPPED 已发货 / PARTIAL 部分到货 / RECEIVED 已到货
    track_status = Column(String(20), default="PENDING_ACCEPT")
    shipped_date = Column(Date, nullable=True)
    notes = Column(Text, default="")

    __table_args__ = (UniqueConstraint("company_id", "purchase_order_id"),)


class StockUpRequest(AuditMixin, Base):
    """备货申请单（04b-1 StockUpRequest）：销售/PM 主动提议囤货，金额阈值分流审批。

    引擎排除「备货」业务（引擎 02 §2.9）→ 全新增 doc_type。流程：
      DRAFT →[阈值分流]→ PENDING_PM（<20万 PM 单批）/ PENDING_REVIEW（★≥20万 PM+FINANCE 会审）
      → APPROVED → TRACKING（消单中）→ CLOSED ；REJECTED / CANCELLED 终态。
    ≥20万会审复用并行会签标准件（services/cosign，cosign_group=STOCK_REVIEW，PM+FINANCE 都签才放行）。
    建单 START effect 拍下当时库存/在途快照（只读列）；request_number 月度连号 SU-YYMM-001。
    字段防火墙（§00-8）：amount 按含税报价口径，对 SALES 可见（单上无成本/买价列）。
    """
    __tablename__ = "stock_up_request"
    __doc_types__ = ("STOCK_UP_REQUEST",)
    id = Column(Integer, primary_key=True)
    request_number = Column(String(30), index=True, nullable=False)  # SU-YYMM-001 月度连号
    requested_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 发起人（创建态自动置）
    requester_role = Column(String(30), default="")  # 发起角色（SALES / PRODUCT_MANAGER，区分谁提议）
    material_id = Column(Integer, ForeignKey("material.id"), nullable=True)  # 型号
    stockup_quantity = Column(Numeric(12, 2), nullable=True)  # 原始备货数量（永不改，消单基准）
    stock_on_hand = Column(Numeric(12, 2), nullable=True)     # 当时库存（只读快照，建单 effect 拍下）
    in_transit_qty = Column(Numeric(12, 2), nullable=True)    # 当时在途（只读快照，采购在途投影）
    intended_customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)  # 意向客户（给谁备）
    signing_company_id = Column(Integer, ForeignKey("company.id"), nullable=True)  # 签单公司（=company_id，绝不跨公司）
    customer_arrears = Column(Numeric(16, 2), nullable=True)  # 客户欠款情况（应收视图带出 + 可补注）
    reason = Column(Text, default="")        # 备货原因
    risk_notes = Column(Text, default="")    # 风险点（会审前必填）
    amount = Column(Numeric(16, 2), nullable=True)  # 备货金额（含税报价口径，驱动阈值分流；对 SALES 可见）
    currency = Column(String(3), default="USD")
    draft_po_id = Column(Integer, ForeignKey("purchase_order.id"), nullable=True)  # 关联 PO（草稿，先做单给会审看）
    consumed_quantity = Column(Numeric(12, 2), default=0)  # 已消数量（SO 成交累加，段3 派生；≤备货数量）
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    material = relationship("Material")

    __table_args__ = (UniqueConstraint("company_id", "request_number", name="ux_stock_up_request_number"),)


class StockUpConsumption(AuditMixin, Base):
    """备货消单流水（段3b）：SO 成交累加 STOCK_UP_REQUEST.consumed_quantity 的明细留痕 + 幂等锚。

    一行 = 一次「某 SO 明细消某备货单 N 件」。(stock_up_request_id, sales_order_line_id) 唯一，
    使 consume_on_sales_order EXPLICIT effect 多次触发不重复累加（幂等守卫读本表）。
    """
    __tablename__ = "stock_up_consumption"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    stock_up_request_id = Column(Integer, ForeignKey("stock_up_request.id"), nullable=False)
    sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=False)
    sales_order_line_id = Column(Integer, ForeignKey("sales_order_line.id"), nullable=False)
    quantity = Column(Numeric(12, 2), nullable=False)
    __table_args__ = (
        UniqueConstraint("stock_up_request_id", "sales_order_line_id", name="ux_stockup_consumption_so_line"),
    )


class SampleSdn(AuditMixin, Base):
    """样品 SDN 头（04b-3，权威=SDN Record.xlsx 31 列）：向原厂申请免费/收费样品，
    走其他入库进样品仓，跟回签/算超期/跟测试，测试通过转正可下正式单。

    引擎排除「样品」业务（引擎 02 §2.9）→ 全新增 doc_type + 子表 sample_sdn_line。流程：
      REQUESTED → VENDOR_SHIPPED → STOCKED_SAMPLE → SENT_TO_CUSTOMER → SIGNED → TESTING
      → CONVERTED（转正：该批库存 SAMPLE→AVAILABLE）/ RETURNED / CLOSED 终态。
    建单 START effect 取号 SDN-{C/L}-YYMM-NNN（供应商线字母由 supplier_line 列拼进，月度连号）。
    超期天数 overdue_days = 计算字段（前端/定时任务按 today−基准日，本段留只读列）。
    字段防火墙（§00-8）：target_price（目标价）对 SALES 遮蔽（query+schema 两路）。
    """
    __tablename__ = "sample_sdn"
    __doc_types__ = ("SAMPLE_SDN",)
    id = Column(Integer, primary_key=True)
    sdn_number = Column(String(40), index=True, nullable=False)  # SDN-{C/L}-YYMM-NNN
    supplier_line = Column(String(4), default="")   # 供应商线字母（C/L…），拼进 SDN 号
    sdn_date = Column(Date, nullable=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    pa_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 负责 PA（多 PA 实样含逗号串，本段单值＋备注兜底）
    pa_names = Column(String(120), default="")      # 多 PA 名（实样「边远,杨日红」逗号串，关联表留 gap-11）
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)  # 申请所用客户身份（PM 定）
    sales_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    sample_nature = Column(String(12), default="FREE")        # FREE 免费 / NOT_FREE 收费（访谈 07:1302）
    paid_disposition = Column(String(16), default="")         # 非免费处置：RETURN 归还 / RESELL 转销售 / RETURNED 已归还
    signed_return = Column(String(12), default="")            # 回签状态：Y / N / RETURNED 已归还 / NA
    application = Column(Text, default="")
    competitor = Column(Text, default="")
    demand = Column(Text, default="")
    target_price = Column(Numeric(16, 4), nullable=True)      # 目标价（成本侧，对 SALES 遮蔽，§00-8）
    tracking = Column(String(100), default="")
    project_status = Column(String(16), default="")          # 项目状态：IN_TEST 在测 / PASSED 通过 / FAILED 失败 / CONVERTED 转正
    pd_dept = Column(String(60), default="")                 # 产品线归属部门（如「光电材料部」）
    overdue_basis_date = Column(Date, nullable=True)         # 超期基准日（默认寄客户日，gap-5；overdue_days 据此前端/定时算）
    remark = Column(Text, default="")
    status = Column(String(30), default="REQUESTED")

    supplier = relationship("Supplier")
    customer = relationship("Customer")

    __table_args__ = (UniqueConstraint("company_id", "sdn_number", name="ux_sample_sdn_number"),)


class SampleSdnLine(Base):
    """样品 SDN 明细（一型号一行，权威=SDN Record P/N/Description/QTY/SN）。"""
    __tablename__ = "sample_sdn_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    sample_sdn_id = Column(Integer, ForeignKey("sample_sdn.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    description = Column(Text, default="")            # 质量描述（旧AR/Dummy样品/良品/机械样品）
    quantity = Column(Numeric(12, 2), nullable=False)
    serial_lot_number = Column(String(100), default="")
    __table_args__ = (UniqueConstraint("sample_sdn_id", "line_number"),)


class Rma(AuditMixin, Base):
    """RMA 退货统一单（04b-5，权威=RMA record.xlsx 24 列）：一张统一单共用一个 RMA 号，
    SA 看客户侧 / PA 看货物侧（决策⑨ 字段防火墙，同一单两视图）。

    引擎排除「退货」业务（引擎 02 §2.9）；采购侧 RMA ≠ WMS 客退 SALES_RETURN → 全新增
    doc_type + 子表 rma_line。流程（节点级 allowed_roles 分 SA/PA/PM 控权，规避 D-02e 边级坑）：
      REPORTED(SA) → PA_VERIFY(PA 核料) → ESCALATED_PM(PM 决策) → VENDOR_RMA / INTERNAL
      → GOODS_RETURNED(货回入库带 source_marker) → RETURN_TO_CUSTOMER(SA) → CLOSED ；REJECTED 终态。
    核料判定 effect（PA_VERIFY 推进）：sold_by_us 倒查 SN/LOT+PO+出库、under_warranty=ship_date+质保期 vs today；
    非我方卖/过保 → 建议 REJECTED（PA 确认，gap-7）。货回入库 effect（GOODS_RETURNED 推进）：生成退货入库
    inbound_type=RETURN + inventory.source_marker（RMA来源+品质+原厂），好货 status=AVAILABLE 混回可售（§5.4）。
    ★字段防火墙（决策⑨）：对 SA(SALES_ASSISTANT)+SALES 遮蔽采购侧列
    （supplier_id/po_number/unit_price/supplier_rma_number），对 PA/PM 给全列（tools.py query+schema 两路）。
    """
    __tablename__ = "rma"
    __doc_types__ = ("RMA",)
    id = Column(Integer, primary_key=True)
    rma_number = Column(String(40), index=True, nullable=False)  # RMA-YYMM-NNN（我方内部档案号）
    rma_date = Column(Date, nullable=True)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)   # ★PA 视图（对原厂）；对 SA 遮蔽
    failure_description = Column(Text, default="")           # 失效描述（客户报来）
    failure_location = Column(Text, default="")
    po_number = Column(String(50), default="")               # ★PA 视图（倒查是否我方卖）；对 SA 遮蔽
    ship_date = Column(Date, nullable=True)                  # 发货日期（判过保基准）
    invoice_number = Column(String(50), default="")
    supplier_rma_number = Column(String(50), default="")     # ★PA 视图（原厂 RMA 号回填）；对 SA 遮蔽
    tracking = Column(String(100), default="")
    remark = Column(Text, default="")
    sales_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    pa_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    pe_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    pm_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)     # 上报对象/决策人
    pd_dept = Column(String(60), default="")
    sold_by_us = Column(Boolean, nullable=True)              # 核料派生：是否我方卖（倒查 SN/LOT+PO+出库）
    under_warranty = Column(Boolean, nullable=True)          # 核料派生：是否在保（ship_date+质保期 vs today）
    pm_decision = Column(String(16), default="")             # PM 决策：VENDOR 报原厂 / INTERNAL 内部消化（换/退/修在 remark）
    return_customs_status = Column(String(20), default="")   # 退运/退关状态（关联 04 报关，180 天预警）
    status = Column(String(30), default="REPORTED")

    customer = relationship("Customer")
    supplier = relationship("Supplier")

    __table_args__ = (UniqueConstraint("company_id", "rma_number", name="ux_rma_number"),)


class RmaLine(Base):
    """RMA 明细（一 SN/型号一行，权威=RMA record P/N/SN/QTY/Failure）。"""
    __tablename__ = "rma_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    rma_id = Column(Integer, ForeignKey("rma.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    serial_lot_number = Column(String(100), default="")     # 核料倒查键
    quantity = Column(Numeric(12, 2), nullable=False)
    failure_description = Column(Text, default="")
    quality_result = Column(String(10), default="")         # 货回品质：GOOD 好 / BAD 坏（GOODS_RETURNED 录）
    __table_args__ = (UniqueConstraint("rma_id", "line_number"),)


class PurchaseInvoice(AuditMixin, Base):
    """采购发票：与外购入库单勾稽后形成采购核算（04a-7：PA 录→★FINANCE 审→形成应付）。"""
    __tablename__ = "purchase_invoice"
    __doc_types__ = ("PURCHASE_INVOICE",)
    id = Column(Integer, primary_key=True)
    invoice_number = Column(String(50), index=True, nullable=False)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_order.id"), nullable=True)
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipt.id"), nullable=True)
    amount = Column(Numeric(16, 2), nullable=False)
    currency = Column(String(3), default="CNY")
    tax_rate = Column(Numeric(5, 2), default=0)
    invoice_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)  # 04a-7：到期日（按付款条件推；货后付款据此发起）
    matched_at = Column(DateTime, nullable=True)
    # 04a-7 ★进项发票审核：财务核发票号/金额/与入库一致 → 形成应付（FINANCE 审核留痕）。
    reviewed_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    __table_args__ = (UniqueConstraint("company_id", "invoice_number"),)


class PurchaseInvoiceLine(Base):
    __tablename__ = "purchase_invoice_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    purchase_invoice_id = Column(Integer, ForeignKey("purchase_invoice.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    purchase_order_line_id = Column(Integer, ForeignKey("purchase_order_line.id"), nullable=True)
    goods_receipt_line_id = Column(Integer, ForeignKey("goods_receipt_line.id"), nullable=True)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    quantity = Column(Numeric(12, 2), nullable=False)
    unit_price = Column(Numeric(12, 4), nullable=False)
    total_price = Column(Numeric(16, 2), nullable=False)
    tax_rate = Column(Numeric(5, 2), default=0)
    __table_args__ = (UniqueConstraint("purchase_invoice_id", "line_number"),)


class SalesInvoice(AuditMixin, Base):
    """销售发票：与销售出库勾稽后形成收入和销售成本核算。"""
    __tablename__ = "sales_invoice"
    __doc_types__ = ("SALES_INVOICE",)
    id = Column(Integer, primary_key=True)
    invoice_number = Column(String(50), index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=True)
    shipment_id = Column(Integer, ForeignKey("shipment_request.id"), nullable=True)
    amount = Column(Numeric(16, 2), nullable=False)
    currency = Column(String(3), default="CNY")
    tax_rate = Column(Numeric(5, 2), default=0)
    invoice_date = Column(Date, nullable=True)
    matched_at = Column(DateTime, nullable=True)
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    __table_args__ = (UniqueConstraint("company_id", "invoice_number"),)


class SalesInvoiceLine(Base):
    __tablename__ = "sales_invoice_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    sales_invoice_id = Column(Integer, ForeignKey("sales_invoice.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    sales_order_line_id = Column(Integer, ForeignKey("sales_order_line.id"), nullable=True)
    shipment_line_id = Column(Integer, ForeignKey("shipment_line.id"), nullable=True)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    quantity = Column(Numeric(12, 2), nullable=False)
    unit_price = Column(Numeric(12, 4), nullable=False)
    total_price = Column(Numeric(16, 2), nullable=False)
    tax_rate = Column(Numeric(5, 2), default=0)
    cost_amount = Column(Numeric(16, 2), default=0)
    __table_args__ = (UniqueConstraint("sales_invoice_id", "line_number"),)


class InventoryValuation(AuditMixin, Base):
    __tablename__ = "inventory_valuation"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    cost_method = Column(String(15), default="WEIGHTED_AVG")
    current_unit_cost = Column(Numeric(16, 4), default=0)
    total_quantity = Column(Numeric(16, 2), default=0)
    total_value = Column(Numeric(16, 2), default=0)
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("company_id", "material_id"),)


class InventoryTransaction(Base):
    __tablename__ = "inventory_transaction"
    __doc_types__ = ("INVENTORY_COSTING",)
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"))
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"))
    transaction_type = Column(String(20))
    transaction_date = Column(Date, index=True)
    quantity = Column(Numeric(16, 2))
    unit_cost = Column(Numeric(16, 4))
    total_cost = Column(Numeric(16, 2))
    reference_type = Column(String(30), default="")
    reference_id = Column(BigInteger, nullable=True)
    voucher_id = Column(Integer, ForeignKey("voucher.id"), nullable=True)
    period_id = Column(Integer, ForeignKey("accounting_period.id"), nullable=False)
    status = Column(String(15), default="START", index=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (Index("ix_inv_txn_material_date", "company_id", "material_id", "transaction_date"),)


class CommandLog(Base):
    """统一命令执行日志：所有跨模块写操作先落这里。"""
    __tablename__ = "command_log"
    id = Column(Integer, primary_key=True)
    command_name = Column(String(80), nullable=False, index=True)
    idempotency_key = Column(String(160), nullable=True)
    actor_id = Column(Integer, ForeignKey("user_account.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=True, index=True)
    status = Column(String(20), default="RUNNING", index=True)
    request_payload = Column(JSONB, default=dict)
    result_payload = Column(JSONB, default=dict)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now(), index=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "ux_command_log_name_key_active",
            "command_name",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL AND status IN ('RUNNING', 'SUCCESS')"),
        ),
        Index("ix_command_log_name_created", "command_name", "created_at"),
    )


class InventoryMovement(Base):
    """库存事实流水：记录库存/预留变化，inventory 当前值只是投影。"""
    __tablename__ = "inventory_movement"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False, index=True)
    command_log_id = Column(Integer, ForeignKey("command_log.id"), nullable=True, index=True)
    movement_type = Column(String(30), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"), nullable=True, index=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=True, index=True)
    quantity_delta = Column(Numeric(16, 2), default=0)
    reserved_delta = Column(Numeric(16, 2), default=0)
    unit_cost = Column(Numeric(16, 4), default=0)
    source_doc_type = Column(String(30), default="", index=True)
    source_doc_id = Column(BigInteger, nullable=True, index=True)
    notes = Column(Text, default="")
    created_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_inventory_movement_material_created", "company_id", "material_id", "created_at"),
        Index("ix_inventory_movement_source", "source_doc_type", "source_doc_id"),
    )


# ============================================================
# CRM
# ============================================================

class Project(AuditMixin, Base):
    __tablename__ = "project"
    __doc_types__ = ("PROJECT",)
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id"))
    name = Column(String(200))
    stage = Column(String(20), default="PROSPECTING")
    product_engineer_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    sales_engineer_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    description = Column(Text, default="")
    expected_annual_revenue = Column(Numeric(16, 2), nullable=True)
    currency = Column(String(3), default="USD")
    expected_mass_production_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)

    customer = relationship("Customer")


class ProjectMaterial(Base):
    __tablename__ = "project_material"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("project.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    stage = Column(String(20), default="PROSPECTING")
    quantity_estimate = Column(Numeric(12, 2), nullable=True)
    notes = Column(Text, default="")
    __table_args__ = (UniqueConstraint("project_id", "material_id"),)


class ProjectActivity(Base):
    __tablename__ = "project_activity"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("project.id"), nullable=False)
    activity_type = Column(String(15), nullable=False)
    date = Column(Date, nullable=False)
    description = Column(Text, nullable=False)
    created_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


# ============================================================
# 第二层：流程定义
# ============================================================

class WorkflowDefinition(Base):
    """
    第二层：流程定义（极简：一张表，一个 JSONB）

    states 是流程的全部内容，每个 state（节点）含：
      - code: 状态码（status 字段的值）
      - name: 中文名
      - is_initial / is_terminal: 起始/终止节点
      - allowed_roles: 谁能在这一步操作
      - editable_fields: 这一步能改哪些字段（同时也是创建时能填的字段）
      - description: 给 Agent 看的中文描述（业务规则的主战场）
      - agent_tools: Agent 在这步能用的工具
      - custom_html: 可选自定义页面 HTML
      - hard_rules: 可选硬规则（暂留字段，未实现执行器）
      - next: [{to: "下个状态码", label: "动作名"}, ...] —— 状态可推进到哪些下一状态
    """
    __tablename__ = "workflow_definition"
    id = Column(Integer, primary_key=True)
    doc_type = Column(String(30), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    version = Column(Integer, default=1)
    description = Column(Text, default="")  # 流程总描述
    states = Column(JSONB, default=[])
    node_positions = Column(JSONB, default={})  # {"DRAFT":{"x":100,"y":50},...} 管理员拖拽保存
    group_name = Column(String(50), default="", index=True)  # 分组（财务/业务/仓储等）
    is_published = Column(Boolean, default=False)  # 已上线（一旦 True 永久 True，内容锁定）
    is_active = Column(Boolean, default=True)  # 对用户可见、可发起；可来回切（停用/启用）
    is_frozen = Column(Boolean, default=False)  # 旧字段（保留兼容，未使用）
    created_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("doc_type", "version"),)


class WorkflowLog(Base):
    """第五层：操作日志（只增不改）"""
    __tablename__ = "workflow_log"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    doc_type = Column(String(30), nullable=False, index=True)
    doc_id = Column(BigInteger, nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False)
    workflow_version = Column(Integer, nullable=False)
    transition_name = Column(String(100), nullable=False)
    from_state = Column(String(30), nullable=False)
    to_state = Column(String(30), nullable=False)
    triggered_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=False)
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    changed_fields = Column(JSONB, default={})
    data_snapshot = Column(JSONB, default={})
    hooks_executed = Column(JSONB, default=[])
    comment = Column(Text, default="")
    ip_address = Column(String(45), nullable=True)

    __table_args__ = (Index("ix_wflog_doc", "doc_type", "doc_id", "timestamp"),)


# ============================================================
# 知识库（通用条目）
# ============================================================

class KnowledgeEntry(Base):
    """
    第三层：知识库 — 跨流程的业务规则和提醒

    entry_type:
      SYSTEM_PROMPT  — Agent的公司/角色背景
      RULE           — 跨流程业务规则（如信用额度、FIFO）
      ALERT          — 预警规则
      GUIDE / FAQ    — 使用指南

    节点描述不再放这里 —— 直接写在 WorkflowDefinition.states[i].description
    """
    __tablename__ = "knowledge_entry"
    id = Column(Integer, primary_key=True)
    entry_type = Column(String(30), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    applicable_doc_types = Column(JSONB, default=[])
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ============================================================
# Agent日志（AgentDefinition已删除，用户Agent的提示词在KnowledgeEntry里）
# ============================================================

class AgentLog(Base):
    __tablename__ = "agent_log"
    id = Column(Integer, primary_key=True)
    agent_type = Column(String(20), nullable=False)  # USER / NODE
    user_id = Column(Integer, ForeignKey("user_account.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=True)
    user_query = Column(Text, nullable=False)
    tools_called = Column(JSONB, default=[])
    response = Column(Text, default="")
    tokens_used = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    timestamp = Column(DateTime, server_default=func.now(), index=True)


class WorkflowDefAuditLog(Base):
    """流程定义的所有改动记录（管理员对流程的操作）"""
    __tablename__ = "workflow_def_audit"
    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey("workflow_definition.id"), nullable=False, index=True)
    change_type = Column(String(30), nullable=False)
    # create / delete / fork / publish / disable / enable / change_group / edit_states / save_positions
    summary = Column(Text, default="")  # 自动算的简短描述
    before_snapshot = Column(JSONB, default=None, nullable=True)
    after_snapshot = Column(JSONB, default=None, nullable=True)
    danger_mode = Column(Boolean, default=False)  # 危险修改模式
    changed_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=False)
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    ip_address = Column(String(45), nullable=True)
    comment = Column(Text, default="")


# ============================================================
# 段0b · 后端基础设施（编号规则 / 并行会签 / 金蝶 outbox / 通知 / 配置审计）
#
# 全部为 ➕extension（引擎当前无此能力）。均为 __queryable__ 台账/子表，
# 不挂 __doc_types__（无独立审批状态机，避免被 WorkflowDefinition 强配）。
# 引擎五条不破坏：唯一写入路径仍是 Command→Workflow→Domain，本段只加积木。
# ============================================================

class NumberingRule(Base):
    """编号规则引擎（总览 §7）：公司×单据类型×前缀×重置周期×当前序号。

    引擎原生 `*_number` 只给唯一前缀（_auto_fill_required_fields），不支持
    「月度重置 + 连号」。本表 + `allocate_document_number` 命令补这层业务编号规则。
    取号走 SELECT FOR UPDATE 行锁，原子自增 current_seq，跨期（月/年）自动重置。
    """
    __tablename__ = "numbering_rule"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False, index=True)
    doc_type = Column(String(40), nullable=False, index=True)  # PO / INBOUND / OUTBOUND / INVOICE / RMA / SAMPLE ...
    prefix = Column(String(20), nullable=False, default="")    # 抬头编码前缀（如 PO / PR / PD / I），可空
    reset_period = Column(String(10), nullable=False, default="MONTH")  # MONTH / YEAR / NEVER
    seq_padding = Column(Integer, nullable=False, default=3)    # 序号补零位数（PR2603-001 → 3）
    separator = Column(String(5), nullable=False, default="-")  # 前缀/周期/序号之间的分隔符
    period_format = Column(String(10), nullable=False, default="%y%m")  # 周期段格式（月=%y%m，年=%Y）
    current_period = Column(String(10), nullable=False, default="")  # 当前周期标识（如 2606），跨期则重置
    current_seq = Column(Integer, nullable=False, default=0)    # 当前已发到的序号
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, default="")
    created_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("company_id", "doc_type", name="ux_numbering_rule_company_doctype"),)


class CosignLine(Base):
    """并行会签子表（标准件，05 §3）：挂在任意要会签的单据上。

    提交进入会签态时按本关卡 required_roles 预生成 N 行待签；每个签票方往
    「自己那行」填 decision（同意/驳回）。集齐校验器（cosign_collect_validator）
    放行条件 = 所有行 decision='AGREE'；任一 'REJECT' → 打回。
    多关卡复用：用 (doc_type, doc_id) 定位单据，cosign_group 区分同一单上的多个会签关卡。
    """
    __tablename__ = "cosign_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False, index=True)
    doc_type = Column(String(40), nullable=False, index=True)  # 被会签单据的 doc_type（如 CUSTOMER / STOCK_REVIEW）
    doc_id = Column(BigInteger, nullable=False, index=True)     # 被会签单据 id
    cosign_group = Column(String(40), nullable=False, default="DEFAULT")  # 同一单多个会签关卡时区分
    required_role = Column(String(30), nullable=False)         # 应签角色（PA / FINANCE / BOSS ...）
    decision = Column(String(10), nullable=False, default="PENDING")  # PENDING / AGREE / REJECT
    signed_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    comment = Column(Text, default="")
    signed_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index("ix_cosign_line_doc", "doc_type", "doc_id", "cosign_group"),
        UniqueConstraint("doc_type", "doc_id", "cosign_group", "required_role", name="ux_cosign_line_one_per_role"),
    )


class KingdeeOutbox(Base):
    """金蝶云星空推送 outbox（07b 页面1）：每张到触发态的业务单写一行。

    业务单号=幂等键，绝不静默丢单、失败可重推。__queryable__（DataExplorer 台账），
    不挂 __doc_types__（推送任务非审批单，状态由命令驱动而非人工流转）。
    真实 HTTP（金蝶 OpenAPI Save→Submit→Audit）留 TODO 占位，开关默认 OFF/dry-run。
    """
    __tablename__ = "kingdee_outbox"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False, index=True)  # 金蝶组织（行级 _company_filter）
    doc_type = Column(String(40), nullable=False, index=True)        # 业务单据类型（PO / GOODS_RECEIPT / SHIPMENT ...）
    biz_no = Column(String(80), nullable=False, index=True)          # 业务单号 = 幂等键（= 命令 idempotency_key）
    business_doc_type = Column(String(40), default="")               # 源单反链 doc_type
    business_doc_id = Column(BigInteger, nullable=True)              # 源单反链 id
    trigger_state = Column(String(30), default="")                   # 触发态（源单 to_state）
    form_id = Column(String(40), default="")                         # 金蝶 formId（映射表带入，07b 页面2）
    request_url = Column(String(120), default="")                    # 金蝶请求 URL（/v2/<域>/<formId>/<操作>）
    kingdee_bill_no = Column(String(80), default="")                 # 金蝶单据号（成功后回填）
    status = Column(String(20), nullable=False, default="RUNNING", index=True)  # RUNNING / SUCCESS / FAILED
    payload = Column(JSONB, default=dict)                            # 推送请求体快照
    receipt = Column(JSONB, default=dict)                            # 金蝶返回原文 / 错误码
    error_message = Column(Text, default="")
    command_log_id = Column(Integer, ForeignKey("command_log.id"), nullable=True, index=True)  # 接线 retry
    retried_from_id = Column(Integer, ForeignKey("kingdee_outbox.id"), nullable=True)  # 重推来源行
    retry_count = Column(Integer, nullable=False, default=0)
    created_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    completed_at = Column(DateTime, nullable=True)
    __table_args__ = (
        Index("ix_kingdee_outbox_company_status", "company_id", "status"),
        Index("ix_kingdee_outbox_biz", "doc_type", "biz_no"),
    )


class Notification(Base):
    """通知子系统（总览 §2「通知中心」）：到期/超额/退运180/签收超期/盘点提醒等。

    态推进 effect 派发 + 定时扫描骨架生成。__queryable__（站内未读台账）。
    引擎无 cron → scan 留可调度入口（手动触发或外部调度调命令）。邮件适配器占位。
    """
    __tablename__ = "notification"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False, index=True)
    recipient_id = Column(Integer, ForeignKey("user_account.id"), nullable=True, index=True)  # 收件人（空=按角色广播）
    recipient_role = Column(String(30), default="", index=True)  # 角色广播（recipient_id 为空时用）
    category = Column(String(40), nullable=False, index=True)  # DUE / OVER_LIMIT / RETURN_180 / SIGN_OVERDUE / COUNT / PUSH_FAILED ...
    title = Column(String(200), nullable=False, default="")
    body = Column(Text, default="")
    severity = Column(String(10), nullable=False, default="INFO")  # INFO / WARN / CRITICAL
    source_doc_type = Column(String(40), default="", index=True)  # 来源单据反链
    source_doc_id = Column(BigInteger, nullable=True)
    dedup_key = Column(String(160), nullable=True, index=True)  # 幂等去重键（定时扫描防重复生成）
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    email_status = Column(String(20), nullable=False, default="NONE")  # NONE / QUEUED / SENT / FAILED（邮件适配器占位）
    created_at = Column(DateTime, server_default=func.now(), index=True)
    __table_args__ = (
        Index("ix_notification_recipient_unread", "recipient_id", "is_read"),
        UniqueConstraint("dedup_key", name="ux_notification_dedup"),
    )


class ConfigAudit(Base):
    """配置变更独立审计表（EXT-01-E 已定技术方案=新建独立审计表）。

    用户/角色/授权/字段防火墙配置 CRUD 写本表（不动 WorkflowDefAuditLog，那张专管流程定义）。
    含变更类型/对象/前后快照/操作者/IP/时间（技术文档 07 FR-7.5：配置变更须含前后快照）。
    """
    __tablename__ = "config_audit"
    id = Column(Integer, primary_key=True)
    object_type = Column(String(40), nullable=False, index=True)  # USER / ROLE / USER_COMPANY_ACCESS / FIELD_FIREWALL ...
    object_id = Column(String(60), nullable=True, index=True)     # 目标对象主键（字符串容纳复合键）
    change_type = Column(String(30), nullable=False)              # create / update / delete / grant / revoke / disable / enable
    summary = Column(Text, default="")
    before_snapshot = Column(JSONB, default=None, nullable=True)
    after_snapshot = Column(JSONB, default=None, nullable=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=True, index=True)
    changed_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    comment = Column(Text, default="")
    timestamp = Column(DateTime, server_default=func.now(), index=True)


# ============================================================
# 段0b · 主数据扩充（PRD 02 主数据）
#
# 8 类主数据：客户·联系人·供应商·产品型号·产品代码·产线·库位·HS·计量单位。
# 沿用引擎现有模型（Customer/Supplier/Material=型号/WarehouseLocation=库位），
# 缺的实体新建为 __queryable__ 纯字典/子表（标准引擎用法 ✅），不挂 __doc_types__
# （主数据默认纯字典 + 留痕，不设财务关卡；客户/产品如需建档审核可后续注册轻量态机）。
# 引擎五条不破坏：本段只 append 模型 + alembic 加列/加表，不动唯一写入路径。
#
# 已有列扩展（在上方 Customer / Supplier / Material / WarehouseLocation 类内 append）：
#   Customer  += region/business_unit/grade/default_payment_term/credit_limit/
#                customer_vendor_code/owner_sales_id/qualified_code/label_template_ref
#   Supplier  += supplier_type/payment_term/responsible_pa_id/backup_pa_id/region
#   Material  += control_mode/uom_id/min_pack_qty/pack_qty_variable/hs_code_origin_id/
#                hs_code_cn_id/eccn/country_of_origin/moq/mpq/warranty_months/has_battery/
#                date_code_rule/pcn_flag/product_line_id/status（型号=Material，新增不破旧）
#   WarehouseLocation += location_type/capacity（zone/shelf/position 已是货区/货架/货层三级）
# ============================================================

class CustomerContactLine(Base):
    """客户联系人子表（PRD 02 页面1 子表 customer_contact_line）。

    挂在客户上的多行联系人，DocEditor 里 SubTableEditor 网格录入。__queryable__ 子表。
    relation_level=A信任/B亲切/C熟悉/D初识（蓝图 §3.1 关系等级）。
    email 是 RMA/入库邮件搜索的锚点（访谈 08:700）。
    """
    __tablename__ = "customer_contact_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=False, index=True)
    line_number = Column(SmallInteger, nullable=False, default=1)
    department = Column(String(100), default="")
    title = Column(String(100), default="")
    name = Column(String(100), nullable=False)  # 显示名
    phone = Column(String(30), default="")
    email = Column(String(120), default="")
    relation_level = Column(String(2), default="")  # A / B / C / D
    background = Column(Text, default="")
    __table_args__ = (UniqueConstraint("customer_id", "line_number"),)


class ProductLine(AuditMixin, Base):
    """产线（PRD 02 页面5 product_line）：1 产线 = 1 供应商。

    绑定负责 PM / FAE / PA，是 KPI「产线×工程师」维度与 PA/PM/FAE「本产线」行作用域的锚点。
    「1 线=1 供应商」唯一约束（PRD ➕extension）落 DB UniqueConstraint(company_id, supplier_id)，
    引擎不原生强制业务唯一性 → 用 DB 约束兜底（不破坏引擎，纯主数据无态机）。
    """
    __tablename__ = "product_line"
    # 段0c：产线需可建档（PM 维护），挂轻量单状态机 PRODUCT_LINE（ACTIVE）。
    __doc_types__ = ("PRODUCT_LINE",)
    id = Column(Integer, primary_key=True)
    code = Column(String(30), index=True, default="")
    line_name = Column(String(100), nullable=False)  # 显示名 name
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=False, index=True)
    pm_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)   # 负责 PM（KPI 维度）
    fae_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 负责工程师
    pa_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)   # 负责 PA（与供应商-PA 映射一致）
    status = Column(String(15), default="ACTIVE")
    is_active = Column(Boolean, default=True)
    notes = Column(Text, default="")

    supplier = relationship("Supplier")
    __table_args__ = (
        UniqueConstraint("company_id", "supplier_id", name="ux_product_line_one_per_supplier"),
        UniqueConstraint("company_id", "line_name", name="ux_product_line_company_name"),
    )


class ProductCode(AuditMixin, Base):
    """产品代码（PRD 02 页面4 product_code）：型号 × 供应商 → 内部 code（一型号多 code）。

    解决「同一型号不同供应商」的内部区分，是 PO/入库/库存批次实际引用的最细粒度料号。
    复合唯一 (product_id, supplier_id) 走 DB 约束（公司内）。__queryable__ 纯主数据。
    内部 code 默认 PA 手编 + 唯一校验（GAP-4 待甲方确认是否系统生成）。
    """
    __tablename__ = "product_code"
    # 段0c：产品代码需可建档（PA 建型号×供应商内部 code），挂轻量单状态机 PRODUCT_CODE（ACTIVE）。
    __doc_types__ = ("PRODUCT_CODE",)
    id = Column(Integer, primary_key=True)
    internal_code = Column(String(60), nullable=False, index=True)  # 显示名 code
    product_id = Column(Integer, ForeignKey("material.id"), nullable=False, index=True)  # 型号=Material
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=False, index=True)
    vendor_pn = Column(String(100), default="")            # 原厂料号/原厂型号
    customer_material_no = Column(String(100), default="")  # 客户侧物料号（对账/标签匹配）
    status = Column(String(15), default="ACTIVE")
    notes = Column(Text, default="")

    supplier = relationship("Supplier")
    __table_args__ = (
        UniqueConstraint("company_id", "internal_code", name="ux_product_code_company_code"),
        UniqueConstraint("company_id", "product_id", "supplier_id", name="ux_product_code_product_supplier"),
    )


class HsCode(Base):
    """HS 编码字典（PRD 02 页面7 hs_code）：报关用，被型号 hs_code_origin/hs_code_cn 双码引用。

    默认全局字典（不带 company_id，6 公司共用同一 HS 库），按 region 区分原产码 vs 中国码。
    退税率/关税率为占位字段（GAP-8 报关模块为主）。__queryable__ 纯字典。
    """
    __tablename__ = "hs_code"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    hs_number = Column(String(30), nullable=False, index=True)  # 显示名 code（如 85414100）
    description_cn = Column(String(200), default="")           # 中文名（如「連接器」）
    description_en = Column(String(200), default="")           # 货品名称
    region = Column(String(10), nullable=False, default="ORIGIN")  # ORIGIN（原产国）/ CN（中国）
    tax_rebate_rate = Column(Numeric(6, 3), nullable=True)     # 退税率（占位）
    tariff_rate = Column(Numeric(6, 3), nullable=True)         # 关税率（占位）
    is_active = Column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("hs_number", "region", name="ux_hs_code_number_region"),)


class UnitOfMeasure(Base):
    """计量单位字典（PRD 02 页面8 unit_of_measure）：包/盘/PCS，被型号 uom 引用。

    决定库存最小存储单位。芯片=包/盘、器件=PCS。默认全局字典（不带 company_id）。
    每包实际数量可变 → 实际数量在库存批次行（蓝图 §5.3），本页只定单位类型与默认换算。
    """
    __tablename__ = "unit_of_measure"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    uom_code = Column(String(20), nullable=False, unique=True, index=True)  # 显示名 code（PCS/包/盘/K）
    uom_name = Column(String(50), nullable=False)
    is_package_unit = Column(Boolean, default=False)  # 包/盘 vs 计件 PCS
    pcs_per_unit = Column(Numeric(16, 4), nullable=True)  # 换算（如 200K=200000，显示倍率）
    is_active = Column(Boolean, default=True)


# ============================================================
# 段3a · CRM 前段（线索 → 商机 → 报价，PRD 05-客户销售-CRM前段）
# 线索/商机是售前漏斗一/二级，纯前段（不推金蝶）；报价（QUOTATION）已有，本段对齐扩。
# ============================================================

class Lead(AuditMixin, Base):
    """线索（PRD 05 页面3 lead）：售前漏斗第一级。

    承接「飞书群分派」现状：网络/电话咨询 → 线索登记 → 销售经理分派 → 销售+FAE 跟进 →
    转商机 / 关闭丢失。客户可空（询价先于建档，访谈 09:172-196）。
    «转商机» EXPLICIT effect 派生 opportunity 草稿并回填客户/产线/干系人（crm.create_opportunity_from_lead）。
    纯前段不推金蝶。lead_number 月度连号 LD-YYMM-NNN（numbering effect）。
    """
    __tablename__ = "lead"
    __doc_types__ = ("LEAD",)
    id = Column(Integer, primary_key=True)
    lead_number = Column(String(30), index=True, nullable=False)
    source = Column(String(20), default="BAIDU")        # 百度/电话/网询/展会/转介
    content = Column(Text, default="")                  # 内容（允许一句话，容笼统需求）
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)  # 可空（询价先于建档）
    customer_name_raw = Column(String(120), default="")  # 未建档时的原始客户名（「北京客户」）
    product_line_id = Column(Integer, ForeignKey("product_line.id"), nullable=True)  # 初判所属产线
    assigned_sales_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 分派目标销售
    assigned_fae_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)    # 配合的产品工程师(FAE=SE)
    region = Column(String(20), default="")             # 华北/华南等
    next_step = Column(String(200), default="")         # 下一步（与跟进记录呼应）
    close_reason = Column(String(200), default="")      # 关闭丢失原因
    status = Column(String(30), default="DRAFT")
    notes = Column(Text, default="")

    customer = relationship("Customer")
    __table_args__ = (UniqueConstraint("company_id", "lead_number"),)


class Opportunity(AuditMixin, Base):
    """商机/项目（PRD 05 页面4 opportunity）：售前漏斗第二级，核心阶段状态机。

    阶段=状态机：前期沟通→送样→小批量→批量→关闭赢/关闭丢/无进展（可回退前期沟通）。
    科研 vs 光通信分流（business_unit 驱动）：科研推进阶段时 research_sub_market 必填（hard_rule）。
    干系人=销售(owner_sales_id)+FAE(fae_id)。跟进记录子表 opportunity_followup_line。
    纯前段不推金蝶。opportunity_number 月度连号 OPP-YYMM-NNN。
    """
    __tablename__ = "opportunity"
    __doc_types__ = ("OPPORTUNITY",)
    id = Column(Integer, primary_key=True)
    opportunity_number = Column(String(30), index=True, nullable=False)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=True)  # 来源线索（转商机派生回填）
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)  # 推进到送样后必填（hard_rule）
    product_line_id = Column(Integer, ForeignKey("product_line.id"), nullable=True)  # 原厂=产线=供应商
    project_name = Column(String(200), default="")      # 项目名称
    product_model = Column(String(120), default="")     # 产品型号（科研早期可无型号，允许手填占位）
    business_unit = Column(String(40), default="")      # 事业部（光通信/科研SIO）——驱动分流
    research_sub_market = Column(String(60), default="")  # 科研细分市场（科研推进时必填，hard_rule）
    grade = Column(String(20), default="")              # 项目等级
    owner_sales_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 干系人-销售
    fae_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)          # 干系人-FAE(SE)
    expected_amount = Column(Numeric(16, 2), nullable=True)  # 预期金额
    expected_close_date = Column(Date, nullable=True)        # 预期成交日
    stage = Column(String(30), default="EARLY")         # 冗余阶段镜像（status 为权威，前端展示用）
    next_step = Column(String(200), default="")         # 下一步计划
    close_reason = Column(String(200), default="")      # 关闭丢失原因
    status = Column(String(30), default="DRAFT")
    remark = Column(Text, default="")

    customer = relationship("Customer")
    __table_args__ = (UniqueConstraint("company_id", "opportunity_number"),)


class OpportunityFollowupLine(Base):
    """商机跟进记录子表（PRD 05 页面5 opportunity_followup_line）：网格追加。

    名含 `_line` + 指向 opportunity 的 FK → 引擎自动识别为子表，DocEditor 渲 SubTableEditor 网格。
    对应销售周报模板「按周更新」列群（日期/类型/联系人/内容/下一步/负责人）。
    """
    __tablename__ = "opportunity_followup_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunity.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    activity_date = Column(Date, nullable=True)         # 日期
    activity_type = Column(String(20), default="")      # 电话/邮件/拜访/送样/报价/其他
    contact_id = Column(Integer, ForeignKey("customer_contact_line.id"), nullable=True)  # 联系人（限本客户）
    content = Column(Text, default="")                  # 内容（周报周更正文）
    next_step = Column(String(200), default="")         # 下一步（可回写商机 next_step）
    owner_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 负责人
    __table_args__ = (UniqueConstraint("opportunity_id", "line_number"),)


# ============================================================
# 段3c 客户/销售收尾（PRD 05）：客户认证（薄+并行会签复用）/ 售后技术工单 /
# Forecast 接单（占位薄）/ 特批发货（可隐藏模块）+ 功能开关 FeatureFlag。
# 引擎排除「退货/售后」类业务（引擎 02 §2.9）→ 全新增 doc_type + 子表 + WorkflowDefinition。
# 会签复用 services/cosign 标准件（CosignLine 子表 + register_cosign_checkpoint），不另造。
# ============================================================

class CustomerQualification(AuditMixin, Base):
    """客户认证单（薄版，PRD 05-客户认证与会签 页面1）：大客户准入审核，
    系统只管认证状态 + 资料清单勾选 + 协议风险审查项留痕 + 附件，不写协议正文。

    ★审核 = 并行会签（复用 services/cosign 标准件，cosign_group=CERTIFICATION）：
      DRAFT 备资料/填风险审查 → UNDER_COSIGN（进态 auto effect 预生成 PA+FINANCE+BOSS 三行待签）
      → 各方往自己 cosign_line 行 sign（self-loop 编辑）→ 集齐三方 AGREE 才 APPROVED（cosign 校验器把关），
      任一 REJECT → REJECTED（打回整改可重提）→ EXPIRED（到期失效重认）。
    APPROVED auto effect 回写 customer.qualified_code（已认证供应商码）。
    认证单号 QUAL-YYMM-NNN 月度连号（NumberingRule + 建单取号 effect）。本单不推金蝶（内部准入单）。
    """
    __tablename__ = "customer_qualification"
    __doc_types__ = ("CUSTOMER_QUALIFICATION",)
    id = Column(Integer, primary_key=True)
    qualification_number = Column(String(30), index=True, nullable=False)  # QUAL-YYMM-NNN
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    qualification_type = Column(String(30), default="NEW_SUPPLIER")  # 新供应商认证/年度复审/体系认证
    valid_until = Column(Date, nullable=True)            # 有效期至（通过时写）
    qualified_code = Column(String(50), default="")      # 客户给的已认证供应商码（通过回写 customer.qualified_code）
    risk_summary = Column(Text, default="")              # 风险审查总评（违约/索赔/质保期冲突摘要）
    notes = Column(Text, default="")
    status = Column(String(30), default="DRAFT")

    customer = relationship("Customer")

    __table_args__ = (UniqueConstraint("company_id", "qualification_number", name="ux_customer_qualification_number"),)


class QualificationDocLine(Base):
    """认证资料清单子表（PRD 05 §2.3 qualification_doc_line）：营业执照/质量体系/产品资料/银行信息…，
    标「必备」的项须齐才能提交（提交 hard_rule）。名含 `_line` → 前端 SubTableEditor 网格。"""
    __tablename__ = "qualification_doc_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    qualification_id = Column(Integer, ForeignKey("customer_qualification.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    doc_item = Column(String(60), default="")            # 资料项（营业执照/质量体系/产品资料/银行信息…）
    is_required = Column(Boolean, default=True)          # 是否必备（必备项须齐）
    is_ready = Column(Boolean, default=False)            # 是否齐备
    attachment_ref = Column(Text, default="")            # 附件引用（占位，附件域跨模块共用）
    __table_args__ = (UniqueConstraint("qualification_id", "line_number"),)


class QualificationRiskLine(Base):
    """协议风险审查项子表（PRD 05 §2.3 qualification_risk_line）：违约金/索赔/质保期冲突/其他，
    三项均须判（有/无+说明）才能提交（提交 hard_rule）。"""
    __tablename__ = "qualification_risk_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    qualification_id = Column(Integer, ForeignKey("customer_qualification.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    risk_type = Column(String(20), default="")           # 违约金/索赔/质保期冲突/其他
    presence = Column(String(10), default="PENDING")     # PRESENT 有 / ABSENT 无 / PENDING 待定
    note = Column(Text, default="")                      # 说明（「有」时建议填）
    __table_args__ = (UniqueConstraint("qualification_id", "line_number"),)


class ServiceTicket(AuditMixin, Base):
    """售后技术工单（薄，PRD 05-售后技术工单 05c-2）：客户报技术问题/质量故障 → FAE 处理 → 关闭。

    引擎排除「售后」业务（引擎 02 §2.9）→ 全新增 doc_type + 可选子表 service_ticket_line。
    轻量四态主干 + RMA 升级旁路（节点级 allowed_roles 分 SALES/SA/FAE/PM/PA 控权，规避 D-02e 边级坑）：
      OPEN（提报）→ IN_PROGRESS（FAE 处理：答疑/判定/维修建议）→ RESOLVED（已解决）→ CLOSED；
      旁路 ESCALATED_RMA（需实物退换报原厂→关联 04b RMA，rma_id 回链）→ 回 RESOLVED；
      OPEN→CLOSED 直关（无效/误报）；RESOLVED→IN_PROGRESS 重开（客户反馈未解决）。
    工单号 ST-YYMM-NNN 月度连号。本单不推金蝶（内部技术服务单，无财务关卡）。
    """
    __tablename__ = "service_ticket"
    __doc_types__ = ("SERVICE_TICKET",)
    id = Column(Integer, primary_key=True)
    ticket_number = Column(String(30), index=True, nullable=False)  # ST-YYMM-NNN
    reported_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 提报人（创建态自动置）
    report_channel = Column(String(20), default="PHONE")  # 电话/邮件/微信/客户系统/其他
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=True)  # 故障型号（单型号；多型号走子表）
    serial_lot_number = Column(String(100), default="")  # SN/LOT（倒查发货/批次，扫码兜底手填可 NA）
    sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=True)  # 关联 SO（哪一单售出，可选）
    issue_type = Column(String(20), default="QUALITY")   # 答疑咨询/质量故障/使用指导/其他
    issue_summary = Column(Text, default="")             # 失效现象/问题描述（客户报来）
    usage_context = Column(Text, default="")             # 使用场景/失效位置（辅助 FAE 判定）
    urgency = Column(String(10), default="MEDIUM")       # 高/中/低（轻量优先级，非 SLA 硬卡）
    assignee_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 负责 FAE（指派/流转）
    product_line = Column(String(40), default="")        # 产线/事业部（数据范围 + 统计维度）
    resolution_type = Column(String(20), default="")     # 远程答疑/国内维修/寄原厂维修/报原厂换退/内部消化
    resolution_notes = Column(Text, default="")          # 处理过程/答疑内容（RESOLVED 前必填）
    quality_verdict = Column(String(12), default="PENDING")  # 良品/不良/待判定/NA（与 04b RMA 好坏标记同源）
    repair_advice = Column(Text, default="")             # 维修建议（国内修/寄原厂修）
    rma_id = Column(Integer, ForeignKey("rma.id"), nullable=True)  # 关联 RMA（转实物退换时，04b）
    closure_note = Column(Text, default="")              # 关闭结论（CLOSED 前必填）
    status = Column(String(30), default="OPEN")

    customer = relationship("Customer")
    material = relationship("Material")

    __table_args__ = (UniqueConstraint("company_id", "ticket_number", name="ux_service_ticket_number"),)


class ServiceTicketLine(Base):
    """售后工单可选明细子表（PRD 05 05c-2 service_ticket_line）：一型号/一 SN 一行，多型号时启用。"""
    __tablename__ = "service_ticket_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    service_ticket_id = Column(Integer, ForeignKey("service_ticket.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=False)
    serial_lot_number = Column(String(100), default="")  # 多 SN 多行（扫码兜底）
    quantity = Column(Numeric(12, 2), nullable=True)
    line_issue = Column(Text, default="")                # 单项失效现象
    line_verdict = Column(String(12), default="PENDING")  # 单项质量判定 良品/不良/待判定
    __table_args__ = (UniqueConstraint("service_ticket_id", "line_number"),)


class CustomerForecast(AuditMixin, Base):
    """客户 Forecast 滚动预测单（占位薄版，PRD 05-Forecast接单 05d-2）：把客户系统里的滚动预测
    抄录留痕，可联动备货/SO。范围待定 → 薄实现（头 + 滚动月份子表网格），直连客户系统列后期 ➕。

    引擎无现成 Forecast 模型（引擎 08 §8.8）→ 新增轻量 doc_type + 子表 customer_forecast_line。
    薄流程：DRAFT（SA 录客户×型号×多月预测网格）→ CONFIRMED（确认存档，可起备货建议）→ SUPERSEDED（被新版滚动替代）。
    预测/接单无财务凭证含义 → 财务无关卡、不推金蝶。预测单号 FC-YYMM-NNN 月度连号。
    """
    __tablename__ = "customer_forecast"
    __doc_types__ = ("CUSTOMER_FORECAST",)
    id = Column(Integer, primary_key=True)
    forecast_number = Column(String(30), index=True, nullable=False)  # FC-YYMM-NNN
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    forecast_version = Column(String(40), default="")    # 滚动版本/期次（如「2026-06 滚动」）
    source_system = Column(String(60), default="")       # 客户系统名（烽火多系统/通用一套…，手录留痕）
    product_line = Column(String(40), default="")        # 产线（数据范围 + 统计维度）
    notes = Column(Text, default="")
    status = Column(String(30), default="DRAFT")

    customer = relationship("Customer")

    __table_args__ = (UniqueConstraint("company_id", "forecast_number", name="ux_customer_forecast_number"),)


class CustomerForecastLine(Base):
    """客户预测滚动月份子表（PRD 05 05d-2 customer_forecast_line）：客户×型号×月份×预测量网格。
    薄版：一行 = 一型号一月份的预测量（多月多行）。"""
    __tablename__ = "customer_forecast_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    customer_forecast_id = Column(Integer, ForeignKey("customer_forecast.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=True)
    forecast_month = Column(String(7), default="")       # 预测月份（YYYY-MM）
    forecast_qty = Column(Numeric(12, 2), nullable=True)  # 预测量
    note = Column(Text, default="")                      # 交叉应答 gap/动作（提拉/推迟/正常）备注
    __table_args__ = (UniqueConstraint("customer_forecast_id", "line_number"),)


class SpecialShipment(AuditMixin, Base):
    """特批发货单（先发后补单，可隐藏模块，PRD 05-订单与履约 页面4b，决策⑫）：客户未下单先经
    ★财务特批审出货 → 事后补录 SO 勾稽补推金蝶。是「发货必关联 SO」硬规则的唯一受控例外（独立 doc_type 隔离）。

    引擎排除此类例外业务 → 全新增 doc_type + 入仓编号明细子表 special_shipment_line。流程：
      DRAFT（SALES/SA 发起：客户+特批理由+风险承诺+预计补单期限+入仓编号明细，无 SO）→
      ★FINANCE_SPECIAL_APPROVAL（财务特批审：核风险/授信/资质）→ APPROVED（特批放行，通知 03b 出库）→
      SHIPPED_PENDING_SO（已发货·待补单，挂「待补单」债务，逾期升级）→
      RECONCILED（补录 SO 勾稽：回填 SO 号、抵减 SO 在途、补推金蝶销售源）→ CLOSED；CANCELLED 终态。
    feature_flag feature.special_batch_shipment 默认 OFF（前端按开关隐藏入口/创建权）。
    特批单号 SS-YYMM-NNN 月度连号。
    """
    __tablename__ = "special_shipment"
    __doc_types__ = ("SPECIAL_SHIPMENT",)
    id = Column(Integer, primary_key=True)
    shipment_number = Column(String(30), index=True, nullable=False)  # SS-YYMM-NNN
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    special_reason = Column(String(20), default="")      # 紧急订单/口头确认/战略客户/样机急发/其他
    special_reason_note = Column(Text, default="")       # 「其他」须填说明
    risk_commitment = Column(Text, default="")           # 风险承诺/授权人（替代邮件特批的责任人）
    authorized_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)  # 授权人
    expected_reorder_date = Column(Date, nullable=True)  # 预计补单期限（默认 +30 天，逾期升级催办）
    price_term = Column(String(10), default="")          # 贸易条件 CFR/FCA/EXW/CIF（补单后随 SO 对齐）
    reorder_sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=True)  # 关联补单 SO（补单时填，强制事后勾稽）
    special_approved = Column(Boolean, default=False)    # 特批放行标志（财务特批审置位）
    pending_so = Column(Boolean, default=False)          # 待补单标志（出库即置真、勾稽置假，债务可视化）
    notes = Column(Text, default="")
    status = Column(String(30), default="DRAFT")

    customer = relationship("Customer")

    __table_args__ = (UniqueConstraint("company_id", "shipment_number", name="ux_special_shipment_number"),)


class SpecialShipmentLine(Base):
    """特批发货入仓编号明细子表（PRD 05 页面4b special_shipment_line）：逐行指定要发的批次（串货隔离），
    勾稽时回填补单 SO 明细行、抵减补单 SO 在途。"""
    __tablename__ = "special_shipment_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    special_shipment_id = Column(Integer, ForeignKey("special_shipment.id"), nullable=False)
    line_number = Column(SmallInteger, nullable=False)
    material_id = Column(Integer, ForeignKey("material.id"), nullable=True)
    inbound_code = Column(String(100), default="")       # 入仓编号（批次，串货匹配键）
    serial_lot_number = Column(String(100), default="")  # SN/LOT
    quantity = Column(Numeric(12, 2), nullable=True)     # 发货数量（≤批次结存；勾稽时抵减补单 SO 在途）
    reconciled_so_line_id = Column(Integer, ForeignKey("sales_order_line.id"), nullable=True)  # 已勾稽到补单 SO 明细行（勾稽回填）
    __table_args__ = (UniqueConstraint("special_shipment_id", "line_number"),)


class FeatureFlag(Base):
    """功能开关（per-company，PRD 05 页面4b feature.special_batch_shipment）：引擎无原生「per-company
    功能开关隐藏 doc_type/导航」→ ➕扩展。一行 = 一个 (company_id, flag_key) 的开关。

    特批发货 feature.special_batch_shipment 默认 OFF（隐藏入口 + 隐藏 doc_type 创建权，历史只读可查）；
    关时前端按本表过滤，创建权由命令/effect 读本表受控。__queryable__（配置台账）。
    """
    __tablename__ = "feature_flag"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False, index=True)
    flag_key = Column(String(60), nullable=False, index=True)  # feature.special_batch_shipment ...
    is_enabled = Column(Boolean, nullable=False, default=False)  # 默认 OFF
    notes = Column(Text, default="")
    created_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("company_id", "flag_key", name="ux_feature_flag_company_key"),)
