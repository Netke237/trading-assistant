# DIRECT-SEND-EXPIRY-PLACEHOLDER (#591)

Branch board/direct-send-expiry-placeholder-4ff3bc02. Prerequisite for presentation #609. SizeS/complexity2: one persisted-field defect and two enforcement/display consumers. No existing Portfolio rows, tracking builder, known-contract broker requests, pricing or alert policy changes.

## Concrete policy

Refuse direct sends when the selected contract has no supplied expiry. Do not infer a calendar expiry from a default24DTE or a display label. This choice is explicitly inside #591's scope (the plan chooses derivation or refusal). Keep supplied nonblank expiries as today; broader malformed-calendar validation is outside this missing-field defect. Missing/null/empty/whitespace values all count unavailable.

The immutable draft is also built during render, so do not throw from it or make the page crash. Use its existing DirectRoute.blocked field to expose a clear missing-expiry reason. For an unavailable direct route the position expiry is empty/unusable, never a made-up date; it is never submitted. The direct-send handler enforces the same missing-expiry guard before quote/server preview/save/broker requests. Keep the existing captured-review/fingerprint/confirmation machinery; test that removal of expiry after review invalidates that review and cannot write.

## Task1 — missing-expiry refusal

Allowed source: frontend/lib/submissionDraft.ts and frontend/app/(frame)/screener/step-7-trade-card/page.tsx. Allowed tests: frontend/lib/__tests__/submissionDraft.test.ts and existing Step7 direct-send/broker-review/golden payload tests; one focused new expiry test if more maintainable. No other source changes. Coordinator owns plan/state, issue/PR, audits/pushes.

Read AGENTS.md, docs/agents/agent-briefs.md and actual draft/direct-send handler before edits. First add failing regressions for missing contractDetails and missing/blank expiry for both LMT and MKT, with supplied expiry preserved. Existing behavior must fail by returning2026-12-31 and/or reaching preview under unknown expiry. Page test proves a clear refusal and zero quote/preview/persist/order calls for unavailable expiry; valid details still reach reviewed save-first route with unchanged payload. Include known-to-missing changed-review isolation. Keep all old transport/safety assertions; update only golden cases intentionally pinning the erroneous placeholder/missing-field route.

Add a small exported pure directExpiryBlock(card) (or equally narrow existing helper) that returns a clear reselect-contract reason for unavailable expiry, else null. Use the same helper for DirectRoute.blocked and reviewDirectOrder preflight. Preserve the existing broker-type block on valid expiries. Remove directPosition's hardcoded2026-12-31; missing route uses empty expiry, never a supplied synthetic date. This is a blocked draft/readout only. Verify all production direct-position save paths pass the handler guard and confirmation freshness checks; no merely cosmetic disabled-button protection. Keep trackingRequest unchanged, including its current DTE derivation (out of scope).

Run focused tests (prove red then green), frontend typecheck and full Jest (two workers/silent acceptable). Do not change backend. Commit `fix(direct-send): refuse missing contract expiry` with Codex attribution. Implementer does not push, switch branch, edit state or call self-review an audit.

## Acceptance and audits

Fresh independent plan review before child ticket creation/implementation; then one fresh implementer. Coordinator pushes and closes build child after checks, fetches/merges latest main, reruns relevant checks on changes and obtains independent code audit on integrated diff (numeric/persistence/mechanism gate, cap3 per stage, shrinking fix scopes). No real provider, broker or notification calls. Keep phasebuilt/audit false until independent clean review; self-merge only with all board.md step7 conditions and exact-head CI green. Then merge prerequisite into presentation branch before #609. Preserve both phases' separate historical counters.
