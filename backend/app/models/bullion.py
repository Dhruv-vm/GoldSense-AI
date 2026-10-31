from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BullionCity(Base):
    """
    Mandatory city entity: Chennai, Bengaluru, Mumbai, Coimbatore, Hyderabad.
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
    Standardized precious metal product traded or tracked across cities.
    Examples:
      - GOLD_100G_999 (100g 24K bar)
      - GOLD_1KG_9999 (1kg 99.99 purity bar)
      - MJDTA_GOLD_24K (Reference rate per gram)
      - MJDTA_SILVER (Reference rate per gram)
      - SILVER_1KG_999 (1kg silver bar)
    """
    __tablename__ = "bullion_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    metal: Mapped[str] = mapped_column(String(20), nullable=False)  # "GOLD" or "SILVER"
    purity: Mapped[float] = mapped_column(Float, nullable=False)  # e.g., 0.999, 0.9999
    weight: Mapped[float] = mapped_column(Float, nullable=False)  # numerical weight
    unit: Mapped[str] = mapped_column(String(20), nullable=False)  # "g", "kg", "oz"
    rate_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "RETAIL", "WHOLESALE", "MJDTA_BENCHMARK"
    source_product_id: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. "48", "49", "50"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    observations = relationship("BullionRateObservation", back_populates="product", cascade="all, delete-orphan")
    latest_rates = relationship("BullionLatestRate", back_populates="product", cascade="all, delete-orphan")


class BullionRateObservation(Base):
    """
    Append-only historical price observation for a specific city and product.
    Traceable to source URL and publication timestamp.
    """
    __tablename__ = "bullion_rate_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_code: Mapped[str] = mapped_column(String(50), ForeignKey("bullion_cities.city_code"), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(50), ForeignKey("bullion_products.product_id"), index=True, nullable=False)

    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    rate_type: Mapped[str] = mapped_column(String(50), default="RETAIL", nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="100g", nullable=False)

    source_url: Mapped[str] = mapped_column(String(255), default="http://www.kjpl.in/", nullable=False)
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    is_changed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(20), default="FRESH", nullable=False)  # "FRESH", "DELAYED", "STALE", "UNAVAILABLE"

    city = relationship("BullionCity", back_populates="observations")
    product = relationship("BullionProduct", back_populates="observations")

    __table_args__ = (
        Index("idx_bullion_obs_city_prod_time", "city_code", "product_id", "observed_at"),
    )


class BullionLatestRate(Base):
    """
    Current materialized view / state table for fastest dashboard queries.
    Holds latest verified price, previous price, timestamps and delta.
    """
    __tablename__ = "bullion_latest_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_code: Mapped[str] = mapped_column(String(50), ForeignKey("bullion_cities.city_code"), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(50), ForeignKey("bullion_products.product_id"), index=True, nullable=False)

    latest_price: Mapped[float] = mapped_column(Float, nullable=False)
    previous_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_inr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    change_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="100g", nullable=False)
    rate_type: Mapped[str] = mapped_column(String(50), default="RETAIL", nullable=False)

    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    freshness_status: Mapped[str] = mapped_column(String(20), default="FRESH", nullable=False)  # "FRESH", "DELAYED", "STALE", "UNAVAILABLE"
    source_url: Mapped[str] = mapped_column(String(255), default="http://www.kjpl.in/", nullable=False)

    city = relationship("BullionCity", back_populates="latest_rates")
    product = relationship("BullionProduct", back_populates="latest_rates")

    __table_args__ = (
        UniqueConstraint("city_code", "product_id", name="uq_bullion_city_product"),
    )


class CollectorRun(Base):
    """
    Execution trace for all data collection workers (KJPL, Market, News).
    Diagnoses parsing errors, collection duration, and record deltas.
    """
    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collector_name: Mapped[str] = mapped_column(String(50), index=True, nullable=False)  # e.g., "KJPL_CITY_COLLECTOR"
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "SUCCESS", "FAILED", "PARTIAL"
    records_extracted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_changed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class DataSourceStatus(Base):
    """
    Live health and connectivity status of each upstream data provider.
    """
    __tablename__ = "data_source_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)  # "KJPL", "YAHOO_FINANCE", "GDELT"
    last_successful_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failed_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_status: Mapped[str] = mapped_column(String(20), default="OPERATIONAL", nullable=False)  # "OPERATIONAL", "DEGRADED", "DOWN"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
