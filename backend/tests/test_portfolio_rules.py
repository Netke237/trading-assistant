"""
Portfolio risk rule tests (prep for FR-42).

Tests exposure limit calculations even if not yet enforced by the router.
"""

import pytest
from app.schemas import PortfolioPosition


def _make_position(
    symbol: str = "AAPL",
    contract: str = "AAPL 190C 05/16",
    contracts: int = 2,
    entry_price: float = 4.15,
    current_price: float = 5.02,
    pnl_dollar: float = 870,
    pnl_pct: float = 20.96,
    direction: str = "Bullish",
) -> PortfolioPosition:
    return PortfolioPosition(
        symbol=symbol,
        contract=contract,
        direction=direction,  # type: ignore[arg-type]
        entryDate="2026-04-08",
        expiry="2026-05-16",
        dteRemaining=28,
        dteTotal=38,
        entryPrice=entry_price,
        currentPrice=current_price,
        pnlDollar=pnl_dollar,
        pnlPct=pnl_pct,
        stop=180.0,
        target=198.0,
        status="PASS",  # type: ignore[arg-type]
        ivRank=42,
        delta=0.58,
        theta=-0.08,
        vega=0.22,
        contracts=contracts,
    )


def _total_notional(positions: list[PortfolioPosition]) -> float:
    """Sum of (contracts * 100 * currentPrice) for all positions."""
    return sum(p.contracts * 100 * p.currentPrice for p in positions)


def _total_pnl(positions: list[PortfolioPosition]) -> float:
    return sum(p.pnlDollar for p in positions)


def _max_concentration(positions: list[PortfolioPosition]) -> tuple[str, float]:
    """Return (symbol, pct) of the largest position by notional."""
    total = _total_notional(positions)
    if total == 0:
        return ("", 0.0)
    by_symbol: dict[str, float] = {}
    for p in positions:
        by_symbol[p.symbol] = by_symbol.get(p.symbol, 0.0) + p.contracts * 100 * p.currentPrice
    max_sym = max(by_symbol, key=by_symbol.get)  # type: ignore[arg-type]
    return (max_sym, round(by_symbol[max_sym] / total * 100, 2))


class TestExposureCalculations:
    """Pure calculation tests for portfolio risk metrics."""

    def test_empty_portfolio_zero_notional(self):
        assert _total_notional([]) == 0.0

    def test_single_position_notional(self):
        pos = _make_position(contracts=2, current_price=5.0)
        assert _total_notional([pos]) == 2 * 100 * 5.0

    def test_multiple_positions_notional(self):
        p1 = _make_position(symbol="AAPL", contracts=2, current_price=5.0)
        p2 = _make_position(symbol="MSFT", contracts=3, current_price=8.0)
        assert _total_notional([p1, p2]) == (2 * 100 * 5.0) + (3 * 100 * 8.0)

    def test_total_pnl(self):
        p1 = _make_position(pnl_dollar=500)
        p2 = _make_position(pnl_dollar=-200)
        assert _total_pnl([p1, p2]) == 300

    def test_concentration_single_position_is_100_percent(self):
        p1 = _make_position(symbol="AAPL", contracts=2, current_price=5.0)
        sym, pct = _max_concentration([p1])
        assert sym == "AAPL"
        assert pct == 100.0

    def test_concentration_split_50_50(self):
        p1 = _make_position(symbol="AAPL", contracts=1, current_price=5.0)
        p2 = _make_position(symbol="MSFT", contracts=1, current_price=5.0)
        sym, pct = _max_concentration([p1, p2])
        assert pct == 50.0

    def test_concentration_weighted_by_contracts(self):
        p1 = _make_position(symbol="AAPL", contracts=3, current_price=5.0)
        p2 = _make_position(symbol="MSFT", contracts=1, current_price=5.0)
        sym, pct = _max_concentration([p1, p2])
        assert sym == "AAPL"
        expected = round((3 * 100 * 5.0) / ((3 + 1) * 100 * 5.0) * 100, 2)
        assert pct == expected


class TestPortfolioRiskLimits:
    """Risk limit gate tests — thresholds that will be enforced by FR-42."""

    MAX_POSITION_PCT = 25.0  # max % of portfolio in one symbol
    MAX_NOTIONAL = 100_000.0  # max total notional

    def test_portfolio_within_limits_passes(self):
        p1 = _make_position(symbol="AAPL", contracts=1, current_price=5.0)
        p2 = _make_position(symbol="MSFT", contracts=1, current_price=5.0)
        p3 = _make_position(symbol="NVDA", contracts=1, current_price=5.0)
        p4 = _make_position(symbol="META", contracts=1, current_price=5.0)
        p5 = _make_position(symbol="TSLA", contracts=1, current_price=5.0)
        positions = [p1, p2, p3, p4, p5]
        total = _total_notional(positions)
        _, max_pct = _max_concentration(positions)
        assert total <= self.MAX_NOTIONAL
        assert max_pct <= self.MAX_POSITION_PCT

    def test_concentration_over_limit_fails(self):
        p1 = _make_position(symbol="AAPL", contracts=10, current_price=50.0)
        p2 = _make_position(symbol="MSFT", contracts=1, current_price=5.0)
        positions = [p1, p2]
        _, max_pct = _max_concentration(positions)
        assert max_pct > self.MAX_POSITION_PCT

    def test_notional_over_limit_fails(self):
        p1 = _make_position(symbol="AAPL", contracts=21, current_price=50.0)
        positions = [p1]
        total = _total_notional(positions)
        assert total > self.MAX_NOTIONAL

    def test_adding_position_would_breach_limit(self):
        existing = [_make_position(symbol="AAPL", contracts=10, current_price=50.0)]
        existing_total = _total_notional(existing)
        existing_conc = _max_concentration(existing)[1]

        new_pos = _make_position(symbol="AAPL", contracts=5, current_price=50.0)
        hypothetical = existing + [new_pos]
        hypo_total = _total_notional(hypothetical)
        hypo_conc = _max_concentration(hypothetical)[1]

        assert existing_total <= self.MAX_NOTIONAL
        assert hypo_total > self.MAX_NOTIONAL or hypo_conc > self.MAX_POSITION_PCT
