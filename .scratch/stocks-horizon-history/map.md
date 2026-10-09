# HISTORY coordination map

## Scope
D1 #112 plan/audit -> D2 #113 build/audit/PR -> D3 #114 mini PC execution.
The numeric/persistence audit gate in PROJECT_STATE.json is authoritative.

## Current Frontier
- D1 #112: plan ready for independent round 1; no build started.

## DAG
01 retention -> 02 coherent backfill -> 03 refresh/evidence -> 04 verification/runbook -> 05 audit/PR -> 06 mini PC.
01 is blocked by D1 clean. 06 also requires D2 merged and the mini PC host.

## Status
D1 in-progress. All local build tickets pending; external build issues not yet published.
