# A4f-rules — stored HMM_intraday composite RULES on '1D'/'1W' move to '5m'; the rules API refuses new ones

Branch `claude/hopeful-volta-ujru28`, off main `489202d` (A4f for watches merged at `f49446e`).
Builds decision **A4F-MIGRATE-LEGACY-RULES-TOO-2026-09-25** (PROJECT_STATE `decisions[0]`):
the same treatment as the watches. At backend startup each stored rule is moved to '5m'
once, every migrated rule is logged, and its name gets an "interval was 1D" note.

Starting point: the unmerged plan revision 2 on `claude/dazzling-ride-0unofk` (`3622046`,
§2b/§2e/§2f), re-based onto what main actually shipped. Main's A4f already has
`market.is_intraday_interval`, the dialog's '5m' default, and the watch-side
reject and migration (in `StrategyWatchStore.load()`). None of that is re-done here.

## 1. Verification (on main `489202d`, before planning)

**A stored HMM_intraday composite rule on '1D'/'1W' never fires.**
`evaluate_and_notify_for_symbol` (`app/routers/chart_alerts.py` ~:894-906) passes
`bars_intraday=[]` and `regime_bars_intraday=None` when `interval in ("1D", "1W")`. So
`evaluate_from_context_detailed`'s HMM_intraday branch logs
`HMM_intraday requested but no intraday bars supplied; skipping` (WARNING) and returns
not-fired on every tick. The rule is dead, which is the exact condition the decision covers.

**New ones can no longer come from the dialog**, since main's A4f defaults it to '5m'.
But `POST /alerts/rules` and `PUT /alerts/rules/{id}` accept the pair from any client,
and there's a second client in the frontend (§1, last paragraph).

**Only two paths evaluate rules**, and both go through `evaluate_and_notify_for_symbol`:
`chart_alert_scheduler._tick` (the background loop started in `lifespan`) and the chart
websocket (`routers/chart.py` ~:100).

**The Alerts page reads rules from localStorage.** `chartAlertStore` is `persist()`ed
(`'bamendjou:alerts'`, v2). `syncRules()` replaces local rules with the server's, but it is
called only from `ChartWorkspace` (~:257). The Alerts page's rules table
(`app/(frame)/alerts/page.tsx` ~:558) reads `useChartAlertStore().rules`. Its toggle calls
`updateRule` → `putRuleToAPI`, which re-sends the LOCAL `interval` and `composite_def` on
every PUT. So after a backend migration, a user who hasn't opened the chart since sees
'1D', and toggling there would PUT '1D' + HMM_intraday back onto a migrated rule.

## 2. The change

### 2a. One predicate (backend)

`app/services/composite_trigger_evaluator.py`:

```python
def hmm_intraday_interval_error(trigger_def: object, interval: object) -> str | None:
    """A4f-rules: the message to refuse a composite HMM_intraday definition on a
    non-intraday interval with, else None. Never raises: a non-dict trigger_def /
    primary means "no model" (other validation owns malformed bodies)."""
```

It returns `f"HMM_intraday needs an intraday interval (e.g. 5m, 15m, 1h), got {interval!r}"`,
the same wording as `StrategyWatchStore.add_composite_watch`, when
`primary.model == "HMM_intraday"` and `not market.is_intraday_interval(interval)`.
`strategy_watch_store._primary_model` stays where it is; only its three-line logic is repeated here.
Reason: the store must not import the evaluator (the evaluator imports market and
regime modules at call time; keep the watch store's import surface unchanged).

### 2b. The rules API refuses new bad pairs (422)

- **`POST /alerts/rules`**, `rule_type == 'composite'`: after the existing `composite_def`
  check, `err = hmm_intraday_interval_error(body.composite_def, body.interval)`, and if
  set, `HTTPException(422, err)`. No row is written. 422 matches this router's existing
  body-validation code. The watch router's 400 is its own convention and is unchanged.
- **`PUT /alerts/rules/{id}`**, `rule_type == 'composite'`: the check runs BEFORE any
  `row.*` assignment. It compares against the stored pair, meaning `row.interval` and the
  primary model read from `json.loads(row.rule_json)`. If that parse fails or the stored
  row is not composite, the pair counts as changed. **It rejects only when the new pair
  is invalid AND differs from the stored pair.** Why the exemption: if the startup
  migration failed (errors are logged, not fatal, §2c), a legacy '1D' rule must still be
  toggleable, renameable and deleteable rather than stranded. A PUT that sends a migrated
  '5m' rule back to '1D' changes the pair, so it is rejected. That covers the stale
  localStorage toggle in §1. DELETE and PATCH are untouched; PATCH only carries
  `enabled` and `last_triggered_at`.
- Standard rules are untouched: a `regime` condition with `model: HMM_intraday` inside a
  standard group is a different code path (A4c) and outside this decision.

### 2c. Stored rules are migrated before the scheduler's first tick

New `async def migrate_hmm_intraday_rule_intervals(session_factory=None) -> list[dict]`
in `app/routers/chart_alerts.py`, next to `_rule_to_dict`. `None` resolves to
`app.database.AsyncSessionLocal` at call time, so tests pass their in-memory sessionmaker.

**Where it runs:** at the top of `chart_alert_scheduler.run_chart_alert_scheduler()`,
before the `while True` loop, in its own `try/except Exception` + `logger.error(...,
exc_info=True)`, so a failure cannot stop the scheduler. Why here and not as a `lifespan`
line:
1. The order "migrate, then first scheduler tick" is fixed inside one function, and a test
   can pin it by driving that function with `_tick` and `asyncio.sleep` patched. It never
   runs the real `lifespan`, which rewrites `settings.yaml`, restores scans, and starts
   ingestion and notifying schedulers. That was the gate-level finding against T9 in
   plan round 2 on the old branch.
2. It runs exactly once per server start, because `lifespan` creates the task once. It
   never runs on import (tests import `app.main` freely).

The chart websocket can evaluate a rule before the migration's single query commits,
right at boot. Before the migration a '1D' HMM_intraday rule cannot fire (§1), so
nothing wrong can happen in that window. It only logs the existing warning.

**What it does, in one session:** select the `AlertRuleModel` rows with
`interval IN ('1D', '1W')`. Only these two are dead (§1: the rule path's own gate). An
unknown interval string isn't this decision, and those rows aren't touched. For each row
whose `rule_json` parses to a dict with `__type == "composite"` and
`primary.model == "HMM_intraday"`:
- `old = row.interval`; `row.interval = "5m"`
- `note = f" (interval was {old})"`; `row.name = row.name[:200 - len(note)] + note`
  (the column is `String(200)`). This is the report the decision chose. The Alerts page
  and the notification text show the name. No schema change.
- `row.condition_state = '{}'`. The interval changed, so any sustain clock is
  meaningless; this matches `replace_rule`'s reset on a changed definition.
- `enabled`, `rule_json`, `last_triggered_at`, `cooldown_minutes` are untouched.
- collect `{"id", "symbol", "name", "from": old}`.

A row whose `rule_json` doesn't parse, or isn't a dict, is skipped (DEBUG log), never
raised on. One commit. If anything migrated, one
`logger.warning("A4f: migrated %d HMM_intraday composite rule(s) from a daily/weekly interval to '5m' (on that interval they could not fire): [%s]", ...)`
lists `id symbol 'old'` for each rule, in the same shape as the watch-side warning.
Returns the list.

**Idempotent:** a migrated row is '5m', so the `IN ('1D','1W')` filter skips it on later
starts, and the note is appended exactly once.
**`user_id`:** all rows, not only `'default'`. Every CRUD path uses `'default'`, but the
dead condition does not depend on the owner.

### 2d. The Alerts page syncs rules on mount

`app/(frame)/alerts/page.tsx`: a mount effect that calls
`useChartAlertStore.getState().syncRules()`, the same call `ChartWorkspace` makes. After a
migration the page shows '5m' and the "(interval was 1D)" name, and a toggle PUTs the
migrated pair.

**Race, accepted:** a toggle made before the first sync returns still PUTs the stale '1D'.
The backend rejects it (§2b), so server state stays right, and the sync then shows the
server's rule. `putRuleToAPI` ignores the status (fire-and-forget, pre-existing), so that
one toggle is lost without a message. It needs a click within one request round-trip on
the first visit after the migration.

## 3. Tests (each must fail on pre-change code or on its named mutant)

Backend: new `tests/test_a4f_rules_hmm_intraday_interval.py`, using the in-memory
`_make_app()` pattern of `tests/test_chart_alerts_edit_resets_sustain.py` (its own engine
and `dependency_overrides[get_db]`, with no real DB, lifespan or scheduler).

- **R1** `hmm_intraday_interval_error`: returns a message for HMM_intraday + '1D' and + '1W'.
  Returns None for HMM_intraday + '5m', '15m', '60m', '4h'; for OMM + '1D' and
  HMM_daily + '1D'; when `primary` is missing or is a string; and when `trigger_def` is
  a string, None or a list. Also HMM_intraday + `['5m']` gives a message without raising.
- **R2** `POST /alerts/rules`. First `GET /alerts/rules` → 200, which proves the path exists
  so the 422 can't be a 404. Composite HMM_intraday + '1D' → 422, and GET then lists no
  rules. HMM_intraday + '5m' → 201. OMM + '1D' → 201. Standard + '1D' → 201.
- **R3** `PUT /alerts/rules/{id}`:
  - (a) a SEEDED legacy row (direct insert: composite HMM_intraday '1D') takes a same-pair
    `enabled: false` PUT → 200, disabled, still '1D'
  - (b) the same row PUT with '1W' → 422, and the row is unchanged (enabled, name, interval re-read from DB)
  - (c) a composite HMM_intraday '5m' row PUT with '1D' (the stale-localStorage case) → 422, and the row stays '5m'
  - (d) a composite OMM '1D' row PUT to HMM_intraday '1D' → 422
  - (e) a seeded STANDARD row PUT to composite HMM_intraday '1D' → 422
  - (f) a seeded row with unparseable `rule_json` PUT to composite HMM_intraday '1D' → 422 (counts as changed)
  - (g) a composite HMM_intraday '5m' row PUT with '15m' → 200
- **R4** migration: seed six rows with `condition_state`
  `'{"composite": "2026-09-25T10:00:00"}'` on the first:
  - (1) composite HMM_intraday '1D'
  - (2) composite HMM_intraday '1W', with a 195-char name
  - (3) composite HMM_intraday '5m'
  - (4) composite OMM '1D'
  - (5) standard '1D' carrying a `regime` HMM_intraday condition
  - (6) '1D' with `rule_json = 'not json'`

  After `await migrate_hmm_intraday_rule_intervals(Session)`:
  - (1) and (2) are '5m'. (1) is named `"<name> (interval was 1D)"`; (2)'s name ends
    with `" (interval was 1W)"` and is ≤ 200 chars.
  - (1)'s `condition_state == '{}'`.
  - `enabled` and `rule_json` are unchanged on both.
  - (3)-(6) are unchanged.
  - The return value lists exactly (1) and (2).
  - One WARNING (caplog) names both ids.
  - A second call returns `[]`, logs no A4f warning, and neither name is double-suffixed.
- **R5** a migrated rule is no longer dead. Take a migrated '5m' row from R4 and call
  `evaluate_and_notify_for_symbol` for '5m', with the HMM fit patched to report the
  target state and the notify/history side effects stubbed. The composite rule is
  evaluated with non-empty `regime_bars_intraday`. Asserting on the evaluator call is
  enough, and it holds only because the row's interval is now intraday. This is a
  behaviour pin, not a presence pin. If stubbing the function body turns out
  disproportionate, R5 narrows to "the scheduler's `_tick` query now yields
  `(symbol, '5m')`", with the narrowing written down.
- **R6** ordering: drive `run_chart_alert_scheduler()` with `migrate_...` and `_tick`
  replaced by recorders, and `asyncio.sleep` patched to raise `asyncio.CancelledError`
  after the first tick. The recorded order is `["migrate", "tick"]`. A second case has
  `migrate` raising `RuntimeError`: `_tick` still runs, and an ERROR is logged.

Frontend (`app/(frame)/alerts/__tests__/page.test.tsx`, extend the existing file):
- **R7** mounting the page calls `syncRules` exactly once. Spy on
  `useChartAlertStore.getState().syncRules`, or mock `fetch` and assert one GET
  `/alerts/rules`, whichever the existing mocks make honest.

Mutations to kill (each run, seen to fail, then reverted):
- **M1** predicate: `is_intraday_interval` → always True. Kills R1, R2, R3c.
- **M2** PUT rejects even when the pair is unchanged. Kills R3a.
- **M3** PUT never rejects. Kills R3b/c/d.
- **M4** PUT check placed AFTER the `row.*` assignments, with no rollback. Kills R3b's
  "row unchanged": the request session is not committed, but check it anyway. If R3b
  passes under M4 because the session is discarded, M4 is equivalent: record that and drop it.
- **M5** migration without the name note. Kills R4.
- **M6** migration without the `condition_state` reset. Kills R4.
- **M7** migration filter drops `__type == "composite"`. Kills R4's row (5).
- **M8** `run_chart_alert_scheduler` migrates after the first tick. Kills R6.
- **M9** the migration's `try/except` removed. Kills R6's second case.
- **M10** Alerts page without the `syncRules` effect. Kills R7.

## 4. Out of scope / logged

- **A migrated rule can fire at its first evaluation after startup**, before the owner has
  read the log or noticed the name. Accepted: it is the alert they built, on the interval
  the dialog showed. Disabling migrated rules was not part of the decision.
- **A toggle during the Alerts page's first sync after a migration is lost without a message** (§2d).
- **VWAP confirmation on '1D'** (`open_questions[2]`(b)) is unchanged.
- **'4h' HMM_intraday** (`open_questions[1]`, too few bars) is unchanged. '4h' is intraday, so it is accepted here.
- `pushRuleToAPI`/`putRuleToAPI` ignore the HTTP status (pre-existing). Unchanged.
- Standard rules with a `regime` HMM_intraday condition on '1D' are not in this decision.
  Whether they have the same dead shape is logged as an open question, not investigated here.

## 5. Verification before merge

`python3 scripts/state.py` exits 0. Backend `.venv/bin/python -m pytest -q`: baseline
3144 passed / 1 skipped (main `489202d`), and the new figure is recorded. Frontend
`npx tsc --noEmit && npx jest` (baseline 1985). M1-M10 are each run and seen to fail
their named test. `git status` shows `backend/config/*.yaml` unmodified after the full
backend run. PROJECT_STATE gets a phase `A4F-RULES-HMM-INTRADAY-INTERVAL` with a probe
on `migrate_hmm_intraday_rule_intervals`. `decisions[0]`'s "NOT BUILT" is updated when it ships.

## 6. Plan round 1

(pending)
