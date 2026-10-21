# APP-AUDIT-B-REGIME-RACE — code round 1

- Reviewer: fresh independent `gate-auditor` subagent (a9e150f6389457db6), bmad-review-adversarial-general
- Reviewed: `git diff origin/main..3b573df6` (whole integrated diff) against the clean plan
- Result: **GATE FINDINGS: 0** — code stage clean.

Checked: `regimeFetchOrder.ts` implements the newest-applied rule and writes the three gate fields together (direction at write time, Settings Markov values at request time); Step 1 (shared ticket + Step-1-only seq; failure only for the latest started request; `markov` still refetches), Step 2 (Refresh ticket; `lastRefreshed` only when applied), Step 3 (refs only when applied); backend `horizon` unused. Remaining direct writers are synchronous direction recomputes whose source data cannot diverge from the gate's owning response (Steps 1–3 are never mounted together). Walked same-mount Markov change/Retry, remounts, StrictMode double effects, cross-page orders, Step 2 Refresh across mounts, older-first / newer-fails / older-fails-later, hard-reload hydration order, saved-context restore: every remaining stale/PENDING case is one the plan accepts and none is worse than before. Targeted suites 8/39 green; typecheck clean; browser evidence consistent.
