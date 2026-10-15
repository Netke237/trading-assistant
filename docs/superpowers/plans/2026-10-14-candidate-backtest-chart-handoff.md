# Candidate backtest chart — planning handoff

Parent: [#288](https://github.com/Netke237/trading-assistant/issues/288). Native blocker: #235.

Approved plan: `2026-10-14-candidate-backtest-chart-plan.md` at `72dc64f6d5752033e48e6553d1de25308fc70760`. Independent `/root/backtest_chart_plan_r1`: one plan round, two source passes, zero numeric/persistence gate findings. Code audit not started; implementation not started.

| Unit | Ticket | Native blocker |
| --- | --- | --- |
| BT-01 | [#289](https://github.com/Netke237/trading-assistant/issues/289) | #235 |
| BT-02 | [#290](https://github.com/Netke237/trading-assistant/issues/290) | #289 |
| BT-03 | [#291](https://github.com/Netke237/trading-assistant/issues/291) | #290 |
| BT-04 | [#292](https://github.com/Netke237/trading-assistant/issues/292) | #291 |
| BT-05 | [#293](https://github.com/Netke237/trading-assistant/issues/293) | #292 |
| BT-06 | [#294](https://github.com/Netke237/trading-assistant/issues/294) | #293 |

Resume from the pushed board branch through the standard board claim/takeover protocol after #235 closes. Never substitute a rerun for original evidence. No change to prior phase audit counters or #150 / PR #224. Board Queue insertion remains user-owned; an agent may only comment.

## Implementation continuation

Branch: `board/candidate-backtest-chart-40fc1ac9`. User requested implementation after #235 completed. Merged current main into preserved planning branch; clean plan round 1 is unchanged, code audit not started.

BT-01 implemented at `a1f70820`: separately typed detached evidence, optional same-invocation collector, actual equity/fills, full input and evaluation candles, open positions and explicit failure states. Aggregate and legacy date-only APIs preserved. RED: 15 expected missing-API failures; focused regressions 70 passed and latest detailed suite 19 passed. Frontend 255 suites/5273 tests and typecheck passed. Full Python3.11 backend verified in two process shards: scan endpoint module 48 passed; every other module 8829 passed/9 skipped. Combined 8877 passed/9 skipped. Initial run had an ambient Telegram configuration failure; that module passed with task-local Telegram variables empty. A scan test was slow rather than proven hung; its complete module passed in334seconds. Final code audit and final integrated validation remain required.

BT-02 next: immutable artifacts, exact candidate linkage, detailed cache and explicit availability states. No application code from BT-02 exists yet.

BT-02 implemented at `d9b5f9f4`: immutable SQLAlchemy artifacts and migration, exact ID/symbol read API, expiry tombstones, scan/report linkage and full-input sidecar cache. Candidate availability status distinguishes missing original evidence and capture/storage failures. Optional cache/persistence errors preserve candidate numeric/trading fields. Engine numeric source-time correction `7a2e4af1` preserves legacy engine summaries while mapping fills/equity to original source bar times; detail contract v2. RED14 timestamp cases; focused110 passed including44 details. BT-02 combined post-correction157 tests and typecheck passed. Frontend255 suites/5273 tests passed. Pre-correction full backend:8903 passed/9 skipped and one explicit-signature test spy failure; that spy was updated for the additive optional collector and its complete module passed in the combined157. SQLite migration upgrade/downgrade passed. Final integrated exact-head full validation and independent audit remain pending.

Next BT-03: typed candidate chart navigation and stale-safe original artifact loading.

## Recovered continuation, 2026-10-15 — final local checkpoint

User requested recovery, claim and continuation. Recovered pushed checkpoint `f3441005` (BT-01–03), continued on `board/candidate-backtest-chart-3c95ac9e`; claim verified and parent branch line updated. Fresh BT-04 implementer committed `30ea2236`, current main `64b9d53f` merged at `b3c29593` (ledger-only conflict), fresh BT-05 implementer committed `6193551f`. Integrated verification committed `bc812079`. Full backend found one new-field inventory mismatch; fresh test/docs-only fix `2625a73f`, preserved production code. Validation record: `2026-10-15-candidate-backtest-chart-validation.md`.

Independent audit: plan1/code2 clean, total3 continuous rounds, caps preserved. Whole feature `64b9d53f..bc812079` clean; shrinking follow-up `bc812079..413e1e4a` clean. No application changes after whole-feature review. Frontend5344, typecheck, production build, browser10 pass. Full backend9084pass9skip1inventoryfailure; all4 affected suites84pass after inventory correction; no full rerun after test/documentation-only correction. Independent follow-up22tests,220invalid-rejected,12finite-accepted.

LOCAL ONLY beyond recovered checkpoint. Automatic approval review rejected new-code GitHub publication and child-ticket closure pending explicit user authorization. #292–294 remain remotely open; no feature PR, hosted CI or merge attempted. Status built, independently audit-clean, not shipped. Keep claim while awaiting prompt reply; recheck/renew before any external write. The continuation branch on origin contains only recovered f3441005. Another environment needs the local continuation bundle or explicit authorization to publish these commits.

Next: obtain explicit publication authorization for this concrete reviewed change, push branch, reconcile completed child tickets, open PR, attach it to the task, and run exact-head CI. Merge only when the repository's own-PR/audit/CI conditions and the user's authorized scope hold. Preserve code audit counts; only documentation verdict/validation records follow the clean scope. No open implementation decision and no real orders/arms/alerts/saves.
