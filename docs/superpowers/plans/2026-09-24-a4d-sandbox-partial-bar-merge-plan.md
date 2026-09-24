# A4d — a partial Tradier-sandbox bar no longer wins the intraday merge (plan)

Date: 2026-09-24. Planned against main at `5726e12`. First of the four A4c follow-ups locked in decision
`A4C-FOLLOWUPS-LOCKED-2026-09-24` (item 1, re-graded ABOVE the gate): "a sandbox Tradier bar still inside the
feed-lag window must not overwrite yfinance's complete bar. Fixes every consumer at once."

**Kenneth, 2026-09-24 (asked before planning, the no-yfinance case):** *keep the partial bar only if it is the
newest bar.* When no other source has that timestamp, the partial sandbox bar is kept while it is the newest bar
of the merged series (it is then the forming candle, which `candles[-2]` and the completed-bars helpers already
skip); if any newer bar sits after it, it is dropped. A partial bar never sits behind a newer bar.

**Revision after plan round 1** (12 findings, all taken; see §8). The main change: the partial bar is now the
newest sandbox bar **and** it must be inside a (generous) feed-lag window, which matches the locked wording
exactly. Round 1 showed the "newest only" test of the first draft would drop a *complete* stale bar.

---

## 1. The defect, verified against today's tree

`fetch_intraday_candles` (`backend/app/data/market.py`) merges yfinance → IBKR → Tradier, and Tradier
overwrites every other source on a timestamp conflict (`merged.update(... tradier_rows)  # Tradier overwrites
all`). Tradier timesales serves `1min`/`5min`/`15min` (`_TRADIER_INTRADAY_INTERVALS`, `market.py:203`), fetched
with `session_filter=all`. yfinance is fetched without `prepost`, so it has regular-session bars only, and it is
real time. IBKR is fetched only for `1h`/`4h`/`daily`/`weekly` (`market.py:397`), a set disjoint from Tradier's,
so **in production IBKR and Tradier never meet in one merge**; the only conflict that matters is Tradier vs
yfinance.

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
condition tests its close, and the notification prints it (`"candle": closed_candle`,
`backend/app/routers/chart_alerts.py` ~941).

On `5min`/`1min` the partial bar sits at `[-3]` or deeper (yfinance supplies the newer bars). It then corrupts
indicator values and structure signals rather than the closed candle. Every other consumer of these intervals
also reads it: the stock scan's 15min strategy bars (`stock_scan.py` 399/726/761), `scan.py` 586, the
auto-trader's intraday regime (`auto_trader.py:912-913`,
`completed_intraday_bars(fetch_intraday_candles(symbol, "15min", 55))`), the regime router, composite watches
and the strategy-watch evaluator. The fix at the merge fixes all of them.

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

Applies **only when the Tradier base this fetch used is the sandbox**. With the live base, the newest Tradier
bar is forming just as yfinance's is, and today's precedence is unchanged.

Let P be the Tradier row with the greatest `time` (by value, not list position), `span` the interval in seconds
(60/300/900), and `fetch_start` the wall clock when `fetch_intraday_candles` began. P is *presumed partial* when

    P.time + span + TRADIER_SANDBOX_FEED_LAG_SECONDS + PARTIAL_BAR_SLACK_SECONDS > fetch_start

with `PARTIAL_BAR_SLACK_SECONDS = 900` (a new module constant beside the A4b one). That is "still inside the
feed-lag window" of the locked decision, with a slack of one more feed lag.

1. Every other Tradier row, and P when it is not presumed partial, overwrites yfinance exactly as today.
2. A presumed-partial P is merged only into a timestamp that holds **no finite bar** from another source. If
   yfinance (or IBKR) has a finite bar at P's timestamp, that bar stays.
3. If P was merged under rule 2 and it is **not** the newest bar of the final, finite-filtered, sorted result,
   it is dropped.

**Why the newest sandbox row AND a window, not either alone.**
- A window alone flags every bar of the last 15 minutes. On `1min` that is up to 15 bars, 14 of them complete; in
  extended hours (no yfinance) rule 3 would then drop 14 complete bars. Taking only the newest row flags one bar
  at most.
- The newest row alone (the first draft) flags a *complete* bar when the sandbox is stale: it serves nothing for
  today, returns a short range, or simply stops. If that bar is an extended-hours bar yfinance lacks and yfinance
  has newer bars, rule 3 would drop a complete bar and leave a gap. The window keeps a stale P under today's
  precedence.
- The slack covers a sandbox that runs somewhat over 900s behind. Only a sandbox more than 30 minutes behind
  would let a partial bar past the window, and then it behaves exactly as today.

The newest sandbox bar is the only bar that can be partial, whatever the exact delay:
- Regular session: P is partial and inside the window; yfinance has a complete bar at P's timestamp, so rule 2
  keeps yfinance's.
- Pre-market and after-hours (04:00-09:30, 16:00-20:00 ET, fetched because of `session_filter=all`): P is
  partial and yfinance does not have it (no `prepost`). Rule 2 merges it, and it is the newest bar, so rule 3
  keeps it as the forming candle — Kenneth's decision.
- Overnight and weekends: P is complete and outside the window, so today's precedence applies.

Beyond the letter of the decision, only one thing changes: a complete P that is still inside the window (e.g.
the 15:45 bar in the minutes after the close) yields to yfinance's bar at the same timestamp. Both are complete,
so nothing is lost; it is the existing yfinance baseline.

## 3. The change — `fetch_intraday_candles` only

A new helper `_merge_tradier_rows(merged, tradier_rows, *, on_sandbox, span, fetch_start) -> int | None` does the
Tradier step and returns the timestamp rule 3 must police (or `None`). Sketch:

```python
fetch_start = _time.time()                            # first line of fetch_intraday_candles
token, base = get_tradier_creds()                     # read ONCE; the request uses this base and token
on_sandbox = _is_sandbox_base(base)
...
merged: dict[int, dict] = {}
merged.update(yf); merged.update(ibkr)                # unchanged
partial_ts = _merge_tradier_rows(merged, tradier_rows, on_sandbox=on_sandbox,
                                 span=_INTERVAL_COMPLETION_SECONDS[interval], fetch_start=fetch_start)
result = sorted(finite(merged.values()), key=time)    # unchanged catch-all
if partial_ts is not None and result and result[-1]["time"] != partial_ts:
    result = [b for b in result if b["time"] != partial_ts]

def _merge_tradier_rows(merged, rows, *, on_sandbox, span, fetch_start):
    if not rows:
        return None
    newest = max(rows, key=lambda b: b["time"])
    partial = on_sandbox and (newest["time"] + span + TRADIER_SANDBOX_FEED_LAG_SECONDS
                              + PARTIAL_BAR_SLACK_SECONDS > fetch_start)
    merged.update({b["time"]: b for b in rows if not (partial and b is newest)})
    if not partial:
        return None
    held = merged.get(newest["time"])
    if held is not None and _finite_ohlc(held):
        return None                                   # another source's finite bar stays
    merged[newest["time"]] = newest
    return newest["time"]
```

- **One credential read.** Today the fetch calls `get_tradier_creds()` for the token, `_tradier_base()` for the
  URL and `_headers()` for the header: three separate reads. The fetch reads `token, base` once and uses them
  for the request, and `on_sandbox` is derived from that same `base`. So the policy cannot disagree with the base
  the rows came from if Settings changes mid-fetch.
- **`_is_sandbox_base(base)`** is new and holds the substring test (`"sandbox.tradier.com" in base`, so a
  trailing slash still counts). `intraday_feed_lag_seconds` is refactored to call it, so the A4b key has one
  source. Its fail-closed branch (900 when reading the base raises) stays in `intraday_feed_lag_seconds`; in the
  merge, the base is already in hand, so there is no unknown-base case.
- The finite check at rule 2 (`_finite_ohlc(held)`) matters: yfinance does `dropna` but not `inf`. Without it, a
  non-finite yfinance bar at P's timestamp would block P and then be dropped by the catch-all, so the timestamp
  would vanish. Today Tradier's finite bar fills it.
- Rule 3 runs **after** the finite catch-all, so "newest bar" means the newest bar a consumer will see.
- `span` comes from the existing `_INTERVAL_COMPLETION_SECONDS` (A4c, `market.py` ~518), not a new map — the helper is only reached with rows for
  `1min`/`5min`/`15min`, all of which it covers. `fetch_start` uses the module's own time source (the local `import time as _time` pattern already used in `market.py`), and tests patch that.
- The merge log line gains the count of presumed-partial sandbox bars yielded or dropped (0/1), at `info`, as it
  is today.
- **Stale comments corrected in the same change:** the `fetch_intraday_candles` docstring ("Tradier bars take
  precedence on timestamp conflicts", `market.py:351`) gains the sandbox exception. The A4b comment above
  `TRADIER_SANDBOX_FEED_LAG_SECONDS` (`market.py:459-461`, "Tradier bars win the merge") and the
  `intraday_feed_lag_seconds` docstring are annotated: after A4d that holds only for a kept partial bar out of
  hours, and the open question (§5.2) asks whether to narrow the lag.
- The comment `# Tradier overwrites all` must **not** be carried onto the live-base line: it is the phase's
  former defect marker. The state probe moves to a presence probe on `def _merge_tradier_rows(` (see §7).
- Nothing else changes. `completed_intraday_bars` keeps its sandbox lag (see §5.2), and the chart cache and
  every consumer are unchanged.

## 4. Consequences

- `15min` chart rules on the sandbox: `candles[-2]` is yfinance's complete bar in the regular session. Price
  conditions and notifications carry the right close.
- `5min`/`1min`: indicators and structure no longer see a partial bar behind newer bars.
- Pre/after-hours on the sandbox: unchanged. The partial bar is the newest, the forming candle.
- Overnight/weekend, a stale sandbox, the live base, and yfinance-only (no token): unchanged.
- The stock scan's intraday strategy bars (VWAP and others) and the auto-trader's intraday regime: in regular
  hours the partial bar is **replaced** by yfinance's complete bar at the same timestamp. It is removed only in
  the rare case that yfinance lacks that timestamp while having a newer bar. No lag is added.

## 5. Decisions and residuals

1. **The no-yfinance case:** Kenneth's "keep only if newest" (above).
2. **Logged, not changed — the A4b sandbox lag in `completed_intraday_bars` is now conservative by up to one
   extra bar when yfinance answered.** Its rationale ("Tradier bars win the merge") no longer holds for the
   partial bar. It still holds in pre/after-hours (the newest bar can be the kept partial sandbox bar), so the
   lag is still needed there. Dropping it only when yfinance covered the tail would need the merge to report
   that. Already logged for Kenneth as an open question; not in this phase.
3. **Logged, not changed — the chart cache can skip a closed candle.** `chart_cache._TTL_BY_INTERVAL` holds a
   `15min` snapshot for 30 minutes (and `1min`/`5min` for 15). The scheduler polls every ~60s but sees the same
   snapshot until it expires, so `candles[-2]` can jump by two 15-minute bars and one closed candle is never
   evaluated. A4d makes each evaluated candle right; it does not make every candle evaluated. Logged as a new
   open question for Kenneth; not in this phase.
4. **Pre-existing, noted:** a Tradier row whose `time` fails to parse is kept with `time = 0` (a 1970 bar). It
   is out of scope. It can only become P if every row failed to parse, and then it is far outside the window, so
   the rule is inert.

## 6. Tests — new `backend/tests/test_a4d_sandbox_partial_bar_merge.py`

Stubs: Tradier via `httpx.get` (as `test_market_data_fixes.py` does); yfinance via `_fetch_intraday_yf`; the
token and base via `get_tradier_creds` returning a token plus the sandbox or the live base; the wall clock via the time source `fetch_start` reads (§3),
so `fetch_start` is a fixed ET instant on a weekday. Fixture rules:
- Tradier and yfinance stamps are built from the **same ET wall time**: Tradier as the naive `"YYYY-MM-DD HH:MM"`
  string, yfinance as `int(datetime.fromisoformat(s).replace(tzinfo=ZoneInfo("America/New_York")).timestamp())`,
  as `test_market_data_fixes.py:285-287` does.
- At every shared timestamp, the Tradier and yfinance closes **differ**, so each assertion shows which source
  won.

Cases:
1. Sandbox, `15min`, the §1 table (`fetch_start` 10:20): the 10:00 bar is yfinance's close; 09:45 is Tradier's
   (older precedence unchanged); 10:15 is yfinance's. `result[-2]` is yfinance's 10:00 bar.
2. Sandbox, pre-market shape (`fetch_start` 08:20, yfinance ends the previous day at 15:45): P (08:00) has no
   counterpart and is the newest: kept, with Tradier's values.
3. Sandbox, P has no counterpart but yfinance has a later bar: P is absent from the result, every other bar
   present.
4. Live base (`api.tradier.com`), the §1 shape: the 10:00 bar is Tradier's (today's behaviour).
5. Sandbox, Tradier rows delivered **out of order**, P first in the list: P is chosen by the greatest `time`.
6. Sandbox, Tradier returns nothing: the yfinance series is returned unchanged.
7. Sandbox, **stale P** (`fetch_start` Monday 10:20; the sandbox's newest bar is Friday 19:45, yfinance has
   Monday bars): P is outside the window, kept, and every Friday Tradier bar keeps today's precedence.
8. Sandbox, window edge: P exactly at the window boundary on `1min` (`P.time + 60 + 1800 == fetch_start` is
   not presumed partial; one second less is).
9. Sandbox, yfinance's bar at P's timestamp is **non-finite** (`inf` close): P fills the timestamp (rule 2's
   finite check), the result has no gap.
10. Sandbox, yfinance's only bar newer than P is non-finite: after the catch-all P is the newest, so it is kept
    (rule 3 runs on the filtered result).
11. Non-Tradier interval (`30min`) on the sandbox: the result equals the plain yfinance series (rule inert,
    `_merge_tradier_rows` never sees rows).
12. `_is_sandbox_base`: a trailing slash on the sandbox base counts; `intraday_feed_lag_seconds` still returns
    900/0 as before (A4b's tests stay green).
13. The merge log line reports 1 on case 1 and 0 on case 4 (`caplog`).
14. End to end: `chart_alert_scheduler._tick` with one enabled `15min` rule in an in-memory SQLite session
    (`sched.AsyncSessionLocal` patched, as `test_a4c_user_alert_completed_bars.py` does),
    `chart_cache._INTRADAY_CACHE` and `sched._last_seen_candle` cleared, `compute_structure` stubbed,
    `evaluate_and_notify_for_symbol` patched at `app.routers.chart_alerts` (it is imported inside `_tick`), and
    sources stubbed as in case 1. The `closed` passed in is yfinance's 10:00 bar.

**Existing test at risk:** `test_tradier_overrides_ibkr_on_conflict` (`test_market_data_fixes.py:274-326`)
pins only `TRADIER_TOKEN`; the base comes from the credential store or `TRADIER_BASE_URL` (env, and `.env` via
`load_dotenv()` in `app/main.py`). Its single bar is dated 2023, far outside the window, so the rule cannot touch
it. The build still pins the live base there, so the test does not depend on the environment. Before counting,
check that no other existing test runs on the sandbox base by accident: the credential store in the test
environment, and `TRADIER_BASE_URL` from `.env` or the environment.

Mutations before the round, each of which must turn at least one test red:
- restore Tradier-overwrites-all on the sandbox (1);
- remove rule 3 (3);
- apply the rule on the live base (4);
- choose P as `tradier_rows[-1]` (5);
- keep P over another source's finite bar (1);
- drop the window test (7);
- drop the slack (8);
- drop the finite check at rule 2 (9);
- run rule 3 before the catch-all (10);
- derive `on_sandbox` from a second `_tradier_base()` read instead of the fetch's own base (a case where the
  stubbed store would answer differently on a second call: add it to 1 as a `side_effect` sequence).

Account for every change against main's backend count.

## 7. Done means

Full backend suite green and reconciling (frontend untouched). `state.py` exit 0 with phase
`A4D-SANDBOX-PARTIAL-BAR-MERGE` flipped to shipped. Its verify probe is changed **now**, at the plan, from the
defect marker `# Tradier overwrites all` (which could be "fixed" by deleting a comment) to kind `absent` on
`def _merge_tradier_rows\(` in `backend/app/data/market.py`; the behavioural pin is the new test file. The
adversarial round on the code is clean at `audit_rule`'s gate. Then merge.

## 8. Plan round 1 (2026-09-24): 12 findings, all taken

1. Newest-row test departed from the locked "inside the feed-lag window" wording and dropped a complete stale
   bar → combined test, newest row AND generous window (§2), tests 7-8.
2. IBKR never meets Tradier in production; `test_tradier_overrides_ibkr_on_conflict` depends on the env base →
   stated in §1; that test is inert under the window, pinned to the live base anyway; the `.env` check added (§6).
3. The defect-marker probe could be satisfied by deleting a comment → presence probe on `_merge_tradier_rows`
   (§7), comment not reused (§3).
4. A non-finite yfinance bar at P's timestamp made the timestamp vanish → finite check at rule 2, test 9.
5. "Out of hours the newest sandbox bar is complete" was false for pre/after-hours → §2 corrected.
6. "Lose a partial bar from the middle" was wrong (it is replaced); `auto_trader` missing from consumers; wrong
   `chart_alerts.py` path → §1, §4 corrected.
7. Stale docstring and A4b comments → corrected in the same change (§3).
8. `on_sandbox` read separately from the fetch's base → single credential read, `_is_sandbox_base` (§3).
9. The end-to-end test was under-specified → test 14.
10. Fixture stamps and distinct closes → §6 fixture rules.
11. No non-Tradier-interval, catch-all-order or log-count test → tests 10, 11, 13.
12. Chart-cache TTL skips closed candles → logged as an open question (§5.3), not in this phase.
