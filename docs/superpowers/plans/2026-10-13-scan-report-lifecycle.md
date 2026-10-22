# LOG-02 lifecycle implementation reconciliation

13 October 2026. Implements approved LOG-02 requirements in
`docs/superpowers/specs/2026-10-13-approved-screener-designs/scan-log-isolation-tickets.md`.
This elaborates application boundaries and tests; it does not change category,
retention, migration, concurrency or broker requirements. Wait until LOG-01 is
committed and coordinator permits dependent work. No frontend implementation:
its new presentation foundations remain blocked. No shipping/audit-clean claim.

## Scope and contract

Owned application files: routers/scan.py, routers/stock_scan.py,
schemas/__init__.py, schemas/stock_scan.py, services/scan_schedule_scheduler.py,
services/scan_report_lifecycle.py (new), and main.py startup recovery. Paths above
are relative to backend/app. Tests: backend/tests/test_scan_report_lifecycle.py
and backend/tests/test_scan_report_routes.py (new). No changes to LOG-01 model,
migration, API or service except a concrete dependency defect reported upstream.

LOG-01 owns begin_run, finish_run, get_latest, get_run, recover_interrupted and
ScanReportStorageError. Each mutation uses its own fresh AsyncSessionLocal
session, never the request session which can already contain scan/broker work.
finish_run accepts the resolved terminal inputs snapshot. Running inputs carry
the immutable dispatch request and explicit unresolved fields. Terminal states
complete/failed/cancelled/no_data/interrupted are source-aware. A scan with zero
survivors and actual completed scoring is complete; do not equate zero with
no_data. No-data applies only when the source actually establishes missing data.
Options core can return state FAILED (all gathered workers raised), so the
terminal mapping must preserve failed plus its observed sanitized diagnostics
and matching result instead of treating every returned object as complete.

Options request category is fixed options. StockScanRequest adds category
Literal[stocks,pullback] default stocks. Existing stock callers retain stocks;
Pullback callers must supply pullback explicitly. Pre-Breakout and Fib transport
routes always select prebreakout and fib. Trigger is server assigned manual for
HTTP entry points and scheduled for scan_schedule_scheduler; client input cannot
pretend to be a scheduled run. There is no active automatic scan engine in this
scope; future automatic callers use the same wrapper with automatic trigger.

Object results add nullable report_run_id/report_generation and
report_persistence (saved/unavailable). Existing scan_id, ranking, candidates,
legacy last-result endpoints, broker calls and order booking stay intact. List
routes preserve list bodies and expose X-Scan-Report-Run-Id,
X-Scan-Report-Generation, X-Scan-Report-Persistence in optional Response headers;
CORS exposes these headers for browser callers. Direct Python calls may omit
Response and still generate durable reports. Read-only retrieval is by LOG-01's
run-ID API. Persistence failure before work refuses with a safe 503 (no claimed
started durable attempt); failure after work returns matching current result
with unavailable save status and identity, leaving prior durable evidence intact.
Failure responses and cancellation finish an existing attempt with safe enum
scan_failed/cancelled. No provider exception string enters durable reports.

## Execution boundaries

A shared async lifecycle runner deep-copies the request at dispatch, establishes
an isolated ContextVar collector, begins durable attempt, executes the existing
core callback, and finishes accepted result plus diagnostics in one LOG-01
transaction. It resets context in finally. CancelledError is caught separately;
a shielded fresh-session terminal write marks cancelled before propagating the
cancellation; storage failures are explicit in logs and safe HTTP error headers
when an HTTP failure is returned. No scan starts merely because report is read.
The existing manual wrappers retain their legacy updates/auto-trade behavior;
lifecycle wraps core scan work, not the broker worker/booking. Scheduled runner
uses the same lifecycle around its globals-free core and remains broker-free.
Successful scheduled metadata is included in its existing result_json. Error
notifications/history persist only safe classified messages for these scans,
not raw exception payloads. Existing disabled/deleted schedule behavior is kept.

The collector records actual expanded symbols before exclusion, dispatched
symbols after exclusion, and observed exclusions at the resolution sites in
both cores and PB/Fib routes. Resolution failure keeps these explicitly
unavailable. PB/Fib capture validated merged params immediately before their
loops. Option/stock diagnostics retain their own pipeline schemas and symbols.
Bare-list PB/Fib diagnostics record accepted symbols and observed exclusions;
reject counts/stage reasons unavailable because these cores don't emit them.
Data-fetch/signal exceptions in PB/Fib may be recorded as safe symbol/code pairs
at their existing catches, without exception text or manufactured rejections.

Options/Stocks result reasons contain provider strings today. Keep normal
transport results unchanged, but persist a sanitized copy: any source exception
becomes a fixed data_processing_failed code at its producing catch; ordinary
known gate reasons and measured values remain. Capture safe per-symbol
exception membership in collector so only those rejected reasons are replaced.
Unknown unsafe diagnostics are explicitly unavailable rather than leaked or
invented. LOG-01 rejects forbidden key names; it does NOT validate secret-bearing
string values. Adapters therefore build an allowlisted persisted request/input
projection BEFORE begin_run and finish_run. Supported override fields use the
actual scanner's fixed field names with finite numeric/bool values and bounded
fixed-domain enum values; arbitrary string values, unknown keys and free text
are omitted with explicit input_fields_unavailable paths. Ticker/universe fields
use bounded domain validation (ticker characters and known preset/sector forms),
not a generic string pass-through. Do not rely on Pydantic's unknown-key ignore
or the service's key-name check to sanitize arbitrary overrides.

Exclusion reason text is arbitrary configuration content and is never persisted
verbatim: store excluded symbol plus fixed excluded_by_scan_policy code and
reason_unavailable true. Known scan gate reasons must be produced from typed
observed values and fixed domain templates; a prefix alone is insufficient to
make an exception-containing reason safe. Sanitize result copies AND diagnostics
AND inputs; retaining an unsafe string in any duplicate envelope location would
still leak it. Transport result behavior is unchanged. Missing unsafe fields
remain explicitly unavailable and no report claims effective inputs complete.
Serialization/storage failure still exposes unavailable save status rather than
a false successful save.

## Effective settings capture, bounded scope

Do not fetch mutable YAML at completion and label it effective. Capture deep
copies at actual value-use boundaries inside owned routers: full scoring cfg
when read, merged reward/risk config, resolved regime/fundamentals gates,
contract rules/event/DTE windows, shortlist cap, effective stock merged strategy
kwargs/multi variant params, PB/Fib validated params and explanation gate/rule
configs already emitted by stock_scorer. Record source-qualified distinct
observations rather than overwrite the first value when a config changes during
an await. Snapshot copies are immutable with respect to later dictionary edits.
Per-symbol records identify symbol when a worker can observe distinct settings.
ContextVar task inheritance isolates concurrent categories and allows gather
workers to collect into their parent run. No global monkeypatch and no alteration
to cache_clear/cache_info or numeric functions. No broad cached-loader wrappers
in this stage. Independently consulted settings not captured at these owned
boundaries are explicitly named configuration_unavailable, and the report marks
effective_configuration_complete false. This avoids claiming a full effective
configuration when scoring internals consult a different cached document.
Adding complete loader-level instrumentation is a later separate small backend
stage, not an implicit expansion into scoring algorithms in this diff.

Startup calls recover_interrupted before restoring legacy sessions and starting
scan schedulers. Failure is a safe startup failure, never a false recovery claim.
Server generations in LOG-01 govern latest attempts/reports: lifecycle code
never uses client timestamps, global mode, list indices or completion order as
report ownership. Late completions may keep their own identity but cannot replace
newer latest reports. Existing legacy globals are not used to label a durable
report or its frozen input snapshot.

## Red-first verification and finish

1. Tests first: shared lifecycle fresh sessions; persisted started attempt before
callback; zero candidates complete; resolution failure and cancellation preserve
prior report; finish storage failure exposes unavailable; deep-copy request and
collector observations survive edits; concurrent collectors don't mix data.
2. Route tests: all five explicit categories and run IDs, matching snapshot/result
symbols and source pipeline schemas; Options A/Stocks B/Pre-Breakout C/Pullback D/
Fib E then Options F leaves B/C/D/E unchanged. Core-stub tests assert same-category
reverse completion and scheduled/manual overlap via real LOG-01 storage. List
responses retain body shape and headers. Stock default stocks and explicit
pullback, server trigger assignment, safe error persistence, missing diagnostics,
no-data only when proven, cancellation and recovery all exercised.
Include secret-bearing values under otherwise permitted keys: overridden method
or parameter strings, exclusion reason containing https://user:password@broker,
and exception-containing gate reason. Assert no durable begin/terminal payload
or scheduled error/result record contains these strings; omitted paths/reasons
are explicitly unavailable. Assert fixed-domain gate reasons and measured
numeric values remain available rather than globally dropping diagnostics.
3. Config tests mutate source dict/control values during awaits and assert saved
observations preserve the actual observed values/symbol identities and mark
uncaptured config unavailable. Numeric/ranking/broker regression suites cover
unchanged results and no scheduled fire. Tests must fail for predicted absent
lifecycle/metadata/capture before implementation; dependency/import failures alone
are not a valid red result.
4. Verify prepared Python 3.11; run focused suites, full backend pytest and
frontend typecheck/test per agent brief. Report unrelated failures without fixing
them. Commit only owned files with repository attribution. Coordinator handles
independent code audit, state, claims, GitHub, push and merge. No self-audit claim.
