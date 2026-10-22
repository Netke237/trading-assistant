"""Offline schema verification only: no FastAPI app, DB, scheduler or provider imports."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess
import sys

if sys.version_info[:2] != (3, 11):
    raise RuntimeError('Use the prepared Python 3.11 interpreter')
ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
SHA = '4b1f6b86e8137f499da0c4c430f23b9c250fd8de'
if subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() != SHA:
    raise RuntimeError('Source HEAD changed; review baseline')
sys.path.insert(0, str(ROOT / 'backend'))
from app.schemas.scan_schedule import ScanScheduleEntry
from app.schemas.stock_scan import StockScanRequest
from pydantic import ValidationError

output = json.loads((HERE / 'output.json').read_text())
checks = []
for index, request in enumerate(output['requests']):
    if (request['path'].startswith('/api/scan-schedule')
            and request['method'] in ('POST', 'PUT')
            and request.get('status') in (200, 422)):
        body = copy.deepcopy(request['body'])
        body['id'] = request.get('response', {}).get('id', 'offline-invalid')
        try:
            ScanScheduleEntry.model_validate(body)
            accepted, error = True, None
        except ValidationError as exc:
            accepted, error = False, str(exc)
        expected = request['status'] == 200
        checks.append({'id': f'schedule-request-{index}', 'path': request['path'],
                       'fixture_status': request['status'], 'expected_schema_accepts': expected,
                       'schema_accepts': accepted, 'error': error,
                       'status': 'pass' if accepted == expected else 'fail'})
stock = next(r['body']['resolved_request'] for r in output['requests']
             if r['method'] == 'POST' and r['path'] == '/api/scan-schedule'
             and r['body']['mode'] == 'stocks')
for key, value, expected in [('ma_crossover_lookback', 0, False),
                             ('breakout_volume_mult', 1, False),
                             ('breakout_volume_mult', 4, True)]:
    body = {**stock, key: value}
    try:
        StockScanRequest.model_validate(body)
        accepted, error = True, None
    except ValidationError as exc:
        accepted, error = False, str(exc)
    checks.append({'id': f'stock-bound-{key}-{value}', 'field': key, 'value': value,
                   'expected_schema_accepts': expected, 'schema_accepts': accepted,
                   'error': error, 'status': 'pass' if accepted == expected else 'fail'})
result = {'source_sha': SHA, 'python': sys.version, 'boundary': 'Pure Pydantic schema validation of captured UI payloads; no server/scheduler/DB',
          'checks': checks,
          'counts': {status: sum(c['status'] == status for c in checks) for status in ('pass', 'fail')}}
(HERE / 'schema-output.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result['counts']))
if result['counts']['fail']:
    raise SystemExit(1)
