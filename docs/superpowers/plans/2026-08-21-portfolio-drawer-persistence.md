# Portfolio Drawer Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist portfolio-drawer edits (stop, structural stop, targets, contract count) to the backend, instead of only mutating local Zustand state that is lost on refresh or overwritten by the next sync.

**Architecture:** Add a `PATCH /api/portfolio/{rec_id}` endpoint that partially updates the four editable columns on `PortfolioPositionModel`. On the frontend, `portfolioStore.updatePosition` keeps its existing synchronous optimistic local update, and additionally schedules a debounced (600ms) PATCH call so rapid keystrokes in the drawer coalesce into one network request instead of one per keystroke. The drawer flushes any pending debounced write immediately when it closes (including when the user switches to editing a different row), so a fast edit-then-navigate never gets silently dropped.

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy (backend), Zustand + fetch (frontend), pytest-asyncio + httpx ASGITransport (backend tests), Jest + fake timers (frontend tests).

---

## Scope

In scope: the four fields the drawer already exposes as editable — `stop`, `structuralStop`, `targets`, `contracts` (→ backend `qty`).

Out of scope, by design:
- **`currentPrice` / `pnlDollar` / `pnlPct`** — the drawer's "Current price" field is documented in its own UI copy as "Manual override — will refresh from broker in live mode." These are live-computed on every `GET /api/portfolio` from a real broker quote; persisting a manual override would just get silently discarded on the next sync anyway, so the PATCH payload never includes them.
- **Full per-field pending-state tracker for the sync poll.** `syncFromBackend`'s 30s poll and a debounced drawer edit can both be in flight at once. Task 3/5 below give this a real (not just documented-away) mitigation: the endpoint re-checks exposure on qty *increases*, and the poll skips overwriting a row that has an unflushed pending edit. What's still not built is a full per-field "this exact value is unconfirmed" tracker (the kind `pending`/`synced` gives whole positions) — that's a materially bigger change than "persist the drawer's edits" calls for, and the mitigations below remove the two concrete failure modes (silent risk-limit bypass, input snapping back mid-keystroke) that would otherwise make the gap actually harmful.

**Risk-gate handling for qty (not out of scope — this was reconsidered during review).** A first draft of this plan treated qty edits as gate-exempt, on the theory that stop/target edits don't need one either. That's a false equivalence: `qty` is exactly the dimension `check_position_risk` exists to police, and the drawer's "Contracts" field has no upper bound (`Math.max(1, Math.round(n))` only floors it). Left ungated, a user could open 1 contract at a trivial exposure, then type an arbitrary number into the drawer and have it persist with zero re-check — a silent, permanent bypass of the exposure cap the POST endpoint enforces at creation. Task 3 therefore re-runs `check_position_risk` whenever a PATCH's `qty` exceeds the position's current stored qty (a *decrease*, e.g. correcting an over-reported fill, does not need it — it can only reduce exposure). This requires the frontend to send `portfolioValue` alongside a qty increase, mirroring what `POST /api/portfolio` already requires (Task 5 Step 1 wires this via the store's existing `accountValue()` helper).

---

## File Structure

- Modify: `backend/app/schemas/__init__.py` — add `PortfolioPositionUpdate` (new class)
- Modify: `backend/app/routers/portfolio.py` — add `PATCH /api/portfolio/{rec_id}` endpoint
- Create: `backend/tests/test_portfolio_update.py` — endpoint tests
- Modify: `frontend/lib/portfolioStore.ts` — debounced remote patch machinery, wired into `updatePosition`/`closePosition`/`closePositionRemote`
- Modify: `frontend/lib/__tests__/portfolioStore.test.ts` — tests for the new behavior
- Modify: `frontend/app/(frame)/portfolio/page.tsx` — flush pending patch when the drawer closes/switches rows; correct the stale "changes stay local" footer copy

---

### Task 1: Backend schema — `PortfolioPositionUpdate`

**Files:**
- Modify: `backend/app/schemas/__init__.py:601-635` (insert after `PortfolioPositionCreate`, before `PortfolioPositionSchema`)

- [ ] **Step 1: Add the schema**

Insert this class immediately after the closing `super().__init__(**mapped)` of `PortfolioPositionCreate` (line 634) and before `class PortfolioPositionSchema(BaseModel):` (line 637):

```python
class PortfolioPositionUpdate(BaseModel):
    """Partial update for a persisted position — only the fields the drawer
    exposes as editable. A field omitted from the request body is left alone;
    the router distinguishes "omitted" from "explicitly null" via
    `model_dump(exclude_unset=True)`, since `{"structuralStop": null}` must
    still be able to clear a previously-set structural stop.

    `qty` IS `Optional[int]` here too (so `{"qty": null}` still validates and
    is tracked in `model_fields_set`, rather than pydantic rejecting it before
    the router ever sees it) — but unlike `stop`/`structuralStop`, there is no
    meaningful "clear the quantity" operation, so the router does NOT treat a
    present-but-null `qty` as a no-op the way it does for those fields. It
    explicitly checks `qty is None or qty < 1` and returns a clean 422 for
    either case — that guard is load-bearing, not redundant, precisely
    because this field's type alone doesn't rule out `None` reaching it.
    `exclude_unset=True` still means an omitted `qty` key never touches this
    field at all.

    `portfolioValue` is only required by the router when `qty` is being
    increased (it re-runs the exposure gate in that case, same as
    `POST /api/portfolio`); a `qty` decrease or an edit that never sends `qty`
    doesn't need it."""
    model_config = ConfigDict(populate_by_name=True)

    stop: Optional[float] = None
    structuralStop: Optional[float] = Field(alias="structural_stop", default=None)
    targets: Optional[list[dict]] = None
    qty: Optional[int] = None
    portfolioValue: Optional[float] = Field(alias="portfolio_value", default=None)
```

- [ ] **Step 2: Confirm it imports cleanly**

Run: `cd backend && python -c "from app.schemas import PortfolioPositionUpdate; print(PortfolioPositionUpdate(stop=1.0).model_dump(exclude_unset=True))"`
Expected output: `{'stop': 1.0}`

---

### Task 2: Backend endpoint — write the failing tests first

**Files:**
- Create: `backend/tests/test_portfolio_update.py`

- [ ] **Step 1: Write the test file**

```python
# backend/tests/test_portfolio_update.py
"""Integration tests for PATCH /api/portfolio/{rec_id} — persists portfolio-drawer
edits (stop, structuralStop, targets, qty) that previously only lived in the
frontend's Zustand store and were lost on refresh.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.routers.portfolio import router as portfolio_router


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c
    await engine.dispose()


async def _add(client, contract="AAPL|185|2026-09-18|C", qty=5, entry=1.00, rec="REC-1",
                stop=None, structural_stop=None, targets=None):
    body = {"recId": rec, "symbol": "AAPL", "contract": contract, "direction": "Bullish",
            "entryPrice": entry, "qty": qty, "entryDate": "2026-05-01",
            "stop": stop, "structuralStop": structural_stop, "targets": targets or [],
            "dteTotal": 140, "portfolioValue": 1_000_000}
    # add_position re-fetches a live premium at save time; stub it away so tests
    # get the submitted values deterministically (same pattern as
    # test_portfolio_close_history.py's `_add` helper).
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_patch_updates_stop(client):
    await _add(client, rec="REC-STOP")
    r = await client.patch("/api/portfolio/REC-STOP", json={"stop": 175.5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stop"] == 175.5
    assert body["qty"] == 5  # untouched


@pytest.mark.asyncio
async def test_patch_updates_structural_stop_and_can_clear_it(client):
    await _add(client, rec="REC-SSTOP", structural_stop=170.0)
    r = await client.patch("/api/portfolio/REC-SSTOP", json={"structuralStop": None})
    assert r.status_code == 200, r.text
    assert r.json()["structuralStop"] is None


@pytest.mark.asyncio
async def test_patch_updates_targets(client):
    await _add(client, rec="REC-TGT")
    new_targets = [{"id": "tp1", "stockPrice": 200.0, "contractsToSell": 2, "status": "PENDING"}]
    r = await client.patch("/api/portfolio/REC-TGT", json={"targets": new_targets})
    assert r.status_code == 200, r.text
    assert r.json()["targets"] == new_targets


@pytest.mark.asyncio
async def test_patch_updates_qty(client):
    await _add(client, rec="REC-QTY", qty=5)
    r = await client.patch("/api/portfolio/REC-QTY", json={"qty": 3})
    assert r.status_code == 200, r.text
    assert r.json()["qty"] == 3


@pytest.mark.asyncio
async def test_patch_rejects_qty_below_one(client):
    await _add(client, rec="REC-QTY0", qty=5)
    r = await client.patch("/api/portfolio/REC-QTY0", json={"qty": 0})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_patch_rejects_qty_null_with_422_not_500(client):
    # Regression: qty is not Optional-shaped the way stop/structuralStop are —
    # explicit null must be a clean 422, not an unhandled TypeError comparing
    # None < 1.
    await _add(client, rec="REC-QTYNULL", qty=5)
    r = await client.patch("/api/portfolio/REC-QTYNULL", json={"qty": None})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_patch_qty_decrease_does_not_require_portfolio_value(client):
    # A decrease only ever reduces exposure, so it skips the risk gate entirely
    # — no portfolioValue needed, and it can't be rejected on exposure grounds.
    await _add(client, rec="REC-QTYDOWN", qty=5)
    r = await client.patch("/api/portfolio/REC-QTYDOWN", json={"qty": 2})
    assert r.status_code == 200, r.text
    assert r.json()["qty"] == 2


@pytest.mark.asyncio
async def test_patch_qty_increase_without_portfolio_value_is_rejected(client):
    await _add(client, rec="REC-QTYUP-NOVAL", qty=1)
    r = await client.patch("/api/portfolio/REC-QTYUP-NOVAL", json={"qty": 2})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_patch_qty_increase_reruns_risk_gate_and_rejects_when_exposure_too_high(client):
    # Proves the exploit this endpoint must NOT allow: open a trivially-small
    # position, then try to inflate it past what the exposure cap would ever
    # have approved at creation. entry=6.00, multiplier=100 (option contract).
    # portfolioValue=10_000 is deliberately above risk_rules.yaml's
    # min_portfolio_value (5_000) — using something below it (e.g. 1_000)
    # would make check_position_risk short-circuit on "portfolio_too_small"
    # before ever reaching the exposure math this test means to exercise, and
    # the 422 would come back for the wrong reason. qty=1 -> capital_at_risk=
    # $600, fine against portfolioValue=1_000_000 at POST time (via `_add`).
    # Increasing to qty=5 against portfolioValue=$10,000 -> capital_at_risk=
    # $3,000 -> 30% single-position exposure, way over the 5%
    # (max_single_position_pct) cap, and too small to reduce-and-approve
    # (max_allowed_premium=$500 / $600-per-contract rounds down to 0) -> hard
    # reject. 30% also exceeds max_total_exposure_pct (25%), so the response
    # detail carries BOTH "single_trade_exposure_too_high" and
    # "total_exposure_limit_reached" — the assertion below only checks the
    # first is present, not that it's the only reason.
    await _add(client, rec="REC-QTYUP-REJECT", qty=1, entry=6.00)
    r = await client.patch(
        "/api/portfolio/REC-QTYUP-REJECT",
        json={"qty": 5, "portfolioValue": 10_000.0},
    )
    assert r.status_code == 422, r.text
    assert "single_trade_exposure_too_high" in r.json()["detail"]
    # The qty must NOT have been silently applied despite the 422.
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)), \
         patch("app.routers.portfolio.fetch_price_async",
               new=AsyncMock(return_value=None)):
        get_r = await client.get("/api/portfolio")
    row = next(p for p in get_r.json() if p["recId"] == "REC-QTYUP-REJECT")
    assert row["qty"] == 1


@pytest.mark.asyncio
async def test_patch_qty_increase_reruns_risk_gate_and_approves_when_exposure_ok(client):
    await _add(client, rec="REC-QTYUP-OK", qty=1, entry=1.00)
    r = await client.patch(
        "/api/portfolio/REC-QTYUP-OK",
        json={"qty": 3, "portfolioValue": 1_000_000.0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["qty"] == 3
    assert r.json().get("adjustedQty") is None  # no soft-reduction happened


@pytest.mark.asyncio
async def test_patch_qty_increase_soft_reduces_and_reports_adjusted_qty(client):
    # Distinct from the hard-reject test above: here the exposure check DOES
    # trigger, but a smaller size still fits, so check_position_risk approves
    # at a reduced size instead of rejecting outright. The PATCH response must
    # surface that (`adjustedQty`), the same way POST /api/portfolio already
    # does via `resp.adjustedQty` — otherwise the drawer shows the qty the
    # user typed while the database quietly holds a smaller one, and the next
    # sync poll would silently snap the input back with zero explanation.
    # entry=2.00, requested qty=5 (at risk_rules.yaml's
    # sizing.max_contracts_per_trade ceiling, so it isn't clamped further) ->
    # capital_at_risk=$1,000 against portfolioValue=$10,000 -> 10% exposure,
    # over the 5% cap -> max_allowed_premium=$500 / $200-per-contract -> 2.
    await _add(client, rec="REC-QTYUP-SOFT", qty=1, entry=2.00)
    r = await client.patch(
        "/api/portfolio/REC-QTYUP-SOFT",
        json={"qty": 5, "portfolioValue": 10_000.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["qty"] == 2
    assert body["adjustedQty"] == 2


@pytest.mark.asyncio
async def test_patch_applies_non_qty_fields_even_when_qty_is_rejected(client):
    # The frontend debounces edits per recId and can merge an unrelated field
    # (Stop) with a qty change into ONE PATCH if both happen within the same
    # ~600ms window. A qty rejection must not take the valid Stop edit down
    # with it — same numbers as the hard-reject test above (entry=6.00,
    # qty 1->5, portfolioValue=$10,000 -> rejected on exposure, see that
    # test's comment for the full math), plus a stop change in the same body.
    await _add(client, rec="REC-COMBINED", qty=1, entry=6.00)
    r = await client.patch(
        "/api/portfolio/REC-COMBINED",
        json={"stop": 175.5, "qty": 5, "portfolioValue": 10_000.0},
    )
    assert r.status_code == 422, r.text

    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)), \
         patch("app.routers.portfolio.fetch_price_async",
               new=AsyncMock(return_value=None)):
        get_r = await client.get("/api/portfolio")
    row = next(p for p in get_r.json() if p["recId"] == "REC-COMBINED")
    # qty rejected and left untouched, but stop still saved.
    assert row["qty"] == 1
    assert row["stop"] == 175.5


@pytest.mark.asyncio
async def test_patch_leaves_unspecified_fields_untouched(client):
    await _add(client, rec="REC-PARTIAL", stop=150.0, structural_stop=148.0, qty=4)
    r = await client.patch("/api/portfolio/REC-PARTIAL", json={"qty": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["qty"] == 2
    assert body["stop"] == 150.0
    assert body["structuralStop"] == 148.0


@pytest.mark.asyncio
async def test_patch_404_for_unknown_rec_id(client):
    r = await client.patch("/api/portfolio/DOES-NOT-EXIST", json={"stop": 100.0})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_empty_body_is_a_noop(client):
    await _add(client, rec="REC-NOOP", stop=150.0)
    r = await client.patch("/api/portfolio/REC-NOOP", json={})
    assert r.status_code == 200, r.text
    assert r.json()["stop"] == 150.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_portfolio_update.py -v`
Expected: every test fails with a 405 (Method Not Allowed) or connection/route error — the PATCH route doesn't exist yet.

---

### Task 3: Backend endpoint — implementation

**Files:**
- Modify: `backend/app/routers/portfolio.py:15-19` (import) and `backend/app/routers/portfolio.py:303-305` (insert point, right after `add_position`, before the `delete_all_history_early` route)

- [ ] **Step 1: Add `PortfolioPositionUpdate`, `orm_positions_to_risk`, and `Optional` to the imports**

`portfolio.py` doesn't import `typing.Optional` today (nothing in the file needed it before this endpoint's `adjusted_qty: Optional[int] = None` local variable). Add it — change:

```python
import asyncio
import uuid
from datetime import date, datetime, timezone
```

to:

```python
import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Optional
```

Change:

```python
from app.services.portfolio_risk import check_position_risk, PortfolioPosition as RiskPosition
```

to:

```python
from app.services.portfolio_risk import check_position_risk, orm_positions_to_risk, PortfolioPosition as RiskPosition
```

and change:

```python
from app.schemas import (
    PortfolioPositionCreate, PortfolioPositionSchema,
    ClosePositionRequest, ClosedPositionSchema,
    PerformanceResponse, PerformancePoint,
)
```

to:

```python
from app.schemas import (
    PortfolioPositionCreate, PortfolioPositionSchema, PortfolioPositionUpdate,
    ClosePositionRequest, ClosedPositionSchema,
    PerformanceResponse, PerformancePoint,
)
```

- [ ] **Step 2: Add the endpoint**

Insert immediately after `add_position`'s closing `return resp` (line 303) and before the `@router.delete('/portfolio/history', ...)` block:

```python
@router.patch('/portfolio/{rec_id}', response_model=PortfolioPositionSchema)
async def update_position(
    rec_id: str,
    body: PortfolioPositionUpdate,
    db: AsyncSession = Depends(get_db),
) -> PortfolioPositionSchema:
    position = (await db.execute(
        select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == rec_id)
    )).scalar_one_or_none()
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Position with rec_id '{rec_id}' not found.")

    # exclude_unset (not exclude_none) so a field the client never sent is left
    # alone, while `{"structuralStop": null}` still clears it — the drawer's
    # "0 means none" control relies on being able to null this back out.
    updates = body.model_dump(exclude_unset=True)
    # Set only when the risk gate approved a qty increase at a SMALLER size
    # than requested — mirrors POST /api/portfolio's resp.adjustedQty below,
    # which exists so a caller is never silently shown a size the backend
    # didn't actually persist.
    adjusted_qty: Optional[int] = None
    # A rejected qty must NOT block stop/structuralStop/targets from saving.
    # The frontend debounces edits per recId and merges whatever fields
    # changed within the same ~600ms window into one PATCH (Task 5) — a user
    # who tweaks Stop and then, moments later, types a Contracts value that
    # fails the exposure gate would otherwise have BOTH edits silently
    # dropped by a single early `raise`, with no indication the valid Stop
    # edit was ever lost. Instead: apply every other field unconditionally,
    # commit, and only raise for qty at the very end — so a qty rejection
    # still reports as a 422 (the frontend must not treat it as success), but
    # the fields that WERE valid are durably saved either way.
    qty_error: Optional[str] = None

    if "qty" in updates:
        qty = updates["qty"]
        if qty is None or qty < 1:
            qty_error = "qty must be an integer of at least 1."
        elif qty > position.qty:
            # Increasing size is new risk, not a correction — re-run the same
            # exposure gate POST /api/portfolio enforces at creation. A decrease
            # only ever reduces exposure, so it skips this gate entirely and
            # doesn't need portfolioValue at all.
            if body.portfolioValue is None:
                qty_error = "portfolioValue is required to increase qty."
            else:
                others = (await db.execute(
                    select(PortfolioPositionModel).where(PortfolioPositionModel.id != position.id)
                )).scalars().all()
                risk = check_position_risk(
                    symbol=position.symbol,
                    contract_id=position.contract,
                    proposed_contracts=qty,
                    entry_premium=position.entry_price,
                    current_price=position.entry_price,
                    portfolio=orm_positions_to_risk(others),
                    portfolio_value=body.portfolioValue,
                )
                if not risk.approved:
                    qty_error = " ".join(risk.reasons)
                else:
                    if risk.adjusted_size is not None:
                        adjusted_qty = risk.adjusted_size
                        qty = risk.adjusted_size
                    position.qty = qty
        else:
            position.qty = qty
    if "stop" in updates:
        position.stop = updates["stop"]
    if "structuralStop" in updates:
        position.structural_stop = updates["structuralStop"]
    if "targets" in updates:
        position.targets = updates["targets"]

    await db.commit()
    await db.refresh(position)

    if qty_error is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=qty_error)

    resp = PortfolioPositionSchema.from_orm_model(position)
    if adjusted_qty is not None:
        resp.adjustedQty = adjusted_qty
    return resp
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_portfolio_update.py -v`
Expected: all 15 tests PASS.

- [ ] **Step 4: Run the full backend portfolio test suite to check for regressions**

Run: `cd backend && python -m pytest tests/test_portfolio_close_history.py tests/test_portfolio_concurrent_add.py tests/test_portfolio_rules.py tests/test_portfolio_missing_column_guard.py -q`
Expected: all passing, same counts as before this change.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/routers/portfolio.py backend/tests/test_portfolio_update.py
git commit -m "feat(portfolio): add PATCH /api/portfolio/{rec_id} to persist drawer edits"
```

---

### Task 4: Frontend store — write the failing tests first

**Files:**
- Modify: `frontend/lib/__tests__/portfolioStore.test.ts` (append a new `describe` block)

- [ ] **Step 1: Add the tests**

Append this block at the end of the `describe('portfolioStore', ...)` body, before its closing `});` (after the existing tests, so it shares the same `beforeEach`/`afterEach`):

```ts
  // Every test below that needs the debounced patch to actually fire uses
  // `await jest.advanceTimersByTimeAsync(600)`, NOT `jest.advanceTimersByTime(600)`
  // followed by a bare `await Promise.resolve()`. The debounced callback chains
  // through `_flushOne` -> `patchPosition`'s `await fetch()` -> `await res.json()`
  // -> the outer `await patchPosition(...)` in `_flushOne` — more microtask turns
  // than a single `Promise.resolve()` unwinds. `advanceTimersByTimeAsync` yields
  // to the event loop after each timer fires, draining that whole chain before
  // the `act()` block returns; using the sync form here would leave assertions
  // that depend on a post-await side effect (e.g. `lastSyncError`) checking state
  // before it actually updates.
  describe('updatePosition persists to the backend', () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });

    afterEach(() => {
      jest.runOnlyPendingTimers();
      jest.useRealTimers();
    });

    it('debounces a PATCH to /api/portfolio/{recId} after inactivity', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-1', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });

      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 185 });
      });
      expect(global.fetch).not.toHaveBeenCalled();

      await act(async () => {
        // The async variant (not sync advanceTimersByTime + one Promise.resolve())
        // — see the note above the first test in this block for why.
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
      expect(url).toContain('/api/portfolio/REC-PATCH-1');
      expect(init.method).toBe('PATCH');
      expect(JSON.parse(init.body)).toEqual({ stop: 185 });
    });

    it('coalesces rapid edits into a single PATCH with the merged fields', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-2', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 185 });
      });
      act(() => {
        jest.advanceTimersByTime(200);
        result.current.updatePosition('AAPL 190C 05/16', { structuralStop: 182 });
      });

      await act(async () => {
        // The async variant (not sync advanceTimersByTime + one Promise.resolve())
        // — see the note above the first test in this block for why.
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [, init] = (global.fetch as jest.Mock).mock.calls[0];
      expect(JSON.parse(init.body)).toEqual({ stop: 185, structuralStop: 182 });
    });

    it('includes portfolioValue when the patch touches contracts (qty), for the backend risk re-check', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-QTY', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { contracts: 3 });
      });

      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [, init] = (global.fetch as jest.Mock).mock.calls[0];
      // portfolioValue: 50000 is set on useRiskStore in the outer beforeEach.
      expect(JSON.parse(init.body)).toEqual({ qty: 3, portfolioValue: 50000 });
    });

    it('does not call the backend for a patch with no persistable fields', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-3', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { currentPrice: 5.5, pnlDollar: 10, pnlPct: 1 });
      });

      await act(async () => {
        // The async variant (not sync advanceTimersByTime + one Promise.resolve())
        // — see the note above the first test in this block for why.
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(global.fetch).not.toHaveBeenCalled();
    });

    it('surfaces lastSyncError when the backend rejects the PATCH', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-4', contract: 'AAPL 190C 05/16', symbol: 'AAPL' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos], lastSyncError: null });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({ detail: 'qty must be at least 1.' }, false, 422));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { contracts: 0 });
      });

      await act(async () => {
        // The async variant (not sync advanceTimersByTime + one Promise.resolve())
        // — see the note above the first test in this block for why.
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(usePortfolioStore.getState().lastSyncError?.detail).toBe('qty must be at least 1.');
      expect(usePortfolioStore.getState().lastSyncError?.symbol).toBe('AAPL');
    });

    it('corrects local contracts and surfaces a notice when the backend soft-reduces a qty increase', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-ADJ', contract: 'AAPL 190C 05/16', contracts: 5 });
      act(() => {
        usePortfolioStore.setState({ positions: [pos], lastSyncError: null });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({ adjustedQty: 2 }));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { contracts: 5 });
      });

      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });

      const updated = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-PATCH-ADJ');
      expect(updated?.contracts).toBe(2);
      expect(usePortfolioStore.getState().lastSyncError?.detail).toContain('2 contracts');
    });

    it('flushPendingPositionPatches sends immediately without waiting for the debounce', async () => {
      const { flushPendingPositionPatches } = await import('@/lib/portfolioStore');
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-5', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 185 });
      });
      expect(global.fetch).not.toHaveBeenCalled();

      await act(async () => {
        flushPendingPositionPatches('REC-PATCH-5');
        await Promise.resolve();
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    it('closePosition cancels a pending patch instead of sending it after the DELETE', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-6', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      const fetchMock = jest.fn().mockResolvedValue(jsonResponse({}));
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 185 });
      });
      act(() => {
        result.current.closePosition('AAPL 190C 05/16');
      });

      await act(async () => {
        // The async variant (not sync advanceTimersByTime + one Promise.resolve())
        // — see the note above the first test in this block for why.
        await jest.advanceTimersByTimeAsync(600);
      });

      // Only the DELETE fired — the debounced PATCH for the same recId was cancelled.
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock.mock.calls[0][1]?.method).toBe('DELETE');
    });
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore`
Expected: the new tests fail (`updatePosition` never calls `fetch`; `flushPendingPositionPatches` is not exported).

---

### Task 5: Frontend store — implementation

**Files:**
- Modify: `frontend/lib/portfolioStore.ts`

- [ ] **Step 1: Add the payload whitelist, PATCH call, and debounce machinery**

Insert this block right after `async function deletePosition(...)` (after line 238, before `function generateRecId()`):

```ts
/** Whitelists the drawer's persistable fields out of an `updatePosition` patch.
 *  `currentPrice`/`pnlDollar`/`pnlPct` are deliberately excluded — they're
 *  live-computed by the backend from a broker quote on every GET, so a manual
 *  override here would just be overwritten by the next sync anyway.
 *
 *  `contracts` (-> `qty`) always carries `portfolioValue` alongside it — the
 *  backend re-runs the exposure gate when a PATCH increases qty (same gate
 *  POST /api/portfolio enforces at creation) and requires it for that check,
 *  the same way the store's own `postPosition` already does for a new order. */
function toUpdatePayload(patch: Partial<PortfolioPosition>): Record<string, unknown> | null {
  const body: Record<string, unknown> = {};
  if ('stop' in patch) body.stop = patch.stop;
  if ('structuralStop' in patch) body.structuralStop = patch.structuralStop;
  if ('targets' in patch) body.targets = patch.targets;
  if ('contracts' in patch) {
    body.qty = patch.contracts;
    body.portfolioValue = accountValue();
  }
  return Object.keys(body).length > 0 ? body : null;
}

async function patchPosition(
  recId: string,
  payload: Record<string, unknown>,
): Promise<{ ok: boolean; detail?: string; adjustedQty?: number }> {
  try {
    const res = await fetch(`${_BASE_URL()}/api/portfolio/${recId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const body = await res.json().catch(() => ({}));
      const adjustedQty = (body as { adjustedQty?: number }).adjustedQty;
      return typeof adjustedQty === 'number' ? { ok: true, adjustedQty } : { ok: true };
    }
    const body = await res.json().catch(() => ({}));
    return { ok: false, detail: (body as { detail?: string }).detail ?? `HTTP ${res.status}` };
  } catch {
    return { ok: false, detail: 'Could not reach the backend — edit was not saved.' };
  }
}

const REMOTE_PATCH_DEBOUNCE_MS = 600;

type PendingPatch = {
  timer: ReturnType<typeof setTimeout>;
  payload: Record<string, unknown>;
  symbol: string;
  contract: string;
};

// Debounces `updatePosition` edits per recId so rapid keystrokes in the drawer
// coalesce into one PATCH instead of one per keystroke. Module-level (not store
// state) — timers are not serializable Zustand state, and this is purely
// network-scheduling plumbing, not UI state.
const _pendingPatches = new Map<string, PendingPatch>();

async function _flushOne(recId: string): Promise<void> {
  const entry = _pendingPatches.get(recId);
  if (!entry) return;
  _pendingPatches.delete(recId);
  const result = await patchPosition(recId, entry.payload);
  if (!result.ok) {
    usePortfolioStore.setState({
      lastSyncError: {
        symbol: entry.symbol,
        contract: entry.contract,
        detail: result.detail ?? 'Edit could not be saved',
        at: Date.now(),
      },
    });
    return;
  }
  if (result.adjustedQty != null) {
    // The backend's exposure gate approved the qty increase at a SMALLER size
    // than requested (mirrors addPosition's own adjustedQty handling above).
    // Correct the local value immediately rather than leaving the drawer show
    // the requested size until the next 30s sync poll silently snaps it back
    // with no explanation — same failure mode Step 4 below prevents for an
    // in-flight edit, but this is a resolved edit the poll would otherwise
    // still be free to overwrite without warning.
    usePortfolioStore.setState((s) => ({
      positions: s.positions.map((p) =>
        p.recId === recId ? { ...p, contracts: result.adjustedQty } : p
      ),
      lastSyncError: {
        symbol: entry.symbol,
        contract: entry.contract,
        detail: `Size reduced to ${result.adjustedQty} contracts to fit your exposure limit.`,
        at: Date.now(),
      },
    }));
  }
}

function scheduleRemotePositionPatch(
  recId: string,
  symbol: string,
  contract: string,
  payload: Record<string, unknown>,
): void {
  const existing = _pendingPatches.get(recId);
  if (existing) clearTimeout(existing.timer);
  const merged = { ...(existing?.payload ?? {}), ...payload };
  const timer = setTimeout(() => { void _flushOne(recId); }, REMOTE_PATCH_DEBOUNCE_MS);
  _pendingPatches.set(recId, { timer, payload: merged, symbol, contract });
}

/** Sends a pending debounced edit immediately instead of waiting out the
 *  debounce window — called when the drawer closes (or switches to editing a
 *  different row) so a fast edit-then-navigate is never silently dropped.
 *  With no `recId`, flushes every pending edit. */
export function flushPendingPositionPatches(recId?: string): void {
  const ids = recId ? [recId] : Array.from(_pendingPatches.keys());
  for (const id of ids) {
    const entry = _pendingPatches.get(id);
    if (!entry) continue;
    clearTimeout(entry.timer);
    void _flushOne(id);
  }
}

/** Drops a pending debounced edit without sending it — used when the position
 *  is being deleted (closePosition/closePositionRemote), so a stale PATCH
 *  never races a DELETE for the same recId. */
function cancelPendingPositionPatch(recId: string): void {
  const entry = _pendingPatches.get(recId);
  if (!entry) return;
  clearTimeout(entry.timer);
  _pendingPatches.delete(recId);
}
```

- [ ] **Step 2: Wire `updatePosition` to schedule the debounced patch**

Replace the existing `updatePosition` action (lines 429-434):

```ts
      updatePosition: (contract, patch) =>
        set((s) => ({
          positions: s.positions.map((r) =>
            r.contract === contract ? { ...r, ...patch } : r
          ),
        })),
```

with:

```ts
      updatePosition: (contract, patch) => {
        // Capture the pre-patch row during the set() updater (the same closure
        // pattern closePosition below already uses), but fire the network side
        // effect AFTER set() returns rather than from inside the updater —
        // every other action in this file (closePosition, addPosition) does
        // its network call after the state update, not inside it.
        let target: PortfolioPosition | undefined;
        set((s) => {
          target = s.positions.find((r) => r.contract === contract);
          return {
            positions: s.positions.map((r) =>
              r.contract === contract ? { ...r, ...patch } : r
            ),
          };
        });
        if (target) {
          const payload = toUpdatePayload(patch);
          if (payload) scheduleRemotePositionPatch(target.recId, target.symbol, target.contract, payload);
        }
      },
```

- [ ] **Step 3: Cancel pending patches on close**

In `closePosition` (around line 435), change:

```ts
      closePosition: (contract) => {
        let closedRecId: string | undefined;
        set((s) => {
          closedRecId = s.positions.find((r) => r.contract === contract)?.recId;
          return { positions: s.positions.filter((r) => r.contract !== contract) };
        });
        if (closedRecId) deletePosition(closedRecId);
      },
```

to:

```ts
      closePosition: (contract) => {
        let closedRecId: string | undefined;
        set((s) => {
          closedRecId = s.positions.find((r) => r.contract === contract)?.recId;
          return { positions: s.positions.filter((r) => r.contract !== contract) };
        });
        if (closedRecId) {
          cancelPendingPositionPatch(closedRecId);
          deletePosition(closedRecId);
        }
      },
```

In `closePositionRemote`'s `run` function (around line 447), add a cancel call as the very first line of `const run = async (): Promise<{ ok: boolean; detail?: string }> => {`:

```ts
        const run = async (): Promise<{ ok: boolean; detail?: string }> => {
          cancelPendingPositionPatch(recId);
          const doClose = async (id: string): Promise<Response> =>
```

- [ ] **Step 4: Don't let the 30s sync poll snap a focused input back to a stale value mid-edit**

`syncFromBackend`'s 30s poll (and the forced re-sync `closePositionRemote` triggers) can land while a debounced edit is still sitting in `_pendingPatches`, waiting out its 600ms window. Every drawer field is a fully-controlled input (`value={position.stop ?? 0}` etc. in `page.tsx`) bound directly to store state, so without this fix the poll's GET response would visibly overwrite whatever the user is mid-typing back to the pre-edit server value — the pending PATCH still eventually fires (it lives independently in `_pendingPatches`, not in `positions`), so no data is lost, but the input would jump under the user's cursor. Skip that: a row with a pending patch keeps showing its current local value across a sync instead of the freshly-fetched one.

Change (in `syncFromBackend`'s inner `run`, right after the GET succeeds):

```ts
            const remote: BackendPosition[] = await res.json();
            const remotePositions = remote.map(fromBackend);
            const remoteContracts = new Set(remotePositions.map((p) => p.contract));
```

to:

```ts
            const remote: BackendPosition[] = await res.json();
            const localForPending = usePortfolioStore.getState().positions;
            const remotePositions = remote.map(fromBackend).map((rp) => {
              if (!_pendingPatches.has(rp.recId)) return rp;
              // An edit for this row is debounced but hasn't reached the
              // backend yet — keep the local value instead of snapping a
              // focused input back to what the server still has.
              return localForPending.find((p) => p.recId === rp.recId) ?? rp;
            });
            const remoteContracts = new Set(remotePositions.map((p) => p.contract));
```

- [ ] **Step 5: Cancel a pending patch when its row is dropped as a phantom**

A synced row that's absent from the backend and was already confirmed before this GET's snapshot is treated as a genuine phantom and silently dropped (see the existing comment `// else: a synced row confirmed before this snapshot...`). If that row happened to have an edit still debounced in `_pendingPatches`, the PATCH would otherwise fire 600ms later against a `rec_id` the frontend just discarded, get a 404, and surface a confusing "Position ... not found" error for a row no longer in the user's list. Cancel it instead.

Change:

```ts
              } else if (typeof p.syncedAt === 'number' && p.syncedAt >= fetchStartedAt) {
                // Confirmed after this GET's snapshot could have been taken — keep
                // (the GET simply predates it); avoids the 30s-poll race dropping it.
                keep.push(p);
              }
              // else: a synced row confirmed before this snapshot but absent from the
              // backend is a genuine phantom (e.g. legacy row, DB reset) — drop it.
```

to:

```ts
              } else if (typeof p.syncedAt === 'number' && p.syncedAt >= fetchStartedAt) {
                // Confirmed after this GET's snapshot could have been taken — keep
                // (the GET simply predates it); avoids the 30s-poll race dropping it.
                keep.push(p);
              } else {
                // A synced row confirmed before this snapshot but absent from the
                // backend is a genuine phantom (e.g. legacy row, DB reset) — drop it,
                // and cancel any edit still debounced for it so a stale PATCH doesn't
                // fire against a rec_id we just forgot.
                cancelPendingPositionPatch(p.recId);
              }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore`
Expected: all tests PASS, including the 8 new ones from Task 4.

- [ ] **Step 7: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean, no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/lib/portfolioStore.ts frontend/lib/__tests__/portfolioStore.test.ts
git commit -m "feat(portfolio): debounce-persist drawer edits to the backend"
```

---

### Task 6: Frontend UI — flush on drawer close/switch, fix stale copy

**Files:**
- Modify: `frontend/app/(frame)/portfolio/page.tsx`

- [ ] **Step 1: Import `flushPendingPositionPatches`**

Change line 16 from:

```ts
import { usePortfolioStore } from '@/lib/portfolioStore';
```

to:

```ts
import { usePortfolioStore, flushPendingPositionPatches } from '@/lib/portfolioStore';
```

- [ ] **Step 2: Flush on unmount inside `EditDrawer`**

`EditDrawer` (starting at line 461) currently opens straight into its returned JSX. Add a cleanup effect so the pending debounced patch is sent immediately whenever this drawer instance goes away — whether via its own close button, or because the parent switched `editing` to a different contract (which unmounts this instance without calling `onClose`). Change:

```tsx
function EditDrawer({
  position,
  onClose,
  onChange,
  onRemove,
}: {
  position: PortfolioPosition;
  onClose: () => void;
  onChange: (patch: Partial<PortfolioPosition>) => void;
  onRemove: () => void;
}) {
  return (
```

to:

```tsx
function EditDrawer({
  position,
  onClose,
  onChange,
  onRemove,
}: {
  position: PortfolioPosition;
  onClose: () => void;
  onChange: (patch: Partial<PortfolioPosition>) => void;
  onRemove: () => void;
}) {
  // Send any debounced-but-not-yet-fired edit immediately when this drawer
  // instance goes away — covers both its own close button and the parent
  // swapping `editing` to a different row (which unmounts this instance
  // without ever calling `onClose`).
  useEffect(() => {
    return () => { flushPendingPositionPatches(position.recId); };
  }, [position.recId]);

  return (
```

- [ ] **Step 3: Fix the stale footer copy**

Change (around line 516-519):

```tsx
      <div className={styles.editFooter}>
        <Text size={11} tone="secondary">
          Changes stay local to this session. Hooking broker write APIs is a Phase 7 task.
        </Text>
```

to:

```tsx
      <div className={styles.editFooter}>
        <Text size={11} tone="secondary">
          Stop, structural stop, targets, and contract count save to your account automatically.
        </Text>
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 5: Manual verification in the browser**

Run: `cd frontend && npm run dev` (localhost:3001), open `/portfolio` with at least one open position.
1. Click the pencil icon to open the edit drawer, change the Stop value, wait ~1 second.
2. In the browser Network tab, confirm a `PATCH /api/portfolio/<recId>` request fired with `{"stop": <value>}`.
3. Reload the page. Confirm the edited stop value is still shown (proves it round-tripped through the backend, not just local state).
4. Edit a value and immediately click the pencil on a different row before the debounce window elapses. Confirm the PATCH for the first row still fires (proves the unmount-flush works).
5. Increase the Contracts field on an existing position by a large amount. Confirm the PATCH body includes `portfolioValue`, and — if it's large enough to exceed the exposure cap in `backend/config/risk_rules.yaml` — confirm the request comes back 422 and the drawer's contract count reverts to the last-saved value on the next sync (proving the risk gate actually runs on the live endpoint, not just in the plan's unit tests).

- [ ] **Step 6: Commit**

```bash
git add "frontend/app/(frame)/portfolio/page.tsx"
git commit -m "fix(portfolio): flush pending drawer edits on close, correct stale local-only copy"
```

---

## Self-Review

**Spec coverage:** The deferred gap was "portfolio-drawer field edits (including `stop` and the new `structuralStop`) aren't persisted to the backend." Task 3 adds the persistence endpoint; Task 5 wires the store to call it for every field the drawer exposes (`stop`, `structuralStop`, `targets`, `contracts`); Task 6 verifies it actually round-trips in the running app. `currentPrice` was intentionally left out — it's documented in the UI itself as a transient override, not a persisted fact.

**Placeholder scan:** No TBD/TODO markers; every step shows the actual code, not a description of it.

**Type consistency:** `toUpdatePayload` output keys (`stop`, `structuralStop`, `targets`, `qty`, `portfolioValue`) match `PortfolioPositionUpdate`'s field names exactly. `flushPendingPositionPatches` and `cancelPendingPositionPatch` names are used identically across Task 5 (definition) and Task 6 (`flushPendingPositionPatches` call site in `page.tsx`).

**Round-1 adversarial audit fixes folded in:** an independent review of this plan (before any code existed) found six issues, all addressed above rather than left as findings against code: (1) qty PATCH originally had no exposure re-check at all — a user could open a trivial position then inflate qty arbitrarily with zero risk gate; Task 1/3 now re-run `check_position_risk` on any qty *increase* and Task 4 has tests proving the reject/approve/decrease-skips-the-gate paths. (2) `qty: null` would have hit an unguarded `qty < 1` comparison and thrown an unhandled 500 instead of a 422; Task 3's endpoint now checks `qty is None` first, and Task 2 has a regression test for it. (3) The original frontend test for a rejected PATCH surfacing `lastSyncError` used `jest.advanceTimersByTime(600)` + a single `await Promise.resolve()`, which doesn't give the `_flushOne` → `patchPosition` → `fetch`/`res.json()` promise chain enough microtask turns to settle before the assertion ran; Task 4 now uses `await jest.advanceTimersByTimeAsync(600)` throughout. (4) The 30s `syncFromBackend` poll landing mid-debounce would have visibly snapped a focused, controlled `<input>` back to the stale server value; Task 5 Step 4 now has the poll skip overwriting a row with a pending patch. (5) A position dropped as a "phantom" during sync could leave a debounced patch to fire 600ms later against a discarded `rec_id`, surfacing a confusing 404; Task 5 Step 5 cancels it. (6) The original `updatePosition` fired its network side effect from inside the Zustand `set()` updater, unlike every other action in the file; Task 5 Step 2 now fires it after `set()` returns, matching `closePosition`'s existing pattern.

**Round-2 adversarial audit fixes folded in:** a second independent review, checking the round-1 fixes rather than re-covering the same ground, confirmed five of six genuinely fixed and found two further issues: (1) the round-1 qty-rejection test used `portfolioValue=1000.0`, which is below `risk_rules.yaml`'s `min_portfolio_value: 5000.0` — the request was rejected, but via the unrelated `portfolio_too_small` short-circuit in `check_position_risk`, not the `single_trade_exposure_too_high` path the test claimed to prove. Task 2's reject test now uses `portfolioValue=10_000.0` (above the floor) with numbers that hand-verifiably reach the intended exposure-reject branch, and asserts on the specific rejection reason. (2) When the risk gate approves a qty increase at a *reduced* size (`adjusted_size` set, not a hard reject), the endpoint was applying that reduced size but never reporting it — unlike `POST /api/portfolio`, which sets `resp.adjustedQty` for exactly this reason (its own schema docstring: so a caller is never silently shown a size that wasn't actually persisted). Left unfixed, a soft-reduced PATCH would return 200, the drawer would keep showing the requested (unpersisted) size, and the next 30s sync poll would silently snap it back once `_flushOne` had already cleared the row from `_pendingPatches` — reintroducing the exact "input snaps back with no explanation" failure mode the round-1 fix (4) exists to prevent, through the one path that fix doesn't cover. Task 3 now mirrors POST's `resp.adjustedQty`; Task 5 Step 1 has the frontend read it and immediately correct the local `contracts` value plus surface a `lastSyncError` notice explaining the reduction; Task 2 and Task 4 each gained a test for the soft-reduction path.

**Post-implementation audit (round 5, against the actual code diff, not the plan text):** after implementing all six tasks, a fifth audit round — a fresh subagent that read every changed file in full and independently re-ran `pytest tests/test_portfolio_update.py` (15 passed), the broader portfolio suite (19 passed, no regressions), `npm run test -- --testPathPattern=portfolioStore` (58 passed), and `npm run typecheck` (clean) — found one issue: `PortfolioPositionUpdate`'s docstring claimed `qty` was "intentionally NOT Optional," which directly contradicted its own `qty: Optional[int] = None` declaration two lines below (faithfully transcribed from an inaccuracy already present in this plan's own Task 1 code block, not introduced during implementation). Not a functional bug — the router's own `qty is None or qty < 1` guard is what actually produces the clean 422, independent of the schema's type — but a real maintenance trap: a future reader trusting the docstring could "simplify away" that router guard as redundant and reintroduce the crash it prevents. Fixed by rewriting the docstring (here and in the implemented code) to correctly describe why `qty` is `Optional` and why the router's guard is load-bearing rather than redundant. No other issues found in this round.

**Round-3 adversarial audit fix folded in:** a third review, hand-verifying the round-2 fixes' arithmetic independently (confirmed both correct) rather than re-trusting the plan's own comments, surfaced one further issue: the frontend debounces and merges *any* fields edited within the same ~600ms window into one PATCH (this is the explicitly-tested `'coalesces rapid edits...'` behavior) — but the original Task 3 endpoint validated `qty` first and `raise`d immediately on a hard rejection, before ever applying `stop`/`structuralStop`/`targets`. A user who edits Stop and then, moments later, types a Contracts value the exposure gate rejects would have BOTH edits silently discarded by one `raise` — not just the invalid qty, but the perfectly valid Stop edit too, with no indication it was ever lost (and no way for the next sync poll to recover it, since `_flushOne` had already cleared the row from `_pendingPatches` by the time the poll ran). Task 3's endpoint now applies every non-qty field unconditionally and defers the qty `raise` to the very end, after `commit()` — a qty rejection still comes back as a 422 (the frontend must not treat it as success), but any other field in the same batch is durably saved regardless. Task 2 gained `test_patch_applies_non_qty_fields_even_when_qty_is_rejected` proving a combined stop+qty PATCH saves the stop even when the qty portion 422s. No new frontend test was needed for this one: the frontend already never rolls back an optimistic edit on a PATCH failure (it only sets `lastSyncError`), so once the backend durably persists the non-qty fields, the existing `syncFromBackend` mitigation (Task 5 Step 4) and the next ordinary poll naturally reconcile — the gap was entirely in the backend silently discarding data it could have kept, not in how the frontend reacts to failure.
