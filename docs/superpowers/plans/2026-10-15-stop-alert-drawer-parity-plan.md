# STOP-ALERT-DRAWER-PARITY — #334

Base: main 473a049a, after #165 / PR #323. Evidence: `docs/superpowers/measurements/broker-path-residuals/stop-direction-t8.md`.

Goal: Portfolio drawer, persisted underlying stops and alerts agree. Never imply a NULL stop will fire. No change to alert firing rules, PATCH provenance, trailing-stop admissibility or missing-quote behavior.

## Decisions and boundaries

Keep the existing gates exactly as characterized for user-set nonpositive values: with a usable checking price, bearish 0/-1 is refused when gates are on; bullish 0/-1 remains accepted as NULL. With gates off, an already-filled order must still be booked, and nonpositive stops are NULL. Make that state explicit in the drawer ("No stop set") and replace the gates-off false "would fire immediately" detail with a truthful "no stop set; STOP_REACHED cannot fire" warning. The existing booking notification must not append a promise that STOP_REACHED will fire for NULL. This chooses the issue's NULL + truthful display option without changing the pre-trade gate policy, so no new policy decision is required.

A generated 0/-1 means unset under `_floor_stop`'s existing contract (also pinned by zero-stop migration and PATCH). Re-anchoring an unset sentinel into a positive stop violates that contract. Apply the floor before re-anchoring generated main stops and structural stops; retain the final floor for positive levels driven nonpositive by the delta. Do not pre-floor user-set main stops before the existing gate check. `stop_required=True` must reject a generated unset stop even with positive delta. Positive generated stops still re-anchor and may cross the quote unchanged.

Alert enable overrides do not affect validity of an estimate: compare the stored stop values to the live underlying, regardless of whether a notification type is enabled. Use `currentPrice` for stocks, `currentStockPrice` for options; never compare an option premium to an underlying stop. Equality is breached. A null main stop disables Estimate and displays no stop; null structural stop is optional. A breached structural stop disables Estimate even when the main stop is valid. Missing/nonpositive live quote keeps both drawer breach warnings and underlying alerts silent; existing estimate price guards remain.

## Task 1 — Drawer / browser alert parity

Files: `frontend/app/(frame)/portfolio/EditDrawer.tsx`, its `__tests__/EditDrawer.test.tsx` (or a dedicated parity test sibling), `frontend/lib/__tests__/alertEngine.test.ts` only if needed. Keep `frontend/lib/alertEngine.ts` behavior unchanged.

Write failing regressions first using the real browser `scanPositions` engine with only stop alert types enabled and a rendered EditDrawer for the same input. Table: stocks/options, Bullish quote120 stops110/120/130 and Bearish quote80 stops90/80/70; both main and structural stops, including main110/structural130. Option premium8.25 deliberately differs. Pin alert types, warning presence and Estimate enabled/disabled together. Include missing quote, unset main stop, and optional unset structural stop controls; stop/structural editor still commits positive crossed stops and 0→null as before. Reuse existing characterized trailing/PATCH cases.

Implement an underlying reference-price and direction breach check matching the existing alert comparisons; apply independently to main and structural stops for both instruments. Render distinct main and structural warnings, disable Estimate for either breach, and show explicit "No stop set" when main is NULL/nonpositive. Preserve existing stock target/price checks and options premium/strike checks. Retain positive trailing stops above entry when below the bullish live quote (vice versa for bearish). Do not derive validity from entry or alert override settings.

Commit: `fix(portfolio): align drawer stop warnings with underlying alerts`.

## Task 2 — Persisted unset stops / truthful booking warning

Files: `backend/app/services/position_writer.py`, `backend/app/services/auto_trade_booking.py`, `backend/tests/test_position_writer_gates.py`, `backend/tests/test_auto_trade_booking.py` (or existing booking test module), and existing stop alert tests only if needed.

Write failing regressions first. Replace the T8 generated-zero characterization with NULL expectations for generated main and structural stops at delta+20; parameterize 0/-1, stock/option, gates on/off. Add stop_required rejection with zero + positive delta. Extend user-zero characterization to both directions/gates/instruments and assert unchanged acceptance/refusal. For gates-off accepted nonpositive user stops assert persisted NULL, no STOP_REACHED from real `generate_alerts`, and truthful warning (no immediate-fire promise). Positive crossed/equality and profitable trailing cases keep their current behavior. Exercise the real booking notification composition for an unset warning and a positive wrong-side stop, to prevent an unconditional "will fire" suffix reintroducing the contradiction.

Before re-anchor, floor generated main and structural stops only. Leave user main raw until after existing gate decisions. For gates off and user nonpositive main stop, return a truthful unset warning through the existing stop-warning outcome and paging path (update its docstring to cover this case). Prevent wrong-side detail being generated for that NULL case; gates-on decisions stay unchanged. Ensure nonpositive user-stop warning is truthful even without checking quote; it is about stored state, not quote direction. Change booking notification composition to describe the warning and ask to correct/verify in Portfolio without asserting STOP_REACHED unconditionally. Positive wrong-side detail itself still says it would fire immediately. Keep existing paging IDs/types and outcome APIs stable.

Commit: `fix(portfolio): preserve unset stops and report booking state truthfully`.

## Validation and delivery

Each implementer records RED failure and GREEN evidence, runs typecheck and full frontend tests; backend implementer runs full backend tests with prepared Python3.11 environment. Coordinator verifies integrated typecheck/full tests after main merge, reusing valid unchanged-source results where applicable. Distinguish baseline failures from introduced defects with evidence; do not alter unrelated tests. No live broker/order/alert delivery calls.

One phase, two child tickets after plan is independently clean. Fresh independent BMad reviewer per round. Gate: wrong user/broker number or corrupted persistence only; mechanism comments only if they would cause a wrong change; report nothing below gate. Three rounds per stage. Round1 whole target; later only prior fixes/interactions. Record exact scope/reviewer/findings/fixes/outstanding in PROJECT_STATE.json. Code audit only after both tickets built and main integrated. PR closes #334; self-merge only if all board step7 conditions hold, otherwise report the actual failed condition.
