from __future__ import annotations

import pytest
from app.services.portfolio_service import PortfolioService


def test_portfolio_update_and_history():
    user = "test_history_user"

    # 1. Create a holding
    item = PortfolioService.create_holding(
        {
            "metal_type": "GOLD",
            "product_name": "MMTC-PAMP Bar",
            "purity": 0.9999,
            "gross_weight": 20.0,
            "weight_unit": "g",
            "quantity": 2,
            "acquisition_cost_inr": 130000.0,
            "notes": "Original note",
        },
        user_id=user,
    )
    assert item is not None
    holding_id = item["id"]
    assert item["fine_weight_grams"] == round(20.0 * 0.9999, 4)

    # 2. Update holding (edit weight and notes)
    updated = PortfolioService.update_holding(
        holding_id,
        {
            "gross_weight": 50.0,
            "notes": "Updated vault location",
        },
        user_id=user,
    )
    assert updated is not None
    assert updated["gross_weight_grams"] == 50.0
    assert updated["fine_weight_grams"] == round(50.0 * 0.9999, 4)
    assert updated["notes"] == "Updated vault location"

    # 3. Test Historical Valuation
    history = PortfolioService.get_historical_valuation(user_id=user)
    assert isinstance(history, list)
    if history:
        assert "date" in history[0]
        assert "gold_rate_inr" in history[0]
        assert "total_valuation_inr" in history[0]
        assert history[0]["total_valuation_inr"] > 0

    # Clean up
    PortfolioService.delete_holding(holding_id, user_id=user)


def test_unknown_acquisition_cost_handling():
    user = "test_unknown_cost_user"

    # Create holding with missing acquisition cost
    item = PortfolioService.create_holding(
        {
            "metal_type": "GOLD",
            "product_name": "Inherited Coin",
            "purity": 0.916,
            "gross_weight": 8.0,
            "weight_unit": "g",
            "quantity": 1,
            "acquisition_cost_inr": None,
        },
        user_id=user,
    )
    assert item is not None
    assert item["acquisition_cost_inr"] is None
    assert item["unrealized_gain_loss_inr"] is None
    assert item["unrealized_gain_loss_pct"] is None

    # Summary should also handle None cost without crashing
    summary = PortfolioService.get_portfolio_summary(user_id=user)
    assert summary["total_estimated_valuation_inr"] > 0
    assert summary["total_recorded_acquisition_cost_inr"] is None
    assert summary["unrealized_gain_loss_inr"] is None

    # Clean up
    PortfolioService.delete_holding(item["id"], user_id=user)
