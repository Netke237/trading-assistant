# Ticket orchestration — trading-assistant contract

The user-level `k-ticket-coordinator` skill (Kenneth's `~/.claude/skills/` and claude.ai account; deliberately not stored in this repo) runs multi-ticket builds here. This file holds the repo-specific values it reads; where it and the skill differ, **this file wins**.

## Who does what

- **Coordinator** = the session Kenneth is talking to. Only it edits `docs/superpowers/PROJECT_STATE.json`, the tracking issue, and runs audits.
- **Implementer** = the `ticket-implementer` agent type where installed (user level), else `general-purpose` with the skill's implementer brief; one fresh subagent per ticket.
- **Gate auditor** = the `gate-auditor` agent type where installed, else `general-purpose` with the skill's auditor brief; one fresh subagent per audit round, applying `.claude/skills/bmad-review-adversarial-general/SKILL.md`.

## Units

- **Phase** (a `phases[]` entry in `PROJECT_STATE.json`, e.g. `STOCKS-STEP-MERGE-S1`) = the claim, the branch, the **audit target**, the round counter.
- **Ticket** (a GitHub child issue) = one plan task = one build unit. Tickets are never audit targets.
- One tracking issue per phase.

## Commands

| What | Command |
|---|---|
| Frontend typecheck | `cd frontend && npm run typecheck` |
| Frontend tests | `cd frontend && npm run test` |
| Backend tests | `cd backend && pytest` (Python **3.11** only — see `CLAUDE.md` "Backend runtime") |
| State check | `python3 scripts/state.py` (on Windows: `python scripts/state.py`; `python3` there is the Microsoft Store stub) |
| Claim | `python3 scripts/claim.py take|renew|release <ID>` (same Windows note) |

## Audit (from `PROJECT_STATE.json` → `audit_rule`)

- Plan stage: a clean plan round before any ticket is cut. Code stage: one target, the integrated diff `origin/main..<branch>`, after every build ticket is closed.
- Cap: three rounds **per stage**. Round N>1 reviews only round N-1's fixes and their interactions.
- Gate (paste into every auditor brief): a finding blocks only if it can put a **wrong number in front of a user or on a broker order**, or **corrupt persisted data**. A comment blocks only if it misstates mechanism (a competent reader acting on it would write a wrong change). Do not report anything else at all. Undecidable → not gate-level.
- Only gate findings are fixed in-branch (by a fresh implementer). Everything else is logged against main.
- Record each round in the phase entry: reviewer, exact diff range, findings, fixes, outstanding. Commit subjects for a round's record use `round N` (`state.py` counts them against `audit_rounds`); implementers never use `round N` in a subject.
- Statuses: `not_started` → `in_progress` (built, auditing) → `shipped` only once merged with `audit_clean: true`.

## Housekeeping

- `python3 scripts/claim.py renew` every ~2h during the build loop (claims expire after 3h).
- `python3 .k-session/k_session.py checkpoint -m "…"` after each closed ticket **if** `.k-session/` exists on the branch.
- Push the branch after each closed ticket so other sessions can see the work.
- Never merge to `main` without Kenneth's explicit go.
