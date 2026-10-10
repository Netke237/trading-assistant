# The Board — how agents pick up work (all agents)

Kenneth starts a cloud session (Claude or Codex) with one line — "Work the board" — and the agent finds its own work, builds it, audits it and stops before any merge. This file is the contract for that loop. It sits on top of `ticket-orchestration.md` (phase rules, audits, claims) and `issue-tracker.md` (GitHub commands); where they differ, **this file wins for picking and reporting, `ticket-orchestration.md` wins for building and auditing**.

Decided by Kenneth on 2026-10-10 (decision `BOARD-WORKER-2026-10-10` in `PROJECT_STATE.json`).

## The pieces

| Piece | What it is |
|---|---|
| **Board issue** | One pinned GitHub issue labelled `board` (currently **#151**). Its "Queue" section lists every **board item** in priority order — **Kenneth sets the order; agents never reorder it**. Its "Waiting for Kenneth" section lists every item that needs him. |
| **Board item** | One GitHub issue labelled `board-item` = **one phase** (a `phases[]` / backlog id in `PROJECT_STATE.json`). Its body holds the scope, links to the design, and the phase id. **The board item is the phase's tracking issue** — the k-ticket-coordinator never creates a second one. Its build tickets are sub-issues of it. |
| **Blocked-by** | Native GitHub dependencies between board items (e.g. P2 blocked by P1). An item with an open blocker is not ready. |
| **Claim** | `scripts/claim.py` with the board item's phase id. The ledger, not GitHub labels, decides who owns an item. |

### Status labels on a board item

| Label | Meaning | Who sets it |
|---|---|---|
| _(none of the below)_ | Ready if all blockers are closed | — |
| `agent-in-progress` | An agent holds the claim and is working it | the agent, after `claim.py take` succeeds |
| `needs-kenneth` | Waiting for a decision; numbered questions with recommendations are in the last comment | the agent |
| `waiting-merge` | Code audit clean, PR open, waiting for Kenneth's go | the agent |
| `blocked` | Stopped on a failure the agent could not resolve (reason in a comment) | the agent |

Kenneth removes `needs-kenneth` when he has answered; that makes the item ready again. An item closes when its PR is merged (`Closes #<item>`), which unblocks the items behind it.

## The loop (what an agent does when told "work the board")

1. **Bootstrap.** Read `CLAUDE.md`/`AGENTS.md`, this file, `ticket-orchestration.md`. Run `python3 scripts/state.py` (Windows: `python`). `gh auth status` must succeed — if not, stop and say `GH_TOKEN` is missing. Never fall back to a local tracker.
2. **Resume before new work.** For each open board item labelled `agent-in-progress`, check the claims ledger (`git fetch origin claims && git show origin/claims:claims.json`). If its claim has **expired** (or is absent) and its branch exists, switch to that branch and `claim.py take <ID>` — expired claims are purged, so no `--force` is needed (`--force` stays reserved for Kenneth's reassignments). A **live** claim belongs to another agent: leave the item alone. Continue a taken-over item in k-ticket-coordinator **RESUME** mode and log the takeover on the item.
3. **Pick.** Otherwise walk the Board's Queue top to bottom and take the **first** item that is open, has none of `agent-in-progress` / `needs-kenneth` / `waiting-merge` / `blocked`, has no open blocker, and is not claimed in the ledger. Then `claim.py take <phase id>`; exit 1 (someone else took it a moment ago) → go to the next item. On success add `agent-in-progress`.
4. **Decisions first.** If planning the item needs a decision only Kenneth can make (design choice, wording, policy, money/risk), do **not** decide it: comment numbered questions with a recommendation each, add `needs-kenneth`, release the claim, notify (step 8), and go back to step 3.
5. **Run the phase** with the k-ticket-coordinator skill (Codex: follow its rules from `ticket-orchestration.md` and the templates referenced there):
   - no plan yet → write `docs/superpowers/plans/<date>-<phase>-plan.md` (tasks test-first, exact files, the item's acceptance list), add the phase entry to `PROJECT_STATE.json`, run the **plan audit** (fresh independent auditor per round, cap 3). Not clean at the cap → `needs-kenneth`, stop the item.
   - clean plan → cut tickets as **sub-issues of the board item** (START mode, using the board item as the tracking issue), build loop, coordinator verification, item acceptance checklist, **code audit** on `origin/main..<branch>` (cap 3).
   - clean code audit → open the PR (`Closes #<item>`), set the phase to `built` / `audit_clean: true`, replace `agent-in-progress` with `waiting-merge`, release the claim.
6. **Never merge.** Merging is Kenneth's alone, always.
7. **Next.** After a PR (or a `needs-kenneth` stop) go back to step 3. Stop when nothing is ready, or when the session is running low — in that case leave the item `agent-in-progress` with an up-to-date Log entry and the branch pushed, so the next agent can resume it.
8. **Notify Kenneth** on every `waiting-merge`, `needs-kenneth`, `blocked`, and when the queue is empty:
   - update the Board's "Waiting for Kenneth" section;
   - `python3 scripts/board_notify.py "<one line>"` — sends to Kenneth's Telegram when `BAMENDJOU_TELEGRAM_BOT_TOKEN` and `BAMENDJOU_TELEGRAM_CHAT_ID` are set, otherwise prints and exits 0 (a missing Telegram never stops work). One line: tag, item, what is needed, link. **Never put secrets, tokens, account numbers or personal data in it**;
   - end the session with the fixed-shape report.

GitHub does not notify Kenneth of actions taken with his own token, so the Board and Telegram are the only signals he gets.

## Several agents at once

- One agent per board item (phase); several items in parallel. Never two agents on one item: the claim prevents it.
- Items that edit the same files must have a blocked-by edge between them; Kenneth (or the agent that cuts the item) adds it. When in doubt, add the edge.
- Claude and Codex follow the same loop. Every issue/comment/PR text starts with `[claude]` or `[codex]`.
- Edits to `PROJECT_STATE.json` or the Board body: pull/rebase first, change only your own entries/lines, push promptly.

## Adding work

Anyone (Kenneth or an agent asked to) adds an item by creating an issue with the **board item template** below, labelling it `board-item`, adding blocked-by edges, and inserting it into the Board's Queue at the position Kenneth wants (bottom by default). Agents add items only when Kenneth asks.

```markdown
**Phase id:** `<PHASE-ID>` · **Design / spec:** `<path or link>` · **Decision:** `<decision id or none>`
**Blocked by:** <#n, … | none>   ·   **Touches:** <main folders/files, so overlaps are visible>

## Goal
<one or two sentences, Kenneth's words>

## Scope
<what is in; what is explicitly out>

## Acceptance
- [ ] <checkable outcome>
- [ ] Typecheck + full tests green; plan audit and code audit clean (`audit_rule`)

## Log
- [<tag>] <date> created
```

## Report shape (every stop)

```
Board: #<n> <link>
Item:      #<item> <PHASE-ID>: <status>
Done:      <tickets / audits this session>
Now:       <nothing | what is running>
Next:      <next ready item or "queue empty">
Needs you: <nothing | decisions / PRs waiting, with links>
```
