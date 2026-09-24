# A4b — the Intraday regime is measured on completed 15-minute bars only (plan)

Date: 2026-09-24. Planned against main at `9cb2ae08` (A4 merged). Kenneth's decision (2026-09-24):
**drop the still-forming 15-minute bar**, on every reader at once, in line with 2B's Option A for daily
bars (decision `AUTOTRADE-2B-UNCLOSED-BAR-OPTION-A-2026-09-21`: the forming bar was "buying a 1-in-100
coin flip rather than information").

---

## 1. The readers, verified against today's tree

Every place a REGIME is measured on 15-minute bars (`regime.intraday.timeframe == "15min"`):

| # | Reader | Where | Series today |
|---|---|---|---|
| R1 | Stock scan | `routers/stock_scan.py` `_process_stock`, `regime_bars = await asyncio.to_thread(fetch_intraday_candles, symbol, "15min", 55)` (~:755-760) | incl. forming bar |
| R2 | Analysis page, the requested horizon | `routers/stock_scan.py` `_analyze_core`, `regime_bars = _intraday_bars if rcfg["timeframe"] == "15min" else bars` (:405) | incl. forming bar |
| R3 | Analysis page, the three horizon blocks | `routers/stock_scan.py` `_regime_block_for_horizon`, `rbars = intraday_bars …` on `15min` (~:548-551) | incl. forming bar |
| R4 | Options scan | `routers/scan.py` `_process_symbol`, `_regime_bars = …fetch_intraday_candles, symbol, "15min", 55` (A4, ~:584) | incl. forming bar |
| R5 | Auto-trade fire path | `services/auto_trader.py` `_fetch_intraday_regime_bars` (A4, ~:912) | incl. forming bar |
| R6 | Step 1, the INTRADAY column of the horizon regime card | `routers/regime.py` `GET /api/regime`, `intra_bars = fetch_intraday_candles('SPY', interval='15min', days=55)` (~:232), feeding `compute_intraday_hmm` and the `compute_omm` fallback (~:229-289) | incl. forming bar — **added in round 1 (F1)** |

**Scope, stated so it is not over-claimed (round 1 F1).** This change covers every measurement of the
**Intraday-horizon regime** — the one `regime.intraday` configures and the screener, the Analysis page,
Step 1 and the auto-trader show or act on. It does NOT cover the user-built alert models that fit a
regime on intraday bars of a user-chosen interval: composite watches with `model == "HMM_intraday"`
(`routers/composite_watch.py:~76-80` snapshot; `services/strategy_watch_evaluator.py:~254-262` →
`composite_trigger_evaluator.evaluate_scheduled`/`evaluate_from_context`, which fire Gmail/Telegram),
chart-drawn composite alerts (`chart_alerts.py:~819-822`), the chart's `/api/regime/intraday-series`
overlay, and strategies' own `require_choppy_regime` checks. Those are separate features with their own
intervals; whether they should drop the forming bar is **logged for Kenneth as a follow-up**, not decided
here.

**Not regime, not touched:** the 15-minute bars intraday STRATEGIES use for signal and backtest
(`stock_scan.py:~723` `intraday_bars`; `_analyze_core`'s `_intraday_bars` at its signal/backtest/chart
uses ~:456/:472/:524). Those are entry-trigger inputs, and whether a trigger may read a forming bar is a
different question from the regime's.

## 2. Bar timing, verified

`fetch_intraday_candles` (`data/market.py:337-449`) returns bars sorted by `time`, a **unix int of the
bar's START** from both sources (Tradier timesales `time`, localised ET → epoch; yfinance
`int(ts.timestamp())` of the interval-start index). It is not cached.

**Feed delay (round 1 F2).** `get_tradier_creds()` falls back to the paper token, whose base is
`https://sandbox.tradier.com`, and sandbox market data is **15 minutes delayed**. Tradier bars take
precedence in the merge, so at 10:46 a sandbox 10:30 bar holding ~one minute of trading replaces
yfinance's complete one, and a `time + 900 <= now` test would keep it. So completeness is
`time + bar_seconds + feed_lag <= now`, with `feed_lag = 900` when the Tradier base in use is the sandbox
and `0` otherwise. When Tradier answered nothing and only yfinance (real time) did, the sandbox lag still
applies — that drops one extra COMPLETE bar, the conservative direction, and is accepted.

## 3. The change

**New helper** in `app/data/market.py`, beside the fetcher:

```python
INTRADAY_REGIME_BAR_SECONDS = 900

def intraday_feed_lag_seconds() -> int:
    """900 when the Tradier base in use is the (15-min delayed) sandbox, else 0."""

def completed_intraday_bars(bars: list[dict], now: float | None = None,
                            bar_seconds: int = INTRADAY_REGIME_BAR_SECONDS,
                            feed_lag: int | None = None) -> list[dict]:
    """Bars whose interval had fully elapsed, in the feed's own clock, at `now`."""
```

- `feed_lag=None` means `intraday_feed_lag_seconds()`; `now=None` means `time.time()`.
- Keeps a bar iff `time` is an int (not bool) and `time + bar_seconds + feed_lag <= now`. A bar whose `time` is not
  an int is **dropped** (fail closed: a bar that cannot be dated cannot be shown to be complete). Nothing
  produces one today.
- Pure; no I/O; `now` injectable for tests.
- Extended hours are included by the same rule: a pre/after-market bar is kept once its 15 minutes have
  elapsed, dropped while forming. Outside all sessions every bar is complete and nothing is dropped.

**Applied at R1–R5 and only there**, immediately where the regime series is formed, BEFORE the
`min_obs` test (so a series that falls under `min_obs` because of the drop is "not measurable", the
existing outcome):
- R1: `regime_bars = completed_intraday_bars(await asyncio.to_thread(fetch_intraday_candles, …))`.
- R2: `regime_bars = completed_intraday_bars(_intraday_bars) if … == "15min" else bars` — the unfiltered
  `_intraday_bars` keeps feeding signal/backtest/chart.
- R3: in `_regime_block_for_horizon`'s `15min` branch, `rbars = completed_intraday_bars(intraday_bars or [])`.
- R4: `_regime_bars = completed_intraday_bars(await asyncio.to_thread(fetch_intraday_candles, …))`
  inside the existing `async with sem:`.
- R5: `_fetch_intraday_regime_bars` returns `completed_intraday_bars(fetch_intraday_candles(...))`.
- R6: `intra_bars = completed_intraday_bars(await asyncio.to_thread(fetch_intraday_candles, 'SPY', …))`,
  BEFORE the `HMM_MIN_BARS` test, so the HMM and the OMM fallback both see the completed series.

The HMM (`compute_directional_hmm`) at R1–R4 runs on the same filtered series, as it already shares the
series with `compute_omm`.

Docstrings touched: `_fetch_intraday_regime_bars` (A4 says the forming bar is "kept … A4 plan s3.1" —
reversed), `_measure_trade_regime`'s `bars:` bullet, the A4 comment block in `scan.py`.

## 4. Decisions and residuals

1. **All six readers at once.** Dropping on a subset reopens the Stocks/Options/auto-trader
   disagreement A4 closed.
2. **The Analysis page is included** (R2, R3): it shows the same regime the scans gate on; leaving it on
   the forming bar would make the page disagree with the scan for the same symbol and horizon.
3. **Lag** of up to 15 minutes on the Intraday regime is accepted (Kenneth).
4. **Scan-to-fire staleness** stays inherent (A4 s3.2), but within one 15-minute slot the scan and the fire
   now measure the identical series.
5. **Clock.** `now` is the server's `time.time()`; bars are epoch-stamped, so no timezone arithmetic is
   involved.

## 5. Tests — new file `backend/tests/test_a4b_completed_intraday_bars.py`

1. Helper: a bar at `now - 900` is kept, at `now - 899` dropped; exactly `time + 900 == now` kept;
   non-int `time` (str, None, bool) dropped; order preserved; empty in → empty out.
1b. Feed lag: with the Tradier base set to the sandbox URL, a bar 16 minutes old is dropped and one
   31 minutes old is kept; with a non-sandbox base, 15 and 16 minutes behave as in test 1.
2. R1–R6 each measure on the completed series: with a fixed `now` and a series whose last bar is forming,
   `compute_omm` receives every bar but the last (patch `time.time` in `app.data.market`, or inject via the
   helper's module clock).
3. A series of exactly `min_obs` bars whose last is forming → unmeasured on R4 and R5 (options card
   `regime_signal` None; fire path abstains → gate `abstained`, sizing `floor:unmeasured`).
4. The unfiltered series still reaches the Analysis page's signal/backtest (R2 does not narrow
   `_intraday_bars` itself).
5. Extend A4's three-readers parity test to assert each reader's regime path goes through
   `completed_intraday_bars`.

Mutation checks before the round: helper `<` vs `<=`; skip the helper at each of R1–R6 in turn; ignore `feed_lag`; filter
`_intraday_bars` itself in R2.

## 6. Done means

Full backend suite green and reconciling; `state.py` exit 0 with a phase entry
`A4B-INTRADAY-COMPLETED-BARS`; an adversarial round on the code clean at `audit_rule`'s gate; merge.

---

## 7. Adversarial round 1 (the plan) — 2026-09-24: TWO gate-level findings, both taken

- **F1 — the reader list was incomplete.** Step 1's Intraday regime card (`GET /api/regime`, SPY 15-min
  HMM + OMM fallback) measured on the forming bar and was not listed. **Taken:** added as R6. The other
  15-minute regime consumers the reviewer named (composite watches `HMM_intraday` and their alerts,
  chart-drawn composite alerts, the chart's intraday-series overlay, strategies' regime filters) are
  **scoped out explicitly** in §1 and logged for Kenneth, so the completeness claim now matches the change.
- **F2 — completeness ignored the source's delay.** The paper-token Tradier sandbox is 15 minutes delayed
  and wins the merge, so `time + 900 <= now` kept a partial bar. **Taken:** completeness is
  `time + bar_seconds + feed_lag <= now`, `feed_lag = 900` on the sandbox base (§2, §3), with a test (1b).

Below the gate, logged: Tradier's parse fallback sets `time = 0` (an int, so "complete", sorts first) —
pre-existing; test 5 proves the helper is called, test 2 proves its result reaches `compute_omm`.

Next: round 2, scoped per `audit_rule` (2) to this revision.

## 8. Adversarial round 2 (the revision) — 2026-09-24: CLEAN

Scoped to `git diff 12d85c46 7face152`. **Zero gate-level findings.** Verified: `_tradier_base()` is the
base the fetch actually used, so a lag keyed on it is right in every credential case (live token → 0;
paper token → sandbox → 900; no creds → yfinance only → 0; sandbox env with no token → 900, the accepted
conservative case); the `T + 1800 <= now` arithmetic; IBKR never joins the 15min merge; R6 filters
before `HMM_MIN_BARS` and feeds both the HMM and the OMM fallback; the 8s fire deadline is unaffected;
every Intraday-horizon regime reader is R1–R6.

Below the gate. **The build adopts 1 and 2:**
1. Tests other than 1b must pass `feed_lag=0` (or patch `intraday_feed_lag_seconds`), or they depend on
   the machine's saved Tradier credentials.
2. Detect the sandbox by substring — `"sandbox.tradier.com" in _tradier_base()` — not equality, so a
   trailing slash on `TRADIER_BASE_URL` still counts.
3. `alert_evaluator.build_regime_snapshot` (regime conditions in price/condition alert rules) belongs in
   §1's scoped-out list; added to the logged follow-up.
