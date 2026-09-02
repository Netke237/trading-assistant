"""Barrier race — the attribution, the tie rule, and the printed arithmetic.

Spec: docs/superpowers/plans/2026-09-02-barrier-race-spec.md section 4 (tests 1-9).

The race is a REFEREE, not a fourth profit-target method: it proposes no level
of its own, it only decides which of three already-existing levels a simulated
path reaches FIRST. The property that makes it worth having — and the one every
test below is ultimately protecting — is that every path is counted exactly
once, so the four shares sum to 1.0. The pre-existing TargetEstimate.probability
and InvalidationEstimate.probability are each measured on their own and can, and
do, sum past 100%.
"""
import numpy as np
import pytest

from app.scoring.first_passage import (
    _attribute,
    _first_day,
    estimate_first_passage,
)

# A deliberately ordinary long call: slightly OTM, a month out, a stop ~5% below.
_BASE = dict(
    stock_price=185.0,
    strike=190.0,
    dte=30,
    premium=5.20,
    delta=0.40,
    is_call=True,
    trend_score=70.0,
    invalidation_price=176.0,
    candles=[],
    t1_pct=0.20,
    t2_pct=0.35,
    t3_pct=0.50,
    horizon_preset="Swing",
    seed=42,
)


def _run(**overrides):
    return estimate_first_passage(**{**_BASE, **overrides})


# -- 1. The headline invariant ------------------------------------------------

def test_four_shares_sum_to_one_for_every_target():
    """Asserted, not merely commented. This is the whole reason the race exists:
    the four outcomes are an attribution of one population, not four independent
    probabilities that happen to be shown together."""
    race = _run().race
    assert race is not None
    assert len(race.outcomes) == 3
    for o in race.outcomes:
        total = (
            o.p_target_first
            + o.p_stock_stop_first
            + o.p_premium_stop_first
            + o.p_neither
        )
        assert total == pytest.approx(1.0, abs=1e-12), f"target {o.target_pct} summed to {total}"


# -- 2. Ordering, not membership ----------------------------------------------

def test_path_hitting_target_then_stop_is_attributed_to_the_target_only():
    """The old two-mask design counted this path in BOTH probabilities. The race
    counts it once, for whichever came first."""
    n_days = 30
    d_tgt = np.array([5])     # target on day 6
    d_stop = np.array([12])   # stop later
    d_prem = np.array([20])   # premium stop later still
    tgt, stop, prem, neither, _ = _attribute(d_tgt, d_stop, d_prem, n_days)
    assert tgt.tolist() == [True]
    assert stop.tolist() == [False]
    assert prem.tolist() == [False]
    assert neither.tolist() == [False]


# -- 3. The tie rule ----------------------------------------------------------

def test_same_day_ties_resolve_pessimistically():
    """Daily closes mean two barriers can be crossed on the same simulated day.
    Ties go to the stop over the target, and to the premium stop over the stock
    stop. Never flatters the trade."""
    n_days = 30
    # target and stock stop on the same day -> the stop wins
    tgt, stop, prem, _, _ = _attribute(np.array([7]), np.array([7]), np.array([25]), n_days)
    assert (tgt.tolist(), stop.tolist(), prem.tolist()) == ([False], [True], [False])

    # all three on the same day -> the premium stop wins
    tgt, stop, prem, _, _ = _attribute(np.array([7]), np.array([7]), np.array([7]), n_days)
    assert (tgt.tolist(), stop.tolist(), prem.tolist()) == ([False], [False], [True])

    # stock stop and premium stop on the same day -> the premium stop wins
    tgt, stop, prem, _, _ = _attribute(np.array([9]), np.array([4]), np.array([4]), n_days)
    assert (tgt.tolist(), stop.tolist(), prem.tolist()) == ([False], [False], [True])


# -- 4. The argmax trap -------------------------------------------------------

def test_first_day_returns_n_days_for_a_never_hitting_row():
    """np.argmax on a boolean row returns 0 for BOTH "hit on day 1" and "never
    hit". Used bare, every never-hitting path would masquerade as the fastest
    possible hit and win the race outright. This is the guard against that."""
    n_days = 4
    mask = np.array([
        [True,  False, False, False],   # hits on day 1 -> index 0
        [False, False, False, False],   # never hits    -> must be n_days, not 0
        [False, False, True,  False],   # hits on day 3 -> index 2
    ])
    assert _first_day(mask, n_days).tolist() == [0, n_days, 2]


def test_a_never_hitting_path_loses_the_race_to_a_day_one_hit():
    """The consequence of the trap, stated as behaviour rather than as an index."""
    n_days = 4
    never = _first_day(np.zeros((1, n_days), dtype=bool), n_days)
    day_one = _first_day(np.array([[True, False, False, False]]), n_days)
    tgt, stop, prem, neither, _ = _attribute(day_one, never, never, n_days)
    assert tgt.tolist() == [True]
    assert neither.tolist() == [False]


# -- 5. The refusal branch ----------------------------------------------------

def test_dte_below_one_returns_no_race_rather_than_four_zeroes():
    """dte < 1 is a refusal to simulate, not a real result. Four zeroes would be
    a 0%-summing 'attribution' the card would render as fact."""
    result = _run(dte=0)
    assert result.race is None
    assert all(t.probability == 0.0 for t in result.targets)


# -- 6. The insight the card exists to show -----------------------------------

def test_a_tighter_premium_stop_starves_the_stock_stop():
    """On this reference contract the premium stop is far tighter than the
    structural stock stop in option-value terms, so it fires first on nearly
    every losing path. The old card reported a standalone chance of hitting the
    invalidation price; the race shows that in practice you are stopped out on
    premium long before the stock ever gets there."""
    tight = _run(premium_stop_pct=0.40).race
    loose = _run(premium_stop_pct=0.95).race
    assert tight is not None
    assert loose is not None

    t0, l0 = tight.outcomes[0], loose.outcomes[0]
    assert t0.p_stock_stop_first < 0.01
    assert t0.p_premium_stop_first > l0.p_premium_stop_first
    assert l0.p_stock_stop_first > t0.p_stock_stop_first


# -- 7. The anti-cancellation guarantee ---------------------------------------

def test_stock_stop_rr_discriminates_between_strikes_but_premium_stop_rr_cannot():
    """The trap that killed two earlier designs. reward_dollar is
    premium * pct by construction, so any risk leg proportional to premium
    cancels it and the ratio degenerates to the typed percentages.

    risk_premium_stop IS proportional to premium, so rr_premium_stop is exactly
    pct / premium_stop_pct on every contract — a constant, shown for completeness
    only. risk_stock_stop is premium - BS(stop, ...), and BS(stop, ...) depends
    on strike, spot at the stop, time and IV independently, so rr_stock_stop
    genuinely varies. Asserted here rather than asserted in prose."""
    strikes = [180.0, 190.0, 200.0, 205.0, 210.0]
    # Deliberately NOT round premiums. An earlier version of this test used
    # [9.80, 5.20, 2.40], every one of which survives cent quantization exactly,
    # so it passed while rr_premium_stop was in fact computed by dividing two
    # rounded dollar legs and varied by up to 14% on sub-$1 premiums. A real
    # option chain is full of prices like these.
    premiums = [9.83, 5.17, 2.43, 1.03, 0.37]

    rr_stock, rr_prem = [], []
    for k, prem in zip(strikes, premiums):
        race = _run(strike=k, premium=prem).race
        assert race is not None
        rr_stock.append(race.outcomes[0].rr_stock_stop)
        rr_prem.append(race.outcomes[0].rr_premium_stop)

    assert all(v is not None for v in rr_stock)
    assert len({round(v, 6) for v in rr_stock}) == len(strikes), (
        f"rr_stock_stop did not discriminate across strikes: {rr_stock}"
    )
    assert len({round(v, 6) for v in rr_prem}) == 1, (
        f"rr_premium_stop should be constant by construction: {rr_prem}"
    )
    # And it is EXACTLY the typed ratio — not approximately. That is the whole
    # claim the card prints beside it ("equals your 20% target / 60% stop, on
    # every contract you could pick"), so it is asserted exactly.
    for v in rr_prem:
        assert v == pytest.approx(_BASE["t1_pct"] / 0.60, rel=1e-12)


def test_a_premium_stop_that_rounds_to_zero_dollars_yields_no_ratio():
    """A 5c contract with a 5% premium stop puts the risk leg at $0.0025, which
    is $0.00 in cents. Dividing by it returned 0.00x — a plausible-looking ratio
    on a card that simultaneously printed "equals your 20% target / 5% stop",
    which is 4.00x. Contradicting itself in one sentence is worse than an em
    dash, and it silently deleted the third term from the edge."""
    race = _run(premium=0.05, premium_stop_pct=0.05).race
    assert race is not None
    o = race.outcomes[0]
    assert o.risk_premium_stop == 0.0
    # Constant by construction, so it is still the honest 4.00x, not 0.00x.
    assert o.rr_premium_stop == pytest.approx(0.20 / 0.05)


# -- 8. The degenerate risk leg -----------------------------------------------

def test_non_positive_stock_stop_risk_yields_no_ratio():
    """A deep-ITM contract on a tight stop can still be worth more at the stop
    than it cost, making risk_stock_stop <= 0. Render an em dash, never a
    negative or infinite ratio."""
    race = _run(strike=100.0, premium=5.20).race
    assert race is not None
    o = race.outcomes[0]
    assert o.risk_stock_stop is not None
    assert o.risk_stock_stop <= 0
    assert o.rr_stock_stop is None
    # The edge is still computable: a negative "risk" is a signed contribution,
    # not an error.
    assert o.edge_per_contract is not None


def test_an_absent_stock_stop_reprices_to_nothing_rather_than_to_zero_dollars():
    """bs_price returns 0.0 for every degenerate input, S <= 0 included, so a
    non-positive stop price used to produce stop_repriced_value == $0.00 — "the
    contract is worth nothing at the stop", which silently makes the risk leg
    the whole premium. It is not a $0.00 contract, it is an absent barrier.

    This also makes the Optional on the wire honest: before it, no input could
    ever produce None there, so formatRaceRisk's "could not reprice at the stop"
    branch was unreachable and its unit test constructed the state by hand."""
    race = _run(invalidation_price=0.0).race
    assert race is not None
    o = race.outcomes[0]
    assert o.stop_repriced_value is None
    assert o.risk_stock_stop is None
    assert o.rr_stock_stop is None
    assert o.edge_per_contract is None


# -- 9. Determinism -----------------------------------------------------------

def test_same_seed_reproduces_and_a_moved_premium_stop_changes_the_answer():
    a = _run().race
    b = _run().race
    assert a is not None
    assert b is not None
    assert [o.p_target_first for o in a.outcomes] == [o.p_target_first for o in b.outcomes]
    assert [o.p_premium_stop_first for o in a.outcomes] == [o.p_premium_stop_first for o in b.outcomes]

    moved = _run(premium_stop_pct=0.30).race
    assert moved is not None
    assert [o.p_premium_stop_first for o in moved.outcomes] != [o.p_premium_stop_first for o in a.outcomes]
    assert moved.premium_stop_price != a.premium_stop_price


# -- Printed-arithmetic consistency -------------------------------------------

def test_every_money_field_is_actually_quantized_to_cents():
    """The decision under test is that money is rounded IN THE SCORING LAYER
    rather than at the presentation boundary, so the printed chains add up.

    An earlier version of this test asserted relations that hold identically
    with and without the rounding (`reward_dollar ~= round(target,2) - 5.20`,
    and a `risk_premium_stop` tolerance of 5e-3, wider than a cent). Deleting
    every round() in the money block left it passing. This asserts the
    quantization itself, on a premium that does NOT survive it by accident."""
    race = _run(premium=5.17).race
    assert race is not None
    for o in race.outcomes:
        for name in (
            "reward_dollar", "stop_repriced_value", "risk_stock_stop",
            "risk_premium_stop", "edge_per_contract",
        ):
            v = getattr(o, name)
            assert v is not None
            assert v == round(v, 2), f"{name} is not quantized to cents: {v!r}"


def test_the_printed_edge_chain_sums_to_the_printed_total():
    """The card prints "0.27 x $1.04 - 0.00 x $5.02 - 0.68 x $3.12 + 0.05 x
    -$1.56 = -$1.93". Before the probabilities were quantized to the 2dp they
    are PRINTED at, the four printed terms summed to a different number than the
    printed total — out by 1.6c per share, which at 100 shares is $1.56 a
    contract, on a card whose entire premise is that you can check its
    arithmetic."""
    race = _run().race
    assert race is not None
    for o in race.outcomes:
        assert o.edge_per_contract is not None
        assert o.risk_stock_stop is not None
        neither = (round(o.terminal_mean, 2) - 5.20) if o.terminal_mean is not None else 0.0
        printed_terms = (
            round(o.p_target_first, 2) * o.reward_dollar
            - round(o.p_stock_stop_first, 2) * o.risk_stock_stop
            - round(o.p_premium_stop_first, 2) * o.risk_premium_stop
            + round(o.p_neither, 2) * neither
        )
        printed_total = o.edge_per_contract / 100.0
        # Both are rendered at 2dp; they must agree once rendered.
        assert round(printed_terms, 2) == pytest.approx(round(printed_total, 2), abs=1e-9), (
            f"printed terms sum to {printed_terms} but the printed total is {printed_total}"
        )


def test_the_stop_leg_is_repriced_at_the_life_REMAINING_not_the_days_elapsed():
    """THE BUG THIS PINS. resolve_reprice_days returns days ELAPSED until the
    stop is reached; bs_price's third argument is the life REMAINING at that
    moment. Passing the former as the latter inverts theta: a stop reached on
    day 2 of a 30-day contract was priced as if two days of life were left
    (worth ~nothing, so the risk leg swallowed the whole premium), while a stop
    reached on day 25 was priced as if 25 days were left — worth MORE. Risk was
    overstated by ~39% and R:R understated by ~28% on the reference contract.

    Asserted two independent ways: against bs_price at the remaining life, and
    directionally, which holds whatever the pricing formula is."""
    from app.models.black_scholes import bs_price
    from app.scoring.reward_risk import _derive_fallback_sigma

    race = _run().race
    assert race is not None
    o = race.outcomes[0]
    dte, premium = float(_BASE["dte"]), _BASE["premium"]
    sigma_iv = _derive_fallback_sigma(premium, 185.0, 190.0, dte / 365.0, 0.05, True, 0.25)
    expected = bs_price(
        176.0, 190.0, (dte - o.reprice_days_stock_stop) / 365.0, 0.05, sigma_iv, True,
    )
    assert o.stop_repriced_value == pytest.approx(round(expected, 2), abs=1e-9)

    # Directional, formula-independent: a stop the simulation says is reached
    # LATER leaves LESS life, so the contract is worth LESS at it and the risk
    # leg is BIGGER. Under the bug this relation ran backwards.
    cfg_early = {"source": "table", "fallback_days": {"Swing": 3},
                 "clamp": {"min_days": 1, "max_fraction_of_dte": 0.75}}
    cfg_late = {"source": "table", "fallback_days": {"Swing": 20},
                "clamp": {"min_days": 1, "max_fraction_of_dte": 0.75}}
    early = _run(reprice_cfg=cfg_early).race.outcomes[0]
    late = _run(reprice_cfg=cfg_late).race.outcomes[0]
    assert early.stop_repriced_value > late.stop_repriced_value
    assert early.risk_stock_stop < late.risk_stock_stop


def test_the_stop_leg_is_identical_on_all_three_rows():
    """The stop leg is a property of the STOP, not of which target is being
    raced against it. Deriving its reprice horizon from a per-target conditional
    median made one stop, at one level, carry three different dollar risks — the
    card printed "$6.00 premium - $1.27 / $1.64 / $1.64 at the stop" with
    nothing explaining why."""
    race = _run(dte=45, strike=185.0, invalidation_price=182.0, premium_stop_pct=0.95).race
    assert race is not None
    assert len({o.stop_repriced_value for o in race.outcomes}) == 1
    assert len({o.risk_stock_stop for o in race.outcomes}) == 1
    assert len({o.reprice_days_stock_stop for o in race.outcomes}) == 1


def test_stage_one_target_stock_price_is_pinned():
    """Stage 1's displayed "roughly what stock price gets you there" moved by
    $2.64-$4.71 when the reprice rule changed, unpinned and unremarked. A LEAP
    was the tell: its target price was solved as though 7 days of life remained,
    because "Swing: 7" is a table about how long you HOLD, not what is left."""
    thirty = _run(dte=30).targets[0].stock_price
    leap = _run(dte=365).targets[0].stock_price
    # Repriced with 23 of its 30 days left, not with 7 days left ($194.34 under
    # the bug, +$5.06).
    assert thirty == pytest.approx(189.28, abs=0.05)
    # The LEAP is the tell: 358 days of life left needs a far smaller move than
    # the 7 days the bug assumed ($196.06, +$9.55).
    assert leap == pytest.approx(186.51, abs=0.05)
    assert leap < thirty


def test_echoed_barriers_match_the_inputs():
    race = _run(premium_stop_pct=0.60).race
    assert race is not None
    assert race.stock_stop_price == pytest.approx(176.0)
    assert race.premium_stop_price == pytest.approx(5.20 * 0.40)
    assert race.n_paths == 2000


# -- Over the wire ------------------------------------------------------------
#
# The dataclass tests above say nothing about the router's mapping onto the
# response model. A field dropped or mis-cased there is invisible to every test
# in this file until it reaches the card as `undefined`.

class TestEndpoint:
    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.contracts import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    _PAYLOAD = {
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 185.0,
        "strike": 190.0, "dte": 30, "premium": 5.20, "delta": 0.40,
        "trend_score": 70, "invalidation_price": 176.0,
    }

    def _post(self, **extra):
        from unittest.mock import AsyncMock, patch
        from tests.test_first_passage import _FLAT_CANDLES
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=_FLAT_CANDLES)):
            return self._client().post(
                "/api/contracts/first-passage", json={**self._PAYLOAD, **extra},
            )

    def test_the_race_reaches_the_client_with_its_shares_still_summing_to_one(self):
        r = self._post()
        assert r.status_code == 200, r.text
        race = r.json()["race"]
        assert race is not None
        assert len(race["outcomes"]) == 3
        for o in race["outcomes"]:
            total = (
                o["pTargetFirst"] + o["pStockStopFirst"]
                + o["pPremiumStopFirst"] + o["pNeither"]
            )
            # Rounded to 4 places on the wire, so this is not the exact-1.0
            # assertion the dataclass test makes — but a dropped or mis-mapped
            # share still fails here.
            assert total == pytest.approx(1.0, abs=2e-4), o

    def test_every_field_the_card_prints_survives_the_mapping(self):
        o = self._post().json()["race"]["outcomes"][0]
        for key in (
            "targetPct", "targetOptionPrice", "rewardDollar", "repriceDaysStockStop",
            "stopRepricedValue", "riskStockStop", "riskPremiumStop",
            "rrStockStop", "rrPremiumStop", "edgePerContract",
            "daysTarget", "daysStockStop", "daysPremiumStop", "terminalMean",
        ):
            assert key in o, f"{key} missing from the response"

    def test_a_moved_premium_stop_changes_the_answer_over_the_wire(self):
        """The seed key includes premium_stop_pct. Without that, moving the
        stop would return a bit-identical answer and the card would look
        frozen."""
        tight = self._post(premium_stop_pct=0.30).json()["race"]
        loose = self._post(premium_stop_pct=0.80).json()["race"]
        assert tight["premiumStopPrice"] != loose["premiumStopPrice"]
        assert (
            [o["pPremiumStopFirst"] for o in tight["outcomes"]]
            != [o["pPremiumStopFirst"] for o in loose["outcomes"]]
        )

    def test_a_premium_stop_of_one_is_rejected_rather_than_silently_accepted(self):
        """pct >= 1 is a total loss, which makes the barrier unreachable by
        definition rather than a stop."""
        assert self._post(premium_stop_pct=1.0).status_code == 422
        assert self._post(premium_stop_pct=0.0).status_code == 422

    def test_an_expiring_contract_returns_no_race_over_the_wire(self):
        assert self._post(dte=0).json()["race"] is None
