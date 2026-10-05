# TC-UI-05 — Collapse captured scoring evidence

Phase: TRADE-CARD-UI-FOLLOWUP

Part of: [Tracking document](TRACKING.md)

Status: blocked by TC-UI-06

Blocked by: TC-UI-06

GitHub issue: not published (API access Forbidden).

## Requirement

The long gray logs shown in the second screenshot (captured stock/contract evidence, inputs, weights, flags and configuration) go inside an accessible expandable section, initially collapsed. This is only scoring evidence, not Order Entry, Exit Plan, recommendation, risk budget, alternatives or calculators. Keep all evidence available on expansion and preserve captured versus current provenance. Closing the section must preserve child state and must not trigger recalculation or requests.

## Acceptance criteria

- [ ] Evidence is hidden initially and keyboard-expandable with correct aria-expanded.
- [ ] Captured provenance, units, precision and mismatch guards survive expansion.
- [ ] Collapsing logs does not hide bars or execution controls, lose state or trigger calculations.

## Source locations to inspect

- `frontend/components/molecules/ScoreCardPanel/index.tsx`
- `frontend/components/molecules/TradeCardQualification/index.tsx`

## Validation and closeout

Follow [the reviewed plan](PLAN.md) for frontend checks and shared numeric/persistence guards. Record changed files, tests and browser evidence on completion. A closed build ticket does not clear the phase audit gate. Coordinate shared-file edits serially. Implementation has not started.
