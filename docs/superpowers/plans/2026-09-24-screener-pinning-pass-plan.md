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
(every arm, both nouns), `eventVolGateTooltip` (F2), `winRateTooltip`, `backtestGateTooltip`,
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
6. **Rendered-page literal pins** in step 5, so the call sites are pinned too, not only
   the builders. One Swing scan with an injected IV-threshold fixture in which **all four
   numbers differ from each other and from the event window** — rank 30/50, absolute
   40/60, event 21/45 (plan round 1 F1: the shipped FALLBACK and every existing fixture set
   rank == absolute, so a page that looked up the rank band for an absolute row was
   invisible). Rows: rank 37 with an event 60d out (IV CAUTION, event PASS — the two sides
   differ); absolute IV 58 with an event 10d out (IV CAUTION, event REJECT); an unreadable
   row. Assert the whole `[data-line="thresholds"]` text literally and **every** row's full
   tooltip literally. These catch a swap at the page's call site (e.g. `evReject:
   evCaution`, or `'rank'` passed for `b` in the `ivBands` map) independent of the circular
   `PART_PINS` rebuild.
7. **`gateDriverPhrase` is pinned on every arm with both nouns** — `'IV rank'` and `'IV'` —
   including the reading-driven IV arm and the reading-driven "both" arm, and
   `eventVolGateTooltip` gets a literal with an absolute basis, IV REJECT, event PASS (plan
   round 1 F2: hard-coding `'IV rank'` in the IV arm shipped 1811/1811 green, labelling an
   absolute level a percentile).

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
  - M11 (plan round 1 F2): `gateDriverPhrase` pushes a hard-coded `'IV rank'` instead of
    `ivNoun`.
  - M12 (plan round 1 F1): the page's `ivBands` map passes `'rank'` instead of `b` to
    `getIvPassMax` / `getIvCautionMax`.
  Each must fail in the new files specifically; the run records which test killed it.
- `python3 scripts/state.py` exits 0 with the new phase entry.

## Done means

Plan round clean → build → code round clean (≤ 3 rounds total), phase entry
`SCREENER-PINNING-PASS` in PROJECT_STATE.json, and `already_shipped[0]`'s note records that
its round-7 findings F1/F2 are closed by this pass (it does NOT set that entry
`audit_clean: true` — the code round on this pass is what speaks to that, and only for the
F1/F2 circularity it was built to remove).

## Audit log

- **Plan round 1** (2026-09-24): 2 gate-level findings, both method gaps, both taken.
  F1 — the planned page fixture used coinciding rank/absolute thresholds (the FALLBACK's),
  so a rank-for-absolute band lookup on the page stayed invisible → method rule 6 now
  injects four distinct thresholds, M12 added. F2 — `gateDriverPhrase`'s reading-driven IV
  arm was pinned only with the noun `'IV rank'`; hard-coding it shipped 1811/1811 green →
  rule 7, M11 added.
