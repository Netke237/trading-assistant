"""The null-`ivRank` path, end to end.

market.py's async chain builder writes `"ivRank": None` on every chain where
neither IBKR nor tastytrade answered -- the DEFAULT configuration. Nothing
covered what the rest of the backend did with that, and the answer was: raised.

`chain.get("ivRank", 50)` returns None rather than 50, because the key is
PRESENT and holds None, so `int(...)` and `float(...)` on it raised TypeError.
That was a 500 on every options scan and every /api/contracts call, not a blank
column. These tests pin the whole path: the chain shape, the augmentation, the
scorer, and the response models (PHASE-A-NULL-IVRANK-2026-09-06).
"""
import pytest

from app.data.augment import _augment, opt_float, opt_int
from app.schemas import AlternativeContract, ContractDetails, OptionContract
from app.scoring.contract_validator import validate_contract


def _chain_row(**over):
    """A chain row shaped exactly as fetch_option_chain_async emits one."""
    row = {
        "id": "AAPL|190|2026-11-20|C",
        "symbol": "AAPL",
        "strike": 190,
        "expiry": "2026-11-20",
        "right": "C",
        "dte": 75,
        "dteTotal": 75,
        "price": 2.50,
        "delta": 0.45,
        "theta": -0.05,
        "iv": 45.0,
        "ivRank": None,        # the default: no rank source answered
        "ivPercentile": None,
        "spread": 0.05,
        "volume": 500,
        "open_interest": 2000,
        "score": 0,
    }
    row.update(over)
    return row


# ── The coercion helper both routers share ───────────────────────────────────

def test_opt_int_preserves_none_instead_of_raising():
    """The exact expression that used to raise, and what replaced it."""
    row = _chain_row()
    with pytest.raises(TypeError):
        int(row.get("ivRank", 50))     # the shipped bug, pinned so it stays fixed
    assert opt_int(row.get("ivRank")) is None


def test_opt_int_rounds_rather_than_truncates():
    assert opt_int(44.6) == 45
    assert opt_int(44.4) == 44
    assert opt_int(0) == 0            # a rank of 0 is a real reading, not absent


def test_opt_float_keeps_one_decimal_and_none():
    assert opt_float(44.66) == 44.7
    assert opt_float(None) is None
    assert opt_float(0) == 0.0


# ── Augmentation ─────────────────────────────────────────────────────────────

def test_augment_survives_a_null_rank_and_reports_the_absolute_basis():
    a = _augment(_chain_row(), 190.0)
    assert a["iv_rank"] == 45.0
    assert a["iv_basis"] == "absolute"
    assert a["iv_percentile"] is None


def test_augment_prefers_a_real_percentile_when_one_exists():
    a = _augment(_chain_row(ivRank=62.0, ivPercentile=70.0), 190.0)
    assert a["iv_rank"] == 62.0
    assert a["iv_basis"] == "rank"
    assert a["iv_percentile"] == 70.0


def test_augment_reports_no_basis_when_there_is_no_volatility_at_all():
    a = _augment(_chain_row(iv=None), 190.0)
    assert a["iv_rank"] is None
    assert a["iv_basis"] == "none"


def test_a_rank_of_zero_is_a_reading_but_an_absolute_iv_of_zero_is_not():
    """The asymmetry is deliberate and mirrors routers/scan.py.

    IV sitting at the very bottom of a name's own 52-week range is a genuine
    and strongly favourable reading; an absolute IV of 0 is a missing-data
    sentinel, since a tradeable option cannot have zero implied volatility.
    """
    ranked = _augment(_chain_row(ivRank=0.0), 190.0)
    assert ranked["iv_rank"] == 0.0 and ranked["iv_basis"] == "rank"

    absolute = _augment(_chain_row(iv=0), 190.0)
    assert absolute["iv_rank"] is None and absolute["iv_basis"] == "none"


# ── The scorer ───────────────────────────────────────────────────────────────

def test_validate_contract_accepts_an_augmented_null_rank_row():
    card = validate_contract(_augment(_chain_row(), 190.0), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons
    assert card.detail["iv_rank"]["iv_basis"] == "absolute"


def test_a_high_absolute_iv_is_no_longer_judged_as_a_percentile():
    """The defect in one test.

    A name at 75% absolute IV used to be hard-rejected by a ceiling written for
    percentiles. It is still rejected today only because the two ceilings are
    seeded equal -- what changed is WHICH ceiling applies, so moving one no
    longer moves the other. `max_iv_abs` raised to 80 must clear it while the
    percentile ceiling stays at 70.
    """
    row = _augment(_chain_row(iv=75.0), 190.0)
    assert row["iv_basis"] == "absolute"
    # ROUND 4 finding 10: reported under the ABSOLUTE name, since that is the
    # quantity and the ceiling that judged it.
    assert "iv_too_high" in validate_contract(row, 70).reject_reasons
    relaxed = validate_contract(row, 70, overrides={"max_iv_abs": 80})
    assert "iv_too_high" not in relaxed.reject_reasons


def test_no_volatility_data_does_not_hard_reject():
    """A data gap is not an expensive contract."""
    card = validate_contract(_augment(_chain_row(iv=None), 190.0), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons
    assert "no_iv_rank_data" in card.soft_flags


# ── The response models ──────────────────────────────────────────────────────

def test_option_contract_accepts_a_null_rank_and_carries_the_absolute_level():
    row = _chain_row()
    c = OptionContract(
        id=row["id"], symbol=row["symbol"], strike=row["strike"],
        expiry=row["expiry"], right="C", dte=row["dte"], dteTotal=row["dteTotal"],
        price=row["price"], delta=row["delta"], theta=row["theta"],
        ivRank=opt_int(row["ivRank"]), iv=opt_float(row["iv"]),
        ivPercentile=opt_int(row["ivPercentile"]),
        spread=row["spread"], volume=row["volume"], score=70,
        contractConfidence="PASS",
    )
    assert c.ivRank is None
    assert c.iv == 45.0


def test_contract_details_accepts_a_null_rank():
    d = ContractDetails(
        strike=190, expiry="2026-11-20", right="C", mid=2.5, delta=0.45,
        theta=-0.05, ivRank=None, iv=45.0, ivPercentile=None, dte=75,
    )
    assert d.ivRank is None and d.iv == 45.0


def test_alternative_contract_accepts_a_null_rank():
    from app.schemas import ContractScoreBreakdown
    a = AlternativeContract(
        symbol="AAPL", strike=195, expiry="2026-11-20", right="C", dte=75,
        mid=1.80, delta=0.35, theta=-0.04, ivRank=None, iv=46.2, score=64,
        contractConfidence="CAUTION",
        contractBreakdown=ContractScoreBreakdown(
            dteFit=70, delta=65, ivAttractiveness=50, liquidity=60, spread=80,
        ),
        rrRatio=1.8, rrModel="Delta approximation", reason="cheaper, less delta",
    )
    assert a.ivRank is None and a.iv == 46.2
