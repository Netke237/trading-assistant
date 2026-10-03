# TRADE-CARD-BARRIER-PRESENTATION — work log

Session event evidence for this task. The canonical status is the task's entry
under `task_backlog.items` in `docs/superpowers/PROJECT_STATE.json`.

## Scope and ownership

- Claim: `TRADE-CARD-BARRIER-PRESENTATION` on branch `claude/zen-newton-o3ix8q`
  (taken 2026-10-03 via `scripts/claim.py`).
- Base: `origin/main` at `c3f6d51`.
- Allowlist: `frontend/components/organisms/BarrierRaceCard/**`. The
  implementation commit touches only these three files:
  - `frontend/components/organisms/BarrierRaceCard/index.tsx`
  - `frontend/components/organisms/BarrierRaceCard/BarrierRaceCard.module.css`
  - `frontend/components/organisms/BarrierRaceCard/__tests__/BarrierRaceCard.test.tsx`
- Not touched: TradeCard, MethodPickSelector, `lib/barrierRace.ts`, shared
  types, backend, the context route and the step-7 page.

## Commit

- `5134201` — TRADE-CARD-BARRIER-PRESENTATION: one comparison row per race
  target. The diff is `c3f6d51..5134201`: 3 files, +510/−194.

## What changed

1. **One comparison row per target.** Each row shows:
   - the target % and the option price;
   - the stacked split bar (still drawn from the raw `p*` shares);
   - all four first-outcome percentages (`weightPercents`, the allocated
     weights);
   - the conditional median to target;
   - the stock-stop R:R (bold);
   - the edge per contract (neutral colour, so no verdict and no gate).
2. **Where the R:R and edge cells come from.** They are the tails of the
   strings that `formatRaceRR` and `formatRaceEdge` already return, cut out
   rather than reformatted. The chain is the only source of each number, so
   the row and the chain cannot disagree. If either formatter ever returns
   output in an unexpected shape, the cell shows an em dash rather than a
   guessed number.
3. **A native `<details>`, closed by default and kept mounted**, holds:
   - the medians to the stock stop and to the premium stop for each target;
   - the full risk / R:R / premium-R:R / edge chains for each target, from the
     original formatters and with the same arguments;
   - all of the original explanatory prose, including the `stopCostShown`
     cross-reference.
4. **Always visible, outside the disclosure:**
   - the generic-IV fallback warning, now at the top of the card;
   - the stock-stop-under-1% warning;
   - the barriers table with its levels, sources and armed state;
   - the standalone invalidation statistic and its median;
   - a short assumptions strip: paths and 100% rows, conditional medians,
     median-day repricing, unchanged IV, and "Edge before commissions". The
     backend `first_passage.py` applies no commission, and TradeCard already
     states this.
5. **Unchanged:**
   - the props and API;
   - the early-return order: the refusal, then `!race || !isFresh`, then the
     `barriersChanged` branch, which is byte-identical and keeps the
     `stockStopMoved` distinction;
   - the formatters, weights and colours.

   No selection shortcut was added.
6. **Width.** The card is bounded with `min-width: 0` (it is a grid item).
   Each table sits in a wrapper that scrolls only as a last resort. Headers
   wrap, values do not, and the split bar is fluid (72–180px).

## Validation (Python not involved; frontend only)

- `npm run typecheck`: clean.
- `npx jest components/organisms/BarrierRaceCard`: 39/39 passed. That is the
  30 original tests, unchanged, plus 9 new ones covering:
  - the order of the row cells and their values;
  - the column headers;
  - row and chain parity across every formatter branch: measured, stop not
    repriced, zero risk, negative risk, null edge and positive edge;
  - the edge cell carries no tone class;
  - the disclosure is closed by default and holds the stop medians, chains
    and prose;
  - both warnings sit outside the disclosure;
  - the barriers and the standalone statistic sit outside the disclosure;
  - the assumptions strip sits outside the disclosure;
  - neither the changed-barrier branch nor the refusal branch has a table or
    a disclosure.
- Dependent suites: TradeCard (including methodPick), MethodPickSelector,
  StockPositionCard methodPick and the step-7 page. 12 suites, 274 tests
  passed.
- Full frontend suite: 184 suites, 4525 tests passed.
- Browser width check. This was a temporary, uncommitted harness page served
  by `next dev` and captured with Playwright Chromium, in dark and light
  themes. The containers were:
  - 600px, which approximates the narrowest real card content width: 1280px
    frame minimum − 220px nav − 300px rail − paddings;
  - 900px;
  - a 600px extreme-value case: edges of −$12345.00, a 124-day median, a
    non-zero stock-stop share and an IV-fallback warning.

  The first check found that the extreme case widened the card by 1–3px. It
  was fixed with `min-width: 0` on the card and 8px cell padding before the
  commit. After the fix, no element overflowed horizontally (`scrollWidth ==
  clientWidth` for the section and every div) and all nine columns were
  visible. The harness was deleted and `.next` was cleared.

## Independent code audit

- Rule: `audit_rule` in PROJECT_STATE, a per-stage cap of 3. Skill:
  `.claude/skills/K-adversarial-audit-loop` with
  `bmad-review-adversarial-general`.
- **Code round 1** (whole target):
  - Reviewer: a fresh general-purpose subagent, agent id `a4230f863de961e65`,
    briefed on the numeric/persistence gate.
  - Scope: `git diff c3f6d51 5134201`, the three files above.
  - Result: **ZERO gate-level findings.**
  - The reviewer verified:
    - the guard order, and that the `barriersChanged` branch is byte-identical;
    - that every old information item is still rendered;
    - that the formatter outputs are unchanged, and that the row cells match
      the chain tails in every branch;
    - weights versus raw shares;
    - that the warnings are visible outside the disclosure;
    - that the "before commissions" claim is true in the backend;
    - the neutral edge colour and that no gate was added;
    - the width handling;
    - its own run of tests and typecheck: 70/70 across BarrierRaceCard and
      `lib/barrierRace`.
  - Below the gate, deliberately not fixed: the under-1% warning still says
    "the edge below", while the edge total now also appears in the row above.
    The full chain is still below, in the disclosure.
- Fixes: none required. Outstanding gate findings: none.
- Code audit stage closed clean after 1 round.

## Not done here (final integration owns it)

- An optional controlled race-row selection shortcut wired to
  `methodPickOptions`.
- Placement within the redesigned TradeCard, and a check at the real frame
  widths (1200/1366/1440/1920) with the side rail.

No merge to main, no deploy and no broker actions.
