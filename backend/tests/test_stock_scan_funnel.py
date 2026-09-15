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
    """Bearish/Position drops trend > 40. Those rejections used to be absorbed
    into other_rejected, where the funnel never showed them at all."""
    body = _run(stock_client, ["AAA", "BBB"], direction="Bearish", horizon="Position",
                score_stock=MagicMock(return_value=_card(60)))

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


@pytest.mark.parametrize("direction,horizon,trend,gated", [
    # The four non-Intraday pairs, at one point either side of each threshold.
    ("Bearish", "Position", 41, True),  ("Bearish", "Position", 40, False),
    ("Bearish", "Swing",    51, True),  ("Bearish", "Swing",    50, False),
    ("Bullish", "Position", 39, True),  ("Bullish", "Position", 40, False),
    ("Bullish", "Swing",    29, True),  ("Bullish", "Swing",    30, False),
    # Intraday is exempt in both modes, at any trend score.
    ("Bearish", "Intraday", 99, False), ("Bullish", "Intraday", 1,  False),
])
def test_stock_gate_thresholds_match_the_options_gate(
    stock_client, direction, horizon, trend, gated,
):
    """The direction gate is hardcoded TWICE — a dict in routers/scan.py and an
    if/else in routers/stock_scan.py — in a repo where every other threshold
    lives in config/*.yaml. They agree today (Bearish 50/40, Bullish 30/40,
    Intraday exempt). Nothing but this test stops one copy from drifting.

    Asserted against the options dict itself, so editing either copy alone
    fails here rather than silently giving the two modes different screens.
    """
    from app.routers.scan import _execute_scan_core  # noqa: F401  (module import)
    import inspect, re

    src = inspect.getsource(_execute_scan_core)
    gate_src = re.search(r"_DIRECTION_TREND_GATE.*?\n    \}", src, re.S).group(0)
    options_gate: dict = {}
    for d, h, kind, val in re.findall(
        r'\("(\w+)",\s*"(\w+)"\):\s*\{"(\w+)":\s*(\d+)\}', gate_src
    ):
        options_gate[(d, h)] = (kind, int(val))

    expected = options_gate.get((direction, horizon))
    if expected is None:
        assert not gated, f"options exempts {direction}/{horizon}; stock must too"
    else:
        kind, threshold = expected
        assert gated == (trend > threshold if kind == "max_trend" else trend < threshold), (
            f"options {kind}={threshold} for {direction}/{horizon} disagrees with stock"
        )

    body = _run(stock_client, ["AAA"], direction=direction, horizon=horizon,
                score_stock=MagicMock(return_value=_card(trend)))
    assert body["pipeline"]["failed_direction"] == (1 if gated else 0)


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
    ("direction_conviction: trend 60 > 40 for Bearish Position", "failed_direction"),
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
    are being dropped."""
    body = _run(stock_client, ["AAA", "BBB"], direction="Bearish", horizon="Position",
                score_stock=MagicMock(return_value=_card(10)))

    pipeline = body["pipeline"]
    assert pipeline["failed_direction"] == 0
    assert _accounted(pipeline) == pipeline["scanned"] == 2
    assert pipeline["candidates"] == len(body["candidates"])
