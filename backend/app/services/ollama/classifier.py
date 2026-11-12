from __future__ import annotations

import json
import os
import re
from typing import Any

import requests
from pydantic import BaseModel, ValidationError

from app.services.sentiment.schemas import (
    GeneralTone,
    GoldImpactDirection,
    GoldMacroDriver,
    GoldSentimentResult,
    MacroSurprise,
)

OLLAMA_PROMPT_VERSION = "GOLD_OLLAMA_PROMPT_V1"
OLLAMA_CLASSIFIER_IMPL_VERSION = "OLLAMA_CLASSIFIER_V2"
DEFAULT_OLLAMA_MODEL = "qwen3.5:4b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

SYSTEM_PROMPT = """You are a quantitative commodities analyst focused exclusively on Indian and global gold pricing.
Classify a single financial news headline strictly as JSON with NO markdown and NO extra keys:
{
  "general_tone": "POSITIVE|NEGATIVE|NEUTRAL|UNKNOWN",
  "gold_impact": "BULLISH|BEARISH|MIXED|NEUTRAL|UNKNOWN",
  "driver": "FED_POLICY|US_INTEREST_RATES|INFLATION|USD|INR|GEOPOLITICS|CENTRAL_BANKS|INDIAN_PHYSICAL_DEMAND|GOLD_ETF|INDIA_IMPORT_DUTY_POLICY|GOLD_PRICE_REPORT|OTHER_MACRO|UNKNOWN",
  "surprise": "HAWKISH_SURPRISE|DOVISH_SURPRISE|POSITIVE_SURPRISE|NEGATIVE_SURPRISE|AS_EXPECTED|UNKNOWN",
  "is_price_report": true|false,
  "confidence": "HIGH|MEDIUM|LOW",
  "evidence_rationale": "short 1-sentence reason"
}

Rules:
- Separate general news tone from gold_impact. E.g., rising interest rates or stronger USD may have POSITIVE equity/macro tone but BEARISH gold_impact.
- Use GOLD_PRICE_REPORT and is_price_report=true for descriptive daily city rate/price recaps with no forward macro driver.
- Use UNKNOWN when gold transmission is genuinely ambiguous rather than guessing.
"""


class OllamaClassificationError(RuntimeError):
    """Raised when Ollama is unavailable or returns invalid/non-conformant JSON."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


class _StrictOllamaPayload(BaseModel):
    general_tone: GeneralTone
    gold_impact: GoldImpactDirection
    driver: GoldMacroDriver
    surprise: MacroSurprise
    is_price_report: bool
    confidence: str
    evidence_rationale: str


def is_ollama_enabled() -> bool:
    return os.getenv("OLLAMA_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def parse_ollama_json_response(
    raw_text: str,
    model_name: str = DEFAULT_OLLAMA_MODEL,
    model_digest: str | None = None,
) -> GoldSentimentResult:
    """
    Strictly parse and validate Ollama JSON response against the separated gold schema.
    Raises OllamaClassificationError('INVALID_OUTPUT', ...) on malformed JSON or invalid enums.
    """
    if not raw_text or not isinstance(raw_text, str):
        raise OllamaClassificationError("INVALID_OUTPUT", "Empty response from Ollama model.")

    cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()

    try:
        parsed_dict: Any = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise OllamaClassificationError("INVALID_OUTPUT", f"Malformed JSON output: {exc}") from exc

    if not isinstance(parsed_dict, dict):
        raise OllamaClassificationError("INVALID_OUTPUT", "Ollama output must be a JSON object.")

    try:
        validated = _StrictOllamaPayload.model_validate(parsed_dict)
    except ValidationError as exc:
        raise OllamaClassificationError("INVALID_OUTPUT", f"Schema validation failed: {exc}") from exc

    conf = validated.confidence.strip().upper()
    if conf not in {"HIGH", "MEDIUM", "LOW"}:
        raise OllamaClassificationError("INVALID_OUTPUT", f"Invalid confidence level: {validated.confidence}")

    return GoldSentimentResult(
        general_tone=validated.general_tone,
        gold_impact=validated.gold_impact,
        driver=validated.driver,
        surprise=validated.surprise,
        is_price_report=validated.is_price_report,
        confidence=conf,
        evidence_rationale=validated.evidence_rationale.strip()[:400],
        sentiment_version="GOLD_OLLAMA_V2",
        model_name=model_name,
        model_digest=model_digest,
        prompt_version=OLLAMA_PROMPT_VERSION,
    )


class OllamaGoldClassifier:
    """Optional local LLM research classifier backed by Ollama (never required in CI)."""

    def __init__(
        self,
        model_name: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.model_name = model_name or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL)).rstrip("/")
        self.timeout = timeout

    def health_check(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=min(self.timeout, 5))
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", []) if isinstance(m, dict)]
            return any(self.model_name in m for m in models)
        except Exception:
            return False

    def _resolve_model_digest(self) -> str | None:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=min(self.timeout, 5))
            resp.raise_for_status()
            for m in resp.json().get("models", []):
                if isinstance(m, dict) and self.model_name in str(m.get("name", "")):
                    digest = str(m.get("digest") or "")
                    return digest[:32] if digest else None
        except Exception:
            return None
        return None

    def classify_and_persist(
        self,
        db: Any,
        *,
        story_cluster_id: str,
        title: str,
        article_id: int | None = None,
        source: str = "",
        language: str = "en",
        classification_scope: str = "CLUSTER",
        collection_run_id: str | None = None,
    ) -> GoldSentimentResult:
        """Classify a headline with Ollama and append an immutable NewsLabelRecord row to DB.

        DB-enforced concurrency idempotency (A3-FINAL-5):
          - Computes deterministic `classification_identity_hash` covering cluster/article
            scope, model name, model version, model digest, prompt version, and classifier
            implementation version, backed by partial unique index `uq_news_label_llm_identity`.
          - Ensures referenced NewsCluster exists safely without racing.
          - Catches concurrent IntegrityError inside a savepoint / rollback so the caller's
            SQLAlchemy session is never poisoned.
          - Never mixes into `deterministic_rules_v2` and never falls back to deterministic rules.
        """
        from contextlib import nullcontext
        from datetime import datetime, timezone
        import hashlib
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError
        from app.models.research import NewsCluster, NewsLabelRecord
        from app.services.sentiment.label_store import compute_label_hash
        from app.services.sentiment.provenance import CLUSTER_VERSION, extract_story_cluster_key

        def _tx_savepoint():
            return db.begin_nested() if hasattr(db, "begin_nested") else nullcontext()

        scope = classification_scope.upper().strip() or "CLUSTER"
        if scope not in {"CLUSTER", "ARTICLE"}:
            raise ValueError(f"Unsupported classification_scope={classification_scope!r}")

        res = self.classify_headline(title=title, source=source, language=language)
        impl_ver = OLLAMA_CLASSIFIER_IMPL_VERSION
        p_ver = res.prompt_version or OLLAMA_PROMPT_VERSION
        m_digest = res.model_digest or ""
        id_payload = "|".join(
            [
                story_cluster_id,
                scope,
                str(article_id) if scope == "ARTICLE" and article_id is not None else "",
                res.model_name,
                res.sentiment_version,
                m_digest,
                p_ver,
                impl_ver,
            ]
        )
        identity_hash = hashlib.sha256(id_payload.encode("utf-8")).hexdigest()[:64]

        l_hash = compute_label_hash(
            story_cluster_id=story_cluster_id,
            sentiment_version=f"{res.sentiment_version}|{p_ver}|{impl_ver}",
            model_name=res.model_name,
            gold_impact=res.gold_impact.value,
            driver=res.driver.value,
            is_price_report=res.is_price_report,
            model_digest=res.model_digest,
        )
        try:
            # Ensure cluster row exists safely even under concurrent workers (or direct standalone calls)
            existing_cluster = db.execute(
                select(NewsCluster).where(NewsCluster.story_cluster_id == story_cluster_id)
            ).scalar_one_or_none()
            if existing_cluster is None:
                try:
                    with _tx_savepoint():
                        db.add(
                            NewsCluster(
                                story_cluster_id=story_cluster_id,
                                cluster_key=extract_story_cluster_key(title)[:255] or story_cluster_id,
                                cluster_version=CLUSTER_VERSION,
                                first_seen_at=None,
                                latest_published_at=None,
                                representative_title=title[:500] or story_cluster_id,
                                article_count=0,
                            )
                        )
                        if hasattr(db, "flush"):
                            db.flush()
                except IntegrityError:
                    pass

            existing_by_id = db.execute(
                select(NewsLabelRecord)
                .where(NewsLabelRecord.classification_identity_hash == identity_hash)
                .limit(1)
            ).scalar_one_or_none()
            if existing_by_id is not None:
                return res

            now_utc = datetime.now(timezone.utc)
            try:
                with _tx_savepoint():
                    db.add(
                        NewsLabelRecord(
                            article_id=article_id,
                            story_cluster_id=story_cluster_id,
                            collection_run_id=collection_run_id,
                            classification_scope=scope,
                            label_created_at=now_utc,
                            db_recorded_at=now_utc,
                            available_at=now_utc,
                            sentiment_version=res.sentiment_version,
                            model_name=res.model_name,
                            model_digest=res.model_digest,
                            prompt_version=p_ver,
                            classifier_impl_version=impl_ver,
                            classification_identity_hash=identity_hash,
                            general_tone=res.general_tone.value,
                            gold_impact=res.gold_impact.value,
                            driver=res.driver.value,
                            surprise=res.surprise.value,
                            is_price_report=res.is_price_report,
                            feature_eligible=True,
                            label_hash=l_hash,
                            confidence=res.confidence,
                            evidence_rationale=res.evidence_rationale,
                            is_human_verified=False,
                        )
                    )
                    if hasattr(db, "flush"):
                        db.flush()
            except IntegrityError:
                # Concurrent worker won uq_news_label_llm_identity; savepoint rolled back cleanly.
                return res

            db.commit()
        except IntegrityError:
            db.rollback()
            return res
        except Exception:
            db.rollback()
            raise
        return res

    def classify_headline(
        self,
        title: str,
        source: str = "",
        language: str = "en",
        max_retries: int = 2,
    ) -> GoldSentimentResult:
        if not title or not title.strip():
            raise OllamaClassificationError("INVALID_INPUT", "Headline title must not be empty.")

        user_prompt = (
            f"Headline: {title.strip()}\n"
            f"Source: {source or 'unknown'}\n"
            f"Language: {language or 'unknown'}\n"
            "Respond with strict JSON only."
        )
        schema_format = _StrictOllamaPayload.model_json_schema()
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": schema_format,
            "options": {"temperature": 0, "num_predict": 384},
        }
        last_exc: Exception | None = None
        for attempt in range(max(1, max_retries)):
            try:
                resp = requests.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                body = resp.json()
            except requests.RequestException as exc:
                last_exc = OllamaClassificationError("UNAVAILABLE", f"Ollama request failed: {exc}")
                continue
            except ValueError as exc:
                last_exc = OllamaClassificationError("INVALID_OUTPUT", f"Invalid Ollama HTTP JSON response: {exc}")
                continue

            message_content = ""
            if isinstance(body, dict):
                msg = body.get("message")
                if isinstance(msg, dict):
                    message_content = str(msg.get("content") or "")
                elif "response" in body:
                    message_content = str(body.get("response") or "")

            try:
                digest = self._resolve_model_digest()
                return parse_ollama_json_response(
                    message_content,
                    model_name=self.model_name,
                    model_digest=digest,
                )
            except OllamaClassificationError as exc:
                last_exc = exc
                continue

        if isinstance(last_exc, OllamaClassificationError):
            raise last_exc
        raise OllamaClassificationError("UNAVAILABLE", "Ollama classification failed.")
