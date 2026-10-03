# Trade card implementation roadmap

The approved design will be implemented as seven sequential reviewable slices. Each gets relevant checks and an independent code audit before the next builds on it. No deployment or merge is implied.

| Slice | Visible outcome | Why separate |
|---|---|---|
| 1. Score evidence | Exact effective weights, thresholds, contributions and gate reasons can be explained | Additive provenance needs numerical/persistence review; do not guess from current defaults |
| 2. Top cards | Slim Market Sentiment, stock/option identity, slim Fundamental Health | Stable visual structure and original green/amber/red colours |
| 3. Handling summary | Entry, contracts, actual exit fields and latest results prominent | Protect edit/revert, price units and latest-result versus chosen-method distinctions |
| 4. Calculation methods | Clear stop/target/size, spaced probability columns, visible Set override | Protect existing calculation and quantity-only Apply behaviour |
| 5. Barrier Race | Outcome probabilities, time, R:R and edge together, explanations expand | Protect first-outcome allocation, freshness and method-selection payloads |
| 6. Qualification | Score evidence and backtested confidence explained | Keep raw scores, historical confidence and checklist gates distinct |
| 7. Execution and reconciliation | Adjacent decision/execution controls, all original information verified | Preserve single control instances, broker/auto-trade state and complete inventory |

Production colour contract: PASS green, CAUTION amber, REJECT red, unknown/pending existing neutral. Bullish green, Bearish red. Existing helper/server verdicts determine colours; the UI does not invent new gate thresholds.

Implementation-plan.md contains exact file scope, behaviour constraints, acceptance checks and audit requirements. Plan-audit.md records the independent plan review. The 520-entry mapping is a checklist to reconcile against source and populated runtime states, not a claim that count alone proves preservation.

Publication note: this is the original seven-slice conceptual roadmap, not the launch schedule. For current status and launch readiness read PROJECT_STATE.json → trade_card_presentation/task_backlog. The parallel handoff defines exclusive ownership and external dependency gates.
