from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(100), default="default_user", index=True, nullable=False)
    
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Types: "PRICE_ABOVE", "PRICE_BELOW", "PREMIUM_ABOVE", "PREMIUM_BELOW", "DAILY_CHANGE_PCT"
    target_metric: Mapped[str] = mapped_column(String(50), default="KJPL_GOLD", nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
