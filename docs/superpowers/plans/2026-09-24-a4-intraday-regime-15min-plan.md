# A4 — the Intraday regime is measured on 15-minute bars (plan)

Date: 2026-09-24. Planned against main at `44a01102`. Kenneth's decision (2026-09-24): **measure on
real 15-minute bars** rather than relabel the existing daily measurement.

Source finding: `open_questions` entry "LOGGED AGAINST MAIN by 2C round 1 (2026-09-21) … the OPTIONS
scan measures the Intraday regime on DAILY bars while LABELLING it `15min`".

---

## 1. The defect, verified against today's tree

`scoring_rules.yaml:452` — `intraday: { timeframe: 15min, lookback: 26, window: 1000, min_obs: 60 }`.
Swing and Position are `daily`.

There are three measurements of a symbol's regime at a horizon. Only one honours `timeframe`:

| Path | Where | Bars it measures on for Intraday |
|---|---|---|
| Stock scan | `routers/stock_scan.py:398-405` | `fetch_intraday_candles(symbol, "15min", 80)` when `rcfg["timeframe"] == "15min"` — **correct** |
| Options scan | `routers/scan.py:567-600` (`_process_symbol`) | `candles` — the ~306 **daily** bars — with `_rcfg["timeframe"]` used only as the emitted label |
| Auto-trade fire path | `services/auto_trader.py` `_measure_trade_regime` → `_fetch_scan_window_bars` | **daily**, for every horizon, deliberately matching the options scan (2B) |

Consequences today, for an Intraday options trade:
- The card's `regime_signal` (state, stability, `conviction_pct`) is a daily regime under a `15min` label.
- `score_stock` feeds that conviction to `_regime_cap` (the headwind gate), so Options and Stocks mode can
  give the same symbol at the same horizon different verdicts.
- The auto-trader's headwind gate and — since SIZING-4 — its sizer read the same daily number at fire time.

## 2. The change

### 2.1 Options scan — `routers/scan.py`, the regime block in `_process_symbol`

- Import `fetch_intraday_candles` from `app.data.market` (already a module of that package's imports).
- Choose the regime series by `timeframe`, exactly as `stock_scan.py:405` does:
  - `15min` → `await asyncio.to_thread(fetch_intraday_candles, symbol, "15min", 80)`; any exception → `[]`.
  - otherwise → `candles`, unchanged.
- `_compute_omm` **and** `_compute_dhmm` both run on that series (the stock scan runs both on
  `regime_bars`); the `min_obs` precondition is tested on it.
- An empty or short intraday series leaves `_regime_signal = None` — the existing "not measurable" outcome
  (no regime gate on the scan; the card's sizing then floors per A2). **No fallback to daily bars**:
  that would reintroduce the mislabelled measurement this plan removes.
- The fetch happens only for Intraday; Swing/Position scans do no new I/O.

### 2.2 Fire path — `services/auto_trader.py`, `_measure_trade_regime`

- The bar source is chosen by `rcfg["timeframe"]`: `15min` → a new `_fetch_intraday_regime_bars(symbol)`,
  which returns `fetch_intraday_candles(symbol, "15min", 80)`; otherwise `_fetch_scan_window_bars`
  unchanged. It runs in the same executor under the same `_REGIME_FETCH_DEADLINE_S`, and every existing
  abstain branch (timeout, exception, `< min_obs`, `compute_omm` None) applies unchanged.
- The daily path's Option A trim (drop the still-forming session bar) is **not** applied to the 15-minute
  series — see §3.1.
- Gate and sizer keep sharing one measurement via `_measure_once`; nothing else in the fire path changes.

### 2.3 One fetch spec, three readers

`("15min", 80)` is written in three places after this change (stock scan, options scan, fire path). A
test pins that all three pass the same arguments, so a later edit to one cannot silently re-open the
Stocks/Options disagreement. `stock_scan.py` itself is **not** edited.

## 3. Decisions taken here, and residuals named

1. **The still-forming 15-minute bar is kept**, on both the options scan and the fire path, because the
   stock scan keeps it and A4's purpose is that the three agree. Dropping it only on the options side would
   recreate a Stocks/Options disagreement. Whether all three should drop it (as 2B's Option A does for the
   daily bar) is a separate question for Kenneth, logged, not decided here.
2. **Scan and fire measure at different times.** An intraday regime moves between the scan and the fire;
   the fire path measures the series available at fire time. This is inherent to an intraday measurement
   and is not a parity defect — the daily path's argument (same completed-bar series) does not transfer.
3. **The source mix is inherited, not fixed.** `fetch_intraday_candles` merges Tradier timesales
   (`session_filter: "all"`, extended hours) with yfinance (regular hours), and caps history at ~55 days
   whatever `days` says. The stock scan already measures on that series; A4 makes the other two match it.
4. **Latency.** A 15-minute fetch can be slower than the daily read. On the fire path a slow fetch hits the
   existing deadline and abstains — the gate abstains and sizing floors at `min_mult`, both existing
   behaviours. On the scan, the fetch is per Intraday symbol, as the stock scan already does.

## 4. Tests — new file `backend/tests/test_a4_intraday_regime_bars.py`

1. Options scan, Intraday: `_compute_omm` receives the closes of the **intraday** series (not `candles`),
   `fetch_intraday_candles` is called with `("15min", 80)`, and the emitted `regime_signal["timeframe"]`
   is `15min` (the harness of `test_scan_db_first.py`: `score_stock` patched, `regime_signal` captured).
2. Options scan, Swing: `fetch_intraday_candles` is **not** called; `_compute_omm` receives `candles`.
3. Options scan, Intraday, the intraday fetch raises or returns too few bars: `regime_signal` is None, and
   `_compute_omm` is never called with the daily series.
4. `_compute_dhmm` receives the intraday series on Intraday.
5. Fire path, Intraday: `_measure_trade_regime` fetches via `fetch_intraday_candles("…","15min",80)` and
   never calls `_fetch_scan_window_bars`; Swing does the reverse.
6. Fire path, Intraday, fetch fails / short: abstains (returns None); with sizing on, the order is floored
   (`sizing="floor:unmeasured"`), never full.
7. The three readers pass identical `(interval, days)` (stock scan, options scan, fire path).

Mutation checks before the round: drop the timeframe branch in either path; fall back to daily on a
failed intraday fetch; run `_compute_dhmm` on `candles`.

## 5. Done means

Full backend suite green and reconciling (+ the new file's count exactly); `state.py` exit 0 with a phase
entry `A4-INTRADAY-REGIME-15MIN` created with the code; an adversarial round on the **code** clean at
`audit_rule`'s gate; then merge.

---

## 6. Adversarial round 1 (the plan) — 2026-09-24: CLEAN

An independent reviewer ran `bmad-review-adversarial-general` on this plan against `44a01102` under
`audit_rule`'s gate. **Zero gate-level findings.** It confirmed: `fetch_intraday_candles` returns
unix-int `time`, and nothing on either regime path reads `time` except `_fetch_scan_window_bars`'s date
trim, which the Intraday branch bypasses; the 55-day source cap still yields ~990 (yfinance) to ~2,400
(merged) bars, clearing `min_obs` 60 and the HMM's 200; the other readers of the options card's regime
are display-only or read only `conviction_pct`/`stability`; the new fetch fits the fire path's executor
and deadline (it writes no shared cache); no other options-path measurement exists; and no existing
fire-path test arms Intraday.

Below the gate (logged, not fixed in the plan). **The build adopts 1 and 2**, because they are about what
the code it writes says, not new scope:

1. **The stock scan's reader is `_process_stock` (`stock_scan.py:751-760`), which fetches
   `("15min", 55)`.** The `("15min", 80)` at `:398` is `_analyze_core` — the Analysis page. Output is
   identical (both sources cap at 55 days), but parity must copy the SCAN. **Build: both new readers use
   `("15min", 55)`, and test 7 pins them against `_process_stock`.** §1's table and §2 should be read
   with `55` where they say `80`.
2. **The options-scan fetch sits outside `sem`**, while the stock scan's runs under its scan semaphore.
   **Build: the options-scan fetch runs inside `async with sem:`.**
3. The card's `MarketSentiment` shows `~{avg_regime_duration}d`, which is in lookback strides, not days —
   already mislabelled on daily Swing/Position; A4 carries it onto Intraday, does not create it.
4. The 8s fire-path deadline against a serial Tradier-then-yfinance fetch is unmeasured offline; if it
   overruns, every Intraday fire abstains and sizes at the floor (§3.4 names it).
