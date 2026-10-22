#!/usr/bin/env python3
"""NO-LIVE-QUOTE Step 0: record RAW Tradier option-chain rows, unfiltered.

WHY THIS EXISTS
---------------
Plan docs/superpowers/plans/2026-09-30-no-live-quote-plan.md rests on a code
comment nobody has observed: "Outside market hours Tradier returns bid=0,
ask=0" (both chain builders in app/data/market.py). This script looks.

It calls Tradier GET /v1/markets/options/chains (greeks=true) DIRECTLY. It
does not go through /api/contracts: the app's chain builder folds bid/ask into
price/spread, fabricates spread = 0.0 when ask is 0, and drops rows where both
ask and last are 0, so the app's output cannot show the case being measured.
Every row Tradier returns is written, calls and puts, including both-zero rows.

PRODUCTION BASE ONLY
--------------------
The base defaults to https://api.tradier.com. The sandbox is 15 minutes
delayed (market.py `_is_sandbox_base`, TRADIER_SANDBOX_FEED_LAG_SECONDS), which
would distort every quote-age number, so a sandbox base is refused unless
--allow-sandbox is passed (and the run is then marked sandbox in its output).
TRADIER_BASE_URL is deliberately NOT read: an app .env pointing at the sandbox
must not silently change what this measures.

TOKEN
-----
Read from the env var named by --token-env (default TRADIER_API_TOKEN), or,
with --prompt-token, typed at a no-echo prompt (keeps it out of shell history).
The prompt is opt-in, never automatic: on Windows isatty() is True for NUL, so
an automatic prompt would hang an unattended run. It is never written to any
output file.

OUTPUT (backend/scripts/out/ is gitignored)
------
    backend/scripts/out/tradier_chain_raw/<UTC stamp>_<phase>/
        rows.csv       one line per chain row, the measured fields
        rows.json      run metadata + every row, including Tradier's raw row
        summary.json   the counts and quote-age distributions printed at the end

READ-ONLY: GETs only (clock, expirations, chains). Nothing in the app is
imported or touched.

USAGE (from backend/)
-----
    .venv/Scripts/python.exe scripts/tradier_chain_raw_sample.py --label in-session
    .venv/Scripts/python.exe scripts/tradier_chain_raw_sample.py --symbols AAPL XOM --expiries-per-symbol 1
See scripts/README_tradier_chain_raw_sample.md for the four-run schedule.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

PRODUCTION_BASE = "https://api.tradier.com"
EASTERN = ZoneInfo("America/New_York")

# Liquid names plus a few thinner ones, so both chain shapes are sampled.
DEFAULT_SYMBOLS = ["AAPL", "MSFT", "XOM", "LYB", "SRE", "CPRT", "TSCO"]

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "out" / "tradier_chain_raw"

# The measured fields, in CSV column order after the identity columns.
QUOTE_FIELDS = (
    "bid", "ask", "last", "close", "prevclose", "volume", "open_interest",
    "bidsize", "asksize", "bid_date", "ask_date", "trade_date",
)
DATE_FIELDS = ("bid_date", "ask_date", "trade_date")

CSV_COLUMNS = (
    ("capture_utc", "capture_et", "base_url", "symbol", "option_symbol", "expiry",
     "dte", "strike", "option_type")
    + QUOTE_FIELDS
    + ("greeks_updated_at",)
    + tuple(f"{f}_age_s" for f in DATE_FIELDS)
    + ("two_sided", "app_fabricates_zero_spread", "app_drops_row")
)

# Quote-age histogram edges, in seconds (upper bound exclusive).
AGE_BUCKETS = (
    ("<1m", 60),
    ("1-15m", 15 * 60),
    ("15-60m", 60 * 60),
    ("1-6h", 6 * 3600),
    ("6-24h", 24 * 3600),
    ("1-3d", 3 * 86400),
    (">=3d", None),
)


# Module-level clock so tests can pin the capture time.
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_sandbox_base(base: str) -> bool:
    """Same rule as app.data.market._is_sandbox_base (pinned by a parity test)."""
    return "sandbox.tradier.com" in (base or "")


def session_phase(now_utc: datetime) -> str:
    """Clock-only label: weekend / pre-market / in-session / after-close (ET).

    Holidays are not known here; the Tradier /markets/clock state recorded in
    the run metadata is the authoritative reading.
    """
    et = now_utc.astimezone(EASTERN)
    if et.weekday() >= 5:
        return "weekend"
    minutes = et.hour * 60 + et.minute
    if minutes < 9 * 60 + 30:
        return "pre-market"
    if minutes < 16 * 60:
        return "in-session"
    return "after-close"


def _num(v: Any) -> float:
    """The app's reading of a quote field: `float(c.get(x) or 0)`."""
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _age_seconds(epoch_ms: Any, now_utc: datetime) -> Optional[float]:
    """Seconds between a Tradier epoch-millisecond stamp and capture; None if absent/0."""
    try:
        ms = float(epoch_ms)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return round(now_utc.timestamp() - ms / 1000.0, 3)


def pick_expiries(dates: list[str], today: date, count: int, min_dte: int, target_dte: int) -> list[str]:
    """The nearest expiry at/after `min_dte`, then the one closest to `target_dte`.

    Deduplicated, at most `count` (1 or 2), in date order.
    """
    eligible = []
    for d in dates:
        try:
            dte = (date.fromisoformat(d) - today).days
        except ValueError:
            continue
        if dte >= min_dte:
            eligible.append((dte, d))
    if not eligible:
        return []
    eligible.sort()
    picks = [eligible[0][1]]
    if count >= 2:
        nearest_target = min(eligible, key=lambda p: (abs(p[0] - target_dte), p[0]))[1]
        if nearest_target not in picks:
            picks.append(nearest_target)
    return sorted(picks)


def _as_list(v: Any) -> list:
    """Tradier collapses a one-element list to a bare dict/str."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


class TradierClient:
    def __init__(self, base: str, token: str, http: Optional[httpx.Client] = None):
        self.base = base.rstrip("/")
        self._http = http or httpx.Client(timeout=20)
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        r = self._http.get(f"{self.base}{path}", headers=self._headers, params=params or {})
        r.raise_for_status()
        return r.json() or {}

    def clock(self) -> dict:
        return self.get("/v1/markets/clock").get("clock") or {}

    def expirations(self, symbol: str) -> list[str]:
        exp = self.get("/v1/markets/options/expirations",
                       {"symbol": symbol, "includeAllRoots": "true"}).get("expirations")
        if not exp:
            return []
        return [str(d) for d in _as_list(exp.get("date"))]

    def chain(self, symbol: str, expiry: str) -> list[dict]:
        opts = self.get("/v1/markets/options/chains",
                        {"symbol": symbol, "expiration": expiry, "greeks": "true"}).get("options")
        if not opts:
            return []
        return [o for o in _as_list(opts.get("option")) if isinstance(o, dict)]


def build_row(raw: dict, symbol: str, expiry: str, today: date, now_utc: datetime, base: str) -> dict:
    bid, ask, last = _num(raw.get("bid")), _num(raw.get("ask")), _num(raw.get("last"))
    try:
        dte: Optional[int] = (date.fromisoformat(expiry) - today).days
    except ValueError:
        dte = None
    greeks = raw.get("greeks") if isinstance(raw.get("greeks"), dict) else {}
    row = {
        "capture_utc": now_utc.isoformat(timespec="seconds"),
        "capture_et": now_utc.astimezone(EASTERN).isoformat(timespec="seconds"),
        "base_url": base,
        "symbol": symbol,
        "option_symbol": raw.get("symbol"),
        "expiry": raw.get("expiration_date") or expiry,
        "dte": dte,
        "strike": raw.get("strike"),
        "option_type": raw.get("option_type"),
    }
    for f in QUOTE_FIELDS:
        row[f] = raw.get(f)  # raw value, None kept as None
    row["greeks_updated_at"] = greeks.get("updated_at")
    for f in DATE_FIELDS:
        row[f"{f}_age_s"] = _age_seconds(raw.get(f), now_utc)
    # What the app's chain builder (market.py) does with this row today.
    row["two_sided"] = bid > 0 and ask > 0
    row["app_fabricates_zero_spread"] = ask <= 0 and last > 0
    row["app_drops_row"] = ask <= 0 and last <= 0
    row["raw"] = raw
    return row


def _age_stats(ages: list[Optional[float]]) -> dict:
    present = sorted(a for a in ages if a is not None)
    hist = {label: 0 for label, _ in AGE_BUCKETS}
    for a in present:
        for label, upper in AGE_BUCKETS:
            if upper is None or a < upper:
                hist[label] += 1
                break
    out: dict = {"n": len(ages), "missing_or_zero": len(ages) - len(present), "buckets": hist}
    if present:
        q = statistics.quantiles(present, n=4, method="inclusive") if len(present) > 1 else [present[0]] * 3
        out.update(min_s=present[0], p25_s=q[0], median_s=q[1], p75_s=q[2], max_s=present[-1])
    return out


def _counts(rows: list[dict]) -> dict:
    def n(pred) -> int:
        return sum(1 for r in rows if pred(r))
    b = lambda r: _num(r["bid"])  # noqa: E731
    a = lambda r: _num(r["ask"])  # noqa: E731
    l = lambda r: _num(r["last"])  # noqa: E731,E741
    return {
        "rows": len(rows),
        "bid_0": n(lambda r: b(r) <= 0),
        "ask_0": n(lambda r: a(r) <= 0),
        "both_0": n(lambda r: b(r) <= 0 and a(r) <= 0),
        "ask_0_last_gt_0": n(lambda r: a(r) <= 0 and l(r) > 0),
        "bid_0_ask_gt_0": n(lambda r: b(r) <= 0 and a(r) > 0),
        "two_sided": n(lambda r: b(r) > 0 and a(r) > 0),
        "crossed_ask_lt_bid": n(lambda r: a(r) > 0 and b(r) > 0 and a(r) < b(r)),
        "both_0_last_0": n(lambda r: b(r) <= 0 and a(r) <= 0 and l(r) <= 0),
        "bid_null": n(lambda r: r["bid"] is None),
        "ask_null": n(lambda r: r["ask"] is None),
    }


def summarize(rows: list[dict], meta: dict) -> dict:
    two_sided = [r for r in rows if r["two_sided"]]
    ages_all = {f: _age_stats([r[f"{f}_age_s"] for r in rows]) for f in DATE_FIELDS}
    ages_two_sided = {f: _age_stats([r[f"{f}_age_s"] for r in two_sided]) for f in ("bid_date", "ask_date")}
    per_symbol = {}
    for sym in sorted({r["symbol"] for r in rows}):
        per_symbol[sym] = _counts([r for r in rows if r["symbol"] == sym])
    return {
        "meta": meta,
        "counts": _counts(rows),
        "per_symbol": per_symbol,
        "quote_age_all_rows": ages_all,
        "quote_age_two_sided_rows": ages_two_sided,
    }


def _fmt_age(s: Optional[float]) -> str:
    if s is None:
        return "-"
    if s < 120:
        return f"{s:.0f}s"
    if s < 7200:
        return f"{s / 60:.1f}m"
    if s < 172800:
        return f"{s / 3600:.1f}h"
    return f"{s / 86400:.1f}d"


def render_summary(summary: dict) -> str:
    m, c = summary["meta"], summary["counts"]
    lines = [
        f"capture {m['capture_utc']} UTC / {m['capture_et']} ET  phase={m['session_phase']}"
        + (f"  label={m['label']}" if m.get("label") else ""),
        f"base {m['base_url']}" + ("  ** SANDBOX: 15-min delayed, quote ages are distorted **" if m["sandbox"] else ""),
        f"tradier clock: {m.get('tradier_clock') or m.get('tradier_clock_error')}",
        "",
        "counts (bid/ask/last read as the app does: missing -> 0)",
    ]
    for k, v in c.items():
        lines.append(f"  {k:<22}{v}")
    lines += ["", "per symbol: rows  bid_0  ask_0  both_0  ask_0&last>0  two_sided"]
    for sym, pc in summary["per_symbol"].items():
        lines.append(f"  {sym:<8}{pc['rows']:>5}{pc['bid_0']:>7}{pc['ask_0']:>7}{pc['both_0']:>8}"
                     f"{pc['ask_0_last_gt_0']:>14}{pc['two_sided']:>11}")
    for title, block in (("quote age, all rows", summary["quote_age_all_rows"]),
                         ("quote age, two-sided rows only", summary["quote_age_two_sided_rows"])):
        lines += ["", f"{title}: field  n  missing  min  p25  median  p75  max | buckets"]
        for f, st in block.items():
            bk = " ".join(f"{k}:{v}" for k, v in st["buckets"].items())
            lines.append(f"  {f:<11}{st['n']:>5}{st['missing_or_zero']:>8}  "
                         f"{_fmt_age(st.get('min_s'))} {_fmt_age(st.get('p25_s'))} "
                         f"{_fmt_age(st.get('median_s'))} {_fmt_age(st.get('p75_s'))} "
                         f"{_fmt_age(st.get('max_s'))} | {bk}")
    if m.get("errors"):
        lines += ["", "errors:"] + [f"  {e}" for e in m["errors"]]
    return "\n".join(lines)


def _parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    p.add_argument("--expiries-per-symbol", type=int, choices=(1, 2), default=2)
    p.add_argument("--min-dte", type=int, default=5,
                   help="first expiry is the nearest at/after this many days (default 5)")
    p.add_argument("--target-dte", type=int, default=30,
                   help="second expiry is the one closest to this DTE (default 30)")
    p.add_argument("--base-url", default=PRODUCTION_BASE)
    p.add_argument("--allow-sandbox", action="store_true",
                   help="permit a sandbox base (15-min delayed; quote ages are distorted)")
    p.add_argument("--token-env", default="TRADIER_API_TOKEN",
                   help="name of the env var holding the PRODUCTION token (default TRADIER_API_TOKEN)")
    p.add_argument("--prompt-token", action="store_true",
                   help="ask for the token at a no-echo prompt instead of reading the env var")
    p.add_argument("--label", default="", help="free-text run label, e.g. pre-market")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return p.parse_args(argv)


def _token(env_name: str, prompt: bool) -> str:
    if prompt:
        return getpass.getpass("Tradier PRODUCTION token (not echoed): ").strip()
    return os.environ.get(env_name, "").strip()


def main(argv: Optional[list[str]] = None, http: Optional[httpx.Client] = None) -> int:
    args = _parse_args(argv)
    base = args.base_url.rstrip("/")
    sandbox = is_sandbox_base(base)
    if sandbox and not args.allow_sandbox:
        print(f"REFUSED: {base} is the Tradier sandbox (15-min delayed quotes). "
              "This measurement needs the production base. Pass --allow-sandbox to override.",
              file=sys.stderr)
        return 2
    token = _token(args.token_env, args.prompt_token)
    if not token:
        print(f"REFUSED: no token. Set the env var {args.token_env} to a Tradier production token, "
              "or pass --prompt-token.",
              file=sys.stderr)
        return 2

    now = _utcnow()
    today_et = now.astimezone(EASTERN).date()
    phase = session_phase(now)
    client = TradierClient(base, token, http)
    errors: list[str] = []

    clock: Optional[dict] = None
    clock_error = None
    try:
        clock = client.clock()
    except Exception as e:  # recorded, not fatal: the chain sample is the point
        clock_error = f"{type(e).__name__}: {e}"

    rows: list[dict] = []
    expiries_used: dict[str, list[str]] = {}
    for sym in args.symbols:
        sym = sym.upper()
        try:
            picks = pick_expiries(client.expirations(sym), today_et, args.expiries_per_symbol,
                                  args.min_dte, args.target_dte)
        except Exception as e:
            errors.append(f"{sym} expirations: {type(e).__name__}: {e}")
            continue
        if not picks:
            errors.append(f"{sym}: no expiry at/after {args.min_dte} DTE")
            continue
        expiries_used[sym] = picks
        for exp in picks:
            try:
                chain = client.chain(sym, exp)
            except Exception as e:
                errors.append(f"{sym} {exp} chain: {type(e).__name__}: {e}")
                continue
            if not chain:
                errors.append(f"{sym} {exp}: empty chain")
            rows.extend(build_row(raw, sym, exp, today_et, now, base) for raw in chain)

    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.out_dir / f"{stamp}_{phase}"
    run_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "capture_utc": now.isoformat(timespec="seconds"),
        "capture_et": now.astimezone(EASTERN).isoformat(timespec="seconds"),
        "session_phase": phase,
        "label": args.label,
        "base_url": base,
        "sandbox": sandbox,
        "tradier_clock": clock,
        "tradier_clock_error": clock_error,
        "symbols": [s.upper() for s in args.symbols],
        "expiries": expiries_used,
        "errors": errors,
        "script": "backend/scripts/tradier_chain_raw_sample.py",
    }
    with open(run_dir / "rows.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(run_dir / "rows.json", "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "rows": rows}, fh, indent=1, default=str)
    summary = summarize(rows, meta)
    with open(run_dir / "summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, default=str)

    print(render_summary(summary))
    print(f"\nwrote {run_dir}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
