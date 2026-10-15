# YAML-DEPTH-BOUND (#167): refreshed evidence, 2026-10-14

Evidence only on `board/yaml-depth-bound-b1dd948c`, base HEAD `7a5fcca659ecbb0bac4711dc30f7c3ad10c81149`. No application code, real stores, DB rows, claims, external apps or state edited. Coordinator holds ownership. This is not an independent audit or a completion verdict.

## Runtime and bounds

`backend/.venv/bin/python --version` returned **Python 3.11.16**. Runtime packages: PyYAML 6.0.1, Pydantic 2.13.4, FastAPI 0.141.1. Every store instance and imported singleton used a new temporary path; HTTP probes assembled only the actual credential/composite routers without lifespan, schedulers, broker calls or market requests. Options restore used its real function with a fake read-only DB session. All probes ran in one subprocess under `timeout 30s`; completed exit 0. No large alias expansion was attempted.

Depth below counts the supplied arbitrary-value field's outer dict as 1, with empty dict at the innermost level. These are sample points, not claims about universal stack thresholds.

## Results

| Probe | Actual result |
|---|---|
| `ScanRequest.overrides`, depths 32 and 33 | Accepted, JSON dump/JSON restore/YAML dump all succeed; no existing 32-level cap |
| Same, depth 220 | Accepted; `model_dump_json()` succeeds; `model_validate_json()` raises `ValidationError` |
| Same, depth 270 | Accepted; JSON dump raises `PydanticSerializationError`; JSON restore raises `ValidationError`; YAML dump succeeds |
| Same, depth 450 | Accepted; JSON dump/restore fail as above; YAML dump raises `RecursionError` |
| `StockScanRequest.overrides` and `PortfolioPositionUpdate.alert_overrides`, depth 450 | Accepted |
| `ScanScheduleEntry.resolved_request.ignored_extension`, depth 450 | Accepted; nested `ScanRequest` ignores extension, while original raw dict is retained/persisted |
| Real credential POST, depth 270 | POST **200**, GET **500**, disk changed, subsequent save succeeds |
| Real composite POST, depth 270 | POST **500**, GET **500**, disk changed, subsequent save succeeds |
| Real credential/composite POST, depth 450 | POST **500**, GET **500**, disk unchanged, memory changed; subsequent save raises `RecursionError` |
| Strategy-watch add, depth 450 | `RecursionError`, disk unchanged, failed watch remains in memory |
| Schedule upsert, depth 450 ignored extension | `RecursionError`, disk unchanged, failed entry remains in memory |
| Injected `os.replace` failure on shallow credential/watch/schedule write | Each raises `OSError`; disk unchanged and memory changed |
| Real options `restore_from_db()`, request at depth 220, no result blob | Uncaught `ValidationError` |
| Tiny cyclic YAML `a: &a [*a]` | Loaded object points to itself |
| Tiny shared YAML alias (`a: &a [1, 2]`, `b: [*a, *a]`) | Both alias references point to the same list |
| 600 nested YAML flow lists | `RecursionError`, **not** an instance of `yaml.YAMLError` |

A depth cap prevents new malicious payloads but does not fix memory/disk divergence on ordinary I/O failure. Credential POST at depth 270 actually succeeds because its response is only `{ok, key}`; the next credential GET fails. This refines the older evidence's blanket “write returns 500” statement.

An initial `TestClient` version timed out (30s; then 50s with unbuffered output) on the first HTTP probe in this environment. Replacing only the HTTP transport with repository-standard `httpx.AsyncClient(ASGITransport(...))` completed all probes. No finding above relies on the timed-out run.

## Current reachable paths and proposed A tasks

The approved split is A (#167): API depth cap 32, atomic memory/disk mutation, guarded options restore. Shared YAML loader alias/corrupt-schedule behavior belongs to B. Leave Pre-Breakout, backtest/chart, screen-label code and `scripts/state.py` untouched.

1. **Bound arbitrary persisted API values before side effects.** Add a small iterative container-depth validator, e.g. `backend/app/schemas/nesting.py`, raising `ValueError` at depth >32; define boundary semantics explicitly (field root dict/list =1, scalar =0). Apply before validators to `ScanRequest.overrides` and portfolio create/update opaque values in `backend/app/schemas/__init__.py`; `StockScanRequest.overrides` in `backend/app/schemas/stock_scan.py`; `CredentialUpdate.values` in `backend/app/routers/credentials.py`; `AddWatch.params_override` in `backend/app/routers/strategy_watch.py`; `CompositeWatchCreate.trigger_def` in `backend/app/routers/composite_watch.py`; **both** schedule model raw `resolved_request` fields in `backend/app/schemas/scan_schedule.py`. Portfolio create values are `exitPlan`, `targets`, `tradeCardSnapshot`, `maxLossOverride`; update values are `targets`, `exitPlan`, `maxLossOverride`, `alertOverrides`. Cover aliases and Python field names, preserving `None` and `exclude_unset`. `ArmRequest` in `backend/app/routers/auto_trade.py` carries `exit_plan`, `targets`, `max_loss_override`, `trade_card_snapshot` into the position writer too: include these boundary values, without changing order behavior. Do not add request-depth rules to response schemas (that could hide/strand legacy persisted rows). Test 32 accepted/33 refused, dict/list alternation, null/omitted, alias spelling, deeply nested unknown schedule-extension values, and no mutation after rejected HTTP input. Existing test homes: `test_credentials_router.py`, `test_strategy_watch_store.py`, `test_scan_schedule_entry.py`, `test_scan_schedule.py`; add a dedicated depth test module for shared schema coverage.
2. **Persist a candidate before publishing it to memory, under one writer lock.** In `backend/app/services/{credential_store,strategy_watch_store,scan_schedule_store}.py`, stage snapshots and serialize/write/replace the candidate while owning the store lock, then install candidate as canonical memory only after success. Preserve credential 0600 and no-persistence mode. Change credential endpoint from its separate `set` + `save` transaction to the new single persistent mutation operation; preserve existing direct `set` semantics needed by fixtures/callers where appropriate. Cover all mutations in affected stores, including delete, enable, state and schedule changes; preserve watch re-enable callback rollback and lock reentrancy. Serialize writers so a failed writer cannot roll back over another successful writer; shallow copies alone do not isolate nested input aliases or callback mutations. Tests: injected dump/write/replace failures preserve old memory and exact disk bytes, later ordinary writes still succeed, no resurrected deletes/lost concurrent successful update, ordinary persisted writes/reload and credential mode still work. Existing test homes: `backend/tests/test_credential_store.py`, `test_credential_store_pin.py`, `test_strategy_watch_store.py`, `test_scan_schedule.py`. Avoid broad YAML-loader changes and schedule-load corruption policy here (B).
3. **Guard legacy options restore.** In `backend/app/routers/scan.py`, validate stored request and result independently in locals, catch validation/JSON-depth failures at each blob, warn without logging raw persisted content, and publish a consistent state only after validation. Do not clear/rewrite DB rows. Invalid request must not auto-resume scheduling; invalid/stale result must not keep “complete/running” status. Preserve valid result when only request fails, valid request's existing stale-result replay semantics, schema-version rejection and no-row behavior. Clear stale in-process globals for rejected blobs. Add `backend/tests/test_scan_restore_depth.py` (or existing restore test home) for a 220-deep persisted request, malformed request, malformed result, independently valid counterpart, stale-version result and valid unchanged pair. Existing stock-request restore is guarded and is evidence/context, not a reason to edit stock/Pre-Breakout router code.

The options persistence bridge is `scan._upsert_session` (`scan.py:1530-1554`): `req.model_dump_json()` is committed in `last_request_json`; `restore_from_db` calls `ScanRequest.model_validate_json` unguarded (`:1618-1619`). The harness demonstrates precisely that serializer/parser mismatch and calls the real restore. It does **not** claim to have run a real market scan or inserted a DB row. Result restore is also currently unguarded (`:1576`).

Before implementation: independent plan audit under the coordinator's recorded phase counter. After integration: required full checks and independent code audit; this evidence alone clears neither gate.

## Exact reproduction

From repository root, save the following as `/tmp/yaml_depth_evidence_20261014.py`, then run:

```sh
backend/.venv/bin/python --version
PYTHONPATH=backend timeout 30s backend/.venv/bin/python -u /tmp/yaml_depth_evidence_20261014.py
```

```python
import os, tempfile, pathlib, json, sys, asyncio
from unittest.mock import patch
from types import SimpleNamespace
root = pathlib.Path(tempfile.mkdtemp(prefix='yaml-depth-evidence-'))
os.environ['BAMENDJOU_CREDS_PATH'] = str(root/'singleton-creds.yaml')
os.environ['BAMENDJOU_STRATEGY_WATCHES_PATH'] = str(root/'singleton-watch.yaml')
os.environ['BAMENDJOU_SCAN_SCHEDULE_PATH'] = str(root/'singleton-schedule.yaml')
import yaml, pydantic, fastapi
from app.schemas import ScanRequest, PortfolioPositionUpdate
from app.schemas.stock_scan import StockScanRequest
from app.schemas.scan_schedule import ScanScheduleEntry
from app.services.credential_store import CredentialStore
from app.services.strategy_watch_store import StrategyWatchStore
from app.services.scan_schedule_store import ScanScheduleStore
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.routers import credentials, composite_watch
print('VERSIONS',sys.version.split()[0],yaml.__version__,pydantic.__version__,fastapi.__version__)
def nested(n):
    v={}
    for _ in range(n-1): v={'x':v}
    return v
base={'universe':[], 'direction':'Bullish', 'horizon':'Swing'}
for n in (32,33,220,270,450):
    req=ScanRequest(**base,overrides=nested(n))
    outcomes=[]
    for name,fn in [('dump_json',lambda:req.model_dump_json()),('json_restore',lambda:ScanRequest.model_validate_json(json.dumps({**base,'overrides':nested(n)}))),('yaml_dump',lambda:yaml.dump(req.model_dump()))]:
        try: fn(); outcomes.append(name+'=ok')
        except Exception as e: outcomes.append(name+'='+type(e).__name__)
    print('DEPTH',n,'validation=ok',*outcomes)
for name,model,body in [('stock',StockScanRequest,{**base,'strategy':'pullback_ema','overrides':nested(450)}),('portfolio_patch',PortfolioPositionUpdate,{'alert_overrides':nested(450)})]:
    try: model.model_validate(body); print('SCHEMA',name,'depth450=accepted')
    except Exception as e: print('SCHEMA',name,type(e).__name__,str(e)[:180])
schedule={'id':'a','label':'a','mode':'options','profile_id':'p','profile_name':'p','profile_synced_at':'now','resolved_request':{**base,'ignored_extension':nested(450)},'pattern':'fixed_time','fire_time':'16:00'}
entry=ScanScheduleEntry(**schedule)
print('SCHEDULE ignored extra depth450 accepted=',bool(entry.resolved_request['ignored_extension']))
# Real credential/composite HTTP handlers, with temp-backed stores; no app lifespan/jobs/network.
for kind in ('credential','composite'):
    for n in (270,450):
        path=root/f'{kind}-{n}.yaml'
        store=CredentialStore(path) if kind=='credential' else StrategyWatchStore(path)
        store.save(); before=path.read_bytes()
        app=FastAPI()
        module=credentials if kind=='credential' else composite_watch
        attr='credential_store' if kind=='credential' else 'strategy_watch_store'
        app.include_router(module.router)
        async def http_probe():
            with patch.object(module,attr,store):
                async with AsyncClient(transport=ASGITransport(app=app,raise_app_exceptions=False),base_url='http://test') as client:
                    url='/settings/credentials' if kind=='credential' else '/api/composite-watches/'
                    body={'key':'tradier_paper','values':{'extension':nested(n)}} if kind=='credential' else {'symbol':'AAPL','trigger_def':{'extension':nested(n)}}
                    post=await client.post(url,json=body)
                    get=await client.get(url)
                    return post.status_code,get.status_code
        post,get=asyncio.run(http_probe())
        try: store.save(); later='ok'
        except Exception as e: later=type(e).__name__
        changed=store.get('tradier_paper').get('extension') is not None if kind=='credential' else len(store.list_watches())==1
        print('HTTP',kind,n,'POST',post,'GET',get,'memory_changed',changed,'disk_changed',path.read_bytes()!=before,'later_save',later)
for kind in ('watch','schedule'):
    path=root/f'{kind}-450.yaml'
    store=StrategyWatchStore(path) if kind=='watch' else ScanScheduleStore(path)
    (store.save() if kind=='watch' else store.upsert({'id':'baseline'}))
    before=path.read_bytes()
    try:
        store.add_watch('AAPL','pullback_ema',nested(450)) if kind=='watch' else store.upsert(entry.model_dump())
    except Exception as e: print('STORE',kind,'depth450',type(e).__name__,'disk_unchanged',path.read_bytes()==before,'entries',len(store.list_watches() if kind=='watch' else store.list()))
# Inject replace failures for shallow writes, proving depth validation alone is insufficient.
for kind in ('credential','watch','schedule'):
    path=root/f'{kind}-io.yaml'
    store=CredentialStore(path) if kind=='credential' else StrategyWatchStore(path) if kind=='watch' else ScanScheduleStore(path)
    (store.save() if kind!='schedule' else store.upsert({'id':'baseline'})); before=path.read_bytes()
    try:
        with patch('os.replace',side_effect=OSError('injected replace failure')):
            if kind=='credential': store.set('tradier_paper',{'account_id':'NEW'}); store.save()
            elif kind=='watch': store.add_watch('AAPL','pullback_ema')
            else: store.upsert({'id':'NEW'})
    except OSError:
        changed=store.get('tradier_paper')['account_id']=='NEW' if kind=='credential' else len(store.list_watches())==1 if kind=='watch' else store.get('NEW') is not None
        print('IO_FAILURE',kind,'memory_changed',changed,'disk_unchanged',path.read_bytes()==before)
# Real options restore, fake read-only session; no DB or persisted state edits.
from app.routers import scan
row=SimpleNamespace(last_result_json=None,last_request_json=json.dumps({**base,'overrides':nested(220)}),status='running',updated_at=None)
class Session:
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def execute(self,*args): return SimpleNamespace(scalar_one_or_none=lambda:row)
with patch.object(scan,'AsyncSessionLocal',Session):
    try: asyncio.run(scan.restore_from_db()); print('RESTORE options ok')
    except Exception as e: print('RESTORE options',type(e).__name__,str(e).splitlines()[0])
# B-only illustrations, deliberately bounded.
cycle=yaml.safe_load('a: &a [*a]')
fanout=yaml.safe_load('a: &a [1, 2]\nb: [*a, *a]\n')
print('YAML small_cycle',cycle['a'][0] is cycle['a'],'small_shared_alias',fanout['b'][0] is fanout['b'][1])
try: yaml.safe_load('['*600+'0'+']'*600)
except Exception as e: print('YAML depth600',type(e).__name__,'is_YAMLError',isinstance(e,yaml.YAMLError))
```

## B follow-up: bounded alias DAG reaches repeated live validation work

A separate Python 3.11.16 subprocess completed in under one second with `timeout 10s` (exit 0). The only payloads were **182 and 218 bytes**, with fanout 5 and respectively 3 and 4 alias levels. No file/store/DB/network mutation or HTTP server was used. An initial harness constructor typo (`_FileResult(file=...)`) raised `TypeError`; the completed run below uses the actual no-argument constructor.

Each document has valid empty `swing`/`position`/`intraday` horizon mappings and an unrelated `_aliases` holder. Its base anchor is `[0]`; each next anchor is a list of five references to the previous list. The actual walker was wrapped only to count calls and container identities; the unmodified original executed all traversal and validation. We called the real `_validated_direction_conviction_blocks`, the real scan-facing `load_direction_conviction_min_trend` (patching only its config source to return the parsed temporary document), and health's real `_check_conviction`.

| Levels / bytes | Real call path | Walker calls (includes scalars) | Container visits / unique containers | Base anchor visits | Outcome |
|---|---|---:|---:|---:|---|
| 3 / 182 | validator | 356 | 200 / 10 | 156 | Valid horizons; each block `None` |
| 3 / 182 | scan loader | 356 | 200 / 10 | 156 | Bullish Swing threshold `30.0` |
| 3 / 182 | health conviction check | 712 | 400 / 10 | 312 | No conviction errors |
| 4 / 218 | validator | 1762 | 981 / 11 | 781 | Valid horizons; each block `None` |
| 4 / 218 | scan loader | 1762 | 981 / 11 | 781 | Bullish Swing threshold `30.0` |
| 4 / 218 | health conviction check | 3524 | 1962 / 11 | 1562 | No conviction errors |

Adding one **36-byte** alias level increased unique containers from 10 to 11 but multiplied walker work approximately fivefold. The same base list is visited `1+5+25+125=156` times at level 3 and `1+5+25+125+625=781` at level 4. This demonstrates the pathological repeated-work mechanism through real reachable validation functions. The bounded payloads complete normally; this run does **not** claim a measured event-loop freeze, a wrong numeric result, or an HTTP-wide green health report. Full health checks include other config validations not exercised by the minimal document.

Reachability in the current source:

- `backend/app/routers/scan.py:1783` and `backend/app/routers/stock_scan.py:1826` synchronously call `load_direction_conviction_min_trend` in their scan cores. `backend/app/services/config_loader.py:367` calls `_validated_direction_conviction_blocks()`, whose loop at `:280` exhausts `_walk_direction_conviction_paths(cfg)`. The actual traversal recurses at `:211` / `:221`. Its ancestor set rejects cycles but deliberately revisits shared containers under every path (`:169` docstring explains the positional-validation reason). These are config-file aliases; JSON request bodies cannot introduce YAML aliases.
- `backend/app/routers/config.py:82` is the sync health handler returning `config_health.report()` at `:89` (FastAPI dispatches sync handlers in its worker pool). `backend/app/services/config_health.py:473` registers `_check_conviction` among scoring-file checks; `:538` invokes `_validated_direction_conviction_blocks(cfg=doc)`. Then `:542` calls `direction_conviction_value_errors`, which validates the whole graph again at `backend/app/services/config_loader.py:417`, explaining the doubled health counts. This is not evidence that this health route itself runs on the event loop.

**B remains separate under the approved split.** The A API cap/atomic-save/options-restore work does not eliminate YAML alias DAG expansion in manually edited config files. No B implementation is proposed or performed by this evidence follow-up.

Exact command from repository root (save the following script under the named `/tmp` path):

```sh
PYTHONPATH=backend timeout 10s backend/.venv/bin/python -u /tmp/yaml_alias_evidence_20261014.py
```

```python
import os
from collections import Counter
from unittest.mock import patch
os.environ['BAMENDJOU_CREDS_PATH']=''
import yaml
from app.services import config_loader, config_health
for levels in (3,4):
    text='horizons: {swing: {}, position: {}, intraday: {}}\n_aliases:\n  n0: &n0 [0]\n'
    for level in range(1,levels+1):
        text+=f'  n{level}: &n{level} ['+', '.join([f'*n{level-1}']*5)+']\n'
    doc=yaml.safe_load(text)
    original=config_loader._walk_direction_conviction_paths
    for route in ('validator','scan_loader','health_conviction'):
        calls=Counter();containers=Counter()
        def counted(node,*args,**kwargs):
            calls['all']+=1
            if isinstance(node,(dict,list,tuple)): containers[id(node)]+=1
            yield from original(node,*args,**kwargs)
        with patch.object(config_loader,'_walk_direction_conviction_paths',counted),patch.object(config_loader,'load_scoring_cfg',return_value=doc):
            if route=='validator': outcome=config_loader._validated_direction_conviction_blocks(doc)
            elif route=='scan_loader': outcome=config_loader.load_direction_conviction_min_trend('Bullish','Swing')
            else:
                result=config_health._FileResult()
                config_health._check_conviction(doc,result)
                outcome=f'errors={len(result.errors)}'
        print('levels',levels,'fanout',5,'bytes',len(text),'path',route,'calls',calls['all'],'container_visits',sum(containers.values()),'unique_containers',len(containers),'n0_visits',containers[id(doc['_aliases']['n0'])],'outcome',outcome)
```
