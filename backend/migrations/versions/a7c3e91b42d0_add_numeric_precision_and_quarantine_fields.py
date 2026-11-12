"""add_numeric_precision_and_quarantine_fields

Revision ID: a7c3e91b42d0
Revises: 0f1a9481a06e
Create Date: 2026-11-11 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e91b42d0"
down_revision: Union[str, Sequence[str], None] = "0f1a9481a06e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade financial columns to Numeric/Decimal, ensure portfolio/alert tables exist, and add validation/quarantine fields."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    with op.batch_alter_table("bullion_products") as batch_op:
        batch_op.alter_column("purity", type_=sa.Numeric(6, 4), existing_type=sa.Float(), existing_nullable=False)
        batch_op.alter_column("weight", type_=sa.Numeric(12, 4), existing_type=sa.Float(), existing_nullable=False)

    with op.batch_alter_table("bullion_rate_observations") as batch_op:
        batch_op.alter_column("price", type_=sa.Numeric(14, 2), existing_type=sa.Float(), existing_nullable=False)
        batch_op.add_column(sa.Column("buy_price", sa.Numeric(14, 2), nullable=True))
        batch_op.add_column(sa.Column("source_name", sa.String(length=50), nullable=False, server_default="KJPL"))
        batch_op.add_column(sa.Column("source_product_id", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("raw_source_name", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("product_weight_grams", sa.Numeric(12, 4), nullable=False, server_default="1.0000"))
        batch_op.add_column(sa.Column("original_price", sa.Numeric(14, 2), nullable=True))
        batch_op.add_column(sa.Column("original_unit", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("normalized_price_per_gram", sa.Numeric(14, 2), nullable=True))
        batch_op.add_column(sa.Column("validation_status", sa.String(length=20), nullable=False, server_default="VALID"))
        batch_op.add_column(sa.Column("quarantine_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("raw_payload_reference", sa.String(length=255), nullable=True))
        batch_op.create_index("ix_bullion_rate_observations_validation_status", ["validation_status"], unique=False)
        batch_op.create_index("idx_bullion_obs_validation", ["validation_status", "observed_at"], unique=False)

    with op.batch_alter_table("bullion_latest_rates") as batch_op:
        batch_op.alter_column("latest_price", type_=sa.Numeric(14, 2), existing_type=sa.Float(), existing_nullable=False)
        batch_op.alter_column("previous_price", type_=sa.Numeric(14, 2), existing_type=sa.Float(), existing_nullable=True)
        batch_op.alter_column("change_inr", type_=sa.Numeric(14, 2), existing_type=sa.Float(), existing_nullable=False)
        batch_op.alter_column("change_pct", type_=sa.Numeric(10, 4), existing_type=sa.Float(), existing_nullable=False)
        batch_op.add_column(sa.Column("buy_price", sa.Numeric(14, 2), nullable=True))
        batch_op.add_column(sa.Column("normalized_price_per_gram", sa.Numeric(14, 2), nullable=True))
        batch_op.add_column(sa.Column("product_weight_grams", sa.Numeric(12, 4), nullable=False, server_default="1.0000"))
        batch_op.add_column(sa.Column("source_product_id", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("validation_status", sa.String(length=20), nullable=False, server_default="VALID"))

    with op.batch_alter_table("collector_runs") as batch_op:
        batch_op.add_column(sa.Column("run_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("records_quarantined", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("gold_rates") as batch_op:
        batch_op.alter_column("gold_mjdta", type_=sa.Numeric(14, 2), existing_type=sa.Float(), existing_nullable=False)
        batch_op.alter_column("gold_with_gst", type_=sa.Numeric(14, 2), existing_type=sa.Float(), existing_nullable=True)
        batch_op.alter_column("silver_mjdta", type_=sa.Numeric(14, 2), existing_type=sa.Float(), existing_nullable=True)

    with op.batch_alter_table("market_rates") as batch_op:
        batch_op.alter_column("value", type_=sa.Numeric(14, 4), existing_type=sa.Float(), existing_nullable=False)

    if "portfolio_holdings" in existing_tables:
        with op.batch_alter_table("portfolio_holdings") as batch_op:
            batch_op.alter_column("purity", type_=sa.Numeric(6, 4), existing_type=sa.Float(), existing_nullable=False)
            batch_op.alter_column("gross_weight_grams", type_=sa.Numeric(14, 4), existing_type=sa.Float(), existing_nullable=False)
            batch_op.alter_column("fine_weight_grams", type_=sa.Numeric(14, 4), existing_type=sa.Float(), existing_nullable=False)
            batch_op.alter_column("acquisition_cost_inr", type_=sa.Numeric(14, 2), existing_type=sa.Float(), existing_nullable=True)
    else:
        op.create_table(
            "portfolio_holdings",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("metal_type", sa.String(length=20), nullable=False),
            sa.Column("product_name", sa.String(length=150), nullable=False),
            sa.Column("purity", sa.Numeric(6, 4), nullable=False),
            sa.Column("gross_weight_grams", sa.Numeric(14, 4), nullable=False),
            sa.Column("fine_weight_grams", sa.Numeric(14, 4), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("acquisition_date", sa.String(length=30), nullable=True),
            sa.Column("acquisition_cost_inr", sa.Numeric(14, 2), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_portfolio_holdings_user_id", "portfolio_holdings", ["user_id"], unique=False)

    if "alert_rules" in existing_tables:
        with op.batch_alter_table("alert_rules") as batch_op:
            batch_op.alter_column("threshold", type_=sa.Numeric(14, 2), existing_type=sa.Float(), existing_nullable=False)
    else:
        op.create_table(
            "alert_rules",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("alert_type", sa.String(length=50), nullable=False),
            sa.Column("target_metric", sa.String(length=50), nullable=False),
            sa.Column("threshold", sa.Numeric(14, 2), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_alert_rules_user_id", "alert_rules", ["user_id"], unique=False)

    # Backfill remediation for pre-existing corrupt rows if upgrading an already-populated DB
    op.execute(sa.text("""
        UPDATE bullion_products
        SET weight = 1.0000, unit = '1g', source_product_id = '48-52'
        WHERE product_id = 'GOLD_100G_999'
    """))
    op.execute(sa.text("""
        UPDATE bullion_products
        SET weight = 1.0000, unit = '1g', source_product_id = '47'
        WHERE product_id = 'GOLD_1KG_9999'
    """))
    op.execute(sa.text("""
        UPDATE bullion_rate_observations
        SET validation_status = 'QUARANTINED',
            freshness_status = 'QUARANTINED',
            quarantine_reason = 'Pre-migration corrupt gold price (<5000 INR/g: weight/com_id/silver/LBMA artifact)'
        WHERE currency = 'INR'
          AND product_id IN ('GOLD_100G_999', 'GOLD_1KG_9999', 'MJDTA_GOLD_24K', 'MJDTA_GOLD_24K_GST')
          AND price < 5000
    """))
    op.execute(sa.text("""
        UPDATE bullion_rate_observations
        SET validation_status = 'QUARANTINED',
            freshness_status = 'QUARANTINED',
            quarantine_reason = 'Pre-migration corrupt silver INR price (<80 INR/g: LBMA USD/oz artifact)'
        WHERE currency = 'INR'
          AND product_id IN ('MJDTA_SILVER', 'MJDTA_SILVER_GST')
          AND price < 80
    """))
    op.execute(sa.text("""
        UPDATE bullion_latest_rates
        SET validation_status = 'QUARANTINED',
            freshness_status = 'QUARANTINED'
        WHERE currency = 'INR'
          AND (
            (product_id IN ('GOLD_100G_999', 'GOLD_1KG_9999', 'MJDTA_GOLD_24K', 'MJDTA_GOLD_24K_GST') AND latest_price < 5000)
            OR (product_id IN ('MJDTA_SILVER', 'MJDTA_SILVER_GST') AND latest_price < 80)
          )
    """))
    op.execute(sa.text("""
        UPDATE bullion_rate_observations
        SET normalized_price_per_gram = price,
            product_weight_grams = 1.0000
        WHERE validation_status = 'VALID'
          AND currency = 'INR'
          AND unit IN ('1g', '100g', '1kg')
          AND price >= 5000 AND price <= 52000
          AND product_id IN ('GOLD_100G_999', 'GOLD_1KG_9999', 'MJDTA_GOLD_24K', 'MJDTA_GOLD_24K_GST')
          AND normalized_price_per_gram IS NULL
    """))
    op.execute(sa.text("""
        UPDATE bullion_latest_rates
        SET normalized_price_per_gram = latest_price,
            product_weight_grams = 1.0000
        WHERE validation_status = 'VALID'
          AND currency = 'INR'
          AND latest_price >= 5000 AND latest_price <= 52000
          AND product_id IN ('GOLD_100G_999', 'GOLD_1KG_9999', 'MJDTA_GOLD_24K', 'MJDTA_GOLD_24K_GST')
          AND normalized_price_per_gram IS NULL
    """))


def downgrade() -> None:
    with op.batch_alter_table("collector_runs") as batch_op:
        batch_op.drop_column("records_quarantined")
        batch_op.drop_column("run_id")

    with op.batch_alter_table("bullion_latest_rates") as batch_op:
        batch_op.drop_column("validation_status")
        batch_op.drop_column("source_product_id")
        batch_op.drop_column("product_weight_grams")
        batch_op.drop_column("normalized_price_per_gram")
        batch_op.drop_column("buy_price")

    with op.batch_alter_table("bullion_rate_observations") as batch_op:
        batch_op.drop_index("idx_bullion_obs_validation")
        batch_op.drop_index("ix_bullion_rate_observations_validation_status")
        batch_op.drop_column("raw_payload_reference")
        batch_op.drop_column("quarantine_reason")
        batch_op.drop_column("validation_status")
        batch_op.drop_column("normalized_price_per_gram")
        batch_op.drop_column("original_unit")
        batch_op.drop_column("original_price")
        batch_op.drop_column("product_weight_grams")
        batch_op.drop_column("raw_source_name")
        batch_op.drop_column("source_product_id")
        batch_op.drop_column("source_name")
        batch_op.drop_column("buy_price")
