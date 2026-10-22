"""T1 tests for `scripts/heston_rr_overpricing_probe.py` (HESTON-RR-OVERPRICING).

Plan: docs/superpowers/plans/2026-10-22-heston-rr-overpricing-plan.md, section 4 T1.
Exactly the five checks the plan lists:

  1. the probe's `heston_chain` re-implementation matches scan.py's source
     block (pinned by AST) and reads the app's constants at call time;
  2. the M3 replay, two captures in ONE process (2026-10-03 and 2026-10-05),
     makes the shipped `fetch_option_chain_async` return exactly each
     capture's rows -- count, ids, expiry, mids, and dte equal to the stored dte;
  3. put-call-parity spot on a fixture;
  4. M1 input recovery reproduces a fixture non-Heston card's ladder to +-$0.01;
  5. `cache_clear` is called before each calibration (a spy).

No network: every test runs under a socket guard.
"""
from __future__ import annotations

import ast
import json
import math
import socket
import sys
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

import heston_rr_overpricing_probe as probe  # noqa: E402
from app.models import heston_cache as hc  # noqa: E402
from app.routers import scan as scan_mod  # noqa: E402
from app.data.strike import canonical_strike, format_strike  # noqa: E402

CAPTURES = BACKEND / "scripts" / "out" / "tradier_chain_raw"
CAPTURE_1003 = CAPTURES / "20261003T210145Z_weekend"
CAPTURE_1005 = CAPTURES / "20261005T160001Z_in-session"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _refuse(*_a, **_k):
        raise AssertionError("network access attempted during a probe test")
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)


# ── 1. heston_chain parity with scan.py ──────────────────────────────────────

# ast.unparse of scan.py `_process_symbol`'s Heston block, from the
# hard_reject_delta_band() read through the `heston_chain = [...]` assignment.
# A change to that block in scan.py changes this text and fails the test, so
# the probe's re-implementation has to be re-checked.
PINNED_SCAN_BLOCK = """\
_default_min_delta, _default_max_delta = hard_reject_delta_band()
_cfg_min_delta = float(contract_overrides.get('min_delta', _default_min_delta))
_cfg_max_delta = float(contract_overrides.get('max_delta', _default_max_delta))
_calib_delta_lo = max(0.0, round(_cfg_min_delta - _HESTON_DELTA_SAFETY_MARGIN, 6))
_calib_delta_hi = min(1.0, round(_cfg_max_delta + _HESTON_DELTA_SAFETY_MARGIN, 6))

def _heston_delta_ok(entry: dict) -> bool:
    d = abs(float(entry.get('delta') or 0))
    if d == 0.0:
        return True
    return _calib_delta_lo <= d <= _calib_delta_hi
heston_chain = [{'strike': float(c.get('strike', 0)), 'expiry_years': c.get('dte', 30) / 365.0, 'mid_price': float(c.get('price', 0)), 'is_call': c.get('right', 'C') == 'C'} for c in chain if float(c.get('price', 0)) > 0 and _heston_delta_ok(c)]"""


def _scan_block() -> ast.Module:
    tree = ast.parse((BACKEND / "app" / "routers" / "scan.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_process_symbol")
    guard = next(n for n in ast.walk(fn)
                 if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                 and n.test.id == "_HESTON_PRICING_ENABLED")
    body: list[ast.stmt] = []
    for stmt in guard.body[0].body:          # the `try:` body
        body.append(stmt)
        if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "heston_chain" for t in stmt.targets):
            break
    return ast.Module(body=body, type_ignores=[])


def _run_scan_block(chain: list[dict], overrides: dict, band, margin) -> list[dict]:
    ns = {"hard_reject_delta_band": band, "_HESTON_DELTA_SAFETY_MARGIN": margin,
          "contract_overrides": overrides, "chain": chain}
    exec(compile(_scan_block(), "<scan.py heston block>", "exec"), ns)
    return ns["heston_chain"]


_CHAIN_FIXTURE = [
    {"strike": 90.0, "dte": 30, "price": 11.2, "delta": 0.9001, "right": "C"},  # just outside
    {"strike": 95.0, "dte": 30, "price": 6.9, "delta": 0.9, "right": "C"},     # = 0.85 + 0.05 edge
    {"strike": 97.5, "dte": 30, "price": 5.1, "delta": 0.7012, "right": "C"},
    {"strike": 100.0, "dte": 30, "price": 3.4, "delta": 0.5, "right": "C"},
    {"strike": 105.0, "dte": 30, "price": 1.2, "delta": 0.15, "right": "C"},    # = 0.20 - 0.05 edge
    {"strike": 110.0, "dte": 30, "price": 0.35, "delta": 0.1499, "right": "C"},  # just outside
    {"strike": 115.0, "dte": 30, "price": 0.05, "delta": 0.0, "right": "C"},     # fail open
    {"strike": 120.0, "dte": 30, "price": 0.0, "delta": 0.0, "right": "C"},      # price 0 dropped
    {"strike": 95.0, "dte": 30, "price": 1.1, "delta": -0.3, "right": "P"},      # put, |delta|
    {"strike": 80.0, "dte": 30, "price": 0.2, "delta": None, "right": "P"},      # None -> 0 -> kept
]


def test_heston_chain_matches_scan_source_block_and_reads_app_constants(monkeypatch):
    assert ast.unparse(_scan_block()) == PINNED_SCAN_BLOCK

    expected = _run_scan_block(_CHAIN_FIXTURE, {}, scan_mod.hard_reject_delta_band,
                               scan_mod._HESTON_DELTA_SAFETY_MARGIN)
    assert probe.heston_chain(_CHAIN_FIXTURE) == expected
    assert len(expected) == 7            # the fixture exercises both edges and fail-open

    # Overrides are honoured exactly as scan.py honours them.
    ov = {"min_delta": 0.3, "max_delta": 0.6}
    assert probe.heston_chain(_CHAIN_FIXTURE, ov) == _run_scan_block(
        _CHAIN_FIXTURE, ov, scan_mod.hard_reject_delta_band, scan_mod._HESTON_DELTA_SAFETY_MARGIN)

    # The probe reads the APP's band and margin at call time, not copies.
    monkeypatch.setattr(scan_mod, "_HESTON_DELTA_SAFETY_MARGIN", 0.0)
    monkeypatch.setattr(scan_mod, "hard_reject_delta_band", lambda: (0.4, 0.6))
    patched = probe.heston_chain(_CHAIN_FIXTURE)
    assert patched == _run_scan_block(_CHAIN_FIXTURE, {}, lambda: (0.4, 0.6), 0.0)
    assert patched != expected


# ── 2. M3 replay through the shipped fetch_option_chain_async ────────────────

def _expected_rows(capture: dict, symbol: str, expiry: str, right: str) -> list[dict]:
    want = "call" if right == "C" else "put"
    out, seen = [], set()
    for r in capture["rows"]:
        if r["symbol"] != symbol or r["expiry"] != expiry or r["option_type"] != want:
            continue
        bid, ask = float(r["bid"] or 0), float(r["ask"] or 0)
        if not ask > 0:
            continue
        try:
            strike = canonical_strike(r["strike"])
        except (TypeError, ValueError):
            continue
        rid = f"{symbol}|{format_strike(strike)}|{expiry}|{right}"
        if rid in seen:
            continue
        seen.add(rid)
        out.append({"id": rid, "expiry": expiry, "price": round((bid + ask) / 2, 2), "dte": r["dte"]})
    return out


def test_m3_replay_two_captures_in_one_process_returns_each_captures_rows():
    caps = [probe.load_capture(CAPTURE_1003), probe.load_capture(CAPTURE_1005)]
    assert [probe.capture_et_date(c).isoformat() for c in caps] == ["2026-10-03", "2026-10-05"]
    chains = 0
    for cap in caps:
        for symbol, expiries in cap["meta"]["expiries"].items():
            for expiry in expiries:
                for right in ("C", "P"):
                    rows, transport = probe.replay_chain(cap, symbol, expiry, right)
                    want = _expected_rows(cap, symbol, expiry, right)
                    assert transport.raised == [], (symbol, expiry, right)
                    assert transport.anomalies == [], (symbol, expiry, right)
                    assert len(want) > 0
                    assert len(rows) == len(want), (symbol, expiry, right)
                    assert [r["id"] for r in rows] == [w["id"] for w in want]
                    assert all(r["expiry"] == expiry for r in rows)
                    assert [r["price"] for r in rows] == [w["price"] for w in want]
                    assert [r["dte"] for r in rows] == [w["dte"] for w in want]
                    chains += 1
    assert chains == 2 * (11 + 14)


def test_m3_replay_mock_raises_on_unknown_requests():
    cap = probe.load_capture(CAPTURE_1003)
    # The mock itself raises (not 404) on an expiry or symbol the capture lacks.
    transport = probe.CaptureTransport(cap)
    with pytest.raises(probe.ReplayRequestError):
        transport(httpx.Request("GET", f"{probe.REPLAY_BASE}/v1/markets/options/chains",
                                params={"symbol": "AAPL", "expiration": "2026-11-20", "greeks": "true"}))
    assert len(transport.raised) == 1
    # Unknown symbol through the shipped fetch: it swallows the error into [],
    # so the probe must have recorded it.
    rows, transport = probe.replay_chain(cap, "ZZZZ", "2026-10-09", "C")
    assert rows == [] and len(transport.raised) == 1
    # Unlisted expiry: the shipped fetch never asks for it, it silently
    # substitutes a listed one -- the probe flags that as an anomaly.
    rows, transport = probe.replay_chain(cap, "AAPL", "2026-11-20", "C")
    assert rows and transport.anomalies


# ── 3. put-call-parity spot ──────────────────────────────────────────────────

def _pair(symbol, expiry, dte, strike, call_mid, put_mid, put_two_sided=True):
    def row(kind, mid, two):
        bid = round(mid - 0.05, 2) if two else 0.0
        ask = round(mid + 0.05, 2) if two else round(2 * mid, 2)
        return {"symbol": symbol, "expiry": expiry, "dte": dte, "strike": strike,
                "option_type": kind, "bid": bid, "ask": ask}
    return [row("call", call_mid, True), row("put", put_mid, put_two_sided)]


def test_parity_spot_on_fixture():
    S, r = 100.0, 0.05

    def call_for(put, K, dte):
        return round(put + S - K * math.exp(-r * dte / 365.0), 2)

    rows = []
    for K, put in ((95.0, 1.10), (105.0, 6.20)):
        rows += _pair("FIX", "2026-11-01", 30, K, call_for(put, K, 30), put)
    # Nearer the money on the same expiry, but the put is one-sided: not usable.
    rows += _pair("FIX", "2026-11-01", 30, 100.0, call_for(3.0, 100.0, 30), 3.0, put_two_sided=False)
    # A later expiry carries the nearest-the-money two-sided pair overall.
    rows += _pair("FIX", "2026-12-01", 60, 100.0, call_for(4.4, 100.0, 60), 4.4)
    # A symbol with no two-sided pair at all.
    rows += _pair("NOPE", "2026-11-01", 30, 50.0, 1.0, 1.0, put_two_sided=False)

    got = probe.parity_spot(rows, "FIX", r=r)
    assert got["strike"] == 100.0 and got["expiry"] == "2026-12-01" and got["dte"] == 60
    assert got["spot"] == pytest.approx(S, abs=0.01)
    assert got["spot"] == pytest.approx(got["call_mid"] - got["put_mid"]
                                        + 100.0 * math.exp(-r * 60 / 365.0), abs=1e-9)
    assert probe.parity_spot(rows, "NOPE", r=r) is None


# ── 4. M1 input recovery ─────────────────────────────────────────────────────

# A non-Heston card, copied from the committed 2026-10-01 scan
# O2-options-position-bullish (REC-20261001-833BAC31), MU, with its request's
# horizon fields. Only the fields M1's recovery reads are kept.
_FIXTURE_CARD = {
    "symbol": "MU", "price": 1072.665, "direction": "Bullish",
    "contract": "MU|1050|2026-11-20|C",
    "contractDetails": {"strike": 1050, "expiry": "2026-11-20", "right": "C",
                        "mid": 100.68, "delta": 0.5662, "dte": 50},
    "entry": {"limit": 100.68, "maxFill": 103.7, "orderType": "Limit"},
    "exit": {
        "invalidation": 441.44, "premiumStop": 60.41, "timeStopDays": 20, "target": 1158.48,
        "targets": [
            {"targetPrice": 1158.48, "stockPrice": 1158.48, "estimatedOptionPrice": 145.15,
             "pricingMethod": "BS repriced (IV-derived)", "rrContribution": 0.74},
            {"targetPrice": 1201.38, "stockPrice": 1201.38, "estimatedOptionPrice": 178.9,
             "pricingMethod": "BS repriced (IV-derived)", "rrContribution": 1.29},
            {"targetPrice": 1244.29, "stockPrice": 1244.29, "estimatedOptionPrice": 215.03,
             "pricingMethod": "BS repriced (IV-derived)", "rrContribution": 1.89},
        ],
        "finalStop": {"price": 441.44, "source": "final_stop"},
    },
    "rrRatio": 0.74, "rrModel": "BS repriced (IV-derived)", "stopCostPct": 100.0,
}
_FIXTURE_REQUEST = {"direction": "Bullish", "horizon": "Position", "horizon_preset": "Position",
                    "hold_min_days": 15, "hold_max_days": 45, "overrides": {"ma_type": "EMA"}}


def test_m1_input_recovery_reproduces_fixture_non_heston_ladder():
    rec = probe.recover_card(_FIXTURE_CARD, _FIXTURE_REQUEST)
    assert rec["reproducible"] is True
    assert len(rec["levels"]) == 3
    for lvl in rec["levels"]:
        assert abs(lvl["recovered_est"] - lvl["stored_est"]) <= 0.01 + 1e-9
    assert [lvl["recovered_est"] for lvl in rec["levels"]] == pytest.approx(
        [145.15, 178.9, 215.03], abs=0.01 + 1e-9)

    # A wrong input must be caught, not absorbed.
    broken = json.loads(json.dumps(_FIXTURE_CARD))
    broken["contractDetails"]["dte"] = 40
    assert probe.recover_card(broken, _FIXTURE_REQUEST)["reproducible"] is False


# ── 5. cache_clear before every calibration ──────────────────────────────────

def test_cache_clear_is_called_before_each_calibration(monkeypatch):
    events: list[str] = []
    real = hc._run_calibration

    class _Spy:
        __wrapped__ = real.__wrapped__

        def __call__(self, *a, **k):
            events.append("calibrate")
            return real(*a, **k)

        def cache_clear(self):
            events.append("cache_clear")
            real.cache_clear()

    monkeypatch.setattr(hc, "_run_calibration", _Spy())

    rows = probe.m2_rows(dte=30, width=15, atm=0.20, skew=-0.10, right="C")
    chain = probe.heston_chain(rows)
    probe.calibrate(chain, probe.SPOT)
    probe.calibrate(chain, probe.SPOT)        # same chain: must still recompute
    assert events == ["cache_clear", "calibrate", "cache_clear", "calibrate"]

    events.clear()
    out = probe.run_m2(cells=[(30, 15, "atm20_mild"), (180, 25, "atm35_steep")])
    n_fits = len(out["fits"])
    assert n_fits == 4                       # per cell: one call chain, one put chain
    assert events.count("cache_clear") == n_fits
    # calibrate_cached returns bs_fallback for a < 3-strike chain without
    # reaching _run_calibration; every other fit must reach it, cleared first.
    assert events.count("calibrate") == sum(1 for f in out["fits"] if f["strikes"] >= 3) >= 2
    for i, e in enumerate(events):
        if e == "calibrate":
            assert i > 0 and events[i - 1] == "cache_clear"


# ── T2 (M4): the script-local `_run_calibration` copy and the option helpers ──
#
# Plan section 2, M4 option A: the wider box runs through a SCRIPT-LOCAL copy of
# `_run_calibration` that takes the grids as arguments; a test pins that copy
# against the shipped function (same method, rmse and params on the default grid
# for fixture chains). Also pinned here: the copy's search loop is the shipped
# loop verbatim, the copy equals the shipped function on the 3-rung full grid,
# option C's anchored leg reduces to estimate_rr's Heston leg at anchor 1, and
# every option's calibration clears the shipped lru_cache first.

def _fixture_chains():
    out = []
    for dte, width, regime, right in ((45, 15, "atm20_steep", "C"), (365, 15, "atm35_steep", "P"),
                                      (90, 25, "atm20_mild", "P")):
        atm, skew = probe.M2_REGIMES[regime]
        out.append((f"m2/{dte}/{width}/{regime}/{right}",
                    probe.heston_chain(probe.m2_rows(dte, width, atm, skew, right)), probe.SPOT))
    cap = probe.load_capture(CAPTURE_1003)
    rows, _ = probe.replay_chain(cap, "AAPL", "2026-10-30", "C")
    spot = probe.parity_spot(cap["rows"], "AAPL")["spot"]
    out.append(("m3/1003/AAPL/2026-10-30/C", probe.heston_chain(rows), spot))
    rows, _ = probe.replay_chain(cap, "AAPL", "2026-10-09", "C")      # the gate rejects this one (bs_flat)
    out.append(("m3/1003/AAPL/2026-10-09/C", probe.heston_chain(rows), spot))
    return out


def _shipped(chain, S, full=False, monkeypatch=None):
    hc._run_calibration.cache_clear()
    if full:
        monkeypatch.setattr(hc, "_USE_FULL_GRID", True)
    try:
        return probe.heston_mod.calibrate_heston(chain, S, probe.R)
    finally:
        if full:
            monkeypatch.setattr(hc, "_USE_FULL_GRID", False)


def test_local_run_calibration_copy_matches_shipped_on_default_and_full_grid(monkeypatch):
    grids = probe.shipped_grids()
    methods = set()
    for name, chain, S in _fixture_chains():
        want = _shipped(chain, S)
        got = probe.calibrate_with_grids(chain, S, grids["default"])
        assert (got.method, got.rmse, got.params) == (want.method, want.rmse, want.params), name
        methods.add(want.method)
    assert {"heston_grid", "bs_flat"} <= methods        # both sides of the gate are exercised
    name, chain, S = _fixture_chains()[0]
    want = _shipped(chain, S, full=True, monkeypatch=monkeypatch)
    got = probe.calibrate_with_grids(chain, S, grids["full"])
    assert (got.method, got.rmse, got.params) == (want.method, want.rmse, want.params)
    # The wider box actually reaches rungs the shipped grids do not have.
    assert set(probe.WIDE_GRID["kappa"]) > set(grids["full"]["kappa"])


def test_local_copy_search_loop_is_the_shipped_loop_verbatim():
    def _loop(fn):
        tree = ast.parse(probe._dedent(probe.inspect.getsource(fn)))
        return next(ast.unparse(n) for n in ast.walk(tree)
                    if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "v0")
    assert _loop(probe.run_calibration_with_grids) == _loop(hc._run_calibration.__wrapped__)


def test_anchored_leg_with_unit_anchor_equals_estimate_rr_heston_leg():
    from app.models.heston import HestonParams
    from app.scoring.reward_risk import estimate_rr
    p = HestonParams(v0=0.06, kappa=0.5, theta=0.08, sigma_v=0.6, rho=-0.8)
    for is_call, target, ry in ((True, 110.0, 20 / 365), (False, 90.0, None)):
        res = estimate_rr(stock_price=100.0, target_price=target, invalidation_price=100.0, strike=100.0,
                          expiry_years=60 / 365, current_premium=4.37, is_call=is_call, r=probe.R,
                          reprice_years=ry, heston_params=p)
        leg = probe.anchored_leg(p, target, 100.0, 60 / 365, 4.37, is_call, ry, 1.0)
        assert res.model_used == "Heston repriced"
        assert (leg["exit"], leg["rr"]) == (res.estimated_exit_premium, res.rr_ratio)
        half = probe.anchored_leg(p, target, 100.0, 60 / 365, 4.37, is_call, ry, 0.5)
        assert half["exit"] < leg["exit"]


def test_calibrate_option_clears_cache_before_every_option(monkeypatch):
    events: list = []
    real = hc._run_calibration

    class _Spy:
        __wrapped__ = real.__wrapped__

        def __call__(self, *a, **k):
            events.append(("calibrate", hc._USE_FULL_GRID))
            return real(*a, **k)

        def cache_clear(self):
            events.append("cache_clear")
            real.cache_clear()

    monkeypatch.setattr(hc, "_run_calibration", _Spy())
    real_copy = probe.calibrate_with_grids
    monkeypatch.setattr(probe, "calibrate_with_grids",
                        lambda *a, **k: (events.append(("copy", a[2] is probe.WIDE_GRID)), real_copy(*a, **k))[1])
    name, chain, S = _fixture_chains()[0]
    for which in ("D", "A_i", "A_ii", "D"):
        probe.calibrate_option(chain, S, which)
    assert events == ["cache_clear", ("calibrate", False), "cache_clear", ("calibrate", True),
                      "cache_clear", ("copy", True), "cache_clear", ("calibrate", False)]
    assert hc._USE_FULL_GRID is False
