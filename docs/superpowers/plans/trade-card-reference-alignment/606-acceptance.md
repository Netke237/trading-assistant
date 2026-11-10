# #606 — Monte Carlo essentials and nested Barrier Race

Covers D06, D08, D09 and the Monte Carlo part of D07. The presentation reference is frozen at d8245e66. The numbers come from the existing production source; no formula, request or freshness rule changed.

Implementation `b77a833` (`fix(trade-card): focus Monte Carlo essentials and nest barrier race`), built after the phase moved from the Codex session to a Claude session on Kenneth's instruction.

## What the Monte Carlo card shows

**Visible**
- T1/T2/T3 % inputs and the explicit Run button.
- The estimate's premium basis.
- **Stop context**: stock barrier, option-price barrier, option value at the stock stop and loss at the stock stop. The last two are priced at barrier time and come only from the current race (the existing `raceIsShowable` gate). Otherwise they read *Unavailable*. They are never Arithmetic or today's Black-Scholes values.
- A one-line source note that links to the shared Exit Plan. It replaces the duplicated "Actual Exit Plan settings" block.
- The compact **Monte Carlo targets** table: Target, Stock price, Option value, Probability (independent touch), Conditional time, Est. dollar outcome. All rows are shown.
- Stale and fallback-volatility cautions stay outside the closed sections.

**Closed by default, still mounted**
- *Barrier Race · graphical outcomes & details*: the unchanged BarrierRaceCard, with bars, shares, Use-target controls, medians, R:R, edge and the deeper risk explanations. It is no longer a full-width section after the method grid.
- *Monte Carlo model, inputs & provenance*: the model, formula, settings, input precedence and the single Structural-level line.

Opening either section runs nothing.

## Browser evidence

Results in [browser-checks.json](evidence/606/browser-checks.json):
- 6 runs: 1200, 1366 and 1920 px, each in dark and light. 39 checks per run, all passed.
- 0 page errors, 0 saves or broker writes, 0 external requests.

States covered:
- **Unrun**: values unavailable, no request on load or when the race is opened.
- **Fresh**: exactly one request. Stop value $0.65 and loss $1.50 come from the race fixture. Column order is as listed above, all 3 rows are shown, the race stays closed, and no race control appears outside the MC card.
- **Stale**: values are hidden, the warning is visible and the race shortcuts are suppressed. The same race returns when the premium stop is restored.
- **Restored** (switch contract and back): the previous race is hidden, so the barrier values read *Unavailable*. This is unchanged existing behaviour.
- **Rerun**: one new request, and the fresh values show again.

Screenshots (1366 px):
- [dark initial](evidence/606/1366-dark-initial.png), [dark calculated](evidence/606/1366-dark-calculated.png), [dark race open](evidence/606/1366-dark-race-open.png), [dark stale](evidence/606/1366-dark-stale.png), [dark restored](evidence/606/1366-dark-restored.png)
- [light calculated](evidence/606/1366-light-calculated.png), [light race open](evidence/606/1366-light-race-open.png)

To reproduce, run this against a local mocked frontend on port 3097, never the live port 3001:

```sh
node docs/superpowers/plans/trade-card-reference-alignment/capture-mc-race.cjs \
  --repo-root "$PWD" --output /tmp/tc606-browser --base-url http://127.0.0.1:3097 \
  --browser /opt/pw-browsers/chromium --widths 1200,1366,1920 --themes dark,light
```

## Local checks (re-run by the coordinator)

- Typecheck is clean.
- Full Jest (`--maxWorkers=2`) passed in one run: 337/337 suites, 6240/6240 tests.
- Expected-red: all 12 new tests in `TradeCard.monteCarloEssentials.test.tsx` failed before the change, each for the expected missing-presentation reason.

## Deviations and notes

- **Field order differs between methods for now.** Arithmetic and Ladder keep the old field order until #607.
- **Stop value and loss are per share**, as in the race's own figures. No new ×100 formula was added.
- **"Structural level found"** now appears once, under provenance, instead of repeating on every row.
- **Not fixed, unchanged behaviour:**
  - BarrierRaceCard's own "same for every target" line reads the first outcome without checking that targets agree.
  - A restored estimate shows the MC rows without the fallback-volatility caveat, because the race is hidden.

## Status

This is ticket-level acceptance only. The integrated phase code audit is still pending, and #607–#610 remain.
