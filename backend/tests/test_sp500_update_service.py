# backend/tests/test_sp500_update_service.py
"""Tests for the safety nets added to sp500_update_service._run() (#27):
pre-write backup + a sanity threshold that refuses to overwrite sp500.csv
with a mostly-empty ("bad") fetch. This is the actual unattended nightly
cron path (sp500_scheduler.py -> start_update_task() -> _run()), so these
are the tests that matter most for this fix per PLAN_TIER3_CLEANUP.md #7.
"""
from __future__ import annotations

import csv
from unittest.mock import patch

import pytest

from app.services import sp500_update_service as svc


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "sector", "liquidity"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _read_csv(path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


@pytest.fixture(autouse=True)
def _reset_state():
    with svc._lock:
        svc._state.update({
            "status": "idle", "last_updated": None, "symbols_updated": 0,
            "error": None, "in_progress": False,
        })
    yield


def test_run_aborts_write_when_liquidity_data_is_mostly_empty(tmp_path):
    """Simulates a 'yfinance returns mostly-empty data' night: the CSV must
    NOT be overwritten, and the failure must be loudly observable via
    get_update_state() since nobody watches this path run in real time."""
    csv_path = tmp_path / "sp500.csv"
    original_rows = [
        {"symbol": "AAPL", "sector": "Technology", "liquidity": "500.0"},
        {"symbol": "MSFT", "sector": "Technology", "liquidity": "480.0"},
        {"symbol": "KO",   "sector": "Consumer Staples", "liquidity": "120.0"},
        {"symbol": "JPM",  "sector": "Financials", "liquidity": "300.0"},
    ]
    _write_csv(csv_path, original_rows)

    # 3 of 4 symbols come back zero — well over the abort threshold.
    bad_liquidity = {"AAPL": 0.0, "MSFT": 0.0, "KO": 0.0, "JPM": 300.0}

    with patch.object(svc, "_CSV_PATH", csv_path), \
         patch.object(svc, "_BACKUP_PATH", tmp_path / "sp500.csv.bak"), \
         patch.object(svc, "_fetch_liquidity", return_value=bad_liquidity):
        svc._run()

    # CSV must be byte-for-byte untouched.
    assert _read_csv(csv_path) == original_rows
    # No backup should have been made — nothing was written.
    assert not (tmp_path / "sp500.csv.bak").exists()

    state = svc.get_update_state()
    assert state["status"] == "failed"
    assert state["error"] is not None
    assert "liquidity=0" in state["error"] or "0%" in state["error"] or "%" in state["error"]
    assert state["in_progress"] is False


def test_run_writes_and_backs_up_when_liquidity_data_looks_healthy(tmp_path):
    csv_path = tmp_path / "sp500.csv"
    backup_path = tmp_path / "sp500.csv.bak"
    original_rows = [
        {"symbol": "AAPL", "sector": "Technology", "liquidity": "500.0"},
        {"symbol": "MSFT", "sector": "Technology", "liquidity": "480.0"},
        {"symbol": "KO",   "sector": "Consumer Staples", "liquidity": "120.0"},
        {"symbol": "JPM",  "sector": "Financials", "liquidity": "300.0"},
    ]
    _write_csv(csv_path, original_rows)

    # Only 1 of 4 symbols zero — under the abort threshold, a normal fetch.
    good_liquidity = {"AAPL": 510.0, "MSFT": 490.0, "KO": 0.0, "JPM": 305.0}

    with patch.object(svc, "_CSV_PATH", csv_path), \
         patch.object(svc, "_BACKUP_PATH", backup_path), \
         patch.object(svc, "_fetch_liquidity", return_value=good_liquidity):
        svc._run()

    updated_rows = _read_csv(csv_path)
    assert {r["symbol"]: float(r["liquidity"]) for r in updated_rows} == good_liquidity

    # Pre-write backup was made of the ORIGINAL content before overwriting.
    assert backup_path.exists()
    assert _read_csv(backup_path) == original_rows

    state = svc.get_update_state()
    assert state["status"] == "done"
    assert state["error"] is None
    assert state["symbols_updated"] == 3  # AAPL, MSFT, JPM > 0


def test_run_records_failure_state_on_unexpected_exception(tmp_path):
    csv_path = tmp_path / "sp500.csv"
    _write_csv(csv_path, [{"symbol": "AAPL", "sector": "Technology", "liquidity": "500.0"}])

    with patch.object(svc, "_CSV_PATH", csv_path), \
         patch.object(svc, "_fetch_liquidity", side_effect=RuntimeError("yfinance down")):
        svc._run()

    state = svc.get_update_state()
    assert state["status"] == "failed"
    assert "yfinance down" in state["error"]
