from __future__ import annotations

import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.sentiment.archive_audit import audit_news_archive


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    summary = audit_news_archive(
        raw_archive_path=repo_root / "data/news/news_articles.csv",
        live_csv_path=repo_root / "data/news/live_news.csv",
        output_audited_path=repo_root / "data/news/news_archive_audited.csv",
        report_md_path=repo_root / "docs/data/NEWS_ARCHIVE_AUDIT.md",
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "synthetic_fixture_rows"}, indent=2))
    print(f"Synthetic fixture rows flagged: {len(summary['synthetic_fixture_rows'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
