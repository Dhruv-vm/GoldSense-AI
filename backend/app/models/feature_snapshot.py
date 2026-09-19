from datetime import datetime

from sqlalchemy import DateTime, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FeatureSnapshot(Base):
    __tablename__ = "feature_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    kjpl_gold: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    usdinr: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    xauusd: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    xagusd: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )