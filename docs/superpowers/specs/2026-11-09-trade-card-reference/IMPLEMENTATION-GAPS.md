# Implemented trade card versus agreed reference: independent design comparison

Reviewed source: frozen main `86982b583b35dcca39fafac4eaa966bbfc2e916b` in the isolated review checkout, including merged PR #594. Compared with conversation decisions and `trade-card-v6.html`. This is a design-gap review, not a new production numerical/persistence audit. No application files changed. A reference preview contains illustrative values and some fixed inputs; those are not numerical specifications.

Evidence classes: **Source-confirmed** means inspected current JSX/CSS/control state. **Archived render corroboration** means the checked-in mocked Chromium evidence from the implementing phase was viewed; it is not a newly run browser capture of current main. Do not describe archived images as mini-PC screenshots. The existing 1366-dark-calculated capture visually corroborates the long, dense and separated result/review flow.

## Confirmed amendments

### D01 — Start with Monte Carlo only and make comparison explicit
- Location: `frontend/components/organisms/TradeCard/index.tsx:626`, `frontend/components/molecules/MethodCompareSelector/index.tsx:15` and `TradeCard/index.tsx:3109`.
- Trigger: open a fresh card.
- Current: comparedMethods initializes all three; canonical order is Arithmetic, Monte Carlo, Ladder; Arithmetic is the first rendered method. Existing checkboxes mean the user immediately sees comparison rather than a focused primary method.
- Required: Monte Carlo is the primary/default view, Arithmetic and Ladder open on demand; entering Compare must retain calculated results and never run/select/apply a method. Keep ability to compare all three.
- Why it matters: the initial page remains crowded despite the user's explicit normal-use preference.
- Evidence: source-confirmed; archived render corroboration. Amendment order: first-pass layout.

### D02 — Match the requested large contract identity
- Location: `TradeCard/index.tsx:2456` (18px strike/right), `:2457` (14px expiry); `TradeCard.module.css:734`.
- Trigger: identify a contract at normal desktop viewing distance.
- Current: strike/right is 18px, expiry 14px. These are larger than the old 11px text but much smaller than the accepted preview (about 30px strike/right, 25px expiry), which puts contract identity on the same hierarchy as the ticker.
- Required: use the durable reference's prominent strike/right and expiry sizing, preserving clear year and wrap behavior. Keep raw contract ID as secondary evidence.
- Evidence: source-confirmed. Amendment order: first-pass identity.

### D03 — Restore the agreed reading order instead of preceding results with the full order/budget block
- Location: `TradeCard/index.tsx:2611` Order inputs & risk budget; `:2874` Structure & Stops; `:3097` Profit-target methods.
- Trigger: trader wants invalidation, TP, time and probability after opening.
- Current: Order Entry, Exit Plan, a full sizing/budget card, and a standalone structure section precede the method results. Stock/contract score expansion also precedes them.
- Required: identity/details → collapsed Stock Qualification → compact shared Exit Plan → method essentials → entry/size → consistent decision review/actions; explanatory qualification/geometry follows or expands in place.
- Why: all desired values exist, but the user must traverse substantial unrelated material to reach the target evidence.
- Evidence: source-confirmed and archived render corroboration. Amendment order: first-pass layout.

### D04 — Keep numeric essentials in Exit Plan; move explanatory/quantity-basis prose behind its default-closed disclosure
- Location: `TradeCard/index.tsx:2676–2795`.
- Trigger: view Exit Plan without opening explanation.
- Current: inline time-exit explanatory paragraph, eight premium-basis/loss/remaining-value KV rows, and cost/assumption text remain visible. Only the later resolution paragraphs are inside details.
- Required: visible invalidation, premium-loss input, loss percentage, succinct remaining value/per-contract loss and readable time threshold. Put detailed basis descriptions, quantity breakdown and time/ATR/structure explanation into the closed explanation; preserve conditional actionable warnings outside.
- This does not mean deleting the user's requested loss/remaining-value figures.
- Evidence: source-confirmed. Amendment order: first-pass density.

### D05 — Fold standalone Structure & Stops back into the associated explanations and result contexts
- Location: `TradeCard/index.tsx:2874–3090`.
- Trigger: card has scan, Arithmetic or structural results.
- Current: large full-width Structure & Stops repeats execution invalidation, final stop, Arithmetic contract valuation, standalone structure lookup and stop-cost detail before methods.
- Required: keep shared settings once; put source geometry under shared Exit Plan and/or relevant method disclosure; retain Check structure action and its distinct source as expandable evidence. Do not fuse distinct pricing bases or copy the raw structure into execution settings.
- Evidence: source-confirmed; archived render shows the full-width block. Amendment order: first-pass density.

### D06 — Move model-specific basis/provenance explanation out of the default method view
- Location: Arithmetic `TradeCard/index.tsx:3119–3141`; Monte Carlo `:3205–3241`; Ladder `:3373–3400`.
- Trigger: open a method.
- Current: long current-versus-saved-input explanations, formula text, model names, horizon settings, risk qualification and repeated contract references precede targets. Most use 10–11px type and remain always visible.
- Required: keep brief source/units and the key stop results visible; move complete prose, formulas, provenance and extra model settings into the relevant explanation expansion. Never hide stale/invalid result warnings or caveats that materially qualify visible numbers.
- Evidence: source-confirmed and archived render corroboration. Amendment order: core readability.

### D07 — Use compact target tables with consistent columns
- Location: Arithmetic target comparison `TradeCard/index.tsx:3153–3194`; MC ProfitTargetRow and Ladder EditableTargetRow; `TradeCard.module.css:646` resultColumns.
- Trigger: compare TP, probability and time across rows/models.
- Current: target results are repeated nested KV cards with repeated labels and explanatory rows; matching field keys do not create the agreed compact table layout.
- Required: a consistent main column order (target, stock price, option value, existing probability, conditional time, existing quantity-based outcome where available); method-specific geometry/model/allocation details expand. Keep Not supplied for genuinely missing probability/time and preserve full-position versus rung outcomes.
- Evidence: source-confirmed and archived render corroboration. Amendment order: core readability.

### D08 — Put Monte Carlo's actual stop consequence beside its barriers
- Location: `TradeCard/index.tsx:3226–3238`; companion `BarrierRaceCard` call `:3451` and its risk-chain disclosure.
- Trigger: inspect Monte Carlo stop context after a fresh run.
- Current: main MC stop slot shows the two race barriers, then repeats actual Exit Plan invalidation and premium-loss settings. It does not put the requested race remaining option value/loss beside those barriers; the reader must find the separate race risk chain.
- Required: visible stock input, option-price input, race value at stock stop, race loss at stock stop with barrier-time basis. Keep the source difference as a concise note/link to shared Exit Plan instead of another full actual-settings block. Apply current race freshness/hide rules to all moved race-derived values.
- Evidence: source-confirmed. Amendment order: key decision evidence.

### D09 — Nest the graphical Barrier Race under Monte Carlo
- Location: `TradeCard/index.tsx:3451`; `BarrierRaceCard/index.tsx:177–179` returns an ordinary section.
- Trigger: after MC computation, inspect normal page or compare methods.
- Current: BarrierRaceCard is a separate full-width sibling after the entire method grid, not a closed expansion inside MC. It can be far below the MC card, particularly when Ladder wraps onto the next row.
- Required: Monte Carlo → Barrier Race graphical outcomes & details, default closed, containing existing bars/table/controls and deeper risk explanations. Keep warnings visible when affected figures are visible, and preserve all existing target-selection behaviors.
- Evidence: source-confirmed and archived render corroboration. Amendment order: key flow.

### D10 — Remove the retained Final Recommendation duplicate result summary
- Location: `TradeCard/index.tsx:3482–3650` (section begins at 3481; selected-result evidence plus further all-target summaries).
- Trigger: run or choose a method.
- Current: Final Recommendation still repeats chosen/latest method results, then the method's stop/target rows and race edge readouts. This was explicitly removed from the proposed reading flow to avoid “which figure is authoritative?” confusion.
- Required: retain final status in identity and one selected-target review near decisions/actions; move unique context into that review or originating method. Do not retain another full latest/all-target results section. Preserve current method/target selection semantics and source/freshness validation.
- Evidence: source-confirmed. Amendment order: remove duplication.

### D11 — Bring method/target selection and the compact selected-target review together
- Location: `TradeCard/index.tsx:3491–3492` portals methodSelector to decisionTarget; `:3539` embeds SubmissionReview in Final Recommendation; `step-7-trade-card/page.tsx:1719` decision/execution area.
- Trigger: select one of three MC/two Arithmetic targets and verify TP/time/quantity outcome before choosing tracking/broker destination.
- Current: method selector lives in the execution rail (or flows below on smaller widths), while the selected-result evidence and SubmissionReview live in Final Recommendation within the long main column. Selected probability/time/outcome are separated from the choice action.
- Required: one clearly grouped decision section with method choices, target-row choices, judgement basis and compact selected-target values/time/probability/quantity outcomes; link to actual Exit Plan once. Keep authoritative submission draft/server resolution logic already implemented; do not revert it to illustrative mock math.
- Evidence: source-confirmed and archived render corroboration. Amendment order: review reliability/readability.

### D12 — Keep transport/diagnostic provenance in secondary disclosure
- Location: `SubmissionReview/index.tsx:116` (Draft generation), `:128–149` detailed execution/attached-plan rows and `:152–181` selection/server-resolution strings; full component.
- Trigger: inspect the “what am I sending?” review.
- Current: long provisional/request/server explanation strings and draft-generation metadata dominate the review alongside repeated actual exit and recorded-target fields.
- Required: show concise destination/contract/quantity/order/actual stop/target basis first; put generation/technical provenance and full explanatory strings in a disclosure, retaining visible re-review/changed-server-value/unknown-fill warnings. Do not hide that a requested value is provisional or that an alert is not a protective broker order.
- Evidence: source-confirmed. Amendment order: review readability.

## Already implemented: preserve rather than report as missing

- Market Sentiment followed directly by Fundamental Health: page `1579–1588`; keep badges/colors, full definitions and chart navigation.
- Visible full Contract Details and spread data: TradeCard `2487–2578`.
- Editable field tint and border, plus read-only separation: TradeCard CSS `307–354`. Relative sizing can be aligned with the reference, but capability/affordance is not absent.
- Shared Ladder stock/premium stop readouts, correctly distinguishing no Ladder-specific stock-stop valuation: TradeCard `3381–3393`.
- All-three-method selection and display-only behavior exists; it is the default/order and interaction pattern that differ.
- CSS equal-height/stretch/subgrid comparison exists: TradeCard CSS `599–636`. Archived verification measured equal outer heights and aligned slots; it notes an 8px Arithmetic targets-slot offset. Do not claim equal-height support is absent. New browser measurement needed before calling current responsive layouts broken.
- Graphical Barrier Race exists; the location/default disclosure is wrong relative to reference, not the absence of the graph.
- Real authoritative basket/broker server-backed review/fingerprint handling is implemented. Retain it. No claim is made here that those payloads are numerically incorrect.
- The difference between current-time Black–Scholes stop cost and barrier-time repricing is now explicitly described in source. Do not restore older contradictory delta-linear prose from the historical preview.

## Verification limits and non-findings (independent source reviewer)

- No production numerical or persistence defect has been proved by this design review. The design divergences above explain why passing the numerical audit did not establish visual conformity.
- No newly executed browser or deployed mini-PC session was used by this reviewer. Archived mock evidence corroborates density but cannot certify the user's actual running build.
- The parent should capture the actual current mock build and the durable target preview at the same viewport/theme for a visual amendment record.
- No application change, re-pricing, protective-order behavior, automatic application of a calculated stop, backend contract rollback or change of alert semantics is proposed here.

## Fresh browser corroboration — parent review, 9 November 2026

The parent executed the existing `capture-final-verification.cjs` against the isolated current frontend on localhost3097 at1366×1000, dark theme, Chromium headless, with all app APIs route-mocked. Seven states completed: initial, calculated, stale, restored, basket-review, broker-review, outcome. No page script errors. The script's write guard confirms only the allow-listed simulated save and broker request were fulfilled by browser fixtures; no real tracking, broker order, auto-trade, provider or notification action occurred.

Current screenshots and check results are stored in `evidence/implemented-*.png` and `evidence/implementation-checks.json`. Fresh initial measurements: Arithmetic and Monte Carlo cards start at y2579 and both measure1394px high; Ladder starts below at y3989. All three methods are open. Equal-height row checks pass. In the two-card layout, target-slot alignment differs by8px according to the existing measurement. These figures describe the mock fixture and viewport, not the deployed mini-PC.

The rebuilt reference at the same viewport/theme opens Monte Carlo only. Its method card starts at y1334; the reference two-card examples are572px wide and887.09px high each. This is a standalone content reference without the production navigation/context rails, so available content widths differ: those positions are evidence of reading-order/default-density differences, not a pixel-for-pixel performance or fit comparison. Test the amended design within the real app shell before acceptance.

## Amendment execution order

1. **A — Layout and default focus:** D01–D05. Match the reference initial state and large identity; keep shared actual settings readable.
2. **B — Method information and disclosure:** D06–D09. Compact target rows, same field order, barrier-time stop consequences and nested race disclosure.
3. **C — Decision and destination review:** D10–D12. Replace duplicate summaries with one compact selected-target review, reuse existing submission/server fingerprint logic, and keep technical detail one click away.
4. **Acceptance:** compare initial, computed, stale, restored, two/three-method and both destination-review states against the reference plus the625-item current-source register. Verify theme/colors, edits, all existing explanations/actions and server-backed request/save parity.

### Required before closing the amendment work

- [ ] Every D01–D12 item has before/after evidence or a user-approved exception.
- [ ] Existing625-item implementation inventory is reconciled, including conditional states; do not use the historical132 explanation list as a replacement.
- [ ] Identical sample inputs are used where claiming numerical agreement; no sample price is promoted to an algorithm requirement.
- [ ] Existing accepted server review, changed-value rejection, limits, persistence, retry, spread and auto-trade behavior remain verified.
- [ ] Visual reference screenshots are reviewed in addition to numeric/persistence gate audits. Passing the latter alone is not evidence of visual conformity.
- [ ] Production changes receive their own appropriate checks and independent audits; this documentation review does not clear them.

## What this change does

This documentation PR preserves an explicit, runnable design reference and amendment register. It does not implement the amendments, reopen closed phase audit counters, or assert the deployed mini-PC is on the reviewed commit. No production numerical/persistence defect is established by this review.

### Latest user placement amendment

Stock Qualification must sit directly beneath Contract Details and start collapsed. Contract Qualification is retained because its component scores/explanations are different from raw contract metrics. This placement is now in the reference; do not remove contract evaluation evidence as duplicate details. This adds an explicit acceptance condition to D03 without changing the frozen implementation review baseline.
