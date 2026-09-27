# backend/tests/test_w2_struct_confirmed_at.py
"""W2-STRUCT (Q16): every FVG / OrderBlock / Divergence / BOS / CHoCH signal carries
`confirmed_at` -- the time of the bar that confirms it -- and a standard structure
condition matches on that bar only. Before this, FVG/OrderBlock/Divergence were
matched on `time_start` (a bar BEFORE confirmation) and never fired on the live
path, which recomputes structure up to the closed candle (A4e)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.routers.chart_alerts import closed_candle_structure
from app.services.alert_evaluator import (
    AlertRuleInput, ConditionGroup, StructureCondition, evaluate_rules,
)
from app.services.market_structure import (
    compute_structure, detect_bos_choch, detect_fvg, detect_order_blocks,
)

FIXTURES = sorted((Path(__file__).parent / 'fixtures').glob('*_candles.json'))
KINDS = ('FVG', 'OrderBlock', 'Divergence', 'BOS', 'CHoCH')
START = 40  # replay from here; earlier bars give compute_structure too little history


def _load(path: Path) -> list[dict]:
    raw = json.loads(path.read_text())
    bars = raw if isinstance(raw, list) else raw.get('bars') or raw.get('candles') or next(iter(raw.values()))
    return [{'time': str(b.get('time') or b.get('date')), 'open': b['open'], 'high': b['high'],
             'low': b['low'], 'close': b['close'], 'volume': b.get('volume', 0)} for b in bars]


def _identity(s: dict) -> tuple:
    return (s['kind'], s.get('direction'), s.get('time') or s.get('time_start'),
            s.get('indicator'), s.get('time_end') if s['kind'] == 'Divergence' else None)


def _rule(kind: str, direction: str | None = None) -> AlertRuleInput:
    return AlertRuleInput(
        id=f'r-{kind}', name=kind, symbol='X', interval='1D', enabled=True,
        group=ConditionGroup(logic='AND', conditions=[
            StructureCondition(kind='structure', signal_kind=kind, direction=direction)]),
        cooldown_minutes=0, expiry_date=None, created_at='2024-01-01T00:00:00Z',
        last_triggered_at=None,
    )


def _c(t: str, o: float, h: float, l: float, c: float) -> dict:
    return {'time': t, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': 1000}


# (a) per-kind definitions ---------------------------------------------------

def test_fvg_confirmed_at_is_the_third_bar():
    bars = [_c('d0', 10, 11, 9, 10.5), _c('d1', 11, 14, 11, 13.5), _c('d2', 13.5, 15, 12, 14)]
    [s] = detect_fvg(bars)
    assert (s['direction'], s['time_start'], s['confirmed_at']) == ('bullish', 'd0', 'd2')
    bars = [_c('d0', 14, 15, 13, 13.5), _c('d1', 13, 13, 10, 10.5), _c('d2', 10.5, 11, 9, 9.5)]
    [s] = detect_fvg(bars)
    assert (s['direction'], s['time_start'], s['confirmed_at']) == ('bearish', 'd0', 'd2')


def test_order_block_confirmed_at_is_the_break_bar():
    bars = [_c('d0', 10, 11, 9, 10), _c('d1', 10, 10.5, 9, 9.2), _c('d2', 9.5, 13, 9.4, 12.8)]
    bos = [{'kind': 'BOS', 'direction': 'bullish', 'time': 'd2', 'confidence': 70}]
    [s] = detect_order_blocks(bars, bos)
    assert (s['time_start'], s['confirmed_at']) == ('d1', 'd2')


@pytest.mark.parametrize('path', FIXTURES, ids=lambda p: p.stem)
def test_fixture_definitions(path):
    bars = _load(path)
    times = [b['time'] for b in bars]
    sigs = compute_structure(bars, '1D', 'X')
    for s in sigs:
        if s['kind'] not in KINDS:
            continue
        assert s['confirmed_at'] in times, s  # (c) always a real candle, no right-edge overflow
        if s['kind'] in ('BOS', 'CHoCH'):
            assert s['confirmed_at'] == s['time']
        elif s['kind'] == 'FVG':
            assert times.index(s['confirmed_at']) == times.index(s['time_start']) + 2
        elif s['kind'] == 'Divergence':
            assert times.index(s['confirmed_at']) == times.index(s['time_end']) + 5
    for s in detect_bos_choch(bars):
        assert s['confirmed_at'] == s['time']


# (b) causality: a signal first exists on the bar named by confirmed_at ---------

@pytest.mark.parametrize('path', FIXTURES, ids=lambda p: p.stem)
def test_signal_first_appears_on_its_confirmed_at_bar(path):
    bars = _load(path)
    seen: set[tuple] = set()
    checked = {k: 0 for k in KINDS}
    for j in range(START, len(bars)):
        for s in compute_structure(bars[:j + 1], '1D', 'X'):
            if s['kind'] not in KINDS:
                continue
            key = _identity(s)
            if key in seen:
                continue
            seen.add(key)
            if j == START:
                continue  # already present when the replay starts
            assert s['confirmed_at'] == bars[j]['time'], (s, bars[j]['time'])
            checked[s['kind']] += 1
    assert checked['FVG'] and checked['Divergence'] and checked['BOS']


# (d) end to end on the live path: closed_candle_structure + evaluate_rules ------

def _replay_fires(path: Path) -> dict[str, int]:
    bars = _load(path)
    fired = {k: 0 for k in KINDS}
    for j in range(START, len(bars) - 1):
        closed = bars[j]
        view = bars[:j + 2]  # the forming bar is present, as on the live path
        signals = closed_candle_structure(view, closed, '1D', 'X')
        for kind in KINDS:
            got = evaluate_rules([_rule(kind)], closed, view, {}, signals, datetime(2030, 1, 1))
            expected = any(s['kind'] == kind and s['confirmed_at'] == closed['time'] for s in signals)
            assert bool(got) == expected, (kind, closed['time'])
            fired[kind] += bool(got)
    return fired


@pytest.mark.parametrize('path', FIXTURES, ids=lambda p: p.stem)
def test_structure_rules_fire_on_the_confirmation_bar(path):
    fired = _replay_fires(path)
    assert fired['FVG'] > 0 and fired['Divergence'] > 0


def test_every_new_kind_fires_somewhere_in_the_fixtures():
    total = {k: 0 for k in KINDS}
    for path in FIXTURES:
        for k, v in _replay_fires(path).items():
            total[k] += v
    assert total['FVG'] > 0 and total['OrderBlock'] > 0 and total['Divergence'] > 0


# (e) filters and fallback ---------------------------------------------------

def test_direction_and_confidence_filters_still_apply():
    closed = _c('d2', 1, 1, 1, 1)
    sig = {'kind': 'FVG', 'direction': 'bullish', 'time_start': 'd0', 'confirmed_at': 'd2', 'confidence': 40}
    assert evaluate_rules([_rule('FVG', 'bullish')], closed, [closed], {}, [sig], datetime.now())
    assert not evaluate_rules([_rule('FVG', 'bearish')], closed, [closed], {}, [sig], datetime.now())
    rule = _rule('FVG')
    rule.group.conditions[0].min_confidence = 50
    assert not evaluate_rules([rule], closed, [closed], {}, [sig], datetime.now())


def test_signal_without_confirmed_at_falls_back_to_time():
    closed = _c('d2', 1, 1, 1, 1)
    bos = {'kind': 'BOS', 'direction': 'bullish', 'time': 'd2', 'confidence': 80}
    assert evaluate_rules([_rule('BOS')], closed, [closed], {}, [bos], datetime.now())
    # time_start alone (pre-deploy FVG) behaves as before: it names an earlier bar
    fvg = {'kind': 'FVG', 'direction': 'bullish', 'time_start': 'd0', 'confidence': 80}
    assert not evaluate_rules([_rule('FVG')], closed, [closed], {}, [fvg], datetime.now())


def test_a_signal_confirmed_after_the_closed_bar_does_not_match():
    closed = _c('d2', 1, 1, 1, 1)
    later = {'kind': 'FVG', 'direction': 'bullish', 'time_start': 'd1', 'confirmed_at': 'd3', 'confidence': 80}
    assert not evaluate_rules([_rule('FVG')], closed, [closed], {}, [later], datetime.now())


# (f) dry-run: one full-history list replayed candle by candle --------------------

def test_dry_run_full_list_matches_only_on_confirmation_bars():
    bars = _load(FIXTURES[0])
    full = compute_structure(bars, '1D', 'X')
    for kind in ('BOS', 'FVG'):
        conf = {s['confirmed_at'] for s in full if s['kind'] == kind}
        assert conf
        for i, candle in enumerate(bars):
            got = evaluate_rules([_rule(kind)], candle, bars[:i + 1], {}, full, datetime(2030, 1, 1))
            assert bool(got) == (candle['time'] in conf), (kind, candle['time'])
