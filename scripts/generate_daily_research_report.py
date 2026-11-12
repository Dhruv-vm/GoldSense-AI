from __future__ import annotations

import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.prediction.daily_report import generate_daily_research_report


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    report = generate_daily_research_report(
        repo_root=repo_root,
        md_output_path=repo_root / "docs/operations/DAILY_RESEARCH_REPORT.md",
        json_output_path=repo_root / "docs/operations/daily_research_report.json",
    )
    print(
        json.dumps(
            {
                "generated_at": report["generated_at"],
                "status": report["status"],
                "eligible_publications": report["eligible_publications"],
                "verified_news_coverage_origins": report["verified_news_coverage_origins"],
                "latest_forecasts_count": len(report["latest_forecasts"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
