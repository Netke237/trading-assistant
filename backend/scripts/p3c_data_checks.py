#!/usr/bin/env python3
"""P3c read-only data checks (plan 2026-09-25-p3c-scan-sizing-leftovers-plan.md, §5 and §6).

WHY THIS EXISTS
---------------
§5: four symbols (WMT CPRT TSCO SRE) produced a NEGATIVE bearish backtest target.
The lead: `historical_store._read_bars` returns close = raw_close x adj_factor
(adjusted) but open/high/low RAW, so across a split every pre-split bar's
high/low sits at the pre-split price next to an adjusted close. ATR is then
inflated and `current - risk x mult` goes below zero. This script measures
that on the real `ohlcv_daily` rows and prints one verdict per symbol:

    STALE ADJ_FACTOR    the adjusted close itself jumps by the split ratio
    MIXED ADJUSTMENT    adjusted close continuous, pre-split high/low raw
    NO SPLIT IN WINDOW  / CLEAN
    NO ROWS             nothing stored for the symbol in the window
    TOO FEW ROWS (n)    1..14 rows, too few for ATR(14)

The bearish pullback_ema targets are measured by calling the REAL
`strategy_engine.pullback_ema_signal`; only its empty-ladder case is patched so
the bar is still recorded (see `_LadderSpy`).

§6: the options regime series length by source -- the DB window, Tradier's
252 bars and the yfinance fallback -- with the compute_omm verdict on each.

READ-ONLY
---------
Postgres is the primary path (decision P3C-SCRIPT-POSTGRES-PRIMARY-2026-09-27):
DATABASE_URL from the environment or backend/.env, ONE connection, ONE
transaction opened with SET TRANSACTION READ ONLY and never committed. A SQLite
URL is refused unless --allow-sqlite is passed (the code's default URL is an
empty dev.db, which would print NO ROWS for everything); then the file is
opened with sqlite3 `mode=ro`. It never calls `get_bars` (which writes on a
stale DB). `--sections sources` is the only part that touches the network (GETs).

USAGE
-----
    cd backend
    .venv/bin/python scripts/p3c_data_checks.py                       # both sections
    .venv/bin/python scripts/p3c_data_checks.py --sections db
    .venv/bin/python scripts/p3c_data_checks.py --symbols WMT TSCO --verbose
    .venv/bin/python scripts/p3c_data_checks.py --params-json '{"pullback_ema_period": 35}'
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse
import asyncio
import json
import math
import os
import sqlite3
import statistics
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import sqlalchemy.exc
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# Run by path, sys.path[0] is backend/scripts, so `import app` needs this
# (as scripts/pin_fixtures.py does). Independent of the cwd.
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

DEFAULT_SYMBOLS = ["WMT", "CPRT", "TSCO", "SRE", "LYB"]

# The request fields `_SIGNAL_KWARGS["pullback_ema"]` reads (stock_scan.py).
PARAM_FIELDS = (
    "pullback_tolerance_pct",
    "pullback_ema_period",
    "pullback_trend_ema",
    "pullback_ma_type",
    "pullback_require_reversal",
)

# One-day raw_close ratio (prev / cur) that reads as a split: N:1 forward
# splits drop the price by N, 1:N reverse splits raise it.
_SPLIT_RATIOS = (2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 20.0)
_SPLIT_TOL = 0.03
# Pre-split median high / adjusted close within this of the split ratio -> MIXED.
_MIXED_TOL = 0.15

_ATR_BARS = 15          # ATR(14) at a bar needs 15 bars (14 true ranges)
_BT_WINDOW = 350        # strategy_backtest.py: trailing slice cap
_BT_MIN_BARS = 60       # strategy_backtest.py: skip under 60 bars
_SPLIT_CONTEXT = 5      # bars either side of a detected split

_SELECT = (
    "SELECT date, open, high, low, close, volume, adj_factor, split_factor, source "
    "FROM ohlcv_daily WHERE symbol = {p}sym AND date >= {p}start AND date <= {p}end "
    "ORDER BY date"
)


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


# ── DB URL ────────────────────────────────────────────────────────────────────

def resolve_url() -> tuple[str, str]:
    """DATABASE_URL as the app would see it: environment first, then backend/.env, then repo-root .env.

    Returns (url, source_description).
    A fresh Settings (not the lru_cached get_settings) with an explicit
    _env_file, because Settings' own env_file=".env" is cwd-relative.
    app.config imports only pydantic_settings and builds no engine.
    """
    if "DATABASE_URL" in os.environ and os.environ["DATABASE_URL"].strip():
        return os.environ["DATABASE_URL"].strip(), "environment"

    backend_env = BACKEND / ".env"
    if backend_env.is_file():
        try:
            from dotenv import dotenv_values
            vals = dotenv_values(backend_env)
            if vals.get("DATABASE_URL"):
                return str(vals["DATABASE_URL"]).strip(), "backend/.env"
        except Exception:
            pass

    root_env = BACKEND.parent / ".env"
    if root_env.is_file():
        try:
            from dotenv import dotenv_values
            vals = dotenv_values(root_env)
            if vals.get("DATABASE_URL"):
                return str(vals["DATABASE_URL"]).strip(), "repo-root .env"
        except Exception:
            pass

    from app.config import Settings
    return Settings(_env_file=BACKEND / ".env").DATABASE_URL, "default"


def route_url(url: str | tuple[str, ...], allow_sqlite: bool) -> tuple[str, object]:
    """Return ("sqlite", Path) or ("postgres", URL), or exit naming the problem.

    Runs BEFORE any app.* import other than app.config: app/database.py builds
    its engine at import, so an unrouted postgres:// URL would crash there.
    """
    if isinstance(url, (tuple, list)):
        url = url[0]
    try:
        u = make_url(url)
    except Exception:
        _die("cannot parse DATABASE_URL (not printed: it may hold a password)")
    driver = u.drivername
    if u.get_backend_name() == "sqlite":
        if not u.database or u.database == ":memory:":
            _die(f"DATABASE_URL is a SQLite URL with no file ({driver}); nothing to read")
        path = Path(u.database)
        if not path.is_absolute():
            path = BACKEND / path
        if not allow_sqlite:
            _die(
                f"DATABASE_URL resolves to SQLite ({path}), not Postgres. Set DATABASE_URL "
                f"(environment or backend/.env) to your Postgres URL, or pass --allow-sqlite "
                f"to read this file."
            )
        if not path.exists():
            _die(f"SQLite file not found: {path}")
        return "sqlite", path
    if driver in ("postgresql+asyncpg", "postgresql", "postgres"):
        # Only the asyncpg form builds an engine here (psycopg2 is not installed).
        return "postgres", u.set(drivername="postgresql+asyncpg")
    _die(f"unsupported DATABASE_URL scheme {driver!r}: expected postgresql+asyncpg, "
         f"postgresql, postgres (or sqlite with --allow-sqlite)")
    raise AssertionError("unreachable")


# ── Reading ohlcv_daily ───────────────────────────────────────────────────────

def _row(r) -> dict:
    d = r[0]
    d = date.fromisoformat(str(d)[:10]) if not isinstance(d, date) else d
    return {
        "date": d,
        "open": float(r[1]),
        "high": float(r[2]),
        "low": float(r[3]),
        "raw_close": float(r[4]),
        "volume": int(r[5]),
        "adj_null": r[6] is None,
        # A NULL adj_factor is read as 1.0 everywhere, as _read_bars does.
        "adj": float(r[6]) if r[6] is not None else 1.0,
        "split_factor": float(r[7]) if r[7] is not None else None,
        "source": r[8],
    }


def read_sqlite(path: Path, symbols: list[str], start: date, end: date) -> dict[str, list[dict]]:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        sql = _SELECT.format(p=":")
        return {
            s: [_row(r) for r in con.execute(
                sql, {"sym": s, "start": start.isoformat(), "end": end.isoformat()}
            ).fetchall()]
            for s in symbols
        }
    finally:
        con.close()


async def read_postgres(url, symbols: list[str], start: date, end: date) -> dict[str, list[dict]]:
    """ONE connection, ONE read-only transaction, never committed.

    engine.connect(), never engine.begin() (which commits on exit). SET
    TRANSACTION READ ONLY covers one transaction only, so nothing here commits;
    close() rolls the transaction back. NullPool: close() really closes, so no
    pooled connection outlives the event loop.
    """
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        conn = await engine.connect()
    except (OSError, sqlalchemy.exc.DBAPIError) as e:
        _die(f"cannot connect to {url.render_as_string(hide_password=True)}: "
             f"{type(e).__name__}: {e}")
    try:
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        sql = text(_SELECT.format(p=":"))
        out = {}
        for s in symbols:
            res = await conn.execute(sql, {"sym": s, "start": start, "end": end})
            out[s] = [_row(r) for r in res.fetchall()]
        return out
    finally:
        await conn.close()


# ── Series ────────────────────────────────────────────────────────────────────

def mixed_series(rows: list[dict]) -> list[dict]:
    """What _read_bars returns: open/high/low RAW, close = raw_close x adj_factor."""
    return [{"time": r["date"].isoformat(), "open": r["open"], "high": r["high"],
             "low": r["low"], "close": round(r["raw_close"] * r["adj"], 6),
             "volume": r["volume"]} for r in rows]


def raw_series(rows: list[dict]) -> list[dict]:
    return [{"time": r["date"].isoformat(), "open": r["open"], "high": r["high"],
             "low": r["low"], "close": r["raw_close"], "volume": r["volume"]} for r in rows]


def adjusted_series(rows: list[dict]) -> list[dict]:
    """OHLC all x adj_factor."""
    return [{"time": r["date"].isoformat(), "open": r["open"] * r["adj"],
             "high": r["high"] * r["adj"], "low": r["low"] * r["adj"],
             "close": r["raw_close"] * r["adj"], "volume": r["volume"]} for r in rows]


def detect_splits(rows: list[dict]) -> list[tuple[int, float]]:
    """(index of the first post-split row, ratio prev/cur) from consecutive raw closes.

    Does not use split_factor: the Alpaca normaliser hard-codes it to 1.0.
    """
    ratios = _SPLIT_RATIOS + tuple(1 / r for r in _SPLIT_RATIOS)
    out = []
    for i in range(1, len(rows)):
        cur = rows[i]["raw_close"]
        if cur <= 0:
            continue
        q = rows[i - 1]["raw_close"] / cur
        for r in ratios:
            if abs(q / r - 1) <= _SPLIT_TOL:
                out.append((i, r))
                break
    return out


def split_rebuilt_series(rows: list[dict], splits: list[tuple[int, float]]) -> list[dict]:
    """Raw OHLC with the detected split ratios applied backwards (ignores adj_factor)."""
    out = []
    for i, r in enumerate(rows):
        f = 1.0
        for idx, ratio in splits:
            if i < idx:
                f /= ratio
        out.append({"time": r["date"].isoformat(), "open": r["open"] * f,
                    "high": r["high"] * f, "low": r["low"] * f,
                    "close": r["raw_close"] * f,
                    "volume": int(round(r["volume"] / f))})
    return out


def verdict(rows: list[dict], splits: list[tuple[int, float]]) -> tuple[str, list[str]]:
    if not splits:
        return "NO SPLIT IN WINDOW", []
    notes = []
    rank = {"CLEAN": 0, "MIXED ADJUSTMENT": 1, "STALE ADJ_FACTOR": 2}
    worst = "CLEAN"
    bounds = [0] + [i for i, _ in splits]
    for k, (i, ratio) in enumerate(splits):
        prev, cur = rows[i - 1], rows[i]
        jump = (prev["raw_close"] * prev["adj"]) / (cur["raw_close"] * cur["adj"])
        pre = rows[bounds[k]:i]
        hi_ratio = statistics.median(r["high"] / (r["raw_close"] * r["adj"]) for r in pre)
        if abs(jump / ratio - 1) <= _SPLIT_TOL:
            v = "STALE ADJ_FACTOR"
        elif abs(hi_ratio / ratio - 1) <= _MIXED_TOL:
            v = "MIXED ADJUSTMENT"
        else:
            v = "CLEAN"
        notes.append(f"split {_ratio_label(ratio)} on {cur['date']}: adjusted-close jump "
                     f"{jump:.3f}, pre-split median high/adj_close {hi_ratio:.3f} -> {v}")
        if rank[v] > rank[worst]:
            worst = v
    return worst, notes


def _ratio_label(r: float) -> str:
    return f"{r:g}:1" if r >= 1 else f"1:{1 / r:g}"


# ── Target measurement (the REAL signal) ─────────────────────────────────────

class _LadderSpy:
    """Wraps strategy_engine._build_target_ladder for the script's own calls.

    Calls the ORIGINAL helper, records its arguments and real result, returns
    the real result unchanged -- unless it is EMPTY, when it returns a bearish
    placeholder one-rung ladder so the signal completes and the bar is still
    recorded. The placeholder is never reported.
    """

    def __init__(self, original):
        self.original = original
        self.last: dict | None = None

    def __call__(self, **kw):
        real = self.original(**kw)
        self.last = {"args": kw, "real": list(real)}
        if real:
            return real
        return [round(kw["entry"] * 0.5, 2)]


def _fmt(x: float | None) -> str:
    if x is None:
        return "None"
    x = 0.0 if x == 0 else x
    return f"{x:.2f}"


def _primary_status(p: float | None, entry: float) -> str:
    """The primary's status by the same 2dp comparison _valid makes (bearish)."""
    if p is None or not math.isfinite(p):
        return "missing"
    if p <= 0:
        return "non-positive"
    if round(p, 2) >= round(entry, 2):
        return "not below entry"
    return "valid"


def measure_targets(bars: list[dict], params: dict) -> list[dict]:
    """Every setup bar of the bearish pullback_ema signal over `bars`.

    Bar i is evaluated on bars[max(0, i+1-350) : i+1], skipped under 60 bars,
    and the signal is called as the backtest calls it (no current_price).
    """
    from app.services import strategy_engine as se

    spy = _LadderSpy(se._build_target_ladder)
    out = []
    with mock.patch.object(se, "_build_target_ladder", spy):
        for i in range(len(bars)):
            sl = bars[max(0, i + 1 - _BT_WINDOW): i + 1]
            if len(sl) < _BT_MIN_BARS:
                continue
            spy.last = None
            sig = se.pullback_ema_signal(sl, direction="Bearish", **params)
            if sig is None:
                continue
            a = spy.last["args"]
            entry, stop = a["entry"], a["stop"]
            risk = abs(entry - stop)
            f = round(entry - risk * max(a["fallback_mult"], se._LADDER_MIN_FALLBACK_R), 2)
            f = 0.0 if f == 0 else f
            ext = list(a["extensions"]) + [None, None]
            out.append({
                "index": i,
                "date": bars[i].get("time"),
                "entry": entry,
                "stop_price": sig.stop_price,
                "primary": a["primary"],
                "ext1": ext[0],
                "ext2": ext[1],
                "real": spy.last["real"],
                "target": spy.last["real"][0] if spy.last["real"] else None,
                "fallback": f,
                "primary_status": _primary_status(a["primary"], entry),
            })
    return out


def describe_bar(rec: dict) -> str:
    head = (f"{rec['date']} stop {_fmt(rec['stop_price'])} rungs primary {_fmt(rec['primary'])} "
            f"ext1 {_fmt(rec['ext1'])} ext2 {_fmt(rec['ext2'])}: ")
    if rec["real"]:
        return head + f"target {_fmt(rec['target'])}"
    f = rec["fallback"]
    line = (f"NONE — no valid rung: primary {_fmt(rec['primary'])} {rec['primary_status']}, "
            f"fallback {_fmt(f)} <= 0. Before P3a the signal emitted {_fmt(f)} as target_price; ")
    if f < 0:
        line += ("had this bar's order FILLED, backtesting.py would have raised "
                 "(0 < price assertion) and failed the symbol's whole backtest.")
    else:
        line += "had it filled, the short would have opened with NO take-profit, no raise."
    return head + line


def summarize_targets(recs: list[dict]) -> list[str]:
    def rungs(r):
        return [x for x in (r["primary"], r["ext1"], r["ext2"]) if x is not None and math.isfinite(x)]

    empty = [r for r in recs if not r["real"]]
    nonpos = [r for r in recs if any(x <= 0 for x in rungs(r))]
    lines = [f"signal fires: {len(recs)} (UPPER BOUND on what the backtest evaluates: it calls "
             f"the signal only while flat; this script calls it on every bar)",
             f"bars with a non-positive raw rung: {len(nonpos)}",
             f"bars with an empty real ladder: {len(empty)}"]
    all_rungs = [(x, r["date"]) for r in recs for x in rungs(r)]
    if all_rungs:
        x, d = min(all_rungs, key=lambda t: t[0])
        lines.append(f"minimum raw rung: {_fmt(x)} on {d}")
    if recs:
        m = min(recs, key=lambda r: r["fallback"])
        lines.append(f"minimum fallback: {_fmt(m['fallback'])} on {m['date']}")
    neg = [r for r in empty if r["fallback"] < 0]
    if neg:
        lines.append(f"FIRST empty-ladder bar with fallback < 0: {neg[0]['date']} "
                     f"(fallback {_fmt(neg[0]['fallback'])}) -- the EARLIEST bar at which the "
                     f"pre-P3a backtest could have raised, not necessarily the one that did")
    else:
        lines.append("no empty-ladder bar with fallback < 0")
    lines.append(f"empty-ladder bars with fallback == 0.00: "
                 f"{sum(1 for r in empty if r['fallback'] == 0)}")
    return lines


# ── ATR ──────────────────────────────────────────────────────────────────────

def atr_at(bars: list[dict], i: int) -> float | None:
    """ATR(14) at bar i, exactly as strategy_engine._atr sees bars[:i+1]."""
    from app.services.strategy_engine import _atr
    if i + 1 < _ATR_BARS:
        return None
    return _atr(bars[i + 1 - _ATR_BARS: i + 1])


# ── Params ───────────────────────────────────────────────────────────────────

def parse_param_overrides(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _die(f"--params-json is not valid JSON: {e}")
    if not isinstance(data, dict):
        _die("--params-json must be a JSON object")
    bad = sorted(set(data) - set(PARAM_FIELDS))
    if bad:
        _die(f"--params-json: refused key(s) {', '.join(bad)}; only these request fields are "
             f"accepted: {', '.join(PARAM_FIELDS)}")
    return data


def build_params(overrides: dict) -> tuple[dict, dict]:
    """The merged set the stock-scan backtest runs: exit < active < request."""
    from pydantic import ValidationError

    from app.routers.stock_scan import _SIGNAL_KWARGS, _merge_strategy_params
    from app.schemas.stock_scan import StockScanRequest
    from app.services.strategy_param_store import get_active, get_exit

    try:
        req = StockScanRequest(universe=[], direction="Bearish", horizon="Swing",
                               strategy="pullback_ema", **overrides)
    except ValidationError as e:
        _die(f"--params-json: {e}")
    req_kw = _SIGNAL_KWARGS["pullback_ema"](req)
    merged = _merge_strategy_params("pullback_ema", "Bearish", req_kw)
    active = get_active("pullback_ema", "Bearish")
    exit_ = get_exit("pullback_ema")
    layers = {}
    for k in merged:
        if req_kw.get(k) is not None:
            layers[k] = "request"
        elif k in active:
            layers[k] = "active"
        elif k in exit_:
            layers[k] = "exit"
    return merged, layers


# ── §5 report ────────────────────────────────────────────────────────────────

def report_symbol(sym: str, rows: list[dict], start: date, end: date, params: dict,
                  verbose: bool) -> str:
    """Print §5 for one symbol; return its verdict."""
    print(f"\n=== {sym} ===")
    n = len(rows)
    if n == 0:
        print(f"NO ROWS in ohlcv_daily for {sym} over {start}..{end}")
        return "NO ROWS"
    if n < _ATR_BARS:
        print(f"TOO FEW ROWS ({n}) in ohlcv_daily for {sym} over {start}..{end} "
              f"(stored {rows[0]['date']}..{rows[-1]['date']})")
        return f"TOO FEW ROWS ({n})"

    print(f"rows: {n}, {rows[0]['date']}..{rows[-1]['date']}")
    print("source mix: " + ", ".join(f"{s or 'NULL'} {c}" for s, c in
                                     Counter(r["source"] for r in rows).most_common()))
    nulls = sum(r["adj_null"] for r in rows)
    for key, label in (("adj", "adj_factor"), ("split_factor", "split_factor")):
        changes = [(rows[i]["date"], rows[i - 1][key], rows[i][key])
                   for i in range(1, n) if rows[i][key] != rows[i - 1][key]]
        extra = f" ({nulls} NULL, read as 1.0)" if key == "adj" and nulls else ""
        print(f"{label} changes: {len(changes)}{extra}")
        for d, a, b in changes[:10]:
            print(f"  {d}: {a} -> {b}")
        if len(changes) > 10:
            print(f"  ... {len(changes) - 10} more")

    mixed = mixed_series(rows)
    hi = max(range(n), key=lambda i: rows[i]["high"] / mixed[i]["close"])
    print(f"max high / (raw_close x adj_factor): {rows[hi]['high'] / mixed[hi]['close']:.3f} "
          f"on {rows[hi]['date']}")
    mv = max(range(1, n), key=lambda i: abs(mixed[i]["close"] / mixed[i - 1]["close"] - 1))
    print(f"largest one-day |delta_close| (adjusted): "
          f"{abs(mixed[mv]['close'] / mixed[mv - 1]['close'] - 1) * 100:.1f}% "
          f"on {rows[mv - 1]['date']} -> {rows[mv]['date']}")

    splits = detect_splits(rows)
    v, notes = verdict(rows, splits)
    for line in notes:
        print(line)
    rebuilt = split_rebuilt_series(rows, splits)

    last = n - 1
    print(f"ATR(14) at {rows[last]['date']}: as _read_bars returns it (mixed) "
          f"{atr_at(mixed, last):.4f}, fully raw {atr_at(raw_series(rows), last):.4f}, "
          f"fully adjusted {atr_at(adjusted_series(rows), last):.4f}")

    atr_m = [atr_at(mixed, i) for i in range(n)]
    atr_r = [atr_at(rebuilt, i) for i in range(n)]
    ratios = [(atr_m[i] / atr_r[i], i) for i in range(n)
              if atr_m[i] is not None and atr_r[i]]
    if ratios:
        q, i = max(ratios)
        print(f"max ATR(14) mixed / split-rebuilt over every bar: {q:.3f} on {rows[i]['date']} "
              f"(mixed {atr_m[i]:.4f}, rebuilt {atr_r[i]:.4f})")

    recs = {"mixed (_read_bars)": measure_targets(mixed, params),
            "split-rebuilt": measure_targets(rebuilt, params)}
    for name, rs in recs.items():
        print(f"-- bearish pullback_ema targets, {name} series --")
        for line in summarize_targets(rs):
            print("  " + line)
        shown = rs if verbose else [r for r in rs if not r["real"]]
        for r in shown:
            print("  " + describe_bar(r))

    for idx, ratio in splits:
        print(f"-- ±{_SPLIT_CONTEXT} bars around the {_ratio_label(ratio)} split on "
              f"{rows[idx]['date']} --")
        by_idx = {name: {r["index"]: r for r in rs} for name, rs in recs.items()}
        for i in range(max(0, idx - _SPLIT_CONTEXT), min(n, idx + _SPLIT_CONTEXT + 1)):
            a, b = atr_m[i], atr_r[i]
            atr_txt = (f"ATR mixed {a:.4f} rebuilt {b:.4f} ratio {a / b:.3f}"
                       if a is not None and b else "ATR n/a")
            print(f"  {rows[i]['date']}: {atr_txt}")
            for name, m in by_idx.items():
                if i in m:
                    print(f"    {name}: " + describe_bar(m[i]))

    print(f"VERDICT {sym}: {v}")
    if v == "NO SPLIT IN WINDOW":
        ext1 = [(r["ext1"], r["date"]) for r in recs["mixed (_read_bars)"]
                if r["ext1"] is not None]
        tail = (f"minimum raw ext1 {_fmt(min(ext1)[0])} on {min(ext1)[1]}" if ext1
                else "no setup bar, so no raw ext1")
        print(f"the split hypothesis does not explain {sym}'s negative target; {tail}")
    return v


# ── §6 report ────────────────────────────────────────────────────────────────

async def report_sources(symbols: list[str], db_rows: dict[str, list[dict]], today: date) -> None:
    import httpx

    from app.data import market
    from app.services.config_loader import load_scoring_cfg
    from app.services.regime_omm import compute_omm

    rcfg = load_scoring_cfg()["regime"]
    daily = {h: c for h, c in rcfg.items()
             if isinstance(c, dict) and c.get("timeframe") == "daily"}
    db_start = today - timedelta(days=int(1.75 * 252))

    def omm_line(bars: list[dict]) -> str:
        if not bars:
            return "    no bars"
        closes = [b["close"] for b in bars]
        parts = []
        for h, c in daily.items():
            for d in ("Bullish", "Bearish"):
                r = compute_omm(closes, direction=d, lookback=c["lookback"],
                                window=c["window"], min_obs=c["min_obs"])
                parts.append(f"{h}/{d}: " + (f"{r.state} conviction {r.conviction_pct}"
                                             if r else "None (too short / too few obs)"))
        return "    " + "; ".join(parts)

    def span(bars: list[dict]) -> str:
        if not bars:
            return "0 bars"
        return f"{len(bars)} bars, {str(bars[0]['time'])[:10]}..{str(bars[-1]['time'])[:10]}"

    def _refuse(request):
        raise httpx.ConnectError("blocked by p3c_data_checks", request=request)

    print("\n##### §6 options regime series by source #####")
    for sym in symbols:
        print(f"\n=== {sym} ===")
        db = mixed_series([r for r in db_rows.get(sym, []) if r["date"] >= db_start])
        print(f"  DB [{db_start}..{today}]: {span(db)}")
        print(omm_line(db))

        market._candles_cache.pop(sym, None)
        with mock.patch.object(market, "_fetch_daily_yf", lambda s: []):
            async with httpx.AsyncClient(timeout=20) as client:
                tr = await market.fetch_candles_async(client, sym)
        market._candles_cache.pop(sym, None)
        print(f"  Tradier: {span(tr)}")
        print(omm_line(tr))

        async with httpx.AsyncClient(transport=httpx.MockTransport(_refuse)) as client:
            yf = await market.fetch_candles_async(client, sym)
        market._candles_cache.pop(sym, None)
        print(f"  yfinance fallback: {span(yf)}")
        print(omm_line(yf))


# ── main ─────────────────────────────────────────────────────────────────────

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="P3c read-only data checks: §5 split/adjustment verdicts and bearish "
                    "pullback_ema targets, §6 options regime series by source.")
    p.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS,
                   help=f"symbols to check (default: {' '.join(DEFAULT_SYMBOLS)})")
    p.add_argument("--sections", default="db,sources",
                   help="comma list of db,sources (default both; only 'sources' uses the network)")
    p.add_argument("--allow-sqlite", action="store_true",
                   help="read a SQLite DATABASE_URL (unit tests); Postgres is the primary path")
    p.add_argument("--params-json", default=None,
                   help="JSON overlay of the pullback_ema request fields: " + ", ".join(PARAM_FIELDS))
    p.add_argument("--verbose", action="store_true",
                   help="print every setup bar, not only the empty-ladder ones")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    sections = {s.strip() for s in args.sections.split(",") if s.strip()}
    unknown = sections - {"db", "sources"}
    if unknown or not sections:
        _die(f"--sections: unknown {', '.join(sorted(unknown)) or '(empty)'}; use db,sources")
    overrides = parse_param_overrides(args.params_json)
    symbols = [s.upper() for s in args.symbols]

    # URL first, before any other app.* import (app/database.py builds its
    # engine at import time).
    resolved = resolve_url()
    if isinstance(resolved, tuple):
        raw_url, source = resolved
    else:
        raw_url, source = resolved, "environment"
    kind, target = route_url(raw_url, args.allow_sqlite)
    if kind == "sqlite":
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{target.as_posix()}"
        print(f"reading SQLite file {target}")
    else:
        os.environ["DATABASE_URL"] = target.render_as_string(hide_password=False)
        print(f"reading {target.render_as_string(hide_password=True)}")
    print(f"DATABASE_URL supplied by {source}")

    # Lazy app.* imports, OUTSIDE the connect try, so an import error is never
    # reported as a connect error.
    from app.routers.stock_scan import _HISTORY_YEARS

    params, layers = build_params(overrides)
    today = date.today()
    start = today - timedelta(days=_HISTORY_YEARS * 365)

    if kind == "sqlite":
        rows = read_sqlite(target, symbols, start, today)
    else:
        rows = asyncio.run(read_postgres(target, symbols, start, today))

    if "db" in sections:
        print(f"\n##### §5 split / adjustment check, window {start}..{today} #####")
        print("pullback_ema Bearish params (as the stock-scan backtest merges them):")
        for k in sorted(params):
            print(f"  {k} = {params[k]!r}  ({layers.get(k, '?')})")
        verdicts = {s: report_symbol(s, rows[s], start, today, params, args.verbose)
                    for s in symbols}
        print("\n##### verdicts #####")
        for s, v in verdicts.items():
            print(f"{s}: {v}")

    if "sources" in sections:
        asyncio.run(report_sources(symbols, rows, today))
    return 0


if __name__ == "__main__":
    sys.exit(main())
