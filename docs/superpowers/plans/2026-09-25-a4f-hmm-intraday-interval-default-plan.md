# A4f — HMM_intraday interval default + stored-watch migration

Branch `claude/dazzling-ride-0unofk`, restarted off main `e2bf498` (A4e merged).
Item (3) of decision A4C-FOLLOWUPS-LOCKED-2026-09-24:

> UI bug: CompositeAlertDialog initialises interval '1D' and shows the 5m-4h select only for
> HMM_intraday, so an untouched select stores '1D' (the browser most likely DISPLAYED '5m',
> the first option -- verify). Backend rejects HMM_intraday with 1D/1W; the dialog sets an
> intraday default when HMM_intraday is chosen; EXISTING stored watches are migrated to '5m'
> (what the user most likely saw), with the list of migrated watches reported, not changed
> silently.

## 1. Verification (done before planning)

**What the user saw: '5m'. Confirmed.** A controlled `<select value="1D">` whose options are
`5m,15m,30m,1h,4h` renders with `value === '5m'`, `selectedIndex === 0` (probe under the
repo's jest/jsdom + react-dom. React's `updateOptions` selects the first non-disabled
option when no option matches, so the same holds in a real browser). The user saw '5m' and
saved '1D'.

**What a stored '1D' HMM_intraday WATCH does today: nothing, silently.**
`strategy_watch_evaluator` calls `fetch_intraday_candles(symbol, interval='1D', days=55)`.
'1D' normalises to `daily`, so this returns about 38 daily bars. `completed_bars_for_interval`
returns them unchanged (daily is outside `_INTERVAL_COMPLETION_SECONDS`), and
`compute_intraday_hmm` returns `None` below `MIN_BARS = 200`. The primary check fails, so the
watch never fires and logs nothing at WARNING. The dialog's live snapshot for the same inputs
gets a 422 ("insufficient history"), so the user most likely saw the snapshot error line too.

**What a stored '1D' HMM_intraday composite RULE (chart_alerts, "rule" delivery mode) does:
it runs, but on a different model.** The chart-alert scheduler groups rules by
`(symbol, interval)` and feeds the rule's own interval's live candles. A '1D' rule fits the
HMM on up to `MAX_LIVE_MODEL_CANDLES` live DAILY candles, which is enough bars. So it
evaluates, but as a daily HMM, not the 5m one the user saw. The locked decision names
stored WATCHES only, so rules are NOT migrated here (§4, open question for Kenneth).

**Where HMM_intraday + interval is created:** only `CompositeAlertDialog`. Its two submit
paths are `api.addCompositeWatch(symbol, triggerDef, direction, interval)` (POST
`/api/composite-watches/`) and `api.addCompositeAlertRule(name, symbol, interval, triggerDef)`
(POST `/api/chart-alerts/rules`, `rule_type: 'composite'`). `chartAlertStore.putRuleToAPI`
re-sends an existing composite rule's interval + composite_def on every PUT, including an
`enabled` toggle. The Alerts page has no composite editor.

## 2. The change

### 2a. One shared predicate (backend)

`app/data/market.py`, next to `completed_bars_for_interval`:

```python
def is_intraday_interval(interval: str) -> bool:
    """True iff `interval` (any accepted spelling) is one of the intraday intervals
    the user-built alert models run on (`_INTERVAL_COMPLETION_SECONDS`).
    Daily, weekly and unrecognised strings are False."""
    return normalize_interval(interval) in _INTERVAL_COMPLETION_SECONDS
```

This reuses the table A4c already made authoritative for "intraday interval". Rejecting
everything outside it covers 1D/1W, daily/weekly and garbage strings. `1min` stays
accepted: the table has it, and the dialog doesn't offer it. `_INTERVAL_COMPLETION_SECONDS` is
not a free-form dict, so a non-string `interval` (Pydantic already types it `str`) is not a
concern.

A tiny helper in `app/services/composite_trigger_evaluator.py` (where the model semantics
live), used by every write path below:

```python
HMM_INTRADAY_INTERVAL_ERROR = ("HMM_intraday needs an intraday interval "
                               "(5m, 15m, 30m, 1h or 4h); got {interval!r}")

def hmm_intraday_interval_error(trigger_def: dict | None, interval: str) -> str | None:
    model = ((trigger_def or {}).get("primary") or {}).get("model")
    if model == "HMM_intraday" and not is_intraday_interval(interval):
        return HMM_INTRADAY_INTERVAL_ERROR.format(interval=interval)
    return None
```

`primary` may be missing or not a dict in a hand-built body. `.get` on a non-dict raises, so
guard it with `isinstance(..., dict)` and treat a non-dict as "no model", meaning no
rejection. Other validation owns malformed bodies, and this check must not 500.

### 2b. Backend rejects (new writes only)

- **`StrategyWatchStore.add_composite_watch`** raises `ValueError(msg)` when the helper
  returns a message. The router already maps `ValueError` to 400. Putting it in the store
  (not just the router) covers every caller.
- **`POST /api/chart-alerts/rules`** with `rule_type == 'composite'`: 422 with the message,
  before the row is built.
- **`PUT /api/chart-alerts/rules/{id}`** with `rule_type == 'composite'`: 422 ONLY IF the
  pair is invalid AND the PUT changes the stored pair. The pair is the interval and the
  primary model. A legacy '1D' HMM_intraday rule must still toggle `enabled`, rename and
  delete. `putRuleToAPI` re-sends the unchanged pair on every toggle, and rejecting that would
  strand the rule with no way to edit it in the UI. The comparison is against the row
  BEFORE the assignments at the top of `replace_rule`, so it is taken first. Stored model is
  read from `json.loads(row.rule_json)` (a composite row's `primary.model`). A row whose
  `rule_json` does not parse, or is not composite, counts as "changed". A PUT that turns a
  standard rule into an invalid composite one is rejected.
- **Not changed:** `GET /api/composite-watches/regime-snapshot` (read-only, and it already
  fails with 422 on '1D'), and the evaluators. A migrated store never hands them a bad pair,
  and a rule the PUT exemption keeps behaves exactly as today.

### 2c. Dialog sets the intraday default

`CompositeAlertDialog` model `onChange`:
`setIntervalVal(next === 'HMM_intraday' ? '5m' : '1D')`, alongside the existing
`setToState('any')`. '5m' is the first option (what an untouched select shows).
Switching away resets to '1D', so OMM/HMM_daily/any rules keep today's daily chart interval,
and a watch keeps today's stored value.
The snapshot effect already depends on `interval`, so it refetches with the value the watch
will store. The initial state stays `'1D'`, because the initial model is OMM.

### 2d. Existing stored watches migrated to '5m', reported

In `StrategyWatchStore.load()`, after the existing `setdefault` block, for each watch where
`watch_type == 'composite'` AND the helper returns a message for
`(trigger_def, interval)`:

- set `interval = "5m"`
- set `interval_migrated = {"from": <old>, "to": "5m", "at": <utc iso>, "reason": "A4f: HMM_intraday cannot run on a daily/weekly interval; 5m is what the dialog displayed"}`
- collect `(id, symbol, old)`.

After releasing the lock, if any were migrated:
- one `logger.warning("strategy_watch_store: A4f migrated %d HMM_intraday watch(es) to 5m: %s", n, "; ".join(f"{id} {symbol} {old}->5m"))`
- `self.save()`, so the migration is persisted once and not re-logged at every start.
  `save()` takes the lock itself, so it must be called outside the `with` block, or it
  deadlocks (`threading.Lock` is not re-entrant).

Idempotent: a migrated watch has an intraday interval, so the second load skips it. The
`interval_migrated` marker is kept (never cleared), so the record survives.
`last_state` is untouched. The watch never fired, so there is no `pending_entry_since` or
armed state from the dead period. The `trigger_def` is untouched.

A save failure (read-only file system) must not break `load()`. Wrap the save in
`try/except OSError` + `logger.warning`: the in-memory store is still migrated for this
process, and the next start retries.

**Reported in the UI:** the Alerts page's composite-watch row already shows `w.interval`.
Under it, when `w.interval_migrated` is present, render
`<Text size={11} tone="caution">was {from}; set to {to} (A4f)</Text>` with a `title`
tooltip carrying the reason. `CompositeWatch` in `lib/api.ts` gains
`interval_migrated?: { from: string; to: string; at: string; reason: string }`.

## 3. Tests (each must fail on the pre-change code: mutation-checked)

Backend:
- **T1** `is_intraday_interval`: True for 5m/5min/15m/30m/1h/60m/4h/1min, False for
  1D/1W/daily/weekly/''/'foo'.
- **T2** `hmm_intraday_interval_error`: message for HMM_intraday+1D and HMM_intraday+1W.
  None for HMM_intraday+15m, OMM+1D, HMM_daily+1D, missing primary, primary not a dict,
  trigger_def None.
- **T3** POST `/api/composite-watches/` HMM_intraday+'1D' → 400, nothing stored.
  HMM_intraday+'15m' → 201. OMM+'1D' → 201.
- **T4** POST `/api/chart-alerts/rules` composite HMM_intraday+'1D' → 422, no row.
  HMM_intraday+'5m' → 201.
- **T5** PUT: a seeded legacy composite HMM_intraday+'1D' row accepts an `enabled` toggle with
  the same pair (200, enabled changed, interval still '1D'). The same row PUT with interval
  '1W' → 422. A valid OMM+'1D' composite row PUT to HMM_intraday+'1D' → 422. A standard row
  PUT to composite HMM_intraday+'1D' → 422.
- **T6** load migration: a YAML with 4 watches (composite HMM_intraday '1D'; composite
  HMM_intraday '1W'; composite HMM_intraday '15m'; composite OMM '1D'; plus a strategy watch
  '1D'). After load, the first two are '5m' with `interval_migrated.from` = '1D'/'1W', and the
  rest are unchanged, with no marker. The file on disk is rewritten with the migration. One
  WARNING names both ids (caplog). A second store loaded from that file migrates nothing and
  logs no A4f warning.
- **T7** load migration survives a failing save: monkeypatch `save` to raise `OSError`.
  `load()` does not raise, and the in-memory watch is '5m'.

Frontend (`CompositeAlertDialog.test.tsx`):
- **T8** choosing HMM_intraday then Save as Watch calls `addCompositeWatch(..., '5m')`, and
  the Interval select shows '5m'. The snapshot is refetched with `'HMM_intraday', ..., '5m'`.
- **T9** HMM_intraday → pick '1h' → back to OMM → Save as Rule calls
  `addCompositeAlertRule(name, sym, '1D', …)`.
- **T10** Alerts page renders the "was 1D; set to 5m" note for a watch with
  `interval_migrated`, and no note without it. The page test file, if one exists for the
  watches tab, gets this. Otherwise a focused render test of the row.

Mutations to kill:
- M1 dialog onChange without the interval reset (T8)
- M2 `is_intraday_interval` returning True always (T1/T3/T6)
- M3 PUT rejecting regardless of "changed" (T5 toggle)
- M4 PUT never rejecting (T5)
- M5 migration without `save()` (T6 disk check)
- M6 migration outside the composite check, which would touch the strategy watch (T6)

## 4. Out of scope / for Kenneth

- ~~Existing composite RULES stay as they are~~ -- SUPERSEDED, see §6.
- The dialog does not offer `1min`, and the backend accepts it. That is unchanged.

## 5. Verification before merge

`python3 scripts/state.py` exit 0. Backend `.venv/bin/python -m pytest -q` (main: 3063+A4e's;
record the new figure). Frontend `npx tsc --noEmit && npx jest`. Each new test is run
against its mutation and seen to fail.

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
