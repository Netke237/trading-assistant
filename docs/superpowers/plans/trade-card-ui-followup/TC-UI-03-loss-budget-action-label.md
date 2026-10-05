# TC-UI-03 — Rename loss-budget action

Phase: TRADE-CARD-UI-FOLLOWUP

Part of: [Tracking document](TRACKING.md)

Status: build complete; integrated phase audit recorded in CODE-AUDIT.md

Blocked by: None

GitHub issue: not published (API access Forbidden).

## Requirement

Replace Set override with Set trade loss budget. Preserve the existing percent/dollar editor, Apply, Use default, validation, sizing recalculation and separate contract-sizing application. Update accessible labels and tests that query the action.

## Acceptance criteria

- [x] New action label opens the same percent/dollar editor.
- [x] Apply and Use default preserve budget behavior; contract count still needs separate sizing application.

## Source locations to inspect

- `frontend/components/organisms/TradeCard/index.tsx`

## Validation and closeout

Follow [the reviewed plan](PLAN.md) for frontend checks and shared numeric/persistence guards. Record changed files, tests and browser evidence on completion. A closed build ticket does not clear the phase audit gate. Coordinate shared-file edits serially. Implementation complete. Frontend typecheck and full Jest suite passed (203 suites, 4,720 tests). Browser coverage uses installed Chromium and temporary local font mocks; production Google-font metrics are unverified. Detailed validation and phase audit are recorded in PROJECT_STATE.json and the implementation evidence.

Integrated review: [CODE-AUDIT.md](CODE-AUDIT.md). See [validation evidence](evidence/README.md) for screenshots and limitations.
