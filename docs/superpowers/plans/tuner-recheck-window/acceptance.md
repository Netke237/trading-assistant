# TUNER-RECHECK-WINDOW acceptance evidence

Tracking issue #638. The live issue and PROJECT_STATE retain authoritative progress/audit status. Machinery only; real J1 tuning remains #115. No provider or broker calls, active parameter adoption or production DB writes are part of this acceptance.

## Baseline before production changes

- Application baseline `236bec67`; independently approved plan SHA256 `7d0f8102121210416d0ca202c7d3f67ebff5eb6f4d3fbc80930a5498095e2ad0`.
- Python 3.11.9 verified for default and prepared backend virtual environment.
- From `backend/`: `.venv/Scripts/python.exe -u -m pytest tests/test_horizon_tuning_core.py tests/test_horizon_tuning_report.py tests/test_setup_tuning.py -q`: **103 passed in 61.31s**. Retained output: `baseline-pytest.txt`.
- Baseline frontend `npm run typecheck`: passed, observed by coordinator before the interrupted implementation handoff.
- Initial sandboxed baseline attempts stalled before any test in asyncio's Windows local socket-pair creation (`conftest.py` session database fixture). Those attempts were stopped; the unchanged tests passed with the needed execution permission. This is not a test failure or a justification for weakening assertions.
- Usage interruption occurred before the first implementer made any changes. Resume uses a fresh pushed board branch and fresh implementer. Plan audit counters are preserved, not rerun or reset.

## Required integrated acceptance (pending)

- [ ] Exact independent full-series versus optimized re-check equality: all six ordinary tuned strategies, both directions/costs, trades/stats/fires/drop counts/verdict.
- [ ] Stateful setup strategies keep complete series; final parameters and sample-grid search unchanged.
- [ ] Scoped/full/cache-window isolation, cold/warm/cache-disabled, worker prewarm and real multiprocessing smoke.
- [ ] Adjusted read-only single-snapshot export, manifests/hashes/missing data and no overwrite/partial publication.
- [ ] Same export with fixed code/config/universe input shares data/run identity across dates; finished cells skip actual work; tampering invalidates resume.
- [ ] Pair-specific workload projections and bounded AAPL/MSFT/NVDA fixture probe; report projection versus measured timing honestly.
- [ ] Mini-PC run-book: fixed inputs and persistent per-strategy output roots, below-normal scheduled task, no MEAS/nightly overlap.
- [ ] Full backend pytest, full frontend Jest and typecheck on integrated code; production configuration/simulator/signal functions/history writers remain unchanged.
- [ ] Actual origin/main merged before independent complete code audit; per-stage cap and exact scope recorded.
- [ ] Exact-head CI/mergeability/ownership/hold checks; pending merge record before guarded self-merge; actual verified merge and separate shipped reconciliation.

No completed application feature, independent code audit, green integrated suite or shipping result is claimed by baseline evidence.

## Verification checkpoint — 2026-11-14 (unfinished)

- T1 source `76ed0c72`, corrected writable Linux Python 3.11.17 full backend: **10,307 passed, 9 skipped** in 2273.41s. This was a T1 snapshot, not the final integrated target.
- T2 source `0e1c2f14c5f073f9851f6aad37709132fc295077`: exporter/report focused checks **41 passed** in 43.51s on Linux Python 3.11; native Python 3.11.9 focused checks also **41 passed**. No independent code audit is claimed.
- Coordinator frontend `npm run typecheck`: passed on 2026-11-14.
- Full frontend Jest remains running in isolated writable source with native Linux Node 20.20.2 dependencies. Several existing Step 7 suites have failed; this run is not green. No assertions, expected values or test timeouts were changed.
- Baseline reproduction: exact `236bec67f01fe5e0a2d38ded047378ff84b4a7aa`, same Node 20 image and default Jest options, `edited-fields-sync.test.tsx`: **21 failed, 10 passed**, 210.646s. This establishes that suite's failure on the unchanged baseline; it does not classify every other failure. `git diff --exit-code 236bec67 HEAD -- frontend` confirmed no frontend source changes.
- Task 2 stays open pending verification; Task 3 and the integrated audit/PR/merge remain outstanding. Phase completion stays 20%, plan one clean round, code zero rounds, audit_clean false.
- Unrelated schedule changes from the separately claimed BG-SCHEDULE-MAINT task are excluded from this phase and its commits.

## Completed local frontend run and resumed diagnosis — 2026-11-14

- The isolated Node 20.20.2 Alpine full run finished: **337 suites passed, 10 failed; 6,322 tests passed, 57 failed**, exit 1, 2862.908s. This supersedes the earlier running status. The exporter snapshot was `0e1c2f14`; frontend source was unchanged from `236bec67`.
- The user first requested a pause until frontend tests pass, then explicitly instructed the coordinator to fix all failures, finish the task, and merge only after all tests pass. No local-check or audit waiver was granted. Resume branch: `board/tuner-recheck-window-f3774d77`.
- Fresh diagnosis helper `frontend_timeout_diagnosis` reran the unchanged `sends the EDITED invalidation` test in isolation under the same Node/Alpine runtime and default five-second test limit: **passed in 4280ms** (cold suite startup 63.191s). Native amd64/x64; no emulation. This shows that one test can pass and has limited headroom; it does not clear the 57 failures or establish a root cause.
- A same-Node-version glibc comparison is pending. No production behavior, assertion, expected value, or timeout has been changed. Independent code audit remains unstarted and the phase remains unfinished.

- Completed disposable diagnostic comparison on native Node20.20.2 glibc: original selected test timed out6703ms; execution/review-only scoping timed out5177ms; including ladder interaction scope passed2223ms against the unchanged5000ms limit. Final command selected one test (1passed/30notselected), not a suite-wide pass. Existing numerical/order assertions and default role visibility remained intact; only search scope changed in the disposable copy. Host frontend sources remained unchanged during diagnosis.
- Fresh independent amendment plan review `tuner_plan_amendment_audit_2` reported zero gate findings at SHA2561941a3aca2ba951a516baf7b3f2c6091e66650414f5aff5838822b99cb3b77fa; record `plan-amendment-audit-2.md`. Original plan1 preserved, continuousround2/planstage2, code0. New Task2a implementation and full-suite verification remain pending.

## T2a plan defect and plan round 3 — 2026-11-16

- Resumed on the new branch `board/tuner-recheck-window-03e0fc95`, cut from `f3774d77` at head `09a4c4fa`. The claim had expired and was re-taken with exit 0. The item still carries `agent-in-progress` and names this branch.
- Before T2a, the ten permitted suites on Windows 11 (native Node 22, 4 logical cores, default workers): **10 failed / 176 passed**, 199 s.
- T2a implementer, semantic scoping only (permitted files plus `frontend/test-utils/tradeCardQueries.ts`, uncommitted): native **183/186**; Node 20 glibc container **179/186**. Residual failures:
  - B7, a calendar failure;
  - two `edited-fields-sync` timeouts, 5155 ms and 5054 ms, against the unchanged 5 s limit.
  The dropped-stop test gave back the shared daily cap only on its last line, so in the container one timeout caused five follow-on failures. Run alone, the test takes about 2.7 s and the suite passes 31/31. The implementer reported this as a plan defect and committed nothing.
- B7 ("B7 inherits the earnings veto…") is a pre-existing failure on `origin/main` `2f8b8dc1` (main CI: 1 failed / 6507 passed). Its fixture scan is dated 2026-10-05 with `earnings_days: 40`, so since 2026-11-15 `stockEarningsGate` treats the veto as expired. The fix belongs on main as a separate change, and this phase must see B7 pass after Task 4 merges `origin/main`.
- Kenneth chose option 1: keep the scoping, restore the cap in `finally`, and verify with `--maxWorkers=2` at unchanged limits. The amendment was appended to the plan.
- Coordinator check after adding the `finally`, native Node 22.23.2 with `--maxWorkers=2`: ten suites **185 passed / 1 failed (B7 only)**, 235 s. `npm run typecheck` was clean. This is a focused subset and does not close the full-frontend gate.
- Plan round 3 (stage 3/3): fresh `gate-auditor` `tuner_plan_amendment_audit_3` on SHA256 `e0adace9657c3701df35ba41eee9ad41d86330b412d882e3997935103bda6af6`, **0 gate findings**. Record: `plan-amendment-audit-3.md`. The plan stage is at its cap and clean. Code stage: 0 rounds, `audit_clean: false`.
- Still to do: the container ten-suite and full frontend Jest runs (`--maxWorkers=2`), the T2a commit, T2 tests, T3, and T4 (merge `origin/main`, integrated checks, code audit, PR).

## T2a #647 built and verified — 2026-11-16

- Coordinator, Node 20.20.2 glibc container (`ta-frontend-test:tuner638-node20-glibc`, 4 cores, `--maxWorkers=2`, default limits, no network), ten suites:
  - run 1: **184/186**, failures B7 and one transient timeout in `submission-review` "shows the actual execution inputs once…";
  - run 2: **185/186**, B7 only.
  That test run alone took 2133 ms. The transient is recorded here and was not explained away. It did not recur in either full run below.
- Fresh implementer committed `296ac66e test(frontend): scope trade-card queries to their semantic sections`. It changes exactly the 11 permitted files, and the coordinator checked the list with `git show --stat`. The implementer made no further code changes. Typecheck is clean.
- Full frontend Jest in the same container with `--maxWorkers=2`:
  - Run A, snapshot of `frontend/` only: 344/347 suites, 6353/6359 tests, 728 s. Besides B7, the failures were `optionsSearchProfilesRecalibration` (5 tests) and `strikeFormatGolden`, which failed to run with ENOENT on `/repo/backend/tests/fixtures/strike_format_golden.json`. Both suites read tracked files outside `frontend/` (`docs/search-profiles/search-profiles-export.json`, `backend/tests/fixtures/strike_format_golden.json`), and the helper's snapshot leaves them out. The failures come from the harness, not the code.
  - Run B: the only change is that the helper's `git archive` also includes those two tracked paths from HEAD. Result: **346/347 suites, 6378/6379 tests, 700 s; the only failure is B7.** This meets amendment 2026-11-16 item 3.
- B7 stays red until main carries its date fix, and must pass after Task 4 merges `origin/main`. Task 2 (#640) can close only after its own required checks pass. Task 3, Task 4 and the code audit are still pending. Phase completion stays at 20 %, because the build milestone needs all build units. Code stage: 0 rounds, `audit_clean: false`.

## T2 #640 verified — 2026-11-16

All runs: container `ta-backend-test:latest`, Python 3.11.17, no network, an ephemeral `git archive` of head `adaee9f9`, and no overlay (the unrelated `sp500.csv` and `strategy_watches.yaml` edits are excluded).
- Harness fix: `.scratch/tuner638_docker_tests.py` (untracked) reopened git's tar in append mode even with nothing to append, and that corrupted the end of the archive ("end of file header"). That is why the 2026-11-14 T2 attempt never ran a test. The helper now skips the append when the overlay is empty.
- Focused tests (`test_export_tuning_bars`, `test_horizon_tuning_report`, `test_horizon_tuning_core`, `test_setup_tuning`): **128 passed**, 34.6 s.
- Full backend run 1: **10331 passed, 9 skipped, 1 failed**, 1815 s. The failure was `test_heston_perf::test_first_calibration_under_500ms` at 0.551 s against its 0.5 s limit. That test alone: 5/5 passed. The phase changes no Heston code. The same load-timing behaviour is already recorded in PROJECT_STATE from an earlier phase, and the limit was not changed.
- Full backend run 2, on an idle machine: **10332 passed, 9 skipped, 0 failed**, 1621 s.
- With T2a's full frontend result (6378/6379, B7 only) and a clean typecheck, T2's required checks are met. T3 and T4 (integrated checks after merging `origin/main`, code audit) are still pending. Phase completion stays at 20 %. Code stage: 0 rounds, `audit_clean: false`.
