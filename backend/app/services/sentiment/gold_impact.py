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
    r"\bfed (?:holds?|keeps?)(?: (?:interest )?rates?)?(?: (?:steady|unchanged))?\b",
    r"\bfed (?:stays? put|tightening|hike fears?)\b",
    r"\brate hold\b",
    r"\binterest rates? unchanged\b",
    r"\bvotes? (?:10-2|\d+-\d+) in favor of rate hold\b",
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
    r"\bfed rate cut expectations?\b",
]

NEUTRAL_OR_MIXED_FED_PATTERNS = [
    r"\bfed (?:rate )?decision\b",
    r"\bfed meeting\b",
    r"\bfed signals?\b",
    r"\bfed day\b",
    r"\bfed outlook\b",
    r"\bahead of fed\b",
    r"\blook to fed\b",
    r"\bbrace for fed\b",
    r"\bfed loom(?:ed|s)\b",
    r"\bfed credibility\b",
    r"\bbreathing room from fed\b",
    r"\bbank of canada raises\b",
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
    r"\b(?:iran|ukraine|russia|middle east|gaza|israel|red sea) (?:war|conflict|tensions?|strikes?)\b",
    r"\bwar (?:costs?|fears?|and falling revenues?)\b",
    r"\bmilitary conflict\b",
    r"\bconflict escalates?\b",
    r"\bgeopolitical (?:tensions?|risks?|crisis)\b",
    r"\bairstrikes?\b",
    r"\bsanctions? (?:tighten|hit|widen|drain)\b",
    r"\bsafe-?haven (?:demand|buying|flows?|appeal)\b",
    r"\bmiddle east conflict\b",
]

INFLATION_MACRO_PATTERNS = [
    r"\boil (?:rall(?:y|ies)|jumps?|surges?|spikes?|above \$?100|rises?)\b",
    r"\bcrude\b",
    r"\boil-?fueled inflation\b",
    r"\binflation (?:fears?|concerns?|data|spikes?|heats? up)\b",
    r"\bcpi\b",
    r"\bpce\b",
    r"\bstagflation\b",
]

BULLISH_PHYSICAL_PATTERNS = [
    r"\bdiwali\b",
    r"\bdhanteras\b",
    r"\bkarwa chauth\b",
    r"\bfestival (?:demand|buying|season)\b",
    r"\bgold demand (?:jumps?|surges?|rebounds?|spikes?)\b",
    r"\bbargain (?:hunting|buyers?|buying)\b",
    r"\bcentral banks? (?:accumulation|buying|purchases?)\b",
    r"\brbi (?:gold|reserves?)\b",
    r"\bpboc (?:gold|reserves?)\b",
    r"\bjewelers? (?:stock up|buying)\b",
    r"\bbon targets\b",
]

PHYSICAL_OR_RETAIL_PATTERNS = [
    r"\bgold rate today\b",
    r"\bprices in (?:delhi|mumbai|kolkata|chennai|hyderabad|pune|west bengal|ahmedabad|kerala)\b",
    r"\bjeweller(?:y|s)?\b",
    r"\bcentral banks? (?:accumulation|buying|purchases?|selling|reserves?)\b",
    r"\b(?:rbi|pboc|kremlin|sovereign) (?:gold|reserves?)\b",
    r"\breserves? (?:hit lowest|lowest level|drain)\b",
    r"\bnon-oil exports\b",
]

BEARISH_MOMENTUM_PATTERNS = [
    r"\btechnical (?:sell-?off|breakdown|liquidation)\b",
    r"\bflash crash\b",
    r"\bstop-?loss triggered\b",
    r"\bprecious metals? retreat on technical\b",
]

BULLISH_MOMENTUM_PATTERNS = [
    r"\btechnical (?:analysis|breakout|surge)\b",
    r"\bcharts? (?:point|signal|indicate)\b",
    r"\bshort squeeze\b",
    r"\bgold hits record\b",
    r"\bbreak \$?\d+ to rally\b",
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
        rationale = "Hawkish Fed rate expectations, rate holds, or rising Treasury yields increase the opportunity cost of holding non-yielding bullion."
    elif any(re.search(p, text) for p in BULLISH_FED_PATTERNS):
        driver = GoldDriver.US_FED_RATES
        direction = "BULLISH"
        confidence = "HIGH"
        rationale = "Expectations of Fed rate cuts or pauses diminish real yield hurdles, supporting capital allocation to precious metals."
    elif any(re.search(p, text) for p in NEUTRAL_OR_MIXED_FED_PATTERNS):
        driver = GoldDriver.US_FED_RATES
        direction = "MIXED"
        confidence = "MEDIUM"
        rationale = "Federal Reserve interest rate decisions and monetary policy outlook dominate bullion positioning."

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
        rationale = "Heightened geopolitical friction, sanctions, or war risk accelerates safe-haven reserve and ETF accumulation."

    # 4. Inflation & Energy Shocks
    elif any(re.search(p, text) for p in INFLATION_MACRO_PATTERNS):
        driver = GoldDriver.INFLATION_MACRO
        direction = "BEARISH" if ("oil rally" in text or "oil rises" in text or "oil jumps" in text) else "MIXED"
        confidence = "MEDIUM"
        rationale = "Surging crude oil and energy inflation stoke persistent yields and delay rate cuts, or prompt stagflation hedging."

    # 5. Physical, Retail & Central Bank Demand
    elif any(re.search(p, text) for p in BULLISH_PHYSICAL_PATTERNS):
        driver = GoldDriver.PHYSICAL_AND_CENTRAL_BANK
        direction = "BULLISH"
        confidence = "HIGH"
        rationale = "Sovereign reserve accumulation or festive consumer bargain buying (Diwali, Dhanteras) provides a structural physical price floor."
    elif any(re.search(p, text) for p in PHYSICAL_OR_RETAIL_PATTERNS):
        driver = GoldDriver.PHYSICAL_AND_CENTRAL_BANK
        direction = "MIXED"
        confidence = "MEDIUM"
        rationale = "Physical bullion demand, domestic retail quotes, or central bank reserve management active in regional trading."

    # 6. Price Momentum & Technical Action
    elif any(re.search(p, text) for p in BULLISH_MOMENTUM_PATTERNS):
        driver = GoldDriver.MARKET_MOMENTUM
        direction = "BULLISH"
        confidence = "MEDIUM"
        rationale = "Short-term technical breakout or record price surge attracts trend-following futures buyers."
    elif any(re.search(p, text) for p in BEARISH_MOMENTUM_PATTERNS):
        driver = GoldDriver.MARKET_MOMENTUM
        direction = "BEARISH"
        confidence = "MEDIUM"
        rationale = "Downward price pressure or technical liquidation indicates active intraday profit-taking."

    # 7. Unmatched General Macroeconomic Commentary
    if direction == "UNCERTAIN":
        driver = GoldDriver.OTHER_MACRO
        if finbert_label.upper() == "POSITIVE" and finbert_score > 0.4:
            direction = "BULLISH"
            confidence = "LOW"
            rationale = "Positive general macroeconomic commentary; specific commodity transmission is broad."
        elif finbert_label.upper() == "NEGATIVE" and finbert_score < -0.4:
            direction = "BEARISH"
            confidence = "LOW"
            rationale = "Cautious general macroeconomic commentary; specific commodity transmission is broad."
        else:
            direction = "MIXED"
            confidence = "LOW"
            rationale = "General market and commodity commentary with balanced or neutral directional implications."

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
