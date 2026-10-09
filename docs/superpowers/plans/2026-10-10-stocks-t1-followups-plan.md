# STOCKS-T1-FOLLOWUPS — green CI (#129) and time exits on Step 6

Phase id: `STOCKS-T1-FOLLOWUPS` · Branch: `claude/stocks-t1-followups` (cut from main `a2b6935c`)
Requested by Kenneth 2026-10-10 after STOCKS-HORIZON-T1 shipped (PR #138).

## Why

1. **F1 (#129).** `main`'s backend CI is red on
   `tests/test_stock_scan_backtest_commission.py::test_analyze_core_passes_commission_from_get_costs`,
   and two `tests/test_shortlist.py` tests fail when the network is unavailable
   (`test_shortlist_keeps_highest_scores_not_universe_order`,
   `test_trimmed_names_are_recorded_and_counted_once`). A red `main` forces every merge to argue
   "it is only #129", which is how a real failure slips through (T1's two-alembic-heads defect was
   caught only by a hand comparison against the known list). These are **test-isolation defects, not
   app defects**.
2. **F2 (time exits on Step 6).** T1 H2 closes a backtest trade at the next open once it has been held
   `hold_max_days` (exit reason `time`), and the backtest counts these (`BacktestResult.n_time_exits`).
   The count never reaches the API or the UI, so a keep/drop verdict that moved because of the time
   exit is shown with no reason. T2 (#116, Adopt) needs it visible.

## The gate (audit_rule)

A finding blocks only if it can put a wrong number in front of a user or on a broker order, or
corrupt persisted data.

## F1 — test isolation for #129 (tests only)

**Mechanism today (verified 2026-10-10 on `a2b6935c`):**

- The commission test builds the score card as a `MagicMock`. `_analyze_core`
  (`backend/app/routers/stock_scan.py`, the confidence cap ~L1051 and the bearish/earnings
  `dataclasses.replace` calls after it) calls `dataclasses.replace(card, ...)` whenever the cached
  confidence for the symbol/strategy is missing (Unvalidated → CAUTION). Whether that cache has an entry
  depends on machine state and on tests that ran earlier, so the test passes or fails by order. The test
  also leaves `_earnings_days_for` unpatched.
- The two shortlist tests patch the scan's quote/candle/chain fetchers but something on the path still
  reaches a live provider (the issue saw a yfinance fallback; locally the two files take minutes, which
  points to live fetches or provider timeouts). Offline, the unstubbed data changes which names rank
  first, so the ranking assertions fail.

**Change (tests only — no file under `backend/app/` changes):**

- Commission test: give `_analyze_core` a real `StockScoreCard` (the shape `test_shortlist.py`'s
  `_pass_card` builds) instead of a `MagicMock`, and pin the inputs the test does not own: the cached
  confidence (a fixed measured value) and the earnings lookup. Keep the assertion: `_analyze_core` passes
  the same `commission=` as `_process_stock`.
- Shortlist tests: find every live-provider call left on the scan path under these fixtures (run with
  sockets blocked to find them) and stub it in the fixture, so the ranking comes only from the scores the
  test sets. Keep both ranking assertions unchanged.
- Do not weaken, skip or `xfail` any of the three; do not change any assertion's expected values.

**Test first:** reproduce each failure deterministically (commission: force the confidence cache empty;
shortlist: block sockets), see it fail for the stated reason, then fix the fixture.

**Done when:** the two files pass alone, in the full suite, and with outbound sockets blocked
(e.g. a `socket.socket.connect` guard in a throwaway conftest or `pytest-socket` if already installed —
do not add a dependency); they run in seconds, not minutes.

## F2 — time exits on Step 6

**Mechanism today:** `run_strategy_backtest` returns `BacktestResult` with `n_time_exits`
(`backend/app/services/strategy_backtest.py`). `stock_scan.py` builds `BacktestOut`
(`backend/app/schemas/stock_scan.py`) at two places (`_analyze_core` ~L1250 and `_process_stock`
~L1636) without it. `BacktestOut` is persisted inside saved scan sessions and the continuous scan's
`stock-current` row, and older rows must still deserialize. The frontend type is
`frontend/types/stockDomain.ts` (and the api type in `frontend/lib/api.ts` ~L250);
Step 6 renders the backtest columns in `frontend/app/(frame)/screener/step-6-backtest/page.tsx`.

**Change:**

- Backend: `BacktestOut` gains `n_time_exits: Optional[int] = None` and `hold_max_days: Optional[int] =
  None`. Both `BacktestOut(...)` constructions fill them from the `BacktestResult` and the hold actually
  passed to that backtest: `_bt_hold = hold_for_backtest(req.horizon, _bt_strategy, req.hold_max_days)`
  (`stock_scan.py` ~L1006 and ~L1497; the same value is in the cache key, so a cached result always
  carries its own hold). The ~L1250 construction is in the analysis endpoint (the caller of
  `_analyze_core`), built from `core.bt_result`; `_AnalyzeCore` has no hold field, so add one
  (`bt_hold`) set from `_bt_hold` inside `_analyze_core` rather than recomputing it. A row saved before
  this change deserializes with both `None` (no `extra="forbid"` on these models).
- **What `None` means (plan round 1, PF-1):** `n_time_exits is None` means **unknown** — a result saved
  before this change (backend `stock-current` row, scan-schedule rows, or the frontend's persisted
  `scanStore.stockScanResult` in localStorage, where the fields are **absent/undefined**, not null). Only
  a NEW result can say "no hold": `n_time_exits` is an int (0 or more) and `hold_max_days` is None
  (Intraday horizon or an intraday strategy). So every new result always carries `n_time_exits` as an
  int, even when no hold was used.
- Frontend: the backtest types gain the two optional fields (`n_time_exits?: number | null`,
  `hold_max_days?: number | null`). Step 6 shows, per candidate, the time exits next to the trade count:
  - `n_time_exits == null` (loose: null or undefined) → `—` for the whole time-exit text, **no hold
    label** (unknown, old row), never `0`;
  - `n_time_exits != null && hold_max_days == null` → `no hold`;
  - otherwise → `3 of 18 on time (hold 15d)`, tooltip "trades closed at the next open after being held
    the horizon's hold, neither stop nor target reached".
  No other column moves. CSS Modules + primitives only (CLAUDE.md conventions).
- Existing test fakes: `test_stock_scan_backtest_commission.py`'s `_fake_bt_result()` is a `MagicMock`;
  once `BacktestOut` reads `n_time_exits` from it, validation fails and `_process_stock` swallows the
  error. Set real ints on that fake (and any other fake `BacktestResult` the suite feeds into
  `BacktestOut`), so those tests still exercise the success path.
- Nothing else: no change to the backtest, the gate, the cache key or any verdict.

**Test first:**

- Backend: the scan (`_process_stock`) and the analysis endpoint return `backtest.n_time_exits` equal to
  the `BacktestResult`'s and `hold_max_days` equal to the hold passed (a Swing request → 15; an
  Intraday/intraday-strategy request → `None` with `n_time_exits` an int); an old `stock-current`
  `StockScanResult` JSON without the fields reloads with both `None`.
- Frontend: Step 6 renders "3 of 18 on time (hold 15d)" for 18 trades / 3 time exits / hold 15;
  "no hold" for `n_time_exits: 0, hold_max_days: null`; "—" and no hold label for
  `n_time_exits: null, hold_max_days: null`; and "—" and no hold label for a fixture with **both fields
  absent** (an old localStorage row).

## Tickets

- **F1** (#129): tests only. Blocked by: none.
- **F2**: backend schema + two constructions + frontend type + Step 6. Blocked by: none. Files are disjoint
  from F1's; still run sequentially (F1 first, so F2's suite runs on a green baseline).
- **Verify, code audit, PR** (coordinator). Blocked by: F1, F2.

## Verification (coordinator)

Backend full suite on Python 3.11 (expected: only the Windows baseline — `test_atomic_yaml` x4,
`test_historical_store_settle::test_19` — and no #129 failures); frontend typecheck + Jest; CI on the PR
fully green on Linux. Live: a Swing `pullback_ema` scan's Step 6 shows a non-zero time-exit count for at
least one candidate when any exists.

## Out of scope

Time exits in the Analysis page, the Position card or the tuner report; any change to the time-exit rule
itself; the Windows-only `test_atomic_yaml` / `test_19` baseline.
