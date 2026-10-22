from __future__ import annotations

import asyncio
import concurrent.futures
import copy
from collections import OrderedDict
import dataclasses
import functools
import hashlib
import json
import logging
import math
import os
import time
from collections.abc import Callable, Iterable
from decimal import Decimal
from datetime import datetime, timezone, date, timedelta
from pathlib import Path as _Path
from typing import Any, Literal, Optional

import httpx
import yaml as _yaml
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.scan_report_lifecycle import (run_reported_scan, current_collector, observe_resolution, observe_configuration, observe_data_failure, observe_no_data, observe_evaluation, observe_terminal)
from fastapi import Response
from app.services.config_health import config_health
from app.database import AsyncSessionLocal, get_db
from app.models.scan_session import ScanSession

from app.services.audit import new_rec_id
from app.services.unvalidated import BEARISH_UNVALIDATED_MESSAGE
from app.scoring.conviction_sizing import (
    SizingConfigError,
    conviction_mult,
    resolve_sizing,
)
from app.schemas.stock_scan import (
    StockScanRequest, StockScanResult, PositionCardOut,
    StrategySignalOut, BacktestOut, StockPipeline, StockAnalysisRequest,
    StockAnalysisOut, GateFlag, RuleContribution, EmaTrendOut,
    RegimeHorizonBlock, SectorTileOut, SectorRsOut, MarketBackdropOut,
)
from app.data.sector_map import sector_for_symbol
from app.routers.regime import _ema as _regime_ema, compute_overall_regime
from app.schemas import SentimentData, ScanSessionStatus, StockExplanation
from app.data.market import (
    fetch_company_name_async, fetch_price_async, fetch_quotes, fetch_intraday_candles,
    completed_intraday_bars,
    fetch_candles_async,
)
from app.services.historical_store import get_bars as get_historical_bars
# _atr is the SAME ATR(14) /contracts/exit-plan uses (contracts.py imports it
# from here too) -- not strategy_engine's same-named one, which is a different
# implementation. The two endpoints must build their ATR floor on one number.
from app.scoring.stock_scorer import (
    score_stock, _atr, resolve_rs_benchmark, effective_event_window, effective_veto_days,
    Horizon as ScoringHorizon,
)
from app.services.strategy_engine import (
    pullback_ema_signal, breakout_base_signal,
    ma_crossover_signal, mean_reversion_rsi_signal,
    mean_reversion_bb_signal,
    mean_reversion_vwap_signal,
    mean_reversion_vwap_daily_signal,
    breakout_setup_signal,
    merge_multi_params,
    multi_signal,
    SIGNAL_WINDOW_BARS,
)
from app.services.strategy_backtest import run_strategy_backtest
from app.services.strategy_backtest_details import ENGINE_CONTRACT_VERSION
from app.services.horizon_profiles import (
    hold_for_backtest, migrate_saved_stock_request, resolve_params_horizon,
)
from app.services.strategy_param_store import get_active, get_costs, get_exit, get_profile
from app.services.walk_forward import commission_for
from app.data.confidence_cache import BARS_BASIS_VERSION, cache_key as conf_cache_key, get_cached, set_cached
from app.data.confidence_cache import generation as conf_generation
from app.data.confidence_cache import invalidated_since as conf_invalidated_since
from app.scoring.signal_confidence import compute_confidence, interpret, load_backtest_cfg
from app.scoring.first_passage import estimate_stock_first_passage
# compute_final_stop / compute_target_row take candles, a direction, a price
# and config -- no contract input, and never had one. /stocks/exit-plan calls
# the SAME two functions with the SAME arguments as /contracts/exit-plan; that
# is what makes the stock plan the options plan minus the premium half rather
# than a second implementation of it.
from app.scoring.exit_plan import compute_final_stop, compute_target_row
from app.services.config_loader import (
    load_first_passage_cfg as _fp_cfg, load_exit_plan_cfg,
    load_direction_conviction_min_trend,
)
# _load_config is lru_cached AND cache_cleared by POST /settings/risk, so the
# risk budget below follows a saved settings change without a restart. A
# private-name import is deliberate: adding a public wrapper would be a second
# door onto one cache that the settings route would then have to know about.
from app.services import portfolio_risk
# Reused rather than redeclared: the stock estimate's invalidation block is an
# exact shape match for the option one, and two copies would drift apart.
# No cycle — contracts.py does not import this module.
from app.routers.contracts import FirstPassageInvalidationOut
from app.services.regime_omm import compute_omm
from app.services.regime_gate import resolve_regime_gate as _resolve_regime_gate
from app.services.money_config import (
    REGIME_HORIZONS, MoneyConfigError, RegimeConfigError, validate_money_blocks,
    validate_regime_block,
)
from app.services.regime_hmm_daily import compute_directional_hmm, alignment
from app.services.fundamentals_store import get_fundamentals as _get_fundamentals
from app.scoring.fundamentals_scorer import score_fundamentals as _score_fundamentals, FundamentalHealth
from app.schemas import FundamentalsOut
from app.services.fundamentals_gate import resolve_fundamentals_gate as _resolve_fundamentals_gate
from app.data.universe_presets import expand_universe, PresetUnavailableError
from app.data.universe_exclusions import Exclusion, ExclusionListError, filter_symbols


class PreBreakoutScanRequest(BaseModel):
    symbols: list[str] = []
    universe: list[str] | None = None   # e.g. ["SP500"] or ["SECTOR:XLK"] or individual tickers
    direction: str = "Bullish"
    params_override: dict | None = None


class PreBreakoutResult(BaseModel):
    symbol: str
    confidence: int
    direction: str
    metrics: dict
    # STOCK-PRES-P1: evidence behind `confidence` and the Fib swing low/high
    # (None when Fib was not used). Send-only, mirrors the route's row dict.
    confidence_breakdown: dict | None = None
    fib_swing: dict | None = None
    backtest_artifact_id: str | None = None
    backtest_artifact_status: str | None = None


_SCORING_CFG = _Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"

_ALLOWED_OVERRIDE_KEYS = frozenset({
    "atr_compression_ratio",
    "atr_avg_lookback",
    "range_atr_mult",
    "range_lookback_bars",
    "vol_compression_ratio",
    "resistance_proximity_pct",
    "swing_lookback",
    "require_trend",
    # Fibonacci pullback
    "fib_enabled",
    "fib_swing_lookback",
    "fib_levels",
    "fib_tolerance_pct",
})

_INT_OVERRIDE_KEYS = frozenset({
    "atr_avg_lookback",
    "range_lookback_bars",
    "swing_lookback",
    "fib_swing_lookback",
})


@functools.lru_cache(maxsize=1)
def _load_full_scoring_cfg() -> dict:
    return _yaml.safe_load(_SCORING_CFG.read_text())


# DOCC-4: the health poll compares this cache's live value with the file on disk.
config_health.watch(
    file="scoring_rules.yaml",
    loader="stock_scan._load_full_scoring_cfg",
    fn=_load_full_scoring_cfg,
    project=lambda doc: doc,
)


def _load_regime_cfg(horizon: str) -> dict:
    return _load_full_scoring_cfg()["regime"][horizon.lower()]


# Shared with auto_trader via app.scoring.conviction_sizing — the two had
# drifted to different formulas. Kept as a module-level alias so existing
# callers and tests importing _conviction_mult from here still resolve.
_conviction_mult = conviction_mult

router = APIRouter(prefix="/api", tags=["stock-scan"])
logger = logging.getLogger(__name__)

_SIGNAL_FNS = {
    "pullback_ema":              pullback_ema_signal,
    "breakout_base":             breakout_base_signal,
    "ma_crossover":              ma_crossover_signal,
    "mean_reversion_rsi":        mean_reversion_rsi_signal,
    "mean_reversion_bb":         mean_reversion_bb_signal,
    "mean_reversion_vwap":       mean_reversion_vwap_signal,
    "mean_reversion_vwap_daily": mean_reversion_vwap_daily_signal,
}

# Strategies that require intraday (15m) bars instead of daily bars for signal + backtest.
_INTRADAY_STRATEGIES = frozenset({"mean_reversion_vwap"})

# Days of 15-minute bars fetched on every path here (scan signal, scan regime,
# Analysis). One number so Analysis cannot measure a different series than the
# scan it explains; the auto-trader's fire path uses the same 55.
_INTRADAY_FETCH_DAYS = 55

# Risk fraction when a request carries neither risk_pct nor risk_fixed_usd.
_DEFAULT_RISK_PCT = 0.01

# ETF proxy fetched for a relative_strength trend benchmark. An index and its
# ETF differ in ROC only by dividends over the 20-50 day RS window. A name not
# listed here fetches nothing -> the trend is unmeasured, never scored against
# a substitute index.
_RS_BENCHMARK_PROXY = {"SPX": "SPY", "NDX": "QQQ"}

_SIGNAL_KWARGS: dict[str, Callable[[StockScanRequest], dict[str, Any]]] = {
    "pullback_ema":          lambda r: {"tolerance": r.pullback_tolerance_pct, "ema_period": r.pullback_ema_period, "trend_ema": r.pullback_trend_ema, "ma_type": r.pullback_ma_type, "require_reversal": r.pullback_require_reversal},
    "breakout_base":         lambda r: {"volume_mult": r.breakout_volume_mult},
    "ma_crossover":          lambda r: {"fast": r.ma_crossover_fast, "slow": r.ma_crossover_slow, "lookback": r.ma_crossover_lookback},
    "mean_reversion_rsi":    lambda r: {"rsi_period": r.rsi_period, "rsi_oversold": r.rsi_oversold, "rsi_overbought": getattr(r, "rsi_overbought", 70.0), "trend_sma": r.rsi_trend_sma, "require_choppy_regime": r.require_choppy_regime},
    "mean_reversion_vwap":   lambda r: {"interval": "15m"},
    "mean_reversion_bb":  lambda r: {"require_choppy_regime": r.require_choppy_regime},
}

def _backtest_commission() -> float:
    """Per-leg cost drag sourced from the same strategy_params.yaml `costs`
    block the WFO tuner (strategy_param_optimizer.py) already uses — keeps
    the Step-6 trader-facing backtest gate cost-aware instead of the
    commission-free number it showed before (2026-08-18 audit finding).
    Same rule as walk_forward.commission_for (Phase C T4)."""
    return commission_for(get_costs())


def _params_horizon(req: StockScanRequest) -> str | None:
    """The tuned horizon whose parameters this request reads (STOCKS-HORIZON-T1
    H4): ``req.params_horizon``, else the tuned horizon nearest the request's
    hold when the scoring horizon is not Intraday, else None (baseline)."""
    return resolve_params_horizon(req.params_horizon, req.horizon, req.hold_max_days)


def _merge_strategy_params(strategy: str, direction: str, request_kwargs: dict,
                           params_horizon: str | None = None) -> dict:
    """Exit policy, then the profile for direction x params horizon, then
    per-request kwargs.

    Precedence is deliberately exit < profile < request: the exit block is a
    baseline the tuner may later override into `active:` (WFO's adopt() writes
    there), the profile (``get_profile``: the direction baseline, overlaid by
    the tuned horizon's profile when one exists) is the adopted value, and an
    explicit per-scan override (any non-None request field) wins over both.

    Note this widens `_backtest_key`'s inputs — `_bt_params` is part of the
    backtest cache key — so every cached BacktestResult is invalidated the first
    time this ships. That is correct: the exits genuinely changed.
    """
    merged = get_exit(strategy)
    merged.update(get_profile(strategy, direction, params_horizon)[0])
    merged.update({k: v for k, v in request_kwargs.items() if v is not None})
    return merged


def _params_source(req: StockScanRequest) -> str:
    """The card's params_source: "tuned" when a tuned profile exists for the
    request's strategy x direction x params horizon, else "baseline"."""
    return get_profile(req.strategy, req.direction, _params_horizon(req))[1]


# ── A5c: scan-drop filters shared by _process_stock and _analyze_core ────────
# Decisions A5B-A5C-LOCKED-2026-09-24 / A5C-SCOPE-SIX-FILTERS-GO-2026-09-25:
# every filter on which the scan DROPS a symbol is one helper here, so the
# Analysis page (which flags it REJECT, card status unchanged) cannot drift
# from the scan. Helpers that produce a drop return the scan's own rejection
# dict (symbol + reason) rather than a bare string: the funnel guard
# (tests/test_stock_scan_funnel.py::test_every_stock_reason_producer_is_classified)
# finds reason producers by regex over this module's source and must still
# see each reason literal where it is written.

_SCAN_DROP_PREFIX = "the scan would drop this: "
_MIN_INTRADAY_BARS = 30


def _scan_drop_flag(gate: str, drop: dict) -> dict:
    """The Analysis gate flag for a filter the scan drops on: REJECT, the
    scan's own reason behind a fixed prefix."""
    return {"gate": gate, "status": "REJECT", "detail": f"{_SCAN_DROP_PREFIX}{drop['reason']}"}


def _stock_explanation_out(symbol: str, card) -> StockExplanation | None:
    """STOCK-PRES-P1: the scorer's own evidence, validated for the wire. A
    failed validation is logged and sent as None -- never drops the candidate.
    getattr: a card without the attribute (a test double) is "no evidence",
    not an exception that would drop the symbol from the scan."""
    explanation = getattr(card, "explanation", None)
    if explanation is not None:
        observe_configuration("stocks.scorer_explanation", explanation, symbol=symbol)
    if explanation is None:
        return None
    try:
        return StockExplanation.model_validate(explanation)
    except ValidationError:
        logger.warning("stock scan: %s score evidence failed validation; sent without it", symbol)
        return None


def _intraday_history_drop(symbol: str, strategy: str, intraday_bars: list[dict]) -> dict | None:
    if strategy in _INTRADAY_STRATEGIES and len(intraday_bars) < _MIN_INTRADAY_BARS:
        return {"symbol": symbol, "reason": "insufficient intraday history"}
    return None



_REGIME_DATA_PREFIX = "regime data unavailable:"


def _regime_data_drop(symbol: str, req, full_cfg: dict, regime_gate: dict, rcfg: dict,
                      regime_bars: list[dict], fetch_exc: Exception | None) -> dict | None:
    """P3a item 12: drop an Intraday name whose 15-min regime bars could not be had.

    Decisions P3A-INTRADAY-REGIME-FETCH-REFUSES-2026-09-25 and
    P3A-INTRADAY-REFUSAL-MATCHES-FIRE-2026-09-25 (Kenneth). Since
    P3B-REGIME-BARS-MISSING-REFUSES the auto-trader REFUSES a fire whose regime
    fetch raised or came back empty, whenever it measures -- which is when the
    YAML regime_gate is enabled or regime sizing is on. The scan drops on the
    same condition (plus `regime_filter`, which the fire never reads, so the
    scan is stricter there), so it cannot propose what the fire will refuse.
    A series that arrived but is too short for `compute_omm` still abstains
    and is floor-sized, as on the fire. Daily timeframes are untouched: a
    symbol with no daily bars is already dropped as "insufficient history".
    """
    if rcfg.get("timeframe") != "15min" or regime_bars:
        return None
    try:
        sizing_on = resolve_sizing(full_cfg.get("regime_sizing", {"enabled": False})) is not None
    except SizingConfigError:
        sizing_on = True   # a broken block is not "sizing off"; fail closed
    if not (bool((regime_gate or {}).get("enabled")) or req.regime_filter or sizing_on):
        return None
    reason = f"{_REGIME_DATA_PREFIX} no completed 15-min bars for {symbol}"
    if fetch_exc is not None:
        reason += f" (fetch failed: {fetch_exc})"
    return {"symbol": symbol, "reason": reason}

def _direction_conviction_drop(symbol: str, card, min_trend: float | None,
                               direction: str, horizon: str) -> dict | None:
    # Direction conviction filter — a FLOOR in both directions, never a
    # ceiling on the bearish side. The trend rule is direction-aware, so
    # a high trend score on a Bearish scan means a strong DOWNtrend,
    # which is the setup a put wants; what this gate removes is a LOW
    # score either way. Thresholds live in scoring_rules.yaml
    # (horizons.<horizon>.direction_conviction); `None` means exempt,
    # which is how Intraday is excused rather than by naming it here.
    # The FLOOR must stay identical to the options gate in routers/scan.py —
    # both read the same resolver, which is what keeps them in step. The
    # unmeasured check below is shared too (see its note).
    if min_trend is None:
        return None
    # A trend rule with nothing to measure (too few bars for its MA, no
    # benchmark series for relative strength) carries a placeholder score --
    # 0 for crossover/additive, 50 for relative strength -- that this gate used
    # to judge as if it were a reading, so the same "no data" was removed on one
    # method and passed on another. It is now removed as UNMEASURED, under its
    # own reason and funnel bucket (decisions Q11 and
    # P3A-UNMEASURED-TREND-REMOVE-2026-09-25). A card with no trend rule at all
    # is the same case: nothing was measured. The options scan runs this same
    # helper in scan._process_symbol (P3c item 2), on the pre-screen card and
    # before the chain fetch, acting only on the unmeasured verdict; its
    # post-gather floor then reads `stockBreakdown.trend` as a real reading.
    _trend = next((r for r in card.rules if r.name == "trend"), None)
    if _trend is None or not getattr(_trend, "measured", True):
        observe_terminal(symbol, "no_data", "trend_unmeasured", observations={"direction": direction}, thresholds={"min_trend": min_trend})
        return {"symbol": symbol,
                "reason": f"direction_conviction_unmeasured: no trend measurement for {direction} {horizon}"}
    _trend_score = _trend.score
    if _trend_score < min_trend:
        observe_terminal(symbol, "filtered", "direction_conviction", observations={"trend_score": _trend_score, "direction": direction}, thresholds={"min_trend": min_trend})
        return {"symbol": symbol, "reason": f"direction_conviction: trend {_trend_score} < {min_trend:g} for {direction} {horizon}"}
    return None


def _regime_headwind(regime_signal: dict | None, regime_gate: dict) -> bool:
    """True when the regime reads as a headwind. The scan drops on it only
    when `req.regime_filter` is on; Analysis flags it either way (REJECT when
    the scan would drop, CAUTION otherwise)."""
    return bool(regime_signal) and \
        regime_signal["conviction_pct"] <= regime_gate.get("headwind_caution_pct", -15)


def _no_setup_drop(symbol: str, strategy: str) -> dict:
    return {"symbol": symbol, "reason": f"no {strategy} setup"}


def _min_score_drop(symbol: str, card, min_stock_score: float | None) -> dict | None:
    """Step-3 "Min stock score" (Q5). The `REJECT score=` prefix files it under
    failed_score, the same funnel stage as the status REJECT it extends."""
    if min_stock_score is not None and card.score < min_stock_score:
        return {"symbol": symbol, "reason": f"REJECT score={card.score} < min {min_stock_score:g}"}
    return None


# ── Earnings veto over the hold (STOCKS-HORIZON-P0B B6) ──────────────────────

def _resolve_stock_veto_days(req) -> int:
    """veto_days = max(reject_days, hold_max_days) for this request.

    Never fails the scan; the same fail-toward-vetoing fallback as the options
    scan (`scan._resolve_earnings_veto_days`): the event window's reject_days,
    then the widest window over every horizon with no overrides."""
    try:
        return effective_veto_days(req.horizon, req.overrides, req.hold_max_days)
    except Exception as exc:
        logger.warning("stock earnings veto window unavailable: %s", exc)
    try:
        return effective_event_window(req.horizon, req.overrides)[0]
    except Exception:
        from typing import get_args
        return max(effective_veto_days(h, None, None) for h in get_args(ScoringHorizon))


async def _earnings_days_for(symbol: str) -> int | None:
    """Days to the symbol's next earnings date, or None when unknown.

    The fire path's lookup (`auto_trader._fetch_earnings_date`: Tradier
    fundamentals, then yfinance, each under its own deadline, with failure
    backoff), looked up at call time so the suite's patch on it lands. The
    batch quote carries no earnings date. A raised lookup, None, or a past
    date is UNKNOWN."""
    from app.services import auto_trader
    try:
        found = await asyncio.to_thread(auto_trader._fetch_earnings_date, symbol)
    except Exception as exc:  # noqa: BLE001 -- a failed lookup is unknown, never a crash
        logger.warning("stock earnings lookup for %s failed: %s", symbol, exc)
        return None
    if found is None:
        return None
    try:
        ev = found.date() if isinstance(found, datetime) else date.fromisoformat(str(found)[:10])
    except (ValueError, TypeError):
        return None
    days = (ev - date.today()).days
    return days if days >= 0 else None


def _stock_earnings_veto(status: str, earnings_days: int | None, veto_days: int) -> tuple[str, dict | None]:
    """(status, gate flag or None). Earnings inside the veto window cap the
    status at CAUTION (a REJECT stays REJECT) and add an `earnings` flag.

    UNKNOWN EARNINGS (None) IS NOT A VETO ON STOCKS. Decision D4's
    unknown-date rule is an options auto-fire policy; extending it to the
    stocks path was not decided (STOCKS-HORIZON-P0B B6)."""
    if earnings_days is None or earnings_days >= veto_days:
        return status, None
    flag = {"gate": "earnings", "status": "CAUTION",
            "detail": f"earnings in {earnings_days}d is inside the hold window (<{veto_days}d)"}
    return ("CAUTION" if status == "PASS" else status), flag


async def _rs_benchmark_candles(req) -> list[dict] | None:
    """The benchmark bars a relative_strength trend rule needs, or None.

    None when the effective trend method is not relative_strength, when the
    benchmark has no ETF proxy, or when the fetch fails or returns nothing --
    the last three leave the trend UNMEASURED, which the direction gate removes
    as "no data" instead of scoring a placeholder 50."""
    name = resolve_rs_benchmark(req.horizon, req.overrides)
    if name is None:
        return None
    proxy = _RS_BENCHMARK_PROXY.get(name.upper())
    if proxy is None:
        logger.warning("relative_strength benchmark %r has no ETF proxy -- trend left unmeasured", name)
        return None
    end = date.today()
    try:
        bars = await get_historical_bars(proxy, end - timedelta(days=_HISTORY_YEARS * 365), end)
    except Exception as exc:
        logger.warning("relative_strength benchmark %s fetch failed: %s", proxy, exc)
        return None
    return bars or None


def _bar_day(bar: dict) -> str | None:
    """A bar's calendar day as YYYY-MM-DD: ISO strings (the history store) or
    unix ints (UTC)."""
    t = bar.get("time")
    if isinstance(t, str):
        return t[:10]
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        return datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
    return None


def _aligned_benchmark(benchmark: list[dict] | None, stock_bars: list[dict]) -> list[dict] | None:
    """The benchmark bars trimmed to the STOCK's last day, or None.

    `_roc` compares the last `period` bars of each series BY POSITION, so a
    benchmark ending on a different day would compare returns over different
    days. Trimmed to bars on or before the stock's last day; if the trimmed
    series does not end on that same day, the benchmark is treated as missing
    -- the trend is UNMEASURED (dropped as "no data"), never compared across
    different days."""
    if not benchmark or not stock_bars:
        return None
    last = _bar_day(stock_bars[-1])
    if last is None:
        return None
    trimmed = [b for b in benchmark if (_bar_day(b) or "") <= last]
    if not trimmed or _bar_day(trimmed[-1]) != last:
        return None
    return trimmed


def _multi_params(req: StockScanRequest) -> dict:
    """mean_reversion_multi's effective params shape for this request
    (STOCKS-HORIZON-T1 H3/H4): the multi profile for direction x params horizon
    under the request's variants, min_confirmations and per-variant fields
    (None = not set). The live loop and the backtest are handed this same
    object."""
    profile = get_profile("mean_reversion_multi", req.direction, _params_horizon(req))[0]
    variants = (req.mean_reversion_variants if req.mean_reversion_variants is not None
                else profile.get("variants") or [])
    variant_params: dict = {}
    for variant in variants:
        kw = dict(_SIGNAL_KWARGS.get(variant, lambda r: {})(req))
        if variant == "mean_reversion_vwap_daily":
            kw.update(vwap_lookback=req.vwap_lookback, vwap_deviation_pct=req.vwap_deviation_pct)
        variant_params[variant] = kw
    return merge_multi_params(
        req.direction,
        profile,
        {"variants": req.mean_reversion_variants,
         "min_confirmations": req.mean_reversion_min_confirmations,
         "variant_params": variant_params},
    )


def _multi_signal(symbol: str, req: StockScanRequest, bars: list[dict],
                  params: dict | None = None) -> tuple[object | None, dict | None]:
    """mean_reversion_multi's vote (strategy_engine.multi_signal) over
    ``params`` (default ``_multi_params(req)``). Returns (signal, None) on a
    confirmed setup, else (None, the scan's rejection dict)."""
    if params is None:
        params = _multi_params(req)
    valid_variants = [v for v in params["variants"] if v in _SIGNAL_FNS]
    fired: list = []
    # Order-independent resolution (resolve_multi_signal): widest stop,
    # tightest target, pooled ladder.
    signal = multi_signal(bars[-SIGNAL_WINDOW_BARS:], direction=req.direction, params=params,
                          signal_fns=_SIGNAL_FNS, fired_out=fired)
    if len(fired) < params["min_confirmations"]:
        return None, {"symbol": symbol, "reason": f"no mean_reversion_multi: {len(fired)}/{len(valid_variants)} signals fired"}
    if signal is None:
        return None, {"symbol": symbol, "reason": "mean_reversion_multi: variants produced no valid combined levels"}
    return signal, None


def _backtest_drop(symbol: str, bt_result) -> dict | None:
    if not bt_result.passes_gate:
        return {"symbol": symbol, "reason": f"backtest gate: {bt_result.summary_text}"}
    return None


def _reject_unsupported_multi_variants(req: StockScanRequest) -> None:
    # mean_reversion_multi's per-variant loop (_multi_signal) always calls
    # each variant on DAILY `bars`, unlike the single-strategy path, which
    # correctly special-cases _INTRADAY_STRATEGIES to fetch and use 15m bars.
    # "mean_reversion_vwap" (the intraday variant, NOT "_daily") is not itself
    # in _INTRADAY_STRATEGIES either, so nothing routes intraday bars into the
    # multi-signal loop for it. A third independent audit round found this
    # would silently run the intraday variant's VWAP/ATR/entry-gate math on
    # daily candles mislabeled as 15-minute bars — no error, just quietly
    # wrong numbers with a plausible shape. Not reachable through the shipped
    # UI today (MeanReversionConfirmPanel only offers rsi/bb/vwap_daily), but
    # rejected here rather than left as a live API footgun for the next
    # caller (a future feature, a test, a script) that adds it. Called by
    # both run_stock_scan and analyze_stock (A5c: Analysis runs the loop too).
    #
    # STOCKS-HORIZON-T1 H4: both checks run on the MERGED shape (profile +
    # request), since the request's multi fields are Optional. A request with
    # 2 variants against a profile min_confirmations 3 is refused here rather
    # than silently never firing.
    if req.strategy != "mean_reversion_multi":
        return
    shape = _multi_params(req)
    variants = shape.get("variants") or []
    if "mean_reversion_vwap" in variants:
        raise HTTPException(
            status_code=422,
            detail="mean_reversion_vwap (intraday) is not supported in mean_reversion_multi — "
                   "its variant loop only evaluates daily bars. Use mean_reversion_vwap_daily instead.",
        )
    min_conf = shape.get("min_confirmations")
    if min_conf is None or min_conf > len(variants):
        raise HTTPException(
            status_code=422,
            detail=f"mean_reversion_min_confirmations ({min_conf}) cannot exceed the number "
                   f"of selected variants ({len(variants)})",
        )


_HISTORY_YEARS = 5
_SCAN_SEM = asyncio.Semaphore(5)

_BACKTEST_TTL = 24 * 3600  # daily — bar history doesn't change within a trading day
# Shortlist-cap ranking (see the cap in _execute_stock_scan_core). Statuses
# not listed sort after CAUTION; a REJECT never reaches the cap (it is dropped
# as "REJECT score=" first), so today that is only a defensive default.
_SHORTLIST_STATUS_ORDER = {"PASS": 0, "CAUTION": 1}
# The frontend matches this prefix to show trimmed names as "over cap" rather
# than as rejections (frontend/lib/stockShortlist.ts) -- change both together.
_SHORTLIST_REASON_PREFIX = "Shortlist cap:"


def _shortlist_rank_key(c: PositionCardOut) -> tuple:
    return (
        _SHORTLIST_STATUS_ORDER.get(c.stock_status, len(_SHORTLIST_STATUS_ORDER)),
        -c.stock_score,
        -(c.confidence if c.confidence is not None else -1),
    )


def classify_stock_rejection(reason: str) -> str:
    """Map a rejection reason to the StockPipeline field that counts it.

    Module-level and total (every input returns exactly one bucket) so the
    funnel's classification can be tested against the real reason strings
    without driving a whole scan. That matters more here than it looks: the
    counters are pure string matching over text produced elsewhere in this
    file, and `other_rejected` is the RESIDUAL. Reword a producer without
    updating its predicate and the bucket silently collapses to zero while the
    residual absorbs it -- the funnel's `scanned == sum of buckets` invariant
    still holds, so nothing fails, and the UI reports real gate rejections as
    "errors". Three reasons were doing exactly that before this was centralised:
    "insufficient intraday history" does not contain "insufficient history",
    and the two mean_reversion_multi misses start with "no " but never say
    "setup".

    Order matters only in that the first match wins; the buckets below are
    mutually exclusive over the reasons this module actually emits, which
    tests/test_stock_scan_funnel.py pins string by string.
    """
    if (
        "insufficient history" in reason
        or "insufficient intraday history" in reason
        or "no price data" in reason
        or reason.startswith("price $")
        # P3a item 12: no 15-min regime bars is a data drop, like no price.
        or reason.startswith(_REGIME_DATA_PREFIX)
        # STOCKS-HORIZON-P0A A2: a `scope: scan` symbol from
        # universe_exclusions.yaml, dropped before any per-symbol work.
        or reason.startswith("Excluded (data):")
    ):
        return "failed_history"
    if reason.startswith("REJECT score="):
        return "failed_score"
    # Listed beside "direction_conviction:" (which it does not match) so the
    # two direction buckets read as a pair.
    if reason.startswith("direction_conviction_unmeasured:"):
        return "failed_direction_unmeasured"
    if reason.startswith("direction_conviction:"):
        return "failed_direction"
    if reason == "regime headwind":
        return "failed_regime"
    if (
        (reason.startswith("no ") and "setup" in reason)
        or reason.startswith("no mean_reversion_multi:")
        or reason.startswith("mean_reversion_multi:")
    ):
        return "failed_signal"
    # The confidence gate is a backtest-derived quality gate applied right after
    # the backtest; it belongs with it rather than among "errors".
    if reason.startswith("backtest gate:") or reason.startswith("confidence gate "):
        return "failed_backtest"
    # Not a gate failure: a candidate that passed everything and was ranked
    # below the cap. The pipeline counts these as original_count - kept, so
    # this bucket only keeps them OUT of the residual (no double count).
    if reason.startswith(_SHORTLIST_REASON_PREFIX):
        return "failed_shortlist"
    return "other_rejected"


def _drop_excluded_symbols(symbols: list[str], label: str) -> tuple[list[str], list[Exclusion]]:
    """Split a scan's FINAL symbol list (presets expanded, typed tickers
    included) into (kept, excluded) by universe_exclusions.yaml's `scope: scan`
    entries (STOCKS-HORIZON-P0A A2). Called before any per-symbol work. A
    broken list is a named 500, logged once here: it must not silently scan
    everything."""
    try:
        kept, excluded = filter_symbols(symbols, purpose="scan")
        observe_resolution(symbols, kept, excluded)
        return kept, excluded
    except ExclusionListError as e:
        logger.error("%s aborted: universe exclusion list unusable: %s", label, e)
        raise HTTPException(status_code=500, detail=str(e))


_BACKTEST_CACHE: dict[str, tuple] = {}  # key → (BacktestResult, expires_at)
_BACKTEST_POOL = concurrent.futures.ProcessPoolExecutor(
    max_workers=max(1, (os.cpu_count() or 2) // 2)
)

_last_stock_request: StockScanRequest | None = None
_last_stock_result: StockScanResult | None = None
_last_stock_status: str = "idle"
_last_stock_updated_at: str | None = None


async def _upsert_stock_session(
    db: AsyncSession,
    req: StockScanRequest | None,
    result: StockScanResult | None,
    status: str = "complete",
) -> None:
    """Persist the last stocks-mode scan to the same scan_sessions table the
    options-mode scan uses, under a distinct id so the two never collide.

    Single place that reassigns the in-memory "last stock scan" globals, so
    `status`/`strategy` (sourced from `_last_stock_request`) always stay in
    sync with each other at every write, including the running/idle writes
    from run_stock_scan() below — not just the final completed write."""
    global _last_stock_request, _last_stock_result, _last_stock_status, _last_stock_updated_at
    await db.merge(
        ScanSession(
            id="stock-current",
            status=status,
            last_result_json=result.model_dump_json() if result else None,
            last_request_json=req.model_dump_json() if req else None,
        )
    )
    await db.commit()
    _last_stock_request = req
    _last_stock_result = result
    _last_stock_status = status
    _last_stock_updated_at = datetime.now(timezone.utc).isoformat()


async def restore_stock_from_db() -> None:
    """Restore _last_stock_result from DB on startup — mirrors scan.py's restore_from_db()."""
    global _last_stock_request, _last_stock_result, _last_stock_status, _last_stock_updated_at
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(ScanSession).where(ScanSession.id == "stock-current"))
        except Exception:
            # Table may not exist (e.g., test_app.py with no DB)
            return
        row = result.scalar_one_or_none()
        if row is None:
            return
        if row.last_result_json:
            _last_stock_result = StockScanResult.model_validate_json(row.last_result_json)
        if row.last_request_json:
            # GUARDED (REGIME-SIZING-AUDIT r3 finding 2): a request saved before
            # a schema tightening (e.g. risk_fixed_usd gaining gt=0) must not
            # abort app startup -- nothing above or in main.py catches it. It
            # is dropped, not coerced: the saved request feeds only the
            # Analysis page's replay and last-run's `strategy` label (shown
            # blank until the next scan), and replaying an input the API would
            # now refuse is worse than offering no replay. The result still
            # loads.
            try:
                # STOCKS-HORIZON-T1 H4: a request saved before the strategy
                # fields became Optional carries their frozen defaults; drop
                # them so a replay follows the profile (idempotent; the row
                # itself is rewritten by the next scan).
                _last_stock_request = StockScanRequest.model_validate(
                    migrate_saved_stock_request(json.loads(row.last_request_json)))
            except (ValidationError, ValueError) as exc:
                logger.warning(
                    "restore_stock_from_db: saved stock-scan request no longer "
                    "validates and was dropped (no Analysis replay until the "
                    "next scan): %s", exc,
                )
                _last_stock_request = None
        # A restored "running" status means the process was killed mid-scan
        # (OOM, container restart) — unlike options mode's continuous-scan
        # scheduler, no in-flight stock-scan request can survive a restart
        # to resume it, so treat it as idle rather than reporting a scan
        # that will never finish as permanently "running".
        _last_stock_status = row.status if row.status != "running" else "idle"
        _last_stock_updated_at = row.updated_at.isoformat() if row.updated_at else None


def _backtest_key(symbol: str, strategy: str, direction: str, bars: list[dict], params: dict | None = None,
                   commission: float = 0.0, min_trades: int | None = None,
                   min_win_rate: float | None = None, hold_max_days: int | None = None) -> str:
    bars_hash = hashlib.md5(
        str([(b["time"], b["close"]) for b in bars[-20:]]).encode()
    ).hexdigest()[:8]
    # Canonical JSON with sorted keys at every depth (STOCKS-HORIZON-T1 H3):
    # mean_reversion_multi's params are nested, and a nested value or key
    # order must change, or not change, the key the same way a flat one does.
    params_hash = hashlib.md5(
        json.dumps(params or {}, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]
    # commission is folded into the key (not just the run_strategy_backtest call)
    # so that editing strategy_params.yaml's costs.fee_pct/slippage_pct doesn't
    # leave a stale pre-edit BacktestResult (including passes_gate) served out of
    # _BACKTEST_CACHE for up to _BACKTEST_TTL (24h) under an unchanged key.
    # A5: the gate thresholds too. The cached BacktestResult's passes_gate /
    # confidence / summary_text are decided on them, and the scan and the
    # Analysis page share this cache -- without them a run at 5 trades served
    # its verdict to a later run at 10 for up to _BACKTEST_TTL.
    # TRADING-REVIEW-PHASE-C T2: the bar basis version too, right after the bars
    # hash (a hash of closes alone does not see a basis change in open/high/low).
    # STOCKS-HORIZON-T1 H2: the time-exit hold too; it changes every trade's exit.
    return (f"{symbol.upper()}|{strategy}|{direction.lower()}|{bars_hash}|{BARS_BASIS_VERSION}"
            f"|{params_hash}|{commission:.6f}|{min_trades}|{min_win_rate!r}|hold={hold_max_days}")


def _get_backtest_cached(key: str):
    entry = _BACKTEST_CACHE.get(key)
    if entry and time.time() < entry[1]:
        return entry[0]
    return None


# Exact inputs AND the legacy cached summary object's identity are required.
# Legacy aggregate entries cannot be upgraded by another backtest invocation.
_BACKTEST_DETAILS: OrderedDict[str, tuple] = OrderedDict()


def _detail_key(symbol, bars, inputs):
    payload = json.dumps(dict(bars=bars, inputs=inputs, bars_basis=BARS_BASIS_VERSION,
                              engine=ENGINE_CONTRACT_VERSION), sort_keys=True,
                         separators=(',', ':'), allow_nan=False, default=str)
    return symbol.upper() + '|' + hashlib.sha256(payload.encode()).hexdigest()


def _run_backtest_with_details(bars, **kwargs):
    """Picklable ProcessPool entry; summary and evidence share one engine run."""
    details = []
    summary = run_strategy_backtest(bars, **kwargs, detail_collector=details)
    return summary, details[0] if len(details) == 1 else None


def _remember_detail(key, summary, detail):
    _BACKTEST_DETAILS[key] = (summary, copy.deepcopy(detail), time.time() + _BACKTEST_TTL)
    _BACKTEST_DETAILS.move_to_end(key)
    while len(_BACKTEST_DETAILS) > 128:
        _BACKTEST_DETAILS.popitem(last=False)


def _cached_detail(key, summary):
    entry = _BACKTEST_DETAILS.get(key)
    if entry is None:
        return None
    if time.time() >= entry[2]:
        _BACKTEST_DETAILS.pop(key, None)
        return None
    if entry[0] is not summary:
        return None
    _BACKTEST_DETAILS.move_to_end(key)
    return copy.deepcopy(entry[1])


async def _original_artifact(detail, *, scan_id, symbol, strategy, direction, horizon,
                             interval, detail_key):
    """Optional persistence must never perturb numeric/trading scan behavior."""
    if detail is None:
        return dict(backtest_artifact_status='original_unavailable')
    if detail.status != 'success':
        return dict(backtest_artifact_status=detail.status)
    collector = current_collector()
    identity = dict(scan_id=scan_id, report_run_id=collector.report_run_id if collector else None,
                    symbol=symbol, strategy=strategy, direction=direction, horizon=horizon,
                    interval=interval, bars_basis_version=BARS_BASIS_VERSION,
                    input_hash=detail_key.split('|', 1)[1],
                    engine_contract_version=detail.engine_contract_version)
    try:
        from app.services.backtest_artifacts import save_artifact
        async with AsyncSessionLocal() as db:
            saved = await save_artifact(db, detail=detail, identity=identity)
        return dict(backtest_artifact_id=saved['artifact_id'], backtest_artifact_status='available')
    except Exception:
        # Never log provider/configuration text or let optional storage drop a row.
        return dict(backtest_artifact_status='storage_unavailable')


def evict_backtest_cache(symbols: Iterable[str]) -> int:
    """Remove every cached BacktestResult for ``symbols``; returns the count removed.

    _backtest_key hashes only the last 20 bars, so an adjustment refresh that
    rewrites older bars (historical_store.refresh_adjustments) leaves the key
    unchanged; without this the pre-refresh result is served for _BACKTEST_TTL
    (TRADING-REVIEW-PHASE-C-HYGIENE T6). Exact prefix with the ``|`` delimiter,
    so ``AAPL`` never evicts ``AAPLX``. A backtest in flight across the refresh
    is kept out by the invalidated_since check at the two stores below.
    """
    prefixes = tuple(f"{s.upper()}|" for s in symbols)
    if not prefixes:
        return 0
    keys = [k for k in list(_BACKTEST_CACHE) if k.startswith(prefixes)]
    for k in keys:
        _BACKTEST_CACHE.pop(k, None)
    for k in list(_BACKTEST_DETAILS):
        if k.startswith(prefixes):
            _BACKTEST_DETAILS.pop(k, None)
    return len(keys)


from app.services.bars_changed import register_bars_listener
register_bars_listener("stock_backtests", evict_backtest_cache)


_INDEX_SYMBOLS = {"SPY", "QQQ", "DIA", "IWM", "SPX", "NDX", "VIX",
                  "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"}


def _is_index(symbol: str) -> bool:
    return symbol.upper() in _INDEX_SYMBOLS


@dataclasses.dataclass
class _AnalyzeCore:
    company: str
    price: float
    card: object                      # StockScoreCard
    regime_signal: dict | None
    fundamentals: object | None       # FundamentalHealth | None
    signal: object | None             # StrategySignal | None
    bt_result: object | None
    conf_val: int | None
    conf_txt: str | None
    sector_rs_pct: float | None
    next_event_days: int | None
    next_event_label: str | None
    daily_bars: list[dict]
    intraday_bars: list[dict]
    gate_flags: list[dict]
    earnings_days: int | None = None
    earnings_veto: bool = False
    # The hold passed to bt_result's backtest (hold_for_backtest; None = no hold).
    bt_hold: int | None = None


async def _analyze_core(symbol: str, req: "StockAnalysisRequest") -> "_AnalyzeCore | None":
    """Gate-free single-symbol computation for the analysis page.

    A5c: every filter on which the scan (_process_stock) would DROP the
    symbol adds a REJECT gate flag worded as a scan drop, via the helpers
    shared with the scan; card.status is not changed by any of them.
    """
    # Resolved first, before any fetch, so a malformed YAML floor raises
    # (-> HTTP 500) instead of being reported as a symbol verdict — the same
    # contract as _process_stock.
    _min_trend = load_direction_conviction_min_trend(req.direction, req.horizon)
    is_index = _is_index(symbol)
    end = date.today()
    start = end - timedelta(days=_HISTORY_YEARS * 365)
    # Captured before the read: a refresh evicting this symbol after it makes
    # set_cached drop the confidence computed from these bars (audit R2-F1).
    _bars_gen = conf_generation()
    bars = await get_historical_bars(symbol, start, end)
    if not bars or len(bars) < 60:
        return None

    gate_flags: list[dict] = []

    # Price
    try:
        price_map = await asyncio.to_thread(fetch_quotes, [symbol])
    except Exception:
        price_map = {}
    quote = price_map.get(symbol)
    price = (float(quote.get("last") or 0) or None) if quote else None
    if not price:
        price = float(bars[-1]["close"]) or None
    async with httpx.AsyncClient(timeout=10) as client:
        if not price:
            price = await fetch_price_async(client, symbol)
        if not price:
            return None
        company = await fetch_company_name_async(client, symbol)

    # Price-range advisory
    if req.min_price is not None and price < req.min_price:
        gate_flags.append({"gate": "price", "status": "REJECT", "detail": f"price ${price:.2f} < min"})
    if req.max_price is not None and price > req.max_price:
        gate_flags.append({"gate": "price", "status": "REJECT", "detail": f"price ${price:.2f} > max"})

    # Always fetch intraday bars — the analysis page shows all three horizon blocks
    # (Intraday / Swing / Position) regardless of req.horizon, so we always need them.
    _intraday_fetch_exc: Exception | None = None
    try:
        _intraday_bars = await asyncio.to_thread(fetch_intraday_candles, symbol, "15min", _INTRADAY_FETCH_DAYS)
    except Exception as exc:
        _intraday_bars = []
        _intraday_fetch_exc = exc
    if (_drop := _intraday_history_drop(symbol, req.strategy, _intraday_bars)):
        gate_flags.append(_scan_drop_flag("intraday_history", _drop))

    full_cfg = _load_full_scoring_cfg()
    rcfg = _load_regime_cfg(req.horizon)
    regime_signal = None
    # A4b: the regime copy drops the still-forming bar; `_intraday_bars` itself
    # stays whole for the signal / backtest / chart uses below.
    regime_bars = completed_intraday_bars(_intraday_bars) if rcfg["timeframe"] == "15min" else bars
    if regime_bars and len(regime_bars) >= rcfg.get("min_obs", 10):
        omm = compute_omm([b["close"] for b in regime_bars], direction=req.direction,
                          lookback=rcfg["lookback"], window=rcfg["window"], min_obs=rcfg["min_obs"])
        if omm:
            dh = None
            try:
                dh = compute_directional_hmm(regime_bars)
            except Exception:
                pass
            regime_signal = {
                "horizon": req.horizon, "timeframe": rcfg["timeframe"], "state": omm.state,
                "p_stay": omm.p_stay, "stability": omm.stability,
                "regime_age_days": omm.regime_age_days, "avg_regime_duration": omm.avg_regime_duration,
                "conviction_pct": omm.conviction_pct, "conviction_label": omm.conviction_label,
                "interpretation": omm.interpretation or "", "hmm_state": dh.state if dh else None,
                "alignment": alignment(omm.state, dh.state if dh else None), "insufficient_data": False,
            }

    # Fundamentals — the gate already carries the bearish cautionAbove/rejectAbove
    # overrides (applied once in services/fundamentals_gate.resolve_fundamentals_gate);
    # no per-site re-application here. Note: if the YAML fundamentals_gate block is
    # ever removed, the resolver returns {} and scoring would run on all-default cfg
    # instead of being skipped — acceptable, documented.
    fund_gate = None if is_index else _resolve_fundamentals_gate(req)
    _fh = None
    if fund_gate is not None and req.horizon.lower() != "intraday":
        _snap = await _get_fundamentals(symbol, staleness_days=fund_gate.get("staleness_days", 90))
        _fh = _score_fundamentals(_snap, req.direction, fund_gate) if _snap else None

    # A5 (decision A5-ANALYSIS-MIRRORS-SCAN): the same resolver as
    # _process_stock, so the Step-3 headwind thresholds the scan ran with are
    # the ones this page scores and flags on.
    _regime_gate = _resolve_regime_gate(
        full_cfg.get("regime_gate"),
        req.regime_headwind_caution_pct,
        req.regime_headwind_reject_pct,
    )
    # P3a item 12, the scan's drop as a flag (A5c).
    if (_drop := _regime_data_drop(symbol, req, full_cfg, _regime_gate, rcfg,
                                   regime_bars, _intraday_fetch_exc)):
        gate_flags.append(_scan_drop_flag("regime_data", _drop))
    card = score_stock(
        symbol=symbol, direction=req.direction, horizon=req.horizon, bars=bars[-120:],
        scoring_mode="stock", regime_signal=regime_signal,
        regime_gate=(_regime_gate or None) if regime_signal else None,
        fundamentals=_fh, fundamentals_gate=fund_gate,
        overrides=req.overrides,
        benchmark_candles=_aligned_benchmark(await _rs_benchmark_candles(req), bars[-120:]),
    )
    if card.status == "REJECT":
        gate_flags.append({"gate": "score", "status": "REJECT", "detail": f"score={card.score}"})
    elif (_drop := _min_score_drop(symbol, card, req.min_stock_score)):
        gate_flags.append(_scan_drop_flag("score", _drop))

    if (_drop := _direction_conviction_drop(symbol, card, _min_trend, req.direction, req.horizon)):
        gate_flags.append(_scan_drop_flag("direction_conviction", _drop))

    if _regime_headwind(regime_signal, _regime_gate):
        _conv = regime_signal["conviction_pct"]
        if req.regime_filter:
            # The scan drops on this ("regime headwind") only with the filter on.
            gate_flags.append({"gate": "regime_headwind", "status": "REJECT",
                               "detail": f"{_SCAN_DROP_PREFIX}regime headwind (conviction {_conv}%)"})
        else:
            gate_flags.append({"gate": "regime_headwind", "status": "CAUTION",
                               "detail": f"conviction {_conv}%"})

    # Strategy signal — the same resolution as the scan, so the backtest below
    # runs on the scan's (_bt_strategy, _bt_bars, _bt_params).
    signal = None
    _bt_strategy = _bt_bars = _bt_params = None
    if req.strategy == "mean_reversion_multi":
        _multi_shape = _multi_params(req)
        signal, _drop = _multi_signal(symbol, req, bars, _multi_shape)
        if signal is not None:
            # The backtest runs the same vote on the same shape object.
            _bt_strategy, _bt_bars, _bt_params = "mean_reversion_multi", bars, _multi_shape
    else:
        signal_fn = _SIGNAL_FNS.get(req.strategy)
        if signal_fn:
            signal_kwargs = _merge_strategy_params(
                req.strategy, req.direction, _SIGNAL_KWARGS.get(req.strategy, lambda r: {})(req),
                _params_horizon(req))
            _sig_bars = (_intraday_bars[-300:] if req.strategy in _INTRADAY_STRATEGIES
                         else bars[-SIGNAL_WINDOW_BARS:])
            # Pass live price so signal uses current price, not yesterday's close.
            _live_price = price if req.strategy not in _INTRADAY_STRATEGIES else None
            try:
                signal = signal_fn(_sig_bars, direction=req.direction,
                                   current_price=_live_price, **signal_kwargs)
            except Exception:
                # The scan drops here too (via its outer `except`, reason str(exc)).
                signal = None
            if signal is not None:
                _bt_strategy = req.strategy
                _bt_bars = _intraday_bars if req.strategy in _INTRADAY_STRATEGIES else bars
                _bt_params = signal_kwargs
        _drop = _no_setup_drop(symbol, req.strategy) if signal is None else None
    if _drop:
        gate_flags.append(_scan_drop_flag("signal", _drop))

    # Backtest + confidence
    bt_result = None
    _bt_hold = None
    conf_val = conf_txt = None
    if signal is not None:
        _bt_commission = _backtest_commission()
        _bt_hold = hold_for_backtest(req.horizon, _bt_strategy, req.hold_max_days)
        _bt_key = _backtest_key(symbol, _bt_strategy, req.direction, _bt_bars, _bt_params,
                                 commission=_bt_commission, min_trades=req.bt_min_trades,
                                 min_win_rate=req.bt_min_win_rate, hold_max_days=_bt_hold)
        bt_result = _get_backtest_cached(_bt_key)
        if bt_result is None:
            bt_result = await asyncio.get_running_loop().run_in_executor(
                _BACKTEST_POOL,
                functools.partial(run_strategy_backtest, _bt_bars, strategy=_bt_strategy,
                                  direction=req.direction, min_trades=req.bt_min_trades,
                                  min_win_rate=req.bt_min_win_rate, params=_bt_params,
                                  commission=_bt_commission, hold_max_days=_bt_hold))
            # A refresh that landed after this request read its bars has already
            # evicted the symbol: storing now would put the pre-refresh result back
            # for _BACKTEST_TTL. It is still this request's result (T6, HYG-P1-F2).
            if not conf_invalidated_since(symbol, _bars_gen):
                _BACKTEST_CACHE[_bt_key] = (bt_result, time.time() + _BACKTEST_TTL)
        if (_drop := _backtest_drop(symbol, bt_result)):
            gate_flags.append(_scan_drop_flag("backtest", _drop))
        # Asymmetric ATR override — a lone target or stop is ignored (both or neither).
        _atr_target = req.confidence_atr_mult_target
        _atr_stop = req.confidence_atr_mult_stop
        if _atr_target is None or _atr_stop is None:
            _atr_target = _atr_stop = None
        _ck = conf_cache_key(symbol, req.direction, req.horizon, _atr_target, _atr_stop, scoring_mode="stock")
        _cached = get_cached(_ck)
        if _cached is None:
            _res = await asyncio.to_thread(compute_confidence, bars, direction=req.direction,
                                           horizon=req.horizon, scoring_mode="stock",
                                           atr_mult_target=_atr_target, atr_mult_stop=_atr_stop)
            _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
            await set_cached(_ck, _cached, bars_generation=_bars_gen)
        conf_val = _cached["confidence"]
        _min_samples = int(load_backtest_cfg(req.horizon)["min_samples"])
        conf_txt = interpret(conf_val, sample_size=_cached["sample_size"], symbol=symbol,
                             min_samples=_min_samples)
        _unvalidated = conf_val is None
        _below_reject = (conf_val is not None and req.confidence_reject_below is not None
                         and conf_val < req.confidence_reject_below)
        _below_caution = (conf_val is not None and req.confidence_caution_below is not None
                          and conf_val < req.confidence_caution_below)
        # Mirrors _process_stock's cap: CAUTION at most, never lowers a REJECT.
        # Applied below the reject threshold too (the scan drops the symbol
        # there), so worse confidence can never read better than milder. A
        # missing confidence is Unvalidated and never PASSes (P0A A5).
        if (_unvalidated or _below_reject or _below_caution) and card.status == "PASS":
            card = dataclasses.replace(card, status="CAUTION")
        if _unvalidated:
            gate_flags.append({"gate": "confidence", "status": "CAUTION",
                               "detail": f"Unvalidated: {_cached['sample_size']} non-overlapping "
                                         f"samples (< {_min_samples})"})
        elif _below_reject:
            gate_flags.append({"gate": "confidence", "status": "REJECT",
                               "detail": f"{conf_val:.0f}% < {req.confidence_reject_below:.0f}%"})
        elif _below_caution:
            gate_flags.append({"gate": "confidence", "status": "CAUTION",
                               "detail": f"{conf_val:.0f}% < {req.confidence_caution_below:.0f}%"})

    if req.direction == "Bearish":
        if card.status == "PASS":
            card = dataclasses.replace(card, status="CAUTION")
        gate_flags.append({"gate": "unvalidated", "status": "CAUTION",
                           "detail": BEARISH_UNVALIDATED_MESSAGE})

    # Earnings veto over the hold (B6), as the scan applies it. Unknown
    # earnings is not a veto on stocks (see _stock_earnings_veto).
    earnings_days = await _earnings_days_for(symbol)
    _status, _earn_flag = _stock_earnings_veto(card.status, earnings_days,
                                               _resolve_stock_veto_days(req))
    if _status != card.status:
        card = dataclasses.replace(card, status=_status)
    if _earn_flag is not None:
        gate_flags.append(_earn_flag)

    # Event proximity
    next_event_days = next_event_label = None
    if quote:
        for field_name, label in [("earnings_date", "earnings"), ("ex_dividend_date", "dividend")]:
            raw = quote.get(field_name)
            if raw:
                try:
                    ev = date.fromisoformat(str(raw)[:10])
                    days = (ev - date.today()).days
                    if days >= 0 and (next_event_days is None or days < next_event_days):
                        next_event_days, next_event_label = days, label
                except (ValueError, TypeError):
                    pass

    return _AnalyzeCore(
        company=company or symbol, price=price, card=card, regime_signal=regime_signal,
        fundamentals=_fh, signal=signal, bt_result=bt_result, conf_val=conf_val, conf_txt=conf_txt,
        sector_rs_pct=None, next_event_days=next_event_days, next_event_label=next_event_label,
        daily_bars=bars, intraday_bars=_intraday_bars, gate_flags=gate_flags,
        earnings_days=earnings_days, earnings_veto=_earn_flag is not None,
        bt_hold=_bt_hold,
    )


def _ema_trend(closes: list[float], period: int = 200) -> "EmaTrendOut | None":
    if len(closes) < period + 1:
        return None
    ema = _regime_ema(closes, period)
    if ema is None:
        return None
    last = closes[-1]
    state = "Above" if last >= ema else "Below"
    return EmaTrendOut(state=state, ema=round(ema, 2), last=round(last, 2),
                       status="PASS" if state == "Above" else "CAUTION")


def _regime_block_for_horizon(
    symbol: str,
    bars: list[dict],
    horizon: str,
    direction: str,
    intraday_bars: list[dict] | None = None,
) -> "RegimeHorizonBlock":
    rcfg = _load_regime_cfg(horizon)
    if rcfg["timeframe"] == "15min":
        # Use pre-loaded bars when provided to avoid blocking the event loop.
        rbars = completed_intraday_bars(intraday_bars) if intraday_bars is not None else []
    else:
        rbars = bars

    def _empty() -> "RegimeHorizonBlock":
        return RegimeHorizonBlock(horizon=horizon, timeframe=rcfg["timeframe"], state="Unknown",
                                  p_stay=0.0, stability="Fragile", regime_age_days=0,
                                  avg_regime_duration=0.0, conviction_pct=0,
                                  conviction_label="Neutral", insufficient_data=True)

    if not rbars or len(rbars) < rcfg.get("min_obs", 10):
        return _empty()
    omm = compute_omm([b["close"] for b in rbars], direction=direction,
                      lookback=rcfg["lookback"], window=rcfg["window"], min_obs=rcfg["min_obs"])
    if not omm:
        return _empty()
    dh = None
    try:
        dh = compute_directional_hmm(rbars)
    except Exception:
        pass
    return RegimeHorizonBlock(
        horizon=horizon, timeframe=rcfg["timeframe"], state=omm.state, p_stay=omm.p_stay,
        stability=omm.stability, regime_age_days=omm.regime_age_days,
        avg_regime_duration=omm.avg_regime_duration, conviction_pct=omm.conviction_pct,
        conviction_label=omm.conviction_label, hmm_state=(dh.state if dh else None),
        alignment=alignment(omm.state, dh.state if dh else None),
        transition_row=list(omm.transition_row),
        state_order=list(omm.state_order),
        insufficient_data=False)


async def _sector_context(symbol: str, closes: list[float]) -> "tuple[SectorTileOut, SectorRsOut]":
    name, etf = sector_for_symbol(symbol)
    benchmark = etf or "SPY"
    end = date.today()
    start = end - timedelta(days=_HISTORY_YEARS * 365)
    try:
        bench_bars = await get_historical_bars(benchmark, start, end)
        bench = [b["close"] for b in bench_bars] if bench_bars else []
    except Exception:
        bench = []
    rs = SectorRsOut(benchmark=benchmark)
    for attr, lookback in (("d1", 1), ("w1", 5), ("m1", 21)):
        if len(closes) > lookback and len(bench) > lookback:
            s = (closes[-1] - closes[-(lookback + 1)]) / closes[-(lookback + 1)] * 100
            bm = (bench[-1] - bench[-(lookback + 1)]) / bench[-(lookback + 1)] * 100
            setattr(rs, attr, round(s - bm, 2))
    tile = SectorTileOut(name=name or "Unknown", etf=etf, change_pct=None)
    return tile, rs


async def _market_backdrop() -> "MarketBackdropOut | None":
    """Cheap macro backdrop — uses compute_overall_regime() (no heavy recompute)."""
    try:
        overall = await asyncio.to_thread(compute_overall_regime)
        return MarketBackdropOut(overall=overall, direction=None, vix=None)
    except Exception:
        return None


@router.post("/analyze-stock")
async def analyze_stock(req: StockAnalysisRequest) -> StockAnalysisOut:
    _reject_unsupported_multi_variants(req)
    # DOCC-1 S3: the Analysis page mirrors the scan (A5-ANALYSIS-MIRRORS-SCAN),
    # so it must not show PASS where the scan refuses on a missing or
    # misspelled money block. Same guards and same 500 as the stock scan core.
    try:
        _cfg_doc = _load_full_scoring_cfg()
    except (OSError, _yaml.YAMLError) as e:
        logger.error("ANALYZE %s aborted: scoring_rules.yaml unreadable: %s", req.symbol, e)
        raise HTTPException(status_code=500, detail=f"scoring_rules.yaml unreadable: {e}")
    if not isinstance(_cfg_doc, dict):
        _msg = f"scoring_rules.yaml must be a mapping, got {type(_cfg_doc).__name__}"
        logger.error("ANALYZE %s aborted: %s", req.symbol, _msg)
        raise HTTPException(status_code=500, detail=_msg)
    try:
        validate_money_blocks(_cfg_doc)
    except MoneyConfigError as e:
        logger.error("ANALYZE %s aborted on scoring_rules.yaml money blocks: %s", req.symbol, e)
        raise HTTPException(status_code=500, detail=str(e))
    # DOCC-2 S3: ALL THREE horizons, because this page builds a regime card for
    # each (`_regime_block_for_horizon`), not only the request's.
    try:
        validate_regime_block(_cfg_doc, REGIME_HORIZONS)
    except RegimeConfigError as e:
        logger.error("ANALYZE %s aborted on scoring_rules.yaml regime block: %s", req.symbol, e)
        raise HTTPException(status_code=500, detail=str(e))
    symbol = req.symbol.upper()
    is_index = _is_index(symbol)

    core = await _analyze_core(symbol, req)
    if core is None:
        raise HTTPException(status_code=404, detail=f"No usable data for {symbol}")

    card = core.card
    closes = [b["close"] for b in core.daily_bars]

    # Intraday bars already fetched inside _analyze_core — reuse to avoid a second call.
    intraday_bars = core.intraday_bars

    # Run all three regime blocks + sector context + backdrop concurrently,
    # each CPU-bound block in a thread so the event loop stays free.
    (intra_blk, swing_blk, pos_blk), (sector_tile, sector_rs), backdrop = await asyncio.gather(
        asyncio.gather(
            asyncio.to_thread(_regime_block_for_horizon, symbol, core.daily_bars, "Intraday", req.direction, intraday_bars),
            asyncio.to_thread(_regime_block_for_horizon, symbol, core.daily_bars, "Swing",    req.direction, None),
            asyncio.to_thread(_regime_block_for_horizon, symbol, core.daily_bars, "Position", req.direction, None),
        ),
        _sector_context(symbol, closes),
        _market_backdrop(),
    )
    regime_by_horizon: dict[str, RegimeHorizonBlock] = {
        "Intraday": intra_blk, "Swing": swing_blk, "Position": pos_blk,
    }

    strategy_out = backtest_out = None
    if core.signal is not None:
        strategy_out = StrategySignalOut(
            strategy=core.signal.strategy, entry_price=core.signal.entry_price,
            stop_price=core.signal.stop_price, target_price=core.signal.target_price,
            targets=list(core.signal.targets),
            rr_ratio=round(core.signal.rr_ratio, 2), atr=core.signal.atr, detail=core.signal.detail)
    if core.bt_result is not None:
        bt = core.bt_result
        backtest_out = BacktestOut(
            n_trades=bt.n_trades, win_rate=round(bt.win_rate, 3),
            total_return_pct=round(bt.total_return_pct, 2),
            max_drawdown_pct=round(bt.max_drawdown_pct, 2), expectancy=bt.expectancy,
            sharpe=bt.sharpe, confidence=getattr(bt, 'confidence', None), passes_gate=bt.passes_gate,
            summary_text=bt.summary_text, n_time_exits=bt.n_time_exits, hold_max_days=core.bt_hold)

    fundamentals_out = None
    if core.fundamentals is not None and not is_index:
        _fh = core.fundamentals
        fundamentals_out = FundamentalsOut(
            score=_fh.score, quality_label=_fh.quality_label, risk_label=_fh.risk_label,
            growth_score=_fh.growth_score, quality_score=_fh.quality_score,
            risk_score=_fh.risk_score, safety_flags=_fh.safety_flags, detail=_fh.detail)

    return StockAnalysisOut(
        symbol=symbol, company=core.company, price=core.price, direction=req.direction,
        stock_score=card.score, stock_status=card.status, is_index=is_index,
        stock_explanation=_stock_explanation_out(symbol, card),
        strategy=strategy_out, backtest=backtest_out,
        confidence=core.conf_val, confidence_text=core.conf_txt,
        sentiment=SentimentData(**core.regime_signal) if core.regime_signal else None,
        fundamentals=fundamentals_out,
        next_event_days=core.next_event_days, next_event_label=core.next_event_label,
        earnings_days=core.earnings_days, earnings_veto=core.earnings_veto,
        rules=[RuleContribution(name=r.name, status=r.status, score=r.score, detail=r.detail or {})
               for r in card.rules],
        gate_flags=[GateFlag(**g) for g in core.gate_flags],
        ema_trend=_ema_trend(closes), iv_rank=None,
        regime_by_horizon=regime_by_horizon, sector=sector_tile, sector_rs=sector_rs,
        market_backdrop=backdrop)


def _position_size(account: float, risk_pct: float | None, risk_fixed: float | None,
                   entry: float, stop: float) -> tuple[int, float]:
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return 0, 0.0
    # The caller resolves the fallback and applies the conviction multiplier
    # before this point; a `risk_pct or 0.01` here used to replace a None with
    # an UNSIZED 1% and so drop the multiplier.
    dollar_risk = risk_fixed if risk_fixed is not None else (account * risk_pct)
    # The 1e-9 is the fire path's (`auto_trader._sized_quantity`): a float
    # quotient such as 669.9999999999999 for an exact 670 must not lose a
    # share. Without it the card rounded DIFFERENTLY from the auto-trader on
    # exact boundaries (REGIME-SIZING-AUDIT r1 finding 3: conviction -36,
    # account 50,000, 1%, risk/share 0.25 -> 669 where the exact figure is 670).
    shares = max(1, int(dollar_risk / risk_per_share + 1e-9))
    return shares, round(dollar_risk, 2)


def _unique_setup_symbols(symbols):
    """Normalize before exclusions/evaluation, preserving first-occurrence tie order."""
    return list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))


async def _process_stock(
    symbol: str,
    req: StockScanRequest,
    scan_id: str,
    price_map: dict[str, dict],
    benchmark_closes: list[float],
    fund_gate: dict | None = None,
    rs_benchmark_candles: list[dict] | None = None,
    veto_days: int | None = None,
) -> PositionCardOut | dict:
    # Resolved OUTSIDE the `try` below, which converts every exception into a
    # per-symbol rejection: a malformed threshold has to propagate as an error,
    # not be reported to the user as though this one symbol had failed to
    # screen. `_execute_stock_scan_core` resolves the same value once before
    # dispatching any of these, so in the scan path this has already raised
    # before the first symbol is touched; the call is kept here so that direct
    # callers (the test suite) screen on the real gate rather than silently
    # running with it disabled.
    observe_evaluation(symbol)
    _min_trend = load_direction_conviction_min_trend(req.direction, req.horizon)
    # The scan resolves the earnings veto window once and passes it in; a
    # direct caller (the test suite) gets the same resolution here.
    if veto_days is None:
        veto_days = _resolve_stock_veto_days(req)
    observe_configuration("stocks.earnings_veto", {"veto_days": veto_days})
    async with _SCAN_SEM:
        try:
            end = date.today()
            start = end - timedelta(days=_HISTORY_YEARS * 365)
            # DB-first: reads from ohlcv_daily table; fetches delta from Tiingo if stale.
            # Eliminates parallel Tiingo calls for large universes (avoids rate-limit errors).
            # The generation is captured before the read: a refresh evicting this
            # symbol after it makes set_cached drop the confidence (audit R2-F1).
            _bars_gen = conf_generation()
            bars = await get_historical_bars(symbol, start, end)
            if not bars or len(bars) < 60:
                observe_terminal(symbol, "no_data", "insufficient_history")
                return {"symbol": symbol, "reason": "insufficient history"}

            # ONE 15-min fetch, when either consumer needs it (P3a item 12, plan
            # round 4 F1): the intraday strategies' signal + backtest, and the
            # 15-min regime (`regime.<h>.timeframe`). It used to be two fetches,
            # the signal's only for mean_reversion_vwap; reusing the signal's
            # would have left every other strategy's regime with the EMPTY
            # default of a fetch that never ran. The exception is kept for the
            # item-12 drop below, which is decided only from a fetch that ran.
            full_cfg = _load_full_scoring_cfg()
            observe_configuration("stocks.worker.scoring", full_cfg, symbol=symbol)
            rcfg = _load_regime_cfg(req.horizon)
            observe_configuration("stocks.worker.regime", rcfg, symbol=symbol)
            intraday_bars: list[dict] = []
            _intraday_fetch_exc: Exception | None = None
            if req.strategy in _INTRADAY_STRATEGIES or rcfg["timeframe"] == "15min":
                try:
                    intraday_bars = await asyncio.to_thread(
                        fetch_intraday_candles, symbol, "15min", _INTRADAY_FETCH_DAYS
                    )
                except Exception as exc:
                    logger.warning("fetch_intraday_candles failed for %s: %s", symbol, exc)
                    _intraday_fetch_exc = exc
                if (_drop := _intraday_history_drop(symbol, req.strategy, intraday_bars)):
                    observe_terminal(symbol, "no_data", "insufficient_intraday_history")
                    return _drop

            # Price fallback chain mirrors the options scan: Tradier batch quote →
            # last stored close (history table) → yfinance. Keeps the stock track
            # usable when Tradier is unavailable.
            quote = price_map.get(symbol)
            price = (float(quote.get("last") or 0) or None) if quote else None
            if not price:
                price = float(bars[-1]["close"]) or None

            async with httpx.AsyncClient(timeout=10) as client:
                if not price:
                    price = await fetch_price_async(client, symbol)
                if not price:
                    observe_terminal(symbol, "no_data", "missing_price")
                    return {"symbol": symbol, "reason": "no price data"}
                company = await fetch_company_name_async(client, symbol)

            if req.min_price is not None and price < req.min_price:
                observe_terminal(symbol, "filtered", "price_min", observations={"price": price}, thresholds={"min_price": req.min_price})
                return {"symbol": symbol, "reason": f"price ${price:.2f} < min"}
            if req.max_price is not None and price > req.max_price:
                observe_terminal(symbol, "filtered", "price_max", observations={"price": price}, thresholds={"max_price": req.max_price})
                return {"symbol": symbol, "reason": f"price ${price:.2f} > max"}

            # --- regime sentiment ---
            regime_signal = None
            if rcfg["timeframe"] == "15min":
                # A4b: completed bars only (decision A4B-DROP-FORMING-15MIN-BAR);
                # `intraday_bars` itself stays whole for the signal / backtest.
                regime_bars = completed_intraday_bars(intraday_bars)
            else:
                regime_bars = bars   # daily bars already fetched

            if regime_bars and len(regime_bars) >= rcfg.get("min_obs", 10):
                omm = compute_omm(
                    [b["close"] for b in regime_bars],
                    direction=req.direction,
                    lookback=rcfg["lookback"],
                    window=rcfg["window"],
                    min_obs=rcfg["min_obs"],
                )
                if omm:
                    dh = None
                    try:
                        dh = compute_directional_hmm(regime_bars)
                    except Exception as exc:
                        logger.debug("HMM unavailable for %s: %s", symbol, exc)
                    regime_signal = {
                        "horizon": req.horizon,
                        "timeframe": rcfg["timeframe"],
                        "state": omm.state,
                        "p_stay": omm.p_stay,
                        "stability": omm.stability,
                        "regime_age_days": omm.regime_age_days,
                        "avg_regime_duration": omm.avg_regime_duration,
                        "conviction_pct": omm.conviction_pct,
                        "conviction_label": omm.conviction_label,
                        "interpretation": omm.interpretation,
                        "hmm_state": dh.state if dh else None,
                        "alignment": alignment(omm.state, dh.state if dh else None),
                        "insufficient_data": False,
                    }

            # Fundamentals (skipped for intraday) — the gate already carries the
            # bearish overrides from services/fundamentals_gate.resolve_fundamentals_gate
            # (see the matching note in _analyze_core); no per-site re-application.

            _fh: FundamentalHealth | None = None
            if req.horizon.lower() != "intraday" and fund_gate is not None:
                _staleness = fund_gate.get("staleness_days", 90)
                _snap = await _get_fundamentals(symbol, staleness_days=_staleness)
                _fh = _score_fundamentals(_snap, req.direction, fund_gate) if _snap else None

            # Was four hand-written lines identical to the options scan's;
            # routed through the shared resolver 2026-09-19 so the two scans and
            # the auto-trader cannot drift on what an override means.
            _regime_gate = _resolve_regime_gate(
                full_cfg.get("regime_gate"),
                req.regime_headwind_caution_pct,
                req.regime_headwind_reject_pct,
            )
            observe_configuration("stocks.regime_gate", _regime_gate, symbol=symbol)

            # P3a item 12: drop where the auto-trader's fire would refuse.
            if (_drop := _regime_data_drop(symbol, req, full_cfg, _regime_gate, rcfg,
                                           regime_bars, _intraday_fetch_exc)):
                observe_terminal(symbol, "error" if _intraday_fetch_exc is not None else "no_data", "regime_fetch_failed" if _intraday_fetch_exc is not None else "regime_data_unavailable")
                return _drop

            card = score_stock(
                symbol=symbol,
                direction=req.direction,
                horizon=req.horizon,
                bars=bars[-120:],
                scoring_mode="stock",
                regime_signal=regime_signal,
                regime_gate=(_regime_gate or None) if regime_signal else None,
                fundamentals=_fh,
                fundamentals_gate=fund_gate,
                overrides=req.overrides,
                benchmark_candles=_aligned_benchmark(rs_benchmark_candles, bars[-120:]),
            )
            if card.status == "REJECT":
                observe_terminal(symbol, "filtered", "score_status", observations={"score": card.score, "status": card.status})
                return {"symbol": symbol, "reason": f"REJECT score={card.score}"}
            if (_drop := _min_score_drop(symbol, card, req.min_stock_score)):
                observe_terminal(symbol, "filtered", "score_min", observations={"score": card.score}, thresholds={"min_stock_score": req.min_stock_score})
                return _drop

            # Direction-conviction floor (shared with _analyze_core — A5c).
            # `_min_trend` was resolved at the top of this function.
            if (_drop := _direction_conviction_drop(symbol, card, _min_trend, req.direction, req.horizon)):
                return _drop

            if req.regime_filter and _regime_headwind(regime_signal, _regime_gate):
                observe_terminal(symbol, "filtered", "regime_headwind")
                return {"symbol": symbol, "reason": "regime headwind"}

            if req.strategy == "mean_reversion_multi":
                _multi_shape = _multi_params(req)
                observe_configuration("stocks.multi_params", _multi_shape, symbol=symbol)
                signal, _drop = _multi_signal(symbol, req, bars, _multi_shape)
                if _drop:
                    observe_terminal(symbol, "no_setup", "setup_not_returned", observations={"strategy": req.strategy})
                    return _drop
                # The backtest runs the same vote on the same shape object.
                _bt_strategy = "mean_reversion_multi"
                bt_bars = bars
                _bt_params = _multi_shape
            else:
                signal_fn = _SIGNAL_FNS.get(req.strategy)
                if not signal_fn:
                    observe_terminal(symbol, "error", "unsupported_strategy")
                    return {"symbol": symbol, "reason": f"unknown strategy {req.strategy}"}
                signal_kwargs = _merge_strategy_params(
                    req.strategy, req.direction,
                    _SIGNAL_KWARGS.get(req.strategy, lambda r: {})(req),
                    _params_horizon(req),
                )
                observe_configuration("stocks.strategy_params", signal_kwargs, symbol=symbol)
                # Intraday strategies use intraday bars for both signal and backtest.
                signal_bars = intraday_bars[-300:] if req.strategy in _INTRADAY_STRATEGIES else bars[-SIGNAL_WINDOW_BARS:]
                _live_price = price if req.strategy not in _INTRADAY_STRATEGIES else None
                signal = signal_fn(signal_bars, direction=req.direction,
                                   current_price=_live_price, **signal_kwargs)
                if signal is None:
                    observe_terminal(symbol, "no_setup", "setup_not_returned", observations={"strategy": req.strategy})
                    return _no_setup_drop(symbol, req.strategy)
                _bt_strategy = req.strategy
                bt_bars = intraday_bars if req.strategy in _INTRADAY_STRATEGIES else bars
                _bt_params = signal_kwargs

            _bt_commission = _backtest_commission()
            _bt_hold = hold_for_backtest(req.horizon, _bt_strategy, req.hold_max_days)
            _bt_key = _backtest_key(symbol, _bt_strategy, req.direction, bt_bars, _bt_params,
                                     commission=_bt_commission, min_trades=req.bt_min_trades,
                                     min_win_rate=req.bt_min_win_rate, hold_max_days=_bt_hold)
            _detail_inputs = dict(strategy=_bt_strategy, direction=req.direction,
                                  min_trades=req.bt_min_trades, min_win_rate=req.bt_min_win_rate,
                                  params=_bt_params, commission=_bt_commission, hold_max_days=_bt_hold)
            try:
                _detail_identity = _detail_key(symbol, bt_bars, _detail_inputs)
            except (ValueError, TypeError):
                _detail_identity = None
            bt_result = _get_backtest_cached(_bt_key)
            try:
                _detail = _cached_detail(_detail_identity, bt_result) if _detail_identity else None
            except Exception:
                _detail = None
            if bt_result is None:
                bt_result, _detail = await asyncio.get_running_loop().run_in_executor(
                    _BACKTEST_POOL,
                    functools.partial(_run_backtest_with_details, bt_bars, **_detail_inputs),
                )
                if not conf_invalidated_since(symbol, _bars_gen):
                    _BACKTEST_CACHE[_bt_key] = (bt_result, time.time() + _BACKTEST_TTL)
                    if _detail_identity:
                        try:
                            _remember_detail(_detail_identity, bt_result, _detail)
                        except Exception:
                            pass
            if (_drop := _backtest_drop(symbol, bt_result)):
                observe_terminal(symbol, "filtered", "backtest_gate", observations={"passes_gate": bt_result.passes_gate, "win_rate": getattr(bt_result, "win_rate", None), "n_trades": getattr(bt_result, "n_trades", None)}, thresholds={"min_trades": req.bt_min_trades, "min_win_rate": req.bt_min_win_rate})
                return _drop

            # Asymmetric ATR override — a lone target or stop is ignored (both or neither).
            _atr_target = req.confidence_atr_mult_target
            _atr_stop = req.confidence_atr_mult_stop
            if _atr_target is None or _atr_stop is None:
                _atr_target = _atr_stop = None
            _ck = conf_cache_key(symbol, req.direction, req.horizon, _atr_target, _atr_stop, scoring_mode="stock")
            _cached = get_cached(_ck)
            if _cached is None:
                _res = await asyncio.to_thread(
                    compute_confidence, bars, direction=req.direction, horizon=req.horizon,
                    scoring_mode="stock", atr_mult_target=_atr_target, atr_mult_stop=_atr_stop,
                )
                _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
                await set_cached(_ck, _cached, bars_generation=_bars_gen)
            conf_val = _cached["confidence"]
            conf_txt = interpret(conf_val, sample_size=_cached["sample_size"], symbol=symbol,
                                 min_samples=int(load_backtest_cfg(req.horizon)["min_samples"]))

            _SEVERITY = {"PASS": 0, "CAUTION": 1, "REJECT": 2}

            # Missing confidence is Unvalidated: a PASS card becomes CAUTION
            # (never lowers a REJECT) and the symbol is kept (P0A A5).
            if conf_val is None and card.status == "PASS":
                card = dataclasses.replace(card, status="CAUTION")

            if conf_val is not None and req.confidence_reject_below is not None:
                if conf_val < req.confidence_reject_below:
                    observe_terminal(symbol, "filtered", "confidence_gate", observations={"confidence": conf_val}, thresholds={"confidence_reject_below": req.confidence_reject_below})
                    return {
                        "symbol": symbol,
                        "reason": (
                            f"confidence gate REJECT: {conf_val:.0f}% "
                            f"< {req.confidence_reject_below:.0f}%"
                        ),
                    }
            if conf_val is not None and req.confidence_caution_below is not None:
                if conf_val < req.confidence_caution_below:
                    if _SEVERITY.get(card.status, 0) < _SEVERITY["CAUTION"]:
                        card = dataclasses.replace(card, status="CAUTION")

            gate_flags = []
            if req.direction == "Bearish":
                if card.status == "PASS":
                    card = dataclasses.replace(card, status="CAUTION")
                gate_flags.append(GateFlag(gate="unvalidated", status="CAUTION",
                                           detail=BEARISH_UNVALIDATED_MESSAGE))

            sizing_cfg = full_cfg.get("regime_sizing", {"enabled": False})
            _sizing = resolve_sizing(sizing_cfg)
            if _sizing is None:
                mult, sizing_basis = 1.0, "off"
            elif regime_signal:
                mult = _conviction_mult(regime_signal["conviction_pct"], sizing_cfg)
                sizing_basis = "measured"
            else:
                # THE FLOOR, NOT FULL SIZE: the 15-min fetch failed, there were
                # fewer than min_obs bars, or compute_omm returned nothing. This
                # used to be 1.0 -- the largest position on the worst input.
                # Mirrors the auto-trader (decision
                # SIZING-4-UNMEASURED-FLOOR-2026-09-24); this card's `shares` is
                # what StockSendDialog sends.
                mult, sizing_basis = _sizing[0], "floor:unmeasured"
            # The 1% default is resolved HERE, before the multiplier, so a
            # request with neither risk_pct nor risk_fixed_usd is conviction-
            # sized like any other (it used to fall through to a flat 1%).
            _base_pct = req.risk_pct if req.risk_pct is not None else _DEFAULT_RISK_PCT
            sized_risk_pct = _base_pct * mult
            sized_risk_fixed = (req.risk_fixed_usd * mult) if req.risk_fixed_usd is not None else None
            shares, dollar_risk = _position_size(
                req.account_size, sized_risk_pct, sized_risk_fixed,
                signal.entry_price, signal.stop_price,
            )

            # Sector RS vs benchmark
            horizon_period = {"Intraday": 2, "Swing": 20, "Position": 50}.get(req.horizon, 20)
            stock_closes_all = [b["close"] for b in bars]
            sector_rs_pct: float | None = None
            if len(stock_closes_all) > horizon_period and len(benchmark_closes) > horizon_period:
                stock_roc = (stock_closes_all[-1] - stock_closes_all[-(horizon_period + 1)]) / stock_closes_all[-(horizon_period + 1)] * 100
                bench_roc = (benchmark_closes[-1] - benchmark_closes[-(horizon_period + 1)]) / benchmark_closes[-(horizon_period + 1)] * 100
                sector_rs_pct = round(stock_roc - bench_roc, 2)

            # Event proximity from quote data
            next_event_days: int | None = None
            next_event_label: str | None = None
            if quote:
                for field_name, label in [("earnings_date", "earnings"), ("ex_dividend_date", "dividend")]:
                    raw = quote.get(field_name)
                    if raw:
                        try:
                            ev = date.fromisoformat(str(raw)[:10])
                            days = (ev - date.today()).days
                            if days >= 0 and (next_event_days is None or days < next_event_days):
                                next_event_days = days
                                next_event_label = label
                        except (ValueError, TypeError):
                            pass

            # Earnings veto over the hold (B6). Looked up only here, after
            # every drop gate, so a dropped symbol costs no lookup. Never drops
            # the candidate. Unknown earnings is not a veto on stocks (see
            # _stock_earnings_veto).
            earnings_days = await _earnings_days_for(symbol)
            _status, _earn_flag = _stock_earnings_veto(card.status, earnings_days, veto_days)
            if _status != card.status:
                card = dataclasses.replace(card, status=_status)
            if _earn_flag is not None:
                gate_flags.append(GateFlag(**_earn_flag))

            _artifact = await _original_artifact(
                _detail, scan_id=scan_id, symbol=symbol, strategy=_bt_strategy,
                direction=req.direction, horizon=req.horizon,
                interval='15m' if _bt_strategy in _INTRADAY_STRATEGIES else '1d',
                detail_key=_detail_identity,
            ) if _detail_identity else dict(backtest_artifact_status='capture_unavailable')
            return PositionCardOut(
                **_artifact,
                symbol=symbol, company=company or symbol, price=price, direction=req.direction,
                strategy=StrategySignalOut(
                    strategy=signal.strategy, entry_price=signal.entry_price,
                    stop_price=signal.stop_price, target_price=signal.target_price,
                    targets=list(signal.targets),
                    rr_ratio=round(signal.rr_ratio, 2), atr=signal.atr, detail=signal.detail,
                ),
                backtest=BacktestOut(
                    n_trades=bt_result.n_trades, win_rate=round(bt_result.win_rate, 3),
                    total_return_pct=round(bt_result.total_return_pct, 2),
                    max_drawdown_pct=round(bt_result.max_drawdown_pct, 2),
                    expectancy=bt_result.expectancy, sharpe=bt_result.sharpe,
                    confidence=bt_result.confidence, passes_gate=bt_result.passes_gate,
                    summary_text=bt_result.summary_text,
                    n_time_exits=bt_result.n_time_exits, hold_max_days=_bt_hold,
                ),
                stock_score=card.score, stock_status=card.status, gate_flags=gate_flags,
                shares=shares, dollar_risk=dollar_risk,
                dollar_size=round(shares * signal.entry_price, 2),
                sizing_basis=sizing_basis,
                confidence=conf_val, confidence_text=conf_txt,
                sector_rs_pct=sector_rs_pct,
                next_event_days=next_event_days, next_event_label=next_event_label,
                earnings_days=earnings_days, earnings_veto=_earn_flag is not None,
                sentiment=SentimentData(**regime_signal) if regime_signal else None,
                fundamentals=FundamentalsOut(
                    score=_fh.score, quality_label=_fh.quality_label, risk_label=_fh.risk_label,
                    growth_score=_fh.growth_score, quality_score=_fh.quality_score,
                    risk_score=_fh.risk_score, safety_flags=_fh.safety_flags, detail=_fh.detail,
                ) if _fh else None,
                params_horizon=_params_horizon(req),
                params_source=_params_source(req),
                stock_explanation=_stock_explanation_out(symbol, card),
            )
        except Exception as exc:
            observe_terminal(symbol, "error", "data_processing_failed")
            observe_data_failure(symbol)
            logger.exception("Error processing %s", symbol)
            return {"symbol": symbol, "reason": str(exc)}


@router.get('/stock-scan/last', response_model=StockScanResult | None)
async def get_last_stock_scan() -> StockScanResult | None:
    """Return the most recently completed stocks-mode scan, if any."""
    return _last_stock_result


@router.get('/stock-scan/last-request')
async def get_last_stock_scan_request() -> dict | None:
    """The request that produced GET /stock-scan/last's result, with its scan_id,
    so the Analysis page can replay it (A5, decision A5-MIRROR-LAST-SCAN-RUN).

    Served ONLY while status is "complete": that is the one state in which the
    two globals come from the same run. run_stock_scan's "running" write pairs
    the NEW request with the PREVIOUS result, and restore_stock_from_db turns a
    persisted "running" row into "idle" with that same mismatch."""
    if (_last_stock_status != "complete" or _last_stock_request is None
            or _last_stock_result is None):
        return None
    return {
        "scan_id": _last_stock_result.scan_id,
        "request": _last_stock_request.model_dump(mode="json", exclude_none=True),
    }


@router.get('/stock-scan/last-run', response_model=ScanSessionStatus)
async def get_last_stock_scan_status() -> ScanSessionStatus:
    """Return last-run metadata (status/timestamp/strategy) for stock-mode scans."""
    return ScanSessionStatus(
        status=_last_stock_status,
        updated_at=_last_stock_updated_at,
        strategy=_last_stock_request.strategy if _last_stock_request else None,
    )


@router.post("/stock-scan")
async def run_stock_scan(req: StockScanRequest, db: AsyncSession = Depends(get_db)) -> StockScanResult:
    _reject_unsupported_multi_variants(req)
    # NOTE: nothing serializes overlapping requests to this endpoint (unlike
    # scan.py's run_scan(), _SCAN_SEM above only throttles per-symbol work
    # inside _process_stock, not the endpoint itself) — two concurrent
    # POST /api/stock-scan calls race on the single shared "stock-current"
    # row/globals below (e.g. one request's failure-triggered idle-revert
    # could clobber another's genuine in-flight/completed state). Accepted as
    # a low-probability edge case given this app is single-user and the UI
    # only issues one stock scan at a time, rather than engineered around
    # with a lock/sequence-token.
    _prev_request, _prev_result, _prev_status = _last_stock_request, _last_stock_result, _last_stock_status
    await _upsert_stock_session(db, req=req, result=_prev_result, status="running")

    try:
        result = await run_reported_scan(req, category=req.category, trigger="manual",
            callback=lambda: _execute_stock_scan_core(req, db, previous_result=_prev_result))
        await _upsert_stock_session(db, req, result, status="complete")
        return result
    except Exception:
        # Revert to the request/result/status that were current before THIS
        # attempt started (not `req`/"idle" unconditionally) — otherwise a
        # scan that fails right after a genuinely completed one would
        # mislabel that still-valid prior result as "idle" instead of
        # "complete". `_prev_status` is "idle" only when there really was no
        # prior scan (module default / a fresh DB). Manual-run-only: Part 3's
        # scheduled runner never touches this global slot at all, so this
        # revert dance doesn't apply there — see _execute_stock_scan_core.
        await _upsert_stock_session(db, req=_prev_request, result=_prev_result, status=_prev_status)
        raise


async def _execute_stock_scan_core(
    req: StockScanRequest, db: AsyncSession, *, previous_result: StockScanResult | None = None,
) -> StockScanResult:
    """The actual stock-scan-running logic — same body run_stock_scan() has
    always run through result construction, with NO write to
    `_last_stock_request`/`_last_stock_result`/`_last_stock_status` (that
    happens in `_upsert_stock_session`, called only by run_stock_scan() and
    Part 3's scheduled runner after this returns, never from inside here).

    `previous_result` is accepted for signature symmetry with the
    options-mode core (_execute_scan_core) — Part 3's scheduled runner passes
    each entry's own prior successful result — but is unused internally
    today: unlike options mode, stock-mode scans compute no rank/score
    deltas (StockScanResult carries no `deltas` field), so there is nothing
    here to compute against it yet."""
    # STOCKS-HORIZON-T1 F1: the scheduled runner reaches this core without
    # run_stock_scan's check, and a stored schedule can turn invalid later (a
    # profile change raising min_confirmations past its variants). Refuse it
    # here so the run is recorded as an error with the reason, not as a
    # 0-candidate success. For run_stock_scan this repeats a check that has
    # already passed, so its HTTP behaviour is unchanged.
    _reject_unsupported_multi_variants(req)
    scan_id = new_rec_id()
    # Deliberately NOT hoisted to the module-level import at line 57 — tests
    # patch `app.data.universe_presets.expand_universe` (not
    # `app.routers.stock_scan.expand_universe`), which only takes effect if
    # this name is re-resolved from the source module at call time.
    from app.data.universe_presets import expand_universe, PresetUnavailableError

    if req.symbols:
        symbols = req.symbols
    else:
        try:
            symbols = expand_universe(req.universe)
        except PresetUnavailableError as e:
            raise HTTPException(status_code=400, detail=str(e))
    # Excluded symbols go into `rejected` below and count in `scanned` and
    # `failed_history`, so scanned == sum of buckets still holds.
    if req.category == "pullback":
        symbols = _unique_setup_symbols(symbols)
    symbols, _excluded = _drop_excluded_symbols(symbols, f"STOCK SCAN {scan_id}")
    _scanned = len(symbols) + len(_excluded)

    # Direction-conviction floor, validated BEFORE the batch quote call and the
    # SPY benchmark fetch below — a malformed threshold must not cost a
    # universe-wide round trip first. 500, not 4xx: the request is fine, the
    # SERVER's YAML is broken and no request can succeed until it is fixed, so
    # this must not be confused with the genuine 4xx this endpoint already
    # raises for a bad user override. HTTPException serialises `detail` at any
    # status, so the message naming the offending key survives to the UI and to
    # the scheduled path's `record_scheduled_scan_run(error=str(exc))`.
    #
    # The explicit log line is NOT redundant: this app installs no exception
    # handler or logging middleware, and starlette's ExceptionMiddleware returns
    # an HTTPException WITHOUT logging it — so raising a 500 here would
    # otherwise leave no server-side trace at all.
    try:
        _min_trend = load_direction_conviction_min_trend(req.direction, req.horizon)
    except ValueError as e:
        logger.error("STOCK SCAN %s aborted on malformed scoring_rules.yaml: %s", scan_id, e)
        raise HTTPException(status_code=500, detail=str(e))

    # regime_sizing, validated in the same place, for the same reason, and with
    # the same 500 — but it is the one block on this list that changes MONEY
    # rather than which names come back: it multiplies the share count every
    # card below carries. So it is validated ONCE here instead of being left to
    # the per-symbol worker, where the `asyncio.gather(..., return_exceptions=True)`
    # below would turn one broken key into a universe of rejected symbols.
    #
    # AN ABSENT BLOCK NOW REFUSES (DOCC-1, decision
    # DOCC-9.6-MONEY-BLOCKS-REQUIRED-2026-09-28). `validate_money_blocks` below
    # refuses a missing or null regime_sizing / regime_gate / confidence_gate /
    # fundamentals_gate, an `enabled` that is not a real bool, and any unknown
    # key inside them (DOCC-9.8) -- all of which used to read as "off" or as
    # the key's default. Off is `enabled: false`. A block that is PRESENT and
    # has an unusable value still refuses through resolve_sizing, unchanged.
    #
    # The document itself is loaded inside the same guard: one that fails to
    # read or parse, or parses to a non-mapping, used to raise past
    # `except SizingConfigError` as a bare 500 with no detail and no log line.
    try:
        _cfg_doc = _load_full_scoring_cfg()
        observe_configuration("stocks.scoring", _cfg_doc)
    except (OSError, _yaml.YAMLError) as e:
        logger.error("STOCK SCAN %s aborted: scoring_rules.yaml unreadable: %s", scan_id, e)
        raise HTTPException(status_code=500, detail=f"scoring_rules.yaml unreadable: {e}")
    if not isinstance(_cfg_doc, dict):
        _msg = f"scoring_rules.yaml must be a mapping, got {type(_cfg_doc).__name__}"
        logger.error("STOCK SCAN %s aborted: %s", scan_id, _msg)
        raise HTTPException(status_code=500, detail=_msg)
    try:
        validate_money_blocks(_cfg_doc)
    except MoneyConfigError as e:
        logger.error("STOCK SCAN %s aborted on scoring_rules.yaml money blocks: %s", scan_id, e)
        raise HTTPException(status_code=500, detail=str(e))
    # DOCC-2 S1 (decision DOCC-2-REGIME-BLOCK-REFUSES-2026-09-28): checked once
    # here, so a broken regime.<horizon> is one named 500 instead of a bare
    # KeyError per symbol that `gather(..., return_exceptions=True)` turned into
    # a universe of rejected names with nothing naming the file.
    try:
        validate_regime_block(_cfg_doc, (req.horizon,))
    except RegimeConfigError as e:
        logger.error("STOCK SCAN %s aborted on scoring_rules.yaml regime block: %s", scan_id, e)
        raise HTTPException(status_code=500, detail=str(e))
    try:
        resolve_sizing(_cfg_doc.get("regime_sizing"))
    except SizingConfigError as e:
        logger.error("STOCK SCAN %s aborted on unusable regime_sizing: %s", scan_id, e)
        raise HTTPException(status_code=500, detail=str(e))

    # Pre-fetch all prices in one Tradier call (removes 519 individual HTTP requests)
    try:
        price_map = await asyncio.to_thread(fetch_quotes, symbols)
    except Exception as exc:
        logger.warning("stock_scan: batch price fetch failed (%s) — falling back to empty map", exc)
        price_map = {}

    # Fetch SPY closes once for sector RS calculation
    benchmark_closes: list[float] = []
    try:
        spy_end = date.today()
        spy_start = spy_end - timedelta(days=_HISTORY_YEARS * 365)
        spy_bars = await get_historical_bars("SPY", spy_start, spy_end)
        benchmark_closes = [b["close"] for b in spy_bars] if spy_bars else []
    except Exception:
        pass   # RS column shows None — non-fatal

    fund_gate = _resolve_fundamentals_gate(req)
    observe_configuration("stocks.fundamentals_gate", fund_gate)
    # Fetched once for the whole universe; None unless the trend method is
    # relative_strength (see _rs_benchmark_candles).
    rs_benchmark_candles = await _rs_benchmark_candles(req)
    # Earnings veto window, max(reject_days, hold), resolved once (B6).
    veto_days = _resolve_stock_veto_days(req)
    observe_configuration("stocks.earnings_veto", {"veto_days": veto_days})
    tasks = [_process_stock(s, req, scan_id, price_map, benchmark_closes, fund_gate=fund_gate,
                            rs_benchmark_candles=rs_benchmark_candles, veto_days=veto_days)
             for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    candidates, rejected = [], []
    for _x in _excluded:
        rejected.append({"symbol": _x.symbol, "reason": f"Excluded (data): {_x.reason}"})
    # gather keeps input order, so each raised exception is named by its symbol.
    for sym, r in zip(symbols, results):
        if isinstance(r, Exception):
            observe_terminal(sym, "error", "data_processing_failed")
            observe_data_failure(sym)
            rejected.append({"symbol": sym, "reason": str(r)})
        elif isinstance(r, PositionCardOut):
            candidates.append(r)
        else:
            rejected.append(r)

    # ── Shortlist cap ─────────────────────────────────────────────────────────
    # Rank BEFORE cutting. `candidates` arrives in universe-file order (gather
    # keeps input order), so slicing it straight kept whichever names come first
    # in sp500.csv and silently dropped better setups further down. The Stocks
    # twin of the options-path fix in scan.py's "Shortlist cap" section.
    #
    # Key: stock_status (PASS before CAUTION, anything else after), then
    # stock_score descending, then backtest-derived confidence descending with
    # an unmeasured confidence (None) after every measured one. Python's sort
    # is stable, so an exact tie keeps universe order. Sorted even when nothing
    # is cut: the frontend's rank deltas (computeStockDeltas) read list position.
    candidates.sort(key=_shortlist_rank_key)
    # No upper clamp (the options path clamps to 50): here every candidate is
    # already fully built before the cut, so a large cap costs nothing, and
    # clamping would silently override an explicit request or a saved schedule.
    original_count = len(candidates)
    _cap = req.shortlist_max_candidates
    observe_configuration("stocks.shortlist", {"max_candidates": _cap})
    shortlist_truncated = original_count > _cap
    # A trimmed name is recorded, not dropped on the floor: it goes into
    # `rejected` so the user can see what the cap cost them. The literal prefix
    # (not an f-string on _SHORTLIST_REASON_PREFIX) keeps it visible to
    # test_every_stock_reason_producer_is_classified's source scan.
    for _k, _c in enumerate(candidates[_cap:], start=_cap + 1):
        observe_terminal(_c.symbol, "filtered", "shortlist_cap", observations={"rank": _k, "original_count": original_count}, thresholds={"cap": _cap})
        _conf = f"{_c.confidence}%" if _c.confidence is not None else "n/a"
        rejected.append({
            "symbol": _c.symbol,
            "reason": f"Shortlist cap: {_c.stock_status} score {_c.stock_score} "
                      f"confidence {_conf} ranked {_k} of {original_count} (cap {_cap})",
        })
    candidates = candidates[:_cap]
    for candidate in candidates:
        observe_terminal(candidate.symbol, "accepted", "candidate_returned")

    _direction_banner: str | None = None
    # The pipeline's `failed_direction`: a measured trend below the floor only
    # ("direction_conviction:" does not match the unmeasured prefix).
    _dir_filtered = sum(
        1 for r in rejected
        if isinstance(r, dict) and r.get("reason", "").startswith("direction_conviction:")
    )
    # The BANNER counts both direction-gate reasons, measured-below and
    # unmeasured ("no data"), since both are this gate's removals.
    _dir_removed = sum(
        1 for r in rejected
        if isinstance(r, dict) and r.get("reason", "").startswith(
            ("direction_conviction:", "direction_conviction_unmeasured:"))
    )
    if not candidates and _dir_removed > 0:
        # Counts, not a cause: the gate often removes a handful while other
        # gates remove the rest, and blaming "market structure" for that told
        # the user something the scan did not measure.
        _floor = f" (trend below {_min_trend:g})" if _min_trend is not None else ""
        _rest = ("" if _dir_removed >= _scanned
                 else "; the rest were removed by other gates — see the pipeline")
        _direction_banner = (
            f"No {req.direction.lower()} candidates survived. The direction-conviction gate "
            f"removed {_dir_removed} of {_scanned}{_floor}{_rest}."
        )
    elif candidates and all(c.stock_status == "CAUTION" for c in candidates):
        _direction_banner = (
            f"No strong {req.direction.lower()} setups detected. "
            "All candidates are CAUTION-grade — consider reducing size or waiting for a clearer signal."
        )

    def _bucket(r) -> str:
        return classify_stock_rejection(r.get("reason", "") if isinstance(r, dict) else "")

    _pipeline = StockPipeline(
        scanned=_scanned,
        failed_history=sum(1 for r in rejected if _bucket(r) == "failed_history"),
        failed_score=sum(1 for r in rejected if _bucket(r) == "failed_score"),
        failed_signal=sum(1 for r in rejected if _bucket(r) == "failed_signal"),
        failed_backtest=sum(1 for r in rejected if _bucket(r) == "failed_backtest"),
        failed_regime=sum(1 for r in rejected if _bucket(r) == "failed_regime"),
        failed_direction=_dir_filtered,
        failed_direction_unmeasured=sum(
            1 for r in rejected if _bucket(r) == "failed_direction_unmeasured"),
        direction_min_trend=_min_trend,
        failed_shortlist=original_count - len(candidates),
        other_rejected=sum(1 for r in rejected if _bucket(r) == "other_rejected"),
        candidates=len(candidates),
    )
    logger.info(
        "STOCK SCAN pipeline: scanned=%d hist_fail=%d score_fail=%d signal_fail=%d bt_fail=%d regime_fail=%d direction_fail=%d shortlist_trim=%d other=%d candidates=%d",
        _pipeline.scanned, _pipeline.failed_history, _pipeline.failed_score,
        _pipeline.failed_signal, _pipeline.failed_backtest, _pipeline.failed_regime,
        _pipeline.failed_direction, _pipeline.failed_shortlist,
        _pipeline.other_rejected, _pipeline.candidates,
    )
    result = StockScanResult(
        scan_id=scan_id, timestamp=datetime.now(timezone.utc).isoformat(),
        candidates=candidates, rejected=rejected, pipeline=_pipeline,
        original_count=original_count, shortlist_truncated=shortlist_truncated,
        direction_banner=_direction_banner, veto_days=veto_days,
    )
    return result


_FIB_ALLOWED_OVERRIDE_KEYS = frozenset({
    "fib_swing_lookback",
    "fib_levels",
    "fib_tolerance_pct",
    "impulse_min_pct",
    "retracement_recency_bars",
    "ema_filter_period",
})
_FIB_INT_OVERRIDE_KEYS = frozenset({"fib_swing_lookback", "retracement_recency_bars", "ema_filter_period"})

_FIB_DEFAULTS = {
    "fib_swing_lookback": 100,
    "fib_levels": [38.2, 61.8],
    "fib_tolerance_pct": 0.015,
    "impulse_min_pct": 0.08,
    "retracement_recency_bars": 40,
    "ema_filter_period": 20,
}


class FibPullbackScanRequest(BaseModel):
    symbols: list[str] = []
    direction: Literal["Bullish", "Bearish"] = "Bullish"
    params_override: dict | None = None
    universe: list[str] | None = None


@router.post("/scan/fib-pullback")
async def fib_pullback_scan(body: FibPullbackScanRequest, response: Response = None) -> list[dict]:
    return await run_reported_scan(body, category="fib", trigger="manual",
        callback=lambda: _fib_pullback_scan_core(body), response=response)


async def _fib_pullback_scan_core(body: FibPullbackScanRequest) -> list[dict]:
    """Scan symbols for Fibonacci retracement setups using fibonacci_pullback_detail."""
    from app.services.strategy_engine import fibonacci_pullback_detail

    scan_id = new_rec_id()
    end = date.today()
    start = end - timedelta(days=365)

    if body.universe:
        try:
            symbols_to_scan = expand_universe(body.universe)
        except PresetUnavailableError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        symbols_to_scan = [s.strip().upper() for s in body.symbols if s.strip()]

    symbols_to_scan = _unique_setup_symbols(symbols_to_scan)
    if not symbols_to_scan:
        observe_resolution([], [], [])
        return []

    # STOCKS-HORIZON-P0A A2: no `rejected` list here, so excluded symbols are
    # skipped and named in one INFO line.
    symbols_to_scan, _excluded = _drop_excluded_symbols(symbols_to_scan, "fib-pullback scan")
    if _excluded:
        logger.info("fib-pullback scan: skipped %d excluded symbol(s): %s",
                    len(_excluded), ", ".join(x.symbol for x in _excluded))

    scan_params: dict = dict(_FIB_DEFAULTS)
    if body.params_override:
        unknown = set(body.params_override) - _FIB_ALLOWED_OVERRIDE_KEYS
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown override keys: {sorted(unknown)}")
        coerced: dict = {}
        for k, v in body.params_override.items():
            if k in _FIB_INT_OVERRIDE_KEYS:
                try:
                    coerced[k] = int(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Override key '{k}' must be an integer")
                if k == "fib_swing_lookback" and coerced[k] < 10:
                    raise HTTPException(status_code=422, detail="fib_swing_lookback must be >= 10")
            elif k == "fib_levels":
                if not isinstance(v, list):
                    raise HTTPException(status_code=422, detail="fib_levels must be a list of numbers")
                if len(v) == 0:
                    raise HTTPException(status_code=422, detail="fib_levels must contain at least one level")
                _VALID_FIB_LEVELS = {23.6, 38.2, 50.0, 61.8, 78.6}
                parsed_levels = [float(x) for x in v]
                invalid_levels = [x for x in parsed_levels if x not in _VALID_FIB_LEVELS]
                if invalid_levels:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Invalid fib_levels values: {invalid_levels}. Allowed: {sorted(_VALID_FIB_LEVELS)}",
                    )
                coerced[k] = parsed_levels
            else:
                try:
                    coerced[k] = float(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Override key '{k}' must be a number")
                if k == "fib_tolerance_pct" and not (0 < coerced[k] <= 0.20):
                    raise HTTPException(status_code=422, detail="fib_tolerance_pct must be between 0 (exclusive) and 0.20")
                if k == "impulse_min_pct" and not (0.0 <= coerced[k] <= 0.50):
                    raise HTTPException(status_code=422, detail="impulse_min_pct must be between 0 and 0.50")
        scan_params.update(coerced)

    observe_configuration("fib.params", scan_params)
    results: list[dict] = []
    missing_data_count = 0
    for sym in symbols_to_scan:
        sym = sym.strip().upper()
        if not sym:
            continue
        observe_evaluation(sym)
        try:
            bars = await get_historical_bars(sym, start, end)
        except Exception as exc:
            observe_terminal(sym, "error", "history_fetch_failed")
            observe_data_failure(sym)
            logger.warning("fib-pullback scan: get_bars failed for %s — %s", sym, exc)
            continue
        if not bars:
            observe_terminal(sym, "no_data", "missing_history")
            missing_data_count += 1
            continue
        try:
            fib = fibonacci_pullback_detail(
                bars,
                body.direction,
                fib_swing_lookback=scan_params["fib_swing_lookback"],
                fib_levels=scan_params["fib_levels"],
                fib_tolerance_pct=scan_params["fib_tolerance_pct"],
                impulse_min_pct=scan_params["impulse_min_pct"],
                retracement_recency_bars=scan_params["retracement_recency_bars"],
            )
            at_level, dist_pct, level_hit = fib["at_level"], fib["dist_pct"], fib["label"]
        except Exception as exc:
            observe_terminal(sym, "error", "signal_processing_failed")
            observe_data_failure(sym)
            logger.warning("fib-pullback scan: signal failed for %s — %s", sym, exc)
            continue
        if level_hit is None:
            observe_terminal(sym, "no_setup", "fib_level_not_returned")
            # Insufficient bars or no swing found — skip
            continue

        # EMA trend filter: price must be on the correct side of the EMA.
        # Bullish: close > EMA; Bearish: close < EMA. 0 disables.
        ema_period = int(scan_params["ema_filter_period"])
        if ema_period > 0 and len(bars) >= ema_period:
            closes = [b["close"] for b in bars]
            k = 2 / (ema_period + 1)
            ema_val = sum(closes[:ema_period]) / ema_period
            for c in closes[ema_period:]:
                ema_val = c * k + ema_val * (1 - k)
            current_close = closes[-1]
            if body.direction == "Bullish" and current_close < ema_val:
                observe_terminal(sym, "filtered", "ema_side", observations={"current_close": current_close, "ema_value": ema_val, "direction": body.direction}, thresholds={"ema_period": ema_period})
                continue
            if body.direction == "Bearish" and current_close > ema_val:
                observe_terminal(sym, "filtered", "ema_side", observations={"current_close": current_close, "ema_value": ema_val, "direction": body.direction}, thresholds={"ema_period": ema_period})
                continue

        # Confidence: 100 if at level, scaled by proximity otherwise
        tol = scan_params["fib_tolerance_pct"] * 100  # convert to pct units
        if dist_pct is None:
            confidence = 0
        elif at_level:
            confidence = max(60, round(100 - (dist_pct / tol) * 40))
        else:
            confidence = max(0, round(60 - ((dist_pct - tol) / tol) * 30))
        _bt_strategy = "fibonacci_pullback"
        _bt_commission = _backtest_commission()
        _bt_hold = hold_for_backtest("Swing", _bt_strategy, None)
        _detail_inputs = dict(
            strategy=_bt_strategy,
            direction=body.direction,
            params=scan_params,
            commission=_bt_commission,
            hold_max_days=_bt_hold,
        )
        try:
            _detail_identity = _detail_key(sym, bars, _detail_inputs)
        except (ValueError, TypeError):
            _detail_identity = None

        try:
            bt_result, _detail = await asyncio.get_running_loop().run_in_executor(
                _BACKTEST_POOL,
                functools.partial(_run_backtest_with_details, bars, **_detail_inputs),
            )
        except Exception:
            bt_result, _detail = None, None

        _artifact = await _original_artifact(
            _detail,
            scan_id=scan_id,
            symbol=sym,
            strategy=_bt_strategy,
            direction=body.direction,
            horizon="Swing",
            interval="1d",
            detail_key=_detail_identity,
        ) if _detail_identity else dict(backtest_artifact_status="capture_unavailable")

        results.append({
            "symbol": sym,
            "direction": body.direction,
            "fib_level_hit": level_hit,
            "fib_dist_pct": dist_pct,
            "at_level": at_level,
            "confidence": confidence,
            # STOCK-PRES-P1: the swing low/high the Fib levels were measured from.
            "fib_swing": {"low": fib["swing_low"], "high": fib["swing_high"]},
            **_artifact,
        })

    # Sort: at-level hits first, then by proximity ascending (closer = better rank).
    results.sort(key=lambda r: (
        not r["at_level"],  # False (0) = at-level → sorts first
        r["fib_dist_pct"] if r["fib_dist_pct"] is not None else float("inf"),
    ))
    if symbols_to_scan and missing_data_count == len(symbols_to_scan):
        observe_no_data()
    for row in results:
        observe_terminal(row["symbol"], "accepted", "candidate_returned")
    return results


@router.post("/scan/prebreakout")
async def prebreakout_scan(body: PreBreakoutScanRequest, response: Response = None) -> list[dict]:
    return await run_reported_scan(body, category="prebreakout", trigger="manual",
        callback=lambda: _prebreakout_scan_core(body), response=response)


async def _prebreakout_scan_core(body: PreBreakoutScanRequest) -> list[dict]:
    """Scan symbols for pre-breakout consolidation setups using breakout_setup_signal."""
    scan_id = new_rec_id()
    end = date.today()
    start = end - timedelta(days=365)

    # Resolve symbol list: universe takes precedence over manual symbols list
    if body.universe:
        try:
            symbols_to_scan = expand_universe(body.universe)
        except PresetUnavailableError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        symbols_to_scan = [s.strip().upper() for s in body.symbols if s.strip()]

    symbols_to_scan = _unique_setup_symbols(symbols_to_scan)
    if not symbols_to_scan:
        observe_resolution([], [], [])
        return []

    # STOCKS-HORIZON-P0A A2: no `rejected` list here, so excluded symbols are
    # skipped and named in one INFO line.
    symbols_to_scan, _excluded = _drop_excluded_symbols(symbols_to_scan, "prebreakout scan")
    if _excluded:
        logger.info("prebreakout scan: skipped %d excluded symbol(s): %s",
                    len(_excluded), ", ".join(x.symbol for x in _excluded))

    base_params = get_active("breakout_setup", body.direction)
    if body.params_override:
        unknown = set(body.params_override) - _ALLOWED_OVERRIDE_KEYS
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown override keys: {sorted(unknown)}")
        # Coerce params to their expected types
        coerced: dict = {}
        for k, v in body.params_override.items():
            if k in _INT_OVERRIDE_KEYS:
                try:
                    coerced[k] = int(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Override key '{k}' must be an integer")
            elif k in ("fib_enabled", "require_trend"):
                coerced[k] = bool(v)
            elif k == "fib_levels":
                if not isinstance(v, list):
                    raise HTTPException(status_code=422, detail="fib_levels must be a list of numbers")
                coerced[k] = [float(x) for x in v]
            else:
                coerced[k] = float(v) if isinstance(v, (int, float)) else v
        base_params.update(coerced)

    observe_configuration("prebreakout.params", base_params)
    results: list[dict] = []
    missing_data_count = 0
    for sym in symbols_to_scan:
        sym = sym.strip().upper()
        if not sym:
            continue
        observe_evaluation(sym)
        try:
            bars = await get_historical_bars(sym, start, end)
        except Exception as exc:
            observe_terminal(sym, "error", "history_fetch_failed")
            observe_data_failure(sym)
            logger.warning("prebreakout scan: get_bars failed for %s — %s", sym, exc)
            continue
        if not bars:
            observe_terminal(sym, "no_data", "missing_history")
            missing_data_count += 1
            continue
        try:
            signal = breakout_setup_signal(bars, sym, direction=body.direction, **base_params)
        except Exception as exc:
            observe_terminal(sym, "error", "signal_processing_failed")
            observe_data_failure(sym)
            logger.warning("prebreakout scan: signal failed for %s — %s", sym, exc)
            continue
        if signal is None:
            observe_terminal(sym, "no_setup", "setup_not_returned")
            continue
        _bt_strategy = "breakout_setup"
        _bt_commission = _backtest_commission()
        _bt_hold = hold_for_backtest("Swing", _bt_strategy, None)
        _detail_inputs = dict(
            strategy=_bt_strategy,
            direction=body.direction,
            params=base_params,
            commission=_bt_commission,
            hold_max_days=_bt_hold,
        )
        try:
            _detail_identity = _detail_key(sym, bars, _detail_inputs)
        except (ValueError, TypeError):
            _detail_identity = None

        try:
            bt_result, _detail = await asyncio.get_running_loop().run_in_executor(
                _BACKTEST_POOL,
                functools.partial(_run_backtest_with_details, bars, **_detail_inputs),
            )
        except Exception:
            bt_result, _detail = None, None

        _artifact = await _original_artifact(
            _detail,
            scan_id=scan_id,
            symbol=sym,
            strategy=_bt_strategy,
            direction=body.direction,
            horizon="Swing",
            interval="1d",
            detail_key=_detail_identity,
        ) if _detail_identity else dict(backtest_artifact_status="capture_unavailable")

        results.append({
            "symbol": sym,
            "confidence": signal.confidence,
            "direction": signal.direction,
            "metrics": signal.metrics,
            # STOCK-PRES-P1: evidence behind `confidence` + Fib swing low/high.
            "confidence_breakdown": signal.confidence_breakdown,
            "fib_swing": signal.fib_swing,
            **_artifact,
        })

    results.sort(key=lambda r: r["confidence"], reverse=True)
    if symbols_to_scan and missing_data_count == len(symbols_to_scan):
        observe_no_data()
    for row in results:
        observe_terminal(row["symbol"], "accepted", "candidate_returned")
    return results


# ── Stock first-passage (Approach B) ──────────────────────────────────────────

class StockFirstPassageRequest(BaseModel):
    # NUMERIC-API-INPUTS T2: every float on this body is finite or a 422.
    model_config = ConfigDict(allow_inf_nan=False)

    symbol:       str
    direction:    Literal["Bullish", "Bearish"]
    horizon:      Literal["Intraday", "Swing", "Position"]
    strategy:     str
    stock_price:  float = Field(..., gt=0)
    stop_price:   float = Field(..., gt=0)
    targets:      list[float] = Field(..., min_length=1, max_length=5)
    trend_score:  float = Field(..., ge=0, le=100)


class StockFirstPassageTargetOut(BaseModel):
    price:        float
    probability:  float
    expectedDays: Optional[float] = None


class StockFirstPassageResponse(BaseModel):
    targets:      list[StockFirstPassageTargetOut]
    invalidation: FirstPassageInvalidationOut
    horizonDays:  int
    #: Non-null when the GBM model is a poor fit for this strategy; the card
    #: renders it verbatim. See the plan's "GBM caveat" decision — labelled, not
    #: suppressed, and decided HERE (next to the model) rather than in the UI so
    #: the rule lives in exactly one place.
    modelCaveat:  Optional[str] = None


#: Surfaced whenever the requested strategy's thesis contradicts the estimator's
#: generative model. Kept as a module constant so the endpoint test can assert on
#: the exact string the user sees rather than a substring guess.
_MEAN_REVERSION_CAVEAT = (
    "Approximate for mean-reversion strategies: this model assumes a constant "
    "drift from the trend score, while a mean-reversion trade's thesis is that "
    "the recent drift is transient. Treat the target probabilities as a rough "
    "upper bound; the stop probability is less affected."
)

#: mean_reversion_vwap's signal and backtest run on 15m intraday bars — its
#: thesis is a same-day reversion — but this estimator always simulates daily
#: closes over `horizon_days` TRADING days (see fetch_candles_async below,
#: unconditional on strategy). The sigma/drift inputs describe a slower,
#: coarser process than the one the strategy actually trades, on top of the
#: mean-reversion mismatch above.
_INTRADAY_MEAN_REVERSION_CAVEAT = (
    _MEAN_REVERSION_CAVEAT + " It also simulates daily closes, not the "
    "intraday moves this strategy's signal and backtest are based on, so "
    "treat the probabilities as an even rougher guide than for other "
    "mean-reversion strategies."
)


def _model_caveat_for(strategy: Optional[str]) -> Optional[str]:
    """The one place the "is the GBM a fair model for this strategy?" rule lives.

    Extracted when /stocks/exit-plan arrived, because it reports probabilities
    from the SAME estimator over the SAME paths: two copies of this rule would
    eventually caption one card and not the other for the same number, which is
    worse than no caption at all. `None` strategy (the exit plan's request makes
    it optional — the arithmetic plan stands on its own without one) returns no
    caveat, same as any non-mean-reversion strategy.
    """
    if not strategy:
        return None
    if strategy in _INTRADAY_STRATEGIES:
        return _INTRADAY_MEAN_REVERSION_CAVEAT
    if strategy.startswith("mean_reversion"):
        return _MEAN_REVERSION_CAVEAT
    return None


@router.post('/stocks/first-passage', response_model=StockFirstPassageResponse)
async def stock_first_passage(req: StockFirstPassageRequest) -> StockFirstPassageResponse:
    """On-demand Monte Carlo first-passage estimate for a stock position's exit
    ladder: probability and expected TRADING days to reach each target, and to
    hit the stop, within this horizon's holding window.

    Fired only by the stock position card's "Estimate" button — never by the scan
    — for the same latency reasons as the options `/contracts/first-passage`.
    The holding window comes from scoring_rules.yaml's
    `confidence_backtest.<horizon>.n_days`, this app's existing definition of how
    long a signal in that horizon takes to resolve.
    """
    # The GBM first-passage model assumes a stop below entry and targets above
    # it (Bullish) or the mirror (Bearish). A target already on the wrong side
    # of entry isn't a valid exit ladder — it's already "hit," which is what
    # silently produced a bogus ~100% probability instead of a real error.
    if req.direction == "Bullish":
        if req.stop_price >= req.stock_price:
            raise HTTPException(status_code=422, detail="stop_price must be below stock_price for a Bullish position")
        if any(t <= req.stock_price for t in req.targets):
            raise HTTPException(status_code=422, detail="all targets must be above stock_price for a Bullish position")
    else:
        if req.stop_price <= req.stock_price:
            raise HTTPException(status_code=422, detail="stop_price must be above stock_price for a Bearish position")
        if any(t >= req.stock_price for t in req.targets):
            raise HTTPException(status_code=422, detail="all targets must be below stock_price for a Bearish position")

    fp_cfg = _fp_cfg()
    try:
        horizon_days = int(load_backtest_cfg(req.horizon)["n_days"])
    except (KeyError, TypeError, ValueError):
        horizon_days = 10   # Swing default; never fail the request over config shape

    async with httpx.AsyncClient(timeout=10) as client:
        candles = await fetch_candles_async(client, req.symbol.upper())

    # Deterministic per-request seed, same construction and same reasoning as
    # contracts.py's: identical inputs return an identical answer instead of
    # visible Monte Carlo noise on repeated presses, while genuinely different
    # inputs still draw independently. sha256, not hash() — the latter is salted
    # per process (PYTHONHASHSEED) and so is not stable across restarts/workers.
    seed_key = (f"{req.symbol.upper()}|{req.direction}|{req.horizon}|"
                f"{round(req.stock_price, 2)}|{round(req.stop_price, 2)}|"
                f"{','.join(f'{t:.2f}' for t in req.targets)}")
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest(), 16) % (2 ** 32)

    # CPU-bound NumPy over n_paths simulated paths. asyncio.to_thread keeps it off
    # the event loop, matching how this module already offloads compute_confidence
    # and fetch_intraday_candles. NOT _BACKTEST_POOL — that is a process pool
    # sized for the backtester, and this work is far too small to justify pickling.
    result = await asyncio.to_thread(
        functools.partial(
            estimate_stock_first_passage,
            stock_price=req.stock_price,
            direction=req.direction,
            trend_score=req.trend_score,
            stop_price=req.stop_price,
            targets=req.targets,
            candles=candles,
            horizon_days=horizon_days,
            max_drift_pct=fp_cfg["max_drift_pct"],
            n_paths=fp_cfg["n_paths"],
            sigma_floor=fp_cfg["sigma_floor"],
            sigma_ceiling=fp_cfg["sigma_ceiling"],
            seed=seed,
        )
    )

    caveat = _model_caveat_for(req.strategy)

    return StockFirstPassageResponse(
        targets=[
            StockFirstPassageTargetOut(
                price=round(t.price, 2),
                probability=round(t.probability, 4),
                expectedDays=t.expected_days,
            )
            for t in result.targets
        ],
        invalidation=FirstPassageInvalidationOut(
            probability=round(result.invalidation.probability, 4),
            expectedDays=result.invalidation.expected_days,
        ),
        horizonDays=result.horizon_days,
        modelCaveat=caveat,
    )


# ── POST /stocks/exit-plan ────────────────────────────────────────────────────
#
# Piece 6, "the stocks arithmetic plan" (docs/superpowers/plans/
# 2026-09-02-piece-6-stocks-arithmetic-plan-spec.md). The options exit-plan
# pipeline with the whole premium half removed:
#
#   compute_final_stop   -> survives verbatim (it never took a contract)
#   compute_target_row   -> survives verbatim (same)
#   estimate_rr          -> DROPPED (it reprices a contract)
#   estimate_first_passage -> replaced by estimate_stock_first_passage
#   stop-vs-premium gate -> DROPPED
#
# THERE IS NO STOCKS STOP-COST GATE, and this is a decision, not an omission.
# The options gate answers "what share of the premium does the stop cost?", a
# question that exists only because an option can be near-worthless before the
# stock reaches the stop. A stock has no such nonlinearity: a 5% stop costs 5%,
# exactly, and `recommendedShares` below already turns that into the only
# protection it needs. A badge that looked like the options one but answered a
# different question is the specific thing spec section 1 forbids.
#
# Its own endpoint rather than a branch of /contracts/exit-plan because that one
# requires strike > 0, dte and premium > 0 — none of which a stock has.


class StockExitPlanRequest(BaseModel):
    # NUMERIC-API-INPUTS T2: every float on this body is finite or a 422.
    model_config = ConfigDict(allow_inf_nan=False)

    symbol:      str
    direction:   Literal["Bullish", "Bearish"]
    entry_price: float = Field(..., gt=0)
    trend_score: float = Field(..., ge=0, le=100)
    #: Picks the holding window the probabilities are measured over, via
    #: scoring_rules.yaml's confidence_backtest.<horizon>.n_days.
    horizon:     Literal["Intraday", "Swing", "Position"]
    #: Only ever used to caption the probabilities with the GBM model caveat —
    #: the arithmetic plan itself does not depend on which strategy found the
    #: candidate, so it is optional.
    strategy:    Optional[str] = None
    #: None -> risk_rules.yaml's exit_plan.target.rr_ratios.
    rr_ratios:   Optional[list[float]] = Field(default=None, min_length=1, max_length=5)

    @field_validator("rr_ratios")
    @classmethod
    def _positive_finite_ratios(cls, v: Optional[list[float]]) -> Optional[list[float]]:
        # An R:R of 0 puts the target ON the entry price and a negative one puts
        # it on the losing side — both would render as a "profit target" that is
        # nothing of the kind. Pydantic's gt= cannot reach inside a list.
        if v is None:
            return v
        for r in v:
            if not math.isfinite(r) or r <= 0:
                raise ValueError("rr_ratios must all be finite and greater than 0")
        return v


class StockExitPlanStopOut(BaseModel):
    price:                float
    source:               Literal["structural", "atr_widened"]
    structuralSource:     Optional[Literal["order_block", "swing_low", "swing_high"]] = None
    structuralConfidence: Optional[int] = None
    structuralPrice:      Optional[float] = None
    atrFloorPrice:        float
    distanceDollar:       Optional[float] = None
    #: |entry - stop|. THE WHOLE "cost of the stop" for a stock, exactly and
    #: without a model — which is why there is no gate above it.
    riskPerShare:         float
    probability:          float
    expectedDays:         Optional[float] = None


class StockExitPlanTargetRowOut(BaseModel):
    rrRatio:         float
    arithmeticPrice: float
    price:           float
    tpSource:        Literal["arithmetic", "structural_snap"]
    structuralPrice: Optional[float] = None
    distanceDollar:  Optional[float] = None   # |structural - arithmetic|
    toleranceDollar: float                    # the snap band
    rewardPerShare:  float                    # |target - entry|
    probability:     float
    expectedDays:    Optional[float] = None
    qualityGood:     bool
    qualityReasons:  list[str]


class StockRaceOutcomeOut(BaseModel):
    """One target's row of the two-barrier stock race (spec section 5).

    Three probabilities that sum to exactly 100% because every simulated path is
    assigned to exactly one of them — unlike `stop.probability` and
    `targets[].probability`, which are each measured on their own and routinely
    sum past 100% (a path can touch both barriers).
    """
    targetPrice:    float
    pTargetFirst:   float
    pStopFirst:     float
    pNeither:       float
    daysTarget:     Optional[float] = None   # CONDITIONAL median: paths where the target won
    daysStop:       Optional[float] = None   # CONDITIONAL median: paths where the stop won
    #: Allocated to hundredths so the three ALWAYS sum to exactly 1.00. The card
    #: prints these; the raw p* above are what any bar is drawn from. One
    #: rounding rule, one implementation — see _allocated_weights.
    weightTarget:   float
    weightStop:     float
    weightNeither:  float
    #: Mean price at the end of the window over the pNeither paths. A stock that
    #: reached no barrier is still an open position at a knowable average price,
    #: not a write-off — which is why this bucket carries a number here and the
    #: option race's does not.
    terminalMean:   Optional[float] = None


class StockBarrierRaceOut(BaseModel):
    outcomes:  list[StockRaceOutcomeOut]
    stopPrice: float
    nPaths:    int


class StockExitPlanResponse(BaseModel):
    stop:              StockExitPlanStopOut
    targets:           list[StockExitPlanTargetRowOut]
    atr:               float
    #: floor(riskBudget / riskPerShare). None when either input is non-positive.
    recommendedShares: Optional[int] = None
    #: The numerator above, surfaced so the division is checkable on the card
    #: rather than being a number the user has to trust. portfolio_value x
    #: max_loss_per_trade_pct, from risk_rules.yaml — the same file and the same
    #: keys the Settings > Risk form reads and writes.
    riskBudget:        float
    #: Spec section 3.2, the one real inconsistency, DISCLOSED rather than
    #: unified: this engine counts TRADING days (its window is a bar count and
    #: its sigma is annualized with sqrt(252)); the options card counts CALENDAR
    #: days (its window is DTE). Both are internally consistent; silently making
    #: them one number would break whichever card lost. The card renders the
    #: word.
    daysBasis:         Literal["trading"] = "trading"
    horizonDays:       int
    #: Non-null when the GBM is a poor generative model for the strategy that
    #: found this candidate. Same rule, same text, same single implementation as
    #: /stocks/first-passage — see _model_caveat_for.
    modelCaveat:       Optional[str] = None
    race:              Optional[StockBarrierRaceOut] = None


@router.post('/stocks/exit-plan', response_model=StockExitPlanResponse)
async def stock_exit_plan(req: StockExitPlanRequest) -> StockExitPlanResponse:
    """The arithmetic profit plan for a STOCK: a structurally-grounded stop (the
    wider of the structural level and an ATR floor), one target row per R:R
    ratio (arithmetic, snapped onto a real structural level when one is close
    enough), each with its probability and expected TRADING days, plus the
    two-barrier race and a risk-budget share count.

    Fired only by the stock position card's button, never by the scan — same
    latency reasoning as /contracts/exit-plan and /stocks/first-passage.
    """
    ep_cfg = load_exit_plan_cfg()
    fp_cfg = _fp_cfg()
    is_bullish = req.direction == "Bullish"

    try:
        horizon_days = int(load_backtest_cfg(req.horizon)["n_days"])
    except (KeyError, TypeError, ValueError):
        horizon_days = 10   # Swing default; never fail the request over config shape

    async with httpx.AsyncClient(timeout=10) as client:
        candles = await fetch_candles_async(client, req.symbol.upper())

    # BOTH guards carried over from /contracts/exit-plan verbatim, same message,
    # for the same reason. Fewer than 2 candles means _atr cannot form even one
    # true range, and find_structural_stop's own len<10 guard also returns None:
    # the ATR floor then collapses onto entry_price exactly, producing a
    # zero-width "final stop" and every target row landing on the entry price
    # too. That is a plan built on no data wearing the clothes of a computed
    # one — refuse it rather than return it.
    if len(candles) < 2:
        raise HTTPException(
            status_code=422,
            detail="insufficient price history to compute an exit plan",
        )

    atr = _atr(candles, 14)

    # A flat or duplicated candle feed (stale upstream data, one bar repeated)
    # clears the guard above and still collapses the ATR floor to zero — the
    # same outcome reached a different way.
    if atr <= 0:
        raise HTTPException(
            status_code=422,
            detail="insufficient price history to compute an exit plan",
        )

    # Identical arguments, identical function, as /contracts/exit-plan: this call
    # IS the guarantee that the stock path is the options path with the premium
    # half removed, rather than a second implementation that drifts.
    raw_stop = compute_final_stop(
        candles, req.direction, req.entry_price, atr,
        ep_cfg["stop"]["atr_multiplier"],
    )

    # QUANTIZED TO CENTS BEFORE IT IS USED, not just before it is printed — and
    # this is the one place the stock path deliberately does something the
    # options path does not. This card's entire value is arithmetic the user can
    # check in his head: "stop $96.00, risk $4.00, so 2R is $108.00". An
    # atr_widened stop is entry - 2 x ATR, and ATR is a mean of true ranges, so
    # it is sub-cent-irrational essentially always. Building the targets off the
    # raw stop and printing the rounded one makes that check fail by a penny on
    # most rows. Rounding first makes every printed number reconcile exactly.
    #
    # The cent FLOOR is the same guard, for the same reason, as
    # resolve_stock_stop's: a wide multiplier on a low-priced name (entry 3.00,
    # ATR 2.00, multiplier 2.0 -> -1.00) drives a bullish floor negative, and a
    # stop at or below zero is not a level. atrFloorPrice below still reports
    # the raw floor, so the card can show WHY the stop sits where it does.
    stop_price = round(raw_stop.price, 2)
    if is_bullish and stop_price < 0.01:
        stop_price = 0.01
    final_stop = dataclasses.replace(raw_stop, price=stop_price)

    risk_per_share = round(abs(req.entry_price - stop_price), 2)

    # The quantized stop landing ON the entry price is the collapsed-plan
    # condition the two guards above exist to prevent, reached by a third route:
    # an ATR small enough that 2 x ATR rounds to nothing at this price. Every
    # target would land on entry and every R:R would be infinite. Refuse it with
    # the same message rather than emit a plan of zeroes.
    if risk_per_share <= 0:
        raise HTTPException(
            status_code=422,
            detail="insufficient price history to compute an exit plan",
        )

    rr_ratios = req.rr_ratios if req.rr_ratios is not None else ep_cfg["target"]["rr_ratios"]
    snap_mult = ep_cfg["target"]["structural_snap"]["atr_multiplier"]

    rows = [
        compute_target_row(
            candles, req.direction, req.entry_price, final_stop, atr, float(rr), snap_mult,
        )
        for rr in rr_ratios
    ]
    target_prices = [round(row.price, 2) for row in rows]

    # Deterministic per-request seed — same construction and same reasoning as
    # /stocks/first-passage's and contracts.py's: identical inputs return an
    # identical answer instead of visible Monte Carlo noise on repeated presses,
    # while genuinely different inputs still draw independently. sha256, not
    # hash(), which is salted per process and so unstable across workers.
    seed_key = (
        f"{req.symbol.upper()}|{req.direction}|{req.horizon}|"
        f"{round(req.entry_price, 2)}|{stop_price}|"
        f"{','.join(f'{t:.2f}' for t in target_prices)}"
    )
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest(), 16) % (2 ** 32)

    # CPU-bound NumPy; asyncio.to_thread keeps it off the event loop, exactly as
    # /stocks/first-passage does. The barrier race rides on the SAME simulated
    # paths — no second simulation and no extra work beyond the attribution.
    fp = await asyncio.to_thread(
        functools.partial(
            estimate_stock_first_passage,
            stock_price=req.entry_price,
            direction=req.direction,
            trend_score=req.trend_score,
            stop_price=stop_price,
            targets=target_prices,
            candles=candles,
            horizon_days=horizon_days,
            max_drift_pct=fp_cfg["max_drift_pct"],
            n_paths=fp_cfg["n_paths"],
            sigma_floor=fp_cfg["sigma_floor"],
            sigma_ceiling=fp_cfg["sigma_ceiling"],
            seed=seed,
            compute_race=True,
        )
    )

    structural_price = round(raw_stop.structural.price, 2) if raw_stop.structural else None
    atr_floor_price = round(raw_stop.atr_floor_price, 2)

    stop_out = StockExitPlanStopOut(
        price=stop_price,
        source=raw_stop.source,
        structuralSource=raw_stop.structural.source if raw_stop.structural else None,
        structuralConfidence=raw_stop.structural.confidence if raw_stop.structural else None,
        structuralPrice=structural_price,
        atrFloorPrice=atr_floor_price,
        distanceDollar=(
            round(abs(structural_price - atr_floor_price), 2)
            if structural_price is not None else None
        ),
        riskPerShare=risk_per_share,
        # Spec section 3.3: the options endpoint never reports a probability for
        # its stop row; this engine returns one in the same call, and "this stop
        # is reached on 34% of paths, typically in 6 trading days" is the most
        # decision-relevant number on the card.
        probability=round(fp.invalidation.probability, 4),
        expectedDays=fp.invalidation.expected_days,
    )

    targets_out = [
        StockExitPlanTargetRowOut(
            rrRatio=row.rr_ratio,
            arithmeticPrice=round(row.arithmetic_price, 2),
            price=price,
            tpSource=row.tp_source,
            structuralPrice=round(row.structural.price, 2) if row.structural else None,
            distanceDollar=round(row.distance_dollar, 2) if row.distance_dollar is not None else None,
            toleranceDollar=round(row.tolerance_dollar, 2),
            rewardPerShare=round(abs(price - req.entry_price), 2),
            probability=round(est.probability, 4),
            expectedDays=est.expected_days,
            qualityGood=row.quality_good,
            qualityReasons=row.quality_reasons,
        )
        # zip over fp.targets rather than re-indexing: estimate_stock_first_passage
        # drops non-finite/non-positive targets, so positions are only guaranteed
        # to line up while the lists are the same length — asserted below.
        for row, price, est in zip(rows, target_prices, fp.targets)
    ]
    if len(targets_out) != len(rows):
        raise HTTPException(
            status_code=422,
            detail="insufficient price history to compute an exit plan",
        )

    try:
        server_value = portfolio_risk.account_value()
    except portfolio_risk.AccountValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    portfolio_cfg = portfolio_risk._load_config().get("portfolio", {})
    risk_budget = round(
        server_value
        * float(portfolio_cfg.get("max_loss_per_trade_pct", 0.0)),
        2,
    )
    # shares = risk budget / risk per share. This IS the protective mechanism a
    # stocks stop-cost gate would have duplicated (spec section 1) — sizing off
    # the risk budget bounds the loss at the stop exactly, with no model.
    #
    # DECIMAL, NOT FLOAT FLOOR-DIVISION. Both operands are cent-quantized
    # decimals, and neither is exactly representable in binary: `2000.0 // 1.6`
    # is 1249, not 1250, because 1.6 is stored fractionally below itself. The
    # card prints this number as the answer to the division it shows right
    # beside it, and Apply writes it onto a broker order and into a persisted
    # position — so being one share light is a wrong number in three places at
    # once. Decimal over the string forms is exact for values that are decimal
    # by construction, where `math.floor(a / b)` merely moves the error.
    #
    # None, never a division by zero and never an unbounded size, when either
    # input is non-positive. risk_per_share > 0 is already guaranteed by the 422
    # above; the guard stays because this arithmetic must not depend on a
    # caller's guard staying where it is.
    #
    # A floor of ZERO is also None, not 0. Zero is not a size — it is "the risk
    # budget cannot buy one share at this stop" — and returning it let the card
    # print a SHARES readout of 0 and offer an "Apply 0 shares" button that
    # wrote a 0-share position into the portfolio. Reachable on a small account:
    # a $2,000 portfolio at 0.1% per trade is a $2.00 budget against a $15.69
    # stop.
    recommended_shares: Optional[int] = None
    if risk_budget > 0 and risk_per_share > 0:
        floored = int(Decimal(str(risk_budget)) // Decimal(str(risk_per_share)))
        recommended_shares = floored if floored > 0 else None

    race_out = None
    if fp.race is not None:
        race_out = StockBarrierRaceOut(
            outcomes=[
                StockRaceOutcomeOut(
                    targetPrice=round(o.target_price, 2),
                    pTargetFirst=round(o.p_target_first, 4),
                    pStopFirst=round(o.p_stop_first, 4),
                    pNeither=round(o.p_neither, 4),
                    daysTarget=o.days_target,
                    daysStop=o.days_stop,
                    weightTarget=o.weight_target,
                    weightStop=o.weight_stop,
                    weightNeither=o.weight_neither,
                    terminalMean=round(o.terminal_mean, 2) if o.terminal_mean is not None else None,
                )
                for o in fp.race.outcomes
            ],
            stopPrice=round(fp.race.stop_price, 2),
            nPaths=fp.race.n_paths,
        )

    return StockExitPlanResponse(
        stop=stop_out,
        targets=targets_out,
        atr=round(atr, 2),
        recommendedShares=recommended_shares,
        riskBudget=risk_budget,
        horizonDays=fp.horizon_days,
        modelCaveat=_model_caveat_for(req.strategy),
        race=race_out,
    )
