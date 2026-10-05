# TC-UI-01 — Align Order Entry and Exit Plan values

Phase: TRADE-CARD-UI-FOLLOWUP

Part of: [Tracking document](TRACKING.md)

Status: build complete; integrated phase audit pending

Blocked by: None

GitHub issue: not published (API access Forbidden).

## Requirement

Use consistent label/value columns and right-aligned values within each card; align card headings and row baselines where corresponding rows permit it. Order type, limit, max fill, contracts, invalidation, premium stop and time exit remain legible, including editable and missing-value states. Units stay attached to values. Numeric inputs retain existing validation and callbacks.

## Acceptance criteria

- [x] Read-only, editable and unavailable values align without clipping at supported widths.
- [x] Inputs retain units, validation and callbacks; order payloads are unchanged.

## Source locations to inspect

- `frontend/components/organisms/TradeCard/index.tsx`
- `frontend/components/organisms/TradeCard/TradeCard.module.css`

## Validation and closeout

Follow [the reviewed plan](PLAN.md) for frontend checks and shared numeric/persistence guards. Record changed files, tests and browser evidence on completion. A closed build ticket does not clear the phase audit gate. Coordinate shared-file edits serially. Implementation complete. Frontend typecheck and full Jest suite passed (203 suites, 4,720 tests). Browser coverage uses installed Chromium and temporary local font mocks; production Google-font metrics are unverified. Detailed validation and phase audit are recorded in PROJECT_STATE.json and the implementation evidence.
