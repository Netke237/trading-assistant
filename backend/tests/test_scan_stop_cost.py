"""The stop-vs-premium gate, priced at SCAN time (Phase B3).

Spec: docs/superpowers/plans/2026-09-02-gate-basis-spec.md §2.3, test 9.
Decision: B3-SCOPED-STOP-2026-09-08.

The ranking table was the last surface in the app with no gate on it. Three
things can go wrong here quietly, and each has a test below:

1. The row loses its verdict. A missing gate reads exactly like an
   unremarkable candidate.
2. The verdict is priced against the WRONG STOP -- the flat percentage
   `exit.invalidation` rather than the structural/ATR level the decision
   picked. No rendering test would ever catch this: both stops produce a
   plausible-looking percentage.
3. The gate stops discriminating. The whole reason for the Black-Scholes
   basis is that the old delta-linear estimator pinned four of eight strikes
   on the spec's reference chain at exactly 100%, so it could not tell a 220
   call from a 240 call. A gate that answers CAUTION to everything has
   regressed to that, while still looking like it works.

FIXTURES: real OHLCV from tests/fixtures/, not a hand-made feed. The first
draft of this file invented a flat 30-bar series, which scores trend 0 and is
REJECTed at the pre-screen -- every test then iterated an empty candidate list
and passed while asserting nothing. `_candidates` therefore asserts the list is
non-empty rather than skipping.
"""

import json
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from app.scoring.exit_plan import compute_final_stop
from app.scoring.stock_scorer import _atr
from app.scoring.stop_cost import compute_stop_cost, horizon_key
from app.services.config_loader import load_exit_plan_cfg, load_scoring_cfg

_FIXTURES = Path(__file__).parent / "fixtures"
_HORIZON = "Swing"

# `min_stock_score` is relaxed because these fixtures are real price history,
# not a series tuned to score well -- MSFT bullish lands just under the
# validator's default 55 and every contract is rejected before a card is ever
# built. Relaxing the CONTRACT gate leaves the gate under test untouched: the
# stop cost is computed from candles, strike, dte, premium and IV, none of
# which this override moves.
_OVERRIDES = {"min_stock_score": 40}


def _candles(symbol: str) -> list[dict]:
    return json.loads((_FIXTURES / f"{symbol}_candles.json").read_text())


def _contract(price: float, *, strike_mult: float, dte: int = 45) -> dict:
    """One synthetic contract on a real underlying.

    The expiry is derived from `dte` against TODAY. A hardcoded date silently
    goes stale -- the first draft used one, and every contract was rejected
    `dte_too_short` because the date had passed months before.
    """
    strike = round(price * strike_mult / 5) * 5
    premium = round(max(0.0, price - strike) + price * 0.02, 2)
    return {
        "strike": strike, "expiry": (date.today() + timedelta(days=dte)).isoformat(),
        "price": premium, "bid": round(premium - 0.03, 2), "ask": round(premium + 0.03, 2),
        "spread": 0.05, "delta": 0.55, "theta": -0.06, "ivRank": 50, "dte": dte,
        "right": "C", "volume": 5000, "open_interest": 8000,
    }


def _candidates(client, symbol="MSFT", *, strike_mult=1.0, dte=45, extra_patches=(), iv=None):
    candles = _candles(symbol)
    price = candles[-1]["close"]
    contract = _contract(price, strike_mult=strike_mult, dte=dte)
    if iv is not None:
        contract["iv"] = iv
    chain = [contract]
    with ExitStack() as stack:
        # HERMETIC ON PURPOSE. /api/scan pre-fetches OHLCV from the DB and quotes
        # in one batch, and `_process_symbol` prefers both over the per-symbol
        # fetches below -- so with a DB that another test has seeded (
        # test_scan_db_first does exactly that, in the same session's database)
        # the patched candles are never consulted at all, the scan scores real
        # stored bars instead, and this module fails ONLY when run after that
        # one. Neutralise both prefetch paths so the fixture is the input
        # whatever ran first. `get_bars` is patched at its source module because
        # _run_scan imports it inside the function body.
        stack.enter_context(patch("app.services.historical_store.get_bars", AsyncMock(return_value=[])))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", return_value={}))
        # Signal confidence is memoised in a SQLITE FILE ON DISK
        # (backend/data/confidence_cache.db), so it survives between runs and
        # between suites. It feeds a scoring rule, which moves the stock score,
        # which decides whether this symbol survives at all -- so leaving it
        # alone makes this module pass or fail depending on what a previous
        # test run happened to leave in that file. Pin it, and never write to
        # it. The value is arbitrary but must be stable.
        stack.enter_context(patch("app.data.confidence_cache.get_cached",
                                  return_value={"confidence": 70, "sample_size": 40}))
        stack.enter_context(patch("app.data.confidence_cache.set_cached", AsyncMock()))
        stack.enter_context(patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=price)))
        stack.enter_context(patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=candles)))
        stack.enter_context(patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=chain)))
        stack.enter_context(patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Test Co")))
        stack.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)))
        for p in extra_patches:
            stack.enter_context(p)
        r = client.post("/api/scan", json={
            "universe": [symbol], "direction": "Bullish",
            "horizon": _HORIZON, "overrides": _OVERRIDES,
        })
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    # NOT a skip. Every assertion in this file is about a field on a candidate,
    # so an empty list makes the whole module vacuously green.
    assert cands, "fixture produced no surviving candidate; every assertion below would be vacuous"
    return cands, price, candles


def test_every_candidate_carries_the_gate(client):
    cands, _, _ = _candidates(client)
    for c in cands:
        assert "stopCostPct" in c and "stopCostStatus" in c
        assert c["stopCostPct"] is not None, "gate did not compute on a healthy fixture"
        assert c["stopCostStatus"] in ("PASS", "CAUTION")
        assert 0.0 <= c["stopCostPct"] <= 100.0


def test_gate_is_priced_at_the_structural_stop_not_the_flat_invalidation(client):
    """THE test of the decision, not of the plumbing.

    `exit.invalidation` is a flat percentage move off the stock price
    (trade_plan.py:119-121). B3 priced the badge at `compute_final_stop`'s
    wider-of-structural-or-ATR level instead. Only reproducing the arithmetic
    can tell which stop was used.
    """
    cands, price, candles = _candidates(client)
    c = cands[0]
    cd = c["contractDetails"]

    atr = _atr(candles, 14)
    assert atr > 0, "fixture must have a real range or this test proves nothing"
    final = compute_final_stop(
        candles, "Bullish", price, atr, load_exit_plan_cfg()["stop"]["atr_multiplier"],
    )
    flat = float(c["exit"]["invalidation"])
    assert abs(round(final.price, 2) - flat) > 0.01, (
        "the two stops coincide on this fixture, so it cannot distinguish them"
    )

    def cost_at(stop):
        return compute_stop_cost(
            stop_price=round(stop, 2), stock_price=price, strike=float(cd["strike"]),
            dte=int(cd["dte"]), premium=float(cd["mid"]), is_call=True,
            iv_pct=cd["iv"], horizon_preset=_HORIZON,
        )

    expected = cost_at(final.price)
    assert expected is not None
    assert c["stopCostPct"] == pytest.approx(round(expected.fraction * 100, 1))
    assert c["stopCostStatus"] == expected.status

    # Positively exclude the stop the decision rejected.
    wrong = cost_at(flat)
    assert wrong is not None, "the flat stop must be priceable, or this exclusion is empty"
    assert round(wrong.fraction * 100, 1) != pytest.approx(round(expected.fraction * 100, 1)), (
        "the two stops price identically here, so this test cannot tell them apart"
    )
    assert c["stopCostPct"] != pytest.approx(round(wrong.fraction * 100, 1)), (
        "badge was priced at exit.invalidation -- the flat percentage stop"
    )


def test_gate_still_discriminates_across_the_chain(client):
    """The reason the basis moved at all.

    Deep in the money the stop keeps most of the contract's value; far out of
    the money it does not. The delta-linear estimator this replaced pinned both
    ends at 100%. If every strike comes back the same verdict, the gate has
    regressed to restating that a long option's maximum loss is its premium.
    """
    seen = {}
    for mult in (0.70, 0.85, 1.0):
        cands, _, _ = _candidates(client, strike_mult=mult)
        pct = cands[0]["stopCostPct"]
        assert pct is not None
        seen[mult] = (pct, cands[0]["stopCostStatus"])

    pcts = [p for p, _ in seen.values()]
    assert pcts == sorted(pcts), f"loss share must rise as the strike rises: {seen}"
    assert max(pcts) - min(pcts) > 20.0, f"gate barely separates the chain: {seen}"
    assert {s for _, s in seen.values()} == {"PASS", "CAUTION"}, (
        f"both verdicts must be reachable across one chain: {seen}"
    )
    assert max(pcts) < 100.0 or min(pcts) < 100.0, "everything pinned at a total loss"


def test_unpriceable_atr_yields_not_computed_and_keeps_the_candidate(client):
    """A feed too flat or too short to form a true range must produce
    "not computed", never a PASS -- and must not take the candidate down with
    it. The ATR floor would otherwise sit exactly on the entry price and the
    gate would grade a zero-distance stop as a real reading."""
    cands, _, _ = _candidates(client, extra_patches=[patch("app.routers.scan._atr", return_value=0.0)])
    for c in cands:
        assert c["stopCostPct"] is None
        assert c["stopCostStatus"] is None


def test_gate_failure_never_drops_a_candidate(client):
    """Every other per-symbol enrichment in _process_symbol degrades rather
    than raises. This one carries less than any of them, so it must too."""
    cands, _, _ = _candidates(client, extra_patches=[
        patch("app.routers.scan.compute_final_stop", side_effect=RuntimeError("boom")),
    ])
    for c in cands:
        assert c["stopCostPct"] is None
        assert c["stopCostStatus"] is None


def test_verdict_and_percentage_agree_with_the_horizon_line(client):
    """The printed pair has to decide the verdict, the same discipline the card
    holds itself to. A badge reading 'PASS 78%' beside a 70% line is the defect
    Phase B round 1 found on the other surface."""
    pass_max = load_scoring_cfg()["horizons"][horizon_key(_HORIZON)]["stop_premium"]["pass_max_fraction"]
    for mult in (0.70, 0.85, 1.0):
        c = _candidates(client, strike_mult=mult)[0][0]
        pct, status = c["stopCostPct"], c["stopCostStatus"]
        assert pct is not None
        expected = "PASS" if pct / 100.0 < pass_max else "CAUTION"
        assert status == expected, f"{pct}% graded {status} against a {pass_max * 100:.0f}% line"


def test_a_decimal_convention_iv_is_refused_not_repriced_at_it(client):
    """`iv` is ABSOLUTE volatility in PERCENT everywhere in this codebase. A
    vendor sending the decimal convention (0.35 for 35%) repriced at 0.35% vol
    reports almost the whole premium as lost at any stop -- a confident,
    plausible, badly wrong CAUTION. The structural-stop ENDPOINT refuses that
    input outright (gt=1.0); a scan cannot 422, so it must drop the number and
    invert the mid instead.
    """
    suspect = _candidates(client, strike_mult=0.70, iv=0.35)[0][0]
    honest = _candidates(client, strike_mult=0.70)[0][0]

    assert suspect["stopCostPct"] is not None, "the gate must still answer, not go dark"
    # Identical to the no-vendor-IV path: the suspect number was dropped, not used.
    assert suspect["stopCostPct"] == pytest.approx(honest["stopCostPct"])
    assert suspect["stopCostStatus"] == honest["stopCostStatus"]
    # And positively: 0.35% vol on a deep-ITM call would price it at nearly
    # pure intrinsic and report a large loss share. It must not read that way.
    assert suspect["stopCostPct"] < 60.0, (
        "priced at 0.35% vol -- the decimal convention was taken at face value"
    )


def test_a_plausible_percent_iv_is_still_used(client):
    """The guard must not throw away real readings. A vendor IV well inside the
    band has to change the answer, or the band is just a disguised `iv=None`."""
    high = _candidates(client, strike_mult=0.70, iv=90.0)[0][0]
    solved = _candidates(client, strike_mult=0.70)[0][0]
    assert high["stopCostPct"] is not None
    assert high["stopCostPct"] != pytest.approx(solved["stopCostPct"]), (
        "an in-band vendor IV was ignored -- the guard is dropping good input too"
    )
