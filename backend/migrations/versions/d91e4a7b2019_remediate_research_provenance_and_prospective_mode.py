"""remediate_research_provenance_and_prospective_mode

Revision ID: d91e4a7b2019
Revises: c4d912f8a103
Create Date: 2026-11-11 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d91e4a7b2019"
down_revision: Union[str, Sequence[str], None] = "c4d912f8a103"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("news_labels") as batch_op:
        batch_op.add_column(sa.Column("model_digest", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("feature_eligible", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("label_hash", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint(
            "uq_news_label_append_only_version",
            ["story_cluster_id", "sentiment_version", "model_name", "label_created_at"],
        )

    with op.batch_alter_table("research_feature_snapshots") as batch_op:
        batch_op.add_column(sa.Column("generation_mode", sa.String(length=24), nullable=False, server_default="BACKTEST"))
        batch_op.add_column(sa.Column("label_cutoff_time", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("origin_observation_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("feature_hash", sa.String(length=64), nullable=True))
        batch_op.alter_column("net_impact", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("unknown_share", existing_type=sa.Float(), nullable=True)
        batch_op.create_index("ix_research_feature_snapshots_generation_mode", ["generation_mode"], unique=False)
        batch_op.create_check_constraint(
            "ck_snapshot_generation_mode",
            "generation_mode IN ('PROSPECTIVE', 'BACKTEST')",
        )

    with op.batch_alter_table("forecast_runs") as batch_op:
        batch_op.drop_constraint("uq_forecast_run_origin_arm_horizon", type_="unique")
        batch_op.drop_index("idx_forecast_arm_horizon_origin")
        batch_op.add_column(sa.Column("generation_mode", sa.String(length=24), nullable=False, server_default="BACKTEST"))
        batch_op.add_column(sa.Column("model_version", sa.String(length=64), nullable=False, server_default="RIDGE_STD_V1"))
        batch_op.add_column(sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("origin_observation_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("target_observation_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("target_observed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("feature_hash", sa.String(length=64), nullable=True))
        batch_op.alter_column("predicted_log_return", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("predicted_price_inr_per_g", existing_type=sa.Numeric(14, 2), nullable=True)
        batch_op.alter_column("up_probability", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("predicted_direction", type_=sa.String(length=32), existing_type=sa.String(length=16), existing_nullable=False)
        batch_op.alter_column("status", type_=sa.String(length=48), existing_type=sa.String(length=32), existing_nullable=False)
        batch_op.create_index("ix_forecast_runs_generation_mode", ["generation_mode"], unique=False)
        batch_op.create_unique_constraint(
            "uq_forecast_run_mode_origin_arm_horizon",
            ["protocol_version", "generation_mode", "arm", "horizon_publications", "origin_observed_at"],
        )
        batch_op.create_index(
            "idx_forecast_mode_arm_horizon_origin",
            ["generation_mode", "arm", "horizon_publications", "origin_observed_at"],
            unique=False,
        )
        batch_op.create_check_constraint(
            "ck_forecast_generation_mode",
            "generation_mode IN ('PROSPECTIVE', 'BACKTEST')",
        )

    # Backfill generated_at from created_at safely before making NOT NULL
    op.execute(sa.text("UPDATE forecast_runs SET generated_at = created_at WHERE generated_at IS NULL"))
    with op.batch_alter_table("forecast_runs") as batch_op:
        batch_op.alter_column("generated_at", existing_type=sa.DateTime(timezone=True), nullable=False)

    with op.batch_alter_table("forecast_evaluations") as batch_op:
        batch_op.add_column(sa.Column("generation_mode", sa.String(length=24), nullable=False, server_default="BACKTEST"))
        batch_op.add_column(sa.Column("target_observation_id", sa.Integer(), nullable=True))
        batch_op.alter_column("abs_error_log_return", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("sq_error_log_return", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("abs_error_inr_per_g", existing_type=sa.Numeric(14, 2), nullable=True)
        batch_op.alter_column("direction_correct", existing_type=sa.Boolean(), nullable=True)
        batch_op.alter_column("brier_score", existing_type=sa.Float(), nullable=True)
        batch_op.create_index("ix_forecast_evaluations_generation_mode", ["generation_mode"], unique=False)
        batch_op.create_check_constraint(
            "ck_eval_generation_mode",
            "generation_mode IN ('PROSPECTIVE', 'BACKTEST')",
        )


def downgrade() -> None:
    with op.batch_alter_table("forecast_evaluations") as batch_op:
        batch_op.drop_constraint("ck_eval_generation_mode", type_="check")
        batch_op.drop_index("ix_forecast_evaluations_generation_mode")
        batch_op.alter_column("brier_score", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("direction_correct", existing_type=sa.Boolean(), nullable=False)
        batch_op.alter_column("abs_error_inr_per_g", existing_type=sa.Numeric(14, 2), nullable=False)
        batch_op.alter_column("sq_error_log_return", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("abs_error_log_return", existing_type=sa.Float(), nullable=False)
        batch_op.drop_column("target_observation_id")
        batch_op.drop_column("generation_mode")

    with op.batch_alter_table("forecast_runs") as batch_op:
        batch_op.drop_constraint("ck_forecast_generation_mode", type_="check")
        batch_op.drop_index("idx_forecast_mode_arm_horizon_origin")
        batch_op.drop_constraint("uq_forecast_run_mode_origin_arm_horizon", type_="unique")
        batch_op.drop_index("ix_forecast_runs_generation_mode")
        batch_op.alter_column("status", type_=sa.String(length=32), existing_type=sa.String(length=48), existing_nullable=False)
        batch_op.alter_column("predicted_direction", type_=sa.String(length=16), existing_type=sa.String(length=32), existing_nullable=False)
        batch_op.alter_column("up_probability", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("predicted_price_inr_per_g", existing_type=sa.Numeric(14, 2), nullable=False)
        batch_op.alter_column("predicted_log_return", existing_type=sa.Float(), nullable=False)
        batch_op.drop_column("feature_hash")
        batch_op.drop_column("target_observed_at")
        batch_op.drop_column("target_observation_id")
        batch_op.drop_column("origin_observation_id")
        batch_op.drop_column("generated_at")
        batch_op.drop_column("model_version")
        batch_op.drop_column("generation_mode")
        batch_op.create_unique_constraint(
            "uq_forecast_run_origin_arm_horizon",
            ["protocol_version", "arm", "horizon_publications", "origin_observed_at"],
        )
        batch_op.create_index("idx_forecast_arm_horizon_origin", ["arm", "horizon_publications", "origin_observed_at"], unique=False)

    with op.batch_alter_table("research_feature_snapshots") as batch_op:
        batch_op.drop_constraint("ck_snapshot_generation_mode", type_="check")
        batch_op.drop_index("ix_research_feature_snapshots_generation_mode")
        batch_op.alter_column("unknown_share", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("net_impact", existing_type=sa.Float(), nullable=False)
        batch_op.drop_column("feature_hash")
        batch_op.drop_column("origin_observation_id")
        batch_op.drop_column("label_cutoff_time")
        batch_op.drop_column("generation_mode")

    with op.batch_alter_table("news_labels") as batch_op:
        batch_op.drop_constraint("uq_news_label_append_only_version", type_="unique")
        batch_op.drop_column("label_hash")
        batch_op.drop_column("feature_eligible")
        batch_op.drop_column("model_digest")
