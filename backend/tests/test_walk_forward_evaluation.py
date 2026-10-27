from __future__ import annotations

from ml.training.walk_forward_evaluation import run_walk_forward_evaluation


def test_walk_forward_evaluation_execution():
    report = run_walk_forward_evaluation()
    assert isinstance(report, dict)
    assert "status" in report
    assert "dataset_metadata" in report
    assert "baseline_benchmarks" in report

    meta = report["dataset_metadata"]
    assert meta["target_variable"] == "next_event_gold"
    assert meta["zero_lookahead_verified"] is True
    assert meta["usable_complete_rows"] <= meta["total_events_in_dataset"]

    # Verify baseline metrics are calculated
    baselines = report["baseline_benchmarks"]
    assert "naive_persistence" in baselines
    assert baselines["naive_persistence"]["mae_inr_per_g"] > 0
    assert baselines["naive_persistence"]["rmse_inr_per_g"] > 0

    assert "sma_3_event" in baselines
    assert baselines["sma_3_event"]["mae_inr_per_g"] > 0
