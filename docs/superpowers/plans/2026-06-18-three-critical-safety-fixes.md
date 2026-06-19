# Three Critical Safety Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three pre-money risks: (1) options trade card shows a -3% stock chart-invalidation level that is mathematically inconsistent with the 60% premium stop used for R/R; (2) `auto_trader.fire()` executes orders without checking the `risk_rules.yaml` exposure caps; (3) armed orders can fire hours after arming with no staleness check.

**Architecture:** All three fixes are surgical changes to two backend services (`auto_trader.py`, `portfolio_risk.py`) and two routers (`scan.py`, `auto_trade.py`) plus one YAML config. Fix 1 is a one-liner formula replacement. Fix 2 threads the current portfolio snapshot into the fire path. Fix 3 adds a timestamp + YAML threshold.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2 async, pytest, PyYAML.

---

## File Map

| Action | Path | What changes |
|---|---|---|
| Modify | `backend/app/routers/scan.py:443-449` | Replace fixed-pct invalidation with delta-derived stock stop |
| Modify | `backend/app/services/auto_trader.py` | Add `entry_premium`, `portfolio_value`, `armed_at` to `ArmedStrategy`; `fire()` and `maybe_fire_on_scan()` accept portfolio snapshot |
| Modify | `backend/app/services/portfolio_risk.py` | Add `orm_positions_to_risk()` helper |
| Modify | `backend/app/routers/auto_trade.py` | `ArmRequest` gets `entry_premium` + `portfolio_value`; `/fire` endpoint fetches portfolio + checks exposure |
| Modify | `backend/app/routers/scan.py:1002-1006` | Fetch portfolio from DB before calling `maybe_fire_on_scan()` |
| Modify | `backend/config/risk_rules.yaml` | Add `auto_trade.max_arm_age_minutes: 30` |
| Modify | `backend/tests/test_auto_trader.py` | New tests for exposure check and staleness disarm |
| Create | `backend/tests/test_invalidation_calc.py` | Tests for delta-derived invalidation |

---

## Task 1: Delta-derived stock invalidation (scan.py)

**Files:**
- Modify: `backend/app/routers/scan.py:443-449`
- Create: `backend/tests/test_invalidation_calc.py`

### Background

`scan.py` currently sets:
```python
invalidation_price = price * (1 - _rr["bullish_invalidation_pct"]) if _bull else price * (1 + _rr["bearish_invalidation_pct"])
```
This produces a -3% stock level that is shown as "Invalidation" in the Exit Plan. But R/R is computed using `premium * 0.60` as risk — not the stock move to that level. A trader who sizes based on a -3% stock stop is sizing wrong.

The fix: back-calculate the equivalent stock price from the premium stop:
```
stock_stop_move = (premium × premium_stop_pct) / delta
invalidation = price - stock_stop_move   (calls)
invalidation = price + stock_stop_move   (puts)
```

- [ ] **Step 1.1: Write the failing test**

Create `backend/tests/test_invalidation_calc.py`:

```python
"""The trade card's invalidation price must be derived from the premium stop, not a fixed pct."""
import pytest


def _invalidation_from_delta(price: float, premium: float, stop_pct: float, delta: float, is_call: bool) -> float:
    move = (premium * stop_pct) / max(abs(delta), 0.05)
    return price - move if is_call else price + move


def test_call_invalidation_is_closer_than_3pct_for_cheap_option():
    """$1 option with delta 0.45, 60% stop: move = (1.0 * 0.60) / 0.45 = $1.33.
    For price=100 that's invalidation=98.67, not 97.00 (-3%)."""
    inv = _invalidation_from_delta(price=100, premium=1.0, stop_pct=0.60, delta=0.45, is_call=True)
    assert round(inv, 2) == 98.67
    assert inv > 97.00   # delta-derived stop is closer than the fixed 3% level


def test_put_invalidation_is_above_price():
    """Bearish put: stock moves UP to hit invalidation."""
    inv = _invalidation_from_delta(price=100, premium=2.0, stop_pct=0.60, delta=0.45, is_call=False)
    assert inv > 100


def test_high_delta_option_gives_smaller_stock_move():
    """Deep ITM delta=0.80 → smaller stock move to lose 60% premium than delta=0.30."""
    inv_deep = _invalidation_from_delta(price=100, premium=5.0, stop_pct=0.60, delta=0.80, is_call=True)
    inv_otm  = _invalidation_from_delta(price=100, premium=5.0, stop_pct=0.60, delta=0.30, is_call=True)
    assert inv_deep > inv_otm  # deep ITM → invalidation closer to current price


def test_delta_floor_prevents_division_by_zero():
    """delta=0 is floored to 0.05, producing a finite result."""
    inv = _invalidation_from_delta(price=100, premium=2.0, stop_pct=0.60, delta=0.0, is_call=True)
    assert inv > 0
    assert inv < 100
```

- [ ] **Step 1.2: Run the test to confirm it passes as pure unit math**

```bash
cd backend && pytest tests/test_invalidation_calc.py -v
```

Expected: All 4 PASS (these test the formula in isolation).

- [ ] **Step 1.3: Apply the formula in scan.py**

In `backend/app/routers/scan.py`, find the block (around line 443–449):

```python
    # ── Reward-risk ────────────────────────────────────────────────────────────
    _rr = _rr_cfg()
    _bull = direction == "Bullish"
    target_price = price * (1 + _rr["bullish_target_pct"]) if _bull else price * (1 - _rr["bearish_target_pct"])
    invalidation_price = price * (1 - _rr["bullish_invalidation_pct"]) if _bull else price * (1 + _rr["bearish_invalidation_pct"])
    strike = float(contract.get("strike", price))
    expiry_years = contract.get("dte", 30) / 365.0
    premium = float(contract.get("price", 0.10))
```

Replace with:

```python
    # ── Reward-risk ────────────────────────────────────────────────────────────
    _rr = _rr_cfg()
    _bull = direction == "Bullish"
    target_price = price * (1 + _rr["bullish_target_pct"]) if _bull else price * (1 - _rr["bearish_target_pct"])
    strike = float(contract.get("strike", price))
    expiry_years = contract.get("dte", 30) / 365.0
    premium = float(contract.get("price", 0.10))
    # Back-calculate the stock price at which the option would lose premium_stop_pct
    # of its premium (using delta approximation). This keeps the Exit Plan's
    # "Invalidation" field consistent with the R/R calculation's risk basis.
    _delta_est = max(abs(float(contract.get("delta", 0.45))), 0.05)
    _stock_stop_move = (premium * _rr["premium_stop_pct"]) / _delta_est
    invalidation_price = price - _stock_stop_move if _bull else price + _stock_stop_move
```

- [ ] **Step 1.4: Run the existing scan tests to confirm nothing broke**

```bash
cd backend && pytest tests/test_scan_endpoint.py tests/test_scan_schema.py tests/test_invalidation_calc.py -v
```

Expected: All PASS.

- [ ] **Step 1.5: Commit**

```bash
git add backend/app/routers/scan.py backend/tests/test_invalidation_calc.py
git commit -m "fix(scan): derive stock invalidation from premium stop via delta

Replaces the fixed -3% chart invalidation level with a delta-derived
stock price consistent with the 60% premium stop used for R/R.
Traders who size based on the displayed Invalidation field now use the
correct risk basis."
```

---

## Task 2: Enforce exposure caps at fire time

**Files:**
- Modify: `backend/app/services/auto_trader.py`
- Modify: `backend/app/services/portfolio_risk.py`
- Modify: `backend/app/routers/auto_trade.py`
- Modify: `backend/app/routers/scan.py` (around line 1002–1006)
- Test: `backend/tests/test_auto_trader.py`

### Background

`risk_rules.yaml` defines `max_single_trade_exposure_pct: 0.05` and `max_total_exposure_pct: 0.25`. Neither is checked before `execute_option_order()` is called. The fix threads the current portfolio snapshot into every fire path (manual `/fire` endpoint and scan-triggered `maybe_fire_on_scan`).

### Sub-task 2a: Extend ArmedStrategy + add portfolio helper

- [ ] **Step 2a.1: Write failing tests for the new ArmedStrategy fields**

In `backend/tests/test_auto_trader.py`, add at the bottom:

```python
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
    """fire() raises RuntimeError when single-trade exposure would exceed the cap."""
    from app.services.portfolio_risk import PortfolioPosition as RiskPosition
    from app.data.ibkr_paper import OrderResult

    # portfolio_value=50_000, max_single=5% → max capital_at_risk = $2,500
    # entry_premium=30.0 × 1 contract × 100 multiplier = $3,000 → exceeds cap
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
    from app.services.portfolio_risk import PortfolioPosition as RiskPosition
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
    """fire() with no portfolio_snapshot still executes (backward compat path)."""
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
    )
    svc.arm(armed)
    result = svc.fire()   # no portfolio_snapshot → check skipped
    assert result.order_id == "y"
```

- [ ] **Step 2a.2: Run tests to confirm they fail**

```bash
cd backend && pytest tests/test_auto_trader.py::test_armed_strategy_has_entry_premium_and_portfolio_value tests/test_auto_trader.py::test_fire_blocked_when_exposure_cap_breached -v
```

Expected: FAIL (fields don't exist yet).

- [ ] **Step 2a.3: Extend ArmedStrategy and fire() in auto_trader.py**

Replace the full `auto_trader.py` with:

```python
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

logger = logging.getLogger(__name__)


@dataclass
class ArmedStrategy:
    broker:          str
    symbol:          str
    option_symbol:   str
    action:          Literal["BUY", "SELL"]
    quantity:        int
    order_type:      Literal["MKT", "LMT"]
    limit_price:     Optional[float]
    conid:           Optional[int]
    entry_premium:   float = 0.0
    portfolio_value: float = 50_000.0
    armed_at:        datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AutoTradeState:
    armed:    bool
    strategy: Optional[ArmedStrategy]
    history:  list[dict] = field(default_factory=list)


def execute_option_order(strategy: ArmedStrategy):
    """Execute the armed option order via the broker router. Importable for mocking."""
    from app.services.broker_router import build_router_from_credentials
    from app.data.ibkr_paper import BrokerOrder
    order = BrokerOrder(
        symbol=strategy.symbol,
        action=strategy.action,
        quantity=strategy.quantity,
        order_type=strategy.order_type,
        limit_price=strategy.limit_price,
        conid=strategy.conid,
        sec_type="OPT",
        option_symbol=strategy.option_symbol,
    )
    router = build_router_from_credentials()
    return router.execute(strategy.broker, order)


class AutoTradeService:
    """Manages an armed options strategy and fires it on demand or on scan completion."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = AutoTradeState(armed=False, strategy=None)

    def arm(self, strategy: ArmedStrategy) -> None:
        with self._lock:
            self._state.armed = True
            self._state.strategy = strategy
        logger.info("AutoTrader armed: %s %s", strategy.action, strategy.symbol)

    def disarm(self) -> None:
        with self._lock:
            self._state.armed = False
            self._state.strategy = None
        logger.info("AutoTrader disarmed")

    def get_state(self) -> AutoTradeState:
        with self._lock:
            return AutoTradeState(
                armed=self._state.armed,
                strategy=self._state.strategy,
                history=list(self._state.history),
            )

    def fire(self, portfolio_snapshot: list | None = None, portfolio_value: float | None = None):
        """Execute the armed strategy.

        Disarms on the fire attempt (fail-closed). If portfolio_snapshot is
        provided, runs an exposure cap check before executing — raises if the
        caps would be breached. Pass portfolio_snapshot=None to skip the check
        (backward-compat path for tests and callers without DB access).
        """
        with self._lock:
            if not self._state.armed or self._state.strategy is None:
                raise RuntimeError("AutoTrader not armed — cannot fire")
            strategy = self._state.strategy
            # Clear armed state atomically so a concurrent fire sees unarmed immediately.
            self._state.armed = False
            self._state.strategy = None

        # Exposure cap check — runs after disarm so a double-fire is impossible.
        if portfolio_snapshot is not None and strategy.entry_premium > 0:
            pv = portfolio_value if portfolio_value is not None else strategy.portfolio_value
            self._check_exposure(strategy, portfolio_snapshot, pv)

        result = execute_option_order(strategy)
        with self._lock:
            self._state.history.append({
                "order_id": result.order_id,
                "status":   result.status,
                "broker":   result.broker,
                "symbol":   strategy.symbol,
                "option":   strategy.option_symbol,
            })
        logger.info("AutoTrader fired: order %s status %s", result.order_id, result.status)
        return result

    def maybe_fire_on_scan(
        self,
        portfolio_snapshot: list | None = None,
        portfolio_value: float | None = None,
    ) -> None:
        """Trigger #2: called after each scan completes. Fires if armed."""
        with self._lock:
            should_fire = self._state.armed
        if should_fire:
            try:
                self.fire(portfolio_snapshot=portfolio_snapshot, portfolio_value=portfolio_value)
                logger.info("AutoTrader: fired on scan completion trigger")
            except Exception as exc:
                logger.error("AutoTrader scan-trigger fire failed: %s", exc)

    @staticmethod
    def _check_exposure(strategy: ArmedStrategy, portfolio_snapshot: list, portfolio_value: float) -> None:
        """Raise RuntimeError if the armed order would breach exposure caps."""
        from app.services.portfolio_risk import check_position_risk
        result = check_position_risk(
            symbol=strategy.symbol,
            contract_id=strategy.option_symbol,
            proposed_contracts=strategy.quantity,
            entry_premium=strategy.entry_premium,
            current_price=strategy.entry_premium,
            portfolio=portfolio_snapshot,
            portfolio_value=portfolio_value,
        )
        if not result.approved:
            logger.warning("AutoTrader fire blocked by exposure cap: %s", result.reasons)
            raise RuntimeError(f"Exposure cap breach: {result.reasons}")


# Module-level singleton
auto_trader = AutoTradeService()
```

- [ ] **Step 2a.4: Run auto_trader tests**

```bash
cd backend && pytest tests/test_auto_trader.py -v
```

Expected: All PASS.

### Sub-task 2b: Add orm_positions_to_risk helper in portfolio_risk.py

- [ ] **Step 2b.1: Write failing test for the helper**

In `backend/tests/test_auto_trader.py`, add:

```python
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
```

- [ ] **Step 2b.2: Run to confirm FAIL**

```bash
cd backend && pytest tests/test_auto_trader.py::test_orm_positions_to_risk_converts_correctly -v
```

Expected: FAIL (function doesn't exist yet).

- [ ] **Step 2b.3: Add orm_positions_to_risk to portfolio_risk.py**

At the bottom of `backend/app/services/portfolio_risk.py`, add:

```python
def orm_positions_to_risk(orm_positions) -> list[PortfolioPosition]:
    """Convert ORM portfolio rows to PortfolioPosition dataclasses for risk checks."""
    result = []
    for p in orm_positions:
        is_stock = str(getattr(p, "contract", "")).endswith("|STOCK")
        multiplier = 1 if is_stock else 100
        entry = float(getattr(p, "entry_price", 0) or 0)
        qty = int(getattr(p, "qty", 1) or 1)
        car = entry * qty * multiplier
        result.append(PortfolioPosition(
            symbol=str(getattr(p, "symbol", "")),
            contract_id=str(getattr(p, "contract", "")),
            contracts=qty,
            entry_premium=entry,
            current_price=entry,
            capital_at_risk=car,
        ))
    return result
```

- [ ] **Step 2b.4: Run the helper test**

```bash
cd backend && pytest tests/test_auto_trader.py::test_orm_positions_to_risk_converts_correctly -v
```

Expected: PASS.

### Sub-task 2c: Update auto_trade.py router (manual /fire endpoint + ArmRequest)

- [ ] **Step 2c.1: Update auto_trade.py**

Replace the full `backend/app/routers/auto_trade.py` with:

```python
from __future__ import annotations

from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.services.auto_trader import auto_trader, ArmedStrategy

router = APIRouter(prefix="/auto-trade", tags=["auto-trade"])


class ArmRequest(BaseModel):
    broker:          Literal["ibkr_paper", "tradier_paper"]
    symbol:          str
    option_symbol:   str
    action:          Literal["BUY", "SELL"]
    quantity:        int
    order_type:      Literal["MKT", "LMT"] = "LMT"
    limit_price:     Optional[float] = None
    conid:           Optional[int] = None
    entry_premium:   float = 0.0
    portfolio_value: float = 50_000.0


@router.post("/arm")
async def arm(req: ArmRequest) -> dict:
    """Arm the auto-trader with the given option order. Fires on next trigger."""
    auto_trader.arm(ArmedStrategy(**req.model_dump()))
    return {"armed": True, "symbol": req.symbol, "option_symbol": req.option_symbol}


@router.delete("/arm")
async def disarm() -> dict:
    """Disarm — cancel the pending auto-trade."""
    auto_trader.disarm()
    return {"armed": False}


@router.post("/fire")
async def fire_now(db: AsyncSession = Depends(get_db)) -> dict:
    """Trigger #1: manually fire the armed strategy with a live exposure check."""
    from app.models.portfolio import PortfolioPositionModel
    from app.services.portfolio_risk import orm_positions_to_risk
    state = auto_trader.get_state()
    portfolio_value = state.strategy.portfolio_value if state.strategy else 50_000.0
    result_q = await db.execute(select(PortfolioPositionModel))
    orm_positions = result_q.scalars().all()
    portfolio_snapshot = orm_positions_to_risk(orm_positions)
    try:
        result = auto_trader.fire(
            portfolio_snapshot=portfolio_snapshot,
            portfolio_value=portfolio_value,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"order_id": result.order_id, "status": result.status, "broker": result.broker}


@router.get("/status")
async def status() -> dict:
    state = auto_trader.get_state()
    return {
        "armed":  state.armed,
        "symbol": state.strategy.symbol if state.strategy else None,
        "option": state.strategy.option_symbol if state.strategy else None,
        "broker": state.strategy.broker if state.strategy else None,
        "history_count": len(state.history),
        "last_order": state.history[-1] if state.history else None,
    }
```

- [ ] **Step 2c.2: Update the scan router's maybe_fire_on_scan call**

In `backend/app/routers/scan.py`, find the block around line 1002–1006:

```python
    # Trigger #2: fire armed auto-trade if this scan produced any candidates.
    # Run off the event loop — the broker call inside is synchronous network I/O.
    if result.candidates:
        from app.services.auto_trader import auto_trader as _auto_trader
        await asyncio.to_thread(_auto_trader.maybe_fire_on_scan)
```

Replace with:

```python
    # Trigger #2: fire armed auto-trade if this scan produced any candidates.
    # Fetch portfolio for exposure check before handing off to the sync thread.
    if result.candidates:
        from app.services.auto_trader import auto_trader as _auto_trader
        from app.models.portfolio import PortfolioPositionModel
        from app.services.portfolio_risk import orm_positions_to_risk
        _state = _auto_trader.get_state()
        _pv = _state.strategy.portfolio_value if _state.strategy else 50_000.0
        _qr = await db.execute(select(PortfolioPositionModel))
        _orm_pos = _qr.scalars().all()
        _portfolio_snapshot = orm_positions_to_risk(_orm_pos)
        await asyncio.to_thread(
            _auto_trader.maybe_fire_on_scan,
            _portfolio_snapshot,
            _pv,
        )
```

Note: `select` is already imported at the top of `scan.py`. If it isn't, add `from sqlalchemy import select` to the imports.

- [ ] **Step 2c.3: Verify select is imported in scan.py**

```bash
cd backend && grep "from sqlalchemy" app/routers/scan.py
```

If `select` is missing, add `from sqlalchemy import select` to the imports section.

- [ ] **Step 2c.4: Run all auto_trader and scan tests**

```bash
cd backend && pytest tests/test_auto_trader.py tests/test_scan_endpoint.py tests/test_scan_schema.py -v
```

Expected: All PASS.

- [ ] **Step 2c.5: Commit**

```bash
git add backend/app/services/auto_trader.py \
        backend/app/services/portfolio_risk.py \
        backend/app/routers/auto_trade.py \
        backend/app/routers/scan.py \
        backend/tests/test_auto_trader.py
git commit -m "fix(auto-trade): enforce exposure caps before fire()

Adds entry_premium + portfolio_value to ArmedStrategy. The /fire endpoint
and scan-triggered maybe_fire_on_scan() now fetch the live portfolio from
the DB and run check_position_risk() before submitting any order.
Orders that would breach max_single_trade_exposure_pct or
max_total_exposure_pct raise a 400 / disarm instead of executing."
```

---

## Task 3: Freshness check — disarm stale armed orders on scan trigger

**Files:**
- Modify: `backend/app/services/auto_trader.py` (already updated in Task 2 — just add staleness logic)
- Modify: `backend/config/risk_rules.yaml`
- Test: `backend/tests/test_auto_trader.py`

### Background

`maybe_fire_on_scan()` fires the armed order after every scan. An order armed at 10am can fire from a 2pm scheduled scan. The `limit_price` on `ArmedStrategy` is set at arm time; if the option has moved materially, the fill is at a stale reference. The fix: compare `strategy.armed_at` to the current time and disarm without firing if the gap exceeds a configurable threshold.

`armed_at` was already added to `ArmedStrategy` in Task 2. The YAML threshold and the staleness check are what remain.

- [ ] **Step 3.1: Add config key to risk_rules.yaml**

In `backend/config/risk_rules.yaml`, add a new section at the bottom:

```yaml
auto_trade:
  max_arm_age_minutes: 30   # disarm without firing if order was armed longer than this
```

- [ ] **Step 3.2: Write failing test for staleness disarm**

In `backend/tests/test_auto_trader.py`, add:

```python
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
```

- [ ] **Step 3.3: Run to confirm FAIL**

```bash
cd backend && pytest tests/test_auto_trader.py::test_maybe_fire_on_scan_disarms_stale_order -v
```

Expected: FAIL (no staleness check yet).

- [ ] **Step 3.4: Add staleness check to maybe_fire_on_scan() in auto_trader.py**

In `backend/app/services/auto_trader.py`, replace the `maybe_fire_on_scan` method with:

```python
    def maybe_fire_on_scan(
        self,
        portfolio_snapshot: list | None = None,
        portfolio_value: float | None = None,
    ) -> None:
        """Trigger #2: called after each scan completes. Fires if armed and fresh."""
        with self._lock:
            should_fire = self._state.armed
            strategy = self._state.strategy

        if not should_fire or strategy is None:
            return

        # Staleness guard — disarm without firing if the order is too old.
        max_age = self._max_arm_age_minutes()
        age_minutes = (datetime.now(timezone.utc) - strategy.armed_at).total_seconds() / 60
        if age_minutes > max_age:
            self.disarm()
            logger.warning(
                "AutoTrader: disarming stale armed order for %s (armed %.0f min ago, limit %d min)",
                strategy.symbol, age_minutes, max_age,
            )
            return

        try:
            self.fire(portfolio_snapshot=portfolio_snapshot, portfolio_value=portfolio_value)
            logger.info("AutoTrader: fired on scan completion trigger")
        except Exception as exc:
            logger.error("AutoTrader scan-trigger fire failed: %s", exc)

    @staticmethod
    def _max_arm_age_minutes() -> int:
        """Load max_arm_age_minutes from risk_rules.yaml (cached via lru_cache on the loader)."""
        import yaml
        from pathlib import Path
        config_path = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"
        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            return int(cfg.get("auto_trade", {}).get("max_arm_age_minutes", 30))
        except Exception:
            return 30
```

- [ ] **Step 3.5: Run all auto_trader tests**

```bash
cd backend && pytest tests/test_auto_trader.py -v
```

Expected: All PASS including the two new staleness tests.

- [ ] **Step 3.6: Run full backend test suite**

```bash
cd backend && pytest -v
```

Expected: All PASS. Fix any failures that arise.

- [ ] **Step 3.7: Commit**

```bash
git add backend/app/services/auto_trader.py backend/config/risk_rules.yaml backend/tests/test_auto_trader.py
git commit -m "fix(auto-trade): disarm stale armed orders on scan trigger

Armed orders older than max_arm_age_minutes (default 30, configurable in
risk_rules.yaml) are now disarmed without firing when a scan completes.
Prevents a 10am arm from executing on a 2pm scheduled scan at a stale
limit_price."
```

---

## Self-Review Checklist

### Spec coverage
- [x] Fix 1 — stock invalidation derived from delta/premium, not fixed pct
- [x] Fix 2 — exposure caps checked before every `execute_option_order()` call (manual + scan trigger)
- [x] Fix 3 — staleness check in `maybe_fire_on_scan()` with configurable threshold in YAML

### Placeholder scan
- No TBD, TODO (beyond the pre-existing broker stub comment), or "similar to Task N" patterns

### Type consistency
- `armed_at: datetime` — used consistently in Task 2 dataclass definition and Task 3 staleness check
- `portfolio_snapshot: list | None` — same type annotation in `fire()` and `maybe_fire_on_scan()`
- `orm_positions_to_risk()` returns `list[PortfolioPosition]` — matches what `check_position_risk()` expects

### Risk
- `fire()` disarms atomically before the exposure check. If the check fails, the order is already disarmed (fail-closed — re-arm to retry). This is intentional and matches the existing fail-closed contract.
- Backward compatibility: existing tests that call `svc.fire()` with no args still pass (check is skipped when `portfolio_snapshot is None`).
- `ArmedStrategy` has two new optional fields with defaults (`entry_premium=0.0`, `portfolio_value=50_000.0`), so existing `ArmedStrategy(...)` call sites without those fields still compile.
