# Trade card presentation implementation plan

Status: draft for independent plan audit. No production implementation is authorised by this document. User requested the next-step plan and audit; this task ends with an audited plan and corrected preview.

Baseline: repository HEAD `1c8b94ffb9bd177f68d9383423aaa10e7e2065df`, inspected 2026-10-03. Approved visual reference: `preview.html`, revision 02, plus the latest correction that Bullish must remain green. Information inventory: `information-mapping.md` / `mapping.json` (520 entries). Those entries are an inventory, not proof of runtime preservation; every slice must reconcile its affected entries with the real source and tests. The local production server is unavailable and there is no populated user scan session in this workspace.

## Accepted design and scope

1. A slim Market Sentiment card directly below How this page works and above candidate navigation.
2. Stock and readable option identity together, including original identifier, scores, confidence, direction, status and edited indicator.
3. Slim Fundamental Health directly beneath the stock/option header, with all score buckets, explanations and safety flags retained.
4. Handling information prominent: original order fields, exit fields, actual monitoring caveats, latest calculation and existing explicit method choice. Model outputs and editable execution values must be labelled separately.
5. Arithmetic and Monte Carlo results side by side when the available content width allows, otherwise stacked. Probability/time cells have a dedicated column and left padding/divider.
6. Visible Max loss budget and Set/Edit override action. The existing editor and calculations remain authoritative.
7. Barrier Race shows target, option target, all four first-outcome percentages, conditional target time, stock-stop R:R and edge/contract together. Other conditional medians, full chains and explanations remain directly expandable.
8. Qualification shows every current factor, observation, score, weight/contribution where verified, thresholds and gate reasons. Backtested setup confidence has a visible history/payoff explanation and preserves its existing per-symbol text and no-data behaviour.
9. Preserve existing gate, score, warning, direction and risk colours in both themes. Do not copy neutral prototype badges into production.
10. Preserve every input, control, conditional section, refusal, explanation and original payload. No scoring, sizing, pricing, stop, target, monitoring, booking or post-purchase logic changes.

## Non-negotiable behaviour contracts

- `TradeCard` remains the owner of overlays, touched/edited flags, request refs, freshness guards, timestamps and calculation state. Do not move it out of its current lifecycle or create another mounted TradeCard for a side panel. Presentational extraction is acceptable only with controlled props; no new derived state copies.
- `lastRunMethod` chooses the latest-calculation display. `methodPick` is a separate recorded decision. Preserve no default selected method, method-only selection, optional row, clear action, stop basis and invalidation of stale selections.
- Preserve existing `methodPickOptions` mappings: Arithmetic and Ladder rows are stock-price values; Monte Carlo has distinct stock/option values; Barrier Race has option value and null stock value. Never put the displayed option premium into `resolvedTpPrice` or a stock alert target.
- Judged on records a basis; it does not select which alerts fire. Both stock and premium monitoring retain current semantics.
- Invalidation remains the real editable/send/booking field. Its missing-value block survives even when a calculated Arithmetic stop exists. Preserve current validation and edit/revert bounds. The current source's prose about a fixed-% stop is not evidence of the current mechanism; `exit.invalidation` is scan-resolved structural/ATR with documented legacy fallback. Preserve the original explanatory text access, but use accurate source-based labels around it; do not introduce a new stop calculation.
- Premium stop editable value is loss dollars/share. The simulated option stop threshold is different. Keep pinned/global/small-mid/drop notices and fill-time re-anchoring unchanged.
- Arithmetic size Apply only patches contracts and remains disabled below one contract; never repurpose it to apply a model stop. Preserve exact fractional size and existing recommended whole size.
- Price-today Arithmetic loss and simulation-timing race loss are different bases. Preserve both original formatter outputs and their explanations; no shared loss calculator or arithmetic from rounded printed figures.
- `BarrierRaceCard` keeps null/undefined/fresh/changed-barrier distinctions. Reuse existing `weightPercents`, `formatRaceRisk`, `formatRaceRR`, `formatRacePremiumRR`, `formatRaceEdge`, `days`, `money` and stock/premium-source helpers. Preserve raw shares for bar widths versus allocated weights for displayed percentages and edge arithmetic.
- No added Barrier Race gate. A red losing segment is an outcome colour, not a REJECT verdict. Preserve generic-IV fallback and stock-stop-under-1% warnings outside collapsed explanations.
- Preserve current Tracking versus broker order separation. Tracking reserves contract/symbol and makes no broker order. Keep existing booking-before-order, duplicate, earnings, missing-pick/stop, broker refusal, save/sync/retry and auto-trade behaviour.
- New detail disclosures must not unmount stateful editors or suppress active refusals, warnings, live regions or actionable notices. Prefer native details that leave content mounted; preserve the existing Ladder collapse storage key and semantics rather than replacing that persisted component.
- Use production token colours and existing StatusBadge, SymbolHeader direction pills, ScoreBar, ConfidenceBadge and status/tone helpers. PASS green, CAUTION amber, REJECT red, PENDING/NO_DATA existing neutral; Bullish uses `--pass`, Bearish `--reject`. Status labels and values must remain server/helper supplied. Do not recolour all composite scores with one threshold set.

## Delivery structure: seven sequential, independently reviewable slices

Work is sequential because several slices touch the same TradeCard render block. Claim the task with the repository claim script before production edits, honour other active claims, recheck baseline drift, and use an isolated branch. No bulk rewrite of the 3,888-line TradeCard. Target roughly 500 changed implementation lines per reviewed slice; split a slice further if necessary, without bypassing the three-round audit cap. Each slice is a review checkpoint, not an automatic deploy or merge.

### Slice 1 — Traceable score evidence (read-only metadata prerequisite)

Problem: TradeCard currently has factor scores and observation text, but not enough provenance to prove the exact scan-time weights, component contributions, effective thresholds or all demotion reasons. Screenshot totals do not match current default-weight arithmetic. Never infer the original rules from today's YAML or frontend Settings.

First trace actual producers: `backend/app/scoring/stock_scorer.py`, `contract_validator.py`, scan result schemas, card construction in `backend/app/routers/scan.py`, contract recompute in `backend/app/routers/contracts.py`, and `frontend/types/domain.ts` / `tradeCardOverride.ts` / `scanStore.ts`. Resolve real model names before editing.

Expose additive optional display metadata captured alongside each authoritative scoring result: effective factor weight; unrounded weighted contribution or documented contribution absence; authoritative composite and component thresholds; existing raw-band verdict and actual gate/demotion reasons; provenance for horizon/override/config used. Hard-rejected scores need an explicit rejection reason rather than a fictional contribution sum. Use the same existing resolved config objects and RuleResults that produced the result, not a second YAML fetch. This metadata must not enter request decisions, score calculations, broker payloads or gate comparators.

Thread it through the actual card/scan producer, Step-6 override/recompute and client snapshot path without replacing unrelated stock/contract metadata. A new contract must never inherit the old contract's evidence. Optional fields on older persisted cards render 'not captured — re-run scan' while preserving every original score and verdict. Do not require a store migration solely for optional absent fields; if persistence shape changes require migration, follow the repository versioned migration convention and test retained user data.

Acceptance: existing numerical golden outputs remain identical. New metadata reconciles with authoritative score including server rounding, hard-reject/soft-fail and cap paths; weights/thresholds reflect actual resolved rules. Override tests prove no cross-contract evidence leakage. Missing history/config/evidence never renders a guessed PASS or fabricated contribution. Keep frontend display changes for Slice 6.

Verification: relevant backend scorer/scan/recompute and config override tests with prepared Python 3.11; frontend typecheck and snapshot/override tests. Independent code audit covers numerical parity, metadata vintage and persisted-data compatibility. Freeze an exact slice diff before audit.

### Slice 2 — Identity, slim context cards and colours

Files: Step-7 page, TradeCard render/CSS, MarketSentiment, FundamentalHealthCard (their CSS or opt-in compact variant), supporting identity presentation. Avoid global theme or shared default-layout changes.

Move the existing MarketSentiment node to the page's required position using the active effective card, with the same missing/insufficient behaviour. Remove its old instance so it appears once. Keep sentiment changes tied to candidate changes. Place existing FundamentalHealthCard immediately beneath the stock/option identity inside the same card lifetime. If shared molecules need a compact prop, default remains unchanged for other callers. Keep score explanations, flags and all sentiment statistics accessible. Identity may promote already supplied score facts, not calculate new ones.

Reuse existing green/red direction pills; any new badges receive supplied status. The top MarketSentiment may use an explicit display slot if needed but not a second card controller. Candidate navigation, basket, edited fields, identifier and chart links remain wired to current handlers.

Acceptance: correct card order; all original context information reachable; no duplicated card/state or context requests. Bullish green/Bearish red and every gate status retains colour in light/dark themes. Shared callers retain their default layout.

Verification: targeted TradeCard/page and compact context render checks, typecheck, browser screenshots at 1920 and 1366 viewport widths with the real frame/context rail. Missing sentiment, safety flags, Bullish/Bearish and unknown states included.

### Slice 3 — Handling fields and latest-calculation summary

Files: TradeCard render/CSS and presentation-only wrappers. Parent callbacks, send builders, API calls, request/effect state and persistence unchanged.

Promote existing Order Entry and Exit Plan fields and existing Final Recommendation display near top. Render each editable field once with its original component instance, bounds, touched/revert semantics, null state, validation live region and callback. Keep Max fill read-only and Time exit from TIME_STOP_DTE. Label model stops as calculated/simulated, distinct from the booked invalidation/premium fields. Do not seed edits from the latest calculation.

Move the existing final-status badge and lastRunMethod body without rewriting its branches: Arithmetic, fresh/stale Monte Carlo, race details and no-run Ladder default. Keep model-monitoring and expiry/timing caveats visible with affected values. Summary has exactly the values permitted by original freshness checks; no placeholder reference data from the mock.

Acceptance: edits and reverted values produce byte-equivalent outbound values to baseline; navigating candidates preserves current cache/touched behaviour; missing invalidation and unavailable calculation states remain visible and order-blocking. Latest calculation and method choice remain distinct.

Verification: existing edited-fields-sync, rr-overrides-from-scan, contracts-sync, TradeCard methodPick/P2 suites; add a behavioural preservation assertion only where rearrangement creates a real regression risk. Typecheck and populated-session smoke for no-run, Arithmetic, Monte Carlo and changed/restored states.

### Slice 4 — Method result hierarchy and directly visible override

Files: Arithmetic/Monte Carlo/Ladder presentation in TradeCard and its CSS; controlled molecules only if extraction reduces review complexity.

Keep separate Check structure, Compute Arithmetic Plan and Run Monte Carlo Estimate actions and their original handlers, loading, disabling and failures. No unified Run All button or automatic simulation. Each method promotes its current actionable results, keeps independence note, expands explanatory geometry/pricing chains inline and preserves all current row fields.

Reuse MaxLossOverrideEditor. Put its Set/Edit override and actual max-loss budget outside explanatory disclosures, with the same per-card override callbacks, percent/dollar validation, Apply and Use default. Demo override editor is not production code. Keep recommended quantity Apply separate and visibly disabled for zero contracts.

Probability/time column uses a dedicated minimum width, extra gap/left padding and border; both methods use matching spacing, not a font-size reduction. Method cards stack based on usable content width, accounting for the frame/rail. Preserve editable Ladder rows, pricing, R:R, contracts-to-sell and single-contract warning and the existing collapse key.

Acceptance: every mapped method field retained; structure/ATR target warnings visible; no changes to quantities, max-loss override or pricing bases; probability/time never clips the card at supported widths; Set override is visible without opening details.

Verification: existing TradeCard tests, risk/override tests and responsive populated card screenshots (two-column and stacked). Check overriding/reverting budget, zero-size Apply, structure unavailable/error, scan-only stop, target geometry warning and editable Ladder rows.

### Slice 5 — Barrier Race comparison and decision shortcut

Files: BarrierRaceCard render/CSS/tests, TradeCard controlled prop wiring, MethodPickSelector only if necessary for presentation.

Rearrange outputs of existing formatters: every row includes target %/option price, split, four outcome shares, conditional target median, stock-stop R:R and edge/contract. Preserve other medians and complete chains within inline row/detail disclosure; identify medians as conditional. Keep barrier levels/source, standalone invalidation touch statistic and its own median, sampling count, IV/timing and commission assumptions. Active fallback and weak-stock-stop warnings always visible.

If adding 'Select row' next to a race outcome, call the exact existing method-and-row decision path. Build the row from the same `methodPickOptions` data; only enable when that option's `unavailable` is null. Set method barrier_race, rowStockPrice null, rowOptionPrice the original outcome option price, preserve existing stopBasis (stock default on first pick) and timestamp as current selector does. Do not infer a stock target, enable orders, change latestRunMethod, or change stop monitoring. Optional row selection remains optional; sidebar selection is not another state owner.

Keep original early-return branches and race freshness/changed-barrier guards before any new values or callbacks render. When premium stop alone changes, preserve standalone invalidation statistic as existing logic permits; when stock stop changes, suppress it as currently required. A retained snapshot must not leak during candidate/contract transition.

Acceptance: printed shares and edge chains agree, including allocation edge cases; simulated expiry refusal distinct from not run; no stale or mixed-contract results; shortcut selection equals existing selector outputs, preserving target units and optional row semantics.

Verification: existing BarrierRaceCard, barrierRace helper, TradeCard.methodPick and direct-send tests; add shortcut payload/state-transition test. Browser inspect premium-only versus stock-stop change, contract navigation, same-row click, clear, no IV solution and median-null values.

### Slice 6 — Qualification and interpretation

Files: TradeCard scorecard presentation, ScoreCardPanel via opt-in variant or dedicated controlled molecules, statusTooltip presentation and evidence types from Slice 1. Shared scoring functions and statuses unchanged.

Render every existing factor/observation/score and add effective weight and contribution from Slice-1 authoritative metadata. Separate raw composite score, server verdict, backtested confidence and pre-trade checklist; different thresholds are not harmonised. Preserve existing factor bar colours from their current helper, even when adjacent verdict uses another rule. Raw stock 55/35 and contract 65/45 are default rules only; display actual metadata when known and label defaults as defaults when old cards lack provenance.

Title confidence 'Backtested setup confidence'. Visible short text: 'Based on historical entry signals, adjusted for favourable versus adverse move size. This is a confidence score, not this contract’s predicted chance of profit.' Keep per-symbol confidenceText, sample count where supplied, original tooltip and insufficient-history states. Do not relabel an adjusted score as measured win rate.

Existing checklist remains computed from published effectiveCard via tradeCardUiStore. Avoid reproducing its comparisons in score components. If changing location to the decision rail requires composition, retain the parallel-route lifecycle/provider and existing evaluator, statuses, config override handling and warnings. Historical analogs, Quick Look and Data Sources remain available.

Acceptance: score decomposition reconciles where evidence exists; missing provenance honest; no new gate or strength recommendation; historical confidence and Monte Carlo probabilities visually distinct; original checklist threshold differences remain accurate.

Verification: existing checklist rail, ScoreCardPanel, confidenceText and threshold suites; tests for raw PASS capped by a gate, contract hard rejection, missing confidence/evidence, IV rank versus absolute IV, Step-6 override, earnings unknown/ETF, and defaults-versus-effective provenance.

### Slice 7 — Execution layout and final information reconciliation

Files: Step-7 page layout/CSS and presentation slots only; TradeCard controlled callbacks. Keep broker/booking implementations intact.

Place existing single MethodPickSelector and existing execution components in the adjacent panel at wide content widths. Use a single DOM instance per control and responsive grid, not separate desktop/laptop render trees. On laptop allow the decision panel to remain alongside stacked methods when sufficient width, otherwise flow inline. Do not relocate AutoTradeArm in a way that remounts/clears armed state. Preserve current BrokerPicker configured/disabled reasons, Place Limit/Market, Tracking dialog, pinned basket, per-broker notices and external feedback region.

Feedback must remain visible regardless of broker selection when current source renders it that way. No existing submit or warning is buried in collapsed details. Dialog/auto-trade contents remain the original components; no reproduction of demo stub buttons. Keep chart/exports/recommendation ID, alternatives/spread sections and Quick Look accessible.

Reconcile all 520 inventory entries against populated source states and record exact live destination plus evidence (screenshot/test/state). Correct inventory errors rather than asserting count is proof. Run full frontend regression/typecheck/build once after the last slice, plus backend parity if Slice 1 changed backend. Do not rerun all suites for every cosmetic slice without a failure reason.

Acceptance: same send/arm/save payloads and blockers; single-instance lifecycle; all information retained, active warnings visible, keyboard/focus/disclosures usable, laptop/desktop no page overflow in both themes. Current global 1200px minimum-width gate remains; check 1200, 1366, 1440 and 1920 with real frame, side rail and browser zoom. Internal table scrolling is permitted for expanded evidence, not clipping essential actions or outcome columns.

## Audit and validation workflow

Plan stage: fresh independent reviewer invokes `.claude/skills/bmad-review-adversarial-general/SKILL.md` against this exact document and real source. The PROJECT_STATE audit_rule governs: count only reachable wrong-user-number, wrong-order-number, persisted-data corruption, or a mechanism claim that would induce such a wrong change. Do not pad ten findings with cosmetics. Review full plan in round 1; later rounds review only fixes and their interactions. Max three rounds for this plan stage. Preserve each exact plan revision, findings, fixes, reviewer ID, scope and unresolved items in `plan-audit.md`. One verified zero-gate-findings round closes plan audit.

Code stage later: each slice has a frozen diff and its own fresh independent audit and meaningful tests. Do not label plan approval as code approval. Stop at cap and report unresolved findings; no automatic merging, deploying or placing orders. Before implementation, rebase the plan against current HEAD and active claims, then retain evidence that calculations/payloads remain baseline-equivalent.

Visual acceptance is separate: direction/gate colours, slim-card positions, probability column spacing and complete information preservation are explicit user requirements even if not numerical audit findings. Check them in screenshots and reconciliation, not by lowering the numerical audit gate.

## Completion criteria

An audited plan means the document passed the plan stage; it is not an implemented or shipped design. Production completion requires all seven slices, code audits, preservation reconciliation, numerical/order/persistence parity and visual acceptance. If exact score provenance cannot be supplied by Slice 1 without changing calculations or inventing data, stop that evidence work with an explicit unavailable state and report the missing acceptance item; do not silently ship a false score explanation or claim the whole redesign complete.
