import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.strategy_backtest import _entry_side

def test_entry_side_bullish_admits_stop_below_target_above():
    assert _entry_side("Bullish", entry=100, sl=95, tp=110) == "buy"
    assert _entry_side("Bullish", entry=100, sl=105, tp=110) is None  # stop on wrong side

def test_entry_side_bearish_admits_stop_above_target_below():
    assert _entry_side("Bearish", entry=100, sl=105, tp=90) == "sell"
    assert _entry_side("Bearish", entry=100, sl=95, tp=90) is None    # stop on wrong side


from app.services.strategy_backtest import run_strategy_backtest

def test_bearish_backtest_runs_and_tags_direction():
    # import the death-cross fixture from C3
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from test_strategy_engine_bearish import _death_cross_bars
    bars = []
    for _ in range(6):
        for b in _death_cross_bars():
            nb = dict(b); nb["time"] = len(bars); bars.append(nb)
    res = run_strategy_backtest(bars, strategy="ma_crossover",
                                direction="Bearish", min_trades=0, min_win_rate=0.0)
    assert res.direction == "Bearish"
