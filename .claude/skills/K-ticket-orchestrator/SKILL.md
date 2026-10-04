---
name: K-ticket-orchestrator
description: 'Central coordination for a multi-ticket build: turn an audited implementation plan into GitHub tickets under one tracking issue, then drive fresh implementer subagents ticket by ticket (blockers first), verify each, keep the tracking issue current, and finish with the independent adversarial code audit and a PR. Use whenever Kenneth says "break this plan into tickets", "create the GitHub issues", "spawn subagents to implement/test/audit", "coordinate the build", "run the tickets", "orchestrate this plan", or hands over a plan file and wants it built without managing the steps himself. Works in local sessions and cloud containers.'
---

# K-Ticket Orchestrator

Kenneth wants **one coordinator and one place to look**. You are the coordinator: the only agent that talks to Kenneth, writes the project state file, edits the tracking issue and runs audits. Subagents do the building; they never coordinate.

The single place Kenneth looks is the **tracking issue** on GitHub. Keep it true at every step. If he has to read a subagent transcript or a commit log to know where things stand, the skill has failed.

## Roles

| Role | Who | Does | Never does |
|---|---|---|---|
| Orchestrator | this session | tickets, frontier, spawning, verification, tracking-issue updates, state file, audits, PR, reports to Kenneth | write feature code itself (except trivial merge glue) |
| Implementer | fresh subagent per ticket (`ticket-implementer` agent if defined) | one ticket, test-first, commits on the integration branch, reports back | touch other tickets, edit the state file's audit fields, review its own work as an audit |
| Gate auditor | fresh subagent per audit round (`gate-auditor` agent if defined) | applies `bmad-review-adversarial-general` to the plan or the integrated diff, reports gate findings | fix anything, see previous rounds' findings |

## Before you start: read the repo contract

1. `CLAUDE.md` (and `AGENTS.md` if present): build/test commands, audit rule, claim rules, session-handoff rules.
2. `docs/agents/issue-tracker.md`: how this repo's tickets work. Missing → run the setup in [Setup](#setup-once-per-repo) first.
3. `docs/agents/ticket-orchestration.md` if present: the repo's own overrides (gate wording, state file, commands). **It wins over this skill where they differ.**
4. The repo's audit rule (in trading-assistant: `docs/superpowers/PROJECT_STATE.json` → `audit_rule`, and `.claude/skills/K-adversarial-audit-loop/SKILL.md`).

## The flow

```
plan ──► plan audit (clean) ──► tickets + tracking issue ──► build loop ──► code audit (clean) ──► PR ──► Kenneth merges
           gate-auditor            orchestrator               implementers     gate-auditor
```

### 1. Preconditions (stop and tell Kenneth if one fails)

- A written plan with numbered tasks exists and is committed on a feature branch (never `main`).
- The work is **claimed** per the repo's claim rule, and the phase/target exists in the state file.
- The **plan audit is clean** (or the repo has no plan-audit rule). Tickets cut from an unaudited plan copy its errors into every ticket. Run the plan audit via `K-adversarial-audit-loop` audit-only mode if it has not run.
- `gh auth status` succeeds. In a cloud container without `gh` auth, use the GitHub MCP tools if present; otherwise stop and tell Kenneth. Do **not** silently switch to a local tracker: the point is one shared place.

### 2. Cut the tickets

One ticket per plan task, unless two tasks are inseparable (then one ticket naming both). Each ticket is a vertical slice that ends green (`typecheck` + tests) on its own.

Work out **blocking edges** from the plan, not from task order alone:
- B needs code or tests A creates → A blocks B.
- A and B edit the **same file** → serialize them (pick the plan's order). This is the usual reason parallelism is not worth it.
- The final verify/audit/PR task is the orchestrator's ticket and is blocked by every other ticket.

Create, in this order (bodies in [templates.md](templates.md)):
1. Labels if missing: `tracking`, `ready-for-agent`, `agent-in-progress`, `blocked`, plus one feature label (kebab-case of the phase id).
2. The **tracking issue** (label `tracking` + feature label).
3. One child issue per ticket (feature label; `ready-for-agent` only if it has no blockers). Link each as a **sub-issue** of the tracking issue and add native **blocked-by** dependencies (commands in `docs/agents/issue-tracker.md`). If either API is unavailable, the `Part of` / `Blocked by` lines in the body are the fallback; say so in the tracking issue.
4. Edit the tracking issue's checklist with the real issue numbers. Record the tracking issue number in the state file's phase note.

Show Kenneth the tracking issue link and the ticket graph before building, then continue unless he objects. (Cutting tickets is not irreversible; building is cheap to stop.)

### 3. Build loop

Repeat until no open child ticket remains:

1. **Frontier** = open children whose blockers are all closed. Empty but tickets remain → a cycle or a `blocked` ticket: stop and tell Kenneth.
2. **Sequential by default**: take the first frontier ticket in plan order. Run tickets in parallel only when they touch **disjoint files**; then give each its own worktree (`Agent` with `isolation: "worktree"`) and merge each result into the integration branch yourself, re-running the checks after every merge.
3. Mark it: `--remove-label ready-for-agent --add-label agent-in-progress`; tick nothing yet.
4. Spawn **one fresh implementer** (`run_in_background: false` when sequential) with the brief in [templates.md](templates.md). Never reuse an implementer across tickets.
5. **Verify, don't trust.** When it returns: check the commits exist on the branch (`git log`), re-run the repo's typecheck and full test command yourself, and confirm only files the ticket allows changed (`git diff --stat <before>..HEAD`). Self-reported "all green" is not evidence.
6. Outcome:
   - **Done** → comment on the ticket (commits, test counts, any deviation the implementer reported), close it, tick it in the tracking issue, add `ready-for-agent` to any ticket it unblocked, push the branch.
   - **Implementer blocked, or a check fails and one retry with a fresh implementer (given the failure output) also fails** → label `blocked`, comment the exact failure, add it under "Needs Kenneth" in the tracking issue, stop the loop and tell Kenneth.
   - **Implementer reports a plan defect** (plan wrong about the code) → do not let it improvise. Stop, fix the plan (a plan change after a clean plan audit is a new plan-audit round only if it changes behaviour), then continue.
7. Follow the repo's housekeeping between tickets (trading-assistant: `claim.py renew` every ~2h; `k_session.py checkpoint` if `.k-session/` exists).

### 4. Code audit (the shipping gate)

After the last build ticket closes, run the orchestrator ticket:
1. Any end-to-end/manual verification the plan lists (use the `run` skill / app preview); record what you saw.
2. `K-adversarial-audit-loop` **audit-only** on the integrated diff (`<base>..<branch>`) with a fresh `gate-auditor` per round, briefed with the repo's gate (brief in [templates.md](templates.md)).
3. Record each round where the repo says (state file: reviewer, diff range, findings, fixes) and in the tracking issue's Audit section. Fix gate findings only, by spawning a fresh implementer with the finding as its ticket; log non-gate findings, do not fix them.
4. Respect the per-stage round cap. At the cap without a clean round: stop, leave the target not clean, tell Kenneth.

**Per-ticket reviews are never audit rounds.** Auditing each ticket separately would spend the phase's round cap seven times over and breaks the repo rule. The phase (the integrated diff) is the audit target.

### 5. Finish

Only after a clean code round: push, open the PR (link the tracking issue; `Closes #<tracker>`), update the state file (status per the repo's vocabulary: built-not-merged is not "shipped"), release the claim, and report to Kenneth. **Do not merge** unless Kenneth says so.

## Reporting to Kenneth

Every report, at every stop, uses the same shape so nothing is confusing:

```
Tracking issue: <link>
Done:      #12 A, #13 B          (n/total)
Now:       #14 C — implementer running
Next:      #15 D (blocked by #14)
Audit:     plan 1 round, clean · code not started
Needs you: nothing  |  <one sentence, the decision only you can make>
```

## Setup (once per repo)

If `docs/agents/issue-tracker.md` is missing: Kenneth can run `/setup-matt-pocock-skills`, or you write it from that skill's GitHub template, adding the orchestration labels and the sub-issue / dependency commands. Also add to the repo's `CLAUDE.md` an `## Agent skills` section pointing at `docs/agents/` and stating the per-ticket vs per-phase audit rule. Copy this skill and the two agent definitions into the repo's `.claude/` so cloud containers (which only see the repo) have them.
