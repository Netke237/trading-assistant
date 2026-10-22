# Ticket orchestration — trading-assistant contract

The user-level `k-ticket-coordinator` skill (Kenneth's `~/.claude/skills/` and claude.ai account; deliberately not stored in this repo) runs multi-ticket builds here. This file holds the repo-specific values it reads; where it and the skill differ, **this file wins**.

## Who does what

- **Coordinator** = the session Kenneth is talking to. Only it edits `docs/superpowers/PROJECT_STATE.json`, the tracking issue, and runs audits.
- **Implementer** = the `ticket-implementer` agent type where installed (user level), else `general-purpose` with the implementer brief (skill `templates.md`, or the repo copy `docs/agents/agent-briefs.md`); one fresh subagent per ticket.
- **Gate auditor** = the `gate-auditor` agent type where installed, else `general-purpose` with the auditor brief (skill `templates.md`, or `docs/agents/agent-briefs.md`); one fresh subagent per audit round, applying `.claude/skills/bmad-review-adversarial-general/SKILL.md`.

## Units

- **Phase** (a `phases[]` entry in `PROJECT_STATE.json`, e.g. `STOCKS-STEP-MERGE-S1`) = the claim, the branch, the **audit target**, the round counter.
- **Ticket** (a GitHub child issue) = one plan task = one build unit. Tickets are never audit targets.
- One tracking issue per phase. When the phase is a **board item** (`docs/agents/board.md`), the board item issue *is* that tracking issue: do not create another; START mode cuts the tickets as its sub-issues and records Tickets / Audit / Needs Kenneth / Log as **comments** on the item, never body edits (only the `**Branch:**` value changes). For board items, `board.md` wins on branches, claims, ownership, labels and tracking.

## Required task ratings and progress

Follow [task-ratings.md](task-ratings.md) for every board phase, confirmed defect and build ticket. Before publishing or starting a task, apply exactly one `size:*` and one `complexity:*` label, explain the estimate, and record an evidence-based completion milestone. Recheck ratings after plan approval and scope changes. Include completion, size and complexity in tracking updates and stop reports. These requirements supplement the user-level `k-ticket-coordinator` skill; existing claims, audit caps and merge gates remain authoritative.

## Commands

| What | Command |
|---|---|
| Frontend typecheck | `cd frontend && npm run typecheck` |
| Frontend tests | `cd frontend && npm run test` |
| Backend tests | `cd backend && pytest` (Python **3.11** only — see `CLAUDE.md` "Backend runtime") |
| State check | `python3 scripts/state.py` (on Windows: `python scripts/state.py`; `python3` there is the Microsoft Store stub) |
| Claim | `python3 scripts/claim.py take <ID>` · `renew` (no id; renews this branch's claims) · `release <ID>` · `list` (same Windows note). Exit 1 = held by another branch; exit 2 = git/push failure → stop |

## Audit (from `PROJECT_STATE.json` → `audit_rule`)

- Plan stage: a clean plan round before any ticket is cut. Code stage: one target, the integrated diff `origin/main..<branch>`, after every build ticket is closed.
- Cap: three rounds **per stage**. Round N>1 reviews only round N-1's fixes and their interactions.
- Gate (paste into every auditor brief): a finding blocks only if it can put a **wrong number in front of a user or on a broker order**, or **corrupt persisted data**. A comment blocks only if it misstates mechanism (a competent reader acting on it would write a wrong change). Do not report anything else at all. Undecidable → not gate-level.
- Only gate findings are fixed in-branch (by a fresh implementer). Everything else is logged against main.
- Record each round in the phase entry: reviewer, exact diff range, findings, fixes, outstanding. Commit subjects for a round's record begin `docs(state): FULL-PHASE-ID round N` (also `docs(state): FULL-PHASE-ID plan round N` or `code round N`), using the exact case-sensitive `phases[].id`. `state.py` excludes a canonical record owned by a different known phase only when the active phase's full ID is absent as a whole token from the rest of the subject; mixed interaction subjects remain evidence. Unknown IDs, shorthand owners and other prefixes remain unowned evidence and can still cause cross-phase alarms. An absent/unresolved active phase or an `already_shipped` target retains all evidence. For singular `round N, K findings` (also `finding`, case-insensitive), a sole comma-introduced implicit K is a finding count; primary and explicit round/r numbers, plural round lists, other delimiters and ambiguous multiple implicit continuations remain round evidence. This parsing correction also applies to unowned subjects and helper calls without ownership filtering. Implementers never use `round N` in a subject.
- Statuses: `not_started` → `in_progress` (implementation underway) → `built` (code exists, unmerged) → `shipped` only once merged with `audit_clean: true`. `built` applies whether the code audit is pending, has findings, or is clean; record that separately in `audit_rounds` / `audit_clean`. A clean audit does not mark an unmerged target shipped.
- Presence probes check code existence, not merge or audit completion: `built`, `shipped`, and the legacy `shipped_unaudited` status expect the probe to confirm code exists. `not_started` and `in_progress` expect it not to confirm the completed target yet. A built target without `audit_clean: true` remains in the UNAUDITED warning, including under `--quiet`.

## Source tag (Claude and Codex share one GitHub identity)

Every tool authenticates as Kenneth's account, so GitHub shows the same author for all of them. Every issue body, issue comment, PR body and PR comment an agent writes **starts with its source tag**: `[claude]` or `[codex]` (add the role when useful, e.g. `[claude · coordinator]`, `[codex · implementer]`). An edit to a tracking issue's body adds a Log line with the tag. Untagged agent text is a housekeeping defect: tag it in the next update; do not rewrite history.

## Housekeeping

- `python3 scripts/claim.py renew` every ~2h during the build loop (claims expire after 3h).
- `python3 .k-session/k_session.py checkpoint -m "…"` after each closed ticket **if** `.k-session/` exists on the branch.
- Push the branch after each closed ticket so other sessions can see the work.
- Merge to `main` only through the self-merge conditions in `board.md` step 7 (decision `AGENT-SELF-MERGE-2026-10-11`; they apply to every phase, board item or not), or on Kenneth's explicit go in your own session's chat.

## Existing NO-LIVE-QUOTE split exception

User decision `NO-LIVE-QUOTE-SCOPED-AUDITS-2026-10-09` explicitly authorizes the existing NLQ split to keep NLQ-1 closure and audit NLQ-2/3/4 independently, each with at most three code rounds, followed by NLQ-5 integration verification. Historical rounds remain counted. This exception applies only to this existing split; the phase-only rule remains in force elsewhere. The state checker currently has no scoped-cap model, so its phase-level cap warning is retained and explained while this exception is active. Overall audit_clean stays false until all remaining scopes and integration pass.
