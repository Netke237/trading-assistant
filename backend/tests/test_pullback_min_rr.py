"""Fix #6: SPY pullback_ema median planned R/R was 0.11; 95% of signals < 1:1."""
import json
from pathlib import Path

from app.services.strategy_engine import pullback_ema_signal
from app.services.strategy_param_store import get_exit

BARS = json.loads((Path(__file__).parent / "fixtures" / "SPY_candles.json").read_text())
P = dict(ema_period=50, trend_ema=100, atr_stop_mult=1.5, rr_target_mult=2.0,
         tolerance=0.04, exit_swing_lookback=20)


def _signals(**extra):
    out = []
    for n in range(120, len(BARS) + 1):
        s = pullback_ema_signal(BARS[:n], direction="Bullish", **P, **extra)
        if s is not None:
            out.append(s)
    return out


def _rr(s):
    return abs(s.target_price - s.entry_price) / abs(s.entry_price - s.stop_price)


def test_default_still_emits_sub_1r_signals():
    """The floor is opt-in: with no min_signal_rr the engine's behaviour is
    unchanged, i.e. it still emits signals whose first target is under 1R."""
    base = _signals()
    assert any(_rr(s) < 1.0 for s in base)


def test_floor_drops_sub_1r_signals():
    base, floored = _signals(), _signals(min_signal_rr=1.0)
    assert len(floored) < len(base)
    assert all(_rr(s) >= 1.0 - 1e-9 for s in floored)


def test_floor_skips_never_clamps():
    """D7: a floored signal is a subset of the unfloored ones, byte-identical
    (no target was rewritten to reach the floor)."""
    base = {(s.entry_price, s.stop_price, s.target_price) for s in _signals()}
    floored = {(s.entry_price, s.stop_price, s.target_price)
               for s in _signals(min_signal_rr=1.0)}
    assert floored <= base


def test_yaml_exit_block_carries_the_floor():
    """exit: is merged by run_strategy_backtest, the live scan and the watch
    evaluator, and adopt() never touches it."""
    assert get_exit("pullback_ema")["min_signal_rr"] == 1.0


def test_floor_reaches_scan_merge_and_only_pullback_ema():
    """The live scan merges exit: via _merge_strategy_params; the key is
    pullback_ema-only, so no other signal function receives the new kwarg."""
    from app.routers.stock_scan import _merge_strategy_params, _SIGNAL_FNS

    for d in ("Bullish", "Bearish"):
        assert _merge_strategy_params("pullback_ema", d, {})["min_signal_rr"] == 1.0
    for k in _SIGNAL_FNS:
        if k != "pullback_ema":
            assert "min_signal_rr" not in get_exit(k)
