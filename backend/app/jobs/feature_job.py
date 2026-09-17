from app.services.market.feature_collector import collect_feature_snapshot


def run_feature_snapshot():
    snapshot = collect_feature_snapshot()

    print(
        f"[FEATURES] Saved ID={snapshot.id} "
        f"KJPL=₹{snapshot.kjpl_gold:,.2f} "
        f"USDINR=₹{snapshot.usdinr:,.4f} "
        f"XAUUSD=${snapshot.xauusd:,.2f} "
        f"XAGUSD=${snapshot.xagusd:,.2f}"
    )