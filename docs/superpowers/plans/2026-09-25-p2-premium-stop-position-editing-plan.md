# P2 — Premium stop, position editing & trade-card display — plan

Package: P2 in `docs/superpowers/plans/2026-09-25-work-packages.md`. Decision: BACKLOG-DECISIONS-2026-09-25 (Q6, Q7, Q8, Q9, Q15 are settled — not re-asked here).
Branch: `claude/quirky-pasteur-r1kt0v`, cut from main `91e6725`. No other package had merged when this plan was written (`git log HEAD..origin/main` empty).

**Re-check against current code (step 4 of the package rules):** all 23 backlog entries and the 5 decision items were re-read against the code at `91e6725`. None had been fixed by another package. Each item below cites the line it was verified at.

**Owned files touched:** `frontend/components/organisms/TradeCard/**`, `frontend/app/(frame)/portfolio/EditDrawer.tsx`, `frontend/components/organisms/AutoTradeArm/**`, `frontend/lib/portfolioStore.ts`, `frontend/lib/premiumStop.ts`, `frontend/lib/alertEngine.ts`, the Settings page's premium-stop field only, `backend/app/routers/risk_settings.py`, their tests, and the schematic `docs/superpowers/specs/2026-09-02-trade-card-schematic.html`.
**One unowned file:** `frontend/app/(frame)/portfolio/page.tsx`, a single render line for P2-08 (no package owns it; it is the only reader of a store field P2 changes).
**Not touched:** step-7 page, `position_writer.py` (P1); `auto_trader.py` (P3b); `routers/portfolio.py`, `schemas/__init__.py` (P6); `ClosePositionDrawer` (nobody's; P2-01 needs no change there).

## A. Kenneth's decisions

**P2-01 (Q6, open_questions[34], round_1_batch_followups[1] R1-8).** Mark a position worthless by closing it at $0. A typed 0 in Current price stays refused.
- Verified: closing at $0 already works end to end. `ClosePositionDrawer` input `min={0}`, `Math.max(0, …)`. The store sends `exitPrice: opts.exitPrice ?? null`, so 0 survives. The router checks `if exit_price is None`, so 0 is used. `ClosePositionRequest.exitPrice` has no lower bound.
- Change: EditField gets an optional `zeroMessage` prop. Current price passes "Must be greater than 0 — to mark it worthless, close the position at $0 (Close button). Kept the previous value." Other fields keep the current text.
- Tests: an EditDrawer test that 0 is refused with that message. A portfolioStore test that `closePositionRemote(…, {exitPrice: 0})` POSTs `exitPrice: 0`, not null. A backend test that POST `/api/portfolio/{rec}/close` with `exitPrice: 0` gives realized P&L of -100% of premium. It uses the existing test DB fixture pattern and writes no yaml.

**P2-02 (Q7, open_questions[35], R1-10, round_13 F2).** Cap the global premium stop at 99%.
- Backend `RiskConfig.premiumStopPct`: `le=1.0` becomes `le=0.99`. GET `/risk` returns `min(stored, 0.99)`. A hand-edited legacy `1.0` in `risk_rules.yaml` then loads into the form as 0.99 and the form can save. Without that, every later Risk save would 422.
- Frontend Settings field: `max={PREMIUM_STOP_MAX_PCT}`; `Math.min(PREMIUM_STOP_MAX_PCT, …)`, imported from `premiumStop.ts` so the per-position and global caps are one number. `handleSaveRisk` also clamps what it posts.
- Residual, logged not fixed: `alert_generator` and `premium_stop.py` still read a hand-edited yaml 1.0 as-is. Those are not P2 files. The yaml is only written through this endpoint, which now refuses anything above 0.99.
- Tests: backend `premiumStopPct: 1.0` → 422, `0.99` → 200; GET with a stored 1.0 → 0.99. Both use tmp `_RISK_PATH` monkeypatching as in the existing `test_risk_settings.py`, never the real yaml. Frontend: RiskForm test that typing 1 stores 0.99.

**P2-03 (Q8, open_questions[36] + [37], decision MAXFILL-TIMESTOP).** The card's `Time stop {N}d` row becomes `Time exit: 3 DTE`. Options only; a stock card has no time exit. That is the rule `alertEngine.ts:311` and `alert_generator.py` actually fire on. The number is exported from `alertEngine.ts` as `TIME_STOP_DTE = 3` and used by the comparison, the card and the drawer's `'3 DTE or less'` string. Max fill stays display-only under the existing decision. Its entry closes as "stays read-only; threading remains the deferred build".
- Tests: the card shows "Time exit" and "3 DTE" and never `data.exit.timeStopDays`. Mutation check: changing `TIME_STOP_DTE` changes both the alert and the label.

**P2-04 (Q9, open_questions[38], round_1_batch_followups[0] R1-3).** A stored per-position ratio outside 10–99% is accepted as stored; the dollar stop is the truth. The drawer's PremiumStopEditor shows a caution under the field when `own` is outside `[PREMIUM_STOP_MIN_PCT, PREMIUM_STOP_MAX_PCT]`: "Stored at X% of the fill — outside the 10–99% the editors accept, because it was set in dollars against the mid. It fires as stored." No server clamp. `premiumStop.ts`'s band doc points at Q9.
- Tests: warning shows at 7.5% and at 99.5%, not at 45%. The value is not changed and nothing is PATCHed.

**P2-05 (Q15, round_2_batch_followups[2] R2-9).** A rejection message in the drawer is cleared only by the user's own edits. Remove the render-phase `setRejected(null)` in EditField (`EditDrawer.tsx:~910`) and in PremiumStopEditor (`~1115`). Clear it on the user's keystroke (input `onChange`) and on commit, as today.
- Tests: reject on Stop, then the stored value changes from outside (rerender with a new `position.stop`) → message still shown. Typing a character → message gone. Mutation: restoring the render-phase clear fails the first test.

## B. Backlog entries

**P2-06 (round_11 [10]).** The `skipPost` promotion (`portfolioStore.ts:~889`) and the ok-path promotion (`~913`) mark a row `synced` and keep `premiumStopDollar`. Both now drop `premiumStopDollar` on the same transition, as the offline-retry branch does. Test: after `addPosition(…, {skipPost:true})` and after an ok POST, the row has no `premiumStopDollar` key.

**P2-07 (round_11 [9]).** `migratePortfolioPersist` gates each step by version: v2→v3 `if (version < 3)`, v3→v4 `if (version < 4)`, v4→v5 already gated. Persist version 5 → **6**. New v5→v6 step (idempotent): delete `premiumStopDollar` from synced rows, which cleans rows P2-06's bug left in localStorage. The stop/structuralStop floor and legacy `syncStatus` tagging stay unconditional; they are idempotent and a legacy row can carry any version. Tests: with version 5 input, a synced row loses `premiumStopDollar`. With version 4 input, a v3→v4 normalisation still runs. With version 5 input, a row with `premiumStopPct: undefined` is NOT rewritten to null (gate proven). Mutation: removing a gate fails that test.

**P2-08 (round_11 [6]).** `lastPremiumStopDropped` is first-wins across cycles and never cleared except by dismiss. Keep first-wins for the named position. Add `moreCount: number` to the notice: each later drop while it is undismissed increments it, so a second drop is never silent. The portfolio page appends "(and N more)". Also clear the notice automatically when the named contract is no longer in `positions` after a sync (closed), because then it names nothing. Tests: two drops in two cycles → first named, `moreCount 1`. The named row disappears on sync → notice cleared.

**P2-09 (round_11 [2]).** The three sites that adopt the server's `entryPrice` keep the client's `currentPrice/pnlDollar/pnlPct`: `applyPersistedPosition ~506`, addPosition ok-path `~946`, pending retry `~1227`. New helper `withEntryPrice(row, entry)`: set `entryPrice` and, when `currentPrice > 0`, recompute `pnlDollar = (cur − entry) × mult × qty` and `pnlPct = (cur − entry)/entry × 100`. The formula and multiplier are the ones the drawer's Current price handler uses. Short stock flips sign, as `ClosePositionDrawer` does. All three sites call it. Tests: card mid 5.20 with current 5.20, server entry 4.00 → pnlPct = +30%, at each site.

**P2-10 (round_13 F1).** `fromBackend` drops `stopIsUserSet` and `scanStockPrice`. The backend has no column for either, so they cannot come back from GET. In `syncFromBackend`'s map, carry both from the local row with the same `recId` when one exists. A row with no local twin keeps `stopIsUserSet: false, scanStockPrice: undefined`. The router re-anchors only with a `scanStockPrice`, so such a row cannot be re-anchored on a re-POST either. Test: local row `stopIsUserSet: true, scanStockPrice: 145` → after sync it keeps both. `syncToBackend` then posts `stopIsUserSet: true`.

**P2-11 (round_11 [8]).** EditDrawer `stockAnchor`: live underlying first. Without it, anchor on the position's own current stop (`position.stop > 0`), not the scan price. The range exists to catch a misplaced decimal, and the current stop is a level already accepted against a recent price. The scan price can be months old. Without either: no range, as today. Test: `scanStockPrice 50`, no live underlying, stop 400 → typing 380 is accepted (range [80, 1200]); before the fix it was refused against the scan range [10, 150].

**P2-12 (G1-11).** A Monte Carlo re-run restamps `resolvedTpPrice` from `targets[0]`. It now restamps from the target whose price is nearest the currently stamped `resolvedTpPrice`, which keeps the rung the user picked. `targets[0]` is used only when nothing is stamped. On the stock path the targets are the position's own target prices, so a T2 pick matches T2 exactly. On the option path the levels are recomputed, and nearest keeps the rung. Test: stamped = T2 price → after re-run the stamp is the new T2. Mutation: `targets[0]` fails it.

**P2-13 (round_13 F7).** The stock position's editor label reads `Stop — 45% of entry` instead of `Premium stop — 45%`. That matches `alertFiresAgainst`'s own "stock $" wording. Options keep "Premium stop". Test for both.

**P2-14 (R2-8).** Correct EditDrawer's Current price comment. A typed value IS persisted to localStorage (partialize `{positions}`) and survives reload while syncs fail. Comment only. Under Q6 a typed 0 is refused, so the persisted-value concern that fed R1-8 no longer reaches a -100% row.

**P2-15 (R1-13).** Label `EditDrawer.test.tsx:~1440` "leaves a real edit alone" as documentation-of-intent, as the boundary pair already is.

**P2-16 (round_11 [0]).** `premiumStop.test.ts`'s four tests that cannot fail:
- Arity: drop the `.length` assertion and keep the value assertions.
- Contract switch: delete; it tests a literal.
- Algebraic identity: replace with a real property of `premiumStopFiringPrice`. For each entry and dollar, `premiumStopFiringPrice(entry, dollar/entry) <= entry − dollar + 1e-9`, and it is within one cent of it.
- 'Agrees with the Python resolver': rename to what it runs (`hasOwnPremiumStopPct`: null/undefined inherit, a number is own, including 0). The comment names the Python twin `test_premium_stop_per_position.py::test_changing_the_global_moves_null_positions_and_leaves_set_ones_alone` as a separate test of the same rule, and claims no cross-language check.

**P2-17 (round_11 [1]).** Schematic line 278: `$251 left` → `$250 left`, which is what `formatStopLossHeadline` computes for 401/651.

**P2-18 (round_11 [3] + open_questions[68] item 5, and item 3).** AutoTradeArm:
- (a) Before arming, when `premiumStopDollar != null` and `premiumStopPctFromDollars(...)` is undefined, show a caution under the button: "Your $X premium stop is at or above the $Y premium — the armed trade will use the global N% stop." N comes from `settingsStore.premiumStopPct`.
- (b) After Fire now: when `res.booked === false`, the order-id line renders in caution tone as "Order sent — ID: … (not booked)", never the green "Auto-trade fired".
- (c) Item 3 wording: "…with the invalidation this card had when you armed it" becomes "…the invalidation you typed, or the plan's invalidation moved with the stock price at booking…". That is what `book_fired_order` does for an untyped stop.
- open_questions[68] items 1 (backend `_build_body`, P3b/P1 files), 2 (stored only), 4 (harmless), 6 (step-7 call-site mutants, P1 tests) and 7 (note) are NOT P2's. The entry stays open, annotated with which items P2 fixed and who owns the rest.

**P2-19 (round_11 [4]).** The untouched Premium stop row on the card shows `round(liveMid × global, 2)` when a live mid exists, labelled `(global N%)`. Otherwise it shows the scan seed. It never shows the stale scan dollar against a live quote. Display only: a touched field shows the overlay as today, and send paths are untouched (they already send null for untouched). No-op-blur safety: the displayed value is what EditableKV compares against, so focus-blur still writes nothing. Tests: scan mid 5.20, live 1.00, global 0.60 → shows $0.60 and "(global 60%)". Blur without typing leaves `premiumStop` untouched.

**P2-20 (round_13 F3).** EditableKV rounds at `decimals`: `Math.round(parsed × 10^d)/10^d`. Test with `decimals={3}` through an exported test seam (EditableKV is exported for tests) or a new 3dp render.

**P2-21 (round_13 F5).** Move the Exit Plan section (Invalidation, Premium stop, Time exit, its note) out of the collapsed "Fixed % Ladder Plan" section, directly above it, always visible. The idempotent `expandLadder()` helpers in TradeCard's and step-7's tests become no-ops for these fields and need no change. Test: `Edit Invalidation` and `Edit Premium stop` are present with the ladder collapsed.

**P2-22 (round_13 F6).** alertEngine's `referenceValue` uses a `pythonRound4` helper in `premiumStop.ts`: `Number(x.toFixed(4))`, which rounds the exact binary value correctly, except on an exact binary tie (`x × 10^4` exactly `n + 0.5` and exactly representable), which rounds half-to-even. The comment claim then holds. Test: a table produced by Python's `round(x, 4)` (including 1.03125 → 1.0312, 2.00015 etc.) is asserted value for value.

**P2-23 (round_13 F8).** The TradeCard bounds' mid anchor falls back to `data.entry.limit` when there is no live and no contract mid, for both the Entry limit and Premium stop bounds. Only a card with neither degrades to `{min: 0.01}`. Test: a card with no `contractDetails.mid` and `entry.limit 2.50` → typing 25 into Limit is refused.

**P2-24 (R2-6).** When the anchor mid is below $0.02, the Premium stop row renders read-only as "global" with the reason. The single penny the band collapses to is 100% of the mid and produces no stop. Test at mid 0.01: there is no `Edit Premium stop`. `premiumStop.ts`'s note is updated from "logged rather than fixed".

## C. State file

One phase `P2-PREMIUM-STOP-POSITION-EDITING`, verify probe `present` on `frontend/lib/alertEngine.ts` pattern `export const TIME_STOP_DTE`. Each finished entry moves to `closed_questions` with its commit and test as evidence. open_questions[68] is annotated, not closed.

## D. Verification

Backend `cd backend && .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit && npx jest`; `python3 scripts/state.py` exit 0. Mutation checks named per item above, each run by hand and recorded in the phase note.

## E. Revisions after plan round 1 (NOT CLEAN: 8 MAJOR, 12 MINOR). These override sections A–B where they differ.

- **R1-1 (P2-21).** `CollapsibleSection` does not render its children while collapsed. TradeCard.test.tsx's `expandLadder()` sentinel therefore changes from `Edit Invalidation` to the `Sell-to-Close Plan` heading, and the test at :732 is renamed. The P1-owned step-7 helpers (edited-fields-sync, direct-send-stop-gate) were checked: after `expandLadder()` they only touch Invalidation and Limit, so becoming no-ops is harmless. No P1 file is edited.
- **R1-2 (P2-02).** The browser engine reads settingsStore's persisted global, which can still be a legacy 1.0. So `resolvePremiumStopPct` caps the GLOBAL branch at `PREMIUM_STOP_MAX_PCT`; a per-position value passes through as stored, per Q9. Test: a global of 1.0 fires at `entry × 0.01`. The Python twin is not P2's file. It still reads a stored 1.0 as never-firing until Settings is saved, which R1-3 surfaces. Here the browser errs toward a stop that fires.
- **R1-3 (P2-02).** GET `/risk` returns the stored value UNCLAMPED; the plan's GET clamp is dropped. When the loaded value is above 0.99, the Settings field shows a caution: "Stored 100% can never fire. This browser's alerts use 99%; save to apply 99% to the server's alerts too." `handleSaveRisk` posts `min(0.99, value)`. The residual note is corrected: a stored 1.0 is not hand-edited legacy but a value this app accepted until now.
- **R1-4 (P2-12).** One `mcRungPrice` is computed: the MC target nearest the current stamp, else `targets[0]`. It feeds both `restampIfActive` and the `mcTargetPrice` prop, so the selector shows and re-stamps the same rung. Test: the displayed Monte Carlo price equals the stamp after a re-run.
- **R1-5 (P2-11).** With no live underlying, the range is the HULL of the stop-anchored range and the scan-anchored range (each [0.2x, 3x]), so a mis-stored stop can always be corrected back toward the scan price. With a live underlying: live only, as today. Tests: stop 14 / scan 145 → 140 accepted; stop 400 / scan 50 → 380 accepted; stop 140 / scan 145 → 1400 refused.
- **R1-6 (P2-16).** The property test asserts `firing <= premiumStopThresholdPrice(entry, pct)` with NO slack, and `threshold − firing < 0.01`, over a sweep. The mutation `Math.floor(t*100)/100` must make it fail.
- **R1-7 (P2-09).** When the server's `entryPrice` is adopted, `currentPrice` is set to that entry and `pnlDollar`/`pnlPct` to 0, because the row has no quote newer than the booking. The next sync supplies the live mark. The test asserts 0 P&L and `currentPrice === server entry` at all three sites. There is no sign flip for shorts (that follows the backend GET and the drawer); the short-stock sign is out of scope and not touched.
- **R1-8 (P2-08).** A queue replaces first-wins: `premiumStopDropQueue` (not persisted). `lastPremiumStopDropped` becomes the queue's head, same shape, so the page is unchanged. `clearPremiumStopDropped` pops the head, and the next one shows. After a sync, entries whose contract is no longer in `positions` are removed. `portfolio/page.tsx` is NOT edited. Tests: two drops in two cycles → the first is named, and dismiss names the second; closing the first → the second is named.
- **R1-10 (P2-20).** `EditableKV` gets a named export used only by the test.
- **R1-11 (P2-23).** The anchor chain uses `> 0` at each step: live, then contract mid, then `entry.limit`. A literal 0 mid falls through.
- **R1-12 (P2-24).** The read-only condition is `premiumStopPctFromDollars(bounds.max, anchor) === undefined`, with the same anchor as R1-11. That is exactly "the band offers no dollar that makes a stop" (mid ≤ $0.01). The test runs at mid 0.01 (read-only) and at 0.02 (editable).
- **R1-13 (P2-03).** TradeCard.test.tsx:743 is updated. `TIME_STOP_DTE` ties the browser engine, the card and the drawer only. The Alerts page label (alerts/page.tsx, P4a) and `alert_generator.py`'s `<= 3` are not P2 files and stay literal 3; the constant's comment names both.
- **R1-14 (P2-19).** `(global N%)` is a separate dim Text beside the row, never EditableKV's `label`, so `Edit Premium stop` is unchanged. One `effectivePremiumStop` is computed: `edited.premiumStop` or no live mid → `overlay.premiumStop`, else `round(liveMid × global, 2)`. It feeds the row, `EditableTargetRow`'s `premiumStop` and the barrier-race premium barrier, so the card never shows one stop and computes with another. The send path still reads the tracked flag and is unchanged.
- **R1-15 (P2-17).** The schematic's per-contract headline is recomputed from its own $1.49/share example, verified against `formatStopLossHeadline` at build.
- **R1-16 (P2-02).** The Settings input gets `step={0.01}`, and the `le=1.0` comments at premiumStop.ts:33-34 and in TradeCard are updated.
- **R1-17.** The close-at-$0 backend test goes in a NEW file, `backend/tests/test_p2_close_worthless.py`, with its own in-memory app, as `test_portfolio_close_history.py` does. `portfolio/page.tsx` is not touched (R1-8).
- **R1-18 (P2-18a).** The caution shows only when `premium > 0 && dollar >= premium`.
- **R1-19 (P2-13).** The stock label is `Loss stop — 45% below entry` (inherited: `Loss stop — 60% (global) below entry`). Existing `Stop` queries in EditDrawer.test.tsx are checked.
- **R1-20 (P2-22).** Tie detection: `s = x*1e4`; a tie is `s*2` an integer, `s` not an integer, and `s/1e4 === x`. The expected table is generated by `scripts/`-free inline Python run at build. The generator is committed as a comment block plus `frontend/lib/__tests__/fixtures/python_round4.json` produced by `backend/.venv/bin/python`.

## F. Revisions after plan round 2 (NOT CLEAN: 6 MAJOR, 9 MINOR). These override A, B and E where they differ.

- **R2-1 (P2-22).** `pythonRound4(x)` works as follows:
  - Start from `Number(x.toFixed(4))`, which is the exact-decimal rounding.
  - Detect a TRUE binary tie from the exact expansion `x.toFixed(100)` (exact for thresholds ≥ 2^-10). It is a tie only when the digits after the 4th decimal are `5` followed by zeros. Only then round half-to-even.
  - Below 2^-10, and for non-finite input, keep the `toFixed(4)` result.
  - The fixture is `frontend/lib/__tests__/fixtures/python_round4.json`, generated by the committed script `frontend/lib/__tests__/fixtures/gen_python_round4.py` run with `backend/.venv/bin/python`. It holds non-tie near-halves (0.00035, 0.00095, 0.00115, 2.00015), true ties (1.03125, 0.40625, 2.53125) and a 5,000-value sweep.
  - Mutation checks: `Math.round(x*1e4)/1e4` and the round-1 rule must both fail it.
- **R2-2 (P2-10).** Neither field is carried onto a synced row:
  - A synced row's `stop`/`structuralStop`/`targets` are already the server's re-anchored values (`position_writer.py:164-217`).
  - Carrying `scanStockPrice` would shift them twice on a re-send.
  - Carrying `stopIsUserSet: true` would switch on the wrong-side 422 during the close-after-404 re-send.

  The fix is instead in `toBackendPayload` for a row whose `syncStatus` is `'synced'`: it sends `scanStockPrice: null` and `stopIsUserSet: false`. The writer shifts only with a scan price (verified at build, `position_writer.py:161-217`), so a re-send stores the stop as it stands, unshifted. The wrong-side guard is not switched on. Pending rows (never accepted) keep sending both, as today.

  Tests: the payload for a synced row has `scanStockPrice null` / `stopIsUserSet false`; a pending row keeps them. F1 closes as "a synced row's stop is already absolute; re-sends no longer carry the anchor that would move it".
- **R2-3 / R2-6 (F2).** F2 is NOT closed. The 99% cap closes R1-10's 100% route only. What remains is a threshold below $0.01 at 99% on an entry under $1, the band's 99% max, or a Q9 stored ratio.

  Without changing behaviour, the drawer shows a caution under the premium-stop preview when `premiumStopFiringPrice(...) <= 0`: "At this entry the stop threshold is below $0.01, so it can never fire." Settings says the same in its hint for a sub-$1 entry. F2 stays open and is narrowed to `entry × (1 − pct) < $0.01`. Any behaviour change there is Kenneth's.
- **R2-4 (P2-18a).** The caution reads: "Your $X premium stop is at or above today's $Y premium. If the fill is at or below $X, the booked position inherits the global stop (N%); above it, your $X stop applies." N comes from the settings global.
- **R2-5 (P2-12).** The rung rule applies only when `activeTpMethod === 'monte_carlo'`; otherwise `targets[0]`, as today.
  - The match is by the rung's LABEL, taken from the previous MC result held in component state when this drawer has one.
  - Otherwise, nearest to the stamp: the first re-run after reopening. The stock path's prices are the position's own targets, so they match exactly there.
  - Tests: an MC-active stamp at T2 stays T2 after a re-run; with 2R active, the MC option still offers T1.
- **R2-7 / R2-8 (R1-2 withdrawn).** `resolvePremiumStopPct` is NOT capped, so the TS/Python twins keep one rule and nothing new diverges. A legacy global of 1.0 stays never-firing in BOTH engines until Settings is saved, and that is made visible:
  - the Settings caution (R1-3);
  - the drawer's inherited-stop hint: "The global stop is 100% and can never fire — lower it in Settings."

  Every reader continues to read the one global.
- **R2-9 (R1-3).** `handleSaveRisk` clamps once and uses the clamped value for the POST, `setPremiumStopPct` and `setLocalStopPct`, so the caution clears after a save.
- **R2-10 (P2-13).** The stock label names the mechanism, not a loss: `Stock stop — fires 45% below entry` (inherited: `… 60% (global) …`). That is what `alertEngine` does for either direction. The direction-blind comparison for a SHORT stock (it fires on a gain) is logged as a NEW open question for Kenneth. It is not fixed here.
- **R2-11 (R1-14).** `effectivePremiumStop` feeds only the row display and `EditableTargetRow`. The barrier-race snapshot (:1239) and `raceBarriersMoved` (:1804) stay on `overlay.premiumStop`, so a live mid arriving does not clear a finished race. The residual is stated in a code comment: the race's premium barrier is the scan-seeded dollar until the field is touched.
- **R2-12 (R1-12).** Read-only is only for an anchor `> 0` whose band yields no stop. With no anchor at all, the field stays editable as today (bounds `{min: 0.01}`), so a cached touched value is never trapped. Test at mid 0.01 with a cached value: the row shows it read-only with the reason. `premiumStopDollarToSend` drops it, because `premiumStopPctFromDollars` rejects it; this is pinned in the test.
- **R2-13 (P2-23).** `anchorStockPrice` also chains `> 0`.
- **R2-14 (P2-07).** The v3→v4 test uses version 3 input; a version 4 input asserts the step does NOT run.
- **R2-15 (R1-1).** Corrected: edited-fields-sync also edits Premium stop after `expandLadder()`. That stays harmless because the field is now always visible.

## G. Plan round 3 (NOT CLEAN: 2 MAJOR, 7 MINOR) — the cap is reached. The fixes below are written in but NOT re-audited. Stopped for Kenneth.

- **R3-1 (MAJOR, R1-3/R2-7).** The Settings caution text, shown whenever `global > PREMIUM_STOP_MAX_PCT`, becomes: "Stored 100% can never fire, in this browser or on the server. Save to apply 99%." The drawer hint uses the same condition. A test pins the exact text.
- **R3-2 (MAJOR, R2-12/P2-24).** The earlier claim was wrong: `premiumStopDollarToSend` does NOT drop a cached dollar (premiumStop.ts:225-230), and the send path is P1's page. So a read-only row with `touched.premiumStop` labels the cached pinned dollar as pinned, not "global". The server's fill-relative ratio decides, and a ratio ≥ 1 raises the existing drop notice. Pinned: `premiumStopDollarToSend(0.01) === 0.01`. Whether to clear the cache on entering read-only is Kenneth's call (question Q-P2-2).
- **R3-3 (P2-10).** Rationale corrected. Rows from GET already send neither field (`fromBackend` drops them). The change matters for promoted-but-not-yet-reconciled rows. Residual, logged: such a row re-POSTed after a backend loss stores unshifted plan levels.
- **R3-4 (P2-05).** `EditDrawer.test.tsx:1119` ("retires a rejection message when the value changes from OUTSIDE") is inverted to Q15's rule, and an EditField twin is added.
- **R3-5 (P2-02).** Test list: "GET with a stored 1.0 returns 1.0" (tmp `_RISK_PATH`). RiskForm: loaded 1.0 → caution → blur → POST 0.99 → caution gone.
- **R3-6 (R2-3).** The Settings hint computes its entry limit `0.01/(1−pct)` from the current value, and is worded "below $0.01 — fires only on a sub-penny quote".
- **R3-7.** The source of "global" on the card and in AutoTradeArm is `useSettingsStore((s) => s.premiumStopPct)`. Residual: the browser copy can differ from the server's yaml until Settings mounts.
- **R3-8 (P2-16).** The property test becomes `firing <= threshold` (strict) and `threshold − firing <= 0.01 + 1e-9`.
- **R3-9 (P2-12).** The stamped rung's label is captured at the top of `runEstimate`, before `setMcResult(null)`, with nearest price as the fallback. A test covers target % settings changing between runs.

Open questions for Kenneth raised by the plan rounds:
- **Q-P2-1:** a SHORT stock's per-position percent stop fires on a price FALL, which is a gain for a short (alertEngine.ts:266, direction-blind).
- **Q-P2-2:** clear a cached per-position dollar when the card's mid drops to where the band offers no stop?
- **Q-P2-3:** below $0.01 thresholds (entry × (1 − pct) < $0.01), which F2 narrows to: change behaviour, or warn only (the plan warns only)?

## H. Kenneth's answers after the round-3 cap (2026-09-25)

- **Plan cap:** a 4th plan round is allowed. Per audit_rule (2) it reviews section G's unreviewed fixes and these answers, plus their interactions with the already-reviewed plan (not the whole plan again).
- **Q-P2-1 (short stock percent stop fires on a price fall):** log only for now. P2 keeps the truthful relabel (R2-10); no behaviour change. Stays an open question in PROJECT_STATE.
- **Q-P2-2 (mid too low for any band stop, but a typed dollar stop exists):** keep and show it. The cached pinned dollar is not cleared; the read-only row labels it as pinned (R3-2 as written).
- **Q-P2-3 (threshold below $0.01):** warn only. F2 stays open, narrowed to `entry × (1 − pct) < $0.01`; the drawer and Settings cautions (R2-3/R2-6, R3-6) are the whole change.

## I. Plan round 4 (NOT CLEAN: 2 gate-level) — the round Kenneth authorised past the cap. These fixes override G and F where they differ; Kenneth chose to apply them and run a 5th plan round over this section only.

Both findings were re-verified against the code: Settings accepts any typed value up to 1.0 (`settings/page.tsx:1433-1438`, `max={1.0}`, `step={0.05}`), the backend accepts `le=1.0` (`risk_settings.py:47-50`), and GET returns the stored value unclamped (`risk_settings.py:121`).

- **R4-1 (G/R3-1 + F/R2-7 drawer hint).** The "Stored 100% can never fire" caution and the drawer's "The global stop is 100% and can never fire" hint are keyed on `global > PREMIUM_STOP_MAX_PCT`. A stored 0.995 is reachable and DOES fire (at `entry × 0.005` in both engines), so the user would see a wrong percentage and a false never-fires claim next to a "fires at" preview that disagrees. Fix: the never-fires text only when `global >= 1`. For `0.99 < global < 1`: "Stored {premiumStopPctLabel(global)} is above the 99% maximum. Save to apply 99%." with no never-fires claim; the drawer hint stays silent there. Tests pin both texts at 1.0 and at 0.995.
- **R4-2 (G/R3-6 + E/R1-3).** The Settings hint's entry limit `0.01/(1−pct)` becomes `$Infinity` at a loaded legacy 1.0, the exact case R3-5 tests. Fix: hide the sub-cent hint while `pct >= 1` (the R4-1 caution covers it) and compute it from the clamped value otherwise; round the limit UP to the cent. Test at a loaded 1.0: no "Infinity" anywhere on the page.

Below the gate (logged, not fixed): R3-8's "strict" wording means `<=`; R3-9 option-path labels are `T{pct}%`, so after a target-% change the matched label follows the percentage, not the rung position; an untouched read-only row at a $0.01 mid shows `$0.01 (global 60%)`; the server's "never fires at 1.0" holds unless a quote of exactly 0 reaches `generate_alerts` (`alerts.py:48` filters only None); R3-3 and R3-7 residuals as already stated.
