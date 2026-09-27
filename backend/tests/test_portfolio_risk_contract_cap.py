# backend/tests/test_portfolio_risk_contract_cap.py
"""P1a (Q18, P1-CLAMP-AT-SOURCE-2026-09-25): `check_position_risk` REFUSES an
option quantity above `sizing.max_contracts_per_trade` instead of clamping it
and judging the smaller number. Stocks are judged at their real share count
(STOCK-SENDS flipped test 3; the stock caps are pinned in
tests/test_stock_sends_real_shares.py).

Plan: docs/superpowers/plans/2026-09-25-p1a-backend-contract-cap-plan.md s5 1-4.
"""
from __future__ import annotations

import pytest

from app.services.portfolio_risk import (
    EXCEEDS_MAX_CONTRACTS, _load_config, check_position_risk,
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
    """STOCK-SENDS flipped this test: the |STOCK clamp is gone. 100 sh x $10 on
    $100k is $1,000 (1%), well inside the stock caps, and never refused for
    max_contracts_per_trade."""
    r = _check(100, premium=10.0, contract="AAPL|STOCK")
    assert EXCEEDS_MAX_CONTRACTS not in r.reasons
    assert r.approved is True
    assert r.judged_size == 100
    assert r.adjusted_size is None


@pytest.mark.parametrize("qty, value", [
    (CAP, 100_000.0),        # approved
    (CAP + 1, 100_000.0),    # the cap refusal
    (CAP + 1, 100.0),        # the portfolio_too_small early return
])
def test_4_the_result_carries_the_cap_it_read(qty, value):
    assert _check(qty, value=value).max_contracts == CAP
