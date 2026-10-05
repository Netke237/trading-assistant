# TC-UI-04 — Space alternative contracts

Phase: TRADE-CARD-UI-FOLLOWUP

Part of: [Tracking document](TRACKING.md)

Status: ready for implementation

Blocked by: None

GitHub issue: not published (API access Forbidden).

## Requirement

Give Alternatives 1 and 2 consistent columns that use available width, with readable labels, values, score/status and trade-off text. Preserve wrapping at supported minimum widths and all displayed contract fields; display-only rows remain display-only.

## Acceptance criteria

- [ ] Inspect both alternative rows at minimum and wide viewports.
- [ ] All values, labels, status, score and explanation remain readable; rows remain display-only.

## Source locations to inspect

- `frontend/components/molecules/AlternativeContractRow/index.tsx`
- `frontend/components/molecules/AlternativeContractRow/AlternativeContractRow.module.css`

## Validation and closeout

Follow [the reviewed plan](PLAN.md) for frontend checks and shared numeric/persistence guards. Record changed files, tests and browser evidence on completion. A closed build ticket does not clear the phase audit gate. Coordinate shared-file edits serially. Implementation has not started.
