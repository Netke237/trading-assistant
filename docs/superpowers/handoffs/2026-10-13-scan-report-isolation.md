# Scan report isolation handoff

Tracking issue #236; branch `board/scan-report-isolation-b6c806b9`.

Explicit user instruction resumed this phase after usage interruption. Options
#233 retains its independent live owner; do not take or overwrite that work.

## Built and preserved

- LOG01 #237: `759bd364`, additive durable storage/API/migration, closed.
- LOG02 #238: `fbb1d241`, category-local lifecycle and safe actual observations,
  manual/scheduled routing, cancellation/failure/restart outcomes, closed.
- LOG03 #239: `75588a08`, five-category durable inspector, frozen inputs,
  previous evidence, unavailable diagnostics, legacy retrieval, v19 preserving
  client migration. Uses existing mode/navigation location and broker handlers.
- Test-only full-suite contract repairs `de5ac3da` and `aa4c51dc`.

## Verification and gates

Prior frozen plan round1 clean. Lifecycle elaboration round2 found G1 (service
key validation could not validate free-text values). Revised plan adapters use
allowlisted typed projections, safe reasons and explicit unavailable fields.
Exact lifecycle plan SHA256
`973811c4d045b267d607b1961b235bc36b739cc0d6160e378a181cea495390a2`.
Fresh /root/resume_plan_round3 reviewed fix and interactions: zero findings,
plan stage clean at round3. Prior usage-failed invocation did not run an audit.
Counters preserved. Separate code stage starts next at round4 (code1 of max3).

Python3.11.16 backend full7961pass9skip2fail, both failing test assumptions
subsequently fixed; whole affected modules727pass. Focused lifecycle/routes14,
report/broker51, scan/scheduler55 passed. Full backend not rerun after test-only
repairs; exact-head CI still required. Frontend typecheck,22suites200tests and
final changed4suites23tests passed. Full frontend suite currently running.

Effective configuration observations remain incomplete where independently
consulted source is unavailable; PB/Fib stage/rejection diagnostics unavailable.
No fabricated counters. This limitation is explicit in API and inspector.
No live PostgreSQL or browser end-to-end restart probe; storage/API/recovery
and remount identity behavior covered by meaningful tests.

## Next

Finish full frontend suite and fresh integrated independent code audit against
origin/main and the frozen application head. Preserve stage caps and review only
fixes/interactions on later rounds. Phase built but audit_clean false, unfinished,
not merge-ready. Prepare PR only after gates; follow existing merge conditions.

## Completed verification

Frontend full237suites5018tests passed; productionbuild/typecheck passed.
Fresh independent code round1 (continuous4) zero gate findings on9034d6e;
exact evidence in audits/2026-10-13-scan-report-code-round1.md. Phasebuilt/audit
clean/unmerged. PR/exact-head CI and normal merge conditions next.
