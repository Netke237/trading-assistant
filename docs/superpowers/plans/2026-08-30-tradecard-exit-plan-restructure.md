# TradeCard Exit-Plan Restructure — Implementation Plan

> **Status:** Planning-only, converged over a multi-round `/grill-me`-style interview with
> Kenneth (this doc is the write-up of that interview's settled decisions — no code has been
> touched yet). Every decision below traces to a specific thing Kenneth said; the traceability
> table in "Demand ledger" exists specifically so nothing gets silently dropped during
> implementation or during the adversarial audit pass this plan is about to go through.

**Goal:** Kenneth's TradeCard has accreted three parallel, overlapping profit-target systems
over time (a fixed-formula ladder from the original design, a Monte-Carlo-based estimate added
later, and a structural/ATR-based "Exit Plan" added most recently) with no clear hierarchy
between them, one real state-sync bug (Contracts), and — the thing that triggered this whole
redesign — a structural-vs-ATR stop calculation that only ever shows you the *winning* number,
discarding the one it didn't pick. This plan reorganizes the three methods into a clear,
named hierarchy with one primary method (Arithmetic), full numeric transparency on every
stop/target decision, a single source of truth for order size, and a documentation-only
"Final Recommendation" card — without dropping anything the three methods currently do.

**Architecture:** Frontend-heavy restructure of `TradeCard/index.tsx` (component extraction,
reordering, one bug fix) plus two small, additive backend response-shape extensions to
`POST /api/contracts/exit-plan` (exposing values that are already computed internally and
currently discarded, per the audit that motivated this plan). No new backend algorithms —
`compute_final_stop`/`compute_target_row` in `backend/app/scoring/exit_plan.py` already
compute everything this plan needs to expose; they just don't return all of it today.

**Tech Stack:** Next.js 15/TypeScript (strict) frontend, FastAPI/Pydantic v2 backend, per repo
`CLAUDE.md`.

---

## Demand ledger — every decision, tagged, traced to where it's implemented below

Read this table before touching code. If a build step doesn't visibly map to at least one D#
here, stop and check whether something got lost in translation. If the closing adversarial
audit on this plan finds a D# with no corresponding implementation step, that's a blocking
finding, not a nice-to-have.

| # | Demand (Kenneth's words/decision, paraphrased) | Implemented in |
|---|---|---|
| D1 | Remove "Check structure" and "Compute Exit Plan" buttons from the Exit Plan card — restore its original form | Feature 1 |
| D2 | Group original-design cards into one collapsible container; collapsed shows only the section name; needs a name | Feature 1 → **"Fixed % Ladder Plan" — ✅ CONFIRMED by Kenneth** |
| D3 | Rename the existing Monte-Carlo "Profit Target" card, name should reflect the 3-method context | Feature 2 → "Monte Carlo Profit Target" |
| D4 | Monte Carlo card's estimate flow must fold in Check-Structure's output — show the found structure used | Feature 2 — line named "Structural level found" (round 9: renamed from "Bottom" to avoid colliding with Feature 3's differently-computed "Bottom (final stop)") |
| D5 | Document/preserve what the system displays when no structure is found | Feature 2 + Feature 3 (existing strings, listed explicitly, must not regress) |
| D6 | New card "Arithmetic Profit Target" gathering Compute-Exit-Plan + Check-Structure output | Feature 3 |
| D7 | Arithmetic card shows placeholder RR rows even before Estimate is triggered | Feature 3 |
| D8 | Arithmetic card is full width (= width of the Profit Targets card, i.e. the main content column) | Feature 3 |
| D9 | Arithmetic card holds the editable Max risk exposure field | Feature 3 + Feature 5 |
| D10 | Arithmetic card holds a static "Check Structure" button | Feature 3 |
| D11 | The stop/structure value is always shown once Estimate is pressed, but can also display standalone (Check Structure alone, before a full compute) | Feature 3 |
| D12 | Card order top-to-bottom under Contract Details | Feature 6 (final layout) |
| D13 | Full transparency on the stop: expose BOTH the structural stop price and the ATR-floor price, not just the winner, plus the $ distance between them and which was used and why (no "tolerance" concept applies to the stop — see Feature 4 note) | Feature 4 (backend) + Feature 3 (frontend) |
| D14 | Full transparency on targets: raw arithmetic price AND nearest structural price, the $ distance, the $ tolerance, and an explicit 4-state within/above-and-beyond/above-but-before/no-structural-found label | Feature 4 (backend) + Feature 3 (frontend) |
| D15 | "Reduced recommendation within tolerance" = the existing snap behavior (price snaps onto the real structural level) — confirmed, not a sizing change | Feature 4 (no new logic — existing snap, just better-labeled) |
| D16 | Entry price must be exposed on the card, not just implicit | Feature 3 |
| D17 | General max-risk is a % of portfolio, YAML-editable | Already true (`risk_rules.yaml`) — confirmed, no change needed |
| D18 | New pre-trade override to increase risk exposure for a specific trade, feeding sizing immediately | Feature 5 |
| D19 | That override persists onto the resulting `PortfolioPosition.maxLossOverride` once the position is opened | Feature 5 — covers the two real Options-mode order-creation paths (`buildPaperPosition`, `positionFromOrder`); auto-trade and Stocks mode are explicitly out of scope, see Feature 5's notes and the out-of-scope list, since neither creates a `PortfolioPosition` through a path this override can reach |
| D20 | No free-text "Reason" note field — cut from scope | Feature 5 (explicitly NOT built) |
| D21 | Order type + Limit: always visible, general interest, not inside any collapsible group | Feature 6 |
| D22 | Max fill: keep its existing logic (it is ALREADY per-trade editable today, confirmed in code — this demand is "explain the logic and keep it," not "make it global") | Feature 6 (relocated, editability preserved) |
| D23 | Fix the real Contracts/SendToBrokerDialog disconnect bug | Feature 7 |
| D24 | Single persistent "Order Entry" strip (Order type/Limit/Max fill/Contracts), not duplicated per card | Feature 6 |
| D25 | Arithmetic's Risk-derived size gets an "Apply" action writing into the shared Contracts field; silent overwrite, no confirm prompt | Feature 3 + Feature 7 |
| D26 | Final Recommendation becomes a documentation/journal snapshot, not cross-method reconciliation | Feature 8 |
| D27 | Final Recommendation is NOT part of the "Fixed % Ladder Plan" collapsible group — stands alone | Feature 8 |
| D28 | Final Recommendation auto-shows whichever of {Arithmetic, Monte Carlo} was most recently explicitly run, labeled "computed via: X, HH:MM" | Feature 8 |
| D29 | Final Recommendation placement: bottom of the page, after all three method cards | Feature 6 (final layout) |
| D30 | Final Recommendation empty state (neither method run): implicitly falls back to the Fixed % Ladder Plan's live numbers, explicitly labeled as a default | Feature 8 |
| D31 | No cross-method reconciliation/comparison logic between the three methods | Explicitly out of scope — noted in Feature 8 |
| D32 | Unambiguous button names: "Compute Arithmetic Plan", "Run Monte Carlo Estimate", "Check Structure" (unchanged) | Feature 2 + Feature 3 |
| D33 | Arithmetic is Kenneth's primary method → expanded by default (not collapsed) | Feature 3 |
| D34 | Fixed % Ladder Plan group: collapsed by default, and persisting that toggle across visits — **both ✅ CONFIRMED by Kenneth** | Feature 1 |
| D35 | **⚠ New, round-4 finding — not yet put to Kenneth.** Final Recommendation is not currently an empty card: it already shows a `finalStatus` PASS/CAUTION/REJECT badge (shown nowhere else on the card), plus "Historical accuracy" and "Contract confidence" rows and a "Projected R/R" figure. None of Kenneth's conversation addressed whether this existing content survives the redesign alongside the new last-run-method content, or is replaced by it. | Feature 8 — working default proposed (round 5: keep `finalStatus`, stack the new content below it — see Feature 8), flagged for Kenneth's confirmation rather than treated as fully settled, same as D2/D34 |

---

## Context

Three profit-target systems exist on `TradeCard` today, each added in a different pass:

1. **Original design** — Entry Plan / Exit Plan (invalidation, premium stop, time stop) /
   Sell-to-Close Plan (fixed T1/T2/T3 ladder: `T1 = stock_price ± 8%` from
   `risk_rules.yaml:reward_risk.bullish_target_pct/bearish_target_pct`, `T2 = move×1.5`,
   `T3 = move×2.0`) / Risk-Reward / Final Recommendation.
2. **Monte Carlo "Profit Target" card** — %-of-premium T1/T2/T3 targets, "Estimate" button,
   probability + expected days via the `first_passage` engine. Already has a
   "R:R vs. structural stop" row per target (`ProfitTargetRow` in `TradeCard/index.tsx`) — it
   just doesn't currently surface the *price* behind that ratio, only the ratio itself.
3. **Exit Plan card (structural/ATR)** — "Check structure" + "Compute Exit Plan" buttons,
   2R/3R rows from `backend/app/scoring/exit_plan.py`, added most recently (see
   `docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md`).

An adversarial data-exposure audit of (3) — see the prior session's turns in this doc's parent
conversation — found that `compute_final_stop` internally computes both the structural stop
price and the ATR-floor price, compares them, and returns only the winner; the loser's price is
discarded before it ever reaches `ExitPlanStopOut`/`ExitPlanTargetRowOut` (both defined in
`backend/app/routers/contracts.py`). That gap is what triggered this whole restructure —
Kenneth wants (3), promoted to primary status as "Arithmetic Profit Target," to show its work
in full: every number that goes into a stop or target decision, not just the one that won.

---

## Feature 1 — Revert the Exit Plan card, build the collapsible "Fixed % Ladder Plan" group

- [ ] `TradeCard/index.tsx`: remove the "Check structure" button, the "Compute Exit Plan"
      button, and the entire 2R/3R rendering block from the Exit Plan section — back to just
      Invalidation / Premium stop / Time stop, exactly as it existed before Feature B of the
      exit-plan pipeline plan. **[D1]**
- [ ] **Round-9 finding, MEDIUM-HIGH: "Invalidation" here and "Bottom (final stop)" on the new
      Arithmetic card (Feature 3) are two independently-computed, unrelated stop-loss prices for
      the same trade — the restructure actively pulls them further apart with no disclaimer.**
      Today the two sit in the same card, adjacent, so at least both are visible together. After
      this restructure, "Invalidation" moves into the collapsed-by-default Fixed % Ladder Plan
      group while "Bottom (final stop)" becomes the headline number on the expanded-by-default,
      primary, full-width Arithmetic card — one buried behind a click, one always visible up top
      — and the two prices can legitimately disagree by a large margin with nothing connecting
      or distinguishing them. Add a one-line note to the reverted Exit Plan card: "Invalidation
      is a fixed-% stop, independent of the Arithmetic card's structural/ATR stop above."
      **Round-10 addition: that note must also say Invalidation remains functionally load-
      bearing, not just a display figure.** Verified: `SendToBrokerDialog`'s submit gate
      (`hasMissingInvalidation`, from `checkTradeRisk`'s `missing_invalidation` reason, itself
      `!checkInvalidation(card.exit.invalidation)` — `frontend/lib/risk.ts:195-198`) is computed
      purely from the Ladder's Invalidation field, with zero awareness of Arithmetic's stop —
      `submit()` returns early and the Send button is disabled with tooltip "Invalidation stop
      required" whenever it's missing. After this restructure, Invalidation is the only place
      that still functionally blocks a submission, yet it now lives inside the collapsed-by-
      default Fixed % Ladder Plan group, while Arithmetic (the promoted primary method) has zero
      bearing on whether the trade can be sent at all. Practical risk is low (Invalidation is a
      deterministic `stock_price ± 8%` figure, essentially never actually zero in real data),
      but the note must be honest that these aren't just two independently-displayed numbers —
      one of them is still a silent hard gate the other has no relationship to. **[D1, D13]**
- [ ] New collapsible wrapper component (e.g. `CollapsibleSection`, if one doesn't already
      exist in `components/molecules/` — check before building a new one) containing, in this
      order: Exit Plan (reverted form above), Sell-to-Close Plan, Risk-Reward. **Final
      Recommendation is explicitly excluded from this group — see Feature 8.** **[D2, D27]**
- [ ] Container title: **"Fixed % Ladder Plan"** (chosen to parallel "Arithmetic Profit Target"
      / "Monte Carlo Profit Target" naming — all three now read as `<method> Profit Target`,
      with "Fixed %" naming this one's actual basis, same way "Arithmetic" and "Monte Carlo"
      name theirs). Collapsed state shows only this title + a chevron, no content. **[D2, D34]**
- [ ] Default state: **collapsed**. **[D33 — Arithmetic is primary, this is least-used]**
- [ ] Expand/collapse state persists per browser across visits — check what pattern existing
      collapsible panels in this codebase already use (verify during build; if none exists,
      plain `localStorage` under a new colon-form key per `CLAUDE.md`'s persistence convention,
      e.g. `'bamendjou:tradecard-ladder-collapsed'`) rather than resetting to collapsed on every
      page load. **✅ CONFIRMED by Kenneth** — persistence-across-visits, not just
      collapsed-by-default. **[D34]**
- [ ] **✅ CONFIRMED by Kenneth: "Fixed % Ladder Plan" stands as the container name**, despite
      only precisely describing the Sell-to-Close Plan sub-section (Exit Plan and Risk-Reward,
      the other two things it hides, aren't "ladders"). No longer an open question.
- [ ] **Round-7 finding, cosmetic: update the Sell-to-Close Plan's disclaimer copy for a
      3-method page.** Its current text ("FIXED-FORMULA LADDER — INDEPENDENT OF THE PROFIT
      TARGETS ESTIMATE ABOVE; THE TWO CAN DISAGREE", `TradeCard/index.tsx` line 1173) only
      references Monte Carlo — accurate before this restructure, silently wrong once Arithmetic
      also sits on the page as a third independent method. Reword to something method-count-
      agnostic, e.g. "independent of the other profit-target methods on this page; they can
      disagree" rather than naming a specific one.

## Feature 2 — Rename & extend the Monte Carlo card

- [ ] Rename the existing "Profit Target" card to **"Monte Carlo Profit Target"**. **[D3]**
- [ ] Rename its "Estimate" button to **"Run Monte Carlo Estimate"** (the current "Estimate"
      label is ambiguous now that two other cards also have compute actions). **[D32]**
- [ ] `ProfitTargetRow`'s existing "R:R vs. structural stop" line gets a new line above it —
      **named "Structural level found"** (round 9: not "Bottom," see the collision note below —
      stated here as the final name to avoid confusion) — showing the actual structural stop
      price used (not just the derived ratio) — reuse whatever structural-stop fetch already
      backs that ratio (`checkStructure`'s result); no new backend call needed, this is exposing
      a value TradeCard already has in memory but doesn't currently render on this specific card.
      **[D4]**
- [ ] Preserve, verbatim, the four existing structural-lookup states this row already
      distinguishes — do not regress or collapse them into one generic "n/a": `"Checking…"`,
      `"No structural stop found"` (search ran, found nothing), `"N/A (stop = price)"` (found a
      level, but it's degenerate — resolves to current price), and `"—"` (not yet run this
      mount). The new "Structural level found" line reuses the same four states, not a separate
      two-state simplification. **[D5]**
- [ ] Freshness gating: the codebase already gates the existing R:R-vs-structural-stop figure
      behind `structuralIsFreshRef`/`firstPassageIsFreshRef` (`TradeCard/index.tsx` lines
      259-302) so it never shows a confident number next to stale data. The new "Structural
      level found" line must be gated the same way — if the R:R cell would show `"—"` because
      its freshness check failed, this line on the same row shows the same gated state, not a
      confident-looking price next to a gated ratio. **[D4]**
- [ ] **Round-9 finding, HIGH severity, motivating the naming above: this line and Feature 3's
      "Bottom (final stop)" line can
      show two different prices for the same contract, both starting with the word "Bottom," on
      two cards now sitting one above the other on the same page.** This card's "Bottom" is
      specified (above) to reuse the raw `checkStructure` fetch alone — no ATR-floor comparison.
      Feature 3's "Bottom (final stop)" is `compute_final_stop`'s *winner* — the wider of that
      same raw structural stop and an ATR floor (`backend/app/scoring/exit_plan.py:32-56`).
      When the structural stop is tighter than the floor, `compute_final_stop` discards it
      entirely and returns the ATR-widened price instead — so the two "Bottom" numbers
      genuinely disagree in that case, with nothing distinguishing the labels. This is the same
      class of gap the "can disagree" disclaimers (Features 1/2/3) already fix for the *target*
      side, never applied to this specific *stop*-side label collision until now. The rename
      above to "Structural level found" avoids the collision outright, rather than requiring a
      reader to parse a disclaimer to tell two same-named numbers apart. **[D4, D13]**
- [ ] No sizing or override changes on this card — it stays a pure display/estimate surface.
- [ ] **Round-7 finding, cosmetic: same disclaimer-copy update as Feature 1's, other direction.**
      This card's current "MONTE CARLO ESTIMATE — INDEPENDENT OF THE SELL-TO-CLOSE PLAN BELOW;
      THE TWO CAN DISAGREE" (line 1094) has the same problem — only references the Ladder, not
      Arithmetic. Reword alongside Feature 1's fix so both disclaimers describe "the other
      methods on this page" generically rather than naming one specific other card.

## Feature 3 — New "Arithmetic Profit Target" card

- [ ] New component, full width (= the main content column's width, matching the Monte Carlo
      card's width today — **not** the viewport including the right-hand context rail, per
      Kenneth's own clarification). **[D8]**
- [ ] Expanded by default (this is Kenneth's primary method). **[D33]**
- [ ] Header row: **Entry price** (explicitly labeled, not just implicit from a quote header
      elsewhere on the page) and **Direction**. **Round-11 finding: label this "Stock entry
      price," not a bare "Entry price"** — verified this is the underlying stock's price
      (`computeExitPlan`'s `entry_price = stockQuote?.price ?? data.price`,
      `TradeCard/index.tsx:458/463`, e.g. ~$150), a different figure from Feature 6's "Limit"
      field (the option contract's premium limit, `overlay.entryLimit`, e.g. ~$2.30) — which
      sits in the Order Entry strip immediately above this card per Feature 6's final layout.
      Two differently-scaled "price" figures stacked vertically deserve the same disambiguation
      this document already applies to every other pair of adjacent, confusable numbers. **[D16]**
- [ ] **Round-8 finding: this new card needs the same "can disagree with the other methods"
      disclaimer round 7 added to Features 1 and 2 — a gap round 7 itself introduced by only
      updating the two pre-existing cards' copy, not the new one.** Arithmetic is the third
      independent method on the page and, per D33, the primary, expanded-by-default one — the
      card most likely to be read on its own, and currently the one card that wouldn't tell the
      user its numbers can differ from Ladder/Monte Carlo. Add matching copy, e.g. "independent
      of the other profit-target methods on this page; they can disagree."
- [ ] Standalone **"Check Structure"** button — runs a structure lookup independent of the full
      compute, and its result displays on its own, before/without "Compute Arithmetic Plan"
      being pressed. Kenneth's D5 answer applies everywhere structure is looked up, not just on
      the Monte Carlo card — this button's result must distinguish the same states Feature 2's
      "Structural level found" line does: the four fallback states `"Checking…"`, `"No structural stop found"`,
      `"N/A (stop = price)"`, `"—"` (not yet run this mount / reset on contract switch), **plus**
      the success case, which is a separate branch, not a fifth item in the same list — round 2's
      "same four states" phrasing conflated the success case with the fallback list; be precise
      about which is which so an implementer doesn't drop `"—"` by mistake. **Round-7 correction:
      the success case is source + price + distance, not "source + confidence"** — verified
      against the actual block being relocated (`TradeCard/index.tsx:1001-1011`), which renders
      a source label, the found price, and `distancePct`; it does not render `confidence` today
      even though `StructuralStop.confidence` exists as a field. Reuse that existing block
      rather than building a new "source + confidence" display that would drop the price/distance
      Kenneth's D5/D13 transparency asks clearly want kept. **[D10, D11, D5]**
- [ ] **"Compute Arithmetic Plan"** button (renamed from "Compute Exit Plan" now that it lives
      here) — runs the full pipeline: stop + both target rows. **[D6, D32]**
- [ ] Before either button is pressed: render placeholder rows for the Bottom/stop line and
      both the 2:1 and 3:1 target rows (e.g. `"— not yet computed —"`), not an empty/missing
      section — so the card's shape is stable and visible before any interaction. **[D7]**
- [ ] Stop row content, once computed (needs the backend fields from Feature 4):
  - Bottom (final stop) price, **structural stop price — labeled "Structural stop — Order
    Block/Swing Low/Swing High" (round 10: reuse the exact phrasing from this card's own
    standalone Check Structure block below, rather than a third, differently-worded "structural
    stop price" label for what is normally the same underlying `find_structural_stop` value —
    both draw from the identical function, and inconsistent copy for the same number on the
    same card is a smaller-scale version of the label collision round 9 already fixed across
    cards)**, ATR-floor price, ATR(14) value, **and the $ distance between the structural and
    ATR-floor prices** (`abs(structuralPrice - atrFloorPrice)`, both now exposed by Feature 4 —
    this is the stop-side counterpart to the target rows' distance transparency; Kenneth's
    original ask was explicit that both the stop AND the targets get full "how close/far"
    transparency, not just the targets). No tolerance figure here — the stop decision has no
    tolerance band, only a strict winner-takes-it comparison (see Feature 4's note); don't
    render a "tolerance" line that doesn't correspond to anything the algorithm actually does.
  - **Round-10 finding: when no structural candidate exists at all, the structural-price field
    and the justification sentence below both need an explicit state, not a blank/broken one.**
    `find_structural_stop` genuinely returns `None` in three real branches (too few candles, no
    swing/order block found — `structural_stop.py:40,79,85`), not a hypothetical — when that
    happens, `structuralPrice`/`distanceDollar` are both `None` while `source` is still just
    `'atr_widened'` (no separate enum value distinguishes "structural existed and lost" from
    "no structural candidate to compare at all"). The target-row four-state spec above already
    gets this right (its state 1 is explicitly "No structural level found ahead"); apply the
    same rigor here: when `structuralPrice` is `null`, the structural-stop field shows **"No
    structural stop found"** (reusing Feature 2/Check-Structure's exact string, per D5's
    "everywhere structure is looked up" mandate) instead of a blank or `$null`.
  - One justification sentence naming which one won and why, generated client-side from the
    now-exposed raw values (backend keeps returning `source`, frontend composes the sentence —
    no new backend text field needed). **Three cases now, not two** (round 10 adds the missing
    third): *"Using structural — it already clears the ATR floor by $X, no widening needed"*
    (structural found and won) vs. *"Structural stop $X was inside the ATR floor — widened to
    $Y for a minimum-distance stop"* (structural found but lost) vs. **"No structural stop
    found nearby — stop set at the ATR floor of $Y"** (no structural candidate at all — the
    case above). **[D13]**
- [ ] Each target row (2:1 and 3:1), once computed:
  - Arithmetic target price, nearest structural price (if any), the $ distance between them,
    the $ tolerance (from Feature 4's new `toleranceDollar` field), and one of **four** explicit
    states, not three — the backend's own `compute_target_row` already produces a fourth case
    that a 3-state UI would silently swallow:
    1. **No structural level found ahead** — nothing to compare against.
    2. **WITHIN tolerance → snapped** onto the structural price.
    3. **Outside tolerance, target sits BEFORE (short of) the structural level** — quality-fine,
       arithmetic price stands, nothing to warn about, but Kenneth explicitly asked to see these
       prices even when not snapped ("above but not in the range I want to see these prices") —
       this state must show its own distinguishing label, e.g. *"Outside tolerance — using
       arithmetic price, sits before the next structural level"* — not fall silently into the
       same bucket as state 4.
    4. **Outside tolerance, target sits BEYOND the structural level** (`target_beyond_structural`
       in the backend) — the ⚠ warning state, e.g. *"Target sits beyond the next real structural
       level."*
    Each of the 4 gets its own label text, not a single boolean quality flag. **[D14, D15]**
  - Contract price, pricing model, probability, expected days (existing fields, unchanged).
  - **Risk-derived size** line with an **"Apply"** button that writes the recommended contract
    count directly into the single shared Contracts field from Feature 6, overwriting silently
    (no confirmation dialog) even if a custom value was typed in manually. **[D9, D25]**

## Feature 4 — Backend: stop exposing only the winner

`backend/app/scoring/exit_plan.py`:

- [ ] `FinalStopResult` gains an `atr_floor_price: float` field — `compute_final_stop` already
      computes this as a local variable (`atr_floor_price`) before deciding which one wins; it
      just needs to survive past that comparison instead of being discarded. No new computation.
      **[D13]**
- [ ] `TargetRowResult` already carries `structural: Optional[StructuralStop]` (the full
      candidate, not just source/confidence) — add `distance_dollar: Optional[float]` (round-8
      correction: `Optional`, not plain `float` — the value is only defined "when a structural
      candidate exists," so it must be able to be `None` otherwise, matching
      `ExitPlanTargetRowOut.distanceDollar`'s already-correct `Optional[float]` typing below;
      `abs(structural.price - arithmetic_price)` when a structural candidate exists, else
      `None`) and `tolerance_dollar: float` (non-Optional is correct here — unconditionally
      computable as `snap_atr_multiplier * atr`, already computed locally as `snap_distance`) so
      the caller doesn't have to re-derive them. **[D14]**

`backend/app/routers/contracts.py`:

- [ ] `ExitPlanStopOut` gains `structuralPrice: Optional[float]` (currently only
      `structuralSource`/`structuralConfidence` are exposed — the actual price of the structural
      candidate, win or lose, was never in this schema), `atrFloorPrice: float`, and
      `distanceDollar: Optional[float]` (`abs(structuralPrice - atrFloorPrice)` when a structural
      candidate exists — trivially derivable from the two fields just added, no new computation,
      but must not be skipped: Kenneth's transparency ask was explicit about "both the Structural
      stop and the Stop based on ATR," not just the targets, so the stop side gets the same
      distance treatment the target rows get below). **No `toleranceDollar` on the stop side —
      unlike targets, `compute_final_stop` has no tolerance-band concept at all; it's a strict
      "whichever is further from entry wins" comparison, so only `distanceDollar` applies here.
      This asymmetry is real and intentional, not an omission — call it out explicitly in the UI
      copy rather than implying a tolerance exists where the algorithm has none.** **[D13]**
- [ ] `ExitPlanTargetRowOut` gains `distanceDollar: Optional[float]` and `toleranceDollar: float`
      (both already computed inside `compute_target_row`/available in `TargetRowResult` once the
      change above lands — this endpoint just needs to pass them through). `structuralPrice` is
      already present on this schema today; no change needed there. **[D14]**
- [ ] `frontend/types/domain.ts`: widen `ExitPlan.stop` and `ExitPlanTargetRow` to match the two
      schema additions above. **[D13, D14]**
- [ ] Extend `backend/tests/test_exit_plan.py` — it already contains both the unit tests for
      `compute_final_stop`/`compute_target_row` AND the `TestClient`-based router tests for
      `POST /api/contracts/exit-plan` in the same file (the router test class starts around
      line 172) — no second test file to create or hunt for. Assert the new fields are populated
      correctly in both the "structural wins" and "ATR-widened" branches, and in the
      "snapped"/"not snapped" target branches.

No YAML changes — `exit_plan.stop.atr_multiplier`, `exit_plan.target.rr_ratios`, and
`exit_plan.target.structural_snap.atr_multiplier` are all already correctly wired and unchanged
by this plan.

## Feature 5 — Pre-trade max-risk override

- [ ] New UI on the Arithmetic card: toggle between **% of account** and **$ amount**, an input,
      and an **Apply** action — mirrors the shape of the existing post-trade
      `maxLossOverride: {mode: 'dollar'|'percent', value: number}` on `PortfolioPosition`, but
      usable *before* a position exists. Defaults to displaying (not silently using) the global
      `maxLossPerTradePct × portfolioValue` figure so the default basis is always visible.
      **[D9, D18]**
- [ ] The override value feeds the Arithmetic card's own Risk-derived-size calculation
      immediately (client-side — `maxLossAtStop`/`recommendedContractSize` in `frontend/lib/
      risk.ts` already take a $ risk figure as input; this just changes which figure is passed
      in when an override is active). **Round-11 finding: don't reinvent the override-resolution
      math — a canonical helper for exactly this already exists and is already the established
      pattern.** `resolveMaxLossLimitDollar(portfolioValue, globalPct, override?)`
      (`frontend/lib/risk.ts:113-122`) already accepts an optional `MaxLossOverride`, is already
      unit-tested for both modes (`risk.test.ts:246-257`), and is already used exactly this way
      by the existing post-trade override (`EditDrawer.tsx:680`). The Arithmetic card's
      `recommendedSize` calc currently calls it 2-arg, with no override
      (`TradeCard/index.tsx:762`) — both this bullet's fix and the `checkTradeRisk` fix below
      must call the same 3-arg form `EditDrawer.tsx` already does, not reimplement the
      mode-branching logic locally. Without this citation, three call sites (`EditDrawer`,
      `checkTradeRisk`, `recommendedSize`) could end up computing "effective max-loss dollar
      limit" three subtly different ways instead of sharing one function. **[D18]**
- [ ] No free-text "Reason"/justification note field — explicitly decided against. Do not add
      one; a numeric override with a visible "overridden from default" badge is the full scope
      here. **[D20]**
- [ ] **Round-5 finding, CRITICAL — a layer above every previous fix, and none of Feature 5's
      other bullets can work without it: the override value never leaves `TradeCard`'s
      component scope in the first place.** The Arithmetic card (Feature 3) lives *inside*
      `TradeCard/index.tsx`, exactly like the existing Exit Plan/Monte Carlo sections — Feature
      5's new override UI is therefore component-local state by construction, the same way the
      existing "Risk-derived size" line it's built on top of is 100% component-local today
      (`recommendedSize`, `TradeCard/index.tsx:758-764`, reads `useRiskStore` directly, carries
      nothing out). `TradeCard` exposes exactly four callbacks for surfacing a client-only value
      to its page-level caller — `onEditsChange`, `onStructuralStopChange`,
      `onFirstPassageChange`, `onExitPlanChange` (lines 160, 169, 181, 194) — and none of them
      carries a max-loss-override value; there is no fifth, and no `forwardRef`/
      `useImperativeHandle` either. Every later bullet in this feature (the ones that say
      `buildPaperPosition`/`positionFromOrder` should "read the active override from the same
      pre-trade state Feature 5 introduces") silently assumes a conduit that doesn't exist —
      unlike Feature 7's Contracts boundary crossing — **round 11 correction: Feature 7 doesn't
      design anything new there, it discovers and reuses an existing pair (`contracts`/
      `onEditsChange`, already on `TradeCard` before this plan); the comparison isn't "Feature 7
      designs, Feature 5 doesn't" but "Feature 7's crossing already had plumbing in place,
      Feature 5's has none, so a genuinely new pair is unavoidable here."** **Concrete fix
      (round 6: narrowed to one
      fully-specified option — the "fold into `EditOverlay`" alternative round 5 raised is
      dropped, not offered as a coequal choice, since it names an unresolved `isDirty`/
      `defaultOverlay` correctness problem without solving it; don't let an implementer pick the
      "simpler-looking" option and inherit a known, undescribed bug):**
      1. Add a fifth callback pair mirroring the existing pattern exactly:
         `initialMaxLossOverride?: MaxLossOverride | null` prop +
         `onMaxLossOverrideChange?: (v: MaxLossOverride | null) => void` callback. **Round-11
         correction to the wiring description**: `onEditsChange` is called *directly* inside
         `patch()`'s state updater (`onEditsChange?.(next)`, `TradeCard/index.tsx:738`) — there
         is no ref or separate effect involved; that ref-synced-effect pattern actually belongs
         to `onStructuralStopChange`/`onFirstPassageChange` (lines 407-413), a different pair
         that needs the extra indirection specifically to guard against stale-closure races on
         Prev/Next navigation (per the plan's own reasoning at those lines). Wire the new
         override callback the same direct way `onEditsChange` actually works — call it inline
         wherever the override state updates — unless the override also needs stale-closure
         protection across candidate switches, in which case say so explicitly and use the ref
         pattern instead (see item 3 below on resetting on candidate switch, which suggests it
         likely does need the same protection — don't leave this ambiguous).
      2. **Round-6 finding: the "wired the same way `onEditsChange` is" claim needs a correction
         — `onEditsChange` itself is not actually wired at the one real call site today.**
         Verified: `TradeCard` has exactly one production JSX call site
         (`step-7-trade-card/page.tsx:788-797`), and it currently passes `data`, `recId`,
         `onSendToBroker`, `sendLabel`, `sendDisabled`, `onStructuralStopChange`,
         `onFirstPassageChange`, `onExitPlanChange` — **not** `onEditsChange`, and not
         `contracts` either (Feature 7 fixes the latter). So "the same pattern already works"
         is not proof this will work; it must be explicitly instructed here too: add
         `initialMaxLossOverride={...}` and `onMaxLossOverrideChange={...}` to that same JSX
         call site, sourced from a new page-level `maxLossOverrideBySymbol: Record<symbol,
         MaxLossOverride | null>` state.
      3. **Round-6 finding: reset on candidate switch, matching every other piece of per-candidate
         state in this file.** `TradeCard`'s contract-switch effect (`index.tsx:343-375`)
         explicitly resets `overlay`, `structuralStop`, `firstPassage`, `exitPlan`, etc. whenever
         `data.symbol`/`data.contract` changes, specifically to stop one candidate's stale values
         bleeding onto the next after a CandidateNav Prev/Next click. Add the new override state
         to that same reset list, or the newly active card will briefly show the *previous*
         candidate's override.
      4. **Round-6 finding: cache key must be stated explicitly, matching the rigor the plan
         already applies to the analogous Contracts-map question in Feature 7.** Key
         `maxLossOverrideBySymbol` by **symbol**, not contract — matches "per-trade" intent at
         the level the override actually applies (a risk decision about the underlying, not a
         specific strike/expiry), and matches `structuralBySymbol`'s existing keying rather than
         `exitPlanByContract`'s.
      The page captures the value into this cache (mirroring `structuralBySymbol`/
      `exitPlanByContract`, which do exist and work the way this assumes — confirmed) for
      `buildPaperPosition`/`positionFromOrder` to actually read from. **Without this bullet,
      every other Feature 5 bullet below is unreachable code** — the override UI would display
      and compute correctly, but the value it holds would never reach the functions that are
      supposed to persist it. **[D18, D19]**
- [ ] When the position is actually opened from this TradeCard, pass the active override through
      so it lands on the created `PortfolioPosition.maxLossOverride`, not just used transiently
      for the pre-trade size suggestion. **Confirmed required, not an open question** — verified
      against current code: `PortfolioPositionCreate` (`backend/app/schemas/__init__.py:612-629`)
      has no `maxLossOverride` field today (only `PortfolioPositionUpdate`, the PATCH schema,
      does). Backend scope: add `maxLossOverride: Optional[dict] = None` to
      `PortfolioPositionCreate`, wire it through `add_position` in `backend/app/routers/
      portfolio.py` to set `max_loss_override` on the ORM model at creation time. **[D19]**
- [ ] **The frontend side is not one call site, it's two** (round 3 corrects round 2's count —
      see the auto-trade note below). `toBackendPayload` in `frontend/lib/portfolioStore.ts`
      (lines 156-174) is the single backend-facing function; two independent
      `PortfolioPosition`-builder functions feed it and neither currently sets
      `maxLossOverride`: `buildPaperPosition` (the quick "Place Limit"/"Right Now" order path)
      and `positionFromOrder` (the basket/`SendToBrokerDialog` submit path, `step-7-trade-card/
      page.tsx` line 74). Both must read the active override from the same pre-trade state
      Feature 5 introduces and pass it into the payload each builds. **[D19]**
- [ ] **Round-4 finding: `toBackendPayload` itself is the last link and it's missing — without
      this, D19 fails silently even after every bullet above is done correctly.** Verified: the
      object literal `toBackendPayload` (lines 156-174) returns to build the `POST /api/portfolio`
      body has no `maxLossOverride` key at all, unlike its sibling `toUpdatePayload` (the PATCH
      path used by the existing post-trade `EditDrawer`/`MaxLossBanner` override), which
      correctly does `if ('maxLossOverride' in patch) body.maxLossOverride = patch
      .maxLossOverride;`. Concrete failure mode without this fix: the client's own optimistic
      local state shows the override correctly right after submit (because `addPosition`'s
      optimistic `set()` genuinely has it) — but the backend never receives it in the JSON body,
      so `add_position` creates the row with `max_loss_override=None` regardless of the schema/
      router wiring above; the very next backend sync (`fromBackend`, e.g. a page reload) then
      overwrites the optimistic value with `null`, and the override silently vanishes. Fix: add
      `maxLossOverride: p.maxLossOverride ?? null,` to `toBackendPayload`'s returned object. This
      is the exact "looked fixed in the optimistic UI, wasn't actually fixed" failure mode that
      has recurred with D19 in every prior round — this time in a different file each time. **[D19]**
- [ ] **Round-3 finding, correcting a round-2 error: there is no third builder to fix.**
      Round 2 assumed "whatever `AutoTradeArm` builds internally for its own order path" was a
      third `PortfolioPosition`-builder needing the same override wiring. It isn't — verified
      end to end: `AutoTradeArm.handleArm()`/`handleFireNow()` only call
      `api.armAutoTrade()`/`api.fireAutoTrade()`; the backend's `/auto-trade/arm` and
      `/auto-trade/fire` routes (`backend/app/routers/auto_trade.py`) never construct or persist
      a `PortfolioPositionModel`; `AutoTradeService.fire()` (`backend/app/services/
      auto_trader.py`) submits to the broker router and appends to an in-memory history list —
      nothing else. Project-wide, `PortfolioPositionModel(` is constructed exactly once in
      production code, in `add_position` (`backend/app/routers/portfolio.py:271`), which
      auto-trade never calls. **Consequence: D19 ("override persists onto the resulting
      `PortfolioPosition` once opened") is structurally unsatisfiable for auto-trade-fired
      trades today, independent of this plan** — those trades never become `PortfolioPosition`
      rows through any existing code path, so there is nothing for an override to attach to.
      This is a pre-existing gap in auto-trade's own architecture, out of this plan's scope to
      fix (making `/auto-trade/fire` create a portfolio row on fill would be a materially larger,
      separate change). Flag this explicitly to Kenneth rather than silently implying the
      override "just works" for auto-trade the way it does for the other two paths. **[D19]**
- [ ] **Round-5 finding: `checkTradeRisk` (`frontend/lib/risk.ts:225-248`) has zero awareness of
      the new override — not just a stale comment, but load-bearing logic.** It computes
      `lossLimitDollar = resolveMaxLossLimitDollar(limits.portfolioValue,
      limits.maxLossPerTradePct)` with no override parameter, and `SendToBrokerDialog` uses it
      for its own independent risk-check display (lines 57-64) that forces an extra confirmation
      click when a trade appears to exceed max loss per trade. Concrete inconsistency without a
      fix: a user raises their pre-trade override on the Arithmetic card, sizes up via Apply,
      opens Send-to-broker — and `checkTradeRisk`, unaware of the override they just set, flags
      the trade as exceeding the (stale, un-overridden) limit and demands a second, confusing
      confirmation click to override a warning that only exists because the override wasn't
      threaded into this check. Fix: add an optional override parameter to `checkTradeRisk`,
      used when computing `lossLimitDollar`, so the dialog's gate agrees with the Arithmetic
      card's own sizing math — or, if this friction is judged acceptable, say so explicitly here
      rather than leaving it unaddressed. **[D18]**
- [ ] **Round-6 finding: the `checkTradeRisk` fix above is inert as stated — its one caller has
      no way to obtain a value for the new parameter.** `checkTradeRisk`'s only production call
      site is `SendToBrokerDialog/index.tsx:61`, inside a `useMemo` that runs it once **per
      pinned basket row** (`for (const c of cards)`), not just the currently-active `TradeCard` —
      and `SendToBrokerDialog`'s props are only `{ cards, onClose, onSubmit }` today, with no
      channel for a per-trade override to reach it. Since the Arithmetic card's override UI can
      only exist on the one currently-active `TradeCard` (Feature 3), but the dialog needs to
      risk-check *every* pinned symbol at once, this needs its own per-symbol map, not just "the
      new parameter." Fix: add a new `overridesBySymbol: Record<symbol, MaxLossOverride | null>`
      prop to `SendToBrokerDialog`, sourced from the same page-level `maxLossOverrideBySymbol`
      cache the bullet above introduces, passed at the `<SendToBrokerDialog>` call site
      (`step-7-trade-card/page.tsx:862-868`, which currently passes only `cards`/`onClose`/
      `onSubmit`), and read as `overridesBySymbol[c.symbol]` inside the `riskChecks` `useMemo`
      that calls `checkTradeRisk`. **[D18]**
- [ ] The existing Portfolio `EditDrawer` post-trade override UI (`MaxLossBanner`) is unchanged
      by this plan — same mechanism, now also settable earlier, not two separate mechanisms.
- [ ] **Round-9 finding, HIGH severity, same class as the auto-trade limitation already flagged
      above — name this gap explicitly rather than letting it stay implicit.** Promoting
      Arithmetic to the primary, expanded-by-default card does **not** change what the
      post-trade alert system actually monitors as the position's stop. Verified: both real
      order-creation paths persist `PortfolioPosition.stop` from the **Ladder's** invalidation,
      never from Arithmetic's — `positionFromOrder` (`step-7-trade-card/page.tsx:95`):
      `stop: c.exit.invalidation`; `buildPaperPosition` (line 584): `stop: card.exit.invalidation`.
      `exitPlan` (the full Arithmetic result, including the "Bottom (final stop)" price this
      restructure makes the headline number) is persisted alongside as a separate field, but
      `frontend/lib/alertEngine.ts` never reads it — it has exactly two stop-related alert
      types, `STOP_REACHED` (keyed on `p.stop`, the Ladder invalidation) and
      `STRUCTURAL_STOP_BREACHED` (keyed on `p.structuralStop`, the **raw** structural stop
      *before* any ATR-widening decision) — there is no `EXIT_PLAN_STOP_BREACHED` type at all.
      Unlike the target side, which already has an `activeTpMethod` selector
      (`ladder | monte_carlo | exit_plan_2r | exit_plan_3r`, from the prior exit-plan-pipeline
      plan) letting a user make `TP_HIT` follow Arithmetic, **no equivalent mechanism exists for
      the stop side, and this plan doesn't add one.** Concretely: once a structural stop is
      ATR-widened — the algorithm's own documented, non-rare case — the number Kenneth was
      looking at on the primary card when deciding to trade is never the number any automated
      alert fires against. Building a real fix (a new alert type, or a stop-side active-method
      selector mirroring `activeTpMethod`) is a legitimately separate, larger feature, out of
      scope here — but flag it explicitly: the user must still manually copy
      `exitPlan.stop.price` into the position's editable `.stop` field in `EditDrawer`
      (`EditDrawer.tsx:325`) if they want the alert system to track it. **[D13, D18]**
- [ ] **Round-3 finding, widened in round 5: stale doc comments asserting "no pre-trade override
      exists" appear in (at least) four places, not the one round 3 happened to be looking at —
      sweep all of them, not just the first one found:**
      1. `frontend/types/domain.ts:690-693` — the `MaxLossOverride` interface comment: "pre-trade
      (TradeCard/SendToBrokerDialog) uses the existing two-click override UX instead of a
      persisted field" — true today (describing `SendToBrokerDialog`'s unrelated
      risk-check-bypass confirmation, `overrideReady`, not a sizing override), but this feature
      introduces exactly the persisted pre-trade field that comment says doesn't exist.
      2. `frontend/types/domain.ts:683-686` — `RiskCheckResult.maxLossLimitDollar`'s own comment:
      "no per-trade override exists pre-trade; that field lives on `PortfolioPosition` only."
      3. `frontend/lib/risk.ts:225-228` — `checkTradeRisk`'s own comment stating the same thing
      (load-bearing — see the bullet above, this is the same gap, not just stale prose).
      4. `frontend/components/organisms/TradeCard/index.tsx:751-753` — the `recommendedSize`
      memo's comment: "No per-trade override exists pre-trade (same reasoning as
      `checkTradeRisk`'s identical note) — always the global default." This is the exact code
      Feature 3/5 modify, and it explicitly cross-references `checkTradeRisk` by name.
      Update all four when this lands, so none of them mislead the next reader.
- [ ] **Round-3 finding: Stocks-mode position creation is a fourth builder, explicitly untouched.**
      `frontend/lib/paperTrade.ts`'s `buildPaperStockPosition` (lines 123-180) is a separate
      `PortfolioPosition`-builder used by the entire Stocks-mode flow (`step-7-position-card`,
      `StockPositionCard`, `StockSendDialog`, `ChartWorkspace`, `step-4-stocks`) — it also never
      sets `maxLossOverride`. This plan's Arithmetic card and pre-trade override live only on the
      Options-mode `TradeCard`; Stocks mode has its own risk gate (`confidenceGate`,
      backtest-driven) and no equivalent card. Confirmed out of scope, not silently dropped —
      see the out-of-scope list below.

## Feature 6 — Persistent Order Entry strip + final page layout

- [ ] New thin, always-visible, non-collapsible strip containing: **Order type**, **Limit**,
      **Max fill**, **Contracts** — pulled out of the old Entry Plan card, sits above all three
      method cards, rendered exactly once (not duplicated per card). **[D21, D24]**
- [ ] Max fill's *default value* is computed by a global YAML rule (`mid × (1 + slippage%)`,
      `entry_quality.max_slippage_pct`) — but **it is already per-trade editable in the app
      today** (`TradeCard/index.tsx` lines 930-938, an `EditableKV` identical in mechanism to
      Limit and Contracts). This plan does not touch that: relocating it into the strip must
      preserve its existing `EditableKV`/`onChange` editability verbatim. Only the *slippage
      percentage itself* — the formula that produces the default — stays a global,
      non-per-trade YAML setting (per D22); the resulting dollar value on any given trade has
      always been, and remains, freely overridable by hand. Do not ship this as read-only —
      that would be a regression from current behavior, not a neutral relocation. **[D22]**
- [ ] Final page order, top to bottom, under Contract Details:
      1. Order Entry strip (Feature 6)
      2. Arithmetic Profit Target — full width, expanded (Feature 3)
      3. Monte Carlo Profit Target — renamed (Feature 2)
      4. Fixed % Ladder Plan — collapsible, collapsed by default (Feature 1)
      5. Final Recommendation — standalone, always visible (Feature 8)
      **[D12, D29]**

## Feature 7 — Fix the Contracts / SendToBrokerDialog disconnect

- [ ] Confirmed real, pre-existing bug (found during the audit that led to this plan, not
      introduced by it): `TradeCard`'s `overlay.contracts` and `SendToBrokerDialog`'s own
      `rows[symbol].contracts` are two independent pieces of state that both default to `1` but
      never sync — editing Contracts on the card does not change what the broker dialog sends.
      **[D23]**
- [ ] **Correction (round-2 audit caught round-1's fix over-stating the gap): `TradeCard`
      already has most of the plumbing this needs — don't redesign it, wire into it.** Verified
      against current code: `TradeCard` already accepts a `contracts?: number` prop
      (`contracts: initialContracts = 1`, line 213) that seeds `overlay.contracts` on mount AND
      re-syncs on every later prop change via `useEffect(() => setOverlay(prev => ({...prev,
      contracts: initialContracts})), [initialContracts])` (lines 730-732), and already exposes
      every overlay change — `.contracts` included — upward via the existing `onEditsChange`
      callback (line 160, wired through `patch()` at line 738), the same `initial<X>` prop +
      `on<X>Change` callback pattern already used for `onStructuralStopChange`/
      `onFirstPassageChange`/`onExitPlanChange`. **What's genuinely missing is narrower than
      round 1's fix described**: `TradeCardData` (`frontend/types/domain.ts:345+`) has no
      `contracts` field, the `<TradeCard>` call site in `step-7-trade-card/page.tsx` (line 788)
      never passes the existing `contracts` prop, and the basket carries no per-symbol value —
      but `TradeCard`'s own `overlay.contracts` state ownership does **not** need to change; it
      already reads from a prop and reports changes via callback. **[D23]**
- [ ] Concrete fix, in three parts, all at the page/basket level — `TradeCard` itself is
      untouched:
      1. **New shared state**: a per-symbol contracts map lifted to page level in
         `step-7-trade-card/page.tsx` (or a small dedicated store, if state needs to survive
         basket navigation the way pinned candidates already do) — `Record<symbol, number>`.
         Feed it into `<TradeCard>`'s existing `contracts` prop and update it from the existing
         `onEditsChange` callback — no new prop/callback pair needed, both already exist.
      2. **Round-3 finding: `SendToBrokerDialog` itself — the literal other half of D23's own
         bug description — was never wired in round 2's fix.** `SendToBrokerDialog` seeds its
         own independent state entirely from the `1` default: `useState(() =>
         Object.fromEntries(cards.map((c) => [c.symbol, { contracts: 1, autoSend: true }])))`
         (lines 37-39), with its own editable `<input type="number">` per row (lines 163-171,
         205-213); the call site (`step-7-trade-card/page.tsx:863-867`) passes only `cards`,
         `onClose`, `onSubmit` today — no contracts map. Pass the shared per-symbol map from
         part 1 as a new prop into `SendToBrokerDialog` and seed `rows`'s initializer from it
         (falling back to `1` only for a symbol with no map entry) — without this, the dialog
         keeps showing stale `1`s regardless of what the persistent Contracts strip says,
         reproducing the exact bug being fixed. **Working default (round 9, matching how D2/
         D34/D35 already handle an unconfirmed item elsewhere in this plan rather than leaving a
         bare fork — this one had sat unresolved with no proposed default across several
         rounds, breaking that pattern): a one-off override for that submission only — editing
         inside the dialog does not write back to the shared map/strip.** Rationale: the dialog
         explicitly reviews/finalizes a snapshot of the basket right before sending, not a place
         for editing live pre-trade state that the rest of the page also reads from — writing
         back would mean an edit made while reviewing one basket item silently changes what the
         Arithmetic card's Risk-derived size and the persistent strip show for that symbol after
         the dialog closes. **✅ CONFIRMED by Kenneth** — "One-off, doesn't write back," matching
         this default exactly.
      3. **Wire it through everywhere else**: every other order-placement path reads from this
         same map instead of a hardcoded `1` — see the expanded list of paths in the note below.
         **[D23]**
- [ ] **Round-2 finding: three separate order-placement paths hardcode `contracts`/`quantity`
      to `1`, not just `SendToBrokerDialog` — all three must be fixed, or the bug persists
      through paths this plan never touched.** Verified in `step-7-trade-card/page.tsx`:
      `placeLimitPaper`/`placeMarketNow` (bound to the always-visible "Place Limit @ $X" /
      "Right Now — Market" buttons, lines 831-846) call `api.postOptionOrder({..., quantity: 1,
      ...})` (lines 614, 647) and `buildPaperPosition(...)` which hardcodes `contracts: 1` (line
      593) — entirely independent of `SendToBrokerDialog`. `AutoTradeArm/index.tsx` line 57 also
      hardcodes `quantity: 1`. All three must read from the same shared per-symbol map as the
      dialog, or editing Contracts (or clicking Feature 3's "Apply") will silently do nothing
      when a trade is placed through "Place Limit," "Right Now — Market," or auto-trade —
      reproducing the exact bug Kenneth asked fixed, just through unaudited paths. **[D23]**
- [ ] **Round-5 finding, scope corrected in round 6: `AutoTradeArm`'s wiring was asserted
      ("reads from the same shared per-symbol map"), not designed, unlike `SendToBrokerDialog`'s
      — specify it the same way, and only where a quantity actually exists to fix.**
      `AutoTradeArm`'s props are only `{ card, broker }` (`AutoTradeArm/index.tsx:12-15`), its
      call site (`step-7-trade-card/page.tsx:856`) passes only `card`/`broker`. `quantity: 1` is
      hardcoded at line 57, inside `handleArm`'s `api.armAutoTrade({...})` call — that's the only
      literal to fix. **`handleFireNow` has no quantity to change**: it calls
      `api.fireAutoTrade()` with an empty body (`api.ts` — `post('/auto-trade/fire', {})`), and
      the backend's `/auto-trade/fire` route takes no request body at all; it re-fires whatever
      `ArmedStrategy` (quantity included) was captured earlier by `/auto-trade/arm`. Fix: thread
      a `contracts` prop into `AutoTradeArm`, sourced from the shared map at the same call site,
      read only in `handleArm` instead of the literal `1`. **Side effect worth flagging to
      Kenneth, not fixable within this plan's scope**: once a trade is armed, a later Contracts
      edit or Feature 3's Apply click will *not* retroactively change what `Fire now` submits —
      the quantity is frozen at arm time by auto-trade's own existing design, independent of
      this fix. **[D23]**
- [ ] **Round-2 finding, signature corrected in round 3: fix a latent bug this change
      activates.** `isDirty()` (`TradeCard/index.tsx` line 54: `function isDirty(overlay:
      EditOverlay, data: TradeCardData): boolean`, called via `useMemo(() => isDirty(overlay,
      data), [overlay, data])` at line 766) compares `overlay.contracts !== 1` against a literal
      `1`, not against `initialContracts`. Today this is harmless because nothing ever passes a
      non-default `contracts` prop. Once this feature causes `initialContracts` to be something
      other than `1` for a previously-untouched candidate (e.g. after Feature 3's Apply button
      sets a symbol's map entry to 4), `overlay.contracts` will initialize to that value on
      mount and `isDirty` will wrongly report the card as manually edited. **Round-2's fix
      ("compare against `initialContracts`, matching every other field") isn't directly
      implementable as stated**: every *other* field `isDirty` compares is checked against
      `data.*` (a `TradeCardData` field); `initialContracts` is a component *prop*, not a `data`
      field, and `isDirty`'s current signature has no access to it. Concrete fix: widen the
      signature to `isDirty(overlay: EditOverlay, data: TradeCardData, initialContracts:
      number): boolean`, compare `overlay.contracts !== initialContracts`, and add
      `initialContracts` to the `useMemo` dependency array at the one call site.
- [ ] This is what makes Feature 3's "Apply" button meaningful end-to-end: Apply writes the
      recommended size into the shared map (via Feature 6's single Contracts field), and that
      value is now what actually reaches every order-placement path for that symbol, not just
      the basket dialog. **[D25]**
- [ ] New test coverage: a basket test with 2+ pinned symbols asserting each one's Contracts
      value reaches the broker dialog AND the quick-order paths (`placeLimitPaper`/
      `placeMarketNow`/auto-trade), not just a single-symbol happy path through the dialog alone;
      a regression test for the corrected `isDirty` comparison.

## Feature 8 — Final Recommendation: documentation, not reconciliation

- [ ] Explicitly **no** cross-method comparison/reconciliation logic. Rationale (from the
      interview): the Fixed % Ladder's basis (a flat 8% stock-price move) isn't on the same axis
      as Arithmetic's (ATR/structure-derived RR) or Monte Carlo's (% of premium, probability-
      weighted) — a numeric "these three agree/disagree" comparison would be comparing
      incommensurate things and was deliberately ruled out. **[D26, D31]**
- [ ] Content: whichever method — Arithmetic or Monte Carlo — was most recently explicitly run
      this session, its full output (stop/target or T1/T2/T3, whichever applies), and a
      timestamp label: `"computed via: <method>, HH:MM"`. **Round-2 finding: this needs a new
      field, not just Arithmetic's existing one.** `ExitPlan.computedAt` already exists and is
      client-set on receipt (`domain.ts` line 216, set at `TradeCard/index.tsx` line 470), so
      Arithmetic's timestamp is free — but `FirstPassageEstimate`/`FirstPassageContext`
      (`domain.ts` 166-185), which back the Monte Carlo card, carry **no timestamp field**, and
      `setFirstPassage({ targets: res.targets, invalidation: res.invalidation })` (line 602)
      never sets one today. Add a client-set `computedAt: string` to `FirstPassageEstimate` the
      same way `ExitPlan.computedAt` works, stamped at the same point `setFirstPassage` is
      called, so Final Recommendation has a real timestamp to source "HH:MM" from regardless of
      which of the two methods was run last. **[D28]**
- [ ] **Round-10 finding: when this content shows Arithmetic's stop, cross-reference Feature 5's
      alert-monitoring caveat — don't let this card's prominence make that gap easier to miss.**
      Final Recommendation is the most prominent, always-visible, bottom-of-page summary of the
      trade — exactly the kind of place a user glances at last before sending, without
      necessarily having opened the Arithmetic card's own detail. Feature 5 already documents
      that the post-trade alert system doesn't monitor `exitPlan.stop.price` (still keyed on the
      Ladder's `.stop` field) unless manually copied into `EditDrawer` after the position opens.
      When this card shows "computed via: Arithmetic, HH:MM" with Arithmetic's stop price, add
      one line making that caveat visible here too, not just buried in Feature 5: *"This stop
      price is not automatically monitored by alerts unless copied into the position's stop
      field after opening — see Feature 5."* **[D13, D18, D28]**
- [ ] **Round-4 finding, ✅ RESOLVED — Kenneth confirmed the working default below.**
      The Final Recommendation card is not currently empty. As it exists today
      (`TradeCard/index.tsx:1207-1243`) it already renders a `finalStatus` PASS/CAUTION/REJECT
      badge (`LabeledStatusBadge`, also color-tints the whole section) — the trade's overall
      verdict, shown **nowhere else** on the card (verified by grep) — plus "Historical accuracy
      (3×ATR exit)" (`stockConfidence`), "Contract confidence" (`contractConfidence`), and
      "Projected R/R (+8% stock move)" (`editedRR.rr`). Kenneth's conversation about Final
      Recommendation was entirely about what documents *which method was used* — it never
      addressed whether this pre-existing verdict/confidence content is kept alongside the new
      content, moved elsewhere on the page, or removed. `stockConfidence`/`contractConfidence`
      are lower-risk if dropped (also shown via `ScoreCardPanel` higher up the card) but
      `finalStatus` is not duplicated anywhere — silently deleting it during this redesign would
      remove the one place the trade's overall pass/fail call is shown. **Working default
      (round 5, matching how D2/D34 handle an unconfirmed item — propose a low-risk default so
      Build sequence step 6 isn't blocked, rather than stalling entirely): keep the `finalStatus`
      badge and its section-tinting exactly as-is, stack the new "computed via: <method>, HH:MM"
      content below it.** `stockConfidence`/`contractConfidence` are dropped — `ScoreCardPanel`
      already shows them elsewhere on the card; `finalStatus` is kept, since it's genuinely
      unique to this spot. **✅ CONFIRMED by Kenneth** — "Keep verdict, drop confidence rows,"
      matching this default exactly. **[D35]**
- [ ] **Round-8 finding, now actionable given D35's confirmed resolution above: update the
      `finalStatus` badge's tooltip copy in the same change.** `LabeledStatusBadge`'s tooltip
      reads "Overall recommendation for this trade — the worse of the stock signal's historical
      accuracy and the contract's quality verdict **below**" — "below" refers to the
      `stockConfidence`/`contractConfidence` rows, now confirmed dropped. Update this tooltip
      text so it doesn't point at content that's no longer on the card.
- [ ] **Round-7 finding, HIGH severity — D35's "working default" above left the fourth
      pre-existing row unresolved, and that omission reintroduces exactly the cross-method
      reconciliation Kenneth ruled out (D26, D31).** "Projected R/R (+8% stock move)"
      (`editedRR.rr`, line 1234) is **the Fixed % Ladder Plan's own R:R figure** — `editedRR` is
      computed from `overlay.targets[0]`, itself seeded from `data.exit.targets`, i.e. the exact
      8%-stock-move formula the plan's own Context section identifies as the Ladder's basis. It
      is *also* rendered independently, moments earlier on the same card, in the standalone
      "Risk / Reward" section (line 1196-1205) — which Feature 1 moves into the "Fixed % Ladder
      Plan" collapsible group. D35's "working default" resolved `finalStatus` (keep) and
      `stockConfidence`/`contractConfidence` (may drop) but never decided this row's fate, and
      instructed stacking the new "computed via" content "below it" unconditionally — meaning,
      as currently written, Final Recommendation would show *both* an always-on, unlabeled
      Ladder-derived R:R number *and* whichever of Arithmetic/Monte Carlo ran last, side by
      side: two methods' figures on the one card Kenneth said should document assumptions, not
      compare methods (D26, D28, D31). **Resolution: drop "Projected R/R (+8% stock move)" from
      the always-on content.** It is not lost — D30's empty-state fallback already shows the
      Ladder's live numbers, properly labeled ("No method explicitly run — showing Fixed %
      Ladder Plan (default)"), covering the exact same figure honestly instead of leaving it as
      an unlabeled permanent fixture. Once Arithmetic or Monte Carlo has been run, only that
      method's content (plus the kept `finalStatus` badge) shows — no Ladder number alongside it.
      **✅ CONFIRMED by Kenneth** — "Drop it from the always-on view," matching this resolution
      exactly. **[D26, D28, D30, D31, D35]**
- [ ] Stands alone — not inside the Fixed % Ladder Plan collapsible group, since it can reflect
      any of the three methods and semantically doesn't belong to just one of them. **[D27]**
- [ ] Empty state (neither Arithmetic nor Monte Carlo has been explicitly run this session):
      falls back to showing the Fixed % Ladder Plan's live numbers (that method needs no button
      — it's always-on math off Contracts + Limit), explicitly labeled **"No method explicitly
      run — showing Fixed % Ladder Plan (default)"** so it's never a blank card, but also never
      silently presented as a deliberate choice. **[D30]**
- [ ] **Round-8 finding, HIGH severity: this fallback must explicitly name its fields, or the
      "Projected R/R is not lost, just relabeled" claim above is unverified and may be false.**
      "Fixed % Ladder Plan" (Feature 1) is a group containing three distinct sub-sections — Exit
      Plan, Sell-to-Close Plan (T1/T2/T3 targets), and Risk-Reward (`editedRR.rr`) — and "the
      Ladder's live numbers" most naturally reads as just the T1/T2/T3 targets, not the
      separately-labeled Risk-Reward figure Feature 1 merely co-locates in the same collapsible
      container. If this fallback is built showing only T1/T2/T3, the R:R figure the previous
      bullet's fix relies on ("not lost — D30's fallback already shows it, properly labeled")
      would in fact be gone from Final Recommendation in *every* state — dropped from the
      always-on content per that fix, and never present here either. **Explicit spec: the
      fallback must include `editedRR.rr`/`editedRR.model` (the Risk-Reward figure) alongside
      the T1/T2/T3 targets**, so the earlier claim is actually true as built, not just asserted.
      **[D26, D28, D30, D31, D35]**
- [ ] Placement: bottom of the page (Feature 6). **[D29]**

---

## Explicitly out of scope (confirmed during the interview, listed so it isn't re-litigated)

- Free-text "Reason" note on the risk override — cut. **[D20]**
- A per-trade override on the *slippage percentage formula* that produces Max fill's default —
  that formula stays global YAML. (The resulting dollar figure itself is already, and remains,
  hand-editable per trade today — see Feature 6's D22 bullet; that part was never in scope to
  remove.) **[D22]**
- Any cross-method reconciliation, "these agree/disagree" logic, or a single arbitrated
  number across Arithmetic/Monte Carlo/Ladder. **[D31]**
- Any change to the Monte Carlo engine, the fixed-ladder math, or the exit-plan algorithm
  itself (`compute_final_stop`/`compute_target_row`'s decision logic is untouched — only what
  they *return* changes).
- Stocks-mode position creation (`buildPaperStockPosition` and its callers in
  `step-7-position-card`, `StockPositionCard`, `StockSendDialog`, `ChartWorkspace`,
  `step-4-stocks`) — the pre-trade override lives on the Options-only Arithmetic card and has no
  Stocks-mode equivalent in this plan. **[D18, D19]**
- Making auto-trade-fired orders create a `PortfolioPosition` row — a pre-existing gap in
  auto-trade's own architecture (it never persists a position on fill today, for any reason, not
  just overrides) that this plan does not fix. See Feature 5's auto-trade note. **[D19]**
- Post-trade transparency in the Portfolio `EditDrawer`'s own separate "Compute Exit Plan" card
  (~`EditDrawer.tsx` lines 570-630) — it calls the same `/contracts/exit-plan` endpoint and will
  receive Feature 4's new fields automatically, but this plan does not add UI there to display
  them. Kenneth's interview was scoped around the pre-trade `TradeCard`; if the same "both
  prices, distance, justification" transparency is wanted post-trade too, that's a follow-up,
  not silently included here. **[D13, D14]**

## Build sequence with checkpoints

1. **Feature 4** (backend field exposure) first — everything else displays these values, build
   the source before the consumers. ✅ checkpoint: `pytest tests/test_exit_plan.py` +
   the router test green, new fields verified present in both stop branches and both
   snap/no-snap target branches.
2. **Feature 6 + Feature 7** together (Order Entry strip + the Contracts bug fix) — this is
   larger than it first looks (round-2 audit finding): a new per-symbol shared-contracts state,
   wired into all three order-placement paths (`SendToBrokerDialog`, `placeLimitPaper`/
   `placeMarketNow`, `AutoTradeArm`), plus the `isDirty` comparison-bug fix it activates. This is
   the shared plumbing that Feature 3's Apply button and every card's scale-out math depend on;
   get the single source of truth right, across *all* order paths, before building on top of it.
   ✅ checkpoint.
3. **Feature 1 + Feature 2** (revert Exit Plan, extend/rename Monte Carlo card) — lower risk,
   mostly subtractive/renaming, do before the new card so the page never has 4 exit-plan
   systems visible at once mid-build.
4. **Feature 3** (new Arithmetic card) — the largest, most novel piece; depends on Features 4,
   6, 7 all being done first.
5. **Feature 5** (pre-trade override) — layered onto Feature 3. Threaded through both real
   Options-mode `PortfolioPosition`-builders (`buildPaperPosition`, `positionFromOrder`);
   auto-trade and Stocks mode are confirmed out of scope (round 3 finding — neither creates a
   `PortfolioPosition` through a path this override can reach), not silently missed.
6. **Feature 8** (Final Recommendation) — last, since it depends on knowing what Features 2 and
   3 each expose once built.

Each checkpoint: `npm run typecheck && npm run test` (frontend), `pytest` (backend touched
paths), plus a manual pass through the demand ledger confirming every D# for that feature is
visibly satisfied on screen — not just "the code compiles."

## Verification

- Backend: `cd backend && pytest tests/test_exit_plan.py` (extended — this one file already
  covers both the unit tests and the `/contracts/exit-plan` router tests).
- Frontend: `cd frontend && npm run typecheck && npm run test` (TradeCard, EditDrawer,
  SendToBrokerDialog suites).
- Manual: open a TradeCard, confirm the Order Entry strip shows once and its Contracts value is
  what actually reaches the broker dialog; confirm Arithmetic renders placeholders before any
  click, then full transparency (structural price, ATR-floor price, distance, tolerance,
  justification sentence) after "Compute Arithmetic Plan"; confirm "Check Structure" alone on
  the Arithmetic card populates its structural-stop display (source + price + distance) without
  a full compute — this reuses the existing "Structural stop — Order Block/Swing Low/Swing
  High" block, not a line literally labeled "Bottom"; confirm the Monte Carlo card's renamed
  button and its new "Structural level found" line (round 9: renamed from "Bottom" — verify it
  reads distinctly from Arithmetic's "Bottom (final stop)" and that the two can genuinely show
  different prices for the same contract when the stop is ATR-widened); confirm the Fixed %
  Ladder Plan group is collapsed by
  default and its old Exit Plan sub-card has no compute buttons; confirm Final Recommendation
  is blank-but-labeled before any method runs, then updates to whichever method ran last with a
  timestamp; confirm a pre-trade risk override changes Risk-derived size and, after Apply,
  updates the shared Contracts field, and that placing the order carries the override onto the
  resulting Portfolio position — **then reload the portfolio page (forcing a fresh backend sync,
  not just reading the optimistic post-submit UI state) and re-confirm the override is still
  present**, per Feature 5's `toBackendPayload` finding: the optimistic UI can look correct even
  when the override never reached the backend at all.
- Walk the full demand ledger top to bottom against the running app — every D# gets a checkmark
  against an actual screen, not just a code diff.
