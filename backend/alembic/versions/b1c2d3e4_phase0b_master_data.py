"""phase0b master data: 8 master-data types (customer/contact/supplier/product/product_code/product_line/location/hs/uom)

Revision ID: b1c2d3e4
Revises: a0b1c2d3
Create Date: 2026-06-16

PRD 02 主数据。沿用引擎现有模型（Customer/Supplier/Material=型号/WarehouseLocation=库位）加列，
缺的实体新建为 __queryable__ 纯字典/子表。引擎五条不破坏：只加列/加表，不动唯一写入路径。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========== 新表：unit_of_measure（全局字典，无 company_id）==========
    op.create_table(
        "unit_of_measure",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uom_code", sa.String(length=20), nullable=False),
        sa.Column("uom_name", sa.String(length=50), nullable=False),
        sa.Column("is_package_unit", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("pcs_per_unit", sa.Numeric(16, 4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uom_code"),
    )
    op.create_index("ix_unit_of_measure_uom_code", "unit_of_measure", ["uom_code"])

    # ========== 新表：hs_code（全局字典，无 company_id）==========
    op.create_table(
        "hs_code",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hs_number", sa.String(length=30), nullable=False),
        sa.Column("description_cn", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("description_en", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("region", sa.String(length=10), nullable=False, server_default="ORIGIN"),
        sa.Column("tax_rebate_rate", sa.Numeric(6, 3), nullable=True),
        sa.Column("tariff_rate", sa.Numeric(6, 3), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hs_number", "region", name="ux_hs_code_number_region"),
    )
    op.create_index("ix_hs_code_hs_number", "hs_code", ["hs_number"])

    # ========== 新表：product_line（1 线=1 供应商 DB 唯一约束）==========
    op.create_table(
        "product_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=True, server_default=""),
        sa.Column("line_name", sa.String(length=100), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("pm_id", sa.Integer(), nullable=True),
        sa.Column("fae_id", sa.Integer(), nullable=True),
        sa.Column("pa_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=15), nullable=True, server_default="ACTIVE"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["supplier_id"], ["supplier.id"]),
        sa.ForeignKeyConstraint(["pm_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["fae_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["pa_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "supplier_id", name="ux_product_line_one_per_supplier"),
        sa.UniqueConstraint("company_id", "line_name", name="ux_product_line_company_name"),
    )
    op.create_index("ix_product_line_code", "product_line", ["code"])
    op.create_index("ix_product_line_supplier_id", "product_line", ["supplier_id"])
    op.create_index("ix_product_line_company_id", "product_line", ["company_id"])

    # ========== 新表：product_code（型号×供应商→code，复合唯一）==========
    op.create_table(
        "product_code",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("internal_code", sa.String(length=60), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("vendor_pn", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("customer_material_no", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("status", sa.String(length=15), nullable=True, server_default="ACTIVE"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["material.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["supplier.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "internal_code", name="ux_product_code_company_code"),
        sa.UniqueConstraint("company_id", "product_id", "supplier_id", name="ux_product_code_product_supplier"),
    )
    op.create_index("ix_product_code_internal_code", "product_code", ["internal_code"])
    op.create_index("ix_product_code_product_id", "product_code", ["product_id"])
    op.create_index("ix_product_code_supplier_id", "product_code", ["supplier_id"])
    op.create_index("ix_product_code_company_id", "product_code", ["company_id"])

    # ========== 新表：customer_contact_line（客户联系人子表）==========
    op.create_table(
        "customer_contact_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("department", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("title", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True, server_default=""),
        sa.Column("email", sa.String(length=120), nullable=True, server_default=""),
        sa.Column("relation_level", sa.String(length=2), nullable=True, server_default=""),
        sa.Column("background", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "line_number"),
    )
    op.create_index("ix_customer_contact_line_customer_id", "customer_contact_line", ["customer_id"])

    # ========== 加列：customer（PRD 02 页面1）==========
    op.add_column("customer", sa.Column("region", sa.String(length=10), nullable=True, server_default=""))
    op.add_column("customer", sa.Column("business_unit", sa.String(length=40), nullable=True, server_default=""))
    op.add_column("customer", sa.Column("grade", sa.String(length=20), nullable=True, server_default="SMALL"))
    op.add_column("customer", sa.Column("default_payment_term", sa.String(length=60), nullable=True, server_default=""))
    op.add_column("customer", sa.Column("credit_limit", sa.Numeric(16, 2), nullable=True))
    op.add_column("customer", sa.Column("customer_vendor_code", sa.String(length=50), nullable=True, server_default=""))
    op.add_column("customer", sa.Column("owner_sales_id", sa.Integer(), nullable=True))
    op.add_column("customer", sa.Column("qualified_code", sa.String(length=50), nullable=True, server_default=""))
    op.add_column("customer", sa.Column("label_template_ref", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_customer_owner_sales", "customer", "user_account", ["owner_sales_id"], ["id"])
    op.create_foreign_key("fk_customer_label_template", "customer", "label_template", ["label_template_ref"], ["id"])

    # ========== 加列：supplier（PRD 02 页面2）==========
    op.add_column("supplier", sa.Column("supplier_type", sa.String(length=10), nullable=True, server_default="OEM"))
    op.add_column("supplier", sa.Column("payment_term", sa.String(length=60), nullable=True, server_default=""))
    op.add_column("supplier", sa.Column("responsible_pa_id", sa.Integer(), nullable=True))
    op.add_column("supplier", sa.Column("backup_pa_id", sa.Integer(), nullable=True))
    op.add_column("supplier", sa.Column("region", sa.String(length=10), nullable=True, server_default=""))
    op.create_foreign_key("fk_supplier_responsible_pa", "supplier", "user_account", ["responsible_pa_id"], ["id"])
    op.create_foreign_key("fk_supplier_backup_pa", "supplier", "user_account", ["backup_pa_id"], ["id"])

    # ========== 加列：material=型号（PRD 02 页面3 ⭐）==========
    op.add_column("material", sa.Column("pn", sa.String(length=100), nullable=True, server_default=""))
    op.add_column("material", sa.Column("desc_cn", sa.String(length=300), nullable=True, server_default=""))
    op.add_column("material", sa.Column("desc_en", sa.String(length=300), nullable=True, server_default=""))
    op.add_column("material", sa.Column("product_name", sa.String(length=200), nullable=True, server_default=""))
    op.add_column("material", sa.Column("control_mode", sa.String(length=5), nullable=True, server_default="LOT"))
    op.add_column("material", sa.Column("uom_id", sa.Integer(), nullable=True))
    op.add_column("material", sa.Column("min_pack_qty", sa.Numeric(12, 2), nullable=True))
    op.add_column("material", sa.Column("pack_qty_variable", sa.Boolean(), nullable=True, server_default=sa.text("false")))
    op.add_column("material", sa.Column("hs_code_origin_id", sa.Integer(), nullable=True))
    op.add_column("material", sa.Column("hs_code_cn_id", sa.Integer(), nullable=True))
    op.add_column("material", sa.Column("eccn", sa.String(length=30), nullable=True, server_default=""))
    op.add_column("material", sa.Column("country_of_origin", sa.String(length=50), nullable=True, server_default=""))
    op.add_column("material", sa.Column("moq", sa.Numeric(12, 2), nullable=True))
    op.add_column("material", sa.Column("mpq", sa.Numeric(12, 2), nullable=True))
    op.add_column("material", sa.Column("warranty_months", sa.Integer(), nullable=True))
    op.add_column("material", sa.Column("has_battery", sa.Boolean(), nullable=True, server_default=sa.text("false")))
    op.add_column("material", sa.Column("date_code_rule", sa.String(length=100), nullable=True, server_default=""))
    op.add_column("material", sa.Column("pcn_flag", sa.Boolean(), nullable=True, server_default=sa.text("false")))
    op.add_column("material", sa.Column("product_line_id", sa.Integer(), nullable=True))
    op.add_column("material", sa.Column("status", sa.String(length=15), nullable=True, server_default="ACTIVE"))
    op.create_foreign_key("fk_material_uom", "material", "unit_of_measure", ["uom_id"], ["id"])
    op.create_foreign_key("fk_material_hs_origin", "material", "hs_code", ["hs_code_origin_id"], ["id"])
    op.create_foreign_key("fk_material_hs_cn", "material", "hs_code", ["hs_code_cn_id"], ["id"])
    op.create_foreign_key("fk_material_product_line", "material", "product_line", ["product_line_id"], ["id"])

    # ========== 加列：warehouse_location=库位（PRD 02 页面6）==========
    op.add_column("warehouse_location", sa.Column("location_type", sa.String(length=15), nullable=True, server_default="NORMAL"))
    op.add_column("warehouse_location", sa.Column("capacity", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("warehouse_location", "capacity")
    op.drop_column("warehouse_location", "location_type")

    op.drop_constraint("fk_material_product_line", "material", type_="foreignkey")
    op.drop_constraint("fk_material_hs_cn", "material", type_="foreignkey")
    op.drop_constraint("fk_material_hs_origin", "material", type_="foreignkey")
    op.drop_constraint("fk_material_uom", "material", type_="foreignkey")
    for col in [
        "status", "product_line_id", "pcn_flag", "date_code_rule", "has_battery",
        "warranty_months", "mpq", "moq", "country_of_origin", "eccn", "hs_code_cn_id",
        "hs_code_origin_id", "pack_qty_variable", "min_pack_qty", "uom_id",
        "control_mode", "product_name", "desc_en", "desc_cn", "pn",
    ]:
        op.drop_column("material", col)

    op.drop_constraint("fk_supplier_backup_pa", "supplier", type_="foreignkey")
    op.drop_constraint("fk_supplier_responsible_pa", "supplier", type_="foreignkey")
    for col in ["region", "backup_pa_id", "responsible_pa_id", "payment_term", "supplier_type"]:
        op.drop_column("supplier", col)

    op.drop_constraint("fk_customer_label_template", "customer", type_="foreignkey")
    op.drop_constraint("fk_customer_owner_sales", "customer", type_="foreignkey")
    for col in [
        "label_template_ref", "qualified_code", "owner_sales_id", "customer_vendor_code",
        "credit_limit", "default_payment_term", "grade", "business_unit", "region",
    ]:
        op.drop_column("customer", col)

    op.drop_table("customer_contact_line")
    op.drop_table("product_code")
    op.drop_table("product_line")
    op.drop_table("hs_code")
    op.drop_table("unit_of_measure")
