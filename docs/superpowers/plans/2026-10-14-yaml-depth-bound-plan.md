# YAML-DEPTH-BOUND — board #167, phase A

## Scope and preserved evidence

Resume `board/yaml-depth-bound-b7c4dc2b` at c58843bf; preserve its 2026-10-11 evidence verbatim. Current branch `board/yaml-depth-bound-b1dd948c` includes main 65b58bb5. No previous plan/code rounds exist. Issue #167's final untagged reply approved the A/B split and the four recommendations. This phase is A: refuse excessive nesting before API persistence, make the affected stores transactional in memory and on disk, and guard options request restore. Phase B (shared YAML parsing/alias policy, unreadable-file save refusal, chart scheduler catch) is separate and is not created or implemented in this session. Small alias/depth fixtures reproduce B as supporting evidence only. The checked-in YAML format, numerical validation, migrations, aliases, defaults, optional null semantics, and scan result vintage rules remain unchanged.

Do not edit Pre-Breakout, backtest/chart, screen-label presentation, scripts/state.py, .github, or the already-fixed isdigit/isdecimal work. Coordinator edits only plan/audit/state records; fresh implementer per ticket. Fresh independent auditors apply the repository gate and cap of three per stage.

## Rejection contract

Free-form persisted request fields accept at most 32 nested dict/list containers, counting the field's own root container as level 1. Scalars do not add a level. Reject level 33 with a named PydanticCustomError (`payload_depth`, a validation ValueError) and HTTP 422 before handlers run. Do not truncate, coerce, discard unknown keys inside free-form dicts, or change optional/null behavior. Existing unknown top-level request keys retain Pydantic's existing behavior. Scheduled `resolved_request` must itself be bounded, including extra keys that its parsed ScanRequest/StockScanRequest would ignore. Existing numeric and cross-field validators still run.

Use an iterative walker, no recursive Python calls. Handle shared Python containers without exponential traversal (memoize the greatest visited depth; deeper visits must still be checked) and reject cycles by the depth bound; do not expand/serialize an alias graph. This helper validates an already-decoded request field, not YAML source. Preserve accepted objects and field JSON schemas.

## Task 1 — request boundaries

Files: new `backend/app/schemas/payload_depth.py`, `backend/app/schemas/__init__.py`, `backend/app/schemas/stock_scan.py`, `backend/app/schemas/scan_schedule.py`, `backend/app/routers/{credentials,strategy_watch,composite_watch,auto_trade}.py`, `backend/app/main.py`, new `backend/tests/test_payload_depth.py`.

Add shared depth validation and field validators only to:
- ScanRequest.overrides; StockScanRequest.overrides (inherited StockAnalysisRequest is covered).
- ScanScheduleEntry and ScanScheduleEntryCreate.resolved_request (whole dict, not just a parsed request).
- CredentialUpdate.values, AddWatch.params_override, CompositeWatchCreate.trigger_def.
- ArmRequest.exit_plan, targets, max_loss_override, trade_card_snapshot: apply the same bound before arming, since downstream PortfolioPositionCreate validation runs after a fill. Update the nearby uncapped-container mechanism comment; change no order logic.
- PortfolioPositionCreate: exitPlan, targets, tradeCardSnapshot, maxLossOverride; PortfolioPositionUpdate: exitPlan, targets, maxLossOverride, alertOverrides.

Leave output models unchanged so historical rows can still be read. When the response contains a named payload_depth error, omit input from every error record before the production request_validation_handler calls _finite_or_str/jsonable_encoder: another missing/type error may contain the whole rejected body. Without a payload_depth error, preserve existing input handling. Otherwise a decoder-reachable depth900 input can make the refusal itself recurse. Preserve all ordinary numeric/error behavior and do not echo or log the rejected body. Tests must install the production exception handler and send bounded raw JSON at depth900 as well as historical failing depths; verify a compact 422 and no side effects. This is required safe-rejection acceptance coverage. Tests first: valid shallow payloads and depth32 round-trip; depth33 and historically failing depth220/300 rejected at every boundary. Include mixed dict/list chains, repeated shared children including a deeper later occurrence, cycles via model_validate, snake_case and camelCase portfolio aliases, absent and explicit null fields, and valid request defaults/numeric validation. For all four arm fields, cover HTTP refusal before arming/broker side effects and accepted depth32 through auto_trade_booking._build_body. Exercise real FastAPI request validation on small router-only apps with mocked handler dependencies; verify depth rejection does not mutate stores/DB or start scan work. Preserve field schema shapes. Run required full checks, commit `fix(config): bound persisted request payload nesting` with repository attribution trailer.

## Task 2 — transactional file-backed mutations

Files: `backend/app/services/{credential_store,strategy_watch_store,scan_schedule_store}.py`, `backend/app/routers/credentials.py`, new `backend/tests/test_payload_persistence_atomicity.py`.

All affected mutation/save operations hold their store lock through persistence and publish the new in-memory state only when persistence succeeds (or restore previous state under that lock on failure). Preserve file formats, migration behavior and credential 0600 permissions. Preserve standalone CredentialStore.set/save semantics used elsewhere; add a single atomic set-and-save operation for the credentials POST, replacing its split set/save. No cache clearing on failed credential persistence. Do not reload files per mutation. Preserve other slots and existing nested data.

Watch operations: add_watch, add_composite_watch, remove_watch, update_state, set_schedule; retain the already-transactional set_enabled transform behavior. Bulk keeps its established per-item behavior. A failed watch add cannot remain active in evaluator memory; failure in a replacement/removal cannot erase an earlier watch. ScanScheduleStore.upsert and delete similarly preserve prior entries on failure, including full replacement by id. `_load` unreadable-file policy is B and is untouched.

Tests first on temp files: injected yaml.dump RecursionError, write_text OSError and os.replace OSError at each applicable transaction boundary leave byte-identical prior file and prior in-memory data; subsequent shallow mutation succeeds and survives a fresh store load. Use small payloads and mocked failures, not huge dumps. Test failed credential POST leaves original slot/cache and unrelated slots intact and 0600 preserved on success; test concurrent independent updates cannot lose a successful write. Do not swallow failures or report success. Serialization still precedes replacing target. Run required full checks, commit `fix(config): roll back failed store persistence` with attribution.

## Task 3 — guarded options restore

Files: `backend/app/routers/scan.py`, new `backend/tests/test_scan_request_depth_restore.py`.

Wrap only ScanRequest.model_validate_json for saved options last_request_json in a validation-error guard, mirroring stock restore. On failure clear _last_request, emit a warning identifying the saved options request without dumping the body, retain valid current-version result and existing status/timestamp behavior. Do not rewrite/delete the database row, manufacture defaults, replay a refused request, change result-vintage rejection, or broaden the result parser's behavior.

Tests first with isolated SQLite/test sessions: depth220 JSON (jiter refusal), valid JSON depth33 (new validator refusal), malformed JSON and another genuine schema-invalid request do not abort restore; saved request absent from last-run metadata, valid saved result remains byte-equivalent and DB unchanged. A valid depth32 request restores unchanged. Vintage-result discard still forces idle and clears timestamp. Seed _last_request before invalid restore to catch stale-request leakage. Run required full checks, commit `fix(scan): guard invalid persisted options requests` with attribution.

## Task 4 — bounded mixed-error refusals (acceptance follow-up)

Files: `backend/app/main.py`, `backend/tests/test_payload_depth.py` only. A bounded reproduction after Task1 found that depth900 with valid required fields returns422, but the same input missing `universe` returns500: the missing-field error has its own `input` pointing at the entire body. This violates safe depth-rejection acceptance even though no handler or persistence runs.

Tests first: send raw depth900 bodies with a missing required field and a separate ordinary field-type error through the real production validation handler. Require a compact422 retaining every loc/msg/type and the named depth error, with no handler/store/broker effects. Retain depth-only refusal coverage and ordinary non-depth/numeric error input behavior (including NaN/Infinity normalization) unchanged. Include actual scan and arm routes so both regular and order-bearing boundaries are covered.

If any error is `payload_depth`, strip `input` from all records in that response before either recursive normalizer/encoder. For responses without a depth error keep current error handling unchanged. Preserve schemas, accepted payloads and all application/order/persistence behavior. Run required full checks; commit `fix(api): keep mixed depth validation errors bounded` with attribution. Fresh implementer; independent integrated code audit includes this follow-up. This is the same phase, and the existing audit counters are not reset. Plan correction uses plan round3 of3 before this ticket is cut.

## Validation and audit

Every implementer verifies Python 3.11 before backend work, runs meaningful red tests before implementing, then `cd frontend && npm run typecheck && npm run test -- --runInBand`, and `cd backend && .venv/bin/python -m pytest`. Coordinator records any failures faithfully; no unrelated fixes or golden re-pins. Full backend/ frontend checks must pass for self-merge. After all tickets are pushed and closed, fetch/merge origin/main immediately before code round1, resolve only authorized scope, rerun required checks. Independent integrated code audit covers exact `origin/main..<head>` plus plan, all four tasks and interactions; later rounds only prior fixes/interactions, never reset counters. Record reviewer, exact head/diff, findings/fixes/outstanding in state and audit files. A fresh implementer fixes gate findings.

Only create PR after code clean; `Closes #167`, status built, audit_clean true. Self-merge only per board.md step7: own claimed PR, no hold, exact reviewed head plus allowed docs/state-only records, green exact-head CI, MERGEABLE, pending merge record pushed and checked, match-head merge commit. Never claim shipped before verified merge. Work only this board item.
