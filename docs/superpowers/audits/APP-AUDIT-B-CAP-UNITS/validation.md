# #368 implementation validation

Fresh implementer: `/root/implement368`, production/test commit `a7ebb25a`.
Plan stages preserved: 2 rounds, independently clean; code stage pending.

## RED / GREEN

- Rendered manual RunScanButton and saved-profile resolver: 18 failed / 32 passed before fix. Literal failure: expected `25000000`, received `25`. Corrected source: 50 passed.
- Direct shared request builder: 10 failed against the exact pre-change module, including expected `25000000` / received `25` and expected `500000` / received `0.5`; corrected source: 10 passed. Baseline module extracted using `git show a7ebb25a^:frontend/lib/resolveOptionsScanRequest.ts` and selected via Jest module mapper, without editing the working tree.
- Backend: Python 3.11.16. New tests against a temporary backend copy with ONLY the exact pre-change schema and scheduler from `a7ebb25a^`: 7 failed / 24 passed. Failures demonstrate legacy cap schedules executing instead of refusing and absent marker support. Corrected source: 31 passed. No original audit captures or golden numbers changed.
- TypeScript checking passed before implementation commit and after resolving current-main integration.

Commands: `npm run test -- --runInBand --runTestsByPath lib/__tests__/scanScheduleResolve.test.ts components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx lib/__tests__/resolveOptionsScanRequest.test.ts`; `npm run typecheck`; `.venv/bin/python -m pytest tests/test_options_cap_units.py -q` from backend.

Fixtures cover min/max 25M, 2B, fractional M/B, explicit zero, blank and nonfinite omission; actual backend cap comparisons below/at/above the USD boundary; marker schema and YAML roundtrip; refusal without invoking scan core; persisted recovery guidance; explicit resync with fresh USD amounts; no-filter/zero-only legacy compatibility; original stored request bytes unchanged by execution. Providers/reporting/notifications are mocked.

The backend test database fixture initially stalled under the network-isolated executor. Running the same command with supported network permission completed; no application workaround was added.

Raw session-log digests (logs retained in execution temporary storage):

- `368-frontend-red.log` SHA256 `d24ff9aa7e1a93d40e14221a4e2128d675d5428d6199523c69a036ae64959783`
- `368-frontend-green.log` SHA256 `ce6da1c89e67876b4eca3de5b2868c75480473110b0b18f988cba0e59aec1906`
- `368-builder-red.log` SHA256 `f9e33e06a4aa5e07f3c63d90b71b67e785e283061f13f014a057eb937eab1a24`
- `368-builder-green.log` SHA256 `4b02e141a69ed373736d0c137ebb181dc378b88991756577e67ad3a3e60cd8f7`
- `368-backend-red.log` SHA256 `eafa448c9e3c26506988023f955447693e6fd6a9928b4e65faf0b824dbec93ae`
- `368-backend-green.log` SHA256 `0381e08b2a480fd2bd92080b4156671826346dd390db140518fa83cd1c01be5e`
- `368-typecheck.log` SHA256 `abc9de01b776a9092cbcf6ff36c285ded283733c1f4375b6dc7158a942c8897f`

## Integrated checks

Integrated current main `6dd96dc6` in `d12559a0`; the only source/test conflict appended the independent #368 and existing #387 RunScanButton suites, retaining both. State reconciliation retains main records and restores only this phase.

- `npm run typecheck`: passed.
- `npm run test -- --runInBand`: **5,639 passed, 286 suites passed**, 333.017 seconds.
- Standard full Python 3.11 backend attempt: interrupted after **5,958 passed, 7 skipped** in 618.93 seconds when an unchanged scan-endpoint test stalled in provider admission. No failures occurred. `--collect-only` identified 9,397 cases; the stalled test is index 5,965. First 5,955 cases are outside the endpoint module, followed by 48 endpoint cases and 3,394 later cases.
- Endpoint module: **48 passed** in 26.89 seconds with a temporary offline pytest plugin. The plugin supplies `historical_store.get_bars → []` and `scan.fetch_quotes → {}` before per-case patches, matching the existing `_no_db_leak` helper. This is a modified-harness result, not an unmodified full-suite pass. The original first ten endpoint passes overlap this rerun and are counted once.
- Remaining 3,394 cases: **3,392 passed, 2 skipped** in 290.32 seconds in the normal harness. Unique combined coverage: **9,388 passed, 9 skipped / 9,397 collected**, with the 48 endpoint cases qualified by the offline harness.

## Inherited provider-isolation limitation

Baseline: 6dd96dc67fd54b3d6099ff496551267345c2ff97
backend/tests/test_scan_endpoint.py: same_as_origin_main=True; sha256=297f7e1b4758d8f04e4acc5563f73b1c2dd731db14a81b98e632d8701c7e8cba
backend/app/data/governor.py: same_as_origin_main=True; sha256=9ff05b9b0d01315367d6bbdb2e1e63a0c6c77967db67cccc8089beb7bcb79cf4
backend/app/data/tiingo.py: same_as_origin_main=True; sha256=6f310fc19b1a9894651edc158f04b1e5e1bb3f421edbb693107420b1bac2a1d3
backend/app/services/historical_store.py: same_as_origin_main=True; sha256=0e0d52786cb3701027a827fbbc9ecd3eaf820e05a9f6790cce082c67b6393ffb
backend/app/routers/scan.py: same_as_origin_main=True; sha256=0979b6275d98f638076027fcf2015063fc7049f5a48e370d302773757ab19adb
Await-chain: get_bars -> _get_bars_locked:688 -> _fetch_chain:376 -> tiingo.fetch_historical_candles:78 -> governor.call:383 -> TokenBucket.acquire:107 -> asyncio.sleep
Tiingo rate=1/72s; capacity=2; three-symbol endpoint test lacks history prefetch isolation and waits on the third request. Existing endpoint _no_db_leak helper (lines215-225) already isolates both history get_bars and batch fetch_quotes in newer tests.
Temporary offline plugin: the temporary offline plugin supplies those two missing prefetch mocks for endpoint module, preserving later explicit per-case patches. Source/tests unchanged. This modified harness run must be disclosed separately from normal full-suite verification.

Temporary plugin source (not an application or repository test change):

```python
"""Temporary local test isolation for the inherited incomplete endpoint mocks."""
import pytest
from unittest.mock import AsyncMock
@pytest.fixture(autouse=True)
def inherited_endpoint_provider_isolation(request, monkeypatch):
    if request.node.path.name != 'test_scan_endpoint.py':
        return
    # Existing per-test mocks target these fallbacks. Skip unmocked prefetches
    # only; later explicit per-case patches still take precedence.
    monkeypatch.setattr('app.services.historical_store.get_bars', AsyncMock(return_value=[]))
    monkeypatch.setattr('app.routers.scan.fetch_quotes', lambda *_: {})
```

The complete unmodified CI suite remains a required shipping gate. The local qualified result cannot substitute for green CI.

## 2026-10-21 resumed integration

Merged current main `55519e05` at `d86e80d1`; only PROJECT_STATE.json conflicted. The new schedule-store corrupt-file recovery and Stock resolver filter/confidence changes are retained. Typecheck passed; five focused frontend suites passed **84 tests** in 9.762 seconds; cap/schedule/schema/recovery backend suites passed **81 tests** in 7.05 seconds under Python 3.11.16. No new product code was introduced by the reconciliation. Full prior-suite qualification remains unchanged; native exact-head CI is required before merge.

## Verified merge and post-merge checks

PR #454 verified MERGED at `a1811c0ee40c324fbd87291a0cad8e1d3a6fb202` on 2026-10-21. All three native CI checks passed on exact final head `c97955f07fd7873890f8760d92b4f466bd966e35`: backend/frontend [CI run](https://github.com/Netke237/trading-assistant/actions/runs/39542548072), browser [run](https://github.com/Netke237/trading-assistant/actions/runs/39542548030). This native full-suite result satisfies the shipping gate beyond the earlier qualified local run.

Actual merged source retested: typecheck passed; five frontend integration suites **84 passed** in 5.34 seconds; four backend cap/schedule/schema/recovery modules **81 passed** in 7.00 seconds (Python 3.11.16). The merge changed no application/test bytes from the checked head. Completion100%; Size M; Complexity4/5.
