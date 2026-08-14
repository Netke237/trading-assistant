# backend/tests/test_update_sp500_liquidity_script.py
"""Tests for the manual update_sp500_liquidity.py script's --dry-run/--force
flags, pre-write backup, and zero-liquidity sanity threshold (#27). The
script is not a package (backend/scripts/ has no __init__.py), so it's
loaded via importlib rather than a normal import.
"""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "update_sp500_liquidity.py"
_spec = importlib.util.spec_from_file_location("update_sp500_liquidity", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "sector", "liquidity"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _read_csv(path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


ROWS = [
    {"symbol": "AAPL", "sector": "Technology", "liquidity": "500.0"},
    {"symbol": "MSFT", "sector": "Technology", "liquidity": "480.0"},
    {"symbol": "KO",   "sector": "Consumer Staples", "liquidity": "120.0"},
    {"symbol": "JPM",  "sector": "Financials", "liquidity": "300.0"},
]


@pytest.fixture()
def csv_path(tmp_path):
    path = tmp_path / "sp500.csv"
    _write_csv(path, ROWS)
    return path


def test_dry_run_does_not_write(csv_path, tmp_path):
    backup_path = tmp_path / "sp500.csv.bak"
    good_liquidity = {"AAPL": 510.0, "MSFT": 490.0, "KO": 130.0, "JPM": 305.0}
    with patch.multiple(
        _mod, CSV_PATH=csv_path, BACKUP_PATH=backup_path,
        fetch_liquidity=lambda symbols: good_liquidity,
        fetch_sectors_for_unknowns=lambda symbols: {},
    ):
        rc = _mod.main(["--dry-run"])
    assert rc == 0
    assert _read_csv(csv_path) == ROWS  # untouched
    assert not backup_path.exists()


def test_sanity_threshold_aborts_without_force(csv_path, tmp_path):
    backup_path = tmp_path / "sp500.csv.bak"
    bad_liquidity = {"AAPL": 0.0, "MSFT": 0.0, "KO": 0.0, "JPM": 300.0}
    with patch.multiple(
        _mod, CSV_PATH=csv_path, BACKUP_PATH=backup_path,
        fetch_liquidity=lambda symbols: bad_liquidity,
        fetch_sectors_for_unknowns=lambda symbols: {},
    ):
        rc = _mod.main([])
    assert rc == 1  # non-zero exit
    assert _read_csv(csv_path) == ROWS  # untouched
    assert not backup_path.exists()


def test_sanity_threshold_overridden_by_force(csv_path, tmp_path):
    backup_path = tmp_path / "sp500.csv.bak"
    bad_liquidity = {"AAPL": 0.0, "MSFT": 0.0, "KO": 0.0, "JPM": 300.0}
    with patch.multiple(
        _mod, CSV_PATH=csv_path, BACKUP_PATH=backup_path,
        fetch_liquidity=lambda symbols: bad_liquidity,
        fetch_sectors_for_unknowns=lambda symbols: {},
    ):
        rc = _mod.main(["--force"])
    assert rc == 0
    updated = _read_csv(csv_path)
    assert {r["symbol"]: float(r["liquidity"]) for r in updated} == bad_liquidity
    assert backup_path.exists()
    assert _read_csv(backup_path) == ROWS


def test_healthy_fetch_writes_and_backs_up(csv_path, tmp_path):
    backup_path = tmp_path / "sp500.csv.bak"
    good_liquidity = {"AAPL": 510.0, "MSFT": 490.0, "KO": 0.0, "JPM": 305.0}
    with patch.multiple(
        _mod, CSV_PATH=csv_path, BACKUP_PATH=backup_path,
        fetch_liquidity=lambda symbols: good_liquidity,
        fetch_sectors_for_unknowns=lambda symbols: {},
    ):
        rc = _mod.main([])
    assert rc == 0
    updated = _read_csv(csv_path)
    assert {r["symbol"]: float(r["liquidity"]) for r in updated} == good_liquidity
    assert backup_path.exists()
    assert _read_csv(backup_path) == ROWS
