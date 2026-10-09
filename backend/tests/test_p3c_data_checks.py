"""scripts/p3c_data_checks.py -- the P3c read-only data checks (plan §5, §6, Verification).

The script lives under scripts/ and is run directly, so it is loaded by path
(like tests/test_iv_basis_analysis.py). The DB-URL routing cases run it in a
SUBPROCESS: in-process, app.database is already imported under the test
sqlite URL (and pytest's sys.path hides a missing path insert), so neither
the import-time engine crash nor a cwd dependency could ever show.
"""
from __future__ import annotations

import importlib.util
import math
import os
import socket
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
_PATH = BACKEND / "scripts" / "p3c_data_checks.py"

# Explicit params so the pins do not depend on strategy_params.yaml.
_PARAMS = {"ema_period": 50, "trend_ema": 100, "tolerance": 0.08, "ma_type": "EMA",
           "require_reversal": False, "atr_stop_mult": 1.5, "rr_target_mult": 2.0,
           "exit_swing_lookback": 20}


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("p3c_data_checks_under_test", _PATH)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


# ── fixtures ─────────────────────────────────────────────────────────────────

def _volume(i: int) -> int:
    # Three quiet bars in every ten: the bar after them passes the signal's
    # volume-contraction gate (3-bar avg < 90% of the 20-bar avg).
    return 500 if i % 10 in (7, 8, 9) else 1000


def _downtrend(n: int, pre_split_mult: float = 1.0) -> list[dict]:
    """Linear bearish trend that sits inside the pullback_ema bounce band.

    pre_split_mult > 1 builds MIXED-shaped bars: high/low at that multiple of
    the (adjusted) close, as _read_bars returns pre-split rows.
    """
    out = []
    d0 = date(2020, 1, 1)
    for i in range(n):
        c = 100 - 0.1 * i
        out.append({"time": (d0 + timedelta(days=i)).isoformat(), "open": c,
                    "high": c * pre_split_mult + 0.5, "low": c * pre_split_mult - 0.5,
                    "close": c, "volume": _volume(i)})
    return out


def _weekdays_back(n: int) -> list[date]:
    out, d = [], date.today() - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _db_rows(sym: str, kind: str, n: int = 300, split_at: int = 200, ratio: float = 3.0):
    rows = []
    for k, d in enumerate(_weekdays_back(n)):
        base = 100 + 5 * math.sin(k / 15)
        pre = kind in ("mixed", "stale") and k < split_at
        close = base * ratio if pre else base
        if kind == "mixed":
            adj = 1 / ratio if pre else 1.0      # Alpaca-shaped: correct adj_factor, raw OHLC
        elif kind == "stale":
            adj = None if k == 10 else 1.0       # never re-adjusted; one legacy NULL
        else:
            adj = 1.0
        rows.append((sym, d.isoformat(), close, close * 1.01, close * 0.99, close,
                     1000 + k, adj, 1.0, "alpaca"))
    return rows


def _make_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE ohlcv_daily (symbol VARCHAR(10) NOT NULL, date DATE NOT NULL, "
                "open NUMERIC NOT NULL, high NUMERIC NOT NULL, low NUMERIC NOT NULL, "
                "close NUMERIC NOT NULL, volume BIGINT NOT NULL, adj_factor NUMERIC, "
                "split_factor NUMERIC, div_cash NUMERIC, source VARCHAR(20), "
                "fetched_at DATETIME, PRIMARY KEY (symbol, date))")
    rows = (_db_rows("AAA", "mixed") + _db_rows("BBB", "stale") + _db_rows("CCC", "clean")
            + _db_rows("DDD", "clean", n=5))
    con.executemany("INSERT INTO ohlcv_daily (symbol, date, open, high, low, close, volume, "
                    "adj_factor, split_factor, source) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


@pytest.fixture
def fixture_db(tmp_path):
    return _make_db(tmp_path / "p3c.db")


# ── §5 target pins ───────────────────────────────────────────────────────────

def test_patched_run_equals_unpatched_signal_when_every_rung_is_positive(mod):
    from app.services.strategy_engine import pullback_ema_signal

    bars = _downtrend(420)
    recs = mod.measure_targets(bars, _PARAMS)
    expected = {}
    for i in range(len(bars)):
        sl = bars[max(0, i + 1 - 350): i + 1]
        if len(sl) < 60:
            continue
        sig = pullback_ema_signal(sl, direction="Bearish", **_PARAMS)
        if sig is not None:
            expected[i] = sig
    assert expected, "fixture must produce setup bars"
    assert {r["index"] for r in recs} == set(expected)
    for r in recs:
        assert r["target"] == expected[r["index"]].target_price
        assert r["stop_price"] == expected[r["index"]].stop_price
        assert r["real"]
    assert any(r["index"] >= 350 for r in recs)


def test_mixed_bars_empty_ladder_recorded_with_negative_fallback(mod):
    from app.services.strategy_engine import pullback_ema_signal

    bars = _downtrend(200, pre_split_mult=3.0)
    recs = mod.measure_targets(bars, _PARAMS)
    assert recs, "fixture must produce setup bars under the patch"
    for r in recs:
        sl = bars[max(0, r["index"] + 1 - 350): r["index"] + 1]
        assert pullback_ema_signal(sl, direction="Bearish", **_PARAMS) is None
        assert r["real"] == []
        assert r["primary_status"] == "not below entry"
        assert r["fallback"] < 0
        line = mod.describe_bar(r)
        assert "NONE — no valid rung" in line
        assert "not below entry" in line
        assert "backtesting.py would have raised" in line


def test_zero_fallback_prints_no_take_profit_and_no_minus_zero(mod):
    rec = {"date": "2024-01-02", "stop_price": 10.0, "primary": 12.0, "ext1": -1.0,
           "ext2": -2.0, "real": [], "target": None, "fallback": -0.0,
           "primary_status": "not below entry"}
    line = mod.describe_bar(rec)
    assert "fallback 0.00 <= 0" in line and "-0.00" not in line
    assert "NO take-profit, no raise" in line


# ── §5 verdicts, read-only, no network ───────────────────────────────────────

def test_verdicts_on_fixture_db_read_only_and_offline(mod, fixture_db, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{fixture_db}")
    before = (fixture_db.read_bytes(), os.stat(fixture_db).st_mtime_ns)

    def _no_socket(*a, **k):
        raise AssertionError("p3c_data_checks opened a socket on --sections db")

    monkeypatch.setattr(socket, "socket", _no_socket)
    rc = mod.main(["--sections", "db", "--allow-sqlite",
                   "--symbols", "AAA", "BBB", "CCC", "DDD", "EEE"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.splitlines()[0] == f"reading SQLite file {fixture_db}"
    assert "AAA: MIXED ADJUSTMENT" in out
    assert "BBB: STALE ADJ_FACTOR" in out
    assert "CCC: NO SPLIT IN WINDOW" in out
    assert "DDD: TOO FEW ROWS (5)" in out
    assert "TOO FEW ROWS (5) in ohlcv_daily for DDD over" in out
    assert "EEE: NO ROWS" in out
    assert "NO ROWS in ohlcv_daily for EEE over" in out
    assert "the split hypothesis does not explain CCC's negative target" in out
    assert "(1 NULL, read as 1.0)" in out
    assert (fixture_db.read_bytes(), os.stat(fixture_db).st_mtime_ns) == before


@pytest.mark.parametrize("key", ["ema_period", "direction", "atr_stop_mult"])
def test_params_json_refuses_keys_outside_the_five(mod, key, capsys):
    with pytest.raises(SystemExit) as e:
        mod.main(["--sections", "db", "--params-json", f'{{"{key}": 1}}'])
    assert e.value.code != 0
    err = capsys.readouterr().err
    assert key in err and "pullback_ema_period" in err


def test_params_json_validation_error_exits(mod, fixture_db, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{fixture_db}")
    with pytest.raises(SystemExit) as e:
        mod.main(["--sections", "db", "--allow-sqlite",
                  "--params-json", '{"pullback_ema_period": 0}'])
    assert e.value.code != 0
    assert "pullback_ema_period" in capsys.readouterr().err


def test_params_json_overlays_request_defaults(mod, monkeypatch):
    merged, layers = mod.build_params({"pullback_trend_ema": 120})
    assert merged["trend_ema"] == 120 and layers["trend_ema"] == "request"
    # STOCKS-HORIZON-T1 H4: request strategy fields default to None, so a
    # field the overlay omits takes the YAML profile (bearish baseline 35),
    # not the old schema default 50.
    assert merged["ema_period"] == 35 and layers["ema_period"] == "active"


# ── read-only contract on the Postgres path ──────────────────────────────────

class _Rec:
    def __init__(self):
        self.log: list[str] = []


class _FakeResult:
    def fetchall(self):
        return []


class _FakeConn:
    __slots__ = ("_rec",)

    def __init__(self, rec):
        self._rec = rec

    async def execute(self, stmt, params=None):
        self._rec.log.append(" ".join(str(stmt).split()[:4]))
        return _FakeResult()

    async def close(self):
        self._rec.log.append("close")


class _FakeEngine:
    __slots__ = ("_rec",)

    def __init__(self, rec):
        self._rec = rec

    async def connect(self):
        self._rec.log.append("connect")
        return _FakeConn(self._rec)


def test_postgres_path_one_read_only_transaction_never_committed(mod, monkeypatch, capsys):
    rec = _Rec()
    engines = []

    def _fake_create(url, **kw):
        engines.append(url)
        return _FakeEngine(rec)

    monkeypatch.setattr(mod, "create_async_engine", _fake_create)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:s3cret@db.example/prod")
    rc = mod.main(["--sections", "db", "--symbols", "WMT", "LYB"])
    out = capsys.readouterr().out
    assert rc == 0
    assert len(engines) == 1
    assert engines[0].drivername == "postgresql+asyncpg"
    assert rec.log == ["connect", "SET TRANSACTION READ ONLY",
                       "SELECT date, open, high,", "SELECT date, open, high,", "close"]
    assert out.splitlines()[0] == "reading postgresql+asyncpg://u:***@db.example/prod"
    assert "s3cret" not in out
    assert "NO ROWS in ohlcv_daily for WMT" in out
    assert "NO ROWS in ohlcv_daily for LYB" in out


# ── DB-URL routing, in a subprocess, from two cwds ───────────────────────────

_CWDS = [BACKEND, BACKEND.parent]


def _run(cwd: Path, url: str | None, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if url is not None:
        env["DATABASE_URL"] = url
    return subprocess.run([sys.executable, str(_PATH), *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("cwd", _CWDS)
def test_help_from_any_cwd(cwd):
    p = _run(cwd, None, "--help")
    assert p.returncode == 0 and "--allow-sqlite" in p.stdout


@pytest.mark.parametrize("cwd", _CWDS)
def test_unsupported_scheme_exits_naming_it(cwd):
    p = _run(cwd, "mysql://u@h/db", "--sections", "db")
    assert p.returncode != 0
    assert "'mysql'" in p.stderr and "Traceback" not in p.stderr


@pytest.mark.parametrize("cwd", _CWDS)
@pytest.mark.parametrize("scheme", ["postgresql+asyncpg", "postgresql", "postgres"])
def test_postgres_schemes_route_to_asyncpg_before_app_import(cwd, scheme):
    p = _run(cwd, f"{scheme}://u:s3cret@127.0.0.1:1/db", "--sections", "db")
    assert p.returncode != 0
    assert "cannot connect to postgresql+asyncpg://" in p.stderr
    assert "***" in p.stderr
    assert "ConnectionRefusedError" in p.stderr or "Connect call failed" in p.stderr
    for bad in ("s3cret", "Traceback", "ModuleNotFoundError", "NoSuchModuleError"):
        assert bad not in p.stderr and bad not in p.stdout
    assert p.stdout.splitlines()[0] == "reading postgresql+asyncpg://u:***@127.0.0.1:1/db"


@pytest.mark.parametrize("cwd", _CWDS)
def test_sqlite_missing_file_exits_naming_resolved_path(cwd, tmp_path):
    missing = tmp_path / "nope.db"
    p = _run(cwd, f"sqlite+aiosqlite:///{missing}", "--sections", "db", "--allow-sqlite")
    assert p.returncode != 0
    assert str(missing) in p.stderr and "Traceback" not in p.stderr


@pytest.mark.parametrize("cwd", _CWDS)
def test_sqlite_refused_without_allow_flag(cwd, fixture_db):
    before = os.stat(fixture_db).st_mtime_ns
    p = _run(cwd, f"sqlite+aiosqlite:///{fixture_db}", "--sections", "db")
    assert p.returncode != 0
    assert "resolves to SQLite" in p.stderr and "--allow-sqlite" in p.stderr
    assert "Traceback" not in p.stderr
    assert os.stat(fixture_db).st_mtime_ns == before


def test_relative_sqlite_url_resolves_against_backend_not_cwd(tmp_path):
    # Run from the repo root: ./dev.db must resolve to backend/dev.db.
    p = _run(BACKEND.parent, "sqlite+aiosqlite:///./p3c-does-not-exist.db", "--sections", "db")
    assert str(BACKEND / "p3c-does-not-exist.db") in p.stderr
