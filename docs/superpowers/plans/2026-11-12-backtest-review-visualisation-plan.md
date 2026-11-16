# BACKTEST-REVIEW-VISUALISATION implementation plan

Date: 2026-11-12. Scope requested in chat: create implementation tickets from the permanent HTML preview; do not start building the application in this session.

## Goal and baseline

Make the candidate backtest understandable without explanation: what the strategy returned, how holding the underlying compared, how equity declined, and where actual trades occurred. Add the preview's presentation and inspection controls to the existing frozen-evidence view.

Application baseline: `236bec67`. Permanent design reference: `docs/superpowers/specs/2026-11-12-backtest-chart-preview/index.html`, committed in `25b08e61`; SHA256 `e43e34195f15580431e30c55b8ae51260df6d39fc135ab8f6569babdf45597c7`. Its fixture data, example trade reasons and toy renderer are NOT application implementation inputs. Current types and recorded artifacts are authoritative.

Existing source inspected: `frontend/types/backtest.ts`; `lib/useOriginalBacktest.ts`; `components/organisms/CandidateChartWorkspace/index.tsx`; `CandidateBacktestWorkspace/{index.tsx,chart.ts,chart.test.ts,index.test.tsx,CandidateBacktestWorkspace.module.css}`; `FreshBacktestControls/`; `frontend/e2e/tests/candidate-backtest.spec.ts`. Existing chart code renders frozen OHLC plus strategy/benchmark indices with range/crosshair synchronization, exact fill inspection, original/fresh separation and provenance. Backend changes are unnecessary for this scope.

## Invariants and numeric contract

1. Use only the selected `BacktestArtifact.detail`; no current scan settings, refreshed prices, preview fixtures or regenerated backtests. Preserve original versus fresh identity, same-symbol interval guards, loading/unavailable reasons, late-response isolation, open positions, exact timestamps, configuration and provenance.
2. Baseline is the engine's recorded 100. Return display is `index - 100`, NOT percent change from the first visible sample. This remains true after date zoom, selected trade zoom, filtering or hiding a curve. Never recalculate or rebase stored samples. Percentage-point difference = final strategy index minus final benchmark index, computed before formatting. No ratios labelled as percentage points.
3. Summary strategy return retains `detail.summary.total_return_pct` and its engine definition. Separately label the chart's indexed ending change if it differs; comparison sentence and benchmark difference use the two final indices on a shared recorded sample, with an explicit equity-return label. Do not silently compare a rounded summary return with an unrounded index or suppress a discrepancy. Empty/non-finite series show unavailable, never zero, infinity or fabricated endpoints. Valid zero and negative values render normally. Preserve full values for calculation and round only for display (normally two decimals).
4. Buy-and-hold is the recorded LONG benchmark, including for a Bearish strategy. Disclose gross/excludes fees versus strategy's recorded commission, recorded test dates, initial cash, sizing, margin/spread and the absence of currency. Do not invent dividend, reinvestment, cash-interest or allocation assumptions. Unknown facts stay unknown; do not offer currency conversion or dollar wealth examples.
5. Strategy equity includes open-position mark-to-market. Do not replace it with closed-trade cumulative P&L to copy TradingView. Closed-trade counts and win rate retain engine summary definitions; do not derive account return by adding trade returns. The recorded summary remains inspectable even if indexed curves are unavailable.
6. Optional drawdown panel is sampled-equity drawdown: `100 * (equity / runningPeak - 1)`, with running peak seeded from positive finite `detail.initial_equity` (engine initial cash basis), then advanced over the complete recorded equity sequence. Non-positive/non-finite starting equity or a non-finite equity sample yields unavailable for the derived drawdown series, not omission/bridging across invalid data. Zero/negative account equity is a legitimate loss value when the peak remains positive. Use the full history before slicing the visible range. Label this separately from `summary.max_drawdown_pct`, retaining that recorded engine metric unchanged.
7. All three panes synchronize by actual UTC timestamp/range, including absent timestamps, unequal series lengths, one sample, empty results, intra-day data and irregular sessions. No candle-to-equity array-index assumption. Crosshairs clear when no exact sample exists; no nearest-session substitution. No feedback loops; clean up subscriptions, markers, ResizeObservers and chart instances on artifact changes/unmount. Display-only controls do not execute a fresh run.
8. OHLC bars/candles use the same recorded OHLC/timestamps; line uses the same closes. No Heikin-Ashi or synthetic price transformations. Entry/exit markers retain actual fills and direction; unmatched candle timestamps remain disclosed in the inspector without snapping. Open positions get entries only, never invented exits.
9. Component-local display state only; no new persistence/store/backend/schema/API endpoints. CSS Modules, global tokens, existing Text/Data/Title primitives and component hierarchy apply. No inline styling system or CDN. Keyboard access and text/table equivalents remain available for chart interactions.

## Target presentation

Original/fresh run identity and period first; performance metrics and a clearly labelled strategy/holding comparison; larger resizable or expand/collapse performance chart with percent/index toggle, series legend/values and visibility controls; sampled-equity drawdown; price chart with Candles/OHLC bars/Line; linked paginated trade table and inspector; full provenance and calculation details in expandable supporting sections. Fresh-run configuration becomes a secondary disclosure without losing fields, validation, confirmation, cancellation or errors. All unavailable/zero-trade/open-position cases remain truthful and usable.

Summary wording must be deterministic, e.g. 'Recorded strategy equity returned X%; long buy-and-hold returned Y%; difference Z percentage points over the full recorded period.' Compare unrounded finite values, handle equal, positive, negative and missing results. Default chart axis is percentage; both visible curves share one scale. No dual scaling that falsely suggests matching returns. Hide either series to inspect its movements, with clear empty guidance when both are hidden. Legend defaults to final recorded values and shows both values/date on hover; unavailable samples remain unavailable.

All-history and trailing-year controls change only display bounds. Trailing year means a UTC calendar-year lookback from the final recorded timestamp, not a guessed 252 daily bars (artifacts may be intraday). Clamp available bounds, preserve original baseline and label full-period metrics. Trade selection may override the visible range temporarily; Clear returns to the last broad range. Keep price/equity separate because their units differ.

## Task 1 — presentation data and numerical contracts

Rating: size:M / complexity:4. Rationale: limited pure helpers but numerical units, drawdown, missing-data and timestamp semantics require precise regression coverage. Blockers: none.

Files: extend `CandidateBacktestWorkspace/chart.ts`, `chart.test.ts`; optionally introduce `presentation.ts`, `presentation.test.ts` in that folder if needed to keep helpers coherent. Do not change `types/backtest.ts` or backend contracts.

Test first: return/index and percentage-point transformations; full-history drawdown; initial-equity peak; negative/zero equity; non-finite/missing data; summary/index discrepancies; zero trades/open P&L; Bearish long benchmark; trailing UTC-year bounds with intraday/leap-year fixtures; timestamp lookup with unequal candle/equity lengths. Tests must pin numerical expectations, not helper implementation structure.

Implement pure read-only models for summary/chart values, formatting boundaries, timestamp/date bounds and table sorting/pagination. Preserve existing exported helpers/callers. No runtime use of synthetic reference data. Commit: `feat(backtest): define recorded performance presentation contracts`.

Done: targeted numeric regressions, typecheck and full frontend Jest pass; no recorded artifact mutation. Build ticket remains part of phase audit target, not independently audit-clean.

## Task 2 — performance summary, comparison and drawdown

Rating: size:M / complexity:3. Rationale: chart/legend lifecycle and accessible presentation across several controls, using Task 1's math. Blocker: Task 1.

Files: `CandidateBacktestWorkspace/index.tsx`, module CSS, `index.test.tsx`; new chart-lifecycle helper in this same folder if necessary; new summary/legend child components only within existing primitives → atoms → molecules → organisms conventions, each with its own folder/module CSS and tests where appropriate. Any added files must be listed in the closing report. `chart.ts` refinements only through agreed Task 1 contract, no math change without reporting plan defect.

Test first: truthful summary versus index difference, permanent labelled legend with final/hover values, percentage/index switching without rebasing, both-series hidden guidance, expanding performance view, full-period metrics retained after date changes; summary and sampled drawdown distinctly labelled. Introduce data fixtures where the first returned equity sample is below starting equity and where price/equity timestamps differ.

Implement performance-first layout, explanatory result, series visibility, shared axis, larger chart, full/year date controls, synchronized timestamp crosshair/ranges and sampled drawdown. Preserve original engine summary and disclosure details; no fake profit factor (not present in the current summary type). Theme and resize changes preserve view and selection; no duplicated chart callbacks. Existing tests keep their numeric assertions; update layout-dependent chart-instance assumptions to identify panes explicitly rather than weakening expectations. Commit: `feat(backtest): clarify performance comparison and drawdown`.

Done: numeric/component regressions, typecheck and full frontend Jest pass. Controls do not call run endpoints or mutate evidence.

## Task 3 — price display controls and linked trade inspection

Rating: size:M / complexity:4. Rationale: series replacement, marker ownership, precision and timestamp-linked selection interact with chart lifecycle. Blocker: Task 2 (same workspace files, must serialize).

Files: same workspace `index.tsx`, module CSS, `index.test.tsx`, lifecycle helper if introduced; trade table molecule/atom files using the repo's hierarchy. Only presentation helper extensions/tests needed for exact selection; preserve Task 1 numeric contract.

Test first: candle/bar/line modes all preserve identical recorded OHLC/close data; select trades by stable id after sorting/pagination; entry/exit values/direction/size/commission/net return remain exact; `time` and `unknown` exit reasons remain truthful (do not copy preview's invented targets/stops); open positions lack an exit; off-candle fills not snapped; selection zoom/clamp/clear; empty trades, partial page, unknown id; pointer and keyboard inspection parity; artifact switch clears stale selection.

Implement compact entry/exit markers with hover/click details, price type/visibility controls, readable sortable/paginated trades and retained detailed inspector. Use recorded `net_return_pct` (not preview's entry/exit formula; shorts and fees matter). Display normal formatted prices in rows, retain full recorded precision in inspector. Keep unknown exit reasons 'Unknown (not recorded by engine)'. Marker selection belongs to the active price series; detach/reattach on chart-type changes without leaks. Do not lose selections when changing theme, units or chart type. Commit: `feat(backtest): add price styles and linked trade review`.

Done: interaction/precision regressions, typecheck/full frontend Jest pass; original timestamps and identities preserved.

## Task 4 — original/fresh page integration and state coverage

Rating: size:S / complexity:3. Rationale: smaller shell change but artifact availability and fresh-run ownership must stay intact. Blocker: Task 3 (page interactions depend on finished workspace).

Files: `CandidateChartWorkspace/index.tsx` and its existing module/tests (or new module CSS/component test there); `FreshBacktestControls/index.tsx` and its existing tests/module CSS only as needed for secondary disclosure. `CandidateBacktestWorkspace` integration glue/test updates permitted; no changes to original-artifact hook, API or store contracts. Inspect existing fresh controls' internal open state before adding another disclosure so it does not accidentally reset configuration/cancel semantics.

Test first: original frozen report is the default; opening/closing configuration does not run or replace evidence; explicit confirmed fresh run only; original/fresh switching keeps identity, result-specific values and recorded intervals; late fresh result after candidate change cannot render on another candidate; cancel/error/loading/unavailable/expired/mismatched contexts preserve their existing meanings and live fallback. No-original state still offers explicit fresh configuration and a labelled live chart, never a fabricated original report. All original fields/provenance/open positions remain discoverable.

Implement page hierarchy with recorded run/period first, secondary fresh configuration, clear original/fresh result switching and preserved unavailable states. Existing standalone live chart and existing screener View Chart handoff remain unchanged. Commit: `feat(backtest): organize original and fresh report navigation`.

Done: original/fresh and legacy regressions, typecheck/full frontend Jest pass; no data fetching ownership or persistence changes.

## Task 5 — integrated verification, independent code audit and PR (coordinator)

Rating: size:M / complexity:4. Rationale: cross-mode artifact fixtures, numeric parity and late-response/browser checks across integrated presentation. Blockers: Tasks 1–4. Build phase remains incomplete until these pass.

Files: `frontend/e2e/tests/candidate-backtest.spec.ts` and additional adjacent presentation spec if needed; existing component/helper tests only to fill integrated acceptance gaps; retained evidence under `docs/superpowers/plans/backtest-review-visualisation/`; coordinator-only PROJECT_STATE entry and tracking updates. No production scope expansion while verifying.

Retain real server-shaped fixtures for Stocks daily/intraday, Bearish long benchmark, Pullback, Pre-Breakout and Fib where original artifacts are supported. Cover original and explicit fresh runs separately. Verify that unsupported/missing/expired/invalid artifacts disclose unavailable, not render substituted curves. Browser automation intercepts fixture API routes only; assert that display controls make zero scan/save/order/fresh-run calls. Real broker/data services must not be exercised.

Browser: light/dark, 1200/1366/1920px, responsive chart resize, keyboard trade inspection, all styles, legend hiding, percentage/index, year/all/selected bounds, crosshair readouts, schema-accurate trade precision/commission/direction, unknown exits, off-candle fills, zero-trade/open-position/empty/single-sample/late-response states. Compare series arrays and displayed summary against the immutable artifact before/after interactions. Preserve engine metrics, chart transformations and original/fresh ids. Capture representative screenshot evidence and a source-to-destination inventory of existing explanatory/provenance fields.

Run typecheck and full frontend Jest; focused numerical payload/consumer regressions; relevant Playwright checks. Backend/API production files remain byte-identical to baseline; backend CI still required where triggered. Python 3.11 verified before any backend test. Do not regenerate golden numeric pins. Run state.py. Record baseline failures with evidence rather than weakening assertions.

Fresh independent code audit under `.claude/skills/K-adversarial-audit-loop/SKILL.md`, target = integrated phase application diff against actual origin/main, including interactions with any merged main updates. Plan and code stages each capped at three qualifying fresh reviewers; continuous phase counter. Whole diff first, fixes/interactions only later. Block only wrong user/order numbers, corrupted persistence, or gate-qualified mechanism claims. Record reviewer, exact range, findings/fixes/outstanding and scope verification. No clean label from self-review or tests.

Commit: `test(backtest): verify integrated report presentation`. Open a PR only after the code gate is clean and required local acceptance passes, naming exact-head CI and applicable merge conditions. Do not merge without session authorization or all existing board self-merge conditions. Mark built/unmerged rather than shipped; post-merge checks and verified merge required for 100%.

## Tracking, delivery and progress

One phase `BACKTEST-REVIEW-VISUALISATION`, one tracking issue, four build sub-issues plus coordinator verification sub-issue. Native dependency chain T1 → T2 → T3 → T4 → T5; T5 also explicitly blocked by T1–T3. Only T1 initially ready. Sequential tasks reflect shared chart workspace files; this is not authorization for parallel writes.

Phase rating size:XL / complexity:4 (approximately 20–28 engineering hours for four frontend units, integrated checks and independent audits; split into reviewable build units, one integrated code audit). Each task has its own rating above. Scope deliberately excludes new statistical analytics, backend calculation changes, benchmark policy changes, strategy tuning, new persistence and TradingView embedding. No option-pricing or execution UI changes.

Implementation progress: 10% while this concrete plan awaits independent approval; 20% once its exact clean verdict is recorded. All tickets then inherit the approved plan milestone, not preview implementation credit. Code audit not started; overall audit_clean false until independent integrated code audit. Highest evidenced milestones follow `docs/agents/task-ratings.md`. Next milestone is 50% once all planned application implementation exists, not merely ticket publication. Publish ratings and completion with evidence on parent and children.

This session ends after clean plan audit, GitHub ticket creation/linking/labels/readback and committed/pushed plan/state. Do not execute the build loop: the user requested tickets only. No board priority/body edits. On later resume, acquire this phase claim on the recorded branch before building; inspect live main/claims and current source first, and report material drift as a plan defect.
