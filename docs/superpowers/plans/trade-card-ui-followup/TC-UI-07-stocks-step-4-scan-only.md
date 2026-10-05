# TC-UI-07 — Stocks scans start at Step 4

Phase: TRADE-CARD-UI-FOLLOWUP

Part of: [Tracking document](TRACKING.md)

Status: build complete; integrated phase audit recorded in CODE-AUDIT.md

Blocked by: None

GitHub issue: not published (API access Forbidden).

## Requirement

Hide/remove the RunScanButton on Step 3 only when screenerMode is stocks. Step 3 continues to configure parameters and navigate. Keep the Stocks Step 4 scan action and its latest parameter handoff, confirmations and error handling. Options and Pre-Breakout Step 3 behavior remains unchanged. Parameter navigation must not start a Stocks scan implicitly.

## Acceptance criteria

- [x] Stocks Step 3 has no scan button and navigation does not initiate a scan.
- [x] Stocks Step 4 still runs with latest Step 3 parameters and preserves confirmation/error behavior.
- [x] Options and Pre-Breakout Step 3 actions remain unchanged.

## Source locations to inspect

- `frontend/app/(frame)/screener/step-3-direction/page.tsx`
- `frontend/app/(frame)/screener/step-4-stocks/page.tsx`
- `frontend/components/organisms/RunScanButton/index.tsx`

## Validation and closeout

Follow [the reviewed plan](PLAN.md) for frontend checks and shared numeric/persistence guards. Record changed files, tests and browser evidence on completion. A closed build ticket does not clear the phase audit gate. Coordinate shared-file edits serially. Implementation complete. Frontend typecheck and full Jest suite passed (203 suites, 4,720 tests). Browser coverage uses installed Chromium and temporary local font mocks; production Google-font metrics are unverified. Detailed validation and phase audit are recorded in PROJECT_STATE.json and the implementation evidence.

Integrated review: [CODE-AUDIT.md](CODE-AUDIT.md). See [validation evidence](evidence/README.md) for screenshots and limitations.
