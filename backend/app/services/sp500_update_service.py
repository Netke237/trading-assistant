"""Background service for updating sp500.csv with fresh liquidity data from yfinance."""
from __future__ import annotations

import csv
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CSV_PATH = Path(__file__).parent.parent / "data" / "sp500.csv"
_PERIOD = "1mo"

_state: dict[str, Any] = {
    "status": "idle",       # idle | running | done | failed
    "last_updated": None,
    "symbols_updated": 0,
    "error": None,
    "in_progress": False,
}
_lock = threading.Lock()


def get_update_state() -> dict:
    with _lock:
        return dict(_state)


def _yf_key(symbol: str) -> str:
    return symbol.replace(".", "-")


def _calc_dollar_vol(data: Any, key: str, single: bool) -> float:
    if single:
        closes  = data["Close"].dropna()
        volumes = data["Volume"].dropna()
    else:
        closes  = data[key]["Close"].dropna()
        volumes = data[key]["Volume"].dropna()
    if len(closes) == 0 or len(volumes) == 0:
        return 0.0
    return round(float((closes * volumes).mean()) / 1_000_000, 2)


def _fetch_liquidity(symbols: list[str]) -> dict[str, float]:
    import yfinance as yf

    yf_syms = [_yf_key(s) for s in symbols]
    sym_map  = {_yf_key(s): s for s in symbols}

    logger.info("sp500_update_service: downloading %s OHLCV for %d symbols", _PERIOD, len(yf_syms))
    data = yf.download(
        tickers=yf_syms,
        period=_PERIOD,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
    )

    result: dict[str, float] = {}
    is_single = len(yf_syms) == 1
    for yf_sym in yf_syms:
        orig = sym_map[yf_sym]
        try:
            result[orig] = _calc_dollar_vol(data, yf_sym, is_single)
        except Exception as exc:
            logger.warning("sp500_update_service: %s — %s", orig, exc)
            result[orig] = 0.0

    zeros = [s for s, v in result.items() if v == 0.0]
    if zeros:
        logger.info("sp500_update_service: retrying %d zero-result symbols individually", len(zeros))
        for orig in zeros:
            yf_sym = _yf_key(orig)
            try:
                d = yf.download(yf_sym, period=_PERIOD, auto_adjust=True, progress=False)
                result[orig] = _calc_dollar_vol(d, yf_sym, True)
            except Exception:
                result[orig] = 0.0

    return result


def _run() -> None:
    with _lock:
        _state.update({"status": "running", "in_progress": True, "error": None})
    try:
        rows = list(csv.DictReader(_CSV_PATH.open(encoding="utf-8")))
        symbols = [r["symbol"] for r in rows]
        liquidity = _fetch_liquidity(symbols)

        fieldnames = ["symbol", "sector", "liquidity"]
        with _CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "symbol": row["symbol"],
                    "sector": row.get("sector", ""),
                    "liquidity": liquidity.get(row["symbol"], 0.0),
                })

        updated = sum(1 for s in symbols if liquidity.get(s, 0) > 0)
        logger.info("sp500_update_service: done — %d/%d symbols have liquidity > 0", updated, len(symbols))
        with _lock:
            _state.update({
                "status": "done",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "symbols_updated": updated,
                "in_progress": False,
            })
    except Exception as exc:
        logger.error("sp500_update_service: update failed — %s", exc, exc_info=True)
        with _lock:
            _state.update({"status": "failed", "error": str(exc), "in_progress": False})


def start_update_task() -> bool:
    """Start the S&P 500 CSV update in a background thread. Returns False if already running."""
    with _lock:
        if _state.get("in_progress"):
            return False
    threading.Thread(target=_run, daemon=True, name="sp500-update").start()
    return True
