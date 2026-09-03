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

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.portfolio import PortfolioPositionModel
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

def test_auto_trader_sizes_off_the_resolved_pct():
    """`auto_trade.premium_stop_pct` is a DIFFERENT global from the alerts'.
    The auto-trader is placing the trade the card described, so it must use the
    number the user set, not either global."""
    from app.services.auto_trader import ArmedStrategy

    armed = ArmedStrategy(
        broker="tradier_paper", symbol="AAPL", option_symbol="AAPL260516C00190000",
        action="BUY", quantity=1, order_type="LMT", limit_price=5.0, conid=None,
        entry_premium=5.0, premium_stop_pct=0.30,
    )
    assert resolve_premium_stop_pct(armed.premium_stop_pct, 0.60) == 0.30

    inheriting = ArmedStrategy(
        broker="tradier_paper", symbol="AAPL", option_symbol="AAPL260516C00190000",
        action="BUY", quantity=1, order_type="LMT", limit_price=5.0, conid=None,
        entry_premium=5.0,
    )
    assert inheriting.premium_stop_pct is None
    assert resolve_premium_stop_pct(inheriting.premium_stop_pct, 0.60) == 0.60


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
