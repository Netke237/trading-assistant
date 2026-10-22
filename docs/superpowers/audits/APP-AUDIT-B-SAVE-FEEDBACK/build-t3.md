# T3 / #482 — remaining channels and deferred commits

Fresh implementer `/root/save371_t3`. Commit `c6863ddd7e8d6a7a9d2c4f625bc9f4c7000f9189`. T3 and phase70% (all3 build units implemented and required local checks pass), ticketM/5, phaseL/5. Independent integrated code audit pending; no merge readiness claimed.

Genuine behavioral RED before fixes:9 failures for retention/deferred orders/history/notifications/four schedules; separate11 failures for brokers/storage/discard/per-field schedule failures and stale concurrent fields;6 failures for unknown-baseline edit/revert. Final focused64 tests in2 suites pass (46 new T3 plus18 T2). TypeScript and whitespace checks pass. Full frontend309 suites/5905 tests pass,167.71s, with `NODE_OPTIONS=--max-old-space-size=4096 npm run test -- --runInBand`.

Default2GB Node run exhausted heap after215 passing suites (exit134; no assertion failures reported). Unchanged-source4GB rerun passed; no project/CI configuration change. This resource adjustment qualifies the local evidence and does not replace exact-head native CI.

Coverage includes all five brokers with both quota/security exceptions, no POST when pre-request storage throws, explicit remote recovery after local retry, failure/finally behavior, late-response discarded draft; notifications non-OK; four schedule forms; per-field schedule receipts; both retention deferred-commit orders and later explicit re-save; unknown server baseline edits/reverts remain dirty until confirmation. Schedule readback waits for that entry's pending writes, preserving intended label/toggle for stale-value comparison; request payloads/submission order unchanged.

Only page.tsx and RemainingSaveFeedback.test.tsx changed. Synthetic/jsdom/mocked API only, no live provider/broker/notification/jobs. Approved plan SHA256 unchanged. Next: merge latest main, rerun required integrated checks, fresh independent code audit (cap3).
