# APP-AUDIT-B-TIMEZONE-RACE — independent plan round 1 of 3

Reviewer: fresh independent subagent `4cc7065a-3c7a-4780-aa4e-95f344274a61`, applying `.claude/skills/bmad-review-adversarial-general/SKILL.md` and the repository numeric/persistence gate. GATE FINDINGS: **3**.

Exact reviewed artifact: `docs/superpowers/plans/2026-10-19-app-audit-b-timezone-race-plan.md`, lines 1–110.

Findings:
1. `frontend/app/(frame)/settings/page.tsx:476-486`: `handleSave` without prior typing left `isDirty.current` false, allowing a late initial GET to overwrite a saved setting.
2. `frontend/app/(frame)/settings/page.tsx:479`: In-flight `putSchedulingTimezone` resolution unconditionally calling `setTz(res.timezone)`, clobbering edits made while save was in flight.
3. `frontend/app/(frame)/settings/page.tsx:476-486, 502-504`: Rapid Save clicks dispatching concurrent out-of-order PUTs due to lack of re-entrancy lock and enabled button.

Action: Plan updated to address all 3 gate findings (setting `isDirty.current = true;` in `handleSave`, functional updater `setTz((current) => (current === submittedTz ? res.timezone : current))`, `saving` lock + `disabled={saving}` on button, and expanded test coverage for cases 5, 6, 7). Proceeding to Round 2.
