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
| T2 | Bar-derived cache keys carry a basis version | T1, T7 | `backend/app/data/confidence_cache.py`, `backend/app/routers/stock_scan.py` (cache key only), `backend/tests/test_confidence_cache_basis_version.py` |
| T3 | Stale adjustment-factor detection and refresh | T1 | `backend/app/services/historical_store.py`, `backend/app/routers/historical_data.py`, `backend/tests/test_adjustment_refresh.py` |
| T4 | WFO selects and scores on net results | T1 | `backend/app/services/walk_forward.py`, `backend/app/services/strategy_param_optimizer.py`, `scripts/retune_archived_basket.py`, `backend/tests/test_walk_forward.py`, `backend/tests/test_wfo_net_costs.py` |
| T5 | WFO evidence floor pooled across the basket | T4 | `backend/app/services/strategy_param_optimizer.py`, `backend/config/strategy_params.yaml`, `backend/tests/test_wfo_evidence_floor.py` |
| T6 | DAY semantics for backtest entry limits | T1 | `backend/app/services/strategy_backtest.py`, `backend/tests/test_backtest_day_limits.py` |
| T7 | Stock trigger honours `setup_window_bars` | T1 | `backend/app/scoring/stock_scorer.py`, `SCORING_RULES.md`, `backend/tests/test_trigger_setup_window.py` |
| T8 | **Withdrawn** (plan round 1, F1). The live de-overlap moves to C4; the harness measures it (T11) | — | — |
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
- T2 waits for T7 so the single version bump covers both basis changes that move cached confidence: T1 bars and T7 trigger.

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

- `confidence_cache` persists in SQLite with a 7-day TTL (`app/data/confidence_cache.py:14,47-80`). Its key is `SYMBOL|direction|horizon|mult|mode` (`:42`). After T1 and T7, a cached confidence computed on mixed bars or the old replay would be served for up to 7 days.
- `stock_scan._BACKTEST_CACHE` is in memory (24h) and is cleared by a restart, but it is keyed without a version.

**Test first.** `backend/tests/test_confidence_cache_basis_version.py`:

1. Assert that `cache_key("AAPL", "Bullish", "Swing", None, None, scoring_mode="stock")` ends with `|b2`.
2. A key written with the old format (no suffix) by a direct `set_cached(old_key, …)` is not returned by `get_cached(cache_key(...))`.
3. The `_BACKTEST_CACHE` key built in `stock_scan.py` (find the key builder near `:635-645`) contains the same `BARS_BASIS_VERSION` token.

**Code.**

- Add `BARS_BASIS_VERSION = "b2"` in `confidence_cache.py`, with a comment naming T1 and T7 as the reasons it last moved, and append `|{BARS_BASIS_VERSION}` to `cache_key`.
- In `stock_scan.py`, add the same token to the backtest cache key.
- Old rows expire naturally. No migration and no delete.

**Commit:** `fix(cache): version bar-derived cache keys so pre-T1 results are not served (Phase C T2)`

## T3 — Stale adjustment-factor detection and refresh

**Mechanism today.** `adj_factor` is the provider's `adjClose/close` **as of the fetch date** (`data/tiingo.py:50`, `data/alpaca.py:109`).

- The nightly Alpaca ingestion re-fetches the whole window for every symbol Alpaca returns and upserts (`ingestion_job.py:108-138`), so those rows are refreshed nightly.
- Symbols Alpaca does not return are gap-filled through `get_bars`, which fetches only `last+1 .. end` (`historical_store.py:375-379`).
- So rows stored in **earlier batches** keep the factor they had when they were fetched.

**There is no single stale signature.** Plan round 1, F3: a "factor step at a batch boundary" misses the commonest case. Daily one-row batches each fetch a factor of ≈ 1.0, and a split or ex-date arriving as the first row of a new batch leaves no factor step anywhere. Detection therefore flags a symbol if **any** of these holds:

- **(a) Unexplained jump.** The **adjusted** close (`raw × factor`, or raw when the factor is NULL) moves more than `_JUMP_THRESHOLD = 0.40` close-to-close. A consistent series absorbs a split into the factor, so a 40% adjusted move left in the series is either a real crash or a missed split. Re-fetching a real crash is harmless.
- **(b) Fetched before a later corporate action.** A row's `fetched_at` date is earlier than the date of a later row with `div_cash ≠ 0` or `split_factor ≠ 1` (Tiingo rows carry both).
- **(c) Batch-boundary factor step.** Two consecutive rows have different `fetched_at` dates and `abs(adj_next / adj_prev − 1) > 1e-4`.
- **(d) Mixed basis in one series.** NULL-factor rows sit next to non-NULL rows, or more than one `source` appears, for example yfinance's pre-adjusted rows next to raw Alpaca/Tiingo rows.

**Residual, recorded rather than fixed.** A dividend-only staleness on a yfinance-only or Alpaca-sourced series between nightly refreshes has no detectable signature, and its effect is the size of one dividend (usually < 1%). T11's report lists it.

**Test first.** `backend/tests/test_adjustment_refresh.py`, in-memory SQLite. Use `_store_bars` once per batch and monkeypatch `_utcnow` so `fetched_at` differs between batches.

1. A series stored in one batch, containing a dividend step in `adj_factor`, is **not** flagged.
2. **(a)** Daily one-row batches, all with factor 1.0, plus a raw ×8 jump on the first row of a later batch (a GE 2021-08-02 style reverse split) are flagged.
3. **(b)** Daily one-row batches, all with factor 1.0, followed by a later Tiingo row with `div_cash 0.5`: every earlier row is flagged, and the earliest flagged date is the first row.
4. **(c)** Two batches with factors 0.98 and 1.0 at the boundary and a continuous raw close are flagged.
5. **(d)** NULL-factor rows followed by factored rows are flagged; a series with sources `yfinance` and `alpaca` is flagged.
6. A real 15% move in one batch with factor 1.0 is not flagged.
7. `refresh_adjustments(["SYM"], fetch=fake)` calls `fake(symbol, first_stored_date, last_stored_date)` once for a flagged symbol and zero times for a clean one, and upserts the result. Afterwards, with the fake returning one consistent batch, the symbol is not flagged.
8. Refresh never deletes rows: the row count is the same before and after.
9. `POST /api/historical/refresh-adjustments` with `{"symbols": ["SYM"]}` returns `{"checked": 1, "stale": [{"symbol", "reasons", "earliest"}], "refreshed": [...], "failed": [...]}`, using the app test client with the fetch monkeypatched.

**Code** in `historical_store.py`:

- `async def find_stale_adjustment(symbol, db) -> StaleReport | None`: one ordered SELECT of `(date, close, adj_factor, split_factor, div_cash, source, fetched_at)`, then a pure `stale_reasons(rows) -> StaleReport | None`. `StaleReport` has `reasons: list[str]` (a subset of `jump`, `pre_action_fetch`, `batch_step`, `mixed_basis`) and `earliest: date`. The pure function carries the rules, so T11 reuses it.
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

**Suite.** Scores move on fixtures where an event happened 2 to W bars ago. Re-pin those under the global rule and list them. This also moves `signal_confidence` replays (the live confidence gate re-scores through `score_stock`), which is why T2's cache-version bump waits for T7.

**Commit:** `feat(scorer): count momentum events within setup_window_bars (Phase C T7, review M4)`

## T8 — Withdrawn (plan round 1, F1)

De-overlapping the **live** confidence replay is **not** done in this phase. `aggregate` returns `confidence=None` when `decisive < min_samples` (`signal_confidence.py:150-151`), and `status_cap(None)` returns **PASS** (`:175-179`). The stock scan's REJECT drop and CAUTION cap both skip a None (`routers/stock_scan.py:1326-1338`).

- `min_samples: 20` was calibrated on overlapping counts.
- On the options window (~306 bars) a Swing replay yields at most ~23 non-overlapping fires, and a Position replay at most ~5.
- So de-overlap would turn the gate off and promote REJECT/CAUTION candidates to PASS.

Fixing it needs either a de-overlapped `min_samples` (a threshold, so Kenneth's decision) or a None → CAUTION fail-closed policy. Both are C4 decisions. T11's calibration harness reports the non-overlapping sample counts per horizon, so Kenneth decides on numbers.

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
4. Frontend, `TradeCard` tests (find the existing test files for `TradeCard`). Plan round 1, F2: `index.tsx:3351` serves **every** row without an `authoritativeRr`, not only edited ones. `authoritativeRr` is passed only when `hasCapturedStockRisk && !rrStale` and the entry limit and premium stop are unedited (`:3221`). Otherwise the row divides by `ladderRisk` (`:1853`), which is `overlay.premiumStop` or `min(premiumStop, capturedStockRisk)`. Tests, all on the full-premium basis (risk leg = `overlay.entryLimit`):
   - (i) an **un-edited** row on a card with **no** `stockStopLoss`: premium 2.00, estimate 3.50 → 0.8 (today 1.3);
   - (ii) an edited target row;
   - (iii) a card with a captured stock risk after the entry limit is edited;
   - (iv) `rrStale` true.
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
  - `TradeCard`: `ladderRisk` becomes `overlay.entryLimit` (the full premium at the overlay's own entry). It no longer reads `premiumStop` or `capturedStockRisk` for R/R. `authoritativeRr` passes the backend's `rrContribution` only while the entry limit is unedited. The stock-stop conditions are no longer relevant because the backend no longer uses that basis.
  - The `premiumStop` **field** itself (the editable alert level) is unchanged.
  - Update the comment at `index.tsx:129-131`, the comment at `:3214-3218`, and the caption at `:3202-3204`, which becomes: "R/R risk: full premium (no protective stop order)." Keep the `rrStale` caption only if `rrStale` still changes anything; it does not for R/R, so remove that branch from the caption only.
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
  - Per symbol, T3's pure `stale_reasons(rows)` on the full row set from a read-only SELECT. It lists the reasons and the earliest date, plus the documented dividend-only residual.
  - Close-to-close jumps above 40%.
  - Pure core: `basis_violations(bars) -> dict`, `big_jumps(bars, threshold) -> list`.
- `scripts/evidence/score_calibration.py`:
  - For each symbol, horizon (CLI, default Swing) and direction, replay `score_stock` over bars, as `compute_confidence` does.
  - For every bar, the status bucket (PASS / CAUTION / REJECT).
  - The forward outcome in R, using `evaluate_fire`'s barriers (horizon `atr_mult_target/stop`, `n_days`): win = +target/stop R, loss = −1R, flat = the close-to-close move ÷ stop distance at the window end.
  - **Distinct setups only.** After a counted bar `i` in a bucket, the next counted bar in that bucket is ≥ `i + n_days`, so forward windows never overlap.
  - **Also report**, per horizon and direction, the confidence replay's sample count both ways: overlapping (today's `compute_confidence` rule) and non-overlapping, against `min_samples`. This is the number Kenneth needs for the C4 decision that T8's withdrawal deferred.
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
