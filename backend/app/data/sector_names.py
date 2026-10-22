"""Canonical sector name mapping shared across the backend.

Maps every known yfinance / legacy name → the canonical display name used
in the sector heatmap (matching _ETF_NAME in sectors.py).
"""
from __future__ import annotations

NORMALIZE: dict[str, str] = {
    # yfinance labels
    "Technology":             "Technology",
    "Communication Services": "Comm. Services",
    "Consumer Cyclical":      "Consumer Discretionary",
    "Industrials":            "Industrials",
    "Financial Services":     "Financials",
    "Consumer Defensive":     "Consumer Staples",
    "Healthcare":             "Health Care",
    "Basic Materials":        "Materials",
    "Real Estate":            "Real Estate",
    "Utilities":              "Utilities",
    "Energy":                 "Energy",
    # Wikipedia GICS label (scripts/fill_sectors.py)
    "Information Technology": "Technology",
    # Already-canonical pass-throughs (idempotent on re-runs)
    "Financials":             "Financials",
    "Consumer Staples":       "Consumer Staples",
    "Health Care":            "Health Care",
    "Materials":              "Materials",
    "Comm. Services":         "Comm. Services",
    "Consumer Discretionary": "Consumer Discretionary",
}
