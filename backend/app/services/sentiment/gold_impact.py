from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from app.services.sentiment.schemas import NewsCategory


# -----------------------------------------------------------------------------
# DRIVER CATEGORIES & MACROECONOMIC TRANSMISSION CHANNELS
# -----------------------------------------------------------------------------
class GoldDriver:
    US_FED_RATES = "US_FED_RATES"
    US_DOLLAR_FX = "US_DOLLAR_FX"
    INFLATION_MACRO = "INFLATION_MACRO"
    GEOPOLITICS_SAFE_HAVEN = "GEOPOLITICS_SAFE_HAVEN"
    PHYSICAL_AND_CENTRAL_BANK = "PHYSICAL_AND_CENTRAL_BANK"
    MARKET_MOMENTUM = "MARKET_MOMENTUM"
    OTHER_MACRO = "OTHER_MACRO"


# Regex patterns for directional commodity inference
BEARISH_FED_PATTERNS = [
    r"\bfed (?:favors?|eyes?|considers?|mulls?|weighs?) hikes?\b",
    r"\bfed (?:hikes?|raises?)(?: interest)? rates?\b",
    r"\bfavor hikes?\b",
    r"\bhawkish\b",
    r"\brate hikes?\b",
    r"\bhigher for longer\b",
    r"\brates? hold with limited guidance\b",
    r"\byields? (?:surge|climb|spike|rise|jump)\b",
    r"\bbond yields? tick higher\b",
    r"\bhotter than expected cpi\b",
]

BULLISH_FED_PATTERNS = [
    r"\bfed cuts?(?: interest)? rates?\b",
    r"\bcuts?(?: interest)? rates?\b",
    r"\brate cuts?\b",
    r"\bdovish\b",
    r"\bfed pauses?\b",
    r"\beasing\b",
    r"\byields? (?:tumble|fall|drop|slide|plunge)\b",
    r"\bcuts? expected\b",
]

BEARISH_DOLLAR_PATTERNS = [
    r"\bdollar (?:firms|strengthens|surges|gains|rallies|climbs)\b",
    r"\bstrong (?:us )?dollar\b",
    r"\bdxy (?:climbs|surges|rallies|jumps)\b",
    r"\bgreenback (?:firms|strengthens|gains)\b",
]

BULLISH_DOLLAR_PATTERNS = [
    r"\bdollar (?:slips|drops|falls|weakens|slides|tumbles)\b",
    r"\bweak (?:us )?dollar\b",
    r"\bdxy (?:drops|falls|slips|slides)\b",
    r"\brupee drops\b",
    r"\busdinr (?:surges|rallies|climbs)\b",
]

BULLISH_GEOPOLITICS_PATTERNS = [
    r"\bwar costs?\b",
    r"\bmilitary conflict\b",
    r"\bconflict escalates?\b",
    r"\bgeopolitical (?:tensions?|risks?|crisis)\b",
    r"\bairstrikes?\b",
    r"\bsanctions? (?:tighten|hit|widen)\b",
    r"\bsafe-?haven (?:demand|buying|flows?|appeal)\b",
    r"\bmiddle east conflict\b",
]

BULLISH_PHYSICAL_PATTERNS = [
    r"\bgold demand (?:jumps?|surges?|rebounds?|spikes?)\b",
    r"\bbargain (?:hunting|buyers?|buying)\b",
    r"\bcentral banks? (?:accumulation|buying|purchases?)\b",
    r"\brbi (?:gold|reserves?)\b",
    r"\bpboc (?:gold|reserves?)\b",
    r"\bfestival (?:demand|buying|season)\b",
    r"\bdhanteras\b",
    r"\bjewelers? (?:stock up|buying)\b",
]

BEARISH_MOMENTUM_PATTERNS = [
    r"\bgold (?:falls?|drops?|slides?|tumbles?|declines?|slips?|edges? lower)\b",
    r"\bgold prices? (?:fall|drop|slide|tumble|decline|retreat)\b",
    r"\bprecious metals? retreat\b",
    r"\bsell-?off in gold\b",
    r"\bgold under pressure\b",
]

BULLISH_MOMENTUM_PATTERNS = [
    r"\bgold (?:rallies|surges?|jumps?|climbs?|rebounds?|soars?)\b",
    r"\bgold prices? (?:rise|surge|jump|climb|rebound|soar)\b",
    r"\bbullion (?:rallies|extends gains?|rises)\b",
    r"\bgold hits record\b",
]


def extract_cluster_key(title: str) -> str:
    """
    Extracts a normalized semantic cluster key to deduplicate syndicated coverage.
    Strips publisher suffixes and keeps the core first 5-6 informative tokens.
    """
    clean = re.sub(r"\s+[-|–—]\s+[A-Za-z0-9\s.&]+$", "", title.strip().lower())
    clean = re.sub(r"[^\w\s]", "", clean)
    words = [w for w in clean.split() if w not in ("a", "an", "the", "in", "on", "at", "to", "for", "of", "and")]
    return " ".join(words[:5]) if len(words) >= 5 else clean


def evaluate_gold_impact(
    title: str,
    published_at: datetime,
    finbert_label: str = "neutral",
    finbert_score: float = 0.0,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    """
    Evaluates the bullion-specific directional impact and macroeconomic driver of an article.
    Distinguishes generic financial sentiment from directional gold implications.
    """
    now = reference_time or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_utc = published_at.replace(tzinfo=timezone.utc)
    else:
        published_utc = published_at.astimezone(timezone.utc)

    # Compute age and freshness
    age_seconds = max(0.0, (now - published_utc).total_seconds())
    age_hours = age_seconds / 3600.0

    # Exponential time-decay weight (half-life ~ 12 hours)
    # At 0h -> 1.0, 6h -> 0.61, 12h -> 0.37, 24h -> 0.14
    freshness_weight = round(math.exp(-age_hours / 12.0), 3)

    if age_hours < 1.0:
        age_display = f"{int(age_seconds // 60)}m ago"
    elif age_hours < 24.0:
        age_display = f"{age_hours:.1f}h ago"
    else:
        age_display = f"{age_hours / 24.0:.1f}d ago"

    text = title.lower()

    # Rule-based directional matching grounded in commodity economics
    driver = GoldDriver.OTHER_MACRO
    direction = "UNCERTAIN"
    confidence = "LOW"
    rationale = "General macroeconomic or market commentary; direct directional gold impact is uncertain."

    # 1. Fed & Rates
    if any(re.search(p, text) for p in BEARISH_FED_PATTERNS):
        driver = GoldDriver.US_FED_RATES
        direction = "BEARISH"
        confidence = "HIGH"
        rationale = "Hawkish Fed rate expectations or rising Treasury yields increase the opportunity cost of holding non-yielding bullion."
    elif any(re.search(p, text) for p in BULLISH_FED_PATTERNS):
        driver = GoldDriver.US_FED_RATES
        direction = "BULLISH"
        confidence = "HIGH"
        rationale = "Expectations of Fed rate cuts or pauses diminish real yield hurdles, supporting capital allocation to precious metals."

    # 2. US Dollar & Currency
    elif any(re.search(p, text) for p in BEARISH_DOLLAR_PATTERNS):
        driver = GoldDriver.US_DOLLAR_FX
        direction = "BEARISH"
        confidence = "HIGH"
        rationale = "A stronger US Dollar increases the acquisition cost of dollar-denominated bullion for international buyers."
    elif any(re.search(p, text) for p in BULLISH_DOLLAR_PATTERNS):
        driver = GoldDriver.US_DOLLAR_FX
        direction = "BULLISH"
        confidence = "MEDIUM"
        rationale = "Dollar softening or Rupee depreciation enhances local bullion value and lowers foreign buyer cost."

    # 3. Geopolitics & Safe-Haven
    elif any(re.search(p, text) for p in BULLISH_GEOPOLITICS_PATTERNS):
        driver = GoldDriver.GEOPOLITICS_SAFE_HAVEN
        direction = "BULLISH"
        confidence = "HIGH"
        rationale = "Heightened geopolitical friction or war risk accelerates safe-haven reserve and ETF accumulation."

    # 4. Physical & Central Bank Demand
    elif any(re.search(p, text) for p in BULLISH_PHYSICAL_PATTERNS):
        driver = GoldDriver.PHYSICAL_AND_CENTRAL_BANK
        direction = "BULLISH"
        confidence = "HIGH"
        rationale = "Sovereign reserve accumulation or physical consumer bargain buying provides a structural physical price floor."

    # 5. Price Momentum & Technical Action
    elif any(re.search(p, text) for p in BULLISH_MOMENTUM_PATTERNS):
        driver = GoldDriver.MARKET_MOMENTUM
        direction = "BULLISH"
        confidence = "MEDIUM"
        rationale = "Short-term technical breakout or upward price momentum attracts trend-following futures buyers."
    elif any(re.search(p, text) for p in BEARISH_MOMENTUM_PATTERNS):
        driver = GoldDriver.MARKET_MOMENTUM
        direction = "BEARISH"
        confidence = "MEDIUM"
        rationale = "Downward price pressure or technical liquidation indicates active intraday profit-taking."

    # Contextual resolution using FinBERT as weak prior if neutral/unmatched
    if direction == "UNCERTAIN":
        if "gold" in text or "bullion" in text or "xauusd" in text:
            driver = GoldDriver.MARKET_MOMENTUM
            if finbert_label.upper() == "POSITIVE" and finbert_score > 0.4:
                direction = "BULLISH"
                confidence = "LOW"
                rationale = "Positive market commentary on bullion, though specific macro transmission channel is broad."
            elif finbert_label.upper() == "NEGATIVE" and finbert_score < -0.4:
                direction = "BEARISH"
                confidence = "LOW"
                rationale = "Negative price commentary on bullion, reflecting short-term caution."
            else:
                direction = "MIXED"
                confidence = "LOW"
                rationale = "Bullion mentioned with balanced or offsetting drivers; market direction is neutral or consolidating."

    cluster_key = extract_cluster_key(title)

    return {
        "title": title,
        "cluster_key": cluster_key,
        "published_at": published_utc.isoformat(),
        "age_hours": round(age_hours, 2),
        "age_display": age_display,
        "freshness_weight": freshness_weight,
        "driver_category": driver,
        "directional_implication": direction,
        "confidence": confidence,
        "evidence_rationale": rationale,
        "finbert_tone": finbert_label.lower(),
        "finbert_score": finbert_score,
    }
