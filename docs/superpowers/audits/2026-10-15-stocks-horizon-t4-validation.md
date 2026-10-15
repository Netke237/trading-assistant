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
Code round 1: one gate finding on afbd292f..154de52c (all 16 original
files). Reviewer: /root/t4_code_audit_1. Recomputing a configured percentage
as depth/100 shifted strict Fib boundaries by one floating-point unit and
fabricated trades on unchanged closes.

Fix b77fb014 uses the detector's canonical ratios and exact frozen origin
for the 100% fallback. Thirty-two boundary regressions cover both directions,
all supported depths, equality, strict one-ULP crossings, frozen stops and
public-adapter trades. Old-code RED: 17 failed / 15 passed. Post-fix focused
setup/tuning/T1 checks: **215 passed**; frontend typecheck passed. Legacy
simulator and existing stock signal code are unchanged by this fix.

Code round 2: fresh reviewer /root/t4_code_audit_2 independently reviewed
c4126c55..b77fb014 and interactions with the public adapter/simulator, frozen
geometry and cache/CLI source identities. **Zero gate findings.** Independent
Python 3.11 check: **89 setup tests passed**, including all 32 new regressions.
Audited application head: b77fb01488df14225aef7e48666fa883b0fb8474.

Plan and code stages are clean after two rounds each. Exact-head CI and
self-merge conditions remain pending; the phase is built and unmerged.

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


## Publication block

Automatic approval review rejected the branch push and PR creation even after
verifying that origin is the same repository linked in #118. GitHub reports
Netke237/trading-assistant as public; the review required explicit user
authorization for public disclosure of the audited code/tests. No workaround
was attempted. Implementation and independent audits are complete locally.
Exact-head CI and self-merge remain pending publication approval.


## Publication authorization

On 2026-10-15 the user explicitly authorized the public branch push and PR
creation only. The automatic-review publication block is resolved for those
actions. Do not merge automatically. Exact-head CI will be checked on the PR;
historical tuning and adoption remain separate.


## Verified merge

The user subsequently instructed merge if audited, superseding the PR-only
hold. Both independent audit stages were verified clean after two rounds each;
all three CI checks were SUCCESS on exact head
33ea2823e13f59e61238661c14d93731419b4ee1. Only documentation records differed
from the final audited application commit. The PR was OPEN and MERGEABLE.

PR #325 was merged with a merge commit and --match-head-commit safeguard.
GitHub verified MERGED at 1031a82fc79cb5803793b60a4f46a9ed35e8ff4a on
2026-10-15T05:53:58Z. Issue #118 closed automatically. The task claim was
released and its agent-in-progress label removed. Historical tuning and
adoption were not part of this merge. This merge record is retained on a
local documentation follow-up branch; the live PR merge is authoritative.
