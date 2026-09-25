# A4f — HMM_intraday interval default + migration of stored watches AND rules

Branch `claude/dazzling-ride-0unofk`, restarted off main `e2bf498` (A4e merged).
Item (3) of decision A4C-FOLLOWUPS-LOCKED-2026-09-24, extended by
A4F-MIGRATE-LEGACY-RULES-TOO-2026-09-25 (Kenneth: stored composite RULES get the same
treatment as watches).

> UI bug: CompositeAlertDialog initialises interval '1D' and shows the 5m-4h select only for
> HMM_intraday, so an untouched select stores '1D' (the browser most likely DISPLAYED '5m',
> the first option -- verify). Backend rejects HMM_intraday with 1D/1W; the dialog sets an
> intraday default when HMM_intraday is chosen; EXISTING stored watches are migrated to '5m'
> (what the user most likely saw), with the list of migrated watches reported, not changed
> silently.

**Revision 2 (2026-09-25).** Rewritten after plan round 1 (§6). What changed since
revision 1: §1's claim about rules corrected; rules migrated too (decision above); both
migrations moved OUT of `StrategyWatchStore.load()` into explicit startup steps (§2d); rules
path corrected to `/alerts/rules`; T3 isolated from the tracked watch file; new §2f (the
Alerts page reads rules from localStorage and would push a stale '1D' back); M6 made
killable; the cheap sub-gate items taken (listed in §6's disposition table).

## 1. Verification (done before planning)

**What the user saw: '5m'. Confirmed.** A controlled `<select value="1D">` whose options are
`5m,15m,30m,1h,4h` renders with `value === '5m'`, `selectedIndex === 0` (probe under the
repo's jest/jsdom + react-dom; React's `updateOptions` selects the first non-disabled option
when none matches, so the same holds in a real browser). The user saw '5m' and saved '1D'.

**A stored '1D' HMM_intraday WATCH never fires, silently.** `strategy_watch_evaluator` calls
`fetch_intraday_candles(symbol, interval='1D', days=55)`; '1D' normalises to daily, so ~38
daily bars come back; `completed_bars_for_interval` returns them unchanged (daily is outside
`_INTERVAL_COMPLETION_SECONDS`); `compute_intraday_hmm` returns `None` below `MIN_BARS = 200`.
The primary check fails every run. The dialog's live snapshot for the same inputs gets a 422
("insufficient history").

**A stored '1D' HMM_intraday composite RULE never fires either** (corrected; round 1 finding
1). `evaluate_and_notify_for_symbol` (`app/routers/chart_alerts.py`) passes
`bars_intraday=[]` and `regime_bars_intraday=None` when `interval in ("1D", "1W")`, so the
HMM_intraday branch of `evaluate_from_context_detailed` logs
`HMM_intraday requested but no intraday bars supplied; skipping` at WARNING on every tick and
returns not-fired. Rules are dead exactly like watches.

**Where HMM_intraday + interval is created:** only `CompositeAlertDialog`, via
`api.addCompositeWatch(symbol, triggerDef, direction, interval)` (POST
`/api/composite-watches/`) and `api.addCompositeAlertRule(name, symbol, interval, triggerDef)`
(POST `/alerts/rules` -- router prefix `/alerts`, `rule_type: 'composite'`).
`chartAlertStore.putRuleToAPI` re-sends a composite rule's `interval` + `composite_def` on
every PUT `/alerts/rules/{id}`, including an `enabled` toggle. There is no composite editor.

**The Alerts page shows rules from localStorage, not the backend** (new, found while
revising). `chartAlertStore` is `persist()`ed (`'bamendjou:alerts'`); `syncRules()` (which
replaces local rules with the server's) is called only from `ChartWorkspace`. The Alerts
page's rules table reads `useChartAlertStore().rules` and its toggle calls `updateRule` ->
`putRuleToAPI` with the LOCAL copy. After a backend migration, a user who has not opened
the chart since would see '1D' there, and toggling would PUT '1D' + HMM_intraday back. §2f.

## 2. The change

### 2a. Shared predicates (backend)

`app/data/market.py`, next to `completed_bars_for_interval`:

```python
def is_intraday_interval(interval: object) -> bool:
    """True iff `interval` is a string naming one of the intraday intervals the
    user-built alert models run on (`_INTERVAL_COMPLETION_SECONDS`, any accepted
    spelling). Daily, weekly, unrecognised strings and non-strings are False."""
    return isinstance(interval, str) and normalize_interval(interval) in _INTERVAL_COMPLETION_SECONDS
```

The `isinstance` guard matters: `normalize_interval` is a dict `.get`, which raises
`TypeError` on an unhashable value, and a hand-edited watch file can hold one (§2d).
`1min` stays accepted (the table has it; the dialog doesn't offer it).

`app/services/composite_trigger_evaluator.py`:

```python
HMM_INTRADAY_INTERVAL_ERROR = ("HMM_intraday needs an intraday interval "
                               "(5m, 15m, 30m, 1h or 4h); got {interval!r}")

def hmm_intraday_interval_error(trigger_def: object, interval: object) -> str | None:
    primary = trigger_def.get("primary") if isinstance(trigger_def, dict) else None
    model = primary.get("model") if isinstance(primary, dict) else None
    if model == "HMM_intraday" and not is_intraday_interval(interval):
        return HMM_INTRADAY_INTERVAL_ERROR.format(interval=interval)
    return None
```

It never raises: a non-dict `trigger_def` or `primary` means "no model", so no rejection.
Other validation owns malformed bodies.

### 2b. Backend rejects new bad pairs

- **`StrategyWatchStore.add_composite_watch`** raises `ValueError(msg)`. The router
  (`app/routers/composite_watch.py`) already maps `ValueError` to **400**. That is the
  existing convention for that router. The rules router uses **422** for body validation
  (`composite_def is required ...`), and the new check follows it. The two codes differ
  on purpose: each matches its own router's convention.
- **`POST /alerts/rules`**, `rule_type == 'composite'`: 422 with the message, after the
  existing `composite_def` check and before the row is built.
- **`PUT /alerts/rules/{id}`**, `rule_type == 'composite'`: 422 when the new pair is
  invalid, UNLESS the PUT leaves the stored pair unchanged. The pair is the interval plus
  the primary model. The comparison uses the row as it was before `replace_rule`'s
  assignments. The stored model is read from `json.loads(row.rule_json)`; if that parse
  fails, or the row isn't composite, the pair counts as changed. After §2e there should be
  no stored invalid pair left, so the exemption is only a safety net: if the rule
  migration failed at startup (its errors are logged, not fatal), a legacy rule can still
  be toggled, renamed and deleted instead of being stranded. A PUT that brings an
  already-migrated '5m' rule back to '1D' changes the pair and is rejected. That covers
  the stale localStorage copy in §2f.
- **Not changed:** `GET /api/composite-watches/regime-snapshot` (read-only; already 422s on
  '1D'); the evaluators.

### 2c. Dialog sets the intraday default

Model `onChange`: `setIntervalVal(next === 'HMM_intraday' ? '5m' : '1D')`, next to the existing
`setToState('any')`. '5m' is the first option, the same value an untouched select shows.
Switching away resets to '1D', so OMM/HMM_daily/any rules and watches keep today's
interval. The snapshot effect already depends on `interval`, so it refetches with the
value that will be stored. The initial state stays `'1D'`, because the initial model is OMM.

### 2d. Stored WATCHES migrated to '5m' at startup, reported

New `StrategyWatchStore.migrate_hmm_intraday_intervals(now: datetime | None = None) -> list[dict]`,
called once from `lifespan` in `app/main.py`. It runs right after the continuous-scan
migration and BEFORE `run_chart_alert_scheduler` and `strategy_watch_scheduler.start()`, so
no evaluator ever sees a pre-migration pair. It is wrapped in `try/except Exception` +
`logger.warning`, like the neighbouring migrations, so a failure cannot block startup.

It is deliberately NOT in `load()`. `load()` runs when `strategy_watch_store` is imported
(a module-level singleton), which includes every test that imports `app.main`, and
`conftest.py` does not pin `BAMENDJOU_STRATEGY_WATCHES_PATH`. A migration there would
rewrite whatever file the import found. An explicit startup call runs only in a real
server start, and tests call it on their own tmp-path stores.

Under the lock, for each watch `w` that is a dict with `w.get("watch_type") == "composite"`
and a non-None `hmm_intraday_interval_error(w.get("trigger_def"), w.get("interval"))`:

- `old = w.get("interval")`, plus a flag for whether the key was really stored. `load()`'s
  `setdefault("interval", "1D")` fills it in memory, so the check is whether the raw YAML
  had it. `load()` records the ids it defaulted in `self._interval_defaulted: set[str]`,
  a one-line change next to the `setdefault`.
- `w["interval"] = "5m"`
- `w["interval_migrated"] = {"from": str(old), "from_was_default": <bool>, "to": "5m", "at": <utc iso>,
  "reason": "A4f: HMM_intraday cannot run on a daily/weekly interval; 5m is what the dialog displayed"}`
- `w["last_state"]` untouched. The watch never fired, so it has no armed or pending state.
- collect `{"id", "symbol", "from", "from_was_default"}`.

After releasing the lock, if anything was collected: one `logger.warning("A4f migrated %d
HMM_intraday watch(es) to 5m: %s", n, "; ".join(...))`, then `self.save()` (outside the
lock, since `threading.Lock` is not re-entrant) inside `try/except OSError` +
`logger.warning`. The in-memory migration stands for this process, and the next start
retries the save. The method returns the list.

**Idempotent:** a migrated watch now has an intraday interval, so later runs skip it. The
`interval_migrated` marker is never cleared.
**Strategy watches are never touched**, even a hand-edited one carrying an HMM_intraday
`trigger_def` (the evaluator ignores `trigger_def` for them). T6 pins this, which makes M6
killable.
**Tolerance kept:** a non-dict `trigger_def` or a non-string `interval` does not raise.
The predicates return None/False, and non-dict watch entries are skipped. The migration
adds no new failure mode to startup. (`load()`'s existing `setdefault` on a non-dict entry
is outside this item and unchanged.)

### 2e. Stored composite RULES migrated to '5m' at startup, reported

New `async def migrate_hmm_intraday_rule_intervals(session_factory) -> list[dict]` in
`app/routers/chart_alerts.py`, next to `_rule_to_dict`. It runs from `lifespan`
immediately after §2d, with the same try/except and the same ordering before the chart
alert scheduler. `session_factory` defaults to `app.database.AsyncSessionLocal`; tests
pass their in-memory sessionmaker.

In one session: select all `AlertRuleModel` rows. For each row whose `rule_json` parses to
a dict with `__type == "composite"` and whose `(parsed, row.interval)` gives a
`hmm_intraday_interval_error`:
- `old = row.interval`; `row.interval = "5m"`
- `row.name = f"{row.name} (interval was {old})"`. This is the report Kenneth chose. The
  Alerts page shows the name, and the table has no marker column (no schema change).
- `row.condition_state = '{}'`. The interval changed, so any sustain clock is meaningless.
  This matches `replace_rule`'s reset on a changed definition.
- `last_triggered_at`, `enabled`, `rule_json` untouched.
- collect `{"id", "symbol", "name", "from"}`.

Commit once; one `logger.warning("A4f migrated %d HMM_intraday composite rule(s) to 5m:
%s", ...)`. A row whose `rule_json` does not parse is skipped (logged at DEBUG), never
raised on. **Idempotent:** a migrated row has interval '5m', so later runs skip it and the
name note is appended exactly once.

### 2f. The Alerts page syncs rules from the backend on mount

`app/(frame)/alerts/page.tsx` calls `useChartAlertStore.getState().syncRules()` in a mount
effect, the same call `ChartWorkspace` makes. After a migration, the page then shows '5m'
and the "(interval was 1D)" name instead of the stale localStorage copy, and a toggle
PUTs the migrated pair. Race: a toggle made before the sync returns still sends the stale
'1D'. The PUT rejects it (§2b: the pair changed and is invalid), so the backend stays
correct, and the sync that completes then shows the server's state. `putRuleToAPI` ignores
the status, so that one toggle is lost without a message. That is accepted and logged,
since it needs a click within the first request's round-trip on the first visit after the
migration.

### 2g. Watch migration reported in the UI

`CompositeWatch` in `lib/api.ts` gains
`interval_migrated?: { from: string; from_was_default?: boolean; to: string; at: string; reason: string }`.
In the Alerts page's composite-watch row, the Interval cell becomes ONE grid child (a `<div>`),
so the row's column count is unchanged:
`<div><Text size={12}>{w.interval}</Text>{w.interval_migrated && <span title={reason}><Text size={11} tone="caution">{note}</Text></span>}</div>`.
The tooltip goes on the `<span>`, because `Text` has no `title` prop. `note` =
`was {from}; set to {to}`. When `from_was_default` is set, it reads
`was unset (1D default); set to {to}` instead, so the UI never claims the user stored '1D'
when they didn't.

## 3. Tests (each must fail on pre-change code or on its named mutant)

Backend: new file `tests/test_a4f_hmm_intraday_interval.py`.
- **T1** `is_intraday_interval`: True for 5m/5min/15m/30m/1h/60m/4h/1min; False for
  1D/1W/daily/weekly/''/'foo'/None/5/['5m'] (the last one pins "no TypeError").
- **T2** `hmm_intraday_interval_error`: message for HMM_intraday + 1D and + 1W; None for
  HMM_intraday + 15m, OMM + 1D, HMM_daily + 1D, primary missing, primary a string,
  trigger_def a string or None.
- **T3** POST `/api/composite-watches/`, using the temp-file-and-reload fixture from
  `tests/test_strategy_watch_router.py` (monkeypatch `BAMENDJOU_STRATEGY_WATCHES_PATH` to
  tmp_path, reload `app.services.strategy_watch_store` and `app.routers.composite_watch`,
  then `create_app()`) so the tracked `config/strategy_watches.yaml` is never written:
  HMM_intraday + '1D' → 400, and the list is empty; HMM_intraday + '15m' → 201;
  OMM + '1D' → 201. The test also asserts the tracked file's bytes are unchanged
  (read before and after).
- **T4** POST `/alerts/rules` (the `_make_app()` in-memory pattern from
  `tests/test_chart_alerts_edit_resets_sustain.py`): composite HMM_intraday + '1D' → 422, no
  row; + '5m' → 201. A sanity request, GET `/alerts/rules` → 200, first proves the path
  exists, so the 422 can't be a 404 in disguise.
- **T5** PUT `/alerts/rules/{id}`: a SEEDED (direct DB insert) legacy composite
  HMM_intraday + '1D' row accepts a same-pair `enabled` toggle (200; enabled flipped;
  interval still '1D'). The same row PUT with '1W' → 422. An HMM_intraday + '5m' row PUT
  with '1D' (the stale-localStorage case) → 422, and the row stays '5m'. An OMM + '1D' row
  PUT to HMM_intraday + '1D' → 422. A standard row PUT to composite HMM_intraday + '1D' →
  422.
- **T6** watch migration on a tmp-path store with: composite HMM_intraday '1D'; composite
  HMM_intraday '1W'; composite HMM_intraday with NO interval key; composite HMM_intraday
  '15m'; composite OMM '1D'; a strategy watch '1D' whose `trigger_def` is hand-edited to
  `{"primary": {"model": "HMM_intraday"}}`; a composite whose `trigger_def` is the string
  `"x"`; a composite HMM_intraday with `interval: [1]`. Expected after
  `migrate_hmm_intraday_intervals()`: the first three and the `[1]` one are '5m' with
  `from` = '1D' / '1W' / '1D' (with `from_was_default=True`) / '[1]'; the rest are
  unchanged and have no marker; the file on disk is rewritten (reload and compare); one
  WARNING names all four ids (caplog). A second call returns `[]` and logs no A4f warning.
- **T7** a failing save: monkeypatch `save` to raise `OSError`. The call does not raise, the
  in-memory watch is '5m', and a WARNING is logged.
- **T8** rule migration: seed composite HMM_intraday '1D' (with `condition_state`
  `{"composite": "<iso>"}`), composite HMM_intraday '1W', composite HMM_intraday '5m',
  composite OMM '1D', a standard rule '1D', and a row with unparseable `rule_json`. After
  `await migrate_hmm_intraday_rule_intervals(Session)`, the first two are '5m', named
  `"<name> (interval was 1D)"` / `"... 1W)"`, with `condition_state == '{}'`; the others
  are unchanged; the call doesn't raise on the bad row; one WARNING names both ids. A
  second call returns `[]`, and the names are not double-suffixed.
- **T9** startup wiring: `lifespan` calls both migrations before the chart-alert and
  strategy-watch schedulers start. Pinned by patching the two migrations and
  `run_chart_alert_scheduler` / `strategy_watch_scheduler.start` with recorders, running
  the lifespan context, and asserting the call order. If the lifespan has too many other
  side effects to run in a test, fall back to a source-order assertion on `app/main.py`,
  marked as a presence pin.

Frontend:
- **T10** (`CompositeAlertDialog.test.tsx`) choose HMM_intraday, then Save as Watch →
  `addCompositeWatch(..., '5m')`. This is the discriminating assertion; on today's code it
  gets '1D'. The snapshot is refetched with `(..., 'HMM_intraday', ..., '5m')`. That also
  discriminates: today it's '1D'. "The select shows '5m'" is NOT asserted as a
  discriminator, because it holds on today's code too.
- **T11** HMM_intraday → pick '1h' → back to OMM → Save as Rule →
  `addCompositeAlertRule(name, sym, '1D', …)`.
- **T12** (`app/(frame)/alerts/__tests__/page.test.tsx`) a watch with `interval_migrated` renders
  "was 1D; set to 5m"; with `from_was_default` it renders "was unset (1D default)"; without
  the marker there is no note. The watches row still has the same number of direct grid children as the
  header row.
- **T13** (same file) mounting the page calls `syncRules` once.

Mutations to kill (each run, seen to fail, reverted):
- M1 dialog onChange without the interval reset (T10)
- M2 `is_intraday_interval` → always True (T1, T3, T6, T8)
- M3 PUT rejects even when the pair is unchanged (T5 toggle)
- M4 PUT never rejects (T5)
- M5 watch migration without `save()` (T6 disk check)
- M6 watch migration without the `watch_type == "composite"` check (T6's hand-edited
  strategy watch)
- M7 rule migration without the name note (T8)
- M8 rule migration without `condition_state` reset (T8)
- M9 lifespan calls the migrations after the schedulers start (T9)
- M10 Alerts page without `syncRules` (T13)
- M11 the note ignores `from_was_default` (T12)

## 4. Out of scope / logged

- The dialog does not offer `1min`, and the backend accepts it. Unchanged.
- **A migrated item can fire at the first evaluation after startup**, before Kenneth has
  read the log or seen the note. Accepted: it is the alert he built, on the interval he
  saw. Disabling migrated items was not part of the decision.
- **A toggle during the Alerts page's first sync after a migration is lost without a
  message** (§2f). Accepted and logged.
- **VWAP confirmations have the same '1D' shape.** A composite with a
  `mean_reversion_vwap` confirmation on a '1D' interval gets no intraday bars on the rule
  path. The decision doesn't cover it; this goes in as an open question in
  PROJECT_STATE.json, not fixed here.
- `putRuleToAPI` / `pushRuleToAPI` ignore HTTP status (pre-existing, fire-and-forget).
  Unchanged.

## 5. Verification before merge

`python3 scripts/state.py` exit 0. Backend `.venv/bin/python -m pytest -q`: the baseline is
**3106 passed / 1 skipped** (main after A4e); record the new figure. Frontend
`npx tsc --noEmit && npx jest`, with the baseline count recorded before building. Each
mutant M1-M11 is run and seen to fail its named test. `git status` shows
`backend/config/strategy_watches.yaml` unmodified after the full backend run.

## 6. Plan round 1 (2026-09-25) -- NOT CLEAN, three gate-level findings; plan to be revised

Fresh subagent, bmad-review-adversarial-general. NOT YET APPLIED to §1-§5 above -- the next
session revises the plan, then runs plan round 2.

1. **§1's claim about '1D' composite RULES is false.** On a '1D' rule the HMM_intraday checker
   gets no intraday bars: it never fires and logs a WARNING every tick (reproduced by calling
   the checker directly). The rules are dead exactly like the watches.
   **DECISION A4F-MIGRATE-LEGACY-RULES-TOO-2026-09-25 (Kenneth, on the corrected facts): MIGRATE
   them to '5m' as well**, by the same mechanism as the watches: a one-shot pass at backend
   startup sets each stored HMM_intraday composite rule on '1D'/'1W' to interval '5m', logs every
   migrated rule, and marks the rule's name with an 'interval was 1D' note. Rejected: leave them
   and only report.
2. **T3 would write into the tracked backend/config/strategy_watches.yaml** (scheduler enabled,
   so the AAPL test watch could send real Gmail/Telegram). T3 must use the temp-file + reload
   pattern of tests/test_strategy_watch_router.py.
3. **Wrong rules path:** the endpoint is `/alerts/rules`, not `/api/chart-alerts/rules`. T4/T5 as
   written would 404 and "fail on old code" vacuously. Fix every path in §2-§3.

Sub-gate items the reviewer raised (not blocking; take the cheap ones into the revision, log the
rest): the M6 mutant is not killable by T6 as written; the watch-file load could crash startup on
a hand-edited non-dict `trigger_def` / non-string `interval` (keep today's tolerance); the
'was 1D; set to 5m' note cannot use `Text title=` (no such prop -- typecheck) and must not break
the Alerts row layout; one T8 assertion already holds on today's code; watch rejection is 400 but
rule rejection is 422; a long-dead watch can fire immediately after migration before Kenneth sees
the note; a migrated watch may say 'was 1D' when the user never stored it; §5's count is stale
(baseline now 3106 / 1); VWAP confirmations have the same '1D' shape (out of this decision -- log it).

**Disposition of round 1 (revision 2):** finding 1 → §1 corrected, and §2e plus T8 added
under decision A4F-MIGRATE-LEGACY-RULES-TOO-2026-09-25. Finding 2 → T3 uses the
temp-file-and-reload fixture and asserts the tracked file is unchanged; the watch migration
also moved out of `load()` into an explicit startup call (§2d). Finding 3 → every rules
path is now `/alerts/rules`, and T4 checks the path exists first. Sub-gate items: M6
killable (T6's hand-edited strategy watch); non-dict/non-string tolerance (`isinstance`
guards; T1/T6); no `Text title=` (tooltip on a `<span>`, one grid child; T12); T8's
non-discriminating assertion dropped (now T10); 400-vs-422 kept per router convention
(§2b); fire-on-migration and the toggle race accepted and logged (§4); "was 1D" when the
field was never stored (`from_was_default`; §2d/§2g; T6/T12); baseline count updated (§5);
VWAP logged (§4).

## 7. Plan round 2

(pending)
