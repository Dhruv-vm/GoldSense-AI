from .client import KJPLClient


def main():
    client = KJPLClient()

    rates = client.fetch_rates()

    print("\n========== KJPL ==========")
    print(f"MJDTA Gold   : ₹{rates.gold_mjdta:,.2f}/g")
    print(f"MJDTA Silver : ₹{rates.silver_mjdta:,.2f}/g")
    gst_display = (
    f"₹{rates.gold_with_gst:,.2f}/g"
    if rates.gold_with_gst is not None
    else "Not found"    
    )

    print(f"Gold + GST   : {gst_display}")
    print(f"Updated      : {rates.source_updated_time}")
    print(f"Observed     : {rates.observed_at.isoformat()}")
    print(f"Source       : {rates.source}")
    print(f"Currency     : {rates.currency}")
    print(f"Unit         : {rates.unit}")
    print("===========================\n")


if __name__ == "__main__":
    main()