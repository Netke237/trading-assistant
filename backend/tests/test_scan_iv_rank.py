"""
Tests for IV rank precision in _augment and threshold boundary in _score_iv_rank.
Covers WS-C fix: augment.py must preserve float iv_rank (not truncate to int)
and forward iv_percentile through the pipeline.
"""
from app.data.augment import _augment
from app.scoring.contract_validator import _score_iv_rank


def test_augment_preserves_float_iv_rank():
    raw = {
        "price": 2.0,
        "spread": 0.1,
        "delta": 0.4,
        "ivRank": 55.9,
        "ivPercentile": 70.0,
        "right": "C",
        "dte": 30,
        "strike": 100,
    }
    result = _augment(raw, stock_price=100.0)
    assert result["iv_rank"] == 55.9
    assert result["iv_percentile"] == 70.0


def test_score_iv_rank_55_9_is_elevated():
    cfg = {"soft_rank": {"preferred_iv_rank_max": 55}}
    score, flags = _score_iv_rank({"iv_rank": 55.9}, cfg)
    assert "iv_rank_elevated" in flags


def test_score_iv_rank_55_0_is_not_elevated():
    cfg = {"soft_rank": {"preferred_iv_rank_max": 55}}
    score, flags = _score_iv_rank({"iv_rank": 55.0}, cfg)
    assert "iv_rank_elevated" not in flags
