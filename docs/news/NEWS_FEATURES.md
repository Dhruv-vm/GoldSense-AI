# News Feature Engineering for ML

## 1. Feature Representation
For each physical market event at date $T_{event}$, news articles within the lookback window $[T_{event} - 24\text{h}, T_{event}]$ are aggregated into four numeric features:

1. **`sentiment_score_mean`**:
   The mean sentiment score $S$ across all gold-relevant articles published in the 24-hour window:
   $$\bar{S} = \frac{1}{K} \sum_{k=1}^K S_k$$
   *(Defaults to $0.0$ if no articles were published).*

2. **`sentiment_score_std`**:
   The standard deviation of sentiment scores, measuring market consensus vs. disagreement:
   $$\sigma_S = \sqrt{\frac{1}{K} \sum_{k=1}^K (S_k - \bar{S})^2}$$
   *(Defaults to $0.0$ if $K \le 1$).*

3. **`news_volume_24h`**:
   The total count of bullion-relevant news articles published in the 24-hour window, capturing market attention and media intensity.

4. **`bullish_ratio`**:
   The proportion of articles with $S > 0.15$ relative to total relevant articles.
