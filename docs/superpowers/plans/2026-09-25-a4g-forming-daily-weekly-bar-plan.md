# A4g — 1D/1W user alerts drop the forming daily/weekly bar (plan)

Date: 2026-09-25. Planned against main at `e2bf498` (A4e merged). Last item of decision
`A4C-FOLLOWUPS-LOCKED-2026-09-24`, part (4):

> 1D/1W user alerts DROP the forming daily bar using 2B guard (i)'s session-hours test
> (auto_trader._todays_bar_is_unclosed moved to a shared home, not copied); weekly by the same rule
> for consistency (accepted cost: a weekly regime lags up to a week). Plan must first verify whether
> historical_store.get_bars even contains today's forming bar -- if not, composite watches and
> require_choppy_regime are already on completed daily bars and only the chart path (live daily
> candles) changes.

**Kenneth, 2026-09-25, asked before planning:** on the 1D/1W chart path, **all** inputs that were fed
the chart's daily candles get completed bars. That covers the HMM_daily fit **and** the rsi/bb strategy
confirmations, including their `require_choppy_regime` OMM. The aim is that a chart composite and a
composite watch with the same trigger see the same data.

A4f (HMM_intraday watches stored on `'1D'`) runs in a parallel session (`claude/dazzling-ride-0unofk`)
and is out of this plan. Its files (`strategy_watch_store`, `CompositeAlertDialog`,
`composite_watch.py`'s HMM_intraday branch) are not touched here.

---

## 1. Does `get_bars` contain today's forming bar? (the lock's first check)

The check is done by reading the code. I could not call a provider: this container has no provider
network, and yfinance returns 403.

- `get_bars` (`services/historical_store.py:218`) fetches only when `last < min(end, _prev_trading_day())`.
  So it fetches only when the DB lacks a **completed** session (`_prev_trading_day` = the session before
  today). The fetch window is `fetch_start .. end`, where `end` is today for every alert caller.
- **yfinance** (`_yfinance_fetch`, `start=`/`end=`): yfinance's `end` is exclusive, so today is excluded.
- **Alpaca** (`_get_bars_page`, `"end": end.isoformat()`, a date-only string): daily bars are stamped
  `T04:00:00Z`/`T05:00:00Z` (00:00 ET). A date-only `end` read as `00:00Z` excludes today's bar.
  **Not verified live.** If Alpaca reads a date-only `end` as end of day, a fetch made mid-session would
  store today's partial bar. Because `last` would then equal today, it would never be re-fetched. That is
  a pre-existing persisted-data risk on every `get_bars` reader, not only alerts.
- **Tiingo** (`endDate` inclusive): Tiingo publishes a day's EOD bar after the close, so any today-bar it
  returns is complete.

**Conclusion, stated with its limit:** by the code, `get_bars` returns completed daily bars. Composite
watches, strategy watches (`require_choppy_regime` included), HMM_daily on intraday-interval chart rules,
and the dialog's OMM/HMM_daily snapshot therefore already read completed bars. **Only the chart path
changes.** The Alpaca reading is logged as an open question for Kenneth: verify with a live mid-session
call, and if it is wrong, clamp `get_bars`' fetch `end` to the last completed session. That is outside
this change.

## 2. The readers that change: `evaluate_and_notify_for_symbol` on 1D/1W

`all_candles` comes from `chart_cache.get_intraday(symbol, '1D'|'1W')`, i.e.
`fetch_intraday_candles(symbol, 'daily'|'weekly')` → IBKR + yfinance. Its last element is today's
(this week's) **forming** bar during the session. Today on 1D/1W, `completed_bars_for_interval` returns
the list unchanged (A4c scoped daily/weekly out).

| # | Reader | Today (1D/1W) | After |
|---|---|---|---|
| D1 | Standard rules' regime conditions: `build_regime_snapshot(_regime_candles)` | forming bar in | completed |
| D2 | Composite OMM primary: `_omm` from `_regime_candles` closes (also the persisted `trigger_values.omm_state`) | forming bar in | completed |
| D3 | Composite `bars_daily` = `_model_candles` on 1D/1W (`chart_alerts.py:~880`). It feeds HMM_daily **and** `_check_strategy_signals` (rsi/bb + `require_choppy_regime`) and `describe_match` | forming bar in | completed (Kenneth, 2026-09-25) |

**Unchanged:** `closed_candle` (`candles[-2]`, already the previous bar), indicators and structure
(A4e), `bars_intraday` (already `[]` on 1D/1W), and every intraday interval (A4c/A4d).

## 3. The shared session test (moved, not copied)

New module `app/services/market_session.py`:
- **`todays_bar_is_unclosed(now=None)`**: the body **and** the docstring of
  `auto_trader._todays_bar_is_unclosed`, moved verbatim. It needs `_market_session_open` (the import of
  `strategy_watch_scheduler._market_open`), `_NYSE_OPEN` and `MARKET_TZ`. These move with it, together
  with the import-rationale comment.
- `auto_trader.py`: `from app.services.market_session import todays_bar_is_unclosed as _todays_bar_is_unclosed`.
  The call site `_fetch_scan_window_bars` (`:854`) still calls the module-global
  `_todays_bar_is_unclosed()`, so the existing `mocker.patch.object(at, "_todays_bar_is_unclosed", …)`
  tests keep patching what runs. `_market_session_open` / `_NYSE_OPEN` are removed from `auto_trader`
  if nothing else there uses them (verified at build).
- **`week_is_unclosed(now=None)`**: True while the current ET week's last session has not closed.
  Mon–Thu → True. Fri → `todays_bar_is_unclosed(now)`, i.e. through 16:00. Sat/Sun → False. `now` is
  normalised the same way (aware → `MARKET_TZ`, naive raises).
- **`completed_session_bars(bars, interval, now=None)`**:
  - `normalize_interval(interval)` ∈ {`daily`} (`1D` aliases to it) → daily rule;
    ∈ {`weekly`} (`1W`) → weekly rule. Any other interval → `bars` unchanged.
  - Only the **newest** bars can be forming, so only trailing bars are examined:
    1. If the last bar's `time` is not an int (or is a bool), drop **that one bar** (fail closed, as in
       A4b). No live source produces one.
    2. Then, while the last bar's `time` is **after the last completed close** (strictly `>`), drop it.
       Stop at the first bar that is not (or is undatable).
       - Daily: `last_session_close(now)` = today's 16:00 ET when today is a weekday and
         `todays_bar_is_unclosed(now)` is False; otherwise the previous weekday's 16:00 ET.
       - Weekly: `last_week_close(now)` = this week's Friday 16:00 ET when `week_is_unclosed(now)` is
         False; otherwise the previous week's Friday 16:00 ET.
  - **Round 1 F1 (taken): compare the bar's timestamp with an INSTANT, not calendar dates.** The earlier
    draft matched the bar's ET-or-UTC date against today's ET date. A bar is one session's bar whatever
    its stamp convention, and every convention in use stamps it at or after the previous close and at or
    before its own close: 00:00 ET (yfinance), 00:00 UTC (= previous evening ET), session open, session
    close (IBKR is not verified). So "stamp > last completed close" is true for exactly the forming bar
    and false for every completed one, with no date arithmetic across zones. At the close itself a
    close-stamped bar (`time == close`) is kept, hence strict `>`. Weekly works the same way for
    Monday-00:00 (yfinance), Sunday-evening-ET and Friday stamps. The only false positive is a bar
    stamped AFTER its own close (e.g. 20:00 ET): it is dropped until that stamp passes, the conservative
    direction. Weekends need no special case: on Sat/Sun the last close is Friday 16:00, and no bar is
    newer. (Guard (i) reads Sat before 09:30 as "unclosed"; `last_session_close` checks the weekday first,
    so that quirk does not reach here.)
  - Order is preserved and the input list is not mutated.

**The `now` for the chart path is the fetch time**, as in A4c. `chart_cache` holds a 1D/1W snapshot for
up to 4h, and a snapshot taken at 15:00 still holds a partial bar at 17:00. So
`now = datetime.fromtimestamp(as_of, MARKET_TZ)` when `as_of` is given; otherwise `datetime.now(MARKET_TZ)`.

## 4. The change in `evaluate_and_notify_for_symbol`

```python
_regime_candles = completed_session_bars(
    completed_bars_for_interval(all_candles or [], interval, now=as_of), interval, now=_as_of_dt,
)[-MAX_LIVE_MODEL_CANDLES:]
```
`completed_session_bars` does nothing on intraday intervals and `completed_bars_for_interval` does
nothing on daily/weekly. So the intraday behaviour is byte-identical and D1/D2 follow directly. D3: on
1D/1W, `_bars_daily = _regime_candles` in place of `_model_candles`. `_model_candles` then only serves
`_bars_intraday` on intraday intervals, which is unchanged.

Docstring: the "1D/1W are unchanged" sentence of the A4c paragraph is replaced by one A4g sentence.

## 5. Decisions and residuals

1. **Lag accepted** (Kenneth, lock): a 1D regime reflects the previous session until 16:00 ET, and a 1W
   regime reflects the previous week until Friday 16:00 ET.
2. **Half days and holidays**: the guard (i) residuals carry over unchanged. On a 13:00 early close, the
   completed bar is still dropped until 16:00. A holiday Friday reads the week unclosed until 16:00.
3. **Host date**: the chart path uses the ET date of `now` itself (aware), not `date.today()`, so guard
   (i)'s host-date limb does not apply here.
4. After 16:00 the regime includes today's completed bar while `closed_candle` is still `candles[-2]`, so
   the regime is one bar newer than the closed candle. Nothing here makes that worse; it is noted, not
   changed.

## 6. Tests — new `backend/tests/test_a4g_forming_daily_weekly_bar.py`

1. `completed_session_bars` daily truth table at explicit ET instants:
   - Wed 10:00: today's bar dropped, yesterday's kept.
   - Wed 16:01: today's bar kept.
   - Wed 08:00: a today-stamped bar dropped.
   - Sat: nothing dropped.
   - A 00:00-UTC-stamped today bar is dropped at Wed 10:00 ET and kept at Wed 17:00 ET.
   - A close-stamped (16:00 ET) today bar is dropped at 15:59 and kept at 16:01.
   - Monday 10:00: Friday's bar kept, today's dropped (the previous weekday skips the weekend).
   - Undatable last bar: dropped (that one only); an undatable middle bar is kept.
   - `15min`/`1h` unchanged; the input is not mutated.
2. Weekly: at Wed 10:00, this week's bar is dropped and last week's kept. At Fri 15:59 dropped, at Fri
   16:01 kept, on Sat kept.
3. `week_is_unclosed` / `todays_bar_is_unclosed`: naive `now` raises, and aware UTC equals its NY
   equivalent.
4. D1/D2/D3 on `1D` with a forming last candle (patched clock at mid-session):
   - the regime snapshot, OMM closes, HMM_daily and `_check_strategy_signals`' `bars_daily` all exclude
     it;
   - on `1W` the same for this week's bar;
   - after the close (patched clock at 17:00, `as_of` 17:00), all include it.
5. `as_of`: a 1D snapshot fetched at 15:00 and evaluated at 17:00 with `as_of` = 15:00 still drops the bar.
6. The move: `auto_trader._todays_bar_is_unclosed is market_session.todays_bar_is_unclosed`. The
   existing guard (i) test that patches `at._market_session_open` is re-pointed at `market_session`
   (reason recorded). Every other auto-trader test is unchanged and green.
7. Intraday parity: a 15min rule's inputs are identical to A4c/A4e (existing tests stay green unchanged).

Mutations before the round:
- `<` vs `<=` at 16:00 via guard (i), inherited;
- `>=` instead of `>` against the close instant (drops a close-stamped completed bar);
- the previous weekday computed as `date - 1 day` (Monday reads Sunday's 16:00);
- the weekly rule reads the daily test;
- `now` taken as wall clock instead of `as_of`;
- D3 left on `_model_candles`;
- the helper skipped entirely;
- drop all undatable bars instead of the last one;
- Friday treated as closed all day.

## 6a. Adversarial round 1 (plan) — NOT CLEAN, one finding, taken

- **F1**: the ET-or-UTC calendar-date match for "today's bar" rests on assumptions about stamp
  conventions across zones and has a false-positive/negative surface at the date edges. Fix: compare the
  bar's timestamp with the last completed close instant (§3, step 2). Taken as proposed by the reviewer.
- Note: the first build of this plan (previous session) was lost uncommitted; this amendment and the
  build are redone from this plan. Round 2 covers the amendment and the code.

## 7. Done means

Full backend suite green and reconciling (frontend untouched), `state.py` exit 0, and a phase entry
`A4G-FORMING-DAILY-WEEKLY-BAR`. Then the code round, clean at `audit_rule`'s gate, then merge.
