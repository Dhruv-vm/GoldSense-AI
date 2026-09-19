from datetime import datetime

from pydantic import BaseModel, Field


class KJPLRate(BaseModel):
    source: str = "KJPL"

    gold_mjdta: float = Field(gt=0)
    silver_mjdta: float | None = Field(default=None, gt=0)

    gold_with_gst: float | None = Field(default=None, gt=0)

    source_updated_time: str | None = None
    source_updated_at: datetime | None = None

    observed_at: datetime

    currency: str = "INR"
    unit: str = "gram"