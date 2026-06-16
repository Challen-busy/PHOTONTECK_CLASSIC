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
    __queryable__ = True
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
    order_number = Column(String(30), unique=True, index=True, nullable=False)
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


# ============================================================
# 采购
# ============================================================

class PurchaseOrder(AuditMixin, Base):
    __tablename__ = "purchase_order"
    __doc_types__ = ("PURCHASE_ORDER",)
    id = Column(Integer, primary_key=True)
    order_number = Column(String(30), unique=True, index=True, nullable=False)
    po_date = Column(Date, nullable=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"))
    purchase_assistant_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    related_sales_order_id = Column(Integer, ForeignKey("sales_order.id"), nullable=True)
    purchase_notice_id = Column(Integer, ForeignKey("purchase_notice.id"), nullable=True)
    is_stock_order = Column(Boolean, default=False)
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
    __queryable__ = True
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
    status = Column(String(15), default="AVAILABLE")

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
    receipt_number = Column(String(30), unique=True, nullable=False)
    purchase_order_id = Column(Integer, ForeignKey("purchase_order.id"))
    warehouse_id = Column(Integer, ForeignKey("warehouse.id"))
    received_by_id = Column(Integer, ForeignKey("user_account.id"), nullable=True)
    received_date = Column(Date, nullable=True)
    status = Column(String(15), default="PENDING")
    notes = Column(Text, default="")


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipt.id"), nullable=False)
    purchase_order_line_id = Column(Integer, ForeignKey("purchase_order_line.id"), nullable=False)
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


class ShipmentRequest(AuditMixin, Base):
    __tablename__ = "shipment_request"
    __doc_types__ = ("SHIPMENT",)
    id = Column(Integer, primary_key=True)
    shipment_number = Column(String(30), unique=True, nullable=False)
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


class ShipmentLine(Base):
    __tablename__ = "shipment_line"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    shipment_id = Column(Integer, ForeignKey("shipment_request.id"), nullable=False)
    sales_order_line_id = Column(Integer, ForeignKey("sales_order_line.id"), nullable=False)
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


class LabelTemplate(Base):
    __tablename__ = "label_template"
    __queryable__ = True
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=False)
    name = Column(String(100), nullable=False)
    template_content = Column(Text, default="")
    fields_mapping = Column(JSONB, default={})
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


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


class PurchaseInvoice(AuditMixin, Base):
    """采购发票：与外购入库单勾稽后形成采购核算。"""
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
    matched_at = Column(DateTime, nullable=True)
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
    __queryable__ = True
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
    __queryable__ = True
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
