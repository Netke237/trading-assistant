# TC-UI-04 — Space alternative contracts

Phase: TRADE-CARD-UI-FOLLOWUP

Part of: [Tracking document](TRACKING.md)

Status: build complete; integrated phase audit recorded in CODE-AUDIT.md

Blocked by: None

GitHub issue: not published (API access Forbidden).

## Requirement

Give Alternatives 1 and 2 consistent columns that use available width, with readable labels, values, score/status and trade-off text. Preserve wrapping at supported minimum widths and all displayed contract fields; display-only rows remain display-only.

## Acceptance criteria

- [x] Inspect both alternative rows at minimum and wide viewports.
- [x] All values, labels, status, score and explanation remain readable; rows remain display-only.

## Source locations to inspect

- `frontend/components/molecules/AlternativeContractRow/index.tsx`
- `frontend/components/molecules/AlternativeContractRow/AlternativeContractRow.module.css`

## Validation and closeout

Follow [the reviewed plan](PLAN.md) for frontend checks and shared numeric/persistence guards. Record changed files, tests and browser evidence on completion. A closed build ticket does not clear the phase audit gate. Coordinate shared-file edits serially. Implementation complete. Frontend typecheck and full Jest suite passed (203 suites, 4,720 tests). Browser coverage uses installed Chromium and temporary local font mocks; production Google-font metrics are unverified. Detailed validation and phase audit are recorded in PROJECT_STATE.json and the implementation evidence.

Integrated review: [CODE-AUDIT.md](CODE-AUDIT.md). See [validation evidence](evidence/README.md) for screenshots and limitations.
