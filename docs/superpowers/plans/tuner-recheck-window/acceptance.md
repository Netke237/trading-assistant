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
