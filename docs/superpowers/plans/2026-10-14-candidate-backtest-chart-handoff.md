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

## Recovered continuation, 2026-10-15 — shipped

User authorized publication and merge after CI. Feature PR #333 is verified MERGED at `2d04dbf34262623b14a0ac6da98f6a9bb20b5bc6`; tested exact head `3e0d1c1e36f0312a73b266c82983f1ff8c9ca35e` has backend/frontend/browser CI all SUCCESS. Backend9105pass/9skip; frontend261suites/5344tests/typecheck/build passed; Playwright smoke passed. One permitted failed-job retry resolved the recorded Google Fonts loader flake on the unchanged head. The merged tree equals the tested head. No application changes after the independent clean audits.

All children #289–294 and parent #288 are closed. Plan1/code2 clean, continuous3, histories/caps preserved. The local inventory mismatch was corrected by test/docs-only commit2625a73f and the full hosted backend run now passes. Separate fresh artifacts preserve original scan evidence and trading inputs; no real orders, arms, alerts or saves.

The documentation-only reconciliation records shipped status, verified SHA and exact-head CI while preserving unrelated state and application audit counters. Current follow-up branch: `board/candidate-backtest-chart-merge-record-6404b638`. Release its claim after reconciliation merges. No feature implementation remains and no user decision is pending.
