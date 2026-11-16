"""Validate evidence integrity only; never certify runtime behavior or phase audit.

Usage: python3 validate.py [--repo-root REPO] [--evidence-root EVIDENCE]
Defaults: discover the repository from cwd/script ancestors; evidence beside script.
"""
import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

MARKER = Path('docs/superpowers/plans/trade-card-decision-review/preservation-register.json')

def discover_repo():
    for origin in (Path.cwd(), Path(__file__).resolve().parent):
        for candidate in (origin, *origin.parents):
            if (candidate / MARKER).is_file():
                return candidate
    return None

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo-root', type=Path, default=discover_repo(), help='Repository root (default: discover from cwd or script ancestors)')
parser.add_argument('--evidence-root', type=Path, default=Path(__file__).resolve().parent, help='Evidence directory (default: this script directory)')
args = parser.parse_args()
if args.repo_root is None:
    parser.error('Cannot discover repository; pass --repo-root.')
root = args.repo_root.resolve()
folder = args.evidence_root.resolve()
b = json.loads((root / MARKER).read_text())
r = json.loads((folder / 'reconciliation.json').read_text())
expected = [e['id'] for key in ('historical_entries', 'inspected_current_contracts', 'shared_source_contracts') for e in b[key]]
got = [e['id'] for e in r['entries']]
assert len(expected) == 625 and len(got) == 625 and len(set(map(str, got))) == 625
assert {(type(x).__name__, x) for x in expected} == {(type(x).__name__, x) for x in got}, 'ID value/type mismatch'
assert sum(type(x) is int for x in got) == 520
assert sum(type(x) is str and x.startswith('N') for x in got) == 67
assert sum(type(x) is str and x.startswith('H') for x in got) == 38
fail = []
for e in r['entries']:
    c = e['current']
    text = (root / c['path']).read_text()
    lines = text.splitlines()
    tag = e['id']
    if not c['line']:
        fail.append((tag, 'no location'))
        continue
    assert c['anchor'] in lines[c['line'] - 1], (tag, 'stale anchor')
    assert hashlib.sha256(text.encode()).hexdigest() == c['file_sha256'], (tag, 'source changed since review')
    runtime = e['runtime']
    status = runtime['status']
    assert status in {'pending', 'pending-current-head-browser', 'test-covered', 'browser-covered'}, (tag, 'unknown runtime status')
    links = runtime.get('evidence_links', [])
    if status in {'pending', 'pending-current-head-browser'}:
        assert not runtime.get('covered_states'), (tag, 'pending item claims covered states')
    else:
        required_kind = 'test-result' if status == 'test-covered' else 'browser-checks'
        matching = [link for link in links if link.get('kind') == required_kind]
        assert matching, (tag, 'covered status needs actual result/check evidence')
        assert runtime.get('covered_states'), (tag, 'covered status needs named states')
        for link in matching:
            linked = Path(link['path'])
            if not linked.is_absolute():
                linked = folder / linked if (folder / linked).is_file() else root / linked
            assert linked.is_file(), (tag, 'evidence file missing', str(linked))
            assert link.get('claim'), (tag, 'evidence link needs a specific supported claim')
            assert link.get('states') and set(link['states']) <= set(runtime['covered_states']), (tag, 'evidence states missing/mismatch')
            if link.get('sha256'):
                assert hashlib.sha256(linked.read_bytes()).hexdigest() == link['sha256'], (tag, 'stale evidence hash')
            if required_kind == 'test-result':
                assert link.get('test_name'), (tag, 'test coverage needs named meaningful test')
            else:
                assert link.get('assertion'), (tag, 'browser coverage needs named actual assertion')
    # Link integrity is checked here; semantic support must be reviewed. Never
    # promote all625 from one matrix or the existence of a screenshot/test file.
    if e['accounting'].startswith('unresolved'):
        fail.append((tag, e['accounting']))
    if (c.get('context') or {}).get('function') == 'TargetRow':
        fail.append((tag, 'dead helper cannot prove live information'))
    for twin in [e.get('unique_twin'), *c.get('secondary_locations', [])]:
        if twin:
            assert twin['anchor'] in (root / twin['path']).read_text().splitlines()[twin['line'] - 1], (tag, 'stale twin/secondary location')
for extra in r.get('linked_presentation_contracts', []):
    assert extra['anchor'] in (root / extra['path']).read_text().splitlines()[extra['line'] - 1], (extra['path'], 'stale linked presentation contract')
for item in r.get('source_manifest', []):
    assert hashlib.sha256((root / item['path']).read_bytes()).hexdigest() == item['sha256'], (item['path'], 'manifest source changed')
assert r['counts'] == dict(collections.Counter(e['accounting'] for e in r['entries']))
assert r['unresolved_source_entries'] == [e['id'] for e in r['entries'] if e['accounting'].startswith('unresolved')]
print('Accounting IDs:625 (520 integer,67 N,38 H); source hashes/anchors/twins checked. Runtime status/link integrity checked; coverage scope remains entry-specific.')
print('Unresolved:', fail)
sys.exit(bool(fail))
