from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GoldRate(Base):
    __tablename__ = "gold_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    source: Mapped[str] = mapped_column(String(50), nullable=False)
    gold_mjdta: Mapped[float] = mapped_column(Float, nullable=False)
    gold_with_gst: Mapped[float | None] = mapped_column(Float)
    silver_mjdta: Mapped[float | None] = mapped_column(Float)

    source_updated_time: Mapped[str | None] = mapped_column(String(50))

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
    )

    unit: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="gram",
    )
