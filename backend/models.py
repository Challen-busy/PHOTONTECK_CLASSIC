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
    created_at = Column(DateTime, server_default=func.now())

    company = relationship("Company")


class UserCompanyAccess(Base):
    """用户可访问的额外公司（老板/财务看多公司）"""
    __tablename__ = "user_company_access"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user_account.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False)
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
    zone = Column(String(20), default="")
    shelf = Column(String(20), default="")
    position = Column(String(20), default="")
    is_active = Column(Boolean, default=True)
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
