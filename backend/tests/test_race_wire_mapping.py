"""Field-by-field pin of the barrier race's wire mapping.

``_race_out`` maps ``BarrierRaceResult`` onto the JSON the Barrier Race card
renders — about twenty fields, every one of them snake_case on one side and
camelCase on the other. Nothing else in the suite reads ``body["race"]``:
``test_barrier_race.py`` calls ``estimate_first_passage`` directly and stops at
the dataclass, and ``test_first_passage.py``'s endpoint tests never touch the
race key. So a transposition here — ``daysStockStop`` fed from
``days_premium_stop``, ``pTargetFirst`` fed from ``p_stock_stop_first`` — used to
survive the entire backend suite untouched and ship a mislabelled number onto a
trader's screen.

The technique is deliberate: every source field gets a DISTINCT sentinel value,
so a mapping that reads the wrong attribute cannot coincidentally produce the
right answer. A shared value (0.0, 1.0, None) in two fields is exactly what lets
a swap hide, which is why none is used twice.
"""
import pytest

from app.routers.contracts import _race_out
from app.scoring.first_passage import BarrierRaceResult, RaceOutcome


# Distinct on purpose — see the module docstring. Chosen to survive the rounding
# _race_out applies (2dp on money, 4dp on probabilities) unchanged, so a failure
# means a wiring error and never a rounding artifact.
OUTCOME_FIELDS = dict(
    target_pct=0.31,
    target_option_price=11.11,
    p_target_first=0.2101,
    p_stock_stop_first=0.2202,
    p_premium_stop_first=0.2303,
    p_neither=0.3394,
    days_target=4.1,
    days_stock_stop=5.2,
    days_premium_stop=6.3,
    days_any_path_reached_stop=7.4,
    weight_target=0.21,
    weight_stock_stop=0.22,
    weight_premium_stop=0.23,
    weight_neither=0.34,
    terminal_mean=22.22,
    reward_dollar=33.33,
    reprice_days_stock_stop=8.55,
    stop_repriced_value=44.44,
    risk_stock_stop=55.55,
    risk_premium_stop=66.66,
    rr_stock_stop=0.6006,
    rr_premium_stop=0.7007,
    edge_per_contract=77.77,
)

RACE_FIELDS = dict(
    premium_stop_price=88.88,
    premium_stop_pct=0.62,
    stock_stop_price=99.99,
    premium_used=12.34,
    iv_solved=True,
    n_paths=1234,
)

# wire field -> source field. Written out longhand rather than derived from a
# camelCase transform: a derivation would reproduce whatever mistake the mapping
# makes, and the pairs that actually matter here (daysStockStop vs
# daysPremiumStop, riskStockStop vs riskPremiumStop, the four p*/weight*) are
# precisely the ones a transform would treat as interchangeable.
OUTCOME_WIRE_TO_SOURCE = {
    "targetPct": "target_pct",
    "targetOptionPrice": "target_option_price",
    "pTargetFirst": "p_target_first",
    "pStockStopFirst": "p_stock_stop_first",
    "pPremiumStopFirst": "p_premium_stop_first",
    "pNeither": "p_neither",
    "daysTarget": "days_target",
    "daysStockStop": "days_stock_stop",
    "daysPremiumStop": "days_premium_stop",
    "daysAnyPathReachedStop": "days_any_path_reached_stop",
    "weightTargetFirst": "weight_target",
    "weightStockStopFirst": "weight_stock_stop",
    "weightPremiumStopFirst": "weight_premium_stop",
    "weightNeither": "weight_neither",
    "terminalMean": "terminal_mean",
    "rewardDollar": "reward_dollar",
    "repriceDaysStockStop": "reprice_days_stock_stop",
    "stopRepricedValue": "stop_repriced_value",
    "riskStockStop": "risk_stock_stop",
    "riskPremiumStop": "risk_premium_stop",
    "rrStockStop": "rr_stock_stop",
    "rrPremiumStop": "rr_premium_stop",
    "edgePerContract": "edge_per_contract",
}

RACE_WIRE_TO_SOURCE = {
    "premiumStopPrice": "premium_stop_price",
    "premiumStopPct": "premium_stop_pct",
    "stockStopPrice": "stock_stop_price",
    "premiumUsed": "premium_used",
    "ivSolved": "iv_solved",
    "nPaths": "n_paths",
}


def _race():
    return BarrierRaceResult(outcomes=[RaceOutcome(**OUTCOME_FIELDS)], **RACE_FIELDS)


@pytest.mark.parametrize("wire,source", sorted(OUTCOME_WIRE_TO_SOURCE.items()))
def test_outcome_field_comes_from_its_own_source(wire, source):
    out = _race_out(_race()).outcomes[0]
    assert getattr(out, wire) == pytest.approx(OUTCOME_FIELDS[source]), (
        f"{wire} is not fed from {source}"
    )


@pytest.mark.parametrize("wire,source", sorted(RACE_WIRE_TO_SOURCE.items()))
def test_race_level_field_comes_from_its_own_source(wire, source):
    out = _race_out(_race())
    assert getattr(out, wire) == RACE_FIELDS[source], f"{wire} is not fed from {source}"


def test_every_source_field_is_covered():
    """The map above must not silently fall behind the dataclass.

    A field added to RaceOutcome and wired into BarrierRaceOutcomeOut without a
    row here would be untested — which is the state this whole file exists to
    end. Fail loudly instead of quietly covering less.
    """
    assert set(OUTCOME_FIELDS) == set(OUTCOME_WIRE_TO_SOURCE.values())
    assert set(RACE_FIELDS) == set(RACE_WIRE_TO_SOURCE.values())
    assert set(OUTCOME_FIELDS) == {f.name for f in RaceOutcome.__dataclass_fields__.values()}
    assert set(RACE_FIELDS) | {"outcomes"} == {
        f.name for f in BarrierRaceResult.__dataclass_fields__.values()
    }


def test_none_race_maps_to_none():
    """"No race" must stay absent, not become a row of zeroes — a refusal is not
    a 100%-summing result (spec 2.1.1)."""
    assert _race_out(None) is None


def test_optional_fields_survive_as_none():
    """The four Optionals must not be coerced. `None` days means "no path got
    there", which the card renders as a dash; 0.0 would read as "immediately"."""
    fields = dict(OUTCOME_FIELDS)
    fields.update(
        days_target=None, days_stock_stop=None, days_premium_stop=None,
        days_any_path_reached_stop=None, terminal_mean=None,
        stop_repriced_value=None, risk_stock_stop=None,
        rr_stock_stop=None, rr_premium_stop=None, edge_per_contract=None,
    )
    out = _race_out(
        BarrierRaceResult(outcomes=[RaceOutcome(**fields)], **RACE_FIELDS)
    ).outcomes[0]
    for wire in ("daysTarget", "daysStockStop", "daysPremiumStop",
                 "daysAnyPathReachedStop", "terminalMean", "stopRepricedValue",
                 "riskStockStop", "rrStockStop", "rrPremiumStop", "edgePerContract"):
        assert getattr(out, wire) is None, wire


def test_rr_stock_stop_is_not_rounded_on_the_wire():
    """Documented at the mapping itself: 4dp rounding turns 0.504950 into 0.505,
    which toFixed(2) then renders as "0.51" beside the division that makes 0.50.
    A rounding added here would be invisible in every other test."""
    fields = dict(OUTCOME_FIELDS, rr_stock_stop=0.5049501234)
    out = _race_out(
        BarrierRaceResult(outcomes=[RaceOutcome(**fields)], **RACE_FIELDS)
    ).outcomes[0]
    assert out.rrStockStop == 0.5049501234
