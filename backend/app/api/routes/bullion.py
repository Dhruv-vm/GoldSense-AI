from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Query

from app.services.bullion_service import (
    get_all_cities,
    get_latest_city_rates,
    get_city_comparison,
    get_bullion_summary,
    get_bullion_history,
    normalize_city_code,
)

router = APIRouter(prefix="/api/bullion", tags=["Bullion Intelligence"])


@router.get("/latest")
def get_bullion_latest() -> dict[str, Any]:
    """
    Get top-level VMD Bullion intelligence summary:
    Chennai benchmark 24K, silver, wholesale 1KG, 5-city retail tape, and parity metrics.
    """
    return get_bullion_summary()


@router.get("/cities")
def get_bullion_cities() -> list[dict[str, Any]]:
    """
    Get all supported cities (Chennai, Bengaluru, Mumbai, Coimbatore, Hyderabad, All India)
    with default flags and sort orders.
    """
    return get_all_cities()


@router.get("/city-rates")
def get_bullion_city_rates(
    city: str | None = Query(None, description="Optional city code filter (e.g. chennai, bengaluru, mumbai)"),
    metal: str | None = Query(None, description="Optional metal filter (GOLD or SILVER)"),
) -> list[dict[str, Any]]:
    """
    Get all latest verified city rates across products, with exact timestamps,
    previous prices, and net price change.
    """
    return get_latest_city_rates(city_code=city, metal=metal)


@router.get("/city-rates/{city}")
def get_single_city_rates(
    city: str,
    metal: str | None = Query(None, description="Optional metal filter (GOLD or SILVER)"),
) -> list[dict[str, Any]]:
    """
    Get latest verified rates for a specific city (e.g. /api/bullion/city-rates/bengaluru).
    """
    norm_city = normalize_city_code(city)
    rates = get_latest_city_rates(city_code=norm_city, metal=metal)
    if not rates:
        raise HTTPException(status_code=404, detail=f"No bullion rates found for city '{city}'")
    return rates


@router.get("/comparison")
def get_bullion_city_comparison() -> dict[str, Any]:
    """
    Get institutional 5-city side-by-side comparison for standard 100g 999 gold bar.
    Baseline benchmark is Chennai. Computes per-gram equivalent, spread in INR, and spread in %.
    """
    return get_city_comparison()


@router.get("/history")
def get_bullion_observations_history(
    city: str | None = Query(None, description="City code (e.g. CHENNAI, BENGALURU)"),
    product_id: str | None = Query(None, description="Product ID (e.g. GOLD_100G_999, MJDTA_GOLD_24K)"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> list[dict[str, Any]]:
    """
    Get historical audit log of price observations for charting and model analysis.
    """
    return get_bullion_history(city_code=city, product_id=product_id, limit=limit, offset=offset)
