from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
    false as sql_false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BullionCity(Base):
    """
    Mandatory city entity: Chennai, Bengaluru, Mumbai, Coimbatore, Hyderabad (plus National ALL_INDIA).
    """
    __tablename__ = "bullion_cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    observations = relationship("BullionRateObservation", back_populates="city", cascade="all, delete-orphan")
    latest_rates = relationship("BullionLatestRate", back_populates="city", cascade="all, delete-orphan")


class BullionProduct(Base):
    """
    Standardized precious metal product or benchmark contract traded or published by KJPL.
    """
    __tablename__ = "bullion_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    metal: Mapped[str] = mapped_column(String(20), nullable=False)  # "GOLD", "SILVER", "FX"
    purity: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)  # e.g., 0.9990, 0.9999
    weight: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)  # numerical weight in unit
    unit: Mapped[str] = mapped_column(String(20), nullable=False)  # "1g", "10g", "100g", "1kg", "oz", "USD"
    rate_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "RETAIL", "WHOLESALE", "MJDTA_BENCHMARK", "KJPL_LIVE", "LBMA_FIX"
    source_product_id: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. "47", "48"..."52"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    observations = relationship("BullionRateObservation", back_populates="product", cascade="all, delete-orphan")
    latest_rates = relationship("BullionLatestRate", back_populates="product", cascade="all, delete-orphan")


class BullionRateObservation(Base):
    """
    Append-only historical price observation for a specific city and product.
    Preserves validation/quarantine state and original source metadata for auditing.
    """
    __tablename__ = "bullion_rate_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_code: Mapped[str] = mapped_column(String(50), ForeignKey("bullion_cities.city_code"), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(50), ForeignKey("bullion_products.product_id"), index=True, nullable=False)

    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    buy_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    rate_type: Mapped[str] = mapped_column(String(50), default="RETAIL", nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="1g", nullable=False)

    # Full audit & normalization fields
    source_name: Mapped[str] = mapped_column(String(50), default="KJPL", nullable=False)
    source_product_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw_source_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    product_weight_grams: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("1.0000"), nullable=False)
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    original_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    normalized_price_per_gram: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    source_url: Mapped[str] = mapped_column(String(255), default="http://www.kjpl.in/", nullable=False)
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_source_published_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_timestamp_precision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    is_timestamp_inferred: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_false(), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    observation_kind: Mapped[str] = mapped_column(String(24), default="ORIGINAL", server_default="ORIGINAL", nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    supersedes_observation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bullion_rate_observations.id", ondelete="RESTRICT"), nullable=True
    )
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_changed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(20), default="FRESH", nullable=False)
    validation_status: Mapped[str] = mapped_column(String(20), default="VALID", index=True, nullable=False)  # VALID, SUSPECT, QUARANTINED, INVALIDATED
    quarantine_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    city = relationship("BullionCity", back_populates="observations")
    product = relationship("BullionProduct", back_populates="observations")

    __table_args__ = (
        Index("idx_bullion_obs_city_prod_time", "city_code", "product_id", "observed_at"),
        Index("idx_bullion_obs_validation", "validation_status", "observed_at"),
        Index(
            "uq_bullion_mjdta_pub_revision",
            "city_code",
            "product_id",
            "source_product_id",
            "source_published_at",
            "revision_number",
            unique=True,
            sqlite_where=text("validation_status = 'VALID' AND rate_type = 'MJDTA_BENCHMARK' AND source_published_at IS NOT NULL"),
            postgresql_where=text("validation_status = 'VALID' AND rate_type = 'MJDTA_BENCHMARK' AND source_published_at IS NOT NULL"),
        ),
    )


class BullionLatestRate(Base):
    """
    Materialized current valid state per city and product.
    Quarantined records never overwrite latest valid snapshots.
    """
    __tablename__ = "bullion_latest_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_code: Mapped[str] = mapped_column(String(50), ForeignKey("bullion_cities.city_code"), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(50), ForeignKey("bullion_products.product_id"), index=True, nullable=False)

    latest_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    buy_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    previous_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    change_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    change_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.0000"), nullable=False)
    normalized_price_per_gram: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    product_weight_grams: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("1.0000"), nullable=False)

    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="1g", nullable=False)
    rate_type: Mapped[str] = mapped_column(String(50), default="RETAIL", nullable=False)
    source_product_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(20), default="VALID", nullable=False)

    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    freshness_status: Mapped[str] = mapped_column(String(20), default="FRESH", nullable=False)
    source_url: Mapped[str] = mapped_column(String(255), default="http://www.kjpl.in/", nullable=False)

    city = relationship("BullionCity", back_populates="latest_rates")
    product = relationship("BullionProduct", back_populates="latest_rates")

    __table_args__ = (
        UniqueConstraint("city_code", "product_id", name="uq_bullion_city_product"),
    )


class CollectorRun(Base):
    """
    Execution trace for designated pipeline writers (MJDTA GHA collector, KJPL Live Oracle worker).
    """
    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collector_name: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "SUCCESS", "FAILED", "PARTIAL", "SOURCE_UNAVAILABLE"
    records_extracted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_changed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_quarantined: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class DataSourceStatus(Base):
    """
    Live health and connectivity status of each upstream pipeline.
    """
    __tablename__ = "data_source_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)  # "KJPL_MJDTA", "KJPL_LIVE", "GDELT"
    last_successful_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failed_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_status: Mapped[str] = mapped_column(String(20), default="OPERATIONAL", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
