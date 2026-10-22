"""HESTON-RR-OVERPRICING probe, T1: measurements M1, M2 and M3.

Plan: docs/superpowers/plans/2026-10-22-heston-rr-overpricing-plan.md (sections 2, 4 T1, 5, 6).
Tests: backend/tests/test_heston_rr_overpricing_probe.py.

Run (Python 3.11, from backend/):
    python scripts/heston_rr_overpricing_probe.py            # M1, M2, M3
    python scripts/heston_rr_overpricing_probe.py --only m1  # one measurement

READ-ONLY EVIDENCE. Nothing under backend/app, backend/config or frontend is
changed, no database is opened, and no network is used: `main()` installs a
socket guard that raises on any connection attempt, M3's chain requests go to an
httpx MockTransport that serves the committed Tradier captures, and every
enrichment that could reach a vendor (IBKR, tastytrade, yfinance IV) is patched
to a no-op for the replay.

Outputs (JSON for machines, Markdown for people), all under
docs/superpowers/measurements/2026-10-22-heston-rr-overpricing/:
    m1.json m1.md  -- reach and exit gap on the committed real scans
    m2.json m2.md  -- the 96-cell synthetic sweep (calls and puts as separate chains)
    m3.json m3.md  -- the five committed Tradier captures, replayed through the
                      shipped chain builder
    provenance.json -- git SHA, interpreter and library versions, SHA-256 of
                       every input file
Every number in them is computed here. The only wall-clock quantity is the
calibration time, labelled single-thread and relative: it is not an
abandonment rate (see plan section 2, M4).

T2 extends this file with an `--options` mode (M4). The pieces it needs are
module-level on purpose: `heston_chain`, `calibrate`, `exit_gaps`, `m2_rows`,
`M2_REGIMES`, `replay_chain`, `parity_spot`, `shipped_grids`.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import math
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
import warnings
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional
from unittest import mock

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

from app.data import governor as app_governor  # noqa: E402
from app.data import market  # noqa: E402
from app.models import heston as heston_mod  # noqa: E402
from app.models import heston_cache as hc  # noqa: E402
from app.models.black_scholes import bs_price  # noqa: E402
from app.models.heston import HestonParams, heston_price_detail  # noqa: E402
from app.routers import scan as scan_mod  # noqa: E402
from app.scoring.reprice_horizon import display_reprice_years  # noqa: E402
from app.scoring.reward_risk import _default_reprice_years, estimate_rr  # noqa: E402
from app.scoring.stop_cost import compute_stop_cost  # noqa: E402
from app.scoring.trade_plan import build_trade_plan  # noqa: E402
from app.services.config_loader import merge_reward_risk_overrides  # noqa: E402

# ── Constants (plan section 2) ───────────────────────────────────────────────

R = 0.05                     # the rate scan.py passes to calibrate_heston
SPOT = 100.0                 # M2 spot
M2_DTES = (30, 45, 60, 90, 180, 365)
M2_WIDTHS = (15, 25, 40, 60)
M2_REGIMES = {               # name -> (ATM vol, skew); iv(k) = atm + skew*k + 0.5*k^2
    "atm20_mild": (0.20, -0.10),
    "atm20_steep": (0.20, -0.30),
    "atm35_mild": (0.35, -0.10),
    "atm35_steep": (0.35, -0.30),
}
M2_LOG_MONEYNESS = 0.40      # strikes evenly spaced over +-40% log-moneyness
M2_CURVATURE = 0.5
MOVES = (0.05, 0.10, 0.15)   # stock moves for the exit gaps (puts: negative)
RIGHTS = ("C", "P")
PRE_D5_PREMIUM_STOP_PCT = 0.60   # the risk leg of the stored (schema v2) R/R
RECOVERY_TOL = 0.01
TARGET_TOL = 0.015
UNRELIABLE_SHARE = 0.10

OUT_DIR = REPO / "docs" / "superpowers" / "measurements" / "2026-10-22-heston-rr-overpricing"
SCANS_DIR = REPO / "docs" / "superpowers" / "measurements" / "scans"
PROTOCOL_DIR = REPO / "docs" / "superpowers" / "measurements" / "protocol-requests"
CAPTURE_DIR = BACKEND / "scripts" / "out" / "tradier_chain_raw"
REPLAY_BASE = "https://tradier-capture-replay.invalid"

_SHIPPED_SOURCES = (
    "backend/app/routers/scan.py",
    "backend/app/models/heston.py",
    "backend/app/models/heston_cache.py",
    "backend/app/scoring/reward_risk.py",
    "backend/app/scoring/trade_plan.py",
    "backend/app/scoring/reprice_horizon.py",
    "backend/app/scoring/stop_cost.py",
    "backend/app/data/market.py",
    "backend/app/scoring/contract_validator.py",
    "backend/config/contract_rules.yaml",
    "backend/config/risk_rules.yaml",
)


def step7_band(rr: Optional[float]) -> Optional[str]:
    """The Step 7 context-rail grade for a full-premium R/R
    (frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx)."""
    if rr is None or not math.isfinite(rr):
        return None
    return "PASS" if rr >= 2.0 else "CAUTION" if rr >= 1.5 else "REJECT"


def _finite(x) -> Optional[float]:
    return float(x) if x is not None and math.isfinite(float(x)) else None


def _spread(values: list[float]) -> Optional[dict]:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if not vals:
        return None
    return {"n": len(vals), "min": min(vals), "median": statistics.median(vals), "max": max(vals)}


# ── No network ───────────────────────────────────────────────────────────────

class NetworkForbidden(RuntimeError):
    pass


@contextlib.contextmanager
def forbid_network():
    """Any outbound connection raises. A probe that tries the network is a bug."""
    def _refuse(*_a, **_k):
        raise NetworkForbidden("network access attempted by the HESTON-RR-OVERPRICING probe")
    with mock.patch.object(socket.socket, "connect", _refuse), \
            mock.patch.object(socket.socket, "connect_ex", _refuse), \
            mock.patch.object(socket, "create_connection", _refuse), \
            mock.patch.object(socket, "getaddrinfo", _refuse):
        yield


# ── The heston_chain rule (scan.py `_process_symbol`) ────────────────────────

def calibration_delta_band(contract_overrides: Optional[dict] = None) -> tuple[float, float]:
    """scan.py's calibration band: the request's selection band widened by
    `_HESTON_DELTA_SAFETY_MARGIN`, both read from the APP at call time."""
    ov = contract_overrides or {}
    dmin, dmax = scan_mod.hard_reject_delta_band()
    cmin = float(ov.get("min_delta", dmin))
    cmax = float(ov.get("max_delta", dmax))
    margin = scan_mod._HESTON_DELTA_SAFETY_MARGIN
    return max(0.0, round(cmin - margin, 6)), min(1.0, round(cmax + margin, 6))


def selection_delta_band(contract_overrides: Optional[dict] = None) -> tuple[float, float]:
    """The selectable ("in-band") delta band: the hard-reject band the contract
    validator applies, without the calibration margin."""
    ov = contract_overrides or {}
    dmin, dmax = scan_mod.hard_reject_delta_band()
    return float(ov.get("min_delta", dmin)), float(ov.get("max_delta", dmax))


def heston_chain(chain: list[dict], contract_overrides: Optional[dict] = None) -> list[dict]:
    """Re-implementation of scan.py's `heston_chain` list (its `_heston_delta_ok`
    is nested in `_process_symbol` and cannot be imported). Pinned against
    scan.py's source block by the T1 test."""
    lo, hi = calibration_delta_band(contract_overrides)

    def _delta_ok(entry: dict) -> bool:
        d = abs(float(entry.get("delta") or 0))
        if d == 0.0:
            return True          # greeks missing: fail open, as scan.py does
        return lo <= d <= hi

    return [
        {
            "strike": float(c.get("strike", 0)),
            "expiry_years": c.get("dte", 30) / 365.0,
            "mid_price": float(c.get("price", 0)),
            "is_call": c.get("right", "C") == "C",
        }
        for c in chain
        if float(c.get("price", 0)) > 0 and _delta_ok(c)
    ]


# ── Calibration (shipped code, cache cleared every time) ─────────────────────

def shipped_grids() -> dict[str, dict[str, list[float]]]:
    """The grids `_run_calibration` searches, read from its SOURCE (they are
    locals, so they cannot be imported). Returns {"default": ..., "full": ...}."""
    fn = getattr(hc._run_calibration, "__wrapped__", hc._run_calibration)
    tree = ast.parse(_dedent(inspect.getsource(fn)))
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "_USE_FULL_GRID")

    def _grab(stmts):
        out = {}
        for s in stmts:
            if isinstance(s, ast.Assign) and isinstance(s.targets[0], ast.Name):
                out[s.targets[0].id.replace("_grid", "")] = [float(v) for v in ast.literal_eval(s.value)]
        return out
    return {"full": _grab(node.body), "default": _grab(node.orelse)}


def _dedent(src: str) -> str:
    import textwrap
    return textwrap.dedent(src)


def calibrate(chain: list[dict], S: float) -> tuple[dict, object]:
    """Shipped `calibrate_heston(chain, S, r=0.05)`, after clearing the
    `_run_calibration` lru_cache (keyed on the chain, not the grid, so a
    repeated chain would otherwise return a stale result in ~0 s)."""
    hc._run_calibration.cache_clear()
    t0 = time.perf_counter()
    res = heston_mod.calibrate_heston(chain, S, R)
    secs = time.perf_counter() - t0
    accepted = res.method == "heston_grid"
    rec: dict = {
        "strikes": len(chain),
        "method": res.method,
        "accepted": accepted,
        "rel_rmse": _finite(res.rmse),
        "params": asdict(res.params),
        "calibration_seconds_single_thread_relative": round(secs, 4),
    }
    if accepted:
        p = res.params
        grids = shipped_grids()["default"]
        sides = {}
        for name in ("kappa", "theta", "sigma_v", "rho"):
            g, v = grids[name], getattr(p, name)
            sides[name] = "min" if v == min(g) else "max" if v == max(g) else "interior"
        rec["boundary_sides"] = sides
        rec["boundary_hit_count"] = sum(1 for s in sides.values() if s != "interior")
        rec["boundary_hits_shipped_diagnostic"] = hc._boundary_hits(p, {"v0": [p.v0], **grids})
        rec["feller_ratio"] = p.sigma_v ** 2 / (2.0 * p.kappa * p.theta)
    return rec, res


# ── Exit gaps for an accepted fit ────────────────────────────────────────────

def protocol_holds() -> dict[str, dict]:
    """Swing and Position preset/hold from the committed options protocol requests."""
    out: dict[str, dict] = {}
    for f in sorted(PROTOCOL_DIR.glob("options-*.request.json")):
        req = json.loads(f.read_text())
        key = req["horizon_preset"]
        val = {"preset": key, "hold_min": req["hold_min_days"], "hold_max": req["hold_max_days"],
               "files": [str(f.relative_to(REPO))]}
        if key in out:
            if (out[key]["hold_min"], out[key]["hold_max"]) != (val["hold_min"], val["hold_max"]):
                raise SystemExit(f"protocol requests disagree on {key} hold window")
            out[key]["files"] += val["files"]
        else:
            out[key] = val
    return out


def horizons() -> dict[str, Callable[[float], Optional[float]]]:
    """name -> f(dte) -> reprice_years (None = estimate_rr's half-expiry default)."""
    holds = protocol_holds()
    sw, po = holds["Swing"], holds["Position"]
    return {
        "card_swing": lambda dte: display_reprice_years(sw["preset"], sw["hold_min"], sw["hold_max"], float(dte)),
        "card_position": lambda dte: display_reprice_years(po["preset"], po["hold_min"], po["hold_max"], float(dte)),
        "alternatives_half_expiry": lambda dte: None,
    }


def exit_gaps(params: HestonParams, rows: list[dict], S: float, is_call: bool,
              contract_overrides: Optional[dict] = None) -> dict:
    """Heston / mid now for every in-band strike and the scored proxy, and the
    scored proxy's exit premium Heston / BS-IV at the three moves, both through
    the shipped `estimate_rr` (full-premium basis, premium = mid)."""
    lo, hi = selection_delta_band(contract_overrides)
    inband = [r for r in rows if float(r.get("price", 0)) > 0
              and lo <= abs(float(r.get("delta") or 0)) <= hi]
    per_strike = []
    for r in inband:
        T = r["dte"] / 365.0
        d = heston_price_detail(S, float(r["strike"]), T, R, params, is_call)
        per_strike.append({"strike": float(r["strike"]), "delta": float(r["delta"]), "mid": float(r["price"]),
                           "heston_now": d.price, "heston_fell_back": d.fell_back,
                           "heston_over_mid": d.price / float(r["price"])})
    out: dict = {"selection_band": [lo, hi], "in_band": per_strike, "scored_proxy": None}
    if not inband:
        return out
    proxy = min(inband, key=lambda r: (abs(abs(float(r["delta"])) - 0.5), float(r["strike"])))
    K, mid, dte = float(proxy["strike"]), float(proxy["price"]), proxy["dte"]
    T = dte / 365.0
    ps = next(p for p in per_strike if p["strike"] == K)
    exits = []
    for hname, hfun in horizons().items():
        ry = hfun(dte)
        ry_used = ry if ry is not None else _default_reprice_years(T)
        for m in MOVES:
            target = S * (1 + m) if is_call else S * (1 - m)
            common = dict(stock_price=S, target_price=target, invalidation_price=S, strike=K,
                          expiry_years=T, current_premium=mid, is_call=is_call, r=R, reprice_years=ry)
            bs = estimate_rr(heston_params=None, **common)
            hs = estimate_rr(heston_params=params, **common)
            exits.append({
                "horizon": hname, "reprice_years": ry_used, "reprice_days": ry_used * 365.0,
                "move": m if is_call else -m, "target": target,
                "bs_exit": bs.estimated_exit_premium, "bs_model": bs.model_used,
                "heston_exit": hs.estimated_exit_premium, "heston_model": hs.model_used,
                "heston_over_bs": (hs.estimated_exit_premium / bs.estimated_exit_premium
                                   if bs.estimated_exit_premium > 0 else None),
                "bs_rr": bs.rr_ratio, "heston_rr": hs.rr_ratio, "risk_basis": hs.risk_basis,
                "bs_band": step7_band(bs.rr_ratio), "heston_band": step7_band(hs.rr_ratio),
                "band_changes": step7_band(bs.rr_ratio) != step7_band(hs.rr_ratio),
            })
    out["scored_proxy"] = {"strike": K, "delta": float(proxy["delta"]), "mid": mid, "dte": dte,
                           "heston_now": ps["heston_now"], "heston_over_mid": ps["heston_over_mid"],
                           "exits": exits}
    return out


# ── M2: the synthetic sweep ──────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def m2_rows(dte: int, width: int, atm: float, skew: float, right: str) -> list[dict]:
    """One synthetic chain, one right: BS mids at iv(k) rounded to $0.01 and
    delta rounded to 4 dp, as market.py rounds them."""
    T = dte / 365.0
    is_call = right == "C"
    rows = []
    for i in range(width):
        k = -M2_LOG_MONEYNESS + 2 * M2_LOG_MONEYNESS * i / (width - 1)
        K = SPOT * math.exp(k)
        iv = atm + skew * k + M2_CURVATURE * k * k
        price = bs_price(SPOT, K, T, R, iv, is_call)
        d1 = (math.log(SPOT / K) + (R + 0.5 * iv * iv) * T) / (iv * math.sqrt(T))
        delta = _norm_cdf(d1) if is_call else _norm_cdf(d1) - 1.0
        rows.append({"strike": K, "dte": dte, "price": round(price, 2), "delta": round(delta, 4),
                     "right": right, "iv": iv})
    return rows


def run_m2(cells: Optional[list[tuple[int, int, str]]] = None) -> dict:
    if cells is None:
        cells = [(d, w, g) for d in M2_DTES for w in M2_WIDTHS for g in M2_REGIMES]
    fits = []
    for dte, width, regime in cells:
        atm, skew = M2_REGIMES[regime]
        for right in RIGHTS:
            rows = m2_rows(dte, width, atm, skew, right)
            chain = heston_chain(rows)
            rec, res = calibrate(chain, SPOT)
            entry = {"dte": dte, "width": width, "regime": regime, "atm": atm, "skew": skew,
                     "right": right, "chain_rows": len(rows), **rec}
            if rec["accepted"]:
                entry["gaps"] = exit_gaps(res.params, rows, SPOT, right == "C")
            fits.append(entry)
    return {"cells": len(cells), "fits": fits}


# ── M3: replay of the committed Tradier captures ─────────────────────────────

def load_capture(path: Path) -> dict:
    d = json.loads((Path(path) / "rows.json").read_text())
    d["dir"] = str(Path(path).relative_to(REPO)) if Path(path).is_absolute() else str(path)
    return d


def capture_et_date(capture: dict) -> date:
    return datetime.fromisoformat(capture["meta"]["capture_et"]).date()


class ReplayRequestError(RuntimeError):
    pass


class CaptureTransport:
    """Serves one capture's expirations and raw chain records; raises on anything else."""

    def __init__(self, capture: dict):
        self.expirations = {s: list(v) for s, v in capture["meta"]["expiries"].items()}
        self.chains: dict[tuple[str, str], list[dict]] = {}
        for r in capture["rows"]:
            self.chains.setdefault((r["symbol"], r["expiry"]), []).append(r["raw"])
        self.requests: list[str] = []
        self.raised: list[str] = []
        self.anomalies: list[str] = []

    def _fail(self, why: str):
        self.raised.append(why)
        raise ReplayRequestError(why)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, dict(request.url.params)
        self.requests.append(f"{path}?{sorted(params.items())}")
        if path.endswith("/v1/markets/options/expirations"):
            sym = params.get("symbol")
            if sym not in self.expirations:
                self._fail(f"expirations for unknown symbol {sym!r}")
            return httpx.Response(200, json={"expirations": {"date": self.expirations[sym]}})
        if path.endswith("/v1/markets/options/chains"):
            key = (params.get("symbol"), params.get("expiration"))
            if key not in self.chains:
                self._fail(f"chain for unknown symbol/expiry {key!r}")
            return httpx.Response(200, json={"options": {"option": self.chains[key]}})
        self._fail(f"unexpected request {path!r}")


class _PassThroughGovernor:
    """Rate limiting only; it changes no data. Replaced so 300 replayed calls do
    not sleep on Tradier's 2/s bucket."""

    async def call(self, provider, coro_factory, retries=2):
        return await coro_factory()

    async def call_overdraft(self, provider, coro_factory):
        return await coro_factory()


def _replay_date_class(d: date):
    class ReplayDate(date):
        @classmethod
        def today(cls):
            return cls(d.year, d.month, d.day)
    return ReplayDate


@contextlib.contextmanager
def replay_patches(capture_date: date):
    import app.data.ibkr as ibkr_mod
    import app.data.tastytrade_iv as tasty_mod
    with mock.patch.object(market, "date", _replay_date_class(capture_date)), \
            mock.patch.object(market, "_tradier_base", lambda: REPLAY_BASE), \
            mock.patch.object(market, "_headers", lambda token=None: {"Accept": "application/json"}), \
            mock.patch.object(app_governor, "get_governor", lambda: _PassThroughGovernor()), \
            mock.patch.object(ibkr_mod, "fetch_iv_metrics_ibkr", lambda *a, **k: None), \
            mock.patch.object(tasty_mod, "fetch_iv_metrics_tastytrade", lambda *a, **k: None), \
            mock.patch.object(market, "_yf_iv_for_chain", lambda *a, **k: {}):
        yield


async def _fetch(transport: CaptureTransport, symbol: str, expiry: str, right: str) -> list[dict]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        return await market.fetch_option_chain_async(client, symbol, expiry=expiry, option_type=right)


def replay_chain(capture: dict, symbol: str, expiry: str, right: str) -> tuple[list[dict], CaptureTransport]:
    """Rows exactly as the shipped `market.fetch_option_chain_async` builds them
    from the capture: date pinned to the capture's ET date, expirations cache
    cleared, mock transport serving only what the capture holds."""
    transport = CaptureTransport(capture)
    with replay_patches(capture_et_date(capture)):
        market._expirations_cache.clear()
        rows = asyncio.run(_fetch(transport, symbol, expiry, right))
    # The shipped fetch silently substitutes another listed expiry when the
    # requested one is not listed; that must never pass unnoticed.
    wrong = sorted({r.get("expiry") for r in rows if r.get("expiry") != expiry})
    if wrong:
        transport.anomalies.append(f"requested expiry {expiry}, shipped fetch returned {wrong}")
    return rows, transport


def parity_spot(capture_rows: list[dict], symbol: str, r: float = R) -> Optional[dict]:
    """Put-call-parity spot, S = C_mid - P_mid + K*exp(-rT), at the pair nearest
    the money that has a two-sided call AND a two-sided put (bid > 0, ask > 0)
    on the same strike and expiry. Spot is unknown, so "nearest the money" is
    the smallest |C_mid - P_mid| across the symbol's expiries (ties: shorter
    dte, then lower strike). Mids are rounded as market.py rounds them. No
    dividend term. None when no such pair exists."""
    calls, puts = {}, {}
    for row in capture_rows:
        if row["symbol"] != symbol:
            continue
        bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
        if not (bid > 0 and ask > 0):
            continue
        key = (row["expiry"], float(row["strike"]))
        mid = round((bid + ask) / 2, 2)
        (calls if row["option_type"] == "call" else puts)[key] = (mid, row["dte"])
    best = None
    for key in calls.keys() & puts.keys():
        (c_mid, dte), (p_mid, _) = calls[key], puts[key]
        rank = (abs(c_mid - p_mid), dte, key[1])
        if best is None or rank < best[0]:
            best = (rank, key, c_mid, p_mid, dte)
    if best is None:
        return None
    _, (expiry, K), c_mid, p_mid, dte = best
    T = dte / 365.0
    return {"spot": c_mid - p_mid + K * math.exp(-r * T), "strike": K, "expiry": expiry, "dte": dte,
            "call_mid": c_mid, "put_mid": p_mid, "r": r}


def run_m3() -> dict:
    captures = []
    for cdir in sorted(p for p in CAPTURE_DIR.iterdir() if (p / "rows.json").exists()):
        cap = load_capture(cdir)
        cdate = capture_et_date(cap)
        out = {"capture": cap["dir"], "capture_et": cap["meta"]["capture_et"], "et_date": cdate.isoformat(),
               "session_phase": cap["meta"].get("session_phase"), "expiries": cap["meta"]["expiries"],
               "spots": {}, "skipped_symbols": [], "chains": [], "listed": []}
        for symbol, expiries in cap["meta"]["expiries"].items():
            spot = parity_spot(cap["rows"], symbol)
            out["spots"][symbol] = spot
            if spot is None:
                out["skipped_symbols"].append({"symbol": symbol,
                                               "reason": "no strike with a two-sided call and put on one expiry"})
            for expiry in expiries:
                for right in RIGHTS:
                    rows, transport = replay_chain(cap, symbol, expiry, right)
                    ch = {"symbol": symbol, "expiry": expiry, "right": right, "rows": len(rows),
                          "dte": rows[0]["dte"] if rows else None,
                          "replay_requests": len(transport.requests), "replay_raised": transport.raised,
                          "replay_anomalies": transport.anomalies}
                    if transport.anomalies:
                        out["listed"].append({**ch, "reason": "; ".join(transport.anomalies)})
                        out["chains"].append({**ch, "status": "anomaly"})
                        continue
                    if not rows:
                        reason = ("shipped fetch returned 0 rows"
                                  + (f"; mock raised: {transport.raised}" if transport.raised else ""))
                        out["listed"].append({**ch, "reason": reason})
                        out["chains"].append({**ch, "status": "zero_rows"})
                        continue
                    hchain = heston_chain(rows)
                    ch["heston_chain_rows"] = len(hchain)
                    ch["delta_zero_rows_kept"] = sum(1 for r in rows if float(r.get("delta") or 0) == 0.0
                                                     and float(r.get("price", 0)) > 0)
                    kind = "call" if right == "C" else "put"
                    ch["one_sided_capture_rows"] = sum(
                        1 for r in cap["rows"] if r["symbol"] == symbol and r["expiry"] == expiry
                        and r["option_type"] == kind and not float(r["bid"] or 0) > 0 and float(r["ask"] or 0) > 0)
                    if len(hchain) < 3:
                        out["listed"].append({**ch, "reason": f"{len(hchain)} rows after the heston_chain filter (< 3)"})
                        out["chains"].append({**ch, "status": "thin"})
                        continue
                    if spot is None:
                        out["chains"].append({**ch, "status": "no_spot"})
                        continue
                    rec, res = calibrate(hchain, spot["spot"])
                    entry = {**ch, "status": "calibrated", "spot": spot["spot"], **rec}
                    if rec["accepted"]:
                        entry["gaps"] = exit_gaps(res.params, rows, spot["spot"], right == "C")
                    out["chains"].append(entry)
        captures.append(out)
    return {"captures": captures}


# ── M1: the committed real scans ─────────────────────────────────────────────

def _options_scan_files() -> list[Path]:
    out = []
    for f in sorted(SCANS_DIR.glob("*/*.result.json")):
        name = f.name
        if name.startswith("stocks-") or "-stocks-" in name:
            continue
        out.append(f)
    return out


def _plan_for(card: dict, request: dict):
    cd, ex = card["contractDetails"], card["exit"]
    # The contract id carries the formatted strike; contractDetails.strike was
    # int()-truncated at the scans' freeze commit (61a03e49).
    strike = float(card["contract"].split("|")[1])
    mid = float(cd["mid"])
    fs = ex.get("finalStop") or {}
    stop_pct = card.get("stopCostPct")
    inputs = {
        "direction": card["direction"], "stock_price": float(card["price"]), "strike": strike,
        "strike_contractDetails": cd["strike"], "dte": int(cd["dte"]), "premium": mid,
        "entry_limit": (card.get("entry") or {}).get("limit"),
        "target_price": float(ex["target"]), "final_stop_price": float(fs.get("price", ex["invalidation"])),
        "stop_cost_fraction": (stop_pct / 100.0) if stop_pct is not None else None,
        "horizon_preset": request.get("horizon_preset"), "hold_min": request.get("hold_min_days"),
        "hold_max": request.get("hold_max_days"),
    }
    overrides = request.get("overrides") or {}
    plan = build_trade_plan(
        direction=inputs["direction"], stock_price=inputs["stock_price"], strike=strike, dte=inputs["dte"],
        premium=mid, entry_bid=mid, entry_ask=mid, entry_mid=mid,
        rr_cfg=merge_reward_risk_overrides(overrides), final_stop_price=inputs["final_stop_price"],
        target_price=inputs["target_price"], stop_cost_fraction=inputs["stop_cost_fraction"],
        heston_params=None, horizon_preset=inputs["horizon_preset"],
        hold_min=inputs["hold_min"], hold_max=inputs["hold_max"],
    )
    return inputs, plan


def recover_card(card: dict, request: dict) -> dict:
    """Re-run shipped `build_trade_plan(heston_params=None)` from the card's
    stored inputs and compare each ladder level's estimatedOptionPrice."""
    rec, _ = _recover(card, request)
    return rec


def _method(v) -> str:
    return getattr(v, "value", v)


def _recover(card: dict, request: dict):
    inputs, plan = _plan_for(card, request)
    stored = card["exit"]["targets"]
    levels, differing = [], []
    for i, (s, p) in enumerate(zip(stored, plan.targets), start=1):
        diff = round(p.estimatedOptionPrice - s["estimatedOptionPrice"], 6)
        lvl = {"level": f"T{i}", "stored_target": s["targetPrice"], "recovered_target": p.targetPrice,
               "stored_est": s["estimatedOptionPrice"], "recovered_est": p.estimatedOptionPrice,
               "diff": diff, "stored_label": s["pricingMethod"], "recovered_label": _method(p.pricingMethod),
               "stored_rr_contribution_pre_d5": s["rrContribution"],
               "recovered_rr_contribution_full_premium": p.rrContribution}
        levels.append(lvl)
        # Ladder stock prices are informational, not the criterion: the freeze
        # code built T2/T3 from the UNROUNDED T1 target, shipped code from the
        # cents-rounded one, so T2/T3 may differ by up to 1.5 cents.
        if abs(s["targetPrice"] - p.targetPrice) > TARGET_TOL + 1e-9:
            differing.append(f"T{i}.targetPrice")
        if s["pricingMethod"] != "Heston repriced" and abs(diff) > RECOVERY_TOL + 1e-9:
            differing.append(f"T{i}.estimatedOptionPrice")
    if len(stored) != len(plan.targets):
        differing.append("ladder length")
    rec = {"inputs": inputs, "levels": levels, "differing_fields": differing,
           "reproducible": not differing,
           "recovered_headline_rr_full_premium": plan.rr_ratio, "recovered_rr_model": plan.rr_model,
           "recovered_reprice_years": plan.reprice_years, "recovered_risk_basis": plan.rr_risk_basis}
    return rec, plan


def _pre_d5_basis_ok(card: dict) -> bool:
    """Stored rrContribution == (est - premium) / (0.60 * premium), rounded."""
    prem = float(card["contractDetails"]["mid"])
    for t in card["exit"]["targets"]:
        if abs(round((t["estimatedOptionPrice"] - prem) / (PRE_D5_PREMIUM_STOP_PCT * prem), 2)
               - t["rrContribution"]) > 0.0101:
            return False
    return True


def _alt_counterfactual(card: dict, alt: dict, request: dict, plan) -> dict:
    """The shipped non-Heston exit premium for an alternative, as scan.py calls
    `estimate_rr` for alternatives (half-expiry default horizon), plus the
    stored exit premium back-solved from the stored schema-v2 rrRatio:
    exit = mid * (1 + 0.60 * rrRatio); rrRatio is rounded to 2 dp, so the
    stored exit is known to +-mid*0.60*0.005."""
    is_call = card["direction"] == "Bullish"
    price = float(card["price"])
    strike, dte, mid = float(alt["strike"]), int(alt["dte"]), float(alt["mid"])
    fs = card["exit"].get("finalStop") or {}
    alt_stop_fraction = None
    if fs.get("source") == "final_stop":
        cost = compute_stop_cost(stop_price=round(float(fs["price"]), 2), stock_price=price, strike=strike,
                                 dte=dte, premium=round(mid, 2), is_call=is_call, iv_pct=None,
                                 horizon_preset=request.get("horizon_preset"))
        if cost is not None:
            alt_stop_fraction = cost.fraction
    rr_cfg = merge_reward_risk_overrides(request.get("overrides") or {})
    bs = estimate_rr(stock_price=price, target_price=plan.target_price_raw,
                     invalidation_price=plan.invalidation_price_raw, strike=strike, expiry_years=dte / 365.0,
                     current_premium=mid, is_call=is_call, heston_params=None,
                     premium_stop_pct=rr_cfg["premium_stop_pct"], risk_fraction=alt_stop_fraction)
    rr_s = float(alt["rrRatio"])
    pct = PRE_D5_PREMIUM_STOP_PCT
    exit_mid = mid * (1 + pct * rr_s)
    exit_lo, exit_hi = mid * (1 + pct * (rr_s - 0.005)), mid * (1 + pct * (rr_s + 0.005))
    return {
        "symbol": alt["symbol"], "strike": strike, "dte": dte, "mid": mid, "stored_label": alt["rrModel"],
        "stored_rr_pre_d5": rr_s, "stored_exit_backsolved": exit_mid,
        "stored_exit_interval": [exit_lo, exit_hi],
        "bs_exit": bs.estimated_exit_premium, "bs_model": bs.model_used, "bs_rr_full_premium": bs.rr_ratio,
        "reprice_years": _default_reprice_years(dte / 365.0), "alt_stop_fraction": alt_stop_fraction,
        "stored_exit_matches_bs": exit_lo - RECOVERY_TOL - 1e-9 <= bs.estimated_exit_premium
        <= exit_hi + RECOVERY_TOL + 1e-9,
    }


def run_m1() -> dict:
    scans, heston_cards, heston_alts, non_heston_alt_checks, recoveries = [], [], [], [], []
    for f in _options_scan_files():
        res = json.loads(f.read_text())
        req_path = f.with_name(f.name.replace(".result.json", ".request.json"))
        req = json.loads(req_path.read_text())
        cards = res.get("candidates") or []
        entry = {"file": str(f.relative_to(REPO)), "request": str(req_path.relative_to(REPO)),
                 "scan_id": res.get("scan_id"), "schema_version": res.get("schema_version"),
                 "date_dir": f.parent.name, "horizon": req.get("horizon_preset"),
                 "direction": req.get("direction"),
                 "cards": len(cards), "cards_by_label": {}, "alternatives": 0, "alternatives_by_label": {},
                 "stored_exit_rrRiskBasis_present": any("rrRiskBasis" in (c.get("exit") or {}) for c in cards)}
        for c in cards:
            lab = c.get("rrModel")
            entry["cards_by_label"][lab] = entry["cards_by_label"].get(lab, 0) + 1
            for a in c.get("alternatives") or []:
                entry["alternatives"] += 1
                al = a.get("rrModel")
                entry["alternatives_by_label"][al] = entry["alternatives_by_label"].get(al, 0) + 1
            rec, plan = _recover(c, req)
            is_heston = lab == "Heston repriced"
            base = {"scan": entry["file"], "date_dir": entry["date_dir"], "horizon": entry["horizon"],
                    "direction": entry["direction"], "symbol": c["symbol"], "contract": c["contract"],
                    "label": lab, "pre_d5_basis_confirmed_by_ladder": _pre_d5_basis_ok(c)}
            if not is_heston:
                recoveries.append({**base, "reproducible": rec["reproducible"],
                                   "differing_fields": rec["differing_fields"],
                                   "max_abs_diff": max(abs(lv["diff"]) for lv in rec["levels"]),
                                   "levels": rec["levels"]})
            else:
                prem = float(c["contractDetails"]["mid"])
                levels = []
                for lv in rec["levels"]:
                    h_rr = (lv["stored_est"] - prem) / prem
                    b_rr = lv["recovered_rr_contribution_full_premium"]
                    levels.append({
                        "level": lv["level"], "target": lv["stored_target"],
                        "target_reproduced": abs(lv["stored_target"] - lv["recovered_target"]) <= TARGET_TOL + 1e-9,
                        "stored_label": lv["stored_label"], "stored_heston_exit": lv["stored_est"],
                        "bs_exit": lv["recovered_est"], "bs_label": lv["recovered_label"],
                        "heston_over_bs": lv["stored_est"] / lv["recovered_est"],
                        "heston_rr_full_premium": round(h_rr, 2), "bs_rr_full_premium": b_rr,
                        "heston_band": step7_band(round(h_rr, 2)), "bs_band": step7_band(b_rr),
                    })
                head_h = levels[0]["heston_rr_full_premium"]
                heston_cards.append({**base, "premium": prem, "dte": c["contractDetails"]["dte"],
                                     "reprice_years": rec["recovered_reprice_years"],
                                     "stored_rrRatio_pre_d5_not_compared": c.get("rrRatio"),
                                     "headline": {"heston_rr_full_premium": head_h,
                                                  "bs_rr_full_premium": rec["recovered_headline_rr_full_premium"],
                                                  "bs_model": rec["recovered_rr_model"],
                                                  "heston_band": step7_band(head_h),
                                                  "bs_band": step7_band(rec["recovered_headline_rr_full_premium"]),
                                                  "band_changes": step7_band(head_h) != step7_band(
                                                      rec["recovered_headline_rr_full_premium"])},
                                     "levels": levels,
                                     "inputs_reproduced": not rec["differing_fields"]})
            for a in c.get("alternatives") or []:
                cf = _alt_counterfactual(c, a, req, plan)
                cf.update({"scan": entry["file"], "date_dir": entry["date_dir"], "horizon": entry["horizon"],
                           "direction": entry["direction"], "card_symbol": c["symbol"], "card_label": lab})
                if a.get("rrModel") == "Heston repriced":
                    h_rr = PRE_D5_PREMIUM_STOP_PCT * cf["stored_rr_pre_d5"]
                    cf.update({
                        "heston_over_bs": cf["stored_exit_backsolved"] / cf["bs_exit"],
                        "heston_over_bs_interval": [cf["stored_exit_interval"][0] / cf["bs_exit"],
                                                    cf["stored_exit_interval"][1] / cf["bs_exit"]],
                        "heston_rr_full_premium": round(h_rr, 2),
                        "heston_rr_full_premium_interval": [round(h_rr - PRE_D5_PREMIUM_STOP_PCT * 0.005, 4),
                                                            round(h_rr + PRE_D5_PREMIUM_STOP_PCT * 0.005, 4)],
                        "heston_band": step7_band(round(h_rr, 2)), "bs_band": step7_band(cf["bs_rr_full_premium"]),
                    })
                    cf["band_changes"] = cf["heston_band"] != cf["bs_band"]
                    heston_alts.append(cf)
                else:
                    non_heston_alt_checks.append(cf)
        scans.append(entry)

    def _agg(key):
        out: dict = {}
        for s in scans:
            k = f"{s['horizon']}/{s['direction']}" if key == "hd" else s["date_dir"]
            a = out.setdefault(k, {"cards": 0, "cards_heston": 0, "alternatives": 0, "alternatives_heston": 0})
            a["cards"] += s["cards"]
            a["cards_heston"] += s["cards_by_label"].get("Heston repriced", 0)
            a["alternatives"] += s["alternatives"]
            a["alternatives_heston"] += s["alternatives_by_label"].get("Heston repriced", 0)
        return out

    n_rec = len(recoveries)
    failed = [r for r in recoveries if not r["reproducible"]]
    alt_fail = [a for a in non_heston_alt_checks if not a["stored_exit_matches_bs"]]
    totals = {
        "scans": len(scans),
        "cards": sum(s["cards"] for s in scans),
        "cards_heston": len(heston_cards),
        "cards_other_by_label": {},
        "alternatives": sum(s["alternatives"] for s in scans),
        "alternatives_heston": len(heston_alts),
        "alternatives_other_by_label": {},
    }
    for s in scans:
        for k, v in s["cards_by_label"].items():
            if k != "Heston repriced":
                totals["cards_other_by_label"][k] = totals["cards_other_by_label"].get(k, 0) + v
        for k, v in s["alternatives_by_label"].items():
            if k != "Heston repriced":
                totals["alternatives_other_by_label"][k] = totals["alternatives_other_by_label"].get(k, 0) + v
    return {
        "basis_note": ("Committed scans are schema_version 2 (no exit.rrRiskBasis). Their stored rrRatio / "
                       "rrContribution use the pre-D5 premium-stop basis (exit - premium) / (0.60 x premium). "
                       "Neither today's frontend nor backend loads them. No stored rrRatio is compared with a "
                       "shipped R/R; both R/Rs below are on the current full-premium basis."),
        "totals": totals,
        "by_horizon_direction": _agg("hd"),
        "by_date": _agg("date"),
        "scans": scans,
        "input_recovery": {
            "non_heston_cards": n_rec, "reproducible": n_rec - len(failed), "not_reproducible": len(failed),
            "fail_share": (len(failed) / n_rec) if n_rec else None,
            "m1_counterfactuals_reliable": (len(failed) / n_rec) <= UNRELIABLE_SHARE if n_rec else False,
            "not_reproducible_list": [{k: r[k] for k in ("scan", "symbol", "contract", "differing_fields",
                                                         "max_abs_diff")} for r in failed],
            "pre_d5_basis_confirmed_cards": sum(1 for r in recoveries if r["pre_d5_basis_confirmed_by_ladder"])
            + sum(1 for h in heston_cards if h["pre_d5_basis_confirmed_by_ladder"]),
            "cards": recoveries,
        },
        "alternatives_exit_recovery_supplementary": {
            "note": ("Non-Heston alternatives: the stored exit premium back-solved from the stored pre-D5 rrRatio "
                     "(interval from its 2 dp rounding, +-$0.01) against the shipped estimate_rr BS exit premium. "
                     "Exit premiums are compared, never R/Rs."),
            "checked": len(non_heston_alt_checks), "match": len(non_heston_alt_checks) - len(alt_fail),
            "mismatch": len(alt_fail),
            "mismatch_list": [{k: a[k] for k in ("scan", "card_symbol", "strike", "dte", "mid",
                                                 "stored_exit_interval", "bs_exit")} for a in alt_fail],
        },
        "heston_cards": heston_cards,
        "heston_alternatives": heston_alts,
        "limits": ["Cards store no Heston parameters, fit error or calibration chain: M1 cannot reproduce a "
                   "Heston number and cannot evaluate any option. It reports reach and the exit gap only.",
                   "Three days of real scans (2026-09-18, 2026-10-01, 2026-10-09)."],
    }


# ── The rrRatio consumer grep ────────────────────────────────────────────────

GATE_FILES = (
    "backend/app/scoring/contract_validator.py",
    "backend/app/scoring/conviction_sizing.py",
    "backend/app/routers/auto_trade.py",
    "backend/app/services/auto_trader.py",
    "backend/app/services/auto_trade_booking.py",
    "backend/app/models/daily_risk.py",
    "backend/app/services/daily_risk.py",
    "backend/app/services/daily_risk_hooks.py",
    "backend/app/services/portfolio_risk.py",
    "backend/app/routers/risk_settings.py",
    "frontend/app/(frame)/screener/step-4-ranking/cardToRow.ts",
    "frontend/app/(frame)/screener/step-4-ranking/page.tsx",
    "frontend/lib/autoTradeStore.ts",
    "frontend/lib/risk.ts",
    "frontend/lib/riskStore.ts",
)


def _git(*args) -> tuple[list[str], str]:
    cmd = ["git", *args]
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    return cmd, p.stdout


def rr_consumer_grep() -> dict:
    pattern = r"rrRatio|rr_ratio"
    excl = [":!*test*", ":!*__tests__*", ":!*__mocks__*", ":!frontend/e2e"]
    cmd_all, out_all = _git("grep", "-n", "-E", pattern, "--", "backend/app", "frontend", *excl)
    cmd_gate, out_gate = _git("grep", "-n", "-E", pattern, "--", *GATE_FILES)
    # `key=lambda`, not bare `key=`: a bare `key=` matches JSX list keys
    # (`<tr key={t.rrRatio}>`), which order nothing.
    sort_pat = r"(sort|sorted|sortBy|key=lambda|rank).*(rrRatio|rr_ratio)|(rrRatio|rr_ratio).*(sort|rank)"
    cmd_sort, out_sort = _git("grep", "-n", "-E", sort_pat, "--", "backend/app", "frontend", *excl)
    missing = [g for g in GATE_FILES if not (REPO / g).exists()]
    all_hits = [ln for ln in out_all.splitlines() if ln]
    return {
        "all_consumers": {"command": " ".join(cmd_all), "hits": len(all_hits),
                          "files": sorted({ln.split(":", 1)[0] for ln in all_hits}), "lines": all_hits},
        "gate_files": {"command": " ".join(cmd_gate), "files": list(GATE_FILES), "missing_files": missing,
                       "hits": [ln for ln in out_gate.splitlines() if ln]},
        "sort_or_rank_expressions": {"command": " ".join(cmd_sort),
                                     "hits": [ln for ln in out_sort.splitlines() if ln]},
        "verdict_no_gate_reads_rrRatio": (not out_gate.strip()) and (not out_sort.strip()) and not missing,
    }


# ── Provenance ───────────────────────────────────────────────────────────────

def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def provenance() -> dict:
    import numpy
    import scipy
    _, sha = _git("rev-parse", "HEAD")
    _, app_diff = _git("status", "--porcelain", "--", "backend/app", "backend/config", "frontend")
    inputs = {}
    for f in _options_scan_files():
        inputs[str(f.relative_to(REPO))] = _sha256(f)
        req = f.with_name(f.name.replace(".result.json", ".request.json"))
        inputs[str(req.relative_to(REPO))] = _sha256(req)
    for f in sorted(PROTOCOL_DIR.glob("options-*.request.json")):
        inputs[str(f.relative_to(REPO))] = _sha256(f)
    for f in sorted(CAPTURE_DIR.glob("*/rows.json")):
        inputs[str(f.relative_to(REPO))] = _sha256(f)
    shipped = {s: _sha256(REPO / s) for s in _SHIPPED_SOURCES}
    return {
        "git_head": sha.strip(),
        "app_config_frontend_worktree_changes": app_diff.splitlines(),
        "python": sys.version.split()[0], "implementation": platform.python_implementation(),
        "scipy": scipy.__version__, "numpy": numpy.__version__, "httpx": httpx.__version__,
        "cpu_count": os.cpu_count(),
        "rate_r": R,
        "shipped_grids": shipped_grids(),
        "heston_full_grid_env_active": bool(hc._USE_FULL_GRID),
        "heston_delta_safety_margin": scan_mod._HESTON_DELTA_SAFETY_MARGIN,
        "hard_reject_delta_band": list(scan_mod.hard_reject_delta_band()),
        "protocol_holds": protocol_holds(),
        "input_sha256": inputs,
        "shipped_source_sha256": shipped,
        "timing_note": ("calibration_seconds_single_thread_relative is measured on this cloud box, one thread, "
                        "cache cleared; compare relatively only. It is not a scan abandonment rate."),
    }


# ── Markdown ─────────────────────────────────────────────────────────────────

def _f(x, nd=3):
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _rng(s: Optional[dict], nd=3) -> str:
    if not s:
        return "–"
    return f"{s['min']:.{nd}f} / {s['median']:.{nd}f} / {s['max']:.{nd}f} (n={s['n']})"


def m1_markdown(m1: dict, grep: dict) -> str:
    t = m1["totals"]
    ir = m1["input_recovery"]
    L = ["# HESTON-RR-OVERPRICING — M1: reach and exit gap on the committed real scans", "",
         "Generated by `backend/scripts/heston_rr_overpricing_probe.py`; machine output in `m1.json`.", "",
         "**Basis.** " + m1["basis_note"], "",
         "## Reach", "",
         f"- Option cards: **{t['cards_heston']} of {t['cards']}** labelled \"Heston repriced\" "
         f"(others: {t['cards_other_by_label']}).",
         f"- Alternative rows: **{t['alternatives_heston']} of {t['alternatives']}** labelled \"Heston repriced\" "
         f"(others: {t['alternatives_other_by_label']}).", "",
         "| scan | horizon | direction | cards | Heston cards | alternatives | Heston alternatives |",
         "|---|---|---|---|---|---|---|"]
    for s in m1["scans"]:
        L.append(f"| {s['file'].split('scans/')[1]} | {s['horizon']} | {s['direction']} | {s['cards']} | "
                 f"{s['cards_by_label'].get('Heston repriced', 0)} | {s['alternatives']} | "
                 f"{s['alternatives_by_label'].get('Heston repriced', 0)} |")
    L += ["", "By horizon / direction:", "", "| horizon/direction | cards | Heston cards | alternatives | Heston alternatives |",
          "|---|---|---|---|---|"]
    for k, a in m1["by_horizon_direction"].items():
        L.append(f"| {k} | {a['cards']} | {a['cards_heston']} | {a['alternatives']} | {a['alternatives_heston']} |")
    L += ["", "## Input-recovery check (non-Heston cards)", "",
          f"Shipped `build_trade_plan(heston_params=None)` from each card's stored inputs reproduces the stored "
          f"ladder `estimatedOptionPrice` to ±$0.01 on **{ir['reproducible']} of {ir['non_heston_cards']}** "
          f"non-Heston cards ({ir['not_reproducible']} not-reproducible, fail share "
          f"{_f(ir['fail_share'])}). M1 counterfactuals reliable (≤10 % fail): "
          f"**{ir['m1_counterfactuals_reliable']}**.",
          f"Pre-D5 basis (rrContribution = (est − premium)/(0.60 × premium)) confirmed by the ladder on "
          f"{ir['pre_d5_basis_confirmed_cards']} of {t['cards']} cards.", ""]
    if ir["not_reproducible_list"]:
        L += ["Not reproducible:", ""]
        for r in ir["not_reproducible_list"]:
            L.append(f"- `{r['scan']}` {r['contract']}: {r['differing_fields']} (max |diff| {r['max_abs_diff']:.4f})")
        L.append("")
    sup = m1["alternatives_exit_recovery_supplementary"]
    L += [f"Supplementary (alternatives): {sup['note']} Match on **{sup['match']} of {sup['checked']}**.", ""]
    for a in sup["mismatch_list"]:
        L.append(f"- `{a['scan']}` {a['card_symbol']} alt {a['strike']} dte {a['dte']}: stored exit "
                 f"{a['stored_exit_interval'][0]:.3f}–{a['stored_exit_interval'][1]:.3f}, shipped BS exit {a['bs_exit']}")
    L += ["", "## Heston cards: stored Heston exit vs shipped non-Heston exit (card horizon)", "",
          "Both R/Rs on the full-premium basis: Heston R/R = (stored Heston exit − premium)/premium; BS R/R from "
          "shipped `build_trade_plan(heston_params=None)`. Band = Step 7 grade (≥2.0 PASS, ≥1.5 CAUTION, else REJECT).", "",
          "| scan | symbol | contract | level | Heston exit | BS exit | Heston÷BS | Heston R/R | BS R/R | bands (H → BS) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for h in m1["heston_cards"]:
        for lv in h["levels"]:
            L.append(f"| {h['scan'].split('scans/')[1]} | {h['symbol']} | {h['contract']} | {lv['level']} | "
                     f"{lv['stored_heston_exit']:.2f} | {lv['bs_exit']:.2f} | {lv['heston_over_bs']:.3f} | "
                     f"{lv['heston_rr_full_premium']:.2f} | {lv['bs_rr_full_premium']:.2f} | "
                     f"{lv['heston_band']} → {lv['bs_band']} |")
    ratios = [lv["heston_over_bs"] for h in m1["heston_cards"] for lv in h["levels"]]
    hb = sum(1 for h in m1["heston_cards"] if h["headline"]["band_changes"])
    L += ["", f"Heston÷BS exit over all Heston-card levels (min / median / max): {_rng(_spread(ratios))}.",
          f"Headline Step 7 band changes between Heston and BS: **{hb} of {len(m1['heston_cards'])}** Heston cards.",
          f"Inputs (target ladder prices) reproduced on {sum(1 for h in m1['heston_cards'] if h['inputs_reproduced'])} "
          f"of {len(m1['heston_cards'])} Heston cards.", "",
          "## Heston alternatives (half-expiry default horizon)", "",
          "The stored exit is back-solved from the stored pre-D5 rrRatio: exit = mid × (1 + 0.60 × rrRatio), "
          "known to ±mid × 0.003 from its 2 dp rounding (interval given).", "",
          "| scan | card | alt strike | dte | mid | stored exit (interval) | BS exit | Heston÷BS | Heston R/R | BS R/R | bands (H → BS) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in m1["heston_alternatives"]:
        lo, hi = a["stored_exit_interval"]
        L.append(f"| {a['scan'].split('scans/')[1]} | {a['card_symbol']} | {a['strike']:g} | {a['dte']} | {a['mid']:.2f} | "
                 f"{a['stored_exit_backsolved']:.2f} ({lo:.2f}–{hi:.2f}) | {a['bs_exit']:.2f} | "
                 f"{a['heston_over_bs']:.3f} | {a['heston_rr_full_premium']:.2f} | {a['bs_rr_full_premium']:.2f} | "
                 f"{a['heston_band']} → {a['bs_band']} |")
    ab = sum(1 for a in m1["heston_alternatives"] if a["band_changes"])
    L += ["", f"Heston÷BS over Heston alternatives: {_rng(_spread([a['heston_over_bs'] for a in m1['heston_alternatives']]))}; "
          f"band changes {ab} of {len(m1['heston_alternatives'])} (alternatives carry no Step 7 grade of their own; "
          "the band is shown for comparison).", "",
          "## Who reads the card's rrRatio (re-verified by grep)", "",
          f"- All consumers: `{grep['all_consumers']['command']}` → {grep['all_consumers']['hits']} lines in "
          f"{len(grep['all_consumers']['files'])} files (listed in `m1.json`).",
          f"- Ranking / contract-score / sizing / auto-trader gate files: `{grep['gate_files']['command']}` → "
          f"**{len(grep['gate_files']['hits'])} hits**" + (f"; missing files {grep['gate_files']['missing_files']}"
                                                          if grep['gate_files']['missing_files'] else "") + ".",
          f"- Sort/rank expressions: `{grep['sort_or_rank_expressions']['command']}` → "
          f"**{len(grep['sort_or_rank_expressions']['hits'])} hits**.",
          f"- Verdict, no gate reads the card's rrRatio: **{grep['verdict_no_gate_reads_rrRatio']}**.", "",
          "## Limits", ""] + [f"- {x}" for x in m1["limits"]] + [""]
    return "\n".join(L)


def _gap_tables(fits: list[dict], group_key: str, group_vals) -> list[str]:
    L = [f"| {group_key} | fits | accepted | scored proxy Heston÷mid (min / median / max) | in-band Heston÷mid (min / median / max) |",
         "|---|---|---|---|---|"]
    for g in group_vals:
        sub = [f for f in fits if f.get(group_key) == g]
        acc = [f for f in sub if f["accepted"]]
        prox = [f["gaps"]["scored_proxy"]["heston_over_mid"] for f in acc if f["gaps"]["scored_proxy"]]
        inb = [s["heston_over_mid"] for f in acc for s in f["gaps"]["in_band"]]
        L.append(f"| {g} | {len(sub)} | {len(acc)} | {_rng(_spread(prox))} | {_rng(_spread(inb))} |")
    return L


def _exit_table(fits: list[dict]) -> list[str]:
    L = ["| horizon | move | Heston÷BS exit (min / median / max) | Heston R/R (min / median / max) | BS R/R (min / median / max) | band changes |",
         "|---|---|---|---|---|---|"]
    acc = [f for f in fits if f["accepted"] and f["gaps"]["scored_proxy"]]
    for h in ("card_swing", "card_position", "alternatives_half_expiry"):
        for m in MOVES:
            rows = [e for f in acc for e in f["gaps"]["scored_proxy"]["exits"]
                    if e["horizon"] == h and abs(abs(e["move"]) - m) < 1e-12]
            if not rows:
                continue
            L.append(f"| {h} | ±{int(m * 100)}% | {_rng(_spread([e['heston_over_bs'] for e in rows]))} | "
                     f"{_rng(_spread([e['heston_rr'] for e in rows]), 2)} | {_rng(_spread([e['bs_rr'] for e in rows]), 2)} | "
                     f"{sum(1 for e in rows if e['band_changes'])} of {len(rows)} |")
    labels: dict[str, int] = {}
    for f in acc:
        for e in f["gaps"]["scored_proxy"]["exits"]:
            k = f"{e['heston_model']} vs {e['bs_model']}"
            labels[k] = labels.get(k, 0) + 1
    fell_back = sum(1 for f in fits if f["accepted"] for s in f["gaps"]["in_band"] if s["heston_fell_back"])
    no_proxy = sum(1 for f in fits if f["accepted"] and not f["gaps"]["scored_proxy"])
    L += ["", f"Exit-premium labels (Heston leg vs BS leg): {labels}. In-band Heston 'now' prices that fell back "
              f"to Black-Scholes: {fell_back}. Accepted fits with no in-band contract (no scored proxy): {no_proxy}."]
    return L


def _fit_quality(fits: list[dict]) -> list[str]:
    acc = [f for f in fits if f["accepted"]]
    sides: dict[str, dict[str, int]] = {}
    for f in acc:
        for k, v in f["boundary_sides"].items():
            sides.setdefault(k, {}).setdefault(v, 0)
            sides[k][v] += 1
    hits = [f["boundary_hit_count"] for f in acc]
    return [f"- rel-RMSE of accepted fits: {_rng(_spread([f['rel_rmse'] for f in acc]), 4)}.",
            f"- Feller ratio σv²/(2κθ) of accepted fits (>1 breaks Feller): {_rng(_spread([f['feller_ratio'] for f in acc]), 2)}.",
            f"- Winner position on the shipped 2-rung grid, per parameter: {sides}. On two rungs every value is a "
            f"boundary, so the hit count ({_rng(_spread([float(h) for h in hits]), 0)}) is arithmetic, not a finding; "
            "the side is the information. The shipped `_boundary_hits` diagnostic is silent on this grid by design.",
            f"- Calibration seconds, single thread, relative only: {_rng(_spread([f['calibration_seconds_single_thread_relative'] for f in fits]), 3)}."]


def m2_markdown(m2: dict) -> str:
    fits = m2["fits"]
    acc = [f for f in fits if f["accepted"]]
    methods: dict[str, int] = {}
    for f in fits:
        methods[f["method"]] = methods.get(f["method"], 0) + 1
    L = ["# HESTON-RR-OVERPRICING — M2: synthetic sweep on current code", "",
         "Generated by `backend/scripts/heston_rr_overpricing_probe.py`; machine output in `m2.json`.", "",
         f"{m2['cells']} cells = 6 DTE (30, 45, 60, 90, 180, 365) × 4 widths (15, 25, 40, 60 strikes) × 4 smile "
         "regimes (ATM 0.20 / 0.35, skew −0.10 / −0.30, iv(k) = atm + skew·k + 0.5·k², k = ln(K/S)). Spot 100, "
         "r = 0.05, strikes evenly spaced over ±40 % log-moneyness. Each cell has a call chain and a put chain, "
         f"calibrated separately: **{len(fits)} fits**. Mids are BS at iv(k) rounded to $0.01, delta to 4 dp; the "
         "chain is filtered with scan.py's heston_chain rule (re-implemented, reading the app's band and margin); "
         "shipped `calibrate_heston(chain, 100, 0.05)` after `_run_calibration.cache_clear()`.", "",
         f"**Accepted (`heston_grid`): {len(acc)} of {len(fits)}** ({100 * len(acc) / len(fits):.1f} %). Methods: {methods}.", "",
         "## Heston ÷ mid now, by DTE (accepted fits)", "",
         "Scored proxy = the in-band contract (|delta| within the hard-reject band) with |delta| closest to 0.50.", ""]
    L += _gap_tables(fits, "dte", M2_DTES)
    L += ["", "By right:", ""] + _gap_tables(fits, "right", RIGHTS)
    L += ["", "By regime:", ""] + _gap_tables(fits, "regime", list(M2_REGIMES))
    L += ["", "## Scored proxy exit premium, Heston ÷ BS-IV, and full-premium R/R", "",
          "Through shipped `estimate_rr` (premium = mid, full-premium basis). Card horizons are "
          "`display_reprice_years` for the committed Swing (hold 5–15) and Position (hold 15–45) protocol requests; "
          "the alternatives' horizon is the half-expiry default.", ""]
    L += _exit_table(fits)
    L += ["", "## Fit quality", ""] + _fit_quality(fits) + [""]
    return "\n".join(L)


def m3_markdown(m3: dict) -> str:
    L = ["# HESTON-RR-OVERPRICING — M3: real chains (five committed Tradier captures)", "",
         "Generated by `backend/scripts/heston_rr_overpricing_probe.py`; machine output in `m3.json`.", "",
         "Rows come from the shipped `market.fetch_option_chain_async`, called with an httpx MockTransport serving "
         "each capture's own raw Tradier records; `market.date` pinned to the capture's ET date "
         "(`meta.capture_et`); `market._expirations_cache` cleared before every call; the mock answers expirations "
         "with the capture's own expiry list (the expiries the capture holds) and raises on any unknown symbol or "
         "expiry; IBKR / tastytrade / yfinance IV enrichment patched to no-ops; the Tradier rate-limit governor "
         "replaced by a pass-through (it changes no data). Then scan.py's heston_chain rule, no two-sided filter. "
         "Captures hold near-dated expiries only (dte 6–46).", "",
         "Spot is put–call parity, S = C_mid − P_mid + K·e^(−rT), at the two-sided call/put pair with the "
         "smallest |C_mid − P_mid| (nearest the money); no dividend term.", "",
         "| capture | chains | 0 rows | < 3 rows | no spot | calibrated | accepted | skipped symbols |",
         "|---|---|---|---|---|---|---|---|"]
    all_chains = []
    for c in m3["captures"]:
        ch = c["chains"]
        all_chains += [x for x in ch if x["status"] == "calibrated"]
        cnt = lambda s: sum(1 for x in ch if x["status"] == s)  # noqa: E731
        L.append(f"| {c['capture'].split('/')[-1]} | {len(ch)} | {cnt('zero_rows')} | {cnt('thin')} | {cnt('no_spot')} | "
                 f"{cnt('calibrated')} | {sum(1 for x in ch if x.get('accepted'))} | {len(c['skipped_symbols'])} |")
    L += ["", "## Parity spots", "", "| capture | symbol | spot | strike | expiry | dte | C mid | P mid |",
          "|---|---|---|---|---|---|---|---|"]
    for c in m3["captures"]:
        for sym, s in c["spots"].items():
            if s is None:
                L.append(f"| {c['capture'].split('/')[-1]} | {sym} | skipped | – | – | – | – | – |")
            else:
                L.append(f"| {c['capture'].split('/')[-1]} | {sym} | {s['spot']:.2f} | {s['strike']:g} | {s['expiry']} | "
                         f"{s['dte']} | {s['call_mid']:.2f} | {s['put_mid']:.2f} |")
    L += ["", "## Chains not calibrated (each listed with its reason)", ""]
    any_listed = False
    for c in m3["captures"]:
        for x in c["listed"]:
            any_listed = True
            L.append(f"- {c['capture'].split('/')[-1]} {x['symbol']} {x['expiry']} {x['right']}: {x['reason']}")
        for x in c["chains"]:
            if x["status"] == "no_spot":
                any_listed = True
                L.append(f"- {c['capture'].split('/')[-1]} {x['symbol']} {x['expiry']} {x['right']}: no parity spot")
        for s in c["skipped_symbols"]:
            L.append(f"- {c['capture'].split('/')[-1]} symbol {s['symbol']} skipped: {s['reason']}")
    if not any_listed:
        L.append("- none")
    methods: dict[str, int] = {}
    for x in all_chains:
        methods[x["method"]] = methods.get(x["method"], 0) + 1
    acc = [x for x in all_chains if x["accepted"]]
    L += ["", f"**Calibrated chains: {len(all_chains)}; accepted (`heston_grid`): {len(acc)}.** Methods: {methods}.", "",
          "## Heston ÷ mid now (accepted fits)", ""]
    L += _gap_tables(all_chains, "right", RIGHTS)
    L += ["", "By dte:", ""] + _gap_tables(all_chains, "dte", sorted({x["dte"] for x in all_chains}))
    L += ["", "## Scored proxy exit premium, Heston ÷ BS-IV, and full-premium R/R", ""]
    L += _exit_table(all_chains)
    L += ["", "## Fit quality", ""] + _fit_quality(all_chains)
    L += ["", "## Limits", "", "- Five captures from 3–5 October 2026, seven symbols, near-dated expiries only.",
          "- Parity spot has no dividend term.",
          "- Replayed rows carry quote-liveness labels for today's clock; calibration does not read them.",
          "- Delta-0 rows (missing greeks) are kept, as scan.py keeps them (fail open); counted per chain in `m3.json`.", ""]
    return "\n".join(L)


# ── Main ─────────────────────────────────────────────────────────────────────

def _write(name: str, obj) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / name
    if isinstance(obj, str):
        p.write_text(obj)
    else:
        p.write_text(json.dumps(obj, indent=1, allow_nan=False, default=str) + "\n")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", choices=("m1", "m2", "m3"), action="append",
                    help="run only these measurements (repeatable); default all")
    args = ap.parse_args(argv)
    which = args.only or ["m1", "m2", "m3"]

    logging.getLogger("app").setLevel(logging.ERROR)
    warnings.simplefilter("ignore")      # scipy IntegrationWarning from the shipped pricer

    with forbid_network():
        _write("provenance.json", provenance())
        if "m1" in which:
            m1 = run_m1()
            grep = rr_consumer_grep()
            _write("m1.json", {**m1, "rr_consumer_grep": grep})
            _write("m1.md", m1_markdown(m1, grep))
            print("M1 written")
        if "m2" in which:
            m2 = run_m2()
            _write("m2.json", m2)
            _write("m2.md", m2_markdown(m2))
            print("M2 written")
        if "m3" in which:
            m3 = run_m3()
            _write("m3.json", m3)
            _write("m3.md", m3_markdown(m3))
            print("M3 written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
