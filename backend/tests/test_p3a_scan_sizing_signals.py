"""P3a — scan sizing & signal correctness.

Plan: docs/superpowers/plans/2026-09-25-p3a-scan-sizing-signals-plan.md.
Decisions: Q2, Q5, Q11 (BACKLOG-DECISIONS-2026-09-25) and
P3A-UNMEASURED-TREND-REMOVE-2026-09-25.

Nothing here writes backend/config/*.yaml or runs the app lifespan.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi import HTTPException
from pydantic import ValidationError

import app.routers.stock_scan as ss
from app.schemas.stock_scan import PositionCardOut, StockScanRequest
from app.scoring import stock_scorer as sc
from app.scoring.conviction_sizing import conviction_mult
from app.scoring.stock_scorer import RuleResult, StockScoreCard
from app.services.strategy_engine import _build_target_ladder
from tests.test_a5c_analysis_scan_drop_flags import (
    PREFIX, _analyze, _Card, _flags, _offline, _Rule, _scan,
)
from tests.test_confidence_gate_stocks import (
    _make_fake_bars, _make_fake_bt, _make_fake_card, _make_fake_signal,
)


# ── Q11: the scorer marks an unmeasured trend ─────────────────────────────────

def _cfg(horizon="Swing"):
    import copy
    return copy.deepcopy(sc._horizon_cfg(horizon))


def test_crossover_with_too_few_bars_is_unmeasured():
    r = sc._trend_crossover([100.0] * 10, _cfg(), "Bullish")
    assert r.detail["reason"] == "insufficient_data" and r.measured is False


def test_additive_with_too_few_bars_is_unmeasured():
    r = sc._trend_additive([100.0] * 5, _cfg(), "Bullish", bars=None)
    assert r.detail["reason"] == "insufficient_data" and r.measured is False


def test_relative_strength_without_a_benchmark_is_unmeasured():
    r = sc._trend_relative_strength([100.0] * 80, _cfg(), "Bullish", benchmark_closes=None)
    assert r.score == 50 and r.measured is False


def test_relative_strength_with_a_benchmark_is_measured():
    closes = [100.0 + i for i in range(80)]
    r = sc._trend_relative_strength(closes, _cfg(), "Bullish", benchmark_closes=[100.0] * 80)
    assert r.measured is True


def test_a_real_reading_is_measured():
    closes = [100.0 + i * 0.5 for i in range(120)]
    r = sc._trend_additive(closes, _cfg(), "Bullish", bars=None)
    assert r.measured is True


# ── Q11: the direction gate removes an unmeasured trend as "no data" ─────────

def _card(rules):
    return StockScoreCard(symbol="X", direction="Bullish", horizon="Swing",
                          score=70, status="PASS", rules=rules)


def test_gate_removes_an_unmeasured_trend_under_its_own_reason():
    r = RuleResult("trend", "CAUTION", 50, {}, measured=False)
    drop = ss._direction_conviction_drop("X", _card([r]), 30.0, "Bullish", "Swing")
    assert drop["reason"].startswith("direction_conviction_unmeasured:")
    assert ss.classify_stock_rejection(drop["reason"]) == "failed_direction_unmeasured"


def test_gate_treats_a_missing_trend_rule_as_unmeasured():
    drop = ss._direction_conviction_drop("X", _card([]), 30.0, "Bullish", "Swing")
    assert drop["reason"].startswith("direction_conviction_unmeasured:")


def test_gate_still_judges_a_measured_trend_on_its_floor():
    low = ss._direction_conviction_drop("X", _card([RuleResult("trend", "REJECT", 20, {})]),
                                        30.0, "Bullish", "Swing")
    assert low["reason"].startswith("direction_conviction: trend 20 < 30")
    ok = ss._direction_conviction_drop("X", _card([RuleResult("trend", "PASS", 60, {})]),
                                       30.0, "Bullish", "Swing")
    assert ok is None


def test_an_exempt_horizon_is_not_gated_even_when_unmeasured():
    r = RuleResult("trend", "CAUTION", 50, {}, measured=False)
    assert ss._direction_conviction_drop("X", _card([r]), None, "Bullish", "Intraday") is None


@pytest.mark.asyncio
async def test_analysis_flags_an_unmeasured_trend_as_the_scan_drop(monkeypatch):
    _offline(monkeypatch, min_trend=30.0)

    def _score(**kw):
        return _Card(rules=[RuleResult("trend", "CAUTION", 50, {}, measured=False)])

    monkeypatch.setattr(ss, "score_stock", _score)
    scan = await _scan()
    assert scan["reason"].startswith("direction_conviction_unmeasured:")
    core = await _analyze()
    fl = _flags(core, "direction_conviction")
    assert len(fl) == 1 and fl[0]["detail"] == PREFIX + scan["reason"]


# ── relative_strength is measured against its own benchmark ──────────────────

def test_resolve_rs_benchmark_follows_the_scorers_override_rules():
    assert sc.resolve_rs_benchmark("Swing", {}) is None or \
        sc._horizon_cfg("Swing")["trend"].get("method") == "relative_strength"
    cfg_bench = sc._horizon_cfg("Swing")["trend"]["relative_strength"].get("benchmark", "NDX")
    assert sc.resolve_rs_benchmark("Swing", {"trend_method": "relative_strength"}) == cfg_bench
    assert sc.resolve_rs_benchmark(
        "Swing", {"trend_method": "relative_strength", "rs_benchmark": "SPX"}) == "SPX"
    assert sc.resolve_rs_benchmark("Swing", {"trend_method": "additive"}) is None


@pytest.mark.parametrize("bench,proxy", [("NDX", "QQQ"), ("SPX", "SPY")])
def test_rs_benchmark_fetches_the_matching_etf(bench, proxy):
    req = StockScanRequest(universe=["X"], direction="Bullish", horizon="Swing",
                           strategy="pullback_ema",
                           overrides={"trend_method": "relative_strength", "rs_benchmark": bench})
    fetch = AsyncMock(return_value=[{"close": 1.0}])
    with patch.object(ss, "get_historical_bars", fetch):
        out = asyncio.run(ss._rs_benchmark_candles(req))
    assert fetch.call_args.args[0] == proxy
    assert out == [{"close": 1.0}]


@pytest.mark.parametrize("overrides,fetch_result", [
    ({"trend_method": "additive"}, [{"close": 1.0}]),                        # not RS
    ({"trend_method": "relative_strength", "rs_benchmark": "RUT"}, [{"close": 1.0}]),  # no proxy
    ({"trend_method": "relative_strength", "rs_benchmark": "NDX"}, RuntimeError("down")),
    ({"trend_method": "relative_strength", "rs_benchmark": "NDX"}, []),
])
def test_rs_benchmark_is_none_rather_than_a_substitute(overrides, fetch_result):
    req = StockScanRequest(universe=["X"], direction="Bullish", horizon="Swing",
                           strategy="pullback_ema", overrides=overrides)
    fetch = AsyncMock(side_effect=fetch_result) if isinstance(fetch_result, Exception) \
        else AsyncMock(return_value=fetch_result)
    with patch.object(ss, "get_historical_bars", fetch):
        assert asyncio.run(ss._rs_benchmark_candles(req)) is None
    if overrides.get("rs_benchmark") == "RUT" or overrides["trend_method"] != "relative_strength":
        fetch.assert_not_called()


def test_the_scan_hands_the_benchmark_to_the_scorer_on_both_paths():
    """A relative_strength scan must score WITH the benchmark on the scan and
    on Analysis, or every name reads unmeasured and is removed."""
    import inspect
    assert "benchmark_candles=_aligned_benchmark(rs_benchmark_candles, bars[-120:])" in inspect.getsource(ss._process_stock)
    assert "benchmark_candles=_aligned_benchmark(await _rs_benchmark_candles(req), bars[-120:])" in inspect.getsource(ss._analyze_core)
    assert "rs_benchmark_candles=rs_benchmark_candles" in inspect.getsource(ss._execute_stock_scan_core)


def test_score_stock_measures_relative_strength_when_given_the_benchmark():
    bars = [{"time": i, "open": 100 + i, "high": 101 + i, "low": 99 + i,
             "close": 100 + i, "volume": 1_000_000} for i in range(120)]
    bench = [{"time": i, "open": 100, "high": 101, "low": 99, "close": 100.0,
              "volume": 1} for i in range(120)]
    ov = {"trend_method": "relative_strength"}
    with_b = sc.score_stock(symbol="X", direction="Bullish", horizon="Swing", bars=bars,
                            scoring_mode="stock", overrides=ov, benchmark_candles=bench)
    without = sc.score_stock(symbol="X", direction="Bullish", horizon="Swing", bars=bars,
                             scoring_mode="stock", overrides=ov)
    t_with = next(r for r in with_b.rules if r.name == "trend")
    t_without = next(r for r in without.rules if r.name == "trend")
    assert t_with.measured is True and t_without.measured is False


# ── Q5: min_stock_score ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_min_stock_score_drops_below_and_keeps_at_or_above(monkeypatch):
    _offline(monkeypatch, min_trend=None)       # card score is 70
    below = await _scan(min_stock_score=75)
    assert below["reason"] == "REJECT score=70 < min 75"
    assert ss.classify_stock_rejection(below["reason"]) == "failed_score"
    at = await _scan(min_stock_score=70)
    assert not (isinstance(at, dict) and at.get("reason", "").startswith("REJECT score="))


@pytest.mark.asyncio
async def test_analysis_flags_the_min_stock_score_drop(monkeypatch):
    _offline(monkeypatch, min_trend=None)
    core = await _analyze(min_stock_score=75)
    fl = _flags(core, "score")
    assert len(fl) == 1 and fl[0]["status"] == "REJECT"
    assert fl[0]["detail"] == PREFIX + "REJECT score=70 < min 75"
    assert not _flags(await _analyze(min_stock_score=70), "score")


def test_min_stock_score_bounds():
    base = dict(universe=["X"], direction="Bullish", horizon="Swing", strategy="pullback_ema")
    with pytest.raises(ValidationError):
        StockScanRequest(**base, min_stock_score=101)
    with pytest.raises(ValidationError):
        StockScanRequest(**base, min_stock_score=-1)
    assert StockScanRequest(**base).min_stock_score is None


# ── sizing: the conviction frame and the risk_pct=None fallback ──────────────

_ON = {"enabled": True, "min_mult": 0.3, "full_conviction_pct": 40}


def _omm(conviction_pct):
    return SimpleNamespace(state="Bear", p_stay=0.9, stability="Stable", regime_age_days=5,
                           avg_regime_duration=10.0, conviction_pct=conviction_pct,
                           conviction_label="Moderate", interpretation="t")


def _run(req, omm_result, sizing=_ON):
    cfg = dict(ss._load_full_scoring_cfg())
    cfg["regime_sizing"] = sizing
    sig = _make_fake_signal()
    omm_spy = []

    def _compute_omm(closes, **kw):
        omm_spy.append(kw)
        return omm_result

    async def run():
        with patch("app.routers.stock_scan.get_daily_regime_bars",
                   new=AsyncMock(return_value=_make_fake_bars())), \
             patch("app.routers.stock_scan.get_historical_bars",
                   new=AsyncMock(return_value=_make_fake_bars())), \
             patch("app.routers.stock_scan.fetch_company_name_async", new=AsyncMock(return_value="A")), \
             patch("app.routers.stock_scan.fetch_price_async", new=AsyncMock(return_value=152.0)), \
             patch("app.routers.stock_scan.score_stock", return_value=_make_fake_card()), \
             patch("app.routers.stock_scan.compute_omm", side_effect=_compute_omm), \
             patch("app.routers.stock_scan.compute_directional_hmm", side_effect=RuntimeError), \
             patch("app.routers.stock_scan._get_fundamentals", new=AsyncMock(return_value=None)), \
             patch.object(ss, "_SIGNAL_FNS", {"pullback_ema": lambda *a, **kw: sig}), \
             patch("app.routers.stock_scan._get_backtest_cached", return_value=_make_fake_bt()), \
             patch("app.routers.stock_scan.get_cached", return_value={"confidence": 60, "sample_size": 50}), \
             patch("app.routers.stock_scan._load_full_scoring_cfg", return_value=cfg):
            return await ss._process_stock("AAPL", req, "scan-1", {}, [])

    card = asyncio.run(run())
    assert isinstance(card, PositionCardOut), card
    return card, omm_spy


def test_bearish_card_sizes_on_the_regime_conviction_as_measured_not_re_mirrored():
    """compute_omm is handed the scan's direction and returns a direction-
    relative conviction; the card must size on THAT figure. Mirroring it again
    for Bearish would size a +20 tailwind as a -20 headwind."""
    req = StockScanRequest(universe=["AAPL"], direction="Bearish", horizon="Swing",
                           strategy="pullback_ema")
    card, omm_spy = _run(req, _omm(20))
    assert omm_spy and omm_spy[0]["direction"] == "Bearish"
    assert conviction_mult(20, _ON) != conviction_mult(-20, _ON)
    assert card.dollar_risk == pytest.approx(round(500 * conviction_mult(20, _ON), 2))


def test_risk_pct_none_is_the_default_one_percent_conviction_sized():
    req = StockScanRequest(universe=["AAPL"], direction="Bullish", horizon="Swing",
                           strategy="pullback_ema", risk_pct=None)
    card, _ = _run(req, _omm(20))
    mult = conviction_mult(20, _ON)
    assert mult < 1.0
    assert card.dollar_risk == pytest.approx(round(50_000 * 0.01 * mult, 2))
    assert card.shares == int(50_000 * 0.01 * mult / 4.0)


def test_negative_risk_pct_and_account_zero_are_refused():
    base = dict(universe=["X"], direction="Bullish", horizon="Swing", strategy="pullback_ema")
    with pytest.raises(ValidationError):
        StockScanRequest(**base, risk_pct=-0.01)
    with pytest.raises(ValidationError):
        StockScanRequest(**base, account_size=0)


@pytest.mark.parametrize("zero", [0, 0.0])
def test_a_stored_zero_risk_pct_runs_at_the_default(zero):
    """Decision P3A-STORED-ZERO-RISK-RUNS-AT-DEFAULT-2026-09-25: a schedule saved
    at 0% still validates and sizes like `risk_pct=None` (1% x conviction)."""
    req = StockScanRequest(universe=["X"], direction="Bearish", horizon="Swing",
                           strategy="pullback_ema", risk_pct=zero)
    assert req.risk_pct is None
    card, _ = _run(req, _omm(20))
    assert card.dollar_risk == pytest.approx(round(50_000 * 0.01 * conviction_mult(20, _ON), 2))


def test_a_stored_zero_percent_schedule_entry_still_validates():
    """Code round 1 F1: one such entry used to 500 the whole schedule list."""
    from app.schemas.scan_schedule import ScanScheduleEntry
    ScanScheduleEntry.model_validate(dict(
        id="x", label="l", mode="stocks", profile_id="p", profile_name="n",
        profile_synced_at="2026-09-01T00:00:00Z", pattern="fixed_time", fire_time="09:30",
        resolved_request={"universe": ["SP500"], "direction": "Bullish", "horizon": "Swing",
                          "strategy": "pullback_ema", "account_size": 100000, "risk_pct": 0}))


# ── bearish target ladder never goes non-positive ────────────────────────────

def test_bearish_ladder_with_no_positive_rung_is_empty():
    # entry 10, stop 30: risk 20, every R rung and the fallback are negative.
    assert _build_target_ladder(entry=10, stop=30, direction="Bearish", primary=None,
                                extensions=[10 - 40, 10 - 60], fallback_mult=2.0) == []


def test_bearish_sub_cent_nudge_at_zero_is_empty():
    assert _build_target_ladder(entry=0.01, stop=0.011, direction="Bearish", primary=None,
                                extensions=[], fallback_mult=2.0) == []


def test_bearish_ladder_with_a_positive_fallback_is_unchanged():
    assert _build_target_ladder(entry=100, stop=105, direction="Bearish", primary=None,
                                extensions=[], fallback_mult=2.0) == [90.0]


def test_bearish_primary_that_rounds_to_zero_is_dropped_not_kept():
    """Open question #49: _valid tested `value <= 0` BEFORE rounding, so a
    positive rung under 0.005 rounded to 0.0 and was kept. As targets[0] that is
    a short with NO take-profit (backtesting.py skips a falsy tp). It must be
    dropped like any other non-positive rung, so the fallback takes over."""
    assert _build_target_ladder(entry=1.0, stop=1.2, direction="Bearish", primary=0.004,
                                extensions=[], fallback_mult=2.0) == [0.6]


def test_bearish_extension_that_rounds_to_zero_is_dropped():
    assert _build_target_ladder(entry=1.0, stop=1.2, direction="Bearish", primary=0.5,
                                extensions=[0.003], fallback_mult=2.0) == [0.5]


def test_bearish_rung_rounding_up_to_one_cent_is_kept():
    # 0.006 rounds to 0.01 (positive): the post-rounding test must not drop it.
    assert _build_target_ladder(entry=1.0, stop=1.2, direction="Bearish", primary=0.006,
                                extensions=[], fallback_mult=2.0) == [0.01]


def test_pullback_ema_bearish_signal_is_none_when_no_positive_target_exists():
    """The public path: a signal function turns the empty ladder into no signal
    (its `if not targets: return None`), never a negative tp for the backtest."""
    from app.services import strategy_engine as se
    with patch.object(se, "_build_target_ladder", return_value=[]):
        bars = [{"open": 50 - i * 0.2, "high": 51 - i * 0.2, "low": 49 - i * 0.2,
                 "close": 50 - i * 0.2, "volume": 1_000_000} for i in range(200)]
        out = se.pullback_ema_signal(bars, direction="Bearish", tolerance=1.0)
    assert out is None


# ── the scan core: pre-check, symbol naming, pipeline, banner ────────────────

def _req(**kw):
    return StockScanRequest(universe=["X"], symbols=["AAA", "BBB", "CCC"], direction="Bearish",
                            horizon="Position", strategy="pullback_ema", **kw)


def _core(results, min_trend=40.0):
    it = iter(results)

    async def _ps(sym, *a, **k):
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    async def run():
        with patch.object(ss, "_process_stock", side_effect=_ps), \
             patch.object(ss, "fetch_quotes", return_value={}), \
             patch.object(ss, "get_historical_bars", new=AsyncMock(return_value=[])), \
             patch.object(ss, "load_direction_conviction_min_trend", return_value=min_trend), \
             patch.object(ss, "_rs_benchmark_candles", new=AsyncMock(return_value=None)):
            return await ss._execute_stock_scan_core(_req(), db=None)

    return asyncio.run(run())


def test_core_names_the_symbol_of_a_raised_exception():
    res = _core([RuntimeError("boom"), {"symbol": "BBB", "reason": "no pullback_ema setup"},
                 {"symbol": "CCC", "reason": "no pullback_ema setup"}])
    assert {"symbol": "AAA", "reason": "boom"} in res.rejected


def test_core_counts_unmeasured_apart_and_reports_the_floor_it_applied():
    res = _core([
        {"symbol": "AAA", "reason": "direction_conviction: trend 20 < 40 for Bearish Position"},
        {"symbol": "BBB", "reason": "direction_conviction_unmeasured: no trend measurement for Bearish Position"},
        {"symbol": "CCC", "reason": "no pullback_ema setup"},
    ])
    p = res.pipeline
    assert p.failed_direction == 1
    assert p.failed_direction_unmeasured == 1
    assert p.failed_signal == 1
    assert p.other_rejected == 0
    assert p.direction_min_trend == 40.0
    # Counts, not a cause.
    assert "market structure" not in res.direction_banner
    # Both direction-gate reasons count (plan round 3 note): AAA below the
    # floor + BBB unmeasured = 2; CCC was another gate, so "the rest" stays.
    assert "removed 2 of 3 (trend below 40); the rest were removed" in res.direction_banner


def test_core_reports_an_exempt_horizon_as_no_floor():
    res = _core([{"symbol": s, "reason": "no pullback_ema setup"} for s in ("AAA", "BBB", "CCC")],
                min_trend=None)
    assert res.pipeline.direction_min_trend is None
    assert res.pipeline.failed_direction_unmeasured == 0


@pytest.mark.parametrize("doc,exc", [(["not", "a", "mapping"], None),
                                     (None, yaml.YAMLError("bad yaml")),
                                     (None, OSError("gone"))])
def test_precheck_refuses_an_unusable_scoring_document_with_detail(doc, exc):
    kw = {"side_effect": exc} if exc else {"return_value": doc}

    async def run():
        with patch.object(ss, "_load_full_scoring_cfg", **kw), \
             patch.object(ss, "load_direction_conviction_min_trend", return_value=40.0), \
             patch.object(ss, "fetch_quotes", side_effect=AssertionError("fetched before refusing")):
            return await ss._execute_stock_scan_core(_req(), db=None)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(run())
    assert ei.value.status_code == 500
    assert "scoring_rules.yaml" in ei.value.detail


def test_the_banner_omits_the_rest_when_the_direction_gate_removed_everything():
    res = _core([
        {"symbol": "AAA", "reason": "direction_conviction: trend 20 < 40 for Bearish Position"},
        {"symbol": "BBB", "reason": "direction_conviction_unmeasured: no trend measurement for Bearish Position"},
        {"symbol": "CCC", "reason": "direction_conviction: trend 10 < 40 for Bearish Position"},
    ])
    assert "removed 3 of 3 (trend below 40)." in res.direction_banner
    assert "the rest" not in res.direction_banner
    assert res.pipeline.failed_direction == 2


def test_the_rs_benchmark_is_aligned_by_date_not_position():
    stock = [{"time": f"2026-01-{d:02d}", "close": 1.0} for d in range(1, 21)]
    same = [{"time": f"2026-01-{d:02d}", "close": 1.0} for d in range(1, 23)]
    aligned = ss._aligned_benchmark(same, stock)
    assert aligned[-1]["time"] == "2026-01-20"          # trimmed to the stock's last day
    early = [{"time": f"2026-01-{d:02d}", "close": 1.0} for d in range(1, 20)]
    assert ss._aligned_benchmark(early, stock) is None   # ends a day earlier -> unmeasured
    gap = [b for b in same if b["time"] != "2026-01-20"]
    assert ss._aligned_benchmark(gap, stock) is None     # missing the stock's last day
    assert ss._aligned_benchmark(None, stock) is None
