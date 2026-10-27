# Model Training & Validation Methodology

## 1. Time-Series Cross Validation
Precious metals prices exhibit non-stationary auto-correlation. Traditional $K$-fold cross-validation is strictly forbidden as it shuffles future events into past training partitions, causing lookahead leakage.

GoldSense AI employs **TimeSeriesSplit (Walk-Forward Validation)**:
- Split 1: Train on events $[1 \dots T_1]$, Test on $[T_1+1 \dots T_2]$
- Split 2: Train on events $[1 \dots T_2]$, Test on $[T_2+1 \dots T_3]$
- Split $k$: Train on $[1 \dots T_k]$, Test on $[T_k+1 \dots T_{k+1}]$

---

## 2. Evaluation Metrics

1. **Mean Absolute Error (MAE)**:
   $$\text{MAE} = \frac{1}{N} \sum_{i=1}^N |y_i - \hat{y}_i|$$
   *Directly interpretable in Indian Rupees per gram (e.g. $\pm ₹45/\text{g}$).*

2. **Root Mean Squared Error (RMSE)**:
   $$\text{RMSE} = \sqrt{\frac{1}{N} \sum_{i=1}^N (y_i - \hat{y}_i)^2}$$
   *Penalizes large prediction errors during geopolitical volatility spikes.*

3. **Directional Accuracy (DA)**:
   $$\text{DA} = \frac{1}{N-1} \sum_{i=2}^N \mathbb{I}\left(\text{sgn}(y_i - y_{i-1}) == \text{sgn}(\hat{y}_i - y_{i-1})\right)$$
   *Measures whether the model correctly anticipates whether gold goes up or down.*
