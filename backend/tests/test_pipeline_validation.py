from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
import pytest

from scripts.validate_pipeline_outputs import validate_pipeline_outputs

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_validate_current_pipeline_outputs():
    """Verify that current on-disk pipeline outputs pass all validation criteria."""
    is_valid, errors = validate_pipeline_outputs(PROJECT_ROOT)
    assert is_valid, f"Pipeline output validation failed with errors: {errors}"
    assert len(errors) == 0


def test_validate_detects_missing_directory(tmp_path: Path):
    """Verify that validator catches missing processed data directory."""
    empty_root = tmp_path / "mock_repo"
    empty_root.mkdir()
    is_valid, errors = validate_pipeline_outputs(empty_root)
    assert not is_valid
    assert any("not found" in err for err in errors)


def test_validate_detects_corrupt_evaluation_json(tmp_path: Path):
    """Verify that validator catches malformed evaluation report JSON."""
    processed_dir = tmp_path / "backend/ml/data/processed"
    processed_dir.mkdir(parents=True)

    # Write invalid JSON
    bad_json = processed_dir / "evaluation_report.json"
    bad_json.write_text("{ corrupt json ...", encoding="utf-8")

    is_valid, errors = validate_pipeline_outputs(tmp_path)
    assert not is_valid
    assert any("Failed to parse evaluation_report.json" in err for err in errors)
