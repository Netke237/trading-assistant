import json
from pathlib import Path
from decimal import Decimal
from app.data.edgar import _build_snapshot, _extract_concept, _pick_annual_values

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "edgar_aapl.json"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def test_pick_annual_values_returns_sorted_newest_first():
    vals = [
        {"end": "2022-09-24", "filed": "2022-10-28", "val": 394328000000, "form": "10-K", "fp": "FY"},
        {"end": "2023-09-30", "filed": "2023-11-03", "val": 383285000000, "form": "10-K", "fp": "FY"},
        {"end": "2022-09-24", "filed": "2023-01-01", "val": 394328000001, "form": "10-K/A", "fp": "FY"},
    ]
    result = _pick_annual_values(vals)
    assert result[0]["end"] == "2023-09-30"
    assert result[1]["end"] == "2022-09-24"
    # deduplication: latest filed wins for the same end date
    assert result[1]["filed"] == "2023-01-01"


def test_extract_concept_revenue_falls_back():
    # Fixture only has the primary concept; ensure it is found
    facts = _load_fixture()["facts"]
    rows = _extract_concept(facts, "revenue")
    assert rows and rows[0]["val"] == 383285000000


def test_build_snapshot_derived_metrics():
    facts = _load_fixture()["facts"]
    snap = _build_snapshot("AAPL", "0000320193", facts)
    assert snap is not None
    assert snap.symbol == "AAPL"
    assert snap.fiscal_period_end.isoformat() == "2023-09-30"
    # Revenue growth YoY: (383.3B - 394.3B) / 394.3B ~= -2.8%
    assert snap.revenue_growth_yoy is not None
    assert snap.revenue_growth_yoy < 0
    # Gross margin: 169.1B / 383.3B ~= 44%
    assert snap.gross_margin is not None
    assert 0.40 < snap.gross_margin < 0.50
    # FCF: 110.5B - 11.0B = 99.5B
    assert snap.fcf is not None
    assert snap.fcf > Decimal("90000000000")
    # Current ratio: 143.6B / 145.3B ~= 0.99 (AAPL famously < 1)
    assert snap.current_ratio is not None
    assert 0.8 < snap.current_ratio < 1.1


def test_build_snapshot_missing_symbol_returns_none():
    # Empty facts -> None
    snap = _build_snapshot("FAKE", "0000000001", {"us-gaap": {}})
    assert snap is None


def test_ticker_to_cik_returns_none_on_missing(monkeypatch):
    from app.data import edgar
    monkeypatch.setattr(edgar, "_load_cik_map", lambda: {"AAPL": "0000320193"})
    assert edgar.ticker_to_cik("AAPL") == "0000320193"
    assert edgar.ticker_to_cik("UNKN") is None
