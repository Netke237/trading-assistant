# Scheduler timezone awareness + audit.log trimming — implementation plan

Status: plan only, no code changed yet. Written for a swing trader operating from
Germany (default reference timezone: `Europe/Berlin`, CET/CEST) who trades a
US-equity universe (SP500/NDX100/DOW30) and needs jobs "flexible" — configurable,
correct regardless of where the backend process happens to be hosted, and never
silently wrong across the US/EU daylight-saving transition weeks.

Every claim below was checked against the current source in this repo (branch
`claude/bamendjou-scheduler-ordering-eg8rcv`) — file/line references are given so
each item can be re-verified before implementation.

---

## Part 1 — Timezone awareness for all background jobs

### 1.1 Verified current state

| Job | File | How "when to run" is decided today | Timezone-aware? |
|---|---|---|---|
| Strategy tuning (WFO) | `backend/app/services/tuning_scheduler.py` | `APScheduler` `CronTrigger(hour, minute)`, no `timezone=` kwarg | No explicit tz — falls back to APScheduler's own default (see 1.2) |
| OHLCV ingestion | `backend/app/services/ingestion_scheduler.py` | same pattern | same |
| EDGAR fundamentals | `backend/app/services/edgar_scheduler.py` | same pattern | same |
| S&P 500 liquidity update | `backend/app/services/sp500_scheduler.py` | same pattern | same |
| IBKR keep-alive | `backend/app/services/ibkr_keepalive_scheduler.py` | `IntervalTrigger(seconds=45)` | N/A — pure interval, no clock-time semantics |
| Strategy watch evaluation | `backend/app/services/strategy_watch_scheduler.py` | Hand-rolled asyncio loop; `_market_open()` (line 22-27) compares `datetime.now()` to hardcoded `dtime(9,30)`/`dtime(16,0)`; EOD mode (line 53-58) compares `datetime.now()` to a configurable `eod_time` string, default `"16:15"` | **No** — `datetime.now()` called with zero arguments, genuinely naive, no offset attached at all |
| Scan scheduler | `backend/app/services/scan_scheduler.py` | `ZoneInfo(self._cfg.timezone_name)` (line 49), window is `window_start_hour <= now.hour < window_end_hour` in that zone | **Yes** — the only job that does this correctly today |
| Portfolio alert monitor | `backend/app/services/portfolio_alert_monitor.py` | Plain 60s interval loop, no clock-time gate | N/A — but see 1.4, its *data* timestamps are correctly UTC-aware |
| Regime-flip monitor | `backend/app/services/regime_monitor.py` | Plain N-minute interval loop (default 15, `regime_monitor_interval_minutes`), no clock-time gate | N/A — same, its timestamps are correctly UTC-aware |
| Chart-alert evaluator | `backend/app/services/chart_alert_scheduler.py` | Plain interval loop (default 60s, `checkIntervalSeconds`) | N/A |

Grep confirms `datetime.now()` called **with no arguments** (the genuinely naive,
no-offset form) appears in exactly one service file for scheduling purposes:
`strategy_watch_scheduler.py`, three call sites (lines 24, 43, 115). Every other
service (`regime_monitor.py`, `portfolio_alert_monitor.py`, the scan pipeline in
`routers/scan.py`, `alert_generator.py`) already calls `datetime.now(timezone.utc)`
for its own timestamps. **The naive-time defect is narrower than the original
handover suggested — it is not a codebase-wide pattern, it is one file.**

### 1.2 What "no explicit tz" actually means for the four `CronTrigger` jobs

APScheduler's `AsyncIOScheduler()`, when constructed with no `timezone=` argument,
resolves its default timezone once at scheduler-creation time from
`datetime.now().astimezone().tzinfo` — i.e. whatever the **host OS's** local
timezone is (via `tzlocal`/`zoneinfo`). This means:

- `CronTrigger(hour=2, minute=0)` fires at 02:00 **in the host machine's own OS
  timezone**, not necessarily UTC and not necessarily `Europe/Berlin` — it depends
  entirely on how the deployment container/VM's system clock is configured
  (confirmed: this session's own container reports `Etc/UTC`; production's OS tz
  is unknown and unverified — this is an infrastructure fact, not something the
  code declares).
- `next_run_time()` (e.g. `tuning_scheduler.py` line 58-63) returns
  `job.next_run_time.isoformat()`, which **does** carry a UTC offset (because
  APScheduler's resolved timezone is tz-aware internally) — so the frontend's
  `formatNextRun()` (`frontend/app/(frame)/settings/page.tsx` lines 1809-1819,
  1949-1957: `new Date(iso).toLocaleString(...)`) correctly converts it to the
  viewer's browser-local time for display. **The display path is fine already**;
  the problem is only that the *trigger's own reference frame* is an
  unstated/implicit OS setting rather than a declared, portable one.

Net effect: these four jobs work fine today *only as long as* the host OS clock
is set to the intended zone, and that fact isn't visible anywhere in the repo,
Settings UI, or API response — it's invisible infrastructure state. Moving the
deployment to a different host/region (or a container image with a different
base `TZ`) would silently shift all four jobs without any code or config change
signaling it.

### 1.3 Design principle — two different kinds of "timezone" here

This distinction matters and the plan must not collapse it:

- **Operator timezone** (`Europe/Berlin`, configurable) — governs jobs that only
  need *some quiet, convenient local hour*: tuning, ingestion, EDGAR, S&P 500
  liquidity update, and the future `audit.log` rotation job (Part 2). These don't
  care what real-world event they're near; they care about not competing with you
  or with market hours.
- **Market timezone** (`America/New_York`, fixed, not user-configurable) —
  governs anything whose correctness depends on a specific NYSE event: the
  `strategy_watch` EOD trigger and market-open gate, and the "post-close" framing
  of the scan window discussed earlier in this thread. This must never be
  satisfied by "whatever the operator's local zone is" — Berlin and New York
  drift relative to each other by about a week twice a year (EU and US flip
  daylight saving on different dates), so hardcoding an offset instead of using a
  real IANA zone name would be quietly wrong for those transition weeks even if
  it's "set once for Germany."

Conflating these two would just relocate the original bug rather than fix it —
e.g. if `strategy_watch`'s EOD gate were wired to the same `operator_timezone`
setting used by the nightly batch jobs, changing that setting later (say, you
relocate) would silently break the market-close gate along with it.

### 1.4 Data timestamps — verified, not assumed

Checked every place a timestamp is produced or stored that this thread's earlier
turns touched on ("execution time of a scan run" etc.):

- `ScanResult.timestamp` / `ScanHistoryEntry.timestamp` — both declared as plain
  `str` in `backend/app/schemas/__init__.py` (line 577) and
  `backend/app/schemas/scan.py` (line 30), but populated at the call site in
  `backend/app/routers/scan.py` (lines 1339, 1345) via
  `datetime.now(timezone.utc).isoformat()` — **UTC-aware, correct**, includes an
  offset. No change needed.
- `alert_generator.py` (line 98-99): `now = datetime.now(timezone.utc)` — correct.
- `portfolio_alert_monitor.py` (line 168): `datetime.now(timezone.utc).isoformat()`
  — correct.
- `regime_monitor.py` (lines 163, 213, 230): `datetime.now(timezone.utc)`
  throughout, including the `_reject_since` sustain-clock — correct.
- Every relevant SQLAlchemy model column is `DateTime(timezone=True)`:
  `models/base.py` (`created_at`/`updated_at`), `models/closed_position.py`,
  `models/audit_event.py`, `models/portfolio.py`, `models/scan_session.py`,
  `models/position_alert.py`, `models/watchlist.py`, `models/ohlcv_daily.py`,
  `models/fundamentals.py`, `models/watched_contracts.py`,
  `models/symbol_note.py` — all tz-aware at the DB layer already.

**Conclusion: the "timestamps on data" concern is already handled correctly
throughout the app.** The only real defect is in the *scheduling trigger logic*
covered in 1.1-1.3, not in how events/results are timestamped once they happen.
This plan does not need to touch any of the files in this subsection.

### 1.5 Implementation steps

**Step 1 — Add one shared constant and one shared config value.**

In a new small module, e.g. `backend/app/services/scheduling_tz.py`:

```python
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")  # NYSE — never user-configurable
```

Add `timezone: str = "Europe/Berlin"` under a new top-level `scheduling` block in
`settings.yaml` / `settings.example.yaml` (there is currently no app-wide
timezone setting anywhere in config — confirmed by grep, `settings.example.yaml`
has zero `timezone`/`Europe/` references today). This is the **operator
timezone**, read by a small helper:

```python
def operator_zone() -> ZoneInfo:
    return ZoneInfo(_load_settings().get("scheduling", {}).get("timezone", "Europe/Berlin"))
```

`_load_settings()` here is **`scheduling_tz.py`'s own private loader**, reading
only the `scheduling.timezone` key — it does not reuse any existing
`_load_settings()` elsewhere. Verified by grep: `routers/scan.py`,
`services/portfolio_alert_monitor.py`, and `routers/risk_settings.py` each
already define their *own* private `_load_settings()` with different
behavior (`routers/scan.py`'s falls back to `settings.example.yaml` on a
missing file; `portfolio_alert_monitor.py`'s returns `{}` on any error, no
fallback). This is a fifth, deliberately separate copy, consistent with that
existing per-file-private-loader convention — not an import of a shared
utility that doesn't exist.

**Step 2 — Pin the four `CronTrigger` jobs to the operator timezone, and make timezone changes take effect without a restart.**

In `tuning_scheduler.py`, `ingestion_scheduler.py`, `edgar_scheduler.py`,
`sp500_scheduler.py` — each `_get()` currently does
`AsyncIOScheduler()` with no arguments (e.g. `tuning_scheduler.py` line 17-19),
constructed once and cached in a module-level singleton. A naive
`AsyncIOScheduler(timezone=operator_zone())` swap would only apply the
timezone at process-boot time — the Settings-UI timezone field added in Step 4
would then silently do nothing until a full restart, unlike every other field
on that panel (hour/minute), which already takes effect immediately via
`configure()`. To keep that "changes apply immediately" property, `configure()`
must rebuild the scheduler when the timezone differs from what it was built
with, not just add/remove the job on the existing instance:

```python
from app.services.scheduling_tz import operator_zone

_scheduler: AsyncIOScheduler | None = None
_scheduler_tz_key: str | None = None  # str(ZoneInfo) of the zone the current scheduler was built with

def _get() -> AsyncIOScheduler:
    global _scheduler, _scheduler_tz_key
    zone = operator_zone()
    zone_key = str(zone)
    if _scheduler is None or _scheduler_tz_key != zone_key:
        if _scheduler is not None and _scheduler.running:
            _scheduler.shutdown(wait=False)
        _scheduler = AsyncIOScheduler(timezone=zone)
        _scheduler_tz_key = zone_key
        _scheduler.start()
    return _scheduler
```

`configure()` already calls `_get()` before adding/removing the job (per the
existing code in every one of these four files), so this rebuild happens for
free on every settings save that changes the timezone — no separate wiring
needed. This also means `start()`'s existing `if not sched.running: sched.start()`
guard in each file becomes redundant with `_get()` now starting the scheduler
itself on (re)construction; keep it as a no-op safety net rather than removing
it, since `main.py`'s startup hook still calls `configure()` then `start()` in
sequence per the existing pattern.

This removes the dependency on host OS clock configuration entirely — "02:00"
now unambiguously means 02:00 Berlin time (CET/CEST, DST-aware via `zoneinfo`)
regardless of what timezone the container's OS happens to be set to, today or
after any future redeploy/host move, **and** stays correct if the operator
timezone setting itself is later changed, without requiring a restart. No
change needed to the default hour values themselves — per Part 0, those are
fine as "quiet overnight" markers once anchored to a real, declared zone
instead of an implicit one.

**Step 2a — Give `tuning_scheduler.py` a real day-of-week dimension, required by Part 0's "Saturday 05:00 only" default.**

Checked: `tuning_schedule_store.py`'s schema is `{enabled, time}` only, and
`strategy_tuning.py`'s `PUT` handler calls
`tuning_scheduler.configure(body.enabled, body.time)` with no day concept
anywhere in the chain. Part 0's "Saturday-only" default is not buildable
without this — add it explicitly, scoped to `tuning_scheduler.py` only (the
other three nightly jobs run every day, per Part 0, and don't need this):

- `tuning_schedule_store.py`: extend `_DEFAULTS` to
  `{"enabled": False, "time": "05:00", "days_of_week": [5]}` (5 = Saturday,
  matching Python's `datetime.weekday()`/APScheduler's own 0=Mon convention —
  confirm APScheduler's `CronTrigger(day_of_week=...)` accepts either int or
  the `"sat"`-style string form during implementation and pick whichever the
  rest of this codebase's cron usage already favors, for consistency).
- `strategy_tuning.py`'s schedule request/response model and `PUT` handler:
  add `days_of_week: list[int]` alongside `enabled`/`time`.
- `tuning_scheduler.configure(enabled, time_str, days_of_week)`: pass
  `CronTrigger(hour=hour, minute=minute, day_of_week=",".join(map(str, days_of_week)))`
  instead of the current `CronTrigger(hour=hour, minute=minute)`.
- **`tuning_schedule_store.py`'s `set(self, enabled: bool, time: str)`
  (line 40) must also gain the parameter** — audit round 2 caught that the
  original version of this step updated `_DEFAULTS`, the router model, and
  `configure()`'s signature, but not `set()`/its call site
  (`strategy_tuning.py` line 169: `tuning_schedule_store.set(body.enabled, body.time)`).
  Without this, a posted `days_of_week` would take effect on the live
  in-memory scheduler but never persist to `tuning_schedule.yaml`, silently
  reverting to `[5]` on next restart. Change to
  `set(self, enabled: bool, time: str, days_of_week: list[int])` and update
  the call site to pass it through.
- Frontend Settings UI (the same `DataForm`-style component used for
  ingestion/EDGAR/S&P 500 in `frontend/app/(frame)/settings/page.tsx`): add a
  day-of-week picker to tuning's schedule form specifically — the other three
  forms don't need one since they stay daily.

**Step 3a — Give the new `scheduling.timezone` operator setting (Step 1) an
actual way to be changed.** Audit round 2 caught that Step 1 adds a brand-new
`scheduling.timezone` key to `settings.yaml`, but nothing in this plan gives
the operator a way to set it — Step 4 below only covers `ScheduleConfig`'s
*pre-existing*, unrelated `timezone_name` field (scoped to the scan-window
scheduler only). Add a small dedicated endpoint pair,
`GET/PUT /api/settings/scheduling` (new router or a couple of routes added to
`risk_settings.py` alongside the existing `/settings/schedule` ones), backed
by a `{"timezone": str}` Pydantic model, reading/writing the same
`scheduling.timezone` key `operator_zone()` reads — plus one field in the
Settings UI (a timezone-name input, same style as Step 4's) to drive it. Without
this, `Europe/Berlin` is only changeable by hand-editing `settings.yaml` on
the server, contradicting the plan's own framing of it as "operator timezone
(configurable)."

**Step 3 — Fix `strategy_watch_scheduler.py` to use `MARKET_TZ`, not naive local time.**

Replace all three `datetime.now()` call sites:

```python
from app.services.scheduling_tz import MARKET_TZ

def _market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(MARKET_TZ)
    if now.weekday() >= 5:
        return False
    return dtime(9, 30) <= now.time() <= dtime(16, 0)
```

and in `_maybe_run()`:
```python
now = now or datetime.now(MARKET_TZ)
...
if now.time() < dtime(hh, mm):
```
and in `run_now()` (line 115): `self._last_run_at = datetime.now(MARKET_TZ)`.

This makes both the EOD trigger and the poll-mode market-open gate track the
*real* NYSE session regardless of host location — correct in Germany, correct if
the host ever moves, correct across both countries' DST transition weeks since
`zoneinfo` resolves the actual local offset for `America/New_York` on each call
rather than a fixed hardcoded offset.

Note: `_last_eod_run_date = now.date()` (dedup-per-day guard, line 63) will now
be a New-York calendar date rather than a server-local one — this is the
*correct* behavior for "did we already run today's EOD check," since "today" for
an EOD-after-close check should mean the NYSE trading day, not the operator's
own calendar day (these can differ by hours around midnight in either
direction).

**Step 4 — Fix `ScheduleConfig`'s default and expose it in the UI.**

`backend/app/schemas/schedule.py` line 12 currently defaults
`timezone_name: str = "Europe/Paris"`. Change to `"Europe/Berlin"`.

More importantly — verified by grep across
`frontend/app/(frame)/settings/page.tsx`: **there is currently no UI control for
`timezone_name`, `window_start_hour`, or `window_end_hour` at all**, even though
`GET/PUT /api/settings/schedule` (`routers/risk_settings.py` lines 177-186)
already reads/writes them. They're silently stuck at their Pydantic defaults
unless someone calls the API directly. Add three fields to the existing Scan
settings section (`SECTIONS` → Scan, per `CLAUDE.md`'s settings-page table):
a timezone name input (or a fixed dropdown of common zones, defaulting to
`Europe/Berlin`), and the two window-hour inputs, wired the same way the
existing `enabled`/`cadence_minutes` controls already are in that file.

**Step 5 — Multi-window scan scheduling (from earlier in this thread, still open).**

`ScheduleConfig` supports exactly one contiguous `window_start_hour`/
`window_end_hour` pair (validated `start < end`,
`backend/app/schemas/schedule.py` lines 14-20). A pre-market + post-close
two-window setup is not representable without a schema change:
`windows: list[tuple[int,int]]` replacing the two scalar fields, with
`ScanScheduler._should_run_now()` (`scan_scheduler.py` lines 45-53) updated to
check membership across all configured windows instead of one range. Flagged
here as a dependency of this plan but scoped as optional/separate — confirm
before including it in the same PR as Steps 1-4, since it's a schema change
with a settings-migration concern (existing single-window installs need a
default migration into the new list shape).

### 1.6 Tests

- `backend/tests/` — add a test module (mirroring existing scheduler tests if
  any exist under that pattern) asserting:
  - `tuning_scheduler.configure()` (and the other three) produces a
    `next_run_time()` whose UTC offset matches `Europe/Berlin` at that date
    (parametrize across a winter date and a summer date to catch a DST
    regression).
  - `strategy_watch_scheduler._market_open()` returns `True`/`False` correctly
    for a fixed New York wall-clock time, independent of what `TZ` the test
    runner's own OS is set to (set `TZ=Europe/Berlin` or `TZ=UTC` in the test
    environment and assert the result doesn't change — this is exactly the
    regression this plan closes).
  - `ScheduleConfig()` default now serializes `timezone_name == "Europe/Berlin"`.

---

## Part 2 — `audit.log` trimming

### 2.1 Verified current state

`backend/app/services/audit.py`:
- `_LOG_PATH` (line 14-15) resolves to `<repo-root>/audit.log` (or `backend/`,
  depending on where uvicorn is started — see the file's own comment).
- `log_event()` (line 29-62) appends one JSONL line per event — called for
  `scan_started`, `candidate_accepted`, `candidate_rejected`,
  `trade_card_created`, plus `approval`/`rejection`/`override` via the
  `log_approval`/`log_rejection`/`log_override` wrappers (lines 69-113), each
  of which *also* writes the same event to the `AuditEventModel` DB table.
- Grepped the entire `backend/` tree: **nothing reads `audit.log` back** —
  it's write-only from the app's own perspective. (Confirmed separately: no
  frontend route surfaces `AuditEventModel` either — see the earlier turn in
  this thread. Out of scope for this plan per your answer — "the most
  important is that Claude can search the logs.")
- No rotation, no size cap, no age-based deletion anywhere referencing this
  file. Confirmed via grep for `FileHandler`/`rotat`/`purge` across the whole
  backend — no hits.
- By contrast, three *other* data stores already have the equivalent pattern,
  all invoked from `portfolio_alert_monitor.py`'s `_run_once()` (lines 56-64
  and surrounding):
  - `sent_messages.log` (flat file) → `prune_sent_log(retentionDays)` in
    `services/notifications/sent_log.py` (lines 32-51) — rewrites the file,
    dropping lines older than the cutoff. Default 30 days.
  - `PositionAlertHistoryModel` (DB table) →
    `prune_position_alert_history(retention_days)` in
    `services/position_alert_log.py` (lines 116-129) — SQL `DELETE`.
  - `ClosedPositionModel` / `EquitySnapshotModel` / `AuditEventModel`
    **(the DB table, not the file)** → `prune_old_history(retention_years)` in
    `services/history_cleanup.py` (lines 22-70) — SQL `DELETE`, default
    `history_retention_years` from `settings.yaml`, default `10`.

So the DB copy of exactly this same audit data already expires after 10 years.
The flat-file copy never does.

### 2.2 Design — archive, don't delete

Per your stated purpose ("I log data so I am able to explain why I took some
trades" / "the most important is that Claude can search the logs") this should
**not** mirror `prune_sent_log`'s delete-in-place pattern. That pattern is fine
for a throwaway notification-dedup log; it's wrong for the one file that's your
actual trade-rationale trail. Design instead:

1. **Rotate monthly (or at a size cap), never delete the live file's content
   outright.** `audit.log` → renamed to `audit-2026-08.log` at rotation time; a
   fresh `audit.log` starts immediately after.
2. **Prune only the *archives*, and only after `history_retention_years`
   (reuse the existing setting — don't invent a second, inconsistent retention
   window)** — this keeps the file-based copy and the DB-based
   `AuditEventModel` copy expiring on the same clock, by design.
3. Archived files stay fully greppable exactly as-is (`grep pattern
   audit*.log`) — this satisfies "Claude can search the logs" better than one
   ever-growing file, since a search for a specific period can target one
   archive directly.

### 2.3 Implementation steps

**Step 1 — Rotation, in `backend/app/services/audit.py`.** Reviewed and
flagged: `log_event()` already opens/writes/closes `_LOG_PATH` with no
locking, and the size-cap rotation branch below does a read-then-truncate —
without a shared lock, a `log_event()` write landing between that read and
truncate would be silently dropped, for the one file whose entire purpose is
"never lose a trade-rationale record." Every other file-backed store in this
codebase (`tuning_schedule_store.py` etc.) guards its read-modify-write with
a `threading.Lock`; this needs the same, shared between `log_event()` and
rotation/pruning:

```python
import os
import threading
from datetime import datetime, timezone

_ROTATE_SIZE_BYTES = 20 * 1024 * 1024  # 20MB safety cap between monthly rotations
_log_lock = threading.Lock()  # shared by log_event(), rotate_audit_log(), prune_audit_log_archives()

def _archive_path_for(dt: datetime) -> str:
    return os.path.join(os.path.dirname(_LOG_PATH), f"audit-{dt:%Y-%m}.log")

def rotate_audit_log(now: datetime | None = None) -> None:
    """Rename audit.log to audit-YYYY-MM.log if the current month's archive
    doesn't exist yet, or if the live file has grown past the size cap.
    Called once nightly from the same batch as ingestion/EDGAR/tuning — see
    Part 1, Step 2's operator-timezone-anchored scheduler."""
    now = now or datetime.now(timezone.utc)
    with _log_lock:
        if not os.path.exists(_LOG_PATH):
            return
        archive = _archive_path_for(now)
        needs_rotation = not os.path.exists(archive) or os.path.getsize(_LOG_PATH) > _ROTATE_SIZE_BYTES
        if not needs_rotation:
            return
        try:
            # If today's archive already exists (mid-month size-triggered rotation),
            # append rather than clobber it.
            if os.path.exists(archive):
                with open(_LOG_PATH, "r", encoding="utf-8") as src, open(archive, "a", encoding="utf-8") as dst:
                    dst.write(src.read())
                open(_LOG_PATH, "w", encoding="utf-8").close()
            else:
                os.replace(_LOG_PATH, archive)
        except Exception:
            pass  # rotation failures are non-fatal, same policy as log_event() itself
```

`log_event()` (existing function, line 29-62) needs its `with open(_LOG_PATH, "a", ...)`
block wrapped in `with _log_lock:` too, so it can never interleave with a
rotation in progress.

**Step 2 — Archive pruning, same file:**

```python
import glob
import re
from datetime import timedelta

_ARCHIVE_RE = re.compile(r"audit-(\d{4})-(\d{2})\.log$")

def prune_audit_log_archives(retention_years: int) -> None:
    if retention_years <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_years * 365)
    with _log_lock:
        for path in glob.glob(os.path.join(os.path.dirname(_LOG_PATH), "audit-*.log")):
            m = _ARCHIVE_RE.search(path)
            if not m:
                continue
            archived_month = datetime(int(m.group(1)), int(m.group(2)), 1, tzinfo=timezone.utc)
            if archived_month < cutoff:
                try:
                    os.remove(path)
                except Exception:
                    pass
```

`retention_years * 365` has no leap-year adjustment — inherited imprecision,
not a new bug: `history_cleanup.prune_old_history` (the DB-side counterpart
this is deliberately kept in sync with) uses the exact same
`retention_years * 365` arithmetic today. Fixing it here alone would make the
file-based and DB-based copies of this same data expire on very slightly
different days at the margin, which is worse than both being equally
approximate. Leave as-is; if this is ever worth fixing, fix both together in
a separate change.

**Step 3 — Wire into the nightly batch**, reusing `history_retention_years`
from `settings.yaml` (same value `history_cleanup.prune_old_history` already
reads, so both copies expire together):

```python
async def _run_audit_log_maintenance() -> None:
    import asyncio
    from app.services.audit import rotate_audit_log, prune_audit_log_archives
    cfg = _load_settings()  # existing helper pattern from portfolio_alert_monitor.py
    retention_years = int(cfg.get('history_retention_years', 10))
    await asyncio.to_thread(rotate_audit_log)
    await asyncio.to_thread(prune_audit_log_archives, retention_years)
```

`rotate_audit_log`/`prune_audit_log_archives` stay plain synchronous
functions (`threading.Lock`, not `asyncio.Lock` — correct, since they're also
called from `log_event()`, which is itself synchronous and called from
non-async contexts elsewhere in the codebase). The async wrapper above is
what actually runs inside the scheduler job callback, and offloads the
blocking file I/O via `asyncio.to_thread` — audit round 2 flagged the
original version as running a potentially-20MB synchronous read/write
directly inside an async callback, unlike this codebase's established
convention elsewhere (e.g. `fetch_quotes` in `run_scan`). Bounded by the size
cap, so low real-world impact, but worth being consistent.

Add this as a fifth job (or a step inside one of the existing four) in the
operator-timezone-anchored overnight batch from Part 1, Step 2 — it does not
need its own separate cron entry; piggybacking on, e.g., the ingestion job's
nightly tick is enough, since this only needs to happen once a day.

**Step 4 — Tests**, mirroring `backend/tests/test_sent_log.py`'s structure
(confirmed this file exists and is the precedent to follow):
- Rotation creates `audit-YYYY-MM.log` and empties `audit.log`.
- Rotation is idempotent within the same month (doesn't re-rotate every call).
- Size-cap rotation mid-month appends to that month's existing archive rather
  than overwriting it.
- `prune_audit_log_archives` deletes archives older than the cutoff and leaves
  recent ones untouched.
- `retention_years <= 0` disables pruning, matching the other three
  `prune_*` functions' existing convention.

---

## Part 0 — Resolved default times (decided in this thread, applies across Parts 1-3)

All times below are **operator timezone** (`Europe/Berlin`) unless marked NY —
see 1.3 for the operator-vs-market distinction. These replace the shipped
defaults; Part 1, Step 2's `operator_zone()` anchor is what makes these numbers
mean what they say regardless of host OS.

| Job | New default | Reasoning |
|---|---|---|
| OHLCV ingestion | **02:00, every night** — moved off the shipped `03:00` | NYSE close (16:00 ET) ≈ 22:00 Berlin; 02:00 gives ~4h buffer for EOD data to finalize. Needs daily freshness. (Audit round 3: this is a real change from the shipped default, same as S&P 500's row below — the original table implied only S&P 500 changed; corrected.) |
| EDGAR fundamentals | **03:00, every night** — moved off the shipped `04:00` | After ingestion, same overnight block; no same-day urgency but no reason to separate. Also a real change from the shipped default, not "unchanged" as originally implied. |
| S&P 500 liquidity update | **04:00, every night** — moved off the shipped `16:30` | `16:30` only made sense under "server-local = US Eastern." Anchored to Berlin, `16:30` lands mid-US-session (10:30 ET) — wrong. Moved into the same overnight block. |
| Strategy tuning (WFO) | **Saturday 05:00 only, not nightly** | Compute-heavy, doesn't need daily freshness (verified: no EDGAR/fundamentals dependency, OHLCV-only via `historical_store.get_bars`'s self-heal). Weekly is the standard cadence; running after Friday's ingestion sees a full settled week. Set to 05:00, not 03:00 as in an earlier draft of this table — 03:00 would collide with EDGAR's *daily* 03:00 job on Saturdays specifically (EDGAR runs every day, tuning only Saturdays); 05:00 keeps the same sequential-overnight-block pattern already used for ingestion→EDGAR→S&P500, after both have had time to finish. |
| Strategy-watch EOD trigger | **16:30 America/New_York** (market timezone, not operator) | 30 min past the 16:00 ET close, matching the ingestion buffer logic. Deliberately NOT expressed in Berlin time — see 1.3. |
| `audit.log` rotation/prune | Piggybacks on the ingestion job, no separate slot | A few hundred lines/day doesn't need its own cadence. |
| New profile-based scan entries (Part 3) | User-defined per entry | See Part 3 — no single default, this is the point of the feature. |

## Part 3 — Profile-based scan scheduling (stock + options, `fixed_time` + `loop` patterns)

Resolved decisions from this thread, restated so the implementation has a
single source of truth:

- **Storage**: push-on-select/save. `searchProfilesStore` (`frontend/lib/searchProfilesStore.ts`)
  stays the frontend's browse/edit/create surface — it is not migrated. A new
  backend-side list of **schedule entries** is introduced; each entry holds its
  own copy (snapshot) of the profile content it points at, pushed from the
  frontend whenever that entry is created/edited, **and** re-pushed automatically
  whenever the frontend saves changes to a profile that an existing entry
  references (see 3.4 — this is how "live" semantics are achieved without the
  backend ever reading `localStorage` directly).
- **Multiplicity**: a list, not a slot — any number of entries, per mode,
  independently enabled.
- **Modes**: fully independent per mode — options entries and stocks entries
  never share a cadence/window; stocks-mode scheduled execution is new (today
  there is none — verified, `stock_scan.py` has no `_scheduled_scan`/
  `_last_request` equivalent despite `ScheduleConfig.enabled_stocks` existing
  as an unused flag).
- **Patterns**: both **`fixed_time`** (fires every matching weekday at one
  clock time — recurring, like every other job in this plan, *not* a
  single-ever-shot) and **`loop`** (cadence + window, repeating multiple times
  within a window — today's `ScanScheduler` behavior, generalized to run
  per-entry) are fully built now, for both modes — not stubbed. Renamed from
  the earlier "once" — audit round 1 caught that "once" implied single-shot
  while the design (a weekday-repeating `CronTrigger`) is actually recurring
  daily/weekly at a fixed time; `fixed_time` names what it does. `loop` exists
  today for a day-trading use case not yet in active use, but ships working.
- **Manual runs never affect the schedule — enforced structurally, not by
  convention.** Audit round 1 caught that the original design (`_run_scheduled_entry`
  calling `run_scan()`/`run_stock_scan()` directly) would have silently broken
  this: `run_scan()` unconditionally mutates `_last_request`/`_last_result`
  (`routers/scan.py` line 1358) and fires the armed auto-trader
  (`_auto_trader.maybe_fire_on_scan`) on any PASS candidate; `stock_scan.py`
  has the equivalent `_last_stock_request`/`_last_stock_result` globals. A
  Part-3-fired scan would have corrupted the UI's "last scan" state and could
  have placed an unattended live/paper trade with no warning anywhere in this
  plan. Fixed in 3.5 by factoring the actual scan-execution logic out of
  `run_scan`/`run_stock_scan` into a core helper that Part 3 calls directly,
  never touching those globals or the auto-trader. The pre-existing
  `_scheduled_scan()`/`_last_request`/`ScheduleConfig` continuous-scan
  mechanism is retired as part of this change — a schedule with zero entries
  now means "nothing scheduled," not "silently replay whatever was last
  clicked."
- **Profile editing semantics**: a profile only changes when explicitly saved
  (overwrite) or saved-as (new name/id) via `searchProfilesStore.saveProfile`/
  `updateProfile` — never from unsaved on-screen edits. Schedule entries follow
  the saved profile by id, so "live" means "always reflects the last explicit
  save," never mid-edit state.
- **UI**: a flat list of entries in Settings (no grouping structure), each with
  a free-text label (defaults to the profile's name).

### 3.1 New backend schema — pre-resolved request, not a raw profile snapshot

Audit round 1 flagged the original "store the raw `SearchProfileSnapshot` and
convert it server-side" design as the riskiest part of the whole plan, and it
was right: checked `frontend/types/searchProfile.ts`,
`frontend/lib/searchProfileSnapshot.ts`, `backend/app/schemas/stock_scan.py`,
and `backend/app/schemas/__init__.py`'s `ScanRequest` (line 502) directly, and
found real gaps, not just missing glue code:

- `StockScanRequest.strategy` is **required**, but `SearchProfile.strategy`/
  `strategyParams` are only populated once Step 5 has actually been visited —
  a profile saved before that point has neither.
- `StockScanRequest.account_size`/`risk_pct`/`risk_fixed_usd` have **no
  corresponding field anywhere in `SearchProfileSnapshot`** — those live in
  the separate `riskStore`, never captured by `captureCurrentSnapshot()`. A
  naive server-side conversion would silently fall back to request defaults
  ($50k, 1% risk) instead of the user's real position sizing.
- `SearchProfileUniverse` stores **unresolved raw strings**
  (`minPriceRaw`/`maxCapRaw`/`capUnit: 'M'|'B'`) plus a `pick` enum; the
  unit-conversion and validation, and the `horizonPreset`+`holdMax` →
  `Horizon` resolution, only exist today as frontend TypeScript
  (`applySearchProfile` in `searchProfileSnapshot.ts`). Reimplementing that
  logic a second time in Python is real, ongoing-maintenance duplication —
  two implementations of the same business rule that can silently drift.

**Fix: don't push a raw snapshot and convert it server-side at all. Push an
already-resolved request, computed client-side by reusing the exact same
code path the manual "Run Scan" button already calls** (the principle: one
resolution path, used by both the manual button and this feature, never a
second Python reimplementation of unit/horizon parsing).

**Correction (audit round 2): "reusing the manual path fixes the risk-fields
gap for free" is false as originally written, and checkable in the repo
today.** Read `frontend/lib/stockScan.ts`'s `runStockScan()` directly —
it never reads `riskStore` at all; its request body hardcodes
`account_size: 50_000, risk_pct: 0.01` unconditionally (this is the
*existing*, already-shipped manual-run behavior, not something this plan
introduces). Those two fields feed `_position_size()`
(`backend/app/routers/stock_scan.py` lines 613-618, 871-874) — the actual
share-count/dollar-risk shown on every candidate, not cosmetic. So "reuse
the manual path" alone does **not** close this gap; it would silently bake
the existing $50k/1% default into every scheduled entry forever, which is
worse than round 1's original concern since it looks fixed on paper.

**Real fix**: the client-side resolver this plan builds (3.4/open-items)
must explicitly read the live `riskStore` (`useRiskStore.getState()` or
equivalent) and set fields on the resolved request itself, **overriding**
whatever `runStockScan()`'s own request-building would otherwise produce —
not relying on that function's existing behavior to already do it, since it
demonstrably doesn't. **Correction (audit round 3): only two of the three
fields named above actually have a source.** Checked `riskStore.ts`'s
`RiskLimits` directly: `portfolioValue` → `account_size` and
`maxLossPerTradePct` → `risk_pct` both exist and map cleanly;
**`risk_fixed_usd` has no corresponding field anywhere in the frontend
today** (grep confirms it's never populated anywhere in the current
codebase — it's a backend-only optional field,
`StockScanRequest.risk_fixed_usd: Optional[float] = None`). The resolver
sets `account_size`/`risk_pct` from `riskStore`; `risk_fixed_usd` is left
`None` (its documented default) — stated explicitly here rather than
implied as a third mapped field. This is new logic the resolver adds on top
of reusing `runStockScan()`'s other field-mapping, not a byproduct of
calling it. Whether `runStockScan()`'s own hardcoded defaults are also worth
fixing for the *manual* path is a separate, pre-existing bug outside this
plan's scope — flagged here for visibility, not silently fixed as a side
effect.

New file `backend/app/schemas/scan_schedule.py`:

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

class ScanScheduleEntry(BaseModel):
    id:               str
    label:            str
    mode:             Literal['options', 'stocks']
    profile_id:       str              # frontend-side SearchProfile.id, for display/re-sync matching only
    profile_name:     str              # denormalized for display without a round-trip
    profile_synced_at: str             # ISO 8601, set by the frontend on every successful push (3.4) — lets the UI flag a stale/failed re-sync
    resolved_request:  dict            # a full ScanRequest or StockScanRequest body, already resolved client-side
    pattern:          Literal['fixed_time', 'loop']
    enabled:          bool = True
    days_of_week:     list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])

    # 'fixed_time' pattern — fires every matching weekday at this clock time
    fire_time: Optional[str] = None    # "HH:MM", operator timezone

    # 'loop' pattern — fires repeatedly on this cadence within this window
    cadence_minutes:   Optional[int] = Field(None, ge=5, le=1440)
    window_start_hour: Optional[int] = Field(None, ge=0, le=23)
    window_end_hour:   Optional[int] = Field(None, ge=1, le=24)

    @model_validator(mode='after')
    def check_pattern_fields(self) -> 'ScanScheduleEntry':
        if self.pattern == 'fixed_time' and not self.fire_time:
            raise ValueError("fire_time is required for pattern='fixed_time'")
        if self.pattern == 'loop':
            if self.cadence_minutes is None or self.window_start_hour is None or self.window_end_hour is None:
                raise ValueError("cadence_minutes/window_start_hour/window_end_hour required for pattern='loop'")
            if self.window_start_hour >= self.window_end_hour:
                raise ValueError("window_start_hour must be less than window_end_hour")
        return self

    @model_validator(mode='after')
    def check_resolved_request_shape(self) -> 'ScanScheduleEntry':
        # Validate resolved_request actually parses as the right request type
        # for this entry's mode — catches a stale/malformed push at save time,
        # not silently at fire time. Import locally to avoid a schema-module cycle.
        from app.schemas import ScanRequest
        from app.schemas.stock_scan import StockScanRequest
        try:
            if self.mode == 'options':
                ScanRequest.model_validate(self.resolved_request)
            else:
                StockScanRequest.model_validate(self.resolved_request)
        except Exception as exc:
            raise ValueError(f"resolved_request does not match a valid request for mode={self.mode}: {exc}")
        return self
```

Because `resolved_request` is validated against the *real* `ScanRequest`/
`StockScanRequest` schemas at save time, a stocks-mode entry pushed without a
`strategy` field is rejected immediately by Pydantic (that field is required
on `StockScanRequest`) — not discovered as a silent failure the first time
the entry fires unattended.

**Note: this schema deliberately carries no runtime state** (no
`last_run_at`/`last_status`/`last_result`) — audit round 2's version of this
section added such fields directly here, and audit round 3 caught that
mixing frequently-mutated runtime data into what 3.2 defines as an
infrequently-written YAML config store means every scan completion — for a
`loop`-pattern entry, potentially every 5 minutes (`cadence_minutes`'s
schema floor) — would trigger a full in-memory-dict-rewrite-and-`os.replace`
of every entry's config, contradicting 3.2's own stated rationale for using
that storage shape at all. Runtime state lives in the new table introduced
in 3.5 instead, keyed by `schedule_entry_id`, entirely separate from this
config record.

This is deliberately its own schema, not an extension of the existing
`ScheduleConfig` (`backend/app/schemas/schedule.py`) — `ScheduleConfig` is a
single-object settings blob (`enabled`/`cadence_minutes`/window), structurally
wrong for "a list of independent, individually-toggled entries." The two
schemas can still share the multi-window work already flagged as pending
(Part 1, Step 5) at the *validation-logic* level (window containment check),
without sharing the *storage* shape — confirm this split during implementation
rather than forcing one schema to do both jobs.

### 3.2 Storage

New file `backend/app/services/scan_schedule_store.py`. Audit round 1 flagged
that "follows the pattern of `tuning_schedule_store.py`" was under-specified
for a *list*: that file's actual safety property is holding the whole
dataset in memory as canonical state under a lock, mutating it there, then
persisting — not just "atomic tmp-file writes." Spelled out explicitly here
so an implementer doesn't reload-from-disk per call (which would reintroduce
a lost-update race between concurrent requests):

```python
_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "scan_schedule.yaml"

class ScanScheduleStore:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}   # id -> entry, the in-memory canonical state
        if self._path.exists():
            self._load()   # populates self._entries; malformed rows are dropped, not fatal

    def list(self) -> list[dict]:
        with self._lock:
            return list(self._entries.values())

    def get(self, entry_id: str) -> dict | None:
        with self._lock:
            return self._entries.get(entry_id)

    def upsert(self, entry: dict) -> None:   # create or full-replace by id, then persist
        with self._lock:
            self._entries[entry["id"]] = entry
            self._save()   # same tmp-file-then-os.replace pattern as tuning_schedule_store.py

    def delete(self, entry_id: str) -> None:
        with self._lock:
            self._entries.pop(entry_id, None)
            self._save()
```

No new DB table — this is config-shaped data (small, infrequently written,
already-established YAML-store convention across every other scheduler in
this codebase), not transactional application data.

### 3.3 Endpoints

New router `backend/app/routers/scan_schedule.py`:

- `GET  /api/scan-schedule` → `list[ScanScheduleEntry]`
- `POST /api/scan-schedule` → create, body = `ScanScheduleEntry` minus `id`
  (server generates)
- `PUT  /api/scan-schedule/{entry_id}` → full replace (this is also the
  re-sync path used automatically when a referenced profile is saved, see 3.4)
- `DELETE /api/scan-schedule/{entry_id}`
- `POST /api/scan-schedule/{entry_id}/run-now` → bypass the schedule, execute
  immediately (mirrors the existing `run_now()` pattern on
  `strategy_watch_scheduler.py`) — useful for testing a newly-created entry
  without waiting for its fire time.

Each write (`POST`/`PUT`/`DELETE`) calls into 3.5's runner to re-sync the live
job set — same "reconfigure immediately on save" pattern already used by
`ingestion_scheduler.configure()` etc.

### 3.4 Frontend re-sync on profile save

In `frontend/lib/searchProfilesStore.ts`, `saveProfile`/`updateProfile` need
one addition: after a successful save, look up whether any local knowledge of
schedule entries (fetched via `GET /api/scan-schedule` and cached, or looked
up fresh) references the saved `profile_id`, and if so, re-resolve that
profile into a fresh request body (3.1's client-side resolution, same code
path as the manual Run Scan button) and `PUT` each such entry's
`resolved_request` with it. This is the entire mechanism behind "a schedule
always reflects the profile's last explicit save" — the backend never reads
`localStorage`, it just receives pushes, including this automatic one
triggered by the save action itself.

**Push-failure handling — flagged by audit round 3 as unaddressed.** This
whole guarantee depends on that `PUT` actually landing; a network blip or a
backend restart mid-save leaves an entry silently running a stale
`resolved_request` indefinitely — precisely the drift class this feature
exists to eliminate elsewhere. Retry the push a small, bounded number of
times (e.g. 3 attempts with brief backoff); if all fail, surface a visible
warning in the UI (a toast, or a per-entry "may be out of date" badge sourced
from comparing the profile's `updatedAt` against a `profile_synced_at`
timestamp Part 3's schema should also carry) rather than failing silently.
Exact UX is an implementation-time call; the requirement is that a failed
re-sync must be visible somewhere, not swallowed.

### 3.5 Execution core — factored out so scheduled runs can never touch manual-run state

Audit round 1's most severe finding: calling `run_scan()`/`run_stock_scan()`
directly from a scheduled entry would have broken "manual runs never affect
the schedule" in the *other* direction too — those functions unconditionally
mutate `_last_request`/`_last_result` (`routers/scan.py` line 1358) and
`stock_scan.py`'s equivalent globals, and `run_scan()` fires the armed
auto-trader on any PASS candidate. **Audit round 2 then read the actual
~275-line `run_scan()` body (lines 1101-1375) and the actual `stock_scan.py`
structure (its own existing `_run_stock_scan_body()` at line 999, which
itself ends by calling `_upsert_stock_session()` — a function that mutates
all four `_last_stock_*` globals internally) and found round 1's fix, as
sketched, doesn't hold either**: simply "remove the assignment lines" leaves
`run_scan()`'s delta computation (`_compute_deltas(..., _last_result)`,
lines 1338-1349) still *reading* the global — so a scheduled entry's
rank/score deltas would silently compute against whatever the UI (or an
unrelated entry) last produced, not its own history — and never addresses
`_upsert_session()`'s independent `_last_status`/`_last_updated_at`
mutation and its write to the `ScanSession(id="current")` DB row (a
**second** single-slot store the original sketch didn't mention at all).
For `stock_scan.py`, "same split" doesn't even apply mechanically — the
state mutation there lives one level deeper, inside a function the plan
would otherwise reuse unmodified.

**Real fix — each schedule entry gets its own persisted state (its own
"last result," "last status," delta baseline), entirely separate from the
UI's single-slot `_last_request`/`_last_result`/`_last_status`/
`ScanSession(id="current")`, from every other entry's state, and — per audit
round 3 — kept out of `ScanScheduleEntry`'s YAML config record entirely (see
3.1's note added above).**

**Correction (audit round 3): there is no existing scan-history persistence
to "reuse" here — this was checked and it doesn't exist.** `ScanHistoryEntry`
(`backend/app/schemas/scan.py`) is only ever instantiated as an in-memory
Python list on the `ScanScheduler` object (`scan_scheduler.py`'s `_history`
attribute) — never written to a database — and that object is either deleted
or left permanently uninstantiated once 3.9's retirement lands. The only
persisted options/stocks scan state anywhere in the backend is the
single-row `scan_sessions` table (`models/scan_session.py`, hardcoded
`id="current"`, one row total) and its stocks-mode equivalent. Neither is
addressable by scan id, and there's nothing to add a `schedule_entry_id`
column to.

**Real fix: a genuinely new, small DB table**, `ScheduledScanRunModel`
(`backend/app/models/scheduled_scan_run.py`, new Alembic migration):

```python
class ScheduledScanRunModel(Base):
    __tablename__ = "scheduled_scan_runs"
    id                = Column(String, primary_key=True)          # uuid
    schedule_entry_id = Column(String, index=True, nullable=False)  # ScanScheduleEntry.id
    mode              = Column(String, nullable=False)             # 'options' | 'stocks'
    fired_at          = Column(DateTime(timezone=True), nullable=False)
    status            = Column(String, nullable=False)             # 'success' | 'error'
    error             = Column(Text, nullable=True)                # populated only on status == 'error'
    result_json       = Column(Text, nullable=True)                # full ScanResult/StockScanResult JSON, null on error
```

This is where all of a scheduled entry's runtime state actually lives — not
on `ScanScheduleEntry`, resolving both round 3 findings at once:

- `_run_scheduled_entry` writes one row here per completion (success or
  error) instead of calling `scan_schedule_store.upsert()` — `ScanScheduleEntry`
  itself is now only ever written on explicit create/edit/delete, restoring
  3.2's "infrequently written" property.
- Delta baseline lookup: `SELECT * FROM scheduled_scan_runs WHERE
  schedule_entry_id = :id AND status = 'success' ORDER BY fired_at DESC LIMIT 1`,
  deserialize `result_json` back into a `ScanResult`/`StockScanResult`, pass
  as `previous_result` — correctly isolated per entry, a real, queryable
  history instead of an assumed one.
- New endpoint `GET /api/scan-schedule/{entry_id}/runs` (paginated, most
  recent first) serves both the delta-baseline lookup internally and 3.8's
  UI display of last-run status/error (see 3.8's update below) — one store,
  two consumers, not a duplicated mechanism.
- A retention/pruning story for this table follows the same pattern as
  everything else in Part 2 — e.g. `prune_old_history`-style age-based
  deletion, reusing `history_retention_years` — worth adding to the nightly
  batch alongside Part 2's audit-log maintenance rather than left unbounded;
  flagged here, not fully speced, since it's a smaller, lower-risk addendum
  than the core design.

```python
# routers/scan.py
async def _execute_scan_core(
    req: ScanRequest, db: AsyncSession, *, previous_result: ScanResult | None,
) -> ScanResult:
    """The actual scan-running logic — the same body run_scan() has today,
    with the delta computation taking previous_result as a parameter instead
    of silently reading the module-global _last_result, and with no writes
    to _last_request/_last_result/_last_status/ScanSession(id="current") and
    no auto-trade firing. Both the manual handler and Part 3's runner call
    this; only the manual handler additionally updates the UI-facing globals,
    persists to ScanSession(id="current"), and checks the auto-trader."""
    ...
    deltas = _compute_deltas(candidate_result, previous_result)
    result = ScanResult(..., previous_run_id=previous_result.scan_id if previous_result else None, deltas=deltas, ...)
    return result

async def run_scan(req: ScanRequest, db: AsyncSession) -> ScanResult:
    """Manual-trigger entry point — unchanged external behavior for the UI."""
    async with _state_lock:
        previous = _last_result
    result = await _execute_scan_core(req, db, previous_result=previous)
    async with _state_lock:
        _last_request, _last_result = req, result
    if any(c.finalStatus == 'PASS' for c in result.candidates):
        # ... existing auto-trader block, unchanged, manual-trigger-only ...
    await _upsert_session(db, req=req, result=result, status="complete")
    return result
```

`_run_scheduled_entry` (3.6) calls `_execute_scan_core` the same way, but
passes `previous_result` loaded from `ScheduledScanRunModel`'s most recent
successful row for *that entry's own* `schedule_entry_id` (not `_last_result`,
not another entry's rows) — so deltas are always computed against the
entry's own prior run, correctly isolated per entry, never against the UI's
state or another entry's.

For `stock_scan.py`: the reusable core is **not** `_run_stock_scan_body()`
as-is (it ends by calling the global-mutating `_upsert_stock_session()`).
Split it the same way: extract everything through result construction into
a core that takes `previous_result` as a parameter and returns `StockScanResult`
with no global writes; `run_stock_scan()` keeps calling
`_upsert_stock_session()` afterward exactly as today. The existing
revert-on-exception snapshot dance around `_prev_request`/`_prev_result`/
`_prev_status` (lines 983-996) exists specifically to protect the shared
global slot on a mid-request failure — since the scheduled path never
touches that slot at all, this dance simply doesn't apply there; no
equivalent is needed in `_run_scheduled_entry`.

**Whether a scheduled run should ever be allowed to fire the auto-trader is
an explicit, separate decision this plan does not make on your behalf**:
default is **no** — `_execute_scan_core` never calls `_auto_trader`, full
stop, for either mode. An unattended background job placing trades is a
large enough change in risk posture that it deserves its own conversation if
you want it later; it is out of scope here.

**Concurrency — flagged by audit round 3, unaddressed in every prior version
of this section.** The codebase's own comment (`routers/scan.py` lines
262-267) already documents that a manual scan and today's single continuous
scan scheduler "can run fully concurrently — nothing serializes them," with
only a narrow, Heston-calibration-specific semaphore as a safety net (not
candle/quote fetching, DB pool usage, or data-provider rate limits). Part 3
multiplies the number of independent firing sources — N `fixed_time` jobs
plus one shared `loop` runner iterating any number of entries — so two
entries landing in the same minute (or an entry firing while another is
still mid-run) is a real, not hypothetical, scenario once several entries
exist. **Fix**: one process-wide `asyncio.Semaphore`, scoped to Part 3's
scheduled executions only (not manual runs — those stay interactive and
unblocked, as today):

```python
_SCHEDULED_SCAN_SEMAPHORE = asyncio.Semaphore(1)  # serializes scheduled runs only
```

`_run_scheduled_entry` acquires this before calling `_execute_scan_core`/its
stocks-side equivalent and releases it after. A second entry firing while
one is already running simply waits its turn instead of racing it for the
candle cache, DB connections, or broker/data-provider rate limits — an
acceptable tradeoff for unattended background work with no latency
requirement. Starting at `1` (fully serial) is the safe default; widening it
later is a one-line change once real usage shows it's needed, not a
day-one requirement.

**Observability — flagged by audit round 2 as missing entirely from round 1's
version of this section; storage design corrected by round 3 (see the
`ScheduledScanRunModel` table above).** A feature whose entire point is
"find candidates while I'm not watching" cannot silently discard what
happened:

- `_run_scheduled_entry(entry_id)` opens its own DB session
  (`async with AsyncSessionLocal() as db:`, mirroring the pattern the
  *existing* `_scheduled_scan()` wrapper already uses at `routers/scan.py`
  line 1386 — APScheduler's job callback has no `Depends(get_db)` request
  context to draw one from).
- Acquires `_SCHEDULED_SCAN_SEMAPHORE`, wraps the `_execute_scan_core` call
  in `try/except`. `_execute_scan_core`'s body can raise
  `fastapi.HTTPException` today (validation failures inside what is
  currently `run_scan()`) — a type that only makes sense inside a
  request/response cycle. In the scheduled path, catch it (and any other
  exception) at this boundary and write one `ScheduledScanRunModel` row with
  `status='error'`/`error=str(exc)`, log at `error` level, and send one
  notification via the existing `notifications/dispatch.py::notify_enabled_channels(subject, plain_body, html_body)`
  — note its real three-argument signature, and that
  `strategy_watch_evaluator.py`'s existing notification code carries real
  HTML-escaping logic for Telegram's restrictive tag allowlist (with a
  comment there explaining a prior silent-failure bug from getting this
  wrong) — **reuse that same escaping helper**, don't reimplement it — "scan
  entry '<label>' failed: <error>" — rather than a job that fails silently
  forever.
- On success: write one `ScheduledScanRunModel` row with
  `status='success'`/`result_json=<serialized result>`, and send one summary
  notification via the same dispatch layer — "scan entry '<label>': N
  candidates found" (mirroring the shape and escaping of
  `strategy_watch_evaluator`'s existing notification, not inventing a new
  format).

**Deleted-entry-mid-flight**: `_run_scheduled_entry(entry_id)` starts with
`entry = scan_schedule_store.get(entry_id)`; if `None` (entry deleted between
the trigger firing and the handler running), log at `info` level and return —
never let a missing entry raise into APScheduler's job-execution machinery,
which would otherwise log a scary traceback for an entirely expected race.

**The options-mode client-side resolver (3.1/3.4) is real refactoring work,
not a lookup — flagged by audit round 2, understated in the original plan.**
Read `frontend/components/organisms/RunScanButton/index.tsx` in full: the
**stocks**-mode path (`stockScan.ts`'s `runStockScan`) is already a
standalone function, genuinely reusable as originally claimed. The
**options**-mode request-building logic (~85 lines: universe/direction/
horizon/filters/overrides/ATR pairs/fundamentals gate) lives inline inside
`RunScanButton`'s `onClick` `useCallback`, interleaved with React-hook-subscribed
store values, toast side effects, and a regime-REJECT confirmation dialog —
none of which can be called from `searchProfilesStore`'s non-component
save-hook (3.4). This needs an actual extraction: pull the pure
request-building logic out of that closure into a standalone function in
`frontend/lib/` (e.g. `resolveOptionsScanRequest(snapshot, context): ScanRequest`),
parameterized on the values it currently reads from hooks, used by both the
now-thinner `onClick` handler and the profile-save resolver. Scope this as
its own implementation step, not folded silently into "read the function
names during implementation."

### 3.6 Scheduler — `fixed_time` pattern

Reuse the `AsyncIOScheduler(timezone=operator_zone())` instance-per-scheduler
convention from Part 1 rather than inventing a new mechanism. One shared
scheduler instance for scan-schedule entries; each enabled `pattern='fixed_time'`
entry becomes one `CronTrigger`-backed job, id = the entry's `id`:

```python
def _sync_fixed_time_jobs() -> None:
    sched = _get_scan_schedule_scheduler()  # AsyncIOScheduler(timezone=operator_zone()), same rebuild-on-tz-change as Part 1 Step 2
    for job in sched.get_jobs():
        sched.remove_job(job.id)
    for entry in scan_schedule_store.list():
        if entry["enabled"] and entry["pattern"] == "fixed_time":
            hour, minute = map(int, entry["fire_time"].split(":"))
            sched.add_job(
                _run_scheduled_entry, CronTrigger(hour=hour, minute=minute,
                    day_of_week=",".join(map(str, entry["days_of_week"]))),
                args=[entry["id"]], id=entry["id"], replace_existing=True,
            )
```

`_run_scheduled_entry(entry_id)` loads the entry (see 3.5's deleted-entry
handling), validates it's still enabled, then dispatches on `mode`:

- `mode == 'options'` → `ScanRequest.model_validate(entry["resolved_request"])`,
  call `_execute_scan_core(req, db)` (3.5) directly — never `run_scan()`,
  never touching `_last_request`.
- `mode == 'stocks'` → `StockScanRequest.model_validate(entry["resolved_request"])`,
  call the equivalent stocks-side core helper directly — **this is the new
  stocks-mode scheduled execution path that doesn't exist today.**

Because `resolved_request` was already validated as a well-formed
`ScanRequest`/`StockScanRequest` at save time (3.1), this dispatch has no
field-mapping logic left to get wrong at fire time — the hard part happened
once, client-side, at save time, using the same code the manual button uses.

### 3.7 Scheduler — `loop` pattern

**Architecture, resolved (audit round 2 caught the original wording
contradicting itself between here and 3.9 — this section and one shared
runtime object, not per-entry `ScanScheduler` instances, and not "the same
class instance," is the actual design):**

`ScanScheduler._should_run_now()` (`scan_scheduler.py` lines 45-53) is a pure
function of `(cfg, now)` — it reads `self._cfg`'s window/day fields and
`datetime.now(tz)`, no other state. Extract it into a standalone function,
e.g. `services/scan_window.py::window_is_open(window_start_hour,
window_end_hour, days_of_week, timezone_name, now=None) -> bool`, and have
**both** `ScanScheduler` (unchanged class, still backs 3.9's note that the
engine survives) and the new `ScanScheduleLoopRunner` call it — shared
*logic*, not a shared *instance*, resolving the contradiction: `ScanScheduler`
the class stays defined and importable, but after 3.9, nothing instantiates
it any more (its sole caller, `_scheduler` in `routers/scan.py`, is deleted)
— so it becomes dead code unless something new uses it. If you want to avoid
carrying unused code, delete the `ScanScheduler` class itself once
`window_is_open()` is extracted from it and `ScanScheduleLoopRunner` is the
only remaining scheduling engine; keep it only if you expect to reintroduce
a single-global-window scheduler later. Default: delete it — extraction, not
reuse, per the audit's finding.

`ScanScheduleLoopRunner` is **one** background task (not N), modeled on
`ScanScheduler._loop()`'s tick structure: ticks every 60s, and for each
enabled `pattern='loop'` entry independently tracks its own
`last_run_at`/`next_run_at` (kept in an in-memory `dict[entry_id, ...]` inside
the runner, not persisted — a missed loop-tick on restart just means the
entry's cadence timer resets, which is an acceptable, low-stakes edge case
for a repeating scan) and calls `window_is_open(...)` with that entry's own
`window_start_hour`/`window_end_hour`/`days_of_week`.

**Per-entry fault isolation, required and previously unspecified**: because
this is one shared task iterating a list — a materially larger blast radius
than `ScanScheduler`'s one-task-per-config design it's modeled on — each
entry's fire attempt inside the tick **must** be wrapped in its own
`try/except`, logged and reported via 3.5's error-notification path, so one
misbehaving `loop`-pattern entry can never prevent any other entry (or the
next tick) from running. This mirrors `strategy_watch_scheduler._loop()`'s
existing `try/except Exception: logger.error(..., exc_info=True)` around its
own per-tick body — same pattern, applied per-entry instead of per-tick.

On fire, calls the same `_run_scheduled_entry(entry_id)` dispatch as the
`fixed_time` path (3.6) — both patterns converge on identical execution
(3.5's core helpers), they only differ in *when* they decide to fire.
`ScanScheduleLoopRunner`'s own start/stop lifecycle follows the existing
`portfolio_alert_monitor`/`regime_monitor` convention: one `asyncio.create_task`
kept alive via a strong module-level reference from `main.py`'s startup hook,
alongside those two — no add/remove-per-entry lifecycle is needed for the
task itself, only for what it iterates (`scan_schedule_store.list()`, read
fresh each tick).

### 3.8 Frontend — Settings UI

New section under Settings → Scan (alongside the existing continuous-scan
controls, until those are retired per 3.9): a flat list of schedule entries.
Each row: mode badge (options/stocks), label (editable text, defaults to
profile name), profile picker (populated from `useSearchProfilesStore`,
filtered to the row's mode), pattern toggle (`fixed_time`/`loop`),
pattern-specific fields (time + days-of-week picker for `fixed_time`; cadence
+ window-hour + days-of-week pickers for `loop`), enabled toggle, delete
button, "Run now" button (calls 3.3's `run-now` endpoint). An "Add entry"
button appends a new row defaulting to `pattern='fixed_time'`.

**Last-run status display — added per audit round 3.** 3.5 builds real
observability (`ScheduledScanRunModel` rows, Gmail/Telegram notifications on
every completion) specifically because a scheduled scan runs unattended —
but round 3 caught that nothing in the UI actually surfaced it, leaving a
user with notifications off (or who just doesn't check email) with no
in-app way to see a failing entry. Each row also shows: last-run timestamp
and status (success/error, with the error message on hover/expand if
`status='error'`) and a link/count to that entry's candidate results if
successful — sourced from `GET /api/scan-schedule/{entry_id}/runs?limit=1`
(3.5), fetched alongside the entry list rather than requiring a separate
per-row round-trip if that's a meaningful latency concern at implementation
time (e.g. have `GET /api/scan-schedule` embed each entry's latest run
summary directly in its response).

### 3.9 Retiring the old continuous-scan mechanism

Per the resolved decision at the top of Part 3: the pre-existing
`_scheduled_scan()`/`_last_request`-replay/`ScheduleConfig` continuous-scan
toggle in `routers/scan.py` (`start_continuous_scan`/`stop_continuous_scan`,
the `_scheduler` instance bound to it) is retired once Part 3 ships, rather
than kept as a parallel mechanism — two different ways to schedule an
options scan, one keyed off "whatever ran last" and one off an explicit
profile, would be confusing and the exact drift problem this plan exists to
fix. `ScheduleConfig`/`window_is_open()` as *logic* survives (3.7); only the
single-global-slot *binding* of the old mechanism goes away — see 3.7 for
whether the `ScanScheduler` class itself is deleted or kept unused.

**Audit round 2 caught that this section's original one-line removal
instruction, taken literally, breaks backend startup entirely** — every real
call site must be found and updated, not just the two endpoints:

- `backend/app/main.py` line 78: `from app.routers.scan import restore_from_db, _scheduler, _scheduled_scan`
  — a plain `ImportError` at process boot the moment `_scheduler`/`_scheduled_scan`
  no longer exist. Lines 82-95 use them to auto-resume continuous scan on
  startup if `restore_from_db()` reports `status == "running"`; the shutdown
  hook (~lines 229-230) calls `_scheduler.stop()`. **Both blocks must be
  deleted, not just left importing removed names.**
- `backend/app/routers/scan.py` line 1090 (inside `get_last_scan_status()`):
  `status = "running" if _scheduler.get_status().get("running") else _last_status`
  — rewrite to derive "running" from whether any enabled Part-3 entry exists
  for options mode (or drop the "running" concept from this endpoint
  entirely and let the frontend read schedule-entry state directly via
  `GET /api/scan-schedule` instead — confirm which during implementation,
  but the current line cannot survive unmodified).
- **Audit round 3 found a fourth call site round 2 missed**:
  `backend/app/routers/risk_settings.py` line 189, inside
  `PUT /api/settings/schedule`: `scan_router._scheduler.configure(cfg)`,
  wrapped in a broad `except Exception`. Deleting `_scheduler` wouldn't crash
  the process here (the exception is swallowed) — worse, it would make this
  endpoint silently become a no-op that rewrites `settings.yaml` and returns
  `200 OK` while doing nothing, with the failure buried in a warning log.
  This endpoint needs a real answer for what it does once `ScanScheduler` is
  gone — either remove it too (if nothing meaningful reads `ScheduleConfig`
  post-3.9) or repoint it at whatever does — not left as dead code with a
  swallowed exception. Resolve which before implementation; don't leave this
  as a silent no-op.

**Migration story — also missing from the original section, per audit round
2's question about a user with continuous scan already enabled today; the
data source corrected by round 3**: on first boot after this ships, if
`restore_from_db()` reports the old continuous-scan session was
`status == "running"` (i.e. exactly the case the now-deleted startup-resume
code existed to handle), run a one-time migration instead of silently
dropping it: read `ScheduleConfig` from `settings.yaml`'s `scan.schedule`
block (**not** from the `ScanSession` DB row — that row only ever holds
`status`/`last_result_json`/`last_request_json`, per `models/scan_session.py`;
`ScheduleConfig` is never stored there, corrected wording per round 3) the
same way `main.py`'s existing auto-resume code already reads it, and the
last-known `_last_request` from the session row's `last_request_json`. **If
`last_request_json` is null or unparseable** (e.g. a crash between
`_scheduler.start()` and the first completed scan — `restore_from_db()`,
`routers/scan.py` lines 1051-1072, only sets `_last_request` if that column
is truthy) — **skip the migration and just mark the session `stopped`**;
there's no request to build a `ScanScheduleEntry` from, and
`resolved_request` is a required, Pydantic-validated field (3.1), so this
case cannot silently produce an empty/invalid entry. (A single `ScanSession`
row is hardcoded to `id="current"` — there is only ever one candidate
session, so "multiple candidate sessions" is not a case this needs to
handle.) Otherwise create one `pattern='loop'` `ScanScheduleEntry`
(`mode='options'`, `resolved_request` = that last request, cadence/window
from `ScheduleConfig`, label e.g. "Migrated from continuous scan") via
`scan_schedule_store.upsert(...)` directly at startup, then mark the old
session `stopped` either way so this migration only ever runs once. This is
a small, one-shot piece of startup code in `main.py`'s lifespan hook, not a
full migration framework — scope it as such.

### 3.10 Tests

- Backend: `ScanScheduleEntry` validation — missing pattern-specific fields
  rejected, `window_start_hour >= window_end_hour` rejected, a `resolved_request`
  that doesn't validate against `ScanRequest`/`StockScanRequest` for the
  entry's `mode` rejected (e.g. a stocks-mode entry missing `strategy`).
- `_run_scheduled_entry` dispatches to `_execute_scan_core` for `mode='options'`
  and its stocks-side equivalent for `mode='stocks'` — and, critically, that
  neither call mutates `_last_request`/`_last_result`/`_last_stock_request`/
  `_last_stock_result` or invokes `_auto_trader.maybe_fire_on_scan` (this is
  the regression test for audit round 1's top finding — assert those globals
  are unchanged after a scheduled run, and that manual `run_scan()` behavior
  is unchanged by the refactor).
- `_run_scheduled_entry` on a deleted entry id: logs and returns, doesn't raise.
- `fixed_time` pattern: `_sync_fixed_time_jobs()` produces exactly one
  `CronTrigger` job per enabled fixed_time-entry, none for disabled or
  loop-pattern entries; removing an entry removes its job; the job actually
  repeats on matching weekdays (not a true one-shot) — test that the naming
  reflects the behavior, not the reverse.
- `loop` pattern: `ScanScheduleLoopRunner` fires an entry only within its own
  window/cadence, independent of any other entry's state (two loop-entries
  with different windows don't interfere with each other).
- `ScanScheduleStore`: concurrent `upsert()` calls from different entries
  don't lose either write (in-memory-canonical-state-under-lock, not
  reload-per-call); `upsert()`/`delete()` are called only on explicit
  create/edit/delete, never on scan completion (regression test for audit
  round 3's YAML-rewrite-frequency finding).
- `ScheduledScanRunModel`: a completed scheduled run writes exactly one row;
  the delta-baseline lookup for a given `schedule_entry_id` returns the most
  recent `status='success'` row and correctly ignores rows from other
  entries and `status='error'` rows.
- `_SCHEDULED_SCAN_SEMAPHORE`: two entries "fired" concurrently in a test
  (both `_run_scheduled_entry` calls started without awaiting the first)
  execute serially, not overlapping — regression test for audit round 3's
  concurrency finding. Manual `run_scan()` is unaffected by the semaphore
  (doesn't acquire it).
- Migration (3.9): a `ScanSession` with `status="running"` and a valid
  `last_request_json` produces exactly one migrated `loop`-pattern entry and
  marks the session stopped; the same with `last_request_json` null skips
  entry creation but still marks the session stopped; running the migration
  logic twice (simulating a second boot) doesn't create a duplicate entry.
- Frontend: saving/updating a profile that a schedule entry references issues
  the expected `PUT /api/scan-schedule/{id}` re-sync call with a freshly
  re-resolved request body and updates `profile_synced_at`; saving a profile
  with *no* referencing entries issues no such call; a re-sync push that
  fails after retries surfaces the stale/failed indicator rather than
  failing silently.

---

## Open items carried over from this thread, not yet decided

- Multi-window scan scheduling (Part 1, Step 5) — a pre-market + post-close
  pair for the manual/UI-driven side of scanning. Note this is now decoupled
  from Part 3: per 3.7's resolved architecture, `loop`-pattern entries carry
  their *own* `window_start_hour`/`window_end_hour` fields directly on
  `ScanScheduleEntry` (3.1), not a shared `ScheduleConfig` window — so Part 3
  already supports "one entry per window" (e.g. two separate `loop` entries,
  one pre-market, one post-close) without needing this schema change at all.
  Step 5 only still matters if you also want multi-window behavior on
  whatever, if anything, remains of the plain `ScheduleConfig`/`window_is_open()`
  path once 3.9's retirement lands — confirm whether that's still wanted
  before scoping this in.
- Frontend timezone/window controls for `ScheduleConfig`'s pre-existing
  `timezone_name`/`window_start_hour`/`window_end_hour` fields (Part 1, Step 4)
  — still worth shipping for whatever surface continues to read
  `ScheduleConfig` after 3.9 (confirm during implementation whether anything
  still does, per 3.7's note that `ScanScheduler` the class may be deleted
  outright rather than kept idle).
- The exact call graph from "options Run Scan button click" to "request body
  sent to the backend" inside `RunScanButton/index.tsx` needs to be read in
  full and mapped field-by-field during implementation before extracting
  3.5's `resolveOptionsScanRequest` — this plan identified *that* the
  extraction is necessary and roughly what it needs to produce (a `ScanRequest`),
  not the line-by-line extraction itself.
