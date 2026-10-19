import pytest
from unittest.mock import patch
from app.routers.regime import get_regime, _vix_percentile
from app.schemas import RegimeMetric


def _mock_regime_helpers(vix_quote: float | None, vix_closes: list[float]):
    """Context manager setting up patches for get_regime."""
    spx_metric = RegimeMetric(label="SPX trend (200 EMA)", value="Above", status="PASS", trend="up")
    ndx_metric = RegimeMetric(label="NDX trend (200 EMA)", value="Above", status="PASS", trend="up")

    def fake_fetch_candles(symbol: str, bars: int = 260):
        if symbol == 'VIX':
            return [{"close": c} for c in vix_closes]
        return []

    return (
        patch("app.routers.regime._spx_ndx_metric", side_effect=[spx_metric, ndx_metric]),
        patch("app.routers.regime.fetch_price", return_value=vix_quote),
        patch("app.routers.regime.fetch_candles", side_effect=fake_fetch_candles),
        patch("app.routers.regime.compute_omm", return_value=None),
        patch("app.routers.regime._compute_directional_hmm", return_value=None),
        patch("app.routers.regime.fetch_intraday_candles", return_value=[]),
        patch("app.routers.regime.compute_intraday_hmm", return_value=None),
    )


@pytest.mark.asyncio
async def test_get_regime_vix_percentile_252d_regression():
    """Step 1 reproduction:

    Freeze 260 VIX closes: 7 oldest at 1.0, next 252 at 100.0, current at 50.0.
    With current quote at 50.0:
    - 252 prior completed observations are all 100.0, none < 50.0 -> expected 252d rank 0.0%.
    - 30 prior completed observations are all 100.0, none < 50.0 -> expected 30d rank 0.0%.
    Pre-fix: 252d rank includes the 7 oldest bars of 1.0 (7 / 259 = 2.7%).
    """
    vix_closes = [1.0] * 7 + [100.0] * 252 + [50.0]
    assert len(vix_closes) == 260

    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(50.0, vix_closes)
    with p1, p2, p3, p4, p5, p6, p7:
        res = await get_regime()

    assert res.vix_pct_30d == 0.0
    assert res.vix_pct_252d == 0.0


@pytest.mark.asyncio
async def test_get_regime_vix_percentile_exactly_253_entries():
    """Exactly 253 entries: 252 prior completed bars + 1 current bar.

    Prior bars: values 1.0 .. 252.0.
    Current bar: 999.0.
    Quote: 126.5.
    Exactly 126 values (1.0..126.0) < 126.5 out of 252 prior entries -> 50.0%.
    30d window: last 30 prior entries (223.0..252.0), none < 126.5 -> 0.0%.
    """
    prior = [float(i) for i in range(1, 253)]  # 252 values: 1.0 to 252.0
    vix_closes = prior + [999.0]  # 253 entries
    assert len(vix_closes) == 253

    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(126.5, vix_closes)
    with p1, p2, p3, p4, p5, p6, p7:
        res = await get_regime()

    assert res.vix_pct_252d == 50.0
    assert res.vix_pct_30d == 0.0


@pytest.mark.asyncio
async def test_get_regime_vix_percentile_extra_old_outliers_and_ties():
    """Extra old outliers discarded and strict inequality for ties.

    300 closes:
    - 47 oldest: 0.0 (must be discarded by [-253:-1])
    - 252 prior: 100 at 10.0, 100 at 20.0, 52 at 30.0
    - 1 current: 999.0
    Quote: 20.0 (strict < excludes ties at 20.0).
    Count < 20.0 in 252 window: 100 (only the 10.0 bars).
    Percentile: round(100.0 * 100 / 252, 1) = 39.7%.
    30d window: last 30 prior bars are all 30.0 -> none < 20.0 -> 0.0%.
    """
    vix_closes = [0.0] * 47 + [10.0] * 100 + [20.0] * 100 + [30.0] * 52 + [999.0]
    assert len(vix_closes) == 300

    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(20.0, vix_closes)
    with p1, p2, p3, p4, p5, p6, p7:
        res = await get_regime()

    assert res.vix_pct_252d == 39.7
    assert res.vix_pct_30d == 0.0


@pytest.mark.asyncio
async def test_get_regime_vix_percentile_below_and_above_every_observation():
    """Values below and above all observations in the reference window.

    260 closes: 7 oldest at 5.0, 252 at 20.0, 1 current at 99.0.
    """
    vix_closes = [5.0] * 7 + [20.0] * 252 + [99.0]
    assert len(vix_closes) == 260

    # Below all 252 reference values
    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(15.0, vix_closes)
    with p1, p2, p3, p4, p5, p6, p7:
        res_below = await get_regime()
    assert res_below.vix_pct_252d == 0.0
    assert res_below.vix_pct_30d == 0.0

    # Above all 252 reference values
    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(25.0, vix_closes)
    with p1, p2, p3, p4, p5, p6, p7:
        res_above = await get_regime()
    assert res_above.vix_pct_252d == 100.0
    assert res_above.vix_pct_30d == 100.0


@pytest.mark.asyncio
async def test_get_regime_vix_percentile_fewer_than_253_entries():
    """Short history retains existing available-history convention.

    51 closes: 25 at 10.0, 25 at 30.0 (50 prior bars), 1 current at 99.0.
    Quote: 20.0.
    Available prior: 50 bars.
    25 values < 20.0 out of 50 -> 25 / 50 = 50.0%.
    30d window: last 30 prior bars (5 at 10.0, 25 at 30.0).
    5 values < 20.0 out of 30 -> round(100.0 * 5 / 30, 1) = 16.7%.
    """
    vix_closes = [10.0] * 25 + [30.0] * 25 + [99.0]
    assert len(vix_closes) == 51

    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(20.0, vix_closes)
    with p1, p2, p3, p4, p5, p6, p7:
        res = await get_regime()

    assert res.vix_pct_252d == 50.0
    assert res.vix_pct_30d == 16.7


@pytest.mark.asyncio
async def test_get_regime_vix_percentile_empty_and_single_entry():
    """Empty and single-entry history return None for percentiles."""
    # Empty history
    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(20.0, [])
    with p1, p2, p3, p4, p5, p6, p7:
        res_empty = await get_regime()
    assert res_empty.vix_pct_252d is None
    assert res_empty.vix_pct_30d is None

    # Single-entry history
    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(20.0, [20.0])
    with p1, p2, p3, p4, p5, p6, p7:
        res_single = await get_regime()
    assert res_single.vix_pct_252d is None
    assert res_single.vix_pct_30d is None

    # Quote is None
    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(None, [10.0, 20.0, 30.0])
    with p1, p2, p3, p4, p5, p6, p7:
        res_none_quote = await get_regime()
    assert res_none_quote.vix_pct_252d is None
    assert res_none_quote.vix_pct_30d is None


@pytest.mark.asyncio
async def test_get_regime_last_historical_entry_never_enters_windows():
    """Explicitly verify the last historical entry never enters either reference window.

    260 bars: 259 prior bars at 100.0, last bar at 1.0 (an outlier low).
    Quote: 50.0.
    If the last bar entered either window, count < 50.0 would be >= 1 (> 0.0%).
    Since the last bar is excluded, both ranks must be 0.0%.
    """
    vix_closes_260 = [100.0] * 259 + [1.0]
    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(50.0, vix_closes_260)
    with p1, p2, p3, p4, p5, p6, p7:
        res_260 = await get_regime()
    assert res_260.vix_pct_252d == 0.0
    assert res_260.vix_pct_30d == 0.0

    # Also with short history: 5 bars (4 prior at 100.0, last at 1.0)
    vix_closes_5 = [100.0] * 4 + [1.0]
    p1, p2, p3, p4, p5, p6, p7 = _mock_regime_helpers(50.0, vix_closes_5)
    with p1, p2, p3, p4, p5, p6, p7:
        res_5 = await get_regime()
    assert res_5.vix_pct_252d == 0.0
    assert res_5.vix_pct_30d == 0.0


def test_vix_percentile_helper_strict_and_rounding():
    """Unit tests for _vix_percentile helper: strict comparison, rounding, empty fallback."""
    # Empty fallback
    assert _vix_percentile([], 20.0) == 50.0

    # Strict inequality: ties excluded from numerator
    assert _vix_percentile([20.0, 20.0, 20.0], 20.0) == 0.0

    # 1 of 3 below: 33.333... -> 33.3
    assert _vix_percentile([10.0, 20.0, 30.0], 20.0) == 33.3

    # 2 of 3 below: 66.666... -> 66.7
    assert _vix_percentile([10.0, 20.0, 30.0], 30.0) == 66.7

    # All below
    assert _vix_percentile([10.0, 20.0], 5.0) == 0.0

    # All above
    assert _vix_percentile([10.0, 20.0], 50.0) == 100.0
