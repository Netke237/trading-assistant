"""The stop-vs-premium gate, priced at SCAN time (Phase B3).

Spec: docs/superpowers/plans/2026-09-02-gate-basis-spec.md §2.3, test 9.
Decision: B3-SCOPED-STOP-2026-09-08.

The ranking table was the last surface in the app with no gate on it. Three
things can go wrong here quietly, and each has a test below:

1. The row loses its verdict. A missing gate reads exactly like an
   unremarkable candidate.
2. The verdict is priced against the WRONG STOP -- a flat percentage move off
   the stock price rather than the structural/ATR level the decision picked.
   No rendering test would ever catch this: both stops produce a
   plausible-looking percentage. (`exit.invalidation` carried that flat
   percentage until piece 3 repointed it at the resolved stop; it is no longer
   a witness for the rejected basis.)
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
# which this override moves. The scan no longer accepts `min_stock_score` as a
# request override (ScanRequest._drop_stock_mode_min_score), so the floor is
# relaxed in the validator's loaded config instead.
_MIN_STOCK_SCORE = 40


def _relaxed_contract_cfg() -> dict:
    import copy
    import app.scoring.contract_validator as cv
    cfg = copy.deepcopy(cv._load_config())
    cfg["hard_reject"]["min_stock_score"] = _MIN_STOCK_SCORE
    return cfg


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
        # With no fundamentals calendar the scan falls back to a LIVE yfinance
        # lookup of the symbol's next earnings/dividend dates. Offline it fails
        # and the event rule sees none; on a networked CI runner it answered
        # with MSFT's real earnings date (inside Swing's caution window), which
        # moved the stock score below this fixture's relaxed floor and dropped
        # every candidate. Pin it to "no dates", as offline.
        stack.enter_context(patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))))
        stack.enter_context(patch("app.scoring.contract_validator._load_config",
                                  return_value=_relaxed_contract_cfg()))
        for p in extra_patches:
            stack.enter_context(p)
        r = client.post("/api/scan", json={
            "universe": [symbol], "direction": "Bullish", "horizon": _HORIZON,
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


def test_gate_is_priced_at_the_structural_stop_not_a_flat_percentage(client):
    """THE test of the decision, not of the plumbing.

    B3 priced the badge at `compute_final_stop`'s wider-of-structural-or-ATR
    level rather than at a flat percentage move off the stock price. Only
    reproducing the arithmetic can tell which stop was used: both produce a
    plausible-looking percentage.

    UPDATED BY PIECE 3. This used to read the flat stop off
    `exit.invalidation`, which no longer holds one -- piece 3 repointed that
    field at the same resolved stop, so the two now coincide BY DESIGN and
    reading it back would compare the structural stop against itself and prove
    nothing. The rejected stop is therefore reconstructed from
    risk_rules.yaml's own `bullish_invalidation_pct`, which is what
    `exit.invalidation` used to carry. The coincidence is asserted separately,
    as a requirement, in
    test_scan_endpoint.py::test_scan_badge_and_invalidation_grade_the_same_stop.
    """
    from app.services.config_loader import load_reward_risk_cfg

    cands, price, candles = _candidates(client)
    c = cands[0]
    cd = c["contractDetails"]

    atr = _atr(candles, 14)
    assert atr > 0, "fixture must have a real range or this test proves nothing"
    final = compute_final_stop(
        candles, "Bullish", price, atr, load_exit_plan_cfg()["stop"]["atr_multiplier"],
    )
    flat = round(price * (1 - load_reward_risk_cfg()["bullish_invalidation_pct"]), 2)
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
        "badge was priced at the flat percentage stop"
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


def test_a_failed_stop_resolution_never_drops_a_candidate(client):
    """Every other per-symbol enrichment in _process_symbol degrades rather
    than raises. The gate carries less than any of them, so it must too.

    PIECE 3 WIDENED THIS. The badge and `exit.invalidation` now share one
    resolution, so a throw here takes out both -- and the card still needs a
    stop to print. The candidate must survive with the flat-percentage fallback
    and NO provenance block, which is what "not computed" looks like on every
    surface at once.
    """
    from app.services.config_loader import load_reward_risk_cfg

    cands, price, _ = _candidates(client, extra_patches=[
        patch("app.routers.scan.resolve_stock_stop", side_effect=RuntimeError("boom")),
    ])
    expected_flat = round(price * (1 - load_reward_risk_cfg()["bullish_invalidation_pct"]), 2)
    for c in cands:
        assert c["stopCostPct"] is None
        assert c["stopCostStatus"] is None
        assert c["exit"]["finalStop"] is None
        assert c["exit"]["invalidation"] == expected_flat


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


@pytest.mark.parametrize("planted_iv", [0.35, 25.0, 90.0, 400.0])
def test_contract_iv_never_moves_the_gate(client, planted_iv):
    """The gate ALWAYS inverts this contract's own mid. No value of
    `contract["iv"]` may move the answer.

    This replaces two earlier tests that pinned the opposite, one of which
    asserted an in-band `iv` MUST change the result. That was the defect, not
    the contract. `contract["iv"]` is not reliably this contract's volatility:
    when the chain carries no vendor IV, the ATM fill in `_process_symbol`
    (~scan.py:640) broadcasts the ATM's inverted vol into EVERY strike lacking
    one, so a 20-delta wing is handed the ATM's number. It is in-band, so no
    range guard can catch it, and it flattens exactly the smile this gate
    exists to read.

    The invariant that makes the gate coherent is arithmetic, not a range:
    `loss = premium - BS(stop, K, T, r, iv)` only subtracts like from like
    when `iv` reproduces the very mid `premium` came from. Inverting that mid
    guarantees it by construction; any supplied number can only break it.

    The parameters span the decimal-convention slip (0.35), a plausible ATM
    broadcast (25.0), a high but in-band reading (90.0) and an absurd one
    (400.0). All four must be inert.
    """
    planted = _candidates(client, strike_mult=0.70, iv=planted_iv)[0][0]
    solved = _candidates(client, strike_mult=0.70)[0][0]

    assert planted["stopCostPct"] is not None, "the gate must still answer, not go dark"
    assert planted["stopCostPct"] == pytest.approx(solved["stopCostPct"]), (
        f"contract['iv']={planted_iv} moved the gate -- it is being used instead of "
        "the contract's own mid, so a broadcast ATM vol can misprice this row"
    )
    assert planted["stopCostStatus"] == solved["stopCostStatus"]


def test_supplying_an_iv_would_have_changed_the_answer(client):
    """Proves the test above is not vacuous.

    If `compute_stop_cost` happened to ignore `iv_pct`, every assertion above
    would pass while the scan still shipped the bug. This pins that the
    argument IS load-bearing at the unit boundary -- so the scan's choice to
    pass None is a real decision, and a future caller reinstating it would be
    reintroducing a measurable error rather than a no-op.

    The figures are the reviewed scenario: 200/210C, 30 DTE, $4.41 mid, stop
    $192, Swing. The ATM's 25% reads 81% CAUTION; the contract's own mid reads
    50% PASS -- 31 points and an inverted verdict, on the sorted column.
    """
    common = dict(stop_price=192.00, stock_price=200.0, strike=210.0, dte=30,
                  premium=4.41, is_call=True, horizon_preset="Swing")
    with_atm_vol = compute_stop_cost(**common, iv_pct=25.0)
    from_own_mid = compute_stop_cost(**common, iv_pct=None)

    assert with_atm_vol is not None and from_own_mid is not None
    assert round(with_atm_vol.fraction * 100, 1) == pytest.approx(81.0, abs=0.5)
    assert round(from_own_mid.fraction * 100, 1) == pytest.approx(50.0, abs=0.5)
    assert with_atm_vol.status == "CAUTION" and from_own_mid.status == "PASS"
