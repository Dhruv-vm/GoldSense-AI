from __future__ import annotations

import pytest
from app.services.portfolio_service import PortfolioService


def test_portfolio_create_and_valuation():
    # 1. Create a 24K gold bar (100g)
    h_gold = PortfolioService.create_holding({
        "metal_type": "GOLD",
        "product_name": "MMTC-PAMP 24K Bar",
        "purity": 0.999,
        "gross_weight": 100.0,
        "weight_unit": "g",
        "quantity": 1,
        "acquisition_date": "2026-06-01",
        "acquisition_cost_inr": 1250000.0,
    }, user_id="test_user_1")

    assert h_gold["id"] is not None
    assert h_gold["metal_type"] == "GOLD"
    assert h_gold["gross_weight_grams"] == 100.0
    assert h_gold["fine_weight_grams"] == 99.9
    assert h_gold["current_valuation_inr"] > 1000000.0
    assert h_gold["unrealized_gain_loss_inr"] is not None

    # 2. Create a 1kg silver bar (1kg)
    h_silver = PortfolioService.create_holding({
        "metal_type": "SILVER",
        "product_name": "999 Silver Cast Bar",
        "purity": 0.999,
        "gross_weight": 1.0,
        "weight_unit": "kg",
        "quantity": 2,
        "acquisition_cost_inr": 200000.0,
    }, user_id="test_user_1")

    assert h_silver["gross_weight_grams"] == 1000.0
    assert h_silver["fine_weight_grams"] == 999.0
    assert h_silver["quantity"] == 2

    # 3. Summary metrics
    summary = PortfolioService.get_portfolio_summary(user_id="test_user_1")
    assert summary["total_items"] == 3
    assert summary["unique_holdings"] == 2
    assert summary["gold"]["gross_weight_grams"] == 100.0
    assert summary["silver"]["gross_weight_grams"] == 2000.0
    assert summary["total_estimated_valuation_inr"] > 0
    assert summary["gold"]["allocation_pct"] + summary["silver"]["allocation_pct"] == pytest.approx(100.0, rel=1e-2)

    # 4. User isolation: test_user_2 must see empty portfolio
    summary_user2 = PortfolioService.get_portfolio_summary(user_id="test_user_2")
    assert summary_user2["total_items"] == 0
    assert summary_user2["unique_holdings"] == 0
    assert summary_user2["total_estimated_valuation_inr"] == 0.0

    # Clean up
    PortfolioService.delete_holding(h_gold["id"], user_id="test_user_1")
    PortfolioService.delete_holding(h_silver["id"], user_id="test_user_1")
    summary_clean = PortfolioService.get_portfolio_summary(user_id="test_user_1")
    assert summary_clean["total_items"] == 0


def test_reconciled_purity_valuation_and_millesimal_input():
    user = "test_purity_math_user"
    from app.services.portfolio_service import get_current_benchmark_rates
    gold_rate, _ = get_current_benchmark_rates()

    # Case A: 10g bar of standard 999 gold (purity passed as 0.999)
    # Valuation must equal exactly gross_weight * gold_rate
    h_999 = PortfolioService.create_holding({
        "metal_type": "GOLD",
        "product_name": "Standard 999 Bar",
        "purity": 0.999,
        "gross_weight": 10.0,
        "quantity": 1,
    }, user_id=user)
    assert h_999["current_valuation_inr"] == pytest.approx(10.0 * gold_rate, rel=1e-4)

    # Case B: Millesimal purity input (passed as 916.0 instead of 0.916)
    # Should auto-normalize to 0.916 without failing validation
    h_22k = PortfolioService.create_holding({
        "metal_type": "GOLD",
        "product_name": "22K Bangle",
        "purity": 916.0,
        "gross_weight": 10.0,
        "quantity": 1,
    }, user_id=user)
    assert h_22k["purity"] == 0.916
    expected_22k_val = round(10.0 * (0.916 / 0.999) * gold_rate, 2)
    assert h_22k["current_valuation_inr"] == pytest.approx(expected_22k_val, rel=1e-4)

    # Case C: 999.9 Minted Bar (passed as 0.9999)
    # Should evaluate with 0.9999 / 0.999 premium over standard 999
    h_9999 = PortfolioService.create_holding({
        "metal_type": "GOLD",
        "product_name": "999.9 Minted Bar",
        "purity": 0.9999,
        "gross_weight": 10.0,
        "quantity": 1,
    }, user_id=user)
    expected_9999_val = round(10.0 * (0.9999 / 0.999) * gold_rate, 2)
    assert h_9999["current_valuation_inr"] == pytest.approx(expected_9999_val, rel=1e-4)
    assert h_9999["current_valuation_inr"] > h_999["current_valuation_inr"]

    # Clean up
    PortfolioService.delete_holding(h_999["id"], user_id=user)
    PortfolioService.delete_holding(h_22k["id"], user_id=user)
    PortfolioService.delete_holding(h_9999["id"], user_id=user)
