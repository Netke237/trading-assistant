# Trading Review Phase C — Solution Proposal (2026-10-04 review)

> **Status: PROPOSAL, not an audited plan.** No tickets are cut from this file. Once Kenneth answers the
> decisions in §5, it becomes the input to a TDD plan (`2026-10-04-trading-review-phase-c-plan.md`). That plan
> needs a clean plan audit before `k-ticket-coordinator` cuts tickets (`audit_rule`, `docs/agents/ticket-orchestration.md`).
>
> **Spec:** `TRADING_REVIEW.md` as rewritten on 2026-10-04 (overall REJECT; Area 1 and Area 2 REJECT; Areas 3–5 CAUTION).
> That rewrite is **not on any branch yet**: it is still uncommitted on Kenneth's machine. The repo copy is the 2026-10-02
> report. Every code claim below was re-checked in this repo at `fa84b08` (= `origin/main`).
> Every evidence number (44.2%, 29/248, ρ…) comes from the 2026-10-04 review and has **not** been re-measured here:
> this container has no populated `ohlcv_daily`.

## 1. Diagnosis: the findings are three different kinds of problem

The review's findings are not twenty independent bugs. They fall into three layers, and each layer depends on the one below it:

| Layer | Findings | Kind | Can code fix it? |
|---|---|---|---|
| **L1: Data** | H1 mixed-basis bars | A plain bug | Yes, and it must go first |
| **L2: Measuring instruments** | M1 WFO picks on gross Sharpe and charges one round trip per fold · M2 `min_trades: 20` unreachable · M3 GTC limit fills in backtest vs DAY live · M4 `setup_window_bars` dead · Phase-B #11 confidence replay overlap | Bugs in the tools that produce the evidence | Yes |
| **L3: The verdict** | H2 Swing score does not discriminate · H3 the per-symbol gate has no persistence · M5 every bearish strategy loses after costs · M6 `breakout_base` and `mean_reversion_rsi` never reach the gate | **Evidence that there is no edge.** Not bugs | **No.** Code can only make the app say so honestly |
| **Side: consistency** | M7 R/R uses a 60% loss basis while sizing uses 100% · M8 Stocks "After scan" fires on CAUTION · M9 the earnings veto is shorter than long holds (= Phase-B A1-F6) | Small policy contradictions | Yes, once a policy is chosen |

**The core argument.** H2 and H3 were measured on top of L1 and L2. One example: the 2026-10-03 re-tune evidence (`TRADING-REVIEW-RETUNE-EVIDENCE`, "753 adjusted settled bars", 0 of 5 proposals eligible) read its bars through `_read_bars`, so it rests on the mixed basis. The honest sequence is:

1. Fix the data.
2. Fix the instruments.
3. Re-measure with a harness that lives in the repo.
4. Only then decide what the app should claim.

Retuning parameters or reweighting scores before steps 1 to 3 would be curve-fitting to broken bars.

## 2. Verified mechanisms (this repo, `fa84b08`)

- **H1.** `backend/app/services/historical_store.py:236-245` `_read_bars`:
  - `close = raw_close × adj_factor`.
  - `open/high/low` are returned **raw**.
  - Every DB reader goes through it: `get_bars` → stock scan, options scan (`routers/scan.py:1741`), regime, chart alerts, strategy watch, WFO optimizer, auto-trader.
  - `tests/test_historical_store_guard.py:46-59` asserts only the close (`110.0`) and leaves `open 98 / high 102` beside `close 110`, which pins the inconsistency.
  - Providers: `adj_factor = adjClose/close` (`data/tiingo.py:50`, `data/alpaca.py:109`), and that factor includes dividends. yfinance rows are pre-adjusted (`adj_factor 1.0`).
  - Second-order issue: `adj_factor` is as of the fetch date. The nightly Alpaca ingestion re-fetches the full `years` window and upserts (`ingestion_job.py:108-138`), so Alpaca rows are refreshed. Rows gap-filled by Tiingo or yfinance are never re-fetched, so after a later dividend or split their factor is stale. That is a plausible source of the Q10 jumps (GE 2021-08-02 ×7.76, a 1:8 reverse split).
- **M1.**
  - `walk_forward.train_fold` (`walk_forward.py:237-248`) ranks combos on `res.sharpe` from `run_strategy_backtest(...)`, called **without** `commission`, so selection is gross.
  - `apply_costs` (`walk_forward.py:110-122`) subtracts `(fee+slip)×2` **once per fold-window return**, not once per trade (`strategy_param_optimizer.py:126,153`).
  - A fold with 9 trades is charged 1 round trip instead of 9.
- **M2.** `strategy_params.yaml:35` `min_trades: 20` is checked against the per-contributing-symbol OOS average (`strategy_param_optimizer.py:207`). The review measured a best case of about 9.6.
- **M3.** `strategy_backtest.py:158-162` places `buy/sell(limit=…)` every bar with no expiry. `backtesting.py` keeps an unfilled limit order alive until it fills, which is effectively GTC, while live orders are DAY.
- **M4.** `trigger.setup_window_bars` exists in `scoring_rules.yaml:105,264,375` and in the `config_health.py:133` key list, but nothing in `backend/app` reads it.

## 3. Proposed solution: Phase C in four stages

### C1 — Consistent bars (fixes H1). Blocks everything else.

| Ticket | Change | Test first |
|---|---|---|
| C1-T1 | `_read_bars` scales `open/high/low/close` by the same `adj_factor`. NULL factor → all four raw, as today. Volume unchanged (see decision D3) | Rewrite `test_read_bars_returns_adjusted_close` so it asserts all four prices are scaled by 1.1 and `low ≤ open,close ≤ high` holds. A new property test runs the invariant over random factors and bars |
| C1-T2 | Stale-factor repair: a `refresh_adjustments(symbols)` path re-fetches the full window for symbols whose newest row's `fetched_at` is after an older row's last `div_cash ≠ 0` or `split_factor ≠ 1`, or which have an unexplained close-to-close jump above 40% with no split row. It can be run from Settings → Data and is logged. **Never** deletes rows | A fixture with a split mid-series: after refresh, the adjusted series has no jump |
| C1-T3 | Data-quality probe `scripts/evidence/bar_basis_check.py`: read-only SELECTs that report, per symbol, the share of bars with close ∉ [low, high] (from `_read_bars` output) and the jumps flagged above. The 44.2% → ~0% result is the acceptance evidence, run on Kenneth's DB | The script's pure core is unit-tested on fixtures |
| C1-T4 | Invalidate derived caches keyed on bars (scan bar caches, confidence/backtest caches). Mark `TRADING-REVIEW-RETUNE-EVIDENCE` as **superseded: computed on mixed-basis bars** in `PROJECT_STATE.json` | A cache-key test: a basis version bump changes the key |

Golden numeric pins that move because of C1-T1 are re-pinned **with the reason recorded in each test**. This is an intended correctness change, not the "unintended runtime" case that CLAUDE.md forbids re-pinning for. The plan must list every pin that moves.

### C2 — Honest instruments (fixes M1–M4 and Phase-B #11)

| Ticket | Change |
|---|---|
| C2-T1 | WFO selects on **net** results: `train_fold` and the OOS scoring call `run_strategy_backtest(commission=fee+slippage)`, the same per-leg cost the live Step-6 gate already uses (`routers/stock_scan.py` `_backtest_commission`). `apply_costs` per window is deleted, so there is no double charge. |
| C2-T2 | Minimum-evidence rule: `min_trades` counts **pooled OOS trades across the basket** per proposal (the review measured ~9.6 per symbol, so the pooled count clears 20 easily), and a per-symbol floor stays separate. The exact rule is decision D4. |
| C2-T3 | DAY limit semantics in the backtest: an unfilled **entry** limit is cancelled at the next `next()`. Contingent SL/TP orders are untouched. The test is a fixture where the limit is touched on bar t+3: today it fills, after the fix it does not. |
| C2-T4 | `setup_window_bars`: implement it in the stock scorer trigger (momentum events count if they happened within the last N bars), or delete it from YAML and from `config_health`. Decision D2. |
| C2-T5 | (Phase-B #11) The confidence replay is de-overlapped by `n_days` and gated on expectancy in R, not on win rate. The 2:1 barrier asymmetry is already known. |

### C3 — Evidence harness in the repo, then re-measure

Move the reviewer's scratchpad scripts into `scripts/evidence/`. They are now on Kenneth's machine only: `bt5y.py`, `calib.py`/`calib_an.py`, `split.py`, `wfo.py`, `conf_basis.py`, `stale.py`, `basis_impact.py`.

- Each script reads bars **only** through `historical_store._read_bars`, so it measures what the app sees, with read-only SELECTs.
- Each prints a fixed-format report into `docs/superpowers/reports/`.
- Each records the input hashes, the commit and the cost model.

Kenneth runs them on his Postgres after C1 and C2 merge. A cloud container cannot run them because it has no data. Output:

1. Score calibration by status bucket (H2): mean R with a 95% CI, for each horizon and direction.
2. Split-half gate persistence (H3): Spearman ρ against the noise band.
3. 5-year strategy × direction matrix, net of costs, with DAY fills (M5, M6).
4. A fresh WFO run with the C2 objective. This supersedes `2026-10-03-multiyear-retuning.md`.

### C4 — What the app is allowed to claim (decision gate, after C3)

C4 is decided **after** the C3 numbers and is not ticketed now. Default rules, for Kenneth to accept or override:

- A strategy × direction × horizon whose net expectancy CI includes 0 is labelled **"Unvalidated"** on Step 4 and Step 6. It cannot reach PASS, and it cannot be auto-armed.
- Bearish strategies that are still negative after costs are hidden from the picker or locked to "research only".
- If the score still does not separate PASS from REJECT (H2), the score is shown as a **filter**, not a ranking, and the copy says so. The alternative, re-weighting the 5 rules on the C3 calibration data, needs a held-out period so it does not fit noise.
- If the per-symbol gate still shows no persistence (H3), it is replaced by a pooled, per-strategy gate. One symbol's past does not predict its future, so a per-symbol verdict adds noise.

### Side items (small, independent, can run in parallel with C2)

| Ticket | Change | Decision |
|---|---|---|
| S-T1 | R/R loss basis = the loss the position can really take. 100% of premium unless a protective stop order is actually placed at `premium_stop_pct` | D5 |
| S-T2 | Stocks auto-trade "After scan" fires on PASS only, the same as options | D6 |
| S-T3 | Earnings veto window = `max(reject_days, hold_max)` per horizon preset (Phase-B A1-F6) | D6 |

## 4. Sequencing and ticket graph

```
C1-T1 ─┬─ C1-T2 ─ C1-T3
       └─ C1-T4
C1-T1 ─── C2-T1 ─ C2-T2          (same files: walk_forward.py / strategy_param_optimizer.py → serial)
C1-T1 ─── C2-T3                  (strategy_backtest.py)
          C2-T4, C2-T5           (disjoint files → parallel worktrees allowed)
          S-T1, S-T2, S-T3       (disjoint → parallel)
all ───── C3 harness ─── [Kenneth runs on DB] ─── C4 decision ─── C4 plan (separate phase)
```

**Phase boundary.** C1 + C2 + side items + the C3 harness code form one phase, `TRADING-REVIEW-PHASE-C`, with one tracking issue and one code audit over the integrated diff. Running the harness and making the C4 policy change form a later phase, because they depend on numbers that do not exist yet.

## 5. Decisions only Kenneth can make

| ID | Question | Recommended |
|---|---|---|
| D1 | Scope of this phase | C1 + C2 + side items + the C3 harness now; C4 after the numbers |
| D2 | `setup_window_bars`: implement it or delete it? | Implement it. It is the documented design, and the same-bar-only trigger is the stricter accident |
| D3 | Volume across splits: leave it raw, or divide by the split ratio? | Leave it raw in C1, because volume rules use ratios over ≤ 50 bars. Log it as a residual |
| D4 | WFO evidence floor | ≥ 20 pooled OOS trades **and** ≥ 3 contributing symbols per proposal |
| D5 | R/R loss basis | 100% unless a broker stop is placed |
| D6 | Interim safety until C3/C4 | Ship S-T2 (After scan on PASS only) and S-T3 now. Disable bearish auto-arm until C3 shows net-positive bearish evidence |

## 6. Out of scope

- Re-weighting the scorer.
- Changing any threshold or strategy parameter value.
- Adopting any WFO proposal.
- Writing to the production DB, except through the existing ingestion upsert path that C1-T2 triggers.
- Checking the Q10 anomalies (GE, FI, AVB, CTVA, MRNA) against an independent price source. C1-T3 flags them; Kenneth verifies them.
