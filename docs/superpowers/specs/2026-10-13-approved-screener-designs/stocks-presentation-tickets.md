# Stocks position presentation — locked design, implementation tickets

12 October 2026. The user approved preserving the recovered Options and Stocks designs in tickets. Local ticket register; not published GitHub issues. No application implementation in this session. Plan audit pending in stocks-ticket-audit.md. Approved layout authority: stocks-position-preview.html, frozen by design-lock.json. Example numbers, abbreviated disclosures and mock handlers are NOT implementation authority.

## Controlling contract

Use this reading order: context → initial strategy targets → editable order inputs → Structure & Stops → stacked calculation methods → selected plan → actions. Stock target prices and dollar profit lead. Preserve every existing field, conditional disclosure, control, request, validation, warning, numerical source, selection effect, execution gate and persistence behavior. No formula, strategy, risk, ranking or broker behavior change. Stocks have no option strike/premium stop or Heston pricing label. Supporting stock target/stop races are not a new selectable method.

Before implementation read state and claims, claim the applicable task, inventory current sources and resolve overlapping ownership. Primary references: frontend/components/organisms/StockPositionCard/index.tsx; frontend/app/(frame)/screener/step-7-position-card/page.tsx; frontend/lib/stockExecutionSession.ts; frontend/lib/cardEdits.ts; frontend/lib/scanStore.ts; frontend/types/stockDomain.ts; MethodPickSelector and existing child components; corresponding API endpoints and backend stock estimate/plan schemas. Verify source mappings against current code rather than copying mock values. Implement serial small stages with separate plan/code audits and three-round cap per stage. These external drafts do not require a code claim or mutate the repository.

## STK-PRES-01 — Context and initial ladder

- Preserve frame/navigation/context rail, candidate navigation, pin/basket and selected card identity. Use project primitives, CSS Modules and global theme tokens; no shadows. Preserve supported width behavior.
- Context includes symbol/company, price, direction, strategy/horizon, stock score, qualification, sentiment and fundamentals where actually available. Retain complete component/backtest/fundamental evidence, source labels and warnings in accessible disclosures. No invented score, probability or PASS for missing data.
- Show original strategy ladder separately from editable execution targets and calculated plans. Preserve current actual source and distinction. For each target show stock price, reward/share, direction-aware return/R:R where already supplied or truthfully derived, full-position outcome and allocated outcome only if allocation exists. Do not introduce allocation controls or assume allocation support from the illustration; omit or explicitly mark unavailable where the live implementation lacks it. Distinguish full-exit scenarios from partial allocations; never sum mutually exclusive full exits. No probability/time before calculation.
- Acceptance: bullish and bearish cards, missing evidence, zero versus absent, navigation and restored legacy cards retain all current information and correct identity.

## STK-PRES-02 — Inputs, validation and reactive execution risk

- Reuse existing execution overlay and controls for entry/stop/shares/T1–T3 plus any existing allocation controls. Preserve rounding, range checks, direction validity, sizing, risk/concentration warnings and actions. Inventory child content before moving it.
- Position value and execution risk/share/position must use current entered quantities and authoritative current direction/stop basis. No mixing suggested plan shares with entered shares.
- Keep current dependency-specific invalidation exactly: existing estimate, plan and structural keys/request revisions define what becomes stale. Do not copy the preview's blanket invalidation on every input; quantity-only edits must follow live source semantics. Ignore aborted/late responses and results from another symbol, run or execution identity.
- Acceptance: entry, stop, target and quantity edits; invalid values; navigation during pending calls; reordered responses. Existing method/target clearing and execution gates remain enforced.

## STK-PRES-03 — Structure & Stops, distinct bases

- Show editable execution stop and Arithmetic's separately calculated final stop side by side when available, with matching risk/share and dollar loss for clearly labelled entered or suggested quantities. Structural level/source, ATR floor, final-stop source, widening/snap/check results and existing safety disclosures remain accessible.
- Never overwrite execution stop by selecting Arithmetic or checking structure. Never label a structural candidate as the final stop. Missing/uncomputed/error/stale states must stay explicit; a stale result cannot drive the current order or summary.
- Reuse existing Check structure/Compute controls and their actual requests/guards. Preserve current errors and positive/negative risk interpretation for both directions.
- Acceptance: structural versus ATR-derived final stop, mismatch with execution stop, absent data and invalidated results; before/after broker payload parity.

## STK-PRES-04 — Stacked Original, Arithmetic and Monte Carlo evidence

- Show all existing method content stacked, preserving actual controls and ordering semantics. Original uses the existing original-method source. Arithmetic keeps its own final stop/targets/geometry, sizing budget/suggested shares and Apply shares action; Apply shares retains its actual quantity-only behavior.
- Monte Carlo stock estimate uses the current execution entry/stop/targets and source-defined model/horizon. Preserve target and stop probabilities/times, model/window caveats and errors. Label actual backend time units and statistic; do not replace expected time with median or calendar with trading days by assumption.
- Arithmetic target rows share the returned final stop. Preserve actual target/R:R, snap/quality evidence, stop/target probabilities/timing, risk sizing and concentration checks. Source-supplied races show target first / stock stop first / neither with their exact definitions; no premium barrier for shares.
- Independent hit probabilities are not target-before-stop probabilities. Do not invent a stock race for a source that lacks it, rescale probabilities, or derive a best-trade verdict. Never put Heston/Black-Scholes on stock outputs.
- Acceptance: returned schema parity, both directions, unavailable/failed/stale estimates, timing labels and full evidence inventory against source.

## STK-PRES-05 — Explicit method/target and selected summary

- Reuse existing MethodPickSelector, card-edit writes, method IDs and row identity. User chooses method and explicit target; unavailable methods/rows remain unavailable. Selection records intent, does not automatically apply a stop/target/share change or place an order.
- Summary identifies selected method/target, actual stock price, calculation stop basis, execution stop, quantity and direction-aware outcome, with probability/time only from a matching current result and exact units/definition. Preserve any existing summary fields and freshness warnings.
- Keep per-symbol/per-scan persistence and row disappearance checks. Ignore late responses after edits/new run/navigation. Preserve reload, migration, same-version sanitization and original storage keys; version/migration required for any breaking persisted shape. Do not persist ephemeral numerical estimates just to restore a selected label.
- Acceptance: method change, explicit row pick, result invalidation, new scan, symbol change, older stored picks and reload do not send stale/mismatched picks.

## STK-PRES-06 — Actions and execution safety

- Preserve chart, pin/basket, Add to Portfolio, Recommendation/broker modes, actual available brokers, order preview/confirmation, market/limit, auto-trade and execution feedback. Inventory conditional child content and disabled states; simplified mock controls are not the live inventory.
- Keep research-only/unvalidated refusal and every confidence/regime/risk/position/broker gate. No preview validation or method choice overrides them. Preserve actual order entry/stop/targets/shares and selected-field payloads.
- Acceptance: action payload parity for bullish/bearish cards, blocked execution, duplicate click/in-flight handling and existing feedback paths.

## STK-PRES-07 — Saved scan report integration

- Adopt scan-log-isolation-tickets.md LOG-01–03 as required prerequisites for new durable diagnostics. Independent latest reports for Options, Stocks, Pre-Breakout, Pullback and Fib; another category's scan never overwrites a report. Category captured at dispatch; same-category ordering follows audited server run identity.
- Inspector opens saved run/settings/outcomes without scanning. Parameter changes may affect visible candidates as today but never erase the saved report. Missing diagnostics are unavailable, not zero failures. Backend system lookup and UI use the same report identity. Do not mix StockPipeline with OptionsPipeline.
- Acceptance: five categories, mode changes/reload/restart, same-category replacement and out-of-order completion; source-specific failed/cancelled/partial states. This is a separate functional persistence stage, not completed by the mockup.

## STK-PRES-08 — Preservation crosswalk and release gate

- Create a source-to-destination inventory for every control, field, conditional warning/disclosure, request, source, selection write, cache guard and persistence path. Mock placeholders cannot count as covered content.
- Focused meaningful tests for field/source/units, invalidation and response races, selection/persistence and broker payload parity; frontend typecheck before every commit. Any backend tests use verified Python 3.11; never regenerate numerical golden pins for runtime drift.
- Fresh independent adversarial review per implementation stage: wrong displayed number/order or corrupted persistence gate, three rounds maximum, later rounds only prior fixes/interactions. Record exact diff/hash, reviewer, findings/fixes and remaining findings. Plan audit is not implementation audit. No done/merge claim before clean code audit.

## Delivery

STK-PRES-01/02/03 → 04/05 → 06. Crosswalk throughout. STK-PRES-07 follows separately audited LOG contracts. Frozen design may be changed only by explicit new user feedback recorded as an amendment; numeric and behavior correctness always follow live sources.
