from __future__ import annotations

import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.prediction.mjdta_series import load_and_audit_mjdta_series


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    _, summary = load_and_audit_mjdta_series(
        kjpl_csv_path=repo_root / "data/kjpl/kjpl_rates.csv",
        audited_csv_output=repo_root / "data/kjpl/mjdta_gold_24k_audited.csv",
        report_md_path=repo_root / "docs/ml/MJDTA_TARGET_AUDIT.md",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
