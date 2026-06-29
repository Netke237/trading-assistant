from __future__ import annotations

import logging
import numpy as np
from fastapi import APIRouter, Query

_log = logging.getLogger(__name__)

from app.schemas import MarketRegime, RegimeMetric, OmmData, IntraHmmData, IntraHmmTransition
from app.data.market import fetch_price, fetch_candles, fetch_intraday_candles
from app.services.regime_omm import compute_omm
from app.services.regime_hmm import compute_intraday_hmm
from app.services.regime_hmm_daily import compute_directional_hmm as _compute_directional_hmm, alignment as _regime_alignment

router = APIRouter(prefix='/api', tags=['trading'])

_PRIORITY = {"REJECT": 0, "CAUTION": 1, "PENDING": 2, "NO_DATA": 2, "PASS": 3}


def _ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _vix_status(vix: float) -> str:
    if vix < 20:
        return 'PASS'
    if vix <= 30:
        return 'CAUTION'
    return 'REJECT'


def _spx_ndx_metric(symbol: str, label: str) -> RegimeMetric | None:
    try:
        candles = fetch_candles(symbol, bars=200)
    except Exception:
        return RegimeMetric(label=label, value='—', status='PENDING', trend=None)

    if not candles:
        return RegimeMetric(label=label, value='—', status='PENDING', trend=None)

    closes = [c["close"] for c in candles]
    ema_200 = _ema(closes, 200)
    if ema_200 is None or len(closes) == 0:
        return RegimeMetric(label=label, value='—', status='PENDING', trend=None)

    price = closes[-1]
    if price > ema_200:
        return RegimeMetric(label=label, value='Above', status='PASS', trend='up')
    if price >= 0.97 * ema_200:
        return RegimeMetric(label=label, value='Near', status='CAUTION', trend='flat')
    return RegimeMetric(label=label, value='Below', status='REJECT', trend='down')


def _vix_percentile(history: list[float], current: float) -> float:
    """Percentile rank of current within history (0–100)."""
    if not history:
        return 50.0
    below = sum(1 for v in history if v < current)
    return round(100.0 * below / len(history), 1)


def _derive_regime_direction(
    omm_state: str | None,
    spx_status: str | None,
    ndx_status: str | None,
) -> str:
    """Return 'BULL', 'BEAR', or 'MIXED' from OMM state (primary) or EMA metrics (fallback).

    OMM states: 'Bull', 'Bear', 'Choppy' (Choppy → MIXED).
    EMA fallback: both indices above 200 EMA → BULL; both below → BEAR; otherwise MIXED.
    The early-return path (no market data) returns MarketRegime with regime_direction=None
    via Pydantic default — intentional; the frontend renders no pill.
    """
    if omm_state == 'Bull':
        return 'BULL'
    if omm_state == 'Bear':
        return 'BEAR'
    if omm_state is not None:          # Choppy or any other OMM state
        return 'MIXED'
    # Fallback: both indices must agree; a single CAUTION yields MIXED
    if spx_status == 'PASS' and ndx_status == 'PASS':
        return 'BULL'
    if spx_status == 'REJECT' and ndx_status == 'REJECT':
        return 'BEAR'
    return 'MIXED'


def compute_overall_regime() -> str:
    """Return the current market overall status (PASS/CAUTION/REJECT/PENDING) without a full MarketRegime object."""
    try:
        spx = _spx_ndx_metric('SPX', 'SPX trend (200 EMA)')
        ndx = _spx_ndx_metric('NDX', 'NDX trend (200 EMA)')
    except Exception:
        return 'PENDING'

    try:
        vix = fetch_price('VIX')
        vix_status = _vix_status(vix) if vix is not None else 'PENDING'
    except Exception:
        vix_status = 'PENDING'

    statuses = [m.status for m in (spx, ndx) if m is not None] + [vix_status]
    if not statuses:
        return 'PENDING'
    return min(statuses, key=lambda s: _PRIORITY.get(s, 2))


@router.get('/regime', response_model=MarketRegime)
async def get_regime(
    horizon:   str   = Query(default='swing',  description="'intraday' | 'swing' | 'position'"),
    lookback:  int   = Query(default=20,   ge=5,   le=252, description='OMM rolling-return window in bars'),
    threshold: float = Query(default=0.02, ge=0.001, le=0.1, description='Bull/Bear return threshold'),
    smoothing: float = Query(default=0.0,  ge=0.0,   le=0.99, description='EMA weight on return signal'),
) -> MarketRegime:
    # ── 1. Existing EMA / VIX gate (unchanged) ────────────────────────────────
    spx = _spx_ndx_metric('SPX', 'SPX trend (200 EMA)')
    ndx = _spx_ndx_metric('NDX', 'NDX trend (200 EMA)')

    try:
        vix = fetch_price('VIX')
    except Exception:
        vix = None

    if vix is not None:
        vix_status = _vix_status(vix)
        vix_metric = RegimeMetric(
            label='VIX',
            value=f'{vix:.1f}',
            status=vix_status,
            trend='down' if vix_status == 'PASS' else ('up' if vix_status == 'REJECT' else 'flat'),
        )
    else:
        vix_metric = RegimeMetric(label='VIX', value='—', status='PENDING', trend=None)

    metrics: list[RegimeMetric] = [m for m in (spx, ndx, vix_metric) if m is not None]
    statuses = [m.status for m in metrics]

    if not statuses:
        return MarketRegime(
            overall='CAUTION',
            headline='Market data unavailable',
            metrics=[],
        )

    overall = min(statuses, key=lambda s: _PRIORITY.get(s, 2))

    parts: list[str] = []
    for m in metrics:
        if m.status == 'PENDING':
            parts.append(f'{m.label} unavailable')
        elif m.label == 'VIX':
            parts.append(f'VIX {m.value} — {m.status}')
        else:
            parts.append(f'{m.label} {m.value} 200 EMA · {m.status}')

    headline = ' · '.join(parts)

    # ── 2. VIX percentile ────────────────────────────────────────────────────
    vix_pct_30d: float | None = None
    vix_pct_252d: float | None = None
    if vix is not None:
        try:
            vix_history = fetch_candles('VIX', bars=260)
            vix_closes = [c['close'] for c in vix_history]
            if len(vix_closes) >= 2:
                vix_pct_30d = _vix_percentile(vix_closes[-31:-1], vix)
                vix_pct_252d = _vix_percentile(vix_closes[:-1], vix)
        except Exception:
            pass

    # ── 3. OMM (always computed — useful for all horizons) ────────────────────
    omm_out: OmmData | None = None
    _spx_hmm_state: str | None = None
    try:
        spx_candles = fetch_candles('SPX', bars=600)
        if spx_candles:
            closes = [c['close'] for c in spx_candles]
            result = compute_omm(
                closes,
                direction="Bullish",
                lookback=lookback,
                threshold=threshold,
                smoothing=smoothing,
            )
            if result:
                omm_out = OmmData(
                    state=result.state,
                    p_stay=result.p_stay,
                    stability=result.stability,
                    regime_age_days=result.regime_age_days,
                    avg_regime_duration=result.avg_regime_duration,
                    transition_row=result.transition_row,
                    state_order=result.state_order,
                    conviction_pct=result.conviction_pct,
                    conviction_label=result.conviction_label,
                )
            # Directional HMM on same SPX series
            try:
                _dh_res = _compute_directional_hmm(spx_candles)
                _spx_hmm_state = _dh_res.state if _dh_res else None
            except Exception as exc:
                _log.debug("Directional HMM unavailable for SPX: %s", exc)
    except Exception:
        pass

    # ── 4. Gaussian HMM (always computed — regime step is before horizon selection) ─
    intraday_hmm_out: IntraHmmData | None = None
    intraday_hmm_status: str = 'unavailable'
    intra_bars: list[dict] = []
    try:
        intra_bars = fetch_intraday_candles('SPY', interval='15min', days=55)
        if intra_bars:
            result_hmm = compute_intraday_hmm(intra_bars)
            if result_hmm:
                intraday_hmm_out = IntraHmmData(
                    state=result_hmm.state,
                    p_stay=result_hmm.p_stay,
                    p_transition=[
                        IntraHmmTransition(to=t['to'], prob=t['prob'])
                        for t in result_hmm.p_transition
                    ],
                )
                intraday_hmm_status = 'ok'
            else:
                # Fetch returned some bars but HMM returned None (insufficient_data)
                intraday_hmm_status = 'insufficient_data'
        # else: intra_bars is empty → status stays 'unavailable'
    except Exception:
        pass

    # ── 5. Intraday OMM fallback (when hmmlearn is unavailable) ──────────────────
    # Compute OMM on the same 15-min bars so the Intraday panel shows something
    # meaningful even on Python versions where hmmlearn can't be installed.
    intraday_omm_out: OmmData | None = None
    if not intraday_hmm_out and intra_bars:
        try:
            closes_15m = [b['close'] for b in intra_bars]
            # lookback=26: one full trading session (6.5 h × 4 bars/h ≈ 26 bars)
            result_intra = compute_omm(closes_15m, lookback=26, threshold=0.002, smoothing=0.2)
            if result_intra:
                intraday_omm_out = OmmData(
                    state=result_intra.state,
                    p_stay=result_intra.p_stay,
                    stability=result_intra.stability,
                    regime_age_days=result_intra.regime_age_days,
                    avg_regime_duration=result_intra.avg_regime_duration,
                    transition_row=result_intra.transition_row,
                    state_order=result_intra.state_order,
                )
        except Exception:
            pass

    return MarketRegime(
        overall=overall,
        headline=headline,
        metrics=metrics,
        omm=omm_out,
        intraday_hmm=intraday_hmm_out,
        intraday_hmm_status=intraday_hmm_status,
        intraday_omm=intraday_omm_out,
        vix_pct_30d=vix_pct_30d,
        vix_pct_252d=vix_pct_252d,
        conviction_pct=omm_out.conviction_pct if omm_out else None,
        conviction_label=omm_out.conviction_label if omm_out else None,
        hmm_state=_spx_hmm_state,
        alignment=_regime_alignment(omm_out.state if omm_out else None, _spx_hmm_state),
        regime_direction=_derive_regime_direction(
            omm_out.state if omm_out else None,
            spx.status if spx else None,
            ndx.status if ndx else None,
        ),
    )


@router.get('/regime/series')
async def get_regime_series(
    symbol: str = 'SPX',
    limit: int = 500,
):
    """Get per-bar OMM regime state for chart background overlay.

    Returns list of {time, state} dicts — one per trading day.
    state: 'Bull' | 'Bear' | 'Choppy'
    """
    from app.services.historical_store import get_bars
    from app.services.regime_omm import compute_regime_series
    from datetime import date, timedelta

    end = date.today()
    start = end - timedelta(days=max(limit * 2, 730))  # fetch enough history
    try:
        bars = await get_bars(symbol, start, end)
    except Exception:
        bars = []
    if not bars:
        return []
    return compute_regime_series(bars[-limit:] if len(bars) > limit else bars)


@router.get('/regime/intraday-series')
async def get_intraday_hmm_series(
    symbol: str = 'SPY',
    interval: str = '15m',
    limit: int = 252,
):
    """Get per-bar HMM state and conviction for intraday chart overlay.

    Returns list of {time, state, conviction} dicts.
    Display only — Viterbi-decoded over full window, not point-in-time.
    """
    from app.services.regime_hmm import compute_intraday_hmm_series

    # Use the same intraday fetch mechanism as the existing /regime endpoint:
    # fetch_intraday_candles from app.data.market
    try:
        bars = fetch_intraday_candles(symbol, interval='15min', days=55)
    except Exception:
        bars = []
    if not bars:
        return []
    return compute_intraday_hmm_series(bars, max_bars=limit)
