# Stocks and Pre-Breakout information-flow proposal

Source baseline: `0a453f1940a077015949e760d02ef5a6d921f62a`, checked in `/workspace/trade-card-current-preview`. This is a design proposal for review. No application code, calculations, screening rules, persistence or broker behaviour changes are authorized by this document.

## What changed in Options

The work reorganized the Options Step 7 Trade Card. It retained existing scan/model calculations and execution rules.

- Market Sentiment followed by Fundamental Health; prominent stock and contract identity; raw Contract Details; Stock Qualification then Contract Qualification directly beneath, both default closed with existing preferences retained.
- One compact editable Exit Plan. Existing stop, premium-loss/remaining-value information and time-exit threshold stay visible; full explanations, ATR/structure evidence and Check structure remain accessible in closed disclosures.
- Consistent Monte Carlo, Arithmetic and Ladder presentation, essential target/probability/time/outcome values, aligned comparison of two or three methods, on-demand calculations retained. Displaying/comparing a method is separate from selecting a method/target for the trade.
- Method-specific details and full explanations retained in expandable sections. The Options graphical Barrier Race is nested under Monte Carlo.
- Clear entry/quantity inputs, one selected-target review, grouped decisions/actions and concise basket/broker reviews tied to existing submission values and safeguards.
- No new financial model; no automatic adoption of calculated stops into editable execution fields. Complete explanatory-text preservation was independently checked. The last amendment moved Contract Qualification from the bottom to beneath Stock Qualification, without changing its contents.

## Shared design rules

1. Front: information needed for the immediate decision, existing editable fields, source/units, material differences, blocking notices and action outcomes.
2. Expandable: full explanatory text, component scores, model assumptions, structural evidence, provenance and raw records. Short summaries never replace the complete original text.
3. Preserve semantic colours, badges, tooltips, links, actions, input handlers and saved preferences. Keep disabled/blocked reasons readable alongside their actions.
4. Opening a disclosure, changing the viewed method or comparing results must not trigger a new calculation or silently change the selected decision or execution fields.
5. Reuse existing data and display calculations only. No new probability, target, stop, return, time estimate, chart line, broker capability or data fetch. Do not substitute a value from another model/source when information is unavailable.
6. Keep source distinctions visible: scan versus live context; original strategy versus edited order; calculation stop versus execution stop; suggested versus entered shares. Keep probability horizon and day basis visible with statistical values.

## Stocks: proposed order

Scope: the full Position Card (`presentation="position"`) on the terminal Stocks page. Preserve the default embedded card used by Step 6 Backtest; review its shared-component compatibility explicitly.

| Order | Visible by default | Expandable content / preserved destination |
| --- | --- | --- |
| 1. Context | Existing sentiment, then Fundamental Health; current execution/research restriction remains prominent near actions as well | Full context explanations, fundamental component/safety details; retain the existing data source |
| 2. Identity | Symbol, company, direction, strategy, status/confidence badges, current versus scan price, recorded horizon; View Chart, Pin/Unpin and candidate navigation | Existing provenance detail where lengthy; keep current/scan distinctions readable |
| 3. Qualification | Closed Stock Qualification and Backtest Evidence rows, with their existing summaries where appropriate | Complete stock score factors, weights/contributions, observations, capped/final verdicts; win rate, sample count, expectancy, return, drawdown, Sharpe, confidence text and recorded scan thresholds |
| 4. Execution stop and risk | Existing editable execution stop, risk/share and loss for entered shares, with source/basis; invalid-stop warning remains visible | Structure & Stops: structural candidate/source/confidence/distance, ATR/floor, returned Arithmetic stop, Check structure and all justification text. A differing calculated stop remains explicitly identified in the method result and decision area |
| 5. Method results | Consistent Ladder / Arithmetic / Monte Carlo viewing and comparison pattern; each method's existing target, stock price, available probability/window, conditional time and full-position outcome for entered shares. Stop basis remains clear | Full equations, source assumptions, target-quality comparisons, reward/share, sizing arithmetic, stop statistics and complete method caveats. Detailed assumptions can fold; material fit warnings remain visible |
| 6. Entry and quantity | Existing editable entry and shares, position value, execution risk; existing target and allocation editors remain directly reachable and visibly editable when opened | Existing T1/T2/T3 and share-allocation editors. Keep Arithmetic's suggested-size/Apply action and concentration warning together, visible when that recommendation is being considered; Apply retains its current share-only behaviour |
| 7. Decision and actions | Existing method/target choice, selected target, matching probability/window/time where supplied, selected full-position outcome, entered quantity and actual execution stop; existing basket/portfolio/broker actions and their restrictions | Full selected-plan explanations, checklist evidence, ownership/server-validation details and Auto-trade execution. Keep any action-blocking state, exposure resize, queued/unknown result and retry warning visible |

### Stocks-specific rules

- Stocks already has the three method choices. Ladder uses **edited execution targets**. The separate **initial scanned strategy targets** are different evidence: retain their entire table and observations in a clearly named disclosure associated with Ladder; never relabel them as the edited ladder or invent original allocations.
- Ladder supplies no probability/time estimate. Preserve that absence; do not borrow another method's statistics.
- Monte Carlo uses the existing execution entry/stop/targets. Arithmetic has its own returned structural/ATR final stop. Selecting a method records intent and does not apply a stop, target or quantity change. The calculation/execution difference must remain visible; no new Apply-stop action.
- All current stock simulation windows and medians use **trading days**. Retain the distinction between independent barrier touches and exclusive first-hit outcomes, and between entered and recommended share quantities.
- The existing **Which comes first** race graphic is supplied by `plan.race` in Arithmetic. Nest it within Arithmetic, closed by default; do not move its ownership to Monte Carlo or add a fourth selectable method.
- The existing Latest Calculation section contains unique chronology/freshness information. Move that information to a named closed disclosure in the method area, keeping every unique datum and mapping duplicated numeric summaries to their surviving original results.
- Stocks currently states: **“Unvalidated — research only. Strategy validation is unavailable; broker sending and automatic arming are blocked.”** This presentation work retains that restriction. Research portfolio actions and execution actions must keep their current distinct behaviour.
- Before specifying any consolidated “what will be sent” review, trace `addToBasket`, current execution edits, `StockSendDialog.effective`, research save and `sendStockSaveFirst`. Reposition existing review information only after that mapping. Do not imply that choosing a calculated TP replaces submitted editable targets or that pinning itself sends an order.

## Pre-Breakout: proposed order

Scope: all three existing Setup Scanner submodes—Pre-Breakout, Pullback to EMA and Fib Pullback. This page selects setups and provides chart/watchlist/alert actions; it does not provide a terminal execution card for all three modes.

| Order | Visible by default | Expandable content / preserved destination |
| --- | --- | --- |
| 1. Scan context | Existing universe/manual-symbol override, direction, horizon, submode selector and Run Scan; scanning/error state | Existing mode explanations and full parameter controls/help/reset actions, default closed; original applied thresholds remain distinct from edited current controls |
| 2. Selected context | For the selected symbol: sentiment, then Fundamental Health, retaining badges/colours and visible original-versus-supplementary source labels | Complete original/supplementary scope, request details, raw context and fundamentals, all safety flags and unavailable states |
| 3. Candidate list | Identity/company where supplied, direction and current mode's essential metrics; selection, WatchStar, open-chart and Alert actions stay accessible | Existing detailed metric definitions and threshold explanations remain reachable in disclosures; preserve sorting, keyboard selection and all returned rows |
| 4. Selected setup | Current selected-symbol chart and existing scan-evidence price lines; existing selected identity/context | Setup evidence, complete returned fields/raw records, swing/Fib observations, confidence breakdown and existing scan-scope explanation. No new trigger/entry/stop/target inferred from chart levels |
| 5. Qualification | Closed selected-stock score/qualification section, with source and final verdict distinguished from setup confidence | Existing component factors, weights, caps, gate flags, earnings/veto data, historical-confidence compatibility, raw original and supplementary records |
| 6. Supporting research | Existing news section as a named closed disclosure | Preserve every headline, publisher, date, original link, returned/requested-symbol label, loading/error/empty state and unsupported-industry-feed notice |
| 7. Scan diagnostics | Existing Candidates count and Filter Breakdown access | Full saved report/analysis log, exclusions, threshold snapshots, run identity, counters and per-mode latest-report behaviour; opening it must not rerun the scan |

### Submode essentials

- **Pre-Breakout:** setup confidence, ATR ratio, volume ratio and proximity to the swing level, as currently displayed. Preserve range qualification, current ATR, swing level, all metric fields and component weights in Setup Evidence. Retain existing chart lines rather than generating trading levels.
- **EMA Pullback:** returned stock score, price and historical signal confidence with direction; full strategy/stock evidence remains expandable.
- **Fib Pullback:** returned Fib-level label, distance, at-level state and proximity confidence; preserve swing evidence, scanned tolerance and EMA-filter explanation.
- Setup confidence, stock filter score, historical confidence and Fib proximity confidence are different quantities. Label them accordingly. None becomes “probability of profit.”
- The selected context hook already fetches supplementary stock analysis separately. Preserve its existing fetch triggers, compatibility checks and stale-response ownership. Do not hide the source label or present supplementary `pullback_ema` analysis as qualification of the selected Pre-Breakout/Fib setup.
- Do not invent a scan price for row types that do not supply one; separately fetched prices retain their live-context label. Do not add a broker/TP/time-to-TP card where the existing page lacks that workflow.

## Proposed delivery sequence

1. **Complete the preservation inventory.** Enumerate every current field, paragraph, tooltip, badge, colour meaning, action, link, condition and unavailable/loading/error state. For each record exact source and future visible/disclosure destination. Trace Stocks basket/save/send payloads and original-versus-edited ownership. The source review behind this proposal is not yet that exhaustive inventory.
2. **Create permanent interactive previews before implementation.** Separate Stocks and Setup Scanner previews, stored in the repository; light/dark, initial/expanded states, Stocks two/three-method comparison, and all three setup submodes. Show unavailable/on-demand and mismatched-stop examples without implying new calculations. Review these previews with the user before coding.
3. **Implement Stocks as its own phase.** Layout/qualification; compact execution settings; method display/comparison and preserved evidence; entry/decision/action grouping; existing review rearrangement. Keep calculation/store/API/transport behaviour unchanged and protect the Step 6 embedded use.
4. **Implement Setup Scanner as a separate phase.** Shared selected-symbol/context layout; three submode tables; chart/evidence/qualification disclosures; parameters/news/diagnostics access. Keep scan request and selection/scope behaviour unchanged.
5. **Verify preservation and behaviour.** Reconcile every inventory entry, inspect expanded full text, verify badges/colours, test light/dark and supported desktop widths; no calculation caused by viewing, no edits changed by selection, no stale candidate/scan context, no unsupported statistic relabelled. Compare existing numeric/persistence/submission tests; audit each phase independently before publishing or merging.

Provisional implementation sizing, to refine after inventory and preview review: **Stocks L / complexity 3; Setup Scanner L / complexity 3**. These are two separate implementation phases; no implementation has started. Board tickets and the detailed execution plan follow the agreed preview; this proposal does not claim their plan/code gates are already complete.

## Source map

- `frontend/app/(frame)/screener/step-7-position-card/page.tsx`
- `frontend/components/organisms/StockPositionCard/index.tsx`
- `frontend/components/organisms/StockPositionCard/InitialStrategyTargets.tsx`
- `frontend/components/organisms/StockPositionCard/PositionEvidence.tsx`
- `frontend/components/organisms/StockSendDialog/index.tsx`
- `frontend/lib/stockExecutionSession.ts`
- `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`
- `frontend/app/(frame)/screener/step-4-prebreakout/PreBreakoutRowDetails.tsx`
- `frontend/app/(frame)/screener/step-4-prebreakout/SelectedStockContext.tsx`
- `frontend/app/(frame)/screener/step-4-prebreakout/SelectedStockNews.tsx`
- `frontend/app/(frame)/screener/step-4-prebreakout/SelectedSetupChart.tsx`
- `frontend/app/(frame)/screener/step-4-prebreakout/scanChartLines.ts`
- Options acceptance and shipping records under `docs/superpowers/plans/trade-card-reference-alignment/` and `trade-card-qualification-placement/`.
