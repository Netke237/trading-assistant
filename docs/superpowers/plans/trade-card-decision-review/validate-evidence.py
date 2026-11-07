"""Sanity checks for partial evidence; does not close running-build or audit gates."""
import hashlib
import json
from pathlib import Path

folder = Path(__file__).resolve().parent
root = folder.parents[3]
read = lambda path: json.loads(path.read_text())
register = read(folder / 'preservation-register.json')
manifest = read(folder / 'source-evidence-manifest.json')
historical = read(root / 'docs/superpowers/specs/2026-10-03-trade-card-presentation/mapping.json')
entries = register['historical_entries']
assert len(entries) == register['historical_entry_count'] == len(historical) == 520
assert [e['id'] for e in entries] == list(range(1, 521))
assert [e['item'] for e in entries] == [e['item'] for e in historical]
assert all(e['actual_running_build'] == 'not_verified' for e in entries)
assert all(e['preservation_check'].startswith('open') for e in entries)
assert manifest['actual_running_revision'] is None and manifest['actual_running_url'] is None
assert manifest['application_diff_from_source_revision'] == ''
assert hashlib.sha256((folder / 'capture-local-baseline.cjs').read_bytes()).hexdigest() == manifest['portable_harness_sha256']
for path, expected in manifest['source_files'].items():
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected, path
for state, capture in manifest['screenshots'].items():
    png = folder / f'evidence/local-mocked/{state}.png'
    assert png.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'), state
    assert hashlib.sha256(png.read_bytes()).hexdigest() == capture['sha256'], state
    assert (folder / f'evidence/local-mocked/{state}.txt').stat().st_size > 0
checks = read(folder / 'evidence/local-mocked/checks.json')
assert not checks['errors'] and len(checks['results']) == 15
allowed = {'/api/contracts/exit-plan', '/api/contracts/structural-stop', '/api/contracts/first-passage'}
assert checks['posts'] and set(checks['posts']) <= allowed
for entry in register['inspected_current_contracts']:
    path = root / entry['source']['path']
    start, end = entry['source']['lines']
    assert 1 <= start <= end <= len(path.read_text().splitlines()), entry['id']
    assert entry['evidence_level'] == 'source_inspected'
    assert entry['actual_running_build'] == 'not_verified'
    assert all(entry[k] for k in ['mutability', 'units', 'time_basis', 'applicable_state', 'proposed_future_location'])
    for check in entry['browser_assertions']:
        assert check['file'] == 'evidence/local-mocked/checks.json'
        assert 0 <= check['result_index'] < len(checks['results'])
portable = read(folder / 'evidence/portable-checks.json')
assert not portable['errors'] and not portable['blockedWrites']
assert len(portable['results']) == 16 and set(portable['posts']) <= allowed
print('PASS: 520 historical obligations, 33 inspected contracts, 35 source hashes, four capture hashes, 15 original and 16 portable named checks; actual build unresolved.')
