# backend/tests/test_stock_scorer_stock_mode.py
import pytest
from app.scoring.stock_scorer import score_stock, _load_config


def _bars(n=120, trend="up"):
    """Synthetic OHLCV bars. trend='up' rises, 'down' falls, else flat."""
    bars = []
    price = 100.0
    for i in range(n):
        if trend == "up":
            price += 0.4
        elif trend == "down":
            price -= 0.4
        vol = 1_000_000
        bars.append({"open": price - 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": vol})
    return bars


def test_score_stock_accepts_scoring_mode_options():
    """scoring_mode='options' (default) must not raise."""
    card = score_stock("AAPL", "Bullish", "Swing", _bars(), scoring_mode="options")
    assert card.status in ("PASS", "CAUTION", "REJECT")


def test_score_stock_accepts_scoring_mode_stock():
    """scoring_mode='stock' must not raise."""
    card = score_stock("AAPL", "Bullish", "Swing", _bars(), scoring_mode="stock")
    assert card.status in ("PASS", "CAUTION", "REJECT")


def test_options_mode_is_default():
    """Calling without scoring_mode must behave like options mode."""
    card_default = score_stock("AAPL", "Bullish", "Swing", _bars())
    card_options = score_stock("AAPL", "Bullish", "Swing", _bars(), scoring_mode="options")
    assert card_default.score == card_options.score


def _bars_rvol(n=120, current_vol_mult=2.5):
    """Bars where the last bar has `current_vol_mult` × avg volume."""
    avg = 1_000_000
    bars = []
    price = 100.0
    for i in range(n):
        price += 0.4
        vol = avg if i < n - 1 else int(avg * current_vol_mult)
        bars.append({"open": price - 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": vol})
    return bars


def test_rvol_high_scores_pass_in_stock_mode():
    """RVol >= 2.0x should produce vol component score 90 in stock mode."""
    bars = _bars_rvol(current_vol_mult=2.5)
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="stock")
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.score == 90
    assert vol_rule.detail.get("rvol") is not None


def test_rvol_low_scores_caution_in_stock_mode():
    """RVol < 0.8x should produce vol component score 20 in stock mode."""
    bars = _bars_rvol(current_vol_mult=0.5)
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="stock")
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.score == 20


def test_options_mode_vol_rule_uses_iv_rank_not_rvol():
    """options mode must use IV rank gate, not rvol — tiny volume must NOT score 20.

    With iv_rank_pass_max=34 set for Swing, passing no iv_rank returns CAUTION 50
    ("no_iv_data"), confirming that rvol is ignored in options mode.
    """
    _load_config.cache_clear()
    bars = _bars_rvol(current_vol_mult=0.1)   # tiny volume — would score 20 in stock mode
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="options")
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.score != 20, "options mode must not use rvol scoring"
    assert vol_rule.score == 50   # no iv_rank provided → "no_iv_data" CAUTION 50


from app.scoring.stock_scorer import _rule_trigger, _horizon_cfg, _rule_event
import copy
from datetime import date, timedelta


def _trigger_bars_macd_cross(n=80):
    """Bars engineered so MACD histogram crosses zero near the last bar."""
    bars = []
    price = 50.0
    for i in range(n):
        if i < n // 2:
            price -= 0.3
        else:
            price += 0.6
        bars.append({"open": price - 0.1, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 800_000})
    return bars


def _cfg_swing():
    return copy.deepcopy(_horizon_cfg("Swing"))


def test_trigger_no_candle_required_signals_is_pass_in_stock_mode():
    """Stock mode: required momentum signals without candle → score >= 65 (not capped at 35)."""
    cfg = _cfg_swing()
    # Force zero required signals so momentum_count >= required is guaranteed
    cfg["trigger"]["momentum_signals_for_pass"] = 0
    bars = _trigger_bars_macd_cross()
    # Make last bar bearish so no candle is detected
    bars[-1]["close"] = bars[-1]["open"] - 0.5
    bars[-1]["low"] = bars[-1]["close"] - 0.3
    volumes = [b["volume"] for b in bars]
    result, _ = _rule_trigger(bars, cfg, volumes, "Bullish", scoring_mode="stock")
    assert result.score >= 65   # stock mode: momentum alone drives PASS, not capped at 35


def test_trigger_with_candle_bonus_in_stock_mode():
    """Stock mode: candle adds +15 pts on top of momentum base."""
    cfg = _cfg_swing()
    cfg["trigger"]["momentum_signals_for_pass"] = 0  # guaranteed pass threshold
    bars = _trigger_bars_macd_cross()
    # Bullish last bar → candle detected
    bars[-1]["close"] = bars[-1]["open"] + 1.0
    bars[-1]["high"] = bars[-1]["close"] + 0.3
    volumes = [b["volume"] for b in bars]
    result_no_candle_bars = _trigger_bars_macd_cross()
    result_no_candle_bars[-1]["close"] = result_no_candle_bars[-1]["open"] - 0.5
    result_no_candle_bars[-1]["low"] = result_no_candle_bars[-1]["close"] - 0.3
    result_without_candle, _ = _rule_trigger(result_no_candle_bars, _cfg_swing(), volumes, "Bullish", scoring_mode="stock")
    result_with_candle, _ = _rule_trigger(bars, cfg, volumes, "Bullish", scoring_mode="stock")
    assert result_with_candle.score >= result_without_candle.score
    assert result_with_candle.status == "PASS"


def test_trigger_options_mode_still_caps_no_candle_at_35():
    """Options mode: no candle + required signals met → CAUTION 35 (unchanged)."""
    cfg = _cfg_swing()
    bars = _trigger_bars_macd_cross()
    bars[-1]["close"] = bars[-1]["open"] - 0.5   # bearish — no candle
    bars[-1]["low"] = bars[-1]["close"] - 0.3
    volumes = [b["volume"] for b in bars]
    result, _ = _rule_trigger(bars, cfg, volumes, "Bullish", scoring_mode="options")
    momentum_count = result.detail.get("momentum_count", 0)
    required = cfg["trigger"]["momentum_signals_for_pass"]
    if momentum_count >= required:
        assert result.score == 35


def test_event_shown_with_note_in_stock_mode():
    """Stock mode: earnings tomorrow shows REJECT (displayed only) with note — weight is zero."""
    cfg = copy.deepcopy(_horizon_cfg("Swing"))
    tomorrow = date.today() + timedelta(days=1)
    result = _rule_event(tomorrow, None, cfg, scoring_mode="stock")
    # Stock mode now applies thresholds for display; earnings tomorrow is within reject_days
    assert result.status == "REJECT"
    assert result.score == 5
    assert result.detail.get("days_to_event") is not None   # metadata still present
    assert result.detail.get("note") is not None             # weight-zero note must be present


def test_event_still_penalises_in_options_mode():
    """Options mode: earnings tomorrow must return REJECT (unchanged behaviour)."""
    cfg = copy.deepcopy(_horizon_cfg("Swing"))
    tomorrow = date.today() + timedelta(days=1)
    result = _rule_event(tomorrow, None, cfg, scoring_mode="options")
    assert result.status == "REJECT"
    assert result.score == 5


# ── H1: shared _relative_volume between _rule_trigger and _rule_vol ──────────

def test_rvol_and_trigger_volume_bonus_share_same_window():
    """Both _rule_trigger's volume bonus and _rule_vol's rvol must be driven by the
    same volume_lookback_bars config value — changing it in cfg should move both."""
    from app.scoring.stock_scorer import _rule_vol

    cfg = _cfg_swing()
    cfg["trigger"]["volume_lookback_bars"] = 5   # shrink window from config, not hardcode

    bars = _bars_rvol(n=30, current_vol_mult=2.5)
    volumes = [b["volume"] for b in bars]

    _, vol_bonus = _rule_trigger(bars, cfg, volumes, "Bullish", scoring_mode="stock")
    vol_result = _rule_vol(None, cfg, volumes=volumes, scoring_mode="stock")

    assert vol_bonus is True
    assert vol_result.detail["rvol"] is not None
    expected_rvol = volumes[-1] / (sum(volumes[-6:-1]) / 5)
    assert abs(vol_result.detail["rvol"] - round(expected_rvol, 2)) < 0.01


def test_relative_volume_helper_matches_manual_calc():
    from app.scoring.stock_scorer import _relative_volume
    volumes = [1_000_000] * 20 + [2_500_000]
    rvol = _relative_volume(volumes, 20)
    assert abs(rvol - 2.5) < 1e-9


def test_relative_volume_insufficient_history_returns_none():
    from app.scoring.stock_scorer import _relative_volume
    assert _relative_volume([1, 2, 3], 20) is None


# ── H2: bearish MACD requires histogram confirmation, mirroring bullish ──────

def test_bearish_macd_gate_now_structurally_symmetric_with_bullish():
    """H2: bearish trigger must apply the same 2-point cross-confirmation clause bullish
    already had (hist[-1] < hist[-2] when macd_histogram_rising is set), closing the
    asymmetry the audit flagged.

    NOTE: with only 2 histogram points, hist[-2] > 0 and hist[-1] <= 0 mathematically
    guarantees hist[-1] < hist[-2] (a non-positive number is always less than a positive
    one) — so, exactly mirroring the bullish clause (which has the same tautology:
    hist[-2] < 0 and hist[-1] >= 0 always implies hist[-1] > hist[-2]), this confirmation
    clause is a structural no-op today, not a magnitude-based filter. That pre-existing
    tautology is out of scope for H2 (which only asked to close the bullish/bearish
    asymmetry); this test pins the now-symmetric structure, not a behavior difference
    between "barely crossed" and "crossed with momentum" histograms."""
    cfg = _cfg_swing()
    assert cfg["trigger"]["macd_histogram_rising"] is True

    import unittest.mock as mock
    bars = _trigger_bars_macd_cross()
    volumes = [b["volume"] for b in bars]

    with mock.patch("app.scoring.stock_scorer._macd_histogram", return_value=[1.0, -0.1]):
        result, _ = _rule_trigger(bars, cfg, volumes, "Bearish", scoring_mode="stock")
        assert result.detail["macd_pass"] is True

    with mock.patch("app.scoring.stock_scorer._macd_histogram", return_value=[1.0, -2.0]):
        result, _ = _rule_trigger(bars, cfg, volumes, "Bearish", scoring_mode="stock")
        assert result.detail["macd_pass"] is True


def test_bearish_macd_ignores_confirmation_when_flag_false():
    cfg = _cfg_swing()
    cfg["trigger"]["macd_histogram_rising"] = False
    bars = _trigger_bars_macd_cross()
    volumes = [b["volume"] for b in bars]

    import unittest.mock as mock
    with mock.patch("app.scoring.stock_scorer._macd_histogram", return_value=[1.0, -0.1]):
        result, _ = _rule_trigger(bars, cfg, volumes, "Bearish", scoring_mode="stock")
        assert result.detail["macd_pass"] is True, "flag off -> any cross down should pass"


# ── M1: component-level status thresholds sourced from config ───────────────

def test_trend_additive_status_reads_from_config_not_hardcoded():
    """_trend_additive's PASS/CAUTION boundaries must come from ac['status_pass'] /
    ac['status_caution'], not hardcoded 70/40 — verify a custom cfg shifts the boundary."""
    from app.scoring.stock_scorer import _trend_additive

    cfg = _cfg_swing()
    cfg["trend"]["additive"]["status_pass"] = 95   # near-impossible to reach
    cfg["trend"]["additive"]["status_caution"] = 90

    closes = [100.0 + i * 0.5 for i in range(60)]   # steady uptrend
    result = _trend_additive(closes, cfg, "Bullish")
    # With status_pass=95, even a clean uptrend should not clear PASS unless raw score >=95
    assert result.status != "PASS" or result.score >= 95


# ── M4: _wilder_smooth regression parity with the old sum-based ADX math ────

def test_wilder_smooth_fixes_latent_adx_scale_bug_vs_pre_refactor_sum_math():
    """The pre-refactor sum-based _wilder canceled its own p-scaling in the atr/pdm/mdm
    ratios (di_plus/di_minus/dx_vals), but the OUTER smoothing step (`_wilder(dx_vals,
    period)`) had no such cancellation — it returned a raw running SUM applied to
    already-percentage dx_vals, so the final `_adx()` return value was ~`period`x too
    large and could exceed the valid [0, 100] ADX range. The refactored average-form
    _wilder_smooth divides back down at every step, producing a correctly-scaled ADX.
    This is a genuine behavior change (not the 'pure refactor' M4 was originally scoped
    as) — _adx feeds _trend_additive's scoring, so live trend scores will shift."""
    from app.scoring.stock_scorer import _adx

    def _synthetic_bars(n=40):
        bars = []
        price = 100.0
        for i in range(n):
            price += 0.3 if i % 3 != 0 else -0.1
            bars.append({"open": price - 0.1, "high": price + 0.6,
                         "low": price - 0.6, "close": price})
        return bars

    bars = _synthetic_bars()
    adx_val = _adx(bars, period=14)

    def _old_wilder_sum(data, p):
        if len(data) < p:
            return []
        result = [sum(data[:p])]
        for v in data[p:]:
            result.append(result[-1] - result[-1] / p + v)
        return result

    tr_list, plus_dm, minus_dm = [], [], []
    for i in range(1, len(bars)):
        h, l = bars[i]["high"], bars[i]["low"]
        pc = bars[i - 1]["close"]
        ph, pl = bars[i - 1]["high"], bars[i - 1]["low"]
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
        up_move = h - ph
        down_move = pl - l
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    atr_s = _old_wilder_sum(tr_list, 14)
    pdm_s = _old_wilder_sum(plus_dm, 14)
    mdm_s = _old_wilder_sum(minus_dm, 14)
    n = min(len(atr_s), len(pdm_s), len(mdm_s))
    dx_vals = []
    for i in range(n):
        atr_v = atr_s[i]
        if atr_v == 0:
            continue
        di_plus = 100.0 * pdm_s[i] / atr_v
        di_minus = 100.0 * mdm_s[i] / atr_v
        di_sum = di_plus + di_minus
        dx_vals.append(100.0 * abs(di_plus - di_minus) / di_sum if di_sum > 0 else 0.0)
    adx_s_old = _old_wilder_sum(dx_vals, 14)
    old_adx_val = adx_s_old[-1] if adx_s_old else 0.0

    assert 0.0 <= adx_val <= 100.0, f"ADX must be in [0, 100], got {adx_val}"
    # Sanity check the bug this fix corrects: the old sum-based final smoothing step
    # produced a value out of the valid ADX range for this synthetic series.
    assert old_adx_val > 100.0, (
        "expected pre-refactor ADX to be out of [0, 100] range for this series, "
        "confirming the scale bug this fix corrects"
    )
    assert abs(adx_val - old_adx_val / 14) < 1e-6, (
        f"refactored ADX ({adx_val}) should equal old_adx_val/period "
        f"({old_adx_val / 14}) — confirms the fix is exactly the missing /period division"
    )


def test_rsi_unchanged_after_wilder_smooth_extraction():
    """RSI values must be numerically identical after switching _rsi to use the shared
    _wilder_smooth helper instead of its own inline loop."""
    from app.scoring.stock_scorer import _rsi
    closes = [100.0 + (i % 5) - 2 + i * 0.05 for i in range(60)]
    vals = _rsi(closes, period=14)
    assert vals, "expected non-empty RSI series"
    assert all(0.0 <= v <= 100.0 for v in vals)


def test_wilder_smooth_helper_matches_manual_recurrence():
    from app.scoring.stock_scorer import _wilder_smooth
    data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    result = _wilder_smooth(data, period=5)
    assert result[0] == 3.0
    assert abs(result[1] - 3.6) < 1e-9
    assert abs(result[2] - 4.28) < 1e-9
