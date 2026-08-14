import pytest
from datetime import datetime, timezone
from app.services.auto_trader import AutoTradeService, ArmedStrategy, AutoTradeState


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
        action="BUY",
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
        action="BUY", quantity=2, order_type="MKT",
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
        action="BUY", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50,
    )
    svc.arm(armed)
    result = svc.fire()
    assert result.order_id == "999"
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
        action="BUY", quantity=1, order_type="LMT",
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
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="x", status="PreSubmitted", broker="ibkr_paper"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=1, order_type="LMT",
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
        action="BUY", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=50_000.0,
    )
    svc.arm(armed)
    result = svc.fire(portfolio_snapshot=[])
    assert result.order_id == "ok"
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
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="y", status="PreSubmitted", broker="ibkr_paper"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=1, order_type="LMT",
        limit_price=30.0, conid=None,
        entry_premium=30.0, portfolio_value=200_000.0,   # would fail cap if snapshot provided
    )
    svc.arm(armed)
    result = svc.fire()   # no portfolio_snapshot → cap check skipped
    assert result.order_id == "y"


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
    """An order armed more than max_arm_age_minutes ago must be disarmed without firing."""
    from datetime import timedelta
    from app.data.ibkr_paper import OrderResult

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
        action="BUY", quantity=1, order_type="LMT",
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
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="x", status="PreSubmitted", broker="ibkr_paper"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=1, order_type="LMT",
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
        action="BUY", quantity=1, order_type="LMT",
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
        action="BUY", quantity=1, order_type="LMT",
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
        action="BUY", quantity=qty, order_type="LMT",
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
    """conviction=20, full=40 → mult=0.5 → quantity=2 halved to 1."""
    from app.data.ibkr_paper import OrderResult
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("s1", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=20)

    svc = AutoTradeService()
    strategy = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=2, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    )
    svc.arm(strategy)
    svc.fire()
    assert captured.get("quantity") == 1, "Low conviction must halve quantity from 2 to 1"


def test_vol_sizing_keeps_full_quantity_at_high_conviction(mocker):
    """conviction=50, full=40 → mult capped at 1.0 → quantity unchanged."""
    from app.data.ibkr_paper import OrderResult
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("s2", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=50)

    svc = AutoTradeService()
    strategy = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    )
    svc.arm(strategy)
    svc.fire()
    assert captured.get("quantity") == 4, "High conviction must not reduce quantity"


def test_vol_sizing_skipped_when_conviction_is_none(mocker):
    """If conviction cache is None (monitor hasn't run), sizing is skipped — full quantity fires."""
    from app.data.ibkr_paper import OrderResult
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("s3", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=None)

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=3, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    ))
    svc.fire()
    assert captured.get("quantity") == 3


def test_vol_sizing_sell_halved_in_strongly_bullish_market(mocker):
    """SELL at conviction=80 (strongly bullish) → bearish_conv=20 < full_conviction=40 → min_mult=0.5."""
    from app.data.ibkr_paper import OrderResult
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("s4", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=80)

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620P00185000",
        action="SELL", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    ))
    svc.fire()
    assert captured.get("quantity") == 2, (
        "SELL in strongly bullish market (conviction=80) must halve from 4 to 2"
    )


# ── entry_premium guard (Task 5) ──────────────────────────────────────────────

def test_arm_raises_if_entry_premium_is_zero():
    """arm() must refuse a zero entry_premium — exposure check would be silently bypassed."""
    svc = AutoTradeService()
    with pytest.raises(ValueError, match="entry_premium"):
        svc.arm(ArmedStrategy(
            broker="ibkr_paper",
            symbol="AAPL",
            option_symbol="AAPL260620C00185000",
            action="BUY",
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
            action="BUY",
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
        action="BUY",
        quantity=1,
        order_type="LMT",
        limit_price=2.50,
        conid=None,
        entry_premium=2.50,
    ))
    assert svc.get_state().armed is True
