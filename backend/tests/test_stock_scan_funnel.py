"""StockPipeline's funnel counters — the stock half of the funnel fix.

Nothing exercised StockPipeline before this file: `failed_direction`,
`failed_shortlist` and the residual `other_rejected` were all wired up on the
strength of reading the code. The stock funnel had the same defect the options
one was fixed for — the backend counted `failed_regime` and `other_rejected`
and the UI rendered neither, so stock-mode direction_conviction rejections were
absorbed into a bucket nobody could see.

The invariant pinned here matches the options one:
    scanned == candidates + every drop bucket

KNOWN GAP: `failed_shortlist` is never exercised with a non-zero value. Getting
a symbol all the way through to being a candidate needs a real strategy signal
AND a passing backtest, which means mocking `_SIGNAL_FNS` and
`run_strategy_backtest` deeply enough that the test would mostly be asserting
its own mocks. The identical `original_count - len(candidates)` arithmetic IS
covered on the options side (test_scan_direction_funnel.py's cap test), so this
is left uncovered deliberately rather than faked.
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers.stock_scan import router as stock_scan_router
from tests.conftest import _override_get_db


@pytest.fixture
def stock_client():
    app = FastAPI()
    app.include_router(stock_scan_router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


_BARS = [
    {"time": f"2024-01-{d:02d}", "open": 150.0, "high": 155.0,
     "low": 148.0, "close": 152.0, "volume": 1_000_000}
    for d in range(1, 62)
]


def _card(trend: int):
    """A PASS card whose only interesting axis is the trend rule score — the
    single field the direction-conviction gate reads."""
    rule = MagicMock()
    rule.name = "trend"
    rule.score = trend
    card = MagicMock()
    card.status = "PASS"
    card.score = 70
    card.rules = [rule]
    return card


def _accounted(p: dict) -> int:
    return (
        p["candidates"]
        + p["failed_history"]
        + p["failed_score"]
        + p["failed_signal"]
        + p["failed_backtest"]
        + p["failed_regime"]
        + p["failed_direction"]
        + p["failed_shortlist"]
        + p["other_rejected"]
    )


def _run(stock_client, symbols, *, direction, horizon, score_stock, **body):
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.stock_scan.fetch_quotes", return_value={}))
        stack.enter_context(patch(
            "app.routers.stock_scan.get_historical_bars", AsyncMock(return_value=_BARS)))
        stack.enter_context(patch("app.routers.stock_scan.score_stock", score_stock))
        stack.enter_context(patch(
            "app.routers.stock_scan.fetch_company_name_async", AsyncMock(return_value="Test")))
        stack.enter_context(patch(
            "app.routers.stock_scan.fetch_price_async", AsyncMock(return_value=152.0)))
        r = stock_client.post("/api/stock-scan", json={
            "symbols": symbols, "universe": [], "direction": direction,
            "horizon": horizon, "strategy": "pullback_ema", **body,
        })
    assert r.status_code == 200, r.text
    return r.json()


def test_direction_gated_symbols_get_their_own_bucket(stock_client):
    """Bearish/Position drops trend < 40. Those rejections used to be absorbed
    into other_rejected, where the funnel never showed them at all.

    trend=10 rather than the 60 this used to pass: the gate is a FLOOR in both
    directions now, so 60 on a Bearish scan is a strong downtrend and survives.
    """
    body = _run(stock_client, ["AAA", "BBB"], direction="Bearish", horizon="Position",
                score_stock=MagicMock(return_value=_card(10)))

    pipeline = body["pipeline"]
    assert pipeline["failed_direction"] == 2
    assert pipeline["other_rejected"] == 0, "direction rejections leaked into the residual"
    assert pipeline["candidates"] == len(body["candidates"]) == 0
    assert _accounted(pipeline) == pipeline["scanned"] == 2
    assert body["direction_banner"], "an empty stock table must explain itself too"


def test_a_raising_symbol_lands_in_the_residual_not_nowhere(stock_client):
    """Exceptions are recorded as str(exc), which matches no reason predicate."""
    def _boom(*_a, **_kw):
        raise RuntimeError("")

    body = _run(stock_client, ["AAA"], direction="Bearish", horizon="Position",
                score_stock=MagicMock(side_effect=_boom))

    pipeline = body["pipeline"]
    assert pipeline["other_rejected"] == 1
    assert _accounted(pipeline) == pipeline["scanned"] == 1


# The gate, spelled out INDEPENDENTLY of the code that implements it.
#
# Deliberately literal rather than read back from config_loader or the YAML: a
# test that derives its expectations from the thing under test asserts only
# that the code equals itself. These numbers are the contract, and a change to
# the YAML is supposed to fail here so that whoever makes it has to say so.
#
# A FLOOR on both sides, and the two sides MIRROR each other. The bearish side
# was a `max_trend` CEILING (50 Swing / 40 Position) until 2026-09-16, which
# inverted the gate: because every trend method in stock_scorer.py is
# direction-aware, a high trend score on a Bearish scan means a strong
# DOWNtrend, so the ceiling deleted the best short setups and kept the names
# that were not falling.
_MIRRORED_FLOORS: dict[tuple[str, str], int | None] = {
    ("Bearish", "Swing"):    30,
    ("Bearish", "Position"): 40,
    ("Bullish", "Swing"):    30,
    ("Bullish", "Position"): 40,
    ("Bearish", "Intraday"): None,   # exempt
    ("Bullish", "Intraday"): None,   # exempt
}


@pytest.mark.parametrize("direction,horizon,trend,gated", [
    # The four non-Intraday pairs, at one point either side of each floor.
    ("Bearish", "Position", 39, True),  ("Bearish", "Position", 40, False),
    ("Bearish", "Swing",    29, True),  ("Bearish", "Swing",    30, False),
    ("Bullish", "Position", 39, True),  ("Bullish", "Position", 40, False),
    ("Bullish", "Swing",    29, True),  ("Bullish", "Swing",    30, False),
    # A STRONG trend in the traded direction survives on BOTH sides. The
    # bearish half of this is the regression that matters: under the old
    # ceiling, trend 85 on a Bearish scan was thrown away.
    ("Bearish", "Position", 85, False), ("Bullish", "Position", 85, False),
    # Intraday is exempt in both modes, at any trend score.
    ("Bearish", "Intraday", 99, False), ("Bullish", "Intraday", 1,  False),
])
def test_stock_gate_matches_the_mirrored_floor_contract(
    stock_client, direction, horizon, trend, gated,
):
    """The stock endpoint screens on the floors in _MIRRORED_FLOORS.

    Both scan modes now resolve their threshold through the one function
    (services/config_loader.load_direction_conviction_min_trend), so the drift
    this test used to guard — a dict in routers/scan.py and an if/else in
    routers/stock_scan.py, edited apart — is no longer possible by
    construction. What is asserted instead is the behaviour itself, end to end
    through the real endpoint.
    """
    floor = _MIRRORED_FLOORS[(direction, horizon)]
    assert gated == (floor is not None and trend < floor), (
        "the parametrize case disagrees with the floor contract it is meant to "
        "exercise — fix the case, not the assertion"
    )

    body = _run(stock_client, ["AAA"], direction=direction, horizon=horizon,
                score_stock=MagicMock(return_value=_card(trend)))
    assert body["pipeline"]["failed_direction"] == (1 if gated else 0)


@pytest.mark.parametrize("horizon", ["Swing", "Position"])
def test_the_bearish_gate_is_a_floor_not_a_ceiling(stock_client, horizon):
    """The inversion regression, asserted THROUGH THE ENDPOINT.

    On a Bearish scan the trend rule scores how strongly price is falling, so
    the STRONGEST short setup scores HIGHEST. A gate that drops high scores on
    the bearish side deletes exactly the candidates the scan exists to find —
    which is what shipped between 2026-06-18 and 2026-09-16.

    This has to run the real request. An earlier version asserted `95 >= floor`
    against the number the resolver returns, which cannot fail no matter which
    way the routers compare against it: flipping `<` to `>` in the gate left
    that version green. The two cases below are the actual regression — a
    textbook downtrend surviving, a structureless name being dropped — and
    re-inverting the comparison breaks the first of them.
    """
    strong_downtrend = _run(stock_client, ["AAA"], direction="Bearish", horizon=horizon,
                            score_stock=MagicMock(return_value=_card(95)))
    assert strong_downtrend["pipeline"]["failed_direction"] == 0, (
        f"Bearish/{horizon} threw away a trend score of 95 — the strongest "
        f"short setup there is. The gate is inverted again."
    )

    no_structure = _run(stock_client, ["AAA"], direction="Bearish", horizon=horizon,
                        score_stock=MagicMock(return_value=_card(5)))
    assert no_structure["pipeline"]["failed_direction"] == 1, (
        f"Bearish/{horizon} admitted a trend score of 5 — the gate no longer "
        f"removes candidates with no directional structure, which is its job."
    )


#  Verbatim from their producers in routers/stock_scan.py. Three of these were
#  landing in the residual until round 2: "insufficient intraday history" does
#  not contain "insufficient history", and the mean_reversion_multi misses
#  start with "no " but never say "setup". Nothing but this test stops that
#  regressing — the residual hides a misclassification from the sum invariant.
_REAL_STOCK_REASONS = [
    ("insufficient history",                              "failed_history"),
    ("insufficient intraday history",                     "failed_history"),
    ("no price data",                                     "failed_history"),
    ("price $3.10 < min",                                 "failed_history"),
    ("REJECT score=20",                                   "failed_score"),
    ("direction_conviction: trend 20 < 40 for Bearish Position", "failed_direction"),
    ("direction_conviction_unmeasured: no trend measurement for Bullish Swing",
     "failed_direction_unmeasured"),
    ("REJECT score=40 < min 50", "failed_score"),
    ("regime headwind",                                   "failed_regime"),
    ("no pullback_ema setup",                             "failed_signal"),
    ("no mean_reversion_multi: 2/3 signals fired",        "failed_signal"),
    ("mean_reversion_multi: variants produced no valid combined levels", "failed_signal"),
    ("backtest gate: 38% win over 12 trades",             "failed_backtest"),
    ("confidence gate REJECT: 41% < 50%",                 "failed_backtest"),
    ("unknown strategy wat",                              "other_rejected"),
]


@pytest.mark.parametrize("reason,bucket", _REAL_STOCK_REASONS)
def test_each_real_stock_reason_lands_in_its_own_bucket(reason, bucket):
    """The classifier is the one place the funnel's honesty is decided, and it
    is pure string matching over text produced elsewhere in the router. Pin
    every real reason to its bucket: reword a producer without updating the
    classifier and this fails, instead of the reason silently sliding into the
    residual where the sum invariant cannot see it."""
    from app.routers.stock_scan import classify_stock_rejection

    assert classify_stock_rejection(reason) == bucket


def test_every_stock_reason_producer_is_classified():
    """Guards the list above against going stale: every literal reason this
    module emits must appear in _REAL_STOCK_REASONS, so a NEW rejection reason
    cannot be added without deciding which bucket it belongs to.

    The regex allows an optional newline+indent before the string because the
    confidence gate writes `"reason": (` then a parenthesised f-string on the
    next line — a form the first version of this guard was silently blind to.
    """
    import inspect, re
    from app.routers import stock_scan as mod

    src = inspect.getsource(mod)
    emitted = {
        s.strip() for s in re.findall(r'"reason":\s*\(?\s*f?"([^"{]*)', src)
    }
    emitted = {s for s in emitted if s}
    # Without this floor, any reformatting that stops the regex matching would
    # make the whole test pass on an empty set.
    assert len(emitted) >= 10, (
        f"reason-producer regex matched only {sorted(emitted)} — it has gone "
        f"stale against the source and this test is no longer guarding anything"
    )
    for required in ("confidence gate ", "unknown strategy", "regime headwind"):
        assert any(e.startswith(required) or required.startswith(e) for e in emitted), (
            f"regex missed the {required!r} producer"
        )

    covered = [r for r, _ in _REAL_STOCK_REASONS]
    unclassified = [
        # `c.startswith(e)` alone, not the old `e.startswith(c[:len(e)])`, which
        # made any short capture trivially "covered" by any bucket string.
        e for e in emitted if not any(c.startswith(e) for c in covered)
    ]
    assert not unclassified, (
        f"new rejection reason(s) with no bucket decision: {sorted(unclassified)}"
    )


def test_funnel_reconciles_when_the_gate_passes_everything(stock_client):
    """The invariant must hold on the happy path too, not only when things
    are being dropped.

    trend=85 rather than the 10 this used to pass: 10 is now BELOW the
    Bearish/Position floor and would be gated, which would have made this test
    assert the opposite of its own name.
    """
    body = _run(stock_client, ["AAA", "BBB"], direction="Bearish", horizon="Position",
                score_stock=MagicMock(return_value=_card(85)))

    pipeline = body["pipeline"]
    assert pipeline["failed_direction"] == 0
    assert _accounted(pipeline) == pipeline["scanned"] == 2
    assert pipeline["candidates"] == len(body["candidates"])


# ── The config fail-fast, end to end ─────────────────────────────────────────
#
# Round 2 audit: deleting the whole fail-fast block from either router left the
# suite 112/112 green, so the entirety of that protection was unguarded. These
# tests are what make deleting it fail.

_BAD_CFG = {"horizons": {"position": {"direction_conviction": {"bearish_min_tren": 30}}}}


def test_a_malformed_threshold_fails_the_stock_scan_instead_of_screening_on_a_stale_one(
    stock_client,
):
    """A config typo must stop the scan and name itself.

    Without the pre-check the scan returns 200 with every symbol rejected under
    a symbol literally called "unknown" — the resolver raises inside
    _process_stock, asyncio.gather(return_exceptions=True) collects it, and
    classify_stock_rejection files it in other_rejected. The user gets an empty
    table and a residual count instead of "your config is broken"."""
    with patch("app.services.config_loader.load_scoring_cfg", return_value=_BAD_CFG):
        r = stock_client.post("/api/stock-scan", json={
            "symbols": ["AAA"], "universe": [], "direction": "Bearish",
            "horizon": "Position", "strategy": "pullback_ema",
        })
    assert r.status_code == 500, r.text
    detail = r.json()["detail"]
    assert "bearish_min_tren" in detail, detail


def test_the_stock_fail_fast_runs_before_the_universe_price_fetch(stock_client):
    """It has to be cheap to be wrong. The check sits above the batch Tradier
    quote call and the SPY benchmark fetch, so a broken config costs no
    universe-wide round trip — it used to sit below both."""
    fetch = MagicMock(return_value={})
    with ExitStack() as stack:
        stack.enter_context(patch("app.services.config_loader.load_scoring_cfg",
                                  return_value=_BAD_CFG))
        stack.enter_context(patch("app.routers.stock_scan.fetch_quotes", fetch))
        r = stock_client.post("/api/stock-scan", json={
            "symbols": ["AAA"], "universe": [], "direction": "Bearish",
            "horizon": "Position", "strategy": "pullback_ema",
        })
    assert r.status_code == 500, r.text
    assert fetch.call_count == 0, (
        "the universe quote fetch ran before the config was checked — the "
        "fail-fast is below it again"
    )


def test_process_stock_lets_a_config_error_propagate_rather_than_rejecting_the_symbol():
    """_process_stock resolves the floor OUTSIDE its `except Exception`.

    Inside it, a config error becomes {"symbol": ..., "reason": "invalid
    direction_conviction..."} — which does not start with "direction_conviction:"
    and so lands in other_rejected, reported to the user as a per-symbol
    scanning failure rather than as the config fault it is. Moving the call back
    inside the try has to fail here."""
    import asyncio
    from app.routers.stock_scan import _process_stock
    from app.schemas.stock_scan import StockScanRequest

    req = StockScanRequest(
        universe=[], symbols=["AAA"], direction="Bearish",
        horizon="Position", strategy="pullback_ema",
    )
    # asyncio.run, matching the other 18 async call sites in this suite. The
    # earlier `get_event_loop_policy().new_event_loop().run_until_complete(...)`
    # never closed its loop, leaking a selector fd per run.
    with patch("app.services.config_loader.load_scoring_cfg", return_value=_BAD_CFG):
        with pytest.raises(ValueError, match="bearish_min_tren"):
            asyncio.run(_process_stock("AAA", req, "scan-1", {}, []))


def test_the_stock_rejection_reason_names_the_floor_as_an_integer(stock_client):
    """The stock path's user-visible reason string had no end-to-end pin, so
    dropping the `:g` from its f-string survived the suite (round 3, M34) and
    the user would have read `trend 20 < 40.0`.

    `direction_conviction:` is also the prefix classify_stock_rejection matches
    on, so a reword silently relocates these into other_rejected and the funnel
    renders them as errors. The options path has had this assertion since
    round 2; this is the missing half."""
    body = _run(stock_client, ["AAA"], direction="Bearish", horizon="Position",
                score_stock=MagicMock(return_value=_card(20)))

    reasons = [r["reason"] for r in body["rejected"]]
    assert reasons == ["direction_conviction: trend 20 < 40 for Bearish Position"], reasons
    assert body["pipeline"]["failed_direction"] == 1
    assert body["pipeline"]["other_rejected"] == 0


# ── regime_sizing's own fail-fast (§9.1, Kenneth 2026-09-17) ─────────────────
#
# The scope table puts regime_sizing on POST /stock-scan AND the auto-trade
# fire path. It is the only entry on that table that changes the NUMBER OF
# SHARES the response carries rather than which names come back, so it gets
# the same pre-check the direction-conviction floor above already has.

_BAD_SIZING = {"regime_sizing": {
    "enabled": True, "min_mult": 0.3, "full_conviction_pct": -40,
}}


def test_an_unusable_regime_sizing_block_fails_the_stock_scan(stock_client):
    """Without the pre-check, every card in the response carries a share count
    multiplied by a number nobody chose — or, once conviction_mult refuses, a
    universe of symbols rejected under the name "unknown"."""
    with patch("app.routers.stock_scan._load_full_scoring_cfg", return_value=_BAD_SIZING):
        r = stock_client.post("/api/stock-scan", json={
            "symbols": ["AAA"], "universe": [], "direction": "Bullish",
            "horizon": "Swing", "strategy": "pullback_ema",
        })
    assert r.status_code == 500, r.text
    detail = r.json()["detail"]
    assert "full_conviction_pct" in detail, detail
    assert "scoring_rules.yaml" in detail, detail


def test_the_sizing_fail_fast_runs_before_the_universe_price_fetch(stock_client):
    fetch = MagicMock(return_value={})
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.stock_scan._load_full_scoring_cfg",
                                  return_value=_BAD_SIZING))
        stack.enter_context(patch("app.routers.stock_scan.fetch_quotes", fetch))
        r = stock_client.post("/api/stock-scan", json={
            "symbols": ["AAA"], "universe": [], "direction": "Bullish",
            "horizon": "Swing", "strategy": "pullback_ema",
        })
    assert r.status_code == 500, r.text
    assert fetch.call_count == 0, (
        "the universe quote fetch ran before regime_sizing was checked"
    )


@pytest.mark.parametrize("cfg", [
    {},                                    # block absent
    {"regime_sizing": None},               # `regime_sizing:` with nothing under it
    {"regime_sizing": {"enabled": False, "full_conviction_pct": "junk"}},
])
def test_sizing_off_does_not_fail_the_scan(stock_client, cfg):
    """Off is a configuration, not a failure: the up-front check must let it
    through. Refusing here would restrict more than section 9.1 asks for.

    WHAT THIS DOES NOT PIN, because round 1 measured it: these symbols drop at
    "insufficient history" and conviction_mult is never called, so this asserts
    only that the fail-fast does not trip. "Junk under a disabled block is
    inert" is pinned in test_conviction_sizing.py, at the level where the
    arithmetic lives.
    """
    with patch("app.routers.stock_scan._load_full_scoring_cfg", return_value=cfg):
        r = stock_client.post("/api/stock-scan", json={
            "symbols": ["AAA"], "universe": [], "direction": "Bullish",
            "horizon": "Swing", "strategy": "pullback_ema",
        })
    assert r.status_code == 200, r.text
