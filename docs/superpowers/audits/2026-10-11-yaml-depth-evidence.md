# YAML-DEPTH-BOUND (board #167, ticket 24): evidence, 2026-10-11

Evidence only, no code changed. A fresh evidence subagent ran every reproduction on a scratch copy of main `48ff4ce9`+ (Python 3.11.17, PyYAML 6.0.1 pure-Python loader, FastAPI 0.141.1, pydantic-core 2.46.4). The coordinator spot-checked the file:line claims.

## Depth limits measured

| Layer | Fails at nesting depth | Result |
|---|---|---|
| FastAPI body `json.loads` | ~1000–1100 | 400 (safe) |
| pydantic `dict` / `dict[str, Any]` fields | none | accepted |
| pydantic `model_validate_json` (jiter) | 201 | ValidationError "recursion limit exceeded" |
| pydantic response serialisation / `model_dump_json` | 255 | `PydanticSerializationError` → 500 |
| `yaml.dump` in a request | ~310–400 | RecursionError |
| `yaml.safe_load` | ~470–520 | RecursionError (not a `yaml.YAMLError`) |

## A. Reachable by a crafted API request (the normal UI never builds this nesting)

- **A1 — the backend can't restart after one request.** POST `/api/scan` with `overrides` nested 201–254 deep returns 200 and persists the request (`scan.py:1531-1535`). On the next start, `restore_from_db` → `ScanRequest.model_validate_json` (`scan.py:1605`) raises, unguarded in lifespan (`main.py:165`), so **startup fails** until the DB row is fixed by hand. The stock path is already guarded (`stock_scan.py:740-762`).
- **A2 — the store is poisoned in memory after a failed save** (depth ~310–1000). Affected:
  - `credential_store.set` (`credential_store.py:125`);
  - `strategy_watch_store.add_composite_watch` (`:220-255`) and `add_watch` (`:168-205`);
  - `scan_schedule_store.upsert` (`:86-90`).

  Each mutates memory, then `yaml.dump` raises, giving a 500. The file is intact, but every later save of that store returns 500 until restart. Watch state transitions are then kept in memory only (`strategy_watch_evaluator.py:136-144` swallows the save error). The failed composite watch stays live in memory.
- **A3 — the data is saved but every later read returns 500** (depth 255–~310). Affected: the same endpoints, plus the portfolio DB (`routers/portfolio.py:160`, `exitPlan` / `targets` / `alertOverrides`). The write is saved, but the response fails. After that, GET `/api/composite-watches/`, `/api/strategy-watch/`, `/api/scan-schedule`, `/settings/credentials` and `/api/portfolio` return 500 permanently.

## B. Reachable only by hand-editing a config file

- **B1 — an alias bomb in scoring_rules.yaml freezes the event loop.** `config_loader._walk_direction_conviction_paths` re-walks shared containers (cost 9^levels). It runs synchronously in the async scan cores and in config health. 8 levels froze a scan for 34 s and the first health poll for 66 s; 10 levels would take ~45 min.
- **B2 — an alias bomb inside `composite_trigger` aborts the process.** GET `/api/composite-watches/defaults` builds a 33 MB response at 7 levels; at 9 levels the process dies with SIGABRT.
- **B3 — deep `settings.yaml`, `strategy_watches.yaml` or `local_credentials.yaml` stops the app importing.** The module-level loaders catch only `YAMLError`.
- **B4 — scoring_rules.yaml at the depth threshold gives a false-green health check while every scan returns 500.** The health check parses in a threadpool, which has a different stack depth.
- **B5 — deep rule files give bare 500s** on several endpoints.
- **B6 — a deep but still loadable settings.yaml or risk_rules.yaml makes every save return 500** (unnamed error; the file stays intact).
- **B7 — any load failure of scan_schedule.yaml silently wipes it on the next save** (`except Exception: pass`, then start empty). The other schedule stores have the same pattern.
- **B8 — a deep settings.yaml edited at runtime kills the chart-alert scheduler** (`chart_alert_scheduler.py:246`, narrow catch).
- **B9 — a recursive alias inside a strategy watch makes the list return 500 permanently**, because every save keeps the cycle.

No path puts a wrong number on screen or in an order. The failures are crashes, hangs, wrong persistence and a false-green health check.

No checked-in config file uses YAML anchors or aliases.

Guards that already hold:
- config_health's parse and `canonical` budget;
- the scoring_rules cycle check;
- `contracts.py:104`;
- `atomic_write_yaml` never writing partial files;
- `adopt` deep-copying before it mutates;
- the guarded stock restore.
