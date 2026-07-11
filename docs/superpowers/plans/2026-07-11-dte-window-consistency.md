# DTE Window Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close two gaps deferred from the Horizon-Driven DTE plan: the duplicated "resolve `dte_window()`, swallow a misconfigured-multiplier `ValueError`" logic in `contracts.py` and `scan.py`, and `/api/contracts` silently ignoring an inverted `hold_min_days`/`hold_max_days` range instead of rejecting it (unlike `/api/scan`, which 422s via `ScanRequest`'s validator).

**Architecture:** Extract the shared "resolve bounds or fall back on misconfigured multiplier" logic into one helper, `resolve_dte_bounds()`, in `app/scoring/dte_window.py`, and have both routers call it instead of duplicating the try/except. Then add an explicit ordering check to `/api/contracts` that raises a 422 shaped like FastAPI's own `RequestValidationError` response — a list of `{loc, msg, type}` dicts, the same top-level shape `/api/scan` already produces via `ScanRequest`'s `model_validator`, so a client parsing `detail` as a list (not a bare string) works against both. The `loc` values will legitimately differ between the two (`/api/contracts`'s check names the specific query param, `["query", "hold_max_days"]`; `/api/scan`'s model-level `model_validator` names the whole body, `["body"]`, since Pydantic `mode="after"` validators aren't tied to one field) — that's an accurate reflection of one being a query-param check and the other a body-model check, not a defect to paper over. Building the helper first means the 422 fix has a clean call site from the start, no stub/placeholder step needed.

**Tech Stack:** FastAPI (Query params, HTTPException), pytest + `TestClient`, existing `dte_window()` in `backend/app/scoring/dte_window.py`.

---

### Task 1: Centralize dte_window resolution behind `resolve_dte_bounds()`

**Files:**
- Modify: `backend/app/scoring/dte_window.py`
- Modify: `backend/app/routers/contracts.py:45-58` and its `dte_window` import (currently `contracts.py:12`)
- Modify: `backend/app/routers/scan.py:879-898` and its `dte_window` import (currently `scan.py:65`)
- Test: `backend/tests/test_dte_window.py`

- [x] **Step 1: Write the failing test**

Read `backend/tests/test_dte_window.py` first to match its existing style (it currently only tests the raw `dte_window()` function), then add:

```python
def test_resolve_dte_bounds_returns_none_when_hold_days_absent():
    from app.scoring.dte_window import resolve_dte_bounds
    assert resolve_dte_bounds(None, None, lambda: 2.0) is None
    assert resolve_dte_bounds(15, None, lambda: 2.0) is None
    assert resolve_dte_bounds(None, 45, lambda: 2.0) is None


def test_resolve_dte_bounds_returns_window_for_valid_input():
    from app.scoring.dte_window import resolve_dte_bounds
    assert resolve_dte_bounds(15, 45, lambda: 2.0) == (30, 90)


def test_resolve_dte_bounds_falls_back_to_none_on_misconfigured_multiplier():
    from app.scoring.dte_window import resolve_dte_bounds
    assert resolve_dte_bounds(15, 45, lambda: 0.0) is None
    assert resolve_dte_bounds(15, 45, lambda: -1.0) is None


def test_resolve_dte_bounds_falls_back_to_none_when_multiplier_fn_raises():
    """The multiplier source can itself fail to produce a number (e.g. a
    non-numeric value in contract_rules.yaml makes float() raise ValueError) —
    that must degrade the same way a bad-but-numeric multiplier does, not 500."""
    from app.scoring.dte_window import resolve_dte_bounds
    def _broken_multiplier():
        raise ValueError("could not convert string to float: 'oops'")
    assert resolve_dte_bounds(15, 45, _broken_multiplier) is None


def test_resolve_dte_bounds_raises_on_inverted_range():
    """A caller that skips its own ordering check (both current callers already
    reject inverted ranges upstream — see Task 2) must get a loud failure here,
    not a silent None that masks the bad input as 'no override requested'."""
    import pytest
    from app.scoring.dte_window import resolve_dte_bounds
    with pytest.raises(ValueError):
        resolve_dte_bounds(100, 15, lambda: 2.0)
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_dte_window.py -k resolve_dte_bounds -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_dte_bounds'`

- [x] **Step 3: Add the helper to `dte_window.py`**

`backend/app/scoring/dte_window.py` opens with a 14-line module docstring (lines 1-14) followed by a blank line, then the existing `dte_window()` function starting at line 17 — the file has no imports today. Add `import logging` immediately *after* the docstring (i.e. as the new line 16, followed by a blank line), not above it — putting an import before the module docstring would demote that string from `__doc__` to a dead, meaningless expression. Then append the new helper below the existing `dte_window()` function:

```python
_log = logging.getLogger(__name__)


def resolve_dte_bounds(
    hold_min_days: int | None,
    hold_max_days: int | None,
    multiplier_fn,
    *,
    log_context: str = "",
) -> tuple[int, int] | None:
    """Resolve a (min_dte, max_dte) window from hold days, or None if unavailable.

    `multiplier_fn` is a zero-arg callable (typically `dte_holding_multiplier`
    itself, passed uncalled) rather than an already-resolved float. Both the
    call to `multiplier_fn()` and the call to `dte_window()` happen inside the
    same try/except here — in the original duplicated code, resolving the
    multiplier and computing the window were both wrapped by one try/except at
    each call site, so a non-numeric config value (`float()` raising ValueError
    inside `dte_holding_multiplier()`) degraded gracefully exactly like a
    zero/negative multiplier did. Accepting a callable instead of a float
    preserves that: if this took a pre-resolved `multiplier: float` parameter,
    the caller would have to call `multiplier_fn()` itself *before* this
    function, outside any try/except, silently reintroducing a crash path this
    refactor is supposed to remove, not add.

    Returns None when either hold value is missing (no override requested), or
    when resolving the multiplier or computing the window fails (e.g. a
    misconfigured dte_holding_multiplier — 0, negative, or non-numeric — in
    contract_rules.yaml) — callers should fall back to their own
    fetch/validator defaults rather than 500 a request driven by otherwise-valid
    user input.

    Raises ValueError if hold_max_days < hold_min_days. Ordering should already
    be rejected at the API boundary (ScanRequest's model_validator; the explicit
    check added to /api/contracts in Task 2) before this is ever called — this
    raise is a guardrail against a future caller skipping that check, so a bad
    range fails loudly here instead of being silently absorbed into "no override,
    use defaults" the way it was before this plan.
    """
    if hold_min_days is None or hold_max_days is None:
        return None
    if hold_max_days < hold_min_days:
        raise ValueError(f"hold_max_days {hold_max_days} is below hold_min_days {hold_min_days}")
    try:
        return dte_window(hold_min_days, hold_max_days, multiplier_fn())
    except (ValueError, TypeError) as exc:
        _log.error(
            "%sdte_window computation failed, falling back to config defaults: %s",
            f"{log_context} " if log_context else "", exc,
        )
        return None
```

Note the broadened `except (ValueError, TypeError)` — `multiplier_fn()` (i.e. `dte_holding_multiplier()`) does `float(_load_config().get(...))`, and a non-numeric config value (e.g. a YAML list or dict for that key) raises `TypeError`, not `ValueError`, from `float()`. The original per-router try/except blocks only caught `ValueError`, so this is a small, deliberate widening — not a regression — since a `TypeError` from a badly-typed config value should degrade the same way a badly-valued one does.

Note the inverted-order check sits *outside* the `try/except` — only the `dte_window()` call for a misconfigured multiplier is meant to be swallowed. An inverted range is a caller bug, not a config problem, and must propagate.

- [x] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_dte_window.py -k resolve_dte_bounds -v`
Expected: PASS

- [x] **Step 5: Wire `contracts.py` to use the helper (behavior-preserving — no 422 yet)**

In `backend/app/routers/contracts.py`, replace lines 45-58:

```python
    dte_bounds: tuple[int, int] | None = None
    contract_overrides: dict | None = None
    if hold_min_days is not None and hold_max_days is not None and hold_max_days >= hold_min_days:
        try:
            dte_bounds = dte_window(hold_min_days, hold_max_days, dte_holding_multiplier())
            contract_overrides = {
                "min_dte": dte_bounds[0], "max_dte": dte_bounds[1],
                "preferred_dte_min": dte_bounds[0], "preferred_dte_max": dte_bounds[1],
            }
        except ValueError:
            # A misconfigured dte_holding_multiplier (0 or negative in contract_rules.yaml)
            # would otherwise 500 this endpoint. Fall back to the fetch/validator defaults.
            dte_bounds = None
            contract_overrides = None
```

with:

```python
    dte_bounds: tuple[int, int] | None = None
    contract_overrides: dict | None = None
    if hold_min_days is not None and hold_max_days is not None and hold_max_days >= hold_min_days:
        dte_bounds = resolve_dte_bounds(
            hold_min_days, hold_max_days, dte_holding_multiplier,
            log_context="GET /api/contracts",
        )
        if dte_bounds is not None:
            contract_overrides = {
                "min_dte": dte_bounds[0], "max_dte": dte_bounds[1],
                "preferred_dte_min": dte_bounds[0], "preferred_dte_max": dte_bounds[1],
            }
```

Note `dte_holding_multiplier` is passed uncalled (no `()`) — `resolve_dte_bounds` calls it internally, inside its own try/except, so a misconfigured value (0, negative, or non-numeric) degrades gracefully instead of raising here where nothing catches it.

Update the import at `backend/app/routers/contracts.py:12`:

```python
from app.scoring.dte_window import resolve_dte_bounds
```

(the file no longer calls `dte_window(...)` directly after this edit — confirm with a search before removing the old import, in case another line still references it).

- [x] **Step 6: Wire `scan.py` to use the helper**

In `backend/app/routers/scan.py`, replace lines 879-898:

```python
    # ── DTE window from the holding horizon ───────────────────────────────────
    # Absent hold days (e.g. an older client), the fetch/validator defaults apply.
    # ScanRequest's own validator guarantees well-ordered, non-negative hold days,
    # so dte_window() can't raise on user input here — but a misconfigured
    # dte_holding_multiplier (e.g. 0 or negative in contract_rules.yaml) would
    # still raise ValueError, and this runs before the per-symbol task loop, so
    # an unguarded raise here would 500 the whole scan instead of degrading one
    # symbol. Fall back to the fetch/validator defaults rather than crash.
    _dte_bounds: tuple[int, int] | None = None
    _dte_win: DteWindow | None = None
    if req.hold_min_days is not None and req.hold_max_days is not None:
        try:
            _mult = dte_holding_multiplier()
            _dte_bounds = dte_window(req.hold_min_days, req.hold_max_days, _mult)
            _dte_win = DteWindow(min_dte=_dte_bounds[0], max_dte=_dte_bounds[1], multiplier=_mult)
            _log.info("SCAN %s dte_window: %d-%dd (hold %d-%dd x %.1f)",
                      scan_id, _dte_bounds[0], _dte_bounds[1],
                      req.hold_min_days, req.hold_max_days, _mult)
        except ValueError as exc:
            _log.error("SCAN %s dte_window computation failed, falling back to config defaults: %s", scan_id, exc)
```

with:

```python
    # ── DTE window from the holding horizon ───────────────────────────────────
    # Absent hold days (e.g. an older client), the fetch/validator defaults apply.
    # ScanRequest's own validator guarantees well-ordered, non-negative hold days;
    # resolve_dte_bounds() still falls back to None on a misconfigured
    # dte_holding_multiplier rather than raise, since this runs before the
    # per-symbol task loop and an unguarded raise here would 500 the whole scan.
    _dte_bounds: tuple[int, int] | None = None
    _dte_win: DteWindow | None = None
    if req.hold_min_days is not None and req.hold_max_days is not None:
        _dte_bounds = resolve_dte_bounds(
            req.hold_min_days, req.hold_max_days, dte_holding_multiplier,
            log_context=f"SCAN {scan_id}",
        )
        if _dte_bounds is not None:
            # Safe to call dte_holding_multiplier() again here, unguarded: we only
            # reach this branch if resolve_dte_bounds() already called it
            # successfully once inside its own try/except, and _load_config()'s
            # underlying YAML read is cached (see contract_validator.py:42-45), so
            # this second call reads the same cached config and cannot newly fail.
            _mult = dte_holding_multiplier()
            _dte_win = DteWindow(min_dte=_dte_bounds[0], max_dte=_dte_bounds[1], multiplier=_mult)
            _log.info("SCAN %s dte_window: %d-%dd (hold %d-%dd x %.1f)",
                      scan_id, _dte_bounds[0], _dte_bounds[1],
                      req.hold_min_days, req.hold_max_days, _mult)
```

`dte_holding_multiplier` is passed uncalled (no `()`) — same reasoning as the contracts.py wiring above. It stays effectively gated by `if hold_min_days/hold_max_days is not None`, since `resolve_dte_bounds()` returns `None` immediately without calling it when either is absent, exactly matching the original code's behavior of never touching the multiplier config for a scan with no hold-day override. (Round 3's audit flagged that `dte_holding_multiplier()` itself is not `@lru_cache`d — the cache is on the underlying `_load_config()` at `contract_validator.py:42-45` — dte_holding_multiplier() just calls `float()` on the cached config's value each time; the safety argument above rests on `_load_config()`'s caching, not on `dte_holding_multiplier()` being cached directly.)

Update the import at `backend/app/routers/scan.py:65`:

```python
from app.scoring.dte_window import resolve_dte_bounds
```

(the module-level variable names `_dte_bounds`/`_dte_win` are unchanged, so the rest of the function — including the `dte_window=_dte_win` field passed to `ScanResult` further down — needs no further edits. Confirm with a search that no other line in `scan.py` still calls `dte_window(...)` directly before removing the old import.)

- [x] **Step 7: Run the full DTE-related test suites**

Run: `cd backend && python -m pytest tests/test_dte_window.py tests/test_horizon_dte.py -v`
Expected: all PASS — behavior is unchanged at this point, only the implementation moved.

Run: `cd backend && python -m pytest -q`
Expected: no new failures relative to the pre-plan baseline. The suite may have shifted since this plan was written (this is an active branch) — compare against a fresh `git stash && python -m pytest -q && git stash pop` run on the unmodified tree rather than trusting a hardcoded count. As of when this plan was written that baseline was 989 passed, 9 skipped, 1 pre-existing unrelated failure (`test_portfolio_monitor.py::test_master_disabled_skips_all`) — treat that as a sanity reference, not a hard target.

- [x] **Step 8: Commit**

```bash
git add backend/app/scoring/dte_window.py backend/app/routers/contracts.py backend/app/routers/scan.py backend/tests/test_dte_window.py
git commit -m "refactor(scan,contracts): centralize dte_window resolution in resolve_dte_bounds()"
```

---

### Task 2: Reject inverted hold-day ranges in `/api/contracts` with 422

**Files:**
- Modify: `backend/app/routers/contracts.py:45-58` (built on Task 1's `resolve_dte_bounds` call site)
- Test: `backend/tests/test_horizon_dte.py`

- [x] **Step 1: Write the failing test**

Add to `backend/tests/test_horizon_dte.py`, near the other `get_contracts` tests (after `test_get_contracts_falls_back_gracefully_on_misconfigured_multiplier`):

```python
def test_get_contracts_rejects_inverted_hold_range(monkeypatch):
    """Parity with ScanRequest: an inverted range must be a clean 422, not a
    silent fallback to default DTE bounds. Also checks the response body's
    top-level shape matches FastAPI's own validation-error format — `detail`
    is a list of {loc, msg, type} dicts, same as /api/scan's ScanRequest
    model_validator — so a client that parses `detail` as a list (not a bare
    string) works against both endpoints. The `loc` contents legitimately
    differ (this is a query-param check, /api/scan's is a whole-body check) —
    only the list-of-dicts envelope is asserted here, not exact loc equality."""
    monkeypatch.setattr("app.routers.contracts.fetch_option_chain",
                         lambda symbol, option_type="C", dte_bounds=None: [])
    monkeypatch.setattr("app.routers.contracts.fetch_price", lambda symbol: 190.0)
    client = TestClient(app)
    resp = client.get("/api/contracts", params={
        "symbol": "AAPL", "right": "C", "hold_min_days": 100, "hold_max_days": 15,
    })
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, list)
    assert "hold_max_days" in detail[0]["msg"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_horizon_dte.py::test_get_contracts_rejects_inverted_hold_range -v`
Expected: FAIL — current code returns 200 because the `hold_max_days >= hold_min_days` gate silently no-ops on an inverted range instead of raising.

- [x] **Step 3: Add the ordering check**

In `backend/app/routers/contracts.py`, replace the block from Task 1 Step 5:

```python
    dte_bounds: tuple[int, int] | None = None
    contract_overrides: dict | None = None
    if hold_min_days is not None and hold_max_days is not None and hold_max_days >= hold_min_days:
        dte_bounds = resolve_dte_bounds(
            hold_min_days, hold_max_days, dte_holding_multiplier,
            log_context="GET /api/contracts",
        )
        if dte_bounds is not None:
            contract_overrides = {
                "min_dte": dte_bounds[0], "max_dte": dte_bounds[1],
                "preferred_dte_min": dte_bounds[0], "preferred_dte_max": dte_bounds[1],
            }
```

with:

```python
    dte_bounds: tuple[int, int] | None = None
    contract_overrides: dict | None = None
    if hold_min_days is not None and hold_max_days is not None:
        if hold_max_days < hold_min_days:
            raise HTTPException(
                status_code=422,
                detail=[{
                    "loc": ["query", "hold_max_days"],
                    "msg": "Value error, hold_max_days must be >= hold_min_days",
                    "type": "value_error",
                }],
            )
        dte_bounds = resolve_dte_bounds(
            hold_min_days, hold_max_days, dte_holding_multiplier,
            log_context="GET /api/contracts",
        )
        if dte_bounds is not None:
            contract_overrides = {
                "min_dte": dte_bounds[0], "max_dte": dte_bounds[1],
                "preferred_dte_min": dte_bounds[0], "preferred_dte_max": dte_bounds[1],
            }
```

`HTTPException` is already imported at the top of `contracts.py` (`from fastapi import APIRouter, HTTPException, Query`) — no import change needed.

`dte_holding_multiplier` is still passed uncalled here (no `()`), same as Task 1 Step 5's wiring — this block only adds the 422 ordering check above the existing `resolve_dte_bounds(...)` call, it does not touch how the multiplier is passed. If you're implementing Task 2 as a standalone diff against a file that doesn't yet match Task 1's exact output, double-check this call site still passes the bare function reference, not `dte_holding_multiplier()` — passing the called (float) form here makes every `resolve_dte_bounds()` call raise `TypeError: 'float' object is not callable` internally, which the widened `except (ValueError, TypeError)` in Task 1 would silently swallow into `None`, permanently disabling the hold-day override for `/api/contracts` (caught by `test_get_contracts_applies_hold_day_dte_window` in Step 5 below, if that test is actually run — don't skip Step 5 by only running the new Step 1 test in isolation).

- [x] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_horizon_dte.py::test_get_contracts_rejects_inverted_hold_range -v`
Expected: PASS

- [x] **Step 5: Run the full existing hold-day test suite to check for regressions**

Run: `cd backend && python -m pytest tests/test_horizon_dte.py -v`
Expected: all PASS, including `test_get_contracts_applies_hold_day_dte_window`, `test_get_contracts_without_hold_days_keeps_legacy_behaviour`, `test_get_contracts_falls_back_gracefully_on_misconfigured_multiplier`.

Run: `cd backend && python -m pytest -q`
Expected: no new failures relative to Task 1 Step 7's baseline.

- [x] **Step 6: Commit**

```bash
git add backend/app/routers/contracts.py backend/tests/test_horizon_dte.py
git commit -m "fix(contracts): reject inverted hold-day range with 422, matching /api/scan"
```

---

### Task 3: Typecheck and frontend regression check

**Files:** none modified — verification only. This plan is backend-only; the frontend already sanitizes hold days before every call (`sanitizeHoldDays()` in `frontend/lib/horizonPresets.ts:101`, called from both `RunScanButton/index.tsx:169` and `step-6-contracts/page.tsx:87` before every `/api/scan` and `/api/contracts` request), so the new 422 in Task 2 is unreachable from the current UI and is defense-in-depth for other/future callers.

- [x] **Step 1: Confirm frontend is untouched and still passes**

Run: `cd frontend && npm run typecheck`
Expected: clean, no errors (no frontend files were touched).

Run: `cd frontend && npm run test -- --testPathPattern=horizonPresets`
Expected: PASS (`sanitizeHoldDays` behavior is unchanged by this plan).

- [x] **Step 2: No commit needed — verification only**
