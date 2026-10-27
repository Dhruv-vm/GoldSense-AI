# Rate Units, Metallurgical Standards & Conversion Math

## 1. Unit Definitions

- **Troy Ounce (oz t)**: Standard unit for international precious metal trading.
  $$1 \text{ oz t} \equiv 31.1034768 \text{ grams}$$
  *(Caution: Do not use the avoirdupois ounce, which equals $28.3495\text{ g}$).*
- **Gram (g)**: Standard retail and wholesale unit in India for gold. KJPL records both Gold (`gold_mjdta` ~₹13,135/g) and Silver (`silver_mjdta` ~₹220/g) in **INR per gram**.
- **Kilogram (kg)**: Standard wholesale physical delivery bar size for silver ($1\text{ kg} = 1000\text{ g} \approx ₹220,000$).

---

## 2. Benchmark Conversion Formulas

### Global Gold Parity (USD/oz to INR/g)
$$\text{Global Gold (INR/g)} = \frac{\text{GC=F (USD/oz)} \times \text{USDINR}}{31.1034768}$$

### Global Silver Parity (USD/oz to INR/kg)
$$\text{Global Silver (INR/kg)} = \frac{\text{SI=F (USD/oz)} \times \text{USDINR} \times 1000}{31.1034768}$$

---

## 3. Domestic Premium / Disparity Index
$$\text{Domestic Premium (\%)} = \frac{\text{KJPL Rate} - \text{Global Rate (INR/g)}}{\text{Global Rate (INR/g)}} \times 100$$

### Why Does a Domestic Premium Exist in India?
1. **Basic Customs Duty (BCD)**: 6% tariff on imported gold bullion.
2. **Agriculture Infrastructure and Development Cess (AIDC)**: Additional cess applied at import customs.
3. **Local Handling, Insurance & Transport**: Transit costs from international vaults (London, Zurich) to Ahmedabad refineries.
4. **Physical Delivery Premium**: Local physical supply tightness vs. paper derivative contracts.
*Normal range observed: $+5.5\%$ to $+7.5\%$.*

---

## 4. Metallurgical Purity Standards

| Purity Code | Common Name | Fineness | Fine Gold / 10g Gross |
| :--- | :--- | :--- | :--- |
| **999.9** | 24K Minted Bar | $0.9999$ | $9.999\text{ g}$ |
| **995.0** | 24K Standard Bullion | $0.9950$ | $9.950\text{ g}$ |
| **916.0** | 22K Hallmarked Jewelry | $0.9160$ | $9.160\text{ g}$ |
| **750.0** | 18K Diamond Jewelry | $0.7500$ | $7.500\text{ g}$ |
