from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

import yfinance as yf


def fetch_candles(symbol: str, bars: int = 120) -> list[dict]:
    """
    Returns up to `bars` daily OHLCV bars for `symbol`, newest last.
    Each dict: {time: str (YYYY-MM-DD), open, high, low, close: float, volume: int}
    Returns [] on any error (unknown symbol, network failure, etc.).
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="6mo", interval="1d", auto_adjust=True)
        if hist.empty:
            return []
        rows = []
        for ts, row in hist.tail(bars).iterrows():
            rows.append({
                "time":   ts.strftime("%Y-%m-%d"),
                "open":   round(float(row["Open"]),   2),
                "high":   round(float(row["High"]),   2),
                "low":    round(float(row["Low"]),    2),
                "close":  round(float(row["Close"]),  2),
                "volume": int(row["Volume"]),
            })
        return rows
    except Exception:
        return []


def fetch_price(symbol: str) -> Optional[float]:
    """
    Returns the latest closing price for `symbol`, or None on failure.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d", interval="1d", auto_adjust=True)
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 2)
    except Exception:
        return None


def fetch_option_chain(symbol: str, expiry: Optional[str] = None) -> list[dict]:
    """
    Returns call contracts for `symbol`.
    If `expiry` is given (YYYY-MM-DD), fetches that expiry only.
    Otherwise fetches the nearest available expiry.
    Each dict matches the OptionContract schema fields:
      id, symbol, strike, expiry, right, dte, dteTotal,
      price, delta, theta, ivRank, ivPercentile, spread, volume, score
    `ivRank`, `ivPercentile`, `delta`, `theta`, `score` default to 0 when unavailable
    (yfinance does not provide greeks directly; downstream scoring fills them).
    Returns [] on any error.
    """
    try:
        ticker = yf.Ticker(symbol)
        exps = ticker.options
        if not exps:
            return []

        target_exp = expiry if expiry in exps else exps[0]
        chain = ticker.option_chain(target_exp)
        calls = chain.calls

        today = date.today()
        try:
            exp_date = date.fromisoformat(target_exp)
        except ValueError:
            return []
        dte = max(0, (exp_date - today).days)

        result = []
        for _, row in calls.iterrows():
            strike = float(row.get("strike", 0))
            bid    = float(row.get("bid", 0) or 0)
            ask    = float(row.get("ask", 0) or 0)
            mid    = round((bid + ask) / 2, 2) if ask > 0 else 0.0
            spread = round(ask - bid, 2) if ask > 0 else 0.0
            volume = int(row.get("volume", 0) or 0)
            oi     = int(row.get("openInterest", 0) or 0)
            iv     = float(row.get("impliedVolatility", 0) or 0)

            if ask <= 0 or math.isnan(ask):
                continue

            result.append({
                "id":           f"{symbol}|{int(strike)}|{target_exp}|C",
                "symbol":       symbol,
                "strike":       int(strike),
                "expiry":       target_exp,
                "right":        "C",
                "dte":          dte,
                "dteTotal":     dte,
                "price":        mid,
                "delta":        0.0,
                "theta":        0.0,
                "ivRank":       int(round(iv * 100)),
                "ivPercentile": 0,
                "spread":       spread,
                "volume":       volume,
                "score":        0,
            })
        return result
    except Exception:
        return []
