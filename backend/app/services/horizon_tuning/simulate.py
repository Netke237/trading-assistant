"""Trade simulator over a precomputed signal series — STOCKS-HORIZON-T1 H8.

``simulate_trades`` reproduces ``strategy_backtest.run_strategy_backtest_trades``
(``backtesting`` 0.6.6, ``cash=100_000``, ``exclusive_orders=True``,
``finalize_trades=False``) without calling the signal function per bar. The
fill rules are copied from ``backtesting.backtesting._Broker._process_orders``:

* Bar 0 is never processed; on every later bar the broker fills orders first,
  then the strategy's ``next()`` runs at that bar's close.
* Entry: a DAY limit order placed at bar t's close, live for bar t+1 only. A
  buy limit fills when ``low <= limit`` at ``min(open, limit)``; a sell limit
  when ``high >= limit`` at ``max(open, limit)``. Size = whole units of
  ``cash * (1 - eps) // (price * (1 + commission))``; zero units cancels it.
  The stop and target take effect from the next bar (never on the fill bar).
* Exits, queue order: a time-exit close order first (inserted at the front by
  ``Trade.close()``), at the bar's open; then the stop (long: ``low <= stop``
  -> ``min(open, stop)``; short: ``high >= stop`` -> ``max(open, stop)``);
  then the target (long: ``high >= target`` -> ``max(open, target)``; short:
  ``low <= target`` -> ``min(open, target)``). So a gap through either fills at
  the open, and a bar touching both is a stop.
* Commission per leg on ``|size| * price``; ``net_return_pct`` is
  ``Trade.pl_pct`` x 100.
* Time exit (H2): at the close of bar t, a trade filled on bar e with
  ``(d_t - d_e).days >= hold_max_days`` gets a close order for bar t+1's open.
* ``allowed[t] is False``: no entry order is placed at bar t's close (the gate
  mask, ``gates.py``, reads bars up to t, as a scan on that close would).
* Fewer than 100 bars: no trades. A trade still open at the end is dropped and
  counted in ``SimulatedTrades.dropped_open``.

Explicit ``SignalPoint.market`` events use next-open market fills instead:
positive finite stop/open/target must have valid geometry, optional R targets
are calculated from the actual open, and brackets are active on the fill bar.
Their setup age also enforces entry windows and gates at both closes. Legacy
three-field points retain every DAY-limit rule above. ``equity_curve`` records
cash plus marked position P&L, including entry commissions, at each close.

The parity test (tests/test_tuning_simulator_parity.py) is the judge.
"""
from __future__ import annotations

import math
import sys
from datetime import date
from math import copysign

import pandas as pd

from app.services.horizon_tuning.signals import MIN_SIGNAL_BARS, SignalPoint
from app.services.strategy_backtest import TradeRecord, _entry_side, normalize_direction

_CASH = 100_000.0
_FULL_EQUITY = 1 - sys.float_info.epsilon    # Strategy._FULL_EQUITY
_MIN_BARS = 100                              # run_strategy_backtest's history floor


class SimulatedTrades(list):
    """The closed trades (a ``list[TradeRecord]``, entry order) plus
    ``dropped_open``: trades still open at the end of the series, dropped as
    ``finalize_trades=False`` drops them (0 or 1: one position at a time)."""

    def __init__(self, trades=(), dropped_open: int = 0, equity_curve=None):
        super().__init__(trades)
        self.dropped_open = dropped_open
        self.equity_curve = equity_curve


def bar_dates(bars: list[dict]) -> list[date]:
    """Each bar's date as the backtest reads it (``pd.to_datetime`` of ``time``)."""
    return [ts.date() for ts in pd.to_datetime(pd.Series([b["time"] for b in bars]))]


def _contingent_ok(price: float | None) -> bool:
    """Trade.sl / Trade.tp setters assert ``0 < price < inf`` for a set value."""
    return not price or 0 < price < math.inf


def simulate_trades(
    bars: list[dict],
    signals: list[SignalPoint | None],
    *,
    direction: str,
    commission: float,
    hold_max_days: int | None,
    entry_start: date | None = None,
    entry_end: date | None = None,
    allowed: list[bool] | None = None,
    dates: list[date] | None = None,
) -> SimulatedTrades:
    """Closed trades for ``signals`` on ``bars`` (see the module docstring).

    ``dates`` (optional) = ``bar_dates(bars)``, precomputed by a caller that
    simulates the same bars many times.
    """
    direction = normalize_direction(direction)
    n_bars = len(bars)
    if len(signals) != n_bars:
        raise ValueError(f"signals has {len(signals)} entries for {n_bars} bars")
    if allowed is not None and len(allowed) != n_bars:
        raise ValueError(f"allowed has {len(allowed)} entries for {n_bars} bars")
    if n_bars < _MIN_BARS:
        return SimulatedTrades()
    # Backtest(...) refuses these (the backtest then returns its empty result).
    if not (-0.1 <= commission < 0.1):
        return SimulatedTrades()
    opens = [float(b["open"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    closes = [float(b["close"]) for b in bars]
    if any(math.isnan(v) for col in (opens, highs, lows, closes) for v in col):
        return SimulatedTrades()
    if dates is None:
        dates = bar_dates(bars)
    if any(b < a for a, b in zip(dates, dates[1:])):
        # Backtest sorts an unsorted index (with a warning); the signal series
        # would then be for a different bar order. The tuner's bars are sorted.
        raise ValueError("simulate_trades needs bars in ascending date order")

    equity = [_CASH] * n_bars
    cash = _CASH
    pending: tuple[str, float, float, float] | None = None   # (side, limit, sl, tp) for the next bar
    pending_market: SignalPoint | None = None
    trade: dict | None = None
    out: list[TradeRecord] = []

    def _close(price: float, i: int) -> None:
        nonlocal cash, trade
        size, entry = trade["size"], trade["entry_price"]
        exit_commission = abs(size) * price * commission
        cash += size * (price - entry) - exit_commission
        commissions = exit_commission + abs(size) * entry * commission
        pl_pct = copysign(1, size) * (price / entry - 1) - commissions / (abs(size) * entry)
        if trade["time_closed"]:
            reason = "time"
        else:
            sl = trade["signal_stop"]
            hit_stop = price <= sl if direction == "Bullish" else price >= sl
            reason = "stop" if hit_stop else "target"
        out.append(TradeRecord(
            entry_date=dates[trade["entry_bar"]], exit_date=dates[i],
            entry_price=entry, exit_price=price,
            net_return_pct=pl_pct * 100.0, exit_reason=reason,
            size=size,
        ))
        trade = None

    for i in range(1, n_bars):
        o, h, lo, c = opens[i], highs[i], lows[i], closes[i]
        # ── broker: orders fill at bar i ──
        if trade is not None:
            long = trade["size"] > 0
            if trade["close_order"]:
                _close(o, i)
            elif trade["sl"] and ((lo <= trade["sl"]) if long else (h >= trade["sl"])):
                _close(min(o, trade["sl"]) if long else max(o, trade["sl"]), i)
            elif trade["tp"] and ((h >= trade["tp"]) if long else (lo <= trade["tp"])):
                _close(max(o, trade["tp"]) if long else min(o, trade["tp"]), i)
        elif pending is not None:
            side, limit, sl, tp = pending
            is_long = side == "buy"
            market = pending_market is not None
            if market or ((lo <= limit) if is_long else (h >= limit)):
                price = o if market else (min(o, limit) if is_long else max(o, limit))
                valid_market = True
                if market:
                    rr = pending_market.rr_multiple
                    if rr is not None:
                        valid_market = math.isfinite(rr) and rr > 0
                        if valid_market:
                            tp = price + (1 if is_long else -1) * rr * abs(price - sl)
                    valid_market = (valid_market and all(math.isfinite(v) and v > 0 for v in (price, sl, tp))
                                    and _entry_side(direction, entry=price, sl=sl, tp=tp) is not None)
                order_size = _FULL_EQUITY if is_long else -_FULL_EQUITY
                adjusted = price * (1 + copysign(0.0, order_size))
                plus_commission = adjusted + (abs(order_size) * price * commission) / abs(order_size)
                units = copysign(int((cash * 1.0 * abs(order_size)) // plus_commission), order_size) if valid_market else 0
                if units and not abs(units) * plus_commission > cash:
                    if not (_contingent_ok(sl) and _contingent_ok(tp)):
                        # Trade.sl/tp assert -> the backtest run fails -> empty result.
                        return SimulatedTrades()
                    size = int(units)
                    cash -= abs(size) * price * commission
                    trade = {"size": size, "entry_price": adjusted, "entry_bar": i,
                             "sl": sl or None, "tp": tp or None, "signal_stop": sl,
                             "close_order": False, "time_closed": False}
                    if market:
                        if (lo <= sl) if is_long else (h >= sl):
                            _close(min(o, sl) if is_long else max(o, sl), i)
                        elif (h >= tp) if is_long else (lo <= tp):
                            _close(max(o, tp) if is_long else min(o, tp), i)
        pending_market = None
        pending = None   # a DAY order: filled or gone
        # ── broker: out of money (equity <= 0) closes at the close and stops ──
        if trade is not None:
            size = trade["size"]
            if cash + (c * size - size * trade["entry_price"]) <= 0:
                _close(c, i)
                equity[i:] = [0.] * (n_bars-i)
                return SimulatedTrades(out, 0, equity)
        equity[i] = cash + (trade["size"] * (c - trade["entry_price"]) if trade is not None else 0.)
        # ── strategy.next() at bar i's close ──
        if i + 1 < MIN_SIGNAL_BARS:
            continue
        if hold_max_days is not None and trade is not None and not trade["time_closed"]:
            if (dates[i] - dates[trade["entry_bar"]]).days >= hold_max_days:
                trade["time_closed"] = True
                trade["close_order"] = True
        if entry_start is not None and dates[i] < entry_start:
            continue
        if entry_end is not None and dates[i] >= entry_end:
            continue
        if trade is None:
            sig = signals[i]
            if sig is None or (allowed is not None and not allowed[i]):
                continue
            if sig.market:
                from app.services.setup_entries import event_allowed
                if not event_allowed(sig, i, dates, allowed=allowed, entry_start=entry_start, entry_end=entry_end):
                    continue
                side = "buy" if direction == "Bullish" else "sell"
                pending_market = sig
            else:
                side = _entry_side(direction, entry=sig.entry, sl=sig.stop, tp=sig.target)
            if side is not None:
                pending = (side, sig.entry, sig.stop, sig.target)

    return SimulatedTrades(out, 1 if trade is not None else 0, equity)
