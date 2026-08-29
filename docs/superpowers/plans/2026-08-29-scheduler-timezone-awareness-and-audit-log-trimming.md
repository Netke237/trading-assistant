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

**Step 2a — Give `tuning_scheduler.py` a real day-of-week dimension, required by Part 0's "Saturday 03:00 only" default.**

Checked: `tuning_schedule_store.py`'s schema is `{enabled, time}` only, and
`strategy_tuning.py`'s `PUT` handler calls
`tuning_scheduler.configure(body.enabled, body.time)` with no day concept
anywhere in the chain. Part 0's "Saturday-only" default is not buildable
without this — add it explicitly, scoped to `tuning_scheduler.py` only (the
other three nightly jobs run every day, per Part 0, and don't need this):

- `tuning_schedule_store.py`: extend `_DEFAULTS` to
  `{"enabled": False, "time": "03:00", "days_of_week": [5]}` (5 = Saturday,
  matching Python's `datetime.weekday()`/APScheduler's own 0=Mon convention —
  confirm APScheduler's `CronTrigger(day_of_week=...)` accepts either int or
  the `"sat"`-style string form during implementation and pick whichever the
  rest of this codebase's cron usage already favors, for consistency).
- `strategy_tuning.py`'s schedule request/response model and `PUT` handler:
  add `days_of_week: list[int]` alongside `enabled`/`time`.
- `tuning_scheduler.configure(enabled, time_str, days_of_week)`: pass
  `CronTrigger(hour=hour, minute=minute, day_of_week=",".join(map(str, days_of_week)))`
  instead of the current `CronTrigger(hour=hour, minute=minute)`.
- Frontend Settings UI (the same `DataForm`-style component used for
  ingestion/EDGAR/S&P 500 in `frontend/app/(frame)/settings/page.tsx`): add a
  day-of-week picker to tuning's schedule form specifically — the other three
  forms don't need one since they stay daily.

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
    from app.services.audit import rotate_audit_log, prune_audit_log_archives
    cfg = _load_settings()  # existing helper pattern from portfolio_alert_monitor.py
    retention_years = int(cfg.get('history_retention_years', 10))
    rotate_audit_log()
    prune_audit_log_archives(retention_years)
```

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
| OHLCV ingestion | **02:00, every night** | NYSE close (16:00 ET) ≈ 22:00 Berlin; 02:00 gives ~4h buffer for EOD data to finalize. Needs daily freshness. |
| EDGAR fundamentals | **03:00, every night** | After ingestion, same overnight block; no same-day urgency but no reason to separate. |
| S&P 500 liquidity update | **04:00, every night** — moved off the shipped `16:30` | `16:30` only made sense under "server-local = US Eastern." Anchored to Berlin, `16:30` lands mid-US-session (10:30 ET) — wrong. Moved into the same overnight block. |
| Strategy tuning (WFO) | **Saturday 03:00 only, not nightly** | Compute-heavy, doesn't need daily freshness (verified: no EDGAR/fundamentals dependency, OHLCV-only via `historical_store.get_bars`'s self-heal). Weekly is the standard cadence; running after Friday's ingestion sees a full settled week. |
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
code path the manual "Run Scan" button already calls** (whatever function
`RunScanButton`/`stockScan.ts` currently uses to turn Step 2/3 UI state into
a `ScanRequest`/`StockScanRequest` body — confirm the precise function names
during implementation, but the principle is: one resolution path, used by
both the manual button and this feature, never a second Python
reimplementation of unit/horizon parsing). This also fixes the risk-fields
gap for free — the frontend has live access to `riskStore` when building the
request the same way the manual path already does, so `account_size`/
`risk_pct`/`risk_fixed_usd` are populated from the user's real current risk
settings, not defaults.

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

### 3.5 Execution core — factored out so scheduled runs can never touch manual-run state

Audit round 1's most severe finding: calling `run_scan()`/`run_stock_scan()`
directly from a scheduled entry would have broken "manual runs never affect
the schedule" in the *other* direction too — those functions unconditionally
mutate `_last_request`/`_last_result` (`routers/scan.py` line 1358) and
`stock_scan.py`'s equivalent globals, and `run_scan()` fires the armed
auto-trader on any PASS candidate. An unattended nightly scan firing a live
or paper trade with zero mention of that anywhere in this plan is not
acceptable to ship silently.

**Fix — factor the actual scan-execution logic out of both routers into a
core helper that never touches the single-slot globals or the auto-trader:**

```python
# routers/scan.py
async def _execute_scan_core(req: ScanRequest, db: AsyncSession) -> ScanResult:
    """The actual scan-running logic, with no side effects on _last_request/
    _last_result and no auto-trade firing. Both the manual POST /scan handler
    and Part 3's scheduled-entry runner call this; only the manual handler
    additionally updates _last_request/_last_result and checks the auto-trader."""
    # ... existing body of what is today run_scan(), minus the
    # `_last_request = req` / `_last_result = result` assignments and the
    # auto-trader block ...
    return result

async def run_scan(req: ScanRequest, db: AsyncSession) -> ScanResult:
    """Manual-trigger entry point — unchanged behavior for the UI."""
    result = await _execute_scan_core(req, db)
    async with _state_lock:
        _last_request, _last_result = req, result
    if any(c.finalStatus == 'PASS' for c in result.candidates):
        # ... existing auto-trader block, unchanged, manual-trigger-only ...
    await _upsert_session(db, req=req, result=result, status="complete")
    return result
```

Same split for `run_stock_scan()`/`_last_stock_request`/`_last_stock_result`
in `stock_scan.py`. This is a refactor of existing functions, not new
behavior for the manual path — `run_scan()`'s external behavior (what the UI
sees) is unchanged; only where the side-effecting lines live moves.

**Whether a scheduled run should ever be allowed to fire the auto-trader is
an explicit, separate decision this plan does not make on your behalf**:
default is **no** — `_execute_scan_core` never calls `_auto_trader`, full
stop, for either mode. An unattended background job placing trades is a
large enough change in risk posture that it deserves its own conversation if
you want it later; it is out of scope here.

**Deleted-entry-mid-flight**: `_run_scheduled_entry(entry_id)` starts with
`entry = scan_schedule_store.get(entry_id)`; if `None` (entry deleted between
the trigger firing and the handler running), log at `info` level and return —
never let a missing entry raise into APScheduler's job-execution machinery,
which would otherwise log a scary traceback for an entirely expected race.

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

A second, lightweight background task (`ScanScheduleLoopRunner`, modeled on
`ScanScheduler._loop()` but iterating multiple entries instead of one global
config): ticks every 60s, and for each enabled `pattern='loop'` entry
independently tracks its own `last_run_at`/`next_run_at` and checks its own
`window_start_hour`/`window_end_hour`/`days_of_week`/`cadence_minutes` — same
`_should_run_now()` logic as today's `ScanScheduler` (`scan_scheduler.py`
lines 45-53), just keyed per-entry instead of holding one global `_cfg`. On
fire, calls the same `_run_scheduled_entry(entry_id)` dispatch as the
`fixed_time` path (3.6) — both patterns converge on identical execution
(3.5's core helpers), they only differ in *when* they decide to fire.

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

### 3.9 Retiring the old continuous-scan mechanism

Per the resolved decision at the top of Part 3: the pre-existing
`_scheduled_scan()`/`_last_request`-replay/`ScheduleConfig` continuous-scan
toggle in `routers/scan.py` (`start_continuous_scan`/`stop_continuous_scan`,
the `ScanScheduler` class instance bound to it) is retired once Part 3 ships,
rather than kept as a parallel mechanism — two different ways to schedule an
options scan, one keyed off "whatever ran last" and one off an explicit
profile, would be confusing and the exact drift problem this plan exists to
fix. Concretely: remove the `POST/DELETE /api/scan/continuous` endpoints and
the `_scheduler`/`_scheduled_scan` globals from `routers/scan.py`, and the
corresponding frontend controls, once Part 3's `fixed_time`/`loop` entries
cover the same ground. `ScheduleConfig`/`ScanScheduler` as a *class* remains
in use — it's the same engine 3.7's `ScanScheduleLoopRunner` is modeled on —
only the single-global-slot *binding* of it (`_scheduled_scan`/
`_last_request`) goes away.

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
  reload-per-call).
- Frontend: saving/updating a profile that a schedule entry references issues
  the expected `PUT /api/scan-schedule/{id}` re-sync call with a freshly
  re-resolved request body; saving a profile with *no* referencing entries
  issues no such call.

---

## Open items carried over from this thread, not yet decided

- Multi-window scan scheduling for the *existing* `ScanScheduler`/`ScheduleConfig`
  engine (Part 1, Step 5) — still schema-shaped scope; Part 3's `loop` pattern
  reuses this same engine per-entry (3.7), so this work benefits both.
- Frontend timezone/window controls for `ScheduleConfig` (Part 1, Step 4) —
  still needed independent of Part 3's UI, since `ScheduleConfig`/`ScanScheduler`
  remains the engine behind Part 3's `loop` pattern even after the old
  single-slot *binding* of it is retired (3.9).
- The precise manual "Run Scan" resolution function names in the frontend
  (Step 2/3 UI state → `ScanRequest`/`StockScanRequest`) that 3.1/3.4's
  client-side resolution needs to reuse — confirmed such logic exists
  (`applySearchProfile` in `searchProfileSnapshot.ts` handles the
  profile-restoration half of this already) but the exact call graph from
  "Run Scan button click" to "request body sent to the backend" needs to be
  read during implementation, not assumed.
