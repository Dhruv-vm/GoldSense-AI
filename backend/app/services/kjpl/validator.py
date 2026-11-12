from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


VALIDATION_STATES = ("VALID", "SUSPECT", "QUARANTINED", "INVALIDATED")


@dataclass(frozen=True)
class ValidationOutcome:
    validation_status: str  # VALID | SUSPECT | QUARANTINED | INVALIDATED
    reason: Optional[str]
    product_weight_grams: float
    normalized_price_per_gram: Optional[float]


# Product-specific validation specifications (INR/g unless currency == USD)
PRODUCT_SPECS: dict[str, dict] = {
    "MJDTA_GOLD_24K": {
        "metal": "GOLD",
        "currency": "INR",
        "min_per_gram": 5000.0,
        "max_per_gram": 50000.0,
        "expected_purity": 0.999,
    },
    "MJDTA_GOLD_24K_GST": {
        "metal": "GOLD",
        "currency": "INR",
        "min_per_gram": 5000.0,
        "max_per_gram": 52000.0,
        "expected_purity": 0.999,
    },
    "MJDTA_SILVER": {
        "metal": "SILVER",
        "currency": "INR",
        "min_per_gram": 80.0,   # Strictly above USD/oz (~50-60) to reject LBMA USD contamination
        "max_per_gram": 1500.0,
        "expected_purity": 0.999,
    },
    "MJDTA_SILVER_GST": {
        "metal": "SILVER",
        "currency": "INR",
        "min_per_gram": 80.0,
        "max_per_gram": 1600.0,
        "expected_purity": 0.999,
    },
    "GOLD_1KG_9999": {
        "metal": "GOLD",
        "currency": "INR",
        "min_per_gram": 5000.0,
        "max_per_gram": 50000.0,
        "expected_purity": 0.9999,
    },
    "GOLD_100G_999": {
        "metal": "GOLD",
        "currency": "INR",
        "min_per_gram": 5000.0,
        "max_per_gram": 50000.0,
        "expected_purity": 0.999,
    },
    "SILVER_1KG_999": {
        "metal": "SILVER",
        "currency": "INR",
        "min_per_gram": 80.0,
        "max_per_gram": 1500.0,
        "expected_purity": 0.999,
    },
    "KJPL_GOLDDEC_INR_10G": {
        "metal": "GOLD",
        "currency": "INR",
        "min_per_gram": 5000.0,
        "max_per_gram": 50000.0,
        "expected_purity": 0.995,
    },
    "KJPL_SILVERDEC_INR_1KG": {
        "metal": "SILVER",
        "currency": "INR",
        "min_per_gram": 80.0,
        "max_per_gram": 1500.0,
        "expected_purity": 0.999,
    },
    "KJPL_SPOT_GOLD_USD": {
        "metal": "GOLD",
        "currency": "USD",
        "min_orig": 1000.0,
        "max_orig": 10000.0,
    },
    "KJPL_SPOT_SILVER_USD": {
        "metal": "SILVER",
        "currency": "USD",
        "min_orig": 15.0,
        "max_orig": 200.0,
    },
    "KJPL_SPOT_USDINR": {
        "metal": "FX",
        "currency": "INR",
        "min_orig": 60.0,
        "max_orig": 150.0,
    },
    "LBMA_GOLD_AM_USD": {
        "metal": "GOLD",
        "currency": "USD",
        "min_orig": 1000.0,
        "max_orig": 10000.0,
    },
    "LBMA_GOLD_PM_USD": {
        "metal": "GOLD",
        "currency": "USD",
        "min_orig": 1000.0,
        "max_orig": 10000.0,
    },
    "LBMA_SILVER_USD": {
        "metal": "SILVER",
        "currency": "USD",
        "min_orig": 15.0,
        "max_orig": 200.0,
    },
}


def resolve_weight_grams(unit: str, weight_value: float) -> float:
    """Resolve explicit product unit + weight numeric into exact grams."""
    u = (unit or "").strip().lower()
    if u in ("1g", "g", "gram", "grams"):
        return weight_value if weight_value > 0 else 1.0
    if u == "10g":
        return 10.0 if weight_value in (1.0, 10.0) else weight_value
    if u == "100g":
        return 100.0 if weight_value in (1.0, 100.0) else weight_value
    if u in ("1kg", "kg"):
        # If weight_value is 1.0 kg -> 1000.0 g; if already 1000.0 -> 1000.0 g
        return weight_value * 1000.0 if weight_value < 100.0 else weight_value
    if u == "oz":
        return 31.1034768
    return weight_value if weight_value > 0 else 1.0


def validate_bullion_observation(
    *,
    product_id: str,
    metal: str,
    currency: str,
    unit: str,
    weight_value: float,
    price: float | Decimal | None,
    source_product_id: str | None = None,
    previous_valid_per_gram: float | None = None,
) -> ValidationOutcome:
    """
    Strictly validate a bullion observation against product-specific bounds,
    weight/unit consistency, and historical anomaly checks.
    Never substitutes values or silently accepts USD/oz or weight/com_id artifacts.
    """
    weight_grams = resolve_weight_grams(unit, float(weight_value or 1.0))

    if price is None:
        return ValidationOutcome("QUARANTINED", "Price is missing/null.", weight_grams, None)

    p = float(price)
    if p <= 0:
        return ValidationOutcome("QUARANTINED", f"Non-positive price {p}.", weight_grams, None)

    # Guard against parsing source_product_id or raw weight number as price
    if source_product_id and source_product_id.isdigit() and abs(p - float(source_product_id)) < 1e-6:
        return ValidationOutcome("QUARANTINED", f"Price {p} equals raw com_id {source_product_id}.", weight_grams, None)
    if product_id == "GOLD_100G_999" and abs(p - 100.0) < 1e-6:
        return ValidationOutcome("QUARANTINED", "Price 100.0 equals 100g weight / com_display_purity artifact.", weight_grams, None)

    spec = PRODUCT_SPECS.get(product_id)
    if not spec:
        return ValidationOutcome("SUSPECT", f"Unregistered product_id '{product_id}'.", weight_grams, None)

    if spec["metal"] != metal.upper():
        return ValidationOutcome("QUARANTINED", f"Metal mismatch: expected {spec['metal']}, got {metal}.", weight_grams, None)
    if spec["currency"] != currency.upper():
        return ValidationOutcome("QUARANTINED", f"Currency mismatch: expected {spec['currency']}, got {currency}.", weight_grams, None)

    # International USD/oz or FX quotes
    if "min_orig" in spec:
        if not (spec["min_orig"] <= p <= spec["max_orig"]):
            return ValidationOutcome(
                "QUARANTINED",
                f"{product_id} price {p} {currency}/{unit} outside valid bounds [{spec['min_orig']}, {spec['max_orig']}].",
                weight_grams,
                None,
            )
        return ValidationOutcome("VALID", None, weight_grams, None)

    # INR bullion products -> compute normalized INR/gram
    per_gram = round(p / weight_grams, 2) if weight_grams > 0 else None
    if per_gram is None:
        return ValidationOutcome("QUARANTINED", "Cannot normalize per-gram price (invalid weight).", weight_grams, None)

    min_g = spec["min_per_gram"]
    max_g = spec["max_per_gram"]

    if not (min_g <= per_gram <= max_g):
        return ValidationOutcome(
            "QUARANTINED",
            f"Normalized rate ₹{per_gram:,.2f}/g (raw {p} {unit}) outside valid {spec['metal']} INR/g bounds [{min_g}, {max_g}].",
            weight_grams,
            per_gram,
        )

    # Anomaly detection against previous verified rate (if provided): flag >20% sudden jump as SUSPECT
    if previous_valid_per_gram and previous_valid_per_gram > 0:
        pct_diff = abs(per_gram - previous_valid_per_gram) / previous_valid_per_gram
        if pct_diff > 0.20:
            return ValidationOutcome(
                "SUSPECT",
                f"Sudden {pct_diff*100:.1f}% deviation from prior verified rate ₹{previous_valid_per_gram:,.2f}/g (new ₹{per_gram:,.2f}/g).",
                weight_grams,
                per_gram,
            )

    return ValidationOutcome("VALID", None, weight_grams, per_gram)
