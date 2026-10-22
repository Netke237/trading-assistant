# T1 / #480 — save ledger and storage reporting

Fresh implementer: `/root/save371_t1`. Commit `cb27d2ed6fd10e9a3db276d3a29d83ec64a5a325`.

Ticket70% (implementation and required local checks), sizeM, complexity4. Phase20%, sizeL, complexity5: 1/3 build units complete, independent code audit not started.

Behavioral RED: two suites with compiling minimal API stubs, 27 failed /1 passed. Missing ledger status and browser-write reporting caused failures, rather than missing modules. GREEN: both targeted suites33 tests; TypeScript clean; full frontend Jest `--runInBand`307 suites/5841 tests pass (286.745s).

Coverage includes synchronous registration/throw passthrough, all-pending settlement, latest outcome/discard sequence, sticky overlap confirmation, explicit later-save recovery, and browser storage failure/retry. Every four-store × quota/security fixture confirms changed memory, unchanged raw bytes, reported failure, and exact thrown error identity. Frozen key/version/field-set tests plus existing migration coverage preserve persisted data contracts. Caller catches in RiskForm, OverrideInput, and SearchProfileBar retain propagation.

Only eight planned library/store/test files changed. No backend or live provider calls. Optional draft-message argument supports invalid strategy-value reporting. Public API is the nonpersisted `useSettingsSaveStatus` store plus helper functions; subscribe to stable store state, not the fresh array returned by `outstanding()`.

Next: T2 footer/primary channels and drafts, then T3 remaining channels and deferred-server regression. This is build evidence, not an independent audit or shipping approval.
