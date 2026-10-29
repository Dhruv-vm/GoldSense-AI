from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, delete

from app.db.session import SessionLocal, engine
from app.db.base import Base
from app.models.portfolio import PortfolioHolding
from app.services.data_service import get_latest_kjpl_from_csv, init_database


def get_current_benchmark_rates() -> tuple[float, float]:
    """Retrieve current gold and silver benchmark rates in INR per gram."""
    kjpl = get_latest_kjpl_from_csv()
    if kjpl:
        gold_rate = float(kjpl["gold_mjdta"])
        silver_rate = float(kjpl["silver_mjdta"])
    else:
        # Fallback conservative benchmarks
        gold_rate = 13135.0
        silver_rate = 220.0
    return gold_rate, silver_rate


class PortfolioService:
    @staticmethod
    def list_holdings(user_id: str = "default_user") -> list[dict[str, Any]]:
        init_database()
        gold_rate, silver_rate = get_current_benchmark_rates()

        with SessionLocal() as session:
            stmt = (
                select(PortfolioHolding)
                .where(PortfolioHolding.user_id == user_id)
                .order_by(PortfolioHolding.created_at.desc())
            )
            holdings = session.scalars(stmt).all()

            results = []
            for h in holdings:
                metal = h.metal_type.upper()
                rate_per_gram = gold_rate if metal == "GOLD" else silver_rate

                # Reconciled benchmark valuation:
                # Rate is quoted for 0.999 benchmark purity.
                # Valuation = Gross Weight * Rate * (Purity / 0.999) * Quantity
                benchmark_purity = 0.999
                current_valuation = round(h.gross_weight_grams * (h.purity / benchmark_purity) * rate_per_gram * h.quantity, 2)

                gain_loss_inr = None
                gain_loss_pct = None
                if h.acquisition_cost_inr is not None and h.acquisition_cost_inr > 0:
                    total_cost = h.acquisition_cost_inr * h.quantity
                    gain_loss_inr = round(current_valuation - total_cost, 2)
                    gain_loss_pct = round((gain_loss_inr / total_cost) * 100, 2)

                results.append({
                    "id": h.id,
                    "metal_type": h.metal_type,
                    "product_name": h.product_name,
                    "purity": h.purity,
                    "gross_weight_grams": h.gross_weight_grams,
                    "fine_weight_grams": h.fine_weight_grams,
                    "fine_weight_kg": round(h.fine_weight_grams / 1000.0, 4),
                    "quantity": h.quantity,
                    "acquisition_date": h.acquisition_date,
                    "acquisition_cost_inr": h.acquisition_cost_inr,
                    "current_valuation_inr": current_valuation,
                    "unrealized_gain_loss_inr": gain_loss_inr,
                    "unrealized_gain_loss_pct": gain_loss_pct,
                    "notes": h.notes,
                    "created_at": h.created_at.isoformat() if h.created_at else None,
                })
            return results

    @staticmethod
    def create_holding(data: dict[str, Any], user_id: str = "default_user") -> dict[str, Any]:
        init_database()
        metal = str(data.get("metal_type", "GOLD")).upper()
        if metal not in ("GOLD", "SILVER"):
            raise ValueError(f"Invalid metal_type: {metal}. Must be 'GOLD' or 'SILVER'.")

        product_name = str(data.get("product_name", "Bullion Item")).strip()
        purity = float(data.get("purity", 0.999))
        if purity > 1.0:
            purity = round(purity / 1000.0, 5)
        if purity <= 0.0 or purity > 1.0:
            raise ValueError(f"Invalid purity: {purity}. Must be between 0.0 and 1.0 (or 0 to 1000 millesimal).")

        unit = str(data.get("weight_unit", "g")).lower()
        raw_weight = float(data.get("gross_weight", 0.0))
        if raw_weight <= 0.0:
            raise ValueError("Gross weight must be greater than 0.")

        # Unit conversion: support grams and kilograms
        gross_grams = raw_weight * 1000.0 if unit in ("kg", "kilogram", "kilograms") else raw_weight
        fine_grams = round(gross_grams * purity, 4)
        quantity = int(data.get("quantity", 1))
        if quantity < 1:
            quantity = 1

        acq_cost = data.get("acquisition_cost_inr")
        acq_cost_val = float(acq_cost) if acq_cost is not None and str(acq_cost).strip() != "" else None

        holding = PortfolioHolding(
            user_id=user_id,
            metal_type=metal,
            product_name=product_name,
            purity=purity,
            gross_weight_grams=gross_grams,
            fine_weight_grams=fine_grams,
            quantity=quantity,
            acquisition_date=data.get("acquisition_date"),
            acquisition_cost_inr=acq_cost_val,
            notes=data.get("notes"),
        )

        with SessionLocal() as session:
            session.add(holding)
            session.commit()
            session.refresh(holding)
            holding_id = holding.id

        return PortfolioService.get_holding_by_id(holding_id, user_id=user_id)

    @staticmethod
    def get_holding_by_id(holding_id: int, user_id: str = "default_user") -> dict[str, Any] | None:
        holdings = PortfolioService.list_holdings(user_id=user_id)
        for h in holdings:
            if h["id"] == holding_id:
                return h
        return None

    @staticmethod
    def update_holding(holding_id: int, data: dict[str, Any], user_id: str = "default_user") -> dict[str, Any] | None:
        init_database()
        with SessionLocal() as session:
            stmt = (
                select(PortfolioHolding)
                .where(PortfolioHolding.id == holding_id, PortfolioHolding.user_id == user_id)
            )
            holding = session.scalar(stmt)
            if not holding:
                return None

            if "metal_type" in data:
                m = str(data["metal_type"]).upper()
                if m in ("GOLD", "SILVER"):
                    holding.metal_type = m
            if "product_name" in data:
                holding.product_name = str(data["product_name"]).strip()
            if "purity" in data:
                p = float(data["purity"])
                if p > 1.0:
                    p = round(p / 1000.0, 5)
                if 0.0 < p <= 1.0:
                    holding.purity = p
            if "gross_weight" in data:
                gw = float(data["gross_weight"])
                unit = str(data.get("weight_unit", "g")).lower()
                gross_grams = gw * 1000.0 if unit in ("kg", "kilogram") else gw
                if gross_grams > 0:
                    holding.gross_weight_grams = gross_grams

            # Recalculate fine weight
            holding.fine_weight_grams = round(holding.gross_weight_grams * holding.purity, 4)

            if "quantity" in data:
                q = int(data["quantity"])
                if q >= 1:
                    holding.quantity = q
            if "acquisition_date" in data:
                holding.acquisition_date = data["acquisition_date"]
            if "acquisition_cost_inr" in data:
                val = data["acquisition_cost_inr"]
                holding.acquisition_cost_inr = float(val) if val is not None and str(val).strip() != "" else None
            if "notes" in data:
                holding.notes = data["notes"]

            holding.updated_at = datetime.now(timezone.utc)
            session.commit()

        return PortfolioService.get_holding_by_id(holding_id, user_id=user_id)

    @staticmethod
    def delete_holding(holding_id: int, user_id: str = "default_user") -> bool:
        init_database()
        with SessionLocal() as session:
            stmt = (
                delete(PortfolioHolding)
                .where(PortfolioHolding.id == holding_id, PortfolioHolding.user_id == user_id)
            )
            res = session.execute(stmt)
            session.commit()
            return res.rowcount > 0

    @staticmethod
    def get_historical_valuation(user_id: str = "default_user") -> list[dict[str, Any]]:
        """
        Evaluate user's current holdings across historical KJPL rate events.
        Produces an auditable time-series of historical portfolio valuations.
        """
        init_database()
        holdings = PortfolioService.list_holdings(user_id=user_id)
        if not holdings:
            return []

        from app.services.data_service import KJPL_CSV
        if not KJPL_CSV.exists():
            return []

        import csv
        with KJPL_CSV.open("r", encoding="utf-8") as f:
            kjpl_records = list(csv.DictReader(f))

        history = []
        for row in kjpl_records:
            try:
                gold_rate = float(row["gold_mjdta"])
                silver_rate = float(row.get("silver_mjdta", 0.0)) if row.get("silver_mjdta") else 220.0
                obs_date = row.get("observed_at", "")[:10]

                total_val = 0.0
                gold_val = 0.0
                silver_val = 0.0

                for h in holdings:
                    qty = h["quantity"]
                    benchmark_purity = 0.999
                    if h["metal_type"] == "GOLD":
                        val = round(h["gross_weight_grams"] * (h["purity"] / benchmark_purity) * gold_rate * qty, 2)
                        gold_val += val
                    else:
                        val = round(h["gross_weight_grams"] * (h["purity"] / benchmark_purity) * silver_rate * qty, 2)
                        silver_val += val
                    total_val += val

                history.append({
                    "date": obs_date,
                    "observed_at": row.get("observed_at"),
                    "gold_rate_inr": gold_rate,
                    "silver_rate_inr": silver_rate,
                    "total_valuation_inr": round(total_val, 2),
                    "gold_valuation_inr": round(gold_val, 2),
                    "silver_valuation_inr": round(silver_val, 2),
                })
            except (ValueError, KeyError):
                continue

        return history

    @staticmethod
    def get_portfolio_summary(user_id: str = "default_user") -> dict[str, Any]:
        holdings = PortfolioService.list_holdings(user_id=user_id)
        gold_rate, silver_rate = get_current_benchmark_rates()

        gold_gross = 0.0
        gold_fine = 0.0
        silver_gross = 0.0
        silver_fine = 0.0

        total_valuation = 0.0
        total_acq_cost = 0.0
        has_known_cost = False

        gold_valuation = 0.0
        silver_valuation = 0.0

        for h in holdings:
            qty = h["quantity"]
            val = h["current_valuation_inr"]
            total_valuation += val

            if h["metal_type"] == "GOLD":
                gold_gross += h["gross_weight_grams"] * qty
                gold_fine += h["fine_weight_grams"] * qty
                gold_valuation += val
            else:
                silver_gross += h["gross_weight_grams"] * qty
                silver_fine += h["fine_weight_grams"] * qty
                silver_valuation += val

            if h["acquisition_cost_inr"] is not None:
                total_acq_cost += h["acquisition_cost_inr"] * qty
                has_known_cost = True

        total_gain_loss = None
        total_gain_loss_pct = None
        if has_known_cost and total_acq_cost > 0:
            total_gain_loss = round(total_valuation - total_acq_cost, 2)
            total_gain_loss_pct = round((total_gain_loss / total_acq_cost) * 100, 2)

        gold_alloc_pct = round((gold_valuation / total_valuation) * 100, 2) if total_valuation > 0 else 0.0
        silver_alloc_pct = round((silver_valuation / total_valuation) * 100, 2) if total_valuation > 0 else 0.0

        return {
            "total_items": sum(h["quantity"] for h in holdings),
            "unique_holdings": len(holdings),
            "gold": {
                "gross_weight_grams": round(gold_gross, 2),
                "fine_weight_grams": round(gold_fine, 2),
                "fine_weight_kg": round(gold_fine / 1000.0, 4),
                "estimated_valuation_inr": round(gold_valuation, 2),
                "allocation_pct": gold_alloc_pct,
            },
            "silver": {
                "gross_weight_grams": round(silver_gross, 2),
                "fine_weight_grams": round(silver_fine, 2),
                "fine_weight_kg": round(silver_fine / 1000.0, 4),
                "estimated_valuation_inr": round(silver_valuation, 2),
                "allocation_pct": silver_alloc_pct,
            },
            "total_estimated_valuation_inr": round(total_valuation, 2),
            "total_recorded_acquisition_cost_inr": round(total_acq_cost, 2) if has_known_cost else None,
            "unrealized_gain_loss_inr": total_gain_loss,
            "unrealized_gain_loss_pct": total_gain_loss_pct,
            "benchmark_rates": {
                "gold_mjdta_inr_per_gram": gold_rate,
                "silver_mjdta_inr_per_gram": silver_rate,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "disclaimer": "Valuation is estimated using Madras Jewellers and Diamond Traders Association (MJDTA) benchmark rates. Physical bullion buyback rates typically trade at a local dealer spread.",
            },
        }
