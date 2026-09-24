# A4d — a partial Tradier-sandbox bar no longer wins the intraday merge (plan)

Date: 2026-09-24. Planned against main at `5726e12`. First of the four A4c follow-ups locked in decision
`A4C-FOLLOWUPS-LOCKED-2026-09-24` (item 1, re-graded ABOVE the gate): "a sandbox Tradier bar still inside the
feed-lag window must not overwrite yfinance's complete bar. Fixes every consumer at once."

**Kenneth, 2026-09-24 (asked before planning, the no-yfinance case):** *keep the partial bar only if it is the
newest bar.* When no other source has that timestamp, the partial sandbox bar is kept while it is the newest bar
of the merged series (it is then the forming candle, which `candles[-2]` and the completed-bars helpers already
skip); if any newer bar sits after it, it is dropped. A partial bar never sits behind a newer bar.

---

## 1. The defect, verified against today's tree

`fetch_intraday_candles` (`backend/app/data/market.py`) merges yfinance → IBKR → Tradier, and Tradier
overwrites every other source on a timestamp conflict (`merged.update(... tradier_rows)  # Tradier overwrites
all`). Tradier timesales serves `1min`/`5min`/`15min` (`_TRADIER_INTRADAY_INTERVALS`), fetched with
`session_filter=all`. yfinance is fetched without `prepost`, so it has regular-session bars only, and it is
real time.

With the paper token, the base is `https://sandbox.tradier.com` (`get_tradier_creds`), and the sandbox feed is
15 minutes delayed (`TRADIER_SANDBOX_FEED_LAG_SECONDS`, recorded in A4b). At wall time T, the sandbox has data
up to about T−15min. So its **newest** bar is the one containing T−15min, and that bar is partial. Every older
sandbox bar is complete, because the delayed feed is internally consistent.

Worked example, `15min`, T = 10:20 ET:

| bar start | sandbox (data to 10:05) | yfinance (real time) | merged today |
|---|---|---|---|
| 09:45 | complete | complete | sandbox, complete |
| 10:00 | **partial (5 of 15 min)** | complete | **sandbox, partial** |
| 10:15 | — | forming | yfinance, forming |

The chart rule's closed candle is `candles[-2]`: `chart_alert_scheduler._tick` (line 60), and the chart WS in
`routers/chart.py` (line ~93). Both read the rows from `chart_cache.get_intraday_with_fetched_at`, which calls
`fetch_intraday_candles`. So on `15min` the "closed" candle is the partial 10:00 sandbox bar. The price
condition tests its close, and the notification prints it (`"candle": closed_candle`, chart_alerts.py ~941).

On `5min`/`1min` the partial bar sits at `[-3]` or deeper (yfinance supplies the newer bars). It then corrupts
indicator values and structure signals rather than the closed candle. Every other consumer of these intervals
also reads it: the stock scan's 15min strategy bars (`stock_scan.py` 399/726/761), `scan.py` 586, the regime
router, composite watches and the strategy-watch evaluator. The fix at the merge fixes all of them.

**The pre-build check the decision asked for — does yfinance have that bar at that instant?** It could not be
observed live from the planning container: Yahoo is blocked by its network policy (proxy 403), there is no
Tradier token, and the market was closed (16:51 ET). What follows from the code and the feeds:
- In the regular session, yes. The partial sandbox bar starts at S ≤ T−15min. yfinance is real time and serves
  every regular-session bar up to its own forming one, so it has S. With span ≤ 15min, S+span ≤ T, so yfinance's
  S bar is complete (for `15min`, possibly only seconds ago, so at worst yfinance's own publish delay of seconds
  to a minute — still a far better bar than a 1–5-minute partial one).
- In pre/after-hours, no. yfinance is fetched without `prepost`. That is Kenneth's case, handled by the
  "newest only" rule.

## 2. The rule

Applies **only when the Tradier base is the sandbox** (`intraday_feed_lag_seconds() > 0`, the same key A4b/A4c
use). With the live base, the newest Tradier bar is forming just as yfinance's is, and today's precedence is
unchanged.

Let P be the Tradier row with the greatest `time` (by value, not list position). P is *presumed partial*.
1. Every other Tradier row overwrites yfinance/IBKR exactly as today.
2. P is merged only into a timestamp **no other source has**. If yfinance or IBKR has P's timestamp, that bar
   stays.
3. If P was merged (no other source had it) and it is **not** the newest bar of the final sorted result, it is
   dropped.

**Why "newest Tradier row", not a timestamp window.** The locked wording says "a sandbox bar still inside the
feed-lag window". A window test (`time + span + 900 > fetch_start`) would be worse in both directions:
- It flags every bar of the last 15 minutes. On `1min` that is up to 15 bars, of which 14 are complete. In
  extended hours (no yfinance), rule 3 would then drop 14 complete bars.
- It misses the partial bar whenever the sandbox's real delay runs a little over 900s.

The newest sandbox bar is the only bar that can be partial, whatever the exact delay. In the regular session it
is always inside the window. Out of hours the newest sandbox bar is complete and yfinance does not have it, so
rule 2 never replaces it there. The only behaviour beyond the letter of the decision: a complete newest sandbox
bar yields to yfinance's bar at the same timestamp. Both are complete, so nothing is lost, and this is the
existing yfinance baseline.

## 3. The change — `fetch_intraday_candles` only

```python
on_sandbox = intraday_feed_lag_seconds() > 0      # evaluated once, beside the Tradier block
...
merged: dict[int, dict] = {}
merged.update(yf); merged.update(ibkr)             # unchanged
partial_ts = None
if tradier_rows:
    if on_sandbox:
        newest = max(tradier_rows, key=lambda b: b["time"])
        partial_ts = newest["time"]
        merged.update({b["time"]: b for b in tradier_rows if b["time"] != partial_ts})
        if partial_ts in merged:
            partial_ts = None                      # another source's bar stays; nothing to police
        else:
            merged[partial_ts] = newest
    else:
        merged.update({b["time"]: b for b in tradier_rows})
result = sorted(finite(merged.values()), key=time)
if partial_ts is not None and result and result[-1]["time"] != partial_ts:
    result = [b for b in result if b["time"] != partial_ts]
```

- `intraday_feed_lag_seconds` is defined below `fetch_intraday_candles` in the module. It is called at run time,
  so there is no ordering issue.
- The merge log line gains the count of partial sandbox bars yielded or dropped (0/1), at `info`, as it is today.
- Nothing else changes. `completed_intraday_bars` keeps its sandbox lag (see §5.2), and the chart cache and
  every consumer are unchanged.

## 4. Consequences

- `15min` chart rules on the sandbox: `candles[-2]` is yfinance's complete bar in the regular session. Price
  conditions and notifications carry the right close.
- `5min`/`1min`: indicators and structure no longer see a partial bar behind newer bars.
- Pre/after-hours on the sandbox: unchanged. The partial bar is the newest, the forming candle.
- The live base, and yfinance-only (no token): unchanged.
- The stock scan's intraday strategy bars (VWAP and others) lose a partial bar from the middle of the tail. This
  is the intended behaviour: it removes a wrong value, it does not add a lag.

## 5. Decisions and residuals

1. **The no-yfinance case:** Kenneth's "keep only if newest" (above).
2. **Logged, not changed — the A4b sandbox lag in `completed_intraday_bars` is now conservative by up to one
   extra bar when yfinance answered.** Its rationale ("Tradier bars win the merge") no longer holds for the
   partial bar. It still holds out of hours (the newest bar can be the kept partial sandbox bar), so the lag is
   still needed there. Dropping it only when yfinance covered the tail would need the merge to report that. This
   goes to Kenneth as an open question, not into this phase.
3. **Pre-existing, noted:** a Tradier row whose `time` fails to parse is kept with `time = 0` (a 1970 bar). It
   is out of scope. It can only become P if every row failed to parse, and then rule 3 drops it whenever any
   other bar exists.

## 6. Tests — new `backend/tests/test_a4d_sandbox_partial_bar_merge.py`

Tradier is stubbed via `httpx.get` (as `test_market_data_fixes.py` does), yfinance via `_fetch_intraday_yf`,
and the base via `get_tradier_creds` returning a token plus the sandbox or the live base.

1. Sandbox, `15min`, the §1 table: the 10:00 bar in the result is yfinance's (its close), 09:45 is Tradier's
   (older precedence unchanged), 10:15 is yfinance's. `result[-2]` is yfinance's complete 10:00 bar.
2. Sandbox, P has no counterpart and is the newest (pre-market shape: yfinance ends the day before): P is kept,
   with Tradier's values.
3. Sandbox, P has no counterpart but yfinance has a later bar: P is absent from the result, and every other bar
   is present.
4. Live base (`api.tradier.com`): the newest Tradier bar still overwrites yfinance (today's behaviour).
5. Sandbox, Tradier rows delivered **out of order**: P is chosen by the greatest `time`, not by list position.
6. Sandbox, Tradier returns nothing: the yfinance series is returned unchanged.
7. End to end: `chart_alert_scheduler._tick` with one enabled `15min` rule, the chart cache cleared, sources
   stubbed as in test 1. The `closed` passed to `evaluate_and_notify_for_symbol` is yfinance's 10:00 bar.
8. `on_sandbox` is keyed like A4b: a trailing slash on the sandbox base still counts (via
   `intraday_feed_lag_seconds`).

Mutations before the round: restore Tradier-overwrites-all on the sandbox; remove rule 3; apply the rule on the
live base; choose P as `tradier_rows[-1]`; and keep P over another source's bar. Each must turn at least one test
red.

At build, check that no existing test runs on the sandbox base by accident (the credential store in the test
environment), and account for every change against main's backend count.

## 7. Done means

Full backend suite green and reconciling (frontend untouched). `state.py` exit 0 with phase
`A4D-SANDBOX-PARTIAL-BAR-MERGE` flipped to shipped (its defect marker, `# Tradier overwrites all`, gone). The
adversarial round on the code is clean at `audit_rule`'s gate. Then merge.
