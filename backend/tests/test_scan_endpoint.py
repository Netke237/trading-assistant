"""Route tests for POST /api/scan.

market.py uses Tradier for live data. All tests that exercise the pipeline
mock async fetch functions so they run network-free and deterministically.
"""

import asyncio
import re
from contextlib import ExitStack
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# ── Shape & contract ──────────────────────────────────────────────────────────

def test_scan_returns_200(client):
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 200


def test_scan_response_has_required_fields(client):
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    data = r.json()
    assert "scan_id"    in data
    assert "timestamp"  in data
    assert "candidates" in data
    assert "rejected"   in data


def test_scan_id_format(client):
    """scan_id must match REC-YYYYMMDD-XXXXXXXX."""
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    scan_id = r.json()["scan_id"]
    assert re.match(r"REC-\d{8}-[A-F0-9]{8}", scan_id), f"Unexpected scan_id: {scan_id}"


def test_scan_empty_universe_returns_empty_lists(client):
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    data = r.json()
    assert data["candidates"] == []
    assert data["rejected"]   == []


def test_scan_invalid_direction_returns_422(client):
    r = client.post("/api/scan", json={
        "universe": ["AAPL"], "direction": "Sideways", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 422


def test_scan_invalid_horizon_returns_422(client):
    r = client.post("/api/scan", json={
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Daily", "overrides": {},
    })
    assert r.status_code == 422


def test_scan_missing_body_returns_422(client):
    r = client.post("/api/scan")
    assert r.status_code == 422


# ── No market data → symbol rejected ─────────────────────────────────────────

def _enter_mock_patches(*, price=None, candles=None, chain=None,
                        company=None, fund=None):
    stack = ExitStack()
    stack.enter_context(patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=price)))
    stack.enter_context(patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=candles or [])))
    stack.enter_context(patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=chain or [])))
    stack.enter_context(patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value=company)))
    stack.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=fund)))
    return stack


def test_scan_no_market_data_rejects_symbol(client):
    """When fetch_price returns None the symbol must appear in rejected, not candidates."""
    with _enter_mock_patches(price=None, candles=[]):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    rejected_symbols = [item["symbol"] for item in data["rejected"]]
    assert "AAPL" in rejected_symbols
    assert all(c["symbol"] != "AAPL" for c in data["candidates"])


# ── With mocked market data — pipeline runs end-to-end ───────────────────────

_MOCK_CANDLES = [
    {"time": f"2026-0{i//10+1}-{i%28+1:02d}", "open": 184.0, "high": 190.0,
     "low": 182.0, "close": 187.0, "volume": 1_000_000}
    for i in range(30)
]

_MOCK_CHAIN = [
    {
        "strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30,
        "right": "C", "volume": 500,
    }
]

_WIDE_MOCK_CHAIN = [
    {"strike": 25,  "expiry": "2026-06-20", "price": 460.0, "spread": 0.20,
     "delta": 0.99, "theta": -0.01, "ivRank": 40, "dte": 30, "right": "C", "volume": 500},
    {"strike": 100, "expiry": "2026-06-20", "price": 86.0,  "spread": 0.20,
     "delta": 0.90, "theta": -0.02, "ivRank": 45, "dte": 30, "right": "C", "volume": 450},
    {"strike": 130, "expiry": "2026-06-20", "price": 12.0,  "spread": 0.20,
     "delta": 0.80, "theta": -0.03, "ivRank": 55, "dte": 30, "right": "C", "volume": 400},
    {"strike": 190, "expiry": "2026-06-20", "price": 2.50,  "spread": 0.20,
     "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30, "right": "C", "volume": 500},
    {"strike": 280, "expiry": "2026-06-20", "price": 0.55,  "spread": 0.20,
     "delta": 0.15, "theta": -0.01, "ivRank": 55, "dte": 30, "right": "C", "volume": 350},
    {"strike": 300, "expiry": "2026-06-20", "price": 0.30,  "spread": 0.20,
     "delta": 0.02, "theta": -0.01, "ivRank": 55, "dte": 30, "right": "C", "volume": 300},
    {"strike": 340, "expiry": "2026-06-20", "price": 0.10,  "spread": 0.10,
     "delta": 0,    "theta": 0.0,   "ivRank": 0,  "dte": 30, "right": "C", "volume": 10},
]


def test_scan_with_mock_data_processes_symbol(client):
    """With valid mock data the symbol appears in candidates or rejected � never missing."""
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_MOCK_CHAIN,
                             company="Apple Inc."):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    all_symbols = (
        [c["symbol"] for c in data["candidates"]] +
        [rej["symbol"] for rej in data["rejected"]]
    )
    assert "AAPL" in all_symbols


def test_scan_with_mock_data_candidate_shape(client):
    """If AAPL is scored as a candidate its TradeCardData shape must be valid."""
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_MOCK_CHAIN,
                             company="Apple Inc."):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    data = r.json()
    for c in data["candidates"]:
        assert "symbol"       in c
        assert "stockScore"   in c
        assert "rrRatio"      in c
        assert "finalStatus"  in c
        assert c["direction"] == "Bullish"


def test_scan_multiple_symbols_all_accounted_for(client):
    """Every symbol in universe must appear in candidates OR rejected � none silently dropped."""
    universe = ["AAPL", "MSFT", "NVDA"]
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_MOCK_CHAIN,
                             company="Test Corp"):
        r = client.post("/api/scan", json={
            "universe": universe, "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    data = r.json()
    processed = (
        {c["symbol"] for c in data["candidates"]} |
        {rej["symbol"] for rej in data["rejected"]})
    assert processed == set(universe)


# ── Horizon-driven DTE window: hard-reject floor must respect hold_max_days ──

def _dte_expiry(days_from_today: int) -> str:
    from datetime import date, timedelta
    return (date.today() + timedelta(days=days_from_today)).isoformat()


def _force_passing_stock_score():
    """Patches app.routers.scan.score_stock so the pre-screen/score gates
    always pass — isolates the DTE hard-reject gate under test from the
    unrelated stock-scoring pipeline, which the synthetic _MOCK_CANDLES series
    doesn't reliably clear on its own.

    Carries a MEASURED trend rule: since P3c item 2 a card with no trend rule
    is an unmeasured trend, which the options direction gate removes."""
    from app.scoring.stock_scorer import StockScoreCard, RuleResult
    return patch(
        "app.routers.scan.score_stock",
        MagicMock(return_value=StockScoreCard(
            symbol="AAPL", direction="Bullish", horizon="Swing", score=80, status="PASS",
            rules=[RuleResult("trend", "PASS", 80, {})],
        )),
    )


def _rr_test_chain(iv_rank: float = 55) -> list[dict]:
    """A single contract that clears every contract_rules.yaml hard-reject
    check (unlike _MOCK_CHAIN, which is missing open_interest and has a stale
    hardcoded expiry date) -- so it reliably becomes a candidate regardless of
    when this test runs."""
    return [{
        "strike": 190, "expiry": _dte_expiry(35), "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": iv_rank, "dte": 35,
        "right": "C", "volume": 500, "open_interest": 2000,
    }]


def _no_db_leak():
    """Force the mocked candles/price fixtures to actually be used. Without
    this, run_scan's DB-backed bars_map/price_map pre-fetch (scan.py's
    fetch_quotes and a locally-imported historical_store.get_bars -- neither
    covered by _enter_mock_patches) can silently return real historical data
    for a symbol this repo's dev database already has ingested, bypassing
    _MOCK_CANDLES/price entirely."""
    return (
        patch("app.routers.scan.fetch_quotes", return_value={}),
        patch("app.services.historical_store.get_bars", AsyncMock(return_value=[])),
    )


def test_scan_rr_target_r_multiple_override_changes_target_price(client):
    """A 3R target is resolved off the same stock stop as the default 2R."""
    fetch_quotes_patch, get_bars_patch = _no_db_leak()
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Apple Inc."), \
         fetch_quotes_patch, get_bars_patch, _force_passing_stock_score():
        r_default = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
        r_override = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {"rr_target_r_multiple": 3},
        })
    default_candidates = r_default.json()["candidates"]
    override_candidates = r_override.json()["candidates"]
    assert default_candidates, "expected AAPL to score as a candidate for this fixture"
    assert override_candidates, "expected AAPL to score as a candidate for this fixture"
    default_target = default_candidates[0]["exit"]["target"]
    override_target = override_candidates[0]["exit"]["target"]
    assert override_target > default_target
    assert round(override_target, 2) == round(185 + 3 * abs(185 - override_candidates[0]["exit"]["invalidation"]), 2)


# A feed that cannot form a single true range: 30 bars with open == high ==
# low == close. `_atr` returns 0.0, `compute_final_stop`'s ATR floor would sit
# exactly ON the entry price, and `resolve_stock_stop` therefore falls back to
# the flat percentage. This is the ONLY path on which Step 3's "Bullish stop %"
# still moves a number, so it needs a fixture of its own.
_FLAT_CANDLES = [
    {"time": f"2026-0{i//10+1}-{i%28+1:02d}", "open": 185.0, "high": 185.0,
     "low": 185.0, "close": 185.0, "volume": 1_000_000}
    for i in range(30)
]


def _scan_one(client, **overrides):
    """POST one Bullish AAPL scan and return its first candidate."""
    candles = overrides.pop("candles", _MOCK_CANDLES)
    fetch_quotes_patch, get_bars_patch = _no_db_leak()
    with _enter_mock_patches(price=185.0, candles=candles, chain=_rr_test_chain(),
                             company="Apple Inc."), \
         fetch_quotes_patch, get_bars_patch, _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
            "overrides": overrides,
        })
    assert r.status_code == 200, r.text
    candidates = r.json()["candidates"]
    assert candidates, "expected AAPL to score as a candidate for this fixture"
    return candidates[0]


def test_scan_invalidation_is_the_structural_atr_stop_not_a_flat_pct(client):
    """PIECE 3, the whole point of it.

    `exit.invalidation` used to be `price * (1 - 0.03)` -- 179.45 on this
    fixture, the same -3% it would print on every symbol in the universe. It is
    now `resolve_stock_stop`'s answer: `_MOCK_CANDLES` is 30 bars of
    high 190 / low 182, so ATR(14) is 8.00 and the 2xATR floor sits at
    185 - 16 = 169.00, well outside anything the flat percentage could reach.

    Asserting the exact 169.00 rather than merely "not 179.45" is deliberate:
    an implementation that resolved a stop and then quietly used the flat one
    anyway would still differ from 179.45 by rounding alone under a weaker
    assertion.
    """
    card = _scan_one(client)
    assert card["exit"]["invalidation"] == 169.00
    assert card["exit"]["invalidation"] != round(185.0 * 0.97, 2)


def test_scan_attaches_the_final_stop_provenance_block(client):
    """`exit.finalStop` says WHERE `exit.invalidation` came from, and the two
    must print the same number -- the "Bottom (final stop)" row renders one and
    the Invalidation field the other, on the same card, inches apart."""
    fs = _scan_one(client)["exit"]["finalStop"]
    assert fs is not None, "the scan must resolve a stop for a 30-bar feed"
    assert fs["price"] == 169.00
    assert fs["source"] == "final_stop"
    # This fixture's bars are identical, so the ATR floor wins over whatever
    # structure detection makes of them.
    assert fs["stopSource"] == "atr_widened"
    assert fs["atrFloorPrice"] == 169.00
    assert fs["atr"] == 8.0
    assert fs["computedAt"]
    # The losing candidate rides along too — the row prints both levels and the
    # gap between them. Structure detection finds a swing low at 182.00 here;
    # it lost because 185 - 182 = 3.00 is narrower than 2 x ATR = 16.00.
    assert fs["structuralSource"] == "swing_low"
    assert fs["structuralPrice"] == 182.00
    assert fs["distanceDollar"] == 13.00


def test_scan_badge_and_invalidation_grade_the_same_stop(client):
    """B3 priced its ranking badge against its own private `compute_final_stop`
    call while `exit.invalidation` still carried the flat percentage -- two
    stops on one card. Piece 3 resolves the stop once; if a future edit
    reintroduces a second computation, the badge's stop and the card's stop
    drift and this fails.

    Pinned through `exit.finalStop.price`, which is the ROUNDED figure the
    badge is priced at (`round(_stock_stop.price, 2)` in scan.py), so this
    catches a drift in either direction rather than only in the resolver.
    """
    card = _scan_one(client)
    assert card["stopCostPct"] is not None, (
        "expected the scan-time gate to price this fixture -- without it this "
        "test cannot tell the two stops apart"
    )
    assert card["exit"]["finalStop"]["price"] == card["exit"]["invalidation"]


def test_scan_rr_bullish_invalidation_pct_override_bites_only_on_a_dead_feed(client):
    """Step 3's "Bullish stop %" is now `resolve_stock_stop`'s FALLBACK.

    On a real bar feed the structural/ATR stop wins and the parameter is inert
    by design -- pinned here so nobody "fixes" that back into a live flat stop.
    On a feed that cannot form one true range there is no structural answer to
    prefer, and the parameter is the only thing left: it must still move the
    number, or a user-visible execution parameter has gone silently dead.
    """
    # Real feed: the structural/ATR stop wins, the override changes nothing.
    assert _scan_one(client)["exit"]["invalidation"] == 169.00
    assert _scan_one(client, rr_bullish_invalidation_pct=0.10)["exit"]["invalidation"] == 169.00

    # Dead feed: the flat percentage is all there is, and it is honoured.
    flat_default = _scan_one(client, candles=_FLAT_CANDLES)
    flat_override = _scan_one(client, candles=_FLAT_CANDLES, rr_bullish_invalidation_pct=0.10)
    assert round(flat_default["exit"]["invalidation"], 2) == round(185.0 * 0.97, 2)
    assert round(flat_override["exit"]["invalidation"], 2) == round(185.0 * 0.90, 2)
    assert flat_override["exit"]["invalidation"] < flat_default["exit"]["invalidation"]

    # And a fallback stop carries NO provenance block: there was no structural
    # level and no ATR floor to report, so "not computed" is the honest shape.
    # A block of nulls would read on the card as "we looked and found nothing".
    assert flat_default["exit"]["finalStop"] is None
    # The ranking badge refuses it for the same reason.
    assert flat_default["stopCostPct"] is None
    assert flat_default["stopCostStatus"] is None


def test_scan_rr_negative_target_override_fails_fast_422(client):
    """Round 2 audit finding: a malformed override (negative target %) must
    be rejected upfront in run_scan(), BEFORE any per-symbol candle/price/
    fundamentals fetch or option-chain scoring runs -- not after every symbol
    in the universe has redundantly done that work and failed identically.
    run_scan() now validates rr_* overrides once via merge_reward_risk_overrides
    before building the per-symbol task list, returning a clean 422 (matching
    contracts.py's recompute-plan endpoint's handling of the same error)
    instead of the old 200-with-every-symbol-rejected behaviour."""
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Apple Inc."), _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {"rr_target_r_multiple": -1},
        })
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "rr_target_r_multiple" in detail
    assert "(0, 10]" in detail


def test_scan_rr_override_leaves_default_scan_unchanged(client):
    """A scan with no rr_* overrides must still use the risk_rules.yaml default
    (2R bullish target) -- guards against the merge helper changing the
    no-override path's numbers."""
    fetch_quotes_patch, get_bars_patch = _no_db_leak()
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Apple Inc."), \
         fetch_quotes_patch, get_bars_patch, _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    candidates = r.json()["candidates"]
    assert candidates
    # Default 2R target uses the resolved stop, with this fixture no snap.
    assert round(candidates[0]["exit"]["target"], 2) == round(185 + 2 * abs(185 - candidates[0]["exit"]["invalidation"]), 2)


def test_scan_entry_negative_spread_override_fails_fast_422(client):
    """APP-AUDIT-B-ENTRY-OVERRIDES: A malformed entry override must fail fast with 422
    upfront before worker tasks dispatch."""
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Apple Inc."), _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {"entry_spread_tolerance_pct": -0.05},
        })
    assert r.status_code == 422, r.text
    assert "entry_spread_tolerance_pct" in r.json()["detail"]


def test_scan_entry_overrides_recorded_and_applied(client):
    """APP-AUDIT-B-ENTRY-OVERRIDES: Entry Quality overrides are recorded on ScanResult.entry_overrides
    and reach build_trade_plan to set max_fill and entry quality status."""
    fetch_quotes_patch, get_bars_patch = _no_db_leak()

    # 1. Zero slippage override: max_fill == premium (2.50) instead of 2.50 * 1.03 = 2.58
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Apple Inc."),          fetch_quotes_patch, get_bars_patch, _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {"entry_max_slippage_pct": 0},
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["entry_overrides"] == {"entry_max_slippage_pct": 0.0}
    candidates = data["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["entry"]["maxFill"] == 2.50
    # In mock patches without earnings fixture, earnings unknown caps at CAUTION,
    # but entry quality PASS does not reject the candidate.
    assert candidates[0]["finalStatus"] in ("PASS", "CAUTION")
    assert candidates[0]["finalStatus"] != "REJECT"

    # 2. Min premium 5.0 override: 2.50 < 5.0 -> entry quality rejects, so finalStatus is REJECT
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Apple Inc."),          fetch_quotes_patch, get_bars_patch, _force_passing_stock_score():
        r2 = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {"entry_min_premium": 5.0},
        })
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    assert data2["entry_overrides"] == {"entry_min_premium": 5.0}
    candidates2 = data2["candidates"]
    assert len(candidates2) == 1
    assert candidates2[0]["finalStatus"] == "REJECT"


def test_scan_horizon_preset_reaches_build_trade_plan(client):
    """Round 9 audit finding: ScanRequest.horizon_preset is forwarded through
    _execute_scan_core -> _process_symbol -> build_trade_plan (scan.py:780),
    but no test ever POSTed a non-default horizon_preset over /api/scan and
    checked the response actually changed -- grepping tests/ for
    horizon_preset turned up zero scan-related references before this. A
    future edit that drops or defaults horizon_preset anywhere in that
    forwarding chain would ship silently, reintroducing the exact
    ladder/Monte-Carlo horizon mismatch this field exists to prevent, with
    zero CI signal.

    _rr_test_chain()'s dte=35: Swing/absent resolves to 7 fallback days,
    Annual resolves to 80 clamped to 0.75*35=26.25 -- both comfortably inside
    bounds, so the Fixed % Ladder must reprice at a different remaining life."""
    fetch_quotes_patch, get_bars_patch = _no_db_leak()
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Apple Inc."), \
         fetch_quotes_patch, get_bars_patch, _force_passing_stock_score():
        r_default = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
        r_annual = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {}, "horizon_preset": "Annual",
        })
    default_candidates = r_default.json()["candidates"]
    annual_candidates = r_annual.json()["candidates"]
    assert default_candidates, "expected AAPL to score as a candidate for this fixture"
    assert annual_candidates, "expected AAPL to score as a candidate for this fixture"
    default_targets = [t["estimatedOptionPrice"] for t in default_candidates[0]["exit"]["targets"]]
    annual_targets = [t["estimatedOptionPrice"] for t in annual_candidates[0]["exit"]["targets"]]
    assert default_targets != annual_targets, (
        "horizon_preset='Annual' produced the same ladder as the default -- "
        "the field is not reaching build_trade_plan through the scan pipeline"
    )


def test_scan_swing_hold_rejects_a_contract_expiring_before_the_hold_ends(client):
    """Adversarial-audit finding on the DTE-tolerance fix: a flat 10-day
    hard-reject tolerance would let a Swing (5-15d hold) scan accept a 12-DTE
    contract — expiring before the 15-day hold is even over. This exercises
    the actual _process_symbol code path (via POST /api/scan), not just
    validate_contract() directly — the unit-level tests in test_horizon_dte.py
    proved the math; this proves scan.py actually wires hold_max_days through."""
    too_short_chain = [{
        "strike": 190, "expiry": _dte_expiry(12), "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 12,
        "right": "C", "volume": 500, "open_interest": 1000,
    }]
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=too_short_chain,
                             company="Apple Inc."), _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
            "hold_min_days": 5, "hold_max_days": 15,
        })
    data = r.json()
    assert all(c["symbol"] != "AAPL" for c in data["candidates"])
    rejected = next(rej for rej in data["rejected"] if rej["symbol"] == "AAPL")
    assert "contracts rejected" in rejected["reason"]
    assert "dte_too_short" in rejected["reason"]


def test_scan_swing_hold_accepts_a_contract_within_the_widened_window(client):
    """Same Swing hold, but a 36-DTE contract — inside the widened-but-floored
    window (36-81d after hold15 + buffer21) — must be allowed through
    to scoring and produce a real candidate, not blocked by the DTE gate."""
    ok_chain = [{
        "strike": 190, "expiry": _dte_expiry(36), "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 36,
        "right": "C", "volume": 500, "open_interest": 1000,
    }]
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=ok_chain,
                             company="Apple Inc."), _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
            "hold_min_days": 5, "hold_max_days": 15,
        })
    data = r.json()
    candidate_symbols = [c["symbol"] for c in data["candidates"]]
    rejected = next((rej for rej in data["rejected"] if rej["symbol"] == "AAPL"), None)
    assert "AAPL" in candidate_symbols or rejected is None or (
        "dte_too_short" not in rejected["reason"] and "dte_too_long" not in rejected["reason"]
    )


# ── O-4: Raise scan concurrency 3 → 5 ────────────────────────────────────────

def test_scan_concurrency_is_five():
    """O-4: _SCAN_CONCURRENCY must be 5 — O-3 batch price fetch reduces per-symbol calls to 3."""
    from app.routers.scan import _SCAN_CONCURRENCY
    assert _SCAN_CONCURRENCY == 5, f"Expected 5, got {_SCAN_CONCURRENCY}"


def test_heston_concurrency_decoupled_from_scan_concurrency():
    """Heston calibration makes no Tradier calls, so its executor/semaphore
    must be sized independently of the Tradier-rate-limit-driven
    _SCAN_CONCURRENCY, scaling with local CPU capacity instead (see scan.py's
    _HESTON_CONCURRENCY comment) — never smaller than _SCAN_CONCURRENCY even
    on a low-core or cpu-count-undetectable host.

    This only checks that the module-level constants were wired up by calling
    _compute_heston_concurrency/_detect_cpu_count — the formula's actual
    edge-case behavior (None, 1, 2 cores) is covered independently by
    test_compute_heston_concurrency_* below, without depending on this host's
    real core count."""
    from app.routers.scan import (
        _SCAN_CONCURRENCY, _HESTON_CONCURRENCY, _HESTON_EXECUTOR, _HESTON_SEMAPHORE,
        _compute_heston_concurrency, _detect_cpu_count,
    )

    assert _HESTON_CONCURRENCY == _compute_heston_concurrency(_SCAN_CONCURRENCY, _detect_cpu_count())
    assert _HESTON_CONCURRENCY >= _SCAN_CONCURRENCY
    assert _HESTON_EXECUTOR._max_workers == _HESTON_CONCURRENCY
    assert _HESTON_SEMAPHORE._value == _HESTON_CONCURRENCY


@pytest.mark.parametrize("detected_cpu_count,expected", [
    (None, 5),   # cpu_count() undetectable — floor at _SCAN_CONCURRENCY
    (1, 5),      # 1 core - 1 = 0, floors at _SCAN_CONCURRENCY
    (2, 5),      # 2 cores - 1 = 1, still floors at _SCAN_CONCURRENCY
    (5, 5),      # 5 cores - 1 = 4, still floors at _SCAN_CONCURRENCY
    (6, 5),      # 6 cores - 1 = 5, exactly at the floor
    (8, 7),      # 8 cores - 1 = 7, above the floor
    (16, 15),    # 16 cores - 1 = 15, above the floor
])
def test_compute_heston_concurrency_edge_cases(detected_cpu_count, expected):
    """Exercises the sizing formula directly against explicit cpu-count
    inputs, independent of the actual host's core count — this is what
    catches an off-by-one or a wrong floor/operator, which a test that only
    re-derives the formula from the live os.cpu_count() value cannot."""
    from app.routers.scan import _compute_heston_concurrency

    assert _compute_heston_concurrency(5, detected_cpu_count) == expected


def test_detect_cpu_count_falls_back_without_sched_getaffinity(monkeypatch):
    """Windows (and some other platforms) have no os.sched_getaffinity —
    must fall back to os.cpu_count() rather than raising."""
    import os
    from app.routers.scan import _detect_cpu_count

    monkeypatch.delattr(os, "sched_getaffinity", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert _detect_cpu_count() == 8


def test_detect_cpu_count_prefers_sched_getaffinity(monkeypatch):
    """When available, sched_getaffinity reflects cpuset/cgroup pinning
    (e.g. Docker --cpuset-cpus) that os.cpu_count() ignores — it must win
    over the host-wide os.cpu_count() figure."""
    import os
    from app.routers.scan import _detect_cpu_count

    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {0, 1}, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert _detect_cpu_count() == 2


# ── O-3: Batch price pre-fetch ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_symbol_skips_per_symbol_price_when_in_price_map():
    """When price_map contains the symbol's price, fetch_price_async must NOT be called."""
    from app.routers.scan import _process_symbol

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()
    price_map = {"AAPL": {"last": 185.0, "prevclose": 183.0}}

    mock_card = MagicMock()
    mock_card.status = "REJECT"
    mock_card.score = 25
    mock_card.rules = []

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)) as mock_price_async,
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=mock_card),
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
            price_map=price_map,
        )

    mock_price_async.assert_not_called()


# ── O-6 (superseded): Heston calibration wired back into the scan pipeline ────
# Originally removed for scan-loop performance (commit 99c51ed). WS-40 added an
# LRU cache + 1s timeout/BS-fallback (app/models/heston_cache.py) specifically so
# this could be reinstated safely — see docs/superpowers/plans/
# 2026-07-25-heston-pricing-in-trade-plan.md.

def _heston_wiring_fixtures():
    """Shared scaffolding for the tests below — mirrors the old O-6 test's mocks."""
    from app.scoring.contract_validator import ContractScoreCard, ContractScoreBreakdown
    from app.scoring.stock_scorer import StockScoreCard
    from app.scoring.entry_quality import EntryAssessment
    from app.scoring.trade_plan import TradePlan

    pass_card = StockScoreCard(
        symbol="AAPL", direction="Bullish", horizon="Swing",
        score=75, status="PASS", rules=[],
    )
    contract_score = ContractScoreCard(
        contract_id="AAPL|190|2026-06-20|C",
        symbol="AAPL", strike=190.0, expiry="2026-06-20",
        is_call=True, score=70, status="PASS",
        breakdown=ContractScoreBreakdown(60, 60, 60, 60, 60, 60),
    )
    entry_result = EntryAssessment(
        limit_price=2.50, max_fill=2.53, order_type="Limit", quality_status="PASS",
    )
    fake_plan = TradePlan(
        entry=entry_result,
        invalidation_price=180.0,
        premium_stop=1.5,
        time_stop_days=12,
        target_price=200.0,
        targets=[],
        rr_ratio=2.5,
        rr_model="Heston repriced",
        target_price_raw=200.0,
        invalidation_price_raw=180.0,
        rr_risk_basis="premium_stop", target_source="arithmetic",
        stock_stop_loss=None, stock_stop_loss_at=None,
        reprice_years=(45 - 7) / 365.0,   # Swing on a 45-DTE contract
    )
    return pass_card, contract_score, fake_plan


@pytest.mark.asyncio
async def test_process_symbol_calls_calibrate_heston_with_the_chain():
    """calibrate_heston must run once per processed symbol, and its result must
    flow into build_trade_plan as heston_params."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=0.01, method="heston_grid")

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration) as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_called_once()
    called_chain = mock_heston.call_args.args[0]
    called_price = mock_heston.call_args.args[1]
    assert called_chain == [{
        "strike": 190.0, "expiry_years": 30 / 365.0, "mid_price": 2.50, "is_call": True,
    }]
    assert called_price == 185.0
    assert mock_build_plan.call_args.kwargs["heston_params"] == fake_params


@pytest.mark.asyncio
async def test_process_symbol_falls_back_when_calibrate_heston_raises():
    """A Heston calibration failure must not fail the whole symbol — build_trade_plan
    must still be called, with heston_params=None (delta approximation)."""
    from app.routers.scan import _process_symbol

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", side_effect=RuntimeError("boom")),
    ):
        result = await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    assert mock_build_plan.call_args.kwargs["heston_params"] is None
    assert result is not None  # symbol still produced a trade card, didn't crash


@pytest.mark.asyncio
async def test_process_symbol_discards_bs_fallback_heston_calibration():
    """Option G (docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md,
    finding #5): a CalibrationResult with method='bs_fallback' is a crude
    single-point IV-seed guess, not a genuine grid fit -- scan.py must NOT
    pass its .params through to build_trade_plan, since reward_risk.py has no
    way to tell a crude guess apart from a real fit once it receives non-None
    HestonParams (both get labelled 'Heston repriced'). heston_params must
    stay None, exactly as if calibration had failed outright, so the existing
    delta-approximation fallback path is used and labelled honestly."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=float("inf"), method="bs_fallback")

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration) as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_called_once()
    assert mock_build_plan.call_args.kwargs["heston_params"] is None, (
        "a bs_fallback CalibrationResult must not reach build_trade_plan as "
        "heston_params -- it would be indistinguishable from a genuine grid "
        "fit and mislabelled 'Heston repriced' downstream"
    )


@pytest.mark.asyncio
async def test_process_symbol_filters_heston_chain_to_delta_band():
    """Option A (docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md,
    findings #4/#5): strikes far from at-the-money dominate calibration cost.
    Filter heston_chain using each contract's own broker-reported delta
    (already present on every chain entry from fetch_option_chain_async,
    app/data/market.py:1210,1222) rather than a raw strike/price moneyness
    ratio -- a fixed moneyness band was found, during this plan's own
    preparation, to badly mismatch the REAL delta-selectable strike range at
    long DTE with realistic volatility. Using the real delta avoids that
    failure mode entirely. The band itself is DERIVED from this request's own
    contract_overrides (min_delta=0.20, max_delta=0.85 defaults here, +/-0.05
    safety margin -> effective band 0.15-0.90) rather than a hardcoded
    constant -- a hardcoded delta band was ALSO found, in a second audit
    round, to reproduce the same fixed-vs-configurable mismatch one layer
    down, since contract_rules.yaml's min_delta/max_delta are live per-request
    overrides a user can set anywhere in [0,1] via the Execution Parameters
    panel. A strike with delta==0 (greeks missing/unavailable -- market.py
    defaults to 0.0 rather than None) fails OPEN -- kept in, since a missing
    greek can't be used to judge selectability."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=0.01, method="heston_grid")

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_WIDE_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan),
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration) as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_called_once()
    called_chain = mock_heston.call_args.args[0]
    called_strikes = sorted(c["strike"] for c in called_chain)
    assert called_strikes == [100.0, 130.0, 190.0, 280.0, 340.0], (
        f"expected the five in-band-or-unknown-delta strikes, got {called_strikes}"
    )


@pytest.mark.asyncio
async def test_process_symbol_heston_delta_band_tracks_request_overrides():
    """Regression guard added after a post-implementation adversarial audit
    found zero test coverage for the request-derived override path -- every
    other Heston delta-band test only exercises the default-from-YAML
    fallback (empty contract_overrides). The whole point of this filter's
    design (see the plan's Round 2/3 adversarial-audit history) is that the
    calibration band must track THIS REQUEST's own min_delta/max_delta, not
    a fixed default -- a regression that silently reverted to the config
    default would pass every other test in this file. This test passes an
    explicit, non-default override (min_delta=0.75, max_delta=0.95) and
    confirms the resulting calibration band (0.70-1.00, after the +/-0.05
    safety margin, clamped to 1.0) actually shifts which strikes reach
    calibration, using the same _WIDE_MOCK_CHAIN fixture as the
    default-band test above so the two tests are directly comparable:
    default band includes [100, 130, 190, 280, 340]; this override's much
    higher band includes only the near-ITM/deep-ITM strikes plus the
    fail-open zero-delta strike: [25, 100, 130, 340]."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=0.01, method="heston_grid")

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_WIDE_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan),
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration) as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
            overrides={"min_delta": 0.75, "max_delta": 0.95},
        )

    mock_heston.assert_called_once()
    called_chain = mock_heston.call_args.args[0]
    called_strikes = sorted(c["strike"] for c in called_chain)
    assert called_strikes == [25.0, 100.0, 130.0, 340.0], (
        f"expected the override-derived band (0.70-1.00) to admit only the "
        f"near/deep-ITM strikes plus the fail-open zero-delta strike, "
        f"got {called_strikes}"
    )


@pytest.mark.asyncio
async def test_process_symbol_filtered_thin_heston_chain_falls_back_honestly():
    """Regression guard for the Task 1 + Task 2 interaction: if the delta-band
    filter (Task 2) narrows a real chain down to fewer than 3 strikes,
    calibrate_cached's own existing len(chain)<3 path
    (app/models/heston_cache.py:86-92) returns method='bs_fallback' before
    ever running the grid search. Combined with Task 1's fix, that fallback
    must be discarded (heston_params stays None), not silently displayed as
    'Heston repriced'. Uses the REAL (unmocked) calibrate_heston ->
    calibrate_cached path end-to-end, overriding the autouse
    _default_fast_heston_calibration fixture (conftest.py) for this one test
    only, so this interaction is actually exercised rather than assumed. The
    len(chain)<3 path returns before any scipy quad() call runs, so this test
    stays fast despite using the real calibration function."""
    from app.routers.scan import _process_symbol
    from app.models.heston import calibrate_heston as _real_calibrate_heston

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    # With the default (0.15, 0.90) effective band, only 2 of these 4 strikes
    # clear it (0.80, 0.45); the filtered heston_chain therefore has length
    # 2, below calibrate_cached's len(chain)<3 floor.
    thin_after_filter_chain = [
        {"strike": 25,  "expiry": "2026-06-20", "price": 460.0, "spread": 0.20,
         "delta": 0.99, "theta": -0.01, "ivRank": 40, "dte": 30, "right": "C", "volume": 500},
        {"strike": 130, "expiry": "2026-06-20", "price": 12.0, "spread": 0.20,
         "delta": 0.80, "theta": -0.03, "ivRank": 55, "dte": 30, "right": "C", "volume": 400},
        {"strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
         "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30, "right": "C", "volume": 500},
        {"strike": 300, "expiry": "2026-06-20", "price": 0.30, "spread": 0.20,
         "delta": 0.02, "theta": -0.01, "ivRank": 55, "dte": 30, "right": "C", "volume": 300},
    ]

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=thin_after_filter_chain)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        # Override the autouse default mock with the REAL function for this
        # one test, so calibrate_cached's real len(chain)<3 path actually runs.
        patch("app.routers.scan.calibrate_heston", side_effect=_real_calibrate_heston),
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    assert mock_build_plan.call_args.kwargs["heston_params"] is None, (
        "a filtered chain of only 2 strikes should hit calibrate_cached's "
        "real len(chain)<3 bs_fallback path, which Task 1's fix must then "
        "discard rather than pass through as heston_params"
    )


@pytest.mark.asyncio
async def test_heston_pricing_disabled_flag_skips_calibration(monkeypatch):
    """HESTON_PRICING_ENABLED=false must be a working kill switch."""
    import app.routers.scan as scan_module
    from app.routers.scan import _process_symbol

    monkeypatch.setattr(scan_module, "_HESTON_PRICING_ENABLED", False)
    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston") as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_not_called()
    assert mock_build_plan.call_args.kwargs["heston_params"] is None


async def _await_abandoned_heston_calibrations(timeout: float = 10.0) -> None:
    """Waits for every _run_heston_calibration task the caller abandoned
    (asyncio.wait gave up on it, leaving it pending-uncancelled -- by design,
    see its docstring) to actually finish on THIS test's event loop.

    A fixed asyncio.sleep sized to the fake calibration's duration is not
    enough: under full-suite load the executor thread can finish after the
    sleep, pytest-asyncio then closes the loop with the task still pending,
    and the task is later finalized as 'Task was destroyed but it is
    pending!' -- an asyncio ERROR that the first LATER test running
    gc.collect() + a caplog assertion
    (test_abandoned_heston_task_exception_does_not_leak_unretrieved) picks up.
    Until it is finalized, such a task also holds a permit on the
    module-global _HESTON_SEMAPHORE, which later tests assert on
    (HESTON-SCAN-TEST-INTERMITTENT-2026-09-29)."""
    tasks = {
        t for t in asyncio.all_tasks()
        if getattr(t.get_coro(), "__qualname__", "") == "_run_heston_calibration"
    }
    if not tasks:
        return
    _done, still_pending = await asyncio.wait(tasks, timeout=timeout)
    assert not still_pending, (
        f"{len(still_pending)} abandoned Heston calibration task(s) still "
        f"pending after {timeout}s"
    )
    # Let the tasks' done callbacks (_log_abandoned_heston_exception) run.
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_process_symbol_falls_back_when_calibration_exceeds_timeout(monkeypatch):
    """A calibration that runs past the wait_for ceiling must not stall this
    symbol — build_trade_plan must still be called promptly, with
    heston_params=None. Regression guard for the finding that
    heston_cache.py's internal 1s timeout does NOT bound real wall-clock time
    (its ThreadPoolExecutor.__exit__ blocks on shutdown(wait=True) regardless)."""
    import time
    import app.routers.scan as scan_module
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    # Shrink the call-site ceiling so the test itself stays fast; the fake
    # calibration below sleeps well past it.
    monkeypatch.setattr(scan_module, "_HESTON_CALIBRATION_TIMEOUT_S", 0.05)

    def _slow_calibrate(option_chain, S, r):
        time.sleep(0.5)
        return CalibrationResult(
            params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
            rmse=0.0, method="heston_grid",
        )

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    try:
        start = time.perf_counter()
        with (
            patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
            patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
            patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
            patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
            patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
            patch("app.routers.scan.score_stock", return_value=pass_card),
            patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
            patch("app.routers.scan.validate_contract", return_value=contract_score),
            patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
            patch("app.routers.scan.log_event"),
            patch("app.routers.scan.calibrate_heston", side_effect=_slow_calibrate),
        ):
            result = await _process_symbol(
                "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
            )
        elapsed = time.perf_counter() - start

        assert elapsed < 0.4, f"_process_symbol took {elapsed:.3f}s — the wait_for ceiling did not bound it"
        assert mock_build_plan.call_args.kwargs["heston_params"] is None
        assert result is not None
    finally:
        # By design (see _run_heston_calibration's docstring), the abandoned
        # calibration keeps running in the background and holds _HESTON_SEMAPHORE
        # until it actually finishes. Wait for it to do so before this test ends,
        # so its event loop doesn't tear down with that task still pending.
        await _await_abandoned_heston_calibrations()


_MULTI_MOCK_CHAIN = [
    {"strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
     "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30, "right": "C", "volume": 500},
    {"strike": 195, "expiry": "2026-06-20", "price": 1.80, "spread": 0.20,
     "delta": 0.35, "theta": -0.04, "ivRank": 55, "dte": 30, "right": "C", "volume": 400},
    {"strike": 200, "expiry": "2026-06-20", "price": 1.20, "spread": 0.20,
     "delta": 0.28, "theta": -0.03, "ivRank": 55, "dte": 30, "right": "C", "volume": 300},
]


@pytest.mark.asyncio
async def test_process_symbol_reuses_heston_params_for_alt_contracts():
    """The runner-up alternatives' estimate_rr calls (scan.py's alts loop) must
    reuse the SAME per-symbol calibration as the primary contract, not None.
    Uses a 3-contract chain so runner_ups (valid_scores[1:3]) is non-empty —
    _MOCK_CHAIN elsewhere in this file has only one contract and never
    exercises this loop at all."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult
    from app.scoring.reward_risk import RrResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=0.01, method="heston_grid")
    fake_rr = RrResult(rr_ratio=1.0, model_used="Heston repriced", estimated_exit_premium=3.0)

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MULTI_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan),
        patch("app.routers.scan.estimate_rr", return_value=fake_rr) as mock_estimate_rr,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration),
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    # Primary contract (strike 190) is scored via build_trade_plan (mocked separately,
    # not estimate_rr) — only the two runner-ups (195, 200) call estimate_rr directly.
    assert mock_estimate_rr.call_count == 2
    for call in mock_estimate_rr.call_args_list:
        assert call.kwargs["heston_params"] == fake_params


@pytest.mark.asyncio
async def test_heston_calibration_respects_scan_concurrency_limit(monkeypatch):
    """Regression guard: an ungated (or per-request-gated) executor could let
    far more than _HESTON_CONCURRENCY symbols calibrate at once, starving each
    other out via the timeout ceiling. Calibration must be gated by the
    module-level _HESTON_SEMAPHORE (not the `sem` parameter passed in below,
    which only gates this function's own network-fetch phases) — so peak
    concurrent calibrations across many symbols processed at once, all
    sharing the process-wide _HESTON_SEMAPHORE, must never exceed
    _HESTON_CONCURRENCY. This also implicitly covers the cross-scan-overlap
    scenario: even if this test constructed a second, independent `sem` and
    ran a second batch of _process_symbol calls "concurrently" with these
    ones, they'd still share the same module-level _HESTON_SEMAPHORE and
    _HESTON_EXECUTOR.

    _HESTON_EXECUTOR's own max_workers happens to equal _HESTON_CONCURRENCY
    too, so a peak <= _HESTON_CONCURRENCY result alone doesn't prove the
    SEMAPHORE is what's enforcing the cap — the executor's worker pool would
    enforce the same bound even with no semaphore at all. To isolate the
    semaphore's effect, this test patches in a much wider executor for its
    duration: if the semaphore weren't doing real work, peak concurrency
    would be free to exceed the semaphore's cap here.

    Both the semaphore and the executor are monkeypatched to a small fixed
    TEST_CONCURRENCY rather than the real (host-dependent) _HESTON_CONCURRENCY
    — on a high-core-count machine the live value could be 60+, which would
    spin up hundreds of OS threads and dozens of symbols just for this one
    test. _run_heston_calibration looks up _HESTON_SEMAPHORE/_HESTON_EXECUTOR
    as module globals at call time, so patching the module attributes is
    sufficient to redirect it."""
    import threading
    import time
    import concurrent.futures
    import app.routers.scan as scan_module
    from app.routers.scan import _process_symbol, _SCAN_CONCURRENCY
    from app.models.heston import HestonParams, CalibrationResult

    TEST_CONCURRENCY = 4
    wide_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=TEST_CONCURRENCY * 4, thread_name_prefix="test-heston-wide",
    )
    monkeypatch.setattr(scan_module, "_HESTON_EXECUTOR", wide_executor)
    monkeypatch.setattr(scan_module, "_HESTON_SEMAPHORE", asyncio.Semaphore(TEST_CONCURRENCY))

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(_SCAN_CONCURRENCY)  # gates only this test's own network-fetch mocks
    mock_client = MagicMock()
    symbol_count = TEST_CONCURRENCY + 10

    lock = threading.Lock()
    current = 0
    peak = 0

    def _tracking_calibrate(option_chain, S, r):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        time.sleep(0.05)
        with lock:
            current -= 1
        return CalibrationResult(
            params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
            rmse=0.0, method="heston_grid",
        )

    try:
        with (
            patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
            patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
            patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
            patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
            patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
            patch("app.routers.scan.score_stock", return_value=pass_card),
            patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
            patch("app.routers.scan.validate_contract", return_value=contract_score),
            patch("app.routers.scan.build_trade_plan", return_value=fake_plan),
            patch("app.routers.scan.log_event"),
            patch("app.routers.scan.calibrate_heston", side_effect=_tracking_calibrate),
        ):
            await asyncio.gather(*[
                _process_symbol(f"SYM{i}", "Bullish", "Swing", mock_client, sem, "test-scan-id")
                for i in range(symbol_count)
            ])
        # Normally a no-op (0.05s fakes vs the 2.0s ceiling); under heavy load
        # a symbol could be abandoned, and its task must finish on this loop.
        await _await_abandoned_heston_calibrations()
    finally:
        wide_executor.shutdown(wait=True)

    assert peak <= TEST_CONCURRENCY, (
        f"peak concurrent calibrations was {peak}, expected <= {TEST_CONCURRENCY} — "
        "even with a much wider executor available, the semaphore must be the thing "
        "holding this bound"
    )


@pytest.mark.asyncio
async def test_run_heston_calibration_holds_semaphore_until_real_completion():
    """Precise regression guard: a caller giving up early — here via
    asyncio.wait with a short timeout, the same give-up-without-cancelling
    contract the real call site relies on — must NOT release
    _HESTON_SEMAPHORE before the underlying calibrate_heston call actually
    finishes — otherwise a new attempt could be admitted while this one still
    occupies a real worker, defeating the point of gating by the semaphore
    at all."""
    import time
    from app.routers.scan import _run_heston_calibration, _HESTON_SEMAPHORE, _HESTON_CONCURRENCY
    from app.models.heston import HestonParams, CalibrationResult

    def _slow(option_chain, S, r):
        time.sleep(0.3)
        return CalibrationResult(
            params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
            rmse=0.0, method="heston_grid",
        )

    with patch("app.routers.scan.calibrate_heston", side_effect=_slow):
        task = asyncio.ensure_future(_run_heston_calibration([], 100.0))
        # Give up without cancelling the task — exactly how _process_symbol
        # does it (asyncio.wait leaves an unfinished task pending-uncancelled).
        await asyncio.wait({task}, timeout=0.05)

        # The caller gave up, but the real job (0.3s) is still running — its
        # semaphore permit must NOT have been released yet.
        assert _HESTON_SEMAPHORE._value == _HESTON_CONCURRENCY - 1, (
            "semaphore permit was released before the underlying calibration "
            "actually finished — a new attempt could now be admitted while "
            "this one still occupies a real worker"
        )

        # Let the real job finish and release its permit, restoring full
        # capacity so this test doesn't leak state into later tests.
        await task
        assert _HESTON_SEMAPHORE._value == _HESTON_CONCURRENCY


@pytest.mark.asyncio
async def test_abandoned_heston_task_exception_does_not_leak_unretrieved(monkeypatch, caplog):
    """Regression guard: a calibration that the caller gives up on (its
    asyncio.wait ceiling elapses), and which then raises AFTER being
    abandoned, must not produce ANY asyncio ERROR log — neither the
    'Task exception was never retrieved' finalizer error (closed by the
    done-callback) NOR the 'exception in shielded future' error that
    asyncio.shield ITSELF emits on Python 3.12+ for an abandoned shielded
    task that raises (closed by not using shield at the call site — plain
    asyncio.wait leaves the task pending-but-uncancelled and logs nothing).
    Distinct from the clean-timeout and immediate-raise paths: here the raise
    happens on the worker thread only after the caller has already moved on."""
    import gc
    import logging
    import time
    import app.routers.scan as scan_module
    from app.routers.scan import _process_symbol

    monkeypatch.setattr(scan_module, "_HESTON_CALIBRATION_TIMEOUT_S", 0.05)

    def _slow_then_raise(option_chain, S, r):
        time.sleep(0.2)
        raise RuntimeError("simulated failure after caller gave up")

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    caplog.set_level(logging.ERROR, logger="asyncio")
    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan),
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", side_effect=_slow_then_raise),
    ):
        await _process_symbol("AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id")
        # Wait for the abandoned task to actually raise and be finalized.
        await _await_abandoned_heston_calibrations()

    # Force finalization of the now-unreferenced task so any unretrieved
    # exception would be logged by asyncio's default finalizer handler.
    gc.collect()

    leaked = [rec.getMessage() for rec in caplog.records
              if rec.name == "asyncio" and rec.levelno >= logging.ERROR]
    assert not leaked, (
        "abandoned Heston task produced asyncio ERROR log noise "
        f"(unretrieved exception or shielded-future error): {leaked}"
    )


def test_default_heston_calibration_fixture_is_active():
    """conftest.py's autouse _default_fast_heston_calibration fixture (added
    later in this same task, alongside the scan.py wiring below) must be
    patching app.routers.scan.calibrate_heston for every test by default —
    otherwise pre-existing multi-contract-chain tests elsewhere in the suite
    (test_alternatives.py, test_scan_router_spreads.py, test_shortlist.py)
    silently start doing real scipy numerical integration."""
    import app.routers.scan as scan_module
    from unittest.mock import Mock
    assert isinstance(scan_module.calibrate_heston, Mock)


# ── O-2: Candle pre-warm endpoint ─────────────────────────────────────────────

_FAKE_CANDLE_ROW = [
    {"time": "2026-01-02", "open": 100.0, "high": 105.0,
     "low": 95.0, "close": 102.0, "volume": 1000}
]


@pytest.mark.asyncio
async def test_prewarm_candles_async_calls_fetch_for_each_symbol():
    """O-2: prewarm_candles_async must call fetch_candles_async once per symbol."""
    from app.data.market import prewarm_candles_async

    with patch("app.data.market.fetch_candles_async", AsyncMock(return_value=_FAKE_CANDLE_ROW)) as mock_fetch:
        count = await prewarm_candles_async(["AAPL", "MSFT", "NVDA"])

    assert mock_fetch.call_count == 3
    symbols_called = {c[0][1] for c in mock_fetch.call_args_list}  # [0] = positional; [1] = symbol
    assert symbols_called == {"AAPL", "MSFT", "NVDA"}
    assert count == 3


def test_prewarm_endpoint_returns_prewarmed_count(client):
    """O-2: POST /api/scan/prewarm-candles must return {"prewarmed": N}."""
    with patch("app.data.market.fetch_candles_async", AsyncMock(return_value=_FAKE_CANDLE_ROW)):
        r = client.post("/api/scan/prewarm-candles", json={"symbols": ["AAPL", "MSFT"]})

    assert r.status_code == 200
    data = r.json()
    assert "prewarmed" in data
    assert data["prewarmed"] == 2
