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
