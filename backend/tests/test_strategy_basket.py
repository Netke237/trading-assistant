"""Tests for stratified basket builder."""

import pytest
from app.services.strategy_basket import build_basket


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
