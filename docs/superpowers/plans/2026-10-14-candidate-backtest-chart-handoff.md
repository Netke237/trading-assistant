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
