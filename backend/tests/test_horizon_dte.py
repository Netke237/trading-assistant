from app.scoring.contract_validator import dte_holding_multiplier


def test_multiplier_loads_from_config():
    assert dte_holding_multiplier() == 2.0


from datetime import date, timedelta

from app.scoring.contract_validator import validate_contract


def _expiry_str(days_from_today: int) -> str:
    return (date.today() + timedelta(days=days_from_today)).isoformat()


def _make_contract(*, bid=1.0, ask=1.10, delta=0.45, days=40, volume=500, oi=1000) -> dict:
    return {
        "symbol": "AAPL",
        "strike": 185,
        "expiry": _expiry_str(days),
        "is_call": True,
        "bid": bid,
        "ask": ask,
        "price": (bid + ask) / 2,
        "delta": delta,
        "theta": -0.05,
        "volume": volume,
        "open_interest": oi,
        "iv_rank": 30,
        "ivRank": 30,
    }


def test_preferred_dte_override_centres_the_soft_score():
    """A 365-DTE contract scores poorly against the fixed 21-60 default preferred
    band, but should score near-perfectly once the preferred band is overridden
    to match a 330-400 DTE Annual window (centre 365)."""
    contract = _make_contract(days=365)
    card_default   = validate_contract(contract, 70)
    card_annual_ov = validate_contract(
        contract, 70,
        overrides={"min_dte": 330, "max_dte": 400, "preferred_dte_min": 330, "preferred_dte_max": 400},
    )
    assert "dte_outside_preferred" in card_default.soft_flags
    assert "dte_outside_preferred" not in card_annual_ov.soft_flags
    assert card_annual_ov.breakdown.dte_score > card_default.breakdown.dte_score


def test_preferred_dte_override_does_not_affect_hard_reject_alone():
    """Setting only preferred_dte_* (no min_dte/max_dte) must not change hard-reject
    behaviour — it only affects the soft score."""
    contract = _make_contract(days=10)  # below default hard min_dte=21
    card = validate_contract(contract, 70, overrides={"preferred_dte_min": 5, "preferred_dte_max": 15})
    assert "dte_too_short" in card.reject_reasons
