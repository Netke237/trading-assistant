# #608 — grouped decisions and one selected-target review

Covers D10 and D11. The presentation reference is frozen at d8245e66. The authoritative submission draft, server review, broker and auto-trade handlers, and all formulas are unchanged.

Implementation: `1a29fcd` (`fix(trade-card): group decisions and selected target review`).

## What changed

**One section, "Decision & execution"** (`section[aria-label="Decision and execution"]`), placed after Order Entry and the loss budget. In order, it contains:
1. **Choices.** The unchanged method picker: all four recorded methods including Barrier Race, Target row, Judged on and Clear.
2. **Your selected target** (`[data-selected-target-review]`, with `data-review-state` reading `not-selected`, `method-only`, `selected`, `ambiguous`, `unmatched` or `unavailable`). It holds:
   - the recorded choice;
   - the estimates at that target: premium, probability, conditional time, model, estimated gross full-position outcome, the Barrier Race edge when the race is chosen, and the applicable quantity;
   - a "Not selected / Unavailable" line instead of old values when nothing is matched.
   All of it comes from the existing `chosenRow` / `chosenMatches` / `chosenPremium` / `chosenOutcome` resolution.
3. **One link** to the actual editable Exit Plan, saying choices never replace those settings.
4. The unchanged **SubmissionReview** (#609 will make it more concise).
5. **Actions:** Track basket / Send, View chart, Export JSON.
6. The page's **Broker execution and auto-trade** panel, moved from the old 280 px side rail into this section and passed in as the new TradeCard `destinations` slot. Its handlers, guards and state are unchanged. It renders on its own only while no card is mounted (an overridden contract's plan is still being prepared). Those two conditions are exact opposites, so it can never render twice.

**Other changes**
- **Final status** moved into the identity block (`[data-identity="final-status"]`).
- **Final Recommendation removed.** It repeated the latest / all-target results. Each unique item now lives either in its method card (Arithmetic's alert caveat is now in that card's stop slot) or in the selected-target review (computed-via line, not-re-run notice, race edge).
- **Layout:** the page is now one column.

## Browser evidence

[browser-checks.json](evidence/608/browser-checks.json):
- 6 runs: 1200, 1366 and 1920 px, each in dark and light.
- 41 checks per run, all passed. 0 page errors, 0 saves or broker writes, 0 external requests.

What the checks cover:
- **Layout:** one decision section and no Final Recommendation. Final status shows in identity. The order is Exit Plan → methods → Order Entry → Decision. The four method choices, the broker panel (exactly once) and the actions sit inside the section, with one Exit Plan link.
- **No false selection:** nothing reads as selected before a choice, and a method with no row chosen isn't shown as a selected target.
- **Monte Carlo:** the review follows the chosen row ($199.00 / 40% → $203.00 / 30%, no leftover values).
- **Quantity:** an edit to 3 contracts shows in the review.
- **Barrier Race:** the selected target is reviewed with its edge.
- **Stale:** moving a barrier makes the Barrier Race review *unavailable*, never the old edge.
- **Ladder:** the selected target is reviewed, and Clear removes the selection.
- **Exit Plan:** method, row and basis choices leave its editable values unchanged.
- **Candidate switch:** the panel still renders once after switching candidate and back.

Screenshots:
- [initial](evidence/608/1366-dark-initial.png)
- [MC selected](evidence/608/1366-dark-mc-selected.png)
- [race selected, light](evidence/608/1366-light-race-selected.png)
- [stale](evidence/608/1366-dark-stale.png)
- [restored](evidence/608/1366-dark-restored.png)
- [1920 light](evidence/608/1920-light-mc-selected.png)

To reproduce, run this against a local mocked frontend on port 3097, never the live port 3001:

```sh
node docs/superpowers/plans/trade-card-reference-alignment/capture-decision.cjs \
  --repo-root "$PWD" --output /tmp/tc608-browser --base-url http://127.0.0.1:3097 \
  --browser /opt/pw-browsers/chromium --widths 1200,1366,1920 --themes dark,light
```

## Local checks (re-run by the coordinator at 1a29fcd)

- Typecheck is clean.
- Full Jest (`--maxWorkers=2`) passed in one run: 339/339 suites, 6259/6259 tests.
- Expected-red: before the change, all 8 new tests in `TradeCard.decisionGroup.test.tsx` and the rewritten `contracts-sync` page test failed because the decision and review regions did not exist yet.
- Coordinator check of the panel move: the broker review, outcome and picker hold no local state. `AutoTradeArm` renders only with a mounted card. The TradeCard has no `key`, so switching candidates does not remount it.

## Deviations and notes

- **New `destinations` slot.** The page's execution panel moved into it, and the side rail was removed.
- **Quote notices moved.** The live-quote notices and the no-live-quote confirm checkbox now sit at the top of the execution panel, beside the sends they gate.
- **Race edge row.** The review shows the selected race target's existing edge (no new math).
- **Tests.** Tests that pinned the removed all-targets list now select a row and assert the same values in the review. Every numerical, freshness, transport and safety assertion is kept.
- **e2e spec.** `frontend/e2e/tests/trade-card-ui-followup.spec.ts`: one locator was retargeted from the removed section to the new region.
- **Not fixed (noticed):**
  - SubmissionReview copy still names "Final Recommendation" (#609).
  - Code comments and the earlier capture scripts still use the old name.
  - `.decisionAnchor` CSS is dead.
  - An edited Ladder stock target is not reflected in the recorded Ladder pick. This is existing selector behaviour; the review labels the value "Recorded".

## Status

This is ticket-level acceptance only. The integrated phase code audit is still pending, and #609 and #610 remain.
