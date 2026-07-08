# yfinance `days` Param Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `fetch_intraday_candles()`'s yfinance leg so it actually respects the caller-supplied `days` parameter instead of always requesting the interval's maximum allowed window (`_YF_MAX_DAYS[...]`), which currently makes `days` silently a no-op for every interval on that leg.

**Architecture:** `market.py:382` calls `_fetch_intraday_yf(symbol, interval=yf_interval, days=yf_max)`, passing the *cap* (`yf_max`) instead of `min(days, yf_max)` (the caller's request, capped). Every current call site in the codebase happens to always request exactly the cap for its interval (e.g. `days=55` for `15min`, `days=730` for `1h`, `days=3650` for `daily`/`weekly`), which is why this bug has gone unnoticed — it's a real, always-triggering defect, just currently benign in practice. Fix the one-line bug and add a regression test using a `days` value smaller than the cap, which is the only case that actually distinguishes correct from buggy behavior.

**Tech Stack:** FastAPI backend, pytest, `unittest.mock.patch`.

---

## File Structure

- Modify: `backend/app/data/market.py:382` — pass `days=min(days, yf_max)` instead of `days=yf_max`.
- Test: `backend/tests/test_market_data_fixes.py` — new tests proving the yfinance leg honors a smaller `days` value, still caps a larger one, and that the `"4h"` interval's pre-existing inner recursive cap still composes correctly with this fix's outer cap.

---

## Task 1: Fix the yfinance leg's `days` argument

**Files:**
- Modify: `backend/app/data/market.py:379-386`
- Test: `backend/tests/test_market_data_fixes.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_market_data_fixes.py`:

```python
def test_yfinance_leg_respects_requested_days_below_cap():
    """fetch_intraday_candles's `days` param must be honored on the yfinance leg —
    previously it always passed the interval's max cap (yf_max), ignoring a smaller
    caller-requested days value. 15min's cap is 55 days; request fewer."""
    from app.data.market import fetch_intraday_candles

    captured_days: list[int] = []

    def _fake_yf(symbol, interval, days):
        captured_days.append(days)
        return [_bar(1_700_000_000)]

    with (
        patch("app.data.market.TRADIER_TOKEN", ""),
        patch("app.data.market._fetch_intraday_yf", side_effect=_fake_yf),
    ):
        result = fetch_intraday_candles("SPY", interval="15min", days=10)

    assert captured_days == [10], f"Expected yfinance to be asked for 10 days, got: {captured_days}"
    assert len(result) > 0


def test_yfinance_leg_still_caps_at_interval_max_when_days_exceeds_it():
    """A caller requesting more days than yfinance supports for the interval must
    still be capped at yf_max (15min's cap is 55 days), not passed through uncapped."""
    from app.data.market import fetch_intraday_candles

    captured_days: list[int] = []

    def _fake_yf(symbol, interval, days):
        captured_days.append(days)
        return [_bar(1_700_000_000)]

    with (
        patch("app.data.market.TRADIER_TOKEN", ""),
        patch("app.data.market._fetch_intraday_yf", side_effect=_fake_yf),
    ):
        result = fetch_intraday_candles("SPY", interval="15min", days=9999)

    assert captured_days == [55], f"Expected cap at 55 days, got: {captured_days}"
    assert len(result) > 0
```

Note: `interval="15min"` is not in `_ibkr_intervals = {"1h", "4h", "daily", "weekly"}`, so IBKR is never attempted for this interval — no IBKR patch is needed for these two tests (unlike the existing `1D`/`1h` tests in this file, which do need to account for IBKR).

Also add a test for the `"4h"` interval, which is the one case where two independent day-caps now compose: the outer fix (`min(days, yf_max)` at line 382, `yf_max=730` for `"4h"`) and `_fetch_intraday_yf`'s own pre-existing internal recursive call for `"4h"` (line 258: `_fetch_intraday_yf(symbol, interval="1h", days=min(days, 730))`, which resamples 1h bars to 4h). Both cap to the same 730-day ceiling today, so this is harmless, but it's untested and worth pinning down explicitly. Test `_fetch_intraday_yf` directly (not the full `fetch_intraday_candles` pipeline) and patch `yfinance.download` globally — the same proven pattern `test_yfinance_fetch_params.py::test_fetch_intraday_yf_uses_period_not_start_end` already uses, which works regardless of `market.py`'s `import yfinance as yf` being a function-local import (patching `app.data.market.yf.download` would NOT work, since that local import never creates a `yf` attribute on the `app.data.market` module itself):

```python
def test_fetch_intraday_yf_4h_recursion_caps_at_730_days():
    """'4h' bars are fetched by a recursive _fetch_intraday_yf(interval='1h', ...)
    call, resampled to 4h afterward (see market.py:257-259). That recursive call's
    own min(days, 730) cap and this fix's outer fetch_intraday_candles-level cap
    both apply for '4h' — confirm the recursion itself still caps at 730 days when
    asked for more (period='2y' per _days_to_yf_period), independent of the outer fix."""
    from app.data.market import _fetch_intraday_yf

    captured_periods: list[str] = []

    def _capture_download(*args, **kwargs):
        captured_periods.append(kwargs.get("period"))
        return pd.DataFrame()  # empty df → _fetch_intraday_yf returns []

    with patch("yfinance.download", side_effect=_capture_download):
        result = _fetch_intraday_yf("SPY", interval="4h", days=9999)

    # Only the recursive '1h' call actually reaches yfinance.download for '4h'
    # (the outer '4h' branch just resamples the 1h result) — its own min(days, 730)
    # must cap 9999 down to 730 days, i.e. period='2y'.
    assert captured_periods == ["2y"], f"Expected the 730-day cap (period='2y'), got: {captured_periods}"
    assert result == []
```

This test needs `import pandas as pd` — the file's current imports (`datetime`, `unittest.mock`, `pytest`) don't include it. Add `import pandas as pd` after the existing `import pytest` line.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_market_data_fixes.py -v -k "yfinance_leg or 4h_recursion"`
Expected: `test_yfinance_leg_respects_requested_days_below_cap` FAILS with `captured_days == [55]` (bug: caller asked for 10, got 55). `test_yfinance_leg_still_caps_at_interval_max_when_days_exceeds_it` and `test_fetch_intraday_yf_4h_recursion_caps_at_730_days` both PASS already (coincidentally / because the `4h` test only exercises the pre-existing, already-correct inner recursive cap, untouched by this fix) — that's expected; they're regression guards for after the fix.

- [ ] **Step 3: Implement**

In `backend/app/data/market.py`, modify line 382 inside `fetch_intraday_candles()`:

Before:
```python
    # ── yfinance (always; extended range for 1h/4h/daily/weekly) ─────────────
    yf_interval = _YF_INTERVAL_MAP.get(interval, interval.replace("min", "m"))
    yf_max = _YF_MAX_DAYS.get(yf_interval, 55)
    yf_rows = _fetch_intraday_yf(symbol, interval=yf_interval, days=yf_max)
```

After:
```python
    # ── yfinance (always; extended range for 1h/4h/daily/weekly) ─────────────
    yf_interval = _YF_INTERVAL_MAP.get(interval, interval.replace("min", "m"))
    yf_max = _YF_MAX_DAYS.get(yf_interval, 55)
    yf_rows = _fetch_intraday_yf(symbol, interval=yf_interval, days=min(days, yf_max))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_market_data_fixes.py -v`
Expected: all tests in the file PASS, including the pre-existing `test_1D_interval_alias_calls_yf_with_1d_and_full_history` (which requests `days=3650` — equal to `1d`'s cap, so `min(3650, 3650) == 3650`, unaffected) and the 3 new tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_data_fixes.py
git commit -m "fix(market): respect the requested days param on the yfinance intraday leg"
```

---

## Final verification

- [ ] `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest -q` — expect all pass, no regressions (in particular, all `test_market_data_fixes.py`, `test_intraday_fetch.py`, and `test_ibkr.py` tests, since they exercise the same function).

## Self-Review Notes

- **Spec coverage:** directly fixes deferred item 7 — the one-line bug at `market.py:382`.
- **No placeholders:** exact before/after code, exact test, exact commands.
- **Why this was previously unnoticed:** every current call site (`composite_watch.py`, `regime.py`, `strategy_watch_evaluator.py`) always passes `days` equal to the interval's own cap, so `days=yf_max` and `days=min(days, yf_max)` produce identical behavior today — this fix only changes behavior for a caller requesting fewer days than the cap, which is exactly what the new tests exercise.
