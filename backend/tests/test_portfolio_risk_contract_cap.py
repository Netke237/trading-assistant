# backend/tests/test_portfolio_risk_contract_cap.py
"""P1a (Q18, P1-CLAMP-AT-SOURCE-2026-09-25): `check_position_risk` REFUSES an
option quantity above `sizing.max_contracts_per_trade` instead of clamping it
and judging the smaller number. Stocks are judged at their real share count by
their risk at the stop (STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES, decision
STOCK-RISK-AT-STOP-2026-09-26) -- tests T-A1..T-A6 and T-A9 below.

Plan: docs/superpowers/plans/2026-09-25-p1a-backend-contract-cap-plan.md s5 1-4.
"""
from __future__ import annotations

import pytest

import math
from types import SimpleNamespace

from app.services.portfolio_risk import (
    EXCEEDS_MAX_CONTRACTS, PortfolioPosition, _load_config, check_position_risk,
    orm_positions_to_risk, position_capital_at_risk,
)

OPTION = "AAPL|185|2026-12-18|C"
CAP = _load_config()["sizing"]["max_contracts_per_trade"]


def _check(qty, premium=1.0, contract=OPTION, value=100_000.0):
    return check_position_risk(
        symbol="AAPL", contract_id=contract, proposed_contracts=qty,
        entry_premium=premium, current_price=premium, portfolio=[],
        portfolio_value=value,
    )


def test_config_precondition():
    assert CAP == 5, "the numbers below assume the shipped cap of 5"


def test_1_an_option_qty_above_the_cap_is_refused_at_its_real_size():
    over = _check(CAP + 1)
    assert over.approved is False
    assert EXCEEDS_MAX_CONTRACTS in over.reasons
    assert over.judged_size == CAP + 1
    at = _check(CAP)
    assert (at.approved, at.reasons, at.judged_size) == (True, [], CAP)


def test_2_the_exposure_caps_are_judged_at_the_real_option_qty():
    """Premium 9.00 on 100k: a 5-lot is 4.5% (fits the 5% single cap), a 6-lot
    is 5.4% (breaches it). Clamped to 5, the 6-lot would never show the resize."""
    five = _check(5, premium=9.0)
    assert (five.approved, five.reasons, five.adjusted_size) == (True, [], None)
    six = _check(6, premium=9.0)
    assert six.approved is False
    assert "size_reduced_to_fit_exposure_limit" in six.reasons
    assert EXCEEDS_MAX_CONTRACTS in six.reasons
    assert six.adjusted_size == int(100_000 * 0.05 / (9.0 * 100))


def test_3_stock_shares_are_judged_at_the_real_count():
    """REWRITTEN on purpose by STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES (it pinned
    the deferred 5-share clamp). Do not restore the clamp to turn it green."""
    r = _check(100, premium=10.0, contract="AAPL|STOCK")
    assert EXCEEDS_MAX_CONTRACTS not in r.reasons
    assert r.approved is True
    assert r.judged_size == 100


@pytest.mark.parametrize("qty, value", [
    (CAP, 100_000.0),        # approved
    (CAP + 1, 100_000.0),    # the cap refusal
    (CAP + 1, 100.0),        # the portfolio_too_small early return
])
def test_4_the_result_carries_the_cap_it_read(qty, value):
    assert _check(qty, value=value).max_contracts == CAP


# ── STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES, Part A (plan s A6 / R6) ─────────

STOCK = "AAPL|STOCK"


def _stock(qty, entry=50.0, stop=None, direction="Bullish", value=100_000.0, portfolio=()):
    return check_position_risk(
        symbol="AAPL", contract_id=STOCK, proposed_contracts=qty,
        entry_premium=entry, current_price=entry, portfolio=list(portfolio),
        portfolio_value=value, stop=stop, direction=direction,
    )


def test_a1_position_capital_at_risk():
    assert position_capital_at_risk(OPTION, 2.0, 3) == 600
    assert position_capital_at_risk(STOCK, 50.0, 200, 45.0, "Bullish") == 1000
    assert position_capital_at_risk(STOCK, 50.0, 100, 55.0, "Bearish") == 500
    # No usable stop -> full notional.
    for stop, direction in [(None, "Bullish"), (50.0, "Bullish"), (55.0, "Bullish"),
                            (45.0, "Bearish"), (0.0, "Bullish"), (math.nan, "Bullish"),
                            (45.0, None), (45.0, "Neutral")]:
        assert position_capital_at_risk(STOCK, 50.0, 100, stop, direction) == 5000, (stop, direction)


def test_a2_a_stock_is_not_clamped_to_the_contract_cap():
    r = _stock(10, stop=49.0)
    assert r.judged_size == 10
    assert EXCEEDS_MAX_CONTRACTS not in r.reasons
    assert r.approved is True


def test_a3_resize_by_risk_at_the_stop():
    # 6000 x $1 = $6,000 at risk = 6% > 5% -> 5000 shares.
    r = _stock(6000, entry=50.0, stop=49.0)
    assert r.approved is True
    assert r.reasons == ["size_reduced_to_fit_exposure_limit"]
    assert r.adjusted_size == 5000


def test_a4_no_stop_falls_back_to_notional():
    r = _stock(6000, entry=50.0, stop=None)
    assert r.adjusted_size == 100  # 5% of 100k / $50


def test_a5_total_exposure_counts_rows_at_risk():
    rows = [
        PortfolioPosition(symbol="MSFT", contract_id="MSFT|STOCK", contracts=1000,
                          entry_premium=50.0, current_price=50.0, capital_at_risk=20_000.0),
        PortfolioPosition(symbol="SPY", contract_id="SPY|500|2026-12-18|C", contracts=1,
                          entry_premium=30.0, current_price=30.0, capital_at_risk=3_000.0),
    ]
    # New stock: 1000 x (50 - 47) = 3,000 -> total 26,000 = 26% > 25%.
    r = _stock(1000, entry=50.0, stop=47.0, portfolio=rows)
    assert r.approved is False
    assert r.reasons == ["total_exposure_limit_reached"]
    assert r.portfolio_exposure_pct == 23.0


def test_a6_options_are_unchanged():
    six = _check(CAP + 1)
    assert EXCEEDS_MAX_CONTRACTS in six.reasons
    with_stop = check_position_risk(
        symbol="AAPL", contract_id=OPTION, proposed_contracts=2, entry_premium=9.0,
        current_price=9.0, portfolio=[], portfolio_value=100_000.0,
        stop=1.0, direction="Bullish")
    without = _check(2, premium=9.0)
    assert (with_stop.approved, with_stop.reasons, with_stop.adjusted_size) == \
        (without.approved, without.reasons, without.adjusted_size)


def test_a9_orm_rows_count_stocks_at_risk():
    def row(stop, direction="Bullish"):
        return SimpleNamespace(symbol="AAPL", contract="AAPL|STOCK", qty=100,
                               entry_price=50.0, stop=stop, direction=direction)
    assert orm_positions_to_risk([row(45.0)])[0].capital_at_risk == 500
    assert orm_positions_to_risk([row(None)])[0].capital_at_risk == 5000
    assert orm_positions_to_risk([row(55.0)])[0].capital_at_risk == 5000
    opt = SimpleNamespace(symbol="AAPL", contract=OPTION, qty=2, entry_price=3.0,
                          stop=150.0, direction="Bullish")
    assert orm_positions_to_risk([opt])[0].capital_at_risk == 600
