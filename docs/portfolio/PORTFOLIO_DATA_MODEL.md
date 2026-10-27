# Personal Bullion Portfolio Data Model

## 1. Domain Object: `PortfolioHolding`

The `PortfolioHolding` entity represents an individual physical bullion item owned by the user.

### Attributes & Units
- **`id`** (`int`): Primary key.
- **`user_id`** (`str`): Multi-tenant owner identifier.
- **`metal`** (`str`): `gold` or `silver`.
- **`gross_weight_g`** (`float`): Gross physical weight normalized to grams.
- **`fine_weight_g`** (`float`): Net weight of 100% pure precious metal in grams.
- **`purity`** (`float`): Millesimal fineness (e.g., $999.9$, $995.0$, $916.0$, $750.0$).
- **`quantity`** (`int`): Number of identical units.
- **`purchase_price_per_g`** (`float`): Acquisition cost per gross gram in INR.
- **`total_acquisition_cost`** (`float`): Total expenditure in INR.
- **`purchase_date`** (`datetime`): Purchase acquisition timestamp.
- **`notes`** (`str`): User annotations (e.g. mint hallmark, certificate number).

---

## 2. Invariant Rules
1. `gross_weight_g > 0`
2. `0 < purity <= 1000`
3. `fine_weight_g = gross_weight_g * (purity / 1000)`
4. `total_acquisition_cost = gross_weight_g * purchase_price_per_g * quantity` (when unit cost is provided).
