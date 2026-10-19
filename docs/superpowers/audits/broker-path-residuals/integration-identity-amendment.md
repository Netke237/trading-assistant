# Integration identity clarification — 2026-10-13

Coordinator discovered after plan round2 while inspecting T1 integration contract; this is not an independent audit verdict.

A generic ledger may implement the historical three-second legacy success window. It must not be called directly by production manual routes: when the server records submitted but the browser loses the HTTP reply, an ID-less retry after four seconds would become a new leader and submit twice. Unknown UI outcome is not eliminated by a known server status.

Plan amendment: production routes resolve a durable explicit identity first. Same prepared-row scope replays the same ID; new unowned server-prepared row or new explicit ID supplies distinct intent; marker-free/standalone and CLOSE legacy requests replay their retained fingerprint identity. Deleted rows do not make a known-success replay a fresh order. Timers/cache expiry are never dispatch authority. Add lost-success plus delay/restart tests for OPEN/CLOSE. Generic T1 compatibility capability remains internal and is not called without resolved ID by routes.

Independent scoped plan review required before T2. This uses the remaining plan round3 of the existing cap; no counters reset and no fourth round permitted. Scope: this identity clarification and its interactions with the exclusive prepared-row ownership fix. The complete earlier plan and F1 fix remain reviewed; no T1 source change or production dispatch occurs for this amendment.
