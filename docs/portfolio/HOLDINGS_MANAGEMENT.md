# Holdings Management & User Guide

## 1. Managing Physical Assets

### Adding a Holding
1. Open the **My Bullion Portfolio** tab in the GoldSense AI terminal.
2. Click **+ Add Holding**.
3. Fill out the details:
   - **Metal**: Gold or Silver.
   - **Weight & Unit**: Enter weight and select `g` (grams) or `kg` (kilograms).
   - **Purity / Fineness**: Select standard presets (24K 999.9, 24K 995, 22K 916, 18K 750) or enter custom millesimal fineness.
   - **Acquisition Cost**: Enter your purchase price per gram or total cost.
   - **Purchase Date & Notes**: Optional tracking notes.
4. Click **Save Holding**.

### Editing a Holding
1. In the **My Bullion** table, click the ✎ (pencil) icon next to any holding.
2. An **Edit Bullion Holding** modal appears, pre-populated with current properties.
3. Update weight, purity, unit, acquisition cost, or notes.
4. Click **Save Changes** (issues `PUT /api/portfolio/holdings/{id}`).

### Handling Unknown or Inherited Acquisition Costs
- If an item was inherited, gifted, or the original purchase price is unknown, leave the cost input empty.
- The platform records the cost as `None` / `Unknown` and marks Unrealized Gain/Loss as `Unmeasured` (`—`).
- This prevents distorting portfolio return percentages with false 100% gains.

### Historical Vault Valuation
- The `GET /api/portfolio/history` endpoint traces the mark-to-market valuation of your physical vault across all recorded historical KJPL trading dates.

### Deleting a Holding
Click the red trash icon on any holding row to remove it from your portfolio.

---

## 2. Strict Non-Commercial Scope
GoldSense AI is dedicated strictly to personal wealth monitoring:
- **No POS transactions or cash register registers.**
- **No invoices or GST billing generation.**
- **No customer accounts, merchant accounts, or sales journals.**
