# NLQ-5 — Final clearance and report

Status: open
Blocked by: NLQ-2, NLQ-3, NLQ-4

## Acceptance
- Full backend suite on Python 3.11 and full Jest + typecheck pass (pre-existing failures named, unchanged).
- The defect marker `spread = 0\.0` is gone from market.py; PROJECT_STATE NO-LIVE-QUOTE phase updated
  (status built, verify switched from defect_marker to a presence probe, audit_rounds, audit_clean true only
  when every ticket's last round was clean); state.py reports no drift.
- Report to Kenneth; NO merge until he says so. Plan's "live check after the build" is scheduled to run
  automatically (Kenneth's rule: data collection runs automatically), not left as a manual step.
