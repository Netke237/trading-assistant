"""HESTON-RR-OVERPRICING probe, T1: measurements M1, M2 and M3.

Plan: docs/superpowers/plans/2026-10-22-heston-rr-overpricing-plan.md (sections 2, 4 T1, 5, 6).
Tests: backend/tests/test_heston_rr_overpricing_probe.py.

Run (Python 3.11, from backend/):
    python scripts/heston_rr_overpricing_probe.py            # M1, M2, M3
    python scripts/heston_rr_overpricing_probe.py --only m1  # one measurement
    python scripts/heston_rr_overpricing_probe.py --options  # M4 (T2): options A-D on fits

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

T2 adds the `--options` mode (M4): options A(i), A(ii), B (four limits), C and
D evaluated on M2's 192 and M3's 134 fits, plus a reconciliation run of today's
code on the synthetic chain committed in 2026-09 (`heston_latency_probe.chain`).
It writes options.json / options.md only and leaves m1-m3 and provenance.json
as T1 wrote them (options.json carries its own provenance block). A(ii) runs
through `run_calibration_with_grids`, a script-local copy of the shipped
`_run_calibration` with the grids as arguments, pinned by T2's tests.
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


# ── M4: options A-D, evaluated on M2's and M3's fits (T2) ────────────────────
#
# Plan section 2, M4. Every result here is about FITS (one calibrated chain and
# its scored proxy), never about cards: no stored card carries the chain, fit
# or parameters an option needs. Prototypes live only in this file.

# A(ii)'s wider box (plan section 2, M4, option A). v0 stays the solved seed.
WIDE_GRID = {"kappa": [0.5, 1.5, 3.0, 6.0],
             "theta": [0.02, 0.04, 0.08, 0.16, 0.25],
             "sigma_v": [0.2, 0.4, 0.6, 0.9, 1.2],
             "rho": [-0.95, -0.8, -0.5, -0.2]}
B_LIMITS = (0.05, 0.10, 0.20, 0.30)
# T1-T3 as the shipped ladder (`estimate_targets`) spaces them: T1 = the base
# move, T2 = 1.5x it, T3 = 2.0x it. A 10 % base makes T1/T2 the same +-10 % /
# +-15 % moves M2 and M3 report, so option D reproduces their exits.
LADDER_BASE_MOVE = 0.10
LADDER = (("T1", 1.0), ("T2", 1.5), ("T3", 2.0))
CARD_HORIZONS = ("card_swing", "card_position")
ALL_HORIZONS = ("card_swing", "card_position", "alternatives_half_expiry")
CALIBRATED_OPTIONS = ("D", "A_i", "A_ii")
OPTION_ORDER = ("D", "A_i", "A_ii", *(f"B_{L:.2f}" for L in B_LIMITS), "C")
OPTION_TITLES = {
    "D": "D. Leave as is (shipped 2-rung grid)",
    "A_i": "A(i). Shipped 3-rung HESTON_FULL_CALIBRATION grid",
    "A_ii": "A(ii). Wider box (4 x 5 x 5 x 4)",
    **{f"B_{L:.2f}": f"B. Fit-error limit L = {L:.2f}" for L in B_LIMITS},
    "C": "C. Anchor Heston to the market (scored proxy)",
}


def run_calibration_with_grids(chain: list[dict], S: float, r: float,
                               grids: dict[str, list[float]]):
    """SCRIPT-LOCAL COPY of `heston_cache._run_calibration`, with the four
    searched grids passed in instead of chosen by `_USE_FULL_GRID` (they are
    locals there and cannot be patched). The seed, the search loop, the
    flat-BS gate and the verdict are the shipped ones; only the WARNING log
    line is left out (it changes no result). Pinned by
    `test_local_run_calibration_copy_matches_shipped_on_default_and_full_grid`
    (same method, rmse and params) and by an AST check that the search loop is
    the shipped loop verbatim."""
    from app.models.heston import CalibrationResult
    from app.models.heston import heston_price  # noqa: F401  (the name the copied loop calls)

    v0_seed = hc._seed_v0(chain, S, r)
    kappa_grid = list(grids["kappa"])
    theta_grid = list(grids["theta"])
    sigma_v_grid = list(grids["sigma_v"])
    rho_grid = list(grids["rho"])
    v0_grid = [v0_seed]

    best_rmse = float("inf")
    best_params = None
    best_chain: list[dict] = []

    for v0 in v0_grid:
        for kappa in kappa_grid:
            for theta in theta_grid:
                for sigma_v in sigma_v_grid:
                    for rho in rho_grid:
                        params = HestonParams(v0=v0, kappa=kappa, theta=theta,
                                              sigma_v=sigma_v, rho=rho)
                        sse = 0.0
                        priced: list[dict] = []
                        for c in chain:
                            mid = c.get("mid_price", 0.0)
                            if mid <= 0:
                                continue
                            try:
                                model_p = heston_price(S, c["strike"], c["expiry_years"],
                                                       r, params, c.get("is_call", True))
                                sse += ((model_p - mid) / mid) ** 2
                                priced.append(c)
                            except Exception:
                                continue
                        if not priced:
                            continue
                        rmse = math.sqrt(sse / len(priced))
                        if rmse < best_rmse:
                            best_rmse = rmse
                            best_params = params
                            best_chain = priced

    if best_params is None:
        fallback = HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7)
        return CalibrationResult(params=fallback, rmse=float("inf"), method="bs_fallback")

    baseline_rmse, baseline_sigma = hc._flat_bs_baseline(best_chain, S, r)
    if baseline_rmse is None:
        return CalibrationResult(
            params=HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7),
            rmse=float("inf"), method="bs_fallback")
    if baseline_rmse <= best_rmse:
        return CalibrationResult(
            params=HestonParams(v0=baseline_sigma ** 2, kappa=2.0, theta=baseline_sigma ** 2,
                                sigma_v=0.3, rho=-0.7),
            rmse=round(baseline_rmse, 6), method="bs_flat")
    return CalibrationResult(params=best_params, rmse=round(best_rmse, 6), method="heston_grid")


def calibrate_with_grids(option_chain: list[dict], S: float, grids: dict[str, list[float]], r: float = R):
    """`calibrate_cached`'s own wrapper (usable-strike filter, < 3 -> thin-chain
    bs_fallback, the JSON round trip the lru_cache key forces) around the local
    copy. No cache: every call searches."""
    from app.models.heston import CalibrationResult
    chain = [c for c in option_chain if c.get("mid_price", 0) > 0 and c.get("expiry_years", 0) > 0]
    if len(chain) < 3:
        return CalibrationResult(params=hc._thin_chain_params(chain, S, r), rmse=float("inf"),
                                 method="bs_fallback")
    return run_calibration_with_grids(json.loads(json.dumps(chain, sort_keys=True)), S, r, grids)


def option_grids() -> dict[str, dict[str, list[float]]]:
    g = shipped_grids()
    return {"D": g["default"], "A_i": g["full"], "A_ii": WIDE_GRID}


def calibrate_option(chain: list[dict], S: float, which: str, grids: Optional[dict] = None) -> tuple[dict, object]:
    """One calibration for option D (shipped, default grid), A_i (shipped,
    `_USE_FULL_GRID` patched True) or A_ii (the local copy on WIDE_GRID). The
    shipped lru_cache is cleared before EVERY call, whichever path runs."""
    grids = grids or option_grids()
    hc._run_calibration.cache_clear()
    t0 = time.perf_counter()
    if which == "D":
        res = heston_mod.calibrate_heston(chain, S, R)
    elif which == "A_i":
        with mock.patch.object(hc, "_USE_FULL_GRID", True):
            res = heston_mod.calibrate_heston(chain, S, R)
    elif which == "A_ii":
        res = calibrate_with_grids(chain, S, WIDE_GRID)
    else:
        raise ValueError(which)
    secs = time.perf_counter() - t0
    accepted = res.method == "heston_grid"
    rec: dict = {"method": res.method, "accepted": accepted, "rel_rmse": _finite(res.rmse),
                 "params": asdict(res.params), "seconds_single_thread": round(secs, 4)}
    if accepted:
        p, g = res.params, grids[which]
        sides = {}
        for name in ("kappa", "theta", "sigma_v", "rho"):
            v = getattr(p, name)
            sides[name] = "min" if v == min(g[name]) else "max" if v == max(g[name]) else "interior"
        rec["boundary_sides"] = sides
        rec["feller_ratio"] = p.sigma_v ** 2 / (2.0 * p.kappa * p.theta)
    return rec, res


def scored_proxy(rows: list[dict], contract_overrides: Optional[dict] = None) -> tuple[Optional[dict], list[dict]]:
    """The scored proxy and the in-band rows, by exactly `exit_gaps`' rule."""
    lo, hi = selection_delta_band(contract_overrides)
    inband = [r for r in rows if float(r.get("price", 0)) > 0
              and lo <= abs(float(r.get("delta") or 0)) <= hi]
    if not inband:
        return None, inband
    return min(inband, key=lambda r: (abs(abs(float(r["delta"])) - 0.5), float(r["strike"]))), inband


def ladder_targets(S: float, is_call: bool) -> list[tuple[str, float, float]]:
    """(level, signed move, stock target) for T1-T3."""
    out = []
    for lvl, mult in LADDER:
        m = LADDER_BASE_MOVE * mult
        out.append((lvl, m if is_call else -m, S * (1 + m) if is_call else S * (1 - m)))
    return out


def _leg(res) -> dict:
    return {"exit": res.estimated_exit_premium, "rr": res.rr_ratio, "band": step7_band(res.rr_ratio),
            "model": res.model_used}


def anchored_leg(params: HestonParams, target: float, K: float, T: float, mid: float, is_call: bool,
                 reprice_years: Optional[float], anchor: float) -> Optional[dict]:
    """Option C: exit = heston(target) x mid / heston(now), with estimate_rr's
    own full-premium arithmetic (exit floored at 0.01, R/R rounded to 2 dp,
    exit shown to the cent). None where the Heston price at the target fails
    (fell back / non-finite / <= 0): the shipped path then prices with BS.
    With anchor = 1.0 this equals estimate_rr's Heston leg (pinned by a test)."""
    ry = reprice_years if reprice_years is not None else _default_reprice_years(T)
    try:
        d = heston_price_detail(target, K, ry, R, params, is_call)
        raw = None if d.fell_back else d.price
    except Exception:
        raw = None
    if raw is None or not math.isfinite(raw) or raw <= 0:
        return None
    exit_p = max(raw * anchor, 0.01)
    rr = round((exit_p - mid) / mid, 2)
    return {"exit": round(exit_p, 2), "rr": rr, "band": step7_band(rr), "model": "Heston repriced"}


def _bs_legs(ctx: dict, H: dict) -> dict:
    p = ctx["proxy"]
    T = p["dte"] / 365.0
    out = {}
    for h in ALL_HORIZONS:
        ry = H[h](p["dte"])
        out[h] = []
        for lvl, move, target in ladder_targets(ctx["S"], ctx["is_call"]):
            res = estimate_rr(stock_price=ctx["S"], target_price=target, invalidation_price=ctx["S"],
                              strike=p["strike"], expiry_years=T, current_premium=p["mid"],
                              is_call=ctx["is_call"], r=R, reprice_years=ry, heston_params=None)
            out[h].append({"level": lvl, "move": move, "target": target, **_leg(res)})
    return out


def evaluate_pricing(ctx: dict, params: Optional[HestonParams], H: dict, bs: dict, anchor: bool = False) -> dict:
    """What the scored proxy would show under one option's pricing: Heston (the
    option's params), anchored Heston (C), or BS when the option yields no
    accepted fit. Levels at T1-T3 on the three horizons."""
    if params is None:
        return {"heston": False, "levels": bs}
    p, S, is_call = ctx["proxy"], ctx["S"], ctx["is_call"]
    K, mid, T = p["strike"], p["mid"], p["dte"] / 365.0
    now = heston_price_detail(S, K, T, R, params, is_call)
    out: dict = {"heston_now": now.price, "heston_now_fell_back": now.fell_back}
    a = None
    if anchor:
        if now.fell_back or not (math.isfinite(now.price) and now.price > 0):
            return {"heston": False, "levels": bs, "anchor_failed": True}
        a = mid / now.price
        out["anchor_factor"] = a
        out["proxy_heston_over_mid"] = now.price * a / mid
        out["in_band_heston_over_mid"] = None   # C anchors the scored proxy only
    else:
        out["proxy_heston_over_mid"] = now.price / mid
        out["in_band_heston_over_mid"] = [
            heston_price_detail(S, float(r["strike"]), r["dte"] / 365.0, R, params, is_call).price
            / float(r["price"]) for r in ctx["in_band"]]
    levels = {}
    fell = 0
    for h in ALL_HORIZONS:
        ry = H[h](p["dte"])
        levels[h] = []
        for i, (lvl, move, target) in enumerate(ladder_targets(S, is_call)):
            if anchor:
                leg = anchored_leg(params, target, K, T, mid, is_call, ry, a)
                if leg is None:
                    leg = {k: bs[h][i][k] for k in ("exit", "rr", "band", "model")}
            else:
                leg = _leg(estimate_rr(stock_price=S, target_price=target, invalidation_price=S, strike=K,
                                       expiry_years=T, current_premium=mid, is_call=is_call, r=R,
                                       reprice_years=ry, heston_params=params))
            if leg["model"] != "Heston repriced":
                fell += 1
            levels[h].append({"level": lvl, "move": move, "target": target, **leg})
    out["levels"] = levels
    out["levels_not_heston"] = fell
    out["heston"] = fell == 0
    # The shipped ladder floors a dip; count any non-increasing Heston ladder.
    out["non_monotone_ladders"] = sum(
        1 for h in ALL_HORIZONS
        if any(levels[h][j + 1]["exit"] < levels[h][j]["exit"] for j in range(len(LADDER) - 1)))
    return out


def options_contexts(limit: Optional[int] = None) -> list[dict]:
    """M2's 192 fits and M3's 134 calibrated chains, rebuilt exactly as T1
    builds them (m2_rows; replay_chain + heston_chain + parity spot)."""
    ctxs: list[dict] = []
    for dte in M2_DTES:
        for width in M2_WIDTHS:
            for regime, (atm, skew) in M2_REGIMES.items():
                for right in RIGHTS:
                    rows = m2_rows(dte, width, atm, skew, right)
                    ctxs.append({"source": "m2", "id": f"m2/{dte}/{width}/{regime}/{right}", "dte": dte,
                                 "width": width, "regime": regime, "right": right, "S": SPOT,
                                 "is_call": right == "C", "rows": rows})
    for cdir in sorted(p for p in CAPTURE_DIR.iterdir() if (p / "rows.json").exists()):
        cap = load_capture(cdir)
        for symbol, expiries in cap["meta"]["expiries"].items():
            spot = parity_spot(cap["rows"], symbol)
            for expiry in expiries:
                for right in RIGHTS:
                    rows, transport = replay_chain(cap, symbol, expiry, right)
                    if transport.anomalies or not rows or len(heston_chain(rows)) < 3 or spot is None:
                        continue
                    ctxs.append({"source": "m3", "id": f"m3/{cdir.name}/{symbol}/{expiry}/{right}",
                                 "capture": cdir.name, "symbol": symbol, "expiry": expiry, "right": right,
                                 "dte": rows[0]["dte"], "S": spot["spot"], "is_call": right == "C",
                                 "rows": rows})
    if limit:
        ctxs = ctxs[:limit] + [c for c in ctxs if c["source"] == "m3"][:limit]
    return ctxs


def evaluate_fit(ctx: dict, H: dict, grids: dict) -> dict:
    proxy, inband = scored_proxy(ctx["rows"])
    chain = heston_chain(ctx["rows"])
    meta = {k: v for k, v in ctx.items() if k not in ("rows",)}
    fit: dict = {**meta, "heston_chain_rows": len(chain), "calibrations": {}, "options": {}}
    results = {}
    for which in CALIBRATED_OPTIONS:
        rec, res = calibrate_option(chain, ctx["S"], which, grids)
        fit["calibrations"][which] = rec
        results[which] = res
    if proxy is None:
        fit["proxy"] = None
        return fit
    ctx = {**ctx, "proxy": {"strike": float(proxy["strike"]), "delta": float(proxy["delta"]),
                            "mid": float(proxy["price"]), "dte": proxy["dte"]},
           "in_band": inband}
    fit["proxy"] = ctx["proxy"]
    fit["in_band_strikes"] = len(inband)
    bs = _bs_legs(ctx, H)
    fit["bs_levels"] = bs
    for which in CALIBRATED_OPTIONS:
        res = results[which]
        params = res.params if res.method == "heston_grid" else None
        fit["options"][which] = evaluate_pricing(ctx, params, H, bs)
    d_rec, d_res = fit["calibrations"]["D"], results["D"]
    for L in B_LIMITS:
        keep = d_rec["accepted"] and d_rec["rel_rmse"] is not None and d_rec["rel_rmse"] <= L
        fit["options"][f"B_{L:.2f}"] = {"heston": keep and fit["options"]["D"]["heston"],
                                        "pricing": "D" if keep else "BS"}
    fit["options"]["C"] = evaluate_pricing(ctx, d_res.params if d_rec["accepted"] else None, H, bs, anchor=True)
    return fit


def option_levels(fit: dict, opt: str) -> dict:
    o = fit["options"][opt]
    if opt.startswith("B_"):
        return fit["options"]["D"]["levels"] if o["pricing"] == "D" else fit["bs_levels"]
    return o["levels"]


def summarize_options(fits: list[dict]) -> dict:
    out: dict = {}
    for opt in OPTION_ORDER:
        s: dict = {"fits": len(fits)}
        withp = [f for f in fits if f["proxy"] is not None]
        s["fits_with_scored_proxy"] = len(withp)
        lab = [f for f in withp if f["options"][opt]["heston"]]
        labD = {f["id"] for f in withp if f["options"]["D"]["heston"]}
        s["heston_labelled"] = len(lab)
        s["label_lost_vs_D"] = sum(1 for f in withp if f["id"] in labD and not f["options"][opt]["heston"])
        s["label_gained_vs_D"] = sum(1 for f in withp if f["id"] not in labD and f["options"][opt]["heston"])
        src = (lambda f: f["options"]["D"]) if opt.startswith("B_") else (lambda f: f["options"][opt])
        s["proxy_heston_over_mid"] = _spread([src(f)["proxy_heston_over_mid"] for f in lab])
        s["in_band_heston_over_mid"] = (None if opt == "C" else
                                        _spread([x for f in lab for x in (src(f)["in_band_heston_over_mid"] or [])]))
        # Fits whose pricing differs from D in either direction.
        changed = {f["id"] for f in withp if f["options"][opt]["heston"] or f["id"] in labD}
        s["fits_heston_under_D_or_option"] = len(changed)
        per = {}
        for h in ALL_HORIZONS:
            for i, (lvl, _) in enumerate(LADDER):
                d_exit, d_rr, bandch = [], [], 0
                for f in withp:
                    lo, ld = option_levels(f, opt)[h][i], option_levels(f, "D")[h][i]
                    if lo["band"] != ld["band"]:
                        bandch += 1
                    if f["id"] in changed:
                        d_exit.append(lo["exit"] - ld["exit"])
                        d_rr.append(round(lo["rr"] - ld["rr"], 2))
                per[f"{h}/{lvl}"] = {"delta_exit_vs_D": _spread(d_exit), "delta_rr_vs_D": _spread(d_rr),
                                     "band_changes_vs_D": bandch}
        s["levels"] = per
        heads = {}
        anyc = set()
        for h in CARD_HORIZONS:
            ids = {f["id"] for f in withp if option_levels(f, opt)[h][0]["band"] != option_levels(f, "D")[h][0]["band"]}
            heads[h] = len(ids)
            anyc |= ids
        s["step7_headline_band_changes_vs_D"] = {**heads, "either_card_horizon": len(anyc)}
        s["step7_headline_band_change_share_vs_D"] = (len(anyc) / len(withp)) if withp else None
        if opt in CALIBRATED_OPTIONS:
            cal = [f["calibrations"][opt] for f in fits]
            meth: dict[str, int] = {}
            for c in cal:
                meth[c["method"]] = meth.get(c["method"], 0) + 1
            s["methods"] = meth
            acc = [c for c in cal if c["accepted"]]
            s["accepted_rel_rmse"] = _spread([c["rel_rmse"] for c in acc])
            s["accepted_feller_ratio"] = _spread([c["feller_ratio"] for c in acc])
            sides: dict = {}
            for c in acc:
                for k, v in c["boundary_sides"].items():
                    sides.setdefault(k, {}).setdefault(v, 0)
                    sides[k][v] += 1
            s["winner_position"] = sides
            s["winners_all_interior"] = sum(1 for c in acc if all(v == "interior" for v in c["boundary_sides"].values()))
            s["winners_any_boundary"] = sum(1 for c in acc if any(v != "interior" for v in c["boundary_sides"].values()))
            ratios = [f["calibrations"][opt]["seconds_single_thread"] / f["calibrations"]["D"]["seconds_single_thread"]
                      for f in fits if f["calibrations"]["D"]["seconds_single_thread"] > 0]
            s["calibration_seconds_relative_to_D"] = {
                "per_fit": _spread(ratios),
                "sum_ratio": (sum(f["calibrations"][opt]["seconds_single_thread"] for f in fits)
                              / sum(f["calibrations"]["D"]["seconds_single_thread"] for f in fits)),
            }
        else:
            s["calibration_seconds_relative_to_D"] = {"per_fit": None, "sum_ratio": 1.0,
                                                      "note": "no extra calibration (reuses D's fit)"}
        s["levels_not_heston_on_labelled_fits"] = sum(
            f["options"][opt].get("levels_not_heston", 0) for f in withp if opt in ("D", "A_i", "A_ii", "C"))
        s["non_monotone_heston_ladders"] = sum(
            f["options"][opt].get("non_monotone_ladders", 0) for f in withp if opt in ("D", "A_i", "A_ii", "C"))
        out[opt] = s
    return out


def t1_consistency(fits: list[dict]) -> dict:
    """Option D re-calibrates every chain; it must reproduce T1's stored M2/M3
    method, rel-RMSE, params, scored proxy and Heston/mid."""
    stored: dict[str, dict] = {}
    m2p, m3p = OUT_DIR / "m2.json", OUT_DIR / "m3.json"
    if m2p.exists():
        for f in json.loads(m2p.read_text())["fits"]:
            stored[f"m2/{f['dte']}/{f['width']}/{f['regime']}/{f['right']}"] = f
    if m3p.exists():
        for c in json.loads(m3p.read_text())["captures"]:
            for x in c["chains"]:
                if x["status"] == "calibrated":
                    stored[f"m3/{c['capture'].split('/')[-1]}/{x['symbol']}/{x['expiry']}/{x['right']}"] = x
    mism = []
    for f in fits:
        s = stored.get(f["id"])
        d = f["calibrations"]["D"]
        if s is None:
            mism.append({"id": f["id"], "why": "not in T1 output"})
            continue
        why = []
        if s["method"] != d["method"]:
            why.append("method")
        if s["rel_rmse"] != d["rel_rmse"]:
            why.append("rel_rmse")
        if s["params"] != d["params"]:
            why.append("params")
        if s.get("accepted") and s.get("gaps", {}).get("scored_proxy"):
            sp = s["gaps"]["scored_proxy"]
            if f["proxy"] is None or sp["strike"] != f["proxy"]["strike"]:
                why.append("scored proxy")
            elif abs(sp["heston_over_mid"] - f["options"]["D"]["proxy_heston_over_mid"]) > 1e-9:
                why.append("heston_over_mid")
            else:
                for e in sp["exits"]:
                    for i, (lvl, mult) in enumerate(LADDER):
                        if abs(abs(e["move"]) - LADDER_BASE_MOVE * mult) < 1e-12:
                            lv = f["options"]["D"]["levels"][e["horizon"]][i]
                            if (lv["exit"], lv["rr"]) != (e["heston_exit"], e["heston_rr"]):
                                why.append(f"{e['horizon']}/{lvl} exit")
        if why:
            mism.append({"id": f["id"], "why": why})
    ids = {f["id"] for f in fits}
    return {"t1_fits": len(stored), "m4_fits": len(fits),
            "t1_fits_missing_from_m4": sorted(set(stored) - ids),
            "mismatches": mism, "all_match": not mism and set(stored) == ids}


# ── 2026-09 reconciliation: the chain the 1.36x figure most likely came from ──

def recon_2026_09() -> dict:
    """Today's shipped calibration on `heston_latency_probe.chain()` -- the
    synthetic chain committed with TIMEOUT-DELETE-INNER on 2026-09-13, the
    change whose round 2 logged the 1.36x / 0.48x figure. Same 6 DTE x 4 widths
    as M2. That chain: spot 201.86, the spec's section 7 reference smile
    (iv = 0.345 + 0.45*(-m) + 1.6*m^2), OTM only (calls above spot, puts
    below, in ONE chain), strikes on a $2.50 ladder over spot*(1 +- 0.45*sqrt(T)).
    Calibrated two ways: the whole chain (as that probe calibrates it) and
    scan.py's heston_chain filter. Deltas for the filter and the in-band set
    are BS at each strike's smile IV, rounded to 4 dp as market.py rounds."""
    import heston_latency_probe as lp
    cells = []
    for dte in M2_DTES:
        for n in M2_WIDTHS:
            raw = lp.chain(dte, n)
            T = dte / 365.0
            rows = []
            for c in raw:
                K, is_call = c["strike"], c["is_call"]
                m = math.log(K / lp.SPOT)
                iv = lp.ATM + lp.SKEW * (-m) + lp.CURV * m ** 2
                d1 = (math.log(lp.SPOT / K) + (lp.R + 0.5 * iv * iv) * T) / (iv * math.sqrt(T))
                delta = _norm_cdf(d1) if is_call else _norm_cdf(d1) - 1.0
                rows.append({"strike": K, "dte": dte, "price": c["mid_price"], "delta": round(delta, 4),
                             "right": "C" if is_call else "P", "iv": iv})
            lo, hi = selection_delta_band()
            for variant, chain in (("whole_chain", raw), ("scan_filtered", heston_chain(rows))):
                rec, res = calibrate(chain, lp.SPOT)
                entry = {"dte": dte, "n_strikes_requested": n, "chain_rows": len(rows), "variant": variant,
                         "calibrated_rows": len(chain), "method": rec["method"], "rel_rmse": rec["rel_rmse"],
                         "params": rec["params"]}
                if rec["accepted"]:
                    p = res.params
                    entry["feller_ratio"] = p.sigma_v ** 2 / (2.0 * p.kappa * p.theta)
                    per = []
                    for r in rows:
                        h = heston_price_detail(lp.SPOT, r["strike"], T, R, p, r["right"] == "C").price
                        per.append({"strike": r["strike"], "right": r["right"], "delta": r["delta"],
                                    "mid": r["price"], "heston_over_mid": h / r["price"],
                                    "in_band": lo <= abs(r["delta"]) <= hi})
                    entry["strikes"] = per
                    inb = [x for x in per if x["in_band"]]
                    entry["proxy"] = (min(inb, key=lambda x: (abs(abs(x["delta"]) - 0.5), x["strike"]))
                                      if inb else None)
                    entry["atm_nearest"] = min(per, key=lambda x: (abs(math.log(x["strike"] / lp.SPOT)), x["strike"]))
                    entry["in_band_spread"] = _spread([x["heston_over_mid"] for x in inb])
                    entry["out_of_band_spread"] = _spread([x["heston_over_mid"] for x in per if not x["in_band"]])
                    entry["all_spread"] = _spread([x["heston_over_mid"] for x in per])
                cells.append(entry)
    out = {"chain_source": "backend/scripts/heston_latency_probe.py chain()",
           "spot": lp.SPOT, "smile": {"atm": lp.ATM, "skew": lp.SKEW, "curvature": lp.CURV},
           "cells": cells}
    for variant in ("whole_chain", "scan_filtered"):
        cs = [c for c in cells if c["variant"] == variant]
        acc = [c for c in cs if c["method"] == "heston_grid"]
        winners: dict[str, int] = {}
        for c in acc:
            k = "kappa={kappa:g} theta={theta:g} sigma_v={sigma_v:g} rho={rho:g}".format(**c["params"])
            winners[k] = winners.get(k, 0) + 1
        out[variant] = {
            "cells": len(cs), "accepted": len(acc),
            "methods": {m: sum(1 for c in cs if c["method"] == m) for m in sorted({c["method"] for c in cs})},
            "winners": winners,
            "feller_ratio": _spread([c["feller_ratio"] for c in acc]),
            "proxy_heston_over_mid": _spread([c["proxy"]["heston_over_mid"] for c in acc if c["proxy"]]),
            "atm_nearest_heston_over_mid": _spread([c["atm_nearest"]["heston_over_mid"] for c in acc]),
            "in_band_heston_over_mid": _spread([x["heston_over_mid"] for c in acc for x in c["strikes"] if x["in_band"]]),
            "out_of_band_heston_over_mid": _spread([x["heston_over_mid"] for c in acc for x in c["strikes"]
                                                    if not x["in_band"]]),
            "proxy_by_dte": {str(d): _spread([c["proxy"]["heston_over_mid"] for c in acc if c["dte"] == d and c["proxy"]])
                             for d in M2_DTES},
        }
    return out


def run_options(limit: Optional[int] = None, progress: bool = True) -> dict:
    H = horizons()
    grids = option_grids()
    ctxs = options_contexts(limit)
    fits = []
    t0 = time.perf_counter()
    for i, ctx in enumerate(ctxs, 1):
        fits.append(evaluate_fit(ctx, H, grids))
        if progress and (i % 10 == 0 or i == len(ctxs)):
            print(f"  options: {i}/{len(ctxs)} fits, {time.perf_counter() - t0:.0f}s", file=sys.stderr, flush=True)
    return {
        "basis": ("Every result is about FITS (a calibrated chain and its scored proxy), never cards. "
                  "Exit premiums and R/R through shipped estimate_rr (full-premium basis, premium = mid) "
                  "except option C's anchored exits, which use estimate_rr's own arithmetic. "
                  "T1-T3 = the shipped ladder spacing (T2 = 1.5x, T3 = 2.0x the T1 move) with a "
                  f"{LADDER_BASE_MOVE:.0%} T1 move. Calibration seconds: single thread, this cloud box, "
                  "cache cleared before every calibration; relative to D only, not abandonment rates."),
        "grids": grids,
        "b_limits": list(B_LIMITS),
        "ladder": {"base_move": LADDER_BASE_MOVE, "levels": [list(x) for x in LADDER]},
        "summary": {"all": summarize_options(fits),
                    "m2": summarize_options([f for f in fits if f["source"] == "m2"]),
                    "m3": summarize_options([f for f in fits if f["source"] == "m3"])},
        "t1_consistency": t1_consistency(fits),
        "fits": fits,
    }


def _rel(s: dict) -> str:
    c = s["calibration_seconds_relative_to_D"]
    if c["per_fit"] is None:
        return "1 (no recalibration)"
    return f"{c['per_fit']['median']:.2f}× median ({c['per_fit']['min']:.2f}–{c['per_fit']['max']:.2f}); total {c['sum_ratio']:.2f}×"


def options_markdown(o: dict, recon: dict) -> str:
    L = ["# HESTON-RR-OVERPRICING — M4: options A–D on fits", "",
         "Generated by `backend/scripts/heston_rr_overpricing_probe.py --options`; machine output in `options.json`.", "",
         "**These are fits, not cards.** " + o["basis"], "",
         f"Fits: M2's {o['summary']['m2']['D']['fits']} synthetic fits and M3's {o['summary']['m3']['D']['fits']} real-chain "
         "fits, rebuilt exactly as T1 builds them. Option D re-calibrates every chain with the shipped default grid "
         "in the same run, so every A timing is paired with its own D timing.", ""]
    tc = o["t1_consistency"]
    L += [f"**Consistency with T1:** D reproduces T1's stored method, rel-RMSE, params, scored proxy, Heston÷mid and "
          f"the ±10 % / ±15 % exits on {tc['m4_fits'] - len(tc['mismatches'])} of {tc['m4_fits']} fits "
          f"(T1 stored {tc['t1_fits']}); all match: **{tc['all_match']}**."
          + (f" Mismatches: {tc['mismatches']}." if tc["mismatches"] else ""), "",
          "Grids: " + "; ".join(f"{k}: " + ", ".join(f"{n} {v}" for n, v in g.items()) for k, g in o["grids"].items()) + ".", ""]
    for part, title in (("m2", "M2 synthetic fits"), ("m3", "M3 real-chain fits"), ("all", "M2 + M3")):
        S = o["summary"][part]
        L += [f"## Summary — {title}", "",
              "Band change = the T1 (headline) Step 7 band differs from option D's, at the Swing or Position card "
              "horizon. Label = every T1–T3 level on every horizon priced \"Heston repriced\".", "",
              "| option | fits with proxy | labelled Heston | lost vs D | gained vs D | scored proxy Heston÷mid (min / median / max) | in-band Heston÷mid (min / median / max) | headline band changes vs D (swing / position / either) | calibration time vs D |",
              "|---|---|---|---|---|---|---|---|---|"]
        for opt in OPTION_ORDER:
            s = S[opt]
            hb = s["step7_headline_band_changes_vs_D"]
            share = s["step7_headline_band_change_share_vs_D"]
            nd = S["D"]["heston_labelled"]
            lost = (f"{s['label_lost_vs_D']} ({100 * s['label_lost_vs_D'] / nd:.1f} % of D's {nd}; "
                    f"{100 * s['label_lost_vs_D'] / s['fits_with_scored_proxy']:.1f} % of all)") if nd else str(s['label_lost_vs_D'])
            L.append(f"| {OPTION_TITLES[opt]} | {s['fits_with_scored_proxy']} | {s['heston_labelled']} | "
                     f"{lost} | {s['label_gained_vs_D']} | {_rng(s['proxy_heston_over_mid'])} | "
                     f"{'– (anchors the proxy only)' if opt == 'C' else _rng(s['in_band_heston_over_mid'])} | "
                     f"{hb['card_swing']} / {hb['card_position']} / {hb['either_card_horizon']} "
                     f"({_f(share * 100 if share is not None else None, 1)} %) | {_rel(s)} |")
        L.append("")
        L += ["Calibration outcome per option:", "",
              "| option | methods | accepted rel-RMSE (min / median / max) | Feller ratio (min / median / max) | winners with every parameter interior | winners on ≥1 boundary | winner position per parameter |",
              "|---|---|---|---|---|---|---|"]
        for opt in CALIBRATED_OPTIONS:
            s = S[opt]
            L.append(f"| {OPTION_TITLES[opt]} | {s['methods']} | {_rng(s['accepted_rel_rmse'], 4)} | "
                     f"{_rng(s['accepted_feller_ratio'], 2)} | {s['winners_all_interior']} | {s['winners_any_boundary']} | "
                     f"{s['winner_position']} |")
        L.append("")
        L += ["Change in the scored proxy's exit premium and full-premium R/R against D, per horizon and level "
              "(over the fits priced by Heston under D or under the option; all fits for the band count):", "",
              "| option | horizon / level | Δ exit $ (min / median / max) | Δ R/R (min / median / max) | band changes vs D |",
              "|---|---|---|---|---|"]
        for opt in OPTION_ORDER:
            if opt == "D":
                continue
            for k, v in S[opt]["levels"].items():
                L.append(f"| {opt} | {k} | {_rng(v['delta_exit_vs_D'], 3)} | {_rng(v['delta_rr_vs_D'], 2)} | "
                         f"{v['band_changes_vs_D']} |")
        L += ["", f"Heston levels that fell back to BS on labelled fits, per option: "
                  f"{ {opt: S[opt]['levels_not_heston_on_labelled_fits'] for opt in ('D', 'A_i', 'A_ii', 'C')} }; "
                  f"non-increasing Heston T1–T3 ladders: "
                  f"{ {opt: S[opt]['non_monotone_heston_ladders'] for opt in ('D', 'A_i', 'A_ii', 'C')} }.", ""]
    L += ["## 2026-09 reconciliation run", "",
          f"Today's shipped `calibrate_heston` (cache cleared) on `{recon['chain_source']}`: spot {recon['spot']}, "
          f"smile iv = {recon['smile']['atm']} + {recon['smile']['skew']}·(−m) + {recon['smile']['curvature']}·m², "
          "OTM calls above spot and OTM puts below in one chain, $2.50 strike ladder over spot·(1 ± 0.45·√T); "
          "the same 6 DTE × 4 widths as M2. Whole chain = as that probe calibrates it; scan-filtered = scan.py's "
          "heston_chain rule (deltas: BS at each strike's smile IV, 4 dp).", "",
          "| variant | cells | accepted | methods | winners (params: cells) | Feller ratio | scored proxy Heston÷mid | ATM-nearest Heston÷mid | in-band Heston÷mid | out-of-band Heston÷mid |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for v in ("whole_chain", "scan_filtered"):
        r = recon[v]
        L.append(f"| {v} | {r['cells']} | {r['accepted']} | {r['methods']} | {r['winners']} | {_rng(r['feller_ratio'], 2)} | "
                 f"{_rng(r['proxy_heston_over_mid'])} | {_rng(r['atm_nearest_heston_over_mid'])} | "
                 f"{_rng(r['in_band_heston_over_mid'])} | {_rng(r['out_of_band_heston_over_mid'])} |")
    L += ["", "Scored proxy Heston÷mid by DTE:", "", "| variant | " + " | ".join(str(d) for d in M2_DTES) + " |",
          "|---|" + "---|" * len(M2_DTES)]
    for v in ("whole_chain", "scan_filtered"):
        L.append(f"| {v} | " + " | ".join(_rng(recon[v]["proxy_by_dte"][str(d)]) for d in M2_DTES) + " |")
    L += ["", "## Limits", "",
          "- Fits, not cards: no stored card carries the chain, fit or parameters an option needs.",
          "- T1–T3 use a fixed 10 % / 15 % / 20 % stock move, not each card's own ATR-derived target.",
          "- Calibration seconds are single-thread on this cloud box (cache cleared each time) and are compared "
          "relative to D only. Scan abandonment at the 2.0 s guard is driven by GIL queueing under concurrency, so "
          "these are not abandonment rates.",
          "- M3: five captures from 3–5 October 2026, seven symbols, near-dated expiries only; parity spot has no "
          "dividend term.", ""]
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
    ap.add_argument("--options", action="store_true",
                    help="M4 only (T2): options A-D on M2's and M3's fits -> options.json / options.md")
    ap.add_argument("--options-render", action="store_true",
                    help="re-render options.md from the committed options.json (no calibration)")
    ap.add_argument("--options-limit", type=int, default=None,
                    help="development only: the first N M2 and N M3 fits (outputs are NOT written)")
    args = ap.parse_args(argv)
    which = args.only or ["m1", "m2", "m3"]

    logging.getLogger("app").setLevel(logging.ERROR)
    warnings.simplefilter("ignore")      # scipy IntegrationWarning from the shipped pricer

    if args.options_render:
        doc = json.loads((OUT_DIR / "options.json").read_text())
        _write("options.md", options_markdown(doc, doc["recon_2026_09"]))
        print("M4 markdown re-rendered from options.json")
        return 0

    if args.options:
        with forbid_network():
            prov = provenance()
            o = run_options(limit=args.options_limit)
            recon = recon_2026_09()
            doc = {"provenance": prov, **o, "recon_2026_09": recon}
            if args.options_limit:
                out = Path(os.environ.get("TMPDIR", "/tmp")) / "heston_options_dev.json"
                out.write_text(json.dumps(doc, indent=1, allow_nan=False, default=str) + "\n")
                print(options_markdown(o, recon))
                print(f"dev run: {out}")
            else:
                _write("options.json", doc)
                _write("options.md", options_markdown(o, recon))
                print("M4 written")
        return 0

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
