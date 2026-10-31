from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class ParsedCityRate(BaseModel):
    """
    Standardized parsed rate for a single city-specific or benchmark bullion product.
    """
    city_code: str = Field(description="Normalized uppercase code: CHENNAI, BENGALURU, MUMBAI, COIMBATORE, HYDERABAD, ALL_INDIA")
    city_display_name: str = Field(description="Human readable name e.g. Bengaluru (even if source says Bangalore)")
    product_id: str = Field(description="Unique system ID e.g. GOLD_100G_999, GOLD_1KG_9999, MJDTA_GOLD_24K, MJDTA_SILVER")
    product_name: str = Field(description="Descriptive product title")
    metal: str = Field(description="'GOLD' or 'SILVER'")
    purity: float = Field(description="Decimal purity e.g. 0.999, 0.9999")
    weight: float = Field(description="Numeric weight in specified unit")
    unit: str = Field(description="Standardized unit: '100g', '1kg', '1g'")
    rate_type: str = Field(description="'RETAIL', 'WHOLESALE', 'MJDTA_BENCHMARK'")
    price: float = Field(description="Numerical price in INR")
    currency: str = Field(default="INR")
    source_product_id: str | None = Field(default=None, description="Raw source commodity id e.g. '48'")
    raw_source_name: str | None = Field(default=None, description="Raw product name from source")
    diff_rate: float | None = Field(default=None, description="Published differential / spread if available")


class ParsedKJPLPayload(BaseModel):
    """
    Complete bundle of parsed data extracted from a single KJPL webpage / JSON feed snapshot.
    """
    observed_at: datetime
    source_updated_time: str | None = None
    source_updated_at: datetime | None = None
    mjdta_gold: float | None = None
    mjdta_silver: float | None = None
    mjdta_gold_with_gst: float | None = None
    mjdta_silver_with_gst: float | None = None
    city_rates: list[ParsedCityRate] = Field(default_factory=list)
    raw_products_count: int = 0
    extraction_errors: list[str] = Field(default_factory=list)
