# PORTFOLIO-ALERT-ACTION — plan (#672, umbrella #656)

Board item #672, branch `board/portfolio-alert-action-255a4b3c`. Scope points **1–3 only**.

> **Point 4 is out of scope.** Kenneth decided in chat on 2026-11-27 to park the
> optional automatic exit (paper or live) indefinitely. This phase builds no
> automatic exit and places, prepares or stages **no orders of any kind**. No
> ticket may add a broker call, an order payload or an "exit now" action. The
> "Close position…" button below only opens the existing manual
> `ClosePositionDrawer` (whose own optional send-to-broker path is unchanged and
> untouched). Point 4 waits for a later decision by Kenneth.

## Goal

Stop/target alerts already fire (evidence on #672: NFLX, BAC, FTNT, COP, HPE,
BMY fired daily for weeks while the positions were held to large losses). Make
them lead to action: show what needs action and for how long, replace repeated
4-hourly messages with first fire + one daily reminder + a daily summary, and
flag closed trades that reached their target but closed at a loss.

## Current behaviour (read from the code on 2026-11-27)

- Detection: backend `alert_generator.generate_alerts` (monitor tick, default
  60 s, and `GET /api/alerts`) and the browser engine `alertEngine.scanPortfolio`
  (portfolio cycle every 30 s, dashboard).
- Logging: `position_alert_log.log_position_alert` writes one
  `position_alert_history` row per `(rec_id, alert_type, source[, note])` per
  `reminderIntervalHours` window (default 4 h). Backend rows are written only
  while `masterEnabled` is on (the monitor returns before generation otherwise);
  frontend rows come from `POST /api/alerts/notify`, which the browser sends at
  most every `dedupWindowMinutes` (15 min) per condition and not at all for an
  acknowledged (suppressed) condition. Rows are pruned after
  `positionAlertRetentionDays` (default 30).
- Notifications: `alert_notifier.notify_alert` (both paths) sends the first fire,
  then a "(reminder)" every `reminderIntervalHours` while the condition stays
  true; `_first_seen` lives until the position closes (`forget_alerts`). There is
  no notion of a condition ending.
- In-app: `alertStore.addToast` keeps one row per condition key, refreshed in
  place; **acknowledge suppresses the key permanently** (until the row is
  deleted).
- Portfolio page: a frame-level stop-breach banner per position whose derived
  breach is the stop or the structural stop (PORTFOLIO-RISK-VIEW #682), with
  "Review <SYM>" and "Close position…" buttons, rendered above the tab strip.
- History tab: EXIT CHECK (stored stop at close, #664) and EXIT REASON columns.

## Definitions (one source each, mirrored where both sides need them)

**Alert key.** `(rec_id, alert_type)`. History rows carry no stop side; every
row in the log post-dates STOP-SEMANTICS (log starts 2026-10-18), so the short
`:short` notifier key is not split in history. The notifier keeps its own
`_dedup_key` (with `:short`) for state; it looks up history by
`(rec_id, alert_type)`.

**Episode.** For one key, the fires (all `position_alert_history` rows, any
source) sorted by `triggered_at`; an episode is a maximal run in which
consecutive fires are at most `EPISODE_GAP` = **72 h** apart. Rationale: rows
arrive every `reminderIntervalHours` (default 4 h, max 168 in the UI) while the
condition is true and the backend runs; 72 h tolerates a backend that is off over
a weekend without splitting an episode. A condition that clears for longer than
72 h starts a new episode; one that clears for less stays in the same episode
(documented trade-off). Effective gap = `max(72 h, 2 × reminderIntervalHours)`
so a user with a long reminder window does not get a new episode on every row.
- **Episode start** = first fire of the episode; **last fire** = latest.
- **Current episode** = the key's latest episode if `now − last fire ≤ gap`.
- **Start truncated** = `episode start − gap ≤ now − positionAlertRetentionDays`
  (an earlier fire could have been pruned without breaking the run). Shown as
  "30+ days" style text, never as an exact count.
- Timestamps: SQLite returns naive datetimes for `DateTime(timezone=True)`;
  every reader treats a naive value as UTC.

**Duration text** (Python and TS, same rules, same fixture tests):
`< 1 h` → "under 1 h"; `< 24 h` → "N h" (floor); else "N days" (floor of whole
24 h periods, "1 day" singular); truncated → "N+ days". The date shown next to it
("since 18 Oct" in the UI, "since 18.10.2026" in messages) is the episode start
in the reader's zone (browser local / Europe/Berlin). **When the start is
truncated** the date is the earliest *known* fire, not the condition's start, so
it is rendered "since before 28 Oct" / "since before 28.10.2026" together with
"N+ days" — in the Action list, the daily summary and every notifier message.
An exact date or count is shown only for a non-truncated start (plan-audit r1
finding 2).

**Action types** (Action list, daily summary): `STOP_REACHED`,
`STRUCTURAL_STOP_BREACHED`, `PREMIUM_STOP`, `TP_HIT`, `TIME_STOP`.
**Episode-notified types** (escalation): `POSITION_ALERT_TYPES` (the five plus
`EVENT_RISK`). `REGIME_CHANGE` and every auto-trader alert type keep today's
`reminderIntervalHours` window behaviour unchanged.

Constants live in `backend/app/services/alert_episodes.py`
(`EPISODE_GAP_HOURS = 72`, `REMINDER_PERIOD_HOURS = 24`,
`DAILY_SUMMARY_HOUR_BERLIN = 9`) and are mirrored in `frontend/lib/alertEpisodes.ts`
with a "keep in step" comment. They are **code constants, not settings**:
`POST /api/settings/alert-delivery` rewrites the `alert_delivery` block with a
fixed key set, so a new yaml key would be dropped on the next save. The episodes
API also returns `gapHours` so the UI never guesses it.

## Design

### 1. Episode core + read API (backend)

New `backend/app/services/alert_episodes.py`:
- `split_episodes(timestamps, gap) -> list[Episode]` (pure; `Episode` =
  start, last, count).
- `effective_gap(delivery_cfg) -> timedelta` per the rule above.
- `format_active_duration(start, now, truncated) -> str` (rules above).
- `async current_episodes(db, rec_ids, now, alert_types=None) -> dict[(rec_id, type), EpisodeView]`
  — one query over `position_alert_history` for those rec_ids (ordered), then
  `split_episodes` per key; returns current episodes only, with `truncated`.
- `async episode_start(db, rec_id, alert_type, now) -> EpisodeStart | None`
  — the current episode's `(start, truncated)` for one key (used by the notifier
  callers; `current_episodes` carries `truncated` too).

Endpoints in `backend/app/routers/alerts.py` (read-only, no writes, no commit):
- `GET /api/alerts/episodes` →
  `{ gapHours, retentionDays, generatedAt, episodes: [{ recId, symbol, alertType, startedAt, lastFiredAt, fireCount, startTruncated }] }`
  — current episodes of `POSITION_ALERT_TYPES` for **open** positions only
  (rec_ids from `portfolio_positions`).
- `GET /api/alerts/history/{rec_id}` → `{ recId, symbol, rows: [...] (newest first, cap 500), episodes: [...] (every episode of every type for that rec_id, newest first) }`;
  404 when `rec_id` is not an open position. Row fields mirror the model
  (`alertType, source, price, referenceValue, referenceKind, note, triggeredAt`).
- Pydantic response models; ISO-8601 UTC strings with offset.

Tests (`backend/tests/test_alert_episodes.py`): BMY-style fixture (rows every 4 h
since 2026-10-18 → one episode, start 2026-10-18); FTNT (TP_HIT 10-18→10-26 then
STOP from 10-31 → separate keys, TP episode not current on 11-11); gap split at
>72 h and not at 71 h; `max(72h, 2×reminder)`; truncation true/false at the
retention edge; naive vs aware timestamps; closed positions excluded; 404;
duration text table (shared with the TS test).

### 2. Escalation (backend notifications)

`alert_notifier.notify_alert` gains `episode_start: EpisodeStart | None = None`
(`(start, truncated)` from history). For an episode-notified type (and
`rec_id != 'regime'`), the window/`_first_seen` path is replaced by per-key
episode state persisted in `alert_dedup.json` under a new `episodes` map:
`{start, truncated, last_seen, last_sent}` (epoch seconds + bool), loaded
tolerantly (missing/garbled entry → dropped), written atomically with the
existing saver.

Pruning moves the earliest surviving history row forward every day once an
episode is older than the retention window, so the history start is a **lower
bound on information, not the start** when truncated. The record therefore
keeps the earliest start it has ever learned and never moves it forward
(plan-audit r1 finding 1). `last_seen` is updated on every call for the key,
**before** the master/type gating returns, so a muted type still keeps its
record current. Decision under `_fired_lock` (H = history `(start, truncated)`
or None):
1. **New episode** when any of: there is no record; `now − record.last_seen >
   gap` (we have not seen the condition for longer than an episode gap); or H
   is given, **not** truncated, and `H.start > record.last_seen` (history shows
   the run restarted after we last saw it). A truncated H never by itself
   starts a new episode.
2. New episode → `record.start, record.truncated = H` when given, else
   `(now, False)`. **Legacy seed (once, at deploy):** when no record exists, H
   is truncated, and a legacy `_first_seen` entry for the key is earlier than
   H.start, use the legacy time as the start, still `truncated = True` (the
   legacy time is the first fire ever, not necessarily this episode's start), so
   messages read "since before <legacy date>".
3. Same episode → `if H and H.start < record.start: record.start, record.truncated = H`
   (only ever moves earlier); otherwise the record is unchanged.
4. New episode → send the first-fire message (`Triggered:` = record start;
   prefixed "before " when truncated).
   Same episode → send a reminder only when `now − last_sent ≥ 24 h`; otherwise
   suppress (return False, no send).
5. Optimistic hold + rollback exactly like today: the record is updated before
   the send; on failure the previous record is restored (new-episode failure
   retries as new; reminder failure retries as reminder).
6. The file is re-saved only when the decision sends, the start changes, or
   `last_seen` advanced by ≥ 1 h (no per-tick disk write).
Reminder body adds `Active for <duration> (since dd.mm.yyyy)` computed from the
record start (`N+ days (since before dd.mm.yyyy)` when truncated), keeping the
original `Triggered:` and "Still active as of" lines. `forget_alerts` also drops
`episodes` entries for closed rec_ids (same first-`|` split). Existing legacy
`_fired` entries for episode types are ignored by the new path, and legacy
`_first_seen` is read only for the seed in rule 2 (so right after deploy each
currently active condition sends one first-fire message); both are still cleared
by `forget_alerts`.

Callers pass the start:
- `portfolio_alert_monitor._run_once`: after the generation commit, one
  `current_episodes` call (new session) for the rec_ids in this tick's alerts;
  pass each alert's `(start, truncated)`. Lookup failure → `None` (rule 1/2
  fall back to the record, or `now` for a brand-new record).
- `routers/alerts.post_alert_notify`: after its commit, `episode_start(db, …)`.

**Daily summary.** `alert_notifier.notify_daily_summary(items, now)` plus
summary-day state (`summary_day`, Berlin `YYYY-MM-DD`) in `alert_dedup.json`.
The monitor calls it at the end of `_run_once` when **all** hold: generation
succeeded this tick, Berlin local time ≥ 09:00, and `summary_day` ≠ today.
**Succeeded** is concrete (plan-audit r1 finding 3), because `fetch_quotes`
swallows errors into `{}` and drops unquoted symbols, and option quote failures
are swallowed by `gather(return_exceptions=True)`: no exception in the
generation block **and** every open position's symbol has a stock quote **and**
every open option contract has an option quote this tick. If not, `summary_day`
is not set and the next tick retries. Deadline: from 12:00 Berlin the summary is
sent even with missing quotes, with an explicit line
`N positions without a quote: SYM, SYM` (and those positions are excluded from
the counts, which the line makes visible); the zero-item rule then requires
zero items **and** zero unquoted positions. Items = this tick's alerts of the action types whose
notification is enabled for that position (`effective_enabled` override, else
global `enabledTypes`), joined with their current episode start/truncation.
- Zero items (and every position quoted) → no message, `summary_day = today`
  (one decision per day).
- Otherwise one message: subject
  `Bamendjou Portfolio — daily summary: 3 positions past stop, 1 at target, 1 time stop`
  (categories with zero omitted; "past stop" = any of STOP_REACHED /
  STRUCTURAL_STOP_BREACHED / PREMIUM_STOP; counts are **distinct positions** per
  category; singular "1 position"), body one line per (position, type), e.g.
  `BMY — Stop hit, active 9 days (since 18.11.2026)` or, truncated,
  `BMY — Stop hit, active 30+ days (since before 28.10.2026)`; Telegram HTML escaped
  like `_build_notification`.
- `summary_day` is set only after a confirmed delivery (or the zero-item case);
  a failed send retries on the next tick.
- `masterEnabled` off → the monitor already returns early: no summary.

**Logging is unchanged**: `log_position_alert`, its dedup window, the monitor's
generation order and the browser's POST cadence are not modified; tests pin row
counts for a simulated multi-day run before/after.

Settings wording (frontend, ticket 5): the "Reminder interval (hours)" hint is
changed to say it sets how often a still-true condition is re-logged to alert
history (and regime-change reminders), and that portfolio stop/target
email/Telegram now remind once a day per active alert plus a daily 09:00 summary.
`types/domain.ts` comment on `reminderIntervalHours` updated to match.

Tests (`backend/tests/test_alert_escalation.py` + adjust existing notifier
tests): first fire sends once; same-day repeats suppressed; reminder at ≥ 24 h
and not at 23 h 59; condition gap > 72 h → new first-fire; pruned-start episode
stays same episode; failure rollback both branches; restart reload; legacy state
ignored; REGIME_CHANGE and auto-trader path unchanged (window semantics);
record start never moves forward as history is pruned (BMY 18.10 under
30-day retention keeps 18.10 in every reminder; a fresh-deploy truncated start
renders "since before"); legacy `_first_seen` seed; muted type keeps
`last_seen` current; summary: once per Berlin day, not before 09:00, not on
generation failure, not when a symbol or option quote is missing before 12:00,
sent with the "without a quote" line after 12:00,
zero-item day, distinct-position counts, disabled type excluded, failed send
retried; log rows unchanged for a 3-day simulated run (monitor + browser POSTs).

### 3. History flag "Reached target, closed at a loss"

Retention (30 days default) can prune a long-held position's TP_HIT rows before
it closes, so the fact is stamped, not re-derived later:
- Migration (single new head above the current head): nullable
  `portfolio_positions.target_first_hit_at` and
  `closed_positions.target_first_hit_at` (`DateTime(timezone=True)`). Backfill in
  `upgrade()` from surviving history: open rows ← `MIN(triggered_at)` of
  `TP_HIT` for the rec_id; closed rows ← `MIN(triggered_at)` of `TP_HIT` for the
  rec_id with `triggered_at ≤ closed_at`. Rows with no surviving history stay
  NULL (no flag). Downgrade drops both in `batch_alter_table`.
- Stamp: in `generate_alerts`' TP_HIT branch and in `post_alert_notify` for a
  `TP_HIT` from a currently open position, set `target_first_hit_at = now` only
  when it is NULL (never overwritten). Server-only column: absent from the
  create/patch schemas, so PATCH (`exclude_unset`) and the merge path keep it.
- Close: `close_position` copies the locked re-read position's value into the
  closed row (every partial close too).
- `ClosedPositionSchema.targetFirstHitAt: str | None`.
- Frontend: `performanceStore` maps it; `tradeStats.targetThenLoss(h)` = 
  `targetFirstHitAt != null && realizedPnlDollar < 0`; the History row's EXIT
  CHECK cell shows a second line "Reached target, closed at a loss" (reject
  tone) with title "Target first reached <date>". A per-position TP_HIT mute
  means no fire, so no flag (documented). CSV export unchanged.

Tests: migration upgrade/downgrade on SQLite with backfill cases (pre-close
TP_HIT, TP_HIT after close ignored, none → NULL); stamp once, never overwritten;
copy on full and partial close; schema field; `targetThenLoss` (loss, win, zero,
null); History cell renders flag for FTNT/COP-like rows only. Postgres migration
run against a throwaway container if Docker is available, else recorded as not
run.

### 4. "Action needed" list (frontend)

- `frontend/lib/api.ts`: `fetchAlertEpisodes()`, `fetchAlertHistory(recId)`
  (typed; failure → throws, callers handle).
- `frontend/lib/alertEpisodes.ts`: constants mirror, `formatActiveDuration`.
- `frontend/lib/alertEpisodesStore.ts` (Zustand, **no persist**): episodes map,
  `fetchedAt`, `error`; `refresh()`; the Portfolio page refreshes on mount and
  every 60 s while mounted.
- `frontend/lib/actionNeeded.ts` (pure): `buildActionItems(positions, episodes, { premiumStopPct, now })`.
  Active conditions = `scanPortfolio([{ ...p, alertOverrides: {} }], { premiumStopPct })`
  (no `enabledTypes`: notification settings do not hide a position past its
  stop — the same override-free engine as the status badge and exit reason),
  filtered to the action types. Per position: symbol, contract, recId, the
  existing stop-breach sentence when the derived breach is stop/structural
  (moved verbatim from `page.tsx` into this helper), and one entry per active
  type: label (PREMIUM_STOP label by side as in the notifier: "Stock stop hit"
  / "Stock stop hit (short)" / "Premium stop hit"), `since` + duration from the
  current episode, or "new — not yet logged" when there is no current episode,
  or "duration unavailable" when the episodes fetch failed. Sort: positions with
  a stop-type entry first, then longest active duration first, then symbol.
- `frontend/components/organisms/ActionNeededList/` (index.tsx + module.css):
  a `section` labelled "Action needed (N)"; one item per position with its
  entries, "Review <SYM>" (opens the editor drawer, as the banner does) and
  "Close position…" (opens the existing `ClosePositionDrawer`; also switches to
  the Open tab, because the drawer renders only there). Items with a stop or
  structural breach keep `role="alert"` and the exact banner sentence. No
  dismiss button (as the banner). Renders nothing when there are no items.
- Placement: the list replaces the stop-breach banners **in their place above
  the tab strip** (directly above the Open tab, which is the default view), so
  the information the banners showed stays visible on both tabs (no silent
  removal). Nothing else on the page moves.
- Existing `stopBreachBanner.test.tsx` expectations stay true (sentence, role,
  buttons); new tests: `actionNeeded.test.ts` (evidence fixtures: BMY stop
  9 days since 18 Nov from a non-truncated episode; BMY since 18 Oct under 30-day
  retention → "30+ days, since before 28 Oct"; TP_HIT + TIME_STOP, premium-stop
  label by side, new/no-episode, fetch failure, sorting, mute ignored) and a
  page test (list renders, buttons open editor/close drawer, Close from the
  History tab switches to Open).

### 5. In-app toasts follow the episode logic (frontend)

`alertStore` (persisted, `bamendjou-alerts-v2`): version 3 → 4; new persisted
`episodes: Record<key, { startedAt: string; lastSeenAt: number; lastSurfacedAt: number }>`.
`episodes` is added to **`partialize`** (so it is written) and to **`merge()`**
(`episodes: ps.episodes ?? {}`, so it survives every hydration — `merge` rebuilds
the state from an explicit field list), and `migrateAlerts` keeps it through the
same tolerant record check it applies to `suppressedAlerts` (entries with a
non-string `startedAt` or non-finite numbers dropped) (plan-audit r1 finding 4).
Its STRUCTURAL_STOP_BREACHED backfill
condition changes from `_version < ALERT_STORE_VERSION` to `_version < 3` so the
bump does not re-run it. For `POSITION_ALERT_TYPES` only (scan lifecycle types
unchanged), in `addToast`:
1. `ep = episodes[key]`; new episode iff `!ep || now − ep.lastSeenAt > gap`
   (72 h, from `alertEpisodes.ts`). `lastSeenAt` is updated **before** the
   suppression check, so an acknowledged condition still keeps its episode alive.
2. New episode → clear `suppressedAlerts[key]`; an existing un-acknowledged row
   for the key is refreshed in place with `firedAt = now`, `dismissed = false`;
   otherwise a new row; chime if sound is on; `episodes[key] = {now, now, now}`.
3. Same episode, `now − lastSurfacedAt ≥ 24 h` → daily reminder: clear the
   suppression; an un-acknowledged row is un-dismissed; otherwise a new row with
   `firedAt = ep.startedAt` (original trigger, the existing convention);
   `lastSurfacedAt = now`; chime if sound is on.
4. Same episode, not due → today's behaviour (suppressed → return; row → refresh
   in place; no row → new row).
5. The notify POST throttle and its early return for a suppressed key are
   **unchanged** (they drive frontend history rows).
`clearAll` also clears `episodes`; `deleteAlert` leaves them. Tests: new
episode after 72 h re-toasts an acknowledged condition; acknowledged condition
re-surfaces once after 24 h and not before; un-dismiss on reminder; POST cadence
unchanged (spy); scan types unaffected; v3→v4 migration keeps toasts and does
not re-add an unchecked STRUCTURAL_STOP_BREACHED; a persist→rehydrate round
trip keeps `episodes` and keeps an acknowledged condition suppressed (no
re-toast, no chime after reload).

## Tickets (sequential; each ends green on its own)

| # | Ticket | Files (main) | Blocked by |
|---|---|---|---|
| T1 | Episode core + read API | `services/alert_episodes.py` (new), `routers/alerts.py`, `schemas` (response models), tests | — |
| T2 | Escalation + daily summary | `notifications/alert_notifier.py`, `portfolio_alert_monitor.py`, `routers/alerts.py`, tests | T1 |
| T3 | History flag (stamp + migration + UI) | migration (new), `models/portfolio.py`, `models/closed_position.py`, `alert_generator.py`, `routers/alerts.py`, `routers/portfolio.py`, `schemas`, `performanceStore.ts`, `tradeStats.ts`, portfolio `page.tsx` (History cell), `types/domain.ts`, tests | T2 |
| T4 | Action needed list | `api.ts`, `alertEpisodes.ts`, `alertEpisodesStore.ts`, `actionNeeded.ts`, `ActionNeededList/`, portfolio `page.tsx`, `types/domain.ts`, tests | T1, T3 |
| T5 | In-app toast episodes + settings wording | `alertStore.ts`, `alerts/page.tsx`, `types/domain.ts`, tests | T4 |

Serial because T1–T3 share `routers/alerts.py`, T3–T4 share `page.tsx`, T3–T5
share `types/domain.ts`. Final verification, `git merge origin/main`, code audit
and PR are the coordinator's.

## Gate notes for auditors

Gate-relevant surfaces: the duration numbers and dates (episode split, gap,
truncation, timezone), the summary counts, the History flag (wrong flag = wrong
claim about a trade), the migration/backfill and the stamp (persisted data), the
`alert_dedup.json` shape (persisted state; tolerant load), and the
`alert_store` v4 migration (persisted browser state). No order or broker path is
touched by any ticket.

## Acceptance (from #672, points 1–3)

- [ ] Action list shows the evidence cases correctly on fixtures (episode start, duration).
- [ ] Dispatch tests: one message per episode start, one reminder per day, daily summary; no lost fires in the log.
- [ ] History flag for target-then-loss trades.
- [ ] Python 3.11; typecheck + full tests green; plan audit and code audit clean (`audit_rule`).
- [ ] Truncated episodes never show an exact date or count.
- [ ] Point 4 not built; no order placement added anywhere.
