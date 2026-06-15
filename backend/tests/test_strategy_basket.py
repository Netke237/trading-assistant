"""Tests for stratified basket builder."""

import pytest
from app.services.strategy_basket import build_basket, propose_basket


def test_basket_picks_top_n_per_sector():
    """Verify that build_basket selects top-N per sector by liquidity."""
    rows = [
        {"symbol": "A", "sector": "Tech", "liquidity": 9},
        {"symbol": "B", "sector": "Tech", "liquidity": 8},
        {"symbol": "C", "sector": "Tech", "liquidity": 1},
        {"symbol": "D", "sector": "Energy", "liquidity": 5},
    ]
    basket = build_basket(rows, per_sector=2)
    assert set(basket) == {"A", "B", "D"}  # top-2 Tech by liquidity + all Energy (only 1)
    assert basket == sorted(basket)  # deterministic / reproducible order


def test_basket_respects_per_sector_limit():
    """Verify that per_sector parameter limits selections."""
    rows = [
        {"symbol": "X1", "sector": "Finance", "liquidity": 10},
        {"symbol": "X2", "sector": "Finance", "liquidity": 9},
        {"symbol": "X3", "sector": "Finance", "liquidity": 8},
        {"symbol": "Y1", "sector": "Health", "liquidity": 7},
        {"symbol": "Y2", "sector": "Health", "liquidity": 6},
    ]
    basket = build_basket(rows, per_sector=2)
    assert basket == ["X1", "X2", "Y1", "Y2"]
    # Exactly 2 per sector
    assert len([s for s in basket if s.startswith("X")]) == 2
    assert len([s for s in basket if s.startswith("Y")]) == 2


def test_basket_empty_sector_handling():
    """Verify that symbols without sector default to 'Unknown'."""
    rows = [
        {"symbol": "A", "sector": "Tech", "liquidity": 5},
        {"symbol": "B", "liquidity": 3},  # No sector
    ]
    basket = build_basket(rows, per_sector=2)
    assert "A" in basket
    assert "B" in basket


def test_basket_deterministic_order():
    """Verify that output order is deterministic (sorted)."""
    rows = [
        {"symbol": "Z", "sector": "Tech", "liquidity": 10},
        {"symbol": "A", "sector": "Tech", "liquidity": 9},
        {"symbol": "M", "sector": "Energy", "liquidity": 5},
    ]
    basket = build_basket(rows, per_sector=2)
    assert basket == ["A", "M", "Z"]


def test_basket_per_sector_validation():
    """Verify that per_sector < 1 raises ValueError."""
    rows = [{"symbol": "A", "sector": "Tech", "liquidity": 5}]
    with pytest.raises(ValueError, match="per_sector must be >= 1"):
        build_basket(rows, per_sector=0)
    with pytest.raises(ValueError, match="per_sector must be >= 1"):
        build_basket(rows, per_sector=-1)


def test_basket_deduplication():
    """Verify that duplicate symbols are removed before grouping."""
    rows = [
        {"symbol": "A", "sector": "Tech", "liquidity": 10},
        {"symbol": "A", "sector": "Tech", "liquidity": 5},  # Duplicate A
        {"symbol": "B", "sector": "Energy", "liquidity": 8},
    ]
    basket = build_basket(rows, per_sector=2)
    # Should keep only first A (liquidity 10), not include it twice
    assert basket.count("A") == 1
    assert set(basket) == {"A", "B"}


def test_propose_basket_returns_sorted_symbols():
    """Verify that propose_basket returns sorted symbols with no duplicates."""
    result = propose_basket(per_sector=1)
    assert len(result) >= 1, "Basket should have at least 1 symbol"
    assert result == sorted(result), "Result should be sorted"
    assert len(set(result)) == len(result), "Result should have no duplicates"
