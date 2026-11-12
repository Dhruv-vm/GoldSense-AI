from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.sentiment.human_review import (
    evaluate_human_review_csv,
    export_human_review_sample,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Human validation workflow for gold news classification.")
    parser.add_argument("--export", action="store_true", help="Export ~250 genuine English headlines for review.")
    parser.add_argument("--evaluate", action="store_true", help="Compute precision/recall/F1, kappa, and confusion matrix.")
    parser.add_argument("--sample-size", type=int, default=250)
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting ONLY when zero human labels exist.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    audited_csv = repo_root / "data/news/news_archive_audited.csv"
    review_csv = repo_root / "data/news/human_review_sample.csv"
    ref_csv = repo_root / "data/news/human_review_reference.csv"

    if not args.export and not args.evaluate:
        args.export = True
        args.evaluate = True

    output: dict = {}
    if args.export:
        output["export"] = export_human_review_sample(
            audited_csv_path=audited_csv,
            output_sample_path=review_csv,
            sample_size=args.sample_size,
            reference_output_path=ref_csv,
            overwrite=args.overwrite,
        )
    if args.evaluate:
        output["evaluation"] = evaluate_human_review_csv(
            review_csv_path=review_csv,
            reference_csv_path=ref_csv,
        )

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
