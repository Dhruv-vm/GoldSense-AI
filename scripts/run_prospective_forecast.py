from __future__ import annotations

import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.db.session as db_session
from app.services.prediction.daily_report import generate_daily_research_report
from app.services.prediction.forecast_engine import generate_prospective_forecast_for_frontier


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    db = db_session.SessionLocal()
    try:
        prospective_res = generate_prospective_forecast_for_frontier(db)
        report = generate_daily_research_report(
            repo_root=repo_root,
            db=db,
            md_output_path=repo_root / "docs/operations/DAILY_RESEARCH_REPORT.md",
            json_output_path=repo_root / "docs/operations/daily_research_report.json",
        )
    finally:
        db.close()

    print(
        json.dumps(
            {
                "prospective_status": prospective_res.get("status"),
                "origin_observed_at": prospective_res.get("origin_observed_at"),
                "persisted": prospective_res.get("persisted"),
                "matured_evaluations_inserted": prospective_res.get("matured_evaluations_inserted"),
                "daily_report_status": report.get("status"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
