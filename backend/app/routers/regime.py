from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Query

from app.schemas import MarketRegime, RegimeMetric, OmmData, IntraHmmData, IntraHmmTransition
from app.data.market import fetch_price, fetch_candles, fetch_intraday_candles
from app.services.regime_omm import compute_omm
from app.services.regime_hmm import compute_intraday_hmm

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


@router.get('/regime', response_model=MarketRegime)
async def get_regime(
    horizon: str = Query(default='swing', description="'intraday' | 'swing' | 'position'"),
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
    try:
        spx_candles = fetch_candles('SPX', bars=600)
        if spx_candles:
            closes = [c['close'] for c in spx_candles]
            result = compute_omm(closes)
            if result:
                omm_out = OmmData(
                    state=result.state,
                    p_stay=result.p_stay,
                    stability=result.stability,
                    regime_age_days=result.regime_age_days,
                    avg_regime_duration=result.avg_regime_duration,
                    transition_row=result.transition_row,
                    state_order=result.state_order,
                )
    except Exception:
        pass

    # ── 4. Gaussian HMM (always computed — regime step is before horizon selection) ─
    intraday_hmm_out: IntraHmmData | None = None
    try:
        intra_bars = fetch_intraday_candles('SPY', interval='15min', days=120)
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
    except Exception:
        pass

    return MarketRegime(
        overall=overall,
        headline=headline,
        metrics=metrics,
        omm=omm_out,
        intraday_hmm=intraday_hmm_out,
        vix_pct_30d=vix_pct_30d,
        vix_pct_252d=vix_pct_252d,
    )
