from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class ParsedCityRate(BaseModel):
    """
    Standardized internal data contract for a single KJPL bullion, city, or benchmark observation.
    """
    source_name: str = Field(default="KJPL")
    city_code: str = Field(description="CHENNAI, BENGALURU, MUMBAI, COIMBATORE, HYDERABAD, ALL_INDIA")
    city_display_name: str = Field(description="Normalized display name e.g. Bengaluru")
    product_id: str = Field(description="Unique internal ID e.g. GOLD_100G_999, GOLD_1KG_9999, MJDTA_GOLD_24K")
    product_name: str = Field(description="Descriptive standardized product title")
    metal: str = Field(description="'GOLD', 'SILVER', or 'FX'")
    purity: float = Field(description="Decimal purity e.g. 0.999, 0.9999")
    weight: float = Field(description="Numeric weight in original unit")
    unit: str = Field(description="Source quote unit: '1g', '10g', '100g', '1kg', 'oz', 'USD'")
    product_weight_grams: float = Field(default=1.0, description="Exact mass basis in grams for the quoted price")
    rate_type: str = Field(description="'RETAIL', 'WHOLESALE', 'MJDTA_BENCHMARK', 'KJPL_LIVE', 'LBMA_FIX'")
    price: float = Field(description="Original quoted sell/reference price")
    buy_price: float | None = Field(default=None, description="Quoted buy price if published (else None)")
    high_price: float | None = Field(default=None, description="Session high if published")
    low_price: float | None = Field(default=None, description="Session low if published")
    normalized_price_per_gram: float | None = Field(default=None, description="Normalized INR/gram for INR bullion")
    currency: str = Field(default="INR")
    source_product_id: str | None = Field(default=None, description="Raw source commodity id e.g. '47', '48'")
    raw_source_name: str | None = Field(default=None, description="Raw product name from KJPL")
    diff_rate: float | None = Field(default=None, description="Uninterpreted source sell_diff if published")
    validation_status: str = Field(default="VALID", description="VALID | SUSPECT | QUARANTINED | INVALIDATED")
    quarantine_reason: str | None = Field(default=None)
    raw_payload_reference: str | None = Field(default=None)


class ParsedKJPLPayload(BaseModel):
    """
    Complete bundle extracted from a single KJPL Pipeline A (HTML) or Pipeline B (WS/kjpl.txt) snapshot.
    """
    observed_at: datetime
    pipeline: str = Field(default="KJPL_HTML", description="KJPL_MJDTA | KJPL_LIVE_WS | KJPL_LIVE_TXT | KJPL_HTML")
    source_updated_time: str | None = None
    source_updated_at: datetime | None = None
    source_timestamp_precision: str | None = Field(
        default=None,
        description="'FULL' when the source published a date+time, 'CLOCK_ONLY' when only HH:MM was published "
        "and the date was inferred at collection time.",
    )
    market_status: str | None = Field(default=None, description="'OPEN' or 'CLOSED' when Type 4 flag is present")
    rate_display_enabled: bool | None = Field(default=None)
    mjdta_gold: float | None = None
    mjdta_silver: float | None = None
    mjdta_gold_with_gst: float | None = None
    mjdta_silver_with_gst: float | None = None
    city_rates: list[ParsedCityRate] = Field(default_factory=list)
    quarantined_rates: list[ParsedCityRate] = Field(default_factory=list)
    raw_products_count: int = 0
    extraction_errors: list[str] = Field(default_factory=list)
