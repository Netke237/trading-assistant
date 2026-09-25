<!-- k-session-reconciliation:begin -->
## Session handoff (all agents)

This repo uses a model-agnostic handoff protocol so an interrupted task can be
continued by any agent, user or container.

- **Before doing anything**, if `.k-session/K-SESSION.md` exists on your branch:
  run `python3 .k-session/k_session.py resume`, read `.k-session/K-SESSION.md`,
  summarize goal / done / next steps / blockers to the user and **wait for
  confirmation** before continuing.
- While working: keep `.k-session/K-SESSION.md` current and run
  `python3 .k-session/k_session.py checkpoint -m "<what changed>"` after each
  meaningful step (it commits WIP and pushes).
- Before stopping: update K-SESSION.md, then `python3 .k-session/k_session.py release`.
- Never write secrets, emails, personal names, absolute container paths or
  chat transcripts into `.k-session/`. Use repo-relative paths.
- Follow the *Conventions* section of K-SESSION.md regardless of which model you are.
- When the task is complete: `python3 .k-session/k_session.py finish`.
<!-- k-session-reconciliation:end -->

<!-- task-claims:begin -->
## Task claims (all agents)

Many sessions work this repo at once and none can see another's unpushed work.
Before you start a task, claim it; the `claims` branch is the shared ledger
(this rule is the explicit permission to push to it — only via the script).

- Session start prints active claims. **Never start a task claimed by another branch.**
- `python3 scripts/claim.py take <TASK-ID> -m "<one line>"` before writing code
  (use the PROJECT_STATE.json id when one exists). Exit 1 = taken → pick something else.
- Push your branch often, and `python3 scripts/claim.py renew` every ~2h (claims expire after 3h).
- `python3 scripts/claim.py release <TASK-ID>` when done or giving up.
- `take --force` only when Kenneth reassigns a task; then `git fetch origin <old-branch>` and continue its work.
<!-- task-claims:end -->
