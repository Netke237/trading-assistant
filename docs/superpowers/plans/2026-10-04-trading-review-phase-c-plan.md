# Trading Review Phase C — Implementation Plan (`TRADING-REVIEW-PHASE-C`)

> **For agentic workers:** this plan is built through `k-ticket-coordinator`. One ticket per task, one fresh
> implementer per ticket, test-first. The coordinator owns `PROJECT_STATE.json`, the tracking issue and the audits.
> Implementers never edit audit fields and never put `round N` in a commit subject.

**Proposal and decisions:** `docs/superpowers/plans/2026-10-04-trading-review-phase-c-proposal.md`.
Kenneth answered on 2026-10-04:

- **D1 scope:** C1, C2, the side items and the C3 harness code. C4 policy waits for the re-measured numbers.
- **D2:** implement `setup_window_bars`.
- **D5:** the R/R loss basis is 100% of premium unless a protective stop order is placed.
- **D6:** of the interim items, only "Stocks After-scan fires on PASS only". The earnings veto window and the bearish auto-arm are **not** in this phase.
- **D3 and D4** take the proposal's defaults:
  - Volume stays raw.
  - WFO evidence floor: ≥ 20 pooled OOS trades and ≥ 3 contributing symbols.

**Spec:** `TRADING_REVIEW.md` 2026-10-04 (Kenneth's local copy, not yet committed). Every mechanism below was re-verified in this repo at `fa84b08`.

**Goal:** after this phase, the app reads price bars on one consistent basis, the tools that produce strategy evidence (WFO, backtest fills, confidence replay) measure net, non-overlapping, DAY-order results, the stock trigger honours its configured setup window, options R/R states the loss a trader can really take, and stock auto-execute fires only on PASS. The phase also adds the read-only harness Kenneth runs on his database to re-measure the review's no-edge findings (H2, H3, M5, M6).

## Global constraints

- **Runtime.**
  - Backend: Python **3.11**. Run `cd backend && .venv/bin/python -m pytest` (on Windows: `.\.venv\Scripts\python.exe -m pytest`).
  - Frontend: `cd frontend && npm run typecheck && npm run test`.
- **TDD.** Write the failing test first, run it, and see it fail for the predicted reason. Then write the code.
- **No threshold changes.** Do not change any score threshold, weight or strategy parameter value. The new keys this plan names are the only exceptions: `trigger.setup_window_bars` gains a reader, `optimization.min_symbols` is new.
- **Numeric golden pins.**
  - A pin that moves because of the task's own mechanism may be re-pinned. Re-pin it **in the same commit**, with a comment `# Re-pinned by TRADING-REVIEW-PHASE-C T<n>: <one-line mechanism>`, and list it in the implementer report under DEVIATIONS.
  - A pin that moves for any other reason is a defect. Stop and report it.
- **YAML comments.** `risk_rules.yaml` is rewritten (comments dropped) by Settings → Risk. New explanations go in code comments or `SCORING_RULES.md`.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Runtime state.** No task writes to a production database. Tests use in-memory SQLite (`sqlite+aiosqlite:///:memory:`), as `tests/test_historical_store_guard.py` does.

## Task graph

| Task | Title | Blocked by | Files (exclusive within the phase unless noted) |
|---|---|---|---|
| T1 | Consistent bar basis in `_read_bars` | — | `backend/app/services/historical_store.py`, `backend/tests/test_historical_store_guard.py` |
| T2 | Bar-derived cache keys carry a basis version | T1 | `backend/app/data/confidence_cache.py`, `backend/app/routers/stock_scan.py` (cache key only), `backend/tests/test_confidence_cache_basis_version.py` |
| T3 | Stale adjustment-factor detection and refresh | T1 | `backend/app/services/historical_store.py`, `backend/app/routers/historical_data.py`, `backend/tests/test_adjustment_refresh.py` |
| T4 | WFO selects and scores on net results | T1 | `backend/app/services/walk_forward.py`, `backend/app/services/strategy_param_optimizer.py`, `scripts/retune_archived_basket.py`, `backend/tests/test_walk_forward.py`, `backend/tests/test_wfo_net_costs.py` |
| T5 | WFO evidence floor pooled across the basket | T4 | `backend/app/services/strategy_param_optimizer.py`, `backend/config/strategy_params.yaml`, `backend/tests/test_wfo_evidence_floor.py` |
| T6 | DAY semantics for backtest entry limits | T1 | `backend/app/services/strategy_backtest.py`, `backend/tests/test_backtest_day_limits.py` |
| T7 | Stock trigger honours `setup_window_bars` | T1 | `backend/app/scoring/stock_scorer.py`, `SCORING_RULES.md`, `backend/tests/test_trigger_setup_window.py` |
| T8 | Confidence replay de-overlapped | T2, T7 | `backend/app/scoring/signal_confidence.py`, `backend/tests/test_confidence_deoverlap.py` |
| T9 | Options R/R at the full-premium loss basis | — | `backend/app/scoring/reward_risk.py`, `backend/app/scoring/trade_plan.py`, `backend/app/routers/scan.py` (alt R/R call only), `frontend/components/organisms/TradeCard/index.tsx`, `frontend/types/domain.ts`, `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx`, tests named in the task |
| T10 | Stocks After-scan auto-execute fires on PASS only | — | `frontend/app/(frame)/screener/step-4-stocks/page.tsx`, its test |
| T11 | Evidence harness: shared loader + bar-basis check + score calibration | T1, T3 | `scripts/evidence/__init__.py`, `scripts/evidence/_bars.py`, `scripts/evidence/bar_basis_check.py`, `scripts/evidence/score_calibration.py`, `backend/tests/test_evidence_harness.py` |
| T12 | Evidence harness: gate persistence + strategy matrix | T4, T6, T11 | `scripts/evidence/gate_persistence.py`, `scripts/evidence/strategy_matrix.py`, `backend/tests/test_evidence_harness.py` (append) |
| T13 | Verify, code audit, PR (coordinator) | all | `docs/superpowers/PROJECT_STATE.json` |

Serialisation:

- T1 and T3 share `historical_store.py`, so they are serial.
- T4 and T5 share `strategy_param_optimizer.py`, so they are serial.
- T11 and T12 share the test file, so they are serial.
- T9 and T10 are disjoint from everything else and may run in parallel worktrees.
- T7 touches `stock_scorer.py`, which T8's replay calls, so T8 waits for T7.

---

## T1 — Consistent bar basis in `_read_bars` (fixes H1)

**Mechanism today.** `historical_store.py:236-245`: `close = raw_close × adj_factor`, while `open/high/low` are raw. A bar fetched before a dividend or split therefore carries a close outside its own `[low, high]`. Every consumer of `get_bars` sees this. The review measured 44.2% of the options window's bars.

**Test first.** In `backend/tests/test_historical_store_guard.py`:

1. Replace `test_read_bars_returns_adjusted_close`. Store `open 98, high 102, low 97, close 100, adj_factor 1.1` and assert that `_read_bars` returns `open 107.8, high 112.2, low 106.7, close 110.0`, each within 1e-6.
2. Add `test_read_bars_basis_invariant`: for adj factors `[0.5, 0.97, 1.0, 1.1, 8.0]` and a bar with `low < open, close < high`, every returned bar satisfies `low ≤ min(open, close)` and `max(open, close) ≤ high`.
3. Keep `test_read_bars_legacy_row_uses_close_directly`, and extend it: with a NULL factor, all four prices are returned raw.
4. Add `test_read_bars_volume_unscaled`: with factor 1.1, volume is returned unchanged (D3).

Run them. Tests 1 and 2 must fail (open/high/low unscaled).

**Code.** In `_read_bars`, compute `adj` once per row and apply `round(x * adj, 6)` to all four prices when `adj is not None`. Update the docstring: "Returns fully adjusted OHLC (each raw price × adj_factor; volume raw)." Nothing else changes.

**Suite.** Run the full backend suite. Any test that fails because it read DB bars through `_read_bars` with a non-1.0 factor may be re-pinned under the global rule. List each one.

**Commit:** `fix(bars): scale open/high/low by adj_factor like close (Phase C T1, review H1)`

## T2 — Bar-derived cache keys carry a basis version

**Mechanism today.**

- `confidence_cache` persists in SQLite with a 7-day TTL (`app/data/confidence_cache.py:14,47-80`). Its key is `SYMBOL|direction|horizon|mult|mode` (`:42`). After T1, and later T7 and T8, a cached confidence computed on mixed bars or the old replay would be served for up to 7 days.
- `stock_scan._BACKTEST_CACHE` is in memory (24h) and is cleared by a restart, but it is keyed without a version.

**Test first.** `backend/tests/test_confidence_cache_basis_version.py`:

1. Assert that `cache_key("AAPL", "Bullish", "Swing", None, None, scoring_mode="stock")` ends with `|b2`.
2. A key written with the old format (no suffix) by a direct `set_cached(old_key, …)` is not returned by `get_cached(cache_key(...))`.
3. The `_BACKTEST_CACHE` key built in `stock_scan.py` (find the key builder near `:635-645`) contains the same `BARS_BASIS_VERSION` token.

**Code.**

- Add `BARS_BASIS_VERSION = "b2"` in `confidence_cache.py`, with a comment naming T1, T7 and T8 as the reasons it last moved, and append `|{BARS_BASIS_VERSION}` to `cache_key`.
- In `stock_scan.py`, add the same token to the backtest cache key.
- Old rows expire naturally. No migration and no delete.

**Commit:** `fix(cache): version bar-derived cache keys so pre-T1 results are not served (Phase C T2)`

## T3 — Stale adjustment-factor detection and refresh

**Mechanism today.** `adj_factor` is the provider's `adjClose/close` **as of the fetch date** (`data/tiingo.py:50`, `data/alpaca.py:109`).

- The nightly Alpaca ingestion re-fetches the whole window and upserts (`ingestion_job.py:108-138`).
- Rows stored by `get_bars`' delta fetch, or gap-filled by Tiingo or yfinance, are never re-fetched.
- So after a later ex-date, the older rows' factors are stale. In a consistent fetch the factor steps only at ex-dates, inside one batch. A stale series shows a factor step between two **consecutive rows from different fetch batches** while the raw close is continuous.

**Test first.** `backend/tests/test_adjustment_refresh.py`, in-memory SQLite:

1. `find_stale_adjustment(symbol, db)` returns `None` for a series stored in one `_store_bars` call (one `fetched_at`), even when it contains a dividend step in `adj_factor`.
2. It returns the earliest stored date when two consecutive rows have **different `fetched_at` dates** and `abs(adj_next / adj_prev − 1) > 1e-4`.
   - Construct it with two `_store_bars` calls with factors 0.98 and 1.0, monkeypatching `_utcnow` so the `fetched_at` values differ.
3. `refresh_adjustments(["SYM"], fetch=fake)` calls `fake(symbol, first_stored_date, last_stored_date)` once for a stale symbol and zero times for a clean one, and upserts the returned bars, so afterwards `find_stale_adjustment` is `None`.
4. Refresh never deletes rows: the row count is the same before and after.
5. `POST /api/historical/refresh-adjustments` with `{"symbols": ["SYM"]}` returns `{"checked": 1, "stale": [...], "refreshed": [...], "failed": [...]}`, using the app test client with the fetch monkeypatched.

**Code** in `historical_store.py`:

- `async def find_stale_adjustment(symbol, db) -> date | None`: one ordered SELECT of `(date, adj_factor, fetched_at)`, skipping NULL factors, comparing consecutive rows.
- `async def refresh_adjustments(symbols, fetch=None) -> dict`:
  - For each stale symbol, re-fetch `[first_stored_date, last_stored_date]` through the same provider order `get_bars` uses (Alpaca → Tiingo → yfinance). Factor the provider chain out of `get_bars` into `_fetch_chain(symbol, start, end)`; `get_bars` behaviour must stay identical (its existing tests must pass unchanged).
  - Store through `_store_bars` (upsert).
  - The `fetch` parameter exists for tests.
  - Log each refreshed symbol.

In `routers/historical_data.py`, add `POST /refresh-adjustments` with a `{symbols: list[str]}` body.

- An empty list means every symbol in `ohlcv_daily`, as `SELECT DISTINCT symbol`.
- It runs inline. It is acceptable for an operator call, and the response says how many symbols were checked.

No UI in this phase. Kenneth calls it once after T1 merges, then runs T11's `bar_basis_check.py`.

**Commit:** `feat(bars): detect and refresh stale adjustment factors across fetch batches (Phase C T3)`

## T4 — WFO selects and scores on net results (fixes M1)

**Mechanism today.**

- `walk_forward.train_fold` (`:237-248`) calls `run_strategy_backtest(...)` without `commission`, which defaults to `0.0` (`strategy_backtest.py:83`), and ranks combos on that gross Sharpe.
- The optimizer then subtracts `apply_costs` (`walk_forward.py:110-122`), which is `(fee+slip)×2` **once per fold-window return** (`strategy_param_optimizer.py:126-131, 153-157`), whatever the number of trades.
- `scripts/retune_archived_basket.py` re-implements the train loop (`ParallelTrainer.__call__`, `evaluate_job` `:84`) and inherits the gross selection.

**Test first.** `backend/tests/test_wfo_net_costs.py`:

1. Monkeypatch `walk_forward.run_strategy_backtest` with a recorder. Assert that `train_fold(...)` passes `commission == fee_pct + slippage_pct` from its `costs` argument.
2. The same for the OOS call in `strategy_param_optimizer._optimize_strategy_sync`.
3. Net cost scales with trades. On a fixture where one combo trades 10× and another 1×, with identical gross per-trade returns, the high-turnover combo's recorded OOS `total_return` is lower by roughly 9 extra round trips. Do not assert the exact figure; assert that the difference is greater than one round trip.
4. In `backend/tests/test_walk_forward.py`, delete `test_apply_costs_reduces_return` together with `apply_costs`. Add a test asserting that `walk_forward` no longer exports `apply_costs`, so it cannot be reintroduced silently.
5. `backend/tests/test_retune_archived_basket.py`: assert that `evaluate_job` passes the same `commission`. Read that file first and extend its existing fixture style.

**Code.**

- `train_fold`: compute `commission = costs.get("fee_pct", 0.001) + costs.get("slippage_pct", 0.001)` and pass it to `run_strategy_backtest`.
- Optimizer:
  - Pass the same commission to the OOS call.
  - Use `res.total_return_pct` directly as the net return for both the IS and OOS windows.
  - Delete both `apply_costs` uses and the function.
  - Rewrite the comment at `:187` ("apply_costs returns net_return…") to say the returns are already net of per-leg commission.
- `retune_archived_basket.py`: pass `commission` in `evaluate_job`, with `costs` taken from the job tuple. That changes the checkpoint key inputs, so the existing `identity` / key logic must already include `costs`. Verify that it does: `key_inputs` has `'costs'`.

**Commit:** `fix(wfo): select and score folds net of per-trade costs (Phase C T4, review M1)`

## T5 — WFO evidence floor pooled across the basket (fixes M2, D4)

**Mechanism today.**

- `oos_metrics["n_trades"] = round(total_n_trades / contributing_symbols)` (`strategy_param_optimizer.py:207-209`).
- `build_proposal` requires `>= min_trades` (`:55`), with `min_trades: 20` from `strategy_params.yaml:35`.
- The best strategy averages about 9.6 per symbol, so no proposal can ever be eligible.

**Test first.** `backend/tests/test_wfo_evidence_floor.py`:

1. `build_proposal(..., oos_metrics={..., "n_trades": 30, "n_symbols": 2}, min_trades=20, min_symbols=3, ...)["eligible"] is False`.
2. `n_trades 30, n_symbols 3` → eligible, given consistency ≥ min.
3. `n_trades 19, n_symbols 5` → not eligible.
4. `_optimize_strategy_sync` reports `oos_metrics["n_trades"]` as the **pooled sum** and `oos_metrics["n_trades_per_symbol"]` as the old average. Use a fixture with 3 symbols × 4 OOS trades: sum 12, per-symbol 4.
5. `strategy_params.yaml` `optimization.min_symbols` is read, and defaults to 3 when absent.

**Code.**

- Pooled `n_trades`.
- Add `n_trades_per_symbol` and `n_symbols` to `oos_metrics`.
- `build_proposal(..., min_symbols: int = 3)`; eligibility also requires `n_symbols >= min_symbols`.
- Thread `min_symbols` from config through `run_optimization` and the retune script's `_optimize_strategy_sync` call (`scripts/retune_archived_basket.py:304`).
- YAML: `optimization.min_symbols: 3`.

Check the frontend for `oos_metrics.n_trades` (Settings → Strategy Tuning) and make sure its label still reads correctly. If it says "per symbol", change it to the pooled wording. If the tuning UI is outside this task's files, report it under NOTICED.

**Commit:** `fix(wfo): pool the OOS trade floor across the basket and require 3 symbols (Phase C T5, review M2)`

## T6 — DAY semantics for backtest entry limits (fixes M3)

**Mechanism today.**

- `strategy_backtest.py:158-162` places `buy/sell(limit=…, sl, tp)` when flat and a signal fires.
- `backtesting` 0.6.6 keeps an unfilled limit order alive until it fills. With `exclusive_orders=True` it is cancelled only when a **new** order is placed (`backtesting.py` `_Broker.new_order`: non-contingent orders are cancelled).
- So a limit from bar t can fill on bar t+5 after the signal is stale. Live orders are DAY.

**Test first.** `backend/tests/test_backtest_day_limits.py`:

1. Monkeypatch the strategy function for a synthetic strategy name. The pattern is in `tests/test_strategy_backtest.py`; read it first.
   - The fixture's signal fires once on bar 100 with `entry_price` 2% below the close, and never again.
   - Bars 101-102 stay above the limit; bar 103 trades through it.
   - Assert `n_trades == 0` after the fix. Today the result is 1.
2. When bar 101 touches the limit, the entry fills (`n_trades == 1`).
3. The contingent SL and TP of an open trade are not cancelled. In a fixture where the entry fills and the target is hit 5 bars later, the trade closes at the target.

**Code.** At the top of `_Strategy.next`, before the warm-up and entry checks, cancel every pending order that is not contingent:

```python
for o in list(self.orders):
    if not o.is_contingent:
        o.cancel()
```

A one-line comment explains that live entries are DAY orders, so a limit lives for exactly the bar after its signal. `next()` runs after bar t closes, the order is tried on bar t+1, and at `next()` for t+1 it is cancelled if unfilled.

**Commit:** `fix(backtest): entry limits live one bar like live DAY orders (Phase C T6, review M3)`

## T7 — Stock trigger honours `setup_window_bars` (fixes M4, D2)

**Mechanism today.**

- `_rule_trigger` (`stock_scorer.py:731-845`) counts MACD, RSI and stochastic events only when they happen **on the last bar**: `hist[-2] < 0 <= hist[-1]`, `rsi[-2] < floor <= rsi[-1]`, the stoch cross on `[-2]→[-1]`.
- `trigger.setup_window_bars` (8 / 10 / 5 per horizon, `scoring_rules.yaml:105,264,375`) is never read.

**Semantics (decided here; the plan audit checks it).** With window `W = tc.get("setup_window_bars", 1)`:

- **Bullish.**
  - `macd_pass` if a cross-up `hist[k-1] < 0 <= hist[k]` happened for some `k` in the last `W` bars **and** `hist[-1] >= 0` still holds.
  - `rsi_pass` if a floor cross `rsi[k-1] < floor <= rsi[k]` happened in the window **and** `rsi[-1] >= floor`.
  - `stoch_pass` if the oversold cross condition held at some `k` in the window **and** `stoch_k[-1] > stoch_d[-1]`.
- **Bearish** mirrors this: a cross-down within the window, with the state still holding.
- `macd_histogram_rising`, when true, applies at the event bar `k`, as today it applies at the last bar.
- The RSI divergence branch is unchanged.
- `W = 1` reproduces today's results exactly.

**Test first.** `backend/tests/test_trigger_setup_window.py`:

1. With `W=1` on every existing trigger fixture in `tests/test_stock_scorer*.py`, the results equal today's. Parametrize over `cfg` copies with `setup_window_bars: 1`.
2. A MACD cross-up 4 bars ago with the histogram still ≥ 0 → `macd_pass` with `W=8`, and not with `W=1`.
3. A cross-up 4 bars ago with the histogram back below 0 now → not `macd_pass` for any `W`.
4. A cross 9 bars ago → not counted with `W=8`.
5. The same three shapes for RSI and stochastic, and the bearish mirror of test 2.

**Code.** A helper `_crossed_within(series_prev_cur_predicate, n, W)` or three small loops. The window is bounded by the series length. Keep `detail` keys unchanged, and add `"setup_window_bars": W` to `detail`. Update `SCORING_RULES.md` trigger section, one line: "`setup_window_bars`: a momentum event counts if it occurred within the last N bars and its state still holds."

**Suite.** Scores move on fixtures where an event happened 2 to W bars ago. Re-pin those under the global rule and list them. This also moves `signal_confidence` replays (T8 runs after T7).

**Commit:** `feat(scorer): count momentum events within setup_window_bars (Phase C T7, review M4)`

## T8 — Confidence replay de-overlapped (Phase-B #11)

**Mechanism today.** `compute_confidence` (`signal_confidence.py:264-285`) scores every bar `i`. Consecutive PASS bars share most of the same `n_days` forward window, so one move is counted up to `n_days` times and `decisive` overstates the sample.

**Test first.** `backend/tests/test_confidence_deoverlap.py`:

1. Monkeypatch `score_stock` to return PASS on every bar, with `n_days = 10` and 100 replay bars after warm-up. The number of `evaluate_fire` calls is `ceil(100 / 10)` (non-overlapping), not 100.
2. With PASS only on bars `{70, 72, 85}` and `n_days = 10`, fires are evaluated at 70 and 85, and 72 is skipped.
3. `aggregate` is unchanged. Re-run the existing `tests/test_signal_confidence*.py`; any count-based pins that move are re-pinned under the global rule.

**Code.** In the loop, keep `next_allowed = warmup`. Skip `i < next_allowed`. After a PASS fire at `i`, set `next_allowed = i + n_days`. The comment explains that each fire's forward window `bars[i+1 : i+1+n_days]` must not overlap the next. Scoring is skipped for `i < next_allowed`, which also makes the replay faster.

**Commit:** `fix(confidence): replay fires on non-overlapping forward windows (Phase C T8)`

## T9 — Options R/R at the full-premium loss basis (fixes M7, D5)

**Mechanism today.**

- `estimate_rr` and `estimate_targets` (`reward_risk.py:112-168, 171-370`) divide reward by `resolved_risk_dollars` = `premium × premium_stop_pct` (0.60), or the smaller captured stock-stop loss (`:379-387`).
- No protective option order is ever placed. The premium stop is an alert level (`services/premium_stop.py`), and sizing assumes the whole premium can be lost (Phase A D5).
- The card's R/R therefore overstates reward per unit of real risk by ≥ 1/0.6.

**Semantics.**

- `estimate_rr(..., protective_stop_order: bool = False)` and `estimate_targets(..., protective_stop_order: bool = False)`.
- When False, which is every caller today:
  - `risk = current_premium` (rounded as today when a captured stock risk exists).
  - `RrResult.risk_basis = "full_premium"`.
- When True, today's `resolved_risk_dollars` and `premium_stop` / `stock_stop` basis apply unchanged.
- `TradePlan.premium_stop`, the dollar alert level, is **unchanged**.
- `resolved_risk_dollars` itself is unchanged; it is still used when True.

**Test first.**

1. `backend/tests/test_rr_full_premium_basis.py`:
   - For a fixed Heston-free input with a premium of 2.00, `estimate_rr(...)` returns `rr_ratio == round((exit − 2.00) / 2.00, 2)` and `risk_basis == "full_premium"`.
   - With `protective_stop_order=True`, the result equals today's value: compute the expected value in the test from `resolved_risk_dollars`.
2. The same pair for `estimate_targets(...)[i].rrContribution`.
3. `build_trade_plan` (`trade_plan.py`) passes no flag, so its `rr_ratio` uses the full premium and `premium_stop` is still `premium × 0.60`.
4. Frontend, `TradeCard` test (find the existing test file for `TradeCard`): when a target is edited, `rrContribution` uses `entryLimit` as the risk basis, not `premiumStop`. Today `index.tsx:3351` passes `premiumStop`.
5. Frontend, the step-7 context-rail checklist row: with `rrRiskBasis: 'full_premium'`, the detail text says "risking the full premium (no protective stop order)".

**Code.**

- Backend:
  - Add the flag.
  - `RrResult.risk_basis` Literal gains `"full_premium"`.
  - `trade_plan.rr_risk_basis` carries it.
  - The `scan.py:1371` alternative-contract call needs no change, because the default applies.
  - `routers/contracts.py:1128,1172` use `estimate_rr` only for `estimated_exit_premium`. Confirm that by reading the code, and leave them unchanged. If either reads `rr_ratio`, stop and report a plan defect.
- Frontend:
  - `types/domain.ts:666` union gains `'full_premium'`.
  - The `TradeCard` edited-target path divides by `entryLimit`.
  - Update the comment at `index.tsx:129-131` accordingly.
  - The step-7 rail text gains the third branch.
- The schema for `rrRiskBasis` in `backend/app/schemas` (find it with `grep -n rrRiskBasis backend/app/schemas`) gains the literal.

**Consequence, recorded for Kenneth and not a defect.** Every options R/R drops by a factor of about 0.6 or more, so the Step-7 checklist row (`≥2.0 PASS / ≥1.5 CAUTION`) will show more CAUTION and REJECT. Its thresholds are **not** changed in this phase. That is a C4 decision.

**Commit:** `fix(rr): options R/R risks the full premium unless a protective stop order exists (Phase C T9, review M7)`

## T10 — Stocks After-scan auto-execute fires on PASS only (fixes M8, D6)

**Mechanism today.**

- `step-4-stocks/page.tsx:244-263` adds a paper position for **every** returned candidate whose symbol is armed `after_scan`, whatever `c.stock_status` says.
- The arm label promises "fire when next scan PASS" (`StockAutoTradeArm/index.tsx:12`).
- Candidates have all passed the backtest gate (`:162-167`), but `stock_status` can be CAUTION.

**Test first.** In the Step-4 stocks page test (find it under `frontend/app/(frame)/screener/step-4-stocks/__tests__/`; create `afterScanPassOnly.test.tsx` there if none covers `onRun`):

1. The scan returns `AAPL` (`stock_status: 'PASS'`) and `MSFT` (`'CAUTION'`), both armed after-scan. `addPosition` is called once, for AAPL.
2. A notice lists `MSFT` as "not fired: CAUTION".

**Code.** Add `if (c.stock_status !== 'PASS') { skipped.push(\`${c.symbol}: ${c.stock_status}\`); continue; }` inside the armed branch, and add a `noticeParts` entry `Not fired (not PASS): …`.

**Commit:** `fix(stocks): after-scan auto-execute fires on PASS only (Phase C T10, review M8)`

## T11 — Evidence harness, part 1: loader, bar-basis check, score calibration

**Purpose.** These are read-only tools Kenneth runs on his Postgres (`ohlcv_daily`) after merge, to re-measure H1 and H2 on what the app actually reads. Cloud containers have no data.

**Shared rules for every harness script.**

- Bars come **only** from `historical_store._read_bars` through `app.database.AsyncSessionLocal`. That is a SELECT only. Never call `get_bars`, which can fetch and write.
- Each script prints a markdown report to stdout and, with `--out <path>`, writes it there.
- The report header records the git commit, a UTC timestamp, the symbols, the date range, `BARS_BASIS_VERSION` and the cost model.
- Pure computation lives in functions that take bar lists, so it can be unit-tested without a DB.

**Files and contents.**

- `scripts/evidence/_bars.py`: `async load_bars(symbols, start, end) -> dict[str, list[dict]]`, plus `report_header(...)`.
- `scripts/evidence/bar_basis_check.py`:
  - Per symbol, the share of bars with `close ∉ [low, high]` or `open ∉ [low, high]`.
  - Per symbol, `find_stale_adjustment` (T3).
  - Close-to-close jumps above 40%.
  - Pure core: `basis_violations(bars) -> dict`, `big_jumps(bars, threshold) -> list`.
- `scripts/evidence/score_calibration.py`:
  - For each symbol, horizon (CLI, default Swing) and direction, replay `score_stock` over bars, as `compute_confidence` does.
  - For every bar, the status bucket (PASS / CAUTION / REJECT).
  - The forward outcome in R, using `evaluate_fire`'s barriers (horizon `atr_mult_target/stop`, `n_days`): win = +target/stop R, loss = −1R, flat = the close-to-close move ÷ stop distance at the window end.
  - **Distinct setups only**, using the same non-overlap rule as T8, applied per bucket.
  - Output per bucket: n, mean R, bootstrap 95% CI (2,000 resamples, fixed seed 7), plus the all-bars base rate.
  - Pure core: `calibrate(bars_by_symbol, horizon, direction, scorer=score_stock) -> list[BucketStat]`.

**Test first.** `backend/tests/test_evidence_harness.py`, which adds `scripts/` to `sys.path` as `tests/test_retune_archived_basket.py` already does (read it):

1. `basis_violations` on 3 hand-made bars (one violation) returns `{"n": 3, "close_outside": 1, ...}`.
2. `big_jumps` flags a ×7.76 step and ignores a 3% move.
3. `calibrate` with a stub scorer (PASS on even bars, REJECT on odd bars) and a monotonic up-trend fixture returns a PASS bucket with mean R > 0, counts that respect non-overlap, and the same output on two runs (fixed seed).
4. No harness module imports `get_bars`. Assert this on the source text.

**Commit:** `feat(evidence): read-only bar-basis and score-calibration harness (Phase C T11)`

## T12 — Evidence harness, part 2: gate persistence and strategy matrix

**Files and contents.**

- `scripts/evidence/gate_persistence.py` (H3):
  - Per strategy × direction, split each symbol's history at its midpoint.
  - Run `run_strategy_backtest(commission=fee+slip)` on each half, with `entry_start` = the half's start and a 260-bar warm-up prefix as in WFO.
  - Across symbols with ≥ 5 trades in both halves, compute Spearman ρ of per-symbol expectancy between halves, with the noise band `±1.96/sqrt(n−1)`.
  - Pure core: `spearman(xs, ys)`, `persistence(results_a, results_b, min_trades)`.
- `scripts/evidence/strategy_matrix.py` (M5, M6):
  - Strategy × direction × symbol over the full stored history, net of costs, with DAY fills (T6).
  - Pooled n, pooled mean trade return, the share of symbols reaching `_MIN_TRADES`, and a bootstrap 95% CI on the pooled mean.
  - Pure core: `pool(results) -> MatrixRow`.

**Test first** (append to `backend/tests/test_evidence_harness.py`):

1. `spearman` equals 1.0 on identical ranks and −1.0 on reversed ranks, and handles ties by average rank.
2. `persistence` excludes symbols below `min_trades` in either half.
3. `pool` of two stub results computes the trade-weighted mean.
4. Both scripts pass `commission` to `run_strategy_backtest`. Check this with a recorder.

**Commit:** `feat(evidence): gate-persistence and strategy-matrix harness (Phase C T12)`

## T13 — Verify, code audit, PR (coordinator only)

1. Full backend suite (Python 3.11), frontend typecheck and Jest. Compare with the baseline recorded in the tracking issue.
2. Code audit loop on `origin/main..claude/keen-pascal-i4zd1f`, with a fresh gate auditor per round and a cap of 3.
3. Update `PROJECT_STATE.json` phase `TRADING-REVIEW-PHASE-C`:
   - The rounds.
   - `TRADING-REVIEW-RETUNE-EVIDENCE` gets the note "superseded: computed on mixed-basis bars and gross WFO selection".
   - A `pending_kenneth` entry: "after merge, run `POST /api/historical/refresh-adjustments`, then `scripts/evidence/*` on the local DB, then decide C4".
4. Open the PR (`Closes #<tracker>`). Never merge.

**Manual checks for Kenneth** (no DB or browser in the container):

- After merge: `bar_basis_check.py` shows close-outside-range ≈ 0%, where the review measured 44.2%.
- A Step-7 card shows `risk_basis` "full premium".
- An after-scan arm on a CAUTION stock does not fire.
