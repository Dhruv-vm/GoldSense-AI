from __future__ import annotations

import csv
import email.utils
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from app.services.sentiment.schemas import NewsArticle
from app.services.sentiment.relevance import GoldRelevanceScorer
from app.services.sentiment.gold_impact import evaluate_gold_impact, extract_cluster_key, GoldDriver

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

DEFAULT_LOOKBACK_HOURS = int(os.environ.get("NEWS_LOOKBACK_HOURS", "24"))

QUERY_GROUPS: dict[str, list[str]] = {
    "GOLD": [
        "gold price",
        "gold bullion",
        "gold futures",
        "spot gold",
        "XAUUSD",
        "COMEX gold",
        "LBMA gold",
    ],
    "FED": [
        "Federal Reserve gold",
        "Fed gold",
        "FOMC gold",
        "Powell gold",
        "Fed interest rates",
        "Fed rate cuts",
        "Fed rate hikes",
    ],
    "INFLATION": [
        "CPI gold",
        "PCE gold",
        "inflation gold",
        "US jobs gold",
        "NFP gold",
        "GDP gold",
    ],
    "YIELDS": [
        "Treasury yields gold",
        "10 year yield gold",
        "real yields gold",
        "bond yields gold",
    ],
    "USD": [
        "DXY gold",
        "dollar gold",
        "USD gold",
    ],
    "INDIA": [
        "India gold price",
        "Indian bullion",
        "MCX gold",
        "IBJA gold",
        "RBI gold",
        "RBI gold reserves",
        "India rupee gold",
        "USDINR gold",
        "Indian gold imports",
    ],
    "GEOPOLITICS": [
        "war gold",
        "geopolitical tensions gold",
        "Middle East gold",
        "Russia Ukraine gold",
        "US China gold",
        "Taiwan gold",
        "India Pakistan gold",
        "India China tensions gold",
        "sanctions gold",
        "trade war gold",
    ],
    "OIL": [
        "oil gold",
        "Brent gold",
        "OPEC gold",
        "oil inflation",
        "oil India rupee",
    ],
    "CENTRAL_BANKS": [
        "central bank gold buying",
        "PBoC gold",
        "China gold reserves",
        "RBI gold reserves",
        "central bank gold reserves",
    ],
    "FINANCIAL_RISK": [
        "banking crisis gold",
        "recession gold",
        "financial crisis gold",
        "market crash gold",
        "VIX gold",
    ],
    "CHINA": [
        "China gold demand",
        "China gold reserves",
        "PBoC gold",
        "Shanghai Gold Exchange",
    ],
}


def normalize_url(url: str) -> str:
    """
    Produce a canonical URL by removing tracking query parameters and trailing slashes.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        clean_query = urllib.parse.parse_qsl(parsed.query)
        # Drop marketing / tracking params
        tracking_prefixes = ("utm_", "oc", "ref", "src", "fbclid", "gclid")
        filtered_query = [
            (k, v) for k, v in clean_query
            if not any(k.lower().startswith(p) for p in tracking_prefixes)
        ]
        new_query = urllib.parse.urlencode(filtered_query)
        clean_path = parsed.path.rstrip("/")
        normalized = urllib.parse.urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                clean_path,
                parsed.params,
                new_query,
                "",  # strip fragment
            )
        )
        return normalized or url.strip().lower()
    except Exception:
        return url.strip().lower().rstrip("/")


def normalize_title(title: str) -> str:
    """
    Produce a normalized title by stripping publisher suffixes, punctuation, and extra whitespace.
    """
    t = title.strip().lower()
    # Strip common news source suffixes like " - Reuters", " | Bloomberg"
    t = re.sub(r"\s+[-|–—]\s+[A-Za-z0-9\s.&]+$", "", t)
    # Strip non-alphanumeric chars
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


class NewsClient:
    """
    Collects recent financial, macroeconomic, and geopolitical news influencing the GoldSense chain.

    Features:
        - Focused multi-group query strategy
        - GDELT 2.0 API with retry intervals and active rate-limit circuit breaker
        - Automatic Google News RSS fallback with strict publication timestamp parsing
        - Robust deduplication (canonical URL & normalized title)
        - Timezone-aware UTC published_at timestamps
        - Future-dated and stale article rejection
        - Separate live dataset (live_news.csv) and historical research archive (news_articles.csv)
    """

    _gdelt_throttled_until: float = 0.0

    def __init__(
        self,
        timeout: int = 25,
        max_retries: int = 3,
        retry_wait_seconds: int = 8,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_wait_seconds = retry_wait_seconds

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            }
        )

    def search(
        self,
        query: str = "gold price",
        start_datetime: datetime | None = None,
        end_datetime: datetime | None = None,
        max_records: int = 50,
        raise_on_error: bool = False,
        enable_fallback: bool = True,
    ) -> list[NewsArticle]:
        """
        Search GDELT for news articles, falling back to RSS if rate-limited.
        """
        # Circuit breaker: if GDELT rate limited recently, immediately use RSS fallback
        if time.time() < self.__class__._gdelt_throttled_until and enable_fallback:
            return self.search_rss(
                query=query,
                max_records=max_records,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
            )

        params: dict[str, Any] = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": min(max_records, 250),
            "sort": "datedesc",
        }

        if start_datetime is not None:
            if start_datetime.tzinfo is not None:
                start_utc = start_datetime.astimezone(timezone.utc)
            else:
                start_utc = start_datetime.replace(tzinfo=timezone.utc)
            params["startdatetime"] = start_utc.strftime("%Y%m%d%H%M%S")

        if end_datetime is not None:
            if end_datetime.tzinfo is not None:
                end_utc = end_datetime.astimezone(timezone.utc)
            else:
                end_utc = end_datetime.replace(tzinfo=timezone.utc)
            params["enddatetime"] = end_utc.strftime("%Y%m%d%H%M%S")

        try:
            response = self._request_with_retry(params=params)
        except Exception as exc:
            if raise_on_error:
                raise
            if enable_fallback:
                print(f"[NEWS] GDELT unavailable ({exc}). Using RSS fallback...")
                return self.search_rss(
                    query=query,
                    max_records=max_records,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                )
            print(f"[NEWS] Warning: GDELT search failed: {exc}. Returning empty list.")
            return []

        try:
            payload = response.json()
        except Exception:
            if enable_fallback:
                print("[NEWS] GDELT returned non-JSON. Falling back to RSS...")
                return self.search_rss(
                    query=query,
                    max_records=max_records,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                )
            return []

        if not isinstance(payload, dict):
            return []

        articles: list[NewsArticle] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()

        for item in payload.get("articles", []):
            if not isinstance(item, dict):
                continue
            article = self._parse_article(item)

            if article is not None:
                canon_url = normalize_url(article.url)
                norm_title = normalize_title(article.title)
                if canon_url in seen_urls or norm_title in seen_titles:
                    continue
                seen_urls.add(canon_url)
                seen_titles.add(norm_title)
                articles.append(article)

        return articles

    def search_query_groups(
        self,
        groups: dict[str, list[str]] | None = None,
        lookback_hours: int | None = None,
        max_records_per_group: int = 15,
    ) -> list[NewsArticle]:
        """
        Executes focused search queries across the macro/gold taxonomy groups.
        Consolidates and deduplicates all results.
        """
        target_groups = groups or QUERY_GROUPS
        hours = lookback_hours if lookback_hours is not None else DEFAULT_LOOKBACK_HOURS
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=hours)

        all_articles: list[NewsArticle] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()

        for group_name, queries in target_groups.items():
            # Pick primary representative query for the group
            query_str = queries[0]
            print(f"[NEWS] Querying group [{group_name}]: '{query_str}'...")

            group_articles = self.search(
                query=query_str,
                start_datetime=start,
                end_datetime=now,
                max_records=max_records_per_group,
                raise_on_error=False,
                enable_fallback=True,
            )

            for art in group_articles:
                canon_url = normalize_url(art.url)
                norm_title = normalize_title(art.title)
                if canon_url in seen_urls or norm_title in seen_titles:
                    continue
                seen_urls.add(canon_url)
                seen_titles.add(norm_title)
                all_articles.append(art)

        print(f"[NEWS] Consolidated {len(all_articles)} unique articles across {len(target_groups)} query groups.")
        return all_articles

    def search_rss(
        self,
        query: str = "gold price",
        max_records: int = 50,
        start_datetime: datetime | None = None,
        end_datetime: datetime | None = None,
    ) -> list[NewsArticle]:
        """
        Collect news from Google News RSS feed for the query.
        Used as a high-reliability fallback when GDELT public API is throttled.
        """
        encoded_q = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-IN&gl=IN&ceid=IN:en"

        try:
            response = self.session.get(rss_url, timeout=self.timeout)
            response.raise_for_status()
        except Exception as exc:
            print(f"[NEWS] RSS fallback request failed: {exc}")
            return []

        try:
            soup = BeautifulSoup(response.text, "xml")
        except Exception:
            soup = BeautifulSoup(response.text, "html.parser")
        items = soup.find_all("item")

        articles: list[NewsArticle] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()

        start_utc = (
            start_datetime.astimezone(timezone.utc)
            if start_datetime and start_datetime.tzinfo
            else (start_datetime.replace(tzinfo=timezone.utc) if start_datetime else None)
        )
        end_utc = (
            end_datetime.astimezone(timezone.utc)
            if end_datetime and end_datetime.tzinfo
            else (end_datetime.replace(tzinfo=timezone.utc) if end_datetime else None)
        )

        for item in items:
            title = item.title.text.strip() if item.title else ""
            link = item.link.text.strip() if item.link else ""
            pub_date_str = item.pubDate.text.strip() if item.pubDate else ""
            source_tag = item.source.text.strip() if item.source else ""

            if not title or not link or not pub_date_str:
                continue

            try:
                published_at = email.utils.parsedate_to_datetime(pub_date_str)
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)
                else:
                    published_at = published_at.astimezone(timezone.utc)
            except Exception:
                continue

            now_utc = datetime.now(timezone.utc)
            # Future-dated check (> 15 minutes ahead of server clock)
            if published_at > now_utc + timedelta(minutes=15):
                continue

            # Time boundary filtering
            if start_utc and published_at < start_utc:
                continue
            if end_utc and published_at > end_utc:
                continue

            source = source_tag
            if not source and " - " in title:
                source = title.split(" - ")[-1].strip()

            canon_url = normalize_url(link)
            norm_title = normalize_title(title)
            if canon_url in seen_urls or norm_title in seen_titles:
                continue
            seen_urls.add(canon_url)
            seen_titles.add(norm_title)

            articles.append(
                NewsArticle(
                    title=title,
                    url=link,
                    published_at=published_at,
                    source=source or "Financial News",
                    language="en",
                    ingested_at=now_utc,
                )
            )

            if len(articles) >= max_records:
                break

        return articles

    def _request_with_retry(
        self,
        params: dict[str, Any],
    ) -> requests.Response:
        """
        Make a GDELT request with controlled retries.
        On HTTP 429:
            attempt 1 -> wait 8 seconds
            attempt 2 -> wait 16 seconds
            attempt 3 -> trigger RSS fallback and set circuit breaker cooldown
        """
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    GDELT_URL,
                    params=params,
                    timeout=self.timeout,
                )

            except requests.RequestException as exc:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        f"GDELT request failed after {self.max_retries} attempts."
                    ) from exc

                wait_seconds = 8 * (attempt + 1)
                print(
                    f"[NEWS] GDELT request error: {exc}. Retrying in {wait_seconds}s..."
                )
                time.sleep(wait_seconds)
                continue

            if response.status_code == 429:
                self.__class__._gdelt_throttled_until = time.time() + 180.0
                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        f"GDELT rate limit reached after {self.max_retries} attempts."
                    )

                wait_seconds = 8 if attempt == 0 else 16
                print(
                    f"[NEWS] GDELT rate limited (HTTP 429). Attempt {attempt + 1}: Waiting {wait_seconds}s..."
                )
                time.sleep(wait_seconds)
                continue

            response.raise_for_status()
            return response

        raise RuntimeError("GDELT request failed unexpectedly.")

    @classmethod
    def _parse_article(
        cls,
        item: dict[str, Any],
        max_lookback_hours: int | None = None,
        max_future_minutes: int = 15,
        reference_time: datetime | None = None,
    ) -> NewsArticle | None:
        published_text = item.get("seendate")
        if not published_text or not isinstance(published_text, str):
            return None

        clean_text = (
            published_text.replace("T", "")
            .replace("Z", "")
            .replace(" ", "")
            .strip()
        )

        if len(clean_text) < 14:
            return None

        try:
            published_at = datetime.strptime(
                clean_text[:14],
                "%Y%m%d%H%M%S",
            ).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

        now_utc = reference_time or datetime.now(timezone.utc)
        # Reject future-dated articles (> 15 minutes ahead of server clock)
        if published_at > now_utc + timedelta(minutes=max_future_minutes):
            return None

        # Reject stale articles if lookback filter is enforced
        if max_lookback_hours is not None:
            if published_at < now_utc - timedelta(hours=max_lookback_hours):
                return None

        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        source = str(item.get("domain") or "").strip()
        language = item.get("language")

        if not title or not url:
            return None

        return NewsArticle(
            title=title,
            url=url,
            published_at=published_at,
            source=source,
            language=language,
            ingested_at=now_utc,
        )

    @classmethod
    def save_news_datasets(
        cls,
        articles: list[NewsArticle],
        live_csv_path: str | Path,
        archive_csv_path: str | Path,
        lookback_hours: int = 24,
        max_live_retention_hours: int = 72,
        reference_time: datetime | None = None,
    ) -> dict[str, int]:
        """
        Saves news into strictly separated live and historical research datasets.

        1. Historical Archive (archive_csv_path):
           - Preserves all unique historical articles for timestamp-aligned backtesting and training.
           - Permanent, append-only, deduplicated by canonical URL and title.
           - Existing research data is NEVER deleted.

        2. Live Dataset (live_csv_path):
           - Contains ONLY fresh articles within the active recency window.
           - Stale articles (> max_live_retention_hours) and future-dated articles are purged.
           - Filtered for gold relevance and macroeconomic driver transmission.
           - Clustered by syndicated headline stem (cluster_key) to prevent wire reprint inflation.
           - Includes exact ingested_at timestamp, driver category, directional implication,
             confidence, and explanatory evidence rationale.
        """
        now = reference_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        scorer = GoldRelevanceScorer()
        archive_path = Path(archive_csv_path)
        live_path = Path(live_csv_path)

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        live_path.parent.mkdir(parents=True, exist_ok=True)

        # -------------------------------------------------------------
        # STEP 1: Process and enrich candidates
        # -------------------------------------------------------------
        valid_candidates: list[dict[str, Any]] = []
        for a in articles:
            # Timestamp validation
            pub_dt = a.published_at
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            else:
                pub_dt = pub_dt.astimezone(timezone.utc)

            # Reject future dated (> 15m)
            if pub_dt > now + timedelta(minutes=15):
                continue

            canon_url = normalize_url(a.url)
            norm_title = normalize_title(a.title)
            if not canon_url or not norm_title:
                continue

            rel = scorer.score_text(a.title)
            impact = evaluate_gold_impact(
                title=a.title,
                published_at=pub_dt,
                reference_time=now,
            )

            ingested_iso = a.ingested_at.isoformat() if a.ingested_at else now.isoformat()

            valid_candidates.append({
                "published_at": pub_dt.isoformat(),
                "published_dt": pub_dt,
                "ingested_at": ingested_iso,
                "title": a.title,
                "url": a.url,
                "canonical_url": canon_url,
                "normalized_title": norm_title,
                "source": a.source,
                "language": a.language or "en",
                "is_gold_relevant": rel.is_gold_relevant,
                "gold_relevance_score": rel.gold_relevance_score,
                "primary_category": rel.primary_category.value if hasattr(rel.primary_category, "value") else str(rel.primary_category),
                "driver_category": impact["driver_category"],
                "directional_implication": impact["directional_implication"],
                "confidence": impact["confidence"],
                "evidence_rationale": impact["evidence_rationale"],
                "cluster_key": impact["cluster_key"],
            })

        # -------------------------------------------------------------
        # STEP 2: Permanent Historical Research Archive (append-only)
        # -------------------------------------------------------------
        existing_archive_urls: set[str] = set()
        existing_archive_titles: set[str] = set()
        archive_exists = archive_path.exists()

        if archive_exists:
            with archive_path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("url"):
                        existing_archive_urls.add(normalize_url(row["url"]))
                    if row.get("title"):
                        existing_archive_titles.add(normalize_title(row["title"]))

        new_archive_count = 0
        with archive_path.open("a", newline="", encoding="utf-8") as f:
            fieldnames = ["published_at", "title", "url", "source", "language"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not archive_exists:
                writer.writeheader()

            for cand in valid_candidates:
                if cand["canonical_url"] in existing_archive_urls or cand["normalized_title"] in existing_archive_titles:
                    continue
                writer.writerow({
                    "published_at": cand["published_at"],
                    "title": cand["title"],
                    "url": cand["url"],
                    "source": cand["source"],
                    "language": cand["language"],
                })
                existing_archive_urls.add(cand["canonical_url"])
                existing_archive_titles.add(cand["normalized_title"])
                new_archive_count += 1

        # -------------------------------------------------------------
        # STEP 3: Strictly Fresh Live Dataset (Pruned & Clustered)
        # -------------------------------------------------------------
        live_pool: dict[str, dict[str, Any]] = {}

        # Load existing live items
        if live_path.exists():
            try:
                with live_path.open("r", newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        try:
                            p_dt = datetime.fromisoformat(row["published_at"])
                            if p_dt.tzinfo is None:
                                p_dt = p_dt.replace(tzinfo=timezone.utc)
                            else:
                                p_dt = p_dt.astimezone(timezone.utc)
                            c_url = normalize_url(row.get("url", ""))
                            n_title = normalize_title(row.get("title", ""))
                            if c_url:
                                row["published_dt"] = p_dt
                                row["canonical_url"] = c_url
                                row["normalized_title"] = n_title
                                live_pool[c_url] = row
                        except Exception:
                            continue
            except Exception:
                pass

        # Add newly collected candidates to live pool
        for cand in valid_candidates:
            live_pool[cand["canonical_url"]] = cand

        # Filter strictly for freshness and relevance
        live_cutoff = now - timedelta(hours=max_live_retention_hours)
        fresh_live_items: list[dict[str, Any]] = []
        pruned_count = 0

        for c_url, item in live_pool.items():
            p_dt = item["published_dt"]
            # Reject stale or future dated
            if p_dt < live_cutoff or p_dt > now + timedelta(minutes=15):
                pruned_count += 1
                continue

            # Check relevance
            is_rel = str(item.get("is_gold_relevant", "False")).lower() in ("true", "1")
            driver = item.get("driver_category", GoldDriver.OTHER_MACRO)
            direction = item.get("directional_implication", "UNCERTAIN")

            if is_rel or driver != GoldDriver.OTHER_MACRO or direction in ("BULLISH", "BEARISH"):
                fresh_live_items.append(item)

        # Cluster syndicated wire stories
        cluster_groups: dict[str, list[dict[str, Any]]] = {}
        for item in fresh_live_items:
            ck = item.get("cluster_key") or extract_cluster_key(item["title"])
            item["cluster_key"] = ck
            if ck not in cluster_groups:
                cluster_groups[ck] = []
            cluster_groups[ck].append(item)

        conf_weights = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        clustered_live_articles: list[dict[str, Any]] = []

        for ck, group in cluster_groups.items():
            # Pick representative article with highest confidence and freshness
            rep = sorted(
                group,
                key=lambda x: (
                    conf_weights.get(x.get("confidence", "LOW"), 1),
                    x["published_dt"],
                ),
                reverse=True,
            )[0]
            rep_copy = dict(rep)
            rep_copy["syndicated_copies_count"] = len(group)
            clustered_live_articles.append(rep_copy)

        # Sort descending by published_at
        clustered_live_articles.sort(key=lambda x: x["published_dt"], reverse=True)

        # Write out live_news.csv
        live_fieldnames = [
            "published_at",
            "ingested_at",
            "title",
            "url",
            "source",
            "language",
            "is_gold_relevant",
            "primary_category",
            "driver_category",
            "directional_implication",
            "confidence",
            "evidence_rationale",
            "cluster_key",
            "syndicated_copies_count",
        ]

        with live_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=live_fieldnames)
            writer.writeheader()
            for art in clustered_live_articles:
                writer.writerow({
                    "published_at": art["published_at"],
                    "ingested_at": art.get("ingested_at") or now.isoformat(),
                    "title": art["title"],
                    "url": art["url"],
                    "source": art["source"],
                    "language": art.get("language") or "en",
                    "is_gold_relevant": art.get("is_gold_relevant", True),
                    "primary_category": art.get("primary_category", "GOLD_DIRECT"),
                    "driver_category": art.get("driver_category", GoldDriver.OTHER_MACRO),
                    "directional_implication": art.get("directional_implication", "UNCERTAIN"),
                    "confidence": art.get("confidence", "LOW"),
                    "evidence_rationale": art.get("evidence_rationale", ""),
                    "cluster_key": art.get("cluster_key", ""),
                    "syndicated_copies_count": art.get("syndicated_copies_count", 1),
                })

        return {
            "new_archive_count": new_archive_count,
            "live_count": len(clustered_live_articles),
            "pruned_count": pruned_count,
        }

    @staticmethod
    def save_to_csv(
        articles: list[NewsArticle],
        csv_path: str | Path,
    ) -> int:
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = path.exists()

        existing_urls: set[str] = set()
        existing_titles: set[str] = set()

        if file_exists:
            with path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("url"):
                        existing_urls.add(normalize_url(row["url"]))
                    if row.get("title"):
                        existing_titles.add(normalize_title(row["title"]))

        new_count = 0
        with path.open("a", newline="", encoding="utf-8") as f:
            fieldnames = ["published_at", "title", "url", "source", "language"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()

            for a in articles:
                canon_url = normalize_url(a.url)
                norm_title = normalize_title(a.title)
                if canon_url in existing_urls or norm_title in existing_titles:
                    continue

                writer.writerow(
                    {
                        "published_at": a.published_at.isoformat(),
                        "title": a.title,
                        "url": a.url,
                        "source": a.source,
                        "language": a.language or "",
                    }
                )
                existing_urls.add(canon_url)
                existing_titles.add(norm_title)
                new_count += 1

        return new_count

    @staticmethod
    def load_from_csv(csv_path: str | Path) -> list[NewsArticle]:
        path = Path(csv_path)
        if not path.exists():
            return []

        articles: list[NewsArticle] = []
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    dt = datetime.fromisoformat(row["published_at"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                except Exception:
                    continue

                articles.append(
                    NewsArticle(
                        title=row.get("title", ""),
                        url=row.get("url", ""),
                        published_at=dt,
                        source=row.get("source", ""),
                        language=row.get("language") or None,
                    )
                )

        return articles