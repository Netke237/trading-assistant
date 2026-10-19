"""Actual ScanScheduleStore on temporary YAML only; no router, scheduler, DB or job."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.version_info[:2] != (3, 11):
    raise RuntimeError('Python 3.11 required')
HERE = Path(__file__).resolve().parent
ROOT = Path.cwd()
SHA = '4b1f6b86e8137f499da0c4c430f23b9c250fd8de'
if subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() != SHA:
    raise RuntimeError('Source HEAD changed')
sys.path.insert(0, str(ROOT / 'backend'))
checks, cases = [], []
def check(name, expected, observed, passed):
    checks.append({'id': name, 'kind': 'persistence', 'expected': expected,
                   'observed': observed, 'status': 'pass' if passed else 'fail'})
def digest(data):
    return hashlib.sha256(data).hexdigest()
with tempfile.TemporaryDirectory(prefix='audit350-schedule-') as directory:
    temp = Path(directory)
    os.environ['BAMENDJOU_SCAN_SCHEDULE_PATH'] = str(temp / 'singleton.yaml')
    from app.services.scan_schedule_store import ScanScheduleStore, scan_schedule_store
    from app.schemas.scan_schedule import ScanScheduleEntry
    import yaml
    assert scan_schedule_store._path.parent == temp
    captured = json.loads((HERE / 'output.json').read_text())
    option = copy.deepcopy(next(r['response'] for r in captured['requests']
        if r['path'] == '/api/scan-schedule' and r['method'] == 'POST' and r['body']['mode'] == 'options'))
    stock = copy.deepcopy(next(r['response'] for r in captured['requests']
        if r['path'] == '/api/scan-schedule' and r['method'] == 'POST' and r['body']['mode'] == 'stocks'))
    for entry in [option, stock]:
        ScanScheduleEntry.model_validate(entry)
    missing = ScanScheduleStore(temp / 'missing.yaml')
    check('yaml-missing-file', 'missing file means empty and no file written',
          {'entries': missing.list(), 'exists': missing._path.exists()},
          missing.list() == [] and not missing._path.exists())
    for name, text in [('syntax-invalid', 'version: 2\nentries: [unterminated\n'),
                       ('root-list', '- a\n- b\n'),
                       ('invalid-version', 'version: not-an-int\nentries: []\n')]:
        path = temp / f'{name}.yaml'
        path.write_text(text)
        before = path.read_bytes()
        store = ScanScheduleStore(path)
        case = {'id': name, 'before_text': text, 'entries_after_load': copy.deepcopy(store.list()),
                'load_preserved_bytes': path.read_bytes() == before,
                'before_sha256': digest(before)}
        check('yaml-'+name+'-load-preserves-bytes',
              'invalid load is empty in memory and does not immediately rewrite file', case,
              store.list() == [] and path.read_bytes() == before)
        store.upsert(option)
        case.update({'after_upsert_text': path.read_text(),
                     'after_upsert_sha256': digest(path.read_bytes()),
                     'backups': [p.name for p in temp.glob(name+'.bak.*.yaml')]})
        check('yaml-'+name+'-next-write-preservation',
              'subsequent ordinary save preserves invalid source for recovery or refuses write',
              copy.deepcopy(case), bool(case['backups']) or path.read_bytes() == before)
        cases.append(case)
    legacy = copy.deepcopy(stock)
    legacy['resolved_request'].update({'horizon':'Swing','hold_max_days':15,
                                       'ma_crossover_lookback':7,'breakout_volume_mult':1.8})
    legacy['resolved_request'].pop('params_horizon', None)
    legacy['future_entry_key'] = {'preserve':'entry extension'}
    path = temp / 'legacy.yaml'
    path.write_text(yaml.safe_dump({'entries':[legacy], 'future_top_level':'extension'}))
    before = path.read_bytes()
    migrated = ScanScheduleStore(path)
    after = yaml.safe_load(path.read_text())
    backups = list(temp.glob('legacy.bak.*.yaml'))
    expected = {k:v for k,v in legacy['resolved_request'].items()
                if k not in ('ma_crossover_lookback','breakout_volume_mult')}
    expected['params_horizon'] = 'Swing'
    case = {'id':'legacy-v1', 'before_text':before.decode(), 'after_text':path.read_text(),
            'in_memory':migrated.list(), 'backup_matches_original':len(backups)==1 and backups[0].read_bytes()==before,
            'unknown_entry_preserved':after['entries'][0]['future_entry_key']==legacy['future_entry_key'],
            'unknown_top_level_preserved':'future_top_level' in after}
    check('yaml-legacy-v1-migration', 'legacy stock strategy overrides drop, hold maps to Swing, backup exact original', case,
          after['version']==2 and after['entries'][0]['resolved_request']==expected and case['backup_matches_original'])
    check('yaml-legacy-restart', 'separate store instance reads same migrated payload without another migration',
          ScanScheduleStore(path).list(), ScanScheduleStore(path).list()==migrated.list())
    cases.append(case)
    rows = [None, {}, 'invalid', option]
    path = temp / 'mixed-rows.yaml'
    path.write_text(yaml.safe_dump({'version':2,'entries':rows,'future_top_level':'extension'}))
    before = path.read_bytes()
    mixed = ScanScheduleStore(path)
    check('yaml-malformed-rows', 'malformed rows lacking id are dropped in memory; original bytes remain',
          {'before_text':before.decode(),'entries':mixed.list(),'bytes_preserved':path.read_bytes()==before},
          mixed.list()==[option] and path.read_bytes()==before)
    mixed.upsert(stock)
    reloaded = ScanScheduleStore(path)
    check('yaml-upsert-reload', 'two valid entries persist and reload', reloaded.list(), len(reloaded.list())==2)
    mixed.delete(option['id'])
    check('yaml-delete-reload', 'only selected id deleted and last record reloads',
          ScanScheduleStore(path).list(), ScanScheduleStore(path).list()==[stock])
    assert all(p.resolve().is_relative_to(temp.resolve()) for p in temp.rglob('*'))
result = {'source_sha':SHA,'python':sys.version,
          'boundary':'Real ScanScheduleStore on TemporaryDirectory only. No API router, scheduler, DB functions or jobs invoked. Restart here means new store instance, not new process.',
          'checks':checks,'cases':cases,'counts':{s:sum(c['status']==s for c in checks) for s in ('pass','fail')},
          'module_sha256':{p:digest((ROOT/p).read_bytes()) for p in ['backend/app/services/scan_schedule_store.py','backend/app/services/horizon_profiles.py','backend/app/scoring/stock_scorer.py']}}
(HERE/'yaml-output.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result['counts']))
