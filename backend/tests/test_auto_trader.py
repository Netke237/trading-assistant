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
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
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
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=0)

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
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
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
        action="BUY", direction="Bullish", quantity=3, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    ))
    svc.fire()
    assert captured.get("quantity") == 3


# ── Direction-aware sizing: the bearish frame ─────────────────────────────────
#
# `conviction` is the SIGNED BULLISH frame, [-100, +100]. Sizing used to pick its
# frame from `action`, which is always "BUY" for a long single-leg option — a
# bearish trade in this app is a long PUT — so every bearish trade was sized off
# the bullish ramp, inverted: largest into the regime that opposes it.
#
# EVERY TEST BELOW ARMS quantity=4, AND THAT IS LOAD-BEARING. `_apply_vol_sizing`
# does `max(1, round(quantity * mult))`, so at quantity=1 the multipliers 0.30,
# 0.65 and 1.00 ALL round to 1 and every assertion here would read `1` with the
# bug still in place. At 4 they separate: 0.30 -> 1, 0.65 -> 3, 1.00 -> 4.
#
# Quantity is also the only observable worth asserting: `_apply_vol_sizing`
# returns an ArmedStrategy and nothing in the changed code returns a multiplier,
# so calling `conviction_mult` directly would not exercise this path at all —
# the negation lives here, not in conviction_sizing.py.

def _fired_quantity(mocker, *, direction: str, conviction: float,
                    quantity: int = 4, action: str = "BUY") -> int:
    """Arm one trade, fire it, and return the quantity that reached the broker.

    The option right follows `direction`, so for the default action="BUY" the
    fixture is a coherent position: a bearish single-leg option is a long put.

    THAT COHERENCE DOES NOT EXTEND TO action="SELL", and ROUND 1 finding 7 was
    right to say so. With `effect` hardcoded to OPEN, SELL+Bullish builds a
    right="C" sell-to-open — a short call, a BEARISH position wearing a
    "Bullish" label, the mirror image of the incoherence this piece retired.
    Exactly one caller passes SELL (`test_vol_sizing_ignores_action_entirely`)
    and it does so deliberately, to prove the sizing expression ignores
    `action`. It is reachable only through this dataclass: `ArmRequest.action`
    is now Literal["BUY"], so that body is a 422 at the HTTP door
    (test_auto_trade.py::test_arm_refuses_sell_because_it_would_be_a_naked_short).
    """
    from app.data.ibkr_paper import OrderResult
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("dir", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=conviction)

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


def test_vol_sizing_bearish_cut_to_floor_in_strongly_bullish_market(mocker):
    """A long put armed into conviction=+80 is cut to the floor, not sized full.

    This replaces `test_vol_sizing_sell_reduced_in_strongly_bullish_market`, which
    armed action="SELL" on a PUT — a SHORT put, which is a BULLISH position — and
    then asserted it must be reduced in a bullish market. It passed, and it was
    asserting the wrong thing about a branch no production caller can reach.

    Bearish at +80 mirrors to -80, which clamps to the 0.30 floor:
    round(4 * 0.30) = 1.
    """
    assert _fired_quantity(mocker, direction="Bearish", conviction=80) == 1


def test_vol_sizing_bearish_floors_when_regime_strongly_opposes(mocker):
    """Bearish at +40 (regime strongly opposes): mirror -40 -> 0.30 floor -> 1.

    With the `action`-based inference this returned 4 — FULL SIZE into the regime
    most opposed to the trade. This is the row where the defect was largest.
    """
    assert _fired_quantity(mocker, direction="Bearish", conviction=40) == 1


def test_vol_sizing_bearish_is_GRADED_when_the_regime_opposes(mocker):
    """Bearish at +20: mirror -20 -> 0.475 -> round(1.9) = 2.

    RENAMED, because it no longer floors and that is the whole point of the
    two-sided ramp. Under the one-sided form every opposed conviction collapsed
    to min_mult, so -1 and -100 sized the same. Now the opposed half grades:
    this sits between the floor at -40 and the midpoint at 0.
    """
    assert _fired_quantity(mocker, direction="Bearish", conviction=20) == 2


def test_vol_sizing_bearish_scales_up_when_regime_favours(mocker):
    """Bearish at -20: mirror +20 -> mid-ramp 0.65 -> round(2.6) = 3 (bug gave 1).

    THE ONLY CASE INSIDE THE RAMP. Every other row here sits on the floor or the
    cap, so this is the one that would notice a later change to
    `full_conviction_pct` (40 today) rather than silently absorbing it.
    """
    assert _fired_quantity(mocker, direction="Bearish", conviction=-20) == 3


def test_vol_sizing_bearish_full_size_when_regime_strongly_favours(mocker):
    """Bearish at -40: mirror +40 -> cap 1.00 -> 4 (bug gave 1 — the inverse)."""
    assert _fired_quantity(mocker, direction="Bearish", conviction=-40) == 4


def test_vol_sizing_bearish_at_neutral_conviction_sits_mid_ramp(mocker):
    """Bearish at 0 -> mirror -0 -> the ramp's MIDPOINT 0.65 -> round(2.6) = 3.

    Still the pin that the mirror of 0 is 0, which is what stops anyone
    reintroducing an offset like `100 - conviction` (under which neutral would
    saturate at FULL size). What changed is where neutral sits: the floor under
    the one-sided ramp, the midpoint under the two-sided one.
    """
    assert _fired_quantity(mocker, direction="Bearish", conviction=0) == 3


def test_vol_sizing_bullish_full_size_at_high_conviction_unchanged(mocker):
    """Regression guard: bullish behaviour is untouched. +40 -> cap 1.00 -> 4."""
    assert _fired_quantity(mocker, direction="Bullish", conviction=40) == 4


def test_vol_sizing_bullish_floors_at_negative_conviction_unchanged(mocker):
    """Regression guard: bullish at -40 -> 0.30 floor -> 1, as before."""
    assert _fired_quantity(mocker, direction="Bullish", conviction=-40) == 1


def test_vol_sizing_ignores_action_entirely(mocker):
    """`action` must no longer influence size, in either direction.

    The rewritten test above was repo-wide the ONLY sizing test constructing
    action="SELL". Without this one, someone reinstating `strategy.action` in the
    sizing expression would break no test — which is exactly the drift removing
    the inference exists to prevent.

    action="SELL" with direction="Bullish" at conviction=+80: the direction
    decides, so mult(+80) caps at 1.00 -> 4. Under the old expression SELL took
    the `100 - 80 = 20` branch -> 0.65 -> round(2.6) = 3. Discriminating.

    This constructs ArmedStrategy DIRECTLY and that is now the only way to
    reach it: ROUND 1 finding 3 narrowed `ArmRequest.action` to Literal["BUY"],
    because SELL + the hardcoded effect="OPEN" is a naked short. So this row is
    a guard on the sizing expression, NOT a claim that a SELL arm is reachable
    or sane — the position it describes is incoherent on purpose, and the HTTP
    door refuses it. See `_fired_quantity`'s docstring.
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


def test_an_absent_block_is_still_sizing_off_not_a_failure(mocker, tmp_path):
    """The distinction the whole change rests on: a file that parses and says
    nothing about regime_sizing has turned sizing OFF, and full size is right."""
    import app.services.auto_trader as at

    ok = tmp_path / "scoring_rules.yaml"
    ok.write_text("some_other_block:\n  a: 1\n")
    mocker.patch.object(at, "_SCORING_CONFIG_PATH", ok)
    at._load_scoring_doc.cache_clear()
    try:
        assert at._load_scoring_config() == {}
        assert at._apply_vol_sizing(_sizing_strategy(4)).quantity == 4
    finally:
        at._load_scoring_doc.cache_clear()


def test_a_broken_block_refuses_before_the_conviction_lookup(mocker):
    """Order matters: a missing conviction returns the strategy unchanged (full
    size), so validating after it would let a broken config through on every
    fire before regime_monitor has cached anything."""
    import app.services.auto_trader as at
    from app.scoring.conviction_sizing import SizingConfigError

    mocker.patch.object(at, "_load_scoring_config",
                        return_value={"enabled": True, "min_mult": 0.3,
                                      "full_conviction_pct": -40})
    conviction = mocker.patch("app.services.regime_monitor.get_last_conviction",
                              return_value=None)
    with pytest.raises(SizingConfigError):
        at._apply_vol_sizing(_sizing_strategy(4))
    conviction.assert_not_called()


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
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=90)

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
    mocker.patch("app.services.regime_monitor.get_last_conviction",
                 return_value=float("nan"))
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


# ── regime_gate on the fire path (2026-09-19, Kenneth's instruction) ──────────
#
# THESE TESTS EXIST BECAUSE THE GATE IS OTHERWISE INERT UNDER TEST. It abstains
# when stability is uncached, and no other test in this file caches it — so
# every assertion above passes with the gate present or absent. Without the
# cases below, wiring it would have been unobservable.

def _fire_with_regime(mocker, *, direction: str, conviction: float,
                      stability: str | None, quantity: int = 4):
    """Arm and fire with BOTH halves of the regime cached. Returns (qty|None, svc)."""
    from app.data.ibkr_paper import OrderResult
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("gate", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=conviction)
    mocker.patch("app.services.regime_monitor.get_last_stability", return_value=stability)

    right = "C" if direction == "Bullish" else "P"
    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol=f"AAPL260620{right}00185000",
        action="BUY", direction=direction, quantity=quantity, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    ))
    svc.fire()
    return captured.get("quantity"), svc


def test_regime_gate_refuses_a_trade_the_scan_would_have_dropped(mocker):
    """Bearish into conviction +80 is -80 in its own frame: past the reject floor.

    Before this was wired the same trade fired at min_mult — `max(1, ...)`
    guarantees at least one contract, so "sized to nothing" still sent an order.
    """
    from app.services.auto_trader import RegimeHeadwindError
    with pytest.raises(RegimeHeadwindError, match="regime headwind"):
        _fire_with_regime(mocker, direction="Bearish", conviction=80, stability="Stable")


def test_regime_gate_refusal_is_recorded_and_sends_nothing(mocker):
    """The refusal must leave a trace AND leave nothing armed. Both, not either."""
    from app.services.auto_trader import RegimeHeadwindError
    from app.data.ibkr_paper import OrderResult
    sent = []
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 side_effect=lambda s: sent.append(s) or OrderResult("x", "ok", "ibkr_paper"))
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=80)
    mocker.patch("app.services.regime_monitor.get_last_stability", return_value="Stable")

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL", option_symbol="AAPL260620P00185000",
        action="BUY", direction="Bearish", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50, portfolio_value=100_000.0,
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

    This is why stability had to be cached rather than assumed. Applying the
    conviction half alone would refuse here — a stricter gate wearing the same
    name as the scan's.
    """
    qty, _ = _fire_with_regime(mocker, direction="Bearish", conviction=80, stability="Fragile")
    assert qty == 1, "fires, floored by sizing"


def test_regime_gate_rejects_exactly_at_the_threshold(mocker):
    """headwind_reject_pct is -40 and the comparison is `<=`, so -40 itself rejects."""
    from app.services.auto_trader import RegimeHeadwindError
    with pytest.raises(RegimeHeadwindError):
        _fire_with_regime(mocker, direction="Bearish", conviction=40, stability="Stable")


def test_regime_gate_lets_the_caution_band_fire(mocker):
    """-20 is past headwind_caution_pct but not the reject floor: it fires.

    An armed trade has no status left to demote, so CAUTION is logged and fires.
    Sizing already floors it.
    """
    qty, _ = _fire_with_regime(mocker, direction="Bearish", conviction=20, stability="Stable")
    assert qty == 2, "fires, and the two-sided ramp grades it rather than flooring it"


def test_regime_gate_applies_to_bullish_trades_too(mocker):
    """The gate reads the MIRRORED number, so it is direction-agnostic.

    A bullish trade at conviction -80 faces exactly the headwind a bearish trade
    faces at +80. If this passed while the bearish case refused, the gate would
    be re-deriving direction instead of reading the frame it was given.
    """
    from app.services.auto_trader import RegimeHeadwindError
    with pytest.raises(RegimeHeadwindError):
        _fire_with_regime(mocker, direction="Bullish", conviction=-80, stability="Stable")


def test_regime_gate_abstains_when_stability_was_never_cached(mocker):
    """No stability -> no evaluation, and it fires rather than guessing.

    Refusing on a guess would invent a rule the scan does not have; firing
    silently would hide that the gate never ran. It fires and logs a warning.
    """
    qty, _ = _fire_with_regime(mocker, direction="Bearish", conviction=80, stability=None)
    assert qty == 1


def test_regime_gate_does_not_fire_when_disabled(mocker, tmp_path, monkeypatch):
    """`enabled: false` means the gate is off, not that it defaults to refusing."""
    import app.services.auto_trader as at
    monkeypatch.setattr(at, "_load_regime_gate_config", lambda: {
        "enabled": False, "headwind_caution_pct": -15,
        "headwind_reject_pct": -40, "require_stable_for_reject": True,
    })
    qty, _ = _fire_with_regime(mocker, direction="Bearish", conviction=80, stability="Stable")
    assert qty == 1


def test_regime_gate_still_refuses_when_regime_sizing_is_disabled(mocker, monkeypatch):
    """`regime_sizing.enabled: false` must NOT switch the headwind gate off.

    Piece 2 round 1 finding 1. `_apply_regime_gate` lives inside
    `_apply_vol_sizing`, which used to `return strategy` as soon as
    `resolve_sizing` reported sizing off — so turning off one feature silently
    turned off a different, independently configured one, and the trade went to
    the broker at the FULL armed quantity. That is worse than the behaviour the
    gate replaced, which at least sized a headwind trade down to min_mult.

    Measured before the fix: this exact setup FIRED qty 4. The sharp edge is
    that conviction_sizing.py's own SizingConfigError text advises "To stop
    trading in a headwind, disable regime_sizing or raise the gate" — following
    the codebase's own advice disabled the gate.

    The other gate tests all mock `_load_regime_gate_config` wholesale and so
    never exercise this axis; this one leaves the gate config real and moves
    only `regime_sizing.enabled`.
    """
    import app.services.auto_trader as at
    from app.services.auto_trader import RegimeHeadwindError

    doc = at._load_scoring_doc()
    real_sizing = dict(doc.get("regime_sizing") or {})
    monkeypatch.setitem(doc, "regime_sizing", {**real_sizing, "enabled": False})

    # Sanity: sizing really is off down this path, so the test would pass
    # vacuously if the gate had simply moved rather than been decoupled.
    from app.scoring.conviction_sizing import resolve_sizing
    assert resolve_sizing(at._load_scoring_config()) is None

    with pytest.raises(RegimeHeadwindError, match="regime headwind"):
        _fire_with_regime(mocker, direction="Bearish", conviction=80, stability="Stable")
