# Stocks presentation V2 preservation crosswalk

Coordinator inventory for #257, 13 October 2026. This inventory maps the completed serial build; eight mocked browser cases pass. Independent integrated audit remains pending. Frozen examples are not numerical or execution authority.

Sources: StockPositionCard/index.tsx and its child components; step-7-position-card/page.tsx; MethodPickSelector; stockExecutionSession; cardEdits; scanStore; StockAutoTradeArm; StockSendDialog; DirectSendNotesPanel; existing shared frame and context rail.

| Source field/action | Destination / condition | Authority and preservation obligation |
| --- | --- | --- |
| Shared mode switch, step navigation, context rail, width gate | Shared frame / supported Step7 widths | Current shared placement; no duplicate mode switch |
| Passing-candidate filtering, Prev/Next, symbol buttons, selected index | Page candidate navigation | backtest.passes_gate and resolved symbol; execution identity includes run generation |
| Basket count, Send basket dialog, direct send notes | Page header / conditional dialog / feedback | Original stockBasket, StockSendDialog and DirectSendNotesPanel |
| Symbol/company, scan price, live quote/loading, direction/status, strategy/horizon | Card context | Card fields and captured stockScanRequest; no live settings masquerading as scan context |
| Sentiment and fundamentals including safety details | Existing child sections | Actual sentiment/fundamentals source; missing evidence stays unavailable |
| Stock score, scorer status before caps, component raw scores/weight/contribution/detail | Qualification / Stock Scorecard | Full stock_explanation, measured flag and final stock_status |
| Win rate, trade count, expectancy, return, drawdown, Sharpe, confidence/explanation, summary and scan thresholds | Qualification / Backtest evidence | Backtest/card plus captured request thresholds; zero distinct from absence |
| Original strategy entry/stop/targets, legacy target fallback, strategy observations | Initial strategy targets | Immutable card.strategy; direction-aware reward/return/R:R; entered-share full exits are alternatives; original allocations unavailable |
| Entered entry/stop/shares, win%, position value and execution risk | Order & exits / Execution risk | Existing overlay patch; stockPositionLevels cent/direction validity; invalid stop risk unavailable |
| T1/T2/T3 prices, R:R, return and allocated shares | Existing editor disclosure | Current overlay and existing allocation clamps; mounted controls; losing targets carry signed ratios |
| Structure check, loading/error/no-level, price/source/distance/reference ratio | Structure & Stops | Existing onCheckStructure response/guard; candidate is reference, not execution or calculated final stop |
| Arithmetic final stop, ATR floor/source/widening, stop risk and justification | Structure & Stops / Arithmetic | Returned plan.stop; execution stop remains distinct and unchanged |
| MC Estimate/loading/error, targets and stop independent-hit probabilities/times, horizon/caveat | Stacked calculation evidence | Existing getStockFirstPassage request/response; explicit actual trading-day statistic |
| Arithmetic Compute/loading/error, targets/reward/R:R/geometry/snap/quality and model caveat | Stacked calculation evidence | Existing getStockExitPlan; all rows share returned final stop |
| Risk budget, recommended shares/notional, concentration flag, Apply shares and mismatch note | Arithmetic sizing evidence | Original budget and stock cap; Apply positive recommended shares changes quantity only |
| Target-first/stop-first/neither allocated weights, times, terminal mean and nPaths | Supporting Arithmetic race | Returned race; allocated percentages unchanged; source statistic explicitly labelled; no premium barrier |
| Latest calculation chronology and absent/stale states | Latest calculation | Local completed-action identity, current available session result; restored chronology unavailable |
| Method availability, method IDs, explicit row keys/prices, judged-on/clear controls | Decision / MethodPickSelector | Existing methodPickOptions and applyMethodPick; Ladder means editable execution ladder, separate from immutable initial strategy |
| Chosen summary and source-matched probability/time | Decision / Selected stock plan | Current matching row only; stock-space prices; selecting intent does not apply stop/shares or order |
| Chart link and pin/unpin | Context actions | Original chart href and basket handlers |
| Add to Portfolio and added/queued/in-flight feedback | Decision / Execution | Original onAddToPortfolio; target-side refusal, picked fields, snapshot, structural reference and holdMaxDays |
| Recommendation and IBKR/Tradier/Alpaca/Tastytrade configured paper modes | Decision / Execution | Existing config sources and mode state; unavailable buttons remain disabled |
| Limit/Market, placing/order feedback/error/warnings, adjusted quantity | Conditional broker execution | Original submit and actual server refusal; no simulated UI gate overrides |
| Bearish/research-only refusal, earnings veto, missing/disappeared pick, send ownership | Visible safety/checklist and disabled actions | Existing gate constants and stockOrderOwnership; duplicate/in-flight guards remain authoritative |
| Auto-trade arms, after-scan intent and feedback | Existing disclosure | StockAutoTradeArm original props/state/handlers; no real arm/fire in verification |
| Recorded gate flags, final/backtest verdict, fundamentals, pending server limits | Pre-trade checklist | Recorded source flags; execution remains unvalidated |
| MC entry/stop/targets key, Arithmetic entry key, structure entry key | Unchanged session dependencies | Quantity/allocation preserve results; target clears MC; stop preserves Arithmetic/structure; entry clears all |
| Abort controllers, revisions, request tokens, symbol/run freshness | Existing request/session paths | Late/reordered responses cannot replace current evidence; use isStockExecutionCurrent |
| Pick stamp, disappearance checks, same-version sanitation/migration/reload | cardEdits / scanStore | Existing keys/schema and per-scan/per-symbol ownership; numerical evidence not persisted just to restore a label |
| Five durable scan report categories and saved-run inspector | Existing audited LOG integration (reconciled #256) | Report identity captured at dispatch; category isolation, unavailable diagnostics and retention preserved |

Final verification must reconcile each pending row to committed source and record field/source/unit checks, bullish/bearish payload parity, response/persistence guards and mocked browser results at 1200/1920 in both themes. Passing ticket tests do not clear the phase code-audit gate.

Timing source verification: backend/app/scoring/first_passage.py stock `_barrier` returns the median first-touch day among paths ever touching that level; race medians use paths where the respective outcome wins. All stock simulation steps are trading days (1/252). Arithmetic applies stock first-passage to its returned final stop/targets. Fractional median days are source evidence, not calendar-duration predictions.

Final browser verification: Chromium bullish/bearish × dark/light × 1200/1920, eight passing cases. Keyboard disclosures, candidate navigation, explicit Arithmetic/Ladder target selection, matching stop/quantity/outcomes and fractional median timing checked. Exactly one mocked portfolio payload preserves entry, execution stop, entered shares, original allocations and picked price; no real broker/arm/save calls. Screenshot inspection includes narrow dark stop/decision and wide light context/stop layouts. Independent integrated code audit is still required.
