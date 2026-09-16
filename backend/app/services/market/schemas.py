from datetime import datetime

from pydantic import BaseModel, Field


class MarketRate(BaseModel):
    symbol: str
    value: float = Field(gt=0)
    currency: str
    unit: str
    observed_at: datetime
    source: str = "Yahoo Finance"
