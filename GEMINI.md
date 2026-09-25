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
