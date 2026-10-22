# Options presentation preservation checklist

12 October 2026. Read-only comparison of the live Step 7 CRWD card and current repository source. No application files changed. The conversation preview is a layout model, not a complete implementation or independent audit.

## Existing information and proposed destination

### Confirmed visual requirements from the supplied screenshots

- Preserve both full score panels: all existing progress bars, component labels, numeric scores and rule notes. Preserve the backtested setup confidence explanation, Unvalidated state, totals, qualification/status badges and both captured scoring evidence disclosures. Folded by default does not mean abbreviated after expansion.
- Market sentiment uses readable labels supported by existing status colors. Preserve conviction, interpretation and alignment independently; do not turn sentiment into a new regime gate or equate bullish state with an automatic PASS.
- Preserve the app's three-font system: Sora titles, DM Sans text and JetBrains Mono numeric data. Existing theme tokens, primitives, component shapes and app navigation remain authoritative.
- The preview's generic Dashboard/Screener/Watchlist sidebar was inaccurate for the screener route. Preserve its existing step navigation and shell instead of redesigning them.

| Existing information / control | Destination |
| --- | --- |
| Page help, step navigation, previous/next candidate, candidate position | Existing shell and page header |
| Pin, basket contents, pending-plan messages | Candidate navigation / basket strip |
| Market sentiment, conviction, horizon, regime stickiness/duration, OMM/HMM divergence | Context card; full existing explanation accessible |
| Symbol, company, stock price, direction, final status | Context card |
| Selected contract identifier, strike, expiry, right, mid, DTE, score/confidence, capital at risk | Combined contract/context card |
| Delta, theta, correctly labelled IV or IV rank | Contract details disclosure |
| Fundamental score, growth/quality/risk, definitions and safety flags | Context card / health disclosure |
| Stock and contract component scores, notes, confidence, qualification, captured evidence | Score disclosures, initially folded |
| Spread legs, side/quantity/strike/right/expiry, debit/credit, max profit/loss, breakeven | Conditional spread details; never suppressed for spreads |
| Alternative contracts, scores, Greeks, pricing and reasons | Alternative contracts disclosure |
| Order type, editable limit/contracts, max fill | Order inputs |
| Editable stock invalidation, premium stop with global/override basis, time exit | Order and exit inputs |
| Edit markers, clear-to-restore behavior, bounds, low-premium read-only state | Corresponding input; preserve current behavior |
| Max-loss default, effective dollar budget, percent/dollar override, Apply, Use default | Visible risk budget editor within order inputs |
| Structural check, source, price, distance, loading/error/no-level/zero-risk states | Structure & Stops |
| ATR(14), ATR-floor price, structural-floor distance, final stop, source and justification | Structure & Stops; retain scan versus freshly computed provenance |
| Stop-loss gate/status, contract premium used, remaining value, per-contract loss, pricing basis | Structure & Stops; warnings visible |
| Arithmetic run, waiting/error states | Arithmetic method |
| Arithmetic target rows: 2:1 and 3:1 by config, or inherited target multiple sequence | Arithmetic results, both rows visible |
| Arithmetic stock price, contract price, pricing model, probability before expiry, expected days | Each Arithmetic target |
| Nearest structure, distance, tolerance, quality reasons, capped/beyond warning | Target geometry disclosure; actionable warnings visible |
| Exact and rounded risk-derived contract size, Apply and zero-size refusal | Risk sizing summary with existing conditions |
| MC editable T1/T2/T3 profit percentages, run, wait/error | Monte Carlo inputs above results |
| MC all target rows: option price, stock price/unreachable, structural pairing state, probability/time | Monte Carlo results |
| MC independent-hit probability explanation | Method disclosure, with concise visible event definition |
| Barrier race availability and barriers-changed messages | Barrier Race, preserve existing gating |
| Stock/premium barrier levels, provenance, stop applicability, independent stock-stop touch probability and median | Barrier definitions / explanatory disclosure |
| Race row for every returned target: option price/percentage, selection, four first-hit outcomes, stacked bar, target median, stock-stop R:R, edge/contract | Barrier Race; all target comparisons remain available |
| Weak-stop warning and simulation assumptions | Race warning visible; concise assumptions visible |
| Stop medians, full risk/R:R/edge chains, premium-stop R:R, repricing/time-decay/model explanations, neither value | Race supporting disclosure |
| Fixed ladder editable stock target prices, option estimates, R:R, status, edited flag, quantity/scale-out, pricing method, full-premium risk basis | Initial ladder / ladder method; same underlying control set |
| Method availability reasons, explicit selection, judged-on controls, record-only note | Selection and chosen-plan summary |
| Latest calculation versus chosen method, timestamps and unavailable/stale states | Chosen-plan summary; preserve existing resolution logic |
| Live stock and premium, quote warnings, recommendation identifier | Relevant price/provenance rows and decision area |
| Track basket, View chart, Export JSON | Existing action area |
| Existing broker picker, config labels, Place Limit, Right Now Market, auto-trade controls | Decision & execution, preserving conditional availability |
| Missing-stop/missing-pick, earnings, bearish-unvalidated, plan-ready and market-block messages | Visible beside affected action; never hidden in disclosure |
| Save/basket/direct-send warnings and errors, persistent direct notes, Remove/status controls | Existing action feedback area |
| Send dialog and its warnings, portfolio tracking toast and link | Existing dialog / feedback behavior |
| Pre-trade checklist, historical analogs, watchlist, portfolio, data-source rail | Existing context rail retained; simplified preview labels are not a replacement |

## Clarifications from source

- Arithmetic's 2:1 and 3:1 are R:R targets, not ATR multiples. Options does not offer local Step 7 editors for these ratios. The request inherits Step 3's target R multiple; backend configuration supplies the default ratio sequence.
- ATR floor multiplier is currently 2.0 in backend/config/risk_rules.yaml; target structural tolerance is separately 0.3 ATR. Neither is a local Step 7 editable input.
- Monte Carlo exposes local T1/T2/T3 percentage inputs. Barrier Race uses the same simulation and renders all returned race outcomes; it has no separate target-calculation run.
- Trade loss budget accepts a percentage of portfolio value or an absolute dollar override and always shows the resolved dollar budget. It changes sizing, not event probability.

## Corrections required to the first preview

- Show Arithmetic contract prices; the first mock incorrectly said they were not provided.
- Show both Arithmetic targets, all Monte Carlo percentage inputs and every race target.
- Expose percent/dollar budget modes, Apply and Use default.
- Preserve the real Options action set; generic mock buttons for stock-oriented actions are not a valid substitute.
- Preserve conditional features and feedback, not just the currently visible CRWD state.
- Preserve source-specific horizons and probability/time definitions. A universal 30-day label is not accurate.

The updated preview addresses the main missing visual groups. Full preservation must be checked against this checklist during implementation and independent review. No claim that the current mock reproduces every field or behavior is made.
