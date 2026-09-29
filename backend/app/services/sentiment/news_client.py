from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

DEFAULT_QUERY = (
    "(gold OR bullion OR XAUUSD OR "
    "\"gold price\" OR \"precious metals\") "
    "AND (market OR inflation OR rates OR "
    "Fed OR dollar OR USD OR India)"
)


@dataclass
class NewsArticle:
    title: str
    url: str
    published_at: datetime
    source: str
    language: str | None = None


class NewsClient:
    """
    Collects recent financial and gold-related news from GDELT.

    Responsibilities:
        - Query GDELT
        - Handle HTTP errors
        - Handle rate limiting
        - Convert API results into NewsArticle objects

    Sentiment analysis is handled separately by analyzer.py.
    """

    def __init__(
        self,
        timeout: int = 20,
        max_retries: int = 3,
        retry_wait_seconds: int = 10,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_wait_seconds = retry_wait_seconds

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": (
                    "GoldSense-AI/1.0 "
                    "(financial research and market analysis)"
                )
            }
        )

    def search(
        self,
        query: str = DEFAULT_QUERY,
        start_datetime: datetime | None = None,
        end_datetime: datetime | None = None,
        max_records: int = 50,
    ) -> list[NewsArticle]:
        """
        Search GDELT for relevant news articles.

        Args:
            query:
                GDELT search query.

            start_datetime:
                Optional lower time boundary.

            end_datetime:
                Optional upper time boundary.

            max_records:
                Maximum number of articles to request.

        Returns:
            List of NewsArticle objects.
        """

        params: dict[str, Any] = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": max_records,
            "sort": "datedesc",
        }

        if start_datetime is not None:
            params["startdatetime"] = (
                start_datetime.strftime(
                    "%Y%m%d%H%M%S"
                )
            )

        if end_datetime is not None:
            params["enddatetime"] = (
                end_datetime.strftime(
                    "%Y%m%d%H%M%S"
                )
            )

        response = self._request_with_retry(
            params=params
        )

        payload = response.json()

        articles: list[NewsArticle] = []

        for item in payload.get("articles", []):
            article = self._parse_article(item)

            if article is not None:
                articles.append(article)

        return articles

    def _request_with_retry(
        self,
        params: dict[str, Any],
    ) -> requests.Response:
        """
        Make a GDELT request with controlled retries.

        HTTP 429 is handled using increasing delays.
        """

        for attempt in range(
            self.max_retries
        ):
            try:
                response = self.session.get(
                    GDELT_URL,
                    params=params,
                    timeout=self.timeout,
                )

            except requests.RequestException as exc:

                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        "GDELT request failed after "
                        f"{self.max_retries} attempts."
                    ) from exc

                wait_seconds = (
                    self.retry_wait_seconds
                    * (attempt + 1)
                )

                print(
                    "[NEWS] GDELT request error. "
                    f"Retrying in {wait_seconds}s..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            if response.status_code == 429:

                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        "GDELT rate limit reached after "
                        f"{self.max_retries} attempts. "
                        "Try again later."
                    )

                wait_seconds = (
                    self.retry_wait_seconds
                    * (attempt + 1)
                )

                print(
                    "[NEWS] GDELT rate limited "
                    f"the request. "
                    f"Waiting {wait_seconds}s..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            response.raise_for_status()

            return response

        raise RuntimeError(
            "GDELT request failed unexpectedly."
        )

    @staticmethod
    def _parse_article(
        item: dict[str, Any],
    ) -> NewsArticle | None:
        """
        Convert a single GDELT article dictionary
        into a NewsArticle.
        """

        published_text = item.get(
            "seendate"
        )

        if not published_text:
            return None

        try:
            published_at = datetime.strptime(
                published_text[:14],
                "%Y%m%d%H%M%S",
            )

        except (TypeError, ValueError):
            return None

        title = (
            item.get("title")
            or ""
        ).strip()

        url = (
            item.get("url")
            or ""
        ).strip()

        source = (
            item.get("domain")
            or ""
        ).strip()

        language = (
            item.get("language")
        )

        if not title or not url:
            return None

        return NewsArticle(
            title=title,
            url=url,
            published_at=published_at,
            source=source,
            language=language,
        )