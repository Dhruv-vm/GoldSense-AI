from app.services.market.collector import collect_usdinr_rate


def run_market_collection():
    record = collect_usdinr_rate()

    print(
        f"[MARKET] Saved ID={record.id} "
        f"{record.symbol}=₹{record.value:,.4f}"
    )
