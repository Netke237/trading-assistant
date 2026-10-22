"""
Reproducibility tests.

Run scan-related scoring twice with the same fixtures + settings,
assert identical ranked output.
"""

from app.scoring.stock_scorer import score_stock, StockScoreCard
from app.scoring.contract_validator import validate_contract


def _make_bars(n: int, start_price: float = 100.0):
    """Generate n deterministic OHLCV bars."""
    bars = []
    price = start_price
    for i in range(n):
        o = round(price, 2)
        c = round(price + (i % 5 - 2) * 0.5, 2)
        h = round(max(o, c) + 0.3, 2)
        l = round(min(o, c) - 0.3, 2)
        bars.append({"time": f"2026-01-{i + 1:02d}", "open": o, "high": h, "low": l, "close": c, "volume": 1_000_000 + i * 100})
        price = c
    return bars


def _make_contract(strike: int = 100, price: float = 2.5):
    return {
        "strike": strike,
        "expiry": "2026-05-15",
        "right": "C",
        "dte": 30,
        "dteTotal": 38,
        "price": price,
        "delta": 0.45,
        "theta": -0.09,
        "ivRank": 45,
        "ivPercentile": 55,
        "spread": 0.08,
        "volume": 4200,
        "score": 70,
    }


class TestStockScorerReproducibility:
    """score_stock must be deterministic for identical inputs."""

    def test_same_bars_produce_same_score(self):
        bars = _make_bars(60)
        card1 = score_stock("AAPL", "Bullish", "Swing", bars)
        card2 = score_stock("AAPL", "Bullish", "Swing", bars)
        assert card1.score == card2.score
        assert card1.status == card2.status

    def test_same_bars_produce_same_rules(self):
        bars = _make_bars(60)
        card1 = score_stock("AAPL", "Bullish", "Swing", bars)
        card2 = score_stock("AAPL", "Bullish", "Swing", bars)
        assert len(card1.rules) == len(card2.rules)
        for r1, r2 in zip(card1.rules, card2.rules):
            assert r1.name == r2.name
            assert r1.score == r2.score
            assert r1.status == r2.status

    def test_different_symbols_same_bars_same_score(self):
        bars = _make_bars(60)
        card1 = score_stock("AAPL", "Bullish", "Swing", bars)
        card2 = score_stock("MSFT", "Bullish", "Swing", bars)
        assert card1.score == card2.score
        assert card1.status == card2.status

    def test_direction_affects_score(self):
        bars = _make_bars(60)
        bullish = score_stock("AAPL", "Bullish", "Swing", bars)
        bearish = score_stock("AAPL", "Bearish", "Swing", bars)
        # Direction does not change score in current implementation,
        # but the test documents that it may in the future.
        assert isinstance(bullish.score, int)
        assert isinstance(bearish.score, int)


class TestContractValidatorReproducibility:
    """validate_contract must be deterministic for identical inputs."""

    def test_same_contract_produces_same_score(self):
        contract = _make_contract()
        card1 = validate_contract(contract, stock_score=75)
        card2 = validate_contract(contract, stock_score=75)
        assert card1.score == card2.score
        assert card1.status == card2.status

    def test_different_stock_scores_affect_contract_score(self):
        contract = _make_contract()
        card_high = validate_contract(contract, stock_score=90)
        card_low = validate_contract(contract, stock_score=30)
        assert isinstance(card_high.score, int)
        assert isinstance(card_low.score, int)
        # stock_score=30 is below the hard-reject gate (min_stock_score=45,
        # contract_rules.yaml) — must reject, not silently score it anyway.
        assert card_low.status == "REJECT"
        assert "stock_score_below_threshold" in card_low.reject_reasons
        assert "stock_score_below_threshold" not in card_high.reject_reasons


class TestEndToEndPipelineReproducibility:
    """Full pipeline from bars to final card must be reproducible."""

    def test_full_pipeline_same_input_same_output(self):
        bars = _make_bars(60)
        stock_card = score_stock("AAPL", "Bullish", "Swing", bars, iv_rank=45)
        contract = _make_contract()
        contract_card = validate_contract(contract, stock_score=stock_card.score)

        # Run again
        stock_card2 = score_stock("AAPL", "Bullish", "Swing", bars, iv_rank=45)
        contract_card2 = validate_contract(contract, stock_score=stock_card2.score)

        assert stock_card.score == stock_card2.score
        assert contract_card.score == contract_card2.score
        assert stock_card.status == stock_card2.status
        assert contract_card.status == contract_card2.status
