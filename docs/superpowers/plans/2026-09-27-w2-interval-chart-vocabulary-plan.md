# W2-INTERVAL — One interval vocabulary (the chart's spellings) — plan

Package: W2-INTERVAL in `docs/superpowers/plans/2026-09-25-work-packages.md`. Phase: INTERVAL-SPELLING-CHART-VOCABULARY.
Decisions: FOLLOWUPS-QUEUE-2026-09-25 (1) ("one vocabulary, the chart's spellings, with stored '5m'/'15m' rules and watches migrated") and P4B-FOLLOWUPS-2026-09-26 (2) ("dialog saves 5min/15min/30min, stored rules+watches migrate once, D5 read-side map deleted"). Backlog entry: open_questions[5] (LOGGED BY A4f-rules).
Branch: `claude/clever-planck-rpz8yh`, restarted from main `d349a18` (P3c merged; P4a and P4b merged earlier, so the package's "start only after P4a and P4b" holds). Claim: INTERVAL-SPELLING-CHART-VOCABULARY.

**Re-check against current code (main `d349a18`):** every item below was re-read there and is still open.

## 0. The problem, in one paragraph

CompositeAlertDialog offers `5m/15m/30m/1h/4h` (index.tsx:232) and defaults an HMM_intraday rule or watch to `'5m'` (:218). The chart's intervals are `1min/5min/15min/1h/4h/1D/1W` (chartStore.ts:6). A rule stored as `'5m'`:
- is never evaluated from the chart tab: `evaluate_and_notify_for_symbol` selects `AlertRuleModel.interval == interval` with the chart's spelling (chart_alerts.py:869), and ChartWorkspace lists rules with `r.interval === interval` (index.tsx:405);
- is evaluated only by the background scheduler, whose `get_intraday_with_fetched_at(symbol, '5m')` passes `'5m'` through `normalize_interval` unchanged, so `fetch_intraday_candles` skips Tradier (`'5m'` is not in `_TRADIER_INTRADAY_INTERVALS`, market.py:217) and reads the yfinance-only series, where a `'5min'` rule reads the Tradier-merged one;
- is labelled `'5m chart'` in notifications (`_INTERVAL_LABELS` has no `'5m'`, chart_alerts.py:288-291).
Composite watches store the same short spellings; P4b's read-side map (`composite_trigger_evaluator._WATCH_TO_FETCH_INTERVAL` / `watch_fetch_interval`, :52-61) translates them at fetch time so a watch reads the rule path's series. The A4f migrations (chart_alerts.py:205-253, strategy_watch_store.py:57-74) write `'5m'` too.

## 1. One spelling map, in market.py

**1a.** New in `backend/app/data/market.py`, next to `_INTERVAL_ALIASES`:
```python
# W2-INTERVAL (decision FOLLOWUPS-QUEUE-2026-09-25 (1)): the chart's spelling of an
# interval is the one stored on composite rules and watches. The short forms the
# CompositeAlertDialog used to save map to it. Deliberately NOT folded into
# normalize_interval: that feeds every fetch, and '15m' callers elsewhere
# (regime.py, strategy_engine) would silently switch series.
_CHART_SPELLING: dict[str, str] = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "60m": "1h"}

def chart_interval(interval):
    """The chart's spelling of `interval`; anything else (incl. non-strings) unchanged."""
    return _CHART_SPELLING.get(interval, interval) if isinstance(interval, str) else interval
```
- `normalize_interval`, `_YF_INTERVAL_MAP`, `_INTERVAL_COMPLETION_SECONDS`, `_TRADIER_INTRADAY_INTERVALS` are unchanged. The chart spellings already fetch correctly (`_YF_INTERVAL_MAP['5min'] = '5m'` is "the scheduler's yfinance fetch still maps them"), and the short spellings keep working for any caller that still passes them.
- Tests: every key maps to its chart spelling; `'1h'`, `'4h'`, `'1D'`, `'1W'`, `'5min'`, an unknown string and `None` pass through unchanged.

## 2. Every write stores the chart spelling

**2a. Rules — POST and PUT** (chart_alerts.py `create_rule` :553, `replace_rule` :604). First line after loading/validating the body: `interval = chart_interval(body.interval)`, and every later use in the handler reads `interval` (the `hmm_intraday_interval_error` call, the PUT's `_stored_pair` comparison, `row.interval =`, the model constructor). All rule types, not only composite: a standard rule is only ever created from the chart with its spelling, so this is a no-op for them, and applying it to both keeps one rule. Effect: a local-only composite the frontend `syncRules` re-POSTs with a stale `'5m'` (chartAlertStore.ts:281) is stored as `'5min'`; a stale PUT of `'5m'` onto a migrated `'5min'` row compares equal and is accepted (not a 422).
- The PATCH endpoint does not take `interval` (unchanged).
- Tests: POST composite `'5m'` → stored and returned `'5min'`; POST `'1h'` unchanged; PUT `'15m'` onto a `'15min'` HMM_intraday row → 200, stored `'15min'`; POST HMM_intraday on `'1D'` still 422.

**2b. Watches** (`strategy_watch_store.add_composite_watch`, :178). `interval = chart_interval(interval)` before the HMM_intraday check and the entry build. `CompositeWatchCreate.interval` default `"1D"` unchanged.
- Test: add composite `'15m'` → stored `'15min'`.

**2c. The A4f migrations write the chart spelling.** `migrate_hmm_intraday_rule_intervals` sets `'5min'` (chart_alerts.py:240) and `_migrate_hmm_intraday_intervals` sets `'5min'` (strategy_watch_store.py:71); their log texts and docstrings say `'5min'`. Their tests are updated to `'5min'` (tests/test_a4f_rules_hmm_intraday_interval.py, tests/test_a4f_hmm_intraday_interval.py).

**2d. The refusal message** in `hmm_intraday_interval_error` (composite_trigger_evaluator.py:37) and `add_composite_watch` (strategy_watch_store.py:196) reads `(e.g. 5min, 15min, 1h)`. The test pinning that both messages are equal stays.

## 3. Stored rows migrate once, reported

**3a. Rules.** New `migrate_rule_interval_spellings(session_factory=None) -> list[dict]` in chart_alerts.py, beside the A4f one and built the same way:
- selects every `AlertRuleModel` with `interval IN ('1m','5m','15m','30m','60m')` (the `_CHART_SPELLING` keys, read from the map, not re-typed) -- every user_id, enabled or not, composite or standard;
- sets `row.interval = chart_interval(row.interval)`; nothing else changes. `name` is NOT annotated and `condition_state` is NOT reset: the rule means the same bars' width on the same symbol; only the spelling and hence the feed source change. (A4f reset the sustain clock because the interval itself changed from daily to intraday.)
- one commit for the batch; a row that raises is logged and skipped (as A4f). Idempotent: a migrated row no longer matches the SELECT.
- reported: one WARNING `"W2-INTERVAL: migrated %d alert rule(s) to the chart's interval spelling: [id SYMBOL '5m'->'5min', ...]"`, and the list is returned.
- Called from `run_chart_alert_scheduler`, in the same `if not rules_migrated:` try block, AFTER `migrate_hmm_intraday_rule_intervals` (so a row that function moves is already `'5min'`; any legacy `'5m'` it did not produce is caught here). `rules_migrated` becomes true only when both succeed; a failure retries both next iteration (both are idempotent).
- Scheduler markers: `_last_seen_candle` / `_last_newest_bar` are keyed by `(symbol, interval)`. The old `(sym, '5m')` key is pruned on the next tick (`_prune_markers`, no enabled rule has it), the new `(sym, '5min')` key starts as a first sighting (newest closed candle only). No candle is evaluated twice under two keys because the migration runs before the first tick of a server start and the markers are in-memory only.
- Tests (in-memory SQLite session factory, as the A4f tests): `'5m'`/`'15m'`/`'30m'`/`'1m'`/`'60m'` rows migrate to their chart spelling and are listed; `'5min'`, `'1h'`, `'1D'` rows are untouched; name, enabled, rule_json and condition_state are byte-identical after; a second call migrates nothing; the scheduler calls both migrations before `_tick`, and retries both after a failure of the second.

**3b. Watches.** In `StrategyWatchStore.load()`, after `_migrate_hmm_intraday_intervals`, a new `_migrate_interval_spellings(self._watches) -> list[tuple]` maps `interval` through `chart_interval` for every entry whose `interval` is a `_CHART_SPELLING` key (composite and strategy watches alike; strategy watches carry `'1D'`, so in practice only composites match). No other field changes; `interval_migrated_from` is not touched (an A4f-migrated watch keeps its `'1D'` record). Reported with one WARNING listing `(id, symbol, old->new)`. Persisted by the same guarded `self.save()` A4f uses (both migrations' lists combined decide whether to save; a failed save logs ERROR and leaves the migration in memory, retried on the next save -- the A4f posture, plan F-1).
- Tests: a YAML with `'5m'`/`'15m'` composite watches loads as `'5min'`/`'15min'` and the file is rewritten; `'1h'`/`'1D'` untouched; `last_state` and `interval_migrated_from` unchanged; a second load migrates nothing and does not rewrite; a failing save does not raise from `load()`.

## 4. The read-side map is deleted

Per P4B-FOLLOWUPS-2026-09-26 (2): delete `_WATCH_TO_FETCH_INTERVAL` and `watch_fetch_interval` (composite_trigger_evaluator.py:52-61) and their uses:
- `strategy_watch_evaluator._evaluate_composite_watch` (:254, :262): `fetch_iv = watch_fetch_interval(interval)` becomes the stored `interval` itself (every later `fetch_iv` use keeps its meaning: after 2b/3b the stored value is the chart spelling).
- `routers/composite_watch.get_regime_snapshot` (:80-85): fetch with `interval` directly; its query default `"15m"` becomes `"15min"`.
- Why deleting is safe: after 3b every loaded watch is in chart spelling (load runs the migration before any evaluation, in memory even if the save fails), and after 2b every new one is. The only remaining way to hold `'5m'` is a hand edit of strategy_watches.yaml while the server runs, which the running store does not re-read anyway.
- `_VWAP_SIGNAL_INTERVAL` (composite_trigger_evaluator.py:186-189) keeps both spellings: it maps to the signal's own allow-list, and keeping the short keys costs nothing.
- Tests: `tests/test_p4b_4h_history.py`'s `watch_fetch_interval` tests are replaced by one pinning that the evaluator and `/regime-snapshot` pass the stored/query interval to `fetch_intraday_candles` unchanged (`'5min'` in → `'5min'` fetched), plus a grep-style test that `watch_fetch_interval` no longer exists.

## 5. Labels

`_interval_label` (chart_alerts.py:294) looks up `_INTERVAL_LABELS.get(chart_interval(interval), ...)`, and `_INTERVAL_LABELS` gains `'30min': '30-minute chart'`. So a notification for a `'30min'` rule says "30-minute chart", and a history entry still carrying `'5m'` (history rows are records and are NOT migrated) is labelled "5-minute chart" too.
- Test: `'5m'`, `'5min'` → "5-minute chart"; `'30min'` → "30-minute chart"; unknown `'2h'` → "2h chart".

## 6. Frontend

**6a. CompositeAlertDialog** (index.tsx): options `['5min', '15min', '30min', '1h', '4h']`, displayed as their value; the HMM_intraday default is `'5min'`. The rule and watch POSTs carry what the select shows (A4f's invariant holds).
**6b. api.ts** `getSymbolRegimeSnapshot`'s default interval `'15m'` → `'15min'`.
**6c. No persisted-store migration.** `bamendjou:alerts` can hold a local-only rule with `'5m'`; `syncRules` re-POSTs it, 2a stores it as `'5min'`, and the next `syncRules` replaces the local copy with the server's (server rules win for known ids, chartAlertStore.ts:289). Until that next sync the local copy shows on no chart tab, as today. No version bump.
- Tests: CompositeAlertDialog.test.tsx -- the select offers exactly the five chart spellings; choosing HMM_intraday selects `'5min'`; a watch/rule created without touching the select posts `'5min'`; the snapshot request carries `'5min'`. Existing `'5m'`/`'15m'` fixtures in AlertRuleBuilder/alerts-page tests are updated only where they model a dialog-saved rule.

## 7. What changes for the user (to state in the merge record)

- Intraday composite rules become visible and evaluated on the matching chart tab (5min, 15min). **`'30min'` stays scheduler-only**: the chart offers no 30-minute tab (chartStore.ts:6), unchanged by this package.
- Migrated `'5m'`/`'15m'` rules and watches read the Tradier-merged series (extended hours included, the sandbox feed lag applied) instead of the yfinance regular-hours series. For watches this is what they already read since P4b D5; for rules it is new, and it is the series a chart-spelled rule has always read. An HMM fitted on the merged series can give a different state from the old one; that is the decided parity, not a defect.
- `'30m'` rules/watches: `'30min'` is not a Tradier interval, so they stay on yfinance; only the spelling changes.

## 8. Out of scope (logged, not built)

- `normalize_interval` does not alias `5m→5min` (1a): other `'15m'` callers (regime.py:348, strategy_engine.py:1006, stock_scan.py:185) keep their series.
- `AlertHistoryModel.interval` rows are not migrated (records of what fired, under the spelling of the day). The history `?interval=` filter (chart_alerts.py:729) therefore does not match old `'5m'` history under `'5min'`.
- Chart gaining a 30min tab.

## 9. Owned files

`backend/app/data/market.py` (1a only), `backend/app/routers/chart_alerts.py` (2a, 2c, 3a, 5), `backend/app/services/chart_alert_scheduler.py` (3a call site), `backend/app/services/strategy_watch_store.py` (2b, 2c, 2d, 3b), `backend/app/services/composite_trigger_evaluator.py` (2d, 4), `backend/app/services/strategy_watch_evaluator.py` (4), `backend/app/routers/composite_watch.py` (4), `frontend/components/organisms/CompositeAlertDialog/index.tsx`, `frontend/lib/api.ts` (one default), their tests; `docs/superpowers/PROJECT_STATE.json`.
**Not touched:** composite_trigger_evaluator.py's `_count_confirmations` (COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD); chart_alerts.py's composite bar-selection block and HMM history window (WATCH-RULE-BAR-PARITY); strategy_watch_evaluator.py's delivery/retry path (WATCH-UNDELIVERED-EVENT-RESEND); dispatch.py (P6).

## 10. Verification

- Backend: `cd backend && .venv/bin/python -m pytest -q` (full), plus the new/changed test modules named above.
- Frontend: `npm run typecheck`, `npm run test`.
- Mutations (each must fail at least one test): `_CHART_SPELLING['5m']` → `'5m'`; drop `chart_interval` from `create_rule`; drop it from `replace_rule`'s `_stored_pair` comparison only; drop the 3a call from the scheduler; drop 3b from `load()`; revert the dialog default to `'5m'`; revert the regime-snapshot default to `'15m'`.
- `python3 scripts/state.py`: the phase's defect marker (the dialog's `['5m', '15m', '30m', '1h', '4h']`) is gone.
