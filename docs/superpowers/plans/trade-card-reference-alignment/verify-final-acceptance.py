"""Check saved acceptance evidence integrity; this is not a new test run or audit."""
import argparse
import hashlib
import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[4])
args = parser.parse_args()
root = args.repo_root.resolve()
plan = root / 'docs/superpowers/plans/trade-card-reference-alignment'
evidence = plan / 'evidence/610/final'


def read_json(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


binding = read_json(evidence / 'source-binding.json')
for item in binding['application_source_pins']:
    assert digest(root / item['path']) == item['sha256'], ('application changed', item['path'])
for item in read_json(evidence / 'image-manifest.json')['images']:
    assert digest(evidence / item['path']) == item['sha256'], ('image changed', item['path'])

expected_runs = {(width, theme) for width in (1200, 1366, 1920) for theme in ('dark', 'light')}
assertions = 0
for kind in ('layout', 'states', 'reviews'):
    report = evidence / kind / 'checks.json'
    assert digest(report) == binding['reports'][kind]['sha256'], ('report changed', kind)
    data = read_json(report)
    assert data['captureRevision'] == binding['verified_application_commit']
    assert data['captureSourcePins'] == binding['application_source_pins']
    runs = data['runs']
    assert len(runs) == 6 and {(r['width'], r['theme']) for r in runs} == expected_runs
    for run in runs:
        assert not run['pageErrors'] and not run['mockedWrites'] and not run['blockedWrites']
        assertions += len(run['results'])
assert assertions == 978

test_results = read_json(evidence / 'tests/610-finisher-final-verification.json')
assert len(test_results['results']) == test_results['suites'] == 27
assert sum(len(r['assertionResults']) for r in test_results['results']) == test_results['passedTests'] == 623
for suite in test_results['results']:
    assert suite['status'] == 'passed'
    assert all(test['status'] == 'passed' for test in suite['assertionResults'])
summary = read_json(evidence / 'tests/verification-summary.json')
passed_paths = {r['name'].split('/frontend/', 1)[1] for r in test_results['results']}
assert set(summary['final_corrected_suite_union']['baseline_failures']) <= passed_paths
assert summary['final_corrected_suite_union']['timeouts_unchanged']


class Links(HTMLParser):
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ('href', 'src') and value and not value.startswith(('https:', 'http:', '#')):
                assert (evidence / value).is_file(), ('missing preview link', value)


correction = (evidence / 'tests/610-approx-tests.log').read_text()
assert 'Test Suites: 11 passed, 11 total' in correction and 'Tests:       168 passed, 168 total' in correction
Links().feed((evidence / 'index.html').read_text())
subprocess.run([
    sys.executable, str(evidence / 'information-preservation/validate.py'),
    '--repo-root', str(root),
], check=True)
subprocess.run([sys.executable, str(evidence / 'information-preservation/paragraph-preservation-final-verify.py'), '--repo-root', str(root)], check=True)
print(f'Accepted evidence intact: {len(binding["application_source_pins"])} application pins, '
      f'18 browser runs/{assertions} assertions, 27 suites/623 tests plus correction11/168; no new execution/audit claimed.')
