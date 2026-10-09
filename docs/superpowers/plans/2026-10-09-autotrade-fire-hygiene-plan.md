# AUTOTRADE-FIRE-HYGIENE implementation plan

Date: 2026-10-09. Stage: proposed plan; not yet independently audited. No application implementation is authorized by this plan alone.

## Problem and boundary

`routers/scan.py:run_scan` awaits `asyncio.to_thread(auto_trader.maybe_fire_on_scan, ...)`, then books the returned FiredOrder on the originating loop/session. Cancelling that await does not stop a running worker: a broker order can finish without the caller booking or recording its unbooked outcome. `routers/auto_trade.py:fire_now` already retains the underlying concurrent Future and records cancellation outcomes through a thread-side callback.

This package brings the scan trigger to that explicit outcome-ownership contract. It records the outcome after cancellation rather than introducing automatic recovery booking. It also makes cancellation during booking observable without falsely declaring a committed position absent. Durable reconciliation, automatic retries, broker-error classification, daily-budget policy, and altered scan eligibility are separate work. The already-fixed entry-premium bound is not reopened.

Scheduled scans call the shared scan core and their own persistence path, not manual `run_scan`; they must continue never to auto-fire. A manual and scheduled scan may overlap. Only the manual trigger owns its submission and booking, using its local `req`, `result`, and portfolio snapshot; no callback reads global `_last_request` or `_last_result` to identify an order.

## Invariants

- One manual trigger submits its worker once; no callback resubmits or re-arms an order.
- Normal completion invokes `book_fired_order` exactly once, on the event loop with the request session. No thread touches AsyncSession, ORM instances, or booking.
- Retain `maybe_fire_on_scan`'s snapshot identity/`expect` safeguards, attempt IDs, stale-arm/refusal routing, broker-rejection handling and durable daily-risk hooks. Executor serialization is not a substitute for those guards, including manual `/fire` racing a scan trigger.
- Release the read transaction before dispatch as today. Capture daily-risk hooks on the originating loop; propagate them unchanged. Do not move risk reservation onto a worker event loop or alter its accounting.
- Cancellation propagates to the caller. There is no background booking using a closing request session and no automatic retry on an uncertain result.
- Cancellation diagnostic handling cannot raise, log credentials, assert a cancelled running thread stopped, or claim booking failed when it may already have committed.

## Build tickets (one fresh implementer per ticket)

### H1 — Retain and report scan-trigger worker outcome

Dependencies: independently clean plan; phase claim available. Add a scan-trigger-specific single-worker ThreadPoolExecutor in `routers/scan.py` (or a small service owned solely by this path), retaining its concurrent Future. Submit `maybe_fire_on_scan` exactly once with existing arguments and await `asyncio.wrap_future`. This executor must not share `/fire`'s executor or the default scan data-fetch pool; queued-work behavior becomes explicit while the existing AutoTrader lock/expect checks remain authoritative.

Catch cancellation around the worker await. Attempt cancellation of the concurrent Future to prevent genuinely queued work; cancellation of already-running work is ineffective and must not be described otherwise. Install exactly one non-raising thread-side done callback, then re-raise. `add_done_callback` handles both completion-before-registration and registration-before-completion. Do not rely on an asyncio task callback that global shutdown can cancel.

The callback distinguishes: cancelled before start (nothing dispatched), successful `None` (no returned order; existing service refusal diagnostics remain authoritative), a FiredOrder (broker outcome returned but booking was never started), and worker exception (dispatch/booking status unknown unless a typed outcome proves otherwise). For FiredOrder include its actual symbol, broker/order ID, status and attempt ID; do not use the currently armed slot. Refusals and explicit broker rejection must not be described as a filled/live trade. Cancellation logging is diagnostic only and writes no synthetic portfolio or risk history rows.

Acceptance tests in `backend/tests/test_autotrade_scan_fire_cancellation.py`: event/barrier-controlled running worker finishes after caller cancellation; future queued behind an occupied executor is cancelled without entering worker or consuming the arm; completion races callback installation; None and exception results; callback does not raise for cancelled Futures. Assert submission count, booking count zero for the cancelled-await branch, and one terminal diagnostic. No timing sleeps or real broker/provider access.

### H2 — Preserve booking ownership and cover downstream cancellation

Depends on H1. Extend the narrow scan auto-fire ownership block through booking, recording its phase: worker pending, booking not started, booking started, booking returned. Keep `book_fired_order` unchanged unless the independently reviewed implementation demonstrates a required adjustment; it intentionally allows CancelledError to propagate and the writer can commit before later notification work completes.

On cancellation after FiredOrder delivery but before booking starts, log the returned outcome once as booking not started. On cancellation while booking is awaited, report **booking confirmation unavailable; check broker and portfolio before acting** with order/attempt identity. Do not assert NOT BOOKED, tell the user to add another position, or launch a second booking. No callback owns booking once the normal coroutine has started it. Cancellation after booking returns must retain the actual returned booked/not-booked status, with no false unbooked diagnostic; cancellation in later scan persistence does not undo a known booking. Preserve local request/result pairing in `_upsert_session`.

Acceptance: successful manual PASS scan submits/books once; non-PASS and unarmed scans do neither; None/refusals do not book; broker rejection uses existing booking policy. Inject cancellation at delivery, while booking awaits before write, after simulated writer commit but before booking return, and during later scan persistence. Verify no duplicate send/booking, truthful diagnostics, cancellation propagation and no session use from workers. Use the existing real writer/booking test harness for commit-then-cancel where available rather than pretending a cancelled coroutine guarantees rollback. Add an integration assertion that scheduled scans never invoke the dispatch helper, including manual/scheduled overlap. Add deterministic re-arm/manual-fire overlap coverage demonstrating existing identity guards prevent authorizing a new order on an old snapshot.

### H3 — Correct stale execution-context documentation

Depends on H2. Update the two `auto_trader.py` descriptions recorded in open_questions that say manual `/fire` runs on the event-loop thread. Describe its dedicated executor and scan's new explicit executor; retain the rule that notification helpers run in threads without an active event loop, while booking remains on the originating loop. Update neighboring claims that scans discard FiredOrder results: normal completion books them, cancellation records the outcome. Changes are explanatory only; do not modify trading policy or unrelated historical audit notes. Review every edited mechanism claim against actual call sites.

## Verification and phase gate

Use the prepared Python 3.11 backend runtime. Run the new cancellation tests plus `test_p3c_fire_off_loop.py`, `test_auto_trader.py`, auto-trade booking/daily-risk tests and scan core/session/schedule tests selected from actual repository names. Tests must isolate DB/files and avoid runtime environment variables that override fixture isolation. Run frontend typecheck before commit per AGENTS even though this package has no frontend edits; run `scripts/state.py` to detect ownership/state drift. No live broker orders are needed.

The coordinator cuts formal tracking/child issues only after a fresh independent plan auditor reports zero gate findings. The gate is wrong user/broker numbers, corrupt persisted data, or mechanism comments that would cause a wrong change. Code is audited as one integrated phase diff after all build tickets close, with fresh reviewers and a maximum of three rounds per stage; later rounds cover fixes/interactions only. Record exact reviewed scope and findings in phase state. A built branch is unfinished until independently audit-clean; merging requires Kenneth's explicit authorization.
