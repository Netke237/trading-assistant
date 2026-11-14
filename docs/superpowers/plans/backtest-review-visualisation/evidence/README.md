# T5 integrated verification evidence (#636)

Verification of the integrated T1–T4 build (`690b034b`, `1d168cb8`, `454dd82b`, `82e7275b`) on branch `codex/backtest-review-99b03167`, 2026-11-14, Windows host, Node/Next dev server on port 3017 (not 3001), Chromium via Playwright 1.62.1. This is test evidence, not an independent audit; the phase code audit is still required.

## Commands and results

| Command (from `frontend/`) | Result |
| --- | --- |
| `BACKTEST_BROWSER_FIXTURES=<repo>/docs/superpowers/plans/backtest-review-visualisation/fixtures/recorded-engine.json npx playwright test -c <temporary config: baseURL http://localhost:3017, no webServer> e2e/tests/candidate-backtest-presentation.spec.ts e2e/tests/candidate-backtest.spec.ts` | 25 passed (23 ok + 2 expected failures for the known defect below), 3.7 min. The six matrix tests were re-run after adding the time-basis/evaluation/commission assertions: 6 passed. |
| same, with `BACKTEST_EVIDENCE_DIR=<this folder>` | wrote the screenshots below |
| `npx jest components/organisms/CandidateBacktestWorkspace components/organisms/CandidateChartWorkspace components/organisms/FreshBacktestControls components/molecules/BacktestTradeTable lib/__tests__/useOriginalBacktest` | 9/9 suites, 109/109 tests passed |
| `npm run typecheck` | clean |
| `npx jest --silent` (full) | 349/354 suites, 6496/6507 tests passed. The 5 failing suites are the known host baseline, green in CI: BarrierRaceCard, StockSendDialog.session and StockPositionCard.referenceFlow (en-DE locale, e.g. `$4.470` vs `4,470`), and step-7-trade-card `edited-fields-sync` / `submission-review` (5000 ms timeouts under full-suite load; re-run alone with `--testTimeout=30000`: 2/2 suites, 40/40 tests passed). None imports a changed file. |
| `git diff --stat origin/main..HEAD -- backend frontend/lib/api.ts frontend/types frontend/lib/useOriginalBacktest.ts` (origin/main `e8eca1b6`) | empty: backend/API/types/hook byte-identical |

Browser isolation: every `/api/*` request not answered by a fixture route is aborted, and the live `/chart/stream/*` websocket is closed in the browser, so no real broker or data service is reached. Display controls were asserted to make zero non-GET `/api` calls and exactly one artifact read; the only write in any test is the explicit `POST /api/backtest-artifacts/fresh` of the fresh-run tests.

What the presentation spec checks (all expected numbers are read from the served artifact, never hardcoded): summary cards and the parsed *Recorded summary / configuration / effective parameters / identity* JSON equal the artifact before and after every interaction, and the served artifact object stays deep-equal to a pristine copy; Return % legend/crosshair = recorded index − 100 and Index 100 = recorded index at exact recorded timestamps; Last year / All history captions; Expand/Reduce; hiding each and both series (guidance); Candles / OHLC bars / Line without extra chart instances; Trade markers (pixel round trip); keyboard Inspect zooms all three panes (pixels differ) and Escape restores each pane pixel-identically and returns focus; Clear selection; sort + pagination keep the selected trade; zero-trade, open-position and off-candle states; every unavailable reason (10 route statuses across stocks/prebreakout/pullback/fib, HTTP 404/410/503/422/500, three invalid-evidence shapes) with no report pane, summary or inspector; widths 1280/1366/1920 in dark and light with no horizontal scroll; `/chart` at 1200px shows the *Desktop required* overlay (gate 1280px), so 1200px is not claimed as a usable chart width.

Fixture coverage limit: the recorded-engine fixture holds Stocks `pullback_ema` artifacts only (daily and 15-minute, Bullish and Bearish, fresh, zero-trade). No Pre-Breakout or Fib original artifact fixture exists; those sources are verified only on their unavailable routes. Pagination/open-position/off-candle browser checks use a display-only derived copy of the Bullish-1d artifact, built inside the spec and labelled there; it is not engine output. Late-response isolation is covered by Jest only.

## Known defect found (not fixed; reported to the coordinator)

After the chart containers widen — a first load at 1920px, or resizing 1366 → 1920 — the panes keep their previous bar spacing, so with *All history* still pressed the left part of a pane stays blank until a range button is pressed again (visible in `report-default-1920-light.png`). Reproduction: the two `KNOWN DEFECT` tests in `candidate-backtest-presentation.spec.ts` (marked `test.fail()`; they compare each pane before and after Last year → All history). Data and numbers are unaffected.

## Screenshots

| File | Shows |
| --- | --- |
| `report-default-1366-dark.png`, `report-default-1920-light.png` | Default original report (header, run line, summary cards, comparison, legend) |
| `index100-1366-dark.png`, `index100-1920-light.png` | Index 100 display with legend values and axis title |
| `line-inspected-1366-dark.png`, `line-inspected-1920-light.png` | Line style with an inspected trade (zoomed panes, selection bar) |
| `fresh-shown-1366-light.png`, `fresh-shown-1920-dark.png` | Fresh result shown separately, Index 100 + Line + inspected trade |
| `unavailable-expired-1366-dark.png`, `unavailable-unsupported-1920-light.png` | Unavailable original with labelled live fallback, no substituted curves |
| `min-width-gate-1200-dark.png` | `/chart` at 1200px: Desktop required overlay (1280px gate) |
