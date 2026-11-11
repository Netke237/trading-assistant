# Current source → approved destination

Baseline `0a453f19`. Every JSX text/expression/prop/condition is enumerated in `baseline-content.json`; this table assigns all source regions, including nested content, rather than treating a shorter label list as exhaustive preservation.

| Baseline source | Destination | Preserved contract |
| --- | --- | --- |
| index.tsx 1–867 | Same controller and embedded helpers | Every hook/identity/token, risk calculation, stock quote, API args, invalidation, pick, save/send, error/result/quantity guard unchanged; view state can be added separately |
| 871–896 | Identity below selected context | Symbol/company/direction/strategy, confidence/status tooltips/colors, quote loading/unavailable versus scan price, stock score/horizon, chart URL/rel, Pin/Unpin handlers |
| 897, 910 | First sentiment then fundamentals | Complete child props and existing child explanations/statuses; component internals unchanged |
| 898–901 | Navigation/help | Preserve section destinations, update disclosure anchors if moved, full help paragraph |
| 903–909 | Prominent restriction/ownership notices | Bearish/general validation block, earnings veto, pending ownership; no warning lost through collapse |
| 911; InitialStrategyTargets.tsx entire file | Closed original scanned strategy within Ladder | Original entry/stop/targets, signed reward/return/RR/full-position quantities, unavailable original allocations, all strategy observations |
| 912–922 | Closed Latest calculation in methods | Identity-matched chronology, missing/stale state, method, stop/risk/horizon, all target price/probability/fractional trading-day medians |
| 927–975 | Compact stop/risk before methods; entry/shares after methods | Same EditableField patch callbacks, entered quantities, win-rate tooltip and tone; execution risk/invalid-stop notice; default embedded grids unchanged |
| 976–1046 | Target/allocation editor beside entry/shares | Every T1/T2/T3 field, reward/RR/return formula/tone, current allocation edits and invalid-target message |
| 1047–1118 | Closed Structure & Stops | Entered and calculated stops, both quantity risk bases, source/confidence, ATR/floor/distance/justification, Check structure loading/error, distance/RR guard, structural reference caveat |
| 1121–1144 | Edited Ladder result/evidence | Every target/full-exit/allocated shares+outcome/reward/RR and absence of probability/time; distinguish original strategy |
| 1145–1251 | MC card and full explanations | Explicit Estimate only, input source, horizon, target and stop probabilities/medians, signed full outcomes, caveat; embedded structural control remains unchanged |
| 1252–1433 | Arithmetic card and full explanations | Explicit plan only, returned stop/risk/ATR/justification, independent reach/time, mismatch warning, returned targets/reward/equations/quality/structural tolerance, recommended versus entered sizing, concentration warning/Apply and stop-basis notice |
| 1434–1484 | Closed Arithmetic race/full caveats | Path count/window, allocated weights/tones, graphical meters, every target/time and neither terminal mean, exclusive versus independent explanation; model caveat/independence paragraph remains reachable |
| PositionEvidence.tsx non-checklist body | Closed Stock Qualification and Backtest Evidence after identity | Final capped versus scorer status, score, non-probability caveat, every component/weight/contribution/measured status/detail; all backtest scales, confidence explanation, summary, scan thresholds/unavailable |
| index.tsx 1492–1628; PositionEvidence checklist body | Decision/actions after entry/shares | MethodPickSelector plus full selected-plan sources/probability/time/quantity/outcome, research save, broker config/mode/order guards, every failure/unknown/queued/adjusted result, Auto-trade and full gate checklist |

## Downstream payload trace (read-only, unchanged)

`scanStore.addToStockBasket` stores card + identity. `resolveBasketExecution` requires matching recorded source identity AND original candidate membership before using session overlay/pick; restores use saved values and missing-method refusal. `StockSendDialog.effective` uses this resolver; current shares are session-owned, restored shares are dialog-owned. `onAddToPortfolio` uses overlay levels/snapshot and method metadata, validates target side, takes ownership, and reports quantity adjustments. `submit` refuses stock validation before `sendStockSaveFirst`; overlay values populate snapshot/levels and selected method fields are intent, not replacement editable targets. `sendStockSaveFirst` saves first and uses approved quantity. No source in this chain is changed by layout.

## Reconciliation record

Pending implementation. New heading labels may clarify Ladder versus scanned strategy. No unique explanatory text may be dropped. Source expressions, conditional warnings and event handlers require source review in addition to visible-text checks. Automatic source inventory is coverage accounting, not proof of rendered correctness.
