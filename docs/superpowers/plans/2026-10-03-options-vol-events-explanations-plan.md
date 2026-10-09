# Options Volatility + Events — explainable gates implementation plan

Date: 2026-10-03. Target: `OPTIONS-VOL-EVENTS-EXPLANATIONS`. Scope: future implementation, not implemented by this document. Plan-stage audit is recorded below; it does not clear the separate future code-stage shipping gate.

## Goal and boundary

A trader must see the applicable thresholds, each check's result, and the condition deciding PASS / CAUTION / REJECT without hovering. Preserve existing numeric gate computation and all scan, watchlist, chart and navigation behavior. No backend scorer, YAML defaults, persistence schema, broker behavior or ranking changes. No new API requests for opening explanations. Use the centre workspace; no horizontal scrolling or hidden clipping.

Companion: `2026-10-03-options-contract-score-explanations-plan.md` in this directory. Implement this page first or independently; agree on terminology, status tokens, expandable-panel conventions and browser overflow tests before Contracts. Neither implementation depends on the other being shipped. Do not broaden this target into contract liquidity or live quote fixes.

## Repository evidence and dependencies

Start implementation with `python3 scripts/state.py`; read `PROJECT_STATE.json` including audit_rule, task claims and relevant decisions. Its presence probes are not behavioral evidence. Required shipped prerequisites: `SCREENER-PINNING-PASS` (literal threshold/driver assertions), `DOCC-3-THRESHOLD-STORES-REFUSE` (validated fetch-only thresholds and session IV overrides), Phase A's rank/absolute IV split (`PHASE-A-NULL-IVRANK-2026-09-06`), and the persisted scan `event_window` echo described in current Step 5. Preserve these mechanisms. `AGENTS.md` has stale threshold-store descriptions and says minimum width 1200; actual `frontend/components/MinWidthGate/index.tsx` defines **1280** and source stores have no hardcoded fallback.

Authoritative paths:

- `frontend/app/(frame)/screener/step-5-vol-events/page.tsx`: effective IV resolution, availability, horizon mapping, echoed event-window merge, `gatedRows`, summary and row interactions.
- Same directory `gateSummary.ts` and `page.module.css`: existing structured summary and styling.
- `frontend/lib/ivBasis.ts`: `resolveIv`, `formatIv`, dynamic column labels. Rank zero is valid; absolute zero is missing. Percentile is separate context, not a gate input.
- `frontend/lib/ivThresholdsStore.ts`: validated backend thresholds, `effectiveIvThresholds`, `getIvPassMax`, `getIvCautionMax`, `ivOverrideFor`; session override changes **absolute pass ceiling only**, not rank ceilings.
- `frontend/lib/eventThresholdsStore.ts`: validated records, latest-request guard and failure clearing. Source endpoints `/api/config/iv-thresholds` and `/api/config/event-thresholds`; base data from `backend/config/scoring_rules.yaml`.
- `frontend/lib/statusTooltips.ts`: `gateDrivers`, `gateDriverPhrase`, `eventVolGateTooltip`; `frontend/lib/status.ts`: `worstStatus`.
- `frontend/lib/scanStore.ts`, `frontend/types/domain.ts`: scan result and `event_window`; do not substitute live edits for recorded scan rules.
- `frontend/components/atoms/EventFlag/index.tsx`: currently uses generic 3/7-day color, unsuitable for this gate's horizon-specific verdict.
- `frontend/components/molecules/TableRow`, atoms `StatusBadge`, `WatchStar`, `OpenChartButton`: preserve controls and status conventions.
- Actual shell: `frontend/app/(frame)/layout.tsx`, `frontend/components/organisms/Frame.module.css`, screener `layout.tsx` / `screener.module.css`, and matching `@contextRail` route. Measure with both rails and shared overflow styles in place.

Existing code has useful model data already. Keep the existing `gatedRows` numeric decisions authoritative, enriching each record with observed input, effective threshold references and provenance. Do not recompute verdicts separately in the details panel, rules header, reason column or tooltip. A small pure display-model helper beside `gateSummary.ts` is allowed; it consumes the computed record and formats it, rather than introducing another scorer.

## Current semantics to preserve

IV rank is preferred to absolute IV when present. IV uses `<= passMax`, then `<= cautionMax`, else REJECT; null pass ceiling means no gate on that basis. Missing IV grades CAUTION on a gated horizon, PASS when both bases are ungated. Events use strict `< reject_days`, then `< caution_days`, else PASS. Missing event date currently contributes PASS; present this as **“No event date available; existing gate applies no event penalty”**, never “no upcoming event confirmed.” Worst severity wins. Only checks tied at the final non-PASS severity are deciding drivers; a lower-severity concern remains visible but must not be named as deciding a worse gate. A PASS row has no adverse driver; explain disabled/missing checks truthfully.

Both threshold records are prerequisites even when a scan echoes an event window. Before first successful fetch: PENDING and no numeric thresholds/verdict counts. Failed/malformed fetch: NO_DATA, no invented thresholds, Retry. In-flight refresh keeps last validated data; a failed refresh clears the failed record and refuses grading. Keep latest-request race semantics. Echoed scan `event_window` overrides fetched event-window keys; legacy result without echo uses horizon YAML and must be labeled current-config fallback. A session IV override is live and remains distinct from scan-time event provenance.

## Intended layout

1. Heading and concise worst-severity explanation.
2. Wrapping “Rules applied” strip: horizon; IV basis-specific pass/caution/reject intervals; event intervals; provenance (“Current backend configuration”, “Recorded scan event window”, or “Legacy scan: current configuration fallback”); applicable absolute session override and its YAML baseline. Render all applicable basis bands, including when no row has a reading. Show ungated bases explicitly. Do not invent an interval when caution maximum is null: after pass, REJECT directly. If a supported absolute pass override exceeds caution maximum, represent actual computation as `<= pass: PASS; > pass: REJECT; CAUTION: no reachable interval`, not contradictory ranges. Avoid misleading override labels on rank-only rows; the strip may identify an absolute-only override as not applicable to the rank values displayed.
3. Full-width compact rows: chart/star, symbol/company, volatility reading **and IV check badge**, event days/label **and event check badge**, final gate, short “Why this gate?” text and disclosure. Move IV percentile to row's secondary detail line or expanded panel labeled “Context only — does not determine this gate”; never broaden the comparison grid to preserve a column. Company labels and reason text wrap. At narrow supported workspace widths, use two aligned row bands rather than shrinking to unreadable tracks. Retain visible symbol, both check results, final gate and deciding reason in collapsed view.
4. Inline disclosure below each row: two wrapping check blocks containing actual value (or missing), basis/unit, exact applicable comparator and thresholds, result, and final combination (“PASS + CAUTION → CAUTION, driven by event proximity”). Mention both when tied. Explain all checks even when only one decides. Context percentile and full company/event label available without hover. Disclosure is a real button (`aria-expanded`, `aria-controls`, Enter/Space), with stable symbol-based IDs and local nonpersisted expansion state.

Event indicators on this page must use **proxStatus**, not generic 3/7-day colors. Prefer page-local labeled indicator/badge with existing tokens; if adding an optional status prop to shared EventFlag, retain default behavior on every existing call site and test it. Numeric negative days currently participate in comparisons but EventFlag hides them: expanded/collapsed text must still expose the actual negative value and actual verdict instead of silently losing the deciding input. Do not change date normalization in this presentation target.

Use CSS Modules and shared tokens. `minmax(0, …)`, `min-width: 0`, wrapping and adaptive row bands should fit the content inside actual workspace width. Remove any new fixed-width sums that cannot fit. Do not solve overflow with `overflow-x:hidden`, clipping reason text, or hiding controls; existing optional tooltips must remain within the viewport and keyboard reachable, but essential explanations cannot depend on them. Prefer inline panels over wide floating overlays.

## Implementation sequence

1. Claim implementation target; inspect active claims; reread latest state and source. Coordinate shared files with Contracts implementer. Establish existing targeted-test baseline.
2. Add pure explanation presentation model using computed `gatedRows`; retain existing structured `data-cell`, `data-side-*`, `data-gate`, `data-part` evidence where meaningful. Adjust existing exact literal pins only for intended new copy, preserving independently hand-derived numeric expectations; do not loosen tests into matching implementation-generated strings.
3. Build rules strip and responsive two-band rows, status-aware event display, short driver explanation and local disclosure. Extract components following repository atoms/molecules/organisms conventions if needed; no fresh-object Zustand selectors.
4. Add boundary/data/provenance and interaction coverage below. Add real-browser fixture/spec to existing Playwright harness; mock endpoints and hydrated scan deterministically using existing `frontend/e2e/fixtures/api-mocks.ts` and `frontend/e2e/tests/iv-basis-rendering.spec.ts` patterns.
5. Run targeted suites, typecheck, browser tests and required broader frontend checks; record actual results. Run a **separate code-stage** fresh independent adversarial audit, fix gate findings and repeat within its own three-round cap. Record reviewer, exact diff, results and residuals in state. Plan audit does not mean feature shipped.

## Numbered acceptance criteria and verification mapping

AC1. Every collapsed row displays basis/unit, IV and event sub-status, final status and deciding reason. With IV PASS/event CAUTION, event alone decides; IV REJECT/event CAUTION, IV alone decides; CAUTION/CAUTION and REJECT/REJECT list both. PASS has no adverse driver. Map: new `__tests__/explanations.test.tsx`, existing `gateSummary.test.tsx` and `frontend/lib/__tests__/statusTooltips.literal.test.ts`.

AC2. Exact numeric boundaries are shown and applied unchanged across Intraday/Swing/Position, using distinct rank and absolute bands in fixtures: IV pass/caution boundary and ±0.01; event reject/caution boundary and ±1 day; coincident event boundaries, null caution and ungated basis. Literal expected text and independently derived expected statuses must agree in header, collapsed badge and expanded details. Map: `literalPins.test.tsx`, `eventGate.test.tsx`, new explanations tests.

AC3. Rank 0 renders valid rank, absolute 0/null renders missing, percentile 0 renders contextual 0 without affecting gate. Unknown IV on gated horizon explains CAUTION; disabled IV explains not checked; null event date explains missing date/no penalty without asserting measured clearance. Negative event input displays exact days/verdict. Map: `ivPercentileZero.test.tsx`, lib `ivBasis.test.ts`, new explanations tests.

AC4. Rules strip identifies horizon and correct provenance. A recorded scan 7/30 event window wins over current config 30/60, later live Step-3 edits do not alter it, reload of persisted result retains it; legacy missing echo labels YAML fallback. Absolute session override changes absolute pass band only, survives refetch, does not change rank grading; above-caution override displays no reachable CAUTION interval. Map: new explanations tests with store updates; existing event gate and threshold suites.

AC5. Loading/failed/malformed config never shows invented numeric bands or fabricated PASS/CAUTION/REJECT, counts or causes; Retry invokes both store fetches and restores valid results. A refresh failure removes formerly shown grading; slow stale success/failure cannot replace latest response. Map: `thresholdsUnavailable.test.tsx`, existing store tests plus explanation render assertions. No candidates shows scan prompt; fetch error text wraps and remains readable.

AC6. Disclosure works by pointer and Enter/Space, accessible name identifies symbol, aria state and target match, independent rows expand/collapse and do not fetch. Chart and star controls remain functional without toggling disclosure; existing step navigation continues. Expansion is not persisted or written to watchlist/scan data. Map: React Testing Library interaction tests and real browser keyboard test.

AC7. At viewport widths **1280, 1440, 1920**, actual frame/rails, collapsed and expanded page, mixed IV bases, long single-word company/event labels, error messages and hovered/focused optional tooltips: document and workspace and page/table/panel scrollWidth are at most clientWidth + 1 CSS pixel; no horizontal scroll container appears, each control/text block is within its owning panel and viewport, all text is accessible without clipped overflow. Verify both themes and normal/dense setting if supported. Below 1280 existing MinWidthGate remains unchanged. Map: new Playwright `frontend/e2e/tests/options-explanations-layout.spec.ts`, browser screenshots and bounding-box checks. CSS text inspection/Jest alone cannot satisfy this criterion.

AC8. Use scan inputs and thresholds already available; expanding any row creates zero network requests, no new persisted fields, no gate/scorer changes. With 20 candidates and all disclosures open, no console errors or lost interactions. Map: browser request count around disclosure, store snapshot equality excluding existing explicit star action; 20-row fixture.

AC9. Targeted Jest and browser checks pass; `npm run typecheck` and full frontend Jest pass. Production build if environment supports it, recording any external-font blocker separately rather than calling it pass. Unchanged numerical behavior pinned by existing suites. If shared/backend paths are touched contrary to planned frontend boundary, pause to revise scope and add appropriate Python 3.11 parity tests before coding. Independent code audit zero gate findings required before merge. Map: command output and code-stage audit record.

## Plan audit record

Canonical task status and counters belong to `docs/superpowers/PROJECT_STATE.json`; the following is historical review evidence. Future implementation remains not started.

Audit contract: maximum **three rounds per PLAN stage**, stop at the first zero gate-finding round, later rounds only prior fixes and their interactions; no fourth round or counter reset. Future code audit has its own separately recorded cap and must not be represented by this plan review.

- Round 1, 2026-10-03: fresh independent reviewer `/root/vol_events_plan/audit_round1`, applying `.claude/skills/bmad-review-adversarial-general/SKILL.md` and the PROJECT_STATE numeric/persistence gate and mechanism exception. Full document reviewed, SHA-256 `5132c8bc437f067a2aa4532b6e0d45fe248f28f5e71f71c065e75422e9a6fae4` (entire content before this audit-log replacement, including corrected companion filename).
- Scope verified: reviewer explicitly read the actual Step 5 page, gateSummary, CSS and existing tests; ivBasis; both threshold stores and tests; statusTooltips/status; scanStore persistence/event-window; EventFlag; frame/screener layouts; MinWidthGate and Playwright patterns. Second pass covered basis/zero/null/disabled distinctions, null caution and above-caution overrides, strict and negative event boundaries, missing dates, tied drivers, failed/stale refresh, and persisted provenance. This is not an audit based only on the author's summary.
- Findings: **0 gate findings**. Fixes: **0**. Outstanding gate findings: **0**. A nonbehavioral in-flight companion-filename correction was disclosed and included in the reviewed hash. No deferred audit findings. Stop after round 1 under the objective exit rule; plan-stage clean only. This log addition records the result and does not alter the implementation scope or acceptance criteria.
- No code written, no runtime feature validated, no code-stage audit claimed. Implementer must execute the acceptance criteria and required separate independent code audit before declaring implementation ready to merge.
