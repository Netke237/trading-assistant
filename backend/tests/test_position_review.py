"""#582 TC-REVIEW-07 -- review and confirm the exact basket tracking values.

A preview runs the SAME resolution as the create (`position_writer`'s one
resolve-and-book path) and stops before anything is written: no position, no
exposure hold transfer, no approval, no commit. Its exposure-guard write is
rolled back in its own isolated session.

A confirmation carries the reviewed fingerprint in `X-Review-Fingerprint`. The
create re-resolves everything (live quote, re-anchor, exposure check, premium
stop, effective TP) under the booking/exposure lock and compares BEFORE any
transfer/add/commit; a material difference answers 412 `review_required` with
the new preview and writes nothing. A request without the header is today's
create, unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.models.audit_event import AuditEventModel
from app.models.broker_attempt import ExposureGuard, ExposureHold
from app.models.portfolio import PortfolioPositionModel
from app.routers.portfolio import router as portfolio_router
from app.schemas import PortfolioPositionCreate
from app.services.portfolio_risk import RiskCheckResult
from app.services.position_writer import (
    PositionPreview, ReviewRequired, create_position, preview_position,
)

HEADER = "X-Review-Fingerprint"


@pytest.fixture(autouse=True)
def _account(monkeypatch):
    from app.services import portfolio_risk
    config = deepcopy(portfolio_risk._load_config())
    config.setdefault("portfolio", {})["portfolio_value"] = 1_000_000
    monkeypatch.setattr(portfolio_risk, "_load_config", lambda: config)


@pytest.fixture(autouse=True)
def _global_premium_stop(monkeypatch):
    monkeypatch.setattr("app.services.position_writer._global_premium_stop_pct", lambda: 0.60)


@pytest_asyncio.fixture
async def Maker(tmp_path):
    """File-backed, so two sessions are two real connections."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'review.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield maker
    await engine.dispose()


def _body(**overrides) -> dict:
    body = {
        "recId": "REC-R1", "symbol": "ABT", "contract": "ABT|97|2027-01-15|C",
        "direction": "Bullish", "entryPrice": 10.45, "qty": 4,
        "entryDate": "2026-07-17", "stop": 89.89, "structuralStop": 88.0,
        "targets": [{"stockPrice": 110.0, "targetPrice": 110.0, "contractsToSell": 2}],
        "dteTotal": 547, "scanStockPrice": 100.0,
        "tradeCardSnapshot": {"symbol": "ABT", "note": "record only"},
    }
    body.update(overrides)
    return body


class Market:
    """The two live fetches, changeable between preview and confirm."""

    def __init__(self, premium=10.80, underlying=101.0):
        self.premium = premium
        self.underlying = underlying

    async def quote(self, _client, _contract):
        return {"price": self.premium, "spread": 0.10}

    async def price(self, _client, _symbol):
        return self.underlying


async def _counts(maker) -> dict:
    async with maker() as db:
        out = {}
        for model in (PortfolioPositionModel, ExposureGuard, ExposureHold, AuditEventModel):
            out[model.__tablename__] = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        return out


def _app(maker) -> FastAPI:
    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with maker() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    return test_app


def _patched(market: Market, rr_ratios=(1.0, 2.0)):
    cfg = {"target": {"rr_ratios": list(rr_ratios)}}
    return (
        patch("app.routers.portfolio.fetch_contract_quote_async", new=market.quote),
        patch("app.routers.portfolio.fetch_price_async", new=market.price),
        patch("app.routers.portfolio.load_exit_plan_cfg", new=lambda: cfg),
    )


async def _post(maker, market, path, body, *, headers=None, rr_ratios=(1.0, 2.0), log=None):
    p1, p2, p3 = _patched(market, rr_ratios)
    approval = log or AsyncMock()
    with p1, p2, p3, patch("app.routers.portfolio.log_approval", new=approval):
        async with AsyncClient(transport=ASGITransport(app=_app(maker)), base_url="http://t") as c:
            return await c.post(path, json=body, headers=headers or {})


# ── preview writes nothing ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_writes_nothing_and_releases_its_guard(Maker):
    before = await _counts(Maker)
    approval = AsyncMock()
    r = await _post(Maker, Market(), "/api/portfolio/preview", _body(), log=approval)
    assert r.status_code == 200, r.text
    assert await _counts(Maker) == before == {
        "portfolio_positions": 0, "exposure_guards": 0, "exposure_holds": 0, "audit_events": 0,
    }, "the guard row lock_exposure inserted must be rolled back with the preview"
    approval.assert_not_awaited()
    preview = r.json()
    assert preview["fingerprint"].startswith("v1:")
    # The complete resolved position, from the writer's own resolution.
    pos = preview["position"]
    assert pos["entryPrice"] == 10.80          # save-time live quote
    assert pos["qty"] == 4
    assert pos["stop"] == 90.89                # generated stop re-anchored by +1.00
    assert pos["structuralStop"] == 89.0
    assert pos["targets"][0]["stockPrice"] == 111.0
    assert pos["activeTpMethod"] == "ladder" and pos["resolvedTpPrice"] is None
    assert preview["entryFromLiveQuote"] is True
    assert preview["inheritedPremiumStopPct"] == 0.60
    fields = {d["field"]: d for d in preview["differences"]}
    assert fields["entryPrice"]["requested"] == 10.45 and fields["entryPrice"]["effective"] == 10.80
    assert fields["stop"]["reason"] == "reanchored"
    assert "qty" not in fields


@pytest.mark.asyncio
async def test_preview_never_calls_transfer_hold_or_commit(Maker):
    """Called directly on its own session. A session that commits or transfers
    a hold would fail this test even if it rolled back afterwards."""
    market = Market()
    with (
        patch("app.services.position_writer.transfer_hold", new=AsyncMock()) as hold,
        patch.object(AsyncSession, "commit", new=AsyncMock(side_effect=AssertionError("preview committed"))),
    ):
        async with Maker() as db:
            preview = await preview_position(
                PortfolioPositionCreate(**_body()), db,
                quote_fetcher=market.quote, price_fetcher=market.price,
                exit_plan_cfg_loader=lambda: {},
            )
            assert len(db.sync_session.new) == 0 and not db.in_transaction()
    hold.assert_not_awaited()
    assert isinstance(preview, PositionPreview)
    assert preview.position.id is None, "the preview's row is transient, never flushed"
    assert (await _counts(Maker))["portfolio_positions"] == 0


@pytest.mark.asyncio
async def test_preview_refuses_a_shared_session_and_leaves_its_work_alone(Maker):
    """A preview rolls back. It must never do that to a caller's transaction."""
    market = Market()
    async with Maker() as db:
        db.add(PortfolioPositionModel(
            rec_id="REC-CALLER", symbol="ZZZ", contract="ZZZ|1|2027-01-15|C",
            direction="Bullish", entry_price=2.0, qty=1, entry_date="2026-07-17"))
        with pytest.raises(ValueError, match="its own session"):
            await preview_position(
                PortfolioPositionCreate(**_body()), db,
                quote_fetcher=market.quote, price_fetcher=market.price,
                exit_plan_cfg_loader=lambda: {},
            )
        assert len(db.sync_session.new) == 1, "the caller's pending row is untouched"
        await db.commit()
    async with Maker() as db:
        await db.execute(select(PortfolioPositionModel))   # a transaction with only a read
        with pytest.raises(ValueError, match="its own session"):
            await preview_position(
                PortfolioPositionCreate(**_body(recId="REC-R2", contract="ABT|98|2027-01-15|C")), db,
                quote_fetcher=market.quote, price_fetcher=market.price,
                exit_plan_cfg_loader=lambda: {},
            )
    counts = await _counts(Maker)
    assert counts["portfolio_positions"] == 1 and counts["exposure_guards"] == 0


# ── confirmation parity ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unchanged_inputs_confirm_exactly_the_previewed_row(Maker):
    market = Market()
    preview = (await _post(Maker, market, "/api/portfolio/preview", _body())).json()
    approval = AsyncMock()
    r = await _post(Maker, market, "/api/portfolio", _body(),
                    headers={HEADER: preview["fingerprint"]}, log=approval)
    assert r.status_code == 201, r.text
    saved = r.json()
    for key in ("entryPrice", "qty", "stop", "structuralStop", "targets", "premiumStopPct",
                "activeTpMethod", "resolvedTpPrice", "exitPlan", "pickedMethod", "dteTotal"):
        assert saved[key] == preview["position"][key], key
    approval.assert_awaited_once()     # the approval belongs to the confirmation only
    async with Maker() as db:
        [row] = (await db.execute(select(PortfolioPositionModel))).scalars().all()
    assert (row.entry_price, row.qty, row.stop) == (10.80, 4, 90.89)


@pytest.mark.asyncio
async def test_a_preview_is_repeatable(Maker):
    market = Market()
    a = (await _post(Maker, market, "/api/portfolio/preview", _body())).json()
    b = (await _post(Maker, market, "/api/portfolio/preview", _body(tradeCardSnapshot={"x": 2}))).json()
    assert a["fingerprint"] == b["fingerprint"], "the record-only snapshot is not material"
    c = (await _post(Maker, market, "/api/portfolio/preview",
                     _body(recId="REC-OTHER", entryDate="2026-07-18"))).json()
    assert c["fingerprint"] == a["fingerprint"], "ids and stamps are not material"
    d = (await _post(Maker, market, "/api/portfolio/preview", _body(qty=5))).json()
    assert d["fingerprint"] != a["fingerprint"]


# ── changes between preview and confirm: review required, nothing written ─


async def _assert_review_required(Maker, r, old_fingerprint, before):
    assert r.status_code == 412, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "review_required"
    assert detail["preview"]["fingerprint"] != old_fingerprint
    assert await _counts(Maker) == before, "no position, hold, guard or approval written"
    return detail["preview"]


@pytest.mark.asyncio
async def test_a_quote_change_requires_review_and_writes_nothing(Maker):
    market = Market()
    preview = (await _post(Maker, market, "/api/portfolio/preview", _body())).json()
    before = await _counts(Maker)
    market.premium = 11.20
    approval = AsyncMock()
    r = await _post(Maker, market, "/api/portfolio", _body(),
                    headers={HEADER: preview["fingerprint"]}, log=approval)
    fresh = await _assert_review_required(Maker, r, preview["fingerprint"], before)
    assert fresh["position"]["entryPrice"] == 11.20, "the new preview is current, never the frozen one"
    approval.assert_not_awaited()
    # Confirming the NEW review succeeds at the new value.
    r2 = await _post(Maker, market, "/api/portfolio", _body(), headers={HEADER: fresh["fingerprint"]})
    assert r2.status_code == 201 and r2.json()["entryPrice"] == 11.20


@pytest.mark.asyncio
async def test_an_underlying_move_requires_review_for_a_generated_stop(Maker):
    market = Market()
    preview = (await _post(Maker, market, "/api/portfolio/preview", _body())).json()
    before = await _counts(Maker)
    market.underlying = 103.0
    r = await _post(Maker, market, "/api/portfolio", _body(), headers={HEADER: preview["fingerprint"]})
    fresh = await _assert_review_required(Maker, r, preview["fingerprint"], before)
    assert fresh["position"]["stop"] == 92.89


@pytest.mark.asyncio
async def test_a_capacity_change_requires_review_and_writes_nothing(Maker):
    market = Market()
    preview = (await _post(Maker, market, "/api/portfolio/preview", _body())).json()
    before = await _counts(Maker)
    resized = RiskCheckResult(approved=True, adjusted_size=2)
    with patch("app.services.position_writer.check_position_risk", return_value=resized):
        r = await _post(Maker, market, "/api/portfolio", _body(), headers={HEADER: preview["fingerprint"]})
    fresh = await _assert_review_required(Maker, r, preview["fingerprint"], before)
    assert fresh["position"]["qty"] == 2 and fresh["adjustedQty"] == 2
    assert fresh["position"]["targets"][0]["contractsToSell"] == 2


@pytest.mark.asyncio
async def test_a_refusal_at_confirm_stays_a_refusal(Maker):
    """Current risk checks are never waived to match a review."""
    market = Market()
    preview = (await _post(Maker, market, "/api/portfolio/preview", _body())).json()
    refused = RiskCheckResult(approved=False, reasons=["total_exposure_limit_reached"])
    with patch("app.services.position_writer.check_position_risk", return_value=refused):
        r = await _post(Maker, market, "/api/portfolio", _body(), headers={HEADER: preview["fingerprint"]})
    assert r.status_code == 422 and r.json()["detail"] == "total_exposure_limit_reached"
    assert (await _counts(Maker))["portfolio_positions"] == 0


@pytest.mark.asyncio
async def test_a_tp_default_change_requires_review(Maker):
    """An Arithmetic pick whose plan rows do not all carry a ratio maps through
    the configured rr_ratios -- the inherited default."""
    plan = {"targets": [{"price": 160.0, "rrRatio": 2.0}, {"price": 170.0}]}
    body = _body(pickedMethod="arithmetic", pickedRowStockPrice=160.0, exitPlan=plan)
    market = Market()
    preview = (await _post(Maker, market, "/api/portfolio/preview", body, rr_ratios=(1.0, 2.0))).json()
    assert preview["position"]["activeTpMethod"] == "exit_plan_3r"
    before = await _counts(Maker)
    r = await _post(Maker, market, "/api/portfolio", body,
                    headers={HEADER: preview["fingerprint"]}, rr_ratios=(2.0, 3.0))
    fresh = await _assert_review_required(Maker, r, preview["fingerprint"], before)
    assert fresh["position"]["activeTpMethod"] == "exit_plan_2r"


@pytest.mark.asyncio
async def test_an_inherited_premium_stop_default_change_requires_review(Maker, monkeypatch):
    market = Market()
    preview = (await _post(Maker, market, "/api/portfolio/preview", _body())).json()
    assert preview["position"]["premiumStopPct"] is None
    before = await _counts(Maker)
    monkeypatch.setattr("app.services.position_writer._global_premium_stop_pct", lambda: 0.50)
    r = await _post(Maker, market, "/api/portfolio", _body(), headers={HEADER: preview["fingerprint"]})
    fresh = await _assert_review_required(Maker, r, preview["fingerprint"], before)
    assert fresh["inheritedPremiumStopPct"] == 0.50


@pytest.mark.asyncio
async def test_a_mismatch_is_judged_before_the_hold_transfer(Maker):
    """Direct call with an exposure attempt: the comparison precedes
    transfer_hold, so a mismatch transfers nothing."""
    market = Market()
    with patch("app.services.position_writer.transfer_hold", new=AsyncMock()) as hold:
        async with Maker() as db:
            with pytest.raises(ReviewRequired) as exc:
                await create_position(
                    PortfolioPositionCreate(**_body()), db,
                    quote_fetcher=market.quote, price_fetcher=market.price,
                    exit_plan_cfg_loader=lambda: {},
                    exposure_attempt_id="ATT-1", review_fingerprint="v1:stale",
                )
    hold.assert_not_awaited()
    assert exc.value.preview.fingerprint.startswith("v1:")
    assert await _counts(Maker) == {
        "portfolio_positions": 0, "exposure_guards": 0, "exposure_holds": 0, "audit_events": 0,
    }


# ── stop / premium / target semantics are the writer's, shown exactly ─────


@pytest.mark.asyncio
async def test_an_absolute_user_stop_is_stored_as_sent_and_shown_unadjusted(Maker):
    market = Market(underlying=101.0)
    body = _body(stop=95.0, stopIsUserSet=True)
    preview = (await _post(Maker, market, "/api/portfolio/preview", body)).json()
    assert preview["position"]["stop"] == 95.0
    assert "stop" not in {d["field"] for d in preview["differences"]}
    assert preview["position"]["structuralStop"] == 89.0, "the plan level still re-anchors"
    r = await _post(Maker, market, "/api/portfolio", body, headers={HEADER: preview["fingerprint"]})
    assert r.status_code == 201 and r.json()["stop"] == 95.0


@pytest.mark.asyncio
async def test_a_wrong_side_user_stop_is_refused_by_the_preview_too(Maker):
    r = await _post(Maker, Market(underlying=101.0), "/api/portfolio/preview",
                    _body(stop=150.0, stopIsUserSet=True))
    assert r.status_code == 422
    assert await _counts(Maker) == {
        "portfolio_positions": 0, "exposure_guards": 0, "exposure_holds": 0, "audit_events": 0,
    }


@pytest.mark.asyncio
async def test_a_fallback_premium_stop_is_previewed_and_stored_identically(Maker):
    """$4.50 typed against a $10.45 card, filled at $4.20: a total loss at the
    saved entry, so the writer keeps the card's own fraction (decision
    PREMIUM-STOP-FALLBACK-USER-FRACTION-2026-10-03)."""
    market = Market(premium=4.20)
    body = _body(premiumStopDollar=4.50, premiumStopPct=0.43)
    preview = (await _post(Maker, market, "/api/portfolio/preview", body)).json()
    assert preview["position"]["premiumStopPct"] == 0.43
    assert "could not be applied" in preview["premiumStopUnapplied"]
    fields = {d["field"]: d for d in preview["differences"]}
    assert fields["premiumStop"]["reason"] == "premium_stop_unapplied"
    r = await _post(Maker, market, "/api/portfolio", body, headers={HEADER: preview["fingerprint"]})
    assert r.status_code == 201 and r.json()["premiumStopPct"] == 0.43


@pytest.mark.asyncio
async def test_a_dollar_premium_stop_is_derived_against_the_saved_entry(Maker):
    market = Market(premium=5.00)
    preview = (await _post(Maker, market, "/api/portfolio/preview", _body(premiumStopDollar=2.0))).json()
    assert preview["position"]["premiumStopPct"] == pytest.approx(0.4)
    assert {d["field"]: d for d in preview["differences"]}["premiumStop"]["reason"] == "derived_from_dollar"


@pytest.mark.asyncio
async def test_a_barrier_race_pick_shows_the_ladder_fallback(Maker):
    body = _body(pickedMethod="barrier_race", pickedRowOptionPrice=14.0)
    preview = (await _post(Maker, Market(), "/api/portfolio/preview", body)).json()
    assert preview["position"]["pickedMethod"] == "barrier_race"
    assert preview["position"]["activeTpMethod"] == "ladder"
    assert {d["field"]: d for d in preview["differences"]}["targetAlert"]["reason"] == "ladder_fallback"


@pytest.mark.asyncio
async def test_a_monte_carlo_pick_seeds_its_stock_level(Maker):
    body = _body(pickedMethod="monte_carlo", pickedRowStockPrice=120.0)
    preview = (await _post(Maker, Market(), "/api/portfolio/preview", body)).json()
    assert (preview["position"]["activeTpMethod"], preview["position"]["resolvedTpPrice"]) == ("monte_carlo", 120.0)
    r = await _post(Maker, Market(), "/api/portfolio", body, headers={HEADER: preview["fingerprint"]})
    assert r.status_code == 201
    assert (r.json()["activeTpMethod"], r.json()["resolvedTpPrice"]) == ("monte_carlo", 120.0)


@pytest.mark.asyncio
async def test_a_duplicate_contract_is_reported_by_the_preview(Maker):
    market = Market()
    assert (await _post(Maker, market, "/api/portfolio", _body())).status_code == 201
    r = await _post(Maker, market, "/api/portfolio/preview", _body(recId="REC-R2"))
    assert r.status_code == 409
    assert (await _counts(Maker))["portfolio_positions"] == 1


# ── requests without a fingerprint keep today's behaviour ─────────────────


@pytest.mark.asyncio
async def test_no_fingerprint_is_todays_create(Maker):
    market = Market()
    r = await _post(Maker, market, "/api/portfolio", _body())
    assert r.status_code == 201
    assert (r.json()["entryPrice"], r.json()["stop"]) == (10.80, 90.89)


@pytest.mark.asyncio
async def test_an_empty_fingerprint_is_a_mismatch_not_an_absence(Maker):
    r = await _post(Maker, Market(), "/api/portfolio", _body(), headers={HEADER: ""})
    assert r.status_code == 412
    assert (await _counts(Maker))["portfolio_positions"] == 0
