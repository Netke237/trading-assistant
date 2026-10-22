# 26: Reproduce and isolate remaining flaky tests

**What to build:** Identify reproducible failures separately from provider/font restrictions and runtime mismatches.

**Blocked by:** Exact current-main baseline and runtime.

**Status:** evidence done 2026-10-10 (no code changed). Four narrow test/infra fixes are proposed below. They need Kenneth's go and the usual audit before anyone builds them.

**Owner category:** agent evidence.

- [x] Record interpreter, working directory, failure signatures and deterministic reproductions.
- [x] Propose narrow fixes only where supported by evidence; keep golden numeric pins and assertions intact.

## Evidence (2026-10-10)

**Setup.** Baseline: main `a2b6935c`, in a detached scratch worktree that was removed afterwards. Backend runs used a scratch Python 3.11.17 venv built from the pinned `requirements.txt`, running `pytest` serially as CI does (`.github/workflows/ci.yml`: Python 3.11, no xdist). Frontend runs used `npx jest --ci` on Node 22; CI uses Node 20, which is a runtime mismatch. The machine has 4 CPUs. CI logs were read through the GitHub MCP. The work was done by a fresh evidence subagent; the coordinator spot-checked the file:line claims.

**Full runs on main.**
- Backend: 3 failed, 6806 passed, 9 skipped, in 1795 s. CI on the same commit: 1 failed, 6808 passed, 9 skipped, in 639 s.
- Frontend: 217 suites, 4845 tests, all passed.

| Test | Class | Evidence | Cause | Proposed narrow fix |
|---|---|---|---|---|
| `test_scan_endpoint.py::test_process_symbol_falls_back_when_calibration_exceeds_timeout` | timing flake (root) | CI on PR #68 failed with `took 0.663s … < 0.4`. Locally: 0 failures in 70 runs, 15 of them under 8 busy loops. | Fixed 0.4 s wall-clock ceiling at `:1038`. The 0.663 s on CI is unexplained, and a pass rate is not proof the flake is absent. | None for the ceiling. Evidence is insufficient, and widening it would weaken the test. |
| `…::test_run_heston_calibration_holds_semaphore_until_real_completion`, `…::test_abandoned_heston_task_exception_does_not_leak_unretrieved` | knock-on failures, **reproduced 3/3** | Forcing only the root assertion to fail reproduces exactly CI's 3 failures (`assert 3 == (5 - 1)`, "Task was destroyed but it is pending"). | The cleanup `await _await_abandoned_heston_calibrations()` (`:1046`) runs after the assertions. When an assertion fails, the background task keeps its permit on the module-level `_HESTON_SEMAPHORE`, and its later garbage-collection log message breaks the next test. | **FIX-26A:** move the cleanup into `try/finally`; the assertions stay unchanged. Optional: give the semaphore test a fresh patched semaphore, as `test_heston_calibration_respects_scan_concurrency_limit` already does. Turns 3 CI failures into 1. |
| `step-7-trade-card/__tests__/direct-send-save-first.test.tsx` test 8 (`:426`) | load flake, **reproduced 5/5 under 12 busy loops** | No load: 0/20 alone and 0/1 in the full suite. 8 loops: 0/6. 12 loops: 5/5, failing with `Exceeded timeout of 5000 ms` at 5058 ms. The 2026-10-05 failure recorded no signature, so a match is likely but unproven. | A long multi-step test under Jest's default 5 s per-test limit. It takes about 1.8 s when idle. | **FIX-26B:** give test 8 an explicit timeout (for example 15000 ms), or split it. Assertions unchanged. |
| CI `next build` Google font fetch (DM_Sans, JetBrains_Mono) | provider restriction | 3 CI occurrences: job 111323151936 (10-04), PR #69, job 114002216445 (10-09). Not reproducible here. | `@next/font/dist/google/loader.js:122` reads `/\.(woff\|woff2\|eot\|ttf\|otf)$/.exec(url)[1]`. Google returned CSS containing a font URL with no extension. | **FIX-26C:** self-host the fonts with `next/font/local`: Sora 700, DM Sans 400/500/600, JetBrains Mono 400/500 (`frontend/app/layout.tsx`). |
| `test_stock_scan_backtest_commission.py::test_analyze_core_passes_commission_from_get_costs` | deterministic | Fails 3/3 locally and in CI with `TypeError: replace() should be called on dataclass instances` (`:175`, a MagicMock card). | — | Tracked in GitHub #129; not part of this ticket. |
| **New:** `test_shortlist.py::test_shortlist_keeps_highest_scores_not_universe_order`, `::test_trimmed_names_are_recorded_and_counted_once` | environment: the tests reach live providers | Fail here, where the sandbox proxy blocks yfinance, Tiingo and Tradier; pass on CI. `test_shortlist_cap_enforced` takes 1018 s and passes. | `_enter_shortlist_patches` (`test_shortlist.py:73`) does not stub `historical_store.get_bars`, `fetch_calendar_dates_async` or `fetch_quotes`, so the tests depend on real network calls. | **FIX-26D:** stub those three in `_enter_shortlist_patches`. A scratch plugin doing this gave 19 passed in about 5 s, 3 runs out of 3. The same stubs cut `test_scan_endpoint.py` from about 300 s to seconds. |

**Other notes.**
- `test_scan_core.py`'s two stock-scan tests take about 71 s each, even with the FIX-26D stubs. Some other provider is still reached; it was not identified.
- `test_walk_forward.py::test_train_fold_finds_a_winner_on_real_sub_gate_trade_counts` takes 105 s; not investigated.
- CI logs show `PytestUnhandledThreadExceptionWarning` / `Event loop is closed` from aiosqlite threads. These are annotations only and do not fail the job.

**Runtime mismatch in the cloud setup (outside this ticket).** `.claude/hooks/session-start.sh:21` builds `backend/.venv` with plain `python3`, which is 3.13.16 in this container. That breaks the CLAUDE.md "Backend runtime" rule, which requires Python 3.11. The fix is to build the venv with `python3.11` and to rebuild an existing venv whose version is wrong. Proposed as **FIX-26E**.

**Ownership check before any fix.** `backend/app/routers/scan.py` belongs to the active AUTOTRADE-FIRE-HYGIENE claim (H1 adds `_SCAN_FIRE_EXECUTOR`). FIX-26A and FIX-26D change only test files, but `test_scan_endpoint.py` may also be edited by that work. Coordinate with that claim, or wait for it to finish, before touching that file.
