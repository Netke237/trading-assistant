# backend/tests/test_premium_stop_per_position.py
"""Piece 4 — the per-position premium stop.

Covers the spec's backend tests (docs/superpowers/plans/
2026-09-02-piece-4-per-position-premium-stop-spec.md §8): the resolver's
inherit-vs-set contract, schema validation, that the value survives a CREATE
(not update-only), that the alert generator both fires on and REPORTS the
resolved value, and that the auto-trader sizes off it.

The frontend half — `alertEngine.scanPortfolio`, the drawer preview, and the
two send paths — is mirrored in frontend/lib/__tests__/premiumStop.test.ts.
"""
from __future__ import annotations

import uuid

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.models.portfolio import PortfolioPositionModel
from app.routers.portfolio import router as portfolio_router
from app.services.alert_generator import generate_alerts
from app.services.premium_stop import (
    PREMIUM_STOP_PCT_FALLBACK,
    premium_stop_threshold_price,
    resolve_premium_stop_pct,
)


async def _make_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _position(**overrides) -> PortfolioPositionModel:
    base = dict(
        id=uuid.uuid4(), rec_id="rec-1", symbol="AAPL",
        contract="AAPL|190|2026-05-16|C",
        direction="Bullish", entry_price=5.0, qty=1, entry_date="2024-01-01",
        stop=140.0, targets=[], dte_total=30, entry_stock_price=145.0,
        alert_state={},
    )
    base.update(overrides)
    return PortfolioPositionModel(**base)


async def _alerts(position, prices, opt_prices):
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(position)
        await db.commit()
        return await generate_alerts(db, prices, opt_prices)


# ── The resolver: NULL inherits, a set value wins ────────────────────────────

def test_null_resolves_to_the_global():
    assert resolve_premium_stop_pct(None, 0.60) == 0.60


def test_a_set_value_beats_the_global():
    assert resolve_premium_stop_pct(0.45, 0.60) == 0.45


def test_changing_the_global_moves_null_positions_and_leaves_set_ones_alone():
    """The whole point of NULL-means-inherit. A position stamped with the
    global's value at creation would be frozen at it; a NULL one tracks it."""
    inheriting, pinned = None, 0.45
    assert resolve_premium_stop_pct(inheriting, 0.60) == 0.60
    assert resolve_premium_stop_pct(inheriting, 0.75) == 0.75   # moved
    assert resolve_premium_stop_pct(pinned, 0.60) == 0.45
    assert resolve_premium_stop_pct(pinned, 0.75) == 0.45       # unmoved


def test_resolver_falls_back_when_no_global_could_be_loaded():
    assert resolve_premium_stop_pct(None, None) == PREMIUM_STOP_PCT_FALLBACK


def test_threshold_price_is_entry_times_one_minus_pct():
    assert premium_stop_threshold_price(5.0, 0.60) == pytest.approx(2.0)
    assert premium_stop_threshold_price(5.0, 0.30) == pytest.approx(3.5)


# ── Schema validation: 0, 1.0 and negatives are rejected, not stored ─────────

@pytest.mark.parametrize("bad", [0, 0.0, 1.0, 1.5, -0.5])
def test_schema_rejects_meaningless_percentages(bad):
    """1.0 is a total loss, which makes the stop unreachable-by-definition
    rather than a stop; 0 is meaningless. Reject rather than store."""
    from pydantic import ValidationError
    from app.schemas import PortfolioPositionCreate, PortfolioPositionUpdate

    for model in (PortfolioPositionCreate, PortfolioPositionUpdate):
        with pytest.raises(ValidationError):
            if model is PortfolioPositionCreate:
                model(recId="r", symbol="A", contract="c", direction="Bullish",
                      entryPrice=1.0, entryDate="2026-01-01", premiumStopPct=bad)
            else:
                model(premiumStopPct=bad)


@pytest.mark.parametrize("good", [0.01, 0.45, 0.60, 0.99])
def test_schema_accepts_the_open_interval(good):
    from app.schemas import PortfolioPositionCreate
    assert PortfolioPositionCreate(
        recId="r", symbol="A", contract="c", direction="Bullish",
        entryPrice=1.0, entryDate="2026-01-01", premiumStopPct=good,
    ).premiumStopPct == good


# ── Settable at CREATION, not update-only (the active_tp_method trap) ────────

def test_premium_stop_pct_survives_a_create_in_both_naming_conventions():
    """`active_tp_method` / `resolved_tp_price` live on the UPDATE schema only.
    Repeating that here would mean a trade sent from the card silently falls
    back to the global on its very first alert."""
    from app.schemas import PortfolioPositionCreate

    camel = PortfolioPositionCreate(
        recId="r", symbol="A", contract="c", direction="Bullish",
        entryPrice=1.0, entryDate="2026-01-01", premiumStopPct=0.45,
    )
    snake = PortfolioPositionCreate(
        rec_id="r", symbol="A", contract="c", direction="Bullish",
        entry_price=1.0, entry_date="2026-01-01", premium_stop_pct=0.45,
    )
    assert camel.premiumStopPct == snake.premiumStopPct == 0.45


def test_create_defaults_to_none_meaning_inherit():
    from app.schemas import PortfolioPositionCreate
    assert PortfolioPositionCreate(
        recId="r", symbol="A", contract="c", direction="Bullish",
        entryPrice=1.0, entryDate="2026-01-01",
    ).premiumStopPct is None


def test_update_tracks_an_explicit_null_so_it_can_clear_the_override():
    """`{"premiumStopPct": null}` must reach the router as a SET key, or there
    is no way back from a pinned value to inheriting the global."""
    from app.schemas import PortfolioPositionUpdate
    assert "premiumStopPct" in PortfolioPositionUpdate(
        premiumStopPct=None
    ).model_dump(exclude_unset=True)


def test_orm_round_trip_preserves_none_rather_than_resolving_it():
    """The frontend renders "60% (global)" vs "45%", so the inherited state has
    to survive the trip out — it must not be resolved server-side."""
    from app.schemas import PortfolioPositionSchema
    from datetime import datetime, timezone

    pos = _position(premium_stop_pct=None)
    pos.created_at = datetime.now(timezone.utc)
    assert PortfolioPositionSchema.from_orm_model(pos).premiumStopPct is None

    pos.premium_stop_pct = 0.45
    assert PortfolioPositionSchema.from_orm_model(pos).premiumStopPct == 0.45


# ── The alert generator fires on, and REPORTS, the resolved value ───────────

@pytest.mark.asyncio
async def test_position_with_own_pct_fires_where_the_global_would_not():
    """entry 5.00, position pct 0.30 -> threshold 3.50. An option at 3.40 is a
    32% loss: past this position's stop, nowhere near the global 60% (2.00)."""
    alerts = await _alerts(
        _position(premium_stop_pct=0.30),
        {"AAPL": 180.0},
        {"AAPL|190|2026-05-16|C": 3.40},
    )
    assert [a.alertType for a in alerts].count("PREMIUM_STOP") == 1


@pytest.mark.asyncio
async def test_same_price_does_not_fire_for_an_inheriting_position():
    """The control for the test above: identical price, identical entry, the
    only difference is that this position inherits the 60% global."""
    alerts = await _alerts(
        _position(premium_stop_pct=None),
        {"AAPL": 180.0},
        {"AAPL|190|2026-05-16|C": 3.40},
    )
    assert not [a for a in alerts if a.alertType == "PREMIUM_STOP"]


@pytest.mark.asyncio
async def test_a_looser_own_pct_suppresses_a_fire_the_global_would_have_made():
    """The mirror direction — a conviction trade given MORE room. At 1.80 the
    global 60% (threshold 2.00) fires; this position's 70% (1.50) does not."""
    fired_under_global = await _alerts(
        _position(premium_stop_pct=None),
        {"AAPL": 180.0}, {"AAPL|190|2026-05-16|C": 1.80},
    )
    assert [a for a in fired_under_global if a.alertType == "PREMIUM_STOP"]

    held_under_own = await _alerts(
        _position(rec_id="rec-2", premium_stop_pct=0.70),
        {"AAPL": 180.0}, {"AAPL|190|2026-05-16|C": 1.80},
    )
    assert not [a for a in held_under_own if a.alertType == "PREMIUM_STOP"]


@pytest.mark.asyncio
async def test_reported_threshold_price_is_the_resolved_one_not_the_global():
    """The alert's own payload must not misreport why it fired. Threshold for
    a 0.30 position on a 5.00 entry is 3.50, not the global's 2.00."""
    alerts = await _alerts(
        _position(premium_stop_pct=0.30),
        {"AAPL": 180.0}, {"AAPL|190|2026-05-16|C": 3.40},
    )
    prem = [a for a in alerts if a.alertType == "PREMIUM_STOP"][0]
    assert prem.referenceValue == pytest.approx(3.50)


@pytest.mark.asyncio
async def test_logged_threshold_pct_is_the_resolved_one_not_the_global(monkeypatch):
    """The audit-log payload must not misreport WHY the alert fired.

    Separate from the test above on purpose: that one asserts the threshold
    PRICE carried on the AlertItem, this one asserts the `thresholdPct` written
    into the audit log. An adversarial mutation round proved they are
    independent — reverting only the logged value to `_premium_stop_pct()` left
    every other test in this file passing, so the price assertion does not
    cover the log and the log needs its own guard.
    """
    import app.services.alert_generator as ag

    captured: list[tuple[str, dict]] = []
    real_log_event = ag.log_event
    monkeypatch.setattr(
        ag, "log_event",
        lambda event_type, rec_id, payload: captured.append((event_type, payload)),
    )
    assert real_log_event is not ag.log_event  # the patch actually took

    await _alerts(
        _position(premium_stop_pct=0.30),
        {"AAPL": 180.0}, {"AAPL|190|2026-05-16|C": 3.40},
    )

    fired = [p for kind, p in captured
             if kind == "alert_fired" and p.get("alertType") == "PREMIUM_STOP"]
    assert len(fired) == 1, "expected exactly one PREMIUM_STOP audit event"
    # 0.30 is this position's own value; 0.60 is the global it must NOT report.
    assert fired[0]["thresholdPct"] == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_logged_threshold_pct_reports_the_global_for_an_inheriting_position(monkeypatch):
    """The control: an inheriting position SHOULD log the global, so the test
    above is proving resolution rather than just a hardcoded 0.30."""
    import app.services.alert_generator as ag

    captured: list[dict] = []
    monkeypatch.setattr(
        ag, "log_event",
        lambda event_type, rec_id, payload: captured.append(payload),
    )

    await _alerts(
        _position(premium_stop_pct=None),
        {"AAPL": 180.0}, {"AAPL|190|2026-05-16|C": 1.50},
    )

    fired = [p for p in captured if p.get("alertType") == "PREMIUM_STOP"]
    assert len(fired) == 1
    assert fired[0]["thresholdPct"] == pytest.approx(
        resolve_premium_stop_pct(None, ag._premium_stop_pct())
    )


# ── The auto-trader sizes off the resolved value ────────────────────────────

def _armed(**kw):
    from app.services.auto_trader import ArmedStrategy
    base = dict(
        broker="tradier_paper", symbol="AAPL", option_symbol="AAPL260516C00190000",
        action="BUY", quantity=1, order_type="LMT", limit_price=5.0, conid=None,
        entry_premium=5.0,
    )
    base.update(kw)
    return ArmedStrategy(**base)


def test_auto_trader_daily_loss_gate_sizes_off_the_resolved_pct(monkeypatch):
    """`auto_trade.premium_stop_pct` is a DIFFERENT global from the alerts'.
    The auto-trader is placing the trade the card described, so it must size the
    daily-loss gate on the number the user set, not on either global.

    This drives `_check_daily_loss` itself. The version of this test that
    shipped constructed an ArmedStrategy and then asserted on
    `resolve_premium_stop_pct(...)` directly, so it passed with the auto-trader
    still reading the global -- both call sites could be reverted with the whole
    suite green. The gate is arithmetic on `stop_pct`, so a threshold that
    straddles the two values is what actually pins the wiring.
    """
    from app.services.auto_trader import AutoTradeService

    # limit = 0.02 x 10_000 = $200. this_risk = 5.00 x 1 x 100 x stop_pct,
    # so the global's 0.60 books $300 (over) and a per-position 0.30 books
    # $150 (under). Nothing else separates the two calls.
    monkeypatch.setattr(
        AutoTradeService, "_risk_config",
        staticmethod(lambda: {"max_daily_loss_pct": 0.02, "premium_stop_pct": 0.60}),
    )

    # Inheriting: sized at the global, and the gate trips.
    with pytest.raises(RuntimeError, match="Daily loss limit reached"):
        AutoTradeService._check_daily_loss(_armed(), [], 10_000.0)

    # The same trade with a tighter declared stop books half the risk and passes.
    AutoTradeService._check_daily_loss(_armed(premium_stop_pct=0.30), [], 10_000.0)

    # And in the other direction, so the per-position value is genuinely in the
    # arithmetic rather than the tighter case merely failing to raise. At
    # $20,000 the limit is $400: the global's $300 passes, a declared 0.90
    # books $450 and trips. A gate still reading the global would let it
    # through.
    AutoTradeService._check_daily_loss(_armed(), [], 20_000.0)
    with pytest.raises(RuntimeError, match="Daily loss limit reached"):
        AutoTradeService._check_daily_loss(_armed(premium_stop_pct=0.90), [], 20_000.0)


def test_auto_trader_books_premium_at_risk_at_the_resolved_pct(monkeypatch):
    """`fire()` stamps `premium_at_risk` on the history entry the daily-loss
    gate later sums. If that were still booked at the global, a per-position
    stop would gate correctly on the way in and then mis-report what it spent,
    so tomorrow's first trade would be sized against the wrong number."""
    from app.services import auto_trader as at_mod
    from app.services.auto_trader import AutoTradeService

    monkeypatch.setattr(
        AutoTradeService, "_risk_config",
        staticmethod(lambda: {"max_daily_loss_pct": 1.0, "premium_stop_pct": 0.60}),
    )

    class _Result:
        order_id, status, broker = "o1", "filled", "tradier_paper"

    # The two things `fire` reaches outside itself: the market-open probe (a
    # network call) and the broker. Everything between them is under test.
    monkeypatch.setattr(at_mod, "_market_is_open", lambda symbol: True)
    monkeypatch.setattr(at_mod, "execute_option_order", lambda strategy: _Result())

    svc = AutoTradeService()
    svc._state.armed = True
    svc._state.strategy = _armed(premium_stop_pct=0.30)
    svc.fire(portfolio_snapshot=None, portfolio_value=100_000.0)

    booked = [e for e in svc._state.history if e.get("order_id") == "o1"]
    assert booked, f"fire() recorded no history entry: {svc._state.history}"
    # 5.00 x 1 x 100 x 0.30 = 150, not the global's 300.
    assert booked[-1]["premium_at_risk"] == pytest.approx(150.0)


def test_arm_request_carries_the_pct_into_the_strategy():
    """`ArmedStrategy(**req.model_dump())` — the field has to exist on BOTH or
    the value is silently dropped at the arm boundary."""
    from app.routers.auto_trade import ArmRequest
    from app.services.auto_trader import ArmedStrategy

    req = ArmRequest(
        broker="tradier_paper", symbol="AAPL",
        option_symbol="AAPL260516C00190000", action="BUY", quantity=1,
        premium_stop_pct=0.30,
    )
    assert ArmedStrategy(**req.model_dump()).premium_stop_pct == 0.30


@pytest.mark.parametrize("bad", [0, 1.0, -0.5])
def test_arm_request_rejects_meaningless_percentages(bad):
    """This endpoint reaches the same sizing arithmetic without ever passing
    through PortfolioPositionCreate, so it needs its own bound."""
    from pydantic import ValidationError
    from app.routers.auto_trade import ArmRequest

    with pytest.raises(ValidationError):
        ArmRequest(
            broker="tradier_paper", symbol="AAPL",
            option_symbol="AAPL260516C00190000", action="BUY", quantity=1,
            premium_stop_pct=bad,
        )


# ── Migration ───────────────────────────────────────────────────────────────

def test_alembic_has_exactly_one_head():
    """This repo has had a multiple-heads incident before
    (2026-07-17-alembic-merge-heads-ghost-alert-audit.md). Piece 4 adds a
    revision, so assert the chain still converges."""
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = Path(__file__).resolve().parent.parent
    cfg = Config()
    cfg.set_main_option("script_location", str(backend / "migrations"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1


def test_migration_adds_and_drops_the_column():
    """Applies and rolls back THIS revision in isolation, so a downgrade that
    does not actually reverse the change fails here rather than in production.

    Deliberately not a full `upgrade head` from an empty database: an earlier
    revision in this chain alters a foreign-key constraint, which the SQLite
    dialect cannot do without batch mode. That is pre-existing and unrelated to
    piece 4 — replaying the whole chain here would test that limitation, not
    this migration. So the table is created at the shape it has one revision
    back, alembic is stamped there, and only the single step under test runs.
    """
    import os
    import sqlite3
    import tempfile
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from app.config import get_settings

    backend = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "migrate.db"
        con = sqlite3.connect(db_path)
        con.execute(
            "CREATE TABLE portfolio_positions ("
            "  id TEXT PRIMARY KEY, rec_id TEXT NOT NULL, symbol TEXT NOT NULL,"
            "  contract TEXT NOT NULL, direction TEXT NOT NULL,"
            "  entry_price FLOAT NOT NULL, qty INTEGER, entry_date TEXT NOT NULL,"
            "  stop FLOAT, structural_stop FLOAT)"
        )
        con.commit()
        con.close()

        cfg = Config()
        cfg.set_main_option("script_location", str(backend / "migrations"))

        def columns() -> set[str]:
            c = sqlite3.connect(db_path)
            try:
                return {r[1] for r in c.execute("PRAGMA table_info(portfolio_positions)")}
            finally:
                c.close()

        # migrations/env.py OVERWRITES whatever sqlalchemy.url the caller set,
        # with settings.DATABASE_URL (env.py:41). Setting the option on `cfg`
        # is therefore ignored, and without this the migration runs against the
        # developer's real database instead of the temp file. get_settings() is
        # lru_cached, so the cache has to be cleared for the new value to land.
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
        get_settings.cache_clear()
        try:
            command.stamp(cfg, "2bf3bf834b29")
            assert "premium_stop_pct" not in columns()

            command.upgrade(cfg, "c7a1e9d4b820")
            assert "premium_stop_pct" in columns()

            command.downgrade(cfg, "2bf3bf834b29")
            assert "premium_stop_pct" not in columns()
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
            get_settings.cache_clear()


def test_new_column_is_nullable_with_no_backfill():
    """NULL means "inherit the global" and is load-bearing: a server default or
    a backfill would freeze every existing position at today's global, which is
    exactly the behaviour piece 4 removes."""
    col = PortfolioPositionModel.__table__.columns["premium_stop_pct"]
    assert col.nullable is True
    assert col.server_default is None
    assert col.default is None or col.default.arg is None


# ── The dollar amount survives a live-quote re-anchor ───────────────────────

def test_dollar_stop_is_resolved_against_the_persisted_entry_not_the_card_mid():
    """The defect this replaced: `portfolio.py` overwrites `entry_price` with
    the live quote, while the client derived the fraction against the card's
    mid. A $3.12 stop on a $5.20 premium filling at $4.00 became a $2.40 stop.

    The fraction is now derived server-side against the entry actually stored,
    so the DOLLAR amount the user typed is what survives.
    """
    dollar_stop, card_mid = 3.12, 5.20
    for persisted_entry in (card_mid, 4.00, 6.10):
        pct = dollar_stop / persisted_entry
        threshold = premium_stop_threshold_price(persisted_entry, pct)
        assert threshold == pytest.approx(persisted_entry - dollar_stop)

    # The old client-side derivation, for contrast: the fraction is pinned to
    # the card's mid, so a different fill silently moves the dollar stop.
    stale_pct = dollar_stop / card_mid
    stale_threshold = premium_stop_threshold_price(4.00, stale_pct)
    assert stale_threshold == pytest.approx(1.60)
    # The loss that stale fraction actually implies -- derived from the value
    # under test, not from two literals. `assert 4.00 - 1.60 == approx(2.40)`
    # compared constants and could not have failed if the helper changed.
    assert 4.00 - stale_threshold == pytest.approx(2.40)   # not the $3.12 typed


def test_create_schema_accepts_the_dollar_field_in_both_conventions():
    from app.schemas import PortfolioPositionCreate
    camel = PortfolioPositionCreate(
        recId="r", symbol="A", contract="c", direction="Bullish",
        entryPrice=5.20, entryDate="2026-01-01", premiumStopDollar=3.12,
    )
    snake = PortfolioPositionCreate(
        rec_id="r", symbol="A", contract="c", direction="Bullish",
        entry_price=5.20, entry_date="2026-01-01", premium_stop_dollar=3.12,
    )
    assert camel.premiumStopDollar == snake.premiumStopDollar == 3.12


@pytest.mark.parametrize("bad", [0, -1.0])
def test_create_schema_rejects_a_non_positive_dollar_stop(bad):
    from pydantic import ValidationError
    from app.schemas import PortfolioPositionCreate
    with pytest.raises(ValidationError):
        PortfolioPositionCreate(
            recId="r", symbol="A", contract="c", direction="Bullish",
            entryPrice=5.20, entryDate="2026-01-01", premiumStopDollar=bad,
        )


# ── The ROUTER, not the arithmetic beside it ─────────────────────────────────
#
# Everything above this line exercises helpers. `add_position`'s derivation
# block and `update_position`'s write are the code that actually decides what
# lands in the column, and neither had a test: the "resolved against the
# persisted entry" case divided two floats itself, and the update case asserted
# only that the schema's exclude_unset produced the right dict. Both now go
# through the endpoint.

@pytest_asyncio.fixture
async def api_client():
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


async def _create(client, *, live_price=None, rec="REC-PS", **extra):
    """POST /api/portfolio with the live quote pinned.

    `live_price=None` means the fetch found nothing and the router keeps the
    submitted entryPrice; a number means the router REPLACES it, which is the
    whole reason the fraction is derived server-side.
    """
    body = {
        "recId": rec, "symbol": "AAPL", "contract": "AAPL|190|2026-05-16|C",
        "direction": "Bullish", "entryPrice": 5.20, "qty": 1,
        "entryDate": "2026-05-01", "targets": [], "dteTotal": 30,
        "portfolioValue": 1_000_000,
    }
    body.update(extra)
    quote = None if live_price is None else {"price": live_price}
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=quote)):
        r = await client.post("/api/portfolio", json=body)
    return r


@pytest.mark.asyncio
async def test_router_derives_the_fraction_against_the_persisted_entry(api_client):
    # $3.12 typed on a $5.20 card, filled at $4.00. The DOLLAR is what the user
    # chose, so the stored fraction has to be the one that reproduces it against
    # the entry the row actually carries -- 0.78, not the 0.60 it would have
    # been against the card's mid.
    r = await _create(api_client, live_price=4.00, premiumStopDollar=3.12)
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["entryPrice"] == 4.00
    assert row["premiumStopPct"] == pytest.approx(0.78)
    # And the alert threshold that fraction produces is the typed dollar back.
    assert premium_stop_threshold_price(
        row["entryPrice"], row["premiumStopPct"]
    ) == pytest.approx(4.00 - 3.12)


@pytest.mark.asyncio
async def test_router_prefers_the_dollar_over_a_client_sent_fraction(api_client):
    r = await _create(api_client, live_price=4.00,
                      premiumStopDollar=2.00, premiumStopPct=0.60)
    assert r.status_code == 201, r.text
    assert r.json()["premiumStopPct"] == pytest.approx(0.50)   # 2.00 / 4.00


@pytest.mark.asyncio
async def test_router_stores_a_client_fraction_when_no_dollar_is_sent(api_client):
    r = await _create(api_client, live_price=4.00, premiumStopPct=0.45)
    assert r.status_code == 201, r.text
    assert r.json()["premiumStopPct"] == pytest.approx(0.45)


@pytest.mark.asyncio
async def test_router_stores_none_when_neither_is_sent(api_client):
    r = await _create(api_client, live_price=4.00)
    assert r.status_code == 201, r.text
    assert r.json()["premiumStopPct"] is None


@pytest.mark.asyncio
async def test_a_dollar_stop_beyond_the_premium_falls_back_rather_than_storing_it(api_client):
    # $6.00 typed on a card whose entry persists at $4.00: the ratio is 1.5, a
    # "stop" past a total loss, which the column's (0, 1) contract cannot hold.
    # It must not be stored, and it must not 422 the create either.
    r = await _create(api_client, live_price=4.00, premiumStopDollar=6.00)
    assert r.status_code == 201, r.text
    assert r.json()["premiumStopPct"] is None


@pytest.mark.asyncio
async def test_an_unusable_dollar_does_not_discard_a_valid_fraction(api_client):
    # The dollar WINS over the fraction, but losing both is a different thing
    # from preferring one: an out-of-range dollar used to overwrite a perfectly
    # valid client-sent fraction with None, silently handing the position back
    # to the global.
    r = await _create(api_client, live_price=4.00,
                      premiumStopDollar=6.00, premiumStopPct=0.45)
    assert r.status_code == 201, r.text
    assert r.json()["premiumStopPct"] == pytest.approx(0.45)


@pytest.mark.asyncio
async def test_patch_writes_the_column_and_an_explicit_null_clears_it(api_client):
    created = await _create(api_client, live_price=4.00, premiumStopDollar=2.00,
                            rec="REC-PATCH")
    assert created.status_code == 201, created.text
    rec = created.json()["recId"]

    patched = await api_client.patch(f"/api/portfolio/{rec}",
                                     json={"premiumStopPct": 0.30})
    assert patched.status_code == 200, patched.text
    assert patched.json()["premiumStopPct"] == pytest.approx(0.30)

    # An omitted key leaves it alone...
    untouched = await api_client.patch(f"/api/portfolio/{rec}", json={"stop": 140.0})
    assert untouched.json()["premiumStopPct"] == pytest.approx(0.30)

    # ...and an explicit null returns the position to inheriting the global.
    cleared = await api_client.patch(f"/api/portfolio/{rec}",
                                     json={"premiumStopPct": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["premiumStopPct"] is None


@pytest.mark.asyncio
async def test_a_sub_cent_live_quote_does_not_store_a_zero_entry(api_client):
    """ROUND 5. `entryPrice` carries `gt=0` precisely because a 0 entry is the
    denominator of the per-position stop -- but that bound validates what the
    CLIENT sent, and the router then OVERWRITES it with the live quote. The
    guard on that overwrite tested the raw quote (`float(live_entry) > 0`) and
    only rounded afterwards, so a sub-cent price sailed through and was stored
    as 0.0.

    A stored 0.0 entry is a silently unprotected position: alert_generator gates
    PREMIUM_STOP on `pos.entry_price > 0`, so the row can never raise a stop
    alert at all, no matter what stop it carries.
    """
    r = await _create(api_client, live_price=0.004, rec="REC-SUBCENT")
    assert r.status_code == 201, r.text
    row = r.json()
    # The sub-cent quote is not a usable entry, so the submitted price stands.
    assert row["entryPrice"] == 5.20
    assert row["entryPrice"] > 0


@pytest.mark.asyncio
async def test_a_sub_cent_live_quote_still_derives_a_usable_stop(api_client):
    """The consequence the zero-entry bug hid: with the entry preserved, a typed
    dollar stop still derives against a real denominator instead of being
    dropped (or dividing by zero)."""
    r = await _create(api_client, live_price=0.004, rec="REC-SUBCENT-2",
                      premiumStopDollar=3.12)
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["entryPrice"] == 5.20
    assert row["premiumStopPct"] == pytest.approx(0.60)
    assert premium_stop_threshold_price(
        row["entryPrice"], row["premiumStopPct"]
    ) == pytest.approx(2.08)


# ── Round 9 — a TYPED stop is an absolute price, not a plan level ────────────
#
# The router re-anchors `stop` by (live price - scanStockPrice) so a level the
# PLAN derived at scan time still sits the same distance from the underlying
# when it is finally saved. This branch made the card's Invalidation an
# editable absolute price, and round 8 bounded that field against the LIVE
# quote -- so a stop typed while looking at today's price was then displaced by
# (today - scan day). `stopIsUserSet` is what tells the two apart.


async def _create_reanchor(client, *, scan_price, live_stock, stop, **extra):
    """POST with BOTH quote fetches pinned, so the re-anchor branch is live.

    `_create` above patches only the contract quote; `need_reanchor` on a
    non-stock contract also awaits `fetch_price_async` for the underlying.
    """
    body = {
        "recId": "REC-RE", "symbol": "AAPL", "contract": "AAPL|190|2026-05-16|C",
        "direction": "Bullish", "entryPrice": 5.20, "qty": 1,
        "entryDate": "2026-05-01", "targets": [], "dteTotal": 30,
        "portfolioValue": 1_000_000,
        "scanStockPrice": scan_price, "stop": stop,
    }
    body.update(extra)
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value={"price": 4.00})), \
         patch("app.routers.portfolio.fetch_price_async",
               new=AsyncMock(return_value=live_stock)):
        return await client.post("/api/portfolio", json=body)


@pytest.mark.asyncio
async def test_a_user_typed_stop_is_stored_as_sent_not_reanchored(api_client):
    # Scanned at $145, reopened and saved at $200 -- the persisted-scanResult
    # staleness the card's own bounds fix documents. $180 is a legitimate stop
    # against today's $200. Re-anchoring made it 180 + 55 = $235, ABOVE spot.
    r = await _create_reanchor(api_client, scan_price=145.0, live_stock=200.0,
                               stop=180.0, stopIsUserSet=True)
    assert r.status_code == 201, r.text
    stored = r.json()["stop"]
    assert stored == pytest.approx(180.0), (
        f"a typed stop must be stored as sent; got {stored}"
    )
    # The point of the fix: this must NOT be a stop the live price already sits
    # at or below, or alert_generator's bullish `price <= pos.stop` raises a
    # Critical STOP_REACHED on the first backend scan.
    assert 200.0 > stored, "stored stop is at or above spot -- fires immediately"


@pytest.mark.asyncio
async def test_the_everyday_small_move_does_not_shift_a_typed_stop(api_client):
    # The same defect without any staleness: scanned 150, saved at 152, typed
    # 147 -> stored 149. Small, silent, and wrong in the dangerous direction.
    r = await _create_reanchor(api_client, scan_price=150.0, live_stock=152.0,
                               stop=147.0, stopIsUserSet=True)
    assert r.status_code == 201, r.text
    assert r.json()["stop"] == pytest.approx(147.0)


@pytest.mark.asyncio
async def test_a_plan_derived_stop_still_reanchors(api_client):
    # The flag is opt-in and narrow. Without it -- every legacy client, and
    # every untouched card -- the re-anchor is still exactly right, because the
    # level was computed against `scanStockPrice` in the first place.
    r = await _create_reanchor(api_client, scan_price=150.0, live_stock=152.0,
                               stop=147.0)
    assert r.status_code == 201, r.text
    assert r.json()["stop"] == pytest.approx(149.0)


@pytest.mark.asyncio
async def test_the_flag_exempts_only_the_stop_not_the_structural_stop(api_client):
    # structuralStop and the targets stay plan-derived and must keep moving
    # with the underlying even when the user typed the invalidation.
    r = await _create_reanchor(api_client, scan_price=150.0, live_stock=152.0,
                               stop=147.0, stopIsUserSet=True,
                               structuralStop=145.0)
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["stop"] == pytest.approx(147.0)
    assert row["structuralStop"] == pytest.approx(147.0)   # 145 + 2, re-anchored
