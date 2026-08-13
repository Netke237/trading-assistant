import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from app.scoring.spread_builder import build_bear_put, build_bear_call

CHAIN_PUTS = [
    {"strike": 180, "bid": 4.0, "ask": 4.2, "delta": -0.45},
    {"strike": 175, "bid": 2.0, "ask": 2.2, "delta": -0.30},
]
CHAIN_CALLS = [
    {"strike": 175, "bid": 3.0, "ask": 3.2, "delta": 0.55},
    {"strike": 180, "bid": 1.4, "ask": 1.6, "delta": 0.35},
]

def test_bear_put_is_a_debit_with_capped_risk():
    sp = build_bear_put(CHAIN_PUTS, expiry="2026-07-17", width=5, short_delta=0.30)
    assert sp.spread_type == "bear_put"
    assert sp.net_debit_credit > 0                      # debit (you pay)
    assert sp.max_loss == round(sp.net_debit_credit, 2)
    assert sp.max_profit == round(5 - sp.net_debit_credit, 2)
    assert sp.legs[0].action == "BUY" and sp.legs[0].right == "P"   # higher strike
    assert sp.legs[1].action == "SELL" and sp.legs[1].right == "P"  # lower strike

def test_bear_put_raises_when_no_higher_strike_available():
    """No strike above the short leg exists in the chain — must raise, not
    silently build a zero-width spread with a negative 'max profit'."""
    chain = [
        {"strike": 90,  "bid": 0.5, "ask": 0.6, "delta": -0.10},
        {"strike": 95,  "bid": 1.0, "ask": 1.1, "delta": -0.20},
        {"strike": 100, "bid": 2.0, "ask": 2.2, "delta": -0.30},
    ]
    with pytest.raises(ValueError):
        build_bear_put(chain, expiry="2026-07-17", width=5, short_delta=0.30)


def test_bear_call_is_a_credit_with_capped_risk():
    sp = build_bear_call(CHAIN_CALLS, expiry="2026-07-17", width=5, short_delta=0.35)
    assert sp.spread_type == "bear_call"
    assert sp.net_debit_credit < 0                      # credit (you collect)
    credit = abs(sp.net_debit_credit)
    assert sp.max_profit == round(credit, 2)
    assert sp.max_loss == round(5 - credit, 2)
    assert sp.legs[0].action == "SELL" and sp.legs[0].right == "C"  # lower strike
    assert sp.legs[1].action == "BUY" and sp.legs[1].right == "C"   # higher strike


from app.scoring.spread_builder import choose_primary

def test_high_iv_prefers_credit_spread():
    assert choose_primary(iv_rank=70, threshold=50) == "bear_call"

def test_low_iv_prefers_debit_spread():
    assert choose_primary(iv_rank=30, threshold=50) == "bear_put"
