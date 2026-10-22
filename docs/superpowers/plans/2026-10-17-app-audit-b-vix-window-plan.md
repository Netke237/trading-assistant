# APP-AUDIT-B-VIX-WINDOW — use252 prior VIX observations (#369)

Independent remediation phase from #350, user-authorized. Existing evidence
and its review counters remain immutable. No calibration, OMM/HMM policy,
provider execution, orders, notifications or jobs are part of this fix.

## Mechanism

get_regime fetches260 daily VIX bars, treats the last entry as the current bar,
and ranks current fetched VIX against all259 prior closes for vix_pct_252d.
The UI labels that field252d. The30-day slice already selects the last30 prior
closes. Repair only the252 prior-history selection to vix_closes[-253:-1].
Retain _vix_percentile's strict comparison/rounding, quote lookup behavior,
last-entry exclusion and existing available-history behavior for short input;
do not invent a new insufficient-data policy or change window calibration.

## Task1 — endpoint regression and bounded history

Fresh implementer owns backend/app/routers/regime.py plus focused backend
regression tests (a new test_vix_percentile_window.py is suitable). A frontend
Step1 display test may be added if needed to pin response label/value; no
frontend production behavior should change.

1. First add a failing deterministic test calling the actual async get_regime
   with patched market providers, OMM/HMM functions and unrelated metrics;
   no app.main lifespan or actual provider access. Freeze260 closes as seven
   oldest1, next252 at100 and current50. Independent expectation is0.0percent;
   assert actual endpoint response252d value, and30d remains0.0. Confirm RED
   from the current2.7percent result, not a mock/setup error.
2. Bound only252-history selection as above. Add independently calculated
   ties, values below/above every observation, exactly253 entries, extra old
   outliers and fewer than253 entries. Empty/one-entry data must retainNone
   behavior; short nonempty prior windows keep existing available-history
   convention. Explicitly prove the last historical entry never enters either
   reference window. Maintain the strict percentile and rounding convention.
3. Verify Step1 consumes vix_pct_252d with its252d label; capture a mocked UI
   display assertion or existing relevant rendering regression. Do not claim
   a live provider/browser verification from a Python helper test.
4. Run focused tests, full backend pytest with prepared Python3.11, frontend
   typecheck and full frontend suite as required by repository instructions.
   Run tests with isolated config/database paths; do not start real jobs or
   broker paths. Record commands/counts/RED-GREEN, retaining baseline failures
   honestly if any; no unrelated fixes or regenerated numerical goldens.
5. Commit only owned source/tests, no coordinator state/audit changes or push.

## Review and closure

Fresh independent plan reviewer before the build ticket. Fresh independent
code reviewer on integrated main..phase diff afterward;3-round cap per stage,
later rounds only fixes/interactions, numeric/persistence gate. Coordinator
merges current main before code1 and records exact diff/reviewer/results.
Self-merge only under every board.md condition with CI green at the exact head.
