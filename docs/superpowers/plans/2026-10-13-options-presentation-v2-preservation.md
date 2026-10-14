# Options presentation V2 preservation crosswalk

Coordinator verification for #249, 13 October 2026. This maps all 40 inventory rows to source; final tests and independent code audit are recorded separately in the validation document and phase history. Browser coverage uses mocked responses and never sends broker orders.

TradeCard owns display/edit state; Step7Page owns the live quote, basket, persistence and execution paths. Relative source roots: frontend/components/organisms/TradeCard/, frontend/components/organisms/BarrierRaceCard/, frontend/components/molecules/MethodPickSelector/, frontend/app/(frame)/screener/step-7-trade-card/, and the existing @contextRail routes.

| Original field/action | Final location | Visibility / conditional states | Numeric source, units and unchanged handler |
| --- | --- | --- | --- |
| Page help, step navigation, previous/next candidate, candidate position | Step7 page header / shared layout | Visible | Navigation / selected candidate index |
| Pin, basket contents, pending-plan messages | CandidateNav / basket strip | Visible | Candidate identity and pending plan state |
| Market sentiment, conviction, horizon, regime stickiness/duration, OMM/HMM divergence | MarketSentiment | Visible | Market state; conviction %, horizon, separate alignment |
| Symbol, company, stock price, direction, final status | Selected stock and contract | Visible | Scan stock price and status |
| Selected contract identifier, strike, expiry, right, mid, DTE, score/confidence, capital at risk | Selected stock and contract / Contract Details | Visible | Selected contract snapshot, mid/share, DTE, score and quantity-scaled capital |
| Delta, theta, correctly labelled IV or IV rank | Contract Details | Contract details section | Greeks; absolute IV versus rank kept separate |
| Fundamental score, growth/quality/risk, definitions and safety flags | FundamentalHealthCard | Visible | Existing fundamentals component definitions |
| Stock and contract component scores, notes, confidence, qualification, captured evidence | Stock & contract scores | Fresh collapsed; saved preference; evidence kept mounted | Original score bars/totals/evidence; fresh collapsed, saved preference honored |
| Spread legs, side/quantity/strike/right/expiry, debit/credit, max profit/loss, breakeven | Conditional spread details | Only for supported spreads | Original legs and signed net debit/credit; zero preserved |
| Alternative contracts, scores, Greeks, pricing and reasons | Alternatives | Conditional, expandable | Original alternative contract fields and reason |
| Order type, editable limit/contracts, max fill | Order Entry | Visible | overlay entryLimit/contracts; scan maxFill is display-only |
| Editable stock invalidation, premium stop with global/override basis, time exit | Exit Plan | Visible | overlay invalidation; effective loss allowance; fixed time exit |
| Edit markers, clear-to-restore behavior, bounds, low-premium read-only state | EditableKV / header edited badge | Visible | patch/revert and original validation bounds / touched flags |
| Max-loss default, effective dollar budget, percent/dollar override, Apply, Use default | Order inputs & risk budget | Visible | maxLoss override, risk basis and original Apply/default handlers |
| Structural check, source, price, distance, loading/error/no-level/zero-risk states | Structure & Stops | Original result/loading/unavailable conditions | checkStructure and original available/error response |
| ATR(14), ATR-floor price, structural-floor distance, final stop, source and justification | Structure & Stops | Original result/loading/unavailable conditions | sharedStop / exitPlan.stop, unchanged stock price/ATR units |
| Stop-loss gate/status, contract premium used, remaining value, per-contract loss, pricing basis | Structure & Stops | Original result/loading/unavailable conditions | matched stopRisk; today premium/value/loss; quantity×100 separately labelled |
| Arithmetic run, waiting/error states | Arithmetic Profit Target | Original result/loading/unavailable conditions | computeExitPlan handler / loading and error |
| Arithmetic target rows: 2:1 and 3:1 by config, or inherited target multiple sequence | Arithmetic comparison table | Original result/loading/unavailable conditions | Every exitPlan.targets row, returned R:R sequence |
| Arithmetic stock price, contract price, pricing model, probability before expiry, expected days | Arithmetic comparison table | Original result/loading/unavailable conditions | Returned stock/option prices, rrModel, independent probability and days |
| Nearest structure, distance, tolerance, quality reasons, capped/beyond warning | Arithmetic target geometry disclosure | Disclosure; actionable warnings visible | Returned tpSource / tolerance / quality; warnings remain visible |
| Exact and rounded risk-derived contract size, Apply and zero-size refusal | Order inputs sizing block | Visible | Original sizing helpers on scan-mid basis; zero-size Apply remains refused |
| MC editable T1/T2/T3 profit percentages, run, wait/error | Monte Carlo Profit Target | Original result/loading/unavailable conditions | Existing T1/T2/T3 state and estimate handler, clamp preserved |
| MC all target rows: option price, stock price/unreachable, structural pairing state, probability/time | Monte Carlo result rows | Original result/loading/unavailable conditions | Returned target prices and probability/time; matched captured/echo premium |
| MC independent-hit probability explanation | Monte Carlo visible notes | Visible | Independent event definition; not race-exclusive probabilities |
| Barrier race availability and barriers-changed messages | BarrierRaceCard freshness / moved barriers | Original result/loading/unavailable conditions | Original isFresh / raceBarriersMoved guards; expired versus absent |
| Stock/premium barrier levels, provenance, stop applicability, independent stock-stop touch probability and median | BarrierRaceCard three barriers | Original result/loading/unavailable conditions | Returned stockStopPrice/premiumStopPrice; invalidation standalone statistic |
| Race row for every returned target: option price/percentage, selection, four first-hit outcomes, stacked bar, target median, stock-stop R:R, edge/contract | BarrierRaceCard outcome table | Original result/loading/unavailable conditions | All outcomes; weightPercents allocation; original selection mappings, RR/edge formatters |
| Weak-stop warning and simulation assumptions | BarrierRaceCard visible warning / assumptions | Original result/loading/unavailable conditions | Original allocated-zero warning, IV fallback and nPaths assumptions |
| Stop medians, full risk/R:R/edge chains, premium-stop R:R, repricing/time-decay/model explanations, neither value | BarrierRaceCard supporting disclosure | Disclosure; no actionable controls hidden | Original risk/edge chains and stop medians; signed neither term |
| Fixed ladder editable stock target prices, option estimates, R:R, status, edited flag, quantity/scale-out, pricing method, full-premium risk basis | Fixed % Ladder Plan | Near top, fresh expanded; saved collapse preference retained | Single editable overlay target set; full-premium R:R; original per-rung allocation |
| Method availability reasons, explicit selection, judged-on controls, record-only note | Final Recommendation / MethodPickSelector | Visible | applyMethodPick; method-only has no selected row; Clear/basis unchanged |
| Latest calculation versus chosen method, timestamps and unavailable/stale states | Final Recommendation / Chosen method and target | Visible | Recorded price pair / pickedAt; exactly one matching result for borrowed evidence |
| Live stock and premium, quote warnings, recommendation identifier | Step7 live quote rows / card footer | Visible | Actual live quote source and quote confirmation; rec identifier |
| Track basket, View chart, Export JSON | Card actions / basket dialog | Visible | Original onSendToBroker, chart toggle and JSON payload |
| Existing broker picker, config labels, Place Limit, Right Now Market, auto-trade controls | Step7 Decision and execution | Original execution/feedback conditions | Original picker config and direct limit/market/AutoTradeArm handlers |
| Missing-stop/missing-pick, earnings, bearish-unvalidated, plan-ready and market-block messages | Step7 adjacent execution warnings | Original execution/feedback conditions | Original stopMissing/pickMissing/earnings/bearishUnvalidated/planReady gates |
| Save/basket/direct-send warnings and errors, persistent direct notes, Remove/status controls | Step7 feedback and basket rows | Original execution/feedback conditions | Original save/order/direct-note and Remove/status handlers |
| Send dialog and its warnings, portfolio tracking toast and link | SendToBrokerDialog / portfolio toast | Original execution/feedback conditions | Original dialog request mapping / successful tracking feedback |
| Pre-trade checklist, historical analogs, watchlist, portfolio, data-source rail | Existing parallel context rail | Visible | Unchanged context rail sources; no replacement with mock widgets |

## Cross-method boundaries

Arithmetic sizing remains scan-mid based. Immediate stop-cost display uses its matched today response; Monte Carlo outcomes use matching returned premium/captured request context; Barrier Race scales returned reward rather than reconstructing percentage prices. Dollar outcomes are display-only selected-contract values, before costs, and never added to requests or persistence. Ladder alternatives must distinguish full-exit and allocated-rung amounts. Missing source evidence means unavailable; zero and signed values remain meaningful.

MethodPick shape and applyMethodPick remain unchanged. A method selection alone does not choose a row or change execution fields. Ladder/Arithmetic record stock levels, Monte Carlo can record stock and premium, Barrier Race records premium with null stock level. The summary borrows probability/time/model only for one matching source row; duplicate or missing matches retain the recorded decision with unavailable evidence. Freshness and candidate-change guards remain authoritative.

## Validation boundary

Existing TradeCard, selector, BarrierRace helpers, downstream Step7 basket/direct/order/session, AutoTradeArm and disclosure tests supply conditional-state coverage. Browser checks cover keyboard disclosure/selection, saved evidence DOM state, readable fields and page overflow at 1200px/1920px in dark/light. They do not substitute for all execution tests or the numeric/persistence audit. The integrated phase is not ready to merge until the independent code audit is clean and required CI passes.
