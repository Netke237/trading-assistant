# A4f — HMM_intraday composite watches: intraday interval default + stored-watch migration

Branch `claude/wizardly-ritchie-ndb5sg`, restarted off main `e2bf498` (A4e merged).
Item (3) of decision A4C-FOLLOWUPS-LOCKED-2026-09-24:

> UI bug: CompositeAlertDialog initialises interval '1D' and shows the 5m-4h select only for
> HMM_intraday, so an untouched select stores '1D' (the browser most likely DISPLAYED '5m', the
> first option -- verify). Backend rejects HMM_intraday with 1D/1W; the dialog sets an intraday
> default when HMM_intraday is chosen; EXISTING stored watches are migrated to '5m' (what the
> user most likely saw), with the list of migrated watches reported, not changed silently.

Two layers (one dialog file + one store/one helper), well under the ~500-line batch size.

## 1. Verification the decision asked for (done before planning)

**The browser displayed `5m` and saved `1D`. Confirmed.** Scratch Jest test (jsdom, the repo's
own react-dom): render the dialog, switch Model to `HMM_intraday`, touch nothing else.
The Interval `<select>` reads `value === '5m'`, `selectedIndex === 0`. React's controlled
`<select>` selects the first enabled option when no option matches the state value `'1D'`.
Create Alert then calls `addCompositeWatch('AAPL', …, 'Bullish', '1D')`. The snapshot request
also goes out with `interval='1D'`.

**What a stored `1D` HMM_intraday watch does today: it never fires.** It does not fire wrongly.
`strategy_watch_evaluator` calls `fetch_intraday_candles(symbol, interval='1D', days=55)`.
`normalize_interval` maps that to `daily`, and yfinance returns ~38 daily bars.
`completed_bars_for_interval` returns daily bars unchanged. `compute_intraday_hmm` needs
`MIN_BARS = 200`, so it returns `None`, and `_check_primary_hmm(None)` is `False`. The watch is
silently dead. For the same reason the dialog's snapshot box said "Live regime unavailable"
(the 422 path).

**Consequence of the locked migration, stated plainly:** moving these watches to `5m` makes them
LIVE for the first time. From the next evaluation they can fire Gmail/Telegram notifications.
That is the decision's intent (the user asked for an intraday watch and saw `5m`), and it is
why the migration is reported rather than silent.

**The committed `backend/config/strategy_watches.yaml` has no composite watches.** The
migration therefore acts only on Kenneth's local file, at load, so the report has to come
from the running backend (§2, B2).

## 2. The change

### F1 — `frontend/components/organisms/CompositeAlertDialog/index.tsx`
The Model `onChange` also sets the interval: `HMM_intraday` → `'5m'`, and every other model →
`'1D'`, which is today's value for them. Both delivery modes share this state, so the Watch
and the live Rule both get it. The initial state stays `'1D'`, because the initial model is
`OMM`. After this change the Interval select's displayed value always equals the saved value.

### B1 — backend rejects HMM_intraday with a non-intraday interval
- `backend/app/data/market.py`: `is_intraday_interval(interval) -> bool` is true iff
  `interval` is a `str` and `normalize_interval(interval)` is a key of
  `_INTERVAL_COMPLETION_SECONDS`. That covers 1m/1min, 5m/5min, 15m/15min, 30m/30min, 1h/60m
  and 4h. It is the same table A4c uses to decide what is "intraday", so there is one source of
  truth.
- `StrategyWatchStore.add_composite_watch`: if the primary model is `HMM_intraday` and
  `not is_intraday_interval(interval)`, it raises `ValueError`. The model is read as
  `(trigger_def.get("primary") or {}).get("model")`, guarded against a non-dict primary. The
  router already maps `ValueError` to 400. This is an allowlist, so `1D`, `1W`, `daily`,
  `weekly` and garbage are all rejected. The decision names 1D/1W, and garbage would be the
  same dead watch.

### B2 — migrate stored watches at load, reported
In `StrategyWatchStore.load()`, after the existing `setdefault` loop and under the same lock:
for each entry with `watch_type == "composite"`, a dict `trigger_def`, a dict `primary` with
`model == "HMM_intraday"`, and `not is_intraday_interval(interval)`:
- set `interval = "5m"` and `interval_migrated_from = <old value>`. This marker persists in
  the YAML and comes back from `GET /api/composite-watches/`.
- `last_state` and `enabled` are left untouched.

After the lock is released, if any entry was migrated, call `save()` once so the change and the
marker are durable. Then log ONE `WARNING` naming every migrated watch:
`A4f: migrated N HMM_intraday composite watch(es) from a daily/weekly interval to '5m' (they
never fired before; they are now live): [id symbol old_interval, …]`. The migration is
idempotent: a migrated entry is intraday, so it is not selected again. A `save()` failure
propagates like any other `save()` failure. The in-memory migration still applies, so the
evaluator uses `5m` either way.

### Out of scope (logged for Kenneth, not changed)
- **Chart-drawn composite RULES (`/alerts/rules`, `rule_type='composite'`) with
  `HMM_intraday` on `1D`.** Unlike watches, these are not dead. The chart path fits the HMM on
  the rule's own live candles, which are daily there, so they run as a daily-bar HMM labelled
  "intraday". The dialog fix stops new ones. Rejecting or migrating existing rows is a
  separate DB change with a behaviour change, so it is Kenneth's call.
- **An OMM/HMM_daily watch with the `mean_reversion_vwap` confirmation** fetches its "intraday
  15m" bars at the watch's interval, which is `1D`. VWAP then runs on daily bars. This is
  pre-existing and unrelated to the HMM_intraday default.
- The snapshot endpoint accepting `HMM_intraday` + `1D` is display-only and unreachable from
  the fixed dialog.

## 3. Tests
Frontend (`CompositeAlertDialog.test.tsx`, new cases):
- FE1: switch to HMM_intraday and save untouched. Displayed value `'5m'` and the saved interval
  is `'5m'`, for Watch and for Rule.
- FE2: switch HMM_intraday → OMM and save. The saved interval is `'1D'`.
- FE3: the snapshot request after switching to HMM_intraday uses `'5m'`.
- FE4: pick `'1h'`, then save. The saved interval is `'1h'`, so a user choice is not
  overridden.

Backend (`backend/tests/test_a4f_hmm_intraday_interval.py`):
- B1a: `is_intraday_interval` is true for each intraday spelling, and false for
  1D/1W/daily/weekly/''/None/'foo'.
- B1b: the store rejects HMM_intraday + 1D and + 1W. It accepts HMM_intraday + 5m/15m/1h/4h,
  and it still accepts OMM/HMM_daily + 1D.
- B1c: the router answers POST HMM_intraday + 1D with 400, and nothing is stored.
- B2a: a YAML with mixed entries. Only the HMM_intraday + 1D/1W/missing-interval composite
  entries become `5m` with `interval_migrated_from`. Strategy watches, OMM/HMM_daily 1D
  composites and HMM_intraday 15m entries are byte-identical. `last_state` and `enabled` are
  kept.
- B2b: the migration is persisted. A reload from disk shows `5m` plus the marker. A second load
  migrates nothing, saves nothing and logs nothing.
- B2c: one WARNING names every migrated id. No log and no save when nothing is migrated.
- B2d: end to end. The evaluator fetches intraday bars at `'5m'` for a migrated watch
  (`fetch_intraday_candles` patched and its interval asserted).

Mutations to kill: F1 not applied on the HMM_intraday branch, F1 not reset to 1D; B1 check
removed or inverted; allowlist replaced by `!= '1D'` (1W passes); migration drops the marker;
migration touches OMM 1D; no `save()` after migration.

## 4. Process
Plan round 1: fresh subagent, bmad-review-adversarial-general, briefed on the gate (a wrong
number to a user or broker, or corrupt persisted data). Build, then a code round limited to the
build diff. Merge when a round comes back clean. The hard cap is 3.
