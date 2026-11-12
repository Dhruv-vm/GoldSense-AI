from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GoldRate(Base):
    __tablename__ = "gold_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    source: Mapped[str] = mapped_column(String(50), nullable=False)
    gold_mjdta: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gold_with_gst: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    silver_mjdta: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    source_updated_time: Mapped[str | None] = mapped_column(String(50))

    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

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
