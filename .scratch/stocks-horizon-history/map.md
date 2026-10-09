# HISTORY coordination map

## Scope
D1 #112 plan/audit -> D2 #113/#123 build/audit/PR -> D3 #114 mini PC execution.
Repository numeric/persistence gate is authoritative. Plan clean: 2 independent rounds.

## Current Frontier
- 04 / #127: focused regression, temporary migration and broader verification in progress.
- 01 / #124, 02 / #125 and 03 / #126: implemented; final closure awaits code audit.

## DAG
#124 -> #125 -> #126 -> #127 -> #128 -> #114.
#114 additionally requires D2 merged and mini PC access.
Implementation acceptance unblocks the next slice; GitHub build-ticket closure waits for final code audit.

## Status
D1 complete. D2 in-progress and unaudited; not ready to merge. D3 pending.
