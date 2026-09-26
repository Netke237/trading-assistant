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
async def test_patch_coerces_a_zero_stop_to_null_instead_of_persisting_it(client):
    """Round-2 audit finding: the drawer's Stop field had no floor, unlike its
    structuralStop sibling. A stock price is never <= 0, so a stop of 0 can
    only mean a cleared-but-unfinished edit (e.g. flushed on drawer unmount
    mid-retype) — persisting it verbatim would leave both alert engines'
    `stop is not None` gate treating a Bearish position as permanently
    breached (referencePrice >= 0 is true for any real price)."""
    await _add(client, rec="REC-ZEROSTOP", stop=150.0)
    r = await client.patch("/api/portfolio/REC-ZEROSTOP", json={"stop": 0})
    assert r.status_code == 200, r.text
    assert r.json()["stop"] is None


@pytest.mark.asyncio
async def test_patch_coerces_a_negative_resolved_tp_price_to_null(client):
    """Round-8 audit finding: resolvedTpPrice was the one price field on this
    endpoint persisted raw, unlike stop/structuralStop above. generate_alerts()'s
    TP_HIT check only special-cased 0 (`resolved_tp_price or ladder_price`,
    Python truthiness), never negative — so a negative value here made TP_HIT
    fire on every single tick for a Bullish position (price >= negative is
    always true) and never fire at all for a Bearish one. Now floored exactly
    like stop/structuralStop: non-positive means unset."""
    await _add(client, rec="REC-NEGTP")
    r = await client.patch("/api/portfolio/REC-NEGTP", json={"resolvedTpPrice": -50.0})
    assert r.status_code == 200, r.text
    assert r.json()["resolvedTpPrice"] is None


@pytest.mark.asyncio
async def test_patch_coerces_a_zero_resolved_tp_price_to_null(client):
    await _add(client, rec="REC-ZEROTP")
    r = await client.patch("/api/portfolio/REC-ZEROTP", json={"resolvedTpPrice": 0})
    assert r.status_code == 200, r.text
    assert r.json()["resolvedTpPrice"] is None


@pytest.mark.asyncio
async def test_patch_updates_resolved_tp_price_when_positive(client):
    await _add(client, rec="REC-POSTP")
    r = await client.patch("/api/portfolio/REC-POSTP", json={"resolvedTpPrice": 210.5})
    assert r.status_code == 200, r.text
    assert r.json()["resolvedTpPrice"] == 210.5


@pytest.mark.asyncio
async def test_patch_updates_structural_stop_and_can_clear_it(client):
    await _add(client, rec="REC-SSTOP", structural_stop=170.0)
    r = await client.patch("/api/portfolio/REC-SSTOP", json={"structuralStop": None})
    assert r.status_code == 200, r.text
    assert r.json()["structuralStop"] is None


@pytest.mark.asyncio
async def test_patch_updates_max_loss_override_and_can_clear_it(client):
    """Feature C (exit-plan pipeline plan, docs/superpowers/plans/
    2026-08-26-exit-plan-pipeline.md) — per-position override of the global
    max-loss-per-trade warning threshold. Same exclude_unset/explicit-null
    pattern as structuralStop above: PATCHing null must clear a previously
    set override, not be treated as "field omitted"."""
    await _add(client, rec="REC-MAXLOSS")
    override = {"mode": "dollar", "value": 300}
    r = await client.patch("/api/portfolio/REC-MAXLOSS", json={"maxLossOverride": override})
    assert r.status_code == 200, r.text
    assert r.json()["maxLossOverride"] == override

    r2 = await client.patch("/api/portfolio/REC-MAXLOSS", json={"maxLossOverride": None})
    assert r2.status_code == 200, r2.text
    assert r2.json()["maxLossOverride"] is None


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


# ── STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES (plan A6 T-A8, R3, Q3 T-A8b) ─────

async def _add_stock(client, rec, qty, stop, entry=50.0):
    body = {"recId": rec, "symbol": rec, "contract": f"{rec}|STOCK", "direction": "Bullish",
            "entryPrice": entry, "qty": qty, "entryDate": "2026-09-26", "stop": stop,
            "targets": [], "dteTotal": 0, "portfolioValue": 1_000_000}
    with patch("app.routers.portfolio.fetch_contract_quote_async", new=AsyncMock(return_value=None)), \
         patch("app.routers.portfolio.fetch_price_async", new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text


async def _stored(client, rec):
    with patch("app.routers.portfolio.fetch_contract_quote_async", new=AsyncMock(return_value=None)), \
         patch("app.routers.portfolio.fetch_price_async", new=AsyncMock(return_value=None)):
        rows = (await client.get("/api/portfolio")).json()
    return next(p for p in rows if p["recId"] == rec)


@pytest.mark.asyncio
async def test_a8_a_stock_qty_raise_is_judged_at_its_stored_stop(client):
    # 100 @ 50, stop 49. Raise to 1000: $1,000 at risk = 1% of 100k -> approved
    # in full. At notional ($50,000 = 50%) it would have been resized to 100.
    await _add_stock(client, "SRA", 100, 49.0)
    r = await client.patch("/api/portfolio/SRA", json={"qty": 1000, "portfolioValue": 100_000.0})
    assert r.status_code == 200, r.text
    assert r.json()["qty"] == 1000


@pytest.mark.asyncio
async def test_a8_same_patch_stop_clear_is_judged_at_notional(client):
    # R3: {qty: 1000, stop: null} in ONE patch is judged against the stop it
    # stores (none -> notional): resized to 100, the current size.
    await _add_stock(client, "SRB", 100, 49.0)
    r = await client.patch("/api/portfolio/SRB",
                           json={"qty": 1000, "stop": None, "portfolioValue": 100_000.0})
    assert r.status_code == 200, r.text
    row = await _stored(client, "SRB")
    assert (row["qty"], row["stop"]) == (100, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", [None, 40.0])
async def test_a8b_a_qty_raise_never_shrinks_the_row(client, stop):
    # Q3: 1000 @ 50, stop 49 (1%). Raise to 1001 while clearing the stop
    # (notional 50% -> resize 100) or widening it to 40 ($10 x 1001 = 10% ->
    # resize 500): both resizes are BELOW the 1000 the broker holds.
    rec = "SRC" if stop is None else "SRD"
    await _add_stock(client, rec, 1000, 49.0)
    r = await client.patch(f"/api/portfolio/{rec}",
                           json={"qty": 1001, "stop": stop, "portfolioValue": 100_000.0})
    assert r.status_code == 422, r.text
    assert "qty left unchanged" in r.text
    assert (await _stored(client, rec))["qty"] == 1000
