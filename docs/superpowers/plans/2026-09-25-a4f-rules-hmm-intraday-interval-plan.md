# A4f-rules — stored HMM_intraday composite RULES on '1D'/'1W' move to '5m'; the rules API refuses new ones

Branch `claude/hopeful-volta-ujru28` (off main `489202d`; A4f for watches merged at `f49446e`).
Builds decision **A4F-MIGRATE-LEGACY-RULES-TOO-2026-09-25** (PROJECT_STATE `decisions[0]`):
stored rules get the same treatment as the watches. At backend startup each rule is moved to
'5m' once, every migrated rule is logged, and its name gets an "interval was 1D" note.

Starting point: the unmerged plan revision 2 on `claude/dazzling-ride-0unofk` (`3622046`),
re-based onto what main actually shipped. Main's A4f already has
`market.is_intraday_interval`, the dialog's '5m' default for HMM_intraday, and the
watch-side reject and migration (in `StrategyWatchStore.load()`). None of that is re-done
here.

**Revision 2** (after plan round 1, §6). §1 adds the '5m'-vs-'5min' fact and corrects the
`syncRules` description. R4 can now kill M7. R5 is rebuilt as a real before/after pin with
every side effect named. R6 names its patch points. M4 is dropped as equivalent. R7
asserts what the page renders. The '4h' citation and the baselines are fixed.

## 1. Verification (on main `489202d`, before planning; re-checked by plan round 1)

**A stored HMM_intraday composite rule on '1D'/'1W' never fires.**
`evaluate_and_notify_for_symbol` (`app/routers/chart_alerts.py` ~:894-906) passes
`bars_intraday=[]` and `regime_bars_intraday=None` when `interval in ("1D", "1W")`. So
`evaluate_from_context_detailed`'s HMM_intraday branch logs
`HMM_intraday requested but no intraday bars supplied; skipping` at WARNING and returns
not-fired on every tick.

**New ones no longer come from the dialog**, because main's A4f defaults it to '5m'. But
`POST/PUT /alerts/rules` accept the pair from any client, including the stale-localStorage
client below.

**Only two backend paths evaluate rules.** Both go through
`evaluate_and_notify_for_symbol`: `chart_alert_scheduler._tick` (the background loop
started once in `lifespan`) and the chart websocket (`routers/chart.py` ~:100).

**'5m' is not a chart interval.** The chart's intervals are
`'1min'|'5min'|'15min'|'1h'|'4h'|'1D'|'1W'` (`frontend/lib/chartStore.ts:6`). The dialog
offers `5m/15m/30m/1h/4h`. The websocket evaluates only rules whose
`interval ==` the chart's own spelling (`chart_alerts.py` ~:782), and
`normalize_interval` has no '5m'→'5min' alias. So a '5m' rule is evaluated ONLY by the
background scheduler, through `get_intraday_with_fetched_at('5m')` → yfinance '5m'
(`_YF_MAX_DAYS['5m'] = 55`, a live feed; Tradier and its feed lag are skipped because
'5m' is not in `_TRADIER_INTRADAY_INTERVALS`). The 5min chart tab never evaluates it,
and `ChartWorkspace` doesn't list it there. This already holds for every rule the dialog
has created on '5m' since A4f, so it isn't introduced here. A migrated rule therefore
RUNS, in the scheduler on yfinance 5m bars, not "on the 5m chart feed" as the decision
text puts it. The '5m' target is kept: it is what the dialog shows and what main's A4f
gave the watches. The spelling split is logged as an open question (§4).

**The Alerts page reads rules from localStorage.** `chartAlertStore` is `persist()`ed
(`'bamendjou:alerts'`, v2). `syncRules()` is called only from `ChartWorkspace` (~:257).
It MERGES: for ids the server knows, the server's copy wins, and local-only rules are
re-POSTed via `pushRuleToAPI` (`chartAlertStore.ts` ~:60-72, ~:212-229). The Alerts
page's rules table reads `useChartAlertStore().rules`, and its toggle calls
`updateRule` → `putRuleToAPI`, which re-sends the LOCAL `interval` and `composite_def`
on every PUT. So after a migration, a user who hasn't opened the chart since sees '1D',
and toggling would PUT '1D' + HMM_intraday back onto the migrated rule.

## 2. The change

### 2a. One predicate (backend)

In `app/services/composite_trigger_evaluator.py`:

```python
def hmm_intraday_interval_error(trigger_def: object, interval: object) -> str | None:
    """A4f-rules: the message to refuse a composite HMM_intraday definition on a
    non-intraday interval with, else None. Never raises: a non-dict trigger_def /
    primary means "no model" (other validation owns malformed bodies)."""
```

It returns `f"HMM_intraday needs an intraday interval (e.g. 5m, 15m, 1h), got {interval!r}"`,
the same wording as `StrategyWatchStore.add_composite_watch`, when
`primary.model == "HMM_intraday"` and `not market.is_intraday_interval(interval)`. The
`market` import happens inside the function, matching this module's call-time imports.

**Why `strategy_watch_store._primary_model` is NOT imported:** importing
`app.services.strategy_watch_store` instantiates its module-level store. That runs
`load()`, which reads `config/strategy_watches.yaml` and can REWRITE it (A4f's watch
migration). The evaluator, and every test that imports it, must never trigger that. The
three lines are duplicated on purpose; don't merge them. R1 pins that the two checks
accept and reject the same intervals.

### 2b. The rules API refuses new bad pairs (422)

- **`POST /alerts/rules`**, `rule_type == 'composite'`: after the existing
  `composite_def` check, `err = hmm_intraday_interval_error(body.composite_def, body.interval)`;
  if `err` is set, raise `HTTPException(422, err)`. No row is written. 422 is this
  router's existing body-validation code; the watch router's 400 is its own convention
  and is unchanged.
- **`PUT /alerts/rules/{id}`**, `rule_type == 'composite'`: the check runs BEFORE any
  `row.*` assignment. That placement is for readability only: `get_db` closes the
  session without committing, so assigning first would not persist either. The stored
  pair is `row.interval` plus the primary model read from `json.loads(row.rule_json)`. A
  parse failure, a non-dict, or a stored non-composite row counts as "changed". **It
  rejects only when the new pair is invalid AND differs from the stored pair.** The
  exemption exists because the startup migration is fail-soft (§2c): if it failed, a
  legacy '1D' rule must still be toggleable, renameable and deleteable rather than
  stranded. A PUT sending a migrated '5m' rule back to '1D' changes the pair, so it is
  rejected; that covers the stale-localStorage toggle. DELETE and PATCH are untouched
  (PATCH carries only `enabled`/`last_triggered_at`).
- **The API refuses more than the migration fixes, on purpose.** `is_intraday_interval`
  is False for '1D', '1W', and also for '1d', 'daily', '1M' and unknown strings. The
  migration moves only '1D'/'1W', the two spellings the rule path treats as daily/weekly
  and that are dead today. A stored rule on any other non-intraday spelling isn't
  migrated and stays usable through the PUT exemption.
- Standard rules are untouched. A `regime` condition with `model: HMM_intraday` inside a
  standard group is a different path (A4c) and outside this decision (§4).

### 2c. Stored rules are migrated before the scheduler's first tick

New `async def migrate_hmm_intraday_rule_intervals(session_factory=None) -> list[dict]` in
`app/routers/chart_alerts.py`, next to `_rule_to_dict`. `None` resolves to this module's
`AsyncSessionLocal` global at call time, so tests pass their in-memory sessionmaker.

**Where it runs:** at the top of `chart_alert_scheduler.run_chart_alert_scheduler()`,
before the `while True`. It uses a call-time import, the same form as `_tick`'s existing
one:

```python
from app.routers import chart_alerts as _chart_alerts
try:
    await _chart_alerts.migrate_hmm_intraday_rule_intervals()
except Exception:
    logger.error('A4f: HMM_intraday rule interval migration failed', exc_info=True)
```

The attribute is resolved on the `chart_alerts` module at call time, so a test patches
`app.routers.chart_alerts.migrate_hmm_intraday_rule_intervals` (R6).

Why here rather than as a `lifespan` line:
1. "Migrate, then first tick" is fixed inside one function, and a test can pin it
   without running the real `lifespan`. The real lifespan rewrites `settings.yaml`,
   restores scans, and starts ingestion and notifying schedulers; that was the gate-level
   finding against the old branch's T9.
2. It runs exactly once per server start, because `lifespan` creates this task once, and
   never on import.

The chart websocket cannot evaluate a '5m' rule at all (§1). It could evaluate a
not-yet-migrated '1D' rule in the moment before the migration commits, but such a rule
can't fire (§1), so that window is harmless.

**What it does, in one session:** select `AlertRuleModel` rows with
`interval IN ('1D', '1W')`. For each row whose `rule_json` parses to a dict with
`__type == "composite"` and `primary.model == "HMM_intraday"` (primary a dict):
- `old = row.interval`; `row.interval = "5m"`
- `note = f" (interval was {old})"`; `row.name = row.name[:200 - len(note)] + note`
  (the column is `String(200)`). This is the report the decision chose. The name shows
  on the Alerts page and in notification text. No schema change.
- `row.condition_state = '{}'`. A sustain clock from another interval is meaningless;
  this is the same reset `replace_rule` does on a changed definition.
- `enabled`, `rule_json`, `last_triggered_at` and `cooldown_minutes` are untouched.
- Collect `{"id", "symbol", "name", "from": old}`.

A row whose `rule_json` doesn't parse, or parses to a non-dict, is skipped (DEBUG log),
never raised on. There is one commit. If anything migrated, one
`logger.warning("A4f: migrated %d HMM_intraday composite rule(s) from a daily/weekly interval to '5m' (on that interval they could not fire): [%s]", ...)`
lists `id symbol 'old'` for each rule, in the same shape as the watch-side warning. The
function returns the list.

**Idempotent:** a migrated row is '5m', so it falls outside the filter and the note is
appended once. **`user_id`:** all rows. Every CRUD path uses `'default'`, but deadness
doesn't depend on the owner.

### 2d. The Alerts page syncs rules on mount

In `app/(frame)/alerts/page.tsx`, a mount effect calls
`useChartAlertStore.getState().syncRules()`, the same call `ChartWorkspace` makes. After
a migration the page shows '5m' and the "(interval was 1D)" name, and a toggle PUTs the
migrated pair.

**Race, accepted:** a toggle before the first sync returns still PUTs the stale '1D'. The
backend rejects it (§2b), so server state stays correct, and the sync then shows the
server's rule. `putRuleToAPI` ignores the status (fire-and-forget, pre-existing), so that
one toggle is lost without a message.

## 3. Tests (each must fail on pre-change code or on its named mutant)

Backend: new `tests/test_a4f_rules_hmm_intraday_interval.py`. It uses the in-memory
`_make_app()` pattern of `tests/test_chart_alerts_edit_resets_sustain.py`: its own
engine, `dependency_overrides[get_db]`, and no lifespan.

- **R1 predicate**
  - `hmm_intraday_interval_error` returns a message for HMM_intraday + '1D', '1W' and
    `['5m']` (no raise).
  - It returns None for HMM_intraday + '5m', '15m', '60m', '4h'; for OMM + '1D'; for
    HMM_daily + '1D'; when `primary` is missing or a string; and when `trigger_def` is a
    string, None or a list.
  - **Parity:** for each interval in `['5m','15m','30m','1h','60m','4h','1min','1D','1W','daily','1d','foo']`,
    `hmm_intraday_interval_error(td, i) is None` equals "`StrategyWatchStore(path=None).add_composite_watch(sym, td, interval=i)` does not raise".
    That constructor with `path=None` touches no file. `strategy_watch_store` is imported
    inside this test only, after monkeypatching `BAMENDJOU_STRATEGY_WATCHES_PATH` to a
    tmp file and reloading the module, the pattern of `tests/test_strategy_watch_router.py`,
    so the tracked yaml is never read or written.
- **R2 POST**
  - `GET /alerts/rules` → 200 first, which proves the path exists.
  - Composite HMM_intraday + '1D' → 422, and the GET list stays empty.
  - HMM_intraday + '5m' → 201; OMM + '1D' → 201; standard + '1D' → 201.
- **R3 PUT**
  - (a) A SEEDED legacy row (direct insert, composite HMM_intraday '1D'), PUT with the
    same pair and `enabled: false` → 200. The row is disabled and still '1D'.
  - (b) The same row PUT with '1W' → 422. Re-read from a fresh session: it is unchanged.
  - (c) A composite HMM_intraday '5m' row PUT with '1D' (the stale-localStorage case) →
    422, and it stays '5m'.
  - (d) A composite OMM '1D' row PUT to HMM_intraday '1D' → 422.
  - (e) A seeded standard row PUT to composite HMM_intraday '1D' → 422.
  - (f) A seeded row with `rule_json='not json'` PUT to composite HMM_intraday '1D' → 422.
  - (g) A composite HMM_intraday '5m' row PUT with '15m' → 200.
- **R4 migration.** Seed seven rows (the first with `condition_state '{"composite": "2026-09-25T10:00:00"}'`):
  1. Composite HMM_intraday '1D'.
  2. Composite HMM_intraday '1W', with a 195-character name.
  3. Composite HMM_intraday '5m'.
  4. Composite OMM '1D'.
  5. A standard '1D' group with a `regime` HMM_intraday condition.
  6. **No `__type`, but an HMM_intraday primary**, on '1D':
     `{"primary":{"model":"HMM_intraday"},"logic":"AND","conditions":[]}`.
  7. '1D' with `rule_json='not json'`.

  Then `await migrate_hmm_intraday_rule_intervals(Session)`. Expected:
  - Rows (1) and (2) are '5m'. Row (1) is named `"<name> (interval was 1D)"`. Row (2)'s
    name ends with `" (interval was 1W)"` and is at most 200 characters.
  - Row (1)'s `condition_state == '{}'`.
  - `enabled` and `rule_json` are unchanged on both.
  - Rows (3)-(7) are unchanged.
  - The return value lists exactly (1) and (2).
  - Exactly one WARNING names both ids (caplog).
  - A second call returns `[]`, logs no A4f warning, and doesn't double the suffix.
- **R5 before/after through the real evaluation function.** Tie it to the migration:
  - Patches, all by `monkeypatch.setattr`:
    - `app.routers.chart_alerts.AsyncSessionLocal` → the test's in-memory `Session`.
    - `app.routers.chart_alerts._dispatch` → an `AsyncMock`.
    - `app.routers.chart_alerts._load_notification_config` → `lambda: {}`.
    - `app.services.regime_hmm.compute_intraday_hmm` → a recorder, which the evaluator
      calls lazily via the module attribute. Verify at build time and patch wherever the
      evaluator actually resolves it.
    - Every other network or settings read the function makes, identified by reading it
      at build time and listed in the test's docstring.
  - Seed one composite HMM_intraday '1D' rule, with no `strategy_confirmations`.
  - Call `evaluate_and_notify_for_symbol(sym, '1D', closed, candles, [], as_of=<fixed>)`
    with 250 synthetic candles. Assert the "no intraday bars supplied" WARNING and that
    the HMM recorder is NOT called.
  - Run the migration.
  - Call again with `interval='5m'` and the same candles. Assert the HMM recorder IS
    called with a non-empty bar list.

  This fails on pre-change code, where the migration doesn't exist and the '5m' call
  finds no row. It also fails under M1'. It doesn't assert that a notification is sent:
  whether the rule fires depends on the fitted state, and firing is existing behaviour.
- **R6 ordering, without the real lifespan or DB.** Patches:
  - `app.routers.chart_alerts.migrate_hmm_intraday_rule_intervals` → an async recorder.
  - `app.services.chart_alert_scheduler._tick` → an async recorder.
  - `app.services.chart_alert_scheduler._load_check_interval_seconds` → `lambda: 15`.
  - `app.services.chart_alert_scheduler.asyncio` → `SimpleNamespace(sleep=<async fn raising _Stop>)`.
    That is module-local, so pytest-asyncio's own loop is untouched. Check that the
    module references only `asyncio.sleep`, and extend the namespace if it uses more.

  Then `with pytest.raises(_Stop): await run_chart_alert_scheduler()`, and assert the
  order is `["migrate", "tick"]`. Case two: `migrate` raises `RuntimeError`, `_tick`
  still runs, and an ERROR record is logged.

Frontend: extend `app/(frame)/alerts/__tests__/page.test.tsx`.
- **R7:**
  - Seed the store with a stale local composite rule `{id:'r1', interval:'1D', name:'X', rule_type:'composite', …}`.
  - Mock `fetch` so GET `/alerts/rules` returns `ok:true` with
    `[{id:'r1', interval:'5m', name:'X (interval was 1D)', rule_type:'composite', …}]`,
    and every other call returns `ok:true` with `[]`.
  - Render the page and open the Rules tab. Assert that "X (interval was 1D)" and '5m'
    are shown (findBy).
  - Assert exactly one GET to `/alerts/rules` was issued by the page.
  - Use the existing file's mocks. If the page already fetches other endpoints, match
    only the `/alerts/rules` URL.

Mutations to kill (each is run, seen to fail, then reverted):
- **M1** `hmm_intraday_interval_error` always returns None. Killed by R1, R2 and R3c.
- **M1'** The migration doesn't change `interval`, but still renames the rule. Killed by
  R4 and R5.
- **M2** PUT rejects even when the pair is unchanged. Killed by R3a.
- **M3** PUT never rejects. Killed by R3b, R3c and R3d.
- **M5** The migration without the name note. Killed by R4.
- **M6** The migration without the `condition_state` reset. Killed by R4.
- **M7** The migration filter drops `__type == "composite"`. Killed by R4 row (6).
- **M8** `run_chart_alert_scheduler` migrates after the first tick. Killed by R6.
- **M9** The scheduler's `try/except` around the migration is removed. Killed by R6
  case two.
- **M10** The Alerts page has no `syncRules` effect. Killed by R7.
- **M11** Name truncation is removed. Killed by R4 row (2): 195 + 18 is more than 200.
  SQLite doesn't enforce `String(200)`, so the length assertion is what catches it.

(M4 from revision 1, "check placed after the assignments", is dropped as equivalent: the
request session is never committed on the error path.)

## 4. Out of scope / logged

- **Open question for the owner: '5m' vs '5min'.** A rule on '5m', whether dialog-created
  since A4f or migrated here, is evaluated only by the background scheduler on yfinance
  5m bars. It never runs from the 5min chart tab and isn't listed on it (§1). Options:
  keep this; make the dialog offer the chart spellings ('5min','15min'); or add a
  '5m'→'5min' alias in `normalize_interval`, together with the websocket's equality
  query. This predates this item and isn't changed here.
- **A migrated rule can fire at its first scheduler evaluation after startup**, before
  the owner has read the log or seen the name. That is accepted: it's the alert they
  built, on the interval the dialog showed.
- **A toggle during the Alerts page's first sync after a migration is lost without a
  message** (§2d).
- **Pre-existing, logged:** `syncRules` re-POSTs local-only rules through `pushRuleToAPI`,
  which drops `rule_type`/`composite_def`, so a composite rule that only ever existed
  locally is recreated as an empty standard rule. §2d makes this run on Alerts-page
  visits as well as chart visits. Such a rule could only exist if its original POST
  failed. Unchanged here.
- **VWAP confirmation on '1D'** (`open_questions[2]`(b)): unchanged.
- **'4h'** is intraday, so it's accepted. `open_questions[1]` (too few bars) covers
  WATCHES (`days=55`). The rule path fetches 4h through `chart_cache` with
  `_CHART_HOURLY_DAYS`, and its bar count is not checked here.
- Standard rules with a `regime` HMM_intraday condition on '1D' aren't in this decision.
  They are logged as an open question and not investigated.
- `pushRuleToAPI`/`putRuleToAPI` ignore HTTP status (pre-existing).

## 5. Verification before merge

- `python3 scripts/state.py` exits 0.
- Baselines are re-run on the branch head before building and recorded in §7:
  - Backend: `.venv/bin/python -m pytest -q`.
  - Frontend: `npx tsc --noEmit && npx jest`.

  Main `489202d` recorded 3144 passed / 1 skipped for the backend and 1985 for the
  frontend. The branch has changed only docs and `.k-session/` since.
- Every mutant M1-M11 (without M4) is run and seen to fail its named test.
- `git status` shows `backend/config/*.yaml` unmodified after the full backend run.
- PROJECT_STATE gets:
  - A new phase `A4F-RULES-HMM-INTRADAY-INTERVAL` with a probe on
    `migrate_hmm_intraday_rule_intervals`.
  - `decisions[0]`'s "NOT BUILT" updated.
  - The §4 open questions: '5m' vs '5min', and standard-rule HMM_intraday on '1D'.

## 6. Plan round 1 (2026-09-25): NOT CLEAN, four gate-level findings, all taken

The round used a fresh subagent running bmad-review-adversarial-general against the code.

**Gate-level (4):**
1. M7 could not be killed by R4, because standard rows have no `primary`. Fix: R4 row (6).
2. '5m' is not a chart interval, so migrated rules run only in the scheduler. Fix: §1
   corrected, §2c's websocket paragraph corrected, and the open question added (§4).
   Checked independently: yfinance serves '5m', so migrated rules are live.
3. R5 didn't name its patches, so it could hit the real DB and send real notifications.
   Fix: every patch is named, and the "narrow if disproportionate" escape is removed.
4. R6 didn't name its patch points and would have read `settings.yaml`. Fix: the
   call-time import form is specified, patches are at `chart_alerts.*`,
   `_load_check_interval_seconds` is stubbed, and a module-local `asyncio` namespace is
   used.

**Sub-gate (8), all taken:**
5. §2a's reason was wrong. It now gives the real reason (importing the store runs
   `load()`), and R1 has a parity case.
6. §1 misdescribed `syncRules`. Corrected, and the drop of `composite_def` is logged in §4.
7. R7 was weak. It now checks rendered content.
8. M4 was equivalent. Dropped.
9. R5 couldn't fail. It is now before/after, tied to the migration and M1'.
10. §2b now says the API refuses more than the migration fixes.
11. The '4h' citation was wrong. Corrected.
12. The baselines were stale. §5 now re-runs them on the branch head.

## 7. Plan round 2 (2026-09-25): CLEAN, zero gate-level findings

A fresh subagent ran bmad-review-adversarial-general. It verified the §1 claims against
the code and ran R5 as a throwaway: on '1D' the warning is logged and the HMM is not
called; on '5m' after migration the HMM is called with 250 bars. Its 12 sub-gate items
are taken into the build as follows:
1. R5 candles use int unix `time`, the newest at least 300 s before `as_of`.
2. and 10. The migration is retried at the top of each loop iteration until one run
   succeeds, then never again. R6 lets the fake sleep stop the loop on its SECOND call.
   Case one asserts `["migrate","tick","tick"]` with exactly one migration. Case two:
   the first migration raises, the second succeeds; order
   `["migrate","tick","migrate","tick"]`, and an ERROR is logged. New mutants: **M12**
   migrate on every iteration; **M13** never retry after a failure.
3. R6: `asyncio.to_thread` is used only inside the stubbed `_tick`, so the namespace
   needs only `sleep`.
4. R4 adds a DISABLED legacy row (migrated, stays disabled) and a row with
   `user_id='other'` (migrated). **M14**: the filter adds `enabled == True`.
5. R4 adds `rule_json='[]'` and a composite whose `primary` is a string, both on '1D',
   both unchanged. **M15**: `.get` without the isinstance guards.
6. R4 adds a composite HMM_intraday rule on 'daily', unchanged. **M16**: the filter
   uses `not is_intraday_interval`.
7. The over-rejection cases are tied to mutants. **M17**: the predicate rejects every
   HMM_intraday (killed by R1, R2 '5m', R3g). **M18**: it rejects any composite on '1D'
   (killed by R1 OMM, R2 OMM+'1D').
8. R1 parity: `monkeypatch.setenv` to a tmp path, then a plain import, with no reload.
   Pinning the variable in conftest is logged, not done here.
9. §4: an Alerts-page sync in the first moments after a restart can still show '1D'
   (the migration runs in the scheduler task); it corrects itself on the next visit.
11. The §5 PROJECT_STATE update rewrites `open_questions[2]`'s design inputs to match
    this build (the scheduler task, not lifespan).
12. `_INTERVAL_LABELS` has no '5m', so notifications say "5m chart". Folded into the
    '5m' vs '5min' open question.
