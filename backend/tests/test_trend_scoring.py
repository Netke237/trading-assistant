"""Unit tests for all three trend scoring methods: additive, crossover, relative_strength."""
from __future__ import annotations

import random

from app.scoring.stock_scorer import score_stock


# ---------------------------------------------------------------------------
# Bar / close data generators
# ---------------------------------------------------------------------------

def _make_bars(n: int = 60, trend: str = "up", seed: int = 42) -> list[dict]:
    """Generate OHLCV bars. trend: 'up' | 'down' | 'flat'."""
    random.seed(seed)
    price = 100.0
    bars = []
    for _ in range(n):
        if trend == "up":
            price *= 1 + random.uniform(0.003, 0.010)
        elif trend == "down":
            price *= 1 - random.uniform(0.003, 0.010)
        else:
            price *= 1 + random.uniform(-0.003, 0.003)
        o = price * (1 + random.uniform(-0.002, 0.002))
        c = price
        h = max(o, c) * (1 + random.uniform(0, 0.005))
        l = min(o, c) * (1 - random.uniform(0, 0.005))
        bars.append({"open": o, "high": h, "low": l, "close": c, "volume": 1_000_000})
    return bars


def _make_closes(n: int, start: float, drift_per_bar: float) -> list[float]:
    """Geometric close series: start * (1 + drift)^i for i in range(n)."""
    return [start * (1 + drift_per_bar) ** i for i in range(n)]


def _closes_to_bars(closes: list[float]) -> list[dict]:
    """Wrap a close series into minimal OHLCV dicts (flat O/H/L around close)."""
    bars = []
    for c in closes:
        bars.append({"open": c, "high": c * 1.001, "low": c * 0.999, "close": c, "volume": 1_000_000})
    return bars


# ---------------------------------------------------------------------------
# Additive method tests
# ---------------------------------------------------------------------------

def test_additive_uptrend_bullish_scores_high():
    """Clear uptrend bars: Bullish additive score should be >= 70 (PASS)."""
    bars = _make_bars(n=60, trend="up")
    card = score_stock(
        "TEST", "Bullish", "Swing", bars,
        overrides={"trend_method": "additive"},
    )
    trend = card.rules[0]
    assert trend.name == "trend"
    assert trend.detail["method"] == "additive"
    assert trend.score >= 70, f"Expected score >= 70, got {trend.score}"
    assert trend.status == "PASS"


def test_additive_downtrend_bullish_scores_low():
    """Clear downtrend bars: Bullish additive score should be <= 40."""
    bars = _make_bars(n=60, trend="down")
    card = score_stock(
        "TEST", "Bullish", "Swing", bars,
        overrides={"trend_method": "additive"},
    )
    trend = card.rules[0]
    assert trend.detail["method"] == "additive"
    assert trend.score <= 40, f"Expected score <= 40, got {trend.score}"


def test_additive_bullish_vs_bearish_direction_inverts():
    """Same downtrend candles: Bearish direction should score higher than Bullish."""
    bars = _make_bars(n=60, trend="down")
    card_bullish = score_stock(
        "TEST", "Bullish", "Swing", bars,
        overrides={"trend_method": "additive"},
    )
    card_bearish = score_stock(
        "TEST", "Bearish", "Swing", bars,
        overrides={"trend_method": "additive"},
    )
    trend_bull = card_bullish.rules[0]
    trend_bear = card_bearish.rules[0]
    assert trend_bear.score > trend_bull.score, (
        f"Bearish score ({trend_bear.score}) should be > Bullish score ({trend_bull.score}) on downtrend"
    )


def test_additive_weights_all_in_price():
    """With price_max=100, slope_max=0, adx_max=0: score should be 100 on uptrend, 0 on downtrend."""
    up_bars = _make_bars(n=60, trend="up")
    down_bars = _make_bars(n=60, trend="down")

    pure_price_overrides = {
        "trend_method": "additive",
        "additive_price_max": 100,
        "additive_slope_max": 0,
        "additive_adx_max": 0,
    }

    card_up = score_stock("TEST", "Bullish", "Swing", up_bars, overrides=pure_price_overrides)
    card_down = score_stock("TEST", "Bullish", "Swing", down_bars, overrides=pure_price_overrides)

    trend_up = card_up.rules[0]
    trend_down = card_down.rules[0]

    assert trend_up.score == 100, f"Expected 100 for price above MA, got {trend_up.score}"
    assert trend_down.score == 0, f"Expected 0 for price below MA, got {trend_down.score}"


def test_additive_custom_weight_split_stays_in_range():
    """Non-default weight splits (price_max=50, slope_max=25, adx_max=25) produce valid 0-100 scores."""
    bars = _make_bars(n=60, trend="up")
    card = score_stock(
        "TEST", "Bullish", "Swing", bars,
        overrides={
            "trend_method": "additive",
            "additive_price_max": 50,
            "additive_slope_max": 25,
            "additive_adx_max": 25,
        },
    )
    trend = card.rules[0]
    assert 0 <= trend.score <= 100, f"Score out of range: {trend.score}"


# ---------------------------------------------------------------------------
# Crossover method tests
# ---------------------------------------------------------------------------

def test_crossover_fast_above_slow_rising_gives_pass():
    """250+ bars of uptrend: Bullish crossover should yield PASS and score 90."""
    # Swing uses fast_ema=50, slow_ema=200 — need 260+ bars
    bars = _make_bars(n=260, trend="up")
    card = score_stock(
        "TEST", "Bullish", "Swing", bars,
        overrides={"trend_method": "crossover"},
    )
    trend = card.rules[0]
    assert trend.detail["method"] == "crossover"
    assert trend.status == "PASS", f"Expected PASS, got {trend.status}"
    assert trend.score == 90, f"Expected score 90, got {trend.score}"


def test_crossover_fast_below_slow_gives_reject():
    """250+ bars of downtrend: Bullish crossover should yield REJECT and score 10."""
    bars = _make_bars(n=260, trend="down")
    card = score_stock(
        "TEST", "Bullish", "Swing", bars,
        overrides={"trend_method": "crossover"},
    )
    trend = card.rules[0]
    assert trend.detail["method"] == "crossover"
    assert trend.status == "REJECT", f"Expected REJECT, got {trend.status}"
    assert trend.score == 10, f"Expected score 10, got {trend.score}"


def test_crossover_produces_discrete_scores():
    """Crossover scores should be one of the discrete values: 0, 10, 20, 60, or 90."""
    allowed = {0, 10, 20, 60, 90}
    for trend_dir in ("up", "down", "flat"):
        bars = _make_bars(n=260, trend=trend_dir)
        for direction in ("Bullish", "Bearish"):
            card = score_stock(
                "TEST", direction, "Swing", bars,
                overrides={"trend_method": "crossover"},
            )
            trend = card.rules[0]
            assert trend.score in allowed, (
                f"Crossover produced non-discrete score {trend.score} "
                f"(trend={trend_dir}, direction={direction})"
            )


# ---------------------------------------------------------------------------
# Relative strength method tests
# ---------------------------------------------------------------------------

def test_rs_outperforms_benchmark_gives_pass():
    """Stock rising faster than benchmark: expect PASS and score 90."""
    # Stock: +0.5% per bar over 25 bars; benchmark: +0.05% per bar
    # rs_period for Swing = 20; need > 20 closes
    n = 25
    stock_closes = _make_closes(n, start=100.0, drift_per_bar=0.005)
    bench_closes = _make_closes(n, start=100.0, drift_per_bar=0.0005)
    stock_bars = _closes_to_bars(stock_closes)
    bench_bars = _closes_to_bars(bench_closes)

    card = score_stock(
        "TEST", "Bullish", "Swing", stock_bars,
        overrides={"trend_method": "relative_strength"},
        benchmark_candles=bench_bars,
    )
    trend = card.rules[0]
    assert trend.detail["method"] == "relative_strength"
    assert trend.status == "PASS", f"Expected PASS, got {trend.status} (rs={trend.detail.get('rs')})"
    assert trend.score == 90, f"Expected score 90, got {trend.score}"


def test_rs_matches_benchmark_gives_caution():
    """Stock and benchmark with identical drift: RS == 0, should yield CAUTION."""
    n = 25
    drift = 0.001
    stock_closes = _make_closes(n, start=100.0, drift_per_bar=drift)
    bench_closes = _make_closes(n, start=100.0, drift_per_bar=drift)
    stock_bars = _closes_to_bars(stock_closes)
    bench_bars = _closes_to_bars(bench_closes)

    card = score_stock(
        "TEST", "Bullish", "Swing", stock_bars,
        overrides={"trend_method": "relative_strength"},
        benchmark_candles=bench_bars,
    )
    trend = card.rules[0]
    assert trend.detail["method"] == "relative_strength"
    # RS = 0.0, which is between rs_caution_threshold (-1.0) and rs_pass_threshold (2.0)
    assert trend.status == "CAUTION", f"Expected CAUTION, got {trend.status} (rs={trend.detail.get('rs')})"


def test_rs_no_benchmark_data_gives_caution_fallback():
    """With benchmark_candles=None, relative_strength should return CAUTION with score 50."""
    bars = _make_bars(n=60, trend="up")
    card = score_stock(
        "TEST", "Bullish", "Swing", bars,
        overrides={"trend_method": "relative_strength"},
        benchmark_candles=None,
    )
    trend = card.rules[0]
    assert trend.detail["method"] == "relative_strength"
    assert trend.detail.get("reason") == "no_benchmark_data", (
        f"Expected reason 'no_benchmark_data', got {trend.detail.get('reason')}"
    )
    assert trend.status == "CAUTION", f"Expected CAUTION, got {trend.status}"
    assert trend.score == 50, f"Expected score 50, got {trend.score}"


def test_rs_bearish_direction_inverts():
    """Stock underperforming benchmark + Bearish direction: RS is negated → positive → PASS."""
    # Stock falls, benchmark rises → stock_roc < bench_roc → rs_raw < 0
    # Bearish: rs = -rs_raw → positive → should PASS
    n = 25
    stock_closes = _make_closes(n, start=100.0, drift_per_bar=-0.005)  # falling
    bench_closes = _make_closes(n, start=100.0, drift_per_bar=0.002)   # rising
    stock_bars = _closes_to_bars(stock_closes)
    bench_bars = _closes_to_bars(bench_closes)

    card = score_stock(
        "TEST", "Bearish", "Swing", stock_bars,
        overrides={"trend_method": "relative_strength"},
        benchmark_candles=bench_bars,
    )
    trend = card.rules[0]
    assert trend.detail["method"] == "relative_strength"
    assert trend.status == "PASS", f"Expected PASS for bearish underperformer, got {trend.status}"
    assert trend.score == 90, f"Expected score 90, got {trend.score}"


# ---------------------------------------------------------------------------
# Default method and distribution tests
# ---------------------------------------------------------------------------

def test_default_method_is_additive():
    """Calling score_stock without trend_method override should use the 'additive' method."""
    bars = _make_bars(n=60, trend="up")
    card = score_stock("TEST", "Bullish", "Swing", bars)
    trend = card.rules[0]
    assert trend.name == "trend"
    assert trend.detail.get("method") == "additive", (
        f"Expected default method 'additive', got '{trend.detail.get('method')}'"
    )


def test_additive_scores_distribute_across_range():
    """Uptrend, flat, and downtrend bars should not all produce the same additive trend score."""
    up_bars = _make_bars(n=60, trend="up", seed=1)
    flat_bars = _make_bars(n=60, trend="flat", seed=2)
    down_bars = _make_bars(n=60, trend="down", seed=3)

    overrides = {"trend_method": "additive"}

    up_score = score_stock("TEST", "Bullish", "Swing", up_bars, overrides=overrides).rules[0].score
    flat_score = score_stock("TEST", "Bullish", "Swing", flat_bars, overrides=overrides).rules[0].score
    down_score = score_stock("TEST", "Bullish", "Swing", down_bars, overrides=overrides).rules[0].score

    # Scores must not all collapse to the same value
    scores = {up_score, flat_score, down_score}
    assert len(scores) > 1, (
        f"Expected diverse scores across uptrend/flat/downtrend, "
        f"got up={up_score}, flat={flat_score}, down={down_score}"
    )
    # The clearest directional check: uptrend score must exceed downtrend score
    assert up_score > down_score, (
        f"Uptrend score ({up_score}) should exceed downtrend score ({down_score})"
    )
