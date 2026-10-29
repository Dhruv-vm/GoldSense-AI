from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PortfolioHolding(Base):
    __tablename__ = "portfolio_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(100), default="default_user", index=True, nullable=False)

    metal_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "GOLD" or "SILVER"
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    purity: Mapped[float] = mapped_column(Float, nullable=False, default=0.999)
    gross_weight_grams: Mapped[float] = mapped_column(Float, nullable=False)
    fine_weight_grams: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    acquisition_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    acquisition_cost_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
