# DECISION-34-WATCH-DELIVERY-RESIDUALS Implementation Plan

Phase ID: `DECISION-34-WATCH-DELIVERY-RESIDUALS`
Tracking Issue: [#178](https://github.com/Netke237/trading-assistant/issues/178)
Branch: `board/decision-34-watch-delivery-residuals-ee173a25`
Date: 2026-10-21

## 1. Goal & Context

Addresses the residuals from ticket 34 / issue #178 on per-channel watch delivery and stuck-alert policy, following Kenneth's explicit decisions on 2026-10-15:
1. **Two stuck alerts in a row (Recommendation B):** Accept another watch's successful delivery on the same channel, in the same run, as proof that the channel works (cross-watch proof). An undeliverable head whose probe failed is dropped on that channel rather than treating the probe failure as an outage when the channel is proven up.
2. **Gmail recipient check (Recommendation A):** Fix `ready_channels` in `backend/app/services/notifications/dispatch.py` to require a recipient (`to` or `BAMENDJOU_GMAIL_TO`). A channel without a recipient cannot deliver and must not count as ready.
3. **Test gaps (Recommendation: yes):** Pin mutation survivor M25 (delivered probe clearing `stuck`), mutation survivor M33 (commit mode queuing fresh event behind non-empty queue), and fix `test_strategy_watch_router.py:176` so `notify.assert_not_called()` can fail if notifications were triggered.
4. **UI (/strategy-watch):** Display of queued alerts deferred to a later UI item per Kenneth's decision (out of scope for this backend phase).

---

## 2. Technical Design

### 2.1 Gmail Recipient Check (`backend/app/services/notifications/dispatch.py`)

In `ready_channels(cfg: dict) -> list[str]`:
Currently (lines 111-115):
```python
    gmail = _channel_block(cfg, 'gmail')
    if gmail.get('enabled') \
            and (gmail.get('smtp_user') or os.getenv('BAMENDJOU_GMAIL_USER', '')) \
            and (gmail.get('smtp_password') or os.getenv('BAMENDJOU_GMAIL_PASSWORD', '')):
        ready.append('gmail')
```
Fix to:
```python
    gmail = _channel_block(cfg, 'gmail')
    if gmail.get('enabled') \
            and (gmail.get('smtp_user') or os.getenv('BAMENDJOU_GMAIL_USER', '')) \
            and (gmail.get('smtp_password') or os.getenv('BAMENDJOU_GMAIL_PASSWORD', '')) \
            and (gmail.get('to') or os.getenv('BAMENDJOU_GMAIL_TO', '')):
        ready.append('gmail')
```
This mirrors `dispatch('gmail', to=gmail.get('to', '') or os.getenv('BAMENDJOU_GMAIL_TO', ''))` in `_send_channels`. When `to` is missing/empty, Gmail is excluded from `ready_channels`, preventing an unconfigured recipient from stalling watch alert queues.

### 2.2 Cross-Watch Delivery Proof (`backend/app/services/strategy_watch_evaluator.py`)

#### Context & Data Structures
`_Run` captures the delivery state of a single evaluation run.
Add tracking fields with defaults:
```python
@dataclass
class _Run:
    mode: str
    cfg: dict = field(default_factory=dict)
    channels: tuple[str, ...] = ()
    delivered_channels: set[str] = field(default_factory=set)
    stuck_probes: list[dict] = field(default_factory=list)
```

#### Tracking Deliveries
Whenever `_send` returns:
For each channel `c` where `res[c]` is True:
```python
run.delivered_channels.add(c)
_apply_cross_watch_proof(run, c)
```

#### Applying Cross-Watch Proof (`_apply_cross_watch_proof`)
```python
def _apply_cross_watch_proof(run: _Run, channel: str) -> None:
    """When channel `channel` is proven up in this run, resolve any pending stuck
    probes on that channel across all watches that ran earlier."""
    if not run.stuck_probes:
        return
    remaining = []
    for item in run.stuck_probes:
        if item["channel"] != channel:
            remaining.append(item)
            continue
        w_id = item["watch_id"]
        c = item["channel"]
        w = strategy_watch_store.get_watch(w_id)
        if not w:
            continue
        committed, queue = _split_state(dict(w.get("last_state") or {}))
        h = item["head_entry"]
        target_h = next((e for e in queue if isinstance(e, dict) and e.get("fired_at") == h.get("fired_at") and _reason(e) == _reason(h)), None)
        if target_h is not None and c not in _done(target_h):
            target_h["channel_done"] = {**_done(target_h), c: "dropped"}
            logger.error(_DROP_LOG, w_id, item["head_failures"], c, _reason(target_h))
            probe_e = item.get("probe_entry")
            if probe_e is not None:
                target_p = next((e for e in queue if isinstance(e, dict) and e.get("fired_at") == probe_e.get("fired_at") and _reason(e) == _reason(probe_e)), None)
                if target_p is not None:
                    now = item.get("now") or _utcnow()
                    if _failure_counts(target_p, c, now):
                        target_p["channel_failures"] = {**_failure_map(target_p), c: _failures(target_p, c) + 1}
                        target_p["channel_last_failure_at"] = {**_last_failure_map(target_p), c: now.isoformat()}
            committed, queue = _pop_complete(committed, queue, run.channels)
            _write(w_id, {**committed, "pending_events": queue} if queue else committed)
    run.stuck_probes = remaining
```

#### Inside `_resend_watch`
When a probe entry `e` is sent on channel `c` for eligible head `h`:
If `res[c]` is True:
- `e["channel_done"] = {**_done(e), c: "delivered"}`
- `h["channel_done"] = {**_done(h), c: "dropped"}`
- `logger.error(_DROP_LOG, ...)`
- `run.delivered_channels.add(c)`
- `_apply_cross_watch_proof(run, c)`

If `not res[c]` (the probe failed on `c`):
- `h, n = stuck.pop(c)`
- If `c in run.delivered_channels`:
  - Channel `c` is already proven up in this run by an earlier watch!
  - `h["channel_done"] = {**_done(h), c: "dropped"}`
  - `logger.error(_DROP_LOG, w["id"], n, c, _reason(h))`
  - `changed = True`
  - Record counted failure on `e` for `c` (now the new head).
  - `blocked.add(c)`
  - Log warning indicating head was dropped via cross-watch proof.
- Else:
  - Record candidate in `run.stuck_probes`:
    `{"watch_id": w["id"], "channel": c, "head_entry": h, "head_failures": n, "probe_entry": e, "now": now}`
  - `blocked.add(c)`
  - Log warning that probe was not delivered and queue kept.

#### Inside `_deliver_or_queue`
For fresh event probes (`c in probes`):
- If `res[c]` is True:
  - `h["channel_done"] = {**_done(h), c: "dropped"}`
  - `run.delivered_channels.add(c)`
  - `_apply_cross_watch_proof(run, c)`
- If `not res[c]`:
  - If `c in run.delivered_channels`:
    - `h["channel_done"] = {**_done(h), c: "dropped"}`
    - `logger.error(_DROP_LOG, t.watch_id, ready[c], c, _reason(h))`
  - Else:
    - Add to `run.stuck_probes` in case subsequent transitions deliver on `c`.

#### Order-Independence
- If Watch B delivers on `c` before Watch A evaluates: `c in run.delivered_channels` is True when Watch A evaluates, so Watch A drops its stuck head immediately.
- If Watch A evaluates before Watch B delivers: Watch A registers a candidate in `run.stuck_probes`. When Watch B delivers later in the same run, `_apply_cross_watch_proof(run, c)` updates Watch A and drops its stuck head.
- If no watch delivers on `c` in the run (full outage): `c` is never in `run.delivered_channels`, `run.stuck_probes` is never triggered, no alerts are dropped.

### 2.3 Test Gaps

1. **Mutation Survivor M25 (`stuck.pop(c)`):**
   - In `test_watch_resend_per_channel.py`, test a queue of 3 events: `[RZ-head (failures=3), RZ-P2 (probe), RZ-P3 (third entry)]`.
   - Deliver `RZ-P2` and `RZ-P3`.
   - Verify `RZ-head` is dropped, `RZ-P2` is delivered, and `RZ-P3` is delivered.
   - If `stuck.pop(c)` were omitted, `stuck` would retain `c` and attempt to drop `RZ-head` again or treat `RZ-P3` as a probe.
2. **Mutation Survivor M33 (`run.mode == "commit"` with non-empty `t.pending`):**
   - Test in `test_watch_resend_per_channel.py` where `run.mode == "commit"` (no notification channel enabled) and watch has existing `pending_events`.
   - Trigger a fresh transition `t`.
   - Verify `t` is appended to `pending_events` (queued) and NOT committed to `committed` state while earlier events remain uncommitted.
3. **`test_strategy_watch_router.py:176` (`notify.assert_not_called()`):**
   - In `test_evaluate_endpoint_runs_scheduled_composites`, patch `read_notification_config` to return an enabled channel with valid configuration (mode `"send"`).
   - This ensures that if `evaluate_scheduled` had returned True, `notify_channels` would have been invoked, making `notify.assert_not_called()` a real, un-bypassable assertion.

---

## 3. Build Tasks & Tickets

- **Ticket 1: Gmail recipient check in `dispatch.py` + tests**
  - Update `ready_channels` to check `gmail.get('to') or os.getenv('BAMENDJOU_GMAIL_TO', '')`.
  - Add unit tests in `test_watch_resend_per_channel.py` verifying that Gmail with credentials but without `to` is excluded from `ready_channels`.
- **Ticket 2: Cross-watch delivery proof in `strategy_watch_evaluator.py` + tests**
  - Add `delivered_channels` and `stuck_probes` to `_Run`.
  - Add `_apply_cross_watch_proof`.
  - Wire cross-watch proof into `_resend_watch` and `_deliver_or_queue`.
  - Add tests in `test_watch_resend_per_channel.py`:
    - Two stuck alerts in Watch A, Watch B delivers on channel in same run -> Watch A head dropped, probe becomes new head.
    - Reverse order (Watch A before Watch B) -> head dropped cleanly via deferred proof.
    - Fresh event probe failure with cross-watch proof -> head dropped.
    - Full outage on channel -> nothing dropped, queue preserved.
    - Single stuck alert alone without probe -> nothing dropped without probe attempt.
- **Ticket 3: Test gaps remediation (M25, M33, router line 176)**
  - Add test killing M25 (delivered probe clears `stuck` before subsequent queue entries).
  - Add test killing M33 (commit mode queues fresh event behind non-empty queue).
  - Update `test_strategy_watch_router.py:176` to patch notification config with ready channels.
- **Ticket 4: Full verification, state ledger & clean code audit**
  - Run full backend pytest suite (Python 3.11).
  - Run frontend typecheck & tests.
  - Run `python scripts/state.py`.
  - Document all audit rounds and evidence.

---

## 4. Acceptance Criteria

- [ ] `ready_channels` excludes Gmail when neither `to` nor `BAMENDJOU_GMAIL_TO` is provided.
- [ ] A watch with two stuck alerts in a row has its head dropped when another watch successfully delivers on the same channel in the same run.
- [ ] Cross-watch proof behaves identically regardless of watch execution order.
- [ ] In a real channel outage (no watch delivers), no alerts are dropped.
- [ ] Mutations M25 and M33 are killed with dedicated tests.
- [ ] `test_strategy_watch_router.py:176` `notify.assert_not_called()` is verified against a configured channel.
- [ ] All backend and frontend tests pass on Python 3.11.
- [ ] `scripts/state.py` reports clean with no drift.
- [ ] Independent plan audit and code audit clean under `audit_rule`.
