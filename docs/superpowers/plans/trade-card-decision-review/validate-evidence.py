"""Validate immutable source inventory and capture integrity, not runtime parity.

Application implementation may change the working tree after #576. Baseline source
hashes and excerpts are always read from the user-authorized pinned git commit.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess

folder = Path(__file__).resolve().parent
root = folder.parents[3]
PINNED = 'c8f3b8a2cb5f0fa7e74fc0da407d1716a381fc6b'


def read(path):
    return json.loads(path.read_text())


@lru_cache(maxsize=None)
def baseline_blob(path):
    return subprocess.check_output(['git', 'show', f'{PINNED}:{path}'], cwd=root)


def digest(data):
    return hashlib.sha256(data).hexdigest()


register = read(folder / 'preservation-register.json')
manifest = read(folder / 'source-evidence-manifest.json')
provenance = read(folder / 'baseline-provenance.json')
historical = json.loads(baseline_blob('docs/superpowers/specs/2026-10-03-trade-card-presentation/mapping.json'))
assert manifest['application_source_revision'] == register['source_inventory_revision'] == provenance['source_revision'] == PINNED
assert manifest['baseline_authorization'] == provenance['baseline_authorization']
assert manifest['baseline_authorization']['revision'] == PINNED
assert register['source_inventory_complete'] is True
assert register['mini_pc_comparison']['status'] == 'user_deferred_not_verified'
assert register['mini_pc_comparison']['blocking'] is False
for metadata in (manifest, provenance, register['mini_pc_comparison']):
    assert metadata['actual_running_revision'] is None and metadata['actual_running_url'] is None
assert 'USER DEFERRED' in manifest['actual_running_comparison']
assert 'USER DEFERRED' in provenance['running_build_comparison']
assert digest((folder / 'capture-local-baseline.cjs').read_bytes()) == manifest['portable_harness_sha256']
for path, expected in manifest['source_files'].items():
    assert digest(baseline_blob(path)) == expected, path
for path, expected in provenance['source_hashes'].items():
    assert digest(baseline_blob(path)) == expected, path


def validate_source(source):
    path = source['path']
    assert path in manifest['source_files'], path
    lines = baseline_blob(path).decode().splitlines()
    start, end = source['lines']
    assert 1 <= start <= end <= len(lines), (path, start, end)
    excerpt = '\n'.join(lines[start - 1:end]) + '\n'
    assert excerpt == source['excerpt'], (path, start, end)
    assert digest(excerpt.encode()) == source['sha256'], path
    if 'anchor' in source:
        assert source['anchor'] in excerpt, path


entries = register['historical_entries']
assert len(entries) == register['historical_entry_count'] == len(historical) == 520
assert [e['id'] for e in entries] == list(range(1, 521))
assert [e['item'] for e in entries] == [e['item'] for e in historical]
helpers = {e['id']: e for e in register['shared_source_contracts']}
assert len(helpers) == len(register['shared_source_contracts']) == 38
for helper in helpers.values():
    validate_source(helper)
    assert helper['evidence_level'] == 'source_inspected' and helper['contract']
for entry in entries:
    validate_source(entry['current_source'])
    if 'binding_source' in entry:
        validate_source(entry['binding_source'])
    assert entry['source_inspection_revision'] == PINNED
    assert entry['evidence_level'] == 'source_inspected'
    assert entry['actual_running_build'] == 'not_verified'
    assert entry['mini_pc_comparison'] == 'user_deferred_not_blocking'
    assert entry['preservation_check'].startswith('pending #584')
    assert entry['current_location'] and entry['proposed_future_location']
    contract = entry['field_contract']
    assert contract['verification'] == 'source_inspected_at_pinned_baseline'
    for key in ('source_binding', 'formatter', 'mutability', 'units', 'time_basis', 'applicable_state', 'copy_and_color'):
        assert isinstance(contract[key], str) and contract[key].strip(), (entry['id'], key)
    assert entry['related_source_contracts'] and set(entry['related_source_contracts']) <= helpers.keys()

checks = read(folder / 'evidence/local-mocked/checks.json')
assert not checks['errors'] and len(checks['results']) == 15
allowed = {'/api/contracts/exit-plan', '/api/contracts/structural-stop', '/api/contracts/first-passage'}
assert checks['posts'] and set(checks['posts']) <= allowed
supplements = register['inspected_current_contracts']
assert len(supplements) == len({e['id'] for e in supplements}) == 67
for entry in supplements:
    validate_source(entry['source_evidence'])
    assert entry['source'] == {key: entry['source_evidence'][key] for key in ('path', 'lines')}
    assert entry['source_inspection_revision'] == PINNED
    assert entry['evidence_level'] == 'source_inspected'
    assert entry['actual_running_build'] == 'not_verified'
    assert entry['mini_pc_comparison'] == 'user_deferred_not_blocking'
    assert entry['preservation_check'].startswith('pending #584')
    assert all(entry[key] for key in ('mutability', 'units', 'time_basis', 'applicable_state', 'proposed_future_location'))
    for check in entry['browser_assertions']:
        assert check['file'] == 'evidence/local-mocked/checks.json'
        assert 0 <= check['result_index'] < len(checks['results'])
for state, capture in manifest['screenshots'].items():
    png = folder / f'evidence/local-mocked/{state}.png'
    assert png.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'), state
    assert digest(png.read_bytes()) == capture['sha256'], state
    body = folder / f'evidence/local-mocked/{state}.txt'
    assert body.stat().st_size > 0 and digest(body.read_bytes()) == capture['body_text']['sha256'], state
portable = read(folder / 'evidence/portable-checks.json')
assert not portable['errors'] and not portable['blockedWrites']
assert len(portable['results']) == 16 and set(portable['posts']) <= allowed
counts = manifest['source_inventory']
assert counts == provenance['source_inventory']
assert counts['historical_entries'] == counts['source_inspected_historical_entries'] == len(entries)
assert counts['current_contract_supplements'] == len(supplements)
assert counts['shared_helper_contracts'] == len(helpers)
print(f'PASS: {len(entries)} individual pinned-source contracts, {len(supplements)} supplements, '
      f'{len(helpers)} helpers, {len(manifest["source_files"])} immutable source hashes; '
      'four captures, 15 original and 16 portable named checks. '
      'Mini-PC comparison user-deferred/unverified; #584 runtime preservation pending. '
      'Current implementation behavior is not validated by baseline hashes.')
