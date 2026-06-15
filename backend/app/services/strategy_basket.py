"""Stratified basket builder for walk-forward optimization."""

from __future__ import annotations
from collections import defaultdict
import csv
from pathlib import Path


def build_basket(rows: list[dict], *, per_sector: int) -> list[str]:
    """Pick top-N most liquid symbols per sector.

    Args:
        rows: List of dicts with keys: symbol, sector, liquidity
        per_sector: Number of top symbols to select per sector

    Returns:
        Sorted list of selected symbols (deterministic order)
    """
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_sector[r.get("sector") or "Unknown"].append(r)

    chosen: list[str] = []
    for sector, items in by_sector.items():
        # Sort by liquidity descending, break ties by symbol for determinism
        items.sort(key=lambda x: (-x.get("liquidity", 0), x.get("symbol", "")))
        chosen.extend(i["symbol"] for i in items[:per_sector])

    return sorted(chosen)


def propose_basket(per_sector: int) -> list[str]:
    """Build a stratified basket from sp500.csv.

    Reads symbol and sector from sp500.csv. Uses a simple liquidity proxy
    (all symbols get liquidity=1.0 for now; could be enhanced with real
    average dollar volume from ohlcv_daily table).

    Args:
        per_sector: Number of top symbols to select per sector

    Returns:
        Sorted list of selected symbols
    """
    csv_path = Path(__file__).parent.parent / "data" / "sp500.csv"

    rows = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "symbol": row["symbol"],
                    "sector": row.get("sector", "Unknown"),
                    "liquidity": 1.0,  # Simple proxy; could use real ADV
                }
            )

    return build_basket(rows, per_sector=per_sector)
