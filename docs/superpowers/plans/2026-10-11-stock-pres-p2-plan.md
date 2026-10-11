# STOCK-PRES-P2-POSITION — approved Position presentation

Board #147 is the phase tracker. Approval: STOCK-PRESENTATION-2026-10-10, proposal 02 / README D1–D14. Board rules supersede its older main-planning instructions: all work stays on this unique claimed branch. P1 is merged. This phase is presentation only; no backend, persisted shape, sizing, calculation, gate, payload, numeric golden-pin or broker change. No merge authorized for this new item.

## Architecture and preservation boundaries

The Position page currently wraps shared StockPositionCard; Backtest also renders that component. Introduce an optional presentation variant (`presentation="position"`, default retains the existing embedded rendering). Only the Position route opts into the new workspace. Existing state, session identity, overlay invalidation, ownership, saved quantities, method choices, callbacks and server requests remain authoritative and shared. Do not duplicate the execution/card model or move it to a new store. New components are display-only.

Use the existing compact MarketSentiment and FundamentalHealthCard components without modifying them (screen-label work is owned elsewhere). Position gets compact strips, candidate navigation / identity, section links, order/exits and calculation cards, qualification cards, and a decision/execution right rail using existing tokens and CSS Modules. All controls/notes in the mapping below stay accessible with the same handlers, labels, tooltips, tones and disabled conditions. Default Backtest rendering remains unchanged. Preserve DOM-mounted calculation/control state; disclosures must not unmount controls or invalidate picks.

Numeric displays repeat existing values with their existing scales/units. P1 `stock_explanation` factor components are evidence; `card.stock_status` remains the final capped verdict. Missing legacy evidence shows unavailable, never reconstructed fake factors or zero. Show the real backtest Sharpe, win rate, trades, expectancy, return, max DD, confidence and confidence_text. Thresholds come from the request belonging to the current stock scan (as the existing Backtest page does); absent provenance shows unavailable, never current Settings defaults. Do not relabel scorer evidence as final gate success.

The checklist displays only existing gate_flags, recorded backtest/score results, earnings veto, the existing Unvalidated/block reading, fundamentals evidence, and execution/risk status where actually known. No new enforcement. A risk/exposure/daily limit that is only checked by the backend at save/send is explicitly pending server validation, never a pre-checked pass. Unknown gate/evidence stays unknown. Changes in symbol, scan, method pick and send ownership must update this display.

Latest calculation repeats the latest successfully accepted live response (Arithmetic or Monte Carlo), not a preferred-method priority. Keep chronology UI-local, keyed to execution identity; do not add persistence/session fields. Never show a stale or invalidated result or accept an aborted/revision-mismatched response; use the existing accepted-response guards. On remount, if chronology is unavailable, say that rather than inventing latest order. Select displayed values from the current live plan/estimate object. If a latest result clears, show an explicit unavailable/recalculate state; do not silently call another older result latest. A newly completed result replaces it. Out-of-order async and repeated runs are regression cases.

The race drawing uses the existing `plan.race.outcomes` probabilities/labels only, with direction-accurate target/stop/neither outcomes; do not infer complementary probabilities, convert days to calendar days or invent a new stock race model. Keep original race text, windows, path counts, days and dollar figures. Finite display guards may show unavailable; do not change the calculated values or alter assertions/golden numbers.

## Task 1 — Position workspace and preservation regressions

One fresh implementer; one ticket under #147. This is a single frontend presentation layer. Files allowed:
- frontend/app/(frame)/screener/step-7-position-card/page.tsx and page.module.css
- frontend/components/organisms/StockPositionCard/index.tsx and StockPositionCard.module.css
- display-only component(s) within StockPositionCard/ if needed to keep JSX manageable
- new StockPositionCard/__tests__/StockPositionCard.presentation.test.tsx
- Position route __tests__/page.test.tsx only if adding preservation tests; existing assertions unchanged
- frontend/e2e/tests/stock-position-presentation.spec.ts
- frontend/components/MinWidthGate/index.tsx and its __tests__/MinWidthGate.test.tsx: extend the existing Options trade-card 1200px exception to the Position route only. Preserve the 1280px default for all other routes, media-query cleanup, and mounted children during resize/route changes. Browser discovery found that the current gate blocks the original plan's 1200px test; this is the bounded scope correction. Test both exact Position boundaries (1199/1200) and a stateful child across route/resize changes. Update the old Position-only 1280 expectation to reflect this deliberate new allowance; keep other route expectations intact.

Do not modify backend, stores, API schemas, shared compact molecules, other routes or existing calculation/send tests. The MinWidthGate exception above is the sole shared-shell scope extension, approved by the coordinator to satisfy the planned 1200px browser validation; an independent plan follow-up must clear it before implementation. Reuse types/components/helpers already on main. If the concrete source requires expanding this set, report the need to coordinator before changing it.

Test-first: add failing assertions for the opt-in layout, all approved new evidence with missing/zero values, final capped status vs scorer status, scan-request thresholds vs changed Settings and missing provenance, unresolved server risk, accepted response chronology and invalidation, bullish/bearish race values, and default embedded rendering. Exercise method picks and edit → calculate → invalidate → re-pick → save/send using existing session/send regressions; keep their assertions/payload expectations intact. Snapshot-free exact assertions should protect data scales and request/save payloads, not just class names. Browser fixture mocks all APIs, never a live broker. Check the approved layout at 1200 and 1920 widths, anchors/disclosures, right rail, no page overflow, navigation and save-first payload parity. Use native Chromium via temporary ignored config if pinned browser unavailable; don't change tracked infrastructure or mock trading behavior to make tests pass.

Build smallest presentation-only change. Record failing tests before implementation and final passing counts. Run frontend typecheck and full Jest; no backend diff means no backend suite needed. Existing tests stay intact; fix integration defects rather than delete assertions or regenerate numeric pins. Commit implementation with a descriptive subject, never an audit round subject. Root owns state/claims/GitHub writes.

## Verification and audit

Coordinator checks every mapping row below against the implementation, including text/tones/tooltips and default shared rendering. Capture the real UI and compare with proposal 02; report any material visual limits. Merge latest origin/main normally immediately before code audit round 1, and rerun appropriate validation for any source changes/conflicts. Fresh independent plan auditor before ticket creation; fresh independent code auditor on integrated origin/main..HEAD after ticket completion. Numeric/persistence/mechanism gate only; at most 3 rounds per stage, later rounds only fixes/interactions. Record exact scope/reviewer/findings/fixes/outstanding; built/audit-clean only after clean independent code review. Open PR closing #147, set waiting-merge, notify Board and release claim. Do not merge or take a second new task: the user asked for the next task.

## Position mapping acceptance (all rows from proposal 02)

- [x] P01: Header: STEP 6 OF 6, Position Card, Send basket → Page head / candidate bar (MOVED).
- [x] P02: Prev / n of N / Next, symbol buttons (gate-passing candidates only) → Candidate bar (MOVED).
- [x] P03: Company, direction · strategy, ConfidenceBadge, StatusBadge + tooltip → Identity header (MOVED).
- [x] P04: Unvalidated text, bearish Unvalidated text, earnings-veto text, in-flight warning → Notes above the card (EXISTING).
- [x] P05: Now: quote (loading / — ) → Identity header (MOVED).
- [x] P06: ENTRY, STOP, T1, R:R AT T1, SHARES, RISK $, SIZE $, WIN % → Order & exits fields + identity facts (MOVED).
- [x] P07: Sell-to-close plan T1–T3: price, R:R, return %, shares (editable) → Order & exits table (MOVED).
- [x] P08: Wrong-side-target error → Order & exits (EXISTING).
- [x] P09: Check structure + structural price, % away, source, R:R, reference note, error → Order & exits “Structural stop” (MOVED).
- [x] P10: Estimate (Monte Carlo /api/stocks/first-passage): window, T1–T3 %, days / unlikely, STOP %, days, caveat, error → Monte Carlo Estimate card (MOVED).
- [x] P11: Arithmetic plan: stop + source + ATR(14), justification, risk/share + % + days, second-opinion warning → Arithmetic card (MOVED).
- [x] P12: Arithmetic targets: R, price, % reached, days, reward/share, equation, structure · away · tol, compare label, stop-widened note → Arithmetic card (MOVED).
- [x] P13: Arithmetic sizing: shares, risk budget ÷ risk/share, ≈ position, concentration flag, Apply N shares, sized-for note → Arithmetic card (MOVED).
- [x] P14: Two-barrier race: window, paths, target / stop / neither % with days and ~$ → “Which comes first” card (MOVED).
- [x] P15: (none) → Bar drawing of the race numbers (NEW).
- [x] P16: Model caveat, “Independent of the other methods…” → Arithmetic card (MOVED).
- [x] P17: MarketSentiment (full) → Compact strip at the top, same content (MOVED).
- [x] P18: FundamentalHealthCard (full) → Compact strip under identity, same content (MOVED).
- [x] P19: MethodPickSelector (Ladder / Arithmetic / Monte Carlo, rows, unavailable reason) → Right column “Your decision” (MOVED).
- [x] P20: Missing-pick / cleared-pick message → Your decision (MOVED).
- [x] P21: View Chart, Pin / Unpin, Add to Portfolio (states) → Identity / candidate bar / Execution (MOVED).
- [x] P22: Broker modes: Recommendation, IBKR, Tradier, Alpaca, Tastytrade (+ not-configured) → Execution (MOVED).
- [x] P23: Limit @ entry, Market Order, disabled reasons; order result, err, warning, queued → Execution (MOVED).
- [x] P24: StockAutoTradeArm + after-scan toggle → Execution disclosure (MOVED).
- [x] P25: DirectSendNotesPanel, StockSendDialog → Under the page / dialog (EXISTING).
- [x] P26: (none) → Latest calculation strip (NEW).
- [x] P27: (stock score total only) → Stock Scorecard factor rows (backend field) (NEW).
- [x] P28: Backtest stats + confidence_text (Backtest page / tooltip) → Backtest evidence card (MOVED).
- [x] P29: (none) → Sharpe (NEW).
- [x] P30: (none) → Pre-trade checklist (existing gates only) (NEW).
- [x] P31: (none) → Section links, “How this page works” (NEW).

These mapping rows preserve every existing item and enumerate approved additions; no additional behavior is in scope.
