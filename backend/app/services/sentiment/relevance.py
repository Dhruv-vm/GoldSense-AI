from __future__ import annotations

import re
from typing import Any

from app.services.sentiment.schemas import NewsArticle, NewsCategory, RelevanceScore

# -----------------------------------------------------------------------------
# CATEGORY KEYWORD TAXONOMY
# -----------------------------------------------------------------------------
CATEGORY_PATTERNS: dict[str, list[str]] = {
    NewsCategory.GOLD_DIRECT.value: [
        r"\bgold price\b",
        r"\bgold prices\b",
        r"\bgold rate\b",
        r"\bgold rates\b",
        r"\bspot gold\b",
        r"\bgold bullion\b",
        r"\bxauusd\b",
        r"\bxau\b",
        r"\byellow metal\b",
        r"\bgold futures\b",
        r"\bcomex gold\b",
        r"\blbma gold\b",
        r"\bgold climbs\b",
        r"\bgold surges\b",
        r"\bgold slips\b",
        r"\bgold falls\b",
        r"\bgold drops\b",
        r"\bgold rallies\b",
        r"\bgold hits\b",
        r"\bgold tumbles\b",
        r"\bgold steadies\b",
        r"\bgold retreats\b",
    ],
    NewsCategory.GOLD_SUPPLY_DEMAND.value: [
        r"\bgold mine\b",
        r"\bgold mining\b",
        r"\bmine production\b",
        r"\bmine strike\b",
        r"\bgold recycling\b",
        r"\bscrap gold\b",
        r"\bcomex inventories\b",
        r"\blbma vaults\b",
        r"\bgold etf\b",
        r"\betf inflows\b",
        r"\betf outflows\b",
        r"\bgold demand report\b",
        r"\bgold supply\b",
        r"\bgold output\b",
        r"\bworld gold council\b",
    ],
    NewsCategory.GEOPOLITICS.value: [
        r"\bwar\b",
        r"\bwars\b",
        r"\bmilitary conflict\b",
        r"\bconflict escalation\b",
        r"\bgeopolitical\b",
        r"\bgeopolitics\b",
        r"\bgeopolitical tension\b",
        r"\bgeopolitical tensions\b",
        r"\bmilitary escalation\b",
        r"\bde-escalation\b",
        r"\bceasefire\b",
        r"\bpeace agreement\b",
        r"\bpeace talks\b",
        r"\bmissile strike\b",
        r"\bairstrike\b",
        r"\bmilitary attack\b",
        r"\bmilitary operation\b",
        r"\bmiddle east conflict\b",
        r"\brussia ukraine\b",
        r"\bukraine war\b",
        r"\btaiwan strait\b",
        r"\bindia pakistan\b",
        r"\bindia china border\b",
        r"\bred sea\b",
        r"\bstrait of hormuz\b",
        r"\bhouthi\b",
        r"\bmaritime attack\b",
        r"\bshipping disruption\b",
        r"\bgaza\b",
        r"\blebanon\b",
        r"\bisrael\b",
        r"\biran attack\b",
    ],
    NewsCategory.US_FED_MONETARY_POLICY.value: [
        r"\bfederal reserve\b",
        r"\bfed\b",
        r"\bfomc\b",
        r"\bjerome powell\b",
        r"\bchair powell\b",
        r"\brate cut\b",
        r"\brate cuts\b",
        r"\brate hike\b",
        r"\brate hikes\b",
        r"\brate pause\b",
        r"\binterest rate decision\b",
        r"\bmonetary policy\b",
        r"\bdot plot\b",
        r"\bquantitative easing\b",
        r"\bquantitative tightening\b",
        r"\bfed balance sheet\b",
        r"\bfed minutes\b",
        r"\bjackson hole\b",
        r"\bfed speech\b",
        r"\bfed expectations\b",
    ],
    NewsCategory.US_MACRO.value: [
        r"\bus gdp\b",
        r"\bus economy\b",
        r"\bus economic\b",
        r"\bism manufacturing\b",
        r"\bism services\b",
        r"\bconsumer confidence\b",
        r"\bus retail sales\b",
        r"\brecession fears\b",
        r"\bus economic growth\b",
        r"\beconomic slowdown\b",
        r"\beconomic expansion\b",
    ],
    NewsCategory.US_INFLATION.value: [
        r"\bus cpi\b",
        r"\bcpi inflation\b",
        r"\bcore cpi\b",
        r"\bconsumer price index\b",
        r"\bpce\b",
        r"\bcore pce\b",
        r"\bproducer price index\b",
        r"\bppi\b",
        r"\bus inflation\b",
        r"\binflation print\b",
        r"\bdisinflation\b",
        r"\bstagflation\b",
        r"\binflation expectations\b",
    ],
    NewsCategory.US_LABOR_MARKET.value: [
        r"\bnonfarm payrolls\b",
        r"\bnfp\b",
        r"\bunemployment rate\b",
        r"\bjobless claims\b",
        r"\bus jobs\b",
        r"\blabor market\b",
        r"\bwage growth\b",
        r"\bjolts\b",
    ],
    NewsCategory.US_DOLLAR.value: [
        r"\bus dollar\b",
        r"\bdxy\b",
        r"\bdollar index\b",
        r"\bgreenback\b",
        r"\bdollar strength\b",
        r"\bdollar weakness\b",
        r"\bdollar rally\b",
        r"\bdollar surge\b",
        r"\bdollar drops\b",
        r"\bdollar funding\b",
        r"\bdollar liquidity\b",
    ],
    NewsCategory.US_TREASURY_YIELDS.value: [
        r"\btreasury yield\b",
        r"\btreasury yields\b",
        r"\b10-year treasury\b",
        r"\b10 year yield\b",
        r"\b2-year treasury\b",
        r"\b2 year yield\b",
        r"\b30-year bond\b",
        r"\bbond yields\b",
        r"\byield curve\b",
        r"\byield curve inversion\b",
        r"\breal yields\b",
        r"\btips\b",
        r"\btreasury auction\b",
        r"\bbenchmark 10-year\b",
    ],
    NewsCategory.GLOBAL_FX.value: [
        r"\beur/usd\b",
        r"\busd/jpy\b",
        r"\busd/cny\b",
        r"\bforex market\b",
        r"\bfx market\b",
        r"\bcurrency market\b",
        r"\bcurrency volatility\b",
        r"\bjapanese yen\b",
        r"\beuro\b",
        r"\bchinese yuan\b",
        r"\bemerging market currencies\b",
    ],
    NewsCategory.INDIA_RBI.value: [
        r"\brbi\b",
        r"\breserve bank of india\b",
        r"\brbi mpc\b",
        r"\brepo rate\b",
        r"\breverse repo\b",
        r"\bcrr\b",
        r"\bslr\b",
        r"\brbi monetary policy\b",
        r"\brbi governor\b",
        r"\bshaktikanta das\b",
        r"\brbi policy\b",
        r"\brbi intervention\b",
        r"\brbi liquidity\b",
    ],
    NewsCategory.INDIA_MACRO.value: [
        r"\bindia gdp\b",
        r"\bindian economy\b",
        r"\biip\b",
        r"\bindia pmi\b",
        r"\bindian manufacturing pmi\b",
        r"\bfiscal deficit\b",
        r"\b10y g-sec\b",
        r"\bg-sec\b",
        r"\bgovernment securities\b",
        r"\bcurrent account deficit\b",
        r"\bfii flows\b",
        r"\bfpi flows\b",
        r"\bforeign capital flows\b",
    ],
    NewsCategory.INDIA_INFLATION.value: [
        r"\bindia cpi\b",
        r"\bretail inflation india\b",
        r"\bindia wpi\b",
        r"\bwholesale inflation india\b",
        r"\bfood inflation india\b",
        r"\bindian inflation\b",
    ],
    NewsCategory.INDIA_FX.value: [
        r"\binr\b",
        r"\bindian rupee\b",
        r"\brupee\b",
        r"\busdinr\b",
        r"\busd/inr\b",
        r"\brupee depreciation\b",
        r"\brupee appreciation\b",
        r"\brupee hits all-time low\b",
        r"\brupee falls\b",
        r"\brupee slips\b",
        r"\brupee edges\b",
        r"\bforex reserves india\b",
        r"\bindia forex reserves\b",
    ],
    NewsCategory.INDIA_BULLION.value: [
        r"\bmcx gold\b",
        r"\bmcx silver\b",
        r"\bmcx bullion\b",
        r"\bmcx futures\b",
        r"\bibja\b",
        r"\bindian bullion\b",
        r"\bdomestic gold\b",
        r"\blocal gold rate\b",
        r"\blocal gold price\b",
        r"\bdomestic premium\b",
        r"\bdomestic discount\b",
        r"\bzaveri bazaar\b",
        r"\bkjpl\b",
        r"\bkjpl bullion\b",
        r"\bkundan\b",
    ],
    NewsCategory.INDIA_GOLD_DEMAND.value: [
        r"\bdiwali gold\b",
        r"\bdhanteras\b",
        r"\bakshaya tritiya\b",
        r"\bwedding season\b",
        r"\bfestival demand\b",
        r"\bindian jewellery demand\b",
        r"\brural gold demand\b",
        r"\bmonsoon harvest gold\b",
        r"\bindia gold demand\b",
        r"\bgold buying festival\b",
    ],
    NewsCategory.INDIA_POLICY.value: [
        r"\bgold import duty\b",
        r"\bcustoms duty on gold\b",
        r"\bgold tariff\b",
        r"\bgold gst\b",
        r"\bhallmarking\b",
        r"\bbis hallmarking\b",
        r"\bgold import restrictions\b",
        r"\bgold monetisation\b",
        r"\bsovereign gold bond\b",
        r"\bsgb\b",
        r"\bunion budget gold\b",
    ],
    NewsCategory.CHINA_GOLD.value: [
        r"\bshanghai gold exchange\b",
        r"\bsge\b",
        r"\bchina gold demand\b",
        r"\bchina gold reserves\b",
        r"\bchinese jewellery\b",
        r"\bchina gold imports\b",
        r"\bchina gold premium\b",
    ],
    NewsCategory.CHINA_MACRO.value: [
        r"\bchina gdp\b",
        r"\bchina stimulus\b",
        r"\bchina economic\b",
        r"\bchinese economy\b",
        r"\bchinese property\b",
        r"\bchina property crisis\b",
        r"\brenminbi\b",
        r"\bchina pmi\b",
    ],
    NewsCategory.CENTRAL_BANK_GOLD.value: [
        r"\bcentral bank gold\b",
        r"\bcentral bank reserves\b",
        r"\bcentral bank purchases\b",
        r"\bcentral bank buying\b",
        r"\bofficial gold reserves\b",
        r"\bpboc gold reserves\b",
        r"\brbi gold reserves\b",
        r"\bde-dollarization\b",
        r"\breserve diversification\b",
        r"\bgold repatriation\b",
    ],
    NewsCategory.OIL_ENERGY.value: [
        r"\bcrude oil\b",
        r"\bbrent\b",
        r"\bbrent crude\b",
        r"\bwti\b",
        r"\bwti crude\b",
        r"\bopec\b",
        r"\bopec\+\b",
        r"\boil prices\b",
        r"\boil shock\b",
        r"\boil supply\b",
        r"\brefinery disruption\b",
        r"\benergy crisis\b",
        r"\bpetroleum\b",
        r"\bsaudi oil\b",
        r"\biran oil\b",
    ],
    NewsCategory.GLOBAL_FINANCIAL_RISK.value: [
        r"\bbanking crisis\b",
        r"\bbank failure\b",
        r"\bbank failures\b",
        r"\bfinancial crisis\b",
        r"\bliquidity crisis\b",
        r"\bcredit crisis\b",
        r"\bsystemic risk\b",
        r"\bmarket crash\b",
        r"\bcontagion\b",
        r"\bvix\b",
        r"\bcredit spread\b",
        r"\bmargin call\b",
        r"\bfinancial stress\b",
    ],
    NewsCategory.GLOBAL_EQUITIES.value: [
        r"\bs&p 500\b",
        r"\bnasdaq\b",
        r"\bdow jones\b",
        r"\bnifty\b",
        r"\bsensex\b",
        r"\bstock selloff\b",
        r"\bequity selloff\b",
        r"\bwall street selloff\b",
        r"\brisk-on\b",
        r"\brisk-off\b",
        r"\bequity rally\b",
        r"\bstock market rout\b",
    ],
    NewsCategory.PRECIOUS_METALS.value: [
        r"\bsilver\b",
        r"\bxagusd\b",
        r"\bsilver price\b",
        r"\bsilver rates\b",
        r"\bplatinum\b",
        r"\bpalladium\b",
        r"\bgold/silver ratio\b",
        r"\bgold silver ratio\b",
        r"\bprecious metals\b",
    ],
    NewsCategory.TRADE_TARIFFS.value: [
        r"\btariff\b",
        r"\btariffs\b",
        r"\btrade war\b",
        r"\btrade dispute\b",
        r"\bcustoms tariff\b",
        r"\bexport controls\b",
        r"\bimport tariff\b",
        r"\bprotectionism\b",
    ],
    NewsCategory.SANCTIONS.value: [
        r"\bsanctions\b",
        r"\bsanction\b",
        r"\bofac\b",
        r"\bfinancial sanctions\b",
        r"\btrade embargo\b",
        r"\basset freeze\b",
        r"\bswift ban\b",
        r"\bsecondary sanctions\b",
    ],
}

# -----------------------------------------------------------------------------
# FALSE POSITIVE EXCLUSIONS
# -----------------------------------------------------------------------------
EXCLUSION_PATTERNS = [
    r"\bolympic\b",
    r"\bolympics\b",
    r"\bmedal\b",
    r"\bgold medal\b",
    r"\bgolden globe\b",
    r"\bgolden globes\b",
    r"\bgolden state\b",
    r"\bwarriors\b",
    r"\bgrammy\b",
    r"\bgrammys\b",
    r"\bbox office\b",
    r"\bhollywood\b",
    r"\bnba\b",
    r"\bfifa\b",
    r"\bfootball\b",
    r"\bpremier league\b",
    r"\bchampionship\b",
    r"\btournament\b",
    r"\balbum\b",
    r"\bsong\b",
    r"\bactor\b",
    r"\bactress\b",
    r"\bmovie\b",
    r"\bconcert\b",
    r"\bgaming\b",
    r"\bvideo game\b",
    r"\besports\b",
    r"\bgold award\b",
    r"\bgold record\b",
    r"\bmarigold\b",
]

FINANCIAL_CONTEXT_WORDS = {
    "market", "price", "rate", "rates", "futures", "investor", "ounce", "dollar",
    "bank", "inflation", "trade", "yield", "bullion", "economy", "central", "reserve",
    "mcx", "fed", "rbi", "crude", "oil", "troy", "g-sec", "rupee", "inr", "usdinr",
    "deficit", "liquidity", "policy", "currency", "bonds", "etf", "import", "customs",
}


class GoldRelevanceScorer:
    """
    Evaluates whether an article is relevant to the complete GoldSense chain:
    Global Macro / Geopolitics -> US Fed / Yields / USD -> Global Gold -> USDINR / India Macro -> Indian Bullion (KJPL).

    Assigns:
        - primary_category (from NewsCategory taxonomy)
        - supporting_categories
        - gold_relevance_score (0.0 to 1.0) & is_gold_relevant (bool)
        - contextual relevance scores (geopolitical, india, us, macro, market)
    """

    def __init__(self) -> None:
        self.category_compiled: dict[str, list[re.Pattern]] = {
            cat: [re.compile(p, re.IGNORECASE) for p in patterns]
            for cat, patterns in CATEGORY_PATTERNS.items()
        }
        self.exclusion_compiled = [
            re.compile(p, re.IGNORECASE) for p in EXCLUSION_PATTERNS
        ]

    def score_text(
        self,
        title: str,
        description: str | None = None,
    ) -> RelevanceScore:
        title_text = title or ""
        desc_text = description or ""
        combined_text = f"{title_text} {desc_text}".strip().lower()

        # 1. Check false positive exclusions
        has_exclusion = any(rx.search(combined_text) for rx in self.exclusion_compiled)
        words_in_text = set(re.findall(r"\w+", combined_text))
        has_financial_context = bool(words_in_text & FINANCIAL_CONTEXT_WORDS)

        if has_exclusion and not has_financial_context:
            return RelevanceScore(
                gold_relevance_score=0.0,
                is_gold_relevant=False,
                primary_category=NewsCategory.OTHER.value,
                supporting_categories=[],
                geopolitical_relevance=0.0,
                india_relevance=0.0,
                us_relevance=0.0,
                macro_relevance=0.0,
                market_relevance=0.0,
                matched_keywords=[],
            )

        category_scores: dict[str, float] = {}
        category_matched_terms: dict[str, list[str]] = {}
        all_matched_keywords: list[str] = []

        # 2. Score each category
        for cat, patterns in self.category_compiled.items():
            matches_title = [
                rx.pattern.replace(r"\b", "")
                for rx in patterns
                if rx.search(title_text)
            ]
            matches_desc = [
                rx.pattern.replace(r"\b", "")
                for rx in patterns
                if rx.search(desc_text) and rx.pattern.replace(r"\b", "") not in matches_title
            ]

            if matches_title or matches_desc:
                # Title matches have high weight (0.7 base), description (0.4 base)
                cat_score = 0.0
                if matches_title:
                    cat_score = 0.7 + min(len(matches_title) - 1, 3) * 0.1
                elif matches_desc:
                    cat_score = 0.4 + min(len(matches_desc) - 1, 3) * 0.1

                category_scores[cat] = min(1.0, cat_score)
                category_matched_terms[cat] = matches_title + matches_desc
                all_matched_keywords.extend(matches_title + matches_desc)

        # 3. Determine primary and supporting categories
        SPECIFIC_GOLD_CATS = {
            NewsCategory.INDIA_BULLION.value,
            NewsCategory.INDIA_POLICY.value,
            NewsCategory.INDIA_GOLD_DEMAND.value,
            NewsCategory.CENTRAL_BANK_GOLD.value,
            NewsCategory.CHINA_GOLD.value,
            NewsCategory.GOLD_SUPPLY_DEMAND.value,
        }

        if category_scores:
            def _sort_key(item: tuple[str, float]):
                cat, score = item
                terms = category_matched_terms.get(cat, [])
                pref = 2 if cat in SPECIFIC_GOLD_CATS else (0 if cat == NewsCategory.GOLD_DIRECT.value else 1)
                term_len = sum(len(t) for t in terms)
                return (score, pref, term_len)

            sorted_cats = sorted(
                category_scores.items(), key=_sort_key, reverse=True
            )
            primary_cat = sorted_cats[0][0]
            supporting_cats = [
                c for c, s in sorted_cats[1:] if s >= 0.35
            ]
        else:
            primary_cat = NewsCategory.OTHER.value
            supporting_cats = []

        # 4. Compute contextual relevance dimensions
        # Geopolitical relevance
        geo_cats = [
            category_scores.get(NewsCategory.GEOPOLITICS.value, 0.0),
            category_scores.get(NewsCategory.TRADE_TARIFFS.value, 0.0),
            category_scores.get(NewsCategory.SANCTIONS.value, 0.0),
        ]
        geopolitical_rel = round(max(geo_cats, default=0.0), 4)

        # India relevance
        india_cats = [
            category_scores.get(NewsCategory.INDIA_RBI.value, 0.0),
            category_scores.get(NewsCategory.INDIA_MACRO.value, 0.0),
            category_scores.get(NewsCategory.INDIA_INFLATION.value, 0.0),
            category_scores.get(NewsCategory.INDIA_FX.value, 0.0),
            category_scores.get(NewsCategory.INDIA_BULLION.value, 0.0),
            category_scores.get(NewsCategory.INDIA_GOLD_DEMAND.value, 0.0),
            category_scores.get(NewsCategory.INDIA_POLICY.value, 0.0),
        ]
        india_rel = round(max(india_cats, default=0.0), 4)

        # US relevance
        us_cats = [
            category_scores.get(NewsCategory.US_FED_MONETARY_POLICY.value, 0.0),
            category_scores.get(NewsCategory.US_MACRO.value, 0.0),
            category_scores.get(NewsCategory.US_INFLATION.value, 0.0),
            category_scores.get(NewsCategory.US_LABOR_MARKET.value, 0.0),
            category_scores.get(NewsCategory.US_DOLLAR.value, 0.0),
            category_scores.get(NewsCategory.US_TREASURY_YIELDS.value, 0.0),
        ]
        us_rel = round(max(us_cats, default=0.0), 4)

        # Macro relevance
        macro_cats = [
            category_scores.get(NewsCategory.US_FED_MONETARY_POLICY.value, 0.0),
            category_scores.get(NewsCategory.US_MACRO.value, 0.0),
            category_scores.get(NewsCategory.US_INFLATION.value, 0.0),
            category_scores.get(NewsCategory.INDIA_MACRO.value, 0.0),
            category_scores.get(NewsCategory.INDIA_INFLATION.value, 0.0),
            category_scores.get(NewsCategory.OIL_ENERGY.value, 0.0),
            category_scores.get(NewsCategory.CENTRAL_BANK_GOLD.value, 0.0),
            category_scores.get(NewsCategory.GLOBAL_FINANCIAL_RISK.value, 0.0),
        ]
        macro_rel = round(max(macro_cats, default=0.0), 4)

        # Market relevance
        market_cats = [
            category_scores.get(NewsCategory.GOLD_DIRECT.value, 0.0),
            category_scores.get(NewsCategory.US_TREASURY_YIELDS.value, 0.0),
            category_scores.get(NewsCategory.US_DOLLAR.value, 0.0),
            category_scores.get(NewsCategory.GLOBAL_FX.value, 0.0),
            category_scores.get(NewsCategory.INDIA_FX.value, 0.0),
            category_scores.get(NewsCategory.INDIA_BULLION.value, 0.0),
            category_scores.get(NewsCategory.GLOBAL_EQUITIES.value, 0.0),
            category_scores.get(NewsCategory.PRECIOUS_METALS.value, 0.0),
        ]
        market_rel = round(max(market_cats, default=0.0), 4)

        # 5. Direct gold relevance score
        # Direct gold categories have maximum impact on gold_relevance_score
        gold_direct_cats = [
            category_scores.get(NewsCategory.GOLD_DIRECT.value, 0.0),
            category_scores.get(NewsCategory.GOLD_SUPPLY_DEMAND.value, 0.0),
            category_scores.get(NewsCategory.INDIA_BULLION.value, 0.0),
            category_scores.get(NewsCategory.INDIA_GOLD_DEMAND.value, 0.0),
            category_scores.get(NewsCategory.INDIA_POLICY.value, 0.0),
            category_scores.get(NewsCategory.CHINA_GOLD.value, 0.0),
            category_scores.get(NewsCategory.CENTRAL_BANK_GOLD.value, 0.0),
        ]
        direct_gold_score = max(gold_direct_cats, default=0.0)

        # Check explicit mention of "gold", "bullion", "xau"
        has_explicit_gold = bool(
            re.search(r"\b(gold|bullion|xauusd|xau|yellow metal)\b", combined_text, re.IGNORECASE)
        )

        if direct_gold_score > 0:
            gold_rel_score = direct_gold_score
        elif has_explicit_gold:
            # Macro / Geopolitical / FX article that explicitly connects to gold
            max_driver = max(geopolitical_rel, us_rel, india_rel, macro_rel)
            gold_rel_score = round(min(1.0, 0.6 + max_driver * 0.3), 4)
        elif category_scores.get(NewsCategory.PRECIOUS_METALS.value, 0.0) > 0:
            gold_rel_score = round(category_scores[NewsCategory.PRECIOUS_METALS.value] * 0.7, 4)
        else:
            # Macro, Geopolitics, or FX without explicit gold mention
            gold_rel_score = 0.0

        is_gold_relevant = gold_rel_score >= 0.4 or has_explicit_gold

        # Deduplicate matched keywords
        unique_matched_keywords = list(dict.fromkeys(all_matched_keywords))

        return RelevanceScore(
            gold_relevance_score=gold_rel_score,
            is_gold_relevant=is_gold_relevant,
            primary_category=primary_cat,
            supporting_categories=supporting_cats,
            geopolitical_relevance=geopolitical_rel,
            india_relevance=india_rel,
            us_relevance=us_rel,
            macro_relevance=macro_rel,
            market_relevance=market_rel,
            matched_keywords=unique_matched_keywords,
        )

    def score_article(self, article: NewsArticle) -> RelevanceScore:
        return self.score_text(
            title=article.title,
            description=article.description,
        )
