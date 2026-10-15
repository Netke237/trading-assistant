# STOCKS-HORIZON-T4 validation

Tracking: #118. Branch: board/stocks-horizon-t4-a4153a02.
Application build: 4516fa10 (#321), 44ede687 (#322).
Plan: docs/superpowers/plans/2026-10-14-stocks-horizon-t4-plan.md.

## Completed checks on the integrated build

- Python 3.11.16; full backend suite: **8,960 passed, 9 skipped** (807.68 s).
- Full 864-case legacy simulator/backtesting.py parity product: **passed**
  (880.96 s, TUNING_PARITY_FULL=1). This product compares actual entry/exit
  dates, prices, exit reasons, net returns and final-open-trade drops.
- Frontend typecheck: passed. Full Jest: **255 suites / 5,273 tests passed**.
- Setup-specific deterministic tests: **57 passed**; final tuning integration:
  **45 passed**, including both directions with real setup detectors and real
  simulation through sample walk-forward, full-universe recheck, heldout
  isolation and both cost levels. Existing scoring gate masks are isolated
  in synthetic research fixtures; gate/window restrictions are tested directly.
- Explicit CLI probe for breakout_setup:Swing,fibonacci_pullback:Swing:
  passed using the three 251-bar repository fixtures. This is a performance
  probe of machinery, not historical trading evidence.

The normal backend suite requires the execution environment's additional
network permission so SQLite worker-thread wakeups reach the asyncio loop.
An initial sandbox-only run stalled in the session table-creation fixture;
no application/test workaround was introduced. An exploratory full run was
stopped after final cache-read hardening; the complete count above comes
from the definitive run after the final application commit.

## Audit and remaining work

Plan: two independent rounds, one numeric finding fixed, then clean.
Code: round 1 reviewing afbd292f..154de52c; not yet clean. Its Fibonacci strict
confirmation rounding finding is pending correction and fresh independent
review. The build is unfinished and not ready to merge until that gate clears.

## Historical evidence

This cloud workspace has repository fixture bars only. No mini-PC database
run, historical adoption evidence or profitability claim is included.

On a machine with the stored historical database and pinned Python 3.11:

```sh
python backend/scripts/tune_horizons.py --cells breakout_setup,fibonacci_pullback --workers 8
```

Use the CLI's output/data paths and immutable run identity to preserve the
resulting report and trades. Default costs remain 0.05% per leg, with 0.2%
per-leg stress results. No active horizon profiles are adopted by this run.
The existing six-strategy default run is unchanged; these setup cells must be
selected explicitly. Their fire rates count gated confirmed entry events,
not raw scanner setup rows. Scanner UI, broker and watch behavior are unchanged.
