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

**Not regime, not touched:** the 15-minute bars intraday STRATEGIES use for signal and backtest
(`stock_scan.py:~723` `intraday_bars`; `_analyze_core`'s `_intraday_bars` at its signal/backtest/chart
uses ~:456/:472/:524). Those are entry-trigger inputs, and whether a trigger may read a forming bar is a
different question from the regime's.

## 2. Bar timing, verified

`fetch_intraday_candles` (`data/market.py:337-449`) returns bars sorted by `time`, a **unix int of the
bar's START** from both sources (Tradier timesales `time`, localised ET → epoch; yfinance
`int(ts.timestamp())` of the interval-start index). It is not cached. So a 15-minute bar is complete
exactly when `now >= time + 900`.

## 3. The change

**New helper** in `app/data/market.py`, beside the fetcher:

```python
INTRADAY_REGIME_BAR_SECONDS = 900

def completed_intraday_bars(bars: list[dict], now: float | None = None,
                            bar_seconds: int = INTRADAY_REGIME_BAR_SECONDS) -> list[dict]:
    """Bars whose interval has fully elapsed at `now` (epoch seconds; default time.time())."""
```

- Keeps a bar iff `time` is an int (not bool) and `time + bar_seconds <= now`. A bar whose `time` is not
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

The HMM (`compute_directional_hmm`) at R1–R4 runs on the same filtered series, as it already shares the
series with `compute_omm`.

Docstrings touched: `_fetch_intraday_regime_bars` (A4 says the forming bar is "kept … A4 plan s3.1" —
reversed), `_measure_trade_regime`'s `bars:` bullet, the A4 comment block in `scan.py`.

## 4. Decisions and residuals

1. **All five readers at once.** Dropping on a subset reopens the Stocks/Options/auto-trader
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
2. R1–R5 each measure on the completed series: with a fixed `now` and a series whose last bar is forming,
   `compute_omm` receives every bar but the last (patch `time.time` in `app.data.market`, or inject via the
   helper's module clock).
3. A series of exactly `min_obs` bars whose last is forming → unmeasured on R4 and R5 (options card
   `regime_signal` None; fire path abstains → gate `abstained`, sizing `floor:unmeasured`).
4. The unfiltered series still reaches the Analysis page's signal/backtest (R2 does not narrow
   `_intraday_bars` itself).
5. Extend A4's three-readers parity test to assert each reader's regime path goes through
   `completed_intraday_bars`.

Mutation checks before the round: helper `<` vs `<=`; skip the helper at each of R1–R5 in turn; filter
`_intraday_bars` itself in R2.

## 6. Done means

Full backend suite green and reconciling; `state.py` exit 0 with a phase entry
`A4B-INTRADAY-COMPLETED-BARS`; an adversarial round on the code clean at `audit_rule`'s gate; merge.
