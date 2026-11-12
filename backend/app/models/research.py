from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NewsCollectionRun(Base):
    """Records per-run news collector health, query version, and partial-failure counts."""

    __tablename__ = "news_collection_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    query_version: Mapped[str] = mapped_column(String(32), nullable=False)
    collector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    cluster_version: Mapped[str] = mapped_column(String(32), nullable=False)
    queries_attempted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    queries_succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    queries_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unique_collected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_archive_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    live_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    db_recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )
    db_tx_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class NewsCluster(Base):
    """Deduplicated story cluster across syndicated financial wire copies."""

    __tablename__ = "news_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_cluster_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    cluster_key: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    cluster_version: Mapped[str] = mapped_column(String(32), nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    latest_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    representative_title: Mapped[str] = mapped_column(Text, nullable=False)
    article_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class NewsArticleRecord(Base):
    """Persisted news article with immutable ingest timestamp and provenance status."""

    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_url: Mapped[str] = mapped_column(String(1024), unique=True, index=True, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="unknown")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    # Must remain NULL if unavailable at original archive time; never backfilled from published_at.
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    content_fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    query_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query_version: Mapped[str] = mapped_column(String(32), nullable=False)
    collector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance_status: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    story_cluster_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("news_clusters.story_cluster_id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class NewsLabelRecord(Base):
    """
    Append-only point-in-time versioned gold sentiment label.
    Updating a classifier appends a NEW row with its actual creation timestamp;
    historical cutoff queries filter `label_created_at <= T`.
    """

    __tablename__ = "news_labels"
    __table_args__ = (
        UniqueConstraint(
            "story_cluster_id",
            "sentiment_version",
            "model_name",
            "label_created_at",
            name="uq_news_label_append_only_version",
        ),
        Index(
            "uq_news_label_llm_identity",
            "classification_identity_hash",
            unique=True,
            sqlite_where=text("model_name <> 'deterministic_rules_v2' AND classification_identity_hash IS NOT NULL"),
            postgresql_where=text("model_name <> 'deterministic_rules_v2' AND classification_identity_hash IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("news_articles.id", ondelete="CASCADE"), index=True, nullable=True
    )
    story_cluster_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("news_clusters.story_cluster_id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    collection_run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("news_collection_runs.run_id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )
    classification_scope: Mapped[str] = mapped_column(
        String(24), default="CLUSTER", server_default="CLUSTER", nullable=False
    )
    label_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    db_recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), index=True, nullable=False
    )
    sentiment_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    classifier_impl_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification_identity_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    general_tone: Mapped[str] = mapped_column(String(20), nullable=False)
    gold_impact: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    driver: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    surprise: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    is_price_report: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    feature_eligible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    label_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW")
    evidence_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_human_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    human_gold_impact: Mapped[str | None] = mapped_column(String(20), nullable=True)
    human_driver: Mapped[str | None] = mapped_column(String(48), nullable=True)


class ResearchFeatureSnapshot(Base):
    """Immutable point-in-time feature vector persisted strictly at forecast cutoff T."""

    __tablename__ = "research_feature_snapshots"
    __table_args__ = (
        CheckConstraint("generation_mode IN ('PROSPECTIVE', 'BACKTEST')", name="ck_snapshot_generation_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="BACKTEST")
    cutoff_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    label_cutoff_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_product: Mapped[str] = mapped_column(String(48), nullable=False, default="MJDTA_GOLD_24K")
    origin_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    origin_source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    origin_gold_price_inr_per_g: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(32), nullable=False)
    cluster_version: Mapped[str] = mapped_column(String(32), nullable=False)
    sentiment_version: Mapped[str] = mapped_column(String(32), nullable=False)
    protocol_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feature_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    n_clusters_relevant: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    net_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    unknown_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    features_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ForecastRun(Base):
    """Immutable forecast ledger strictly separating PROSPECTIVE live shadow runs from BACKTEST replays."""

    __tablename__ = "forecast_runs"
    __table_args__ = (
        UniqueConstraint(
            "protocol_version",
            "generation_mode",
            "model_version",
            "arm",
            "horizon_publications",
            "origin_observed_at",
            name="uq_forecast_run_mode_model_origin_arm_horizon",
        ),
        CheckConstraint("generation_mode IN ('PROSPECTIVE', 'BACKTEST')", name="ck_forecast_generation_mode"),
        Index(
            "idx_forecast_mode_arm_horizon_origin",
            "generation_mode",
            "model_version",
            "arm",
            "horizon_publications",
            "origin_observed_at",
        ),
        Index(
            "uq_prospective_origin_publication",
            "protocol_version",
            "generation_mode",
            "model_version",
            "arm",
            "horizon_publications",
            "origin_source_published_at",
            unique=True,
            sqlite_where=text("generation_mode = 'PROSPECTIVE' AND origin_source_published_at IS NOT NULL"),
            postgresql_where=text("generation_mode = 'PROSPECTIVE' AND origin_source_published_at IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(32), nullable=False)
    protocol_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_mode: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="BACKTEST")
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, default="RIDGE_STD_V1")
    arm: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    horizon_publications: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    cutoff_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    origin_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    origin_source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    origin_price_inr_per_g: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    target_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("research_feature_snapshots.snapshot_id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    feature_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Nullable when unavailable due to INSUFFICIENT_SAMPLE or UNAVAILABLE_NO_NEWS_COVERAGE
    predicted_log_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_price_inr_per_g: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    predicted_direction: Mapped[str] = mapped_column(String(32), nullable=False)
    up_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ForecastEvaluation(Base):
    """Delayed post-maturity evaluation record computed strictly after horizon outcome is observed."""

    __tablename__ = "forecast_evaluations"
    __table_args__ = (
        CheckConstraint("generation_mode IN ('PROSPECTIVE', 'BACKTEST')", name="ck_eval_generation_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("forecast_runs.forecast_id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    protocol_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_mode: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="BACKTEST")
    arm: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    horizon_publications: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    origin_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    target_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    matured_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    actual_price_inr_per_g: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    actual_log_return: Mapped[float] = mapped_column(Float, nullable=False)
    actual_direction: Mapped[str] = mapped_column(String(16), nullable=False)
    abs_error_log_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    sq_error_log_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    abs_error_inr_per_g: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    direction_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_non_overlapping_origin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )


class ForecastEvaluationReassessment(Base):
    """
    A3-FINAL-3: Append-only correction-aware reassessment when an evaluated target
    publication is later revised by a linked CORRECTION observation. Original rows in
    `forecast_evaluations` remain untouched.
    """

    __tablename__ = "forecast_evaluation_reassessments"
    __table_args__ = (
        UniqueConstraint("forecast_id", "corrected_target_observation_id", name="uq_eval_reassessment_forecast_target"),
        Index("ix_eval_reassess_corr_target_id", "corrected_target_observation_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reassessment_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    forecast_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("forecast_evaluations.forecast_id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    original_target_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corrected_target_observation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bullion_rate_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    corrected_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    matured_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    corrected_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    corrected_actual_price_inr_per_g: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    corrected_actual_log_return: Mapped[float] = mapped_column(Float, nullable=False)
    corrected_actual_direction: Mapped[str] = mapped_column(String(16), nullable=False)
    abs_error_log_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    sq_error_log_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    abs_error_inr_per_g: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    direction_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reassessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )
