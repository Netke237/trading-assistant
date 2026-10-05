# TC-UI-02 — Unify recommendation and exit-method presentation

Phase: TRADE-CARD-UI-FOLLOWUP

Part of: [Tracking document](TRACKING.md)

Status: build complete; integrated phase audit pending

Blocked by: None

GitHub issue: not published (API access Forbidden).

## Requirement

Place the exit-method selector beside Final Recommendation. Display the selected method's available results rather than unrelated latest calculation results. Ladder uses its existing live defaults; Arithmetic, Monte Carlo and Barrier Race use their own valid results. If selected results are absent, stale or invalid, show a clear calculation prompt or invalidation message instead of another method's targets. Changing selection does not run calculations or apply execution values. Preserve existing eligibility gates, backend semantics, freshness checks, stop-basis distinctions, persistence and explicit application actions. Audit all consumer callbacks so display changes cannot silently change execution or broker payloads. Cover both scan paths where these controls exist.

## Acceptance criteria

- [x] Test each supported selected method with available, missing and stale results, including no explicit selection.
- [x] No stale or unrelated targets appear; selection neither computes nor applies values.
- [x] Verify stop basis, race freshness, selection invalidation and execution/persistence callbacks remain correct.

## Source locations to inspect

- `frontend/components/organisms/TradeCard/index.tsx`
- `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`
- `frontend/components/organisms/StockPositionCard/index.tsx`

## Validation and closeout

Follow [the reviewed plan](PLAN.md) for frontend checks and shared numeric/persistence guards. Record changed files, tests and browser evidence on completion. A closed build ticket does not clear the phase audit gate. Coordinate shared-file edits serially. Implementation complete. Frontend typecheck and full Jest suite passed (203 suites, 4,720 tests). Browser coverage uses installed Chromium and temporary local font mocks; production Google-font metrics are unverified. Detailed validation and phase audit are recorded in PROJECT_STATE.json and the implementation evidence.
