"""Settings-only persistence evidence; no app.main, sends, jobs, or scheduler startup.

Run from repo root with backend/.venv/bin/python. All writes use a temporary directory;
fresh worker processes establish restart readback. Scheduler methods are recorded stubs.
"""
import hashlib
import importlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parents[6]
OUT = pathlib.Path(__file__).parent
SHA = '880c8441841cc22d5090cdc5f984e4cf7e3d9a8d'


def worker(base, mode):
    assert sys.version_info[:2] == (3, 11)
    base = pathlib.Path(base).resolve()
    assert base.is_relative_to('/tmp')
    os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + str(base / 'isolated.db')
    names = ['ingestion', 'edgar', 'sp500', 'tuning']
    for name, env in zip(names, ['BAMENDJOU_SCHEDULE_PATH', 'BAMENDJOU_EDGAR_SCHEDULE_PATH', 'BAMENDJOU_SP500_SCHEDULE_PATH', 'BAMENDJOU_TUNING_SCHEDULE_PATH']):
        os.environ[env] = str(base / (name + '_schedule.yaml'))
    sys.path.insert(0, str(ROOT / 'backend'))
    import yaml
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    calls = []
    for name in names:
        module_name = 'app.services.' + name + '_scheduler'
        stub = types.ModuleType(module_name)
        stub.configure = lambda *args, name=name: calls.append({'scheduler': name, 'args': args})
        stub.next_run_time = lambda: None  # No scheduler exists in this harness.
        sys.modules[module_name] = stub
    job = types.ModuleType('app.services.ingestion_job')
    def forbidden(*args, **kwargs):
        raise AssertionError('job/send route must never execute')
    job.get_ingestion_state = forbidden
    job.single_provider_symbols = forbidden
    job.start_ingestion_task = forbidden
    sys.modules[job.__name__] = job
    from app.routers import ingestion, notification_settings as notifications, strategy_tuning
    notifications._SETTINGS_PATH = base / 'settings.yaml'
    stores = {}
    for name in names:
        module = importlib.import_module('app.services.' + name + '_schedule_store')
        stores[name] = getattr(module, name + '_schedule_store')
        assert stores[name]._path.is_relative_to(base)
    app = FastAPI()
    for router in (ingestion.router, notifications.router, strategy_tuning.router):
        app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    result = {'mode': mode, 'checks': [], 'requests': [], 'scheduler_configure_calls': calls,
              'isolation': {'main_imported': 'app.main' in sys.modules, 'scheduler_modules_stubbed': names,
                            'job_module_stubbed': True, 'only_temporary_config_files': True,
                            'next_run': 'null stub; real scheduling/timezone computation NOT RUN'}}
    assert not result['isolation']['main_imported']
    def request(method, url, body=None):
        assert url == '/settings/notifications' or url in urls.values()
        res = client.request(method, url, json=body) if body is not None else client.request(method, url)
        try:
            response = res.json()
        except Exception:
            response = res.text
        record = {'method': method, 'url': url, 'request': json.loads(json.dumps(body)), 'status': res.status_code, 'response': response}
        result['requests'].append(record)
        return record
    def check(id, expected, observed, passed):
        result['checks'].append({'id': id, 'expected': expected, 'observed': observed, 'status': 'pass' if passed else 'fail'})
    urls = {name: '/api/data/' + ('ingest' if name == 'ingestion' else name) + '/schedule' for name in names}
    urls['tuning'] = '/api/strategy-tuning/schedule'
    if mode == 'write':
        before = request('GET', '/settings/notifications')
        payload = {'gmail': {'enabled': True, 'to': 'sink@audit.invalid', 'smtp_user': 'fixture@audit.invalid', 'smtp_password': 'FAKE-AUDIT-PASSWORD'},
                   'telegram': {'enabled': False, 'chat_id': 'FAKE-AUDIT-CHAT', 'bot_token': 'FAKE-AUDIT-TOKEN'}}
        saved = request('POST', '/settings/notifications', payload)
        read = request('GET', '/settings/notifications')
        persisted = yaml.safe_load(notifications._SETTINGS_PATH.read_text())['notifications']
        expected = {'gmail': {'enabled': True, 'to': 'sink@audit.invalid', 'smtp_user': 'fixture@audit.invalid'},
                    'telegram': {'enabled': False, 'chat_id': 'FAKE-AUDIT-CHAT'}}
        check('notifications-save-readback', 'public fields match request; write-only fake secrets persisted and omitted from API',
              {'before': before, 'save': saved, 'read': read, 'fake_secret_persisted': persisted['gmail']['smtp_password'] == 'FAKE-AUDIT-PASSWORD' and persisted['telegram']['bot_token'] == 'FAKE-AUDIT-TOKEN'},
              saved['status'] == 200 and read['response'] == expected and persisted['gmail']['smtp_password'] == 'FAKE-AUDIT-PASSWORD' and persisted['telegram']['bot_token'] == 'FAKE-AUDIT-TOKEN')
        payload['gmail']['smtp_password'] = ''
        payload['telegram']['bot_token'] = None
        blank = request('POST', '/settings/notifications', payload)
        persisted = yaml.safe_load(notifications._SETTINGS_PATH.read_text())['notifications']
        check('notifications-blank-secret-retain', 'blank/null fake secret retains existing value', blank,
              persisted['gmail']['smtp_password'] == 'FAKE-AUDIT-PASSWORD' and persisted['telegram']['bot_token'] == 'FAKE-AUDIT-TOKEN')
        prior = notifications._SETTINGS_PATH.read_bytes()
        invalid = request('POST', '/settings/notifications', {'gmail': {'enabled': True}})
        check('notifications-invalid-rollback', 'missing Telegram config gives 422, original YAML intact', invalid,
              invalid['status'] == 422 and notifications._SETTINGS_PATH.read_bytes() == prior)
        from app.services import atomic_yaml
        def refuse(src, dst):
            assert pathlib.Path(src).is_relative_to(base) and pathlib.Path(dst).is_relative_to(base)
            raise OSError('injected isolated config replacement failure')
        payload['gmail']['to'] = 'changed@audit.invalid'
        with patch.object(atomic_yaml.os, 'replace', side_effect=refuse):
            failed = request('POST', '/settings/notifications', payload)
        read = request('GET', '/settings/notifications')
        check('notifications-failed-save-rollback', '500 with unchanged disk/API and no temporary sidecar',
              {'failed': failed, 'read': read, 'sidecars': [p.name for p in base.glob('*.tmp')]},
              failed['status'] == 500 and prior == notifications._SETTINGS_PATH.read_bytes() and read['response'] == expected and not list(base.glob('*.tmp')))
        for index, name in enumerate(names):
            url = urls[name]
            before = request('GET', url)
            payload = {'enabled': True, 'time': ['01:17', '04:23', '16:41', '05:37'][index]}
            if name == 'tuning':
                payload['days_of_week'] = [0, 2, 5]
            saved = request('POST', url, payload)
            read = request('GET', url)
            path = stores[name]._path
            prior = path.read_bytes()
            check(name + '-schedule-save-readback', 'enabled/time/weekdays match API, disk and configure args',
                  {'before': before, 'save': saved, 'read': read, 'yaml': yaml.safe_load(prior), 'configure': calls[-1]},
                  saved['status'] == 200 and read['response'] == dict(payload, next_run=None) and yaml.safe_load(prior) == payload and calls[-1]['scheduler'] == name and list(calls[-1]['args']) == list(payload.values()))
            count = len(calls)
            invalid = request('POST', url, dict(payload, time='24:00'))
            check(name + '-schedule-invalid-rollback', 'invalid time gives 422; file, memory and scheduler unchanged',
                  {'invalid': invalid, 'read': request('GET', url)},
                  invalid['status'] == 422 and path.read_bytes() == prior and stores[name].get() == payload and len(calls) == count)
            if name == 'tuning':
                invalid_days = [request('POST', url, dict(payload, days_of_week=days)) for days in ([], [-1], [7])]
                check('tuning-days-invalid-rollback', 'empty/out-of-range weekdays rejected without mutation', invalid_days,
                      all(r['status'] == 422 for r in invalid_days) and stores[name].get() == payload and path.read_bytes() == prior)
            failing_payload = dict(payload, enabled=False, time='22:59')
            with patch.object(os, 'replace', side_effect=refuse):
                failed = request('POST', url, failing_payload)
            read = request('GET', url)
            sidecar = path.with_suffix('.yaml.tmp')
            check(name + '-schedule-failed-save-rollback', '500 retains last successfully saved API/disk values and cleans sidecar',
                  {'failed': failed, 'read': read, 'disk': yaml.safe_load(path.read_text()), 'sidecar_exists': sidecar.exists(), 'configure_calls_after_failure': len(calls) - count},
                  failed['status'] == 500 and read['response'] == dict(payload, next_run=None) and path.read_bytes() == prior and not sidecar.exists() and len(calls) == count)
    result['final'] = {url: request('GET', url)['response'] for url in ['/settings/notifications', *urls.values()]}
    result['hashes'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in base.glob('*.yaml')}
    def redact(value):
        if isinstance(value, dict):
            return {key: ('[redacted fake secret]' if key in ('smtp_password', 'bot_token') and item else redact(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value
    print(json.dumps(redact(result)))


if len(sys.argv) > 1:
    worker(sys.argv[1], sys.argv[2])
else:
    with tempfile.TemporaryDirectory(prefix='settings-families-audit-') as base:
        runs = []
        for mode in ('write', 'restart-readback'):
            process = subprocess.run([sys.executable, __file__, base, mode], cwd=ROOT, capture_output=True, text=True)
            if process.returncode:
                raise RuntimeError(process.stderr)
            runs.append(json.loads(process.stdout))
        output = {'source_sha': SHA, 'python': sys.version, 'runs': runs,
                  'restart_hashes_identical': runs[0]['hashes'] == runs[1]['hashes'],
                  'restart_api_identical': runs[0]['final'] == runs[1]['final']}
        (OUT / 'families-output.json').write_text(json.dumps(output, indent=2) + '\n')
        print(json.dumps({'checks': runs[0]['checks'], 'restart_hashes_identical': output['restart_hashes_identical'], 'restart_api_identical': output['restart_api_identical']}, indent=2))
