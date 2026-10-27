# Bullion Portfolio Valuation Methodology

## 1. Real-Time Mark-to-Market Valuation
Holdings are valued against the latest domestic physical spot benchmark (KJPL 999 rate).

### Gold Valuation Formula
Given a holding with gross weight $W$ (grams), purity $P$ (parts per thousand, e.g. 916), quantity $Q$, and current spot rate $R_{\text{KJPL}}$ (INR per gram of 999 gold):

$$\text{Current Market Value} = W \times Q \times R_{\text{KJPL}} \times \left(\frac{P}{999}\right)$$

### Silver Valuation Formula
KJPL quotes physical silver in INR per gram (e.g. ₹220.0/g, representing ₹220,000/kg). Given current spot silver rate $R_{\text{silver}}$ in INR per gram of 999 silver:

$$\text{Current Market Value} = W \times Q \times R_{\text{silver}} \times \left(\frac{P}{0.999}\right)$$

*(Or equivalently if referencing per-kilogram wholesale rates: $\frac{W \times Q}{1000} \times R_{\text{silver\_per\_kg}} \times \frac{P}{0.999}$).*

---

## 2. Unrealized PnL Calculation

$$\text{Unrealized PnL (INR)} = \text{Current Market Value} - \text{Total Acquisition Cost}$$

$$\text{Unrealized PnL (\%)} = \left(\frac{\text{Current Market Value} - \text{Total Acquisition Cost}}{\text{Total Acquisition Cost}}\right) \times 100$$
