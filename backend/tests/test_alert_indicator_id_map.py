"""Stable rule references work without chart state, including custom parameters."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.routers.chart_alerts import ConditionGroupIn
from app.services.indicator_compute import compute_indicators_for_conditions, parse_indicator_reference


def candles():
    return [dict(time=f'bar-{i}', open=100+i, close=100+i+(i%3), high=104+i,
                 low=98+i, volume=1000+i*10) for i in range(90)]


@pytest.mark.parametrize('reference', ['EMA(7)', 'SMA(8)', 'RSI(5)', 'ATR(6)',
    'MACD(5,12,4)', 'BB_MID(8,2.5)', 'VWAP', 'volume', 'VOL(default)', 'VWAP(default)',
    'ema20', 'macd_signal', 'bb_upper'])
def test_ui_reference_computes_under_original_key(reference):
    bars = candles()
    condition = SimpleNamespace(kind='indicator', indicator=reference)
    result = compute_indicators_for_conditions(bars, [condition])
    assert len(result[reference]) == len(bars)
    assert result[reference][-1]['value'] is not None
    ConditionGroupIn(conditions=[dict(kind='indicator', indicator=reference, operator='>', value=0)])


@pytest.mark.parametrize('reference', ['', 'ema-20', 'macd-1720000000000', 'EMA(0)',
    'EMA(-1)', 'RSI(1.5)', 'MACD(26,12,9)', 'EMA(' + '1' * 5000 + ')', 'MACD(5,12)', 'SMA(10001)', 'BB_MID(8,nan)', 'BB(8,0)', 'UNKNOWN(2)'])
def test_unrecoverable_or_invalid_reference_cannot_be_saved(reference):
    assert parse_indicator_reference(reference) is None
    assert compute_indicators_for_conditions(candles(), [dict(kind='indicator', indicator=reference)]) == {}
    with pytest.raises(ValidationError):
        ConditionGroupIn(conditions=[dict(kind='indicator', indicator=reference, operator='>', value=0)])


def test_parameterized_ema_uses_seed_bar_and_saved_period():
    bars = candles()
    refs = ['EMA(7)', 'EMA(20)']
    result = compute_indicators_for_conditions(bars, [dict(kind='indicator', indicator=r) for r in refs])
    assert result['EMA(7)'][5]['value'] is None
    assert result['EMA(7)'][6]['value'] == round(sum(b['close'] for b in bars[:7])/7, 4)
    assert result['EMA(7)'][-1]['value'] != result['EMA(20)'][-1]['value']
