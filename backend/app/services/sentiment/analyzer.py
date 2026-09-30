from __future__ import annotations

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.services.sentiment.relevance import GoldRelevanceScorer
from app.services.sentiment.schemas import (
    AnalyzedArticle,
    NewsArticle,
    RelevanceScore,
    SentimentScore,
)

DEFAULT_MODEL_NAME = "ProsusAI/finbert"


class SentimentAnalyzer:
    """
    Financial sentiment analyzer powered by FinBERT (ProsusAI/finbert).

    Separates financial sentiment classification (positive/negative/neutral)
    from gold market relevance.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        device: str | None = None,
        batch_size: int = 16,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size

        if device is not None:
            self.device = torch.device(device)
        elif torch.backends.mps.is_available():
            self.device = torch.device("mps")
        elif torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self.device = torch.device("cpu")

        self._tokenizer: AutoTokenizer | None = None
        self._model: AutoModelForSequenceClassification | None = None
        self._relevance_scorer = GoldRelevanceScorer()
        self._label_indices: dict[str, int] = {}

    def _load_model(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        print(f"[SENTIMENT] Loading FinBERT model ({self.model_name}) on {self.device}...")
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        try:
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                use_safetensors=False,
            )
        except Exception:
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
            )
        self._model.to(self.device)
        self._model.eval()

        id2label = self._model.config.id2label
        # Map label names (lowercase) to their logit indices
        self._label_indices = {
            label.lower(): idx for idx, label in id2label.items()
        }

    @property
    def tokenizer(self) -> AutoTokenizer:
        self._load_model()
        assert self._tokenizer is not None
        return self._tokenizer

    @property
    def model(self) -> AutoModelForSequenceClassification:
        self._load_model()
        assert self._model is not None
        return self._model

    def analyze_text(self, text: str) -> SentimentScore:
        """
        Analyze a single text string and return its financial sentiment score.
        """
        results = self.analyze_texts([text])
        return results[0]

    def analyze_texts(self, texts: list[str]) -> list[SentimentScore]:
        """
        Batch analyze multiple text strings using FinBERT.
        """
        if not texts:
            return []

        self._load_model()
        assert self._model is not None
        assert self._tokenizer is not None

        pos_idx = self._label_indices.get("positive", 0)
        neg_idx = self._label_indices.get("negative", 1)
        neu_idx = self._label_indices.get("neutral", 2)

        results: list[SentimentScore] = []

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]

            # Handle empty / whitespace-only text safely
            clean_batch = [t.strip() if t and t.strip() else "neutral market update" for t in batch_texts]

            inputs = self._tokenizer(
                clean_batch,
                padding=True,
                truncation=True,
                max_length=128,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                outputs = self._model(**inputs)
                probs = torch.softmax(outputs.logits, dim=-1).cpu()

            for j, original_text in enumerate(batch_texts):
                if not original_text or not original_text.strip():
                    results.append(
                        SentimentScore(
                            positive_probability=0.0,
                            negative_probability=0.0,
                            neutral_probability=1.0,
                            sentiment_score=0.0,
                            label="neutral",
                        )
                    )
                    continue

                p_pos = float(probs[j, pos_idx].item())
                p_neg = float(probs[j, neg_idx].item())
                p_neu = float(probs[j, neu_idx].item())

                # Continuous sentiment score from -1.0 (purely negative) to +1.0 (purely positive)
                sentiment_score = round(p_pos - p_neg, 4)

                # Determine dominant label
                prob_map = {"positive": p_pos, "negative": p_neg, "neutral": p_neu}
                label = max(prob_map, key=prob_map.get)

                results.append(
                    SentimentScore(
                        positive_probability=round(p_pos, 4),
                        negative_probability=round(p_neg, 4),
                        neutral_probability=round(p_neu, 4),
                        sentiment_score=sentiment_score,
                        label=label,
                    )
                )

        return results

    def analyze_article(self, article: NewsArticle) -> AnalyzedArticle:
        """
        Analyze a single NewsArticle for both FinBERT sentiment and gold relevance.
        """
        results = self.analyze_articles([article])
        return results[0]

    def analyze_articles(self, articles: list[NewsArticle]) -> list[AnalyzedArticle]:
        """
        Analyze a collection of NewsArticle objects in batch for both
        sentiment and gold relevance.
        """
        if not articles:
            return []

        # 1. Evaluate gold relevance for all articles
        relevances = [self._relevance_scorer.score_article(a) for a in articles]

        # 2. Prepare text for sentiment analysis (headline + description if available)
        texts_to_analyze: list[str] = []
        for a in articles:
            if a.description and a.description.strip():
                texts_to_analyze.append(f"{a.title}. {a.description.strip()}")
            else:
                texts_to_analyze.append(a.title)

        # 3. Batch sentiment inference
        sentiments = self.analyze_texts(texts_to_analyze)

        # 4. Combine into AnalyzedArticle
        analyzed: list[AnalyzedArticle] = []
        for article, sentiment, relevance in zip(articles, sentiments, relevances):
            analyzed.append(
                AnalyzedArticle(
                    article=article,
                    sentiment=sentiment,
                    relevance=relevance,
                )
            )

        return analyzed
