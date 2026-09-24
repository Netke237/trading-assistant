# Screener pinning pass — literal expected strings instead of an 8th round

**Date:** 2026-09-24 · **Branch:** `claude/optimistic-wozniak-nwe8nz` · **Layer:** frontend tests only
**Source:** decision AUTOTRADE-ALERT-AND-SCREENER-WORK-ORDER-2026-09-20 item (3); `already_shipped[0]`
("Screener layout + the tooltip that caused every horizontal scrollbar", 7 rounds, not clean).

## The defect being closed

Rounds 5, 6 and 7 each found the same thing: **the production output is correct, and the
tests vouching for it are circular.** The page-level pins in `gateSummary.test.tsx`
(`PART_PINS`, `CELL_PINS`) rebuild the expected string with the *same builder the page
rendered with*, over data scraped off the rendered element, so a defect *inside* a builder
moves expectation and actual together. Round 7 measured two:

- **F1** — swapping the two bands inside `ivThresholdSentence` ships green; the page prints
  "IV rank ≤ 55 → PASS" beside a CAUTION badge for IV 45.
- **F2** — swapping `evReject` / `evCaution` inside `eventVolGateTooltip` ships green; the
  banner and the tooltip one pixel below state the window in opposite directions.

The page's own good pattern — `eventWindowSentence` pinned by literal strings at two
argument sets (`gateSummary.test.tsx` "the event window sentence states the boundary…") —
was never applied to the other builders. This pass applies it to all of them, once.

## Scope — every sentence builder in the two named files

**`app/(frame)/screener/step-5-vol-events/page.tsx`**

| Builder | Literal pin today? | This pass |
|---|---|---|
| `ivThresholdSentence` | **no** (F1) | add |
| `eventWindowSentence` | yes | — |
| `headSentence` | yes | — |
| `causesSentence` / `CAUSE_LABEL` | yes | — |
| `missingReadingClause` | yes | — |
| inline `gateSentence` branches, `gate-rule` | yes (in `PART_PINS`) | — |

**`lib/statusTooltips.ts`** — none of these has a literal whole-string pin today except
three `gateDriverPhrase` arms (`toBe('IV rank')` etc.); the rest are regex/`toMatch` or
untested: `GENERIC_STATUS_TOOLTIP`, `positionStatusTooltip`, `stockStatusTooltip`,
`regimeStatusTooltip`, `regimeMetricTooltip`, `regimeNoDataTooltip`, `gateDriverPhrase`
(the three PASS arms), `eventVolGateTooltip` (F2), `winRateTooltip`, `backtestGateTooltip`,
`stockScanGateTooltip`, `contractScoreTooltip`, `contractBreakdownTooltip`,
`regimeFitTooltip`, `safetyFlagTooltip`, `fundamentalScoreTooltip`, `riskStatusTooltip`,
`scanPipelineStatusTooltip`, `alertStatusTooltip`, `eventProximityGateTooltip`,
`ruleContributionTooltip` (only the branches this file owns — `confidence`, `regime`,
`fundamentals`, `default`, and the GENERIC fallback when a `scoreDetailText` helper returns
`undefined`; the detail-text helpers themselves live in `lib/scoreDetailText.ts` and are out
of scope).

**Out of scope, named so nobody reads silence as coverage:** `lib/scoreDetailText.ts`,
`lib/ivBasis.ts` (`formatIv`, `ivColumnLabel` — used by step-5 cells, pinned in their own
tests), and any other page's local copy.

## The method (the eventWindowSentence pattern, made explicit)

1. **Every branch gets one whole-string `toBe` against a hand-written literal.** Every
   `switch` arm, every ternary arm, every optional suffix both on and off. No `toMatch`, no
   `toContain`, no expectation built by calling production code.
2. **Numbers are chosen so that no two slots share a value**, so swapping any two
   interpolations changes the string (21/45, 34/55, distinct trade counts, etc.).
3. **Any builder that interpolates a number gets a second argument set with different
   numbers**, so a builder with a value baked in passes one pin and fails the other.
4. **Literals are derived by hand from the rule the sentence states** (the band table, the
   comparator), never by running the builder and pasting the output. Where the hand-derived
   literal and the builder disagree, that is a finding: stop, and if fixing it changes what
   a user sees, ask Kenneth before changing production code.
5. **Band edges are pinned where the builder itself decides a band** (`stockStatusTooltip`,
   `fundamentalScoreTooltip`, `riskStatusTooltip`, `contractScoreTooltip`,
   `backtestGateTooltip`'s expectation clause): value exactly at the edge and one below.
6. **Two rendered-page literal pins** in step 5, so the call sites are pinned too, not only
   the builders: one Swing scan (a rank row at IV rank 45 with an event 30d out; an
   absolute-IV row; an unreadable row) asserting the whole `[data-line="thresholds"]` text
   and one row's full tooltip text literally. These catch a swap at the page's call site
   (e.g. `evReject: evCaution`) independent of the circular `PART_PINS` rebuild.

## Files

- **new** `frontend/lib/__tests__/statusTooltips.literal.test.ts` — every
  `statusTooltips.ts` builder above.
- **new** `frontend/app/(frame)/screener/step-5-vol-events/__tests__/literalPins.test.tsx`
  — `ivThresholdSentence` (rank only; absolute only; both, in the order given; a `null`
  caution max renders `—`; empty list renders `''`) and the two rendered-page pins.
- **edit (comment only)** `page.tsx` lines ~110-116: the comment claims a 20-point shift "is
  now caught"; round 7 proved it was not. Point it at the new literal pins, which is what
  now makes it true.

No production behaviour changes. If step 4 turns up a wrong string, that becomes its own
decision for Kenneth, not a silent fix in this pass.

## Verification

- `npm run typecheck`, full `npm run test` (frontend). Backend untouched, but the full
  backend suite is run once anyway per the session brief.
- **Mutation checks**, each applied to production code, run against the full frontend
  suite, reverted; each must go RED:
  - M1 = F1: swap `passMax`/`cautionMax` inside `ivThresholdSentence`.
  - M2 = F2: swap `evReject`/`evCaution` inside `eventVolGateTooltip`.
  - M3: swap `evReject`/`evCaution` at the page's call site to `eventVolGateTooltip`.
  - M4: `stockStatusTooltip` raw band `>=` → `>` on the PASS edge.
  - M5: `riskStatusTooltip` positions `Math.floor` → `Math.round`.
  - M6: `backtestGateTooltip` drops the "Fails on expectancy" clause.
  - M7: `regimeFitTooltip` swaps 'a clean' / 'a mixed'.
  - M8: `winRateTooltip` swaps `passMin`/`cautionMin` in the band text.
  - M9: `gateDriverPhrase` ungated-PASS wording altered by one word.
  - M10: `contractScoreTooltip` `(+N more)` count off by one.
  Each must fail in the new files specifically; the run records which test killed it.
- `python3 scripts/state.py` exits 0 with the new phase entry.

## Done means

Plan round clean → build → code round clean (≤ 3 rounds total), phase entry
`SCREENER-PINNING-PASS` in PROJECT_STATE.json, and `already_shipped[0]`'s note records that
its round-7 findings F1/F2 are closed by this pass (it does NOT set that entry
`audit_clean: true` — the code round on this pass is what speaks to that, and only for the
F1/F2 circularity it was built to remove).
