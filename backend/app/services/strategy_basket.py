"""Stratified basket builder for walk-forward optimization."""

from __future__ import annotations
import csv
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

_CSV_PATH = Path(__file__).parent.parent / "data" / "sp500.csv"


def build_basket(rows: list[dict], *, per_sector: int) -> list[str]:
    """Pick top-N symbols per sector, sorted by liquidity desc then symbol asc.

    Args:
        rows: List of dicts with keys: symbol, sector, liquidity
        per_sector: Number of symbols to select per sector

    Returns:
        Sorted list of selected symbols (deterministic order)

    Raises:
        ValueError: If per_sector < 1
    """
    if per_sector < 1:
        raise ValueError(f"per_sector must be >= 1, got {per_sector}")

    seen: set[str] = set()
    deduped = [r for r in rows if r["symbol"] not in seen and not seen.add(r["symbol"])]

    by_sector: dict[str, list[dict]] = defaultdict(list)
    for r in deduped:
        by_sector[r.get("sector") or "Unknown"].append(r)

    chosen: list[str] = []
    for sector, items in by_sector.items():
        items.sort(key=lambda x: (-x.get("liquidity", 0), x.get("symbol", "")))
        chosen.extend(i["symbol"] for i in items[:per_sector])

    return sorted(chosen)


def propose_basket(per_sector: int) -> list[str]:
    """Build a stratified basket from sp500.csv.

    Selects symbols alphabetically within each sector. All symbols receive
    liquidity=1.0, so selection within each sector is purely alphabetical.
    Returns [] if sp500.csv is missing or unreadable — does not raise.

    Args:
        per_sector: Number of symbols to select per sector

    Returns:
        Sorted list of selected symbols, or [] on error
    """
    rows: list[dict] = []
    try:
        with open(_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "symbol" not in (reader.fieldnames or []):
                logger.error("sp500.csv is missing a 'symbol' column")
                return []
            for row in reader:
                rows.append(
                    {
                        "symbol": row["symbol"],
                        "sector": row.get("sector", "Unknown"),
                        "liquidity": 1.0,
                    }
                )
    except FileNotFoundError:
        logger.error("sp500.csv not found at %s", _CSV_PATH)
        return []
    except csv.Error as exc:
        logger.error("Failed to read sp500.csv: %s", exc)
        return []

    return build_basket(rows, per_sector=per_sector)
