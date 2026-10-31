import dataclasses
import json
import pytest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from app.services.auto_trader import AutoTradeService, ArmedStrategy, AutoTradeState, FiredOrder


def test_service_starts_unarmed():
    svc = AutoTradeService()
    state = svc.get_state()
    assert state.armed is False
    assert state.strategy is None


def test_arm_sets_state():
    svc = AutoTradeService()
    armed = ArmedStrategy(
        broker="ibkr_paper",
        symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish",
        quantity=1,
        order_type="LMT",
        limit_price=2.50,
        conid=None,
        entry_premium=2.50,
    )
    svc.arm(armed)
    state = svc.get_state()
    assert state.armed is True
    assert state.strategy.symbol == "AAPL"


def test_disarm_clears_state():
    svc = AutoTradeService()
    armed = ArmedStrategy(
        broker="tradier_paper", symbol="NVDA",
        option_symbol="NVDA260620C00130000",
        action="BUY", direction="Bullish", quantity=2, order_type="MKT",
        limit_price=None, conid=None,
        entry_premium=3.00,
    )
    svc.arm(armed)
    svc.disarm()
    assert svc.get_state().armed is False


def test_fire_executes_and_disarms(mocker):
    from app.data.ibkr_paper import OrderResult
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mock_result = OrderResult(order_id="999", status="PreSubmitted", broker="ibkr_paper")
    mock_execute = mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=mock_result
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50,
    )
    svc.arm(armed)
    fired = svc.fire()
    assert fired.result.order_id == "999"
    mock_execute.assert_called_once()
    forwarded = mock_execute.call_args.args[0]
    assert forwarded.symbol == "AAPL"
    assert forwarded.option_symbol == "AAPL260620C00185000"
    assert forwarded.action == "BUY"
    assert forwarded.quantity == 1
    assert forwarded.limit_price == 2.50
    assert svc.get_state().armed is False
    assert len(svc.get_state().history) == 1


def test_fire_when_unarmed_raises():
    svc = AutoTradeService()
    with pytest.raises(RuntimeError, match="not armed"):
        svc.fire()


def test_armed_strategy_has_entry_premium_and_portfolio_value():
    s = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=50_000.0,
    )
    assert s.entry_premium == 2.50
    assert s.portfolio_value == 50_000.0


def test_fire_blocked_when_exposure_cap_breached(mocker):
    """fire() raises RuntimeError when single-trade exposure would exceed the cap.
    portfolio_value=50_000, max_single=5% → max capital_at_risk = $2,500
    entry_premium=30.0 × 1 contract × 100 multiplier = $3,000 → exceeds cap"""
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.portfolio_risk.account_value", return_value=50000)
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="x", status="PreSubmitted", broker="ibkr_paper"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=30.0, conid=None,
        entry_premium=30.0, portfolio_value=50_000.0,
    )
    svc.arm(armed)
    with pytest.raises(RuntimeError, match="Exposure cap"):
        svc.fire(portfolio_snapshot=[])


def test_fire_passes_when_within_cap(mocker):
    """fire() executes when trade is within exposure limit."""
    from app.data.ibkr_paper import OrderResult
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mock_execute = mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="ok", status="PreSubmitted", broker="ibkr_paper"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=50_000.0,
    )
    svc.arm(armed)
    fired = svc.fire(portfolio_snapshot=[])
    assert fired.result.order_id == "ok"
    mock_execute.assert_called_once()
    forwarded = mock_execute.call_args.args[0]
    assert forwarded.symbol == "AAPL"
    assert forwarded.quantity == 1
    assert forwarded.limit_price == 2.50


def test_fire_no_snapshot_skips_check(mocker):
    """fire() with no portfolio_snapshot still executes (backward compat).

    portfolio_value=200_000 keeps this trade ($30 × 1 × 100 × 0.60 = $1,800)
    well inside the daily loss limit ($4,000) so only the exposure-cap path
    is tested here, not the circuit breaker.
    """
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.portfolio_risk.account_value", return_value=200000)
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="y", status="PreSubmitted", broker="ibkr_paper"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=30.0, conid=None,
        entry_premium=30.0, portfolio_value=200_000.0,   # would fail cap if snapshot provided
    )
    svc.arm(armed)
    fired = svc.fire()   # no portfolio_snapshot → cap check skipped
    assert fired.result.order_id == "y"


def test_orm_positions_to_risk_converts_correctly():
    from app.services.portfolio_risk import orm_positions_to_risk

    class FakeORM:
        symbol = "AAPL"
        contract = "AAPL|185|2026-06-20|C"
        entry_price = 2.50
        qty = 2

    positions = orm_positions_to_risk([FakeORM()])
    assert len(positions) == 1
    p = positions[0]
    assert p.symbol == "AAPL"
    assert p.contract_id == "AAPL|185|2026-06-20|C"
    assert p.contracts == 2
    assert p.entry_premium == 2.50
    assert p.capital_at_risk == 2.50 * 2 * 100


def test_orm_positions_to_risk_skips_zero_qty():
    from app.services.portfolio_risk import orm_positions_to_risk

    class ZeroQtyORM:
        symbol = "MSFT"
        contract = "MSFT|300|2026-06-20|C"
        entry_price = 5.0
        qty = 0

    positions = orm_positions_to_risk([ZeroQtyORM()])
    assert positions == []


def test_maybe_fire_on_scan_disarms_stale_order(mocker):
    """An order armed more than max_arm_age_minutes ago must be disarmed without firing.

    STUBS THE DELIVERY CHANNEL since F3 put an alert on this path. Without it
    this test reaches the real `notify_alert` and only stays quiet because the
    ambient `masterEnabled` happens to be off — so a machine configured with
    live Gmail or Telegram credentials would have the suite send Kenneth a real
    page. That is the same class of leak target 2a round 3 found (tests writing
    real runtime state) and conftest's `_isolate_alert_dedup_state` covers only
    the dedup file, not the send.
    """
    from datetime import timedelta
    from app.data.ibkr_paper import OrderResult

    _capture_alerts(mocker)
    svc = AutoTradeService()
    mock_execute = mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="stale", status="PreSubmitted", broker="ibkr_paper"),
    )
    # Arm with a timestamp 60 minutes in the past
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=60)
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50,
        armed_at=stale_time,
    )
    svc.arm(armed)
    svc.maybe_fire_on_scan()   # should disarm, not fire
    mock_execute.assert_not_called()
    assert svc.get_state().armed is False


def test_fire_blocked_records_cap_blocked_history(mocker):
    """Exposure cap breach must be written to history so the event is not lost."""
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.portfolio_risk.account_value", return_value=50000)
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="x", status="PreSubmitted", broker="ibkr_paper"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=30.0, conid=None,
        entry_premium=30.0, portfolio_value=50_000.0,
    )
    svc.arm(armed)
    with pytest.raises(RuntimeError, match="Exposure cap"):
        svc.fire(portfolio_snapshot=[])
    history = svc.get_state().history
    assert len(history) == 1
    assert history[0]["status"] == "cap_blocked"
    assert history[0]["order_id"] is None


def test_fire_failed_order_records_order_failed_history(mocker):
    """Broker execute failure must be written to history with status 'order_failed'."""
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch(
        "app.services.auto_trader.execute_option_order",
        side_effect=RuntimeError("broker timeout"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50,
    )
    svc.arm(armed)
    with pytest.raises(RuntimeError, match="Order failed"):
        svc.fire()
    history = svc.get_state().history
    assert len(history) == 1
    assert history[0]["status"] == "order_failed"
    assert history[0]["order_id"] is None


def test_maybe_fire_on_scan_fires_fresh_order(mocker):
    """An order armed recently must still fire normally."""
    from app.data.ibkr_paper import OrderResult

    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mock_execute = mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="fresh", status="PreSubmitted", broker="ibkr_paper"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50,
        # armed_at defaults to now via field(default_factory=...)
    )
    svc.arm(armed)
    svc.maybe_fire_on_scan()
    mock_execute.assert_called_once()


# ── Daily loss circuit breaker (Task 5) ──────────────────────────────────────

def _make_armed(symbol="AAPL", premium=2.50, qty=1, pv=100_000.0):
    return ArmedStrategy(
        broker="ibkr_paper", symbol=symbol,
        option_symbol=f"{symbol}260620C00185000",
        action="BUY", direction="Bullish", quantity=qty, order_type="LMT",
        limit_price=premium, conid=None,
        entry_premium=premium, portfolio_value=pv,
    )


def test_daily_loss_blocks_fire_when_limit_exceeded(mocker):
    """If today's premium_at_risk already exceeds the daily limit, fire raises."""
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 return_value=OrderResult("x", "ok", "ibkr_paper"))

    svc = AutoTradeService()
    # Inject history: one entry today with large premium_at_risk
    today = datetime.now(timezone.utc).date().isoformat()
    svc._state.history.append({
        "order_id": "prev1",
        "status": "ok",
        "broker": "ibkr_paper",
        "symbol": "NVDA",
        "option": "NVDA_opt",
        "timestamp": f"{today}T10:00:00+00:00",
        "premium_at_risk": 2500.0,   # $2,500 already at risk (> 2% of $100k = $2,000)
    })

    svc.arm(_make_armed(premium=1.0, qty=1, pv=100_000.0))
    with pytest.raises(RuntimeError, match="Daily loss limit"):
        svc.fire()

    # Must be disarmed after the block (fail-closed)
    assert svc.get_state().armed is False


def test_daily_loss_block_records_daily_loss_blocked_history(mocker):
    """Regression: a fire blocked by the daily-loss circuit breaker left no
    history entry at all, unlike the cap_blocked path immediately above it —
    a blocked fire vanished without an audit trail. Must append a
    'daily_loss_blocked' entry before re-raising, mirroring cap_blocked."""
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 return_value=OrderResult("x", "ok", "ibkr_paper"))

    svc = AutoTradeService()
    today = datetime.now(timezone.utc).date().isoformat()
    svc._state.history.append({
        "order_id": "prev1",
        "status": "ok",
        "broker": "ibkr_paper",
        "symbol": "NVDA",
        "option": "NVDA_opt",
        "timestamp": f"{today}T10:00:00+00:00",
        "premium_at_risk": 2500.0,   # already over the $2,000 (2% of $100k) limit
    })

    svc.arm(_make_armed(symbol="AAPL", premium=1.0, qty=1, pv=100_000.0))
    with pytest.raises(RuntimeError, match="Daily loss limit"):
        svc.fire()

    history = svc.get_state().history
    assert history[-1]["status"] == "daily_loss_blocked"
    assert history[-1]["order_id"] is None
    assert history[-1]["symbol"] == "AAPL"
    assert history[-1]["broker"] == "ibkr_paper"


def test_daily_loss_allows_fire_when_under_limit(mocker):
    """If today's premium_at_risk is under the limit, fire proceeds."""
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mock_exec = mocker.patch("app.services.auto_trader.execute_option_order",
                              return_value=OrderResult("y", "ok", "ibkr_paper"))

    svc = AutoTradeService()
    today = datetime.now(timezone.utc).date().isoformat()
    svc._state.history.append({
        "order_id": "prev1", "status": "ok", "broker": "ibkr_paper",
        "symbol": "TSLA", "option": "TSLA_opt",
        "timestamp": f"{today}T10:00:00+00:00",
        "premium_at_risk": 500.0,    # only $500 used — well under $2,000
    })

    svc.arm(_make_armed(premium=1.0, qty=1, pv=100_000.0))
    svc.fire()   # should not raise
    mock_exec.assert_called_once()


def test_daily_loss_ignores_prior_day_entries(mocker):
    """History entries from prior UTC days must not count toward today's limit."""
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 return_value=OrderResult("z", "ok", "ibkr_paper"))

    svc = AutoTradeService()
    svc._state.history.append({
        "order_id": "old", "status": "ok", "broker": "ibkr_paper",
        "symbol": "MSFT", "option": "MSFT_opt",
        "timestamp": "2020-01-01T10:00:00+00:00",   # old date
        "premium_at_risk": 9999.0,   # huge — but from a prior day
    })

    svc.arm(_make_armed(premium=1.0, qty=1, pv=100_000.0))
    svc.fire()   # must not raise
    assert svc.get_state().armed is False


# ── Halt check (Task 6) ───────────────────────────────────────────────────────

def test_fire_blocked_when_market_closed(mocker):
    """If _market_is_open returns False, fire raises without disarming."""
    mocker.patch("app.services.auto_trader._market_is_open", return_value=False)
    svc = AutoTradeService()
    svc.arm(_make_armed())
    with pytest.raises(RuntimeError, match="Market closed"):
        svc.fire()
    # State must still be ARMED after a halt-blocked fire
    assert svc.get_state().armed is True, "Armed state must be preserved after halt block"


def test_fire_proceeds_when_market_open(mocker):
    """If _market_is_open returns True, fire executes normally."""
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 return_value=OrderResult("ord1", "ok", "ibkr_paper"))
    svc = AutoTradeService()
    svc.arm(_make_armed())
    svc.fire()
    assert svc.get_state().armed is False


# ── Vol-scaled sizing (Task 8) ─────────────────────────────────────────────────

def test_vol_sizing_halves_quantity_at_low_conviction(mocker):
    """NEUTRAL conviction, full=40, min_mult=0.3 → mult 0.65 → 2 rounds to 1.

    Was conviction=20 under the one-sided ramp, where 20 gave 0.65. Two-sided,
    20 gives 0.825 and a qty-2 order no longer reduces at all — so the fixture
    moved to the conviction that still exercises this branch rather than the
    assertion moving to match. The branch under test is "a sub-full conviction
    rewrites the quantity", and neutral is now the honest example of one.
    """
    from app.data.ibkr_paper import OrderResult
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("s1", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    import app.services.auto_trader as at
    _forbid_spx_cache(mocker)
    mocker.patch.object(at, "_measure_trade_regime", return_value=(0, "Fragile"))

    svc = AutoTradeService()
    strategy = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=2, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    )
    svc.arm(strategy)
    svc.fire()
    assert captured.get("quantity") == 1, "Low conviction must halve quantity from 2 to 1"


def test_vol_sizing_keeps_full_quantity_at_high_conviction(mocker):
    """Own conviction +50, full=40 → mult capped at 1.0 → quantity unchanged."""
    from app.data.ibkr_paper import OrderResult
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("s2", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    import app.services.auto_trader as at
    _forbid_spx_cache(mocker)
    mocker.patch.object(at, "_measure_trade_regime", return_value=(50, "Fragile"))

    svc = AutoTradeService()
    strategy = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    )
    svc.arm(strategy)
    svc.fire()
    assert captured.get("quantity") == 4, "High conviction must not reduce quantity"


def test_vol_sizing_floors_when_the_symbols_regime_cannot_be_measured(mocker):
    """SIZING-4: an unmeasurable regime sizes at the min_mult FLOOR, not full.

    This was `test_vol_sizing_skipped_when_conviction_is_none`, which asserted
    FULL size on a cold SPX cache -- the abstain-to-full-size shape Kenneth's
    decision rules out (SIZING-4-UNMEASURED-FLOOR-2026-09-24): the largest
    position on the worst input. The gate still abstains and lets it through;
    sizing now bounds it. qty 3 * 0.30 = 0.9 -> round -> 1 (and `max(1, ...)`
    keeps it an order, as the gate intends).
    """
    from app.data.ibkr_paper import OrderResult
    import app.services.auto_trader as at
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("s3", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    _forbid_spx_cache(mocker)
    mocker.patch.object(at, "_measure_trade_regime", return_value=None)

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=10, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    ))
    svc.fire()
    assert captured.get("quantity") == 3, "10 * min_mult 0.30 -> 3, never the full 10"
    last = svc.get_state().history[-1]
    assert last["sizing"] == "floor:unmeasured"
    assert last["regime_gate"] == "abstained", (
        "the gate's fail-open posture is unchanged -- only the SIZE is bounded"
    )


# ── Direction-aware sizing: the trade's own frame ─────────────────────────────
#
# SINCE SIZING-4 sizing reads the traded symbol's own measurement, which
# `compute_omm(direction=...)` returns ALREADY IN THE TRADE'S FRAME: +40 means
# "the symbol's regime favours this trade", whether the trade is a call or a
# put. So these tests stub the measurement in the trade's frame and there is NO
# MIRROR left in auto_trader.py to pin -- what they pin instead is that none is
# applied (a bearish trade the regime favours sizes FULL; a double mirror would
# floor it). Before SIZING-4 they fed a bullish-frame SPX number and pinned the
# `-conviction` mirror; the rows below are the same ramp points restated in the
# trade's frame.
#
# EVERY TEST BELOW ARMS quantity=4, AND THAT IS LOAD-BEARING. `_apply_vol_sizing`
# does `max(1, floor(quantity * mult))` (`_sized_quantity`), so at quantity=1
# the multipliers 0.30, 0.65 and 1.00 ALL give 1. At 4 they separate: 0.30 -> 1,
# 0.65 -> 2, 1.00 -> 4. -20 (0.475) and -40 (0.30) still both give 1 here; see
# test_regime_sizing_parity.py for a quantity where the opposed half separates.
#
# Stability is "Fragile" throughout: with the shipped
# `require_stable_for_reject: true` the gate cannot REJECT a Fragile regime, so
# every row reaches sizing and the assertion is about SIZE alone.

def _fired_quantity(mocker, *, direction: str, conviction: float,
                    quantity: int = 4, action: str = "BUY") -> int:
    """Arm one trade, fire it with its OWN regime measured at `conviction` (in
    the trade's frame), and return the quantity that reached the broker.

    The option right follows `direction`, so for the default action="BUY" the
    fixture is a coherent position: a bearish single-leg option is a long put.

    THAT COHERENCE DOES NOT EXTEND TO action="SELL". With `effect` hardcoded to
    OPEN, SELL+Bullish builds a short call -- a BEARISH position wearing a
    "Bullish" label. Exactly one caller passes SELL
    (`test_vol_sizing_ignores_action_entirely`) and it does so deliberately, to
    prove the sizing expression ignores `action`. It is reachable only through
    this dataclass: `ArmRequest.action` is Literal["BUY"], so that body is a
    422 at the HTTP door
    (test_auto_trade.py::test_arm_refuses_sell_because_it_would_be_a_naked_short).
    """
    from app.data.ibkr_paper import OrderResult
    import app.services.auto_trader as at
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("dir", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    _forbid_spx_cache(mocker)
    mocker.patch.object(at, "_measure_trade_regime",
                        return_value=(conviction, "Fragile"))

    right = "C" if direction == "Bullish" else "P"
    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol=f"AAPL260620{right}00185000",
        action=action, direction=direction, quantity=quantity, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    ))
    svc.fire()
    return captured.get("quantity")


def _research_sized_quantity(mocker, *, conviction: float, quantity: int = 4) -> int:
    """Pin Bearish sizing arithmetic independently of P0B's live-fire refusal."""
    import app.services.auto_trader as at
    _forbid_spx_cache(mocker)
    mocker.patch.object(at, "_measure_trade_regime",
                        return_value=(conviction, "Fragile"))
    strategy = dataclasses.replace(_make_armed(qty=quantity), direction="Bearish")
    return at._apply_vol_sizing(strategy).quantity


def test_research_vol_sizing_bearish_cut_to_floor_when_its_regime_strongly_opposes(mocker):
    """A long put whose own regime reads -80 in its frame is cut to the floor.

    floor(4 * 0.30) = 1.
    """
    assert _research_sized_quantity(mocker, conviction=-80) == 1


def test_research_vol_sizing_bearish_floors_at_the_ramp_end(mocker):
    """Bearish, own regime -40 (the ramp's lower end): 0.30 floor -> 1."""
    assert _research_sized_quantity(mocker, conviction=-40) == 1


def test_research_vol_sizing_bearish_is_GRADED_when_the_regime_opposes(mocker):
    """Bearish, own regime -20: 0.475 -> 1.9, ROUNDED DOWN to 1.

    The two-sided ramp grades the opposed half: this sits between the floor at
    -40 and the midpoint at 0. Was round(1.9) = 2 until decision
    P3B-CONTRACT-SIZING-ROUNDS-DOWN-2026-09-25 (floor, never sizes up); the
    grading itself is pinned by the 3 at +20 and the 2 at 0.
    """
    assert _research_sized_quantity(mocker, conviction=-20) == 1


def test_research_vol_sizing_bearish_scales_up_when_regime_favours(mocker):
    """Bearish, own regime +20: 0.825 -> round(3.3) = 3.

    THE ONLY FAVOURING CASE INSIDE THE RAMP, so the one that would notice a
    later change to `full_conviction_pct` (40 today).
    """
    assert _research_sized_quantity(mocker, conviction=20) == 3


def test_research_vol_sizing_bearish_full_size_when_its_regime_strongly_favours(mocker):
    """Bearish, own regime +40 in its frame -> cap 1.00 -> 4.

    THE NO-DOUBLE-MIRROR PIN. The measurement is already in the put's frame,
    so re-applying the old `-conviction` mirror would read -40 and FLOOR this
    at 1 -- the smallest position into the regime that most favours it.
    """
    assert _research_sized_quantity(mocker, conviction=40) == 4


def test_research_vol_sizing_bearish_at_neutral_conviction_sits_mid_ramp(mocker):
    """Bearish at 0 -> the ramp's MIDPOINT 0.65 -> 2.6, rounded DOWN to 2
    (was round() = 3 until P3B-CONTRACT-SIZING-ROUNDS-DOWN-2026-09-25)."""
    assert _research_sized_quantity(mocker, conviction=0) == 2


def test_vol_sizing_bullish_full_size_at_high_conviction_unchanged(mocker):
    """Bullish, own +40 -> cap 1.00 -> 4."""
    assert _fired_quantity(mocker, direction="Bullish", conviction=40) == 4


def test_vol_sizing_bullish_floors_at_negative_conviction_unchanged(mocker):
    """Bullish, own -40 -> 0.30 floor -> 1."""
    assert _fired_quantity(mocker, direction="Bullish", conviction=-40) == 1


def test_vol_sizing_ignores_action_entirely(mocker):
    """`action` must not influence size, in either direction.

    action="SELL" with direction="Bullish" at own +80: mult caps at 1.00 -> 4.
    The long-retired `action` inference took a `100 - 80 = 20` branch here
    (-> 3), so the row still discriminates if it is ever reinstated. Reachable
    only by constructing ArmedStrategy directly -- see `_fired_quantity`.
    """
    assert _fired_quantity(mocker, direction="Bullish", conviction=80, action="SELL") == 4


# ── entry_premium guard (Task 5) ──────────────────────────────────────────────

def test_arm_raises_if_entry_premium_is_zero():
    """arm() must refuse a zero entry_premium — exposure check would be silently bypassed."""
    svc = AutoTradeService()
    with pytest.raises(ValueError, match="entry_premium"):
        svc.arm(ArmedStrategy(
            broker="ibkr_paper",
            symbol="AAPL",
            option_symbol="AAPL260620C00185000",
            action="BUY", direction="Bullish",
            quantity=1,
            order_type="LMT",
            limit_price=2.50,
            conid=None,
            entry_premium=0.0,
        ))


def test_arm_raises_if_entry_premium_negative():
    svc = AutoTradeService()
    with pytest.raises(ValueError, match="entry_premium"):
        svc.arm(ArmedStrategy(
            broker="ibkr_paper",
            symbol="AAPL",
            option_symbol="AAPL260620C00185000",
            action="BUY", direction="Bullish",
            quantity=1,
            order_type="LMT",
            limit_price=2.50,
            conid=None,
            entry_premium=-1.0,
        ))


def test_arm_succeeds_with_positive_entry_premium():
    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper",
        symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish",
        quantity=1,
        order_type="LMT",
        limit_price=2.50,
        conid=None,
        entry_premium=2.50,
    ))
    assert svc.get_state().armed is True


# ── §9.1 fail closed: a config the sizing path cannot honour stops the trade ──
#
# Kenneth, 2026-09-17. The earlier posture was "a bad config restricts the scan
# and nothing else", decided on the belief that nothing outside the scan touches
# money. regime_sizing multiplies the quantity of a live broker order, so the
# belief was wrong and the posture is amended here. Every test below used to
# describe a fire at FULL SIZE.

def _sizing_strategy(quantity: int = 4) -> ArmedStrategy:
    return ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=quantity, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    )


def test_an_unreadable_scoring_file_refuses_instead_of_firing_full(mocker, tmp_path):
    """_load_scoring_config used to swallow any read error into {}, which reads
    as "sizing disabled" — the largest possible order from the loudest possible
    failure."""
    import app.services.auto_trader as at
    from app.scoring.conviction_sizing import SizingConfigError

    mocker.patch.object(at, "_SCORING_CONFIG_PATH", tmp_path / "gone.yaml")
    at._load_scoring_doc.cache_clear()
    try:
        with pytest.raises(SizingConfigError):
            at._load_scoring_config()
    finally:
        at._load_scoring_doc.cache_clear()


def test_a_file_that_parses_to_a_non_mapping_refuses(mocker, tmp_path):
    import app.services.auto_trader as at
    from app.scoring.conviction_sizing import SizingConfigError

    bad = tmp_path / "scoring_rules.yaml"
    bad.write_text("- not\n- a mapping\n")
    mocker.patch.object(at, "_SCORING_CONFIG_PATH", bad)
    at._load_scoring_doc.cache_clear()
    try:
        with pytest.raises(SizingConfigError):
            at._load_scoring_config()
    finally:
        at._load_scoring_doc.cache_clear()


def test_an_absent_block_now_refuses(mocker, tmp_path):
    """INVERTED by DOCC-1 (decision DOCC-9.6-MONEY-BLOCKS-REQUIRED-2026-09-28).
    This was `test_an_absent_block_is_still_sizing_off_not_a_failure`: a file
    that parsed and said nothing about regime_sizing turned sizing OFF and the
    order went at full size. An absent money block now refuses the fire with a
    SizingConfigError (MoneyConfigError) naming it; off is `enabled: false`."""
    import yaml
    import app.services.auto_trader as at
    from app.scoring.conviction_sizing import SizingConfigError
    from tests.conftest import shipped_scoring_doc

    f = tmp_path / "scoring_rules.yaml"
    f.write_text(yaml.safe_dump(shipped_scoring_doc(drop=("regime_sizing",))))
    mocker.patch.object(at, "_SCORING_CONFIG_PATH", f)
    at._load_scoring_doc.cache_clear()
    try:
        with pytest.raises(SizingConfigError, match="regime_sizing"):
            at._load_scoring_config()
        with pytest.raises(SizingConfigError, match="regime_sizing"):
            at._apply_vol_sizing(_sizing_strategy(4))
    finally:
        at._load_scoring_doc.cache_clear()


def test_a_broken_block_refuses_before_the_conviction_lookup(mocker):
    """Order matters: a config the process already knows it cannot honour must
    refuse BEFORE the symbol's regime is measured -- it must not first buy a
    bounded bar fetch, and a measurement that fails must not mask it. (Before
    SIZING-4 the lookup was the SPX cache; it is now the per-symbol
    measurement, and the order is the same.)"""
    import app.services.auto_trader as at
    from app.scoring.conviction_sizing import SizingConfigError

    mocker.patch.object(at, "_load_scoring_config",
                        return_value={"enabled": True, "min_mult": 0.3,
                                      "full_conviction_pct": -40})
    _forbid_spx_cache(mocker)
    measure = mocker.patch.object(at, "_measure_trade_regime", return_value=None)
    with pytest.raises(SizingConfigError):
        at._apply_vol_sizing(_sizing_strategy(4))
    measure.assert_not_called()


def test_fire_sends_nothing_records_the_refusal_and_stays_disarmed(mocker):
    import app.services.auto_trader as at
    from app.scoring.conviction_sizing import SizingConfigError

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    mocker.patch.object(at, "_load_scoring_config",
                        return_value={"enabled": True, "min_mult": "half",
                                      "full_conviction_pct": 40})

    svc = AutoTradeService()
    svc.arm(_sizing_strategy(4))
    with pytest.raises(SizingConfigError):
        svc.fire()

    execute.assert_not_called()
    state = svc.get_state()
    assert state.armed is False
    assert state.strategy is None
    last = state.history[-1]
    assert last["status"] == "sizing_config_blocked"
    assert last["order_id"] is None
    assert last["premium_at_risk"] == 0.0
    assert "min_mult" in last["error"]


def test_the_scan_trigger_alerts_because_nobody_is_reading_it(mocker):
    """POST /scan runs maybe_fire_on_scan through asyncio.to_thread and discards
    the outcome, so the refusal has no reader. §9.1 is "refuse AND alert"."""
    import app.services.auto_trader as at

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order")
    mocker.patch.object(at, "_load_scoring_config",
                        return_value={"enabled": True, "min_mult": "half",
                                      "full_conviction_pct": 40})
    alert = mocker.patch.object(at, "_alert_sizing_config_refusal")

    svc = AutoTradeService()
    svc.arm(_sizing_strategy(4))
    svc.maybe_fire_on_scan()          # must not raise — this is a fire-and-forget trigger

    assert alert.call_count == 1
    assert alert.call_args.args[0] == "AAPL"
    assert svc.get_state().armed is False


def test_the_alert_reaches_the_channel_that_reaches_a_phone(mocker):
    """notify_alert, not alert_service.broadcast: nothing in the frontend
    subscribes to /ws/alerts, so a broadcast would be a channel with no reader."""
    import app.services.auto_trader as at
    from app.scoring.conviction_sizing import SizingConfigError

    async def _fake_notify(**kwargs):
        captured.update(kwargs)
        return True

    captured: dict = {}
    mocker.patch("app.services.notifications.alert_notifier.notify_alert", _fake_notify)
    at._alert_sizing_config_refusal("AAPL", SizingConfigError("min_mult is not a number"))

    assert captured["symbol"] == "AAPL"
    assert captured["alert_type"] == "CONFIG_ERROR", (
        "the alert's identity is what the email subject and the dedup key are "
        "built from; TP_HIT here reads 'Bamendjou Portfolio Alert - AAPL: "
        "Target reached' for a refused order"
    )
    assert captured["rec_id"] == "auto-trade-sizing-config", (
        "symbol-independent on purpose: the FILE is broken, not the symbol, so "
        "the dedup window collapses a run of scans into one alert"
    )
    assert captured["type_enabled"] is True, (
        "CONFIG_ERROR is not in enabledTypes, so the global check would drop it"
    )
    assert "min_mult is not a number" in captured["reason"]


def test_a_dead_notifier_cannot_turn_a_safe_refusal_into_a_crash(mocker):
    import app.services.auto_trader as at
    from app.scoring.conviction_sizing import SizingConfigError

    async def _boom(**kwargs):
        raise OSError("smtp is down")

    mocker.patch("app.services.notifications.alert_notifier.notify_alert", _boom)
    at._alert_sizing_config_refusal("AAPL", SizingConfigError("bad"))   # must not raise


def test_the_alert_is_skipped_loudly_when_it_would_crash_on_a_running_loop(caplog):
    """asyncio.run raises inside a thread that already has a loop, so the
    helper must degrade to a log line rather than replacing a refusal with a
    RuntimeError from asyncio.

    THE BRANCH IS UNREACHABLE TODAY and this docstring used to claim the
    opposite (round 2): the helper's only caller is maybe_fire_on_scan, whose
    only caller is POST /scan via asyncio.to_thread — always a worker thread
    with no loop. It is pinned because the cost of being wrong about that
    later is section 9.1's "and alert" half silently not happening."""
    import asyncio
    import app.services.auto_trader as at
    from app.scoring.conviction_sizing import SizingConfigError

    async def _from_the_loop():
        with caplog.at_level("ERROR", logger="app.services.auto_trader"):
            at._alert_sizing_config_refusal("AAPL", SizingConfigError("bad"))

    asyncio.run(_from_the_loop())
    assert "NOT alerted" in caplog.text


def test_a_suppressed_alert_is_not_mistaken_for_a_delivered_one(mocker, caplog):
    """notify_alert returns False for the master kill switch, an armed dedup
    window and a genuine delivery failure alike. Discarding that return makes
    §9.1's "and alert" half a silent no-op — which is the class of defect this
    whole change exists to close, so it must not be reintroduced by the fix."""
    import app.services.auto_trader as at
    from app.scoring.conviction_sizing import SizingConfigError

    async def _suppressed(**kwargs):
        return False

    mocker.patch("app.services.notifications.alert_notifier.notify_alert", _suppressed)
    with caplog.at_level("ERROR", logger="app.services.auto_trader"):
        at._alert_sizing_config_refusal("AAPL", SizingConfigError("bad"))
    assert "NOT delivered" in caplog.text


def test_a_full_size_multiplier_still_leaves_a_trace(mocker, caplog):
    """The one outcome worth noticing was the only silent one: every config that
    resolved to mult 1.0 returned before the log line, so a bad-but-honourable
    file sized at full with nothing written anywhere. Round 1 measured that."""
    import app.services.auto_trader as at

    mocker.patch.object(at, "_load_scoring_config", return_value={
        "enabled": True, "min_mult": 0.3, "full_conviction_pct": 40,
    })
    _forbid_spx_cache(mocker)
    mocker.patch.object(at, "_measure_trade_regime", return_value=(90, "Fragile"))

    with caplog.at_level("INFO", logger="app.services.auto_trader"):
        out = at._apply_vol_sizing(_sizing_strategy(10))
    assert out.quantity == 10
    assert "unchanged" in caplog.text
    assert "mult=1.00" in caplog.text


def test_a_bad_conviction_is_recorded_and_alerted_like_a_bad_config(mocker):
    """Round 1 stopped a regime_monitor DATA fault being reported as a broken
    config file — correctly — by raising a plain ValueError, and thereby walked
    the refusal out of fire()'s handler entirely: no history entry, no alert,
    /auto-trade/status still naming the PREVIOUS order as last_order. Nothing
    shipped, so it was below the gate, but it was strictly worse than what it
    replaced on both halves of §9.1. Round 2 measured it across three trees."""
    import app.services.auto_trader as at

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    mocker.patch.object(at, "_load_scoring_config", return_value={
        "enabled": True, "min_mult": 0.3, "full_conviction_pct": 40,
    })
    # A measured conviction that is not a usable number. `compute_omm` returns
    # an int today, so this is the defensive path, stubbed at the seam sizing
    # now reads (SIZING-4) rather than at the retired SPX cache.
    _forbid_spx_cache(mocker)
    mocker.patch.object(at, "_measure_trade_regime",
                        return_value=(float("nan"), "Fragile"))
    alert = mocker.patch.object(at, "_alert_sizing_config_refusal")

    svc = AutoTradeService()
    svc.arm(_sizing_strategy(4))
    svc.maybe_fire_on_scan()

    execute.assert_not_called()
    state = svc.get_state()
    assert state.armed is False
    last = state.history[-1]
    assert last["status"] == "sizing_data_blocked", (
        "a DATA fault must be distinguishable in the history from a CONFIG "
        "fault — the remedy is different and one of them blames the file"
    )
    assert alert.call_count == 1


def test_the_alert_does_not_blame_the_file_for_a_data_fault(mocker):
    async def _fake_notify(**kwargs):
        captured.update(kwargs)
        return True

    captured: dict = {}
    import app.services.auto_trader as at
    mocker.patch("app.services.notifications.alert_notifier.notify_alert", _fake_notify)
    at._alert_sizing_config_refusal("AAPL", ValueError("conviction_pct is not finite (nan)"))
    assert "scoring_rules.yaml" not in captured["reason"]
    assert "conviction" in captured["reason"]


def test_sizing_off_by_configuration_still_leaves_a_trace(mocker, caplog):
    """The last silent full-size return (round 2): a block carrying real
    min_mult/full_conviction_pct values but `enabled: false` comes through here
    rather than through a refusal, and returned at full size with no trace."""
    import app.services.auto_trader as at
    mocker.patch.object(at, "_load_scoring_config", return_value={
        "enabled": False, "min_mult": 0.3, "full_conviction_pct": 40,
    })
    with caplog.at_level("INFO", logger="app.services.auto_trader"):
        out = at._apply_vol_sizing(_sizing_strategy(7))
    assert out.quantity == 7
    assert "off by configuration" in caplog.text


# ── regime_gate on the fire path ─────────────────────────────────────────────
#
# REWRITTEN 2026-09-19 for AUTOTRADE-GATE-INPUTS-FRESH-PER-SYMBOL-2026-09-19.
# The previous versions of these tests stubbed `get_last_conviction` /
# `get_last_stability` and asserted the verdict, which made them blind to the
# defect piece 2's round 1 actually found: the gate was reading SPX's
# market-wide regime while the scan gated each symbol on its own. A test that
# hands the gate its answer cannot notice that the answer came from the wrong
# instrument.
#
# So these drive the gate through REAL BARS and the REAL `compute_omm`, and
# assert on the three axes the finding named — WHICH SYMBOL is measured, in
# WHICH horizon window, and under WHICH thresholds.
#
# MSFT's fixture is the one that yields a measurable regime here, and only at
# the Position horizon (Swing's window returns None on 251 bars). That is not a
# limitation of the test — it is the pair that pins the horizon down: the same
# symbol and the same direction produce a verdict under Position and an
# abstention under Swing, which nothing but a real horizon-driven measurement
# does.

_FIXTURES = Path(__file__).parent / "fixtures"


def _forbid_spx_cache(mocker):
    """SIZING-4: the fire path must not read regime_monitor's SPX cache at all.

    Neither the gate (since 2026-09-19) nor sizing (since SIZING-4) reads it,
    so any call is a regression back onto the market-wide number.
    """
    return mocker.patch(
        "app.services.regime_monitor.get_last_conviction",
        side_effect=AssertionError(
            "the fire path read regime_monitor's SPX cache — sizing and the "
            "gate both read the traded symbol's own measurement since SIZING-4"
        ),
    )


def _sizing_off(mocker):
    """Switch regime_sizing OFF (an absent block) so a GATE test's fired
    quantity is the armed quantity and every assertion is about the gate.

    Before SIZING-4 these tests got that for free from an empty SPX cache
    (`conviction is None` returned the strategy unchanged). Sizing now reads
    the same measurement the gate takes, so a gate test that leaves sizing on
    is also a sizing test; the ones that want that say so explicitly.
    """
    import app.services.auto_trader as at
    _forbid_spx_cache(mocker)
    mocker.patch.object(at, "_load_scoring_config", return_value={})


def _fixture_bars(symbol: str) -> list[dict]:
    with open(_FIXTURES / f"{symbol}_candles.json") as f:
        return json.load(f)


def _gate_fire(mocker, *, symbol="MSFT", direction="Bullish", horizon="Position",
               quantity=4, bars=None, caution_pct=None, reject_pct=None,
               sizing_on=False):
    """Arm and fire with the gate driven by REAL bars through the REAL compute_omm.

    Returns (fired_quantity | None, svc, fetch_spy).

    `sizing_on` defaults to False so the fired quantity is the armed quantity
    and every assertion below is about the GATE and nothing else (see
    `_sizing_off`). With it True, the shipped regime_sizing block sizes off the
    same real measurement. Either way the SPX cache is forbidden.
    """
    from app.data.ibkr_paper import OrderResult
    captured: dict = {}

    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("gate", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    if sizing_on:
        _forbid_spx_cache(mocker)
    else:
        _sizing_off(mocker)
    fetch_spy = mocker.patch(
        "app.services.auto_trader._fetch_scan_window_bars",
        return_value=_fixture_bars(symbol) if bars is None else bars,
    )

    right = "C" if direction == "Bullish" else "P"
    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol=symbol,
        option_symbol=f"{symbol}260620{right}00185000",
        action="BUY", direction=direction, quantity=quantity, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
        horizon=horizon,
        regime_headwind_caution_pct=caution_pct,
        regime_headwind_reject_pct=reject_pct,
    ))
    svc.fire()
    return captured.get("quantity"), svc, fetch_spy


def _research_gate_sizing(mocker, *, direction="Bearish", reject_pct=None, sizing_on=False):
    """Research-only arithmetic remains available for an Unvalidated direction.

    Exercise the real sizing/regime helpers without arming or firing an order.
    P0B's live Bearish refusal is pinned in test_auto_trade_unvalidated.py.
    """
    import app.services.auto_trader as at
    if sizing_on:
        _forbid_spx_cache(mocker)
    else:
        _sizing_off(mocker)
    fetch_spy = mocker.patch("app.services.auto_trader._fetch_scan_window_bars",
                            return_value=_fixture_bars("MSFT"))
    strategy = ArmedStrategy(
        broker="ibkr_paper", symbol="MSFT", option_symbol="MSFT|185|2026-06-20|P",
        action="BUY", direction=direction, quantity=4, order_type="LMT",
        limit_price=2.5, conid=None, entry_premium=2.5, horizon="Position",
        regime_headwind_reject_pct=reject_pct,
    )
    return at._apply_vol_sizing(strategy).quantity, fetch_spy


def _no_stability_requirement(monkeypatch):
    """Drop `require_stable_for_reject` only, leaving the thresholds real.

    MSFT's fixture regime is Fragile, so with the shipped config `_regime_cap`
    cannot return REJECT at any conviction — the same structural inertness
    open_questions[0] finding (3) records for the production regime. Turning
    this one flag off is what makes the REJECT branch reachable from real bars
    instead of from a stubbed verdict.
    """
    import app.services.auto_trader as at
    real = dict(at._load_regime_gate_config())
    monkeypatch.setattr(at, "_load_regime_gate_config",
                        lambda: {**real, "require_stable_for_reject": False})


def test_research_regime_gate_measures_the_traded_symbol_and_not_the_cached_market(mocker):
    """MSFT's Bearish +50 research sizing uses its own bars, never SPX.

    The numeric research pins remain valid while P0B refuses every live
    Bearish fire before reaching the sizing helper.
    """
    qty, fetch_spy = _research_gate_sizing(mocker, sizing_on=True)
    assert qty is not None, "the symbol's own regime passes the research helper"
    assert fetch_spy.call_args.args[0] == "MSFT", (
        "the gate must fetch the TRADED symbol's bars, not a market proxy"
    )
    # SIZING-4, on the same real bars: sizing reads MSFT's own +50 in the
    # Bearish frame -> mult 1.00 -> the full 4. Under the old SPX wiring this
    # audit's reproduced case sized 2 (decision
    # AUTOTRADE-SIZING-ON-PER-SYMBOL-CONVICTION-2026-09-20's measured table).
    # The research helper forbids the SPX cache; ONE fetch serves gate and sizer.
    assert qty == 4
    assert fetch_spy.call_count == 1, "gate and sizer share one measurement"


def test_regime_gate_refuses_on_the_symbols_own_measured_regime(mocker, monkeypatch):
    """And the other half: a refusal must come from the symbol's own bars.

    MSFT Bullish at the Position horizon measures -50, at or below
    headwind_reject_pct (-40). The cache is left EMPTY, so nothing but the
    fixture can be producing this verdict.
    """
    from app.services.auto_trader import RegimeHeadwindError
    _no_stability_requirement(monkeypatch)
    with pytest.raises(RegimeHeadwindError, match=r"MSFT measured -50"):
        _gate_fire(mocker, symbol="MSFT", direction="Bullish", horizon="Position")


def test_regime_gate_message_names_the_measurement_it_refused_on(mocker, monkeypatch):
    """The refusal text is evidence, so it must carry the real numbers.

    Round 1 finding 2 was as much about the MESSAGE as the verdict: it asserted
    "the scan would have dropped this setup" while the scan had passed it. Now
    that the fire path measures what the scan measures, the claim is true — and
    the sentence has to say WHICH symbol, WHICH horizon, WHICH frame and WHAT
    number, or a post-mortem cannot check it.
    """
    from app.services.auto_trader import RegimeHeadwindError
    _no_stability_requirement(monkeypatch)
    with pytest.raises(RegimeHeadwindError) as exc:
        _gate_fire(mocker, symbol="MSFT", direction="Bullish", horizon="Position")
    msg = str(exc.value)
    for fragment in ("MSFT", "-50", "Position", "Bullish", "-40", "Fragile"):
        assert fragment in msg, f"refusal text is missing {fragment!r}: {msg}"


def test_regime_gate_uses_the_trades_own_horizon_window(mocker, monkeypatch):
    """Same symbol, same direction, same bars — a different horizon, a different
    outcome. Nothing but a genuinely horizon-driven measurement does that.

    Position (lookback 50 / window 750 / min_obs 100) yields -50 on this fixture
    and refuses. Swing (20 / 500 / 100) returns no result at all on the same 251
    bars, so the gate abstains and the trade fires. If the horizon were ignored
    — or defaulted — both cases would land on the same branch.
    """
    from app.services.auto_trader import RegimeHeadwindError
    _no_stability_requirement(monkeypatch)

    with pytest.raises(RegimeHeadwindError):
        _gate_fire(mocker, symbol="MSFT", direction="Bullish", horizon="Position")

    qty, _, _ = _gate_fire(mocker, symbol="MSFT", direction="Bullish", horizon="Swing")
    assert qty == 4, "no measurement at the Swing window -> no gate -> full size"


def test_research_regime_gate_passes_the_horizon_config_and_direction_to_compute_omm(mocker):
    """Pins the four numbers, because the outcome alone cannot distinguish them.

    A gate that used compute_omm's module defaults (20/500/100) instead of
    `regime.position` (50/750/100) would still return SOMETHING, and on another
    fixture might even agree. These are the exact values stock_scan.py and
    scan.py pass, read from the same YAML block.
    """
    import app.services.regime_omm as omm_mod
    spy = mocker.spy(omm_mod, "compute_omm")
    _research_gate_sizing(mocker)

    assert spy.call_count == 1
    kwargs = spy.call_args.kwargs
    assert kwargs["direction"] == "Bearish", "the TRADE's frame, not a hardcoded Bullish"
    assert (kwargs["lookback"], kwargs["window"], kwargs["min_obs"]) == (50, 750, 100), (
        "must be scoring_rules.yaml's regime.position block, not compute_omm's defaults"
    )


def test_step3_reject_threshold_snapshot_overrides_the_yaml(mocker, monkeypatch):
    """Round 1 finding 3: the Step-3 "Headwind reject %" now reaches the fire path.

    The same trade that refuses at the YAML -40 must fire once the armed
    strategy carries the trader's own -80, because -50 is not at or below -80.
    Both halves are asserted: an override that changed nothing would pass the
    second assertion alone.
    """
    from app.services.auto_trader import RegimeHeadwindError
    _no_stability_requirement(monkeypatch)

    with pytest.raises(RegimeHeadwindError):
        _gate_fire(mocker, symbol="MSFT", direction="Bullish", horizon="Position")

    qty, _, _ = _gate_fire(mocker, symbol="MSFT", direction="Bullish",
                           horizon="Position", reject_pct=-80)
    assert qty == 4, "the trader's own -80 says fire, so it fires"


def test_step3_snapshot_can_also_tighten_the_research_gate(mocker, monkeypatch):
    """The override is not a loosen-only knob, and a one-sided test would not say so.

    MSFT Bearish at Position measures +50 — a PASS under any sane threshold.
    A snapshot of +60 (the control's own range is -100..0, so this is past what
    the UI can send, and that is the point: the assertion is about the
    ARITHMETIC being applied, not about the UI's bounds) must refuse it.
    """
    from app.services.auto_trader import RegimeHeadwindError
    _no_stability_requirement(monkeypatch)
    with pytest.raises(RegimeHeadwindError):
        _research_gate_sizing(mocker, reject_pct=60)


def test_regime_gate_refusal_is_recorded_and_sends_nothing(mocker, monkeypatch):
    """The refusal must leave a trace AND leave nothing armed. Both, not either."""
    from app.services.auto_trader import RegimeHeadwindError
    _no_stability_requirement(monkeypatch)

    # ONE INVOCATION. This used to open with a `_gate_fire` call inside
    # `pytest.raises` whose tuple assignment could never execute (the call
    # raises), then fire a second time by hand and assert on THAT — so the test
    # fired twice, discarded the first, and silently rebound `svc`. Target 2a
    # round 1. `_gate_fire` cannot serve here because it returns the service
    # only on a successful fire, so the arm/fire is hand-rolled and the
    # assertions are unambiguously about this one service.
    from app.data.ibkr_paper import OrderResult
    sent: list = []
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 side_effect=lambda s: sent.append(s) or OrderResult("x", "ok", "ibkr_paper"))
    _sizing_off(mocker)
    mocker.patch("app.services.auto_trader._fetch_scan_window_bars", return_value=_fixture_bars("MSFT"))

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="MSFT", option_symbol="MSFT260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50, portfolio_value=100_000.0,
        horizon="Position",
    ))
    with pytest.raises(RegimeHeadwindError):
        svc.fire()

    assert sent == [], "a refused fire must not reach the broker"
    last = svc.get_state().history[-1]
    assert last["status"] == "regime_headwind_blocked", last
    assert last["order_id"] is None
    assert svc.get_state().armed is False, "disarm happens before the refusal"


def test_regime_gate_honours_require_stable_for_reject(mocker):
    """Same headwind, Fragile regime: the scan does NOT hard-drop, so neither do we.

    MSFT's fixture regime is Fragile and the shipped config has
    `require_stable_for_reject: true`, so -50 caps at CAUTION rather than
    REJECT. No monkeypatching here — this is the SHIPPED config, and it is why
    every refusal test above has to drop that flag explicitly.
    """
    qty, _, _ = _gate_fire(mocker, symbol="MSFT", direction="Bullish", horizon="Position")
    assert qty == 4, "Fragile cannot hard-drop, so it fires"


def test_regime_gate_refuses_when_no_bars_come_back(mocker):
    """No bars -> REFUSED, not abstained (P3B-REGIME-BARS-MISSING-REFUSES-2026-09-25).

    It used to abstain and fire at the armed quantity. The scan DROPS a symbol
    whose candles it cannot get, so the fire path now refuses too. (A SHORT
    series still abstains -- see the test below.)
    """
    from app.services.auto_trader import RegimeDataUnavailableError
    with pytest.raises(RegimeDataUnavailableError):
        _gate_fire(mocker, symbol="MSFT", direction="Bullish",
                   horizon="Position", bars=[])


def test_regime_gate_still_abstains_on_a_short_series(mocker, caplog):
    """Bars that arrived but are under min_obs -> no gate, said out loud.

    The scan runs no regime gate on a series it cannot measure, so this half
    stays fail-OPEN.
    """
    short = _fixture_bars("MSFT")[:5]
    with caplog.at_level("WARNING", logger="app.services.auto_trader"):
        qty, svc, _ = _gate_fire(mocker, symbol="MSFT", direction="Bullish",
                                 horizon="Position", bars=short)
    assert qty == 4
    assert "NOT evaluated" in caplog.text and "MSFT" in caplog.text
    assert svc.get_state().history[-1]["regime_gate"] == "abstained"


def test_regime_gate_abstains_when_the_armed_strategy_carries_no_horizon(mocker, caplog):
    """A direct constructor with no horizon must not silently lose the gate.

    Unreachable through `/auto-trade/arm` (the field is required there, so a
    body without it is a 422), but `ArmedStrategy` is a plain dataclass and
    tests and future non-HTTP producers construct it directly.
    """
    with caplog.at_level("WARNING", logger="app.services.auto_trader"):
        qty, _, _ = _gate_fire(mocker, symbol="MSFT", direction="Bullish", horizon=None)
    assert qty == 4
    assert "carries no horizon" in caplog.text


def test_regime_gate_does_not_fire_when_disabled(mocker, monkeypatch):
    """`enabled: false` means the gate is off, not that it defaults to refusing."""
    import app.services.auto_trader as at
    monkeypatch.setattr(at, "_load_regime_gate_config", lambda: {
        "enabled": False, "headwind_caution_pct": -15,
        "headwind_reject_pct": -40, "require_stable_for_reject": False,
    })
    qty, _, fetch_spy = _gate_fire(mocker, symbol="MSFT", direction="Bullish",
                                   horizon="Position")
    assert qty == 4
    # UPDATED FOR SIZING-4, WITH THE REASON (the decision required that this
    # test be updated, never deleted). "A disabled gate never fetches" is no
    # longer the rule, because sizing now reads the same per-symbol
    # measurement and needs it whether or not the gate looks. What still holds,
    # and is pinned here, is narrower: with the gate disabled AND sizing off,
    # NOTHING reads the measurement, so nothing pays for the bars. The
    # sizing-on half is the test below.
    assert fetch_spy.call_count == 0, (
        "with the gate disabled and sizing off, nothing reads the measurement "
        "-- no bars may be fetched"
    )


def test_a_disabled_gate_still_measures_when_sizing_needs_it(mocker, monkeypatch):
    """SIZING-4: gate off, sizing on -> sizing measures on its own, once.

    MSFT Bullish at Position measures -50 in its own frame on the fixture, so
    the shipped ramp floors it: 4 * 0.30 -> 1. The gate would have capped this
    at CAUTION (Fragile), but it is disabled, so its outcome is "disabled" --
    and the size still comes from MSFT's own regime, never from SPX.
    """
    import app.services.auto_trader as at
    monkeypatch.setattr(at, "_load_regime_gate_config", lambda: {
        "enabled": False, "headwind_caution_pct": -15,
        "headwind_reject_pct": -40, "require_stable_for_reject": False,
    })
    qty, svc, fetch_spy = _gate_fire(mocker, symbol="MSFT", direction="Bullish",
                                     horizon="Position", sizing_on=True)
    assert fetch_spy.call_count == 1, "sizing needs the measurement the gate skipped"
    assert fetch_spy.call_args.args[0] == "MSFT"
    assert qty == 1, "own -50 on the shipped ramp is the 0.30 floor"
    last = svc.get_state().history[-1]
    assert last["regime_gate"] == "disabled"
    assert last["sizing"] == "measured"


def test_sizing_off_is_recorded_as_off_on_the_history_row(mocker):
    """The "sizing" field tells the three full/floor/measured cases apart."""
    qty, svc, _ = _gate_fire(mocker, symbol="MSFT", direction="Bullish",
                             horizon="Position")
    assert qty == 4
    assert svc.get_state().history[-1]["sizing"] == "off"


def test_a_broken_gate_block_refuses_before_sizing_measures(mocker, monkeypatch):
    """The lazy shared measurement must not be forced by sizing ahead of the
    gate's own config check: a gate that cannot read its rule refuses, and no
    bars are fetched for a fire that was never going to happen."""
    from app.services.auto_trader import RegimeGateConfigError
    import app.services.auto_trader as at
    monkeypatch.setattr(at, "_load_regime_gate_config",
                        lambda: {"enabled": True, "headwind_caution_pct": -15})
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    sent: list = []
    mocker.patch("app.services.auto_trader.execute_option_order",
                 side_effect=lambda s: sent.append(s))
    _forbid_spx_cache(mocker)
    measure = mocker.patch.object(at, "_measure_trade_regime")

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="MSFT", option_symbol="MSFT260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50,
        portfolio_value=100_000.0, horizon="Position",
    ))
    with pytest.raises(RegimeGateConfigError):
        svc.fire()
    measure.assert_not_called()
    assert sent == []


def test_a_caution_band_trade_is_sized_down_the_ramp_when_sizing_is_on(mocker):
    """The shipped config, real bars: MSFT Bullish Position is -50 and Fragile,
    so the gate CAUTIONs rather than refuses -- and, since SIZING-4, the SAME
    -50 sizes it at the 0.30 floor (4 -> 1). Before, a caution-band trade was
    sized off SPX and could fire at the full armed quantity."""
    qty, svc, fetch_spy = _gate_fire(mocker, symbol="MSFT", direction="Bullish",
                                     horizon="Position", sizing_on=True)
    assert qty == 1
    assert fetch_spy.call_count == 1
    last = svc.get_state().history[-1]
    assert last["regime_gate"] == "caution"
    assert last["sizing"] == "measured"


def test_regime_gate_still_refuses_when_regime_sizing_is_disabled(mocker, monkeypatch):
    """`regime_sizing.enabled: false` must NOT switch the headwind gate off.

    Piece 2 round 1 finding 1. `_apply_regime_gate` lives inside
    `_apply_vol_sizing`, which used to `return strategy` as soon as
    `resolve_sizing` reported sizing off — so turning off one feature silently
    turned off a different, independently configured one, and the trade went to
    the broker at the FULL armed quantity. That is worse than the behaviour the
    gate replaced, which at least sized a headwind trade down to min_mult.

    Measured before that fix: this exact setup FIRED at the full armed quantity.
    The sharp edge is that conviction_sizing.py's own SizingConfigError text
    advises "To stop trading in a headwind, disable regime_sizing or raise the
    gate" — following the codebase's own advice disabled the gate.
    """
    import app.services.auto_trader as at
    from app.services.auto_trader import RegimeHeadwindError
    _no_stability_requirement(monkeypatch)

    doc = at._load_scoring_doc()
    real_sizing = dict(doc.get("regime_sizing") or {})
    monkeypatch.setitem(doc, "regime_sizing", {**real_sizing, "enabled": False})

    # Sanity: sizing really is off down this path, so the test would pass
    # vacuously if the gate had simply moved rather than been decoupled.
    from app.scoring.conviction_sizing import resolve_sizing
    assert resolve_sizing(at._load_scoring_config()) is None

    with pytest.raises(RegimeHeadwindError, match="regime headwind"):
        _gate_fire(mocker, symbol="MSFT", direction="Bullish", horizon="Position")


def _gate_fire_measured(mocker, measured, *, direction="Bullish", quantity=4,
                        gate_cfg=None, monkeypatch=None):
    """Fire with `_measure_trade_regime` STUBBED to `measured`, gate config REAL.

    THE DELIBERATE INVERSE OF `_gate_fire`, and target 2a round 1 is why both
    have to exist. `_gate_fire` drives real bars through the real `compute_omm`,
    which is what pins WHICH SYMBOL and WHICH WINDOW are measured — but it can
    only ever produce the verdicts this repo's fixtures happen to yield, and
    those are: Fragile, or nothing at all. Measured across every fixture at
    every horizon, the maximum `p_stay` is 0.50 against `regime_omm`'s 0.75
    Stable threshold, and 16 of the 24 symbol x horizon x direction
    combinations return None.
    **No fixture in this repository produces a Stable regime.** With
    `require_stable_for_reject: true` shipped, `_regime_cap` therefore CANNOT
    reject through `_gate_fire`, and every refusal test above has to drop that
    flag to reach the branch.

    That left the branch that refuses REAL TRADES UNDER THE SHIPPED CONFIG
    covered by nothing at any level of this path. Stubbing the measurement is
    what buys it back: the gate's own rule, thresholds and plumbing stay real,
    and only the number the market would have supplied is supplied by the test.
    A stub is the wrong tool for "which instrument is measured" and the right
    one for "what does the rule do with this measurement" — so the two helpers
    cover the two halves, and neither can substitute for the other.
    """
    from app.data.ibkr_paper import OrderResult
    import app.services.auto_trader as at
    captured: dict = {}

    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("gate", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    _sizing_off(mocker)
    mocker.patch.object(at, "_measure_trade_regime", return_value=measured)
    if gate_cfg is not None:
        assert monkeypatch is not None, "gate_cfg needs monkeypatch"
        monkeypatch.setattr(at, "_load_regime_gate_config", lambda: gate_cfg)

    right = "C" if direction == "Bullish" else "P"
    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="MSFT",
        option_symbol=f"MSFT260620{right}00185000",
        action="BUY", direction=direction, quantity=quantity, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50,
        portfolio_value=100_000.0, horizon="Position",
    ))
    svc.fire()
    return captured.get("quantity"), svc


def test_regime_gate_refuses_under_the_SHIPPED_config_when_the_regime_is_stable(mocker):
    """THE BRANCH THAT REFUSES REAL TRADES, under the config that actually ships.

    Target 2a round 1: `require_stable_for_reject: true` is shipped, no fixture
    in this repo produces a Stable regime, and every other refusal test drops
    that flag — so the production refusal path was exercised by NOTHING, and a
    change that silently stopped the gate from ever rejecting (a renamed or
    re-typed stability, `"STABLE"`, an enum member) would have left all 64 tests
    green while the gate never fired again in production.

    No monkeypatch of the gate config here. That is the whole point: this is
    scoring_rules.yaml's own `regime_gate` block, `require_stable_for_reject`
    included.
    """
    from app.services.auto_trader import RegimeHeadwindError
    with pytest.raises(RegimeHeadwindError, match=r"MSFT measured -50"):
        _gate_fire_measured(mocker, (-50, "Stable"))


def test_regime_gate_stability_is_compared_by_the_exact_string_compute_omm_emits(mocker):
    """The companion to the test above: the rule matches ONE exact string.

    WHAT THIS DOES NOT DO, corrected in round 2 after the docstring claimed it
    did: it does NOT protect against `compute_omm` changing its spelling. Both
    tests in this pair go through `_gate_fire_measured`, which stubs the
    measurement and hands `_regime_cap` a literal — so if `regime_omm.py` began
    emitting "STABLE", the test above (feeding "Stable") would still pass and
    this one (feeding "STABLE") would still pass, while the gate went inert on
    the fire path. The `_gate_fire` tests cannot cover it either, because no
    fixture is Stable.

    That coupling is pinned elsewhere — `tests/test_regime_omm.py` and the
    schema literal in `app/schemas/__init__.py` — so the risk is contained, just
    not by this pair. What this pair really pins is narrower and still worth
    having: `_regime_cap`'s comparison is exact-match, so the reject branch
    cannot be reached by an approximately-right stability value.
    """
    qty, _ = _gate_fire_measured(mocker, (-50, "STABLE"))
    assert qty == 4, (
        "a stability string the rule does not recognise must not reject — and "
        "the test above proves the recognised one does, so the pair brackets "
        "the comparison"
    )


def test_regime_gate_reject_boundary_is_inclusive_on_the_fire_path(mocker):
    """`headwind_reject_pct` is -40 and the comparison is `<=`, so -40 refuses.

    Covered for `_regime_cap` at the scan level (tests/test_regime_gate.py) but
    pinned by nothing on the fire path until target 2a round 1 — the 2a diff
    shipped this test and the 2b rewrite dropped it.
    """
    from app.services.auto_trader import RegimeHeadwindError
    with pytest.raises(RegimeHeadwindError):
        _gate_fire_measured(mocker, (-40, "Stable"))

    qty, _ = _gate_fire_measured(mocker, (-39, "Stable"))
    assert qty == 4, "one point above the threshold is the caution band, not a refusal"


def test_regime_gate_caution_band_fires_and_logs_at_the_full_armed_quantity(mocker, caplog):
    """CAUTION fires — AND the quantity is the full armed one, which is the part
    the docstring used to deny.

    It claimed "sizing already handles the middle: every conviction at or below
    0 floors at min_mult". Both halves are false at HEAD: the ramp is two-sided
    since 2026-09-19 (0 sizes at 0.65, not the 0.30 floor) and sizing reads the
    market-wide cache, not this measurement. With the cache cold — as here, and
    as on any fire before regime_monitor has run — the caution band fires at
    FULL SIZE. Asserted rather than described so the claim cannot rot back.
    """
    with caplog.at_level("INFO", logger="app.services.auto_trader"):
        qty, svc = _gate_fire_measured(mocker, (-20, "Stable"))
    assert qty == 4, "the caution band fires, and carries no size consequence here"
    assert "CAUTION band" in caplog.text and "MSFT" in caplog.text
    assert svc.get_state().history[-1]["regime_gate"] == "caution", (
        "round 3: this was the one outcome value nothing asserted, and a "
        "mutation returning it as 'passed' kept the whole suite green — so the "
        "only in-process evidence there is would have recorded a trade that "
        "fired INTO a headwind as one the gate cleared"
    )


def test_regime_gate_refuses_when_a_threshold_key_is_missing(mocker, monkeypatch):
    """A missing threshold is a refusal, not a KeyError out of fire().

    `_regime_cap` subscribes `gate["headwind_reject_pct"]` directly. Target 2a
    round 1 measured what an absent key did: KeyError — a LookupError, matching
    NO handler in fire() — so the caller got a bare 500, the armed strategy was
    consumed, NO history row was written at all, and /auto-trade/status still
    reported the PREVIOUS order as last_order.
    """
    from app.services.auto_trader import RegimeGateConfigError
    with pytest.raises(RegimeGateConfigError, match="headwind_reject_pct"):
        _gate_fire_measured(
            mocker, (-50, "Stable"), monkeypatch=monkeypatch,
            gate_cfg={"enabled": True, "headwind_caution_pct": -15,
                      "require_stable_for_reject": False},
        )


def test_regime_gate_config_refusal_is_recorded_under_its_own_status(mocker, monkeypatch):
    """And it leaves the trace the KeyError did not: its own status, not the
    sizing one.

    `sizing_data_blocked` would page "the regime conviction is not a usable
    number" for a fault in a block the conviction was never read from.
    """
    from app.services.auto_trader import RegimeGateConfigError
    import app.services.auto_trader as at
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    sent: list = []
    mocker.patch("app.services.auto_trader.execute_option_order",
                 side_effect=lambda s: sent.append(s))
    _sizing_off(mocker)
    monkeypatch.setattr(at, "_load_regime_gate_config",
                        lambda: {"enabled": True, "headwind_caution_pct": -15})

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="MSFT", option_symbol="MSFT260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50,
        portfolio_value=100_000.0, horizon="Position",
    ))
    with pytest.raises(RegimeGateConfigError):
        svc.fire()

    assert sent == [], "a refused fire must not reach the broker"
    last = svc.get_state().history[-1]
    assert last["status"] == "regime_gate_config_blocked", last
    assert last["order_id"] is None
    assert svc.get_state().armed is False


def test_regime_gate_refuses_a_non_finite_threshold_instead_of_going_silently_inert(mocker, monkeypatch):
    """NaN silences the gate completely: `conviction <= nan` is always False.

    Not theoretical — `ArmRequest` declares these thresholds as unbounded
    `Optional[float]` and the JSON parser Starlette uses accepts a bare `NaN`
    token, so this is client-settable. Target 2a round 1 reproduced a trade
    firing at full quantity, gate reading `enabled: true`, because of it.
    `resolve_sizing` already refuses non-finite numbers for `regime_sizing`;
    the gate had no equivalent on any of the three paths that set these.
    """
    from app.services.auto_trader import RegimeGateConfigError
    with pytest.raises(RegimeGateConfigError, match="headwind_reject_pct.*finite"):
        _gate_fire_measured(
            mocker, (-50, "Stable"), monkeypatch=monkeypatch,
            gate_cfg={"enabled": True, "headwind_caution_pct": -15,
                      "headwind_reject_pct": float("nan"),
                      "require_stable_for_reject": False},
        )


def test_regime_gate_refuses_a_block_that_is_not_a_mapping(mocker, monkeypatch):
    """A list/scalar/string block used to raise ValueError or TypeError out of
    `dict(base or {})` — the first filed as `sizing_data_blocked` naming the
    wrong block entirely, the second escaping every handler.
    """
    from app.services.auto_trader import RegimeGateConfigError
    with pytest.raises(RegimeGateConfigError, match="not a mapping"):
        _gate_fire_measured(mocker, (-50, "Stable"), monkeypatch=monkeypatch,
                            gate_cfg=["enabled", "true"])


def test_a_bad_threshold_is_not_validated_when_the_gate_is_disabled(mocker, monkeypatch):
    """`enabled` is checked BEFORE the thresholds are.

    The old order resolved and used the block before testing `enabled`, so an
    unusable threshold could refuse a fire for an operator who had deliberately
    turned the gate OFF — a refusal from a feature that was switched off.

    Precisely scoped: a block that is not a mapping AT ALL still raises, because
    a list or a scalar cannot express `enabled: false` and the gate has no way
    to know it was meant to be off. That case is the test above. This one is the
    case where the operator's intent is legible and must be honoured.
    """
    qty, _ = _gate_fire_measured(
        mocker, (-50, "Stable"), monkeypatch=monkeypatch,
        gate_cfg={"enabled": False, "headwind_caution_pct": "not a number"},
    )
    assert qty == 4, "a disabled gate has nothing to validate and nothing to say"


def test_the_fired_history_row_records_what_the_gate_did(mocker):
    """"Gate passed" and "gate never ran" used to be the same history row.

    Abstention is fail-open and is the DOMINANT outcome on this repo's own
    fixtures (16 of 24 symbol x horizon x direction combinations), so a degraded data feed
    would fire every armed trade ungated and leave a history indistinguishable
    from a clean week. The only evidence was a WARNING in a log.
    """
    qty, svc = _gate_fire_measured(mocker, (50, "Stable"))
    assert qty == 4
    assert svc.get_state().history[-1]["regime_gate"] == "passed"

    qty, svc = _gate_fire_measured(mocker, None)
    assert qty == 4, "abstention is fail-open"
    assert svc.get_state().history[-1]["regime_gate"] == "abstained", (
        "the record must distinguish a trade the gate passed from one "
        "it never evaluated"
    )


def test_the_fired_history_row_records_a_disabled_gate_as_disabled(mocker, monkeypatch):
    """Third outcome, so the field cannot be read as "the gate approved this"."""
    qty, svc = _gate_fire_measured(
        mocker, (-50, "Stable"), monkeypatch=monkeypatch,
        gate_cfg={"enabled": False},
    )
    assert qty == 4
    assert svc.get_state().history[-1]["regime_gate"] == "disabled"


def test_a_headwind_refusal_on_the_scan_trigger_alerts(mocker, monkeypatch):
    """§9.1's "and alert" half, for the refusal that is EXPECTED to happen.

    Target 2a round 1: `RegimeHeadwindError` is a RuntimeError, and the scan
    trigger alerted only `(SizingConfigError, ValueError)`, so a headwind
    refusal fell through to the generic `except Exception` and became one log
    line. POST /scan calls this through `asyncio.to_thread` and discards the
    outcome, so the armed order was consumed, nothing was sent, and Kenneth
    found out by noticing no fill — while a broken YAML file, the RARE case,
    did page.
    """
    import app.services.auto_trader as at
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order")
    _sizing_off(mocker)
    mocker.patch.object(at, "_measure_trade_regime", return_value=(-50, "Stable"))
    alert = mocker.patch.object(at, "_alert_regime_headwind_refusal")
    sizing_alert = mocker.patch.object(at, "_alert_sizing_config_refusal")

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="MSFT", option_symbol="MSFT260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50,
        portfolio_value=100_000.0, horizon="Position",
    ))
    svc.maybe_fire_on_scan()   # fire-and-forget: must not raise

    assert alert.call_count == 1
    assert alert.call_args.args[0] == "MSFT"
    assert sizing_alert.call_count == 0, (
        "a headwind is not a config fault; paging 'regime_sizing cannot be "
        "honoured' would send Kenneth to a file that is fine"
    )
    assert svc.get_state().armed is False


def _capture_alerts(mocker):
    """Drive the REAL `notify_alert` and capture what reaches the CHANNELS.

    THE MOCK BOUNDARY IS THE POINT. The obvious shape — stubbing `notify_alert`
    and counting calls — cannot test any of this, because the defect under test
    lives INSIDE `notify_alert`: the dedup key is built there
    (`f"{rec_id}|{alert_type}"`), the reminder stamping is decided there, and a
    stub would simply reimplement whatever the test author already believed.
    A test that asserts against its own copy of the logic passes in exactly the
    case that matters.

    So only the outermost hop is mocked — `notify_enabled_channels`, the
    function that actually sends — and everything the production path does
    above it runs for real: the master switch, the type gate, the dedup window,
    the persisted first-seen map. A suppressed alert therefore shows up here as
    a MISSING delivery, which is the observation the whole round-2 critical
    turns on.

    Returns the list of (subject, plain) tuples that reached a channel.
    """
    import app.services.notifications.alert_notifier as an
    # The globals and the on-disk dedup file are isolated for EVERY test by
    # conftest's `_isolate_alert_dedup_state` — round 3 found this suite
    # rewriting the real backend/alert_dedup.json and arming two four-hour
    # suppression windows in it. Nothing is cleared here any more; doing it in
    # one helper was what made the leak look contained.
    delivered: list = []

    async def _fake_channels(subject, plain, html):
        delivered.append((subject, plain))
        return True

    mocker.patch.object(an, "notify_enabled_channels", _fake_channels)
    mocker.patch.object(an, "_save_dedup", lambda: None)
    mocker.patch.object(an, "_load_delivery_config", lambda: {"masterEnabled": True})
    return delivered


def test_two_symbols_refused_in_one_dedup_window_produce_two_alerts(mocker):
    """THE ROUND-2 CRITICAL, as a behavioural test rather than a string assert.

    `notify_alert` builds its dedup key as `f"{rec_id}|{alert_type}"` — the
    SYMBOL IS NOT IN IT, it only reaches the message body. With a bare constant
    rec_id, the first headwind refusal alerted and every other symbol's refusal
    inside the window was silently dropped: MSFT at 09:00 paged, AAPL at 10:30
    and NVDA at 12:00 did not. The window defaults to four hours, the map is
    persisted to alert_dedup.json so a restart does not clear it, and
    `forget_alerts` never sees these keys. §9.1's "and alert" half, reopened for
    every refusal but the first.
    """
    import app.services.auto_trader as at
    import app.services.notifications.alert_notifier as an
    from app.services.auto_trader import RegimeHeadwindError
    calls = _capture_alerts(mocker)

    # THE DISCRETE CLEANUP IS SUPPRESSED HERE, AND WITHOUT THAT THIS TEST IS
    # VACUOUS — round 3 proved it by mutation. `discrete=True` clears the dedup
    # key after every successful delivery, so with the cleanup live a BARE
    # CONSTANT rec_id delivers all three alerts too and this test passes on
    # round 1's exact defect. Holding the cleanup off is what leaves the real
    # dedup window standing, which is the thing the per-symbol key has to
    # survive. Re-verified by mutation after this change: reverting
    # `_headwind_rec_id` to the constant fails this test.
    mocker.patch.object(an, "forget_alerts", lambda rec_ids: None)

    for sym in ("MSFT", "AAPL", "NVDA"):
        at._alert_regime_headwind_refusal(sym, RegimeHeadwindError(f"{sym} measured -70"))

    assert len(calls) == 3, (
        "three symbols refused means three trades that did not happen, and "
        "Kenneth has to hear about all three — this is counted at the CHANNEL, "
        "downstream of the real dedup gate, so a suppressed alert is a missing "
        "entry here rather than a call the test counts anyway"
    )
    for sym, (subject, _) in zip(("MSFT", "AAPL", "NVDA"), calls):
        assert sym in subject, subject


def test_a_delivered_headwind_alert_does_not_make_the_next_one_a_reminder(mocker):
    """A refusal is a DISCRETE EVENT, not a standing condition.

    `notify_alert` keeps a persisted `_first_seen` per key and stamps every
    later send as a "(reminder)" carrying the FIRST occurrence's timestamp plus
    a "Still active as of" line — correct for a portfolio condition that is
    still true, wrong for a one-shot refusal weeks later, which then reads as an
    old nag and gets ignored. Round 2.
    """
    import app.services.auto_trader as at
    import app.services.notifications.alert_notifier as an
    from app.services.auto_trader import RegimeHeadwindError
    _capture_alerts(mocker)

    at._alert_regime_headwind_refusal("MSFT", RegimeHeadwindError("MSFT measured -70"))
    assert an._first_seen == {}, (
        "a delivered refusal is over; leaving its first-seen record behind is "
        "what turns the next one into a reminder dated to this one"
    )
    assert an._fired == {}, (
        "and the hold goes with it — a refusal DISARMS the auto-trader, so a "
        "second refusal of the same symbol means a human deliberately re-armed, "
        "which is the last thing that should be suppressed"
    )


def test_a_config_refusal_stays_deduped_because_the_file_is_still_broken(mocker):
    """The deliberate inverse, so `discrete` is not read as "always clear".

    A broken scoring_rules.yaml IS a standing condition: it is still broken on
    the next scan, the remedy has not changed, and collapsing a run into one
    alert is the behaviour the dedup window exists for.
    """
    import app.services.auto_trader as at
    import app.services.notifications.alert_notifier as an
    from app.scoring.conviction_sizing import SizingConfigError
    calls = _capture_alerts(mocker)

    at._alert_sizing_config_refusal("MSFT", SizingConfigError("min_mult is not a number"))
    at._alert_sizing_config_refusal("AAPL", SizingConfigError("min_mult is not a number"))

    assert len(calls) == 1, "one broken file, one alert"
    assert "MSFT" in calls[0][0], calls[0][0]
    assert an._fired, "the hold stays — unlike a headwind refusal"


def test_the_gate_config_alert_is_distinguishable_from_the_sizing_one(mocker):
    """Two exception types and two dedup keys were bought and then thrown away
    at the subject line, which is the half a reader sees first.

    `_build_notification` builds the subject from `alert_type`, so while both
    passed CONFIG_ERROR they arrived as the same "Bamendjou Portfolio Alert —
    MSFT: CONFIG_ERROR". Round 2.
    """
    import app.services.auto_trader as at
    from app.services.auto_trader import RegimeGateConfigError
    from app.scoring.conviction_sizing import SizingConfigError
    calls = _capture_alerts(mocker)

    at._alert_regime_gate_config_refusal("MSFT", RegimeGateConfigError("no headwind_reject_pct"))
    at._alert_sizing_config_refusal("MSFT", SizingConfigError("min_mult is not a number"))

    subjects = [subject for subject, _ in calls]
    assert len(subjects) == 2, subjects
    assert subjects[0] != subjects[1], (
        "two exception types and two dedup keys were bought and then thrown "
        "away at the subject line, which is the half a reader sees first"
    )
    assert "REGIME_GATE_CONFIG_ERROR" in subjects[0], subjects[0]
    assert "CONFIG_ERROR" in subjects[1], subjects[1]
    assert "regime_gate" in calls[0][1]
    assert "regime_sizing" in calls[1][1]


def test_a_gate_config_refusal_on_the_scan_trigger_alerts_as_itself(mocker, monkeypatch):
    """The unattended trigger must route this to its OWN alert.

    Round 2: this branch and `_alert_regime_gate_config_refusal` had no test at
    all, while the sibling headwind branch did — and routing it to
    `_alert_sizing_config_refusal` is exactly the misattribution the
    `RegimeGateConfigError` type was introduced to prevent.
    """
    import app.services.auto_trader as at
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order")
    _sizing_off(mocker)
    monkeypatch.setattr(at, "_load_regime_gate_config",
                        lambda: {"enabled": True, "headwind_caution_pct": -15})
    gate_alert = mocker.patch.object(at, "_alert_regime_gate_config_refusal")
    sizing_alert = mocker.patch.object(at, "_alert_sizing_config_refusal")

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="MSFT", option_symbol="MSFT260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50,
        portfolio_value=100_000.0, horizon="Position",
    ))
    svc.maybe_fire_on_scan()

    assert gate_alert.call_count == 1
    assert gate_alert.call_args.args[0] == "MSFT"
    assert sizing_alert.call_count == 0, (
        "paging 'regime_sizing cannot be honoured' would send Kenneth to a "
        "block that is fine"
    )
    assert svc.get_state().history[-1]["status"] == "regime_gate_config_blocked"


def test_a_populated_gate_block_that_does_not_say_enabled_refuses(mocker, monkeypatch):
    """THE ONE CORRUPTION THAT SILENTLY DISABLED THE WHOLE GATE.

    `raw.get("enabled", False)` meant a block that lost its `enabled: true`
    line, or misspelled it, or carried a null, read as "gate off": the trade
    went to the broker AT FULL ARMED QUANTITY at a -90 Stable headwind, the
    history row said "disabled", and NO alert was sent, because a disabled gate
    is not a refusal and has nothing to report. `resolve_sizing` refuses exactly
    this shape for the sibling block one layer down. Round 2.
    """
    from app.services.auto_trader import RegimeGateConfigError
    for bad in (
        {"enable": True, "headwind_caution_pct": -15, "headwind_reject_pct": -40},
        {"headwind_caution_pct": -15, "headwind_reject_pct": -40},
        {"enabled": None, "headwind_caution_pct": -15, "headwind_reject_pct": -40},
        {"enabled": "false", "headwind_caution_pct": -15, "headwind_reject_pct": -40},
    ):
        with pytest.raises(RegimeGateConfigError, match="enabled"):
            _gate_fire_measured(mocker, (-90, "Stable"), monkeypatch=monkeypatch,
                                gate_cfg=bad)


def test_an_absent_gate_block_is_still_simply_no_gate(mocker, monkeypatch):
    """The boundary of the test above: ABSENT is not CORRUPT.

    An empty/absent `regime_gate` reads as disabled and always has — that is
    what `_regime_cap` does with it too. Only a POPULATED block that fails to
    say it is on is a config fault.
    """
    qty, svc = _gate_fire_measured(mocker, (-90, "Stable"), monkeypatch=monkeypatch,
                                   gate_cfg={})
    assert qty == 4
    assert svc.get_state().history[-1]["regime_gate"] == "disabled"


def test_a_quoted_require_stable_for_reject_refuses_instead_of_disarming_the_gate(mocker, monkeypatch):
    """`"false"` is TRUE to Python — the value that most needs to mean off.

    `_regime_cap` reads `not gate.get("require_stable_for_reject", True)`, so a
    quoted "false" reads as ON and the REJECT branch then needs a Stable regime
    that essentially never occurs. Measured before the fix: a -90 Fragile
    headwind returned CAUTION and FIRED. Round 1 left this key unvalidated while
    validating the inert caution threshold to the point of refusing fires.
    """
    from app.services.auto_trader import RegimeGateConfigError
    with pytest.raises(RegimeGateConfigError, match="require_stable_for_reject"):
        _gate_fire_measured(
            mocker, (-90, "Fragile"), monkeypatch=monkeypatch,
            gate_cfg={"enabled": True, "headwind_caution_pct": -15,
                      "headwind_reject_pct": -40,
                      "require_stable_for_reject": "false"},
        )


def test_an_unusable_caution_threshold_does_not_refuse_a_fire(mocker, monkeypatch, caplog):
    """SEVERITY TRACKS CONSEQUENCE, and round 1 got this one backwards.

    `headwind_caution_pct` cannot cause a refusal: `_regime_cap` tests reject
    FIRST and returns, so this key is read only by trades that already survived,
    and on this path its whole effect is whether a log line is emitted. Round 1
    validated it identically to the reject threshold and refused the fire — an
    availability regression against a state that previously gated correctly, and
    paged as a broken installation.

    The reject rule must still apply on both sides, which is what the two
    assertions below are for: a passing trade still fires, and a rejecting one
    still refuses, with only the caution band gone.
    """
    from app.services.auto_trader import RegimeHeadwindError
    cfg = {"enabled": True, "headwind_caution_pct": float("nan"),
           "headwind_reject_pct": -40, "require_stable_for_reject": False}

    with caplog.at_level("WARNING", logger="app.services.auto_trader"):
        qty, _ = _gate_fire_measured(mocker, (50, "Stable"), monkeypatch=monkeypatch,
                                     gate_cfg=cfg)
    assert qty == 4, "a passing trade must not be refused over an inert threshold"
    assert "headwind_caution_pct" in caplog.text and "REJECT rule is unaffected" in caplog.text

    with pytest.raises(RegimeHeadwindError):
        _gate_fire_measured(mocker, (-50, "Stable"), monkeypatch=monkeypatch,
                            gate_cfg=cfg)


def test_a_missing_caution_threshold_does_not_crash_the_shared_rule(mocker, monkeypatch):
    """`_regime_cap` subscribes the caution key DIRECTLY, so "ignore it" is not
    an option — it has to be present and comparable. The sentinel makes the
    caution band empty rather than absent."""
    qty, svc = _gate_fire_measured(
        mocker, (-20, "Stable"), monkeypatch=monkeypatch,
        gate_cfg={"enabled": True, "headwind_reject_pct": -40,
                  "require_stable_for_reject": False},
    )
    assert qty == 4
    assert svc.get_state().history[-1]["regime_gate"] == "passed:caution-band-disabled", (
        "with no usable caution threshold the band is empty, so a trade that "
        "would have been CAUTION passes rather than crashing — but it must NOT "
        "record as an ordinary 'passed', which would say the gate fully "
        "evaluated a trade whose caution rule it never applied (round 3)"
    )


def test_the_fire_path_accepts_every_enabled_value_the_scan_acts_on(mocker, monkeypatch):
    """The fire path must not be STRICTER than the shared rule about what "on" means.

    Round 3: round 2's bool-only check refused every armed trade on
    `enabled: 1` — a config `_regime_cap` reads as ON, and on which the scan
    correctly drops headwind candidates. A scan that gates and a fire path that
    refuses are two answers to one question, which is the defect class this
    whole piece exists to remove, pointing the other way.
    """
    from app.scoring.stock_scorer import _regime_cap
    from app.services.auto_trader import RegimeHeadwindError

    for value in (True, 1):
        gate = {"enabled": value, "headwind_caution_pct": -15,
                "headwind_reject_pct": -40, "require_stable_for_reject": False}
        assert _regime_cap(-90, "Stable", gate) == "REJECT", (
            f"precondition: the SHARED rule treats enabled={value!r} as on"
        )
        with pytest.raises(RegimeHeadwindError):
            _gate_fire_measured(mocker, (-90, "Stable"), monkeypatch=monkeypatch,
                                gate_cfg=gate)

    for value in (False, 0):
        qty, svc = _gate_fire_measured(
            mocker, (-90, "Stable"), monkeypatch=monkeypatch,
            gate_cfg={"enabled": value, "headwind_caution_pct": -15,
                      "headwind_reject_pct": -40},
        )
        assert qty == 4 and svc.get_state().history[-1]["regime_gate"] == "disabled", (
            f"enabled={value!r} is unambiguously off on both paths"
        )


def test_a_delivered_alert_whose_cleanup_fails_is_not_reported_as_a_failed_alert(mocker, caplog):
    """The two outcomes have opposite remedies, and one was wearing the other's name.

    Round 3: the cleanup sat inside the delivery try, so a failure here logged
    "failed to alert ... (the refusal itself stands)" — telling a post-mortem
    that §9.1's "and alert" half did not happen, when it had, and hiding the
    real consequence: the hold is stuck, so the NEXT refusal is the unheard one.
    """
    import app.services.auto_trader as at
    import app.services.notifications.alert_notifier as an
    from app.services.auto_trader import RegimeHeadwindError

    def _boom(rec_ids):
        raise OSError("dedup store unwritable")

    _capture_alerts(mocker)
    mocker.patch.object(an, "forget_alerts", _boom)

    with caplog.at_level("ERROR", logger="app.services.auto_trader"):
        at._alert_regime_headwind_refusal("MSFT", RegimeHeadwindError("MSFT measured -70"))

    assert "WAS delivered" in caplog.text, caplog.text
    assert "next refusal of this key will be suppressed" in caplog.text
    assert "failed to alert" not in caplog.text, (
        "the alert succeeded; saying it failed sends the reader after the "
        "wrong fault entirely"
    )


def test_a_suppressed_delivery_does_not_clear_anyone_elses_hold(mocker):
    """`delivered and discrete`, not a bare `discrete`.

    Round 3 named this branch untested: a send that failed has already rolled
    its own hold back, so clearing again would drop a concurrent caller's
    optimistic claim on the key and permit a double-send.
    """
    import app.services.auto_trader as at
    import app.services.notifications.alert_notifier as an
    from app.services.auto_trader import RegimeHeadwindError

    cleared: list = []
    mocker.patch.object(an, "forget_alerts", lambda rec_ids: cleared.append(rec_ids))

    async def _never_delivers(**kwargs):
        return False

    mocker.patch.object(an, "notify_alert", _never_delivers)
    at._alert_regime_headwind_refusal("MSFT", RegimeHeadwindError("MSFT measured -70"))

    assert cleared == [], "nothing was delivered, so there is no hold of ours to clear"


def test_the_suite_does_not_write_the_real_alert_dedup_file(mocker):
    """Round 3's operational finding, pinned so it cannot come back.

    A test that reached `notify_alert` or `forget_alerts` unstubbed rewrote
    backend/alert_dedup.json — the file the running backend loads at import —
    with whatever the test had left in the globals, and armed its four-hour
    suppression windows. A backend restarted from the same tree lost every
    genuine portfolio-alert record and would silently not alert the next config
    refusal inside the window.
    """
    import app.services.notifications.alert_notifier as an
    from pathlib import Path
    real = Path(__file__).parent.parent / "alert_dedup.json"
    assert an._DEDUP_PATH != real, (
        "conftest's _isolate_alert_dedup_state must redirect the dedup store "
        "for every test; without it a suite run is a write to production state"
    )


def test_an_order_failed_row_records_what_the_gate_did(mocker):
    """The one refusal-shaped row where the broker call was actually MADE.

    `cap_blocked` and `daily_loss_blocked` provably never reach the broker, so
    "did the gate run" is moot for them. This row means the submission may have
    landed. Round 2.
    """
    import app.services.auto_trader as at
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    _sizing_off(mocker)
    mocker.patch.object(at, "_measure_trade_regime", return_value=None)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 side_effect=RuntimeError("broker exploded"))

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="MSFT", option_symbol="MSFT260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50,
        portfolio_value=100_000.0, horizon="Position",
    ))
    with pytest.raises(RuntimeError):
        svc.fire()

    last = svc.get_state().history[-1]
    assert last["status"] == "order_failed"
    assert last["regime_gate"] == "abstained", (
        "an order that may have landed while the gate never evaluated is "
        "exactly the combination a post-mortem needs to see"
    )


def test_the_headwind_alert_is_not_dressed_as_a_config_error(mocker):
    """Its own alert_type and its own dedup key, for the reason the exception
    has its own type: the remedies are opposites."""
    import app.services.auto_trader as at
    from app.services.auto_trader import RegimeHeadwindError

    captured: dict = {}

    async def _fake_notify(**kwargs):
        captured.update(kwargs)
        return True

    mocker.patch("app.services.notifications.alert_notifier.notify_alert", _fake_notify)
    at._alert_regime_headwind_refusal("MSFT", RegimeHeadwindError("measured -50"))

    assert captured["symbol"] == "MSFT"
    assert captured["alert_type"] == "AUTO_TRADE_REFUSED", (
        "CONFIG_ERROR would read as a broken installation for a gate that "
        "worked exactly as designed"
    )
    assert captured["rec_id"] == "auto-trade-regime-headwind:MSFT", (
        "PER SYMBOL, unlike the sizing key: a headwind is a fact about this "
        "symbol. Round 2: this asserted the bare constant while its own "
        "message claimed the key was per-symbol — it passed, and the thing it "
        "said it proved was false. The behavioural version is the test below; "
        "this one only pins the string."
    )
    assert captured["type_enabled"] is True
    assert "measured -50" in captured["reason"]


def test_regime_gate_never_consults_the_market_wide_conviction_cache(mocker, monkeypatch):
    """Both Bearish research sizing and Bullish fire measure the symbol's bars.

    Each path forbids get_last_conviction, with sizing enabled.
    """
    from app.services.auto_trader import RegimeHeadwindError

    qty, _ = _research_gate_sizing(mocker, sizing_on=True)
    assert qty is not None, "MSFT's own regime passes the research helper"

    _no_stability_requirement(monkeypatch)
    with pytest.raises(RegimeHeadwindError):
        _gate_fire(mocker, symbol="MSFT", direction="Bullish",
                   horizon="Position", sizing_on=True)


# ---------------------------------------------------------------------------
# Round 1 of AUTOTRADE-2A-ALERT-DELIVERY: the refusal kinds that reached nobody
# ---------------------------------------------------------------------------
# All three leave fire() as a BARE RuntimeError, so the scan trigger cannot tell
# them apart by exception class and routes on the history row the attempt
# recorded instead. Each test drives the REAL maybe_fire_on_scan so the routing
# itself is under test, not a reimplementation of it.

def _scan_trigger_service(mocker, *, qty=1):
    """An armed service whose fire path is clear up to the point under test."""
    import app.services.auto_trader as at
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    # Sizing passes straight through: these tests are about what happens AFTER
    # it, and a real sizing call would need scoring config they do not exercise.
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    svc = AutoTradeService()
    svc.arm(_make_armed(symbol="MSFT", qty=qty))
    return at, svc


def test_a_cap_blocked_refusal_on_the_scan_trigger_alerts(mocker):
    """§9.1's "and alert" half for the exposure cap.

    Until round 1 of this target `cap_blocked` fell into the bare
    `except Exception` and produced one log line on a box nobody watches, while
    the armed order was consumed and the service disarmed.
    """
    at, svc = _scan_trigger_service(mocker)
    mocker.patch.object(AutoTradeService, "_check_exposure",
                        side_effect=RuntimeError("Exposure cap breach: ['too big']"))
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    alert = mocker.patch.object(at, "_alert_risk_limit_refusal")

    svc.maybe_fire_on_scan(portfolio_snapshot=[], portfolio_value=100_000.0)

    execute.assert_not_called()
    assert alert.call_count == 1
    assert alert.call_args.args[0] == "MSFT"
    assert alert.call_args.args[2] == "cap_blocked"
    assert svc.get_state().armed is False
    assert svc.get_state().history[-1]["status"] == "cap_blocked"


def test_a_daily_loss_refusal_on_the_scan_trigger_alerts(mocker):
    """The same hole, on the circuit breaker that blocks for the REST OF THE DAY
    — so a silent one costs every remaining trade, not just this one."""
    at, svc = _scan_trigger_service(mocker)
    mocker.patch.object(AutoTradeService, "_check_daily_loss",
                        side_effect=RuntimeError("Daily loss limit reached: 60000 vs 2000"))
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    alert = mocker.patch.object(at, "_alert_risk_limit_refusal")

    svc.maybe_fire_on_scan()

    execute.assert_not_called()
    assert alert.call_count == 1
    assert alert.call_args.args[2] == "daily_loss_blocked"
    assert svc.get_state().armed is False


def test_an_order_failed_alert_does_not_claim_nothing_was_sent(mocker):
    """THE SHARPEST OF THE THREE. `order_failed` means the broker call was MADE
    and errored, so the submission MAY HAVE LANDED — the row's own comment says
    so. Telling Kenneth "nothing was sent" would be a false statement about a
    possibly-live order; telling him nothing at all, which is what happened
    until this round, left him to find it by noticing an unexpected fill.

    Drives the real notify_alert so the delivered TEXT is what is asserted.
    """
    at, svc = _scan_trigger_service(mocker)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 side_effect=RuntimeError("broker timeout after submit"))
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan()

    assert len(calls) == 1, "an order that may have landed must reach a human"
    subject, body = calls[0]
    assert "MSFT" in subject
    assert "MAY HAVE LANDED" in body, body
    assert "Nothing was sent" not in body, (
        "the broker call was made — this alert must not deny it"
    )
    assert svc.get_state().history[-1]["status"] == "order_failed"


def test_a_risk_config_fault_is_not_paged_as_a_sizing_fault(mocker):
    """ROUND 1 FINDING 3. `maybe_fire_on_scan` used to catch
    `(SizingConfigError, ValueError)` around the WHOLE fire path, while fire()'s
    own handler of that pair wraps only `_apply_vol_sizing`. So a non-numeric
    value in risk_rules.yaml raised ValueError out of `_check_daily_loss` and
    was paged as "the regime conviction is not a usable number", sending the
    operator to a scoring_rules.yaml block that was fine — AND arming the
    sizing key's four-hour dedup window, so a genuine sizing refusal inside it
    went unheard.

    The fault also lands past fire()'s disarm and records NO history row, so it
    must still alert — as the unclassified refusal, which does not guess.
    """
    at, svc = _scan_trigger_service(mocker)
    mocker.patch.object(AutoTradeService, "_risk_config",
                        return_value={"max_daily_loss_pct": "2%",
                                      "premium_stop_pct": 0.60})
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    sizing_alert = mocker.patch.object(at, "_alert_sizing_config_refusal")
    unclassified = mocker.patch.object(at, "_alert_unclassified_refusal")

    svc.maybe_fire_on_scan()

    execute.assert_not_called()
    assert sizing_alert.call_count == 0, (
        "a risk_rules.yaml fault must not blame scoring_rules.yaml's "
        "regime_sizing block, nor burn the sizing alert's dedup key"
    )
    assert unclassified.call_count == 1
    assert unclassified.call_args.args[0] == "MSFT"
    assert svc.get_state().armed is False, "it failed past the disarm"


def test_a_genuine_sizing_value_error_still_reaches_the_sizing_alert(mocker):
    """The other side of the narrowing above: a plain ValueError raised BY the
    sizing call is still a sizing refusal and must keep its own wording. It is
    routed on the `sizing_data_blocked` row fire() records, not on its class."""
    import app.services.auto_trader as at
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)

    def _bad_conviction(_s):
        raise ValueError("conviction_pct is not finite (nan)")

    mocker.patch.object(at, "_apply_vol_sizing", _bad_conviction)
    alert = mocker.patch.object(at, "_alert_sizing_config_refusal")
    unclassified = mocker.patch.object(at, "_alert_unclassified_refusal")

    svc = AutoTradeService()
    svc.arm(_make_armed(symbol="MSFT"))
    svc.maybe_fire_on_scan()

    assert alert.call_count == 1, "a sizing ValueError keeps the sizing alert"
    assert unclassified.call_count == 0
    assert svc.get_state().history[-1]["status"] == "sizing_data_blocked"


def test_a_preserved_armed_order_does_not_alert(mocker):
    """THE DELIBERATE SILENCE, and the reason the router checks `consumed`
    rather than alerting on everything that raises.

    `fire()`'s two pre-disarm guards — not armed, and market closed/halted —
    leave the order ARMED for retry and record nothing. maybe_fire_on_scan runs
    after EVERY scan, so paging on those would page on every scan while the
    market is shut, and an alert channel that cries wolf is one that gets muted.
    """
    import app.services.auto_trader as at
    mocker.patch("app.services.auto_trader._market_is_open", return_value=False)
    calls = _capture_alerts(mocker)
    unclassified = mocker.patch.object(at, "_alert_unclassified_refusal")

    svc = AutoTradeService()
    svc.arm(_make_armed(symbol="MSFT"))
    svc.maybe_fire_on_scan()

    assert unclassified.call_count == 0
    assert calls == [], "a preserved armed order is not a refusal"
    assert svc.get_state().armed is True, "market-closed preserves the order"


def test_a_good_fire_clears_the_config_refusal_hold(mocker):
    """ROUND 1 FINDING 1, and the reason the fix is NOT `discrete=True`.

    The config keys are deliberately NOT discrete — a broken scoring_rules.yaml
    is a standing condition and collapsing a run of scans into one alert is
    what the window is for, which
    `test_a_config_refusal_stays_deduped_because_the_file_is_still_broken`
    pins. But nothing cleared them EITHER, and `_first_seen` is persisted and
    outlives the dedup purge, so the next config refusal — however much later,
    after the file had been fixed and re-broken — arrived stamped "(reminder)"
    under the FIRST one's date with a false "Still active as of" line.

    A fire that SUCCEEDS proves both blocks were read and applied, so the
    condition has demonstrably ended. Drives the real notify_alert: without the
    clear the second refusal is SUPPRESSED, so this reads as a missing
    delivery rather than a wording difference.
    """
    import app.services.auto_trader as at
    from app.data.ibkr_paper import OrderResult
    from app.scoring.conviction_sizing import SizingConfigError
    calls = _capture_alerts(mocker)

    at._alert_sizing_config_refusal("MSFT", SizingConfigError("min_mult is not a number"))
    assert len(calls) == 1, "the first refusal pages"

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 return_value=OrderResult("oid-1", "ok", "ibkr_paper"))
    svc = AutoTradeService()
    svc.arm(_make_armed(symbol="MSFT"))
    svc.maybe_fire_on_scan()
    assert svc.get_state().history[-1]["order_id"] == "oid-1", "the fire succeeded"

    at._alert_sizing_config_refusal("AAPL", SizingConfigError("min_mult is not a number"))

    assert len(calls) == 2, (
        "a breakage AFTER a good fire is a new condition and must page again"
    )
    assert "(reminder)" not in calls[1][0], (
        "it is a fresh fault, not a reminder of the one before the good fire"
    )


# ---------------------------------------------------------------------------
# F1 of AUTOTRADE-2A-ALERT-DELIVERY round 1: two scans in one fire window
# ---------------------------------------------------------------------------
# `maybe_fire_on_scan` identified its own history row by SLICE INDEX, captured
# before a call whose window contains `_market_is_open` — a live fetch with a
# 3s deadline — and nothing serializes two scans (scan.py's own docstring says
# so). Each test below drives two real triggers into that window with a
# threading.Barrier, or re-arms inside it, and asserts on what reaches a human.
# All three FAIL on the slice-and-inspect-state shape they replaced.

def _concurrent_fire_service(mocker, barrier):
    """An armed service whose market check parks every caller on `barrier`.

    The barrier sits exactly where the old capture-to-row window was widest, so
    both triggers are guaranteed to be inside it when the first one disarms.
    """
    import app.services.auto_trader as at

    def _open(_symbol):
        barrier.wait()
        return True

    mocker.patch.object(at, "_market_is_open", _open)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    svc = AutoTradeService()
    svc.arm(_make_armed(symbol="MSFT"))
    return at, svc


def _run_two_triggers(svc):
    import threading
    errors: list = []

    def _go():
        try:
            svc.maybe_fire_on_scan()
        except BaseException as exc:      # a trigger must never raise
            errors.append(exc)

    threads = [threading.Thread(target=_go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads), "a trigger deadlocked"
    assert errors == [], f"maybe_fire_on_scan raised: {errors}"


def test_the_loser_of_two_concurrent_triggers_does_not_page_about_the_winners_fill(mocker):
    """THE WORST OF F1's THREE INTERLEAVINGS, because the page is a lie about a
    LIVE POSITION. The losing trigger's slice began before either fire, so it
    picked up the WINNER's `filled` row, matched no refusal branch, and — with
    the armed slot now empty — fell into the unclassified alert: "the armed
    order was consumed and no outcome was recorded. No order was recorded as
    submitted", about an order that had filled as oid-WINNER.

    Nothing was refused here at all. One order filled and the other trigger
    found nothing armed, which is not an event.
    """
    import threading
    from app.data.ibkr_paper import OrderResult
    at, svc = _concurrent_fire_service(mocker, threading.Barrier(2, timeout=10))
    execute = mocker.patch.object(
        at, "execute_option_order",
        return_value=OrderResult("oid-WINNER", "filled", "ibkr_paper"))
    calls = _capture_alerts(mocker)

    _run_two_triggers(svc)

    assert execute.call_count == 1, "the disarm must admit exactly one fire"
    assert calls == [], (
        "a filled order is not a refusal — no trigger may page about it"
    )
    rows = svc.get_state().history
    assert [r["status"] for r in rows] == ["filled"]
    assert svc.get_state().armed is False


def test_one_order_failed_row_pages_exactly_once_under_two_triggers(mocker):
    """"Exactly once per event" broken by the dedup's own cleanup. The winner
    sends the `order_failed` page and its `discrete=True` cleanup clears the
    hold; the loser then reads the SAME row through its stale slice and sends
    an identical second page, which the now-empty window no longer suppresses.

    One broker call errored. One page.
    """
    import threading
    at, svc = _concurrent_fire_service(mocker, threading.Barrier(2, timeout=10))
    mocker.patch.object(at, "execute_option_order",
                        side_effect=RuntimeError("broker timeout after submit"))
    calls = _capture_alerts(mocker)

    _run_two_triggers(svc)

    assert len(calls) == 1, (
        f"one failed broker call must page once, got {len(calls)}: "
        f"{[c[0] for c in calls]}"
    )
    assert "MAY HAVE LANDED" in calls[0][1]
    assert [r["status"] for r in svc.get_state().history] == ["order_failed"]


def test_a_re_arm_inside_the_window_is_not_fired_on_the_old_orders_age(mocker):
    """F1's third interleaving — reachable with no thread of the scan's own: a
    manual POST /auto-trade/fire runs on the event loop while the scan runs in
    a worker thread.

    The trigger read MSFT and checked MSFT's age. Without `expect`, `fire()`
    then took whatever was armed when it got the lock — AAPL — and fired it on
    the strength of a staleness check made against a different order, producing
    a `cap_blocked` row for AAPL while the alert named MSFT.

    Firing nothing is the fail-closed answer: AAPL stays armed with its own
    fresh age for the next scan to judge on its own terms.
    """
    import app.services.auto_trader as at
    svc = AutoTradeService()
    first = _make_armed(symbol="MSFT")
    second = _make_armed(symbol="AAPL")
    svc.arm(first)

    def _open(_symbol):
        svc.disarm()
        svc.arm(second)
        return True

    mocker.patch.object(at, "_market_is_open", _open)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    # Only reachable if the attempt fires the re-armed order — it is here so
    # the pre-fix behaviour this pins produces its recorded `cap_blocked` row.
    mocker.patch.object(AutoTradeService, "_check_exposure",
                        side_effect=RuntimeError("Exposure cap breach: ['too big']"))
    execute = mocker.patch.object(at, "execute_option_order")
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan(portfolio_snapshot=[], portfolio_value=100_000.0)

    execute.assert_not_called()
    assert svc.get_state().history == [], "nothing was attempted on the new order"
    assert calls == [], "no order was refused, so nobody is paged"
    assert svc.get_state().armed is True
    assert svc.get_state().strategy is second, "the re-armed order survives"


def test_a_re_arm_with_an_identical_looking_order_is_still_a_different_decision(mocker):
    """`expect` is checked by IDENTITY, and this is the difference it makes.

    `dataclasses.replace` with no changes copies every field, `armed_at`
    included, so the re-armed order is `==` to the one the trigger read and is
    still a different arming decision made by somebody else. Equality here
    would fire an order this trigger never looked at.
    """
    import app.services.auto_trader as at
    from dataclasses import replace
    svc = AutoTradeService()
    first = _make_armed(symbol="MSFT")
    twin = replace(first)
    assert twin == first and twin is not first, "the pin needs an equal, distinct order"
    svc.arm(first)

    def _open(_symbol):
        svc.disarm()
        svc.arm(twin)
        return True

    mocker.patch.object(at, "_market_is_open", _open)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    execute = mocker.patch.object(at, "execute_option_order")

    svc.maybe_fire_on_scan()

    execute.assert_not_called()
    assert svc.get_state().strategy is twin, "the re-armed order is left for the next scan"


def test_the_attempt_record_ignores_rows_another_attempt_wrote():
    """The lookup is by stamp, not by position — including when a LATER row
    belongs to somebody else, which is exactly what `rows[-1]` got wrong."""
    svc = AutoTradeService()
    svc._state.history.extend([
        {"attempt_id": "other-earlier", "status": "filled",      "symbol": "AAPL"},
        {"attempt_id": "mine",          "status": "cap_blocked", "symbol": "MSFT"},
        {"attempt_id": "other-later",   "status": "filled",      "symbol": "NVDA"},
    ])

    row = svc._fire_attempt_record("mine")
    assert row is not None and row["status"] == "cap_blocked"
    assert row["symbol"] == "MSFT"
    assert svc._fire_attempt_record("an-attempt-that-wrote-nothing") is None


def test_every_history_row_a_fire_writes_carries_its_attempt_id(mocker):
    """Both shapes of row `fire()` appends — the order result and a refusal —
    carry the caller's stamp. Without it on EVERY path the router silently
    falls back to "this attempt recorded nothing" and pages unclassified."""
    import app.services.auto_trader as at
    from app.data.ibkr_paper import OrderResult
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    mocker.patch.object(at, "execute_option_order",
                        return_value=OrderResult("oid-1", "filled", "ibkr_paper"))
    svc = AutoTradeService()

    svc.arm(_make_armed(symbol="MSFT"))
    svc.fire(attempt_id="attempt-GOOD")
    assert svc.get_state().history[-1]["attempt_id"] == "attempt-GOOD"

    mocker.patch.object(at, "execute_option_order",
                        side_effect=RuntimeError("broker timeout after submit"))
    svc.arm(_make_armed(symbol="MSFT"))
    with pytest.raises(RuntimeError):
        svc.fire(attempt_id="attempt-BAD")
    assert svc.get_state().history[-1]["status"] == "order_failed"
    assert svc.get_state().history[-1]["attempt_id"] == "attempt-BAD"


def test_the_pre_disarm_refusals_are_told_apart_by_class_not_by_state(mocker):
    """The silence is declared at the point of refusal now, not inferred
    afterwards from an armed slot another thread can rewrite.

    Still a RuntimeError, so `/auto-trade/fire`'s `except (ValueError,
    RuntimeError)` keeps mapping both to a 400 with the same message text.
    """
    import app.services.auto_trader as at
    from app.services.auto_trader import ArmPreservedError
    assert issubclass(ArmPreservedError, RuntimeError)

    svc = AutoTradeService()
    with pytest.raises(ArmPreservedError, match="not armed"):
        svc.fire()

    mocker.patch.object(at, "_market_is_open", return_value=False)
    svc.arm(_make_armed(symbol="MSFT"))
    with pytest.raises(ArmPreservedError, match="Market closed"):
        svc.fire()
    assert svc.get_state().armed is True, "a preserved order is still armed"


# ---------------------------------------------------------------------------
# F2: a failure BEFORE the broker was contacted must not be paged as one that
# may have landed an order. Round 1 of target 2a-alert, decisions[0] item (2).
# ---------------------------------------------------------------------------

def _expire_the_credentials(mocker):
    """Make `build_router_from_credentials` return a router with NO adapters.

    THE REAL MECHANISM, NOT A STUBBED EXCEPTION. F2's production trigger is
    credentials that expire, get rotated, or are cleared out of the store:
    `build_router_from_credentials` adds an adapter only for a broker whose
    credentials are present, silently omits the rest, and `BrokerRouter.execute`
    then raises `ValueError: Unknown broker 'ibkr_paper'. Available: []` at its
    dict lookup — BEFORE `adapter.place_order`, the only line that can put an
    order in front of a broker.

    Stubbing `execute_option_order` with a side_effect would test the alert
    wording against a fiction; this drives the real credential store, the real
    router build and the real `execute`, so the test fails if any of those three
    ever stops behaving the way the finding describes.
    """
    import app.services.credential_store as cs
    mocker.patch.object(cs.credential_store, "load", lambda: None)
    mocker.patch.object(cs.credential_store, "get", lambda key: None)
    mocker.patch.dict("os.environ", {"TRADIER_PAPER_TOKEN": "",
                                     "TRADIER_PAPER_ACCOUNT_ID": ""})


def test_expired_credentials_do_not_page_as_an_order_that_may_have_landed(mocker):
    """F2, THE HEADLINE. Credentials go stale, nothing whatsoever is sent, and
    the old code paged "the broker call was made and errored, so THE ORDER MAY
    HAVE LANDED. Check the broker before re-arming" — sending Kenneth hunting a
    position at a broker that was never opened a socket to.

    Drives the real notify_alert so the delivered TEXT is what is asserted, the
    same boundary `test_an_order_failed_alert_does_not_claim_nothing_was_sent`
    uses for the opposite claim.
    """
    at, svc = _scan_trigger_service(mocker)
    _expire_the_credentials(mocker)
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan()

    assert len(calls) == 1, "a consumed arm must still reach a human"
    subject, body = calls[0]
    assert "MSFT" in subject
    assert "MAY HAVE LANDED" not in body, (
        "nothing reached the broker — this alert must not suggest a position "
        "may exist:\n" + body
    )
    assert "Nothing was sent" in body, body


def test_a_pre_submission_failure_records_its_own_status(mocker):
    """The row, not just the wording. `order_failed` is the status whose own
    comment says the submission may have landed; a failure that provably never
    reached the broker must not borrow it, or every later reader of the history
    inherits the same false claim.
    """
    at, svc = _scan_trigger_service(mocker)
    _expire_the_credentials(mocker)

    svc.maybe_fire_on_scan()

    last = svc.get_state().history[-1]
    assert last["status"] == "not_submitted", last
    assert last["order_id"] is None
    assert "ibkr_paper" in last["error"], "the row must name the broker that was unreachable"
    assert svc.get_state().armed is False


def test_a_live_broker_block_is_also_pre_submission(mocker):
    """The SECOND pre-submission raise inside `execute`, and the one a narrowing
    that stopped at "wrap router.execute" would have missed: the live-broker
    guard raises before the adapter lookup, so `ibkr_live` never contacts
    anything either.
    """
    at, svc = _scan_trigger_service(mocker)
    # `ArmedStrategy` is frozen (piece B), so swap the armed slot rather than
    # mutate it. Nothing holds the old object: the fire has not started.
    svc._state.strategy = dataclasses.replace(svc._state.strategy, broker="ibkr_live")
    _expire_the_credentials(mocker)

    svc.maybe_fire_on_scan()

    assert svc.get_state().history[-1]["status"] == "not_submitted"


def test_a_failure_inside_place_order_still_says_it_may_have_landed(mocker):
    """THE OTHER SIDE OF THE SPLIT, and the reason it is drawn at
    `adapter.place_order` rather than anywhere more convenient. Once that call
    is entered the auto-trader cannot know whether bytes reached the broker, so
    the conservative claim stands. A fix that moved every error to
    "nothing was sent" would be the same lie pointing the other way.
    """
    at, svc = _scan_trigger_service(mocker)
    import app.services.broker_router as br

    class _Exploding:
        def place_order(self, order):
            raise RuntimeError("connection reset after submit")

    mocker.patch.object(br, "build_router_from_credentials",
                        lambda: br.BrokerRouter(adapters={"ibkr_paper": _Exploding()}))
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan()

    assert len(calls) == 1
    assert "MAY HAVE LANDED" in calls[0][1], calls[0][1]
    assert svc.get_state().history[-1]["status"] == "order_failed"


def test_a_pre_submission_failure_is_not_paged_as_unclassified(mocker):
    """It must route to its OWN alert, not fall through to the unclassified one.
    "could not classify why" is the right message for a fire that recorded no
    row at all; here the cause is known exactly and naming it is the whole
    remedy — the operator has to go and refresh a credential.
    """
    at, svc = _scan_trigger_service(mocker)
    _expire_the_credentials(mocker)
    unclassified = mocker.patch.object(at, "_alert_unclassified_refusal")
    order_failed = mocker.patch.object(at, "_alert_order_failed")
    not_submitted = mocker.patch.object(at, "_alert_not_submitted")

    svc.maybe_fire_on_scan()

    unclassified.assert_not_called()
    order_failed.assert_not_called()
    assert not_submitted.call_count == 1
    assert not_submitted.call_args.args[0] == "MSFT"


def test_a_non_valueerror_before_submission_is_also_not_submitted(mocker):
    """PINS THE BREADTH OF THE CATCH, which survived a mutation to
    `except ValueError` when the F2 tests were first written — every one of
    them came in through `resolve`, so narrowing it changed nothing they
    measured while quietly sending the rest back to "may have landed".

    Not a hypothetical class: `credential_store.load()` runs `os.chmod` on the
    credentials file OUTSIDE its own try, and that raises OSError on a file the
    process cannot re-permission — root-owned after a manual edit, or a
    read-only mount. It contacts no broker, so it belongs on this side of the
    line, and its class is the only thing separating it from the ValueErrors.
    """
    at, svc = _scan_trigger_service(mocker)
    import app.services.credential_store as cs
    mocker.patch.object(cs.credential_store, "load",
                        side_effect=PermissionError("[Errno 1] chmod: credentials.yaml"))
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan()

    assert svc.get_state().history[-1]["status"] == "not_submitted"
    assert len(calls) == 1
    assert "MAY HAVE LANDED" not in calls[0][1], calls[0][1]


# --------------------------------------------------------------------------
# F3 of 2A-ALERT round 1 — the stale-arm disarm was the FOURTH silent refusal
# --------------------------------------------------------------------------

def _stale_armed_service(mocker, *, symbol="MSFT", age_minutes=60):
    """An armed service whose order has already aged past `max_arm_age_minutes`.

    The age is put on `armed_at` rather than achieved by patching the clock,
    because the guard compares the two and a test that moves both proves
    nothing. `max_arm_age_minutes` is left at its real value (30, from
    risk_rules.yaml) so the default configuration is what is exercised.
    """
    from datetime import timedelta
    import app.services.auto_trader as at
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    svc = AutoTradeService()
    armed = dataclasses.replace(
        _make_armed(symbol=symbol),
        armed_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    )
    svc.arm(armed)
    return at, svc


def test_an_expired_arm_alerts_instead_of_dying_silently(mocker):
    """F3, THE HEADLINE. The staleness guard consumed the armed order and
    returned BEFORE `maybe_fire_on_scan`'s try, so none of round 1's routing
    could see it: no history row, no alert, one `logger.warning` inside a
    worker thread whose return value POST /scan discards.

    Against `max_arm_age_minutes: 30` and a scan cadence in minutes this is
    plausibly the most frequent way an armed trade dies, which makes it the
    worst one to have had invisible. Drives the real `notify_alert` so the
    delivered TEXT is asserted, the same boundary the F2 tests use.
    """
    at, svc = _stale_armed_service(mocker)
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan()

    execute.assert_not_called()
    assert len(calls) == 1, "an expired arm consumed the order — it must reach a human"
    subject, body = calls[0]
    assert "MSFT" in subject
    assert "Nothing was sent" in body, body
    assert "MAY HAVE LANDED" not in body, (
        "the guard returns before fire() is even called — no order was built, "
        "let alone submitted:\n" + body
    )
    assert svc.get_state().armed is False


def test_an_expired_arm_records_its_own_history_row(mocker):
    """The ROW, not just the alert. Until F3 the guard wrote nothing at all, so
    the history showed the arm and then showed nothing — a reader could not
    distinguish "expired unfired" from "never triggered". The status is its own
    because the remedy is unique: not a limit to loosen, not a credential to
    fix, but a decision about whether the trade is still wanted.
    """
    at, svc = _stale_armed_service(mocker)
    mocker.patch("app.services.auto_trader.execute_option_order")
    # The alert is neutralised at the CHANNEL, not by patching the helper out of
    # the module. Patching `_alert_stale_arm` would make this test fail on a
    # pre-fix tree with AttributeError — "that name does not exist yet" — which
    # is a statement about the fix, not about the defect. Stubbing the channel
    # instead leaves the assertion below the only thing that can fail.
    _capture_alerts(mocker)

    svc.maybe_fire_on_scan()

    rows = svc.get_state().history
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["status"] == "stale_blocked", row
    assert row["symbol"] == "MSFT"
    assert row["order_id"] is None
    assert row["attempt_id"], "the row must name the attempt, like every other row"
    # Nothing was at risk, and `_check_daily_loss` sums this field over today's
    # rows — a non-zero value would spend the daily budget on a trade that
    # never happened.
    assert row["premium_at_risk"] == 0.0
    assert "regime_gate" not in row, (
        "regime_gate rides only rows whose order may be live; nothing was built here"
    )


def test_an_expired_arm_does_not_consume_an_order_re_armed_underneath_it(mocker):
    """THE INTERLEAVING THE FIX HAD TO CLOSE TO BE HONEST — F1's third one,
    on the one path that never got F1's `expect` because it never calls `fire()`.

    `strategy` is read in one lock acquisition and aged outside the lock. The
    old guard then called `disarm()`, which clears the slot UNCONDITIONALLY. A
    re-arm in that window therefore had a FRESH order destroyed on the EXPIRED
    one's age — and once F3 adds a row and an alert, it would also have paged
    about the expired symbol while silently throwing a live armed order away.

    Simulated at the seam rather than with threads: `_max_arm_age_minutes` is
    the last call before the lock is taken, so re-arming from inside it places
    the new order exactly in the window under test, deterministically.
    """
    at, svc = _stale_armed_service(mocker, symbol="MSFT")
    fresh = _make_armed(symbol="AAPL")
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    # Captured at the channel rather than by patching the helper — see
    # `test_an_expired_arm_records_its_own_history_row` for why that matters.
    calls = _capture_alerts(mocker)

    def _re_arm_in_the_window():
        svc.arm(fresh)
        return 30

    mocker.patch.object(AutoTradeService, "_max_arm_age_minutes",
                        staticmethod(_re_arm_in_the_window))

    svc.maybe_fire_on_scan()

    state = svc.get_state()
    assert state.armed is True, "the freshly armed order must survive the other one's expiry"
    assert state.strategy is fresh
    execute.assert_not_called()
    assert calls == [], "nothing was consumed, so there is nothing to report"
    assert state.history == [], "no order was consumed — no row belongs in history"


def test_an_equal_valued_re_arm_is_still_a_different_decision(mocker):
    """IDENTITY, NOT EQUALITY — and mutation testing is why this test exists:
    swapping the guard's `is` for `==` left the whole suite green, because the
    interleaving test above re-arms a DIFFERENT symbol, where the two operators
    agree.

    `ArmedStrategy` is a dataclass, so a re-arm of the very same contract
    compares `==` to the order that expired while being a different decision
    Kenneth made at a different time — its `armed_at` is fresh. Under `==` the
    guard would mistake it for the expired one and disarm it on the OLD order's
    age, destroying a brand-new arm that has not aged at all. Same reasoning as
    `fire()`'s `expect` check, which F1 pinned against this same mutation.
    """
    from datetime import timedelta
    at, svc = _stale_armed_service(mocker, symbol="MSFT")
    expired = svc.get_state().strategy
    # Equal in every field the dataclass compares, including armed_at, but a
    # DIFFERENT OBJECT: the strongest form of the case, since anything weaker
    # would be separated by `==` and prove nothing about `is`.
    twin = dataclasses.replace(_make_armed(symbol="MSFT"), armed_at=expired.armed_at)
    assert twin == expired and twin is not expired, (
        "this test is only meaningful if the two compare equal"
    )
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    calls = _capture_alerts(mocker)

    def _re_arm_in_the_window():
        svc.arm(twin)
        return 30

    mocker.patch.object(AutoTradeService, "_max_arm_age_minutes",
                        staticmethod(_re_arm_in_the_window))

    svc.maybe_fire_on_scan()

    state = svc.get_state()
    assert state.armed is True, (
        "the re-armed order was consumed on the expired twin's age — the guard "
        "compared by value instead of by identity"
    )
    assert state.strategy is twin
    execute.assert_not_called()
    assert calls == []
    assert state.history == []


def test_a_fresh_arm_is_untouched_by_the_staleness_path(mocker):
    """The regression guard against over-correcting. An order inside the age
    limit must still fire normally — the new row, alert and identity check must
    not leak onto the healthy path.
    """
    from app.data.ibkr_paper import OrderResult
    at, svc = _stale_armed_service(mocker, age_minutes=0)
    execute = mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="ok", status="PreSubmitted", broker="ibkr_paper"),
    )
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan()

    execute.assert_called_once()
    assert calls == [], "a healthy fire must not page anybody"
    assert all(r["status"] != "stale_blocked" for r in svc.get_state().history)


def test_two_symbols_expiring_in_one_dedup_window_both_alert(mocker):
    """THE ROUND-2 CRITICAL, applied to the refusal kind most able to trigger
    it: `notify_alert` keys dedup on `f"{rec_id}|{alert_type}"` and the symbol
    reaches only the body, so a shared key pages the first expiry and drops
    every other symbol's for the next four hours.

    HONEST ABOUT WHAT THIS PINS, because mutation testing showed it pins less
    than its name suggests: with `discrete=True` the delivered alert clears its
    own key, so this stays green even with a bare constant rec_id. It is a
    genuine end-to-end guard on the OUTCOME (two expiries, two pages) and it
    would catch the dedup path breaking, but it is NOT what holds the per-symbol
    key in place. `test_a_failed_dedup_clear_cannot_silence_another_symbol`
    below is the test that does that, in the one state where the two differ.
    """
    at, svc_a = _stale_armed_service(mocker, symbol="MSFT")
    mocker.patch("app.services.auto_trader.execute_option_order")
    calls = _capture_alerts(mocker)

    svc_a.maybe_fire_on_scan()

    _, svc_b = _stale_armed_service(mocker, symbol="AAPL")
    svc_b.maybe_fire_on_scan()

    assert len(calls) == 2, (
        "the second symbol's expiry was suppressed by the first symbol's dedup "
        f"window — got {[c[0] for c in calls]}"
    )
    assert any("MSFT" in s for s, _ in calls)
    assert any("AAPL" in s for s, _ in calls)


def test_an_expired_arm_does_not_page_under_the_order_failed_subject(mocker):
    """THE TYPE SPLIT, pinned where it is actually observable: the SUBJECT LINE.

    `_build_notification` builds the subject from the alert TYPE
    (`_ALERT_TYPE_LABELS.get(alert_type, alert_type)`), and none of the
    auto-trade types has a label entry, so the raw type string is what lands in
    Kenneth's inbox. An expiry reusing `AUTO_TRADE_ORDER_FAILED` would therefore
    arrive under the subject that means "the order may have landed, go and check
    the broker RIGHT NOW" — the most urgent page this module can send — for the
    most routine event it has.

    CORRECTED AFTER MUTATION TESTING. This test first asserted that the expiry
    could not SUPPRESS a later order-failed page, and it passed with the types
    shared, because `discrete=True` makes the expiry clear the key it just used
    (`forget_alerts` matches on rec_id across every type). The suppression this
    was named for cannot happen; the subject collision can, and that is what is
    asserted now.
    """
    import app.services.auto_trader as at_mod
    at, svc = _stale_armed_service(mocker, symbol="MSFT")
    mocker.patch("app.services.auto_trader.execute_option_order")
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan()
    # A genuine may-have-landed page for the SAME symbol, for contrast.
    at_mod._alert_order_failed("MSFT", RuntimeError("connection reset after submit"))

    assert len(calls) == 2, calls
    expiry_subject, expiry_body = calls[0]
    failed_subject, _ = calls[1]
    assert expiry_subject != failed_subject, (
        "a routine expiry and a may-have-landed page arrived under the SAME "
        f"subject line: {expiry_subject!r}"
    )
    assert "ORDER_FAILED" not in expiry_subject, expiry_subject
    assert "EXPIRED" in expiry_subject, expiry_subject


def test_a_repeat_expiry_of_the_same_symbol_alerts_again(mocker):
    """WHY THE ALERT IS `discrete=True`. An expiry is an EVENT, not a standing
    condition: Kenneth re-arms MSFT, it ages out again forty minutes later, and
    that second death is as worth knowing as the first. Without the discrete
    clear the second falls inside the first's four-hour window and is dropped —
    and because expiry is the routine refusal, that window would be armed
    almost permanently, which is §9.1's "and alert" half silently off for the
    most common case.
    """
    at, svc = _stale_armed_service(mocker, symbol="MSFT")
    mocker.patch("app.services.auto_trader.execute_option_order")
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan()
    # Re-armed, and it expires again inside the same dedup window.
    _, svc2 = _stale_armed_service(mocker, symbol="MSFT")
    svc2.maybe_fire_on_scan()

    assert len(calls) == 2, (
        "the second expiry of the same symbol was suppressed by the first's "
        "dedup window — an expiry is a discrete event, not a standing condition"
    )
    assert "(reminder)" not in calls[1][0], (
        "the second expiry is a NEW event, not a reminder about the first"
    )


def test_a_failed_dedup_clear_cannot_silence_another_symbol(mocker):
    """WHY THE REC_ID CARRIES THE SYMBOL even though `discrete=True` normally
    clears it — the degraded path `_alert_refusal` warns about in its own error
    branch: "the next refusal of this key will be suppressed for the rest of the
    window".

    If `forget_alerts` fails, the hold STAYS. With a per-symbol key that costs
    the one symbol. With a bare constant it costs EVERY symbol's expiry for four
    hours, persisted across a restart. That is the only state in which the two
    key choices differ, which is why it needs its own test: mutation testing
    showed the ordinary two-symbol case green either way.
    """
    import app.services.notifications.alert_notifier as an
    at, svc = _stale_armed_service(mocker, symbol="MSFT")
    mocker.patch("app.services.auto_trader.execute_option_order")
    calls = _capture_alerts(mocker)
    mocker.patch.object(an, "forget_alerts",
                        side_effect=RuntimeError("dedup file not writable"))

    svc.maybe_fire_on_scan()          # MSFT expires; its hold is NOT cleared
    _, svc2 = _stale_armed_service(mocker, symbol="AAPL")
    svc2.maybe_fire_on_scan()         # a DIFFERENT symbol expires

    assert len(calls) == 2, (
        "AAPL's expiry was silenced by MSFT's stuck dedup hold — the rec_id is "
        f"not per-symbol. Delivered: {[c[0] for c in calls]}"
    )
    assert any("AAPL" in sub for sub, _ in calls)


def test_the_expiry_alert_is_sent_without_holding_the_state_lock(mocker):
    """The comment on that call says "OUTSIDE THE LOCK" — this is what makes it
    a fact rather than a hope, and mutation testing is why it exists: moving the
    call inside the lock left the whole suite green.

    It is not a deadlock (the notifier never re-enters this lock), which is
    exactly why nothing else catches it. It is an AVAILABILITY defect: the alert
    path runs a fresh event loop and talks to SMTP and Telegram, so holding the
    state lock across it blocks `get_state`, `arm`, `disarm` and every other
    scan trigger for the full network timeout. GET /auto-trade/state would hang
    behind a mail server — the same rule `fire()` follows for `_market_is_open`.

    Probed from inside the delivery call itself, where the lock is either held
    or it is not, rather than by timing anything.
    """
    at, svc = _stale_armed_service(mocker)
    mocker.patch("app.services.auto_trader.execute_option_order")
    import app.services.notifications.alert_notifier as an
    lock_was_free: list = []

    async def _probe_channels(subject, plain, html):
        got = svc._lock.acquire(blocking=False)
        lock_was_free.append(got)
        if got:
            svc._lock.release()
        return True

    mocker.patch.object(an, "notify_enabled_channels", _probe_channels)
    mocker.patch.object(an, "_save_dedup", lambda: None)
    mocker.patch.object(an, "_load_delivery_config", lambda: {"masterEnabled": True})

    svc.maybe_fire_on_scan()

    assert lock_was_free == [True], (
        "the expiry alert was dispatched while holding the auto-trader's state "
        "lock — every reader of that state blocks for the notifier's timeout"
    )


def test_an_expired_arm_refusal_is_still_recorded_when_the_notifier_is_dead(mocker):
    """The refusal has already happened and the order is already consumed, so a
    dead SMTP server must not turn it into an exception inside POST /scan's
    worker thread — nor cost the history row, which is the durable record.
    """
    at, svc = _stale_armed_service(mocker)
    mocker.patch("app.services.auto_trader.execute_option_order")
    import app.services.notifications.alert_notifier as an
    mocker.patch.object(an, "notify_alert", side_effect=RuntimeError("SMTP down"))

    svc.maybe_fire_on_scan()   # must not raise

    assert svc.get_state().history[-1]["status"] == "stale_blocked"
    assert svc.get_state().armed is False


# ---------------------------------------------------------------------------
# Round 5 of target 2a: the fences the fire()/gate delta was missing.
#
# All six of these pin behaviour that already held at HEAD. Round 5 found it
# held by ACCIDENT rather than by assertion: each mutation named below survived
# the full 272-test auto-trade suite before these were written.
# ---------------------------------------------------------------------------


def test_the_refusal_classes_are_disjoint_from_the_silent_one(mocker):
    """No refusal that CONSUMES the armed order may be an `ArmPreservedError`.

    `maybe_fire_on_scan` stays silent on that class alone, on the stated
    invariant that it is raised only BEFORE `fire()`'s disarm. Making any
    consumed-refusal class a subclass of it routes a real refusal into the
    silence -- and round 5 measured `class RegimeHeadwindError(ArmPreservedError)`
    passing 272/272. The invariant is load-bearing, so it is asserted here.
    """
    from app.services.auto_trader import (
        ArmPreservedError, OrderNotSubmittedError,
        RegimeHeadwindError, RegimeGateConfigError,
    )
    from app.scoring.conviction_sizing import SizingConfigError
    for cls in (RegimeHeadwindError, RegimeGateConfigError,
                SizingConfigError, OrderNotSubmittedError):
        assert not issubclass(cls, ArmPreservedError), (
            f"{cls.__name__} consumes the armed order, so it must not be "
            f"caught by maybe_fire_on_scan's deliberate silence"
        )


def test_an_arm_preserved_error_raised_after_the_disarm_still_alerts(mocker):
    """The silence is conditional on nothing having been consumed.

    THE FAILURE THIS FORBIDS, reproduced by round 5 against the real module: a
    post-disarm `ArmPreservedError` consumed the armed order and produced ZERO
    history rows and ZERO alerts -- the only fully silent exit in the module.
    """
    import app.services.auto_trader as at
    from app.services.auto_trader import ArmPreservedError
    mocker.patch.object(at, "_market_is_open", return_value=True)
    # RAISED FROM PAST THE DISARM, and from the one place it escapes with NO
    # ROW AT ALL: `_apply_vol_sizing` runs after the disarm and its handlers
    # name `SizingConfigError`, `ValueError`, `RegimeHeadwindError` and
    # `RegimeGateConfigError` -- this class matches none of them, so it leaves
    # `fire()` unwrapped and unrecorded. That zero-row shape is why the guard
    # cannot be "did this attempt write a row"; it has to be a marker taken at
    # the disarm itself.
    mocker.patch.object(at, "_apply_vol_sizing",
                        side_effect=ArmPreservedError("raised too late"))
    unclassified = mocker.patch.object(at, "_alert_unclassified_refusal")

    svc = AutoTradeService()
    svc.arm(_make_armed(symbol="MSFT"))
    svc.maybe_fire_on_scan()   # must not raise

    assert svc.get_state().armed is False, "the order was consumed"
    assert unclassified.call_count == 1, (
        "a consumed armed order must never be silent, whatever class arrives"
    )


def test_every_one_of_the_seven_rows_fire_writes_carries_its_attempt_id(mocker):
    """The stamp, on all seven rows -- including the two gate refusals.

    The pre-existing `test_every_history_row_...` patches `_apply_vol_sizing`
    to identity, so no GATE refusal is ever produced: it asserts on 2 of the 7
    rows and misses `regime_headwind_blocked` and `regime_gate_config_blocked`,
    two of the four this target owns. Round 5's per-row mutation sweep found
    exactly those two survive having their `attempt_id` dropped. Driven here
    through the REAL gate rather than a stub, so the rows are the real ones.
    """
    import app.services.auto_trader as at
    from app.services.auto_trader import RegimeHeadwindError, RegimeGateConfigError

    def _fire_expecting(exc_type, patch):
        svc = AutoTradeService()
        patch(svc)
        svc.arm(_make_armed(symbol="MSFT"))
        with pytest.raises(exc_type):
            svc.fire(attempt_id="attempt-STAMP")
        row = svc.get_state().history[-1]
        assert row["attempt_id"] == "attempt-STAMP", (
            f"{row['status']} row lost its stamp -- maybe_fire_on_scan then "
            f"cannot correlate this refusal to its attempt and pages "
            f"unclassified about a refusal it recorded perfectly well"
        )
        return row["status"]

    mocker.patch.object(at, "_market_is_open", return_value=True)

    headwind = _fire_expecting(
        RegimeHeadwindError,
        lambda svc: mocker.patch.object(
            at, "_apply_vol_sizing",
            side_effect=RegimeHeadwindError("regime headwind")),
    )
    assert headwind == "regime_headwind_blocked"

    gate_config = _fire_expecting(
        RegimeGateConfigError,
        lambda svc: mocker.patch.object(
            at, "_apply_vol_sizing",
            side_effect=RegimeGateConfigError("regime_gate block is not a mapping")),
    )
    assert gate_config == "regime_gate_config_blocked"


def test_a_failing_risk_check_leaves_a_row_instead_of_vanishing(mocker):
    """A crashed risk check consumed the armed order -- it must still record.

    MEASURED BEFORE THE FIX: `_check_exposure` raising a `TypeError` consumed
    the arm, wrote NO row, escaped `fire_now`'s `except (ValueError,
    RuntimeError)` as a 500, and left `/auto-trade/status` still reporting the
    PREVIOUS order as `last_order`.

    And the attribution matters as much as the row: this must NOT be filed as
    `cap_blocked`, which would tell Kenneth his exposure caps blocked a trade
    they never evaluated.
    """
    import app.services.auto_trader as at
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    mocker.patch.object(AutoTradeService, "_check_exposure",
                        staticmethod(mocker.Mock(side_effect=TypeError("risk engine broke"))))

    svc = AutoTradeService()
    svc.arm(_make_armed(symbol="MSFT"))
    with pytest.raises(TypeError):
        svc.fire(attempt_id="attempt-RISK", portfolio_snapshot=[])

    row = svc.get_state().history[-1]
    assert row["status"] == "risk_check_failed"
    assert row["status"] != "cap_blocked", "the caps never ran -- do not blame them"
    assert row["attempt_id"] == "attempt-RISK"
    assert svc.get_state().armed is False


def test_the_early_expect_check_is_present(mocker):
    """The first of the two `expect` identity checks, pinned.

    It is an OPTIMIZATION -- it saves `_market_is_open`'s 3s fetch when the arm
    has already moved on -- and the load-bearing one is the second, inside the
    disarm's lock. Round 5 measured that deleting this one passes 272/272,
    which means the half a reader is most likely to tidy away has no signal at
    all. Asserted on the observable: a mismatched `expect` must refuse WITHOUT
    the halt fetch having run.
    """
    import app.services.auto_trader as at
    from app.services.auto_trader import ArmPreservedError
    halt = mocker.patch.object(at, "_market_is_open", return_value=True)

    svc = AutoTradeService()
    svc.arm(_make_armed(symbol="MSFT"))
    with pytest.raises(ArmPreservedError):
        svc.fire(expect=_make_armed(symbol="MSFT"))   # a DIFFERENT object

    assert halt.call_count == 0, (
        "the early check exists to refuse before the 3s halt fetch"
    )
    assert svc.get_state().armed is True, "a mismatch preserves the arm"


def test_which_rows_carry_the_regime_gate_outcome(mocker):
    """Pins WHICH rows carry `regime_gate`, because nothing did.

    F2 split the credential-expiry failure out of `order_failed` into
    `not_submitted`, and in doing so stopped that class of attempt carrying the
    gate's verdict -- the row's comment states the rule it followed ("rides
    only where an order may be live"), but no test asserted either way, so the
    change was invisible. Kenneth decided (A7a, 2026-09-24) that it SHOULD
    carry it -- and `sizing` -- so this now pins that rule.
    """
    import app.services.auto_trader as at
    from app.data.ibkr_paper import OrderResult
    from app.services.auto_trader import OrderNotSubmittedError
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)

    mocker.patch.object(at, "execute_option_order",
                        return_value=OrderResult("oid", "filled", "ibkr_paper"))
    svc = AutoTradeService()
    svc.arm(_make_armed(symbol="MSFT"))
    svc.fire(attempt_id="a-filled")
    assert "regime_gate" in svc.get_state().history[-1], (
        "the filled row carries it: a trade the gate never evaluated must not "
        "look identical afterwards to one it passed"
    )

    mocker.patch.object(at, "execute_option_order",
                        side_effect=OrderNotSubmittedError("credentials expired"))
    svc.arm(_make_armed(symbol="MSFT"))
    with pytest.raises(RuntimeError):
        svc.fire(attempt_id="a-notsub")
    row = svc.get_state().history[-1]
    assert row["status"] == "not_submitted"
    # FLIPPED DELIBERATELY by decision A7A-NOT-SUBMITTED-CARRIES-GATE-2026-09-24:
    # the gate ran upstream of the submission, so its verdict is recorded.
    assert "regime_gate" in row and "sizing" in row, (
        "A7a: not_submitted carries what the gate and the sizer decided"
    )


@pytest.mark.asyncio
async def test_the_manual_fire_endpoint_fires_the_order_it_checked(mocker):
    """`POST /auto-trade/fire` must pass `expect`, like the scan trigger does.

    THE SHAPE `expect` EXISTS FOR, from `fire()`'s own docstring: a caller that
    reads the armed slot, decides something about what it read, and only then
    calls. This endpoint does exactly that -- its 400 is that decision -- and
    F1 migrated `maybe_fire_on_scan` while leaving this caller passing nothing.

    Without it, `fire()` resolves the halt check against the symbol read in its
    first lock block and submits whatever the second one finds, so a re-arm
    inside that window -- which spans a 3s network fetch -- authorizes order B
    on order A's halt decision. Round 5 reproduced that against the real
    service: `halt check ran for: ['AAPL']`, `order submitted for: ['HALTD']`.

    Not reachable over HTTP today only because `fire_now` blocks the loop; that
    is this endpoint's shape, not a guard, and it is why this is asserted on
    the contract rather than raced.
    """
    from app.routers import auto_trade as rt
    from app.data.ibkr_paper import OrderResult

    class _FakeResult:
        def scalars(self):
            return self
        def all(self):
            return []

    class _FakeDb:
        async def execute(self, *a, **k):
            return _FakeResult()

        # P3c item 7: fire_now releases the snapshot read's transaction
        # before it waits on the fire executor.
        async def rollback(self):
            pass

    armed = _make_armed(symbol="MSFT")
    rt.auto_trader.arm(armed)
    fire_spy = mocker.patch.object(
        rt.auto_trader, "fire",
        return_value=FiredOrder(OrderResult("oid", "filled", "ibkr_paper"),
                                armed, "a-endpoint"))
    # O4 steps 4+5: the endpoint now books what fired. Not this test's subject
    # (it is about `expect`), and `_FakeDb` has no `commit`.
    mocker.patch.object(rt, "book_fired_order", AsyncMock())
    try:
        await rt.fire_now(db=_FakeDb())
    finally:
        rt.auto_trader.disarm()

    assert fire_spy.call_count == 1
    assert fire_spy.call_args.kwargs.get("expect") is armed, (
        "the endpoint must fire the exact armed order its 400 check read"
    )


# Daily source/count/settlement/cache tests now live in test_daily_regime_integrations.py.
# Old 441-day/provider-trim expectations were superseded by the uniform DB reader.
# Independent market-session utility tests below still apply.
def _ny(y, m, d, hh, mm=0):
    from app.services.scheduling_tz import MARKET_TZ
    return datetime(y, m, d, hh, mm, tzinfo=MARKET_TZ)


@pytest.mark.parametrize("now,expected,why", [
    # 2026-06-10 is a Wednesday; 2026-06-13 a Saturday.
    (_ny(2026, 6, 10, 10, 0),  True,  "mid-session: the bar is being written"),
    (_ny(2026, 6, 10, 9, 30),  True,  "the open itself is inside the session"),
    (_ny(2026, 6, 10, 15, 59), True,  "one minute before the close"),
    (_ny(2026, 6, 10, 7, 0),   True,  "PRE-OPEN: the session has not started, "
                                      "so today's bar is not complete either"),
    (_ny(2026, 6, 10, 16, 30), False, "after the close: today's bar IS the last "
                                      "completed session and must be KEPT"),
    (_ny(2026, 6, 10, 23, 59), False, "late evening, same session day"),
    (_ny(2026, 6, 13, 8, 0),   True,  "weekend before 09:30 — trims, which is "
                                      "the conservative side and inert (no "
                                      "feed dates a bar on a Saturday)"),
    # WEEKEND AFTER 09:30 — the one arm the docstring names explicitly
    # ("WEEKENDS after 09:30 read complete here") and the only arm round 1
    # found unpinned. Inert in production because `last_day >= today` is False
    # on a Saturday, but it is that INERTNESS ARGUMENT that goes unchecked if
    # the arm itself is never exercised.
    (_ny(2026, 6, 13, 10, 0),  False, "Saturday mid-'session': `_market_open` "
                                      "is False on a weekend and 10:00 is not "
                                      "< 09:30, so this reads complete"),
    (_ny(2026, 6, 13, 16, 0),  False, "Saturday at the 16:00 boundary — the "
                                      "weekday inclusivity of `<= 16:00` does "
                                      "not apply, the weekday test fails first"),
    (_ny(2026, 6, 13, 20, 0),  False, "Saturday evening"),
    # F-10, recorded as behaviour rather than described: `_market_open`'s upper
    # bound is INCLUSIVE, so the bell itself still reads "unclosed".
    (_ny(2026, 6, 10, 16, 0),  True,  "16:00:00 exactly — `_market_open` is "
                                      "`<= dtime(16, 0)`, so the bell instant "
                                      "trims; 16:00:01 (below) keeps"),
    (_ny(2026, 6, 10, 16, 1),  False, "one minute after the bell"),
])
def test_guard_i_todays_bar_is_unclosed_tracks_real_session_hours(now, expected, why):
    """The session test itself, on explicit MARKET_TZ instants.

    Both clauses are load-bearing and both are pinned here: `_market_open`
    answers mid-session, and the `< 09:30` clause answers PRE-OPEN, which
    `_market_open` reads as False and which would otherwise keep a bar for a
    session that has not started — round 3's defect with the sign flipped.
    """
    from app.services import auto_trader as at

    assert at._todays_bar_is_unclosed(now) is expected, why


def test_guard_i_uses_the_schedulers_session_test_not_the_price_probe(mocker):
    """The mechanism is the decision, so the mechanism is pinned.

    `_market_is_open` MUST NOT be what decides this: it is a `fetch_price`
    probe that serves close/previous_close around the clock. The scheduler's
    `_market_open` is the real MARKET_TZ hours test and is reused rather than
    copied.

    ROUND 1 F-6: this test used to close with `price_probe.call_count == 0`,
    which pinned NOTHING — `_market_is_open` takes a required `symbol` and
    `_todays_bar_is_unclosed` has no symbol to give it, so there is no shape in
    which it could be called and no mutant the assertion kills. What does the
    real work is `session.call_count == 1` (it kills an inlined re-implementation
    of the hours test) and the ARGUMENT check below, which additionally pins
    F-3's normalisation at the seam where it matters.
    """
    from app.services import auto_trader as at
    from app.services import market_session as ms
    from app.services.scheduling_tz import MARKET_TZ

    # A4g: the hours-test import moved to market_session with the helper (moved,
    # not copied), so the seam is patched where the helper now reads it.
    session = mocker.patch.object(ms, "_market_session_open", return_value=True)

    assert at._todays_bar_is_unclosed(_ny(2026, 6, 10, 10, 0)) is True
    assert session.call_count == 1, "the real session test was not consulted"

    (passed,) = session.call_args.args
    assert passed.utcoffset() == _ny(2026, 6, 10, 10, 0).utcoffset(), (
        "the scheduler's hours test was handed an instant on some other wall "
        "clock — it reads `now.time()`, so that is a silent wrong answer"
    )
    assert passed.tzinfo is MARKET_TZ, (
        "the instant reaching the hours test was not normalised to MARKET_TZ"
    )


def test_guard_i_normalises_an_aware_instant_to_market_tz():
    """F-3: the same real instant must give the same answer on any wall clock.

    NY 20:00 is 00:00 UTC the NEXT DAY. Without the `.astimezone(MARKET_TZ)`
    the `< 09:30` clause reads the UTC wall clock, calls a closed market
    "pre-open", and trims a bar that closed four hours ago — F1 restored, from
    nothing worse than a caller choosing a different tzinfo.
    """
    from app.services import auto_trader as at
    from app.services import market_session as ms  # A4g: `_NYSE_OPEN` moved with the helper

    ny_evening = _ny(2026, 6, 10, 20, 0)
    as_utc = ny_evening.astimezone(timezone.utc)

    assert as_utc.time() < ms._NYSE_OPEN, (
        "premise check: this instant IS < 09:30 on the UTC wall clock"
    )
    assert at._todays_bar_is_unclosed(ny_evening) is False
    assert at._todays_bar_is_unclosed(as_utc) is False, (
        "the same instant answered differently depending on its tzinfo"
    )


def test_guard_i_refuses_a_naive_instant():
    """F-3: naive is ambiguous, so it raises instead of being guessed at.

    MARKET_TZ wall-clock and `.astimezone()`'s host-zone reading are both
    defensible and differ by the host's offset. Refusing also kills a mutant
    class outright: a call site that hands the helper a frozen naive literal
    cannot fail silently.
    """
    from app.services import auto_trader as at

    with pytest.raises(ValueError, match="AWARE"):
        at._todays_bar_is_unclosed(datetime(2026, 6, 10, 12, 0))


def test_guard_i_nyse_open_matches_the_schedulers_own_boundary():
    """F-9: `_NYSE_OPEN` is a SECOND COPY of the scheduler's 09:30.

    The two constants are read by the two clauses of one predicate, so a drift
    between them opens a gap or an overlap around the open. The scheduler keeps
    its boundary inline, so this is pinned by behaviour rather than by symbol:
    one minute before the copy must be pre-open, and the boundary itself must
    be inside the scheduler's session.
    """
    from app.services import market_session as ms  # A4g: `_NYSE_OPEN` moved with the helper
    from app.services.strategy_watch_scheduler import _market_open

    boundary = _ny(2026, 6, 10, ms._NYSE_OPEN.hour, ms._NYSE_OPEN.minute)

    assert _market_open(boundary) is True, (
        "`_NYSE_OPEN` is not the scheduler's open — the `< _NYSE_OPEN` clause "
        "and the session test disagree about where the session starts"
    )
    assert _market_open(boundary - timedelta(minutes=1)) is False, (
        "the scheduler's session starts BEFORE `_NYSE_OPEN`, so the minute "
        "between them is claimed by neither clause"
    )


# --------------------------------------------------------------------------
# Piece B — a malformed `direction` is refused at construction
# (docs/superpowers/plans/2026-09-18-B-armed-strategy-runtime-validation.md §5)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["bullish", "Bulish", "BULLISH", "", None, " Bullish", 1])
def test_a_malformed_direction_is_refused_at_construction(bad):
    """Before piece B every one of these constructed and then sized as BEARISH,
    because `_apply_vol_sizing`'s `== "Bullish"` sends anything else to `else`."""
    from app.services.auto_trader import MalformedDirectionError
    with pytest.raises(MalformedDirectionError, match="direction"):
        dataclasses.replace(_make_armed(), direction=bad)


def test_an_object_equal_to_everything_is_refused():
    """Membership alone would pass it (`in` falls back to `==`), and it would then
    steer `strategy.direction == "Bullish"` in `_apply_vol_sizing` -- so the guard
    requires an actual `str` first."""
    from app.services.auto_trader import MalformedDirectionError

    class _EqualsAnything:
        def __eq__(self, other):
            return True
        __hash__ = object.__hash__

    with pytest.raises(MalformedDirectionError):
        dataclasses.replace(_make_armed(), direction=_EqualsAnything())


@pytest.mark.parametrize("bad", ["bullish", None])
def test_a_malformed_direction_never_reaches_the_armed_slot(bad):
    """The refusal is before `arm()`, so there is nothing armed to fire and no
    history row, alert or rec_id to file it under."""
    from app.services.auto_trader import MalformedDirectionError
    svc = AutoTradeService()
    with pytest.raises(MalformedDirectionError):
        svc.arm(ArmedStrategy(
            broker="ibkr_paper", symbol="AAPL", option_symbol="AAPL260620C00185000",
            action="BUY", direction=bad, quantity=1, order_type="LMT",
            limit_price=2.5, conid=None, entry_premium=2.5,
        ))
    state = svc.get_state()
    assert state.armed is False and state.strategy is None and state.history == []


@pytest.mark.parametrize("good", ["Bullish", "Bearish"])
def test_both_valid_directions_construct(good):
    assert dataclasses.replace(_make_armed(), direction=good).direction == good


def test_the_guard_accepts_exactly_the_direction_literal():
    """Pins the guard to `app.schemas.Direction` rather than a hand-kept copy, so
    widening the Literal widens the guard and nothing else has to remember to."""
    from typing import get_args
    from app.schemas import Direction
    assert set(get_args(Direction)) == {"Bullish", "Bearish"}
    for d in get_args(Direction):
        dataclasses.replace(_make_armed(), direction=d)


def test_replace_still_works_on_a_valid_strategy():
    """Production changes an armed strategy ONLY through `dataclasses.replace`
    (`_apply_vol_sizing`'s two `_dc_replace` calls), so freezing must not break it."""
    s = _make_armed(qty=1)
    t = dataclasses.replace(s, quantity=3, regime_gate_outcome="passed")
    assert (t.quantity, t.regime_gate_outcome, t.direction) == (3, "passed", "Bullish")
    assert s.quantity == 1 and s.regime_gate_outcome is None


@pytest.mark.parametrize("field_name,value", [("direction", "bullish"), ("quantity", 5)])
def test_an_armed_strategy_cannot_be_mutated(field_name, value):
    """FROZEN IS PART OF THE FIX: without it `s.direction = "x"` would skip the
    check, and the next `_dc_replace` inside fire()'s sizing `try` would re-run
    it there -- raising into the refusal taxonomy piece B exists to stay out of."""
    s = _make_armed()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(s, field_name, value)
    assert s.direction == "Bullish" and s.quantity == 1


def test_malformed_direction_error_is_not_a_value_error():
    """Round 3's lesson, pinned: fire()'s inner handler catches
    `(SizingConfigError, ValueError)` and files it as `sizing_data_blocked` with a
    log line blaming the conviction. This refusal must never be able to land there."""
    from app.services.auto_trader import MalformedDirectionError, SizingConfigError
    assert issubclass(MalformedDirectionError, TypeError)
    assert not issubclass(MalformedDirectionError, ValueError)
    assert not issubclass(MalformedDirectionError, SizingConfigError)


# ── Q2 hardening: the risk is computed ONCE, before the order ───────────────
#
# `fire()` used to resolve `premium_stop_pct` twice: inside `_check_daily_loss`
# before the order, and again after `execute_option_order` for the success
# row's `premium_at_risk`. A second computation AFTER a broker call is the one
# place where a disagreement means a placed order with no history row. These
# pin that there is none. Since A6 the risk is the FULL premium and no stop
# fraction is resolved on the fire path at all; the tests below were rewritten
# deliberately to pin that.


def _q2_fire_service(mocker):
    from app.data.ibkr_paper import OrderResult
    import app.services.auto_trader as at
    mocker.patch.object(at, "_market_is_open", return_value=True)
    execute = mocker.patch.object(at, "execute_option_order",
                                  return_value=OrderResult("q2", "ok", "ibkr_paper"))
    svc = AutoTradeService()
    svc.arm(_make_armed())
    return svc, execute


def test_the_success_row_books_the_risk_the_breaker_gated_on(mocker):
    """The success row books exactly the dollars `_check_daily_loss` gated on
    -- the full premium since A6 -- and the config is read once, before the
    order. Any later config read returns a malformed value; the row must not
    care."""
    reads = []

    def _cfg():
        reads.append(1)
        return ({"max_daily_loss_pct": 1.0} if len(reads) == 1
                else {"max_daily_loss_pct": "2%"})

    mocker.patch.object(AutoTradeService, "_risk_config", staticmethod(_cfg))
    svc, execute = _q2_fire_service(mocker)
    gated = mocker.spy(AutoTradeService, "_check_daily_loss")

    fired = svc.fire(portfolio_value=100_000.0)

    assert fired.result.order_id == "q2"
    execute.assert_called_once()
    row = svc.get_state().history[-1]
    assert row["order_id"] == "q2"
    # 2.50 x 1 x 100 -- the full premium, the value the breaker gated on.
    assert row["premium_at_risk"] == pytest.approx(250.0)
    assert row["premium_at_risk"] == gated.spy_return
    assert len(reads) == 1, "the config was read again after the order went out"


def test_no_stop_fraction_is_resolved_on_the_fire_path(mocker):
    """A6: the daily-loss gate no longer reads a premium stop, so the fire
    path resolves none. `auto_trader` no longer imports
    `resolve_premium_stop_pct`, and the source-module function is never called
    during a fire."""
    import app.services.auto_trader as at
    import app.services.premium_stop as ps
    assert not hasattr(at, "resolve_premium_stop_pct")
    mocker.patch.object(AutoTradeService, "_risk_config",
                        staticmethod(lambda: {"max_daily_loss_pct": 1.0,
                                              "premium_stop_pct": 0.60}))
    spy = mocker.spy(ps, "resolve_premium_stop_pct")
    svc, _ = _q2_fire_service(mocker)

    svc.fire(portfolio_value=100_000.0)

    assert spy.call_count == 0
    assert svc.get_state().history[-1]["order_id"] == "q2"


def test_a_malformed_premium_stop_key_no_longer_affects_the_fire(mocker):
    """FLIPPED DELIBERATELY. Before A6 a non-numeric
    `auto_trade.premium_stop_pct` was refused because the breaker read it.
    Since A6 nothing reads that key, so the fire proceeds and books the full
    premium. A malformed `max_daily_loss_pct` IS still refused (the
    risk_rules.yaml fault test earlier in this file)."""
    mocker.patch.object(AutoTradeService, "_risk_config",
                        staticmethod(lambda: {"max_daily_loss_pct": 1.0,
                                              "premium_stop_pct": "60%"}))
    svc, execute = _q2_fire_service(mocker)

    svc.fire(portfolio_value=100_000.0)

    execute.assert_called_once()
    row = svc.get_state().history[-1]
    assert row["order_id"] == "q2"
    assert row["premium_at_risk"] == pytest.approx(250.0)


# ── P3b: auto-trader hardening (docs/superpowers/plans/2026-09-25-p3b-auto-trader-hardening-plan.md) ──


def _doc_with(**overrides):
    """The real scoring doc with top-level blocks replaced — IN MEMORY ONLY.
    Never written to backend/config; patched in over `_load_scoring_doc`."""
    import copy
    import app.services.auto_trader as at
    doc = copy.deepcopy(at._load_scoring_doc())
    doc.update(overrides)
    return doc


@pytest.mark.parametrize("fault", ["type_error", "float_value_error"])
def test_a_daily_loss_config_fault_writes_one_risk_check_failed_row(mocker, fault):
    """Phase AUTOTRADE-DAILY-LOSS-FAULT-TEST (2A-GATE round 6's missing guard).

    `_check_daily_loss` failing -- a TypeError, or the `float()` ValueError on
    a `max_daily_loss_pct: "2%"` -- has consumed the armed order, so it must
    leave EXACTLY ONE `risk_check_failed` row (not `daily_loss_blocked`: the
    breaker never evaluated) and page the unclassified alert once.
    """
    at, svc = _scan_trigger_service(mocker)
    if fault == "type_error":
        mocker.patch.object(AutoTradeService, "_check_daily_loss",
                            staticmethod(mocker.Mock(side_effect=TypeError("breaker broke"))))
    else:
        mocker.patch.object(AutoTradeService, "_risk_config",
                            return_value={"max_daily_loss_pct": "2%",
                                          "premium_stop_pct": 0.60})
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    unclassified = mocker.patch.object(at, "_alert_unclassified_refusal")
    before = len(svc.get_state().history)

    svc.maybe_fire_on_scan()

    rows = svc.get_state().history[before:]
    assert len(rows) == 1, rows
    assert rows[0]["status"] == "risk_check_failed"
    assert rows[0]["error"].startswith("daily-loss check failed:")
    assert rows[0]["premium_at_risk"] == 0.0
    assert rows[0]["attempt_id"]
    execute.assert_not_called()
    assert svc.get_state().armed is False
    assert unclassified.call_count == 1
    assert unclassified.call_args.args[0] == "MSFT"


def test_an_ibkr_reply_with_an_id_and_an_empty_message_list_is_a_question(mocker):
    """P3b E1: `{"id": ..., "message": []}` is the reply-message shape with no
    text. It used to read as an order with no id; it is a question now."""
    import app.data.ibkr_paper as ib
    from app.data.ibkr_paper import BrokerOrder, IbkrPaperAdapter

    class _Resp:
        status_code = 200
        text = ""

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    mocker.patch.object(ib, "paper_gateway_available", return_value=True)
    adapter = IbkrPaperAdapter(base_url="https://localhost:7499/v1/api",
                               account_id="DU123456")
    order = BrokerOrder(symbol="MSFT", action="BUY", effect="OPEN", quantity=1,
                        order_type="LMT", limit_price=2.5, sec_type="OPT", conid=123)
    for body, expected in [
        ([{"id": "abc", "message": []}], True),
        ([{"id": "abc", "message": ""}], True),
        ([{"id": "abc"}], False),                       # no message key at all
        ([{"order_id": "1", "id": "abc", "message": []}], False),  # an order
    ]:
        mocker.patch.object(ib.httpx, "post", return_value=_Resp(body))
        assert adapter.place_order(order).awaiting_confirmation is expected, body


def test_a_bad_arm_request_reject_threshold_does_not_blame_the_yaml(mocker):
    """P3b E3: the NaN came from the ARM REQUEST, the YAML is fine -- the
    refusal must say so rather than send the operator to scoring_rules.yaml."""
    from app.services.auto_trader import RegimeGateConfigError
    with pytest.raises(RegimeGateConfigError) as ei:
        _gate_fire(mocker, reject_pct=float("nan"))
    msg = str(ei.value)
    assert "armed with" in msg and "not scoring_rules.yaml" in msg
    assert "scoring_rules.yaml's regime_gate.headwind_reject_pct" not in msg


def test_a_bad_yaml_reject_threshold_still_names_the_yaml(mocker, monkeypatch):
    import app.services.auto_trader as at
    from app.services.auto_trader import RegimeGateConfigError
    monkeypatch.setattr(at, "_load_regime_gate_config", lambda: {
        "enabled": True, "headwind_caution_pct": -15,
        "headwind_reject_pct": "x", "require_stable_for_reject": True,
    })
    with pytest.raises(RegimeGateConfigError) as ei:
        _gate_fire(mocker)
    assert "scoring_rules.yaml's regime_gate.headwind_reject_pct" in str(ei.value)


def test_the_gate_config_alert_lead_does_not_blame_the_yaml(mocker):
    import app.services.auto_trader as at
    sent = mocker.patch.object(at, "_alert_refusal")
    at._alert_regime_gate_config_refusal("MSFT", Exception("detail"))
    reason = sent.call_args.args[2]
    assert "scoring_rules.yaml's regime_gate block cannot be read" not in reason
    assert reason.endswith("detail")


def test_forget_alerts_reports_a_hold_that_survives_on_disk(mocker):
    """P3b E4: the memory hold clears but the file write fails -> False."""
    import app.services.notifications.alert_notifier as an
    an._fired["k1|T"] = 1.0
    mocker.patch.object(an, "_save_dedup", return_value=False)
    assert an.forget_alerts({"k1"}) is False
    assert "k1|T" not in an._fired
    mocker.patch.object(an, "_save_dedup", return_value=True)
    assert an.forget_alerts({"k1"}) is True


def test_save_dedup_returns_false_when_it_cannot_write(mocker):
    import app.services.notifications.alert_notifier as an
    mocker.patch.object(an.tempfile, "mkstemp", side_effect=OSError("disk full"))
    assert an._save_dedup() is False


def test_a_delivered_discrete_alert_whose_hold_stays_on_disk_is_logged(mocker, caplog):
    import app.services.auto_trader as at
    import app.services.notifications.alert_notifier as an

    async def _delivered(**_kw):
        return True

    mocker.patch.object(an, "notify_alert", _delivered)
    mocker.patch.object(an, "forget_alerts", return_value=False)
    with caplog.at_level("ERROR", logger="app.services.auto_trader"):
        at._alert_refusal("MSFT", "x refusal", "r", "rec", "T", discrete=True)
    assert "dedup file could not be written" in caplog.text


def test_a_good_fire_logs_a_config_hold_that_stays_on_disk(mocker, caplog):
    import app.services.auto_trader as at
    import app.services.notifications.alert_notifier as an
    mocker.patch.object(an, "forget_alerts", return_value=False)
    with caplog.at_level("ERROR", logger="app.services.auto_trader"):
        at._clear_config_refusal_holds()
    assert "dedup file could not be written" in caplog.text


# E7: missing bars refuse (decision P3B-REGIME-BARS-MISSING-REFUSES-2026-09-25)

def test_the_regime_fetch_deadline_outlasts_the_provider_timeout():
    """8s was shorter than fetch_candles' 10s httpx timeout, so the yfinance
    fallback could never answer after a stalled Tradier call."""
    import app.services.auto_trader as at
    assert at._REGIME_FETCH_DEADLINE_S == 25.0
    assert at._REGIME_FETCH_DEADLINE_S > 10


@pytest.mark.parametrize("how", ["timeout", "raises", "empty", "none"])
def test_missing_regime_bars_refuse_the_fire_and_alert(mocker, how):
    import threading
    import app.services.auto_trader as at
    from app.data.ibkr_paper import OrderResult
    release = threading.Event()

    def _fetch(symbol):
        if how == "timeout":
            release.wait(5)
            return []
        if how == "raises":
            raise RuntimeError("tradier down")
        return [] if how == "empty" else None

    mocker.patch.object(at, "_REGIME_FETCH_DEADLINE_S", 0.05)
    mocker.patch.object(at, "_fetch_scan_window_bars", _fetch)
    mocker.patch.object(at, "_market_is_open", return_value=True)
    _forbid_spx_cache(mocker)
    execute = mocker.patch("app.services.auto_trader.execute_option_order",
                           return_value=OrderResult("x", "ok", "ibkr_paper"))
    alert = mocker.patch.object(at, "_alert_regime_data_refusal")
    unclassified = mocker.patch.object(at, "_alert_unclassified_refusal")

    svc = AutoTradeService()
    s = _make_armed(symbol="MSFT", qty=4)
    svc.arm(dataclasses.replace(s, horizon="Position"))
    try:
        svc.maybe_fire_on_scan()
    finally:
        release.set()

    execute.assert_not_called()
    row = svc.get_state().history[-1]
    assert row["status"] == "regime_data_blocked"
    assert row["premium_at_risk"] == 0.0
    assert svc.get_state().armed is False
    assert alert.call_count == 1 and alert.call_args.args[0] == "MSFT"
    assert unclassified.call_count == 0


def test_missing_bars_refuse_even_with_the_gate_disabled_and_sizing_on(mocker, monkeypatch):
    """Sizing measures on its own when the gate is off; no bars refuse there too
    instead of sizing at the floor."""
    import app.services.auto_trader as at
    from app.services.auto_trader import RegimeDataUnavailableError
    monkeypatch.setattr(at, "_load_regime_gate_config", lambda: {"enabled": False})
    with pytest.raises(RegimeDataUnavailableError):
        _gate_fire(mocker, bars=[], sizing_on=True)


def test_missing_bars_do_not_matter_with_gate_and_sizing_both_off(mocker, monkeypatch):
    import app.services.auto_trader as at
    monkeypatch.setattr(at, "_load_regime_gate_config", lambda: {"enabled": False})
    qty, _, fetch = _gate_fire(mocker, bars=[])
    assert qty == 4 and fetch.call_count == 0


def test_the_gate_and_sizer_share_one_refusing_measurement(mocker):
    """`_measure_once` memoises a refusal: one fetch, same outcome for both."""
    import app.services.auto_trader as at
    from app.services.auto_trader import RegimeDataUnavailableError
    m = mocker.patch.object(at, "_measure_trade_regime",
                            side_effect=RegimeDataUnavailableError("no bars"))
    measure = at._measure_once(_make_armed())
    for _ in range(2):
        with pytest.raises(RegimeDataUnavailableError):
            measure()
    assert m.call_count == 1


def test_a_consumed_regime_data_row_routes_to_its_own_alert(mocker):
    import app.services.auto_trader as at
    alert = mocker.patch.object(at, "_alert_regime_data_refusal")
    svc = AutoTradeService()
    svc._state.history.append({"attempt_id": "a1", "status": "regime_data_blocked",
                               "symbol": "MSFT"})
    svc._alert_for_consumed_attempt("a1", "MSFT", Exception("x"))
    assert alert.call_count == 1


# E9: a malformed regime.<horizon> block is a recorded config refusal

@pytest.mark.parametrize("regime", [
    ["not", "a", "mapping"],
    {"position": "lookback 20"},
    {"position": {"lookback": 50, "window": 750, "min_obs": "ten", "timeframe": "1day"}},
    {"position": {"lookback": 50, "window": 750, "min_obs": True, "timeframe": "1day"}},
])
@pytest.mark.parametrize("gate_enabled", [True, False])
def test_a_malformed_regime_block_is_recorded_as_a_config_refusal(
        mocker, monkeypatch, regime, gate_enabled):
    import app.services.auto_trader as at
    from app.services.auto_trader import RegimeGateConfigError
    doc = _doc_with(regime=regime)
    if not gate_enabled:
        doc["regime_gate"] = {"enabled": False}
    monkeypatch.setattr(at, "_load_scoring_doc", lambda: doc)
    mocker.patch.object(at, "_market_is_open", return_value=True)
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    mocker.patch("app.services.auto_trader._fetch_scan_window_bars", return_value=_fixture_bars("MSFT"))
    svc = AutoTradeService()
    svc.arm(dataclasses.replace(_make_armed(symbol="MSFT", qty=4), horizon="Position"))
    with pytest.raises(RegimeGateConfigError) as ei:
        svc.fire()
    assert "regime" in str(ei.value)
    execute.assert_not_called()
    assert svc.get_state().history[-1]["status"] == "regime_gate_config_blocked"


def test_a_missing_regime_horizon_now_refuses(mocker, monkeypatch):
    """INVERTED BY DOCC-2 (decision DOCC-2-REGIME-BLOCK-REFUSES-2026-09-28).
    A missing regime.<horizon> used to return {} and the gate ABSTAINED, so the
    trade fired with the regime unmeasured. It is now refused and recorded as
    `regime_gate_config_blocked`, with nothing sent to the broker."""
    import app.services.auto_trader as at
    doc = _doc_with(regime={})
    monkeypatch.setattr(at, "_load_scoring_doc", lambda: doc)
    with pytest.raises(at.RegimeGateConfigError, match="regime.position"):
        _gate_fire(mocker)


# E11: contracts round DOWN (decision P3B-CONTRACT-SIZING-ROUNDS-DOWN-2026-09-25)

@pytest.mark.parametrize("qty,mult,expected", [
    (5, 0.3, 1),     # 1.5: round() gave 2
    (5, 0.5, 2),     # 2.5
    (10, 0.7, 7),    # 6.999... in floats must not lose a contract
    (1, 0.3, 1),     # never below 1
    (4, 1.0, 4),
])
def test_contract_sizing_rounds_down(qty, mult, expected):
    import app.services.auto_trader as at
    assert at._sized_quantity(qty, mult) == expected


def test_the_unmeasured_floor_rounds_down_too(mocker):
    """5 x min_mult 0.30 = 1.5 -> 1 on the floor path (round() gave 2)."""
    import app.services.auto_trader as at
    mocker.patch.object(at, "_measure_trade_regime", return_value=None)
    mocker.patch.object(at, "_load_regime_gate_config", return_value={"enabled": False})
    out = at._apply_vol_sizing(dataclasses.replace(_make_armed(qty=5), horizon="Position"))
    assert out.sizing_basis == "floor:unmeasured"
    assert out.quantity == 1
