# Strategy Watch Deferred Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close three gaps deferred from the Strategy Watch Bullish/Bearish direction-picker feature (session of 2026-07-22): direction-blind dedup, loosely-typed direction fields on the API, and a missing strategy option in the Add-a-watch UI.

**Architecture:** Three small changes: (1) `StrategyWatchStore.add_watch` gains `direction` to its duplicate-key check, so the same symbol+strategy can be watched once Bullish and once Bearish; (2) `AddWatch`/`BulkAdd` Pydantic models switch `direction: str` to `direction: Literal["Bullish", "Bearish"]` so the API itself rejects bad values instead of silently storing them; (3) the frontend's `STRATEGIES` list on the Strategy Watch page gains the already-backend-supported `mean_reversion_bb` entry, which today can't be selected from the UI at all.

**Task ordering constraint — read before dispatching:** Task 1 and Task 2 both edit `backend/tests/test_strategy_watch_router.py`. They are **not** independent for execution purposes and must **not** be run in parallel (e.g. via two concurrent subagents) — Task 1 must be fully completed and committed first, then Task 2 edits the file as it exists after Task 1's commit. Task 3 touches only frontend files with no overlap and may run in parallel with either backend task.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 / pytest (backend); TypeScript / React / Next.js (frontend, UI-only change, no test scaffolding exists for this page so verification is manual in-browser).

---

### Task 1: Dedup key includes `direction`

**Files:**
- Modify: `backend/app/services/strategy_watch_store.py:100-103`
- Test: `backend/tests/test_strategy_watch_store.py`
- Test: `backend/tests/test_strategy_watch_router.py`

Today `add_watch` rejects a new watch if `symbol` and `strategy_key` match an existing entry, regardless of `direction`. That means a user can't watch `AAPL` with `pullback_ema` both Bullish and Bearish at the same time — the second call raises `ValueError("AAPL/pullback_ema already watched")` even though the first watch has a different direction. This predates the direction-picker feature (the check just never accounted for the new field).

- [ ] **Step 1: Write the failing tests (store-level)**

In `backend/tests/test_strategy_watch_store.py`, change lines 25-29 (the entire existing `test_add_watch_rejects_duplicate_pair` function) from:

```python
def test_add_watch_rejects_duplicate_pair(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    store.add_watch("AAPL", "pullback_ema")
    with pytest.raises(ValueError, match="already watched"):
        store.add_watch("aapl", "pullback_ema")
```

to (one renamed test made explicit about direction, plus one new test — two functions total replacing the original one):

```python
def test_add_watch_rejects_duplicate_pair_same_direction(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    store.add_watch("AAPL", "pullback_ema", direction="Bullish")
    with pytest.raises(ValueError, match="already watched"):
        store.add_watch("aapl", "pullback_ema", direction="Bullish")


def test_add_watch_allows_same_symbol_strategy_different_direction(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    bullish = store.add_watch("AAPL", "pullback_ema", direction="Bullish")
    bearish = store.add_watch("AAPL", "pullback_ema", direction="Bearish")
    assert bullish["id"] != bearish["id"]
    symbols = {(w["symbol"], w["strategy_key"], w["direction"]) for w in store.list_watches()}
    assert symbols == {("AAPL", "pullback_ema", "Bullish"), ("AAPL", "pullback_ema", "Bearish")}
```

After this edit, `test_add_watch_rejects_duplicate_pair` no longer exists in the file — it has been replaced by these two functions, not supplemented.

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `cd backend && python -m pytest tests/test_strategy_watch_store.py -v`
Expected: `test_add_watch_allows_same_symbol_strategy_different_direction` FAILS with `ValueError: AAPL/pullback_ema already watched` (the second `add_watch` call raises even though direction differs). `test_add_watch_rejects_duplicate_pair_same_direction` PASSES already (behavior unchanged for the same-direction case — it's a rename, not a new scenario).

- [ ] **Step 3: Write the failing test (router-level)**

In `backend/tests/test_strategy_watch_router.py`, `test_add_duplicate_returns_409` ends at line 52, followed by two blank lines (53-54) before `test_bulk_add`'s `@pytest.mark.asyncio` decorator at line 55 — this double-blank-line spacing separates every top-level test function in the file. Insert the new test after line 54 (i.e. after both existing blank lines, immediately before `test_bulk_add`), then add two blank lines after the new function to preserve the same double-blank convention before `test_bulk_add`:

```python
@pytest.mark.asyncio
async def test_add_same_symbol_strategy_different_direction_returns_201(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        bullish = await ac.post("/api/strategy-watch/",
                            json={"symbol": "AAPL", "strategy_key": "ma_crossover", "direction": "Bullish"})
        bearish = await ac.post("/api/strategy-watch/",
                            json={"symbol": "AAPL", "strategy_key": "ma_crossover", "direction": "Bearish"})
    assert bullish.status_code == 201
    assert bearish.status_code == 201
    assert bullish.json()["id"] != bearish.json()["id"]
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_strategy_watch_router.py -v -k test_add_same_symbol_strategy_different_direction_returns_201`
Expected: FAILS — the second POST (`Bearish`) returns 409, so `assert bearish.status_code == 201` fails. This is the current, pre-fix behavior: the dedup check in `add_watch` doesn't yet look at `direction`.

- [ ] **Step 5: Fix the dedup check**

In `backend/app/services/strategy_watch_store.py`, change lines 100-103 from:

```python
        with self._lock:
            for w in self._watches:
                if w["symbol"] == symbol and w["strategy_key"] == strategy_key:
                    raise ValueError(f"{symbol}/{strategy_key} already watched")
```

to:

```python
        with self._lock:
            for w in self._watches:
                if (w["symbol"] == symbol and w["strategy_key"] == strategy_key
                        and w.get("direction", "Bullish") == direction):
                    raise ValueError(f"{symbol}/{strategy_key}/{direction} already watched")
```

Use `.get("direction", "Bullish")` rather than `["direction"]` purely to match the same default already used elsewhere for this field — `load()`'s migration backfill (`w.setdefault("direction", "Bullish")`, line 75) and the Pydantic model defaults added in Task 2 both default to `"Bullish"`. Every entry actually in `self._watches` at runtime already has `direction` set (by `add_watch` itself, by `add_composite_watch`, or by `load()`'s backfill, which always runs before any `add_watch` call is possible) — `.get()` isn't covering a real missing-key case, it's just consistent style with the rest of the codebase's handling of this field.

The router at `backend/app/routers/strategy_watch.py:52-54` only checks `"already watched" in msg` to decide 409 vs 400 — the message still contains that substring, so no router change is needed here.

- [ ] **Step 6: Run store tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_strategy_watch_store.py -v`
Expected: PASS — all tests including the two from Step 1.

- [ ] **Step 7: Run router test to verify it now passes**

Run: `cd backend && python -m pytest tests/test_strategy_watch_router.py -v`
Expected: PASS — all tests including `test_add_same_symbol_strategy_different_direction_returns_201` from Step 3.

- [ ] **Step 8: Run full strategy-watch test files to verify everything passes**

Run: `cd backend && python -m pytest tests/test_strategy_watch_store.py tests/test_strategy_watch_router.py tests/test_strategy_watch_evaluator.py tests/test_strategy_watch_bearish.py -v`
Expected: PASS, all tests.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/strategy_watch_store.py backend/tests/test_strategy_watch_store.py backend/tests/test_strategy_watch_router.py
git commit -m "fix(strategy-watch): dedup watches on symbol+strategy+direction, not just symbol+strategy"
```

---

### Task 2: `direction` fields use `Literal["Bullish", "Bearish"]`

**Files:**
- Modify: `backend/app/routers/strategy_watch.py:3-26`
- Test: `backend/tests/test_strategy_watch_router.py`

`AddWatch.direction` and `BulkAdd.direction` are currently typed as plain `str` with a `"Bullish"` default (lines 16-20 and 23-26). Any other string (`"sideways"`, `"BULLISH"`, `""`) is accepted by Pydantic and stored as-is, then silently misread by everything downstream that compares against exactly `"Bearish"` (e.g. `strategy_watch_evaluator.py`, the frontend pill in `page.tsx:136-138`). Narrowing the type makes FastAPI reject bad values with a 422 at the boundary instead of letting bad data reach the store.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_strategy_watch_router.py`, `test_add_list_remove_roundtrip` ends at line 36 (`assert lst2.json() == []`), followed by two blank lines (37-38) before `test_add_unknown_strategy_returns_400`'s `@pytest.mark.asyncio` decorator at line 39 — the same double-blank convention used throughout this file. Insert both new tests after line 38 (immediately before `test_add_unknown_strategy_returns_400`), with two blank lines between the two new functions and two blank lines after the second one, preserving the convention on both sides:

```python
@pytest.mark.asyncio
async def test_add_watch_rejects_invalid_direction(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post("/api/strategy-watch/",
                            json={"symbol": "AAPL", "strategy_key": "pullback_ema", "direction": "sideways"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_bulk_add_rejects_invalid_direction(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post("/api/strategy-watch/bulk",
                            json={"symbols": ["AAPL"], "strategy_key": "pullback_ema", "direction": "sideways"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_strategy_watch_router.py -v -k invalid_direction`
Expected: FAIL — both return 201 (the store doesn't validate direction, so the bad string is stored as a new watch).

- [ ] **Step 3: Narrow the type**

In `backend/app/routers/strategy_watch.py`, add the import and change lines 3-26 (the file's two header lines — the `# backend/app/routers/strategy_watch.py` path comment and its module docstring — stay untouched above this range) from:

```python
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.strategy_watch_store import strategy_watch_store, VALID_STRATEGIES
from app.services.strategy_watch_scheduler import strategy_watch_scheduler

router = APIRouter(prefix="/api/strategy-watch", tags=["strategy-watch"])


class AddWatch(BaseModel):
    symbol: str
    strategy_key: str
    params_override: dict | None = None
    direction: str = "Bullish"


class BulkAdd(BaseModel):
    symbols: list[str]
    strategy_key: str
    direction: str = "Bullish"
```

to:

```python
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.schemas import Direction
from app.services.strategy_watch_store import strategy_watch_store, VALID_STRATEGIES
from app.services.strategy_watch_scheduler import strategy_watch_scheduler

router = APIRouter(prefix="/api/strategy-watch", tags=["strategy-watch"])


class AddWatch(BaseModel):
    symbol: str
    strategy_key: str
    params_override: dict | None = None
    direction: Direction = "Bullish"


class BulkAdd(BaseModel):
    symbols: list[str]
    strategy_key: str
    direction: Direction = "Bullish"
```

`Direction = Literal['Bullish', 'Bearish']` already exists at `backend/app/schemas/__init__.py:16` (under its "Shared literals" section) and is the codebase's established convention for this exact value — every other router imports shared field types from `app.schemas` rather than redeclaring them locally (e.g. `app/routers/watchlist.py:9`, `app/routers/scan.py:28`), so this reuses it instead of adding a second, redundant `Literal["Bullish", "Bearish"]` definition.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_strategy_watch_router.py -v`
Expected: PASS, all tests including the two new ones and everything from Task 1.

- [ ] **Step 5: Run the full strategy-watch backend suite**

Run: `cd backend && python -m pytest tests/test_strategy_watch_store.py tests/test_strategy_watch_evaluator.py tests/test_strategy_watch_router.py tests/test_strategy_watch_bearish.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/strategy_watch.py backend/tests/test_strategy_watch_router.py
git commit -m "fix(strategy-watch): reject non-Bullish/Bearish direction values at the API boundary"
```

---

### Task 3: Add `mean_reversion_bb` to the Add-a-watch strategy picker

**Files:**
- Modify: `frontend/app/(frame)/strategy-watch/page.tsx:8-13`

The backend already fully supports `mean_reversion_bb` — it's in `VALID_STRATEGIES` (`backend/app/services/strategy_watch_store.py:30`) and wired into the evaluator's `_SIGNAL_FNS` (`backend/app/services/strategy_watch_evaluator.py:35`) — but the frontend's hardcoded `STRATEGIES` list never picked it up, so it can't be selected from either the single-add or bulk-add dropdown, and any existing watch with this `strategy_key` falls back to displaying the raw key instead of a label (see the `?? w.strategy_key` fallback at `page.tsx:134`).

There is no existing test file for this specific page, and no extractable pure function to unit-test the way `step-4-ranking`'s `cardToRow` is tested in `frontend/app/(frame)/screener/step-4-ranking/__tests__/page.test.ts` — this change is a one-line addition to a plain data array rendered straight into JSX, with no logic to isolate. Page-level UI in this codebase is verified manually in those cases, consistent with how the direction-picker feature's own page.tsx change was verified live in-browser rather than with a Jest test. This task follows that same convention: no new test file, manual browser verification instead.

- [ ] **Step 1: Add the strategy entry**

In `frontend/app/(frame)/strategy-watch/page.tsx`, change lines 8-13 from:

```tsx
const STRATEGIES = [
  { key: 'pullback_ema',       label: 'Pullback EMA' },
  { key: 'breakout_base',      label: 'Breakout Base' },
  { key: 'ma_crossover',       label: 'MA Crossover' },
  { key: 'mean_reversion_rsi', label: 'Mean Reversion RSI' },
] as const;
```

to:

```tsx
const STRATEGIES = [
  { key: 'pullback_ema',       label: 'Pullback EMA' },
  { key: 'breakout_base',      label: 'Breakout Base' },
  { key: 'ma_crossover',       label: 'MA Crossover' },
  { key: 'mean_reversion_rsi', label: 'Mean Reversion RSI' },
  { key: 'mean_reversion_bb',  label: 'Mean Reversion BB' },
] as const;
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean, no errors.

- [ ] **Step 3: Manual browser verification**

Start the backend (`cd backend && uvicorn app.main:app --reload --port 8000`) and frontend (`cd frontend && npm run dev`, port 3001), then:
1. Open `/strategy-watch`.
2. Confirm the single-add strategy dropdown now lists "Mean Reversion BB" as the last option.
3. Confirm the bulk-add strategy dropdown also lists it.
4. Add a watch with symbol `AAPL`, strategy "Mean Reversion BB", direction "Bearish". Confirm it appears in the Watched table with the label "Mean Reversion BB" (not the raw key `mean_reversion_bb`) and a red-tinted "Bearish" pill.
5. Reload the page and confirm the watch persists with the correct label.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/strategy-watch/page.tsx"
git commit -m "feat(strategy-watch): add Mean Reversion BB to the Add-a-watch strategy picker"
```

---

## Self-Review Notes

- **Spec coverage:** all three deferred items from the 2026-07-22 handoff are covered — dedup-on-direction (Task 1), `Literal` typing for `direction` (Task 2), missing `mean_reversion_bb` UI entry (Task 3).
- **No placeholders:** every step shows exact before/after code and exact commands.
- **Type consistency:** Task 1's dedup check reads `w.get("direction", "Bullish")`, matching the same default used in `load()`'s migration (`w.setdefault("direction", "Bullish")`) and the Pydantic model defaults from Task 2. Task 3's added key `mean_reversion_bb` matches exactly the string already used in `VALID_STRATEGIES` and `_SIGNAL_FNS` — no renaming drift.
- **Ordering:** Task 1 and Task 2 both edit `backend/tests/test_strategy_watch_router.py` (Task 1 adds one test, Task 2 adds two more). Per the Task ordering constraint stated in the Architecture section, Task 1 must be dispatched and fully committed before Task 2 starts — not run in parallel — so Task 2's edits land on top of Task 1's already-committed file rather than racing it.
- **TDD sequencing:** Task 1 was restructured so both the store-level test (Step 1-2) and the router-level test (Step 3-4) are written and confirmed failing *before* the fix (Step 5) — no step claims a test "fails" after the fix that makes it pass has already landed.
