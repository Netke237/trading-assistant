"""Tests for scripts/check_contract_strikes.py (EXACT-STRIKE ES-4).

The script is a READ-ONLY report over every persisted contract id (plan
docs/superpowers/plans/2026-10-09-exact-strike-plan.md section 3, ES-4). These
tests seed a throwaway aiosqlite database in tmp_path with the app's own
models and assert (1) the per-row categories and summary counts, (2) that the
run issues no write of any kind, (3) the --chain AMBIGUOUS case against a
mocked chain fetch, and (4) the refusal to report on the default fallback
database or a SQLite file that does not exist (plan section 8, note a).

backend/scripts/ is not a package, so the script is loaded via importlib.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.engine import Engine

import app.models  # noqa: F401  (populates Base.metadata)
from app.database import Base
from app.models.audit_event import AuditEventModel
from app.models.closed_position import ClosedPositionModel
from app.models.daily_risk import DailyRiskAttempt
from app.models.portfolio import PortfolioPositionModel
from app.models.position_alert import PositionAlertHistoryModel
from app.models.scan_session import ScanSession, ScanSessionBase
from app.models.watched_contracts import WatchedContractModel

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "check_contract_strikes.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_contract_strikes", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: the script's dataclasses resolve their string
    # annotations through sys.modules[cls.__module__].
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture()
def script():
    return _load_script()


FUTURE = "2030-01-18"   # unexpired for the life of this test file
PAST = "2020-01-17"     # expired


def _position(rec_id: str, contract: str, symbol: str) -> dict:
    return dict(
        id=uuid.uuid4(), rec_id=rec_id, symbol=symbol, contract=contract,
        direction="Bullish", entry_price=1.0, qty=1, entry_date="2026-10-01",
        active_tp_method="ladder",
    )


def _closed(rec_id: str, contract: str, symbol: str) -> dict:
    return dict(
        id=uuid.uuid4().hex, rec_id=rec_id, symbol=symbol, contract=contract,
        direction="Bullish", entry_price=1.0, entry_date="2026-09-01",
        exit_price=2.0, exit_date="2026-09-10", qty_closed=1,
        realized_pnl_dollar=100.0, realized_pnl_pct=100.0, source="manual",
    )


SCAN_RESULT = {
    "scan_id": "s1",
    "timestamp": "2026-10-20T15:00:00Z",
    "candidates": [
        {
            "symbol": "AAPL",
            "contract": f"AAPL|185|{FUTURE}|C",
            "contractDetails": {"strike": 185, "expiry": FUTURE, "right": "C"},
            "alternatives": [
                {"symbol": "AAPL", "strike": 182.5, "expiry": FUTURE, "right": "C"},
                {"symbol": "AAPL", "strike": 190.0, "expiry": FUTURE, "right": "C"},
            ],
        },
        {
            "symbol": "KO",
            "contract": f"KO|60.0|{FUTURE}|C",
            "contractDetails": {"strike": 60, "expiry": FUTURE, "right": "C"},
            "alternatives": [],
        },
    ],
    "rejected": [],
}


@pytest.fixture()
def seeded_db(tmp_path) -> Path:
    """An aiosqlite-compatible file created with the app's models, seeded with
    every category the report distinguishes."""
    db_path = tmp_path / "live.db"
    eng = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(eng)
    ScanSessionBase.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(insert(PortfolioPositionModel.__table__), [
            _position("P1", f"AAPL|185|{FUTURE}|C", "AAPL"),     # canonical int
            _position("P2", f"AAPL|187.0|{FUTURE}|C", "AAPL"),   # NONCANONICAL
            _position("P3", f"XYZ|22.5|{FUTURE}|P", "XYZ"),      # canonical fractional
            _position("P4", "BA|STOCK", "BA"),                   # stock
            _position("P5", "AAPL 185C", "AAPL"),                # UNPARSEABLE
            _position("P6", f"OLD|50|{PAST}|C", "OLD"),          # expired int
        ])
        conn.execute(insert(ClosedPositionModel.__table__), [
            _closed("C1", f"MSFT|0187|{FUTURE}|C", "MSFT"),      # NONCANONICAL
            _closed("C2", f"MSFT|187.0001|{FUTURE}|C", "MSFT"),  # UNPARSEABLE (4 dp)
        ])
        conn.execute(insert(WatchedContractModel.__table__), [
            dict(id=uuid.uuid4(), contract_id=f"XYZ|22|{FUTURE}|P"),       # canonical int
            dict(id=uuid.uuid4(), contract_id="AAPL|185|2030-13-01|C"),   # bad date
        ])
        conn.execute(insert(AuditEventModel.__table__), [
            dict(id=uuid.uuid4(), event_type="approval", rec_id="P1",
                 recommendation_id="P1", payload={"strike": 185, "stockScore": 70}),
            dict(id=uuid.uuid4(), event_type="approval", rec_id="P2",
                 recommendation_id="P2", payload={"strike": 187.0}),       # NONCANONICAL
            dict(id=uuid.uuid4(), event_type="approval", rec_id="P3",
                 recommendation_id="P3", payload={"strike": 22}),          # MISMATCH vs 22.5
            dict(id=uuid.uuid4(), event_type="approval", rec_id="P4",
                 recommendation_id="P4", payload={"strike": None}),        # stock: skipped
            dict(id=uuid.uuid4(), event_type="rejection", rec_id="P5",
                 recommendation_id="P5", payload={"reason": "x", "strike": "junk"}),  # not an approval
        ])
        conn.execute(insert(ScanSession.__table__), [
            dict(id="current", status="complete", last_result_json=json.dumps(SCAN_RESULT)),
            dict(id="broken", status="complete", last_result_json="not json{"),
            dict(id="empty", status="idle", last_result_json=None),
        ])
        conn.execute(insert(PositionAlertHistoryModel.__table__), [
            dict(id=uuid.uuid4(), rec_id="P2", symbol="AAPL", alert_type="TP_HIT",
                 source="backend", contract=f"AAPL|187.0|{FUTURE}|C"),     # NONCANONICAL
            dict(id=uuid.uuid4(), rec_id="P4", symbol="BA", alert_type="TP_HIT",
                 source="backend", contract=None),                          # skipped
        ])
        conn.execute(insert(DailyRiskAttempt.__table__), [
            dict(id="a1", day="2026-10-01", reserved_cents=100, state="retained", outcome="",
                 instrument="AAPL  300118C00185000", source="manual", quantity=1,
                 price="1", multiplier=100),                                # OSI: fine
            dict(id="a2", day="2026-10-01", reserved_cents=100, state="retained", outcome="",
                 instrument="BA|STOCK", source="manual", quantity=1, price="1", multiplier=1),
            dict(id="a3", day="2026-10-01", reserved_cents=100, state="retained", outcome="",
                 instrument="legacy-auto", source="legacy-auto", quantity=0, price="0",
                 multiplier=100),                                           # UNPARSEABLE
        ])
    eng.dispose()
    return db_path


def _url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _summary(out: str) -> dict[str, int]:
    """Parse the `SUMMARY <CATEGORY> <n>` lines."""
    counts: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "SUMMARY":
            counts[parts[1]] = int(parts[2])
    return counts


def _lines(out: str, category: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith(category + " ")]


# ── Report content ──────────────────────────────────────────────────────────

def test_report_categories_and_counts(script, seeded_db, capsys):
    rc = script.main(["--database-url", _url(seeded_db)])
    out = capsys.readouterr().out
    assert rc == 0

    counts = _summary(out)
    assert counts["NONCANONICAL"] == 6
    assert counts["UNPARSEABLE"] == 5
    assert counts["MISMATCH"] == 1
    assert "AMBIGUOUS" not in counts  # only with --chain

    nonc = "\n".join(_lines(out, "NONCANONICAL"))
    assert f"portfolio_positions.contract rec_id=P2 'AAPL|187.0|{FUTURE}|C'" in nonc
    assert f"closed_positions.contract" in nonc and f"'MSFT|0187|{FUTURE}|C'" in nonc
    assert "audit_events.payload.strike rec_id=P2 187.0" in nonc
    assert f"scan_sessions.last_result_json id=current candidates[1].contract 'KO|60.0|{FUTURE}|C'" in nonc
    assert "scan_sessions.last_result_json id=current candidates[0].alternatives[1].strike 190.0" in nonc
    assert f"position_alert_history.contract rec_id=P2" in nonc

    unp = "\n".join(_lines(out, "UNPARSEABLE"))
    assert "portfolio_positions.contract rec_id=P5 'AAPL 185C'" in unp
    assert f"'MSFT|187.0001|{FUTURE}|C'" in unp
    assert "watched_contracts.contract_id" in unp and "'AAPL|185|2030-13-01|C'" in unp
    assert "scan_sessions.last_result_json id=broken" in unp
    assert "daily_risk_attempts.instrument id=a3 'legacy-auto'" in unp

    mism = "\n".join(_lines(out, "MISMATCH"))
    assert "audit_events.payload.strike rec_id=P3 22" in mism and "22.5" in mism

    # Canonical integer, fractional, stock and OSI values are not listed.
    listed = "\n".join(_lines(out, "NONCANONICAL") + _lines(out, "UNPARSEABLE") + _lines(out, "MISMATCH"))
    assert "rec_id=P1" not in listed
    assert "portfolio_positions.contract rec_id=P3" not in listed  # canonical 22.5
    assert "BA|STOCK" not in listed
    assert "300118C00185000" not in listed
    assert "182.5" not in listed

    # Per-table scan counts, the target and the localStorage footer.
    assert "TABLE portfolio_positions.contract rows=6" in out
    assert "TABLE position_alert_history.contract rows=1" in out
    assert "TABLE daily_risk_attempts.instrument rows=3" in out
    assert "sqlite+aiosqlite" in out and seeded_db.name in out
    assert "localStorage" in out and "bamendjou-auto-trade" in out
    assert "not scanned" in out.lower()
    assert "Chain check: off" in out


def test_resolves_database_url_like_the_app(script, seeded_db, capsys, monkeypatch, tmp_path):
    """No --database-url: DATABASE_URL (env / .env) is used, as the app does."""
    monkeypatch.setenv("DATABASE_URL", _url(seeded_db))
    monkeypatch.chdir(tmp_path)
    rc = script.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert _summary(out)["NONCANONICAL"] == 6
    assert "DATABASE_URL" in out


# ── Never writes ────────────────────────────────────────────────────────────

def test_run_issues_no_writes(script, seeded_db, capsys):
    before_bytes = seeded_db.read_bytes()
    before_mtime = seeded_db.stat().st_mtime_ns
    before_files = sorted(p.name for p in seeded_db.parent.iterdir())

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        rc = script.main(["--database-url", _url(seeded_db)])
    finally:
        event.remove(Engine, "before_cursor_execute", _record)
    capsys.readouterr()
    assert rc == 0

    assert statements, "the listener saw no statements at all"
    for stmt in statements:
        head = stmt.lstrip().split(None, 1)[0].upper()
        assert head in {"SELECT", "PRAGMA"}, stmt

    assert seeded_db.read_bytes() == before_bytes
    assert seeded_db.stat().st_mtime_ns == before_mtime
    assert sorted(p.name for p in seeded_db.parent.iterdir()) == before_files


def test_guard_refuses_write_statements(script):
    for stmt in ("INSERT INTO t VALUES (1)", "update t set x=1", " DELETE FROM t",
                 "CREATE TABLE t (x)", "DROP TABLE t", "COMMIT"):
        with pytest.raises(script.ReadOnlyViolation):
            script.assert_read_only_statement(stmt)
    for stmt in ("SELECT 1", "  select x from t", "PRAGMA table_info(t)", "SHOW server_version"):
        script.assert_read_only_statement(stmt)


# ── --chain: AMBIGUOUS ──────────────────────────────────────────────────────

def _row(symbol, strike, expiry, right):
    return {"id": f"{symbol}|{strike}|{expiry}|{right}", "symbol": symbol,
            "strike": strike, "expiry": expiry, "right": right}


def test_chain_reports_ambiguous_rows(script, seeded_db, capsys, monkeypatch):
    from app.data import market

    calls: list[tuple[str, str, str]] = []

    async def fake_chain(client, symbol, expiry=None, option_type="C", **kwargs):
        calls.append((symbol, expiry, option_type))
        if (symbol, option_type) == ("AAPL", "C"):
            return [_row("AAPL", s, expiry, "C") for s in (182.5, 185, 185.5, 187, 187.5, 190)]
        if (symbol, option_type) == ("XYZ", "P"):
            return [_row("XYZ", s, expiry, "P") for s in (22, 22.5, 23)]
        if symbol == "KO":
            # The real fetch falls back to ANOTHER expiry when E is not
            # listed; those rows must not be read as E's chain.
            return [_row("KO", 60.5, "2030-02-15", "C")]
        return []  # MSFT: no chain

    monkeypatch.setattr(market, "fetch_option_chain_async", fake_chain)

    rc = script.main(["--database-url", _url(seeded_db), "--chain"])
    out = capsys.readouterr().out
    assert rc == 0

    amb = "\n".join(_lines(out, "AMBIGUOUS"))
    assert f"portfolio_positions.contract rec_id=P1 'AAPL|185|{FUTURE}|C'" in amb
    assert f"portfolio_positions.contract rec_id=P2 'AAPL|187.0|{FUTURE}|C'" in amb
    assert f"watched_contracts.contract_id" in amb and f"'XYZ|22|{FUTURE}|P'" in amb
    assert f"scan_sessions.last_result_json id=current candidates[0].contract 'AAPL|185|{FUTURE}|C'" in amb
    assert f"position_alert_history.contract rec_id=P2" in amb
    assert "185.5" in amb and "187.5" in amb and "22.5" in amb
    # 190 has no fractional neighbour in (190, 191); 22.5 itself is fractional.
    assert "alternatives[1]" not in amb
    assert f"'XYZ|22.5|{FUTURE}|P'" not in amb
    counts = _summary(out)
    assert counts["AMBIGUOUS"] == 5
    assert counts["CHAIN_UNAVAILABLE"] == 2  # MSFT (empty) and KO (other expiry)

    # Expired ids, stocks and fractional ids never reach the chain; one fetch
    # per (symbol, expiry, right).
    assert sorted(calls) == sorted([
        ("AAPL", FUTURE, "C"), ("XYZ", FUTURE, "P"), ("MSFT", FUTURE, "C"), ("KO", FUTURE, "C"),
    ])
    assert "Chain check: on" in out


def test_no_chain_flag_never_fetches(script, seeded_db, capsys, monkeypatch):
    from app.data import market

    async def boom(*a, **k):
        raise AssertionError("chain must not be fetched without --chain")

    monkeypatch.setattr(market, "fetch_option_chain_async", boom)
    assert script.main(["--database-url", _url(seeded_db)]) == 0
    assert not _lines(capsys.readouterr().out, "AMBIGUOUS")


# ── Refusals (plan section 8, note a) ───────────────────────────────────────

def test_refuses_default_fallback_database(script, capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    rc = script.main([])
    captured = capsys.readouterr()
    assert rc != 0
    assert "default" in captured.err.lower()
    assert "--database-url" in captured.err
    assert not (tmp_path / "dev.db").exists()
    assert "SUMMARY" not in captured.out


def test_refuses_default_fallback_even_if_file_exists(script, seeded_db, capsys, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(seeded_db.parent)
    seeded_db.rename(seeded_db.parent / "dev.db")
    rc = script.main([])
    captured = capsys.readouterr()
    assert rc != 0
    assert "SUMMARY" not in captured.out


def test_explicit_default_url_is_allowed(script, seeded_db, capsys, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(seeded_db.parent)
    seeded_db.rename(seeded_db.parent / "dev.db")
    rc = script.main(["--database-url", "sqlite+aiosqlite:///./dev.db"])
    out = capsys.readouterr().out
    assert rc == 0
    assert _summary(out)["NONCANONICAL"] == 6


def test_refuses_missing_sqlite_file_and_never_creates_it(script, capsys, tmp_path):
    missing = tmp_path / "nope.db"
    rc = script.main(["--database-url", _url(missing)])
    captured = capsys.readouterr()
    assert rc != 0
    assert "does not exist" in captured.err
    assert not missing.exists()


def test_missing_sqlite_file_via_env_is_refused(script, capsys, monkeypatch, tmp_path):
    missing = tmp_path / "gone.db"
    monkeypatch.setenv("DATABASE_URL", _url(missing))
    rc = script.main([])
    captured = capsys.readouterr()
    assert rc != 0
    assert not missing.exists()


def test_target_line_never_prints_credentials(script, capsys):
    rc = script.main(["--database-url", "postgresql+asyncpg://kuser:s3cretpw@127.0.0.1:1/tradedb"])
    captured = capsys.readouterr()
    assert rc != 0  # nothing listens on port 1
    text = captured.out + captured.err
    assert "s3cretpw" not in text
    assert "kuser" not in text
    assert "127.0.0.1" in text and "tradedb" in text


def test_absent_optional_table_is_reported(script, tmp_path, capsys):
    """A database missing a scanned table says so instead of failing."""
    db_path = tmp_path / "partial.db"
    eng = create_engine(f"sqlite:///{db_path.as_posix()}")
    PortfolioPositionModel.__table__.create(eng)
    with eng.begin() as conn:
        conn.execute(insert(PortfolioPositionModel.__table__),
                     [_position("P1", f"AAPL|185|{FUTURE}|C", "AAPL")])
    eng.dispose()
    rc = script.main(["--database-url", _url(db_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "TABLE portfolio_positions.contract rows=1" in out
    assert "TABLE daily_risk_attempts.instrument ABSENT" in out
    assert "TABLE scan_sessions.last_result_json ABSENT" in out
