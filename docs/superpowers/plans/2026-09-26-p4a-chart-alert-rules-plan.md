# P4a — Chart alert rules: sync, toggle, missed candles — plan

Package: P4a in `docs/superpowers/plans/2026-09-25-work-packages.md`. Decisions: BACKLOG-DECISIONS-2026-09-25 Q1 (syncRules proposal YES), Q14 (the chart-alert check must not skip a closed candle), and FOLLOWUPS-QUEUE-2026-09-25 (toggle and last_triggered_at use PATCH). Phases: ALERTS-SYNC-LOCAL-ONLY-COMPOSITE, ALERTS-RULE-TOGGLE-PATCH, plus the new P4A-CHART-ALERT-RULES entry that carries the package's rounds.
Branch: `claude/exciting-wozniak-dqdqy8`, restarted from main `9288592` (P2 merged). Claim: P4A-CHART-ALERT-RULES.

**Re-check against current code:** every item below was re-read at `9288592` and is still open; each cites the line it was verified at.

**Owned files touched:** `frontend/lib/chartAlertStore.ts`, `frontend/app/(frame)/alerts/page.tsx`, `frontend/components/organisms/ChartWorkspace/index.tsx` (the two last_triggered_at stamps only), `backend/app/data/chart_cache.py`, `backend/app/services/chart_alert_scheduler.py`, `backend/app/services/alert_evaluator.py`, `backend/app/services/market_session.py` (one docstring), their tests. `backend/tests/test_auto_trader.py`: one test's clock patch (the A4g entry P4a carries).
**Read, not edited:** `backend/app/data/market.py` (`_INTERVAL_COMPLETION_SECONDS`, `_TRADIER_INTRADAY_INTERVALS`, `intraday_feed_lag_seconds`), `backend/app/routers/chart_alerts.py` (POST/PUT/PATCH already exist, :553/:604/:650).
**Not touched:** CompositeAlertDialog and market.py interval aliases (W2-INTERVAL); composite_trigger_evaluator.py (P4b).

## A. Frontend — rules reach the server intact, and a toggle cannot be lost

**A1 (Q1). One body builder for POST and PUT.** `pushRuleToAPI` (chartAlertStore.ts:60-73) sends only `group`, so a local-only COMPOSITE rule re-POSTed by `syncRules` (:221) is created as an empty standard rule: a dead alert under the user's rule name. New `ruleBodyForApi(rule)` returns the composite body (`rule_type: 'composite', composite_def`) or the standard body (`group`), plus the shared fields, exactly as `putRuleToAPI` builds them today (:81-91). POST adds `id`. Both `pushRuleToAPI` and `putRuleToAPI` use it.
- Tests: a composite local-only rule re-POSTs with `rule_type` and `composite_def` and no `group`; a standard one with `group`; PUT bodies unchanged (pinned).

**A2 (Q1). A refusal keeps the rule and says so.** `pushRuleToAPI` returns an outcome: `'ok'` (2xx or 409 already exists), `'refused'` with the server's `detail` (any other 4xx), `'offline'` (network error or 5xx). `syncRules` keeps every local-only rule in the merged list as today, and records refusals in a new NON-persisted map `unsavedRules: Record<ruleId, detail>` (not in `partialize`, so no persist version bump; rebuilt by every `syncRules`; an id that later POSTs ok is removed). `addRule` records a refusal the same way. The Alerts page shows "Not saved to server: {detail}" in caution tone under the rule's name.
- Why a map, not a field on the rule: `AlertRule` is persisted, so a field would need a migration, and a stale mark would outlive the refusal it describes.
- Tests: a 422 on re-POST keeps the rule locally and sets the mark with the detail; 409 and 201 set no mark; a network error sets no mark; the page renders the mark.

**A3 (toggle PATCH).** New store action `setRuleEnabled(id, enabled)`: sets `enabled` locally and sends `PATCH /alerts/rules/{id}` with `{ enabled }` only. The Alerts page toggle (page.tsx:575) uses it. The server's own interval / composite_def are never re-sent, so a stale local copy can neither be refused (the A4f-rules case: a local '1D' on a rule the server migrated to '5m' is a 422 on PUT, :618) nor overwrite the server. A 404 (the rule is local-only) changes nothing further: the next `syncRules` re-POSTs it with the current `enabled`.
- Tests: the toggle sends PATCH with exactly `{enabled}`, never PUT; a rule whose local interval differs from the server's is toggled without its interval being sent.

**A4 (last_triggered_at stamps).** New store action `stampRuleTriggered(id, at, { persist })`: sets `last_triggered_at` locally; with `persist: true` it sends `PATCH {last_triggered_at}`. ChartWorkspace's two call sites (index.tsx:380, :429) move to it:
- the WebSocket `alert_triggered` stamp (:380) uses `persist: false`: the backend already wrote `last_triggered_at` (chart_alerts.py:927) and the old full PUT from here could overwrite a server-side edit;
- the client-side evaluation stamp (:429) uses `persist: true`: nothing else writes it to the server.
- `updateRule` stays for AlertRuleBuilder's full edit (standard rules only; composite rules have no editor, page.tsx:581).
- Tests: the WS stamp sends nothing; the client-side stamp sends PATCH with exactly `{last_triggered_at}`.

## B. Backend — no closed candle is skipped (Q14), and a missed alert is not an exception

**B1 (Q14). The scheduler refetches when a new candle has closed.** Today `chart_cache` holds a 15min snapshot for 30 minutes (chart_cache.py:18-26) and the scheduler (chart_alert_scheduler.py:57-62) evaluates only `candles[-2]`, so `candles[-2]` can advance by two bars and one closed candle is never evaluated (open question "the chart cache can skip a closed candle").
- `get_intraday_with_fetched_at(..., refresh_on_close=False)`: with `True`, a cached entry is refetched when its newest bar is due to be complete in the feed's clock after the entry was fetched: `fetched_at < rows[-1].time + span + lag <= now`. `span` is `market._INTERVAL_COMPLETION_SECONDS[interval]`; `lag` is `intraday_feed_lag_seconds()` for `market._TRADIER_INTRADAY_INTERVALS`, else 0 (the same pair `completed_bars_for_interval` uses, market.py:633-638). Daily/weekly, an unknown interval, an empty or non-int `time` newest bar: no refresh rule (TTL only), as today.
- The overnight case costs nothing: a fetch after the last bar's close has `fetched_at` past the due instant, so no refetch until the next bar exists.
- The scheduler passes `refresh_on_close=True`. The chart WebSocket and `/chart/history` do not (unchanged); they benefit from the fresher entry.
- Tests: an entry fetched before its newest bar's due instant is refetched after it; one fetched after it is not; daily is not; the lag is honoured (a Tradier interval is not refetched until `span + lag`).

**B2 (Q14). The scheduler evaluates every closed candle it has not seen, oldest first.** A refresh cannot close every gap: a 1min rule with a 60s tick, a delayed feed, or a slow tick can still move `candles[-2]` by more than one bar.
- Per `(symbol, interval)`, the closed candles are `candles[:-1]`. Those with `time` greater than `_last_seen_candle[key]` are evaluated in time order. For the newest (`candles[-2]`) the call is exactly today's (full `candles`, including the forming bar). For an older one the call receives `candles[:i+1]` — the candle is the last bar — for both `closed_candle_structure` and `evaluate_and_notify_for_symbol`, so no regime model, indicator or structure reads a bar after it.
- At most 3 candles per pair per tick (the newest 3); more than that logs one WARNING naming how many were not evaluated (after downtime, hours-old alerts are noise). First sighting of a key evaluates only the newest, as today. `_last_seen_candle` is set to the newest evaluated time.
- Residuals, stated: `_last_seen_candle` is in memory, so a restart evaluates only the newest; a bar that appears later with an OLDER time than one already evaluated (A4d's pre-market bar) is still not evaluated; an older candle's VWAP confirmation sees no forming bar (it did not exist then); the intraday rule's daily bars (`get_bars`) are not truncated.
- Tests: two candles closing between ticks are both evaluated, oldest first, the older one with the truncated list; the newest keeps the full list; 5 missed → 3 evaluated + one WARNING; first sighting → newest only.

**B3 (open question A4e: crosses with a None previous value).** `_evaluate_condition` (alert_evaluator.py:224-232) compares `series[idx-1]['value']` without a None check; on the first post-warm-up bar that raises TypeError, `evaluate_rules` (:371) does not catch it, and the whole batch for that symbol/interval is skipped. Fix: a None previous value is "not met". Test: crosses_above and crosses_below on the first post-warm-up bar return not met, and the rest of the batch still evaluates.

**B4 (open question A4g round 2, the items the package lists).**
- (1) Test: two forming copies of one session at the tail (IBKR and yfinance stamps) are both dropped (pins the `while`, market_session.py:270).
- (2) Test: two undatable bars at the tail — only the last is dropped, the walk stops at the second (pins the documented "that one bar only").
- (6) The `todays_bar_is_unclosed` docstring's "the one production call site (the end-trim) passes no argument" (market_session.py:104-106) is corrected: the chart path passes an aware instant through `completed_session_bars` → `last_session_close`.
- (7) Test: `market_session._NYSE_CLOSE` equals the upper bound of `strategy_watch_scheduler._market_open` (16:00 open, 16:00:01 closed).
- (8) `test_guard_i_call_site_consults_the_real_clock` (test_auto_trader.py:4077) also freezes `auto_trader.datetime`; `_clock_at`'s docstring says which modules it is installed in.
- Items (3), (4), (5), (9), (10) are notes, not fixes; the entry stays open for them, annotated.

## C. State file

Phase `P4A-CHART-ALERT-RULES` (rounds counted here). ALERTS-SYNC-LOCAL-ONLY-COMPOSITE and ALERTS-RULE-TOGGLE-PATCH ship with it (their defect markers go). The open questions for A4e crosses and "the chart cache can skip a closed candle" close with evidence; the A4g round-2 entry is annotated.

## D. Verification

Backend `cd backend && .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit && npx jest`; `python3 scripts/state.py` exit 0. A mutation per item, run by hand and recorded in the phase note.
