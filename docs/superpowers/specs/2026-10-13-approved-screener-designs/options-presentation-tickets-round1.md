# Options Step 7 presentation — implementation ticket drafts

Date: 12 October 2026. Status: drafted, independent plan audit pending. No application implementation authorized by this artifact. Local drafts, not GitHub issues.

## Controlling scope

Presentation only. Preserve all existing information, controls, formulas, backend requests, defaults, ranking, gates, selection effects, cache invalidation, persistence and execution behavior. No new risk logic, auto-application of stops, probability ranking, best-method verdict or trading recommendation. Earlier OPT-UI-17–21 and CROSS-UI-14–16 are incorporated here; earlier Stocks table/backtest tickets are outside this Options page.

The preview is an illustrative layout reference, not numeric authority, functional specification or field-complete implementation. Actual components, types, responses and the preservation checklist control data/behavior. Never copy preview numbers or its simplified selection handlers into production. Runtime model labels and statuses must be driven by actual sources. Do not infer missing prices, probabilities, times, timestamps or sources.

Before implementation: inspect latest PROJECT_STATE, canonical trade-card handoff and live claims; claim the applicable task on an implementation branch, clear overlapping owners/dependencies and follow repository checks. These drafts do not override existing task ownership. Keep source-file edits serial where tickets overlap. No claim is taken and no repository file is changed for these external local drafts.

## Evidence and preservation baseline

- Source: frontend/components/organisms/TradeCard/index.tsx, frontend/components/molecules/MethodPickSelector/index.tsx, frontend/components/organisms/BarrierRaceCard/index.tsx and frontend/app/(frame)/screener/step-7-trade-card/page.tsx.
- Additional source: frontend/components/molecules/MarketSentiment/, frontend/components/organisms/AutoTradeArm/, frontend/components/organisms/BrokerPicker/, existing frame/context-rail components, frontend/types/domain.ts, backend/app/routers/contracts.py and backend/app/scoring/{exit_plan,first_passage,reward_risk}.py. Backend is reference only, not an edit target.
- Same-directory options-preservation-checklist.md is a required implementation inventory. Validate each row against current source before coding; enumerate conditional child-component content rather than treating generic placeholders as coverage.
- Same-directory options-trade-flow.html is the evolving illustrative mock. Its example figures and incomplete disclosures are expressly excluded from the audited implementation instructions.
- Live observation: CRWD Step 7 showed both scorecards, captured-evidence disclosures, editable order/exit controls, percent/dollar budget, scan stop and independent Check structure, 2:1 / 3:1 Arithmetic rows, editable Monte Carlo target percentages, fixed ladder and basket/broker actions.

## OPT-PRES-01 — Preserve app shell and combine contract/context basis

Problem: contract identity/details are dispersed; generic preview navigation is not the screener's real shell.

Acceptance:
- Keep existing TopBar, stepper, parallel context rail, step navigation, page help, candidate Prev/Next, pin and basket. Reorganize within Step 7 only.
- Merge selected-contract summary and details without losing identifier, symbol/company, stock price, direction/status, strike, right, expiry, DTE, premium, Greeks, volatility with correct IV/IV-rank basis, scores/confidence and capital at risk.
- Keep conditional spread legs and max profit/loss/breakeven/debit-credit data, alternative contracts and their reasons.
- Distinguish market quotes, scan snapshots, calculation snapshots and edited inputs using existing provenance. Show existing quote warnings; never fabricate freshness metadata.
- Keep Sora titles, DM Sans text, JetBrains Mono numeric data, current primitives/theme tokens/status helpers and existing CSS Modules. No shell redesign or storage-key rename.

Validation: compare single-leg and supported spread/alternative states; typecheck and relevant existing component tests. Check desktop widths including the app's 1200px minimum.

## OPT-PRES-02 — Keep context labels and full score/evidence disclosures

Acceptance:
- Market Sentiment shows explicit state/conviction/alignment labels supported by existing colors. Retain horizon/timeframe, conviction percent/label, interpretation, stickiness, duration, OMM/HMM alignment and missing-data states.
- Do not equate a bullish market state with a PASS gate, relabel conviction as predicted contract profit, or overwrite component-specific status semantics.
- Keep Fundamental Health and all component/definition/safety-flag information.
- Stock & contract scores start collapsed for the intended presentation. On expansion preserve both complete panels: every bar, component score and note; backtested confidence explanation, Unvalidated/qualification/status badges, totals and both captured-scoring-evidence disclosures.
- Audit existing disclosure persistence before changing defaults: no storage rename, no new persisted schema and no override of an existing user's saved open/closed preference. Specify the fresh/default render behavior separately from restoration.

Validation: existing score/evidence and disclosure tests; manually inspect supplied screenshot coverage, fresh default and restored disclosure states.

## OPT-PRES-03 — Bring editable order inputs and trade-loss budget together

Acceptance:
- Keep Order type, editable entry limit/contracts, read-only Max fill, editable execution stock invalidation and premium-stop loss amount, global/override source labels, read-only Time exit and all edit/clear/restore bounds and special cases.
- Keep Set/Edit trade loss budget, percent-of-portfolio and absolute-dollar modes, input, Apply and Use default. Always show the resolved dollar budget and its account-default/override basis.
- Reuse existing maxLossLimitDollar, recommendedContractSize and quantity handlers. Budget affects sizing, not probability. Keep exact and rounded recommended size, explicit Apply and disabled state when fewer than one contract fits.
- Clearly distinguish entered quantity, recommended quantity, full-premium exposure and estimated stop loss. Retain existing cost/contract multiplier conventions and spread semantics; never assume every instrument is a single long option for all states.
- Time exit remains distinct from estimated time to target. Do not create new reset/apply behavior or a new persistence migration.

Validation: relevant existing budget/quantity/input tests; percent/dollar override, Use default, zero-fit, low-premium read-only state, restore and candidate-switch cases.

## OPT-PRES-04 — Separate Structure & Stops with four loss figures

Acceptance:
- Move existing Check structure and related displays into a dedicated section. Preserve standalone structural result versus scan final stop versus newly calculated final stop provenance; do not merge mismatched objects into a false single snapshot.
- Keep structural source/price/confidence where currently available, reference stock price, ATR(14), configured floor, ATR-floor price, structural-floor distance, final structural/ATR stop, justification and existing warnings/availability/loading/error/zero-risk states.
- Present execution stock invalidation separately and state that calculation does not replace it. Do not change stop precedence in Arithmetic, Monte Carlo, alerts or order construction.
- Show together, from ONE matched existing stop-cost result: estimated premium remaining per share; loss per contract; loss for the actual applicable quantity; **premium loss per share**. The last is the user's requested fourth figure.
- Use the result's premiumUsed and contractPriceAtStop/risk values, model/time basis and existing formatters. Never subtract an editable order limit or unrelated live quote from a differently based stop estimate. Example only: $4.00 used − $1.80 remaining = $2.20/share, $220 per standard 100-share contract, $440 for two.
- Keep the separate Arithmetic stop contract-value result and stop-cost gate if they use different pricing bases; label their roles instead of substituting one for the other. Missing values stay unavailable, not zero or PASS.
- ATR floor is currently backend-configured (2.0); target structural tolerance is separately configured (0.3 ATR). Display effective existing data; no new Step 7 multiplier editor.

Validation: formatter/source tests plus meaningful display checks that mismatched premium/quote bases cannot be combined; stop-source transitions, unavailable and live-vs-scan states. Never regenerate numerical pins.

## OPT-PRES-05 — Consolidate Arithmetic target comparison

Acceptance:
- Lead with strike/right, stock entry reference, premium used, quantity/risk basis and one shared final stock stop. Both target rows reuse the same computed stop.
- Show every actual returned target, normally configured 2:1 and 3:1. Target multiple is inherited from Step 3 when supplied; do not hardcode exactly two ratios or add local editors. Ratios describe stock geometry, not guaranteed option R:R.
- One primary result table shows target ratio, option premium, available dollar outcome with exact quantity/basis label, arithmetic versus effective snapped stock target, probability before expiry, conditional median time with calendar-day units, and actual pricing model. Retain structure/geometry/source/quality/cap reasons and warnings.
- Consolidate redundant display, never delete distinct values or explanations. Essential values are visible; supporting geometry/calculation details may fold. If no target estimate exists, show its real unavailable state.
- Do not alter computeExitPlan requests, seeds, quote resolution, target selection or recommendation-size behavior.

Validation: configured and overridden ratios, structural snap/cap, unavailable probability/time and compute failure; relevant existing Arithmetic tests and unchanged request payload checks.

## OPT-PRES-06 — Make Monte Carlo essentials and inputs complete

Acceptance:
- Show strike/right, stock reference and option premium actually used by the estimate; distinguish editable order entry when different.
- Preserve locally editable T1/T2/T3 profit percentages with units/bounds, inherited/fetched inputs, Run, waiting, error and all target result rows.
- Each target prominently shows option premium, available dollar outcome for explicitly named quantity/basis, stock-price equivalent or not reachable, probability, conditional median time and structural-pairing availability.
- Probability means target premium reached at any point before expiry, even when a stop is also reached. Current simulation uses calendar-day steps to DTE; do not replace this with a trading-day holding horizon. Keep inherited holding/repricing settings separately named.
- State that Monte Carlo does not propose a stop. Show the existing effective stock/premium barriers as inputs to the companion Barrier Race, with execution stops distinct. Keep independent stock-stop probability/time information in its existing race disclosure.
- Label simulation and pricing separately: GBM simulated paths and Black-Scholes option repricing in the current engine. Do not label this engine Heston based on another card's model.
- Preserve freshness, stop precedence, auto-refresh inside the existing run handler and structural/race invalidation behavior; no added recalculation or synchronization.

Validation: existing first-passage/freshness tests; target bounds/changes, unreachable target, no stop, restored results, quote fallbacks and active stop computation.

## OPT-PRES-07 — Keep all Barrier Race targets action-ready

Acceptance:
- Same simulation/run as Monte Carlo, no new independent calculation or invented levels. Show every returned outcome row and preserve Use target.
- Show target percentage/premium, applicable dollar outcome, target-first, stock-stop-first, premium-stop-first and neither; keep bars/legend and use the existing allocated percentages consistently with risk/edge arithmetic.
- Keep target conditional median, stock-stop R:R, edge per contract and visible applicable weak-stop warnings. Display actual numeric results, not mock placeholders. No highest-probability or best-stock verdict.
- Keep barrier levels, stop sources, independent stock-touch probability/time, path count, conditional-median/repricing/unchanged-IV/before-commission assumptions, full stop medians and risk/R:R/edge/premium-stop-R:R/neither explanations.
- Reuse existing formatters and model/time labels. Immediate stop-cost and race median-day losses remain separately labelled; neither is not automatically a loss. Preserve actual expiry horizon.
- Preserve barriers-changed/contract freshness guards and unavailable reasons. Race option premium remains premium space; no stock equivalent is fabricated from it.

Validation: existing race tests, exact percentage/allocation and formatters, target choice, barriers changed, missing race, zero/negative risk leg and weak-stop cases.

## OPT-PRES-08 — Preserve method plus explicit target choice and summary

Acceptance:
- Relocate the existing MethodPickSelector after method evidence, keeping all four methods, disabled reasons, Clear, target-row selector and Judged on stock/premium basis.
- Method choice alone does not choose a row; changing method clears row prices per current behavior. Arithmetic target row is a returned R:R row; Monte Carlo is a returned target percentage row. Barrier Race Use target records method and row together, preserving stopBasis.
- Reuse existing rowStockPrice/rowOptionPrice mappings and applyMethodPick; never put an option premium into a stock target. Arithmetic/ladder carry stock-row prices; Monte Carlo can carry both; race carries option premium and null stock price. Do not expand the persisted MethodPick schema.
- Summary explicitly shows chosen method and target, relevant premium/stock price, time/probability and quantity with actual basis, followed by actual execution fields. When only a method is selected label target not selected; preserve current selection/order-gate behavior rather than adding a new gate.
- Distinguish latest-calculation fallback from explicit choice; keep timestamps, invalidated/unavailable/restored states, stop-basis explanation and both independent alerts. Selection records a decision; it does not run/apply calculations or synchronize order fields.
- Pricing-model labels reflect the actual source per result: Heston repriced, BS repriced (IV-derived), Delta approximation or unavailable; labels are not method selectors. Do not attach a model label to a snapshot lacking that evidence.

Validation: existing selector and downstream execution/session tests; method-only, row change, method change, Clear, basis change, stale result/candidate transitions and premium-versus-stock mapping regression.

## OPT-PRES-09 — Preserve ladder, broker actions and feedback

Acceptance:
- Initial ladder near the top has its real provenance; restored selections/results retain theirs. Keep existing editable stock target controls, premium estimates, authoritative/local-edit R:R, pricing badge, statuses, edited flags, quantities and scale-out notes. No new estimate run on edits.
- Avoid creating duplicate independent ladders: one underlying state/control set, reused read-only summary if needed. Dollar outcome distinguishes full-position exit from per-rung allocation; never imply cumulative profit by adding alternative target outcomes.
- Keep current Options action set: Track basket/dialog, chart, JSON export, actual BrokerPicker states and direct Place Limit/Right Now Market actions; applicable AutoTradeArm controls and all gates remain.
- Keep live quotes/identifier, save/basket/order/direct-note errors/warnings, re-anchored-stop disclosures, Remove/status actions and portfolio-tracking feedback/link. Required warnings remain visible beside their actions and outside unrelated broker-selection gates where currently required.
- Keep the existing context rail's checklist, historical analogs/unavailable, watchlist, portfolio and data-source statuses. Fit broker labels without fragmented wrapping.

Validation: existing basket/direct-send/auto-trade and warnings tests; broker configured/unconfigured, missing pick/stop, unknown/rejected earnings, bearish unvalidated, unavailable plan and quote warning states. Browser verification is observation only: never place broker orders for visual testing.

## OPT-PRES-10 — Preservation verification and independent code gate

Depends on 01–09. This ticket is a verification gate, not permission to change trading behavior.

- Reconcile every row in options-preservation-checklist.md with the final implementation: original field/action, new location, default visibility, units/basis, unchanged handler and conditional states. Include child components/dialogs/context rail; absence in one live screenshot is not proof a feature is absent.
- Compare same saved fixture/state before and after; numeric values, method picks, requests, stop resolution and persisted shapes must agree. New display-only dollar derivations must use matched original source/quantity/multiplier with rounding consistent with existing formatters; when a meaningful amount cannot be derived, show unavailable instead of inventing it. Do not add these amounts to orders or persistence.
- Run typecheck before every commit, relevant existing frontend tests and focused request/mapping regression coverage. Backend tests only when needed to validate claims, with Python 3.11 verified; no backend implementation changes here.
- Verify readable labels, keyboard disclosure/selection, contrast, current density/themes and supported desktop widths. Preserve the 1200px gate and existing app shell.
- Fresh independent code audit under K-adversarial-audit-loop and project numeric/persistence gate is required before implementation can be called done. Plan audit does not clear code shipping. Three-round cap per stage; keep unresolved findings and unaudited state if cap reached or independent review unavailable.

## Proposed execution order

01–03 establish basis/inputs; 04 establishes the structural presentation; 05–07 reorganize methods; 08 wires unchanged selection; 09 preserves actions/ladder/context; 10 verifies final integration. Shared TradeCard/page changes are serialized. Split further if implementation/audit scope becomes too large.
