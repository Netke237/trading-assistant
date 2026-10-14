# Pre-Breakout presentation V2 validation

Baseline: main `3b144eed7503ef655da36c5bae3cb538fb78abec`. Implementation is not complete and no code audit has run.

- Initial state check: exit 0, no drift; three inherited unrelated warnings (STATE-PROBE-REVIVAL, STATE-PROBE-NULL-POINTER, STATE-PROBE-TARGET-SCOPING).
- Initial frontend baseline: 241 suites / 5,158 tests passed; `npm run test -- --maxWorkers=2 --silent`, 129.792 seconds. Typecheck passed.
- Backend runtime prepared separately: Python 3.11.16, requirements installed; host default Python 3.12 is not used for backend checks. Full initial run: 7,962 passed / nine skipped / one environment-only notification test failure in 868.17 seconds.
- Browser verification will use installed system Chromium. Playwright's download host is denied by current network policy; system Chromium is available without that download.
- #258 reconciliation: `c6b140ff`, documentation-only, typecheck passed; coordinator-reviewed crosswalk records current source and prior PR #224 provenance. No prior PR merge/closure or application port performed by this ticket.
- Frozen source plan round 1 and separate revised-layout round 1 evidence preserved in phase registration. Current-source/diagnostics/live-context independent plan round2 /root/pb_plan_r2 clean on exact head753065bf; second pass and scope verified.

Ticket RED/GREEN evidence, integrated preservation/browser/build checks and independent code-audit scope will be appended as work completes.

- #259 `a35da6c7`: initial RED3 expected shell/invalidation/7.25% formatting failures; focused3 suites12 tests and full243 suites5169 tests passed, typecheck clean. Added further regressions after initial implementation recorded candidly. WeakMap snapshot follows actual stored array identity, remounts, unknown replacement arrays, applied integer truncation/Fib1.55%, scope races and prior rows on error. Durable API report generation untouched; ephemeral table ID assigned only with accepted current response.

- Initial backend failure: test_notifications.py::TestTelegram::test_telegram_skips_when_not_configured inherits configured session Telegram variables through its empty-argument fallback. All6 notification tests pass with only those variables removed from the test command environment; no source/test changes. Subsequent full backend commands use the same scoped isolation. Diagnostic single Options scan test passed in79.42s; no backend failure attributed to Pre-Breakout.
- #260 `1b840255`: four initial expected RED missing evidence/identity/percent/Pullback chart failures; focused4 suites18 tests/full244 suites5175 tests/typecheck pass. Complete raw setup/legacy/conditional evidence preserved, dynamic returned confidence weights, zero/missing values, Fib percentage once and applied1.55% tolerance. Actual mode orders preserved.

- #261 `b8379697`: all-mode clicked Bearish row/ambient Bullish RED plus missing chart/race/error and price-line/Fib helper evidence; focused3 suites19 tests/full247 suites5194 tests/typecheck pass. Daily chart and existing indicators, exact finite known Fib/swing levels, stale candle guards, local errors, cleanup before disposal, clicked-row symbol/direction and keyboard preservation. Usage interruption resolved on14 October with same implementer; no review counter reset.

- #262 `ea923796`: source19 initial RED; source focused67 and full backend7982 passed/9 skipped (847.77s, Python3.11.16, scoped notification env isolation and native math threads1). UI6 initial RED; finalfocused20/full248 suites5214 tests/typecheck pass after browser verification found double Bearish alignment. Backend regime_omm conviction already aligns to request direction; two RED regressions reproduced positive/negative Bearish reversal, fixed by preserving returned conviction unchanged. This was pre-commit verification, not a qualifying code audit; code stage remains0.
- Interim browser preview: installed Chromium, actual1280 Step4 minimum, Bearish selected Pre row; official cached Google Fonts used locally because font host unavailable. No horizontal document overflow (1280/1280), page errors0. Original/live context and amended panel order inspected. All writes mocked, no real orders/arms/saves. Final all-mode/theme/width checks remain #266; temporary3002 server stopped.
