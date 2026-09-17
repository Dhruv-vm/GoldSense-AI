from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    target_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    predicted_gold_price: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    predicted_direction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    model_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    actual_gold_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    actual_direction: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )

    absolute_error: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    percentage_error: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    direction_correct: Mapped[bool | None] = mapped_column(
        nullable=True,
    )