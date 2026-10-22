from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import concurrent.futures
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

import httpx
import yaml
from pathlib import Path as _Path
from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import AsyncSessionLocal, get_db
from app.models.scan_session import ScanSession
import json as _json

# NOTE: lru_cache (inside load_reward_risk_cfg) caches this at first call.
# Restart the backend to pick up changes to risk_rules.yaml (premium_stop_pct,
# target %, etc.). Shared with app.routers.contracts's recompute endpoint so
# both build a trade plan off the same numbers.
from app.services.scan_report_lifecycle import (run_reported_scan, observe_resolution, observe_configuration, observe_data_failure)
from app.services.config_loader import load_reward_risk_cfg as _rr_cfg
from app.services.config_loader import resolve_target_r_multiple
from app.services.config_loader import merge_reward_risk_overrides as _merge_rr_cfg
from app.services.config_loader import effective_rr_overrides
from app.services.config_loader import effective_entry_overrides, resolve_entry_config
from app.scoring.entry_quality import EntryConfig
from app.services.config_loader import load_scoring_cfg as _load_scoring_cfg
from app.services.config_loader import load_direction_conviction_min_trend

from app.schemas import (
    ScanRequest, ScanResult, RejectedCandidate, TradeCardData,
    ScoreBreakdown, ContractScoreBreakdown, ContractDetails, TradeEntry, TradeExit,
    ScanDelta, ScanState, OptionsPipeline,
    AlternativeContract, DteWindow, EventWindow, ScanSessionStatus,
    TrendDetail, PullbackDetail, TriggerDetail, EventDetail, VolDetail,
    DteDetail, DeltaDetail, IvRankDetail, LiquidityDetail, SpreadDetail,
    SentimentData, FundamentalsOut, SCAN_RESULT_SCHEMA_VERSION,
    RegimeGateSnapshot, ScanRequestContext,
)
from app.services.fundamentals_store import get_fundamentals, prefetch_universe as _prefetch_fundamentals
from app.services.fundamentals_gate import resolve_fundamentals_gate as _resolve_fundamentals_gate
from app.scoring.fundamentals_scorer import score_fundamentals, FundamentalHealth
from app.services.regime_omm import compute_omm as _compute_omm
from app.services.regime_gate import resolve_regime_gate as _resolve_regime_gate
from app.services.money_config import (
    MoneyConfigError, RegimeConfigError, validate_money_blocks, validate_regime_block,
)
from app.services.regime_hmm_daily import compute_directional_hmm as _compute_dhmm, alignment as _hmm_alignment
from typing import Literal
from app.data.market import (
    fetch_candles_async, fetch_price_async, fetch_option_chain_async,
    fetch_company_name_async, fetch_fundamentals_calendar,
    fetch_market_cap_async, fetch_calendar_dates_async,
    fetch_quotes, fetch_intraday_candles, completed_intraday_bars,
    _extract_earnings_date, _extract_dividend_date,
    _compute_iv_bs,
    get_tradier_creds,
)
from app.models.black_scholes import bs_delta  # kept for other callers in this module
from app.data.etfs import is_etf
from app.data.augment import _augment, opt_float, opt_int
from app.data.strike import canonical_strike, format_strike
from app.scoring.stock_scorer import score_stock, StockScoreCard, Horizon, effective_event_window, effective_veto_days
from app.scoring.signal_confidence import load_gate_cfg, compute_confidence
from app.data import confidence_cache
from app.data.universe_exclusions import ExclusionListError, filter_symbols
from app.scoring.contract_validator import validate_contract, ContractScoreCard
from app.scoring.contract_validator import contract_caution_threshold, effective_contract_overrides, effective_dte_limits, is_finite_rule_value
from app.scoring.contract_validator import dte_holding_multiplier
from app.scoring.contract_validator import hard_reject_delta_band
from app.scoring.dte_window import resolve_dte_bounds, widen_contract_overrides_for_dte, widened_min_dte
from app.scoring.reward_risk import estimate_rr
from app.scoring.trade_plan import build_trade_plan
from app.scoring.exit_plan import resolve_stock_stop, final_stop_out, resolve_t1_target
from app.scoring.stock_scorer import _atr
from app.scoring.stop_cost import compute_stop_cost
from app.services.config_loader import load_exit_plan_cfg
from app.models.heston import calibrate_heston, HestonParams
from types import SimpleNamespace
# P3c: stock_scan imports only the regime and contracts routers, neither of
# which imports this module, so there is no cycle.
from app.routers.stock_scan import (
    _regime_data_drop, _direction_conviction_drop, _rs_benchmark_candles, _aligned_benchmark,
)
from app.services.unvalidated import BEARISH_UNVALIDATED_MESSAGE
from app.services.audit import new_rec_id, log_event
from app.scoring.spread_builder import choose_primary, build_bear_put, build_bear_call
from pydantic import BaseModel, ValidationError

# Kill switch: calibrating Heston changes every trade card's headline R/R number,
# so this can be turned off without a code deploy if it misbehaves in
# production — set the env var and restart the process. Read once at import
# time (same pattern as heston_cache.py's _USE_FULL_GRID), so it does NOT
# take effect on an already-running process without a restart.
_HESTON_PRICING_ENABLED = os.getenv("HESTON_PRICING_ENABLED", "1").strip().lower() not in ("0", "false", "no")

router = APIRouter(prefix='/api', tags=['scan'])


class _PrewarmRequest(BaseModel):
    symbols: list[str]

# Load settings once at module level (patchable in tests via app.routers.scan._settings).
# settings.yaml is gitignored (local override); settings.example.yaml is the committed
# default, so a fresh checkout with no local settings.yaml still imports successfully.
_SETTINGS_PATH = _Path(__file__).parent.parent.parent / "config" / "settings.yaml"
_SETTINGS_EXAMPLE_PATH = _Path(__file__).parent.parent.parent / "config" / "settings.example.yaml"


def _load_settings() -> dict:
    path = _SETTINGS_PATH if _SETTINGS_PATH.exists() else _SETTINGS_EXAMPLE_PATH
    return yaml.safe_load(path.read_text()) or {}


_settings: dict = _load_settings()

# ── Manual-run state (Part 3: scheduled runs never touch any of this) ───────

_last_request: ScanRequest | None = None
_last_result: ScanResult | None = None
_last_status: str = "idle"
_last_updated_at: str | None = None
# Serialises concurrent reads/writes of _last_request and _last_result so that
# a scheduler-triggered scan and a user-triggered scan don't race on these globals.
_state_lock = asyncio.Lock()


# ── Helpers ──────────────────────────────────────────────────────────────────

_ORDER = {"REJECT": 0, "CAUTION": 1, "PASS": 2}

# P3c item 1: the options request has no `regime_filter` field; handing the
# stock helper this stand-in makes its drop condition exactly the fire's
# (regime gate enabled OR regime sizing on).
_NO_REGIME_FILTER = SimpleNamespace(regime_filter=False)


def _rule_score(card: StockScoreCard, name: str) -> int:
    for r in card.rules:
        if r.name == name:
            return r.score
    return 50


def _final_status(*statuses: str) -> str:
    return min(statuses, key=lambda s: _ORDER.get(s, 1))


def _earnings_veto(card, veto_days: int) -> bool:
    """Earnings inside max(reject, hold) vetoes options; dividends remain a score penalty."""
    r = next((r for r in card.rules if r.name == "event"), None)
    if r is None:
        return False
    days = r.detail.get("earnings_days")
    return days is not None and 0 <= days < veto_days


def _resolve_earnings_veto_days(horizon, overrides, hold_max_days, reject_days) -> int:
    """Keep a veto window if request resolution fails, using the event echo first."""
    try:
        return effective_veto_days(horizon, overrides, hold_max_days)
    except Exception as exc:
        _log.warning("earnings veto window unavailable: %s", exc)
        if reject_days is not None:
            return reject_days
        from typing import get_args
        return max(effective_veto_days(h, None, None) for h in get_args(Horizon))


def _earnings_unknown_caps(card, symbol: str) -> bool:
    """D4 as amended 2026-10-03 (Kenneth): a SINGLE STOCK whose next earnings
    date is unknown (none on file, or only a past one) is capped at CAUTION.
    The score is unchanged.

    THE CAP IS DISPLAY AND RANKING ONLY; IT DOES NOT STOP AN AUTO-FIRE (audit
    round 1, F7). Nothing on the fire path reads this card: neither
    `/auto-trade/arm` nor `maybe_fire_on_scan` checks `finalStatus`, so an
    armed trade fires whatever the next scan grades it. What actually protects
    auto-fire is the fire path's OWN lookup in `auto_trader._apply_event_veto`,
    which refuses a single stock whose date it cannot establish. These are not
    two independent guards -- there is one, at fire time.

    An ETF (`app.data.etfs.is_etf`) has no earnings and is never capped. A
    symbol missing from that curated set counts as a stock: the safe direction.
    No event rule at all means nothing says when earnings are -- unknown.
    """
    if is_etf(symbol):
        return False
    r = next((r for r in card.rules if r.name == "event"), None)
    return r is None or r.detail.get("earnings_days") is None


def _resolve_gate(req: ScanRequest) -> dict:
    """Confidence gate = YAML default, overridden by any per-scan request values."""
    gate = dict(load_gate_cfg())
    cb = getattr(req, "confidence_caution_below", None)
    rb = getattr(req, "confidence_reject_below", None)
    if cb is not None:
        gate["cautionBelow"] = cb
    if rb is not None:
        gate["rejectBelow"] = rb
    return gate



# Shortlist ranking: lower sorts first. Any other status sorts after CAUTION --
# in practice REJECT, which `_final_status` returns when entry quality is REJECT
# and which does survive to the cap (a REJECT *contract* never does: it leaves
# earlier as "all contracts rejected").
_SHORTLIST_STATUS_ORDER: dict[str, int] = {"PASS": 0, "CAUTION": 1}
# Reason prefix for candidates trimmed by the shortlist cap. The funnel's
# `_is_shortlist` bucket and the frontend's scanLogTotals both match on it.
_SHORTLIST_REASON_PREFIX = "Shortlist cap:"
# NO-LIVE-QUOTE (plan 3f): the per-name reason _process_symbol writes when
# EVERY contract of the name was rejected for no_live_quote and for nothing
# else -- the "all contracts rejected" counter below names one reason with its
# count and no "; best contract score" tail (that tail needs a contract with no
# reject reason). validate_contract's reject mode short-circuits a non-live row
# to exactly ["no_live_quote"], so a mixed chain never matches. Counted into
# ScanResult.noLiveQuoteNames, which the scheduled-scan notice reads.
_NO_LIVE_QUOTE_ONLY_REASON = re.compile(r"contracts rejected: no_live_quote\(\d+\)")


def _compute_deltas(current: ScanResult, previous: ScanResult | None) -> list[ScanDelta]:
    """Compare current candidates with previous run and compute rank/score deltas."""
    if previous is None or not previous.candidates:
        return []

    prev_by_symbol = {c.symbol: (idx, c.stockScore) for idx, c in enumerate(previous.candidates)}
    deltas: list[ScanDelta] = []

    for new_rank, cand in enumerate(current.candidates):
        if cand.symbol in prev_by_symbol:
            old_rank, old_score = prev_by_symbol[cand.symbol]
            deltas.append(ScanDelta(
                symbol=cand.symbol,
                rank_delta=old_rank - new_rank,
                score_delta=cand.stockScore - old_score,
            ))

    return deltas


def _alt_reason(alt: dict, primary: dict, *, is_call: bool) -> str:
    alt_strike = float(alt.get("strike", 0))
    pri_strike = float(primary.get("strike", 0))
    alt_dte    = int(alt.get("dte", 0))
    pri_dte    = int(primary.get("dte", 0))

    parts: list[str] = []
    if alt_dte > pri_dte + 7:
        parts.append("longer DTE — more time for thesis to develop")
    elif alt_dte < pri_dte - 7:
        parts.append("shorter DTE — lower theta cost")

    if is_call:
        if alt_strike < pri_strike - 1:
            parts.append("lower strike — higher delta, more directional exposure")
        elif alt_strike > pri_strike + 1:
            parts.append("higher strike — lower cost, higher leverage if stock moves strongly")
    else:
        if alt_strike > pri_strike + 1:
            parts.append("higher strike — higher delta for downside move")
        elif alt_strike < pri_strike - 1:
            parts.append("lower strike — lower cost, higher leverage on further decline")

    return "; ".join(parts) if parts else "similar profile — alternative liquidity/spread characteristics"


# Kept at 3 to stay below Tradier's rate-limit threshold.
# 10 concurrent × 5 calls = 50 simultaneous requests caused severe throttling (50-78s/symbol).
# 3 concurrent × 5 calls = 15 simultaneous requests → consistent ~4-6s/symbol.
# O-3 batch price fetch drops Pass 1 to 3 calls; 5 × 3 = 15 — same ceiling, more throughput.
# This bounds Tradier-facing HTTP concurrency ONLY (the network fetch phase of
# _process_symbol, gated by the per-scan `sem` parameter). It must NOT be used
# to size anything that doesn't call Tradier — see _HESTON_CONCURRENCY below.
_SCAN_CONCURRENCY = 5

# calibrate_heston (via heston_cache.calibrate_cached) makes no network calls —
# it's pure local CPU work (a brute-force grid search priced with SciPy) against
# an option chain already fetched. It is therefore bound by local CPU capacity,
# not by Tradier's rate limit, and reusing _SCAN_CONCURRENCY here would leave
# most cores idle on any machine with more than 5 logical cores. Scale with the
# host's core count instead, leaving a one-core margin for the event loop
# thread and other concurrent per-request work; floor at _SCAN_CONCURRENCY so
# this is never smaller than before on constrained hosts (or if the core count
# is undetectable).
def _detect_cpu_count() -> int | None:
    """Prefer sched_getaffinity: under Docker/Kubernetes CPU pinning
    (--cpuset-cpus, a Kubernetes cpuset-manager allocation), it reflects the
    container's actual usable cores, whereas os.cpu_count() always reports
    the host's total, which would oversize the pool on a constrained
    container. Linux-only (absent on Windows and macOS), and doesn't see
    quota-only limits (e.g. Docker --cpus with no cpuset pinning) — those
    still fall through to cpu_count()'s host-wide figure, so this is a
    partial mitigation, not a full one. Computed once at import time, so a
    later live cpuset resize isn't picked up without a process restart.

    Not defensive against every failure mode of the underlying syscall — a
    sandboxed/seccomp environment could plausibly raise OSError instead of
    just lacking the attribute; that's accepted here since this project's
    actual deployments (bare host, plain Docker) don't do that.
    """
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count()


def _compute_heston_concurrency(scan_concurrency: int, detected_cpu_count: int | None) -> int:
    return max(scan_concurrency, (detected_cpu_count or scan_concurrency) - 1)


# Known accepted gap: this sizes the *thread pool*, not the underlying
# numeric work. If SciPy's BLAS/LAPACK backend is itself multi-threaded,
# each worker thread can fan out into several more OS threads, oversubscribing
# the CPU beyond what this constant implies. Not addressed here — pinning
# OMP_NUM_THREADS/OPENBLAS_NUM_THREADS/MKL_NUM_THREADS would be a
# process-wide change affecting all numeric code, not just this call site,
# and is out of scope for this fix.
_HESTON_CONCURRENCY = _compute_heston_concurrency(_SCAN_CONCURRENCY, _detect_cpu_count())

# calibrate_heston (via heston_cache.calibrate_cached) is a synchronous call
# of UNBOUNDED duration, and the safeguards below are the only thing that
# bounds it. It used to carry its own internal 1s "timeout", which did not
# bound it either: that timeout only picked which result got returned, because
# the ThreadPoolExecutor context manager it sat in still blocked on
# shutdown(wait=True) for the real grid-search duration. TIMEOUT-DELETE-INNER-
# 2026-09-13 deleted it for exactly that reason, so heston_cache.py no longer
# has a clock in it at all — which changes nothing for this call site, whose
# safeguards never relied on that timeout and are scoped to this call site
# only:
#   1. A small dedicated pool, sized to _HESTON_CONCURRENCY, so a pile-up of
#      slow calibrations can't starve asyncio's shared default executor (also
#      used by compute_confidence and _compute_dhmm in this same function).
#   2. Gating calibration behind a PROCESS-WIDE semaphore sized to match the
#      executor (see the calibration call site below) — this caps concurrent
#      calibrations at _HESTON_CONCURRENCY across the WHOLE process, not just
#      within one scan. Deliberately NOT the per-request `sem` parameter
#      _process_symbol receives: `semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)`
#      in run_scan() is created fresh on every call, and _execute_scan_core
#      itself is shared by run_scan() (manual) and Part 3's scheduled runner
#      (scan_schedule_scheduler.py) — the two can still run fully
#      concurrently at the _process_symbol level even though
#      _SCHEDULED_SCAN_SEMAPHORE serializes scheduled runs against each
#      other (it does not serialize them against a manual run — see that
#      semaphore's own docstring), and _state_lock only guards a few lines of
#      _last_request/_last_result bookkeeping, not scan execution —
#      two independent per-request semaphores would let up to 2x
#      _HESTON_CONCURRENCY symbols contend for this single executor's workers.
#   3. A hard per-symbol wait_for ceiling, so one slow calibration can't stall
#      this symbol's scan processing — the abandoned calibration keeps running
#      in the background in _HESTON_EXECUTOR, but this symbol moves on with
#      heston_params=None (delta approximation) instead of waiting on it.
_HESTON_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_HESTON_CONCURRENCY, thread_name_prefix="heston-calib",
)
_HESTON_SEMAPHORE = asyncio.Semaphore(_HESTON_CONCURRENCY)
# Note: asyncio.Semaphore binds to whichever event loop is running the first
# time it actually blocks. Production runs a single long-lived loop, so this
# is a non-issue there. In tests (function-scoped event loops), a semaphore
# that blocked on one test's loop binding to a different loop on a later test
# raises RuntimeError on Python <=3.12; this project's runtime (3.14)
# tolerates it, but that's a version-specific relaxation, not a guarantee.
#
# Unchanged by the _HESTON_CONCURRENCY split above: this bounds each symbol's
# own wait, not queueing delay. Decoupling concurrency from _SCAN_CONCURRENCY
# removes queueing as a cause of timeouts, but whether 2.0s comfortably covers
# a free worker's actual grid-search time hasn't been measured against a real
# scan — still an open item (see the "Heston repriced vs. delta approximation
# split" follow-up).
_HESTON_CALIBRATION_TIMEOUT_S = 2.0

# Investigation findings #4/#5 (docs/superpowers/plans/
# 2026-07-27-heston-long-dte-slowness-investigation.md): calibration cost
# rises sharply for strikes far from at-the-money, and those strikes are
# never selectable as the scored contract anyway. Two earlier approaches were
# tried and rejected during this plan's own adversarial audit: (1) a FIXED
# MONEYNESS RATIO -- the real delta-selectable moneyness range shifts
# substantially with volatility/time-to-expiry, so a static ratio either
# wrongly excludes real candidates at long DTE or is too wide to filter
# anything useful; (2) a FIXED DELTA BAND -- contract_rules.yaml's
# min_delta/max_delta are live, per-request overrides a user can set
# anywhere in [0,1] via the Execution Parameters panel, so a hardcoded delta
# band reproduces the same fixed-vs-configurable mismatch one layer down.
# This margin is instead added on both sides of THIS REQUEST's actual
# min_delta/max_delta (contract_overrides, the same dict validate_contract
# uses for real contract selection -- and, when no override is present,
# whatever contract_rules.yaml's hard_reject band currently is, read live via
# hard_reject_delta_band() rather than a hardcoded fallback) at the call
# site below, so the calibration band always tracks whatever selection band
# is actually in effect, by construction.
_HESTON_DELTA_SAFETY_MARGIN = 0.05


async def _run_heston_calibration(heston_chain: list[dict], price: float):
    """Runs calibrate_heston under _HESTON_SEMAPHORE, held until the executor
    job ACTUALLY finishes — not just until a caller's wait_for gives up.
    calibrate_heston can't be truly cancelled once a worker has picked it up
    (concurrent.futures threads aren't interruptible), so releasing the
    semaphore the instant a caller times out — while the abandoned job keeps
    running — would let new calibration attempts queue behind already-busy
    workers indefinitely, all timing out without ever getting a worker.
    Holding the semaphore for the job's real lifetime keeps it an accurate
    measure of real executor occupancy, so backpressure shows up as callers
    waiting on the (cheap-to-abandon) semaphore rather than an ever-growing
    (expensive-to-abandon) thread-pool backlog. Callers that want to give up
    early must NOT cancel this task — do it via
    `asyncio.wait({task}, timeout=...)` (which leaves an unfinished task in
    `pending` uncancelled) rather than `wait_for`, so it keeps running (and
    keeps holding the semaphore) in the background until it genuinely
    completes. See the call site in _process_symbol for why plain
    `asyncio.shield` is avoided here.
    """
    async with _HESTON_SEMAPHORE:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_HESTON_EXECUTOR, calibrate_heston, heston_chain, price, 0.05)


def _log_abandoned_heston_exception(task: asyncio.Task) -> None:
    """Consumes the exception of a _run_heston_calibration task that the
    original caller gave up on (its asyncio.wait ceiling elapsed while the
    task was still running) — without this, an abandoned task that later
    raises produces an unretrieved-exception ERROR log from asyncio's
    default handler when it's garbage-collected. This is separate from (and
    can fire even when) the caller's own 'Heston calibration failed or timed
    out' warning already logged."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _log.debug("Abandoned Heston calibration task raised: %s", exc)


async def _build_spreads(
    symbol: str,
    direction: str,
    contract: dict,
    iv_rank: float | None,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    *,
    dte_bounds: tuple[int, int] | None = None,
    min_dte_floor: int | None = None,
    dte_limits: tuple[int, int, int, int] | None = None,
    spread_width: float = 5.0,
    short_leg_delta: float = 0.30,
    iv_rank_threshold: float = 50.0,
    iv_abs_threshold: float = 50.0,
    iv_basis: str = "none",
    min_credit: float = 0.50,
    max_debit_pct: float = 40.0,
):
    """Fetch chains and build primary + alternative spread for Bearish direction.

    Returns (primary_sp, alt_sp) — both None for Bullish or on fetch failure.
    """
    if direction != "Bearish":
        return None, None

    _primary_type = choose_primary(
        iv=iv_rank, iv_basis=iv_basis,
        rank_threshold=iv_rank_threshold, abs_threshold=iv_abs_threshold,
    )
    # Pin the legs to the main contract's expiry: the legs are labelled with it
    # (`_spread_expiry` below), so re-deriving the expiry from the bounds would
    # let any drift between the two fetches (arguments, or date.today() across
    # midnight) put another expiry's strikes under this one's label. An explicit
    # expiry wins in the picker; bounds + floor remain only as the fallback.
    _leg_expiry = contract.get("expiry")
    try:
        async with sem:
            _puts_chain, _calls_chain = await asyncio.gather(
                fetch_option_chain_async(client, symbol, expiry=_leg_expiry, option_type="P",
                                         dte_bounds=dte_bounds, min_dte_floor=min_dte_floor,
                                         dte_limits=dte_limits),
                fetch_option_chain_async(client, symbol, expiry=_leg_expiry, option_type="C",
                                         dte_bounds=dte_bounds, min_dte_floor=min_dte_floor,
                                         dte_limits=dte_limits),
            )
    except Exception as exc:
        _log.debug("Spread: chain fetch failed for %s: %s", symbol, exc)
        return None, None

    _spread_expiry = contract.get("expiry", "TBD")
    primary_sp = None
    alt_sp = None

    if _primary_type == "bear_put" and len(_puts_chain) >= 2:
        try:
            _sp = build_bear_put(_puts_chain, expiry=_spread_expiry, width=spread_width, short_delta=short_leg_delta)
            if _sp.net_debit_credit <= (spread_width * max_debit_pct / 100):
                primary_sp = _sp
        except Exception as exc:
            _log.debug("Spread: build_bear_put failed for %s: %s", symbol, exc)
        if len(_calls_chain) >= 2:
            try:
                _sp = build_bear_call(_calls_chain, expiry=_spread_expiry, width=spread_width, short_delta=short_leg_delta)
                if -_sp.net_debit_credit >= min_credit:
                    alt_sp = _sp
            except Exception as exc:
                _log.debug("Spread: build_bear_call (alt) failed for %s: %s", symbol, exc)

    elif _primary_type == "bear_call" and len(_calls_chain) >= 2:
        try:
            _sp = build_bear_call(_calls_chain, expiry=_spread_expiry, width=spread_width, short_delta=short_leg_delta)
            if -_sp.net_debit_credit >= min_credit:
                primary_sp = _sp
        except Exception as exc:
            _log.debug("Spread: build_bear_call failed for %s: %s", symbol, exc)
        if len(_puts_chain) >= 2:
            try:
                _sp = build_bear_put(_puts_chain, expiry=_spread_expiry, width=spread_width, short_delta=short_leg_delta)
                if _sp.net_debit_credit <= (spread_width * max_debit_pct / 100):
                    alt_sp = _sp
            except Exception as exc:
                _log.debug("Spread: build_bear_put (alt) failed for %s: %s", symbol, exc)

    return primary_sp, alt_sp


def _safe(model_cls, d: dict | None):
    """Construct a Pydantic detail model from a dict, ignoring unknown keys."""
    if not d:
        return None
    try:
        known = {f: d[f] for f in model_cls.model_fields if f in d}
        return model_cls(**known)
    except Exception:
        return None


def _regime_gate_snapshot(gate: dict) -> RegimeGateSnapshot:
    """The two resolved headwind thresholds, as the card carries them.

    A non-numeric YAML value is carried as None rather than failing the card:
    None tells the fire path to read scoring_rules.yaml, which is the same
    value the scan itself was handed, so the two cannot disagree. `bool` is
    excluded because it is an `int` to Python and is never a percentage.
    """
    def _num(v):
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return RegimeGateSnapshot(
        headwindCautionPct=_num(gate.get("headwind_caution_pct")),
        headwindRejectPct=_num(gate.get("headwind_reject_pct")),
    )


def _observed_guard_cfg(symbol):
    cfg = _load_scoring_cfg()
    observe_configuration("options.worker.guard_scoring", cfg, symbol=symbol)
    return cfg


async def _process_symbol(
    symbol: str,
    direction: str,
    horizon: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    scan_id: str,
    *,
    min_price: float | None = None,
    max_price: float | None = None,
    min_cap_usd: float | None = None,
    max_cap_usd: float | None = None,
    overrides: dict | None = None,
    dte_bounds: tuple[int, int] | None = None,
    hold_min_days: int | None = None,
    hold_max_days: int | None = None,
    veto_days: int | None = None,
    # The HOLDING preset key ("Swing", "Annual", "Custom", ...), NOT `horizon`
    # above — that one is the collapsed scoring horizon and cannot express
    # Quarterly/SemiAnnual/Annual/Custom. Only the repricing horizon reads it.
    horizon_preset: str | None = None,
    gate: dict | None = None,
    atr_mult_target: float | None = None,
    atr_mult_stop: float | None = None,
    # Step-3 Regime Gate overrides for THIS scan. None means "use the
    # scoring_rules.yaml value" — the same contract StockScanRequest's pair of
    # the same name has carried since it was added.
    regime_headwind_caution_pct: float | None = None,
    regime_headwind_reject_pct: float | None = None,
    price_map: dict | None = None,
    bars_map: dict | None = None,
    fund_map: dict | None = None,
    fund_gate: dict | None = None,
    spread_width: float = 5.0,
    short_leg_delta: float = 0.30,
    iv_rank_threshold: float = 50.0,
    iv_abs_threshold: float = 50.0,
    min_credit: float = 0.50,
    max_debit_pct: float = 40.0,
    # P3c item 2: the direction-conviction floor (None = exempt, e.g. Intraday),
    # the relative_strength benchmark bars fetched once per scan (None unless
    # that trend method is on), and a shared list collecting the names whose
    # bars did not align with the benchmark (for the per-scan INFO line).
    direction_min_trend: float | None = None,
    rs_benchmark: list[dict] | None = None,
    rs_misaligned: list[str] | None = None,
    # confidence_cache.generation() captured by the caller before `bars_map` was
    # read; set_cached drops a confidence computed from bars read before this
    # symbol's last invalidation (audit R2-F1). None = unconditional write.
    bars_generation: int | None = None,
    entry_cfg: EntryConfig | None = None,
) -> TradeCardData | RejectedCandidate:
    """Process one symbol: fetch data, score stock, validate contracts, build trade card.

    Two-pass fetch: pass 1 fetches candles/price/fundamentals (no chain) and pre-screens
    the stock scorer.  ~70-80% of symbols are rejected here, avoiding the expensive option
    chain fetch entirely.  Pass 2 fetches the chain only for survivors.
    """
    option_type: Literal["C", "P"] = "C" if direction == "Bullish" else "P"

    # ── Pass 1: core data — no option chain ───────────────────────────────────
    prefetched_price = (price_map or {}).get(symbol, {}).get("last")
    async with sem:
        db_bars = (bars_map or {}).get(symbol) if bars_map else None
        if db_bars is not None:
            # Bars already in hand — derive price from last close, no network call needed.
            candles = db_bars
            price = prefetched_price or float(db_bars[-1]["close"])
            company, fund_data = await asyncio.gather(
                fetch_company_name_async(client, symbol),
                fetch_fundamentals_calendar(client, symbol),
            )
        elif prefetched_price:
            candles, company, fund_data = await asyncio.gather(
                fetch_candles_async(client, symbol),
                fetch_company_name_async(client, symbol),
                fetch_fundamentals_calendar(client, symbol),
            )
            price = prefetched_price
        else:
            candles, price, company, fund_data = await asyncio.gather(
                fetch_candles_async(client, symbol),
                fetch_price_async(client, symbol),
                fetch_company_name_async(client, symbol),
                fetch_fundamentals_calendar(client, symbol),
            )
        company = company or symbol

        if not price or not candles:
            log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "no market data"})
            return RejectedCandidate(symbol=symbol, reason="no market data")

        # ── Price filter ───────────────────────────────────────────────────────
        if min_price is not None and price < min_price:
            return RejectedCandidate(symbol=symbol, reason=f"price filter (${price:.2f} < ${min_price:.2f} min)")
        if max_price is not None and price > max_price:
            return RejectedCandidate(symbol=symbol, reason=f"price filter (${price:.2f} > ${max_price:.2f} max)")

        # ── Market-cap filter ──────────────────────────────────────────────────
        if min_cap_usd is not None or max_cap_usd is not None:
            market_cap = await fetch_market_cap_async(symbol)
            if market_cap is not None:
                if min_cap_usd is not None and market_cap < min_cap_usd:
                    cap_b = market_cap / 1e9
                    min_b = min_cap_usd / 1e9
                    return RejectedCandidate(symbol=symbol, reason=f"cap filter (${cap_b:.1f}B < ${min_b:.1f}B min)")
                if max_cap_usd is not None and market_cap > max_cap_usd:
                    cap_b = market_cap / 1e9
                    max_b = max_cap_usd / 1e9
                    return RejectedCandidate(symbol=symbol, reason=f"cap filter (${cap_b:.1f}B > ${max_b:.1f}B max)")

        earnings_date = _extract_earnings_date(fund_data)
        dividend_date = _extract_dividend_date(fund_data)

    # ── yfinance calendar fallback (outside semaphore, has its own rate limiter) ─
    if earnings_date is None or dividend_date is None:
        yf_earn, yf_div = await fetch_calendar_dates_async(symbol)
        if earnings_date is None:
            earnings_date = yf_earn
        if dividend_date is None:
            dividend_date = yf_div

    # ── Regime sentiment ──────────────────────────────────────────────────────
    _regime_signal = None
    # P3c item 1: all three exist even when the config read below raises, so
    # the Intraday data-drop check after `_regime_gate` can read them.
    _regime_bars: list[dict] = []
    _regime_fetch_exc: Exception | None = None
    _rcfg: dict | None = None
    # DOCC-2: read OUTSIDE the `try` below. S2 in `_execute_scan_core` has
    # already validated regime.<horizon> for this same `horizon` (req.horizon),
    # so this cannot raise there; and if a future caller skips S2, a config
    # fault now raises instead of being swallowed by the WARNING handler into
    # an ungated card. The `try` keeps wrapping only the data fetch and the
    # computation, whose failures still abstain.
    _rcfg_doc = _load_scoring_cfg()
    observe_configuration("options.worker.scoring", _rcfg_doc, symbol=symbol)
    _rcfg = _rcfg_doc["regime"][horizon.lower()]
    try:
        # A4: the regime is measured on the bars its `timeframe` names. Intraday
        # is `15min`; this block used to measure it on the DAILY `candles` and
        # only LABEL it 15min, so Options and Stocks mode could give one symbol
        # different regime verdicts. The fetch copies the stock scan's reader
        # (`stock_scan._process_stock`: `fetch_intraday_candles(symbol, "15min",
        # 55)`) and, like it, runs under the scan's semaphore. A failed or short
        # intraday series leaves the regime unmeasured -- there is NO fallback to
        # daily bars, which would bring back the mislabelled measurement.
        if _rcfg["timeframe"] == "15min":
            try:
                async with sem:
                    # A4b: completed bars only -- the still-forming bar
                    # is dropped (decision A4B-DROP-FORMING-15MIN-BAR).
                    _regime_bars = completed_intraday_bars(await asyncio.to_thread(
                        fetch_intraday_candles, symbol, "15min", 55
                    ))
            except Exception as exc:
                _log.warning("Intraday regime bars unavailable for %s: %s", symbol, exc)
                _regime_bars = []
                _regime_fetch_exc = exc
        else:
            _regime_bars = candles
        if _regime_bars and len(_regime_bars) >= _rcfg.get("min_obs", 10):
            _omm = _compute_omm(
                [b["close"] for b in _regime_bars],
                direction=direction,
                lookback=_rcfg["lookback"],
                window=_rcfg["window"],
                min_obs=_rcfg["min_obs"],
            )
            if _omm:
                _dh = None
                try:
                    _dh = await asyncio.to_thread(_compute_dhmm, _regime_bars)
                except Exception as exc:
                    _log.debug("HMM unavailable for %s: %s", symbol, exc)
                _regime_signal = {
                    "horizon": horizon,
                    "timeframe": _rcfg["timeframe"],
                    "state": _omm.state,
                    "p_stay": _omm.p_stay,
                    "stability": _omm.stability,
                    "regime_age_days": _omm.regime_age_days,
                    "avg_regime_duration": _omm.avg_regime_duration,
                    "conviction_pct": _omm.conviction_pct,
                    "conviction_label": _omm.conviction_label,
                    "interpretation": _omm.interpretation,
                    "hmm_state": _dh.state if _dh else None,
                    "alignment": _hmm_alignment(_omm.state, _dh.state if _dh else None),
                    "insufficient_data": False,
                }
    except Exception as exc:
        _log.warning("Regime signal failed for %s: %s", symbol, exc)

    # The gate thresholds for THIS scan: the YAML block, then the Step-3
    # per-scan overrides. A COPY, because `_load_scoring_cfg()` is cached and
    # hands out a reference into one shared mutable dict — writing an override
    # into it would repoint every later reader in the process. Same shape, same
    # None-means-YAML rule, as stock_scan.py:804-808.
    #
    # Resolved once and used at BOTH score_stock call sites below (pre-screen
    # and the post-chain re-score). Two independently built gate dicts on one
    # symbol is how the two passes would come to disagree.
    _gate_doc = _load_scoring_cfg()
    observe_configuration("options.worker.gate_scoring", _gate_doc, symbol=symbol)
    _regime_gate = _resolve_regime_gate(
        _gate_doc.get("regime_gate"),
        regime_headwind_caution_pct,
        regime_headwind_reject_pct,
    )
    observe_configuration("options.regime_gate", _regime_gate, symbol=symbol)

    # P3c item 1 (decision P3A-INTRADAY-REFUSAL-MATCHES-FIRE-2026-09-25): an
    # Intraday name with NO completed 15-min regime bars (fetch raised or came
    # back empty) is dropped whenever the auto-trader's fire would refuse it --
    # regime gate enabled or regime sizing on. The helper is the stock scan's,
    # called not copied; the options request has no `regime_filter`, so
    # `_NO_REGIME_FILTER` reduces its condition to exactly the fire's. A short
    # but non-empty series still abstains (unmeasured), as on the fire. `_rcfg`
    # is None only when the regime config read raised; that name continues
    # unmeasured, as before.
    if _rcfg is not None and (_drop := _regime_data_drop(
            symbol, _NO_REGIME_FILTER, _observed_guard_cfg(symbol), _regime_gate, _rcfg,
            _regime_bars, _regime_fetch_exc)):
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": _drop["reason"]})
        return RejectedCandidate(symbol=symbol, reason=_drop["reason"])

    # ── Pre-screen: score without IV rank ─────────────────────────────────────
    # iv_rank is unknown until the chain is fetched (pass 2). Score with None to gate
    # on trend/pullback/trigger/event — the components that drive most rejections.
    # ~70-80% of symbols exit here, saving the option chain fetch entirely.
    _fh: FundamentalHealth | None = (fund_map or {}).get(symbol)
    # relative_strength needs the benchmark trimmed to THIS symbol's last day;
    # None leaves the trend unmeasured (removed below as "no data"). Computed
    # once and handed to both score_stock calls.
    _bench = _aligned_benchmark(rs_benchmark, candles)
    if rs_benchmark is not None and _bench is None and rs_misaligned is not None:
        rs_misaligned.append(symbol)   # one event loop (gather): no lock needed
    card_pre: StockScoreCard = score_stock(
        symbol, direction, horizon, candles,
        benchmark_candles=_bench,
        earnings_date=earnings_date,
        dividend_date=dividend_date,
        iv_rank=None,
        overrides=overrides,
        regime_signal=_regime_signal,
        regime_gate=_regime_gate if _regime_signal else None,
        fundamentals=_fh,
        fundamentals_gate=fund_gate,
    )
    if card_pre.status == "REJECT":
        bd = {r.name: r.score for r in card_pre.rules}
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"Pre-screen: score {card_pre.score} rejected"})
        return RejectedCandidate(symbol=symbol, reason=f"Pre-screen: score {card_pre.score} rejected", breakdown=bd)

    # P3c item 2 (decision P3C-UNMEASURED-TREND-NO-SCHEMA-FIELD-2026-09-25): an
    # UNMEASURED trend (no trend rule, or its placeholder 0/50) is removed as
    # "no data" here, before the chain fetch, with the stock scan's helper --
    # the trend rule does not read iv_rank, so card_pre's trend is the final
    # card's. Only the unmeasured verdict is acted on; a measured trend below
    # the floor is left to the post-gather gate in _execute_scan_core.
    _dc = _direction_conviction_drop(symbol, card_pre, direction_min_trend, direction, horizon)
    if _dc and _dc["reason"].startswith("direction_conviction_unmeasured:"):
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": _dc["reason"]})
        return RejectedCandidate(symbol=symbol, reason=_dc["reason"])

    # ── Pass 2: fetch option chain only for survivors ─────────────────────────
    # The fetch must only consider expiries the validator will accept, so it
    # gets the same floor the contract hard-reject uses (widen_contract_overrides_for_dte);
    # with no hold window, the validator's min_dte/max_dte and preferred DTE band.
    _dte_floor = widened_min_dte(dte_bounds[0], hold_max_days) if dte_bounds is not None else None
    _dte_limits = effective_dte_limits(overrides) if dte_bounds is None else None
    async with sem:
        chain = await fetch_option_chain_async(client, symbol, option_type=option_type,
                                               dte_bounds=dte_bounds, min_dte_floor=_dte_floor,
                                               dte_limits=_dte_limits)

    if not chain:
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "no option chain"})
        return RejectedCandidate(symbol=symbol, reason="no option chain")

    # ── Final score with the volatility figure from the chain ────────────────
    # TWO DIFFERENT QUANTITIES, and which one we have decides which thresholds
    # judge it (PHASE-A-NULL-IVRANK-2026-09-06):
    #   ivRank -- an IV RANK, present only when IBKR or tastytrade
    #             answered. Judged against the rank thresholds.
    #   iv     -- ABSOLUTE implied volatility, 0-100, from Tradier per strike
    #             (or the Black-Scholes inversion below). Judged against the
    #             absolute thresholds, which is what the 34/55/70 numbers have
    #             actually been judging all along.
    # Prefer the rank: a rank says where this vol sits for THIS name,
    # which an absolute level cannot.
    atm = sorted(chain, key=lambda c: abs(float(c.get("strike", 0)) - price))
    c0 = atm[0] if atm else None
    iv_rank: float | None = None
    iv_basis: str = "none"
    if c0 is not None and c0.get("ivRank") is not None:
        iv_rank, iv_basis = float(c0["ivRank"]), "rank"
    elif c0 is not None and c0.get("iv"):
        iv_rank, iv_basis = float(c0["iv"]), "absolute"

    # No vendor IV at all — invert Black-Scholes for the ATM contract. This
    # yields an ABSOLUTE volatility, never a rank, so it can only ever
    # feed the absolute path.
    if iv_rank is None and c0 is not None:
        iv_bs = _compute_iv_bs(
            mid=float(c0.get("price", 0)),
            S=price,
            K=float(c0.get("strike", price)),
            dte=int(c0.get("dte", 30)),
            is_call=(option_type == "C"),
        )
        if iv_bs is not None:
            iv_rank, iv_basis = round(iv_bs * 100, 1), "absolute"
            # Fill only strikes that have NO absolute IV of their own. The ATM
            # figure is a stand-in for a missing number, not a correction to a
            # present one -- broadcasting it over every strike (which this loop
            # used to do into `ivRank`) flattened the smile and told the UI that
            # a 20-delta wing carried the ATM's volatility.
            for c in chain:
                if not c.get("iv"):
                    c["iv"] = round(iv_bs * 100, 1)
                    c["implied_volatility"] = round(iv_bs, 4)

    # ── Signal confidence (cached; computed in a thread to avoid blocking loop) ─
    _conf: int | None = None
    _conf_n: int = 0
    if gate is not None:
        _ck = confidence_cache.cache_key(
            symbol, direction, horizon, atr_mult_target, atr_mult_stop, scoring_mode="options"
        )
        _cached = confidence_cache.get_cached(_ck)
        if _cached is None:
            _res = await asyncio.to_thread(
                compute_confidence, candles, direction=direction, horizon=horizon,
                atr_mult_target=atr_mult_target, atr_mult_stop=atr_mult_stop,
            )
            _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
            await confidence_cache.set_cached(_ck, _cached, bars_generation=bars_generation)
        _conf = _cached["confidence"]
        _conf_n = _cached["sample_size"]

    card: StockScoreCard = score_stock(
        symbol, direction, horizon, candles,
        benchmark_candles=_bench,
        earnings_date=earnings_date,
        dividend_date=dividend_date,
        iv_rank=iv_rank,
        iv_basis=iv_basis,
        overrides=overrides,
        confidence=_conf,
        confidence_gate=gate,
        confidence_sample_size=_conf_n,
        regime_signal=_regime_signal,
        regime_gate=_regime_gate if _regime_signal else None,
        fundamentals=_fh,
        fundamentals_gate=fund_gate,
    )
    if card.status == "REJECT":
        bd = {r.name: r.score for r in card.rules}
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"Score gate: score {card.score} rejected"})
        return RejectedCandidate(symbol=symbol, reason=f"Score gate: score {card.score} rejected", breakdown=bd)

    augmented = [_augment(c, stock_price=price) for c in chain]
    # DTE bounds are derived from the holding horizon and apply to contracts only,
    # via a separate dict — kept apart from `overrides` for clarity, not because
    # score_stock() would misinterpret these keys (its override handling is an
    # allow-list that already ignores unrecognised keys).
    contract_overrides = dict(overrides or {})
    if dte_bounds is not None:
        lo, hi = dte_bounds
        # Hard-reject AND soft-score preferred-band bounds are both widened by
        # the same DTE_WINDOW_TOLERANCE_DAYS -- see widen_contract_overrides_for_dte's
        # docstring for why the two must move together, not just the hard bound.
        contract_overrides = widen_contract_overrides_for_dte(contract_overrides, lo, hi, hold_max_days)
    scored = [(validate_contract(c, card.score, overrides=contract_overrides or None), c)
              for c in augmented]

    valid_scores = [(s, c) for s, c in scored if s.status != "REJECT"]
    if not valid_scores:
        reason_counts: dict[str, int] = {}
        best_low_score: int | None = None
        for s, _ in scored:
            for r in s.reject_reasons:
                reason_counts[r] = reason_counts.get(r, 0) + 1
            # A contract that clears every hard rule but scores below the
            # caution band is REJECT with no reason of its own; unnamed, a
            # chain of them read as a bare "all contracts rejected". Found
            # while checking open question #8 (Step 3's liquidity floors at 0):
            # the floors do reach validate_contract on main as of 2026-10-02,
            # but the soft Preferred floors can still sink a thin contract's
            # score. #8's original report (hard-reason counts unchanged with
            # both floors at 0) did not reproduce and stays unexplained.
            if not s.reject_reasons:
                reason_counts["contract_score_below_caution"] = (
                    reason_counts.get("contract_score_below_caution", 0) + 1
                )
                best_low_score = s.score if best_low_score is None else max(best_low_score, s.score)
        if reason_counts:
            detail = ", ".join(
                f"{r}({n})" for r, n in sorted(reason_counts.items(), key=lambda x: -x[1])
            )
            if best_low_score is not None:
                detail += f"; best contract score {best_low_score} < caution {contract_caution_threshold()}"
            reject_reason = f"contracts rejected: {detail}"
        else:
            reject_reason = "all contracts rejected"
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": reject_reason})
        return RejectedCandidate(symbol=symbol, reason=reject_reason)

    valid_scores.sort(key=lambda x: x[0].score, reverse=True)
    best_score, contract = valid_scores[0]
    contract_card: ContractScoreCard = best_score
    runner_ups = valid_scores[1:3]

    # ── Entry / Exit / Reward-risk / targets (shared with the recompute endpoint) ─
    _rr = _merge_rr_cfg(overrides)
    observe_configuration("options.reward_risk", _rr, symbol=symbol)
    # `contract["strike"]`, never a `price` fallback (EXACT-STRIKE ES-2.4):
    # every chain row carries a valid strike or was dropped by the builder, so
    # a stock price can never become a strike.
    strike = float(contract["strike"])
    premium = max(float(contract.get("price", 0.10)), 0.01)

    # ── Heston calibration (best-effort) ───────────────────────────────────────
    heston_params: HestonParams | None = None
    if _HESTON_PRICING_ENABLED:
        try:
            _default_min_delta, _default_max_delta = hard_reject_delta_band()
            _cfg_min_delta = float(contract_overrides.get("min_delta", _default_min_delta))
            _cfg_max_delta = float(contract_overrides.get("max_delta", _default_max_delta))
            # round() guards against binary float dust (e.g. 0.20 - 0.05 ==
            # 0.15000000000000002 in IEEE 754), which would otherwise exclude
            # a delta exactly AT the intended boundary from the inclusive
            # comparison below.
            _calib_delta_lo = max(0.0, round(_cfg_min_delta - _HESTON_DELTA_SAFETY_MARGIN, 6))
            _calib_delta_hi = min(1.0, round(_cfg_max_delta + _HESTON_DELTA_SAFETY_MARGIN, 6))

            def _heston_delta_ok(entry: dict) -> bool:
                d = abs(float(entry.get("delta") or 0))
                if d == 0.0:
                    # Greeks missing/unavailable for this quote (market.py
                    # defaults to 0.0, not None) -- indistinguishable from a
                    # genuinely near-zero-delta strike using this field
                    # alone. Fail OPEN: keep it in rather than risk wrongly
                    # excluding a live, valid contract.
                    return True
                return _calib_delta_lo <= d <= _calib_delta_hi

            heston_chain = [
                {
                    "strike": float(c.get("strike", 0)),
                    "expiry_years": c.get("dte", 30) / 365.0,
                    "mid_price": float(c.get("price", 0)),
                    "is_call": c.get("right", "C") == "C",
                }
                for c in chain
                if float(c.get("price", 0)) > 0 and _heston_delta_ok(c)
            ]
            calibration_task = asyncio.ensure_future(_run_heston_calibration(heston_chain, price))
            # Always consume the task's exception, even if we give up on it
            # below — otherwise an abandoned task that later raises (e.g. the
            # dedicated executor is mid-shutdown) surfaces as an asyncio
            # "Task exception was never retrieved" ERROR when it is GC'd.
            calibration_task.add_done_callback(_log_abandoned_heston_exception)
            # asyncio.wait (NOT wait_for + shield) is deliberate: on timeout it
            # leaves the still-running task in `pending` WITHOUT cancelling it,
            # so it keeps running and keeps holding _HESTON_SEMAPHORE in the
            # background (the point of _run_heston_calibration — see its
            # docstring). shield would also keep the task alive, but on Python
            # 3.12+ asyncio.shield ITSELF ERROR-logs "exception in shielded
            # future" (with a full traceback) whenever an abandoned shielded
            # task later raises — precisely the production log noise this
            # feature must not generate. asyncio.wait neither cancels nor logs.
            _done, _pending = await asyncio.wait(
                {calibration_task}, timeout=_HESTON_CALIBRATION_TIMEOUT_S,
            )
            if calibration_task in _done:
                # .result() re-raises if the (in-time) calibration failed —
                # caught below, falling back to delta approximation. Only a
                # genuine grid-search fit ("heston_grid") is honest to label
                # "Heston repriced" downstream. TWO other labels exist and
                # both are discarded by the equality test below, so this
                # symbol falls back to the same delta-approximation path as a
                # genuine calibration failure rather than silently displaying
                # a non-Heston number mislabelled as a real Heston fit:
                #
                #   "bs_fallback" — a crude single-point IV-seed guess:
                #     the chain had fewer than 3 usable strikes, or no grid
                #     combination priced a single one of them. It used to
                #     ALSO mean calibrate_cached's own inner 1.0s timeout had
                #     fired on a fit that was already computed; that timeout
                #     was deleted by TIMEOUT-DELETE-INNER-2026-09-13, so this
                #     label now means the chain, not the clock. See
                #     docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md
                #     finding #5 for the original behaviour.
                #   "bs_flat" — Phase F2's baseline gate: the grid fit was no
                #     better than a SINGLE flat volatility on the same chain,
                #     so the flat vol is returned instead. Before F2 a fit
                #     3.27x worse than one flat vol still reached the card as
                #     "Heston repriced" (spec section 3.3). No change was
                #     needed here for the discard to work — the test is
                #     `== "heston_grid"` — but the label is named so that
                #     anyone widening this condition sees what it would admit.
                _calibration_result = calibration_task.result()
                if _calibration_result.method == "heston_grid":
                    heston_params = _calibration_result.params
            # else: still running past the ceiling — move on with
            # heston_params=None; the task finishes in the background.
        except Exception as exc:
            _log.warning("Heston calibration failed or timed out for %s: %s", symbol, exc)
            heston_params = None

    # ── Piece 3: the stock stop, resolved ONCE per symbol, before the plan ────
    # Everything below that says "the stop" -- `exit.invalidation`, the
    # `exit.finalStop` provenance block, and the B3 ranking badge -- reads this
    # one result. Two computations would be two stops on one card, which is the
    # class of defect pieces 1 and 2 spent their rounds closing.
    #
    # `find_structural_stop` inside `resolve_stock_stop` is synchronous CPU work
    # over the whole bar feed, so it runs in a thread the same way every other
    # comparable per-symbol computation in this function does (_compute_dhmm,
    # compute_confidence).
    #
    # A failure here must not take the candidate down: the plan still needs a
    # stop, so fall back to the same flat percentage `resolve_stock_stop`'s own
    # degenerate-feed branch uses, and send no `finalStop` block -- which reads
    # as "not computed" on the card rather than as a structural level that was
    # never found.
    _ep_stop_cfg = load_exit_plan_cfg()["stop"]
    observe_configuration("options.exit_stop", _ep_stop_cfg, symbol=symbol)
    _flat_fallback_pct = (
        _rr["bullish_invalidation_pct"] if direction == "Bullish"
        else _rr["bearish_invalidation_pct"]
    )
    _stock_stop = None
    try:
        _stock_stop = await asyncio.to_thread(
            resolve_stock_stop,
            candles, direction, price, _atr(candles, 14),
            _ep_stop_cfg["atr_multiplier"], _flat_fallback_pct,
        )
    except Exception as exc:
        _log.warning("Stock stop resolution failed for %s: %s", symbol, exc)

    if _stock_stop is not None:
        _stock_stop_price = _stock_stop.price
    else:
        _stock_stop_price = (
            max(price * (1 - _flat_fallback_pct), 0.01) if direction == "Bullish"
            else price * (1 + _flat_fallback_pct)
        )

    # ── Stop-vs-premium gate, priced at scan time (Phase B3) ──────────────────
    # Spec §2.3, decision B3-SCOPED-STOP-2026-09-08. The ranking table is the
    # last surface with no gate on it; this computes the verdict here, where
    # the auto-picked contract and the candles are both already in hand, and
    # sends down the two fields the row needs.
    #
    # The stop is the wider of the structural level and an ATR floor. Grading a
    # candidate at a fixed -3% would measure the same distance on every symbol
    # in the universe regardless of where its structure actually sits, which is
    # the stop this project is on record as replacing.
    #
    # NO LONGER SCOPED. B3 shipped this badge against its own private
    # `compute_final_stop` call while `exit.invalidation` kept the flat
    # percentage; piece 3 has now repointed `exit.invalidation` at the same
    # resolved stop, so this block reads `_stock_stop` above rather than
    # computing a second one. The badge and the card's Invalidation field
    # therefore grade the same level by construction.
    _stop_cost_fraction = None
    stop_cost_pct: float | None = None
    stop_cost_status: str | None = None
    try:
        # `source == "final_stop"` is exactly the old `_atr(candles, 14) > 0`
        # guard, expressed once, in `resolve_stock_stop`. `_atr` returns 0.0 for
        # a feed too short or too flat to form a true range; the resulting stop
        # is a flat percentage, not a structural level, and pricing a badge
        # against it would grade a number the model did not choose. Refuse
        # instead: "not computed" is an honest answer and a PASS is not. Same
        # guard, same reason, as the exit-plan endpoint's 422.
        if _stock_stop is not None and _stock_stop.source == "final_stop":
            # Priced at the ROUNDED stop for the same reason the endpoint is:
            # the figure graded has to be the figure a user can be shown.
            _scan_cost = compute_stop_cost(
                stop_price=round(_stock_stop.price, 2),
                stock_price=price,
                strike=strike,
                dte=int(contract.get("dte", 30)),
                premium=round(premium, 2),
                is_call=(direction == "Bullish"),
                # ALWAYS None -- invert this contract's OWN mid with the
                # bracketed solver, which is compute_stop_cost's normal basis.
                #
                # Passing `contract["iv"]` here was WRONG, and confidently so.
                # The gate is `loss = premium - BS(stop, K, T, r, iv)`, and
                # that subtraction is only coherent when the vol reproduces
                # the very mid `premium` came from. `contract["iv"]` does not
                # when the ATM fill above (~line 640) fired: on a chain with
                # no vendor IV, that loop broadcasts the ATM's inverted vol
                # into EVERY strike lacking one, so a 20-delta wing is handed
                # the ATM's volatility. It is in-band, so no range guard can
                # catch it, and it flattens the smile the gate exists to read.
                # Measured on a 200/210C, 30 DTE, $4.41 mid, stop $192: the
                # ATM's 25% priced 81% CAUTION where the contract's own mid
                # gives 50% PASS -- 31 points and an inverted verdict, on the
                # column the table sorts by. compute_stop_cost's own docstring
                # names the hazard: "a caller-supplied iv_pct need not
                # reproduce the contract's own mid".
                #
                # Never `iv_rank` either: it holds an IV RANK whenever
                # iv_basis == "rank", and feeding a rank to a function
                # taking absolute volatility is the conflation Phase A ended.
                iv_pct=None,
                horizon_preset=horizon_preset,
            )
            if _scan_cost is not None:
                _stop_cost_fraction = _scan_cost.fraction
                stop_cost_pct = round(_scan_cost.fraction * 100, 1)
                stop_cost_status = _scan_cost.status
    except Exception as exc:
        # A gate that cannot price itself must not take the candidate down with
        # it. Every other per-symbol enrichment in this function (regime,
        # Heston, confidence) degrades the same way, and this one carries less:
        # the row simply reads "not computed".
        _log.warning("Scan-time stop cost failed for %s: %s", symbol, exc)

    _r_multiple = resolve_target_r_multiple(overrides)
    try:
        _t1_price, _t1_source = await asyncio.to_thread(
            resolve_t1_target, candles, direction, price, _stock_stop,
            _stock_stop_price, _r_multiple,
            load_exit_plan_cfg()["target"]["structural_snap"]["atr_multiplier"],
        )
    except Exception as exc:
        _log.warning("Scan target resolution failed for %s: %s", symbol, exc)
        _t1_price = price + (1 if direction == "Bullish" else -1) * _r_multiple * abs(price - _stock_stop_price)
        _t1_source = "flat_fallback"

    _entry_cfg = entry_cfg if entry_cfg is not None else (
        resolve_entry_config(overrides) if overrides else None
    )

    _plan = build_trade_plan(
        direction=direction,
        stock_price=price,
        strike=strike,
        dte=int(contract.get("dte", 30)),
        premium=premium,
        entry_bid=float(contract.get("bid", 0)),
        entry_ask=float(contract.get("ask", 0)),
        entry_mid=float(contract.get("price", 0)),
        rr_cfg=_rr,
        heston_params=heston_params,
        horizon_preset=horizon_preset,
        hold_min=hold_min_days,
        hold_max=hold_max_days,
        final_stop_price=_stock_stop_price,
        target_price=_t1_price,
        target_source=_t1_source,
        stop_cost_fraction=_stop_cost_fraction,
        entry_cfg=_entry_cfg,
    )
    entry = _plan.entry
    target_price = _plan.target_price
    invalidation_price = _plan.invalidation_price
    rr = SimpleNamespace(rr_ratio=_plan.rr_ratio, model_used=_plan.rr_model)
    targets = _plan.targets
    # Unrounded target/invalidation for the runner-up alternatives' estimate_rr
    # (see below) — feeding the rounded values would drift their R/R vs the
    # pre-refactor behaviour.
    _target_raw = _plan.target_price_raw
    _invalidation_raw = _plan.invalidation_price_raw

    # ── Build TradeCardData ────────────────────────────────────────────────────
    from datetime import date as _date
    next_event_days = None
    next_event_label = None
    for ev_date, ev_label in [(earnings_date, "Earnings"), (dividend_date, "Dividend")]:
        if ev_date is None:
            continue
        days = max(0, (ev_date - _date.today()).days)
        if next_event_days is None or days < next_event_days:
            next_event_days = days
            next_event_label = ev_label

    # Build a name → detail lookup for rich ScoreBreakdown fields
    rule_detail = {r.name: r.detail for r in card.rules}

    # Piece 3's provenance block for the stop `invalidation_price` already
    # carries. Sent ONLY for a stop the structural/ATR model actually chose:
    # on the flat-percentage fallback (a degenerate bar feed) there is no
    # structural level and no ATR floor to report, and a block full of nulls
    # would read on the card as "we looked and found nothing" rather than "we
    # could not look at all". Absent is the honest shape for both that case and
    # a resolution that raised.
    _final_stop_block = final_stop_out(
        _stock_stop, datetime.now(timezone.utc).isoformat(),
    )

    # Production scans pass one precomputed window. Preserve direct callers by
    # resolving from their own horizon/hold, with the same event-rule fallback.
    if veto_days is None:
        veto_days = _resolve_earnings_veto_days(
            horizon, overrides, hold_max_days, rule_detail.get("event", {}).get("reject_days"),
        )

    trade_card = TradeCardData(
        symbol=symbol,
        company=company,
        price=price,
        direction=direction,
        status=_final_status(card.status, "CAUTION" if direction == "Bearish" else "PASS"),
        stockScore=card.score,
        stockConfidence=card.status,
        stockExplanation=card.explanation,
        stockBreakdown=ScoreBreakdown(
            trend=_rule_score(card, "trend"),
            pullback=_rule_score(card, "pullback"),
            trigger=_rule_score(card, "trigger"),
            event=_rule_score(card, "event"),
            volatility=_rule_score(card, "vol"),
            trendDetail=    _safe(TrendDetail,    rule_detail.get("trend")),
            pullbackDetail= _safe(PullbackDetail, rule_detail.get("pullback")),
            triggerDetail=  _safe(TriggerDetail,  rule_detail.get("trigger")),
            eventDetail=    _safe(EventDetail,    rule_detail.get("event")),
            volDetail=      _safe(VolDetail,      rule_detail.get("vol")),
        ),
        nextEventDays=next_event_days,
        nextEventLabel=next_event_label,
        contract=f"{symbol}|{format_strike(strike)}|{contract.get('expiry','TBD')}|{'C' if direction=='Bullish' else 'P'}",
        contractScore=contract_card.score,
        contractConfidence=contract_card.status,
        contractExplanation=contract_card.explanation,
        contractBreakdown=ContractScoreBreakdown(
            dteFit=contract_card.breakdown.dte_score,
            delta=contract_card.breakdown.delta_score,
            ivAttractiveness=contract_card.breakdown.iv_rank_score,
            liquidity=contract_card.breakdown.liquidity_score,
            spread=contract_card.breakdown.spread_score,
            dteDetail=      _safe(DteDetail,       contract_card.detail.get("dte")),
            deltaDetail=    _safe(DeltaDetail,     contract_card.detail.get("delta")),
            ivDetail=       _safe(IvRankDetail,    contract_card.detail.get("iv_rank")),
            liquidityDetail=_safe(LiquidityDetail, contract_card.detail.get("liquidity")),
            spreadDetail=   _safe(SpreadDetail,    contract_card.detail.get("spread")),
        ),
        contractDetails=ContractDetails(
            strike=canonical_strike(strike),
            expiry=contract.get("expiry", "TBD"),
            right="C" if direction == "Bullish" else "P",
            mid=round(premium, 2),
            delta=float(contract.get("delta", 0.45)),
            theta=float(contract.get("theta", -0.05)),
            ivRank=opt_int(contract.get("ivRank")),
            iv=opt_float(contract.get("iv")),
            ivPercentile=opt_int(contract.get("ivPercentile")),
            dte=int(contract.get("dte", 30)),
        ),
        entry=TradeEntry(
            limit=round(entry.limit_price, 2),
            maxFill=round(entry.max_fill, 2),
            orderType=entry.order_type,
        ),
        exit=TradeExit(
            invalidation=invalidation_price,
            premiumStop=_plan.premium_stop,
            timeStopDays=_plan.time_stop_days,
            target=target_price,
            targets=targets,
            finalStop=_final_stop_block,
            stockStopLoss=_plan.stock_stop_loss,
            stockStopLossAt=_plan.stock_stop_loss_at,
            rrRiskBasis=_plan.rr_risk_basis,
            targetSource=_plan.target_source,
        ),
        rrRatio=rr.rr_ratio,
        rrModel=rr.model_used,
        finalStatus=_final_status(
            card.status, contract_card.status, entry.quality_status,
            "REJECT" if _earnings_veto(card, veto_days) else "PASS",
            # D4 amended 2026-10-03: unknown earnings caps a single stock.
            "CAUTION" if _earnings_unknown_caps(card, symbol) else "PASS",
            "CAUTION" if direction == "Bearish" else "PASS",
        ),
        unvalidatedReason=BEARISH_UNVALIDATED_MESSAGE if direction == "Bearish" else None,
        earningsVeto=_earnings_veto(card, veto_days),
        earningsUnknown=bool(rule_detail.get("event", {}).get("earnings_unknown", False)),
        isEtf=is_etf(symbol),
        earningsDays=rule_detail.get("event", {}).get("earnings_days"),
        confidence=(_conf_rule.detail.get("confidence") if (_conf_rule := next((r for r in card.rules if r.name == "confidence"), None)) else None),
        confidenceText=(_conf_rule.detail.get("interpretation") if _conf_rule else None),
        sentiment=SentimentData(**_regime_signal) if _regime_signal else None,
        stopCostPct=stop_cost_pct,
        stopCostStatus=stop_cost_status,
        # The SAME resolved dict both score_stock calls above were handed, so
        # the card cannot describe a rule its own scoring did not use. The arm
        # payload reads the thresholds off this, not off live Step-3 state.
        regimeGate=_regime_gate_snapshot(_regime_gate),
    )

    trade_card.fundamentals = FundamentalsOut(
        score=_fh.score,
        quality_label=_fh.quality_label,
        risk_label=_fh.risk_label,
        growth_score=_fh.growth_score,
        quality_score=_fh.quality_score,
        risk_score=_fh.risk_score,
        safety_flags=_fh.safety_flags,
        detail=_fh.detail,
    ) if _fh else None

    # ── Bearish spread attachment (Pass 2 survivors only) ────────────────────────
    _primary_sp, _alt_sp = await _build_spreads(
        symbol, direction, contract, iv_rank, client, sem,
        dte_bounds=dte_bounds,
        min_dte_floor=_dte_floor,
        dte_limits=_dte_limits,
        spread_width=spread_width,
        short_leg_delta=short_leg_delta,
        iv_rank_threshold=iv_rank_threshold,
        iv_abs_threshold=iv_abs_threshold,
        iv_basis=iv_basis,
        min_credit=min_credit,
        max_debit_pct=max_debit_pct,
    )

    if _primary_sp is not None:
        from app.schemas import OptionLeg as _OptionLeg
        trade_card.spreadType = _primary_sp.spread_type
        trade_card.netDebitCredit = _primary_sp.net_debit_credit
        trade_card.maxProfit = _primary_sp.max_profit
        trade_card.maxLoss = _primary_sp.max_loss
        trade_card.breakeven = _primary_sp.breakeven
        trade_card.legs = [
            _OptionLeg(
                right=leg.right,
                strike=leg.strike,
                expiry=leg.expiry,
                action=leg.action,
                qty=leg.qty,
                bid=leg.bid,
                ask=leg.ask,
            )
            for leg in _primary_sp.legs
        ]

    alts: list[AlternativeContract] = []
    for alt_card, alt_c in runner_ups:
        if alt_c.get("price") is None or alt_c.get("strike") is None or alt_c.get("dte") is None:
            # No real quote/strike/DTE for this runner-up -- do not fabricate
            # a value and run it through the real-IV reward/risk pipeline as
            # if it were observed data. Skip it; alternativesCount below is
            # len(alts), so this naturally yields a correct, consistent
            # count with no further bookkeeping.
            continue
        alt_strike = float(alt_c["strike"])
        alt_expiry_years = alt_c.get("dte", 30) / 365.0
        alt_premium = float(alt_c.get("price", 0.10))
        alt_stop_fraction = None
        if _stock_stop is not None and _stock_stop.source == "final_stop":
            try:
                alt_cost = compute_stop_cost(
                    stop_price=round(_stock_stop.price, 2), stock_price=price,
                    strike=alt_strike, dte=int(alt_c["dte"]), premium=round(alt_premium, 2),
                    is_call=direction == "Bullish", iv_pct=None, horizon_preset=horizon_preset,
                )
                if alt_cost is not None:
                    alt_stop_fraction = alt_cost.fraction
            except Exception as exc:
                _log.warning("Alternative stop cost failed for %s: %s", symbol, exc)
        alt_rr = estimate_rr(
            stock_price=price,
            target_price=_target_raw,
            invalidation_price=_invalidation_raw,
            strike=alt_strike,
            expiry_years=alt_expiry_years,
            current_premium=alt_premium,
            is_call=(direction == "Bullish"),
            heston_params=heston_params,
            premium_stop_pct=_rr["premium_stop_pct"],
            risk_fraction=alt_stop_fraction,
        )
        alts.append(AlternativeContract(
            symbol=symbol,
            strike=canonical_strike(alt_strike),
            expiry=alt_c.get("expiry", "TBD"),
            right="C" if direction == "Bullish" else "P",
            dte=int(alt_c.get("dte", 30)),
            mid=round(float(alt_c.get("price", 0)), 2),
            delta=round(float(alt_c.get("delta", 0.45)), 3),
            theta=round(float(alt_c.get("theta", -0.05)), 3),
            ivRank=opt_int(alt_c.get("ivRank")),
            iv=opt_float(alt_c.get("iv")),
            score=alt_card.score,
            contractConfidence=alt_card.status,
            contractExplanation=alt_card.explanation,
            contractBreakdown=ContractScoreBreakdown(
                dteFit=alt_card.breakdown.dte_score,
                delta=alt_card.breakdown.delta_score,
                ivAttractiveness=alt_card.breakdown.iv_rank_score,
                liquidity=alt_card.breakdown.liquidity_score,
                spread=alt_card.breakdown.spread_score,
                dteDetail=      _safe(DteDetail,       alt_card.detail.get("dte")),
                deltaDetail=    _safe(DeltaDetail,     alt_card.detail.get("delta")),
                ivDetail=       _safe(IvRankDetail,    alt_card.detail.get("iv_rank")),
                liquidityDetail=_safe(LiquidityDetail, alt_card.detail.get("liquidity")),
                spreadDetail=   _safe(SpreadDetail,    alt_card.detail.get("spread")),
            ),
            rrRatio=alt_rr.rr_ratio,
            rrModel=alt_rr.model_used,
            reason=_alt_reason(alt_c, contract, is_call=(direction == "Bullish")),
        ))
    # Append the alternative spread type (bear_call ↔ bear_put) if built
    if direction == "Bearish" and _alt_sp is not None:
        from app.schemas import OptionLeg as _OptionLeg
        # ROUND 4 finding 9. choose_primary picks by iv_basis, and on most chains
        # the deciding quantity is an ABSOLUTE IV against abs_threshold -- so
        # naming "IV rank" here explained a credit-vs-debit choice, on the row
        # the user may send to a broker, by the quantity that did not make it.
        _iv_word = "IV rank" if iv_basis == "rank" else "IV"
        _spread_reason = (
            f"bear call spread — collects credit; better when {_iv_word} is high"
            if _alt_sp.spread_type == "bear_call"
            else f"bear put spread — debit spread; better when {_iv_word} is low"
        )
        alts.append(AlternativeContract(
            symbol=symbol,
            strike=canonical_strike(_alt_sp.legs[0].strike),
            expiry=_alt_sp.legs[0].expiry,
            right=_alt_sp.legs[0].right,
            dte=int(contract.get("dte", 30)),
            mid=round(abs(_alt_sp.net_debit_credit), 2),
            delta=round(float(contract.get("delta", 0.30)), 3),
            theta=round(float(contract.get("theta", -0.05)), 3),
            ivRank=opt_int(contract.get("ivRank")),
            iv=opt_float(contract.get("iv")),
            score=contract_card.score,
            contractConfidence=contract_card.status,
            contractBreakdown=ContractScoreBreakdown(
                dteFit=contract_card.breakdown.dte_score,
                delta=contract_card.breakdown.delta_score,
                ivAttractiveness=contract_card.breakdown.iv_rank_score,
                liquidity=contract_card.breakdown.liquidity_score,
                spread=contract_card.breakdown.spread_score,
                dteDetail=      _safe(DteDetail,       contract_card.detail.get("dte")),
                deltaDetail=    _safe(DeltaDetail,     contract_card.detail.get("delta")),
                ivDetail=       _safe(IvRankDetail,    contract_card.detail.get("iv_rank")),
                liquidityDetail=_safe(LiquidityDetail, contract_card.detail.get("liquidity")),
                spreadDetail=   _safe(SpreadDetail,    contract_card.detail.get("spread")),
            ),
            rrRatio=rr.rr_ratio,
            rrModel=rr.model_used,
            reason=_spread_reason,
            spreadType=_alt_sp.spread_type,
            legs=[
                _OptionLeg(
                    right=leg.right,
                    strike=leg.strike,
                    expiry=leg.expiry,
                    action=leg.action,
                    qty=leg.qty,
                    bid=leg.bid,
                    ask=leg.ask,
                )
                for leg in _alt_sp.legs
            ],
            netDebitCredit=_alt_sp.net_debit_credit,
            maxProfit=_alt_sp.max_profit,
            maxLoss=_alt_sp.max_loss,
            breakeven=_alt_sp.breakeven,
        ))

    trade_card.alternatives = alts
    trade_card.alternativesCount = len(alts)

    log_event("trade_card_created", scan_id, {"symbol": symbol, "score": card.score})
    return trade_card


async def _upsert_session(
    db: AsyncSession,
    req: ScanRequest | None,
    result: ScanResult | None,
    status: str,
) -> None:
    """Persist scan state to the DB as a single row with id='current'."""
    global _last_status, _last_updated_at
    await db.merge(
        ScanSession(
            id="current",
            status=status,
            # Stamped on the way out so a later restore can tell a blob this
            # code wrote from one written before the IV basis split
            # (PHASE-A-NULL-IVRANK-2026-09-06). Set here rather than at every
            # construction site so no scan can be persisted unmarked.
            last_result_json=(
                result.model_copy(update={"schema_version": SCAN_RESULT_SCHEMA_VERSION}).model_dump_json()
                if result else None
            ),
            last_request_json=req.model_dump_json() if req else None,
        )
    )
    await db.commit()
    _last_status = status
    _last_updated_at = datetime.now(timezone.utc).isoformat()


async def restore_from_db() -> str | None:
    """Restore _last_request and _last_result from DB on startup.

    Returns the stored status string so the caller can auto-resume the scheduler.
    """
    global _last_request, _last_result, _last_status, _last_updated_at
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(ScanSession).where(ScanSession.id == "current"))
        except Exception:
            # Table may not exist (e.g., test_app.py with no DB)
            return None
        row = result.scalar_one_or_none()
        if row is None:
            return None
        _refused = False
        if row.last_result_json:
            _restored = ScanResult.model_validate_json(row.last_result_json)
            # A result stored under an older schema carries at least one field
            # whose name no longer describes what it holds, with nothing on the
            # record saying so -- v0's `ivRank` held raw implied volatility
            # under a rank's name; v1's `exit.invalidation` held a flat
            # percentage move under the resolved structural+2xATR stop's name.
            # Serving either puts a wrong number on the card the user acts
            # from, and the frontend cannot repair it: its own migrations only
            # reach localStorage, and StoreHydration re-persists whatever
            # /scan/last returns at the CURRENT store version, so the bad figure
            # is stamped as migrated and never revisited.
            #
            # Dropped rather than relabelled, for the same reason
            # ivBasis.stripLegacyIvFields drops: the basis is not recoverable,
            # and guessing would be right for most rows and silently wrong for
            # the rest. The cost is one re-scan of data that was stale market
            # data anyway (PHASE-A-NULL-IVRANK-2026-09-06, PIECE-3-2026-09-09).
            #
            # A COMPARISON, not `is None`. This guard was written when exactly
            # one bump existed and tested for its absence, so piece 3's bump was
            # silently exempt and a v1 blob -- a flat -3% stop with no
            # provenance block -- was served, re-persisted at the current store
            # version, seeded into the editable Invalidation field, passed
            # `checkInvalidation`, and stored as `PortfolioPosition.stop` for
            # STOP_REACHED to fire against. Every future bump is now covered
            # without touching this line.
            if (_restored.schema_version or 0) < SCAN_RESULT_SCHEMA_VERSION:
                _log.warning(
                    "Discarding the persisted scan result: written at schema "
                    "version %s, below the current %s, so at least one of its "
                    "fields no longer means what its name says. Run a scan to "
                    "repopulate.",
                    _restored.schema_version, SCAN_RESULT_SCHEMA_VERSION,
                )
                # ROUND 5 finding 11. The STATUS must go with the result. Left
                # set, /scan/last-run reported COMPLETED at the old timestamp
                # while /scan/last returned null: the TopBar pill claimed a
                # finished scan and every table underneath it was empty, with
                # the only explanation in a server log the user never sees.
                # "idle" is what the frontend already renders as "no scan yet",
                # which is the true state once the result is gone.
                _refused = True
            else:
                _last_result = _restored
        if row.last_request_json:
            try:
                _last_request = ScanRequest.model_validate_json(row.last_request_json)
            except ValidationError:
                _last_request = None
                # Validation errors can contain the saved input; log no body.
                _log.warning(
                    "restore_from_db: saved options request no longer validates "
                    "and was dropped; valid saved results remain available.",
                )
        if _refused:
            _last_status = "idle"
            _last_updated_at = None
            return _last_status
        _last_status = row.status
        _last_updated_at = row.updated_at.isoformat() if row.updated_at else None
        return row.status


@router.get('/scan/last', response_model=ScanResult | None)
async def get_last_scan() -> ScanResult | None:
    """Return the most recently completed scan, if any — survives a backend
    restart because _last_result is repopulated from the DB in main.py's
    lifespan startup hook (restore_from_db()). Used by the frontend as a
    fallback when localStorage has no cached scan result."""
    return _last_result


@router.get('/scan/last-run', response_model=ScanSessionStatus)
async def get_last_scan_status() -> ScanSessionStatus:
    """Return last-run metadata (status/timestamp/request params) for the
    manual-run UI slot. Part 3's scheduled runs never touch this — each has
    its own status/history reachable via GET /api/scan-schedule/{id}/runs
    instead (see routers/scan_schedule.py).

    The request fields and `scan_id` are snapshotted TOGETHER under
    `_state_lock`, the same lock run_scan writes the pair under. That is what
    makes the returned scan_id a usable key: a client that fetches this
    endpoint and /scan/last can compare the two and know whether the
    thresholds it just read belong to the result it holds, or to a scan that
    completed in between. Read unlocked, the request and the result could be
    read from either side of a scan's write and quietly describe two runs.

    `_last_status`/`_last_updated_at` are deliberately OUTSIDE that guarantee —
    _upsert_session writes them without the lock, so they may lag the pair by a
    scan. Nothing that consumes the thresholds depends on them."""
    async with _state_lock:
        req, res = _last_request, _last_result
    return ScanSessionStatus(
        status=_last_status,
        updated_at=_last_updated_at,
        universe=req.universe if req else None,
        direction=req.direction if req else None,
        horizon=req.horizon if req else None,
        # None here is "no result to pair with", which includes the case where
        # restore_from_db refused a pre-split blob and kept its request: the
        # params below are then real, but they describe a scan whose rows this
        # backend will not serve.
        scan_id=res.scan_id if res else None,
        # Post-validator values: ScanRequest._seed_pre_split_iv_knobs has
        # already filled iv_abs_threshold on a pre-split body, so these are the
        # numbers the run APPLIED, not the ones it happened to name.
        iv_abs_threshold=req.iv_abs_threshold if req else None,
        iv_rank_threshold=req.iv_rank_threshold if req else None,
    )


async def _execute_scan_core(
    req: ScanRequest, db: AsyncSession, *, previous_result: ScanResult | None,
) -> ScanResult:
    """The actual scan-running logic — the same body run_scan() always ran,
    with the delta computation taking `previous_result` as a parameter
    instead of silently reading the module-global _last_result, and with NO
    writes to _last_request/_last_result/_last_status/ScanSession(id="current")
    and no auto-trade firing. Both the manual handler (run_scan, below) and
    Part 3's scheduled runner (_run_scheduled_entry) call this; only the
    manual handler additionally updates the UI-facing globals, persists to
    ScanSession(id="current"), and checks the auto-trader — see run_scan()."""
    scan_id = new_rec_id()
    log_event("scan_started", scan_id, {"universe": req.universe, "direction": req.direction})

    # Expand preset universe strings to individual ticker lists
    from app.data.universe_presets import expand_universe, PresetUnavailableError
    from fastapi import HTTPException

    try:
        symbols = expand_universe(req.universe)
    except PresetUnavailableError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # STOCKS-HORIZON-P0A A2: drop `scope: scan` symbols from the FINAL list
    # (presets expanded, typed tickers included) before any per-symbol work.
    # Each one is reported in `rejected` below and counted in `scanned` and
    # `failed_data`. A broken list is a named 500: it must not silently scan
    # everything.
    try:
        _expanded_symbols = list(symbols)
        symbols, _excluded = filter_symbols(symbols, purpose="scan")
        observe_resolution(_expanded_symbols, symbols, _excluded)
    except ExclusionListError as e:
        _log.error("SCAN %s aborted: universe exclusion list unusable: %s", scan_id, e)
        raise HTTPException(status_code=500, detail=str(e))

    # Validate rr_* overrides ONCE upfront, before dispatching any per-symbol
    # work. Without this, a malformed override (e.g. a negative target %)
    # only surfaced inside _process_symbol -- AFTER that symbol's full
    # candle/price/fundamentals fetch and option-chain scoring had already
    # run, and it failed identically for every symbol in the universe. Fail
    # fast instead, matching contracts.py's recompute-plan endpoint's
    # handling of the same error. The per-symbol _merge_rr_cfg(overrides)
    # call inside _process_symbol is left in place as defense in depth (now
    # effectively unreachable via this endpoint since the same overrides
    # dict is validated here first).
    try:
        _merge_rr_cfg(req.overrides)
        resolve_target_r_multiple(req.overrides)
        _entry_config = resolve_entry_config(req.overrides)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # DOCC-1 S2: the four money blocks are required, explicit and closed
    # (decisions DOCC-9.6-MONEY-BLOCKS-REQUIRED-2026-09-28 and
    # DOCC-9.8-CLOSED-MONEY-SUBTREES-2026-09-28). Checked BEFORE `_resolve_gate`
    # below, which bare-indexes `confidence_gate` and would otherwise answer a
    # missing block with an unnamed KeyError. 500 and a log line, for the
    # reasons given at the conviction-floor check below.
    try:
        _cfg_doc = _load_scoring_cfg()
        observe_configuration("options.scoring", _cfg_doc)
    except (OSError, yaml.YAMLError) as e:
        _log.error("SCAN %s aborted: scoring_rules.yaml unreadable: %s", scan_id, e)
        raise HTTPException(status_code=500, detail=f"scoring_rules.yaml unreadable: {e}")
    if not isinstance(_cfg_doc, dict):
        _msg = f"scoring_rules.yaml must be a mapping, got {type(_cfg_doc).__name__}"
        _log.error("SCAN %s aborted: %s", scan_id, _msg)
        raise HTTPException(status_code=500, detail=_msg)
    try:
        validate_money_blocks(_cfg_doc)
    except MoneyConfigError as e:
        _log.error("SCAN %s aborted on scoring_rules.yaml money blocks: %s", scan_id, e)
        raise HTTPException(status_code=500, detail=str(e))
    # DOCC-2 S2 (decision DOCC-2-REGIME-BLOCK-REFUSES-2026-09-28): a broken
    # regime.<horizon> refuses the whole scan. It used to be read inside
    # `_process_symbol`'s regime `try`, whose handler only logs a WARNING, so
    # the symbol was scored with NO headwind gate and names the gate would
    # REJECT came back PASS (round-5 finding G2).
    try:
        validate_regime_block(_cfg_doc, (req.horizon,))
    except RegimeConfigError as e:
        _log.error("SCAN %s aborted on scoring_rules.yaml regime block: %s", scan_id, e)
        raise HTTPException(status_code=500, detail=str(e))

    gate = _resolve_gate(req)
    observe_configuration("options.confidence_gate", gate)
    # Direction-conviction floor, resolved HERE — before the chain, quote and
    # fundamentals fan-out below — so a malformed threshold costs nothing. The
    # gate itself runs after `asyncio.gather`; resolving it there would let a
    # config typo burn a full rate-limited scan of the universe before failing.
    #
    # 500, not 4xx: the request is fine, the SERVER's YAML is broken and no
    # request can succeed until it is fixed. This endpoint already raises a
    # genuine 422 a few lines above for a malformed USER override from the
    # Step-3 panel; reusing that status here would make "your input is wrong"
    # and "the server is misconfigured" indistinguishable to the client.
    # HTTPException serialises `detail` at any status, so the message naming
    # the offending key survives to the UI and to the scheduled path's
    # `record_scheduled_scan_run(error=str(exc))`.
    #
    # The explicit log line is NOT redundant: this app installs no exception
    # handler or logging middleware, and starlette's ExceptionMiddleware
    # returns an HTTPException WITHOUT logging it — so raising a 500 here
    # would otherwise leave no server-side trace at all, which is strictly
    # worse than the unhandled ValueError it replaced.
    try:
        _direction_min_trend = load_direction_conviction_min_trend(req.direction, req.horizon)
    except ValueError as e:
        _log.error("SCAN %s aborted on malformed scoring_rules.yaml: %s", scan_id, e)
        raise HTTPException(status_code=500, detail=str(e))
    # Asymmetric ATR override — a lone target or stop is ignored (both or neither).
    _atr_target = req.confidence_atr_mult_target
    _atr_stop = req.confidence_atr_mult_stop
    if _atr_target is None or _atr_stop is None:
        _atr_target = _atr_stop = None

    candidates: list[TradeCardData] = []
    rejected: list[RejectedCandidate] = [
        RejectedCandidate(symbol=_x.symbol, reason=f"Excluded (data): {_x.reason}")
        for _x in _excluded
    ]
    # Excluded symbols were scanned and dropped, so the funnel's `scanned` (and
    # the direction banner's "of N") count them: scanned == sum of buckets.
    _scanned = len(symbols) + len(_excluded)
    has_exception = False

    # Pre-fetch all prices in one Tradier batch call (removes N individual HTTP requests)
    try:
        price_map = await asyncio.to_thread(fetch_quotes, symbols)
    except Exception as exc:
        _log.warning("scan: batch price fetch failed (%s) — using per-symbol fallback", exc)
        price_map = {}

    # Pre-fetch OHLCV bars from DB for all symbols — replaces per-symbol Tradier calls.
    from app.services.historical_store import get_bars as _get_bars
    from datetime import date as _date, timedelta as _td
    _bar_end = _date.today()
    _bar_start = _bar_end - _td(days=int(1.75 * 252))  # 441 calendar days ≈ 316 weekdays ≈ ~306 trading days, NOT 252
    # Captured before any bar is read (this gather, and the per-symbol fallback
    # fetch later): a refresh evicting a symbol after it makes set_cached drop the
    # confidence computed from these bars (audit R2-F1).
    _bars_generation = confidence_cache.generation()
    _bars_results = await asyncio.gather(
        *[_get_bars(sym, _bar_start, _bar_end) for sym in symbols],
        return_exceptions=True,
    )
    bars_map = {
        sym: result
        for sym, result in zip(symbols, _bars_results)
        if isinstance(result, list) and result
    }
    _bars_from_db = len(bars_map)
    _bars_missed = len(symbols) - _bars_from_db

    # Pre-fetch fundamentals for all non-intraday symbols
    fund_gate = _resolve_fundamentals_gate(req)
    observe_configuration("options.fundamentals_gate", fund_gate)
    fund_map: dict[str, FundamentalHealth | None] = {}
    if str(req.horizon).lower() != "intraday":
        _staleness = fund_gate.get("staleness_days", 90)
        _fund_results = await asyncio.gather(
            *[get_fundamentals(sym, staleness_days=_staleness) for sym in symbols],
            return_exceptions=True,
        )
        for sym, snap in zip(symbols, _fund_results):
            if isinstance(snap, Exception):
                fund_map[sym] = None
            else:
                fund_map[sym] = score_fundamentals(snap, req.direction, fund_gate) if snap else None

    # ── DTE window from the holding horizon ───────────────────────────────────
    # Absent hold days (e.g. an older client), the fetch/validator defaults apply.
    # ScanRequest's own validator guarantees well-ordered, non-negative hold days;
    # resolve_dte_bounds() still falls back to None on a misconfigured
    # dte_holding_multiplier rather than raise, since this runs before the
    # per-symbol task loop and an unguarded raise here would 500 the whole scan.
    _dte_bounds: tuple[int, int] | None = None
    _dte_win: DteWindow | None = None
    if req.hold_min_days is not None and req.hold_max_days is not None:
        _dte_bounds = resolve_dte_bounds(
            req.hold_min_days, req.hold_max_days, dte_holding_multiplier,
            log_context=f"SCAN {scan_id}",
        )
        if _dte_bounds is not None:
            # Safe to call dte_holding_multiplier() again here, unguarded: we only
            # reach this branch if resolve_dte_bounds() already called it
            # successfully once inside its own try/except, and _load_config()'s
            # underlying YAML read is cached (see contract_validator.py:42-45), so
            # this second call reads the same cached config and cannot newly fail.
            _mult = dte_holding_multiplier()
            _dte_win = DteWindow(min_dte=_dte_bounds[0], max_dte=_dte_bounds[1], multiplier=_mult)
            _log.info("SCAN %s dte_window: %d-%dd (hold %d-%dd x %.1f)",
                      scan_id, _dte_bounds[0], _dte_bounds[1],
                      req.hold_min_days, req.hold_max_days, _mult)

    # P3c item 2: the relative_strength benchmark, fetched once per scan (None
    # unless that trend method is on, so the shipped `additive` method fetches
    # nothing). A failure here -- a malformed `trend` block raises outside the
    # helper's own try -- must not fail the scan: None leaves every trend
    # unmeasured, the fail-closed outcome.
    try:
        _rs_bench = await _rs_benchmark_candles(
            SimpleNamespace(horizon=req.horizon, overrides=req.overrides or {}))
    except Exception as exc:
        _log.warning("SCAN %s rs_benchmark resolve failed: %s -- trend left unmeasured", scan_id, exc)
        _rs_bench = None
    _rs_misaligned: list[str] = []

    # The event window score_stock will apply, echoed on the result (see
    # effective_event_window). Never allowed to fail the scan.
    _event_win = None
    try:
        _ew = effective_event_window(req.horizon, req.overrides)
        _event_win = EventWindow(reject_days=_ew[0], caution_days=_ew[1])
    except Exception as exc:
        _log.warning("SCAN %s event_window unavailable: %s", scan_id, exc)

    veto_days = _resolve_earnings_veto_days(
        req.horizon, req.overrides, req.hold_max_days,
        _event_win.reject_days if _event_win is not None else None,
    )
    if _event_win is not None:
        _event_win.veto_days = veto_days

    # The contract rules every symbol below is graded with (before the hold-days
    # DTE widening, which /api/contracts re-derives from the same hold days),
    # echoed on the result so Step 6's table grades with them too. Never
    # allowed to fail the scan: None makes Step 6 say the rules are unknown.
    _contract_rules = None
    try:
        _rules = effective_contract_overrides(req.overrides)
        # A non-finite value ("inf", "nan" -- float() takes both) cannot be sent
        # back: it serialises as null and /api/contracts refuses it. Record
        # nothing instead, so Step 6 says the rules are unknown.
        if all(is_finite_rule_value(v) for v in _rules.values()):
            _contract_rules = _rules
        else:
            _log.warning("SCAN %s contract_rules not recorded: non-finite value in %s", scan_id, _rules)
    except Exception as exc:
        _log.warning("SCAN %s contract_rules unavailable: %s", scan_id, exc)

    # The Reward/Risk overrides every plan below is priced with, echoed so
    # Step 7's recompute-plan reprices with the scan's values rather than live
    # scanOverrides (STEP3-PARAM-REACH). Validated above (422 on a bad value);
    # never allowed to fail the scan: None makes Step 7 fall back to live.
    _rr_overrides = None
    try:
        _rr_overrides = effective_rr_overrides(req.overrides)
    except Exception as exc:
        _log.warning("SCAN %s rr_overrides unavailable: %s", scan_id, exc)

    _entry_overrides = None
    try:
        _entry_overrides = effective_entry_overrides(req.overrides)
    except Exception as exc:
        _log.warning("SCAN %s entry_overrides unavailable: %s", scan_id, exc)

    # The request fields Steps 5-7 read back as their scan context, echoed so a
    # result restored into an empty browser does not default to Bullish/Swing.
    _request_context = None
    try:
        _request_context = ScanRequestContext(
            universe=list(req.universe),
            direction=req.direction,
            horizon=req.horizon,
            horizon_preset=req.horizon_preset,
            hold_min_days=req.hold_min_days,
            hold_max_days=req.hold_max_days,
        )
    except Exception as exc:
        _log.warning("SCAN %s request_context unavailable: %s", scan_id, exc)

    observe_configuration("options.contract_rules", _contract_rules)
    observe_configuration("options.event_window", _event_win)
    observe_configuration("options.dte_window", _dte_bounds)
    semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)
    _tradier_tok, _tradier_base = get_tradier_creds()
    async with httpx.AsyncClient(
        base_url=httpx.URL(_tradier_base),
        headers={
            "Authorization": f"Bearer {_tradier_tok}",
            "Accept": "application/json",
        },
        timeout=httpx.Timeout(10.0),
    ) as client:
        tasks = [
            _process_symbol(
                symbol, req.direction, req.horizon, client, semaphore, scan_id,
                min_price=req.min_price,
                max_price=req.max_price,
                min_cap_usd=req.min_cap_usd,
                max_cap_usd=req.max_cap_usd,
                overrides=dict(req.overrides) if req.overrides else None,
                dte_bounds=_dte_bounds,
                hold_min_days=req.hold_min_days,
                hold_max_days=req.hold_max_days,
                veto_days=veto_days,
                horizon_preset=req.horizon_preset,
                gate=gate,
                atr_mult_target=_atr_target,
                atr_mult_stop=_atr_stop,
                regime_headwind_caution_pct=req.regime_headwind_caution_pct,
                regime_headwind_reject_pct=req.regime_headwind_reject_pct,
                price_map=price_map,
                bars_map=bars_map,
                fund_map=fund_map,
                fund_gate=fund_gate,
                spread_width=req.spread_width,
                short_leg_delta=req.short_leg_delta,
                iv_rank_threshold=req.iv_rank_threshold,
                iv_abs_threshold=req.iv_abs_threshold,
                min_credit=req.min_credit,
                max_debit_pct=req.max_debit_pct,
                direction_min_trend=_direction_min_trend,
                rs_benchmark=_rs_bench,
                rs_misaligned=_rs_misaligned,
                bars_generation=_bars_generation,
                entry_cfg=_entry_config,
            )
            for symbol in symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    if _rs_bench is not None:
        _log.info("SCAN %s rs_benchmark: misaligned=%d of %d",
                  scan_id, len(_rs_misaligned), len(symbols))

    _log.info(
        "SCAN %s data-provenance: bars_from_db=%d bars_missed=%d symbols=%d",
        scan_id, _bars_from_db, _bars_missed, len(symbols),
    )

    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception):
            has_exception = True
            observe_data_failure(symbol)
            rejected.append(RejectedCandidate(symbol=symbol, reason=str(result)))
        elif isinstance(result, RejectedCandidate):
            rejected.append(result)
        elif isinstance(result, TradeCardData):
            candidates.append(result)

    # ── Direction conviction filter ───────────────────────────────────────────
    # Removes candidates that show no actual directional structure — prevents
    # "least bad" stocks in an opposing trend from polluting the results.
    # Intraday is exempt: intraday reversals are common regardless of daily trend.
    #
    # A FLOOR IN BOTH DIRECTIONS. The trend rule is direction-aware, so a high
    # trend score on a Bearish scan means a strong DOWNtrend — the setup a put
    # wants — and the thing this gate removes is a LOW score either way. The
    # bearish side was a ceiling until 2026-09-16 and deleted exactly the
    # candidates it should have kept; see config_loader for the full note.
    #
    # Thresholds live in scoring_rules.yaml
    # (horizons.<horizon>.direction_conviction) with defaults in config_loader.
    # `None` means this direction/horizon is exempt. `_direction_min_trend` was
    # resolved at the top of this function, before the fan-out.
    _min_trend = _direction_min_trend
    if _min_trend is not None and candidates:
        _kept: list[TradeCardData] = []
        for _c in candidates:
            # `stockBreakdown` is a REQUIRED field on TradeCardData
            # (schemas/__init__.py), and a pydantic model defines neither
            # __bool__ nor __len__, so it is always truthy. The `if ... else 50`
            # guard this used to carry was dead, and its 50 quietly changed
            # meaning when the gate became a floor — it went from "rejected on a
            # bearish scan" to "passes". Removed rather than re-tuned.
            # An int, but never a placeholder: an UNMEASURED trend (0 or 50
            # with nothing measured) was already removed as "no data" in
            # _process_symbol (P3c item 2), so what reaches here is a reading.
            _t = _c.stockBreakdown.trend
            if _t < _min_trend:
                rejected.append(RejectedCandidate(
                    symbol=_c.symbol,
                    # `:g` so a threshold that resolved to 40.0 reads "40" in
                    # the rejection record the user sees, not "40.0".
                    reason=f"direction_conviction: trend {_t} < {_min_trend:g} "
                           f"for {req.direction} {req.horizon}",
                ))
            else:
                _kept.append(_c)
        candidates = _kept

    # Two funnel buckets for the one gate, as the stock scan keeps them:
    # `failed_direction` is a MEASURED trend below the floor (removed above,
    # after scoring); `failed_direction_unmeasured` is "no data" (removed in
    # _process_symbol, right after the pre-screen and BEFORE the chain fetch,
    # so the funnel must not show those names as having passed chain and
    # contracts). "direction_conviction:" does not match the unmeasured
    # prefix. The BANNER counts both, since both are this gate's removals.
    def _is_direction(r):
        return r.reason.startswith("direction_conviction:")
    def _is_direction_unmeasured(r):
        return r.reason.startswith("direction_conviction_unmeasured:")
    _dir_removed = sum(1 for r in rejected if _is_direction(r) or _is_direction_unmeasured(r))

    # Compose direction banner: shown when candidates all score CAUTION, or when
    # nothing survived and the direction gate removed some. The stock scan's
    # form, word for word: counts, not a cause -- "market structure does not
    # support" named a cause the scan did not measure.
    _direction_banner: str | None = None
    if not candidates and _dir_removed > 0:
        _floor = f" (trend below {_min_trend:g})" if _min_trend is not None else ""
        _rest = ("" if _dir_removed >= _scanned
                 else "; the rest were removed by other gates — see the pipeline")
        _direction_banner = (
            f"No {req.direction.lower()} candidates survived. The direction-conviction gate "
            f"removed {_dir_removed} of {_scanned}{_floor}{_rest}."
        )
    elif candidates and all(c.status == "CAUTION" for c in candidates):
        _direction_banner = (
            f"No strong {req.direction.lower()} setups detected. "
            "All candidates are CAUTION-grade — consider reducing size or waiting for a clearer signal."
        )

    # ── Shortlist cap ─────────────────────────────────────────────────────────
    # Clamped like the override below: a settings value of 0 or less would
    # otherwise slice nonsensically and now also write every candidate into
    # `rejected` as "ranked 0 of N (cap -1)".
    _default_max = max(1, min(50, int(_settings.get("scan", {}).get("shortlist_max_candidates", 10))))
    try:
        _overrides = req.overrides or {}
        max_candidates: int = max(1, min(50, int(
            _overrides.get("shortlist_max_candidates", _default_max)
        )))
    except (ValueError, TypeError):
        max_candidates = _default_max
    observe_configuration("options.shortlist", {"max_candidates": max_candidates})
    # Rank BEFORE cutting. `candidates` arrives in universe-file order (the
    # order of `symbols`), so slicing it unsorted kept whichever names happened
    # to sit early in sp500.csv and dropped higher scorers further down — a
    # measured Semi-annual run lost PFE, CRM, GILD, HPE and SMCI that way while
    # keeping lower-scoring names. finalStatus first (a CAUTION must never push
    # out a PASS), then stock score, then contract score. The sort is stable,
    # so exact ties keep universe order. It runs even when nothing is trimmed:
    # _compute_deltas reads list position as rank, which is only meaningful
    # once the list is ranked.
    candidates.sort(key=lambda c: (
        _SHORTLIST_STATUS_ORDER.get(c.finalStatus, len(_SHORTLIST_STATUS_ORDER)),
        -c.stockScore,
        -c.contractScore,
    ))
    original_count: int = len(candidates)
    shortlist_truncated: bool = original_count > max_candidates
    # Trimmed names go into `rejected` with a reason the funnel can classify
    # (`_is_shortlist` below). Before, they vanished: neither returned nor
    # rejected, so a user could not tell a name the cap dropped from one the
    # scan never looked at.
    for _rank, _c in enumerate(candidates[max_candidates:], start=max_candidates + 1):
        rejected.append(RejectedCandidate(
            symbol=_c.symbol,
            reason=f"{_SHORTLIST_REASON_PREFIX} {_c.finalStatus} score {_c.stockScore} "
                   f"contract {_c.contractScore} ranked {_rank} of {original_count} (cap {max_candidates})",
        ))
    candidates = candidates[:max_candidates]

    # ── Pipeline funnel counters ───────────────────────────────────────────────
    # Built HERE, after every filter, not straight after scoring. Snapshotting
    # `candidates` before the direction-conviction gate made the funnel report a
    # yield the ranking table never received: a Bearish/Position scan that scored
    # 5 candidates and then had all 5 stripped for trend > 40 rendered
    # "Candidates 5" above a table with no rows and, because step-4-ranking
    # returns early when the list is empty, no banner explaining where they went.
    # stock_scan.py has always built StockPipeline after its own filters; this is
    # the options path catching up, so the invariant holds:
    # pipeline.candidates == len(result.candidates) == rows in the table.
    #
    # `other_rejected` is the RESIDUAL, computed as a leftover rather than by a
    # predicate of its own. Every bucket below matches on `r.reason` text, and a
    # per-symbol exception is recorded as `reason=str(result)` (line ~1528),
    # which for httpx/asyncio errors is routinely the empty string -- matching
    # nothing. Counting the residual instead of enumerating causes is what makes
    # `scanned == candidates + every bucket` true on a PARTIAL/FAILED run and on
    # any future reason nobody remembered to classify.
    _data_kw = ("no market data", "price filter", "cap filter")
    # "regime data unavailable:" (P3c item 1) is a data drop, as the stock scan
    # counts it under failed_history (no 15-min regime bars is like no price).
    # "Excluded (data):" (STOCKS-HORIZON-P0A A2) is a `scope: scan` symbol from
    # universe_exclusions.yaml, dropped before any per-symbol work.
    def _is_data(r):       return (any(k in r.reason for k in _data_kw)
                                   or r.reason.startswith("regime data unavailable:")
                                   or r.reason.startswith("Excluded (data):"))
    def _is_pre_screen(r): return r.reason.startswith("Pre-screen:")
    def _is_no_chain(r):   return r.reason == "no option chain"
    def _is_score(r):      return r.reason.startswith("Score gate:")
    def _is_contracts(r):  return "contracts rejected" in r.reason
    def _is_shortlist(r):  return r.reason.startswith(_SHORTLIST_REASON_PREFIX)
    _buckets = (_is_data, _is_pre_screen, _is_direction_unmeasured, _is_no_chain,
                _is_score, _is_contracts, _is_direction, _is_shortlist)

    _pipeline = OptionsPipeline(
        scanned=_scanned,
        failed_data=sum(1 for r in rejected if _is_data(r)),
        failed_pre_screen=sum(1 for r in rejected if _is_pre_screen(r)),
        no_chain=sum(1 for r in rejected if _is_no_chain(r)),
        failed_score=sum(1 for r in rejected if _is_score(r)),
        failed_contracts=sum(1 for r in rejected if _is_contracts(r)),
        other_rejected=sum(1 for r in rejected if not any(f(r) for f in _buckets)),
        failed_direction=sum(1 for r in rejected if _is_direction(r)),
        failed_direction_unmeasured=sum(1 for r in rejected if _is_direction_unmeasured(r)),
        direction_min_trend=_min_trend,
        failed_shortlist=original_count - len(candidates),
        candidates=len(candidates),
    )
    # NO-LIVE-QUOTE (plan 3f): names whose every contract had no live quote.
    # Not a funnel bucket -- those names stay under failed_contracts.
    _no_live_quote_names = sum(
        1 for r in rejected if _NO_LIVE_QUOTE_ONLY_REASON.fullmatch(r.reason)
    )
    _log.info(
        "SCAN %s pipeline: scanned=%d data_fail=%d pre_screen_fail=%d direction_unmeasured=%d no_chain=%d score_fail=%d contract_fail=%d direction_fail=%d shortlist_trim=%d other=%d candidates=%d",
        scan_id, _pipeline.scanned, _pipeline.failed_data, _pipeline.failed_pre_screen,
        _pipeline.failed_direction_unmeasured,
        _pipeline.no_chain, _pipeline.failed_score, _pipeline.failed_contracts,
        _pipeline.failed_direction, _pipeline.failed_shortlist, _pipeline.other_rejected,
        _pipeline.candidates,
    )

    # Determine state: PARTIAL if some exceptions occurred but we still got candidates
    state: ScanState = 'COMPLETED'
    if has_exception and candidates:
        state = 'PARTIAL'
    elif has_exception and not candidates:
        state = 'FAILED'

    deltas = _compute_deltas(
        # TRANSIENT -- built only to hand _compute_deltas a comparable shape,
        # never persisted and never returned, so the stamp is functionally
        # irrelevant here. Stamped anyway to keep the invariant TOTAL: "every
        # ScanResult construction carries the version" is enforceable by the
        # AST check in test_scan_result_vintage.py, whereas "every construction
        # that might one day be persisted" is a judgement call that drifts --
        # which is how the scheduler's write site went unstamped for two rounds.
        ScanResult(
            schema_version=SCAN_RESULT_SCHEMA_VERSION,
            scan_id=scan_id, timestamp=datetime.now(timezone.utc).isoformat(),
            candidates=candidates, rejected=rejected,
        ),
        previous_result,
    )

    result = ScanResult(
        # ROUND 4 findings 3 and 13. Stamped HERE, where the result is produced,
        # rather than at each write site. _upsert_session stamped its own copy
        # via model_copy, which left two holes: the scheduler wrote
        # `result.model_dump_json()` straight into scheduled_scan_runs UNSTAMPED
        # (so every scheduled row was indistinguishable from a pre-split blob,
        # and any future attempt to enforce the vintage guard on that table
        # would have discarded ALL of them), and the in-memory _last_result kept
        # the unstamped original, so /api/scan/last reported schema_version null
        # for a scan run in this process and 1 for the same scan after a
        # restart. Stamping at production means a writer cannot forget.
        #
        # The field's DEFAULT must stay None: it is the pre-split marker, and a
        # default of 1 would make every old blob parsed from JSON claim to be
        # current, which is the whole thing the marker exists to detect.
        schema_version=SCAN_RESULT_SCHEMA_VERSION,
        scan_id=scan_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        candidates=candidates,
        rejected=rejected,
        state=state,
        previous_run_id=previous_result.scan_id if previous_result else None,
        deltas=deltas,
        shortlist_truncated=shortlist_truncated,
        original_count=original_count,
        pipeline=_pipeline,
        direction_banner=_direction_banner,
        dte_window=_dte_win,
        event_window=_event_win,
        contract_rules=_contract_rules,
        rr_overrides=_rr_overrides,
        entry_overrides=_entry_overrides,
        request_context=_request_context,
        noLiveQuoteNames=_no_live_quote_names,
    )
    return result


# AUTOTRADE-FIRE-HYGIENE H1: run_scan's auto-fire runs
# `auto_trader.maybe_fire_on_scan` here, and keeps the concurrent Future so a
# cancelled request still records what the worker did (`_log_scan_fire_outcome`).
# DEDICATED: not /fire's `_FIRE_EXECUTOR` and not the default pool the scan's
# data fetches use. ONE worker, so a second manual scan's trigger QUEUES behind
# the first; a queued call cancelled with its request never runs. The
# AutoTrader lock and `expect`/identity checks stay the guards against /fire or
# a re-arm racing it — this serialises scan triggers only. Non-daemon, joined at
# interpreter exit like the default executor's.
_SCAN_FIRE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="scan-auto-fire",
)


def _fired_order_fields(fired) -> str:
    """The returned order's own identity, for a diagnostic. Selected fields
    only, never a whole object. May raise: callers format it inside a guard."""
    order, strategy = fired.result, fired.strategy
    return (
        f"symbol={strategy.symbol} option_symbol={strategy.option_symbol} "
        f"broker={order.broker} order_id={order.order_id!r} "
        f"status={order.status!r} attempt_id={fired.attempt_id}"
    )


def _log_scan_booking_unconfirmed(scan_id, fired) -> None:
    """AUTOTRADE-FIRE-HYGIENE H2: POST /scan was cancelled WHILE
    `book_fired_order` was awaited.

    The writer may already have committed the position (it commits before the
    audit record, history link and pages that follow), and a cancelled
    coroutine does not roll that back — so this says neither booked nor NOT
    booked, and asks for nothing to be added. Runs ONCE, on the loop, in
    run_scan's handler just before the re-raise; nothing books again. MUST NOT
    RAISE: it would replace the CancelledError.
    """
    head = "scan auto-trade: POST /scan was cancelled"
    try:
        _log.error("%s while the fired order was being booked (scan %s); "
                   "booking confirmation unavailable; check broker and "
                   "portfolio before acting: %s (status as the broker "
                   "reported it)", head, scan_id, _fired_order_fields(fired))
    except Exception as fmt_exc:
        try:
            _log.error("%s while the fired order was being booked (scan %s); "
                       "booking confirmation unavailable; check broker and "
                       "portfolio before acting (order not describable: %s)",
                       head, scan_id, type(fmt_exc).__name__)
        except Exception:
            pass


def _log_scan_fire_outcome(scan_id, cf: concurrent.futures.Future) -> None:
    """Record the outcome of a `maybe_fire_on_scan` whose POST /scan was cancelled.

    Runs as a `concurrent.futures` done-callback — in the worker thread when
    the call finishes, or at once if it already has — so it is written even
    while shutdown is cancelling every task. Writes ONE log line and nothing
    else: no portfolio, risk or history row. Booking never started on this
    path; the request's session is gone. MUST NOT RAISE (`add_done_callback`
    would swallow it and lose the line): `cancelled()` first, `exception()`
    before `result()`, and every field is formatted inside the guard. Logs
    selected fields only, never a whole object (an adapter config may ride
    along on one).
    """
    head = "scan auto-trade: POST /scan was cancelled"
    try:
        if cf.cancelled():
            _log.warning("%s before maybe_fire_on_scan ran (scan %s); nothing "
                         "was dispatched", head, scan_id)
            return
        exc = cf.exception()
        if exc is not None:
            detail = f"{type(exc).__name__}: {exc}"
            _log.error("%s while maybe_fire_on_scan ran (scan %s); it raised "
                       "%s. Whether an order reached the broker is unknown and "
                       "this scan booked nothing; check the broker and "
                       "portfolio before acting", head, scan_id, detail)
            return
        fired = cf.result()
        if fired is None:
            # Not armed, stale or refused: the service's own diagnostics for
            # that exit are authoritative, so this does not restate them.
            _log.warning("%s while maybe_fire_on_scan ran (scan %s); it "
                         "returned no order, so there was nothing to book",
                         head, scan_id)
            return
        # The ORDER THE WORKER RETURNED — never the armed slot, which a re-arm
        # may have replaced. Status is the broker's word, not interpreted: a
        # rejected order is logged as rejected, not as a position.
        fields = _fired_order_fields(fired)
        _log.error("%s while maybe_fire_on_scan ran (scan %s); the broker "
                   "returned an order outcome and booking never started, so "
                   "it was NOT booked: %s (status as the broker reported it). "
                   "Check the broker and portfolio before acting",
                   head, scan_id, fields)
    except Exception as fmt_exc:
        try:
            _log.error("%s while maybe_fire_on_scan ran (scan %s); its outcome "
                       "could not be described (%s) and was NOT booked; check "
                       "the broker and portfolio before acting",
                       head, scan_id, type(fmt_exc).__name__)
        except Exception:
            pass


@router.post('/scan', response_model=ScanResult)
async def run_scan(req: ScanRequest, db: AsyncSession = Depends(get_db)) -> ScanResult:
    """Manual-trigger entry point — unchanged external behavior for the UI.

    Note (accepted behavioral narrowing): `previous` is read *before*
    _execute_scan_core runs, not atomically with the write at the end, as it
    was pre-refactor. Under two genuinely overlapping manual run_scan() calls
    (already possible today — nothing serializes two manual scans, or a
    manual scan against a scheduled Part-3 run either — see the concurrency
    note on _SCHEDULED_SCAN_SEMAPHORE in scan_schedule_scheduler.py), both
    calls could read the same stale `_last_result` before either writes,
    producing deltas neither reflects the other's outcome. Today's behavior
    under that same scenario isn't a clean "first writer wins" either — it's
    already best-effort — so this is accepted as-is rather than engineered
    around."""
    global _last_request, _last_result
    async with _state_lock:
        previous = _last_result
    result = await run_reported_scan(req, category="options", trigger="manual",
        callback=lambda: _execute_scan_core(req, db, previous_result=previous))
    async with _state_lock:
        _last_result = result
        _last_request = req
    # Trigger #2: fire armed auto-trade only when at least one PASS candidate exists.
    # Run off the event loop — the broker call inside is synchronous network I/O.
    # Manual-trigger only — Part 3's scheduled runner never reaches this.
    if any(c.finalStatus == 'PASS' for c in result.candidates):
        from app.services.auto_trader import auto_trader as _auto_trader
        if _auto_trader.get_state().armed:
            from app.models.portfolio import PortfolioPositionModel
            from app.services.portfolio_risk import orm_positions_to_risk
            _qr = await db.execute(select(PortfolioPositionModel))
            _orm_pos = _qr.scalars().all()
            _portfolio_snapshot = orm_positions_to_risk(_orm_pos)
            # Scan persistence occurs in _upsert_session below. This read-only
            # transaction can release its connection while the worker reserves
            # durable budget in a fresh transaction on the originating loop.
            from app.services.portfolio_exposure_hooks import capture_exposure_hooks, sessions_for
            exposure_sessions = sessions_for(db)
            await db.rollback()
            from app.services.daily_risk_hooks import capture_daily_risk_hooks
            hooks = capture_daily_risk_hooks()
            exposure_hooks = capture_exposure_hooks(exposure_sessions) if exposure_sessions is not None else None
            cf = _SCAN_FIRE_EXECUTOR.submit(
                _auto_trader.maybe_fire_on_scan,
                _portfolio_snapshot,
                None,  # fire() resolves the server account configuration at dispatch
                daily_risk_hooks=hooks,
                exposure_hooks=exposure_hooks,
            )
            # AUTOTRADE-FIRE-HYGIENE H2: this block owns the fire's outcome
            # until booking returns, and `phase` says how far it got, so a
            # cancellation reports only what is known — once:
            # - "worker_pending" / "booking_not_started": no await separates
            #   delivery from the booking call, so a cancel at delivery is
            #   raised by the worker await with `cf` already done. Either way
            #   the H1 callback below logs the worker's outcome; booking never
            #   started.
            # - "booking_started": the writer may have committed; confirmation
            #   unavailable, and nothing books again.
            # - "booking_returned": no await follows inside the block; the
            #   booked / NOT booked line was logged before `_upsert_session`,
            #   so a cancel there leaves that known status standing.
            phase = "worker_pending"
            fired = None
            try:
                fired = await asyncio.wrap_future(cf)
                phase = "booking_not_started"
                # O4 step 5: book the fired order, back ON the event loop with
                # this request's session (it never enters the worker thread).
                # None on every non-fire. `book_fired_order` never raises,
                # pages its own refusals and rolls back what it wrote, so
                # `_upsert_session` below runs on a usable session either way.
                # It lets CancelledError through — handled below.
                if fired is not None:
                    from app.services.auto_trade_booking import book_fired_order
                    phase = "booking_started"
                    booking = await book_fired_order(fired, db)
                    phase = "booking_returned"
                    if booking.booked:
                        _log.info("scan auto-trade: fired order booked as %s", booking.rec_id)
                    else:
                        _log.error("scan auto-trade: fired order NOT booked: %s", booking.error)
            except asyncio.CancelledError:
                if phase in ("worker_pending", "booking_not_started"):
                    # Cancelling the await does not stop a RUNNING worker; the
                    # broker call can still complete. `cf.cancel()` only stops
                    # a call still queued behind the one worker. The outcome is
                    # logged on the THREAD side of `cf` — an asyncio-side
                    # callback would see only "cancelled" during shutdown — and
                    # `add_done_callback` runs it at once if `cf` is already
                    # done. Nothing is booked: the request's session is going
                    # away.
                    cf.cancel()
                    cf.add_done_callback(
                        functools.partial(_log_scan_fire_outcome, result.scan_id))
                elif phase == "booking_started":
                    _log_scan_booking_unconfirmed(result.scan_id, fired)
                raise
    # `req`, not `_last_request`. The global is read AFTER the auto-trade block
    # above, whose awaited `_SCAN_FIRE_EXECUTOR` call is a synchronous broker call —
    # a window measured in seconds. A second overlapping manual scan (nothing
    # serializes two of them; see this function's docstring) completing inside
    # it replaces `_last_request` with ITS request, and this line would then
    # persist THIS scan's result beside THAT scan's request. The crossed row
    # survives a restart: restore_from_db rebuilds the globals from it, and
    # /scan/last-run would report the pair as verified — a matching scan_id
    # next to a threshold the scan never applied, which
    # scripts/iv_basis_analysis.py stamps into the measurement store as
    # measured. The in-memory pair is already atomic (both globals are written
    # together under _state_lock); passing the local request makes the
    # PERSISTED pair atomic too. Found by Phase-A-batch round 1.
    await _upsert_session(db, req=req, result=result, status="complete")
    return result


@router.post('/scan/prewarm-candles')
async def prewarm_candles(req: _PrewarmRequest) -> dict:
    """Pre-populate the candle cache before the scan runs.

    Called from the frontend when the user leaves Step 2 (direction). By the time
    the actual scan executes (Step 4+), daily bars are already in-process cache.
    """
    from app.data.market import prewarm_candles_async
    count = await prewarm_candles_async(req.symbols)
    return {"prewarmed": count}
