"""EXACT-STRIKE ES-4: READ-ONLY check of every persisted option contract id.

Plan: docs/superpowers/plans/2026-10-09-exact-strike-plan.md, section 3 (ES-4)
and section 8 below-gate notes (a) and (c). Until EXACT-STRIKE every
chain-built contract id truncated its strike (`int(strike)`), so a stored
`X|22|E|C` may have been meant as the 22.5 contract. This script LISTS the rows
Kenneth may want to look at. It never changes one (plan Q-1: report only).

It NEVER WRITES:
  - SQLite is opened through a `mode=ro` URI, so the driver itself refuses a
    write, and a file that does not exist is never created.
  - PostgreSQL (asyncpg) is opened with `default_transaction_read_only=on`,
    so the server refuses a write in this session.
  - Every statement passes `assert_read_only_statement` (SELECT / PRAGMA /
    SHOW only) before it reaches the driver, and nothing is ever committed.
  - `--chain` only reads quotes through the app's own `fetch_option_chain_async`.

Database: the same DATABASE_URL the app resolves (environment, then `.env` in
the CURRENT DIRECTORY, then the built-in fallback `sqlite+aiosqlite:///./dev.db`),
or `--database-url`. The resolved target is printed (driver, host, port,
database; never a user name or password). It REFUSES to run when the URL is the
built-in fallback and was not given explicitly, and whenever a SQLite file does
not exist: a wrong working directory must never yield a "clean" report on an
empty new file (plan section 8, note a).

Scanned (plan ES-4 table, plus note (c) history columns):
  portfolio_positions.contract           open positions
  closed_positions.contract              closed history
  watched_contracts.contract_id          stars
  scan_sessions.last_result_json         candidates[*].contract,
                                         candidates[*].contractDetails.strike,
                                         candidates[*].alternatives[*]
  audit_events.payload.strike            the trade-card snapshot (`strike`)
                                         recorded at buy time for a position
  position_alert_history.contract        alert history (note c)
  daily_risk_attempts.instrument         daily-risk history (note c); an OCC
                                         option symbol is exact and not listed

Report lines, one per finding:
  NONCANONICAL       strike text != format_strike(text) (`187.0`, `0187`).
                     Still quotes correctly after ES-1, but a string compare
                     against a new id (a star against a Step 6 row) misses.
  UNPARSEABLE        not SYMBOL|STRIKE|YYYY-MM-DD|C/P or SYMBOL|STOCK, or a
                     strike text the app's parse_strike_text refuses (such an
                     id cannot be quoted at all).
  MISMATCH           a recorded strike (trade-card snapshot, scan card
                     contractDetails) differs from its contract id's strike.
  AMBIGUOUS          (--chain only) an unexpired integer-strike id X|k|E|R
                     whose live Tradier chain for E lists a fractional strike
                     in (k, k+1). It MAY have been meant as that contract. An
                     id that reached a broker was ordered as the k contract and
                     is correct; the script cannot tell which.
  CHAIN_UNAVAILABLE  (--chain only) the chain for E could not be read (no
                     Tradier token, network, or E is no longer listed): the id
                     was NOT checked for ambiguity.
followed by `TABLE` lines (rows read per column, or ABSENT), `SUMMARY` counts
and a footer on what is not scanned. Exit 0 after a report (report only);
exit 2 when it refuses or cannot open the database.

Usage (from backend/, so `.env` resolves exactly as it does for the app):
    cd backend && .venv/Scripts/python.exe scripts/check_contract_strikes.py
    cd backend && .venv/Scripts/python.exe scripts/check_contract_strikes.py --chain
    ... scripts/check_contract_strikes.py --database-url 'postgresql+asyncpg://...'
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import event, inspect, text  # noqa: E402
from sqlalchemy.engine import URL, make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.config import Settings  # noqa: E402
from app.data.strike import canonical_strike, format_strike, parse_strike_text  # noqa: E402

EXIT_OK = 0
EXIT_REFUSED = 2

NONCANONICAL = "NONCANONICAL"
UNPARSEABLE = "UNPARSEABLE"
MISMATCH = "MISMATCH"
AMBIGUOUS = "AMBIGUOUS"
CHAIN_UNAVAILABLE = "CHAIN_UNAVAILABLE"

_SYMBOL = r"[A-Z0-9][A-Z0-9./-]*"
_OPTION_ID = re.compile(rf"({_SYMBOL})\|([^|]*)\|([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})\|([CP])")
_STOCK_ID = re.compile(rf"{_SYMBOL}\|STOCK")
# OCC/OSI option symbol (root, optionally space-padded, YYMMDD, C/P, strike*1000
# in 8 digits): what the broker paths store in daily_risk_attempts.instrument.
# Its strike is exact by construction.
_OSI = re.compile(r"[A-Z0-9.]{1,6} *[0-9]{6}[CP][0-9]{8}")

_DEFAULT_URL = Settings.model_fields["DATABASE_URL"].default

FOOTER = (
    "NOT SCANNED: frontend localStorage (bamendjou-auto-trade, bamendjou-alerts-v2,\n"
    "  legacy bamendjou-portfolio-v1, bamendjou-watched-contracts-v1) lives in the\n"
    "  browser and cannot be read by a backend script. Every producer of those ids\n"
    "  truncated, so they are integer-form and stay byte-identical (plan I1); the only\n"
    "  exposure is the AMBIGUOUS case, covered for stars and positions by the database\n"
    "  copies above.\n"
    "Report only: this script changed nothing. Any correction of a persisted id is a\n"
    "  per-row decision (plan Q-1); changing an id changes which contract is marked,\n"
    "  alerted or ordered."
)


# ── Read-only guard ─────────────────────────────────────────────────────────

class ReadOnlyViolation(RuntimeError):
    """A statement that is not a plain read was about to reach the database."""


_READ_HEADS = frozenset({"select", "pragma", "show"})


def assert_read_only_statement(statement: str) -> None:
    words = statement.split(None, 1)
    head = words[0].lower().rstrip("(;") if words else ""
    if head not in _READ_HEADS:
        raise ReadOnlyViolation(f"refusing non-read statement: {statement.strip()[:60]!r}")


def _guard(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
    assert_read_only_statement(statement)


# ── Target resolution (plan section 8, note a) ──────────────────────────────

class Refusal(Exception):
    """The script will not run against this target; the message says why."""


@dataclass
class Target:
    url: URL
    connect_args: dict
    label: str
    source: str


def resolve_target(explicit: Optional[str]) -> Target:
    if explicit is not None:
        raw, source = explicit, "--database-url"
    else:
        # A fresh Settings(), not the cached get_settings(): the same
        # resolution the app performs at startup in this directory.
        raw = Settings().DATABASE_URL
        source = "DATABASE_URL (environment, then ./.env, as the app resolves it)"
        if raw == _DEFAULT_URL:
            raise Refusal(
                f"DATABASE_URL resolved to the app's built-in default fallback ({_DEFAULT_URL}).\n"
                "  That usually means the wrong working directory (no .env here) and the\n"
                "  report would describe a local file, not the live app's database.\n"
                "  Run from backend/ where the app's .env is, or pass --database-url explicitly."
            )
    try:
        url = make_url(raw)
    except Exception:  # never echo the URL: it may carry a password
        raise Refusal(f"{source} is not a valid SQLAlchemy URL") from None

    backend, driver = url.get_backend_name(), url.get_driver_name()
    if backend == "sqlite":
        if driver != "aiosqlite":
            raise Refusal(f"unsupported SQLite driver {url.drivername!r}; use sqlite+aiosqlite")
        db = url.database or ""
        if db in ("", ":memory:") or db.startswith("file:"):
            raise Refusal("the SQLite URL names no plain database file (in-memory or URI form)")
        path = Path(db)
        if not path.is_absolute():
            path = Path.cwd() / path
        path = path.resolve()
        if not path.is_file():
            raise Refusal(
                f"SQLite file {path} does not exist. Refusing: opening it would create an\n"
                "  empty database and report a false 'clean'."
            )
        ro_url = URL.create("sqlite+aiosqlite", database=path.as_uri(),
                            query={"mode": "ro", "uri": "true"})
        return Target(ro_url, {}, f"sqlite+aiosqlite file={path} (opened mode=ro)", source)
    if backend == "postgresql":
        if driver != "asyncpg":
            raise Refusal(f"unsupported PostgreSQL driver {url.drivername!r}; use postgresql+asyncpg")
        label = (f"postgresql+asyncpg host={url.host} port={url.port or 5432} "
                 f"database={url.database} (session default_transaction_read_only=on)")
        connect_args = {"server_settings": {"default_transaction_read_only": "on"}, "timeout": 15}
        return Target(url, connect_args, label, source)
    raise Refusal(f"unsupported database {url.drivername!r}; this script opens only "
                  "sqlite+aiosqlite and postgresql+asyncpg, read-only")


# ── Classification ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ParsedId:
    symbol: str
    strike: int | float
    expiry: str
    right: str

    def text(self) -> str:
        return f"{self.symbol}|{format_strike(self.strike)}|{self.expiry}|{self.right}"


@dataclass
class Check:
    category: Optional[str]  # None = fine
    detail: str = ""
    parsed: Optional[ParsedId] = None


def check_contract_id(value: Any, *, allow_osi: bool = False) -> Check:
    if not isinstance(value, str):
        return Check(UNPARSEABLE, "not a string")
    if _STOCK_ID.fullmatch(value):
        return Check(None)
    if allow_osi and _OSI.fullmatch(value):
        return Check(None)
    m = _OPTION_ID.fullmatch(value)
    if m is None:
        return Check(UNPARSEABLE, "not SYMBOL|STRIKE|YYYY-MM-DD|C/P or SYMBOL|STOCK")
    symbol, strike_text, expiry, right = m.groups()
    try:
        date.fromisoformat(expiry)
    except ValueError:
        return Check(UNPARSEABLE, f"expiry {expiry!r} is not a calendar date")
    try:
        strike = parse_strike_text(strike_text)
    except (TypeError, ValueError):
        return Check(UNPARSEABLE, f"strike text {strike_text!r} is refused by parse_strike_text "
                                  "(the app cannot quote this id)")
    parsed = ParsedId(symbol, strike, expiry, right)
    canonical = format_strike(strike)
    if strike_text != canonical:
        return Check(NONCANONICAL, f"strike text {strike_text!r}, canonical {canonical!r}", parsed)
    return Check(None, parsed=parsed)


def check_strike_value(value: Any) -> Check:
    """A strike stored as a JSON value (number, or text). `parsed` is unused;
    the canonical value is returned in `detail` only on findings."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return Check(UNPARSEABLE, "strike is not a number")
    if isinstance(value, str):
        try:
            canonical = format_strike(parse_strike_text(value))
        except (TypeError, ValueError):
            return Check(UNPARSEABLE, "strike text is refused by parse_strike_text")
        stored = value
    else:
        try:
            canonical = format_strike(value)
        except (TypeError, ValueError, OverflowError):
            return Check(UNPARSEABLE, "strike is not a finite positive number")
        stored = json.dumps(value)
    if stored != canonical:
        return Check(NONCANONICAL, f"stored as {stored}, canonical {canonical}")
    return Check(None)


def _strike_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    try:
        return parse_strike_text(value) if isinstance(value, str) else canonical_strike(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _shown(value: Any) -> str:
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)


# ── Report accumulation ─────────────────────────────────────────────────────

@dataclass
class Report:
    findings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    tables: list[str] = field(default_factory=list)
    # (where, shown value, parsed id): every option id that could be ambiguous.
    chain_candidates: list[tuple[str, str, ParsedId]] = field(default_factory=list)

    def add(self, category: str, where: str, shown: str, detail: str) -> None:
        self.counts[category] = self.counts.get(category, 0) + 1
        self.findings.append(f"{category} {where} {shown} -- {detail}")

    def id_value(self, where: str, value: Any, *, allow_osi: bool = False) -> Check:
        chk = check_contract_id(value, allow_osi=allow_osi)
        if chk.category:
            self.add(chk.category, where, repr(value), chk.detail)
        if chk.parsed is not None:
            self.chain_candidates.append((where, repr(value), chk.parsed))
        return chk

    def strike_value(self, where: str, value: Any) -> Check:
        chk = check_strike_value(value)
        if chk.category:
            self.add(chk.category, where, _shown(value), chk.detail)
        return chk

    def mismatch(self, where: str, value: Any, id_where: str, parsed: Optional[ParsedId]) -> None:
        """A recorded strike `value` against the id it belongs to."""
        strike = _strike_or_none(value)
        if parsed is None or strike is None or strike == parsed.strike:
            return
        self.add(MISMATCH, where, _shown(value),
                 f"recorded strike {format_strike(strike)} != strike {format_strike(parsed.strike)} "
                 f"of {id_where} {parsed.text()!r}")


# ── Scanners ────────────────────────────────────────────────────────────────

# (table, column, row-key columns) for plain contract-id columns.
_ID_COLUMNS: list[tuple[str, str, tuple[str, ...]]] = [
    ("portfolio_positions", "contract", ("rec_id",)),
    ("closed_positions", "contract", ("rec_id",)),
    ("watched_contracts", "contract_id", ()),
    ("position_alert_history", "contract", ("rec_id", "alert_type")),
    ("daily_risk_attempts", "instrument", ("id",)),
]


def _schema(sync_conn) -> dict[str, set[str]]:
    insp = inspect(sync_conn)
    return {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names()}


def _present(report: Report, schema: dict[str, set[str]], table: str, columns: tuple[str, ...],
             label: str) -> bool:
    if table not in schema:
        report.tables.append(f"TABLE {label} ABSENT (no such table in this database; not scanned)")
        return False
    missing = [c for c in columns if c not in schema[table]]
    if missing:
        report.tables.append(f"TABLE {label} ABSENT (column(s) {', '.join(missing)} missing; not scanned)")
        return False
    return True


async def _scan_id_columns(conn, schema, report: Report, ids_by_rec: dict[str, tuple[str, Check]]) -> None:
    for table, column, keys in _ID_COLUMNS:
        label = f"{table}.{column}"
        if not _present(report, schema, table, (column, *keys), label):
            continue
        cols = ", ".join((*keys, column))
        rows = (await conn.execute(text(
            f"SELECT {cols} FROM {table} WHERE {column} IS NOT NULL ORDER BY {cols}"
        ))).all()
        for row in rows:
            *key_vals, value = row
            key = " ".join(f"{k}={v}" for k, v in zip(keys, key_vals))
            where = f"{label} {key}".rstrip()
            chk = report.id_value(where, value, allow_osi=(table == "daily_risk_attempts"))
            if table in ("portfolio_positions", "closed_positions") and key_vals:
                ids_by_rec.setdefault(str(key_vals[0]), (f"{table}.contract", chk))
        report.tables.append(f"TABLE {label} rows={len(rows)}")


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, (str, bytes, bytearray)) else value


async def _scan_snapshots(conn, schema, report: Report, ids_by_rec: dict[str, tuple[str, Check]]) -> None:
    label = "audit_events.payload.strike"
    if not _present(report, schema, "audit_events", ("rec_id", "event_type", "payload"), label):
        return
    rows = (await conn.execute(text(
        "SELECT rec_id, payload FROM audit_events "
        "WHERE event_type = 'approval' AND payload IS NOT NULL ORDER BY rec_id"
    ))).all()
    n = 0
    for rec_id, raw in rows:
        where = f"{label} rec_id={rec_id}"
        try:
            payload = _json(raw)
        except ValueError:
            n += 1
            report.add(UNPARSEABLE, where, "<payload>", "approval payload is not valid JSON")
            continue
        if not isinstance(payload, dict) or payload.get("strike") is None:
            continue  # no snapshot strike (a stock card, or an older snapshot)
        n += 1
        value = payload["strike"]
        report.strike_value(where, value)
        id_where, chk = ids_by_rec.get(str(rec_id), ("", Check(None)))
        report.mismatch(where, value, id_where, chk.parsed)
    report.tables.append(f"TABLE {label} rows={n} (trade-card snapshot of a position, by rec_id)")


def _scan_result_blob(report: Report, where_row: str, data: Any) -> int:
    """Check one parsed ScanResult. Returns the number of values checked."""
    checked = 0
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(candidates, list):
        return 0
    for i, card in enumerate(candidates):
        if not isinstance(card, dict):
            continue
        base = f"{where_row} candidates[{i}]"
        parsed = None
        if card.get("contract") is not None:
            checked += 1
            parsed = report.id_value(f"{base}.contract", card["contract"]).parsed
        details = card.get("contractDetails")
        if isinstance(details, dict) and details.get("strike") is not None:
            checked += 1
            where = f"{base}.contractDetails.strike"
            report.strike_value(where, details["strike"])
            report.mismatch(where, details["strike"], f"{base}.contract", parsed)
        alternatives = card.get("alternatives")
        for j, alt in enumerate(alternatives if isinstance(alternatives, list) else []):
            if not isinstance(alt, dict) or alt.get("strike") is None:
                continue
            checked += 1
            where = f"{base}.alternatives[{j}]"
            chk = report.strike_value(f"{where}.strike", alt["strike"])
            strike = _strike_or_none(alt["strike"])
            symbol, expiry, right = alt.get("symbol"), alt.get("expiry"), alt.get("right")
            if chk.category == UNPARSEABLE or strike is None:
                continue
            built = check_contract_id(f"{symbol}|{format_strike(strike)}|{expiry}|{right}")
            if built.parsed is None:
                report.add(UNPARSEABLE, where, _shown({"symbol": symbol, "expiry": expiry, "right": right}),
                           "alternative's symbol/expiry/right do not form a contract id")
            else:
                report.chain_candidates.append((where, repr(built.parsed.text()), built.parsed))
    return checked


async def _scan_sessions(conn, schema, report: Report) -> None:
    label = "scan_sessions.last_result_json"
    if not _present(report, schema, "scan_sessions", ("id", "last_result_json"), label):
        return
    rows = (await conn.execute(text(
        "SELECT id, last_result_json FROM scan_sessions WHERE last_result_json IS NOT NULL ORDER BY id"
    ))).all()
    values = 0
    for sid, raw in rows:
        where_row = f"{label} id={sid}"
        try:
            data = _json(raw)
        except ValueError:
            report.add(UNPARSEABLE, where_row, "<blob>", "last_result_json is not valid JSON")
            continue
        values += _scan_result_blob(report, where_row, data)
    report.tables.append(f"TABLE {label} rows={len(rows)} values={values}")


# ── --chain ─────────────────────────────────────────────────────────────────

async def _fetch_fractional_strikes(groups: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], Optional[list]]:
    """{(symbol, expiry, right): strikes listed for exactly that expiry, or None
    when the chain could not be read}. One sequential fetch per group, through
    the app's own chain builder; it only reads quotes."""
    import httpx

    from app.data import market

    out: dict[tuple[str, str, str], Optional[list]] = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for symbol, expiry, right in groups:
            try:
                rows = await market.fetch_option_chain_async(client, symbol, expiry=expiry, option_type=right)
            except Exception:
                rows = None
            strikes = []
            for row in rows or []:
                # The builder falls back to ANOTHER expiry when E is not listed;
                # those rows are not E's chain.
                if row.get("expiry") != expiry or row.get("right", right) != right:
                    continue
                s = _strike_or_none(row.get("strike"))
                if s is not None:
                    strikes.append(s)
            out[(symbol, expiry, right)] = strikes or None
    return out


async def _check_chain(report: Report) -> int:
    """Adds AMBIGUOUS / CHAIN_UNAVAILABLE findings. Returns the expired count."""
    today = date.today()
    live: list[tuple[str, str, ParsedId]] = []
    expired = 0
    for where, shown, parsed in report.chain_candidates:
        if not isinstance(parsed.strike, int):
            continue  # a fractional id is already exact
        if date.fromisoformat(parsed.expiry) < today:
            expired += 1
            continue
        live.append((where, shown, parsed))
    groups = sorted({(p.symbol, p.expiry, p.right) for _, _, p in live})
    chains = await _fetch_fractional_strikes(groups) if groups else {}
    for where, shown, p in live:
        strikes = chains.get((p.symbol, p.expiry, p.right))
        if strikes is None:
            report.add(CHAIN_UNAVAILABLE, where, shown,
                       f"no chain rows for {p.expiry} {p.right} (no Tradier token, network, or "
                       "expiry not listed); NOT checked")
            continue
        k = p.strike
        near = sorted(s for s in strikes if k < s < k + 1)
        if near:
            listed = ", ".join(format_strike(s) for s in near)
            report.add(AMBIGUOUS, where, shown,
                       f"chain for {p.expiry} {p.right} lists fractional strike(s) {listed} in "
                       f"({k}, {k + 1}); this id may have been meant as one of them. If it reached "
                       f"a broker it was ordered as the {k} contract and is correct")
    return expired


# ── Main ────────────────────────────────────────────────────────────────────

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="READ-ONLY report of persisted option contract ids (EXACT-STRIKE ES-4). Never writes.")
    p.add_argument("--database-url", default=None,
                   help="Database to read instead of the app's DATABASE_URL resolution. Required to "
                        "read the built-in default fallback (sqlite+aiosqlite:///./dev.db).")
    p.add_argument("--chain", action="store_true",
                   help="Also read the live Tradier chain for every unexpired integer-strike id "
                        "and list AMBIGUOUS rows (quotes only; nothing is ordered or written).")
    return p


async def run(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        target = resolve_target(args.database_url)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    print("EXACT-STRIKE persisted contract-id check (ES-4) -- READ-ONLY, report only")
    print(f"Database: {target.label}")
    print(f"  from {target.source}")
    print(f"Chain check: {'on (live Tradier, unexpired integer-strike ids)' if args.chain else 'off (pass --chain to list AMBIGUOUS rows)'}")
    print()

    report = Report()
    engine = create_async_engine(target.url, connect_args=target.connect_args)
    event.listen(engine.sync_engine, "before_cursor_execute", _guard)
    try:
        async with engine.connect() as conn:
            schema = await conn.run_sync(_schema)
            ids_by_rec: dict[str, tuple[str, Check]] = {}
            await _scan_id_columns(conn, schema, report, ids_by_rec)
            await _scan_snapshots(conn, schema, report, ids_by_rec)
            await _scan_sessions(conn, schema, report)
            await conn.rollback()  # nothing to undo; never commit
    except ReadOnlyViolation:
        raise
    except Exception as exc:
        reason = type(getattr(exc, "orig", None) or exc).__name__
        print(f"REFUSED: could not read the database ({reason}). Nothing was reported.", file=sys.stderr)
        return EXIT_REFUSED
    finally:
        await engine.dispose()

    expired = await _check_chain(report) if args.chain else None

    for line in report.findings:
        print(line)
    if report.findings:
        print()
    for line in report.tables:
        print(line)
    if expired is not None:
        print(f"INFO expired integer-strike ids not chain-checked: {expired}")
    print()
    categories = [NONCANONICAL, UNPARSEABLE, MISMATCH]
    if args.chain:
        categories += [AMBIGUOUS, CHAIN_UNAVAILABLE]
    for cat in categories:
        print(f"SUMMARY {cat} {report.counts.get(cat, 0)}")
    print()
    print(FOOTER)
    return EXIT_OK


def main(argv: Optional[list[str]] = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    sys.exit(main())
