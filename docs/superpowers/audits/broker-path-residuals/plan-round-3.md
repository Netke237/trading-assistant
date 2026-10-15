# Plan round 3 (plan stage round 3 of 3) — integration identity amendment

- Reviewer: fresh independent subagent applying `bmad-review-adversarial-general`, briefed on the audit_rule numeric/persistence gate. Read-only.
- Scope: `697647a2..e4ca9c4d` — `docs/superpowers/plans/2026-10-13-broker-path-residuals-plan.md` (Durable submission identity, Production identity resolution, T2 files/body/red-green, T3 wording) and `integration-identity-amendment.md`, plus interactions with the round-1 F1 exclusive prepared-row ownership fix. Branch code consulted only to test implementability.
- Verdict: **0 gate findings.** Plan stage clean.

## Paths checked (no wrong number, no corrupt persisted data)
1. Options lost reply (only ID-less in-app caller): save-first row marker matches the order payload; retry after delay > 3 s or restart resolves to the owning attempt and replays it — one broker POST.
2. Deliberate re-buy after close: unique `contract` + close deletes row → at most one prepared candidate; new unowned row proves new intent.
3. Explicit-ID stock sends stay payload-bound; unresolved matching fingerprint still 409.
4. Added fill on an owned row then ID-less retry falls through to durable success replay (removes a duplicate the old 3 s window allowed).
5. Ownership bound under the exposure guard in the attempt-insert transaction; definitely-not-submitted verification releases ownership; T1 3 s method cannot authorize dispatch.

## Non-gate notes (not findings, logged)
- Options UI "retry" after an unknown outcome = Remove (confirm says only if broker shows no order) → new save → new intent. If the broker did accept the first order, a second is sent. Reachable under the round-2-clean plan already, depends on the user's broker assertion, and the first attempt's hold keeps exposure counted. The amendment's "deleted rows" protection covers only retries without a new row.
- Identical ID-less CLOSE / standalone OPEN now replay indefinitely (`deduped: true`). No in-repo CLOSE caller; external callers need a fresh explicit ID to repeat deliberately.
