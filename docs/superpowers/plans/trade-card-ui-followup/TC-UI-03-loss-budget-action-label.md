# TC-UI-03 — Rename loss-budget action

Phase: TRADE-CARD-UI-FOLLOWUP

Part of: [Tracking document](TRACKING.md)

Status: ready for implementation

Blocked by: None

GitHub issue: not published (API access Forbidden).

## Requirement

Replace Set override with Set trade loss budget. Preserve the existing percent/dollar editor, Apply, Use default, validation, sizing recalculation and separate contract-sizing application. Update accessible labels and tests that query the action.

## Acceptance criteria

- [ ] New action label opens the same percent/dollar editor.
- [ ] Apply and Use default preserve budget behavior; contract count still needs separate sizing application.

## Source locations to inspect

- `frontend/components/organisms/TradeCard/index.tsx`

## Validation and closeout

Follow [the reviewed plan](PLAN.md) for frontend checks and shared numeric/persistence guards. Record changed files, tests and browser evidence on completion. A closed build ticket does not clear the phase audit gate. Coordinate shared-file edits serially. Implementation has not started.
