from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from app.services.sentiment.provenance import (
    CLUSTER_VERSION,
    SENTIMENT_VERSION,
    compute_story_cluster_id,
    extract_story_cluster_key,
)
from app.services.sentiment.schemas import (
    GeneralTone,
    GoldImpactDirection,
    GoldMacroDriver,
    MacroSurprise,
)


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


# Explicit city/today price bulletins checked BEFORE directional scoring (F-07)
GOLD_PRICE_REPORT_PATTERNS = [
    r"\bgold (?:rate|price)s? today\b",
    r"\bsilver (?:rate|price)s? today\b",
    r"\bcheck (?:latest )?(?:22k|24k|18k)? ?(?:gold|silver) (?:rate|price)s?\b",
    r"\bprices? in (?:delhi|mumbai|kolkata|chennai|hyderabad|bengaluru|coimbatore|pune|ahmedabad|kerala)\b",
    r"\b(?:22k|24k) gold (?:rate|price)s?(?: in| today)?\b",
    r"\bmcx gold (?:futures? )?(?:closes?|opens?|trades?|edges?)\b",
]

_DESCRIPTIVE_MOVE_RE = re.compile(
    r"\b(?:spot )?gold (?:edges?|ticks?|slips?|dips?|falls?|rises?|gains?|climbs?|steadies?|trades?|hits? record high) "
    r"(?:slightly )?(?:up|down|higher|lower|flat)?\b"
)
# A3-9 / F-07 over-exclusion: a price-bulletin prefix ("Gold price today: ...") must not
# swallow a headline that carries an actual macro / policy / FX / geopolitical event.
_MACRO_CONTENT_RE = re.compile(
    r"\b(?:fed|fomc|powell|ecb|rbi|boj|boe|pboc|repo rate|rate[- ](?:cut|hike)s?|yields?|cpi|pce|inflation|"
    r"dollar|dxy|greenback|rupee|usdinr|war|conflict|sanctions?|safe-?haven|geopolitic\w*|central banks?|"
    r"etfs?|(?:import|customs) duty|tariffs?|crude|oil)\b"
)
_CAUSAL_MACRO_GUARD_RE = re.compile(
    r"\b(?:after|amid|as|on|ahead of)\b.*\b(?:fed|powell|ecb|rbi|rate|yields?|cpi|inflation|dollar|dxy|rupee|war|conflict|sanctions|safe-?haven|central bank|etf|duty|tariff)\b"
)

# Negated/cooled hike phrases -> DOVISH / BULLISH (F-05)
DOVISH_NEGATED_HIKE_PATTERNS = [
    r"\b(?:cools?|eases?|fades?|dampens?|reduces?|trims?|scales? back|dials? back|pares?(?: back)?|eliminates?) (?:bets (?:on )?|odds (?:of )?|fears (?:of )?)?(?:fed |us )?(?:interest )?rate hikes?\b",
    r"\b(?:fed )?(?:rate )?hike (?:bets|fears|odds|expectations?) (?:cool|ease|fade|drop|fall|slip|tumble|diminish|recede)\b",
    r"\bfed (?:pauses?|skips?|halts?|ends?) (?:interest )?rate hikes?\b",
    r"\bno (?:more )?(?:fed )?rate hikes?\b",
    r"\brate hikes? (?:off the table|unlikely)\b",
    r"\bsofter (?:us )?(?:cpi|pce|inflation)\b",
    r"\bcooler (?:us )?(?:cpi|pce|inflation)\b",
]

# Negated cut phrases -> HAWKISH / BEARISH (F-05)
HAWKISH_NEGATED_CUT_PATTERNS = [
    r"\b(?:rate[- ])?cuts? (?:are |is )?(?:not on the table|off the table|ruled out|unlikely|delayed|pushed back)\b",
    r"\b(?:rules? out|push(?:es|ing)? back (?:on|against)|pushback (?:on|against)|delays?|rejects?|cools? on|"
    r"(?:in )?no hurry to|not in a hurry to) (?:fed |further |more )?(?:interest )?(?:rate[- ])?cut(?:s|ting)?\b",
    r"\bno (?:more |further |immediate )?(?:rate[- ])?cuts?\b",
    r"\b(?:won't|will not|would not|wouldn't|not ready to|not going to) cut(?: interest)? rates?\b",
    r"\bfewer (?:rate[- ])?cuts?\b",
    r"\b(?:rate[- ])?cut (?:bets|odds|expectations?|hopes) (?:fade|cool|drop|tumble|recede|dim)\b",
]

BEARISH_FED_PATTERNS = [
    r"\bfed (?:unexpectedly |reportedly |widely )?(?:hikes?|raises?|favors? hiking|eyes? hiking)(?: interest)? rates?\b",
    r"\bfed (?:favors?|eyes?|considers?|mulls?|weighs?) hikes?\b",
    r"\bfavor hikes?\b",
    r"\bhawkish\b",
    r"\brate hikes?\b",
    r"\bhigher for longer\b",
    r"\brates? hold with limited guidance\b",
    r"\bfed (?:holds?|keeps?) (?:interest )?rates?(?: (?:steady|unchanged))?(?=.*limited guidance)\b",
    r"\bfed (?:stays? put|tightening|hike fears?)\b",
    r"\bvotes? (?:10-2|\d+-\d+) in favor of rate hold\b",
    r"\byields? (?:surge|climb|spike|rise|jump)\b",
    r"\b(?:rising|higher|surging|climbing|jumping) (?:bond |treasury )?yields?\b",
    r"\bbond yields? tick higher\b",
    r"\btreasury yields? (?:rise|surge|climb|jump)\b",
    r"\bhotter than expected cpi\b",
    r"\b\d+\s*(?:bps|bp|basis[- ]points?) (?:rate )?hikes?\b",
]

BULLISH_FED_PATTERNS = [
    r"\b\d+\s*(?:bps|bp|basis[- ]points?) (?:rate )?cuts?\b",
    r"\bsurprise (?:rate )?cuts?\b",
    r"\bfed (?:unexpectedly |reportedly )?cuts?(?: interest)? rates?\b",
    r"\bfed rate cuts?\b",
    r"\brate cuts?\b",
    r"\bdovish\b",
    r"\bfed pauses?\b",
    r"\beasing\b",
    r"\byields? (?:tumble|fall|drop|slide|plunge)\b",
    r"\btreasury yields? (?:fall|drop|slide|ease)\b",
    r"\bcuts? expected\b",
    r"\bfed rate cut expectations?\b",
]

# A Fed action (cut/hike/hold) that the headline itself calls expected carries no
# incremental policy surprise for gold (F-05 residual).
FED_POLICY_ACTION_PATTERNS = [
    r"\b(?:fed|fomc)(?: \w+)? (?:cuts?|hikes?|raises?|lowers?|holds?|keeps?|leaves?)\b",
]

NEUTRAL_AS_EXPECTED_FED_PATTERNS = [
    r"\bfed (?:holds?|keeps?|leaves?) (?:interest )?rates? (?:steady|unchanged)(?: as expected| in line with expectations)\b",
]

INSUFFICIENT_CUE_FED_PATTERNS = [
    r"\bahead of (?:the )?fed\b",
    r"\blook to fed\b",
    r"\bbrace for fed\b",
    r"\bfed (?:rate )?decision due\b",
    r"\bfed meeting\b",
    r"\bfed outlook\b",
    r"\bfed signals?\b",
    r"\bfed day\b",
    r"\bfed credibility\b",
]

# Non-Fed Central Bank policy decisions explicitly separated (F-05)
RBI_HAWKISH_PATTERNS = [
    r"\brbi (?:unexpectedly )?(?:hikes?|raises?) (?:the )?(?:repo )?rates?\b",
]
RBI_DOVISH_PATTERNS = [
    r"\brbi (?:unexpectedly )?cuts? (?:the )?(?:repo )?rates?\b",
]
# Foreign (non-Fed, non-RBI) central-bank POLICY moves have an ambiguous net effect on
# INR gold (rate channel vs USD channel), so they are tagged OTHER_MACRO / UNKNOWN rather
# than given a direction or conflated with central-bank GOLD BUYING (F-05 residual).
NON_FED_CB_NAME_RE = re.compile(
    r"\b(?:ecb|boe|boj|pboc|snb|bank of england|bank of japan|bank of canada|people's bank of china|"
    r"european central bank|swiss national bank)\b"
)
NON_FED_CB_POLICY_PATTERNS = [
    r"\b(?:ecb|boe|boj|pboc|snb|bank of england|bank of japan|bank of canada|european central bank|swiss national bank)"
    r"(?: \w+)? (?:unexpectedly )?(?:cuts?|hikes?|raises?|lowers?|holds?|keeps?)(?: (?:interest|policy|key))?(?: rates?)?\b",
]
_FED_NAME_RE = re.compile(r"\b(?:fed|fomc|powell|federal reserve)\b")

# Headline reports gold failing to follow the implied direction -> do not emit that direction.
FAILED_RALLY_RE = re.compile(r"\bgold (?:fails?|struggles?|unable) to (?:rally|rise|gain|climb|hold gains|extend gains)\b|\bgold shrugs off\b")
FAILED_DROP_RE = re.compile(r"\bgold (?:fails?|struggles?|unable) to (?:fall|drop|decline|extend losses)\b")

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
]

BULLISH_INR_PATTERNS = [
    r"\brupee (?:drops|falls|weakens|slips|hits record low|hits all-time low)\b",
    r"\busdinr (?:surges|rallies|climbs|jumps)\b",
    r"\bweak(?:er)? rupee\b",
]

BEARISH_INR_PATTERNS = [
    r"\brupee (?:strengthens|rallies|gains|climbs|appreciates|firms)\b",
    r"\busdinr (?:drops|falls|slips|slides)\b",
]

BULLISH_IMPORT_DUTY_PATTERNS = [
    r"\b(?:hikes?|raises?|increases?) (?:customs?|import) duty on gold\b",
    r"\bgold (?:import|customs) duty hike\b",
]

BEARISH_IMPORT_DUTY_PATTERNS = [
    r"\b(?:cuts?|slashes?|reduces?|lowers?) (?:customs?|import) duty on gold\b",
    r"\bgold (?:import|customs) duty cut\b",
]

BULLISH_ETF_PATTERNS = [
    r"\bgold etfs? (?:see |post |record )?inflows?\b",
    r"\betf inflows? into gold\b",
]

BEARISH_ETF_PATTERNS = [
    r"\bgold etfs? (?:see |post |record )?outflows?\b",
    r"\betf outflows? from gold\b",
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
    r"\binflation (?:fears?|concerns?|spikes?|heats? up)\b",
    r"\bhotter cpi\b",
    r"\bstagflation\b",
]

BULLISH_CENTRAL_BANK_PATTERNS = [
    r"\bcentral banks? (?:gold )?(?:accumulation|buying|purchases?|adds?|buys?|boosts?)\b",
    r"\b(?:rbi|pboc|central bank)s? (?:gold )?reserves? (?:jump|rise|increase|grow|hit (?:fresh )?high|climb)\b",
    r"\b(?:rbi|pboc|central bank)s? (?:buys?|adds?) (?:more )?gold\b",
    r"\bsovereign gold (?:accumulation|buying|purchases?)\b",
    r"\bbon targets\b",
]

BEARISH_CENTRAL_BANK_PATTERNS = [
    r"\bcentral banks? (?:sells?|selling|cuts?|reduces?|halts? (?:gold )?(?:buying|purchases?)|pauses? (?:gold )?buying)\b",
    r"\b(?:rbi|pboc|central bank)s? gold reserves? (?:fall|drop|decline|shrink|hit lowest|drain)\b",
]

BULLISH_PHYSICAL_PATTERNS = [
    r"\bdiwali\b",
    r"\bdhanteras\b",
    r"\bkarwa chauth\b",
    r"\bfestival (?:demand|buying|season)\b",
    r"\bgold demand (?:jumps?|surges?|rebounds?|spikes?|steady)\b",
    r"\bjewelers? (?:stock up|buying)\b",
    r"\bjewelry retailers? report (?:steady|strong|brisk) (?:bullion )?demand\b",
    r"\bbargain (?:hunting|buyers?|buying)\b",
]

BEARISH_PHYSICAL_PATTERNS = [
    r"\bgold demand (?:slumps?|drops?|falls?|plunge|weakens?)\b",
    r"\bphysical (?:demand )?slump\b",
]

PHYSICAL_UNSPECIFIED_PATTERNS = [
    r"\bjeweller(?:y|s)?\b",
    r"\bcentral banks? reserves?\b",
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

_SURPRISE_RULES: list[tuple[list[str], MacroSurprise]] = [
    (
        [
            r"\bhotter than expected\b",
            r"\bhawkish surprise\b",
            r"\bunexpected(?:ly)? (?:hike|raises?|tighten)\b",
            r"\bfaster inflation\b",
        ],
        MacroSurprise.HAWKISH_SURPRISE,
    ),
    (
        [
            r"\bcooler than expected\b",
            r"\bsofter (?:than expected )?(?:us )?(?:inflation|cpi|pce)\b",
            r"\bdovish surprise\b",
            r"\bunexpected(?:ly)? cut\b",
        ],
        MacroSurprise.DOVISH_SURPRISE,
    ),
    (
        [
            r"\bbetter than expected\b",
            r"\bstronger than expected\b",
            r"\bbeats? (?:estimates|forecasts|expectations)\b",
        ],
        MacroSurprise.POSITIVE_SURPRISE,
    ),
    (
        [
            r"\bweaker than expected\b",
            r"\bworse than expected\b",
            r"\bmisses? (?:estimates|forecasts|expectations)\b",
        ],
        MacroSurprise.NEGATIVE_SURPRISE,
    ),
    (
        [
            r"\bin line with expectations\b",
            r"\bas expected\b",
            r"\bwidely expected\b",
        ],
        MacroSurprise.AS_EXPECTED,
    ),
]


def extract_cluster_key(title: str) -> str:
    return extract_story_cluster_key(title)


def _normalize_general_tone(finbert_label: str | None) -> GeneralTone:
    raw = (finbert_label or "").strip().upper()
    if raw == "POSITIVE":
        return GeneralTone.POSITIVE
    if raw == "NEGATIVE":
        return GeneralTone.NEGATIVE
    if raw == "NEUTRAL":
        return GeneralTone.NEUTRAL
    return GeneralTone.UNKNOWN


def _detect_surprise(text: str) -> MacroSurprise:
    for patterns, tag in _SURPRISE_RULES:
        if any(re.search(p, text) for p in patterns):
            return tag
    return MacroSurprise.UNKNOWN


def _is_price_report_first(text: str) -> bool:
    if any(re.search(p, text) for p in GOLD_PRICE_REPORT_PATTERNS) and not _MACRO_CONTENT_RE.search(text):
        return True
    if _DESCRIPTIVE_MOVE_RE.search(text) and not _CAUSAL_MACRO_GUARD_RE.search(text):
        return True
    return False


def _match_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _mask_patterns(patterns: list[str], text: str) -> tuple[bool, str]:
    matched = False
    masked = text
    for p in patterns:
        if re.search(p, masked):
            matched = True
            masked = re.sub(p, " ", masked)
    return matched, masked


def evaluate_gold_impact(
    title: str,
    published_at: datetime,
    finbert_label: str = "UNKNOWN",
    finbert_score: float = 0.0,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    """
    Evaluate separated gold-specific directional impact with entity, negation,
    surprise, and price-report precedence safeguards (F-05, F-06, F-07).
    """
    now = reference_time or datetime.now(timezone.utc)
    published_utc = (
        published_at.replace(tzinfo=timezone.utc)
        if published_at.tzinfo is None
        else published_at.astimezone(timezone.utc)
    )

    age_seconds = max(0.0, (now - published_utc).total_seconds())
    age_hours = age_seconds / 3600.0
    freshness_weight = round(math.exp(-age_hours / 12.0), 3)
    if age_hours < 1.0:
        age_display = f"{int(age_seconds // 60)}m ago"
    elif age_hours < 24.0:
        age_display = f"{age_hours:.1f}h ago"
    else:
        age_display = f"{age_hours / 24.0:.1f}d ago"

    text = title.lower()
    general_tone = _normalize_general_tone(finbert_label)
    surprise = _detect_surprise(text)

    # F-07: Check explicit price-report bulletins first (while allowing causal macro headlines through)
    if _is_price_report_first(text):
        story_cluster_id, cluster_key = compute_story_cluster_id(title, published_utc, CLUSTER_VERSION)
        return {
            "title": title,
            "cluster_key": cluster_key,
            "story_cluster_id": story_cluster_id,
            "cluster_version": CLUSTER_VERSION,
            "published_at": published_utc.isoformat(),
            "age_hours": round(age_hours, 2),
            "age_display": age_display,
            "freshness_weight": freshness_weight,
            "general_tone": general_tone.value,
            "gold_impact": GoldImpactDirection.NEUTRAL.value,
            "driver": GoldMacroDriver.GOLD_PRICE_REPORT.value,
            "surprise": surprise.value,
            "is_price_report": True,
            "sentiment_version": SENTIMENT_VERSION,
            "driver_category": GoldDriver.OTHER_MACRO,
            "directional_implication": GoldImpactDirection.NEUTRAL.value,
            "confidence": "MEDIUM",
            "evidence_rationale": "Descriptive daily bullion rate/price recap without a forward-looking causal macro driver.",
            "finbert_tone": general_tone.value.lower(),
            "finbert_score": finbert_score,
        }

    bullish_signals: list[tuple[GoldMacroDriver, str, str, str]] = []
    bearish_signals: list[tuple[GoldMacroDriver, str, str, str]] = []
    neutral_driver: tuple[GoldMacroDriver, str, str] | None = None
    uncertain_driver: tuple[GoldMacroDriver, str, str] | None = None

    # First check explicit negated Fed hike/cut phrases and mask them to prevent substring false positives (F-05)
    dovish_neg_matched, text_after_neg = _mask_patterns(DOVISH_NEGATED_HIKE_PATTERNS, text)
    if dovish_neg_matched:
        bullish_signals.append((GoldMacroDriver.FED_POLICY, GoldDriver.US_FED_RATES, "HIGH", "Cooling rate-hike expectations or softer inflation reduce real-yield headwinds on gold."))

    hawkish_neg_matched, text_clean = _mask_patterns(HAWKISH_NEGATED_CUT_PATTERNS, text_after_neg)
    if hawkish_neg_matched:
        bearish_signals.append((GoldMacroDriver.FED_POLICY, GoldDriver.US_FED_RATES, "HIGH", "Pushback against rate cuts sustains restrictive opportunity-cost pressure on non-yielding gold."))

    # Check non-Fed central bank policy FIRST and mask matched phrases so e.g. 'ECB cuts' does not misattribute to Fed
    if _match_any(RBI_HAWKISH_PATTERNS, text_clean):
        bearish_signals.append((GoldMacroDriver.INR, GoldDriver.US_DOLLAR_FX, "MEDIUM", "RBI repo rate hike supports INR and domestic yields, softening domestic bullion parity."))
        _, text_clean = _mask_patterns(RBI_HAWKISH_PATTERNS, text_clean)
    if _match_any(RBI_DOVISH_PATTERNS, text_clean):
        bullish_signals.append((GoldMacroDriver.INR, GoldDriver.US_DOLLAR_FX, "MEDIUM", "RBI repo rate cut lowers domestic real yields and softens INR support."))
        _, text_clean = _mask_patterns(RBI_DOVISH_PATTERNS, text_clean)
    foreign_cb_only = bool(NON_FED_CB_NAME_RE.search(text_clean)) and not _FED_NAME_RE.search(text_clean)
    if _match_any(NON_FED_CB_POLICY_PATTERNS, text_clean) or foreign_cb_only:
        uncertain_driver = (GoldMacroDriver.OTHER_MACRO, GoldDriver.OTHER_MACRO, "Foreign central-bank policy move: net transmission to INR gold (rates vs USD channel) is ambiguous.")
        _, text_clean = _mask_patterns(NON_FED_CB_POLICY_PATTERNS, text_clean)

    fed_as_expected = (
        surprise == MacroSurprise.AS_EXPECTED
        and not dovish_neg_matched
        and not hawkish_neg_matched
        and _match_any(FED_POLICY_ACTION_PATTERNS, text_clean)
    )

    # Fed policy & US interest rates (distinguish expected hold vs hawkish surprise/guidance)
    if foreign_cb_only:
        pass
    elif fed_as_expected:
        neutral_driver = (GoldMacroDriver.FED_POLICY, GoldDriver.US_FED_RATES, "Fed action was described as expected; no incremental policy surprise.")
    elif _match_any(NEUTRAL_AS_EXPECTED_FED_PATTERNS, text_clean) and not _match_any(BEARISH_FED_PATTERNS, text_clean):
        neutral_driver = (GoldMacroDriver.FED_POLICY, GoldDriver.US_FED_RATES, "Fed held rates as expected without an incremental policy surprise.")
    elif _match_any(BULLISH_FED_PATTERNS, text_clean):
        drv = GoldMacroDriver.US_INTEREST_RATES if ("yield" in text_clean and "fed" not in text_clean) else GoldMacroDriver.FED_POLICY
        bullish_signals.append((drv, GoldDriver.US_FED_RATES, "HIGH", "Fed rate cuts or falling real yields reduce the opportunity cost of holding gold."))
    if not foreign_cb_only and not fed_as_expected and _match_any(BEARISH_FED_PATTERNS, text_clean):
        drv = GoldMacroDriver.US_INTEREST_RATES if ("yield" in text_clean and "fed" not in text_clean) else GoldMacroDriver.FED_POLICY
        bearish_signals.append((drv, GoldDriver.US_FED_RATES, "HIGH", "Hawkish Fed rate expectations, rate hikes/holds, or rising Treasury yields increase the opportunity cost of holding non-yielding bullion."))
    if not bullish_signals and not bearish_signals and not neutral_driver and _match_any(INSUFFICIENT_CUE_FED_PATTERNS, text_clean):
        uncertain_driver = (GoldMacroDriver.FED_POLICY, GoldDriver.US_FED_RATES, "Federal Reserve preview/commentary lacks a realized hawkish or dovish surprise.")

    # Import duty
    if _match_any(BULLISH_IMPORT_DUTY_PATTERNS, text):
        bullish_signals.append((GoldMacroDriver.INDIA_IMPORT_DUTY_POLICY, GoldDriver.PHYSICAL_AND_CENTRAL_BANK, "HIGH", "Higher Indian import duty raises landed domestic bullion prices."))
    if _match_any(BEARISH_IMPORT_DUTY_PATTERNS, text):
        bearish_signals.append((GoldMacroDriver.INDIA_IMPORT_DUTY_POLICY, GoldDriver.PHYSICAL_AND_CENTRAL_BANK, "HIGH", "Lower Indian import duty reduces domestic landed bullion cost."))

    # INR & USD FX
    if _match_any(BULLISH_INR_PATTERNS, text):
        bullish_signals.append((GoldMacroDriver.INR, GoldDriver.US_DOLLAR_FX, "MEDIUM", "Rupee depreciation increases INR-denominated gold import parity."))
    if _match_any(BEARISH_INR_PATTERNS, text):
        bearish_signals.append((GoldMacroDriver.INR, GoldDriver.US_DOLLAR_FX, "MEDIUM", "Rupee appreciation reduces INR landed price pressure on gold."))
    if _match_any(BULLISH_DOLLAR_PATTERNS, text):
        bullish_signals.append((GoldMacroDriver.USD, GoldDriver.US_DOLLAR_FX, "MEDIUM", "Dollar weakness lowers global acquisition cost for bullion buyers."))
    if _match_any(BEARISH_DOLLAR_PATTERNS, text):
        bearish_signals.append((GoldMacroDriver.USD, GoldDriver.US_DOLLAR_FX, "HIGH", "A stronger US Dollar increases the acquisition cost of dollar-denominated bullion."))

    # Geopolitics
    if _match_any(BULLISH_GEOPOLITICS_PATTERNS, text):
        bullish_signals.append((GoldMacroDriver.GEOPOLITICS, GoldDriver.GEOPOLITICS_SAFE_HAVEN, "HIGH", "Geopolitical conflict or safe-haven demand supports gold inflows."))

    # Central bank reserve accumulation vs selling & physical demand
    if _match_any(BULLISH_CENTRAL_BANK_PATTERNS, text):
        bullish_signals.append((GoldMacroDriver.CENTRAL_BANKS, GoldDriver.PHYSICAL_AND_CENTRAL_BANK, "HIGH", "Sovereign central bank reserve buying adds physical structural demand."))
    if _match_any(BEARISH_CENTRAL_BANK_PATTERNS, text):
        bearish_signals.append((GoldMacroDriver.CENTRAL_BANKS, GoldDriver.PHYSICAL_AND_CENTRAL_BANK, "HIGH", "Central bank gold reserve sales or paused purchases weigh on physical demand."))
    if _match_any(BULLISH_PHYSICAL_PATTERNS, text):
        bullish_signals.append((GoldMacroDriver.INDIAN_PHYSICAL_DEMAND, GoldDriver.PHYSICAL_AND_CENTRAL_BANK, "HIGH", "Festive and retail physical bullion demand provides physical price support."))
    if _match_any(BEARISH_PHYSICAL_PATTERNS, text):
        bearish_signals.append((GoldMacroDriver.INDIAN_PHYSICAL_DEMAND, GoldDriver.PHYSICAL_AND_CENTRAL_BANK, "MEDIUM", "Weak physical retail demand softens domestic bullion absorption."))

    # Gold ETF flows
    if _match_any(BULLISH_ETF_PATTERNS, text):
        bullish_signals.append((GoldMacroDriver.GOLD_ETF, GoldDriver.MARKET_MOMENTUM, "MEDIUM", "Gold ETF inflows add physical-backed institutional demand."))
    if _match_any(BEARISH_ETF_PATTERNS, text):
        bearish_signals.append((GoldMacroDriver.GOLD_ETF, GoldDriver.MARKET_MOMENTUM, "MEDIUM", "Gold ETF outflows reduce institutional bullion holdings."))

    # Inflation / Oil shocks
    if _match_any(INFLATION_MACRO_PATTERNS, text):
        if "oil rally" in text or "oil rises" in text or "oil jumps" in text or "hotter cpi" in text:
            bearish_signals.append((GoldMacroDriver.INFLATION, GoldDriver.INFLATION_MACRO, "MEDIUM", "Energy/CPI inflation shock strengthens higher-for-longer yield expectations."))
        elif not bullish_signals and not bearish_signals:
            uncertain_driver = (GoldMacroDriver.INFLATION, GoldDriver.INFLATION_MACRO, "Inflation headline lacks unambiguous hawkish vs stagflationary net direction.")

    # Technical momentum (only if no causal macro driver matched; preserve causal driver priority)
    if not bullish_signals and not bearish_signals:
        if _match_any(BULLISH_MOMENTUM_PATTERNS, text):
            bullish_signals.append((GoldMacroDriver.OTHER_MACRO, GoldDriver.MARKET_MOMENTUM, "MEDIUM", "Technical breakout or record momentum attracts trend buyers."))
        if _match_any(BEARISH_MOMENTUM_PATTERNS, text):
            bearish_signals.append((GoldMacroDriver.OTHER_MACRO, GoldDriver.MARKET_MOMENTUM, "MEDIUM", "Technical liquidation or breakdown weighs on near-term positioning."))

    if not bullish_signals and not bearish_signals and not neutral_driver and not uncertain_driver and _match_any(PHYSICAL_UNSPECIFIED_PATTERNS, text):
        uncertain_driver = (GoldMacroDriver.INDIAN_PHYSICAL_DEMAND, GoldDriver.PHYSICAL_AND_CENTRAL_BANK, "Physical sector commentary lacks clear directional evidence.")

    # Resolve final direction cleanly
    if bullish_signals and bearish_signals:
        driver, legacy_driver, _, b_rat = bullish_signals[0]
        gold_impact = GoldImpactDirection.MIXED
        confidence = "MEDIUM"
        rationale = f"Conflicting bullish ({driver.value}) and bearish ({bearish_signals[0][0].value}) bullion drivers: {b_rat}"
    elif bullish_signals:
        driver, legacy_driver, confidence, rationale = bullish_signals[0]
        gold_impact = GoldImpactDirection.BULLISH
    elif bearish_signals:
        driver, legacy_driver, confidence, rationale = bearish_signals[0]
        gold_impact = GoldImpactDirection.BEARISH
    elif neutral_driver is not None:
        driver, legacy_driver, rationale = neutral_driver
        gold_impact = GoldImpactDirection.NEUTRAL
        confidence = "MEDIUM"
    elif uncertain_driver is not None:
        driver, legacy_driver, rationale = uncertain_driver
        gold_impact = GoldImpactDirection.UNKNOWN
        confidence = "LOW"
    else:
        driver = GoldMacroDriver.UNKNOWN
        legacy_driver = GoldDriver.OTHER_MACRO
        gold_impact = GoldImpactDirection.UNKNOWN
        confidence = "LOW"
        rationale = "No unambiguous gold-specific macro or physical driver identified; impact marked UNKNOWN."

    if (gold_impact == GoldImpactDirection.BULLISH and FAILED_RALLY_RE.search(text)) or (
        gold_impact == GoldImpactDirection.BEARISH and FAILED_DROP_RE.search(text)
    ):
        rationale = f"Headline reports gold failing to follow the implied {gold_impact.value.lower()} driver ({driver.value}); direction withheld."
        gold_impact = GoldImpactDirection.UNKNOWN
        confidence = "LOW"

    story_cluster_id, cluster_key = compute_story_cluster_id(title, published_utc, CLUSTER_VERSION)

    return {
        "title": title,
        "cluster_key": cluster_key,
        "story_cluster_id": story_cluster_id,
        "cluster_version": CLUSTER_VERSION,
        "published_at": published_utc.isoformat(),
        "age_hours": round(age_hours, 2),
        "age_display": age_display,
        "freshness_weight": freshness_weight,
        "general_tone": general_tone.value,
        "gold_impact": gold_impact.value,
        "driver": driver.value,
        "surprise": surprise.value,
        "is_price_report": False,
        "sentiment_version": SENTIMENT_VERSION,
        "driver_category": legacy_driver,
        "directional_implication": gold_impact.value,
        "confidence": confidence,
        "evidence_rationale": rationale,
        "finbert_tone": general_tone.value.lower(),
        "finbert_score": finbert_score,
    }
