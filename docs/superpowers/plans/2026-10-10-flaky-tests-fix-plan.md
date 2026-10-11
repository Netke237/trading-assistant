# FLAKY-TESTS-FIX — plan

Board item / tracking issue: **#160** · Branch: `board/flaky-tests-fix-fec8e2c9` (from `origin/main` e765cf4f) · Tests only.

## Goal (from #160)

Make the suites deterministic and offline.

## Source evidence

`.scratch/project-ticket-reconciliation-20261009/issues/26-flaky-tests.md` (ticket 26; also `f501ad40` on `claude/relaxed-fermat-sm9xru`). It proposes five narrow fixes. Status on current main (e765cf4f):

| Fix | What | Status / decision |
|---|---|---|
| FIX-26A | Heston timeout test: its cleanup runs after the assertions, so a failed timing assertion leaks a semaphore permit and a pending task into the next two tests (3 CI failures from 1) | **In scope — Task 1** |
| FIX-26B | Step 7 `direct-send-save-first` test 8 exceeds Jest's default 5 s limit under load (reproduced 5/5 under 12 busy loops) | **In scope — Task 2** |
| FIX-26D | Stub the live providers in `test_shortlist.py::_enter_shortlist_patches` | **Already on main** (`backend/tests/test_shortlist.py:81-92`, the #129 fix) — nothing to do; Task 3 pins that it stays offline |
| FIX-26C | Self-host the Google fonts (`next/font/local`) so `next build` cannot fail on a font fetch | **Out of scope:** it changes `frontend/app/layout.tsx` and adds font binaries, not tests. Listed for Kenneth as a separate item |
| FIX-26E | `.claude/hooks/session-start.sh` builds `backend/.venv` with `python3` (3.13 in cloud containers) instead of 3.11 | **Out of scope:** a hook, not a test. Listed for Kenneth as a separate item |

The 0.4 s wall-clock ceiling itself (`test_scan_endpoint.py:1038`) is **not** widened: the evidence found the CI outlier unexplained, and widening would weaken the test. No assertion anywhere changes; no golden numeric pin changes.

## Task 1 — FIX-26A: the Heston timeout test always cleans up

File: `backend/tests/test_scan_endpoint.py` only (the test ending ~L1046, `test_process_symbol_falls_back_when_calibration_exceeds_timeout`).

- Test first (red): in a scratch copy, force the timing assertion to fail (e.g. temporarily make the fake calibration's ceiling check impossible) and run this test together with `test_run_heston_calibration_holds_semaphore_until_real_completion` and `test_abandoned_heston_task_exception_does_not_leak_unretrieved`. Record that the two neighbours fail as in CI (`assert 3 == (5 - 1)` / "Task was destroyed but it is pending"). Then restore it. This scratch forcing is evidence only and is never committed.
- Change: wrap everything from `start = time.perf_counter()` through the three assertions in `try:` and move `await _await_abandoned_heston_calibrations()` into `finally:`. The assertions, the patches and the 0.4 s ceiling keep their text.
- Green: with the same forced failure, only the forced test fails and its two neighbours pass. Without it, the file passes.

Commit: `test(scan): the Heston timeout test always waits for its abandoned calibration (FLAKY-TESTS-FIX T1)`

## Task 2 — FIX-26B: Step 7 test 8 gets an explicit timeout

File: `frontend/app/(frame)/screener/step-7-trade-card/__tests__/direct-send-save-first.test.tsx` only (`it('8. an ORDER-UNKNOWN note survives Next, Prev, a basket submit, a new send and a remount', …)`, ~L426).

- Red: reproduce the timeout under CPU load, as in the evidence (e.g. 12 busy loops via `yes > /dev/null &`, then kill them), recording the `Exceeded timeout of 5000 ms` failure. If it cannot be reproduced in this container, record that and proceed: the change is a pure timeout and the evidence reproduced it 5/5.
- Change: pass an explicit per-test timeout of `15_000` ms as the third argument of that `it(...)`, with a one-line comment citing ticket 26. No other test, assertion or helper changes.
- Green: the file passes, and under the same load test 8 passes.

Commit: `test(step7): explicit 15 s timeout for the long multi-step ORDER-UNKNOWN test (FLAKY-TESTS-FIX T2)`

## Task 3 — confirm FIX-26D holds (no file change unless it fails)

Run `backend/tests/test_shortlist.py` with outbound network blocked for the provider hosts (this container's proxy already returns 403 for yfinance / Tiingo / Tradier). It must pass quickly and log no provider fetch attempt. If anything still reaches the network, stop and report; that would be a plan defect, not something to fix here.

## Acceptance (#160)

- [ ] FIX-26A and FIX-26B in, test files only, no assertion or pin changed (diff review)
- [ ] FIX-26D confirmed offline on main
- [ ] Full Python 3.11 backend suite and full Jest + typecheck green
- [ ] FIX-26C and FIX-26E reported to Kenneth as separate items (not built here)
- [ ] Plan audit and code audit clean (`audit_rule`)
