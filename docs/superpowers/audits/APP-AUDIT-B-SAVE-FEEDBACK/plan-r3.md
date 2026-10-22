# APP-AUDIT-B-SAVE-FEEDBACK — plan round 3 (stage round 3, cap reached)

- Reviewer: fresh independent gate-auditor subagent ada9d0942d4ddfcaa (bmad-review-adversarial-general), 2026-10-20.
- Reviewed: round-2 fixes only, `git diff e9e22697 03e5d93c -- docs/superpowers/plans/2026-10-20-app-audit-b-save-feedback-plan.md` (plan SHA256 2d9e986b92849338cf55d8094e3798fb8af5bc2aecfac8fb5d4b7bfe8d8ac8fc) and their interactions with the plan and code.
- Result: **1 gate finding. Not clean. Plan stage at its three-round cap.**

## R3-F1 — a late in-flight attempt clears a newer discarded edit
The rule "success clears the channel's discarded record" let an attempt already in flight when the section was left (it is still the channel's latest attempt) erase the record of a newer edit made during that attempt. Timezone: save Osaka (PUT pending), type Tokyo, switch to Risk, PUT succeeds → footer "Saved", server Osaka, Tokyo never sent (`page.tsx:526, 537, 547-561, 80-96`). Brokers likewise (`page.tsx:1969-2004`).
Proposed fix (written into the plan, **unaudited**): a discarded record stores the attempt sequence at discard time; only an attempt that began after the discard clears it. Test added to T2/T3.

## Below the gate (not fixed)
Confirmed F2/F3 fixes behave as intended; schedule-entry label refresh race undecidable; deleted entry's records persist until reload (conservative); no-op IV Apply clearing a discarded record (below gate).
