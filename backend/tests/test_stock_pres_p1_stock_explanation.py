"""STOCK-PRES-P1 T1: every stock-scan candidate carries `stock_explanation`,
exactly the scorer's own `StockScoreCard.explanation` (weights, factor
components, scorer caps). `stock_status` stays the scan's final verdict; a bad
explanation is sent as null and never drops the candidate; results persisted
before the field load with it as None.

Plan: docs/superpowers/plans/2026-10-10-stock-pres-p1-backend-evidence-plan.md,
Task 1.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.routers import stock_scan as ss
from app.schemas import StockExplanation
from app.schemas.stock_scan import PositionCardOut, StockScanResult
from app.scoring.stock_scorer import RuleResult, StockScoreCard, score_stock as _real_score_stock
from tests.test_scan_bearish_unvalidated import stock_client  # noqa: F401 -- fixture reused

_FIXTURES = Path(__file__).parent / "fixtures"


def _trend_bars(slope: float) -> list[dict]:
    """300 daily bars on a straight line. Measured on Python 3.11: the real
    scorer gives Bullish PASS on slope +0.1 and Bearish PASS (66) on -0.2, so
    neither direction is dropped as a score REJECT."""
    out = []
    for i in range(300):
        c = 200.0 + slope * i
        out.append({"time": 1_700_000_000 + i * 86400, "open": c + 0.2, "high": c + 1.0,
                    "low": c - 1.0, "close": c, "volume": 1_000_000})
    return out


@pytest.fixture
def evidence_client(stock_client, monkeypatch):  # noqa: F811 -- pytest fixture injection
    """The stock_client harness, but with the REAL score_stock wrapped so the
    card it returned is recorded, and bars chosen per test via `use_bars`."""
    recorded: list[StockScoreCard] = []
    bars_box: dict = {"bars": _trend_bars(0.1)}

    def recorder(**kw):
        card = _real_score_stock(**kw)
        recorded.append(card)
        return card

    async def _bars(symbol, start, end):
        return bars_box["bars"]

    monkeypatch.setattr(ss, "score_stock", recorder)
    monkeypatch.setattr(ss, "get_historical_bars", _bars)
    stock_client.recorded = recorded
    stock_client.bars_box = bars_box
    return stock_client


def _scan(client, direction: str) -> dict:
    response = client.post("/api/stock-scan", json={
        "universe": ["TEST"], "symbols": ["TEST"], "direction": direction,
        "horizon": "Swing", "strategy": "pullback_ema",
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["candidates"]) == 1, data["rejected"]
    return data["candidates"][0]


def _wire(explanation: dict) -> dict:
    return json.loads(StockExplanation.model_validate(explanation).model_dump_json())


def test_stock_explanation_equals_the_scorers_dict(evidence_client):
    candidate = _scan(evidence_client, "Bullish")
    assert len(evidence_client.recorded) == 1
    recorded = evidence_client.recorded[0]
    assert recorded.explanation is not None
    assert candidate["stock_explanation"] == _wire(recorded.explanation)
    assert candidate["stock_score"] == recorded.score


def test_verdict_stays_separate_from_the_scorer_evidence(evidence_client):
    evidence_client.bars_box["bars"] = _trend_bars(-0.2)
    candidate = _scan(evidence_client, "Bearish")
    recorded = evidence_client.recorded[-1]
    # The scan's Bearish cap is the verdict...
    assert candidate["stock_status"] == "CAUTION"
    # ...the evidence is the scorer's own, untouched by the cap.
    assert recorded.status == "PASS"
    assert candidate["stock_explanation"]["status"] == recorded.status
    assert candidate["stock_explanation"] == _wire(recorded.explanation)
    assert candidate["stock_score"] == recorded.score


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "NVDA"])
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
@pytest.mark.parametrize("horizon", ["Intraday", "Swing", "Position"])
def test_real_scorer_output_always_validates(symbol, direction, horizon):
    bars = json.loads((_FIXTURES / f"{symbol}_candles.json").read_text())
    card = _real_score_stock(symbol=symbol, direction=direction, horizon=horizon,
                             bars=bars[-120:], scoring_mode="stock")
    assert card.explanation is not None
    StockExplanation.model_validate(card.explanation)


def _fixed_card(explanation):
    def _score(**kw):
        return StockScoreCard(kw["symbol"], kw["direction"], kw["horizon"], 75, "PASS",
                              [RuleResult("trend", "PASS", 90, {})], explanation=explanation)
    return _score


def test_a_bad_explanation_never_drops_the_candidate(stock_client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ss, "score_stock", _fixed_card({"version": 1}))
    bad = _scan(stock_client, "Bullish")
    monkeypatch.setattr(ss, "score_stock", _fixed_card(None))
    none = _scan(stock_client, "Bullish")
    assert bad["stock_explanation"] is None
    assert none["stock_explanation"] is None
    assert bad["stock_score"] == none["stock_score"] == 75
    assert bad["stock_status"] == none["stock_status"] == "PASS"


def test_old_persisted_results_load_and_present_evidence_round_trips(evidence_client):
    candidate = _scan(evidence_client, "Bullish")
    assert candidate["stock_explanation"] is not None

    old = dict(candidate)
    old.pop("stock_explanation")
    stored = json.dumps({"scan_id": "old", "timestamp": "2026-10-01T00:00:00+00:00",
                         "candidates": [old], "rejected": []})
    result = StockScanResult.model_validate_json(stored)
    assert result.candidates[0].stock_explanation is None

    card = PositionCardOut.model_validate(candidate)
    again = PositionCardOut.model_validate_json(card.model_dump_json())
    assert again == card
    assert json.loads(again.model_dump_json())["stock_explanation"] == candidate["stock_explanation"]
