# STOCK-PRES-P3-BACKTEST — Backtest page (Stocks Step 5 of 6) in the Options layout

Phase id: `STOCK-PRES-P3-BACKTEST` · Board item / tracking issue: **#148** · Programme: #144
Branch: `board/stock-pres-p3-backtest-88bae253` (cut from `origin/main` `472bb1b0`)
Design: `docs/superpowers/specs/2026-10-10-stock-presentation/` (`preview.html` → Backtest view, README D1–D14)
Decision: `STOCK-PRESENTATION-2026-10-10`

## Why

The Stocks Backtest page still lays its 17 columns out as a plain table. Kenneth approved proposal 02: the same page in the Options layout, every current item kept, plus only the approved new items. This phase is presentation only.

## The gate (audit_rule)

A finding blocks only if it can put a **wrong number in front of a user or on a broker order**, or **corrupt persisted data**. A comment blocks only if it misstates mechanism.

## Scope

**Files this phase may change (nothing else):**

- `frontend/app/(frame)/screener/step-6-backtest/page.tsx`
- `frontend/app/(frame)/screener/step-6-backtest/page.module.css`
- new tests under `frontend/app/(frame)/screener/step-6-backtest/__tests__/`
- this plan and `docs/superpowers/PROJECT_STATE.json` (coordinator only)

**Out:** backend, `frontend/types/`, `StockPositionCard` and `PositionEvidence`, `scanStore`, `scanParamsStore`, `statusTooltips.ts`, `api.ts`, the saved-scan inspector, persistence (no store version bump, no new persisted key). No gate, threshold, filter, or sort-of-record change. Existing tests in this folder stay green. They stay unedited except the three health-sort clicks in `union.test.tsx`, which follow the moved button (Task 2).

## Mechanism today (verified on `472bb1b0`)

`step-6-backtest/page.tsx` renders, top to bottom:

- Header: `STEP 5 OF 6`, title `Backtest Results`, one count sentence `{filtered count} candidates · {gate-rejected count}` plus ` · {over-cap count} over cap` only when that count is above 0, then the Unvalidated banner (byte-for-byte the caution text in the file), then `Last stock scan: {label}` after mount.
- Scan error (`tone="reject"`) and notice (`tone="caution"`), then `DirectSendNotesPanel`.
- Empty copy when there is no result, and when a result has no rows left after the event filter.
- `Filter Breakdown` button. With a result its label is `Filter Breakdown ({notRanked} Not Ranked)`; without one it is `Filter Breakdown · saved report`. It opens `SavedScanReportInspector` (`category="stocks"`, `tableRunId={result?.report_run_id}`, `isDrawer`).
- Direction banner, only when `result.direction_banner` is set.
- Hidden-row sentence, only when the event filter removed rows: `{n} of {candidates.length} hidden by the event filter.`
- The 17-column grid. Headers are an unlabeled star column, then `SYMBOL SUMMARY SCORE STATUS Δ WIN % TRADES RETURN MAX DD`, a Health sort button, then `VS SPX EVENT CONF GATE DETAILS POSITION`.
- Each row: `WatchStar`, symbol plus the in-portfolio dot, the summary text before the first `·`, `stock_score` with title `Score is a filter, not evidence of profitable edge`, `StatusBadge` of `stock_status`, the delta cell, win % as `(win_rate * 100).toFixed(0)` with the existing tone and tooltip, the trades cell (`data-testid={`trades-${symbol}`}`) including the time-exit subline, return `toFixed(1)`, max drawdown `Math.abs(...).toFixed(1)` in reject tone, health score or `—`, sector RS, event, `ConfidenceBadge` of **card** `confidence` (not `backtest.confidence`), gate badge `PASS` or `REJECT` from `backtest.passes_gate` only, Expand/Collapse, Open Position.
- Expand sets `openSymbol` and renders `StockPositionCard` with `key={stockPositionCardKey(c)}`, `card`, `strategyKey={scannedRequestStrategy ?? c.strategy.strategy}`, `afterScanArmed`, `onAfterScanToggle`. `scannedRequestStrategy` is `request?.strategy` (a missing request stays undefined; it must not be read as `request.strategy`). Collapse unmounts it.
- `Send basket (n)` when `stockBasket.length > 0`, opening `StockSendDialog`.
- Open Position calls `setSelectedSymbol` then `router.push('/screener/step-7-position-card')`.

Counts come from the existing `splitStockRejected(result?.rejected)`: `gateRejected` is every rejected row whose reason does **not** start with the shortlist-cap prefix; `overCap` is the rest. The header uses those two lengths, not `rejected.length`.

The event filter is unchanged: `avoid` hides rows with `next_event_days <= 7` (null days stay); `only_pre_event` keeps rows with `next_event_days != null && <= 21`; any other value, including `include`, keeps every candidate. The Strategy panel's labels for those three values are `Include`, `Avoid`, and `Events only`.

Health sort is local React state, not persisted. `null → desc → asc → null`. Missing `fundamentals.score` sorts as `-1`. Sort off returns 0, so scan order stays. Only Health sorts today.

The gate rule, stated in `stockScanGateTooltip` / `backtestGateTooltip` and mirrored from `strategy_backtest.py`, is `win_rate >= min_win_rate AND n_trades >= min_trades AND expectancy >= 0`. The expectancy floor is 0. It is not a field on the scan request. When either `bt_min_trades` or `bt_min_win_rate` is null, the win % cell and the gate badge already say `Threshold provenance unavailable for this scan` and show no numeric threshold.

Time exits (D14, merged `ea9c67ce`, pinned by `timeExits.test.tsx`): `n_time_exits == null` or the field absent → `—` and no hold label; a number with `hold_max_days == null` → `no hold`; otherwise `{n} of {trades} on time (hold {days}d)` with the existing tooltip. Never show a stored unknown as `0`.

`union.test.tsx` pins all of the following and must stay green. The only edit is the three health-sort clicks in Task 2: the column labels it lists (it does not list `HEALTH`), Expand opening the full card without navigating, Open Position navigating, the hidden-count sentence exactly once, the string `Pipeline log` **absent**, and rejection reasons readable only inside the Filter Breakdown dialog.

Score factors already arrive as `card.stock_explanation` (P1, optional). `PositionEvidence` on the full card already prints each component's `name` and, when `measured`, `raw_score` to 0 decimals, else `Unavailable`. Absent explanation → `Scorer factors unavailable`. `explanation.status` is the scorer's verdict **before** later caps. The verdict on this page is `stock_status`. Sharpe is `backtest.sharpe` (already on the card, not in the table). The earnings sentence `Earnings inside the reject window — no send` is `EARNINGS_VETO_MESSAGE`. The expanded card does not read `earnings_veto` by itself. `StockPositionCard` sets `earningsVeto` from `stockEarningsGate(card, stockScanResult.timestamp, stockScanResult.veto_days).veto` (`frontend/lib/earningsGate.ts`). That helper ages `earnings_days` by whole calendar days since the scan and judges the result against `veto_days`. A stored `earnings_veto: false` can become a veto on a later day, and a stored `true` stops being a veto once the aged distance drops below zero. (Plan round 1 finding P3-A1.)

The 17-column grid is `20px 70px minmax(120px, 1fr) repeat(12, minmax(55px, auto)) 65px 105px` with `min-width: 1320px` and `.results { overflow-x: auto }`. Keeping every column means that horizontal scroll stays. The item forbids removing or merging columns, so this phase does not restack the table to kill the scroll.

## What this phase does not put back

The 2026-10-10 mockup still draws a "Pipeline log" disclosure and inline rejected / over-cap lists. On current main those explanations live in the Filter Breakdown inspector. `union.test.tsx` fails if the words `Pipeline log` are on the page. This phase keeps the inspector and does not add those lists or that disclosure.

## Target layout

```
Header: STEP 5 OF 6, title, the existing count sentence, Unvalidated banner
        Send basket (n)   ← moved here, same condition and dialog
How this page works       ← new, collapsed (Task 3)
Summary strip             ← new, existing numbers only (Task 1)
error / notice, DirectSendNotesPanel, empty states
Filter Breakdown button   ← unchanged
direction banner, hidden-count sentence
Candidates:
  Sort: Health | Score | Confidence     ← Health kept, Score and Confidence new (Task 2)
  the same 17-column table
  Expand → quick summary, then the same full StockPositionCard (Task 3)
inspector
```

Cards and the strip use existing tokens only: `border: 1px solid var(--border-subtle)`, `background: var(--bg-surface)`, no new hex colors, no shadow.

## Acceptance — this phase's slice (nothing removed)

| # | Item today | Where it goes | Kind |
|---|---|---|---|
| B1 | Header: STEP 5 OF 6, Backtest Results, count sentence, Unvalidated banner | Page head, same text | EXISTING |
| B2 | Last stock scan label, after mount only | Summary strip, same text, still after mount only | MOVED |
| B3 | 17 columns, tones, tooltips, star, in-portfolio dot, time-exit subline | Same grid, same cells | EXISTING |
| B4 | Health sort, three-state, missing score as -1 | Sort row. Column header becomes the plain text `HEALTH` | EXISTING |
| B5 | Expand → full `StockPositionCard` with the same props; Collapse removes it | Under the quick summary | EXISTING |
| B6 | Open Position → selected symbol + Step 6 route | Same button, same handler | EXISTING |
| B7 | Send basket + dialog | Page head, same condition | MOVED |
| B8 | Error, notice, direct-send notes, direction banner, both empty states, hidden-count sentence | Same text, same conditions | EXISTING |
| B9 | Filter Breakdown + inspector. No `Pipeline log`. No inline rejected list | Unchanged | EXISTING |
| B10 | — | Summary strip of the counts, the gate this scan used, the event-filter label, the hidden count, the last-scan label | NEW |
| B11 | — | Score sort and Confidence sort. One sort at a time | NEW |
| B12 | — | Quick summary above the full card | NEW |
| B13 | — | How this page works | NEW |

Plus: `timeExits.test.tsx` green with no edits; `union.test.tsx` green, with only the three health-sort clicks moved to the new button; typecheck + full Jest green; plan audit and code audit clean.

## Tasks (test-first; one ticket each; T1 → T2 → T3, serial — all three edit `page.tsx`)

Each new test file mocks `next/navigation`, `StockPositionCard`, `StockSendDialog`, `DirectSendNotesPanel`, `WatchStar`, and `SavedScanReportInspector` the way `timeExits.test.tsx` mocks organisms. Do not mock `StatusBadge` or `ConfidenceBadge`.

### Task 1 — summary strip of numbers the page already shows

**Files:** `page.tsx`, `page.module.css`, new `__tests__/presentationStrip.test.tsx`.

**Change:**

1. Add a strip under the header. Each item is a label plus the value below. Labels: `Candidates`, `Rejected`, `Over cap`, `Gate this scan used`, `Event filter`, `Hidden`, `Last stock scan`.
2. Values, and no others:
   - Candidates = `filteredCandidates.length` (the same integer as the header sentence, not the unfiltered length).
   - Rejected = `gateRejected.length`.
   - Over cap = `overCap.length`, including 0. The header sentence still omits the over-cap clause when it is 0. The strip always shows the integer.
   - Gate: when both `request.bt_min_trades` and `request.bt_min_win_rate` are numbers (0 is a real number), the text is `win ≥{pct}% · trades ≥{minTrades} · expectancy ≥ 0`, where `pct` is `(bt_min_win_rate * 100).toFixed(0)` and `minTrades` is the stored number. When either is null or undefined, the text is exactly `Threshold provenance unavailable for this scan` and the `win ≥` form is absent. Do not read any other request field. The expectancy floor is the existing gate's 0.
   - Event filter: `include` → `Include`, `avoid` → `Avoid`, `only_pre_event` → `Events only`. Any other stored value is shown unchanged.
   - Hidden = `candidates.length - filteredCandidates.length` (0 when nothing is hidden). This is a separate `Hidden {n}` value. Do not repeat the sentence `{n} of {candidates.length} hidden by the event filter.` The existing sentence stays exactly once, under the same condition as today.
   - Last stock scan: move the existing header line here. Same `_labelWithDate`, same `stockScanAt && mounted` guard, same text `Last stock scan: {label}`. It is not also left in the header.
3. Move `Send basket (n)` into the header. Same condition, same label, same dialog.
4. Do not change the count sentence, the Unvalidated banner, the Filter Breakdown label, or the column grid.

**Tests first (must fail before the change, because the strip is absent):**

Mock `next/navigation`, `StockPositionCard`, `StockSendDialog`, `DirectSendNotesPanel`, `WatchStar`, and `SavedScanReportInspector` the way `timeExits.test.tsx` mocks the organisms. Do not mock `StatusBadge`.

- A result with 2 candidates, one ordinary rejection, and one shortlist-cap rejection shows Candidates `2`, Rejected `1`, Over cap `1`. The header sentence still contains `2 candidates · 1 rejected · 1 over cap`.
- `bt_min_trades: 8`, `bt_min_win_rate: 0.45` shows `win ≥45% · trades ≥8 · expectancy ≥ 0`.
- `stockScanRequest: null` shows `Threshold provenance unavailable for this scan` inside the strip and does not show `win ≥`.
- `eventFilter: 'avoid'` shows `Avoid`. `only_pre_event` shows `Events only`. A candidate hidden by `avoid` shows `Hidden 1` and the existing sentence `1 of 2 hidden by the event filter.` exactly once.
- `stockScanAt` set and the mount effect flushed shows one `Last stock scan:` line, not two.
- `stockBasket` of length 2 shows one `Send basket (2)` button.

**Commit:** `feat(backtest): show the existing scan counts in a summary strip`

### Task 2 — Score and Confidence sorts, Health sort kept

**Files:** `page.tsx`, new `__tests__/presentationSort.test.tsx`.

**Change:**

One sort is active. State starts off (today's scan order).

Three buttons, in a row above the column headers:

- accessible name `Sort by fundamental health score` (the title the Health header has today)
- `Sort by score`
- `Sort by confidence`

The `HEALTH` column header becomes plain text `HEALTH`, not a second button. `SCORE` and `CONF` stay plain text, exactly those strings, so `union.test.tsx`'s `getByText` still matches.

`union.test.tsx` also has `cycles health sorting descending, ascending, then original order`. That test clicks a button named `/HEALTH/`. The plan's earlier line that this file does not mention HEALTH was wrong about that test. It still does not use `getByText('HEALTH')`. Change only those three clicks to the button named `Sort by fundamental health score`. Leave the three order assertions as they are. No other line in that file changes.

Click a sort that is off: it becomes the only active sort, direction descending. Click the active sort: descending → ascending → off. Off means the comparator returns 0.

Values:

- Health: `fundamentals?.score ?? -1` (unchanged).
- Score: `stock_score`. Do not round it for the sort.
- Confidence: card `confidence`, with `null` and `undefined` as `-1`. `0` stays `0`. Never `backtest.confidence`.

Ties return 0. Do not break ties by symbol. The active button shows `↓` or `↑`. An inactive button shows `↕`.

**Tests first (must fail before the change):**

Three candidates in scan order, scores 10, 30, 20. Render order of their symbols is that order. One click on `Sort by score` shows 30 then 20 then 10. A second click shows 10 then 20 then 30. A third click restores 10, 30, 20.

Confidence values 10, `null`, 40. One click on `Sort by confidence` orders 40, 10, then the null (null is `-1`, so it is last when descending). A following click on `Sort by score` leaves confidence off: the null is not stuck at the end unless the score sort puts it there.

Health: missing `fundamentals` sorts as below a score of 0 when descending (the missing row is last). Turning Health on clears a previous Score direction.

**Commit:** `feat(backtest): sort candidates by score or confidence`

### Task 3 — How this page works, and the quick summary above the full card

**Files:** `page.tsx`, `page.module.css`, new `__tests__/presentationSummary.test.tsx`.

**Change:**

1. Under the header, a collapsed `<details className={styles.pageExplanation}>`. Summary text `How this page works`. Body, this sentence only: `One row per candidate. Expand a row for a short summary and the full position card. Open Position to review on Step 6.` Copy the four `.pageExplanation` rules from `step-4-stocks/page.module.css` into this page's CSS. Do not import that file.
2. When a row is open, render a `<section aria-label={`Quick summary ${symbol}`}>` **after** the 17-cell row and **before** `StockPositionCard`. It is not a cell in the 17-column grid. Collapse removes the section and the card together.

The section has three groups.

**Why this score.** Show `stock_score` with the same string the SCORE cell uses (`{c.stock_score}`, no extra rounding). If `stock_explanation` is null or absent, the text `Scorer factors unavailable` and no factor rows. Otherwise one row per `Object.entries(stock_explanation.components)` in that order: the component `name`, and `raw_score.toFixed(0)` only when `measured` is true and `raw_score` is finite; otherwise `Unavailable`. Do not print `explanation.status`, weights, or contributions. Do not recompute `stock_score`.

**Backtest vs this scan's gate.** Label and value, values copied from the row, not recomputed:

| Label | Value |
|---|---|
| Win rate | `(win_rate * 100).toFixed(0)` + `%` |
| Trades | `n_trades`, the integer only. Not the time-exit subline |
| Expectancy | `expectancy.toFixed(2)`, sign kept |
| Return | `total_return_pct.toFixed(1)` + `%`, sign kept. Do not take `Math.abs` |
| Max DD | `Math.abs(max_drawdown_pct).toFixed(1)` + `%` |
| Sharpe | finite `sharpe.toFixed(2)`, otherwise `Unavailable`. No pass/fail tone |

Threshold line under those values: when both mins are numbers, `Scan thresholds: ≥ {minTrades} trades · ≥ {pct}% win rate · expectancy ≥ 0` with `pct` from `(bt_min_win_rate * 100).toFixed(0)`. Otherwise exactly `Threshold provenance unavailable for this scan`.

**Flags.**

- `Backtest gate PASS` or `Backtest gate REJECT` from `passes_gate` only. A stored `false` stays REJECT even when win rate, trades, and expectancy would pass the numeric rule.
- The sentence `Earnings inside the reject window — no send` only when `stockEarningsGate(c, result?.timestamp, result?.veto_days).veto` is true. Call that existing helper with those three arguments, the same call the card makes. Do not pass a custom `now`. Do not reimplement the ageing math. Do not key the sentence off `earnings_veto` alone, and do not edit `frontend/lib/earningsGate.ts`. When the helper's `veto` is false, the sentence is absent.
- `Fundamentals {score}` when `fundamentals.score` is a finite number, using the score as stored (the same number as the HEALTH cell). Otherwise `Fundamentals unavailable`.
- Each `gate_flags` entry, in order: `{gate}: {status} · {detail}`. Missing or empty array: `Recorded gates unavailable`. Do not invent a flag.

`StockPositionCard` props stay the ones listed under Mechanism. Do not pass new props.

**Tests first (must fail before the change):**

- Before any click, `How this page works` is on the page and `Quick summary AAPL` is not. The details element is not open.
- Expand AAPL: the section exists, and `Full shared card` (the mocked card) is still present. In the section's parent, the summary section comes before the card.
- Collapse removes both the section and the card.
- Explanation components `[{ name: 'Trend', measured: true, raw_score: 85.4 }, { name: 'Event', measured: false, raw_score: 80 }]` show `Trend` with `85` and `Event` with `Unavailable`, not `80`.
- No `stock_explanation`: `Scorer factors unavailable`.
- `win_rate: 0.584` shows `58%`. `total_return_pct: -1.84` shows `-1.8%`. `max_drawdown_pct: -6.14` shows `6.1%`. `sharpe: 1.1` shows `1.10`. `expectancy: -0.2` shows `-0.20`.
- `passes_gate: false` with win rate 0.9, 100 trades, expectancy 1 shows `Backtest gate REJECT`.
- Freeze the clock at `new Date(2026, 9, 8, 10, 0, 0)` and set the result `timestamp` to `2026-10-05T14:30:00` and `veto_days` to 60. `earnings_days: 61` with `earnings_veto: false` shows the veto sentence (the stored flag is false; the aged distance is inside the window). `earnings_days: 2` with `earnings_veto: true` does not show it (the print aged below zero). Restore the real clock after the test. These are the two cases in `frontend/lib/__tests__/earningsGate.test.ts` under `stockEarningsGate`.
- One gate flag `{ gate: 'liquidity', status: 'CAUTION', detail: 'wide spread' }` shows `liquidity: CAUTION · wide spread`.
- `bt_min_trades` and `bt_min_win_rate` null: the section contains `Threshold provenance unavailable for this scan` and not `Scan thresholds:`.

The time-exit lines in the trades cell are still asserted by the unedited `timeExits.test.tsx`. This task does not duplicate them into the summary.

**Commit:** `feat(backtest): add a quick summary above the full card`

## Checks before the phase is called built

- `cd frontend && npm run typecheck`
- `cd frontend && npm run test`
- No backend run: the diff has no backend file.
- `python scripts/state.py` exits 0. Drift that is only this phase's own not-yet-built probe is fixed by the status field, not by weakening the probe.
- Mapping rows B1–B13 ticked in a comment on #148.
- `git merge origin/main` immediately before code-audit round 1, then the checks again.

## Needs Kenneth

Visual check of the finished page against `preview.html`'s Backtest view, if this session has no browser. That check does not block the PR. It is named in the `waiting-merge` / PR note.
