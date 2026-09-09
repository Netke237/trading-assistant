"""Piece 3 — the stock stop every trade card is built around.

`resolve_stock_stop` is the one place that decides WHICH stop applies: the
structural+ATR final stop whenever the bar feed can form one, else Step 3's
flat percentage. Before piece 3 that decision did not exist — `build_trade_plan`
derived a flat percentage move off the stock price and every symbol in the
universe got the same -3%.

These tests pin the split itself, the shape of the wire block, and the two
places a stop can silently regress: the endpoint that recomputes a plan after a
Step 6 contract override, and the fallback path.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scoring.exit_plan import final_stop_out, resolve_stock_stop

# 30 bars, high 190 / low 182, close 187 — one true range of 8.00 on every bar,
# so ATR(14) == 8.00 exactly and a 2x floor sits 16.00 from entry.
RANGED = [
    {"time": f"2026-0{i//10+1}-{i%28+1:02d}", "open": 184.0, "high": 190.0,
     "low": 182.0, "close": 187.0, "volume": 1_000_000}
    for i in range(30)
]
# The same 30 bars with no range at all — `_atr` returns 0.0.
FLAT = [
    {"time": f"2026-0{i//10+1}-{i%28+1:02d}", "open": 185.0, "high": 185.0,
     "low": 185.0, "close": 185.0, "volume": 1_000_000}
    for i in range(30)
]

COMPUTED_AT = "2026-09-09T12:00:00+00:00"


def test_a_real_feed_resolves_the_structural_atr_stop():
    r = resolve_stock_stop(RANGED, "Bullish", 185.0, 8.0, 2.0, 0.03)
    assert r.source == "final_stop"
    assert r.final_stop is not None
    assert r.atr == 8.0
    assert round(r.price, 2) == 169.00      # 185 - 2 * 8
    # Nowhere near the flat percentage it replaced.
    assert round(r.price, 2) != round(185.0 * 0.97, 2)


def test_a_dead_feed_falls_back_to_the_flat_pct():
    """atr == 0 is the degenerate branch: fewer than two bars, or a stale feed
    repeating one bar. `compute_final_stop` on such a feed returns an ATR floor
    sitting exactly ON entry — a zero-width stop every consumer downstream
    would read as a real level."""
    r = resolve_stock_stop(FLAT, "Bullish", 185.0, 0.0, 2.0, 0.03)
    assert r.source == "flat_fallback"
    assert r.final_stop is None
    assert r.atr == 0.0
    assert round(r.price, 2) == round(185.0 * 0.97, 2)


def test_the_fallback_honours_the_step_3_parameter_in_both_directions():
    """The flat percentage is Step 3's "Bullish stop %" / "Bearish stop %".
    Demoted to a fallback, but NOT dead: on this path it is the only thing
    deciding the number, and a user who moves it must see it move."""
    bull = resolve_stock_stop(FLAT, "Bullish", 185.0, 0.0, 2.0, 0.10)
    bear = resolve_stock_stop(FLAT, "Bearish", 185.0, 0.0, 2.0, 0.10)
    assert round(bull.price, 2) == round(185.0 * 0.90, 2)
    assert round(bear.price, 2) == round(185.0 * 1.10, 2)


def test_a_bearish_stop_sits_above_entry_on_both_branches():
    """Direction is not cosmetic here: a bearish stop above entry and a bullish
    stop below it are what make `stock_paths >= invalidation_price` in
    first_passage measure an invalidation rather than a profit."""
    assert resolve_stock_stop(RANGED, "Bearish", 185.0, 8.0, 2.0, 0.03).price > 185.0
    assert resolve_stock_stop(FLAT, "Bearish", 185.0, 0.0, 2.0, 0.03).price > 185.0
    assert resolve_stock_stop(RANGED, "Bullish", 185.0, 8.0, 2.0, 0.03).price < 185.0
    assert resolve_stock_stop(FLAT, "Bullish", 185.0, 0.0, 2.0, 0.03).price < 185.0


def test_a_wide_multiplier_cannot_drive_a_bullish_stop_to_or_below_zero():
    """entry 3.00 with ATR 2.00 and a 2x floor is -1.00 unclamped.
    `estimate_stock_first_passage` switches on `invalidation_price > 0` to price
    the stop leg at all, so a non-positive stop drops that leg silently instead
    of failing."""
    r = resolve_stock_stop(RANGED, "Bullish", 3.00, 2.0, 2.0, 0.03)
    assert r.price == 0.01
    assert r.source == "final_stop"


def test_the_wire_block_reports_both_candidates_not_just_the_winner():
    """The "Bottom (final stop)" row prints the structural level, the ATR floor
    and the distance between them — so the block has to carry the loser too."""
    r = resolve_stock_stop(RANGED, "Bullish", 185.0, 8.0, 2.0, 0.03)
    out = final_stop_out(r, COMPUTED_AT)
    assert out is not None
    assert out.price == 169.00
    assert out.source == "final_stop"
    assert out.stopSource == "atr_widened"
    assert out.atrFloorPrice == 169.00
    assert out.atr == 8.0
    assert out.computedAt == COMPUTED_AT
    # The LOSER is reported too. Structure detection does find a swing low at
    # 182.00 on this feed; it lost to the floor because 185 - 182 = 3.00 is
    # narrower than 2 x ATR = 16.00, and the row prints both plus the gap.
    assert out.structuralSource == "swing_low"
    assert out.structuralPrice == 182.00
    assert out.distanceDollar == 13.00      # |182.00 - 169.00|


def test_the_block_price_is_the_stop_price_rounded_to_the_same_cent():
    """The provenance row and the Invalidation field sit inches apart on one
    card. They must print the same number, not two roundings of it."""
    r = resolve_stock_stop(RANGED, "Bullish", 185.37, 8.0, 2.0, 0.03)
    out = final_stop_out(r, COMPUTED_AT)
    assert out.price == round(r.price, 2)


def test_no_block_for_a_fallback_stop_or_a_failed_resolution():
    """A block of nulls would read on the card as "we looked and found
    nothing". Absent reads as "not computed", which is what actually happened."""
    assert final_stop_out(resolve_stock_stop(FLAT, "Bullish", 185.0, 0.0, 2.0, 0.03), COMPUTED_AT) is None
    assert final_stop_out(None, COMPUTED_AT) is None


# ── The Step 6 contract override ──────────────────────────────────────────────

def _recompute(payload: dict):
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app).post("/api/contracts/recompute-plan", json=payload)


BASE = {
    "symbol": "AAPL", "direction": "Bullish", "stock_price": 185.0,
    "strike": 190, "dte": 30, "premium": 2.50, "delta": 0.45, "spread": 0.20,
}
BLOCK = {
    "price": 169.00, "source": "final_stop", "stopSource": "atr_widened",
    "structuralSource": None, "structuralPrice": None,
    "atrFloorPrice": 169.00, "distanceDollar": None, "atr": 8.0,
    "computedAt": COMPUTED_AT,
}


def test_a_contract_override_keeps_the_stop_the_scan_resolved():
    """`mergePlan` replaces `exit` wholesale. An endpoint that returned no stop
    of its own would wipe `finalStop` and drop `invalidation` back to a flat
    percentage for exactly the cards a user hand-picked a contract on."""
    r = _recompute({**BASE, "final_stop": BLOCK})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exit"]["invalidation"] == 169.00
    assert body["exit"]["finalStop"]["price"] == 169.00
    assert body["exit"]["finalStop"]["stopSource"] == "atr_widened"
    assert body["exit"]["finalStop"]["computedAt"] == COMPUTED_AT


def test_the_override_does_not_move_the_stop_when_the_contract_changes():
    """The stop is a STOCK level. Which contract is being traded has no bearing
    on where the structure sits, so two different contracts on one symbol must
    come back with the same stop — and both with the scan's, not a re-derived
    one that a feed which has moved on since would answer differently."""
    a = _recompute({**BASE, "final_stop": BLOCK})
    b = _recompute({**BASE, "strike": 200, "premium": 1.10, "final_stop": BLOCK})
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["exit"]["invalidation"] == b.json()["exit"]["invalidation"] == 169.00


def test_a_card_with_no_resolved_stop_falls_back_and_echoes_nothing():
    """A scan session persisted before piece 3 carries no `finalStop`. The
    endpoint must not invent one."""
    from app.services.config_loader import load_reward_risk_cfg
    r = _recompute(BASE)
    assert r.status_code == 200, r.text
    body = r.json()
    expected = round(185.0 * (1 - load_reward_risk_cfg()["bullish_invalidation_pct"]), 2)
    assert body["exit"]["invalidation"] == expected
    assert body["exit"]["finalStop"] is None


def test_the_step_3_override_still_reaches_the_fallback_through_the_endpoint():
    """Same demotion as the scan's: inert when a stop is supplied, live when
    one is not."""
    with_stop = _recompute({**BASE, "final_stop": BLOCK, "rr_bullish_invalidation_pct": 0.10})
    without = _recompute({**BASE, "rr_bullish_invalidation_pct": 0.10})
    assert with_stop.json()["exit"]["invalidation"] == 169.00
    assert without.json()["exit"]["invalidation"] == round(185.0 * 0.90, 2)


@pytest.mark.parametrize("bad", [
    {**BLOCK, "source": "made_up"},
    {**BLOCK, "stopSource": "made_up"},
    {**BLOCK, "structuralSource": "made_up"},
])
def test_a_malformed_stop_block_is_rejected_rather_than_used(bad):
    """The block round-trips through the client, so its enums are validated on
    the way back in — a `source` nothing renders would print an empty
    justification line next to a real dollar stop."""
    assert _recompute({**BASE, "final_stop": bad}).status_code == 422
