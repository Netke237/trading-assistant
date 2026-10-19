# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

The repo is `Netke237/trading-assistant` (private); `gh` infers it inside a clone. On Windows the account is already authenticated; in a cloud container check `gh auth status` first and, if it fails, use the GitHub MCP tools or stop and tell Kenneth (do not fall back to a local tracker).

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## Coordinated builds (k-ticket-coordinator)

Multi-ticket builds are coordinated by the user-level `k-ticket-coordinator` skill under one **tracking issue**. Repo-specific rules: `docs/agents/ticket-orchestration.md`.

Labels:

| Label | Meaning |
|---|---|
| `tracking` | The one coordination issue for a phase. Kenneth reads this; only the coordinator edits it. |
| `ready-for-agent` | Child ticket with every blocker closed, waiting for an implementer. |
| `agent-in-progress` | An implementer subagent is working it. |
| `blocked` | Stopped; the reason is in a comment and under "Needs Kenneth" in the tracking issue. |
| `<phase-id-kebab>` | Groups every issue of one phase, e.g. `stocks-step-merge-s1`. |
| `size:XS` / `size:S` / `size:M` / `size:L` / `size:XL` | Exactly one required effort estimate per phase/defect/build ticket; see `task-ratings.md`. |
| `complexity:1` through `complexity:5` | Exactly one required technical-difficulty rating per task, independent of priority/severity. |

- **Sub-issue link** (child under the tracking issue): `gh api --method POST repos/Netke237/trading-assistant/issues/<tracker>/sub_issues -F sub_issue_id=<child-db-id>`.
- **Blocked-by edge**: `gh api --method POST repos/Netke237/trading-assistant/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`.
- `<…-db-id>` is the numeric database id: `gh api repos/Netke237/trading-assistant/issues/<n> --jq .id` (not the `#number`, not `node_id`).
- If either endpoint is refused, the `Part of #<tracker>` / `Blocked by: #…` lines at the top of each child body are the record; note the fallback in the tracking issue.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
