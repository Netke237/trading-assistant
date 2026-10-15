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
async def client(monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    from app.services import portfolio_risk
    cfg = portfolio_risk._load_config()
    monkeypatch.setattr(portfolio_risk, '_load_config', lambda: {**cfg, 'portfolio': {**cfg['portfolio'], 'portfolio_value': 10000}})
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
                stop=None, structural_stop=None, targets=None, direction="Bullish",
                symbol="AAPL"):
    body = {"recId": rec, "symbol": symbol, "contract": contract, "direction": direction,
            "entryPrice": entry, "qty": qty, "entryDate": "2026-05-01",
            "stop": stop, "structuralStop": structural_stop, "targets": targets or [],
            "dteTotal": 140, "portfolioValue": 1_000_000}
    # add_position re-fetches a live premium at save time; stub it away so tests
    # get the submitted values deterministically (same pattern as
    # test_portfolio_close_history.py's `_add` helper).
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        with patch("app.services.position_writer.account_value", return_value=1_000_000):
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
    like stop/structuralStop: non-positive means unset.

    P6 (G1-5): the price now travels WITH its method, so the floor is pinned on
    the ladder path -- the one method for which a null price is legal. A
    non-ladder method with a non-positive price is refused instead (below)."""
    await _add(client, rec="REC-NEGTP")
    r = await client.patch("/api/portfolio/REC-NEGTP",
                           json={"activeTpMethod": "ladder", "resolvedTpPrice": -50.0})
    assert r.status_code == 200, r.text
    assert r.json()["resolvedTpPrice"] is None


@pytest.mark.asyncio
async def test_patch_coerces_a_zero_resolved_tp_price_to_null(client):
    await _add(client, rec="REC-ZEROTP")
    r = await client.patch("/api/portfolio/REC-ZEROTP",
                           json={"activeTpMethod": "ladder", "resolvedTpPrice": 0})
    assert r.status_code == 200, r.text
    assert r.json()["resolvedTpPrice"] is None


@pytest.mark.asyncio
async def test_patch_updates_resolved_tp_price_when_positive(client):
    await _add(client, rec="REC-POSTP")
    r = await client.patch("/api/portfolio/REC-POSTP",
                           json={"activeTpMethod": "monte_carlo", "resolvedTpPrice": 210.5})
    assert r.status_code == 200, r.text
    assert r.json()["resolvedTpPrice"] == 210.5
    assert r.json()["activeTpMethod"] == "monte_carlo"


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
async def test_patch_qty_increase_without_portfolio_value_uses_server_account(client):
    await _add(client, rec="REC-QTYUP-NOVAL", qty=1, entry=0.50)
    r = await client.patch(
        "/api/portfolio/REC-QTYUP-NOVAL",
        json={"qty": 2, "expectedQty": 1, "addedFillPrice": 0.50},
    )
    assert r.status_code == 200, r.text
    assert r.json()["qty"] == 2
    assert r.json()["entryPrice"] == 0.50


@pytest.mark.asyncio
async def test_patch_qty_increase_over_the_cap_persists_the_full_fill_and_warns(client):
    # A reported fill is indivisible. 5 contracts at 6.00 is $3,000, over both
    # the option single cap and the 25% total cap at the $10,000 account. The
    # row keeps the full quantity and weighted entry, and the response warns.
    await _add(client, rec="REC-QTYUP-REJECT", qty=1, entry=6.00)
    r = await client.patch(
        "/api/portfolio/REC-QTYUP-REJECT",
        json={"qty": 5, "expectedQty": 1, "addedFillPrice": 6.00},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["qty"] == 5
    assert body["entryPrice"] == 6.00
    assert body.get("adjustedQty") is None
    assert "single_trade_exposure_too_high" in body["exposureBreach"]
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)), \
         patch("app.routers.portfolio.fetch_price_async",
               new=AsyncMock(return_value=None)):
        get_r = await client.get("/api/portfolio")
    row = next(p for p in get_r.json() if p["recId"] == "REC-QTYUP-REJECT")
    assert row["qty"] == 5
    assert row["entryPrice"] == 6.00


@pytest.mark.asyncio
async def test_patch_qty_increase_reruns_risk_gate_and_approves_when_exposure_ok(client):
    # 1 @ 0.50 plus 1 @ 1.50 is 2 @ 1.00. Notional 200 is inside the option cap
    # at the fixture's $10,000 account, so this increase is not resized.
    await _add(client, rec="REC-QTYUP-OK", qty=1, entry=0.50)
    r = await client.patch(
        "/api/portfolio/REC-QTYUP-OK",
        json={"qty": 2, "expectedQty": 1, "addedFillPrice": 1.50},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["qty"] == 2
    assert body["entryPrice"] == 1.0
    assert body.get("adjustedQty") is None
    assert not body.get("exposureBreach")


@pytest.mark.asyncio
async def test_patch_qty_increase_that_would_resize_persists_the_full_fill(client):
    # entry=1.50, requested qty=5 -> $750 against the $10,000 account, over the
    # 3.75% option cap. The check would resize to 2. The reported fill is still
    # stored at 5, with a warning and no adjustedQty shrink.
    await _add(client, rec="REC-QTYUP-SOFT", qty=1, entry=1.50)
    r = await client.patch(
        "/api/portfolio/REC-QTYUP-SOFT",
        json={"qty": 5, "expectedQty": 1, "addedFillPrice": 1.50},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["qty"] == 5
    assert body["entryPrice"] == 1.50
    assert body.get("adjustedQty") is None
    assert "size_reduced_to_fit_exposure_limit" in body["exposureBreach"]


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


@pytest.mark.asyncio
async def test_full_fill_scales_rungs_down_to_the_persisted_qty(client):
    # The fill persists all 5, so rungs are capped to that quantity, not to the
    # size the exposure check would have resized to. 6/4 of 10 scales to 3/2.
    await _add(client, rec="REC-QTYUP-RUNGS", qty=1, entry=1.50)
    rungs = [{"stockPrice": 200.0, "contractsToSell": 6}, {"stockPrice": 210.0, "contractsToSell": 4}]
    r = await client.patch(
        "/api/portfolio/REC-QTYUP-RUNGS",
        json={"qty": 5, "expectedQty": 1, "addedFillPrice": 1.50, "targets": rungs},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["qty"] == 5
    assert body.get("adjustedQty") is None
    assert [t["contractsToSell"] for t in body["targets"]] == [3, 2]
    assert [t["stockPrice"] for t in body["targets"]] == [200.0, 210.0]
    stored = next(p for p in (await client.get("/api/portfolio")).json() if p["recId"] == "REC-QTYUP-RUNGS")
    assert stored["qty"] == 5
    assert [t["contractsToSell"] for t in stored["targets"]] == [3, 2]


@pytest.mark.asyncio
async def test_full_fill_leaves_stored_rungs_that_still_fit(client):
    # Rungs not sent with the fill were planned for the pre-fill qty. They fit
    # the persisted 5, so they stay. The cap warning is separate from rungs.
    await _add(client, rec="REC-QTYUP-KEEP", qty=1, entry=1.50,
               targets=[{"stockPrice": 200.0, "contractsToSell": 1}])
    r = await client.patch(
        "/api/portfolio/REC-QTYUP-KEEP",
        json={"qty": 5, "expectedQty": 1, "addedFillPrice": 1.50},
    )
    assert r.status_code == 200, r.text
    assert r.json()["qty"] == 5
    assert r.json().get("adjustedQty") is None
    assert [t["contractsToSell"] for t in r.json()["targets"]] == [1]
    assert r.json()["exposureBreach"]


async def _patch_rungs(client, rec, body):
    r = await client.patch(f"/api/portfolio/{rec}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_full_fill_keeps_rungs_that_fit_the_persisted_qty(client):
    # Rungs typed against the fill total are stored as sent when they fit the
    # persisted quantity. They are not scaled as if the cap had resized it.
    await _add(client, rec="REC-QTYUP-FIT", qty=1, entry=1.50)
    body = await _patch_rungs(client, "REC-QTYUP-FIT", {
        "qty": 5, "expectedQty": 1, "addedFillPrice": 1.50,
        "targets": [{"stockPrice": 200.0, "contractsToSell": 1}, {"stockPrice": 210.0, "contractsToSell": 1}],
    })
    assert body["qty"] == 5
    assert body.get("adjustedQty") is None
    assert [t["contractsToSell"] for t in body["targets"]] == [1, 1]


@pytest.mark.asyncio
async def test_targets_only_patch_selling_more_than_held_is_capped(client):
    # Delta review B1: a rung edit sent on its own (behind a resized raise, or
    # simply over-typed) must not store a plan selling more than is held.
    # 4/4 of 5 held -> 3/2 (ties go to the earlier rung).
    await _add(client, rec="REC-RUNG-OVER", qty=5, entry=1.00)
    body = await _patch_rungs(client, "REC-RUNG-OVER", {
        "targets": [{"stockPrice": 200.0, "contractsToSell": 4}, {"stockPrice": 210.0, "contractsToSell": 4}],
    })
    assert [t["contractsToSell"] for t in body["targets"]] == [3, 2]


@pytest.mark.asyncio
async def test_targets_only_patch_that_fits_is_stored_verbatim(client):
    await _add(client, rec="REC-RUNG-FIT", qty=5, entry=1.00)
    rungs = [{"stockPrice": 200.0, "contractsToSell": 2, "id": "t1"}, {"stockPrice": 210.0, "contractsToSell": 2}]
    body = await _patch_rungs(client, "REC-RUNG-FIT", {"targets": rungs})
    assert body["targets"] == rungs


@pytest.mark.asyncio
async def test_qty_decrease_caps_the_stored_rungs(client):
    await _add(client, rec="REC-QTYDOWN-RUNGS", qty=5, entry=1.00,
               targets=[{"stockPrice": 200.0, "contractsToSell": 3}, {"stockPrice": 210.0, "contractsToSell": 2}])
    body = await _patch_rungs(client, "REC-QTYDOWN-RUNGS", {"qty": 2})
    assert body["qty"] == 2
    assert [t["contractsToSell"] for t in body["targets"]] == [1, 1]


@pytest.mark.asyncio
async def test_rejected_qty_raise_still_caps_the_rungs_sent_with_it(client):
    # The increase is refused (no added-fill price) but the rungs in the same
    # PATCH are saved against the qty actually held (5), not the asked 9.
    await _add(client, rec="REC-QTYREJ-RUNGS", qty=5, entry=1.00)
    r = await client.patch("/api/portfolio/REC-QTYREJ-RUNGS", json={
        "qty": 9, "targets": [{"stockPrice": 200.0, "contractsToSell": 9}],
    })
    assert r.status_code == 422, r.text
    stored = next(p for p in (await client.get("/api/portfolio")).json() if p["recId"] == "REC-QTYREJ-RUNGS")
    assert stored["qty"] == 5
    assert [t["contractsToSell"] for t in stored["targets"]] == [5]


@pytest.mark.asyncio
async def test_full_fill_with_null_targets_clears_them(client):
    await _add(client, rec="REC-QTYUP-NULL", qty=1, entry=1.50,
               targets=[{"stockPrice": 200.0, "contractsToSell": 1}])
    body = await _patch_rungs(client, "REC-QTYUP-NULL", {
        "qty": 5, "expectedQty": 1, "addedFillPrice": 1.50, "targets": None,
    })
    assert body["qty"] == 5
    assert body.get("adjustedQty") is None
    assert body["targets"] == []

@pytest.mark.asyncio
async def test_invalid_account_refuses_create_but_books_placed_order_unchanged(client, monkeypatch):
    from app.services import portfolio_risk
    from app.services.position_writer import create_position
    from app.schemas import PortfolioPositionCreate
    from app.database import get_db
    monkeypatch.setattr(portfolio_risk, '_load_config', lambda: {'portfolio': {'portfolio_value': False}})
    payload = dict(recId='REC-INVALID', symbol='AAPL', contract='AAPL|STOCK', direction='Bullish', entryPrice=100, qty=20, entryDate='2026-05-01', targets=[], portfolioValue=1e12)
    response = await client.post('/api/portfolio', json=payload)
    assert response.status_code == 422
    get_session = client._transport.app.dependency_overrides[get_db]
    async for session in get_session():
        outcome = await create_position(PortfolioPositionCreate(**payload), session, enforce_pre_trade_gates=False)
        assert outcome.position.qty == 20
        assert outcome.over_exposure

@pytest.mark.asyncio
async def test_quantity_decrease_bypasses_invalid_account(client, monkeypatch):
    from app.services import portfolio_risk
    await _add(client, rec='REC-INVALID-DECREASE', qty=5)
    monkeypatch.setattr(portfolio_risk, '_load_config', lambda: {'portfolio': {'portfolio_value': False}})
    response = await client.patch('/api/portfolio/REC-INVALID-DECREASE', json={'qty': 2})
    assert response.status_code == 200
    assert response.json()['qty'] == 2


# ── T8: PATCH has no quote and no stop provenance ────────────────────────────
#
# Entry stays 100. The live quote is not an input. A positive stop is stored
# on either side of that entry, for both directions, including one equal to a
# quote this handler never sees. stopIsUserSet is not an update field.

@pytest.mark.asyncio
async def test_patch_stores_a_positive_stop_with_no_provenance(client):
    await _add(client, contract="ABT|STOCK", qty=1, entry=100.0, rec="REC-BULL-STOP", stop=90.0)
    for stop in (110.0, 120.0, 130.0, 90.0):
        r = await client.patch(
            "/api/portfolio/REC-BULL-STOP",
            json={"stop": stop, "stopIsUserSet": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["stop"] == stop
        assert r.json()["entryPrice"] == 100.0
        assert r.json()["direction"] == "Bullish"

    await _add(
        client, contract="IBM|STOCK", qty=1, entry=100.0, rec="REC-BEAR-STOP",
        stop=110.0, direction="Bearish", symbol="IBM",
    )
    for stop in (90.0, 80.0, 70.0, 110.0):
        r = await client.patch(
            "/api/portfolio/REC-BEAR-STOP",
            json={"stop": stop, "structuralStop": stop},
        )
        assert r.status_code == 200, r.text
        assert (r.json()["stop"], r.json()["structuralStop"]) == (stop, stop)
        assert r.json()["entryPrice"] == 100.0
        assert r.json()["direction"] == "Bearish"


@pytest.mark.asyncio
async def test_patch_floors_zero_negative_and_null_and_leaves_an_omitted_stop(client):
    await _add(
        client, contract="ABT|STOCK", qty=1, entry=100.0, rec="REC-FLOOR-STOP",
        stop=110.0, structural_stop=115.0,
    )
    r = await client.patch("/api/portfolio/REC-FLOOR-STOP", json={"stop": 0, "structuralStop": 0})
    assert r.status_code == 200, r.text
    assert (r.json()["stop"], r.json()["structuralStop"]) == (None, None)

    r = await client.patch("/api/portfolio/REC-FLOOR-STOP", json={"stop": -5, "structuralStop": -1})
    assert r.status_code == 200, r.text
    assert (r.json()["stop"], r.json()["structuralStop"]) == (None, None)

    r = await client.patch("/api/portfolio/REC-FLOOR-STOP", json={"stop": 110.0, "structuralStop": 115.0})
    assert r.status_code == 200, r.text
    r = await client.patch("/api/portfolio/REC-FLOOR-STOP", json={"stop": None})
    assert r.status_code == 200, r.text
    assert r.json()["stop"] is None
    assert r.json()["structuralStop"] == 115.0

    r = await client.patch("/api/portfolio/REC-FLOOR-STOP", json={})
    assert r.status_code == 200, r.text
    assert r.json()["stop"] is None
    assert r.json()["structuralStop"] == 115.0
    assert r.json()["entryPrice"] == 100.0
