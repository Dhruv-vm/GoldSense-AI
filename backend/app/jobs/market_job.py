from app.services.market.collector import (
    collect_gold_usd_rate,
    collect_silver_usd_rate,
    collect_usdinr_rate,
)
def run_market_collection():
    usd_inr = collect_usdinr_rate()

    print(
        f"[MARKET] Saved ID={usd_inr.id} "
        f"{usd_inr.symbol}=₹{usd_inr.value:,.4f}"
    )

    gold_usd = collect_gold_usd_rate()

    print(
        f"[MARKET] Saved ID={gold_usd.id} "
        f"{gold_usd.symbol}=${gold_usd.value:,.2f}/oz"
    )

    silver_usd = collect_silver_usd_rate()

    print(
        f"[MARKET] Saved ID={silver_usd.id} "
        f"{silver_usd.symbol}=${silver_usd.value:,.2f}/oz"
    )