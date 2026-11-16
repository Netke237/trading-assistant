# #605 — compact Exit Plan and expandable structure evidence

D04/D05 presentation amendment following #604. Frozen reference d8245e66; numerical/editing authority is existing production source. Source/transport/calculation helpers and alert rules stay unchanged.

The actual Exit Plan is one full-width section with three responsive columns. Invalidation, premium-loss amount per option share, loss percentage, remaining option value and per-contract loss/value remain visible. Main stock/premium/time figures are24px, other readouts16px with12px labels; heading20px. The time threshold reads **3 days to expiry**, with its concise ≤3DTE/no-automatic-close qualification. Missing invalidation and small-premium pinned/global handling remain visible and use the existing fields and bounds.

Detailed premium basis, entered-quantity totals, full resolution/inheritance and time explanation are in default-closed disclosures. The complete original Structure & Stops evidence, its scan/Arithmetic/raw-structure pricing distinctions, ATR/geometry, stop-cost results/explanations and Check structure action are in **Structure evidence · ATR, pricing & Check structure**, closed initially inside Exit Plan. Opening a disclosure runs no calculation. The separate large block is removed from the main reading path. Its duplicate execution invalidation KV is deliberately removed; the one actual editable Invalidation field supplies that same information and value.

Information preservation: every unique structure/result/action JSX block remains; all original `exitPremium` basis/share/contract/quantity strings remain in their applicable visible or expandable context. No calculated stop is applied automatically. The source stop-cost detail is not substituted for Monte Carlo barrier-time risk. This is not a new pricing or stop engine. Later method/decision amendments remain separate.

## Browser evidence

[Six-run checks](evidence/605/browser-checks.json):1200/1366/1920px, dark/light themes,34 assertions per run, zero page errors. Initial, calculated, stale and restored states verified with guarded fixture APIs; no Portfolio save/broker order attempted. Covers unchanged section order, contract typography, compact readable time threshold, closed structure evidence, no automatic calculations, comparison alignment and stale/candidate isolation.

Inspect the compact section: [dark](evidence/605/1366-dark-exit-plan.png), [light](evidence/605/1366-light-exit-plan.png). Full-page [dark initial](evidence/605/1366-dark-initial.png), [light initial](evidence/605/1366-light-initial.png), [dark restored](evidence/605/1366-dark-restored.png), [light restored](evidence/605/1366-light-restored.png).

Reproduce against a local mocked frontend at3097 (not live3001):

```sh
node docs/superpowers/plans/trade-card-reference-alignment/capture-exit-plan.cjs \
  --repo-root "$PWD" --output /tmp/tc605-browser --base-url http://127.0.0.1:3097 \
  --browser /usr/bin/chromium --widths 1200,1366,1920 --themes dark,light
```

## Regression and phase status

Expected-red tests demonstrated the old abbreviated threshold and absent nested evidence before implementation. Exact local-check results and implementation SHA are appended after the run completes. Independent plan stage3 is clean for the remaining approved tasks; integrated phase code audit remains pending all seven builds. Browser acceptance is specific to this amendment and does not claim all D01–D12 are complete.

## Completed local checks

Implementation `2df60eb649da6790cc144979c4098737f80f81ef`. Final typecheck passed. Expected-red:2 failed/19 passed before changes. Full Jest:333/336 suites and6224/6228 tests passed, with4 timing failures across3 unchanged suites under2-worker load. All3 suites then passed unchanged serially (84/84 tests), preserving their original assertions and timeouts. Combined336-suite/6228-test coverage is clear. No production changes after the six browser runs. This is full-run plus focused-retest evidence, not a single all-green full invocation.
