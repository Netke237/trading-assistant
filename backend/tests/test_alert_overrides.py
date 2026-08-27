# backend/tests/test_alert_overrides.py
"""Feature D — per-position alert overrides and the resolved-TP snapshot.

Mirrors frontend/lib/__tests__/alertEngine.test.ts's own Feature D block; the
two engines are documented mirrors of each other, so a rule proved here should
have a counterpart there.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.portfolio import PortfolioPositionModel
from app.services.alert_generator import effective_enabled, generate_alerts


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _position(**overrides) -> PortfolioPositionModel:
    base = dict(
        id=uuid.uuid4(), rec_id='rec-1', symbol='AAPL', contract='AAPL|150|2099-01-01|C',
        direction='Bullish', entry_price=5.0, qty=1, entry_date='2024-01-01',
        stop=140.0, targets=[{'stock_price': 200.0}], dte_total=30,
        entry_stock_price=145.0, alert_state={},
    )
    base.update(overrides)
    return PortfolioPositionModel(**base)


async def _alerts(position, prices, **kwargs):
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(position)
        await db.commit()
        return await generate_alerts(db, prices, **kwargs)


# ── effective_enabled: the three-way resolution ─────────────────────────────

def test_effective_enabled_returns_none_when_no_override_present():
    assert effective_enabled({}, 'TP_HIT') is None
    assert effective_enabled(None, 'TP_HIT') is None
    assert effective_enabled({'STOP_REACHED': False}, 'TP_HIT') is None


def test_effective_enabled_returns_the_explicit_override():
    assert effective_enabled({'TP_HIT': False}, 'TP_HIT') is False
    assert effective_enabled({'TP_HIT': True}, 'TP_HIT') is True


def test_effective_enabled_treats_a_non_bool_value_as_absent():
    # A truthy string must not be coerced into "force this alert on".
    assert effective_enabled({'TP_HIT': 'yes'}, 'TP_HIT') is None
    assert effective_enabled({'TP_HIT': 1}, 'TP_HIT') is None


# ── generate_alerts: an explicit False suppresses, everything else doesn't ──

@pytest.mark.asyncio
async def test_muted_type_produces_no_alert_for_that_position():
    alerts = await _alerts(
        _position(alert_overrides={'STOP_REACHED': False}), {'AAPL': 130.0})
    assert not any(a.alertType == 'STOP_REACHED' for a in alerts)


@pytest.mark.asyncio
async def test_muting_one_type_leaves_the_others_firing():
    alerts = await _alerts(
        _position(alert_overrides={'STOP_REACHED': False}, targets=[{'stock_price': 120.0}]),
        {'AAPL': 130.0})
    types = {a.alertType for a in alerts}
    assert 'STOP_REACHED' not in types
    assert 'TP_HIT' in types


@pytest.mark.asyncio
async def test_explicit_true_still_generates_the_alert():
    # An explicit True is NOT filtered here — the global-enabledTypes bypass it
    # buys happens at dispatch (notify_alert's type_enabled), not generation.
    alerts = await _alerts(
        _position(alert_overrides={'STOP_REACHED': True}), {'AAPL': 130.0})
    assert any(a.alertType == 'STOP_REACHED' for a in alerts)


@pytest.mark.asyncio
async def test_absent_override_preserves_pre_feature_d_behavior():
    alerts = await _alerts(_position(alert_overrides={}), {'AAPL': 130.0})
    assert any(a.alertType == 'STOP_REACHED' for a in alerts)


@pytest.mark.asyncio
async def test_muting_clears_a_half_elapsed_sustain_clock():
    from sqlalchemy import select
    Session = await _make_session_factory()
    async with Session() as db:
        past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
        db.add(_position(alert_state={'STOP_REACHED': past},
                         alert_overrides={'STOP_REACHED': False}))
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 130.0}, sustain_minutes=5)
        await db.commit()
        refreshed = (await db.execute(select(PortfolioPositionModel))).scalar_one()
    # Without the clock reset the alert would fire the instant it's un-muted,
    # even though it was off for the whole sustain window.
    assert not any(a.alertType == 'STOP_REACHED' for a in alerts)
    assert 'STOP_REACHED' not in (refreshed.alert_state or {})


# ── resolved TP snapshot drives TP_HIT ──────────────────────────────────────

@pytest.mark.asyncio
async def test_resolved_tp_price_overrides_the_ladder_target():
    # Ladder says 200, the active method's snapshot says 160 — price 165 must
    # hit the snapshot and not the ladder.
    alerts = await _alerts(
        _position(targets=[{'stock_price': 200.0}], resolved_tp_price=160.0,
                  active_tp_method='exit_plan_2r'),
        {'AAPL': 165.0})
    tp = [a for a in alerts if a.alertType == 'TP_HIT']
    assert len(tp) == 1
    assert tp[0].referenceValue == 160.0


@pytest.mark.asyncio
async def test_resolved_tp_price_can_also_hold_the_alert_back():
    alerts = await _alerts(
        _position(targets=[{'stock_price': 160.0}], resolved_tp_price=200.0,
                  active_tp_method='exit_plan_3r'),
        {'AAPL': 165.0})
    assert not any(a.alertType == 'TP_HIT' for a in alerts)


@pytest.mark.asyncio
async def test_falls_back_to_the_ladder_when_no_snapshot_was_stamped():
    alerts = await _alerts(
        _position(targets=[{'stock_price': 160.0}], resolved_tp_price=None,
                  active_tp_method='exit_plan_2r'),
        {'AAPL': 165.0})
    assert any(a.alertType == 'TP_HIT' for a in alerts)


@pytest.mark.asyncio
async def test_snapshot_alone_fires_tp_hit_with_no_ladder_targets():
    alerts = await _alerts(
        _position(targets=[], resolved_tp_price=160.0, active_tp_method='exit_plan_2r'),
        {'AAPL': 165.0})
    assert any(a.alertType == 'TP_HIT' for a in alerts)


@pytest.mark.asyncio
async def test_bearish_snapshot_fires_on_the_way_down():
    alerts = await _alerts(
        _position(direction='Bearish', stop=None, targets=[],
                  resolved_tp_price=140.0, active_tp_method='exit_plan_2r'),
        {'AAPL': 135.0})
    assert any(a.alertType == 'TP_HIT' for a in alerts)

    quiet = await _alerts(
        _position(direction='Bearish', stop=None, targets=[],
                  resolved_tp_price=140.0, active_tp_method='exit_plan_2r'),
        {'AAPL': 145.0})
    assert not any(a.alertType == 'TP_HIT' for a in quiet)


@pytest.mark.asyncio
async def test_tp_hit_reason_names_the_active_method_that_fired():
    # Mirrors frontend alertEngine's tpMethodNote — the backend reason (which
    # is what email/Telegram/the websocket broadcast actually show, not just
    # the in-app toast) must name which method's snapshot supplied the price.
    alerts = await _alerts(
        _position(targets=[{'stock_price': 200.0}], resolved_tp_price=160.0,
                  active_tp_method='exit_plan_2r'),
        {'AAPL': 165.0})
    tp = [a for a in alerts if a.alertType == 'TP_HIT']
    assert len(tp) == 1
    assert '(2R exit plan)' in tp[0].reason


@pytest.mark.asyncio
async def test_tp_hit_reason_leaves_the_ladder_unlabelled():
    alerts = await _alerts(
        _position(targets=[{'stock_price': 160.0}]),
        {'AAPL': 165.0})
    tp = [a for a in alerts if a.alertType == 'TP_HIT']
    assert len(tp) == 1
    assert '(' not in tp[0].reason


@pytest.mark.asyncio
async def test_tp_hit_reason_does_not_label_a_fallen_back_method():
    # active_tp_method is exit_plan_2r but its snapshot was never stamped, so
    # this fires off the ladder target instead — the reason must not claim
    # the 2R plan supplied a price it never actually resolved.
    alerts = await _alerts(
        _position(targets=[{'stock_price': 160.0}], resolved_tp_price=None,
                  active_tp_method='exit_plan_2r'),
        {'AAPL': 165.0})
    tp = [a for a in alerts if a.alertType == 'TP_HIT']
    assert len(tp) == 1
    assert '(' not in tp[0].reason


def test_effective_enabled_ignores_an_account_wide_type():
    # REGIME_CHANGE is never raised per position — a stray key for it must not
    # be allowed to override the user's global setting.
    assert effective_enabled({'REGIME_CHANGE': True}, 'REGIME_CHANGE') is None
    assert effective_enabled({'SCAN_COMPLETE': False}, 'SCAN_COMPLETE') is None


@pytest.mark.asyncio
async def test_a_zero_snapshot_falls_back_to_the_ladder_instead_of_firing_always():
    # 0 is never a real stock price. Read as a genuine target it would make
    # `price >= 0` true on every tick for a bullish position.
    alerts = await _alerts(
        _position(targets=[{'stock_price': 200.0}], resolved_tp_price=0.0,
                  active_tp_method='exit_plan_2r'),
        {'AAPL': 165.0})
    assert not any(a.alertType == 'TP_HIT' for a in alerts)


@pytest.mark.asyncio
async def test_a_zero_ladder_target_does_not_fire_tp_hit():
    # Pre-existing latent bug, fixed in passing by resolving the TP price once:
    # a target row carrying no usable stock price used to collapse to 0 and fire
    # immediately for a bullish position.
    alerts = await _alerts(
        _position(targets=[{'stock_price': 0}], resolved_tp_price=None),
        {'AAPL': 165.0})
    assert not any(a.alertType == 'TP_HIT' for a in alerts)
