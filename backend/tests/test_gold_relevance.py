from app.services.sentiment.relevance import GoldRelevanceScorer
from app.services.sentiment.schemas import NewsArticle, NewsCategory
from datetime import datetime, timezone
import pytest


@pytest.fixture
def scorer():
    return GoldRelevanceScorer()


# 1. Direct gold article -> relevant
def test_direct_gold_article(scorer):
    res = scorer.score_text("Gold prices surge as safe-haven demand rises amid economic uncertainty")
    assert res.is_gold_relevant is True
    assert res.gold_relevance_score >= 0.7
    assert res.primary_category == NewsCategory.GOLD_DIRECT.value


# 2. Fed article -> relevant
def test_fed_article(scorer):
    res = scorer.score_text("Federal Reserve officials signal caution on future monetary policy path")
    assert res.us_relevance >= 0.7
    assert res.macro_relevance >= 0.7
    assert res.primary_category == NewsCategory.US_FED_MONETARY_POLICY.value


# 3. Fed rate decision -> relevant
def test_fed_rate_decision(scorer):
    res = scorer.score_text("Fed cuts interest rates by 25 basis points at FOMC meeting")
    assert res.us_relevance >= 0.7
    assert res.primary_category == NewsCategory.US_FED_MONETARY_POLICY.value


# 4. US CPI article -> relevant
def test_us_cpi_article(scorer):
    res = scorer.score_text("US CPI inflation rises 0.3% in August, beating forecasts")
    assert res.us_relevance >= 0.7
    assert res.primary_category == NewsCategory.US_INFLATION.value


# 5. Treasury yield article -> relevant
def test_treasury_yield_article(scorer):
    res = scorer.score_text("US 10-year Treasury yield climbs to 4.25% following strong economic data")
    assert res.us_relevance >= 0.7
    assert res.market_relevance >= 0.7
    assert res.primary_category == NewsCategory.US_TREASURY_YIELDS.value


# 6. Dollar/DXY article -> relevant
def test_dollar_dxy_article(scorer):
    res = scorer.score_text("US dollar index DXY surges to multi-month peak on hawkish expectations")
    assert res.us_relevance >= 0.7
    assert res.market_relevance >= 0.7
    assert res.primary_category == NewsCategory.US_DOLLAR.value


# 7. War article -> relevant
def test_war_article(scorer):
    res = scorer.score_text("Middle East conflict escalation threatens maritime trade and oil shipments")
    assert res.geopolitical_relevance >= 0.7
    assert res.primary_category == NewsCategory.GEOPOLITICS.value


# 8. Geopolitical escalation -> relevant
def test_geopolitical_escalation(scorer):
    res = scorer.score_text("Geopolitical tensions intensify as missile strikes target energy facilities")
    assert res.geopolitical_relevance >= 0.7
    assert res.primary_category == NewsCategory.GEOPOLITICS.value


# 9. Sanctions article -> relevant
def test_sanctions_article(scorer):
    res = scorer.score_text("US Treasury imposes new financial sanctions on foreign commodity exports")
    assert res.geopolitical_relevance >= 0.7
    assert res.primary_category in (NewsCategory.SANCTIONS.value, NewsCategory.GEOPOLITICS.value)


# 10. Oil shock -> relevant
def test_oil_shock(scorer):
    res = scorer.score_text("Brent crude oil prices jump 4% as OPEC announces unexpected production cuts")
    assert res.macro_relevance >= 0.7
    assert res.primary_category == NewsCategory.OIL_ENERGY.value


# 11. RBI article -> relevant
def test_rbi_article(scorer):
    res = scorer.score_text("RBI MPC maintains repo rate at 6.5%, warns of food inflation risks")
    assert res.india_relevance >= 0.7
    assert res.primary_category == NewsCategory.INDIA_RBI.value


# 12. INR article -> relevant
def test_inr_article(scorer):
    res = scorer.score_text("Indian rupee falls to record low against US dollar amid trade deficit widening")
    assert res.india_relevance >= 0.7
    assert res.primary_category == NewsCategory.INDIA_FX.value


# 13. USDINR article -> relevant
def test_usdinr_article(scorer):
    res = scorer.score_text("USDINR breaks above 84.00 as dollar demand picks up in Mumbai market")
    assert res.india_relevance >= 0.7
    assert res.market_relevance >= 0.7
    assert res.primary_category == NewsCategory.INDIA_FX.value


# 14. MCX gold article -> relevant
def test_mcx_gold_article(scorer):
    res = scorer.score_text("MCX gold futures cross ₹75,000 per 10 grams on strong festive buying")
    assert res.is_gold_relevant is True
    assert res.gold_relevance_score >= 0.7
    assert res.primary_category == NewsCategory.INDIA_BULLION.value


# 15. Indian gold import-duty article -> relevant
def test_indian_gold_import_duty(scorer):
    res = scorer.score_text("Union Budget slashes gold import duty to curb smuggling and boost domestic jewellers")
    assert res.is_gold_relevant is True
    assert res.gold_relevance_score >= 0.7
    assert res.primary_category == NewsCategory.INDIA_POLICY.value


# 16. Central-bank gold buying -> relevant
def test_central_bank_gold_buying(scorer):
    res = scorer.score_text("Global central banks accelerate official gold reserves purchases in de-dollarization push")
    assert res.is_gold_relevant is True
    assert res.gold_relevance_score >= 0.7
    assert res.primary_category == NewsCategory.CENTRAL_BANK_GOLD.value


# 17. PBoC gold buying -> relevant
def test_pboc_gold_buying(scorer):
    res = scorer.score_text("PBoC gold reserves expand for 18th consecutive month as China diversifies reserves")
    assert res.is_gold_relevant is True
    assert res.gold_relevance_score >= 0.7
    assert res.primary_category in (NewsCategory.CENTRAL_BANK_GOLD.value, NewsCategory.CHINA_GOLD.value)


# 18. China gold demand -> relevant
def test_china_gold_demand(scorer):
    res = scorer.score_text("Shanghai Gold Exchange reports record premium as Chinese retail gold demand surges")
    assert res.is_gold_relevant is True
    assert res.gold_relevance_score >= 0.7
    assert res.primary_category == NewsCategory.CHINA_GOLD.value


# 19. Financial crisis -> relevant
def test_financial_crisis(scorer):
    res = scorer.score_text("Banking crisis fears re-emerge as regional lender reports severe liquidity stress")
    assert res.macro_relevance >= 0.7
    assert res.primary_category == NewsCategory.GLOBAL_FINANCIAL_RISK.value


# 20. Gold supply disruption -> relevant
def test_gold_supply_disruption(scorer):
    res = scorer.score_text("Major gold mine strike in South Africa halts production, tightening global supply")
    assert res.is_gold_relevant is True
    assert res.gold_relevance_score >= 0.7
    assert res.primary_category == NewsCategory.GOLD_SUPPLY_DEMAND.value


# 21. Indian festival/bullion-demand article -> relevant when genuinely market-related
def test_indian_festival_bullion_demand(scorer):
    res = scorer.score_text("Dhanteras gold buying surges 20% across Indian jewellery showrooms despite high rates")
    assert res.is_gold_relevant is True
    assert res.gold_relevance_score >= 0.7
    assert res.primary_category == NewsCategory.INDIA_GOLD_DEMAND.value


# 22. Olympic gold article -> NOT relevant
def test_olympic_gold_excluded(scorer):
    res = scorer.score_text("Sprinter wins Olympic gold medal in historic 100-meter dash final")
    assert res.is_gold_relevant is False
    assert res.gold_relevance_score == 0.0
    assert res.primary_category == NewsCategory.OTHER.value


# 23. Golden State Warriors -> NOT relevant
def test_golden_state_warriors_excluded(scorer):
    res = scorer.score_text("Golden State Warriors win NBA Western Conference playoff game")
    assert res.is_gold_relevant is False
    assert res.gold_relevance_score == 0.0
    assert res.primary_category == NewsCategory.OTHER.value


# 24. Golden Globe -> NOT relevant
def test_golden_globe_excluded(scorer):
    res = scorer.score_text("Blockbuster movie sweeps top honours at 82nd annual Golden Globe awards")
    assert res.is_gold_relevant is False
    assert res.gold_relevance_score == 0.0
    assert res.primary_category == NewsCategory.OTHER.value


# 25. Movie/entertainment gold article -> NOT relevant
def test_movie_entertainment_gold_excluded(scorer):
    res = scorer.score_text("Pop star achieves certified gold album status with hit single streaming records")
    assert res.is_gold_relevant is False
    assert res.gold_relevance_score == 0.0
    assert res.primary_category == NewsCategory.OTHER.value
