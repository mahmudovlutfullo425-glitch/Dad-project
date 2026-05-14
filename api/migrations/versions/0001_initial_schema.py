"""initial schema: users, products, inventory, flash sales, orders, payments, audit

Revision ID: 0001
Revises:
Create Date: 2026-05-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Enums ----
    # Pre-create the types via raw DDL, then build column types with
    # `postgresql.ENUM(..., create_type=False)` so op.create_table does
    # not try to CREATE TYPE again on the before_create hook.
    op.execute(
        "CREATE TYPE order_status AS ENUM "
        "('pending','paid','fulfilling','shipped','delivered','cancelled','refunded')"
    )
    op.execute(
        "CREATE TYPE payment_status AS ENUM "
        "('initiated','captured','failed','refunded')"
    )
    op.execute(
        "CREATE TYPE flash_sale_status AS ENUM "
        "('scheduled','active','ended','cancelled')"
    )
    order_status = postgresql.ENUM(
        "pending", "paid", "fulfilling", "shipped", "delivered", "cancelled", "refunded",
        name="order_status",
        create_type=False,
    )
    payment_status = postgresql.ENUM(
        "initiated", "captured", "failed", "refunded",
        name="payment_status",
        create_type=False,
    )
    flash_sale_status = postgresql.ENUM(
        "scheduled", "active", "ended", "cancelled",
        name="flash_sale_status",
        create_type=False,
    )

    # ---- users ----
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---- addresses ----
    op.create_table(
        "addresses",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("line1", sa.String(255), nullable=False),
        sa.Column("line2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("postal_code", sa.String(20), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_addresses_user_id", "addresses", ["user_id"])

    # ---- categories ----
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("slug", sa.String(120), nullable=False, unique=True),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_categories_slug", "categories", ["slug"], unique=True)

    # ---- products ----
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(280), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("brand", sa.String(100), nullable=True),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("base_price >= 0", name="ck_products_price_nonneg"),
    )
    op.create_index("ix_products_category_id", "products", ["category_id"])
    op.create_index("ix_products_brand", "products", ["brand"])
    op.create_index("ix_products_slug", "products", ["slug"], unique=True)
    op.create_index("ix_products_active_category", "products", ["is_active", "category_id"])

    # ---- product_variants ----
    op.create_table(
        "product_variants",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.BigInteger, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False, unique=True),
        sa.Column("variant_name", sa.String(255), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("weight_grams", sa.Integer, nullable=True),
        sa.CheckConstraint("price >= 0", name="ck_variants_price_nonneg"),
    )
    op.create_index("ix_product_variants_product_id", "product_variants", ["product_id"])
    op.create_index("ix_product_variants_sku", "product_variants", ["sku"], unique=True)

    # ---- inventory_levels ----
    op.create_table(
        "inventory_levels",
        sa.Column(
            "variant_id",
            sa.BigInteger,
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("quantity_on_hand", sa.Integer, nullable=False, server_default="0"),
        sa.Column("quantity_reserved", sa.Integer, nullable=False, server_default="0"),
        sa.Column("low_stock_threshold", sa.Integer, nullable=False, server_default="10"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity_on_hand >= 0", name="ck_inv_onhand_nonneg"),
        sa.CheckConstraint("quantity_reserved >= 0", name="ck_inv_reserved_nonneg"),
    )

    # ---- flash_sales ----
    op.create_table(
        "flash_sales",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", flash_sale_status, nullable=False, server_default="scheduled"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_flash_window_valid"),
    )
    op.create_index("ix_flash_sales_starts_at", "flash_sales", ["starts_at"])
    op.create_index("ix_flash_sales_ends_at", "flash_sales", ["ends_at"])

    # ---- flash_sale_items ----
    op.create_table(
        "flash_sale_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("flash_sale_id", sa.BigInteger, sa.ForeignKey("flash_sales.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant_id", sa.BigInteger, sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sale_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("quantity_allocated", sa.Integer, nullable=False),
        sa.Column("per_user_limit", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("flash_sale_id", "variant_id", name="uq_flash_sale_variant"),
        sa.CheckConstraint("sale_price >= 0", name="ck_flash_price_nonneg"),
        sa.CheckConstraint("quantity_allocated > 0", name="ck_flash_qty_pos"),
    )
    op.create_index("ix_flash_sale_items_flash_sale_id", "flash_sale_items", ["flash_sale_id"])

    # ---- carts ----
    op.create_table(
        "carts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_carts_user_id", "carts", ["user_id"])

    # ---- cart_items ----
    op.create_table(
        "cart_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("cart_id", sa.BigInteger, sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant_id", sa.BigInteger, sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint("cart_id", "variant_id", name="uq_cart_variant"),
        sa.CheckConstraint("quantity > 0", name="ck_cart_qty_pos"),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])

    # ---- orders ----
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("address_id", sa.BigInteger, sa.ForeignKey("addresses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", order_status, nullable=False, server_default="pending"),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("shipping_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("flash_sale_id", sa.BigInteger, sa.ForeignKey("flash_sales.id", ondelete="SET NULL"), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("total >= 0", name="ck_orders_total_nonneg"),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_user_placed", "orders", ["user_id", "placed_at"])

    # ---- order_items ----
    op.create_table(
        "order_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.BigInteger, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant_id", sa.BigInteger, sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_item_qty_pos"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])

    # ---- payments ----
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.BigInteger, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("status", payment_status, nullable=False, server_default="initiated"),
        sa.Column("provider_ref", sa.String(255), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ---- audit_log ----
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("actor_user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("payments")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("cart_items")
    op.drop_table("carts")
    op.drop_table("flash_sale_items")
    op.drop_table("flash_sales")
    op.drop_table("inventory_levels")
    op.drop_table("product_variants")
    op.drop_table("products")
    op.drop_table("categories")
    op.drop_table("addresses")
    op.drop_table("users")

    sa.Enum(name="flash_sale_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="payment_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="order_status").drop(op.get_bind(), checkfirst=True)
