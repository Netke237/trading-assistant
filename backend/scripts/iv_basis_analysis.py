#!/usr/bin/env python3
"""Measure the IV figures a real scan actually produced, and show where the
SEEDED (unmeasured) thresholds would cut them.

WHY THIS EXISTS
---------------
Phase A (PHASE-A-NULL-IVRANK-2026-09-06) split one conflated field into two
quantities and gave each its own thresholds:

  * ABSOLUTE implied volatility 0-100, from Tradier's per-strike IV or the
    Black-Scholes inversion. This is the path almost every chain takes, and the
    iv_abs_* numbers are the ones the rule has in fact been applying all along.
  * A TRUE PERCENTILE, present only when IBKR or tastytrade answered. The
    iv_rank_* numbers were SEEDED from the absolute set so that nothing changed
    on the day the split shipped. Nobody has ever checked that a percentile
    deserves the same cut-offs as a level.

Three seeded numbers came out of that, and all three are open questions:

  1. horizons.<h>.vol.iv_rank_pass_max / iv_rank_caution_max  (scoring_rules.yaml)
  2. soft_rank.preferred_iv_rank_max, hard_reject.max_iv_rank (contract_rules.yaml)
  3. iv_abs_threshold, the spread picker's credit-vs-debit line (default 50)

This script is the measuring instrument. It does not decide anything and it
does not change anything: it reads the persisted scan blob, appends what it
found to a growing sample file, and prints where each threshold falls in that
sample.

Q7's stop-premium fractions (0.80 / 0.70 / 0.60) are deliberately NOT in scope.
Those are a CLOSED decision -- taken as proposed on Kenneth's explicit call,
with "revisit only if the observed flag rate looks wrong" as the stated trigger
(docs/superpowers/plans/2026-09-02-gate-basis-spec.md:39) -- and they gate a
Phase B basis that is not built yet. There is nothing for this script to read.

READ-ONLY
---------
It opens the database read-only (sqlite URI mode=ro), issues GETs only, calls
no broker, and writes exactly one file: its own sample store.

ONE SCAN IS ONE DAY OF ONE UNIVERSE
-----------------------------------
A single run measures one market session. That is not enough to move a
threshold on. `collect` therefore APPENDS to a JSONL store keyed on scan_id, so
several sessions -- ideally several vol regimes -- accumulate before anyone
edits a YAML number. `report` reads the whole store, not just today's run.

USAGE
-----
    cd backend
    .venv/bin/python scripts/iv_basis_analysis.py                 # collect + report
    .venv/bin/python scripts/iv_basis_analysis.py collect         # append only
    .venv/bin/python scripts/iv_basis_analysis.py report          # analyse the store
    .venv/bin/python scripts/iv_basis_analysis.py report --horizon Swing

Sources, in the order auto-detection tries them:
    --json PATH     a saved ScanResult, or {"result": ..., "request": ...}
    --sqlite PATH   the scan_sessions row id='current' (aiosqlite dev.db)
    --url BASE      a running backend; GETs /api/scan/last and /api/scan/last-run
                    (the latter supplies direction/horizon and the IV cut-offs
                    the run applied, paired to the result on scan_id)

Only PyYAML is needed beyond the stdlib (to read the two config files), so the
backend venv is enough -- no app import, no engine, no settings.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent

DEFAULT_STORE = ROOT / "docs" / "superpowers" / "measurements" / "iv-basis-samples.jsonl"
DEFAULT_URL = "http://127.0.0.1:8000"

BOLD, DIM, RED, GREEN, YELLOW, RESET = (
    "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"
)
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    BOLD = DIM = RED = GREEN = YELLOW = RESET = ""


# ── Config ───────────────────────────────────────────────────────────────────

def load_thresholds() -> dict:
    """The live threshold set, read from the YAML rather than restated here.

    Restating them would make this script drift the moment someone edits a
    number -- which is the one thing a measuring instrument must not do.
    """
    scoring = yaml.safe_load((BACKEND / "config" / "scoring_rules.yaml").read_text())
    contract = yaml.safe_load((BACKEND / "config" / "contract_rules.yaml").read_text())
    horizons = {}
    for key, block in (scoring.get("horizons") or {}).items():
        vol = (block or {}).get("vol") or {}
        horizons[key] = {
            "abs": {
                "compressed": vol.get("iv_abs_compressed_caution"),
                "pass_max": vol.get("iv_abs_pass_max"),
                "caution_max": vol.get("iv_abs_caution_max"),
            },
            "rank": {
                "compressed": vol.get("iv_rank_compressed_caution"),
                "pass_max": vol.get("iv_rank_pass_max"),
                "caution_max": vol.get("iv_rank_caution_max"),
            },
        }
    hr = contract.get("hard_reject") or {}
    sr = contract.get("soft_rank") or {}
    return {
        "horizons": horizons,
        "hard_reject": {"abs": hr.get("max_iv_abs"), "rank": hr.get("max_iv_rank")},
        "soft_rank": {
            "abs": sr.get("preferred_iv_abs_max"),
            "rank": sr.get("preferred_iv_rank_max"),
        },
    }


# ── Sources ──────────────────────────────────────────────────────────────────

def _sqlite_path_from_env() -> Path | None:
    """The dev.db an unset/sqlite DATABASE_URL points at, if it is on disk.

    Postgres deployments get no auto-detection: there is no stdlib driver, so
    the honest answer there is --url or --json, and read_auto says so.
    """
    url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
    if not url.startswith("sqlite"):
        return None
    tail = url.split("///", 1)[1] if "///" in url else ""
    if not tail:
        return None
    p = Path(tail)
    if not p.is_absolute():
        p = BACKEND / tail
    return p if p.exists() else None


def read_sqlite(path: Path) -> tuple[dict | None, dict | None, str]:
    con = None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = con.execute(
            "SELECT last_result_json, last_request_json FROM scan_sessions WHERE id = 'current'"
        ).fetchone()
    except sqlite3.Error as exc:
        # Covers a missing file, a missing scan_sessions table, and a path that
        # is not a database at all (pointing --sqlite at the JSONL store is an
        # easy slip and used to come out as a raw traceback).
        raise SystemExit(f"{RED}Cannot read scan_sessions from {path}: {exc}{RESET}")
    finally:
        if con is not None:
            con.close()
    if row is None:
        raise SystemExit(f"{RED}No scan_sessions row id='current' in {path}. Run a scan first.{RESET}")
    result = json.loads(row[0]) if row[0] else None
    request = json.loads(row[1]) if row[1] else None
    return result, request, f"sqlite {path}"


def read_url(base: str) -> tuple[dict | None, dict | None, str]:
    base = base.rstrip("/")

    def _get(path: str):
        try:
            with urllib.request.urlopen(f"{base}{path}", timeout=15) as r:
                body = r.read().decode()
        except urllib.error.URLError as exc:
            raise SystemExit(f"{RED}GET {base}{path} failed: {exc}{RESET}")
        return json.loads(body) if body.strip() else None

    # /scan/last-run carries what the ScanResult itself does not: the direction
    # and horizon of the run, and the two IV cut-offs it applied -- including
    # iv_abs_threshold, choose_primary's credit/debit line, which section 4
    # used to have to assume was the schema default.
    #
    # Two GETs are two instants, so the pair is only worth recording when both
    # saw the SAME scan. The endpoint returns the scan_id of the result it was
    # paired with (snapshotted under the router's state lock), so a scan that
    # lands between the calls is detectable rather than silently stamping one
    # run's threshold onto another run's rows. One re-read settles it; a second
    # mismatch is refused, because a wrong threshold here does not merely lose
    # a measurement, it produces a false one.
    result = _get("/api/scan/last")
    status = _get("/api/scan/last-run") or {}
    sid = status.get("scan_id")
    if sid is not None and (result or {}).get("scan_id") != sid:
        result = _get("/api/scan/last")
        if (result or {}).get("scan_id") != sid:
            raise SystemExit(
                f"{RED}A scan completed while collecting: /scan/last-run reports"
                f" {sid} and /scan/last does not agree, twice. Nothing was written."
                f" Re-run collect once the backend is idle.{RESET}"
            )
    request = {
        "direction": status.get("direction"),
        "horizon": status.get("horizon"),
        "universe": status.get("universe"),
    }
    if sid is not None:
        request["iv_abs_threshold"] = status.get("iv_abs_threshold")
        request["iv_rank_threshold"] = status.get("iv_rank_threshold")
        request["_threshold_source"] = (
            f"{base}/api/scan/last-run, paired on scan_id {sid}"
            if status.get("iv_abs_threshold") is not None else
            f"not recorded: /scan/last-run pairs scan_id {sid} but carries no"
            f" threshold (the backend holds a result whose request it lost)"
        )
    else:
        # No scan_id means either nothing to pair (no last result) or a backend
        # older than the field. Either way the thresholds are left absent --
        # None, which observations() records as "not recoverable", never 50.
        request["_threshold_source"] = (
            "not recorded: this backend's /scan/last-run carries no scan_id to"
            " pair on (upgrade it, or collect with --sqlite/--json)"
        )
    return result, request, f"url {base}"


def read_json(path: Path) -> tuple[dict | None, dict | None, str]:
    blob = json.loads(path.read_text())
    if isinstance(blob, dict) and "candidates" in blob:
        return blob, None, f"json {path}"
    if isinstance(blob, dict):
        return blob.get("result"), blob.get("request"), f"json {path}"
    raise SystemExit(f"{RED}{path} is not a ScanResult or a {{result, request}} envelope.{RESET}")


def read_auto(args) -> tuple[dict | None, dict | None, str]:
    if args.json:
        return read_json(Path(args.json))
    if args.sqlite:
        return read_sqlite(Path(args.sqlite))
    if args.url:
        return read_url(args.url)
    db = _sqlite_path_from_env()
    if db is not None:
        return read_sqlite(db)
    if not os.environ.get("DATABASE_URL", "sqlite").startswith("sqlite"):
        print(f"{DIM}DATABASE_URL is not sqlite -- there is no stdlib driver for it, so"
              f" falling back to {DEFAULT_URL}. Pass --url or --json to be explicit.{RESET}")
    return read_url(DEFAULT_URL)


# ── Extraction ───────────────────────────────────────────────────────────────

def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _figure_and_basis(detail: dict | None) -> tuple[float | None, str]:
    """The IV figure a *Detail block carries, and which quantity it is.

    The basis field is only trustworthy WHEN THERE IS A FIGURE. VolDetail
    declares `iv_basis: Literal[...] = "absolute"`, and stock_scorer._rule_vol's
    no-IV path returns `{"reason": "no_iv_data"}` with no basis at all -- so a
    row with no volatility reading arrives on the wire stamped "absolute" by the
    model default, not by a measurement. Counting those as absolute rows would
    invent a population. A null figure is reported as basis "none" here
    regardless of what the field says.
    """
    if not isinstance(detail, dict):
        return None, "none"
    fig = _num(detail.get("iv_rank"))
    if fig is None:
        return None, "none"
    basis = detail.get("iv_basis")
    return fig, basis if basis in ("rank", "absolute") else "none"


def observations(result: dict, request: dict | None, collected_at: str) -> list[dict]:
    """One record per candidate row (plus one per attached alternative).

    The STOCK-level figure is the one that matters for the spread line: scan.py
    computes a single ATM iv_rank/iv_basis per symbol and hands the SAME pair to
    both score_stock and _build_spreads, so stockBreakdown.volDetail holds
    exactly the number choose_primary saw. The CONTRACT-level figure is recorded
    beside it because the two are scored against different ceilings and a round
    may want to check that they agree.
    """
    req = request or {}
    iv_abs_thr = _num(req.get("iv_abs_threshold"))
    iv_rank_thr = _num(req.get("iv_rank_threshold"))
    meta = {
        "scan_id": result.get("scan_id"),
        "scan_timestamp": result.get("timestamp"),
        "schema_version": result.get("schema_version"),
        "collected_at": collected_at,
        "direction": req.get("direction"),
        "horizon": req.get("horizon"),
        "universe_size": len(req.get("universe") or []) or None,
        # None means "not recoverable from this source", NOT 50. Over HTTP that
        # is now only the case when /scan/last-run gives no scan_id to pair the
        # thresholds to the result; the report says so rather than quietly
        # measuring against a number this scan may not have used.
        "iv_abs_threshold": iv_abs_thr,
        "iv_rank_threshold": iv_rank_thr,
        "shortlist_truncated": bool(result.get("shortlist_truncated")),
        "original_count": result.get("original_count"),
    }

    rows: list[dict] = []
    for c in result.get("candidates") or []:
        stock_fig, stock_basis = _figure_and_basis(
            (c.get("stockBreakdown") or {}).get("volDetail")
        )
        cb = c.get("contractBreakdown") or {}
        con_fig, con_basis = _figure_and_basis(cb.get("ivDetail"))
        cd = c.get("contractDetails") or {}
        rows.append({
            **meta,
            "row": "primary",
            "symbol": c.get("symbol"),
            "price": _num(c.get("price")),
            "contract": c.get("contract"),
            "stock_iv": stock_fig,
            "stock_basis": stock_basis,
            "contract_iv": con_fig,
            "contract_basis": con_basis,
            "contract_preferred_max": _num((cb.get("ivDetail") or {}).get("preferred_max")),
            # The raw per-strike fields, kept separately: `iv` is always absolute
            # and `ivRank`/`ivPercentile` are always percentiles, whatever the
            # basis says, so they are a cross-check on the basis itself.
            "detail_iv_abs": _num(cd.get("iv")),
            "detail_iv_rank": _num(cd.get("ivRank")),
            "detail_iv_percentile": _num(cd.get("ivPercentile")),
            "spread_type": c.get("spreadType"),
            "net_debit_credit": _num(c.get("netDebitCredit")),
        })
        for a in c.get("alternatives") or []:
            a_fig, a_basis = _figure_and_basis(
                (a.get("contractBreakdown") or {}).get("ivDetail")
            )
            rows.append({
                **meta,
                "row": "alternative",
                "symbol": a.get("symbol") or c.get("symbol"),
                "price": _num(c.get("price")),
                "contract": f"{a.get('strike')}{a.get('right')} {a.get('expiry')}",
                # An alternative carries no stock-level figure of its own -- it is
                # the same underlying -- so the parent's is repeated for grouping
                # and excluded from the primary distribution by the `row` tag.
                "stock_iv": stock_fig,
                "stock_basis": stock_basis,
                "contract_iv": a_fig,
                "contract_basis": a_basis,
                "contract_preferred_max": _num(
                    ((a.get("contractBreakdown") or {}).get("ivDetail") or {}).get("preferred_max")
                ),
                "detail_iv_abs": _num(a.get("iv")),
                "detail_iv_rank": _num(a.get("ivRank")),
                "detail_iv_percentile": None,
                "spread_type": a.get("spreadType"),
                "net_debit_credit": _num(a.get("netDebitCredit")),
            })

    # Right-tail truncation. A symbol whose whole chain was thrown out reports
    # "contracts rejected: iv_too_high(7), delta_too_low_far_otm(3)" -- the only
    # visible trace of IV mass above the hard ceiling, since a rejected
    # candidate carries no figure. Counted as scan-level metadata, not as
    # observations: there is no number to put in the distribution.
    trunc_abs = trunc_rank = 0
    for r in result.get("rejected") or []:
        reason = r.get("reason") or ""
        if "iv_too_high" in reason:
            trunc_abs += 1
        if "iv_rank_too_high" in reason:
            trunc_rank += 1
    for row in rows:
        row["scan_rejected_iv_too_high"] = trunc_abs
        row["scan_rejected_iv_rank_too_high"] = trunc_rank
        # Names the shortlist cap trimmed are listed in `rejected` too (reason
        # prefix "Shortlist cap:", scan.py) but were not rejected; excluded so
        # this stays comparable with rows measured before they were listed.
        row["scan_rejected_total"] = sum(
            1 for r in (result.get("rejected") or [])
            if not str(r.get("reason", "")).startswith("Shortlist cap:")
        )
    return rows


# ── Store ────────────────────────────────────────────────────────────────────

def load_store(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"{YELLOW}Skipping malformed store line {n}{RESET}", file=sys.stderr)
    return out


def append_store(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


# ── Stats ────────────────────────────────────────────────────────────────────

def percentile(sorted_xs: list[float], q: float) -> float | None:
    if not sorted_xs:
        return None
    if len(sorted_xs) == 1:
        return sorted_xs[0]
    k = (len(sorted_xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_xs[int(k)]
    return sorted_xs[lo] * (hi - k) + sorted_xs[hi] * (k - lo)


def summary_line(xs: list[float]) -> str:
    s = sorted(xs)
    if not s:
        return "no rows"
    q = [percentile(s, p) for p in (0.05, 0.25, 0.50, 0.75, 0.95)]
    return (f"n={len(s)}  min {s[0]:.1f}  p5 {q[0]:.1f}  p25 {q[1]:.1f}  "
            f"med {q[2]:.1f}  p75 {q[3]:.1f}  p95 {q[4]:.1f}  max {s[-1]:.1f}")


def histogram(xs: list[float], width: float = 5.0, marks: dict[float, str] | None = None) -> list[str]:
    if not xs:
        return ["    (no rows)"]
    marks = marks or {}
    buckets: Counter = Counter()
    for x in xs:
        buckets[int(x // width)] += 1
    lo, hi = min(buckets), max(buckets)
    peak = max(buckets.values())
    out = []
    for b in range(lo, hi + 1):
        n = buckets.get(b, 0)
        edge_lo, edge_hi = b * width, (b + 1) * width
        bar = "#" * int(round(40 * n / peak)) if n else ""
        label = ", ".join(t for v, t in sorted(marks.items()) if edge_lo <= v < edge_hi)
        out.append(f"    {edge_lo:5.0f}-{edge_hi:<5.0f} {n:5d}  {bar}"
                   + (f"  {YELLOW}<- {label}{RESET}" if label else ""))
    return out


def cut(xs: list[float], thr: dict) -> str:
    """How a compressed/pass/caution threshold trio splits a sample."""
    if thr.get("pass_max") is None:
        return "        vol scoring SKIPPED at this horizon (pass_max is null)"
    n = len(xs)
    if not n:
        return "        no rows"
    comp = thr.get("compressed")
    pm, cm = thr["pass_max"], thr.get("caution_max")
    n_comp = sum(1 for x in xs if comp is not None and x < comp)
    n_pass = sum(1 for x in xs if x <= pm and not (comp is not None and x < comp))
    n_caut = sum(1 for x in xs if x > pm and (cm is not None and x <= cm))
    n_rej = n - n_comp - n_pass - n_caut
    def pc(k): return f"{k:5d} ({100.0 * k / n:5.1f}%)"
    # A null caution ceiling means "no caution band" -- REJECT straight above
    # pass_max, exactly as stock_scorer._rule_vol reads it (round 5 finding 8).
    caut_label = f"CAUTION   <={cm}" if cm is not None else "CAUTION   (no ceiling set)"
    rej_label = f"REJECT     >{cm}" if cm is not None else f"REJECT     >{pm}"
    return (f"        compressed <{comp}   {pc(n_comp)}\n"
            f"        PASS      <={pm}    {pc(n_pass)}\n"
            f"        {caut_label}    {pc(n_caut)}\n"
            f"        {rej_label}    {pc(n_rej)}")


# ── Report ───────────────────────────────────────────────────────────────────

def report(rows: list[dict], thresholds: dict, args) -> None:
    if args.horizon:
        rows = [r for r in rows if (r.get("horizon") or "").lower() == args.horizon.lower()]
    if args.direction:
        rows = [r for r in rows if (r.get("direction") or "").lower() == args.direction.lower()]

    # Every section below the header is about the STOCK-LEVEL figure -- one per
    # symbol per scan, and the one choose_primary and _rule_vol both saw. Runner-up
    # contracts repeat their parent's, so folding them in here would count a symbol
    # once per alternative it happened to have and quietly reweight the
    # distribution toward names with deep chains. They get their own section
    # instead, at the CONTRACT level, where they are a real extra observation.
    alt_rows = [r for r in rows if r.get("row") == "alternative"]
    rows = [r for r in rows if r.get("row") != "alternative"]

    if not rows:
        print(f"{YELLOW}No observations match. Run `collect` after a scan, or relax the filters.{RESET}")
        return

    scans = {r["scan_id"]: r for r in rows if r.get("scan_id")}
    stamps = sorted(r.get("scan_timestamp") or "" for r in rows)
    print(f"\n{BOLD}IV-BASIS MEASUREMENT{RESET}  {DIM}{args.store}{RESET}")
    print(f"  {len(rows)} candidate rows ({len(alt_rows)} runner-up contracts held back)"
          f" from {len(scans)} scan(s)   {stamps[0][:19]} .. {stamps[-1][:19]}")
    hz = Counter(r.get("horizon") or "?" for r in rows)
    dr = Counter(r.get("direction") or "?" for r in rows)
    print(f"  horizons: {dict(hz)}   directions: {dict(dr)}")
    if len(scans) < 3:
        print(f"  {YELLOW}One scan is one day of one universe. Accumulate several sessions "
              f"across different vol regimes before moving any number.{RESET}")

    # ── What the sample is not ───────────────────────────────────────────────
    print(f"\n{BOLD}0. WHAT THIS SAMPLE IS -- AND IS NOT{RESET}")
    print("  These are SURVIVORS, not a universe. Before a row reaches the blob it has")
    print("  passed the pre-screen, the stock-score gate, and contract validation -- so the")
    print("  distribution below is TRUNCATED on the right by the very ceilings it is being")
    print("  used to judge:")
    print(f"    hard_reject.max_iv_abs  = {thresholds['hard_reject']['abs']}"
          "   (whole chain thrown out above this)")
    print(f"    hard_reject.max_iv_rank = {thresholds['hard_reject']['rank']}")
    # Per-scan counts, so summing them means "across every scan in the sample"
    # rather than counting one scan's rejects once per row it contributed.
    by_scan = {r["scan_id"]: r for r in rows if r.get("scan_id")}
    t_abs = sum((r.get("scan_rejected_iv_too_high") or 0) for r in by_scan.values())
    t_rank = sum((r.get("scan_rejected_iv_rank_too_high") or 0) for r in by_scan.values())
    print(f"  Symbols whose entire chain was rejected with an IV component, summed over the"
          f" {len(by_scan)} scan(s): iv_too_high {t_abs}, iv_rank_too_high {t_rank}.")
    if any(r.get("shortlist_truncated") for r in rows):
        oc = max((r.get("original_count") or 0) for r in rows)
        print(f"  {YELLOW}At least one scan was SHORTLIST-TRUNCATED (original_count {oc}) -- the tail"
              f" of the ranking is missing from the sample too.{RESET}")

    # ── Basis mix ────────────────────────────────────────────────────────────
    print(f"\n{BOLD}1. BASIS MIX{RESET}  {DIM}(stock-level ATM figure -- the one choose_primary sees){RESET}")
    mix = Counter(r.get("stock_basis") or "none" for r in rows)
    for b in ("absolute", "rank", "none"):
        n = mix.get(b, 0)
        print(f"    {b:<9} {n:5d} ({100.0 * n / len(rows):5.1f}%)")
    cmix = Counter(r.get("contract_basis") or "none" for r in rows)
    print(f"  {DIM}contract-level: {dict(cmix)}{RESET}")
    disagree = [r for r in rows
                if r.get("stock_basis") in ("rank", "absolute")
                and r.get("contract_basis") in ("rank", "absolute")
                and r["stock_basis"] != r["contract_basis"]]
    if disagree:
        print(f"  {RED}{len(disagree)} row(s) where the stock and contract bases DISAGREE"
              f" -- e.g. {disagree[0]['symbol']}. Both are set from the same chain;"
              f" a disagreement is a defect, not a data condition.{RESET}")

    abs_rows = [r["stock_iv"] for r in rows if r.get("stock_basis") == "absolute" and r.get("stock_iv") is not None]
    rank_rows = [r["stock_iv"] for r in rows if r.get("stock_basis") == "rank" and r.get("stock_iv") is not None]

    # ── Absolute distribution ────────────────────────────────────────────────
    print(f"\n{BOLD}2. ABSOLUTE IV DISTRIBUTION{RESET}")
    print(f"    {summary_line(abs_rows)}")
    marks = {}
    for key, block in thresholds["horizons"].items():
        for name in ("pass_max", "caution_max"):
            v = block["abs"].get(name)
            if v is not None:
                marks.setdefault(float(v), f"{key}.{name}")
    if thresholds["soft_rank"]["abs"] is not None:
        marks.setdefault(float(thresholds["soft_rank"]["abs"]), "preferred_iv_abs_max")
    if thresholds["hard_reject"]["abs"] is not None:
        marks.setdefault(float(thresholds["hard_reject"]["abs"]), "max_iv_abs")
    for line in histogram(abs_rows, marks=marks):
        print(line)

    print(f"\n{BOLD}3. WHERE THE ABSOLUTE THRESHOLDS CUT{RESET}"
          f"  {DIM}(evidence-backed only in that they are what the rule already applied){RESET}")
    if len(hz) > 1:
        print(f"  {YELLOW}The sample mixes horizons {dict(hz)}. Each block below applies ONE"
              f" horizon's thresholds to ALL of them -- scope it with --horizon to judge"
              f" a horizon on its own rows.{RESET}")
    for key in sorted(thresholds["horizons"]):
        print(f"    horizons.{key}.vol (iv_abs_*)")
        print(cut(abs_rows, thresholds["horizons"][key]["abs"]))
    sr = thresholds["soft_rank"]["abs"]
    if sr is not None and abs_rows:
        n = sum(1 for x in abs_rows if x > sr)
        print(f"    soft_rank.preferred_iv_abs_max = {sr}: "
              f"{n} of {len(abs_rows)} ({100.0 * n / len(abs_rows):.1f}%) soft-penalised")

    # ── The spread line ──────────────────────────────────────────────────────
    # ONE decision, TWO thresholds, and which of them a row exercises is decided
    # by that row's BASIS -- never by a setting anyone picked
    # (PHASE-A-SPREAD-BASIS-2026-09-06). choose_primary reads
    #     threshold = rank_threshold if iv_basis == "rank" else abs_threshold
    # and scan.py sets the basis to "rank" whenever the ATM contract carried a
    # vendor ivRank. So a rank source's COVERAGE decides which line each symbol
    # measures, and one run can exercise a line thoroughly while leaving the
    # other with zero rows -- which is how the 2026-09-07 attempt came back
    # empty. The bearish rows are therefore split by basis BEFORE either line is
    # reported: an empty half is the finding, and it used to be INVISIBLE here.
    # With no absolute rows the whole split-and-sensitivity block simply did not
    # print, under a heading that named ivAbsThreshold, while the cross-check
    # below it still said "all N checkable rows match" in green.
    print(f"\n{BOLD}4. THE SPREAD PICKER'S CREDIT/DEBIT LINE{RESET}"
          f"  {DIM}(ivAbsThreshold / ivRankThreshold){RESET}")
    print("  choose_primary runs on BEARISH candidates only: at or above the line it sells")
    print("  premium (bear call, credit, assignment exposure), below it buys premium (bear")
    print("  put, debit, defined risk). These are the seeded numbers with real money on the")
    print("  other side of them.")
    bear = [r for r in rows if (r.get("direction") or "") == "Bearish"]
    if not bear:
        print(f"  {YELLOW}NO BEARISH ROWS IN THE SAMPLE. choose_primary never ran, so NEITHER line")
        print(f"  is measured. Run a Bearish scan -- what follows is arithmetic on the whole")
        print(f"  sample, a counterfactual, not evidence.{RESET}")

    pool = bear or rows
    bmix = Counter(r.get("stock_basis") or "none" for r in pool)
    print(f"\n  {BOLD}{'bearish' if bear else 'sample'} rows by basis{RESET}"
          f"  {DIM}-- a row measures ONE line and says NOTHING about the other{RESET}")
    for b in ("absolute", "rank", "none"):
        print(f"    {b:<9} {bmix.get(b, 0):5d}")
    if bmix.get("none"):
        print(f"    {DIM}basis 'none' means no vol reading at all: choose_primary returns"
              f" bear_put by deliberate default, judging no threshold.{RESET}")

    # Each line gets its own block, against its OWN recorded threshold. Reading
    # absolute rows against iv_rank_threshold (or the reverse) would measure a
    # number the picker never applied to them.
    for basis, thr_field, thr_label, empty_cause in (
        ("absolute", "iv_abs_threshold", "ivAbsThreshold",
         "Every bearish candidate carried a vendor percentile (IBKR or tastytrade\n"
         "     answered for all of them), so choose_primary took the RANK branch on\n"
         "     every one -- ivAbsThreshold decided nothing in this run."),
        ("rank", "iv_rank_threshold", "ivRankThreshold",
         "No bearish candidate carried a vendor percentile, so choose_primary took\n"
         "     the ABSOLUTE branch on every one -- ivRankThreshold decided nothing in\n"
         "     this run. Connect IBKR or tastytrade and collect again."),
    ):
        basis_rows = [r for r in pool if r.get("stock_basis") == basis]
        xs = [r["stock_iv"] for r in basis_rows if r.get("stock_iv") is not None]
        print(f"\n  {BOLD}{thr_label}{RESET}  {DIM}(rows on the {basis} basis){RESET}")
        if not xs:
            print(f"  {RED}   NO ROWS ON THIS BASIS -- {thr_label} IS UNMEASURED BY THIS SAMPLE.{RESET}")
            # State the CAUSE only when there were bearish rows to observe it on.
            # With none, the basis mix says nothing about which branch
            # choose_primary took, because it never ran -- and asserting a cause
            # off an empty pool is the same error the section exists to catch.
            print(f"     {empty_cause}" if bear else
                  "     There are no bearish rows at all, so this is not evidence about the\n"
                  "     basis mix a Bearish scan would produce -- choose_primary never ran.")
            continue

        thr_vals = {r[thr_field] for r in basis_rows if r.get(thr_field) is not None}
        if not thr_vals:
            print(f"  {YELLOW}   The threshold in force is NOT RECORDED for these rows. Rows collected")
            print(f"     over HTTP carry it only when /scan/last-run pairs a scan_id with the")
            print(f"     result (older backends do not, and pre-2026-09-07 rows predate the")
            print(f"     field). Falling back to the schema default of 50.0 -- re-collect against")
            print(f"     an upgraded backend, or from the DB, to measure the real line.{RESET}")
        in_force = sorted(thr_vals) if thr_vals else [50.0]
        print(f"     threshold(s) {'recorded' if thr_vals else 'ASSUMED (schema default)'}: {in_force}")
        if len(in_force) > 1:
            print(f"  {YELLOW}   More than one threshold is represented here; the split below uses"
                  f" {in_force[0]}. Filter with --horizon/--direction, or split the store.{RESET}")

        t0 = in_force[0]
        label = f"bearish {basis} rows" if bear else f"ALL {basis} rows (counterfactual)"
        credit = sum(1 for x in xs if x >= t0)
        print(f"\n     at {t0}: {label}, n={len(xs)}")
        print(f"       >= {t0}  -> bear_call (SELL premium)  {credit:5d} ({100.0 * credit / len(xs):5.1f}%)")
        print(f"       <  {t0}  -> bear_put  (BUY  premium)  {len(xs) - credit:5d}"
              f" ({100.0 * (len(xs) - credit) / len(xs):5.1f}%)")

        print(f"\n     SENSITIVITY -- how many rows change structure if the line moves:")
        for t in (30, 35, 40, 45, 50, 55, 60, 65, 70):
            c = sum(1 for x in xs if x >= t)
            flag = f"  {YELLOW}<- in force{RESET}" if float(t) == float(t0) else ""
            print(f"       {t:3d}: {c:5d} credit ({100.0 * c / len(xs):5.1f}%){flag}")
        near = [x for x in xs if abs(x - t0) <= 5]
        razor = [x for x in xs if t0 - 0.5 <= x < t0]
        print(f"\n       within +/-5 of the line: {len(near)} row(s) -- these flip on a 5-point edit")
        print(f"       in [{t0 - 0.5}, {t0}):        {len(razor)} row(s) -- these flip on a half-point edit")

    # Observed structure vs the structure the line implies. _build_spreads never
    # substitutes the other type: if the chosen one cannot be built it attaches
    # nothing. So whenever spreadType IS set it must equal choose_primary's pick,
    # and a mismatch is a defect rather than a market condition.
    typed = [r for r in bear if r.get("spread_type") in ("bear_call", "bear_put")
             and r.get("stock_iv") is not None and r.get("stock_basis") in ("rank", "absolute")]
    if typed:
        bad, checked = [], 0
        for r in typed:
            t = r.get("iv_abs_threshold") if r["stock_basis"] == "absolute" else r.get("iv_rank_threshold")
            if t is None:
                continue  # the threshold this scan ran with was not recorded
            checked += 1
            expect = "bear_call" if r["stock_iv"] >= t else "bear_put"
            if expect != r["spread_type"]:
                bad.append((r["symbol"], r["stock_iv"], r["stock_basis"], t, r["spread_type"], expect))
        st = Counter(r["spread_type"] for r in typed)
        print(f"\n    structure actually attached: {dict(st)} over {len(typed)} bearish row(s)")
        if not checked:
            print(f"    {YELLOW}none of them could be CHECKED against choose_primary: no row records"
                  f" the threshold its scan ran with (see the note above){RESET}")
        elif bad:
            print(f"    {RED}{len(bad)} row(s) carry a structure the threshold does not imply:{RESET}")
            for s in bad[:5]:
                print(f"      {s[0]}: iv {s[1]} ({s[2]}) vs {s[3]} -> attached {s[4]}, expected {s[5]}")
        else:
            # A green line here says the picker AGREED WITH ITSELF on the rows it
            # judged -- it says nothing about whether either threshold sits in a
            # sensible place, and nothing at all about a basis with no rows.
            print(f"    {GREEN}all {checked} checkable row(s) match choose_primary on the recorded figure{RESET}")
    n_unbuilt = sum(1 for r in bear if not r.get("spread_type"))
    if bear:
        print(f"    {n_unbuilt} bearish row(s) got NO spread (chain too thin, or the credit/debit"
              f" filter rejected it) -- absent, never substituted with the other type")

    # ── Percentile distribution ──────────────────────────────────────────────
    print(f"\n{BOLD}5. PERCENTILE DISTRIBUTION{RESET}  {DIM}(the seeded iv_rank_* numbers){RESET}")
    if not rank_rows:
        print(f"  {RED}NO PERCENTILE ROWS IN THIS SAMPLE.{RESET}")
        print("  A true percentile enters only from IBKR or tastytrade. With neither connected")
        print("  every candidate resolves to the absolute basis, so iv_rank_pass_max /")
        print("  iv_rank_caution_max / preferred_iv_rank_max / max_iv_rank CANNOT BE MEASURED")
        print("  from this data at all -- and a scan will look perfectly healthy while")
        print("  answering nothing about them. Connect a rank source and collect again.")
    else:
        print(f"    {summary_line(rank_rows)}")
        rmarks = {}
        for key, block in thresholds["horizons"].items():
            for name in ("pass_max", "caution_max"):
                v = block["rank"].get(name)
                if v is not None:
                    rmarks.setdefault(float(v), f"{key}.{name}")
        for line in histogram(rank_rows, marks=rmarks):
            print(line)
        print(f"\n  {BOLD}WHERE THE SEEDED PERCENTILE THRESHOLDS CUT{RESET}")
        for key in sorted(thresholds["horizons"]):
            print(f"    horizons.{key}.vol (iv_rank_*)")
            print(cut(rank_rows, thresholds["horizons"][key]["rank"]))
        srr = thresholds["soft_rank"]["rank"]
        if srr is not None:
            n = sum(1 for x in rank_rows if x > srr)
            print(f"    soft_rank.preferred_iv_rank_max = {srr}: "
                  f"{n} of {len(rank_rows)} ({100.0 * n / len(rank_rows):.1f}%) soft-penalised")
        print(f"\n  {DIM}Compare against section 2: the seeds assume a percentile deserves the same"
              f" cut-offs as a level. These two distributions are what tests that.{RESET}")

    # ── Contract-level view ─────────────────────────────────────────────────
    if args.include_alternatives:
        print(f"\n{BOLD}6. CONTRACT-LEVEL DISTRIBUTION (runner-ups folded in){RESET}")
        print(f"  {DIM}Every scored strike, not one figure per symbol. CORRELATED: several rows here"
              f"\n  come off the same chain, so this is a wider sample of the SMILE, not a wider"
              f"\n  sample of the market. Do not read its percentiles as population percentiles.{RESET}")
        for basis, ceiling in (("absolute", thresholds["soft_rank"]["abs"]),
                               ("rank", thresholds["soft_rank"]["rank"])):
            xs = [r["contract_iv"] for r in rows + alt_rows
                  if r.get("contract_basis") == basis and r.get("contract_iv") is not None]
            print(f"    {basis}: {summary_line(xs)}")
            if xs and ceiling is not None:
                n = sum(1 for x in xs if x > ceiling)
                print(f"      above the soft ceiling {ceiling}: {n} ({100.0 * n / len(xs):.1f}%)")

    print(f"\n{DIM}Nothing here changes a threshold. Moving one is a YAML edit and a decision"
          f" record -- take it only on several sessions of this report.{RESET}\n")


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="?", default="both", choices=["collect", "report", "both"])
    ap.add_argument("--store", default=str(DEFAULT_STORE), help="JSONL sample store (appended to)")
    ap.add_argument("--json", help="read a saved ScanResult / {result, request} envelope")
    ap.add_argument("--sqlite", help="read scan_sessions id='current' from this sqlite file")
    ap.add_argument("--url", help=f"read from a running backend (default {DEFAULT_URL})")
    ap.add_argument("--force", action="store_true", help="collect a scan_id already in the store")
    ap.add_argument("--horizon", help="report only rows from this horizon")
    ap.add_argument("--direction", help="report only rows from this direction")
    ap.add_argument("--include-alternatives", action="store_true",
                    help="fold runner-up contracts into the distribution (same chains -- correlated)")
    args = ap.parse_args()
    store = Path(args.store)
    args.store = store
    rc = 0

    if args.command in ("collect", "both"):
        result, request, src = read_auto(args)
        # A blob with no schema_version predates PHASE-A-NULL-IVRANK-2026-09-06:
        # it holds raw implied volatility under `ivRank`, the name of a
        # percentile, and NOTHING on the record says which quantity any figure
        # is. routers/scan.py's restore_from_db refuses to serve one for exactly
        # this reason; collecting it would put mislabelled numbers into the
        # percentile sample and there is no way to tell them apart afterwards.
        if result and result.get("schema_version") is None:
            print(f"{RED}Refusing this blob: it was written before the IV basis split"
                  f" (no schema_version), so its figures have no recoverable basis."
                  f" Run a scan to repopulate.{RESET}")
            # Nothing is appended, but an existing store is still worth reporting,
            # so `both` carries on and only the exit code records the refusal.
            rc = 1
            result = None
        if not result or not result.get("candidates"):
            if rc == 0:
                print(f"{YELLOW}No scan result with candidates at {src}. Run a scan first.{RESET}")
                rc = 1
        else:
            existing = load_store(store)
            seen = {r.get("scan_id") for r in existing}
            scan_id = result.get("scan_id")
            if scan_id in seen and not args.force:
                print(f"{DIM}scan {scan_id} is already in the store -- nothing appended"
                      f" (--force to add it anyway).{RESET}")
            else:
                rows = observations(result, request, datetime.now(timezone.utc).isoformat())
                append_store(store, rows)
                print(f"{GREEN}Appended {len(rows)} observation(s) from scan {scan_id}{RESET}"
                      f" {DIM}({src}) -> {store}{RESET}")
                # Say at COLLECT time whether the credit/debit line got
                # recorded. The report only discovers it rows later, by which
                # point the sample is already written and the run that could
                # have been re-collected is gone.
                thr_src = (request or {}).get("_threshold_source")
                if thr_src:
                    tone = YELLOW if thr_src.startswith("not recorded") else DIM
                    print(f"  {tone}iv thresholds: {thr_src}{RESET}")

    if args.command in ("report", "both"):
        report(load_store(store), load_thresholds(), args)
    return rc


if __name__ == "__main__":
    sys.exit(main())
