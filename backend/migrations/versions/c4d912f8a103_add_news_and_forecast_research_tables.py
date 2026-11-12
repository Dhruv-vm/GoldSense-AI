"""add_news_and_forecast_research_tables

Revision ID: c4d912f8a103
Revises: a7c3e91b42d0
Create Date: 2026-11-11 15:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d912f8a103"
down_revision: Union[str, Sequence[str], None] = "a7c3e91b42d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _declared_columns() -> dict[str, set[str]]:
    """Column names this migration declares per table, read from this file's own create_table calls."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    declared: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_table"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            cols: set[str] = set()
            for arg in node.args[1:]:
                if (
                    isinstance(arg, ast.Call)
                    and isinstance(arg.func, ast.Attribute)
                    and arg.func.attr == "Column"
                    and arg.args
                    and isinstance(arg.args[0], ast.Constant)
                ):
                    cols.add(str(arg.args[0].value))
            declared[str(node.args[0].value)] = cols
    return declared


def _must_create(existing: set[str], name: str) -> bool:
    """
    F-19: Return True when the table must be created. If it already exists (e.g. created earlier by
    `Base.metadata.create_all`), verify every column this migration declares is present and fail
    loudly on schema drift instead of silently skipping the table.
    """
    if name not in existing:
        return True
    present = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(name)}
    missing = sorted(_declared_columns().get(name, set()) - present)
    if missing:
        raise RuntimeError(
            f"Schema drift: pre-existing table '{name}' is missing columns {missing} required by "
            "migration c4d912f8a103. Reconcile the table before upgrading."
        )
    return False


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if _must_create(existing, "news_collection_runs"):
        op.create_table(
            "news_collection_runs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("run_id", sa.String(length=64), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("query_version", sa.String(length=32), nullable=False),
            sa.Column("collector_version", sa.String(length=32), nullable=False),
            sa.Column("cluster_version", sa.String(length=32), nullable=False),
            sa.Column("queries_attempted", sa.Integer(), nullable=False),
            sa.Column("queries_succeeded", sa.Integer(), nullable=False),
            sa.Column("queries_failed", sa.Integer(), nullable=False),
            sa.Column("raw_fetched", sa.Integer(), nullable=False),
            sa.Column("unique_collected", sa.Integer(), nullable=False),
            sa.Column("new_archive_count", sa.Integer(), nullable=False),
            sa.Column("live_count", sa.Integer(), nullable=False),
            sa.Column("error_summary", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_news_collection_runs_run_id", "news_collection_runs", ["run_id"], unique=True)
        op.create_index("ix_news_collection_runs_status", "news_collection_runs", ["status"], unique=False)

    if _must_create(existing, "news_clusters"):
        op.create_table(
            "news_clusters",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("story_cluster_id", sa.String(length=64), nullable=False),
            sa.Column("cluster_key", sa.String(length=255), nullable=False),
            sa.Column("cluster_version", sa.String(length=32), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("latest_published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("representative_title", sa.Text(), nullable=False),
            sa.Column("article_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_news_clusters_story_cluster_id", "news_clusters", ["story_cluster_id"], unique=True)
        op.create_index("ix_news_clusters_cluster_key", "news_clusters", ["cluster_key"], unique=False)
        op.create_index("ix_news_clusters_first_seen_at", "news_clusters", ["first_seen_at"], unique=False)

    if _must_create(existing, "news_articles"):
        op.create_table(
            "news_articles",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("canonical_url", sa.String(length=1024), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=255), nullable=False),
            sa.Column("language", sa.String(length=32), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("query_id", sa.String(length=64), nullable=True),
            sa.Column("query_version", sa.String(length=32), nullable=False),
            sa.Column("collector_version", sa.String(length=32), nullable=False),
            sa.Column("provenance_status", sa.String(length=64), nullable=False),
            sa.Column("exclusion_reason", sa.Text(), nullable=True),
            sa.Column("story_cluster_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["story_cluster_id"], ["news_clusters.story_cluster_id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_news_articles_canonical_url", "news_articles", ["canonical_url"], unique=True)
        op.create_index("ix_news_articles_language", "news_articles", ["language"], unique=False)
        op.create_index("ix_news_articles_published_at", "news_articles", ["published_at"], unique=False)
        op.create_index("ix_news_articles_first_seen_at", "news_articles", ["first_seen_at"], unique=False)
        op.create_index("ix_news_articles_content_fingerprint", "news_articles", ["content_fingerprint"], unique=False)
        op.create_index("ix_news_articles_provenance_status", "news_articles", ["provenance_status"], unique=False)
        op.create_index("ix_news_articles_story_cluster_id", "news_articles", ["story_cluster_id"], unique=False)

    if _must_create(existing, "news_labels"):
        op.create_table(
            "news_labels",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("article_id", sa.Integer(), nullable=True),
            sa.Column("story_cluster_id", sa.String(length=64), nullable=False),
            sa.Column("label_created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sentiment_version", sa.String(length=32), nullable=False),
            sa.Column("model_name", sa.String(length=64), nullable=False),
            sa.Column("prompt_version", sa.String(length=32), nullable=True),
            sa.Column("general_tone", sa.String(length=20), nullable=False),
            sa.Column("gold_impact", sa.String(length=20), nullable=False),
            sa.Column("driver", sa.String(length=48), nullable=False),
            sa.Column("surprise", sa.String(length=32), nullable=False),
            sa.Column("is_price_report", sa.Boolean(), nullable=False),
            sa.Column("confidence", sa.String(length=16), nullable=False),
            sa.Column("evidence_rationale", sa.Text(), nullable=True),
            sa.Column("is_human_verified", sa.Boolean(), nullable=False),
            sa.Column("human_gold_impact", sa.String(length=20), nullable=True),
            sa.Column("human_driver", sa.String(length=48), nullable=True),
            sa.ForeignKeyConstraint(["article_id"], ["news_articles.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_news_labels_article_id", "news_labels", ["article_id"], unique=False)
        op.create_index("ix_news_labels_story_cluster_id", "news_labels", ["story_cluster_id"], unique=False)
        op.create_index("ix_news_labels_label_created_at", "news_labels", ["label_created_at"], unique=False)
        op.create_index("ix_news_labels_gold_impact", "news_labels", ["gold_impact"], unique=False)
        op.create_index("ix_news_labels_driver", "news_labels", ["driver"], unique=False)

    if _must_create(existing, "research_feature_snapshots"):
        op.create_table(
            "research_feature_snapshots",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("snapshot_id", sa.String(length=64), nullable=False),
            sa.Column("cutoff_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("target_product", sa.String(length=48), nullable=False),
            sa.Column("origin_observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("origin_gold_price_inr_per_g", sa.Numeric(14, 2), nullable=False),
            sa.Column("feature_version", sa.String(length=32), nullable=False),
            sa.Column("cluster_version", sa.String(length=32), nullable=False),
            sa.Column("sentiment_version", sa.String(length=32), nullable=False),
            sa.Column("n_clusters_relevant", sa.Integer(), nullable=False),
            sa.Column("net_impact", sa.Float(), nullable=False),
            sa.Column("unknown_share", sa.Float(), nullable=False),
            sa.Column("coverage_ok", sa.Boolean(), nullable=False),
            sa.Column("features_json", sa.JSON(), nullable=False),
            sa.Column("is_immutable", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_research_feature_snapshots_snapshot_id", "research_feature_snapshots", ["snapshot_id"], unique=True)
        op.create_index("ix_research_feature_snapshots_cutoff_time", "research_feature_snapshots", ["cutoff_time"], unique=False)
        op.create_index("ix_research_feature_snapshots_origin_observed_at", "research_feature_snapshots", ["origin_observed_at"], unique=False)

    if _must_create(existing, "forecast_runs"):
        op.create_table(
            "forecast_runs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("forecast_id", sa.String(length=64), nullable=False),
            sa.Column("protocol_version", sa.String(length=32), nullable=False),
            sa.Column("arm", sa.String(length=24), nullable=False),
            sa.Column("horizon_publications", sa.Integer(), nullable=False),
            sa.Column("cutoff_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("origin_observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("origin_price_inr_per_g", sa.Numeric(14, 2), nullable=False),
            sa.Column("snapshot_id", sa.String(length=64), nullable=False),
            sa.Column("predicted_log_return", sa.Float(), nullable=False),
            sa.Column("predicted_price_inr_per_g", sa.Numeric(14, 2), nullable=False),
            sa.Column("predicted_direction", sa.String(length=16), nullable=False),
            sa.Column("up_probability", sa.Float(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("is_immutable", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["snapshot_id"], ["research_feature_snapshots.snapshot_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("protocol_version", "arm", "horizon_publications", "origin_observed_at", name="uq_forecast_run_origin_arm_horizon"),
        )
        op.create_index("ix_forecast_runs_forecast_id", "forecast_runs", ["forecast_id"], unique=True)
        op.create_index("ix_forecast_runs_arm", "forecast_runs", ["arm"], unique=False)
        op.create_index("ix_forecast_runs_horizon_publications", "forecast_runs", ["horizon_publications"], unique=False)
        op.create_index("ix_forecast_runs_cutoff_time", "forecast_runs", ["cutoff_time"], unique=False)
        op.create_index("ix_forecast_runs_origin_observed_at", "forecast_runs", ["origin_observed_at"], unique=False)
        op.create_index("ix_forecast_runs_snapshot_id", "forecast_runs", ["snapshot_id"], unique=False)
        op.create_index("idx_forecast_arm_horizon_origin", "forecast_runs", ["arm", "horizon_publications", "origin_observed_at"], unique=False)

    if _must_create(existing, "forecast_evaluations"):
        op.create_table(
            "forecast_evaluations",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("forecast_id", sa.String(length=64), nullable=False),
            sa.Column("arm", sa.String(length=24), nullable=False),
            sa.Column("horizon_publications", sa.Integer(), nullable=False),
            sa.Column("origin_observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("matured_observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("actual_price_inr_per_g", sa.Numeric(14, 2), nullable=False),
            sa.Column("actual_log_return", sa.Float(), nullable=False),
            sa.Column("actual_direction", sa.String(length=16), nullable=False),
            sa.Column("abs_error_log_return", sa.Float(), nullable=False),
            sa.Column("sq_error_log_return", sa.Float(), nullable=False),
            sa.Column("abs_error_inr_per_g", sa.Numeric(14, 2), nullable=False),
            sa.Column("direction_correct", sa.Boolean(), nullable=False),
            sa.Column("brier_score", sa.Float(), nullable=False),
            sa.Column("is_non_overlapping_origin", sa.Boolean(), nullable=False),
            sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["forecast_id"], ["forecast_runs.forecast_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_forecast_evaluations_forecast_id", "forecast_evaluations", ["forecast_id"], unique=True)
        op.create_index("ix_forecast_evaluations_arm", "forecast_evaluations", ["arm"], unique=False)
        op.create_index("ix_forecast_evaluations_horizon_publications", "forecast_evaluations", ["horizon_publications"], unique=False)
        op.create_index("ix_forecast_evaluations_origin_observed_at", "forecast_evaluations", ["origin_observed_at"], unique=False)
        op.create_index("ix_forecast_evaluations_matured_observed_at", "forecast_evaluations", ["matured_observed_at"], unique=False)


def downgrade() -> None:
    op.drop_table("forecast_evaluations")
    op.drop_table("forecast_runs")
    op.drop_table("research_feature_snapshots")
    op.drop_table("news_labels")
    op.drop_table("news_articles")
    op.drop_table("news_clusters")
    op.drop_table("news_collection_runs")
