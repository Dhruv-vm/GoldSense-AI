from app.services.kjpl.collector import collect_kjpl_rate


def run_kjpl_collection():
    record = collect_kjpl_rate()

    print(
        f"[KJPL] Saved ID={record.id} "
        f"Gold=₹{record.gold_mjdta:,.2f}/g"
    )
