"""Fix #2: on trading-day bars a 3-month test fold is ~62 bars, under the
100-bar engine minimum, so every OOS fold was skipped."""
from datetime import date, timedelta

from app.services.walk_forward import (
    build_folds, precompute_bar_dates, slice_with_warmup, WARMUP_BARS, MIN_SCORED_BARS,
)


def _weekday_bars(years=3, start=date(2021, 1, 4)):
    bars, d, px, i = [], start, 100.0, 0
    end = start + timedelta(days=365 * years)
    while d < end:
        if d.weekday() < 5:
            px *= 1.0015 if i % 7 else 0.985
            bars.append({"time": d.isoformat(), "open": px * 0.998, "high": px * 1.01,
                         "low": px * 0.99, "close": px, "volume": 1_000_000})
            i += 1
        d += timedelta(days=1)
    precompute_bar_dates(bars)
    return bars


def test_trading_day_test_fold_is_short_but_scored_with_warmup():
    bars = _weekday_bars()
    folds = build_folds(bars[0]["_date"], bars[-1]["_date"], train_months=12, test_months=3)
    assert folds
    f = folds[1]
    window, scored = slice_with_warmup(bars, f.test_start, f.test_end)
    assert 55 <= scored <= 70              # the review's 61-62 bars
    assert scored >= MIN_SCORED_BARS
    assert len(window) == scored + WARMUP_BARS
    assert window[WARMUP_BARS]["_date"] >= f.test_start
    assert window[WARMUP_BARS - 1]["_date"] < f.test_start


def test_entry_start_blocks_entries_before_it(monkeypatch):
    """Strict: fails if entry_start is ignored. Spies on backtesting.Backtest.run
    (no production API change) to read the real trades' EntryTime."""
    import json
    from pathlib import Path

    import pandas as pd
    from backtesting import Backtest

    from app.services.strategy_backtest import run_strategy_backtest

    bars = json.loads((Path(__file__).parent / "fixtures" / "SPY_candles.json").read_text())
    cut = date.fromisoformat(str(bars[180]["time"])[:10])

    entry_times = []
    orig_run = Backtest.run

    def spy(self, *a, **kw):
        stats = orig_run(self, *a, **kw)
        entry_times.append(list(stats["_trades"]["EntryTime"]))
        return stats

    monkeypatch.setattr(Backtest, "run", spy)

    # min_signal_rr=0.0 opts out of the YAML's 1R floor (review fix #6): this test
    # needs the pre-floor trade set, since the floor removes the pre-`cut` entry.
    nofloor = {"min_signal_rr": 0.0}
    full = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish",
                                 params=nofloor)
    late = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish",
                                 params=nofloor, entry_start=cut)

    full_entries, late_entries = entry_times
    # Without the cutoff the strategy does trade before `cut` ...
    assert any(t < pd.Timestamp(cut) for t in full_entries)
    # ... with it, no entry is placed before `cut`.
    assert late_entries and all(t >= pd.Timestamp(cut) for t in late_entries)
    assert late.n_trades < full.n_trades


def test_entry_start_with_tz_aware_bar_times():
    """A naive cutoff compared with a tz-aware equity index raised TypeError."""
    import json
    from pathlib import Path

    from app.services.strategy_backtest import run_strategy_backtest

    bars = json.loads((Path(__file__).parent / "fixtures" / "SPY_candles.json").read_text())
    tz_bars = [{**b, "time": str(b["time"])[:10] + "T00:00:00+00:00"} for b in bars]
    cut = date.fromisoformat(str(bars[180]["time"])[:10])
    res = run_strategy_backtest(tz_bars, strategy="pullback_ema", direction="Bullish", entry_start=cut)
    assert res.summary_text != "entry_start needs dated bars"
    assert "tz" not in res.summary_text.lower() and "compare" not in res.summary_text.lower()
    assert res.n_trades > 0


def test_oos_backtest_runs_on_trading_day_folds(monkeypatch):
    """Before the fix the OOS call count was 0 on trading-day bars."""
    from app.services.strategy_backtest import BacktestResult
    from app.services.strategy_param_optimizer import _optimize_strategy_sync
    import app.services.walk_forward as wf
    import app.services.strategy_backtest as sb

    calls = []

    def fake(bars, *, strategy, direction, params=None, entry_start=None, **kw):
        calls.append((len(bars), entry_start))
        return BacktestResult(strategy=strategy, direction=direction, n_trades=3, win_rate=0.6,
                              total_return_pct=1.0, max_drawdown_pct=-1.0, expectancy=0.3,
                              sharpe=0.8, confidence=None, passes_gate=False, summary_text="")

    monkeypatch.setattr(wf, "run_strategy_backtest", fake)
    monkeypatch.setattr(sb, "run_strategy_backtest", fake)
    bars = _weekday_bars()
    folds = build_folds(bars[0]["_date"], bars[-1]["_date"], train_months=12, test_months=3)
    _optimize_strategy_sync("pullback_ema", "Bullish", {"SPY": bars}, folds,
                            {"ema_period": [20]}, {"fee_pct": 0.001, "slippage_pct": 0.001},
                            min_trades=1, min_consistency=0.0)
    # Length filter: a rolling train fold's train_start equals the test_start of
    # fold k-4, so TRAIN calls can match too; a test window is <= warm-up + 100
    # bars while any train window is >= 252 + 252.
    test_starts = {f.test_start for f in folds}
    oos = [c for c in calls
           if c[0] <= WARMUP_BARS + 100 and c[1] is not None and c[1] in test_starts]
    assert len(oos) == len(folds)
