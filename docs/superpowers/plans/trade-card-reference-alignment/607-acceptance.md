# #607 — Arithmetic/Ladder target tables and two/three-method comparison

Covers D06, D07, and the remaining comparison aspects of D01. The presentation reference is frozen at d8245e66. Values come from the existing production source; no formula, request, persistence or selection rule changed.

Implementation:
- `46deb11` `fix(trade-card): align method targets and comparison tables`
- `c8fd126` `fix(trade-card): keep ladder targets unclipped in two-method comparison`. This retry fixed the first browser run's defect: with Monte Carlo + Ladder or Arithmetic + Ladder at 1366 px, the Ladder table scrolled inside a 391 px card, cutting off the full-position outcome and hiding the rung column.

## What the cards show

Every method now uses the same layout: basis slot, then a stop context of four fields, then a target table. The table columns are **Target · Stock price · Option value · Probability · Conditional time · dollar outcome**.

**Arithmetic**
- Visible:
  - calculated stock stop;
  - the shared Exit Plan option threshold, labelled as shared;
  - option value and loss at the stock stop, priced at the **current time** with an explicit Black-Scholes-today basis note (different from the Barrier Race's barrier-time value);
  - the targets in the table use the resolved target.
- Default-closed, still mounted:
  - *Original targets, snap geometry & pricing model*;
  - *Arithmetic basis, inputs & provenance*.

**Ladder**
- Visible:
  - shared Exit Plan stock invalidation and premium threshold, with their source lines;
  - Ladder-specific value and loss at the stock stop read *Not calculated*;
  - probability and time read *Not supplied*;
  - editable target prices with unchanged handlers;
  - full-position and rung outcomes in separate columns, never added together.
- Default-closed: *Ladder R:R, allocation & pricing*, holding per-target R:R and contracts to sell.

**Comparison**
- Cards that share a row have equal outer heights, and their header, basis, stop and target slots line up with 0 px offset.
- When the Ladder is compared and the results area is too narrow for it to share a row unclipped (two methods below a 1024 px results width), it takes a full row.
- With three methods, at most two cards share a row below a 1541 px results width, and the Ladder spans the row.
- Viewing or switching comparisons runs no calculation.

## Browser evidence

[browser-checks.json](evidence/607/browser-checks.json) holds the final run, after `c8fd126`:
- 6 runs: 1200, 1366 and 1920 px, each in dark and light.
- 87 checks per run, all passed. 0 page errors, 0 writes, 0 external requests.

States covered:
- **Initial**: Monte Carlo only, and opening the comparison runs nothing.
- **Three methods, calculated**: every table has the column order above, with rows present. Ladder *Not supplied* / *Not calculated*. Arithmetic current-time label. Disclosures closed but reachable.
- **Each pair of two methods**: MC + Arithmetic, MC + Ladder, Arithmetic + Ladder.
- **Edited Ladder target**: the outcome updates, from $140.00 to $990.00 in the fixture.
- **Stale** and **restored**.

In every state no table scrolls sideways or spills out of its card, there is no page overflow, and the total stays at 2 calculation requests.

Screenshots:
- [1366 dark calculated](evidence/607/1366-dark-calculated.png)
- [1366 light calculated](evidence/607/1366-light-calculated.png)
- [disclosures open](evidence/607/1366-dark-details-open.png)
- [MC + Ladder at 1366](evidence/607/1366-dark-mc-ladder.png)
- [edited](evidence/607/1366-light-edited.png)
- [restored](evidence/607/1366-dark-restored.png)
- [1920 dark](evidence/607/1920-dark-calculated.png)

To reproduce, run this against a local mocked frontend on port 3097, never the live port 3001:

```sh
node docs/superpowers/plans/trade-card-reference-alignment/capture-method-tables.cjs \
  --repo-root "$PWD" --output /tmp/tc607-browser --base-url http://127.0.0.1:3097 \
  --browser /opt/pw-browsers/chromium --widths 1200,1366,1920 --themes dark,light
```

## Local checks (re-run by the coordinator at c8fd126)

- Typecheck is clean.
- Full Jest (`--maxWorkers=2`) passed in one run: 338/338 suites, 6251/6251 tests.
- Expected-red: before `46deb11`, all 10 new tests in `TradeCard.methodTargetTables.test.tsx` and the extended column-order test failed, each for the expected missing-presentation reason.

## Deviations and notes

- **Arithmetic option-price slot.** It shows the shared Exit Plan premium-stop threshold, labelled as shared. Arithmetic has no option stop of its own.
- **Ladder figures helper.** The row's existing arithmetic moved unchanged into the local pure helper `ladderTargetFigures()`, shared by the row and the R:R disclosure.
- **Ladder option cell.** It now always renders, reading *Unavailable* when there is no estimate.
- **Not fixed (noticed):**
  - `TargetRow` looks like dead code.
  - The comment above the Arithmetic slot is mislabelled.
  - The Ladder's 500 px threshold assumes today's value widths; the table keeps its sideways-scroll fallback.

## Status

This is ticket-level acceptance only. The integrated phase code audit is still pending, and #608–#610 remain.
