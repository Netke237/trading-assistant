# Pre-Breakout page — implementation ticket drafts

12 October 2026. Local drafts, not published GitHub issues. No application implementation in this session. Plan audit recorded separately in prebreakout-ticket-audit.md.

## Scope and decisions

Use the existing Stock Ranking page as the layout basis: candidate table left, selected-symbol mini chart right, stock information/score cards below, stock or industry news afterwards. Replace the ranking output with setup-specific metrics. Retain watchlist, chart in a new tab, alert actions, mode-specific parameters and all existing scan behavior. Preserve the actual Pre-Breakout navigation: self-contained Step 4, no new Steps 5–7, no broker handoff.

Requested additions requiring explicit data work: selected-stock context cards, news, and filter breakdown with analysis logs. These are NOT currently all supplied by the Pre-Breakout endpoint. Reuse truthful existing sources where suitable; add independently audited data contracts for missing diagnostics. Do not backfill from unrelated Options scan candidates or fabricate scores for a new symbol.

Assumptions awaiting user validation: the same layout can host Pullback/Fib with their own columns; filter breakdown includes counts and symbol reasons where recorded; stock cards include existing five score components plus sentiment/fundamentals when available. These assumptions do not authorize new scoring, exclusion, execution or alert semantics. Missing information renders unavailable with a reason, never zero/PASS.

Baseline: frontend/app/(frame)/screener/step-4-prebreakout/page.tsx; step-4-ranking/page.tsx; frontend/types/stockDomain.ts; frontend/lib/api.ts; scanStore.ts; backend/app/routers/stock_scan.py; services/strategy_engine.py. Before code, read latest state/claims, claim ownership, inspect current source, enumerate conditional child content and validate units. No task claim or repo mutation is required for these external local drafts. Implement one small stage at a time with independent plan/code gates, maximum three rounds per stage. Never overwrite another branch's work.

## PB-PRES-01 — Shared ranking layout and selected symbol

- Use existing shell, navigation, parallel context rail, theme primitives and CSS Modules. Match Sora titles, DM Sans text, JetBrains Mono numbers, current light/dark tokens. No shadows, hardcoded new colors or storage-key renames.
- Keep mode, inherited direction/universe/horizon, manual-symbol override, scan/reset controls and mode-specific defaults/ranges. Preserve request mapping, universe precedence, errors/loading and result-clearing behavior.
- Selected row drives chart and stock context. Key asynchronous requests by symbol plus relevant direction/horizon/scan snapshot; cancel or ignore late replies. Clear selection when absent from current results; do not show the previous stock's evidence under the new symbol.
- Keep Pre-Breakout confidence-descending order and each other mode's actual existing order. Do not substitute stock score as setup rank.
- Validation: mode changes, changing parameters/universe, late replies, empty/error results, keyboard row selection and supported desktop widths.

## PB-PRES-02 — Mode-specific table, metrics and evidence

- Pre-Breakout: symbol, direction, setup confidence, ATR ratio, volume ratio, proximity; retain all returned metrics and confidence_breakdown/fib_swing evidence in a disclosure (old persisted rows may lack evidence). Name ratios' numerators/denominators from the actual engine; do not invert, rescale or relabel as probabilities.
- Pullback: preserve current symbol/company, direction, score, price, confidence and all existing conditional statuses/evidence and controls. Do not coerce its PositionCardData into Pre-Breakout metrics.
- Fib: preserve fib_level_hit, nullable fib_dist_pct, at_level, confidence, swing bounds and exact confidence semantics. Existing fib_level_hit is a string; preserve percentage formatting without an extra conversion. Preserve the existing tolerance comparison to fibTolerancePct * 100 and source units.
- Show confidence as setup score; Fib confidence is proximity-based and does not assert volatility/volume/trend qualification. Keep unavailable distinct from numeric zero; no invented TP probability or stop/entry/TP outputs.
- Validation: actual field mapping, zero/null values, old persisted rows, both directions and all three modes.

## PB-PRES-03 — Selected-stock mini chart and actions

- Reuse ranking chart/header behavior for the selected symbol with existing chart interval/indicator controls where supported. Chart loading/error states must be local and must not remove the candidates table.
- Keep existing WatchStar add/remove persistence and `/chart?symbol=…` new-tab action for ALL three modes. Use the clicked row symbol, not a stale selected symbol; prevent action clicks from unintentionally selecting another row where appropriate.
- Retain CompositeAlertDialog in all modes, including Fib's existing plus button. Preserve symbol, reset/dismiss and current conditions; no new alert levels or auto-created subscriptions.
- Validation: star/unstar, chart URL/new tab, each mode's Set Alert and selected symbol after sort/filter/scan refresh.

## PB-PRES-04 — Stock context and complete score cards

- Inventory the ranking page's full selected-stock header, total, Trend/Pullback/Trigger/Event/Volatility component content and any existing score/evidence disclosures. Preserve raw score, weight, contribution, notes, status, confidence qualification and safety explanations.
- Identify a supported same-symbol stock-analysis source for context, five-component scores, market sentiment and fundamental health. Verify direction, horizon, strategy and snapshot compatibility before reusing a response. If unavailable or incompatible, show an explicit unavailable state; never join a stale Options/Stocks scan by row index or fall back to zero or PASS.
- Keep setup confidence distinct from stock score, historical confidence, sentiment and fundamentals. All statuses derive from their authoritative source, not a global bullish/PASS conversion. Sentiment uses readable labels supported by color.
- Source integration must be separately reviewed before UI mapping if existing API cannot supply the required context. A selected-symbol fetch must not re-run the user's scan with different parameters or change ranking/filter results.
- Validation: symbol/direction/horizon changes, mixed source availability, stale responses, score evidence/qualification and missing fundamentals.

## PB-PRES-05 — Honest filter diagnostics contract (data prerequisite)

- Current `/scan/prebreakout` returns only accepted rows. Excluded symbols and bars/signal failures can be logged server-side; `signal is None` is silently omitted. Do not reconstruct rejected counts as universe minus displayed rows, scrape server logs, or interpret every omission as a failed setup rule.
- Design an additive, versioned/opt-in diagnostics response or separate scan-run report preserving existing list-response callers. Bind candidates and diagnostics to the SAME evaluated scan, resolved symbol set, parameters/direction and run identity. Do not launch a second scan and call it the first run's log.
- Report authoritative unique input/evaluated/accepted/excluded/no-data/error/no-setup outcomes with documented mutually exclusive terminal categories. Deduplicate consistently before both evaluation and counting; preserve existing candidate numerical values, ordering and trading behavior. Unknown outcomes remain unknown. Record exact observed rule failures only when the engine exposes them without changing selection semantics; a generic no-setup result must not name an unobserved failed rule.
- If reporting multiple rule failures, separately label overlapping per-rule counts and do not sum them as unique rejected stocks. Distinguish data errors and configured exclusions from no setup. Preserve skipped-symbol handling and error isolation.
- Pullback/Fib diagnostics use their own actual pipelines. Do not pretend Pre-Breakout rules rejected their candidates. Legacy responses have diagnostics unavailable, not zero rejected.
- Validation: accepted/excluded/no-data/error/no-setup, duplicates, empty universe, unknown/legacy report, same-run linkage, list-response compatibility and unchanged candidate parity. Verify Python 3.11 before backend work. No numerical golden regeneration to hide drift.

## PB-PRES-06 — Filter breakdown and inspectable analysis log

- Depends on PB-PRES-05's audited contract. Place Filter Breakdown near table heading. Counts/reasons come only from the matching run report. Preserve existing scan controls/table while opening it.
- Show unique terminal outcome counts, searchable symbol reasons when present, thresholds and actual observations with units/source; label partial/unavailable diagnostics. Raw logs must not expose secrets or internal credentials.
- Changing mode/parameters must not silently relabel the old report as current: retain explicit snapshot labeling or invalidate together with its run. Distinguish client table filtering from scan exclusions.
- Validation: accurate count totals against unique outcomes, overlapping rule-count explanation, absent diagnostics, stale run/mode and symbol drilldown.

## PB-PRES-07 — Stock and industry news

- Add news below stock cards. Reuse existing supported news source (`api.getNews` where suitable); maintain headline, publisher, date and original link. Selected-symbol news and industry news must identify their relevance/source; industry coverage is unavailable until a supported industry mapping/feed exists.
- Isolate loading/error/empty states. Ignore responses for a previous selected symbol. No manufactured headlines, dates, market sentiment or trading advice.
- Validation: selected-symbol transition, no news, upstream error, external link and industry-source availability.

## PB-PRES-08 — Preservation crosswalk, checks and shipping gate

- Before implementation, enumerate every current control, displayed field, disclosure, tooltip, conditional warning, request, mode default/reset, result persistence and action against a destination. The screenshot is layout authority, never numeric authority.
- Reuse existing persisted stores; any necessary breaking shape change gets a version bump plus migration, preserving old rows and storage keys. New stores use bamendjou:<name>. No response-shape change without caller compatibility.
- Run frontend typecheck and focused meaningful tests for field units, selection races/actions and diagnostics; backend parity/contract tests for PB-PRES-05. Preview validation is not a code audit.
- Run fresh independent adversarial audits for each implementation stage, numeric/order/persistence gate and shrinking follow-up scopes. No merge or done claim until zero gate findings; max three rounds per stage. Record exact diff, reviewer, fixes and outstanding findings.

## Delivery order

PB-PRES-01/02/03 shell/table/chart/actions first; PB-PRES-04 source verification then cards; PB-PRES-05 data contract then PB-PRES-06 logs; PB-PRES-07 news; PB-PRES-08 crosswalk/checks throughout. Changes to shared files remain serial. All additions are ticketed; no missing-data placeholder counts as completed data integration.
