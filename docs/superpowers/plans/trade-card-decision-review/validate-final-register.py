"""Fail if any #576 baseline contract is unaccounted for in the final register.

Checks the register against the baseline and the working tree, and the captures
against their own measurements. It validates accounting and evidence integrity;
behaviour is covered by the suites named in final-verification.md.

Run from anywhere: PYTHONUTF8=1 python validate-final-register.py
"""
from collections import Counter
import json
from pathlib import Path
import sys

folder = Path(__file__).resolve().parent
root = folder.parents[3]
ALLOWED = {'kept', 'moved', 'moved-into-expansion', 'deliberate-duplicate-removed', 'changed-with-reason'}
WIDTHS = {1200, 1366, 1920}
THEMES = {'dark', 'light'}
STATES = ['initial', 'calculated', 'stale', 'restored', 'basket-review', 'broker-review', 'outcome']


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def source(path):
    return (root / path).read_text(encoding='utf8').replace('\r\n', '\n')


baseline = read(folder / 'preservation-register.json')
final = read(folder / 'final-register.json')
expected = [e['id'] for e in baseline['historical_entries']]
expected += [e['id'] for e in baseline['inspected_current_contracts']]
expected += [e['id'] for e in baseline['shared_source_contracts']]
assert len(expected) == 625 and len(set(expected)) == 625, 'baseline inventory changed'

entries = final['entries']
got = [e['id'] for e in entries]
missing = sorted(set(map(str, expected)) - set(map(str, got)))
extra = sorted(set(map(str, got)) - set(map(str, expected)))
assert not missing, f'baseline ids unaccounted for: {missing}'
assert not extra, f'ids not in the baseline: {extra}'
assert len(got) == len(set(map(str, got))), 'duplicate ids'
assert final['mini_pc_comparison'] == 'user_deferred_not_verified'

for e in entries:
    tag = e['id']
    assert e['status'] in ALLOWED, (tag, e['status'])
    f = e['final']
    assert f and f['path'] and f['anchor'] and f['region'], (tag, 'no final location')
    text = source(f['path']).split('\n')
    assert 1 <= f['line'] <= len(text), (tag, 'line out of range')
    assert f['anchor'] in text[f['line'] - 1], (tag, f['line'], f['anchor'][:60], 'anchor not on the recorded line')
    if e['status'] == 'moved-into-expansion':
        assert f['disclosure'], (tag, 'moved-into-expansion needs its disclosure')
    if e['status'] in ('changed-with-reason', 'deliberate-duplicate-removed'):
        assert e.get('reason'), (tag, 'needs a reason')
    if e['status'] == 'deliberate-duplicate-removed':
        twin = e.get('unique_twin')
        assert twin and twin['anchor'] in source(twin['path']), (tag, 'unique twin not found')

counts = Counter(e['status'] for e in entries)
assert dict(counts) == final['counts'], 'stored counts disagree'

checks = read(folder / 'evidence/final/checks.json')
runs = checks['runs']
assert {(r['width'], r['theme']) for r in runs} == {(w, t) for w in WIDTHS for t in THEMES}, 'width/theme matrix incomplete'
for r in runs:
    tag = (r['width'], r['theme'])
    assert not r['pageErrors'], (tag, r['pageErrors'])
    assert set(r['layout']) == set(STATES), (tag, 'states incomplete')
    assert not r['guard']['blockedWrites'] and not r['guard']['externalAborted'], (tag, r['guard'])
    assert r['guard']['mockedWrites'] == ['POST /api/portfolio', 'POST /broker/option-order'], (tag, r['guard'])
    for state, m in r['layout'].items():
        assert m['horizontalPageOverflow'] is False, (tag, state, 'overflow')
        assert (folder / f"evidence/final/{r['width']}-{r['theme']}-{state}.png").read_bytes().startswith(b'\x89PNG'), (tag, state)
    calc = r['layout']['calculated']
    assert calc['squeezedTargetRows'] == 0 and calc['rowHeightsEqual'], (tag, 'comparison layout')
    assert all(v <= 8 for v in calc['slotOffsetPx'].values()), (tag, calc['slotOffsetPx'])

print(f'PASS: all {len(expected)} baseline ids accounted for: {dict(counts)}. '
      f'{len(runs)} width/theme runs, {len(STATES)} states each, no unsafe write. '
      'Mini-PC comparison user-deferred, not verified.')
sys.exit(0)
