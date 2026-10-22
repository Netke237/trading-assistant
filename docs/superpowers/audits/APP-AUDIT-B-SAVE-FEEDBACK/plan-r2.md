# APP-AUDIT-B-SAVE-FEEDBACK — plan round 2 (stage round 2)

- Reviewer: fresh independent gate-auditor subagent ab3acd4f8542e1988 (bmad-review-adversarial-general), 2026-10-20.
- Reviewed: `docs/superpowers/plans/2026-10-20-app-audit-b-save-feedback-plan.md` at commit e9e22697, SHA256 ed21e76ce0396846c8c5b051fd404767a7871c8f547b401fe0884cc8c199ccdd, against the real code.
- Result: **3 gate findings.**

## F1 — draft cleared on section switch
Sections mount only while their subnav item is active (`page.tsx:80-88`); the footer stays mounted. "Clear draft on unmount" let: edit timezone → switch to Risk → footer → "Saved", zero PUTs (defect case 2 plus one click). Same for brokers, notifications, schedules, invalid strategy override drafts, IV drafts.
Fix: unmount converts a live draft to a persistent `discarded` record, cleared only by that channel's next successful save/commit or reload; tests added.

## F2 — one channel for all schedule-entry fields
`updateEntry` PUTs `{...entry, ...patch}` from the stale server copy (`page.tsx:719-730`); label and Toggle keep local state (`page.tsx:812-814, 1244-1247`). A failed enable followed by a successful fire-time change cleared the enable failure while the server stayed disabled and the toggle showed ON.
Fix: one channel per patched key; label/enabled drafts compare the displayed value with `entry` after refresh; tests added.

## F3 — broker store write outside the tracked attempt
`setAlpacaPaper` etc. run before `postCredentials` (`page.tsx:1969-2004`); a storage throw skipped the POST with no tracked attempt, and the footer's local retry then reported "Saved" though the server never got the credentials.
Fix: `trackSave`'s `run` includes every pre-request step that can stop the request (the broker store write); tests added.

## Below the gate (not fixed)
None reported beyond confirmations: zustand 5.0.15 persist write order, unchanged keys/versions/serialization, OverrideInput catch still receives re-thrown errors, single-tab retry bytes equal memory, every blur save calls trackSave synchronously, api helpers throw on non-OK.
