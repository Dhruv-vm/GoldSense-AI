from __future__ import annotations

import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml
import pytest
import requests

import scripts.collect_kjpl_csv as kjpl_mod
from scripts.collect_kjpl_csv import (
    parse_rate,
    validate_rates,
    check_event_status,
    append_rate_to_csv,
    collect,
)

IST = ZoneInfo("Asia/Kolkata")


def test_parse_rate():
    assert parse_rate("14,285.0") == 14285.0
    assert parse_rate(" 13765 ") == 13765.0
    assert parse_rate("245.50") == 245.50
    assert parse_rate(None) is None
    assert parse_rate("") is None
    assert parse_rate("N/A") is None
    assert parse_rate("-100") is None  # negative rejected


def test_validate_rates():
    # Valid rates
    ok, reason = validate_rates(13765.0, 245.0, "Time : 09:31 am")
    assert ok is True
    assert reason == "Valid"

    # Missing gold
    ok, reason = validate_rates(None, 245.0, "Time : 09:31 am")
    assert ok is False
    assert "missing" in reason.lower()

    # Out of bounds gold
    ok, reason = validate_rates(100.0, 245.0, "Time : 09:31 am")
    assert ok is False
    assert "bounds" in reason.lower()

    ok, reason = validate_rates(100000.0, 245.0, "Time : 09:31 am")
    assert ok is False
    assert "bounds" in reason.lower()

    # Out of bounds silver
    ok, reason = validate_rates(13765.0, 10.0, "Time : 09:31 am")
    assert ok is False
    assert "silver" in reason.lower()

    # Missing / malformed published_time
    ok, reason = validate_rates(13765.0, 245.0, None)
    assert ok is False
    assert "missing" in reason.lower()

    ok, reason = validate_rates(13765.0, 245.0, "Market Open")
    assert ok is False
    assert "clock time format" in reason.lower()


def test_check_event_status_non_existent(tmp_path: Path):
    csv_file = tmp_path / "test_rates.csv"
    now = datetime(2026, 10, 14, 11, 0, tzinfo=IST)
    is_dup, reason = check_event_status("Time : 09:30 am", 13700.0, 245.0, now, csv_path=csv_file)
    assert is_dup is False
    assert "not exist" in reason


def test_check_event_status_duplicate_suppression(tmp_path: Path):
    csv_file = tmp_path / "test_rates.csv"
    now_1030 = datetime(2026, 10, 14, 10, 30, tzinfo=IST)
    now_1100 = datetime(2026, 10, 14, 11, 0, tzinfo=IST)

    # First run appends rate
    append_rate_to_csv(now_1030, "Time : 09:30 am", 13700.0, 245.0, csv_path=csv_file)
    assert csv_file.exists()

    # Second run at 11:00 AM with identical rate and published time
    is_dup, reason = check_event_status("Time : 09:30 am", 13700.0, 245.0, now_1100, csv_path=csv_file)
    assert is_dup is True
    assert "Identical to latest recorded event" in reason


def test_check_event_status_new_event_same_day(tmp_path: Path):
    csv_file = tmp_path / "test_rates.csv"
    now_morning = datetime(2026, 10, 14, 11, 0, tzinfo=IST)
    now_evening = datetime(2026, 10, 14, 18, 0, tzinfo=IST)

    # Morning rate
    append_rate_to_csv(now_morning, "Time : 09:30 am", 13700.0, 245.0, csv_path=csv_file)

    # Evening rate update
    is_dup, reason = check_event_status("Time : 04:30 pm", 13650.0, 245.0, now_evening, csv_path=csv_file)
    assert is_dup is False
    assert "New event detected" in reason


def test_check_event_status_new_day_not_blocked_by_ancient_history(tmp_path: Path):
    csv_file = tmp_path / "test_rates.csv"
    day_1 = datetime(2026, 9, 14, 11, 0, tzinfo=IST)
    day_2 = datetime(2026, 10, 14, 11, 0, tzinfo=IST)

    # An old rate from a month ago
    append_rate_to_csv(day_1, "Time : 09:30 am", 13700.0, 245.0, csv_path=csv_file)
    # A different rate in between
    append_rate_to_csv(day_1 + timedelta(days=5), "Time : 10:00 am", 13800.0, 250.0, csv_path=csv_file)

    # Today, KJPL publishes 13700 at 09:30 am
    is_dup, reason = check_event_status("Time : 09:30 am", 13700.0, 245.0, day_2, csv_path=csv_file)
    assert is_dup is False
    assert "New event detected" in reason


def test_kjpl_workflow_yaml_and_cron_conversions():
    workflow_path = Path(".github/workflows/kjpl-collector.yml")
    assert workflow_path.exists(), "Workflow file must exist"

    with workflow_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["name"] == "KJPL Rate Collector"
    on_block = data.get("on") if "on" in data else data.get(True)
    assert on_block is not None, "Workflow must have 'on' trigger block"
    assert "schedule" in on_block
    schedules = on_block["schedule"]
    crons = [s["cron"] for s in schedules]

    expected_crons = [
        "38 0 * * *",  # 06:08 AM IST (targets ~10:15 - 10:30 AM IST after ~4h queue backlog)
        "8 1 * * *",   # 06:38 AM IST (targets ~10:45 - 11:00 AM IST after ~4h queue backlog)
        "38 1 * * *",  # 07:08 AM IST (targets ~11:15 - 11:30 AM IST after ~4h queue backlog)
        "8 9 * * *",   # 02:38 PM IST (targets ~05:15 - 05:40 PM IST after ~3h queue backlog)
        "38 9 * * *",  # 03:08 PM IST (targets ~05:45 - 06:10 PM IST after ~3h queue backlog)
        "8 10 * * *",  # 03:38 PM IST (targets ~06:15 - 06:40 PM IST after ~3h queue backlog)
    ]

    assert crons == expected_crons, f"Crons must match required 6 schedules: {crons}"

    # Verify UTC to IST conversion for each cron
    for cron_expr in crons:
        minute_str, hour_str = cron_expr.split()[:2]
        utc_time = datetime(2026, 10, 14, int(hour_str), int(minute_str), tzinfo=timezone.utc)
        ist_time = utc_time.astimezone(IST)

        if cron_expr == "38 0 * * *":
            assert ist_time.strftime("%I:%M %p") == "06:08 AM"
        elif cron_expr == "8 1 * * *":
            assert ist_time.strftime("%I:%M %p") == "06:38 AM"
        elif cron_expr == "38 1 * * *":
            assert ist_time.strftime("%I:%M %p") == "07:08 AM"
        elif cron_expr == "8 9 * * *":
            assert ist_time.strftime("%I:%M %p") == "02:38 PM"
        elif cron_expr == "38 9 * * *":
            assert ist_time.strftime("%I:%M %p") == "03:08 PM"
        elif cron_expr == "8 10 * * *":
            assert ist_time.strftime("%I:%M %p") == "03:38 PM"


def test_collect_with_mocked_response(tmp_path: Path, monkeypatch):
    csv_file = tmp_path / "test_kjpl_rates.csv"
    mock_html = """
    <html>
      <body>
        <div class="mjdma_data">Time : 09:35 am</div>
        <div class="gold-rate">13,750.00</div>
        <div class="silver-rate">245.00</div>
      </body>
    </html>
    """

    class MockResponse:
        status_code = 200
        text = mock_html
        def raise_for_status(self):
            pass

    class MockSession:
        def get(self, *args, **kwargs):
            return MockResponse()

    # First collection: records new event
    res1 = collect(csv_path=csv_file, session=MockSession())
    assert res1 is True
    assert csv_file.exists()

    with csv_file.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["gold_mjdta"] == "13750.0"
        assert rows[0]["published_time"] == "Time : 09:35 am"

    # Second collection immediately after: duplicate detected, returns False
    res2 = collect(csv_path=csv_file, session=MockSession())
    assert res2 is False

    with csv_file.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 1  # No duplicate row added!
