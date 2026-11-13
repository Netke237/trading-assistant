# Code Audit Round 3 Report: `OHLCV-ALPACA-DAY-HOLES`

- **Phase:** `OHLCV-ALPACA-DAY-HOLES` (#535)
- **Branch:** `board/ohlcv-alpaca-day-holes-598af15f`
- **Auditor:** Independent Subagent `b0441900-312e-4938-8e6a-06fcdfe0cd4c` (applying `bmad-review-adversarial-general` under numeric/persistence gate)
- **Reviewed Diff:** `git diff 54c44542..1a295497` (evaluating mock signature compatibility fix and interaction invariants)

---

## Evaluation of Changes & Interaction Analysis

1. **Uniform SIP Feed Invariant & Rule T4 Seam Preservation:**
   - When `client is None` and `feed is None` (default): `feed or "sip"` evaluates to `"sip"`, instantiating `AlpacaClient(..., feed="sip")`. `kwargs` is `{}`, so `client.fetch_raw` is invoked with `feed=None`, which falls back to `self.feed = "sip"` in `_get_bars_page`, sending `"feed": "sip"` to the Alpaca API.
   - When `client` is pre-instantiated via `get_alpaca_client()`: `get_alpaca_client` defaults to `feed="sip"`. In `fetch_daily_bars_batch`, `feed` is `None`, so `kwargs` is `{}`, and `_get_bars_page` resolves `target_feed = self.feed = "sip"`.
   - In all production call sites (`historical_store.py`, `history_backfill.py`, `ingestion_job.py`, `backfill_alpaca_holes.py`), queries continue using Alpaca SIP consolidated tape, preventing venue drops and eliminating the Rule T4 `HistorySeamMismatch` rebuild loop.

2. **Explicit Override (`feed="iex"` or `"sip"`):**
   - When `feed is not None` (e.g. `feed="iex"`), `kwargs = {"feed": "iex"}` is passed to `client.fetch_raw(..., feed="iex")`. `_get_bars_page` sets `target_feed = "iex"`, correctly overriding `self.feed`.

3. **Mock Client Compatibility:**
   - Mock clients (e.g. `AlpacaMockClient`, `MagicMock(spec=AlpacaClient)`) whose `fetch_raw` / `fetch_adj` methods do not accept or expect `feed` kwargs are no longer broken on default invocation paths (`kwargs` is `{}`).

4. **Runtime & Test Verification:**
   - Python runtime: verified 3.11.9.
   - Tests: All 68 tests across `test_alpaca_feed_options.py` and `test_history_adjustment_completeness.py` passed clean.
   - Targeted suite: All 43 tests across `test_alpaca_feed_options.py`, `test_history_gap_detector.py`, `test_backfill_alpaca_holes.py`, and `test_alpaca_adapter.py` passed clean.
   - State: `python scripts/state.py` exited code 0 with 0 drift.
   - Frontend: `npm run typecheck` passed clean (exit code 0).

---

GATE FINDINGS: 0 (CLEAN)
