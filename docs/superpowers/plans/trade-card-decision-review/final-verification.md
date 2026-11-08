# TRADE-CARD-DECISION-REVIEW: final implementation verification (#584)

This is the implementer's verification of the finished phase. It is **not** the independent code audit. That audit runs afterwards with a separate auditor, and `audit_clean` stays false until it comes back clean.

TRADE-CARD-DECISION-REVIEW COMPLETE: implementation verification is complete. The independent code audit is still required and has not run.

The mini-PC comparison is user-deferred and not verified. One finding needs the coordinator's decision (FINDING 1 below).

## Revisions

| What | Value |
|---|---|
| Baseline inventory | `c8f3b8a2cb5f0fa7e74fc0da407d1716a381fc6b` |
| Tested tree | `28f5425a81e88449b91b924bbd75ef03dac8b306` plus the working-tree changes committed as `test(trade-card): verify review and information parity (#584)` |
| origin/main merge | Not merged here. The coordinator merges it before the code audit, and the head changes then. |
| Python | 3.11.9 (`backend/.venv`) |
| Browser | Playwright 1.62.1, bundled Chromium, headless |

Backend application code did not change in #584. The backend run started at `28f5425a`.

## Commands and results

| Command | Result |
|---|---|
| `cd frontend && npm run typecheck` | Pass (`tsc --noEmit`, no errors) |
| `cd frontend && npm run test` | 336 suites: 333 passed, 3 failed. 6209 tests: 6206 passed, 3 failed. Run while pytest was running. |
| `npx jest --testPathPattern step-7-trade-card/__tests__/submission-review` (alone, after) | 8/8 passed: the one failure in the full run was a 5 s timeout under load |
| `cd backend && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` | 10124 passed, 12 failed, 11 skipped, 1 error, 2690 s. Run while Jest and `next dev` were running. |
| `pytest tests/test_tradier_admission_daily_risk.py tests/test_tradier_governor_sites.py` (alone, after) | 35 passed: their two failures in the full run did not reproduce alone |
| `python scripts/state.py --quiet` | Exit 1, one drift line: the phase is `in_progress` in PROJECT_STATE.json while the probe now finds the marker in this file. Expected; the coordinator owns that state and this ticket does not edit it. |
| `PYTHONUTF8=1 python validate-final-register.py` | PASS: 625 of 625 ids accounted for; 6 width/theme runs, 7 states each |
| `PYTHONUTF8=1 python validate-evidence.py` (clean checkout, `core.autocrlf=false`, `core.longpaths=true`) | PASS |

Remaining Jest failures, both the known Windows locale pair: `BarrierRaceCard` "2,000 paths" and `StockSendDialog.session` "4,470".

Remaining backend failures, all in the known unrelated files: `test_atomic_yaml` (3), `test_heston_rr_overpricing_probe` (4), `test_payload_persistence_atomicity` (3), and the error in `test_historical_store_settle::test_19`.

## Register reconciliation

[final-register.json](final-register.json) and [final-register.md](final-register.md) give each baseline id a final file, line, anchor, region and disclosure. `build-final-register.py` finds each item in the finished source by its own baseline anchor or excerpt, then derives the status from where it was and is. Judgement calls are in its `OVERRIDES` table, each with a reason. `validate-final-register.py` fails if an id is missing or extra, if an anchor is not on its recorded line, if a required reason or twin is absent, or if a capture check regressed.

| Status | Count |
|---|---|
| kept | 554 |
| moved | 48 |
| moved-into-expansion | 9 |
| changed-with-reason | 13 |
| deliberate-duplicate-removed | 1 |
| **Total** | **625** (520 + 67 + 38) |

**Information lost: none found.** Separately from the register, every user-visible string on a line removed from TradeCard, BarrierRaceCard, SendToBrokerDialog and the Step 7 page since the baseline was searched for in the finished frontend. Seven were absent, and all are accounted for:

| Baseline text | Now |
|---|---|
| "Shared computed stock stop" | "Calculated stock stop", same value |
| "Stock ratio / geometry" column | Row title (`2:1 target`) and geometry line |
| "Arithmetic stock target" column | "Original arithmetic stock target", per-row expansion |
| "Effective stock target" column | "Resolved stock target (used for valuation)", visible |
| "Target geometry" summary | "Original target, snap geometry and pricing" |
| Ladder note ending "...shown separately below." | Ends "...shown in the Final Recommendation below." |
| "Repriced at the median barrier day" | "Stock stop repriced once (touch median or fallback day)", D1 correction |

The one duplicate removed is N50: the four execution echo rows in the Final Recommendation. At Step 7, SubmissionReview states the same inputs from the submitted request. The rows still render when a TradeCard is used without a review.

`rendered_in_expanded_capture` records whether an item's visible text appeared in the fully opened calculated capture. It holds for 107 of the 194 items with a static text probe. The rest are conditional states that the calculated snapshot does not show, and those rest on source location and the suites below. This is supporting evidence, not 625 runtime assertions.

## Coverage map

Existing suites were read first. Tests were added only where a flow was covered in pieces and never end to end.

| Flow | Already covered by | New in #584 |
|---|---|---|
| Fresh card, on-demand only | `TradeCard.monteCarloPresentation` (before a run), `TradeCard.methodComparison` (no request on compare) | Page mount fires no calculation or write (`integrated-flows`) |
| Restored | `TradeCard.methodComparison`, `TradeCard.monteCarloPresentation`, `edited-fields-sync`, `a8-rail-and-structural-cache` | Persisted slice reaches draft and preview; restored results stay labelled with no calculation |
| Edited and reverted | `TradeCard.exitSettings`, `edited-fields-sync`, `submission-review` | Restored edit reverted: plan stop, new draft generation, new preview |
| Contract switch | `TradeCard.methodPick`, `submission-review`, `broker-review` | Nothing borrowed; comparison choice kept (`TradeCard.verification`) |
| Overrides | `TradeCard.orderBudget`, `contracts-sync`, `entry-overrides-from-scan`, `rr-overrides-from-scan`, `identity-market-context` | None needed |
| All methods | `TradeCard.methodPick`, `submissionDraft` | Each of four methods, card to preview to stored request |
| Three-method comparison | `TradeCard.methodComparison` | Browser alignment at three widths |
| Stale and re-run | `TradeCard.methodPick`, `TradeCard.monteCarloPresentation`, `BarrierRaceCard` | Edit clears only the race; re-run restores it and chooses nothing |
| Quantity and entry changes | `TradeCard.exitSettings`, `TradeCard.methodPick`, `BarrierRaceCard`, `trackingReview` | One edit across every method, each on its own basis, no new calculation |
| Spreads | `TradeCard.arithmeticComparison`, `submission-payload-golden`, `submission-review`, `identity-market-context` | Basket row server-reviewed, selected contract only |
| Unavailable estimates | `TradeCard.arithmeticComparison`, `TradeCard.monteCarloPresentation`, `BarrierRaceCard`, `TradeCard.exitSettings` | None needed |
| Fallback targets | `submissionDraft`, `submission-review`, `trackingReview`, `test_position_review` | Fallback shown with its reason on basket and broker reviews |
| Backend adjustments | `test_position_review`, `trackingReview`, `broker-review` | Re-anchor shown on both review surfaces |
| Tracking review versus stored row | `trackingReview`, `basket-tracking-review`, `test_position_review` | Stored body equals reviewed body for every method |
| Pending sync | `trackingReview`, `basket-tracking-review` | None needed |
| Partial and network failures | `basket-tracking-review`, `broker-review`, `direct-send-save-first` | None needed |
| Mocked broker responses | `brokerReview`, `broker-review`, `directOrder`, `direct-send-save-first` | Literal "None"/"null" order id (check b) |
| Disclosure defaults | `TradeCard.exitSettings`, `BarrierRaceCard`, `TradeCard.scoreDisclosure` | Whole computed card at once |
| Auto-trade and arm ownership | `edited-fields-sync`, `contracts-sync`, browser (portable checks) | None needed |
| Outbound payload parity | `submission-payload-golden` | None needed |
| Comparison layout | None effective: jsdom applies no CSS | Browser measurement and a CSS rule test |

New files: `frontend/components/organisms/TradeCard/__tests__/TradeCard.verification.test.tsx` (7 tests) and `frontend/app/(frame)/screener/step-7-trade-card/__tests__/integrated-flows.test.tsx` (15 tests).

No numerical golden changed. `BarrierRaceCard.test.tsx` changed its bar-width expectations in #579 because plan #579 requires allocated weights (D2). No backend fixture or golden file changed in the phase.

## Specific checks

**a. Card-level "Unresolved until server review"** (`SubmissionReview/index.tsx:166-167`). This is correct under plan #581: until server evidence exists, effective values are labelled unresolved, and no TypeScript copy of the routing rule is allowed. The card review never receives a preview, so it keeps saying this while the basket and broker reviews show server values. `integrated-flows` pins both, and that the card does not borrow the server value. It gives no number that could be wrong. A small wording gap remains: the label does not say the server review opens from Track basket or Place Limit. See NOTICED below.

**b. Order id "None" or "null"** (`lib/directOrder.ts:105`). Reachable, but only from a malformed broker reply. See FINDING 1.

**c. Numeric inventory.** Section 1 of `2026-10-10-numeric-api-inputs-plan.md` now records `POST /api/portfolio/preview` and its 4 untyped leaves, taking the count from 35 to 39. Documentation only.

## Browser captures

`capture-final-verification.cjs`, Next dev on 127.0.0.1:3097 with `NEXT_PUBLIC_API_URL=http://127.0.0.1:8097` (nothing listens there). The server was stopped afterwards and port 3001 was not touched. Output is in [evidence/final](evidence/final): widths 1200, 1366, 1920; dark and light; seven states each (initial, calculated with all three methods compared, stale, restored, basket review, broker review, outcome). Images were downscaled and palette-reduced to keep the set to about 5 MB.

- **Unsafe-write guard:** in all six runs no write was blocked because none was attempted outside the allow-list, and no external host was contacted. The only non-calculation writes were one `POST /api/portfolio` and one `POST /broker/option-order` per run, both answered inside the browser's route layer after the final confirmation of the outcome state. No arm or fire request occurred.
- **Measured at every width and theme:** no horizontal page overflow in any state; compared cards in a row have equal height; basis, stop and target slots align across a row; target rows keep readable width; editable affordances visible; every `<details>` closed, scores and alternatives collapsed, Ladder open by default.
- **Layout:** three cards never fit side by side at these widths. 1920 and 1366 show two cards and the Ladder on the next row; 1200 stacks them. This matches the plan's "at fitting widths" wording.

## Limitations

- **Mini-PC comparison: user-deferred, not verified.** Nothing here shows the pinned source equals the running mini-PC build.
- All browser data is synthetic and mocked. No real broker, backend or pricing ran in the captures.
- The browser checks cover the states listed, on one fixture, on Chromium only. Spread cards, tiny premiums and failure states are covered by Jest, not captures.
- A broker review of a spread was not exercised: spreads are bearish, and direct sends of bearish cards are gated.
- `validate-evidence.py` hashes committed bytes, so on this Windows CRLF checkout it fails on line endings. It passed on a clean checkout with `core.autocrlf=false`.

## FINDINGS

**FINDING 1: a reply the backend records as outcome-unknown can read as placed.** Pre-existing logic (`lib/directOrder.ts` is unchanged since the baseline). Path: `tradier_paper.py:149` and `ibkr_paper.py:175` build `order_id` with `str(...)`, so a 2xx reply with a JSON null id becomes the text `"None"`. `routers/broker.py:591` serves it with HTTP 200, and `routers/broker.py:457-458` records `outcome-unknown` because its `_UNUSABLE_ORDER_IDS` includes `none` and `null`. `classifyDirectFailure` (`lib/directOrder.ts:105`) refuses only empty and `unknown`, so the verdict is `placed` (`page.tsx:1329`). The page shows "Order placed — ID: None" beside an outcome saying Order ID "Not reported", and leaves no persistent ORDER-UNKNOWN note. `lib/stockDirectSend.ts` shares it. Not reachable from Tastytrade (`PlacedOrder.id` is a required int in tastytrade 13.2.3) or Alpaca (a null id serves as an empty string, which keeps the row). No price or quantity is wrong and the tracked row stays. Not fixed: it is outside this ticket's files and is a behaviour decision. `integrated-flows` pins today's behaviour and must change if it is aligned.

**FINDING 2 (fixed in #584): Ladder values collapsed in the comparison grid.** With the Ladder moved into a comparison-width card by #580, its source note and pricing badge left the values no width: `.targetMain` measured 0 px at 1366 and 1920, and 53 px at 1200, so the option, outcome and stock figures overlapped. Baseline rows were full width. Restored with two CSS rules scoped to `.methodGrid` (`TradeCard.module.css`). RED: the browser check and the CSS rule test both failed first. GREEN: all six runs report no squeezed row.

## NOTICED, not changed

- The Arithmetic targets slot sits 8 px below Monte Carlo's in the same row, from `.structuralStop`'s margin. Cosmetic.
- `SubmissionReview` could name where the server review happens (check a).
- The broker review does not repeat the "selected contract only" spread caution. The card-level review does.
- `backend/tests/test_request_finite_inventory.py`'s module docstring still says "(35)"; its constant is 39.
