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


def test_a_premium_stop_that_rounds_to_zero_dollars_still_yields_the_true_ratio():
    """A 5c contract with a 5% premium stop puts the risk leg at $0.0025, which
    is $0.00 in cents. Dividing by it returned 0.00x — a plausible-looking ratio
    on a card that simultaneously said the value was the target % over the stop
    %, which is 4.00x. Contradicting itself in one sentence is worse than an em
    dash.

    The ratio comes from the DEFINITION, not the division, so the honest 4.00x
    survives a risk leg that quantizes away. (The test used to be named
    "...yields_no_ratio", which its own body contradicts.)"""
    race = _run(premium=0.05, premium_stop_pct=0.05).race
    assert race is not None
    o = race.outcomes[0]
    assert o.risk_premium_stop == 0.0
    # Constant by construction, so it is still the honest 4.00x, not 0.00x.
    assert o.rr_premium_stop == pytest.approx(0.20 / 0.05)


def test_rr_stock_stop_is_reward_over_risk_and_not_the_other_way_up():
    """THE headline number's orientation, pinned.

    This existed as a coverage hole first and a test second. Inverting line 599
    of first_passage.py to `risk_stock_stop / reward_dollar` — a fully upside
    down reward/risk ratio, the figure the card bolds as the measurement —
    passed the entire backend suite: 1845 passed, 1 skipped, identical to
    baseline. Every existing assertion about rr_stock_stop was satisfied by the
    inverted value too: it still varies across strikes, is still None when risk
    is non-positive, and is still not None when risk is positive. None of them
    ever divided the two legs and compared.

    So divide them and compare, on a fixture where the two orientations cannot
    be confused: reward and risk are deliberately far apart, so a ratio and its
    reciprocal differ by more than any rounding.
    """
    race = _run().race
    assert race is not None
    checked = 0
    for o in race.outcomes:
        if o.risk_stock_stop is None or o.risk_stock_stop <= 0:
            continue
        checked += 1
        assert o.rr_stock_stop == pytest.approx(o.reward_dollar / o.risk_stock_stop)
        # And not the reciprocal. Guarded so the assertion cannot pass vacuously
        # on a contract where reward happens to equal risk.
        reciprocal = o.risk_stock_stop / o.reward_dollar
        if abs(reciprocal - (o.reward_dollar / o.risk_stock_stop)) > 1e-9:
            assert o.rr_stock_stop != pytest.approx(reciprocal)
    assert checked >= 2, "fixture produced too few solvable legs to mean anything"


def test_rr_stock_stop_rises_when_reward_rises_and_falls_when_risk_rises():
    """The same orientation from the other side, in case a future refactor
    computes the ratio somewhere else entirely.

    Across the three targets of one race, reward_dollar increases (T1 -> T3)
    while risk_stock_stop is identical — it is a property of the STOP, which the
    three targets share. So rr_stock_stop must increase monotonically. An
    inverted ratio decreases, and a ratio computed off the wrong risk leg does
    neither reliably.
    """
    race = _run().race
    assert race is not None
    solvable = [o for o in race.outcomes
                if o.risk_stock_stop is not None and o.risk_stock_stop > 0
                and o.rr_stock_stop is not None]
    assert len(solvable) == 3, "all three targets should price on this fixture"

    risks = {round(o.risk_stock_stop, 10) for o in solvable}
    assert len(risks) == 1, f"the stop leg is shared across targets: {risks}"

    rewards = [o.reward_dollar for o in solvable]
    ratios = [o.rr_stock_stop for o in solvable]
    assert rewards == sorted(rewards) and rewards[0] < rewards[-1]
    assert ratios == sorted(ratios), f"rr_stock_stop fell as reward rose: {ratios}"
    assert ratios[0] < ratios[-1]


# -- 8. The degenerate risk leg -----------------------------------------------

def test_non_positive_stock_stop_risk_yields_no_ratio():
    """Render an em dash, never a negative or infinite ratio.

    WHERE THIS IS ACTUALLY REACHABLE, which is not where the spec says. The spec
    calls it "possible for a deep-ITM contract on a tight stop", and that was
    true only while the stop was being repriced at the WRONG time — the old code
    fed elapsed days into bs_price as remaining life, so a stop reached late
    was priced with MORE life than the contract was quoted with. With the
    repricing fixed, a call at its stop has both a lower spot AND less time
    remaining, so it can only be worth less than it cost: risk is positive for
    every quote the model can actually solve. Swept strikes 165-180 against
    premiums $10-$21 to confirm.

    What does reach it is a quote bs_iv cannot solve, where sigma falls back to
    a generic 0.25 that has nothing to do with the contract. So that is the
    fixture, and it is the same state test_a_quote_the_model_cannot_solve...
    below says the card must caveat rather than price confidently."""
    race = _run(strike=170.0, premium=15.60, invalidation_price=184.5).race
    assert race is not None
    assert race.iv_solved is False
    o = race.outcomes[0]
    assert o.risk_stock_stop is not None
    assert o.risk_stock_stop <= 0
    assert o.rr_stock_stop is None
    # The edge is still computable: a negative "risk" is a signed contribution,
    # not an error.
    assert o.edge_per_contract is not None


def test_a_solvable_quote_never_produces_a_non_positive_stock_stop_risk():
    """The other half of the above, asserted rather than left in prose: with a
    solvable IV and the repricing the right way round, the risk leg is positive
    across a real deep-ITM chain. If this ever starts failing, the reprice
    direction has been inverted again."""
    for strike, premium in ((180.0, 6.00), (177.5, 8.40), (175.0, 10.80), (172.5, 13.60)):
        race = _run(strike=strike, premium=premium, invalidation_price=184.0).race
        assert race is not None
        assert race.iv_solved, f"K={strike} must be solvable for this test to mean anything"
        for o in race.outcomes:
            assert o.risk_stock_stop is not None and o.risk_stock_stop > 0
            assert o.rr_stock_stop is not None


def test_a_quote_the_model_cannot_solve_is_flagged_rather_than_priced_confidently():
    """When bs_iv cannot back the contract's own IV out of its quote, sigma
    silently becomes the 0.25 default and the simulation is no longer about this
    contract at all. On a quote far below intrinsic it then prices day 1 above
    the target and reports 100% target-first with a confident dollar edge.

    Every other consumer of that fallback shows a probability; the race is the
    first to turn it into money, so the flag rides with it and the card
    caveats every number."""
    unsolvable = _run(strike=100.0, premium=5.20).race   # ~$85 of intrinsic, quoted at $5.20
    assert unsolvable is not None
    assert unsolvable.iv_solved is False
    assert unsolvable.outcomes[0].p_target_first == 1.0   # the fabricated certainty
    assert _run().race.iv_solved is True


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

    # The SAME seed: this is the evidence that the premium stop does not need to
    # be in the endpoint's seed key. It is a post-hoc barrier over paths that
    # were already simulated, so moving it moves every number that depends on
    # it without touching the draw.
    moved = _run(premium_stop_pct=0.30).race
    assert moved is not None
    assert [o.p_premium_stop_first for o in moved.outcomes] != [o.p_premium_stop_first for o in a.outcomes]
    assert moved.premium_stop_price != a.premium_stop_price
    # ...and the shared simulation is untouched, which is the whole point: the
    # Monte Carlo card's target probabilities do not depend on the premium stop,
    # so they must not move when it does.
    for o in moved.outcomes:
        total = (o.p_target_first + o.p_stock_stop_first
                 + o.p_premium_stop_first + o.p_neither)
        assert total == pytest.approx(1.0, abs=1e-12)
    assert ([t.probability for t in _run(premium_stop_pct=0.30).targets]
            == [t.probability for t in _run().targets])


# -- Printed-arithmetic consistency -------------------------------------------

def test_every_money_field_is_actually_quantized_to_cents():
    """The decision under test is that money is rounded IN THE SCORING LAYER
    rather than at the presentation boundary, so the printed chains add up.

    An earlier version of this test asserted relations that hold identically
    with and without the rounding (`reward_dollar ~= round(target,2) - 5.20`,
    and a `risk_premium_stop` tolerance of 5e-3, wider than a cent). Deleting
    every round() in the money block left it passing. This asserts the
    quantization itself, on a premium that does NOT survive it by accident."""
    # A premium with sub-cent precision, which a live quote genuinely can carry.
    # At 5.17 the assertion below is vacuous for premium_used: the input is
    # already exact, so removing round() changes nothing and the mutation
    # survives.
    race = _run(premium=5.174).race
    assert race is not None
    # The result-level money too: premium_used is what BOTH printed chains
    # subtract from, and premium_stop_price is the barrier the card renders.
    # Neither was covered, so removing their quantization was invisible.
    for name in ("premium_used", "premium_stop_price"):
        v = getattr(race, name)
        assert v == round(v, 2), f"{name} is not quantized to cents: {v!r}"
    for o in race.outcomes:
        for name in (
            "reward_dollar", "stop_repriced_value", "risk_stock_stop",
            "risk_premium_stop", "edge_per_contract",
        ):
            v = getattr(o, name)
            assert v is not None
            assert v == round(v, 2), f"{name} is not quantized to cents: {v!r}"


def test_the_printed_edge_chain_sums_to_the_printed_total():
    """The card prints "0.27 x $1.04 - 0.00 x $5.17 - 0.69 x $3.12 + 0.05 x
    -$1.56 = -$1.95". Those four multipliers are `weight_*`, shipped from here,
    so the terms the user can add up ARE the terms the edge was computed from.

    THE BUG THIS REPLACES. The weights used to be produced by a Python
    imitation of JavaScript's toFixed (`floor(p*100 + 0.5)/100`), which
    disagrees with the real thing on 44 of the 2001 shares reachable at
    n_paths=2000 — every k/2000 whose third decimal is a 5, because multiplying
    by 100 first perturbs the double that decides the tie. On THIS contract's
    T20% row the backend weighted the last term with 0.05 while the card
    printed 0.04, so the printed terms summed to -$1.93 under a printed total
    of -$1.95.

    And the test that was supposed to catch it could not: its oracle was
    `Decimal(repr(v))`, and the repr() round-trip discards exactly the
    information that decides the tie, so it reproduced the bug rather than
    detecting it. There is now one implementation and no oracle to get wrong."""
    for premium in (5.20, 6.63, 2.47, 0.37):
        race = _run(premium=premium).race
        assert race is not None
        for o in race.outcomes:
            assert o.edge_per_contract is not None
            assert o.risk_stock_stop is not None
            weights = (o.weight_target, o.weight_stock_stop,
                       o.weight_premium_stop, o.weight_neither)

            # Each is a whole number of hundredths, so JavaScript's toFixed(2)
            # renders it exactly and cannot disagree with what was used here.
            for w in weights:
                # `abs(... ) < 1e-9`, not `==`: 0.14 * 100 is 14.000000000000002
                # in binary floating point. The value IS a whole hundredth; the
                # multiplication is what has the tail.
                assert abs(w * 100 - round(w * 100)) < 1e-9, f"weight {w} is not a hundredth"
            # And they sum to exactly 1.00, so the labels derived from them sum
            # to exactly 100%.
            assert round(sum(weights), 10) == 1.0, f"weights sum to {sum(weights)}"

            prem_c = round(premium, 2)
            neither = (round(o.terminal_mean, 2) - prem_c) if o.terminal_mean is not None else 0.0
            printed_terms = (
                o.weight_target * o.reward_dollar
                - o.weight_stock_stop * o.risk_stock_stop
                - o.weight_premium_stop * o.risk_premium_stop
                + o.weight_neither * neither
            )
            printed_total = o.edge_per_contract / 100.0
            assert round(printed_terms, 2) == pytest.approx(round(printed_total, 2), abs=1e-9), (
                f"premium {premium}, T{o.target_pct}: printed terms sum to {printed_terms} "
                f"but the printed total is {printed_total}"
            )


def test_the_premium_barrier_and_its_risk_leg_come_off_the_same_premium():
    """The card shows the barrier in one block ("$0.06 option") and the risk leg
    in another, with the premium printed beside them, so
    `premium_used - premium_stop_price == risk_premium_stop` must hold exactly.

    ASSERTS THE DERIVATION, NOT THE IDENTITY. Checking
    `premium_used - premium_stop_price == risk_premium_stop` cannot fail:
    risk_premium_stop is DEFINED as that subtraction, so it is the same
    expression on both sides. Reverting the barrier to the buggy
    `round(premium * (1 - pct), 2)` — off the RAW premium — left that version
    green. What pins it is that the barrier itself comes off the cent-rounded
    premium, checked on premiums where the two genuinely differ."""
    # Live quotes carry sub-cent prices; these are premiums where rounding the
    # premium first and rounding the product first disagree by a cent.
    for premium, pct in ((0.051, 0.30), (0.063, 0.60), (0.064, 0.45), (0.054, 0.30)):
        race = _run(premium=premium, premium_stop_pct=pct).race
        assert race is not None
        expected = round(round(premium, 2) * (1.0 - pct), 2)
        assert race.premium_stop_price == expected, (
            f"premium {premium}: barrier {race.premium_stop_price} was not derived "
            f"from the cent-rounded premium ({expected}); "
            f"off the raw premium it would be {round(premium * (1.0 - pct), 2)}"
        )
        assert expected != round(premium * (1.0 - pct), 2), (
            "this premium no longer separates the two derivations — pick another"
        )
        # And the identity the card depends on still holds.
        assert round(race.premium_used - race.premium_stop_price, 2) == \
            race.outcomes[0].risk_premium_stop


def test_the_edge_uses_the_same_terminal_mean_the_wire_ships():
    """The fourth edge term is weighted with `round(terminal_mean, 2)`, and the
    wire ships that same rounded value — so the card's printed operand is the
    one the total was computed from. Weighting it with the raw value instead
    left every test green: the chain assertion rounds BOTH sides to 2dp, and
    the difference is under half a cent per share, so it cannot see it.

    Asserted on a contract where the two genuinely differ: at 60 DTE with a
    $9.83 premium the T50% edge is -$440 with the rounded value and -$439
    without, a whole dollar per contract."""
    o = _run(dte=60, premium=9.83).race.outcomes[2]
    assert o.terminal_mean is not None and o.risk_stock_stop is not None
    prem_c = round(9.83, 2)

    def edge_from(terminal: float) -> float:
        neither = terminal - prem_c
        return round(round(
            o.weight_target * o.reward_dollar
            - o.weight_stock_stop * o.risk_stock_stop
            - o.weight_premium_stop * o.risk_premium_stop
            + o.weight_neither * neither, 2) * 100, 2)

    assert o.edge_per_contract == edge_from(round(o.terminal_mean, 2))
    # And the fixture is genuinely capable of failing: the raw value differs.
    assert edge_from(o.terminal_mean) != o.edge_per_contract


def test_the_stock_stop_barrier_is_quantized_before_the_paths_are_tested_against_it():
    """The card echoes this level "for auditability", so the level echoed must
    be the level the 2000 paths were actually compared against. Every fixture
    used a whole-cent stop, so removing the quantization changed nothing and the
    guard was untested."""
    race = _run(invalidation_price=176.004).race
    assert race is not None
    assert race.stock_stop_price == 176.0
    deeper = _run(invalidation_price=176.006).race
    assert deeper is not None
    assert deeper.stock_stop_price == 176.01
    # And the echo is exactly what a path was tested against: a stop just under
    # half a cent below a level yields the identical attribution.
    assert [o.p_stock_stop_first for o in race.outcomes] == \
        [o.p_stock_stop_first for o in _run(invalidation_price=176.0).race.outcomes]


def test_the_allocation_gives_the_leftover_hundredths_to_the_biggest_remainders():
    """_allocated_weights' docstring names largest-remainder specifically.
    Flipping the sort to smallest-remainder-first still sums to 1.00 and is
    still deterministic, so every other assertion here survived it — the
    property that makes a label land within one point of its own bar did not."""
    from app.scoring.first_passage import _allocated_weights

    # 0.125 / 0.125 / 0.125 / 0.625: floors are 12/12/12/62 = 98, so two
    # hundredths are left over and the four remainders are equal at 0.5.
    # Largest-remainder with an index tie-break gives them to the first two.
    assert _allocated_weights([0.125, 0.125, 0.125, 0.625]) == [0.13, 0.13, 0.12, 0.62]

    # A clear ordering: remainders 0.9, 0.1, 0.0, 0.0 with one hundredth spare.
    got = _allocated_weights([0.109, 0.101, 0.39, 0.40])
    assert got == [0.11, 0.10, 0.39, 0.40], got

    # And no label is ever more than a point from its own share.
    for shares in ([0.2685, 0.0, 0.6865, 0.045], [0.138, 0.0, 0.785, 0.077],
                   [0.204, 0.0045, 0.4885, 0.303]):
        for w, raw in zip(_allocated_weights(shares), shares):
            assert abs(w - raw) < 0.01


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


def test_the_stop_leg_reprices_at_the_simulation_median_not_the_preset_table():
    """Decision Q2's entire point: "no fixed half-life, every reprice uses the
    simulation's own median days to that barrier, falling back to a per-preset
    YAML value". Nothing pinned the wiring — replacing the sim median with None
    (so the stop leg silently fell back to Swing's 7 days — on a 60-DTE
    reference contract a $0.49 -> $1.84 swing in the repriced value, and
    0.2208 -> 0.3095 in R:R) left every test passing.

    Both halves are asserted: that the horizon IS the simulation's observed
    median, and that it is not the table's."""
    res = _run(dte=60)
    race = res.race
    assert race is not None
    observed = res.invalidation.expected_days
    assert observed is not None
    o = race.outcomes[0]
    assert o.reprice_days_stock_stop == pytest.approx(observed)
    assert o.reprice_days_stock_stop != 7.0, "fell back to the Swing table row"

    # The field the CARD reads to decide which of three mutually exclusive
    # sentences to print. Swapping it for the conditional median (None on this
    # contract) left the whole backend suite green while the card would have
    # said "the preset default; no path reached the stop" beside a horizon that
    # was in fact the observed median of the paths that did.
    assert o.days_any_path_reached_stop == observed

    # And when the simulation reached no barrier at all, the table is what runs.
    no_stop = _run(dte=60, invalidation_price=1.0)   # unreachable stop
    assert no_stop.invalidation.expected_days is None
    assert no_stop.race is not None
    assert no_stop.race.outcomes[0].reprice_days_stock_stop == pytest.approx(7.0)
    assert no_stop.race.outcomes[0].days_any_path_reached_stop is None


def test_the_race_is_skipped_entirely_when_the_caller_does_not_want_it():
    """The exit-plan endpoint calls this once PER TARGET ROW with t1=t2=t3 and
    reads only .targets[0]. Leaving the race on ran three attributions, a
    Black-Scholes reprice and a median over a 2000-row array per row, and threw
    all of it away. Deleting the argument at the call site was invisible to CI."""
    res = _run(compute_race=False)
    assert res.race is None
    # Everything that path actually reads is still there.
    assert len(res.targets) == 3
    assert res.targets[0].probability >= 0.0
    assert res.invalidation.probability >= 0.0
    # ...and it is the same answer the race-computing call gives.
    full = _run()
    assert [t.probability for t in res.targets] == [t.probability for t in full.targets]
    assert res.invalidation.expected_days == full.invalidation.expected_days


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
        """Key presence AND value. The value half is what matters: every field
        the last two rounds made load-bearing was declared with a default on the
        wire model, so deleting its assignment in _race_out was invisible —
        Pydantic filled the default, TypeScript declares the field required so
        tsc saw nothing, and the whole backend suite passed while the card would
        have rendered four "0%" labels under the copy "every row sums to 100%",
        beside an edge chain whose four multipliers were all zero and whose
        printed total was not."""
        payload = self._post().json()
        o = payload["race"]["outcomes"][0]
        for key in (
            "targetPct", "targetOptionPrice", "rewardDollar", "repriceDaysStockStop",
            "stopRepricedValue", "riskStockStop", "riskPremiumStop",
            "rrStockStop", "rrPremiumStop", "edgePerContract",
            "daysTarget", "daysStockStop", "daysPremiumStop", "terminalMean",
            "daysAnyPathReachedStop", "weightTargetFirst", "weightStockStopFirst",
            "weightPremiumStopFirst", "weightNeither",
        ):
            assert key in o, f"{key} missing from the response"

        # The weights are both what the card prints and what the edge was
        # weighted with, so they must be real hundredths summing to 1.00.
        weights = [o["weightTargetFirst"], o["weightStockStopFirst"],
                   o["weightPremiumStopFirst"], o["weightNeither"]]
        assert round(sum(weights), 10) == 1.0, weights
        assert any(w > 0 for w in weights), "all four weights defaulted to zero"
        for w in weights:
            assert abs(w * 100 - round(w * 100)) < 1e-9, f"{w} is not a hundredth"

        # daysAnyPathReachedStop decides which of three mutually exclusive
        # sentences the risk chain prints, so defaulting it to None would make
        # the card say no path reached a stop that 2000 paths did reach.
        assert o["daysAnyPathReachedStop"] == payload["invalidation"]["expectedDays"]
        assert payload["race"]["ivSolved"] is True

    def test_a_moved_premium_stop_changes_the_answer_over_the_wire(self):
        """Moving the premium stop moves the answer over the wire.

        NOTE this does not pin the SEED KEY, despite what it used to claim:
        both assertions below hold whether or not premium_stop_pct is part of
        it, because the barrier itself moved. The seed key is genuinely pinned
        in test_first_passage.py."""
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
