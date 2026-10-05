# TC-UI-06 — Move horizontal-bar score cards upward in both Stocks and Options

Phase: TRADE-CARD-UI-FOLLOWUP

Part of: [Tracking document](TRACKING.md)

Status: build complete; integrated phase audit recorded in CODE-AUDIT.md

Blocked by: None

GitHub issue: not published (API access Forbidden).

## Requirement

Locate the actual score-bar cards on each Step 7 route and place them directly below stock/selected-contract identity and above Fundamental Health. Group under Stock & contract scores, collapsible and initially expanded. Only render cards meaningful to that scan mode; do not invent an option contract for Stocks. Preserve score totals, component bars, confidence, eligibility and captured evidence associations. Avoid duplicate evidence or duplicate mounted calculation components. Evidence collapse is independently controlled and nested with its owning scores where appropriate.

## Acceptance criteria

- [x] On both mode paths, place existing applicable score-bar content below identity and above Fundamental Health.
- [x] Group starts expanded, remains keyboard-collapsible, and evidence has an independent collapsed default.
- [x] No invented contract score or duplicated calculation/evidence children; totals and qualification remain tied to the same captured data.

## Source locations to inspect

- `frontend/components/organisms/TradeCard/index.tsx`
- `frontend/app/(frame)/screener/step-7-position-card/page.tsx`
- `frontend/components/organisms/StockPositionCard/index.tsx`

## Validation and closeout

Follow [the reviewed plan](PLAN.md) for frontend checks and shared numeric/persistence guards. Record changed files, tests and browser evidence on completion. A closed build ticket does not clear the phase audit gate. Coordinate shared-file edits serially. Implementation complete. Frontend typecheck and full Jest suite passed (203 suites, 4,720 tests). Browser coverage uses installed Chromium and temporary local font mocks; production Google-font metrics are unverified. Detailed validation and phase audit are recorded in PROJECT_STATE.json and the implementation evidence.

Integrated review: [CODE-AUDIT.md](CODE-AUDIT.md). See [validation evidence](evidence/README.md) for screenshots and limitations.
