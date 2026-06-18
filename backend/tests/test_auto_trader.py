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
    )
    svc.arm(armed)
    svc.disarm()
    assert svc.get_state().armed is False


def test_fire_executes_and_disarms(mocker):
    from app.data.ibkr_paper import OrderResult
    svc = AutoTradeService()
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
    )
    svc.arm(armed)
    result = svc.fire()
    assert result.order_id == "999"
    mock_execute.assert_called_once()
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


def test_fire_no_snapshot_skips_check(mocker):
    """fire() with no portfolio_snapshot still executes (backward compat)."""
    from app.data.ibkr_paper import OrderResult
    svc = AutoTradeService()
    mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="y", status="PreSubmitted", broker="ibkr_paper"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=1, order_type="LMT",
        limit_price=30.0, conid=None,
        entry_premium=30.0, portfolio_value=50_000.0,   # would fail cap if snapshot provided
    )
    svc.arm(armed)
    result = svc.fire()   # no portfolio_snapshot → check skipped
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
        armed_at=stale_time,
    )
    svc.arm(armed)
    svc.maybe_fire_on_scan()   # should disarm, not fire
    mock_execute.assert_not_called()
    assert svc.get_state().armed is False


def test_maybe_fire_on_scan_fires_fresh_order(mocker):
    """An order armed recently must still fire normally."""
    from app.data.ibkr_paper import OrderResult

    svc = AutoTradeService()
    mock_execute = mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="fresh", status="PreSubmitted", broker="ibkr_paper"),
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None,
        # armed_at defaults to now via field(default_factory=...)
    )
    svc.arm(armed)
    svc.maybe_fire_on_scan()
    mock_execute.assert_called_once()
