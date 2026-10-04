# K-Ticket Orchestrator — templates

Placeholders are `<ANGLE_BRACKETS>`. Replace every one; never publish a placeholder.

## Tracking issue

Title: `[tracking] <PHASE-ID>: <one-line goal>`

```markdown
**Goal:** <one sentence, Kenneth's words>
**Plan:** `<plan path>` · **Branch:** `<branch>` · **Claim:** `<claim id>` · **Phase:** `<PHASE-ID>`

This issue is the one place to see where the build stands. The orchestrator session keeps it current; subagents never edit it.

## Tickets (blockers first)
- [ ] #<n> <title> — blocked by: none
- [ ] #<n> <title> — blocked by: #<n>
- [ ] #<n> Verify, code audit, PR (orchestrator) — blocked by: all of the above

## Audit
- Plan stage: <n> round(s), <clean / not clean> — <reviewer, date>
- Code stage: not started

## Needs Kenneth
- nothing

## Log
- <date> tickets cut
```

## Child ticket

Title: `<PHASE-ID> T<n>: <outcome in domain words>`

```markdown
Part of #<tracker> · Phase `<PHASE-ID>` · Plan task: **Task <n>** of `<plan path>`
Blocked by: <#a, #b | none>

## What
<2–4 sentences: the behaviour after this ticket, in the project's vocabulary.>

## How
Implement **Task <n>** of the plan exactly as written: its failing tests first, then the code, then its commit message. The plan is authoritative; this ticket is the pointer to it.

## Done when
- [ ] The task's new tests were run and seen FAILING before the change (red), then passing (green)
- [ ] <task-specific acceptance bullet>
- [ ] <task-specific acceptance bullet>
- [ ] Typecheck clean and the full test suite green (counts in the closing comment)
- [ ] Committed on `<branch>`; only files listed in the task changed

## Rules
- This ticket is a build unit, **not an audit target**. Do not edit audit fields in the state file and do not put "round N" in a commit subject.
- If the plan is wrong about the code, stop and report it; do not improvise a different design.
- Anything noticed outside this task: report it, do not fix it.
```

## Implementer brief (Agent prompt)

```text
You are the implementer for ONE ticket in <repo>. Fresh context: you know nothing except this brief and the repo.

Ticket: #<n> (`gh issue view <n>`). Plan: <plan path>, Task <n> — read that task in full before anything else.
Branch: <branch> (already checked out<; or: your worktree is on a branch cut from <branch> at <sha>>). Do not switch branches, do not push.

Read first: CLAUDE.md (conventions, test commands, runtime pins), then every file the task names.

Do:
1. Write the task's tests first, run them, confirm they FAIL for the reason the plan predicts. If they fail for a different reason or pass already, stop and report — that is a plan defect.
2. Implement exactly what the task says. Use the `tdd` skill discipline: smallest change to green.
3. Run <typecheck command> and <full test command>. Both must pass.
4. Commit with the plan's commit message (append the repo's attribution trailer). Only the files the task lists.

Do not: edit docs/superpowers/PROJECT_STATE.json audit fields; review your work and call it an audit; touch files outside the task; fix unrelated issues; put "round N" in a commit subject.

Report back, in this shape:
STATUS: done | blocked | plan-defect
COMMITS: <sha subject>, ...
RED: <test names and the failure seen before the change>
GREEN: typecheck <ok/fail>; tests <suites>/<tests> passed
FILES: <list>
DEVIATIONS: <none | what differed from the plan and why>
NOTICED (not fixed): <none | list>
```

## Gate auditor brief (Agent prompt, one fresh agent per round)

```text
You are an independent adversarial auditor. You did not write this and have no stake in it.
Invoke the `bmad-review-adversarial-general` skill via the Skill tool and apply it to:
<PLAN: the file <plan path>, checked against the real code it names>
<CODE: the diff `git diff <base>..<head>` in <repo>, checked against the plan <plan path>>
<ROUND N>1: ONLY the changes since round N-1 (`git diff <prev-head>..<head>`) and their interactions with already-reviewed code.>

THE GATE (report ONLY findings that meet it; do not report anything else at all):
<paste the repo's gate verbatim. trading-assistant: a finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA. A comment counts only if a competent reader acting on it would write a wrong change (it misstates mechanism). Wording, test hygiene, dead code, style, illustrative figures, latent defects with no reachable path: do not report. If you cannot decide whether something meets the gate, it does not.>

For each finding: id, file:line, the concrete failing scenario (inputs → wrong number / corrupted data), why it meets the gate, suggested fix.
End with: GATE FINDINGS: <count>. Zero is an acceptable answer; say what you checked to reach it.
```
