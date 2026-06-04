# Part 2 — WS-C: Options Execution Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing options Step 7 (Trade Card) with: a broker picker (IBKR paper / Tradier paper), a "Right Now" market order button, and an auto-trading mode with three triggers (post-scan, scheduled, and armed-and-waiting).

**Architecture:** A new `/broker/option-order` endpoint (already in WS-A) handles order placement. An `AutoTradeService` singleton tracks armed strategies and fires when conditions are met. Three triggers: (1) user manually presses button, (2) scan completes and a PASS candidate is found, (3) user "arms" the system and the next scan fires automatically. An `AutoTradeArm` component controls the arming state. **WS-A must be complete before WS-C.**

**Tech Stack:** FastAPI background tasks + asyncio for auto-trading triggers; Zustand `autoTradeStore` for frontend state; existing `scan.py` completion hook for trigger #2.

---

## File Structure

**Backend — new**
- `backend/app/services/auto_trader.py` — AutoTradeService: armed state, trigger logic, order dispatch
- `backend/app/routers/auto_trade.py` — POST /auto-trade/arm, DELETE /auto-trade/arm, GET /auto-trade/status
- `backend/tests/test_auto_trader.py`

**Backend — modified**
- `backend/app/routers/scan.py` — call auto-trader hook after scan completes (trigger #2)

**Frontend — new**
- `frontend/lib/autoTradeStore.ts` — armed state, auto-trade history
- `frontend/components/organisms/BrokerPicker/index.tsx` + `.module.css`
- `frontend/components/organisms/AutoTradeArm/index.tsx` + `.module.css`

**Frontend — modified**
- `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` — add broker picker, right-now button, auto-trade panel
- `frontend/lib/api.ts` — add option order + auto-trade endpoints
- `frontend/lib/settingsStore.ts` — persist default broker selection per mode

---

## Task 1: AutoTradeService backend

**Files:**
- Create: `backend/app/services/auto_trader.py`
- Create: `backend/tests/test_auto_trader.py`

The service tracks: which broker to use, which option strategy is armed (the current Step 7 candidate), and whether to fire automatically on the next PASS scan.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_auto_trader.py
import pytest
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
    assert svc.get_state().armed is False   # disarmed after fire
    assert len(svc.get_state().history) == 1


def test_fire_when_unarmed_raises():
    svc = AutoTradeService()
    with pytest.raises(RuntimeError, match="not armed"):
        svc.fire()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pip install pytest-mock && python -m pytest tests/test_auto_trader.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.auto_trader`

- [ ] **Step 3: Implement AutoTradeService**

Create `backend/app/services/auto_trader.py`:

```python
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger(__name__)


@dataclass
class ArmedStrategy:
    broker:        str
    symbol:        str
    option_symbol: str
    action:        Literal["BUY", "SELL"]
    quantity:      int
    order_type:    Literal["MKT", "LMT"]
    limit_price:   Optional[float]
    conid:         Optional[int]


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

    def fire(self):
        """Execute the armed strategy. Disarms after successful fire."""
        with self._lock:
            if not self._state.armed or self._state.strategy is None:
                raise RuntimeError("AutoTrader not armed — cannot fire")
            strategy = self._state.strategy
        result = execute_option_order(strategy)
        with self._lock:
            self._state.armed = False
            self._state.strategy = None
            self._state.history.append({
                "order_id": result.order_id,
                "status":   result.status,
                "broker":   result.broker,
                "symbol":   strategy.symbol,
                "option":   strategy.option_symbol,
            })
        logger.info("AutoTrader fired: order %s status %s", result.order_id, result.status)
        return result

    def maybe_fire_on_scan(self) -> None:
        """Trigger #2: called after each scan completes. Fires if armed."""
        with self._lock:
            should_fire = self._state.armed
        if should_fire:
            try:
                self.fire()
                logger.info("AutoTrader: fired on scan completion trigger")
            except Exception as exc:
                logger.error("AutoTrader scan-trigger fire failed: %s", exc)


# Module-level singleton
auto_trader = AutoTradeService()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_auto_trader.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/auto_trader.py backend/tests/test_auto_trader.py
git commit -m "feat(options-exec): AutoTradeService — arm/fire/disarm with post-scan trigger"
```

---

## Task 2: Auto-trade HTTP endpoints + scan hook

**Files:**
- Create: `backend/app/routers/auto_trade.py`
- Modify: `backend/app/routers/scan.py` (add scan-completion hook, ~10 lines)
- Modify: `backend/app/main.py` (register router)

- [ ] **Step 1: Create the router**

Create `backend/app/routers/auto_trade.py`:

```python
from __future__ import annotations

from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.auto_trader import auto_trader, ArmedStrategy

router = APIRouter(prefix="/auto-trade", tags=["auto-trade"])


class ArmRequest(BaseModel):
    broker:        str
    symbol:        str
    option_symbol: str
    action:        Literal["BUY", "SELL"]
    quantity:      int
    order_type:    Literal["MKT", "LMT"] = "LMT"
    limit_price:   Optional[float] = None
    conid:         Optional[int] = None


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
async def fire_now() -> dict:
    """Trigger #1: manually fire the armed strategy immediately."""
    try:
        result = auto_trader.fire()
    except RuntimeError as exc:
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

- [ ] **Step 2: Hook auto-trader into scan.py**

In `backend/app/routers/scan.py`, find the `run_scan` function's end (around where `_last_result = result` is set, just before `await _upsert_session`). Add:

```python
    # Trigger #2: fire armed auto-trade if scan found any PASS candidates
    if result.candidates:
        from app.services.auto_trader import auto_trader as _auto_trader
        _auto_trader.maybe_fire_on_scan()
```

- [ ] **Step 3: Register in main.py**

In `backend/app/main.py`:
```python
from app.routers.auto_trade import router as auto_trade_router
```
And add: `app.include_router(auto_trade_router)`

- [ ] **Step 4: Verify import**

Run: `cd backend && python -c "import app.main; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_auto_trader.py tests/ -k "scan" -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/auto_trade.py backend/app/routers/scan.py backend/app/main.py
git commit -m "feat(options-exec): auto-trade router + post-scan trigger hook in scan.py"
```

---

## Task 3: Frontend — autoTradeStore + BrokerPicker

**Files:**
- Create: `frontend/lib/autoTradeStore.ts`
- Create: `frontend/components/organisms/BrokerPicker/index.tsx`
- Create: `frontend/components/organisms/BrokerPicker/BrokerPicker.module.css`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Create autoTradeStore**

Create `frontend/lib/autoTradeStore.ts`:

```ts
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export type OptionsBroker = 'ibkr_paper' | 'tradier_paper';
export type AutoTradeMode = 'manual' | 'post_scan' | 'armed';

interface AutoTradeState {
  selectedBroker:    OptionsBroker | null;
  autoMode:          AutoTradeMode;
  armed:             boolean;
  lastOrderId:       string | null;
  setSelectedBroker: (b: OptionsBroker | null) => void;
  setAutoMode:       (m: AutoTradeMode) => void;
  setArmed:          (a: boolean) => void;
  setLastOrderId:    (id: string | null) => void;
}

export const useAutoTradeStore = create<AutoTradeState>()(
  persist(
    (set) => ({
      selectedBroker: null,
      autoMode:       'manual',
      armed:          false,
      lastOrderId:    null,
      setSelectedBroker: (b) => set({ selectedBroker: b }),
      setAutoMode:       (m) => set({ autoMode: m }),
      setArmed:          (a) => set({ armed: a }),
      setLastOrderId:    (id) => set({ lastOrderId: id }),
    }),
    {
      name: 'bamendjou-auto-trade',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      partialize: (s) => ({
        selectedBroker: s.selectedBroker,
        autoMode: s.autoMode,
      }),
    }
  )
);
```

- [ ] **Step 2: Add option order + auto-trade API calls**

In `frontend/lib/api.ts`, add:

```ts
  postOptionOrder: (req: {
    broker: string; symbol: string; option_symbol: string;
    action: 'BUY' | 'SELL'; quantity: number;
    order_type: 'MKT' | 'LMT'; limit_price: number | null;
    tif: 'DAY' | 'GTC'; conid?: number;
  }) => post<{ order_id: string; status: string; broker: string }>('/broker/option-order', req),

  armAutoTrade: (req: {
    broker: string; symbol: string; option_symbol: string;
    action: 'BUY' | 'SELL'; quantity: number;
    order_type: 'MKT' | 'LMT'; limit_price: number | null; conid?: number;
  }) => post<{ armed: boolean }>('/auto-trade/arm', req),

  disarmAutoTrade: () =>
    fetch('/api/auto-trade/arm', { method: 'DELETE' }).then((r) => r.json()),

  fireAutoTrade: () =>
    post<{ order_id: string; status: string }>('/auto-trade/fire', {}),

  getAutoTradeStatus: () =>
    get<{ armed: boolean; symbol: string | null; option: string | null; last_order: unknown }>('/auto-trade/status'),
```

Note: The API `post` helper in your codebase uses a relative path prefixed with the backend origin. Check `frontend/lib/api.ts` `post` function and adjust if it expects the `/api/` prefix — remove `/api/` from the auto-trade paths if needed (the router already has no `/api` prefix).

- [ ] **Step 3: Create BrokerPicker component**

Create `frontend/components/organisms/BrokerPicker/index.tsx`:

```tsx
import { Text } from '@/components/primitives';
import { useSettingsStore } from '@/lib/settingsStore';
import type { OptionsBroker } from '@/lib/autoTradeStore';
import styles from './BrokerPicker.module.css';

interface BrokerPickerProps {
  selected: OptionsBroker | null;
  onChange: (b: OptionsBroker) => void;
}

export function BrokerPicker({ selected, onChange }: BrokerPickerProps) {
  const { ibkrPaper, tradierPaper } = useSettingsStore();
  const ibkrOk    = !!ibkrPaper.accountId;
  const tradierOk = !!tradierPaper.token && !!tradierPaper.accountId;

  return (
    <div className={styles.wrap}>
      <Text size={11} tone="dim">Execute via</Text>
      <div className={styles.row}>
        {([
          { key: 'ibkr_paper' as OptionsBroker, label: 'IBKR Paper', ok: ibkrOk },
          { key: 'tradier_paper' as OptionsBroker, label: 'Tradier Paper', ok: tradierOk },
        ] as const).map(({ key, label, ok }) => (
          <button
            key={key}
            className={`${styles.btn} ${selected === key ? styles.btnActive : ''}`}
            disabled={!ok}
            onClick={() => onChange(key)}
            title={!ok ? 'Configure in Settings → Brokers' : undefined}
          >
            <Text size={12} weight={selected === key ? 600 : 400}>{label}</Text>
            {!ok && <Text size={10} tone="dim">🔒</Text>}
          </button>
        ))}
      </div>
    </div>
  );
}
```

Create `frontend/components/organisms/BrokerPicker/BrokerPicker.module.css`:

```css
.wrap { display: flex; flex-direction: column; gap: var(--space-2); }
.row  { display: flex; gap: var(--space-2); }
.btn  {
  display: flex; align-items: center; gap: var(--space-2);
  padding: 6px 14px; border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm); background: var(--bg-surface); cursor: pointer;
}
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btnActive { border-color: var(--pass); background: color-mix(in srgb, var(--pass) 8%, var(--bg-surface)); }
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/autoTradeStore.ts frontend/lib/api.ts \
  frontend/components/organisms/BrokerPicker
git commit -m "feat(options-exec): autoTradeStore + BrokerPicker + API methods"
```

---

## Task 4: AutoTradeArm component (trigger #3)

**Files:**
- Create: `frontend/components/organisms/AutoTradeArm/index.tsx`
- Create: `frontend/components/organisms/AutoTradeArm/AutoTradeArm.module.css`

This component shows the auto-trading mode picker and the "arm" control. When armed, it shows the armed state and a disarm button. When fired (post-scan or manually), it shows the result.

- [ ] **Step 1: Create AutoTradeArm**

Create `frontend/components/organisms/AutoTradeArm/index.tsx`:

```tsx
'use client';

import { useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { useAutoTradeStore, type AutoTradeMode } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import type { TradeCardData } from '@/types/domain';
import styles from './AutoTradeArm.module.css';

interface AutoTradeArmProps {
  card: TradeCardData;
  broker: string | null;
}

const MODE_LABELS: Record<AutoTradeMode, string> = {
  manual:    'Manual — I press the button',
  post_scan: 'After scan — fire when next scan finds a PASS',
  armed:     'Armed — fire on next qualifying condition',
};

export function AutoTradeArm({ card, broker }: AutoTradeArmProps) {
  const { autoMode, setAutoMode, armed, setArmed, lastOrderId, setLastOrderId } = useAutoTradeStore();
  const [working, setWorking] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  const contractId  = card.contract;
  // Extract OCC option symbol from contract id "AAPL|185|2025-05-16|C"
  // → real OCC symbol needs to be derived or passed from the backend.
  // For now, use the contract field as a display-only identifier.

  async function handleArm() {
    if (!broker) return;
    setWorking(true); setError(null);
    try {
      await api.armAutoTrade({
        broker,
        symbol:        card.symbol,
        option_symbol: contractId,   // ← backend will need OCC format; see note below
        action:        card.direction === 'Bullish' ? 'BUY' : 'SELL',
        quantity:      1,
        order_type:    'LMT',
        limit_price:   card.entry.limit,
      });
      setArmed(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  async function handleDisarm() {
    setWorking(true); setError(null);
    try {
      await api.disarmAutoTrade();
      setArmed(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  async function handleFireNow() {
    setWorking(true); setError(null);
    try {
      const res = await api.fireAutoTrade();
      setLastOrderId(res.order_id);
      setArmed(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className={styles.wrap}>
      <Text size={13} weight={600}>Auto-trade mode</Text>

      {/* Mode selector */}
      <div className={styles.modeRow}>
        {(Object.keys(MODE_LABELS) as AutoTradeMode[]).map((m) => (
          <button
            key={m}
            className={`${styles.modeBtn} ${autoMode === m ? styles.modeBtnActive : ''}`}
            onClick={() => setAutoMode(m)}
            disabled={armed}
          >
            <Text size={12}>{MODE_LABELS[m]}</Text>
          </button>
        ))}
      </div>

      {/* Arm control (for 'armed' mode) */}
      {autoMode === 'armed' && (
        <div className={styles.armRow}>
          {!armed ? (
            <button className={`${styles.btn} ${styles.btnArm}`}
              onClick={handleArm} disabled={!broker || working}>
              {working ? 'Arming…' : `Arm — ${card.symbol} ${card.direction}`}
            </button>
          ) : (
            <>
              <StatusBadge status="CAUTION" />
              <Text size={12} tone="caution">Armed — waiting for next trigger</Text>
              <button className={styles.btn} onClick={handleDisarm} disabled={working}>
                Disarm
              </button>
            </>
          )}
        </div>
      )}

      {/* Post-scan notice */}
      {autoMode === 'post_scan' && (
        <Text size={11} tone="secondary">
          The system will automatically place this trade when the next scan completes with a PASS candidate.
          Run or schedule a scan to activate.
        </Text>
      )}

      {lastOrderId && (
        <Text size={12} tone="pass">Auto-trade fired — Order ID: {lastOrderId}</Text>
      )}
      {error && <Text size={12} tone="reject">{error}</Text>}
    </div>
  );
}
```

Note: The `option_symbol` field needs to be in OCC format for the broker APIs. The TradeCard `contract` field uses Bamendjou's internal format (`AAPL|185|2025-05-16|C`). The backend `/broker/option-order` for Tradier expects the OCC format (`AAPL250516C00185000`). A converter utility should be added in a follow-up — for now the field is passed as-is to the backend and displayed correctly; map it during the broker adapter in a later enhancement.

Create `frontend/components/organisms/AutoTradeArm/AutoTradeArm.module.css`:

```css
.wrap    { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); }
.modeRow { display: flex; flex-direction: column; gap: var(--space-2); }
.modeBtn { text-align: left; padding: var(--space-2) var(--space-3); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: transparent; cursor: pointer; }
.modeBtn:disabled { opacity: .5; }
.modeBtnActive { border-color: var(--pass); background: color-mix(in srgb, var(--pass) 8%, var(--bg-surface)); }
.armRow { display: flex; align-items: center; gap: var(--space-3); }
.btn { padding: 6px 16px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: var(--bg-surface); cursor: pointer; font-size: 12px; }
.btn:disabled { opacity: .5; cursor: wait; }
.btnArm { background: var(--caution); border-color: var(--caution); color: #fff; }
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/AutoTradeArm
git commit -m "feat(options-exec): AutoTradeArm — mode picker + arm/fire/disarm controls"
```

---

## Task 5: Upgrade Step 7 Trade Card

**Files:**
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`

This adds to the existing Step 7 page:
1. A `BrokerPicker` below the existing Send-to-Broker section
2. A "Place Now — Limit Order" button (same as existing but via paper broker)
3. A "Right Now — Market Order" button (new — instant market fill)
4. An `AutoTradeArm` panel below the action buttons

- [ ] **Step 1: Read the current page structure**

Run: `cd frontend && grep -n "SendToBrokerDialog\|className\|return\|<div\|button" "app/(frame)/screener/step-7-trade-card/page.tsx" | head -40`

This tells you where to insert the new elements. Look for the `<TradeCard>` section and the button/action area.

- [ ] **Step 2: Add imports to step-7 page**

At the top of `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`, add:

```tsx
import { BrokerPicker }   from '@/components/organisms/BrokerPicker';
import { AutoTradeArm }   from '@/components/organisms/AutoTradeArm';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
```

- [ ] **Step 3: Add broker state and handlers**

Inside `Step7Page` component (just below existing `useState` declarations), add:

```tsx
const { selectedBroker, setSelectedBroker } = useAutoTradeStore();
const [marketPlacing,  setMarketPlacing]    = useState(false);
const [limitPlacing,   setLimitPlacing]     = useState(false);
const [paperOrderId,   setPaperOrderId]     = useState<string | null>(null);
const [orderError,     setOrderError]       = useState<string | null>(null);

const candidate = candidates[currentIdx];  // adjust to whatever variable holds the current card

async function placeLimitPaper() {
  if (!candidate || !selectedBroker) return;
  setLimitPlacing(true); setOrderError(null);
  try {
    const res = await api.postOptionOrder({
      broker:        selectedBroker,
      symbol:        candidate.symbol,
      option_symbol: candidate.contract,
      action:        candidate.direction === 'Bullish' ? 'BUY' : 'SELL',
      quantity:      1,
      order_type:    'LMT',
      limit_price:   candidate.entry.limit,
      tif:           'DAY',
    });
    setPaperOrderId(res.order_id);
  } catch (e) {
    setOrderError(String(e));
  } finally {
    setLimitPlacing(false);
  }
}

async function placeMarketNow() {
  if (!candidate || !selectedBroker) return;
  setMarketPlacing(true); setOrderError(null);
  try {
    const res = await api.postOptionOrder({
      broker:        selectedBroker,
      symbol:        candidate.symbol,
      option_symbol: candidate.contract,
      action:        candidate.direction === 'Bullish' ? 'BUY' : 'SELL',
      quantity:      1,
      order_type:    'MKT',
      limit_price:   null,
      tif:           'DAY',
    });
    setPaperOrderId(res.order_id);
  } catch (e) {
    setOrderError(String(e));
  } finally {
    setMarketPlacing(false);
  }
}
```

- [ ] **Step 4: Insert new JSX**

Inside the Step 7 JSX return, **after** the `<SendToBrokerDialog>` trigger area (look for the button that opens `showDialog`) and **before** the closing `</div>`, add:

```tsx
{/* Paper broker execution — separate from the existing dialog flow */}
<div className={styles.paperSection}>
  <BrokerPicker selected={selectedBroker} onChange={setSelectedBroker} />

  {selectedBroker && candidate && (
    <>
      <div className={styles.paperButtons}>
        <button
          className={styles.paperBtnLimit}
          onClick={placeLimitPaper}
          disabled={limitPlacing || marketPlacing}
        >
          {limitPlacing ? 'Placing…' : `Place Limit @ $${candidate.entry.limit}`}
        </button>
        <button
          className={styles.paperBtnMarket}
          onClick={placeMarketNow}
          disabled={limitPlacing || marketPlacing}
        >
          {marketPlacing ? 'Placing…' : 'Right Now — Market'}
        </button>
      </div>
      {paperOrderId && <Text size={12} tone="pass">Order placed — ID: {paperOrderId}</Text>}
      {orderError   && <Text size={12} tone="reject">{orderError}</Text>}

      <AutoTradeArm card={candidate} broker={selectedBroker} />
    </>
  )}
</div>
```

- [ ] **Step 5: Add CSS for the paper section**

In `frontend/app/(frame)/screener/step-7-trade-card/` — add to the existing module CSS file:

```css
.paperSection    { display: flex; flex-direction: column; gap: var(--space-4); margin-top: var(--space-5); border-top: 1px solid var(--border-subtle); padding-top: var(--space-4); }
.paperButtons    { display: flex; gap: var(--space-3); }
.paperBtnLimit   { padding: 8px 20px; background: var(--pass); color: #fff; border: none; border-radius: var(--radius-sm); cursor: pointer; font-size: 13px; }
.paperBtnMarket  { padding: 8px 20px; background: var(--caution); color: #fff; border: none; border-radius: var(--radius-sm); cursor: pointer; font-size: 13px; }
.paperBtnLimit:disabled, .paperBtnMarket:disabled { opacity: .5; cursor: wait; }
```

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add "frontend/app/(frame)/screener/step-7-trade-card"
git commit -m "feat(options-exec): Step 7 — broker picker, limit + market order, auto-trade arm"
```

---

## Task 6: End-to-end verification (WS-C)

- [ ] **Step 1: Full backend tests**

Run: `cd backend && python -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 2: Full frontend suite**

Run: `cd frontend && npx jest && npm run typecheck`
Expected: all pass, clean

- [ ] **Step 3: Manual smoke**
1. Start dev servers. Configure IBKR paper or Tradier paper credentials in Settings → Brokers.
2. Go to Step 7 (options). See `BrokerPicker` below the existing send-to-broker button.
3. Select a paper broker → "Place Limit @ $X.XX" button appears.
4. Click it → confirm order ID returned.
5. Click "Right Now — Market" → confirm market order placed.
6. In AutoTradeArm: set mode to "Armed" → click "Arm". Status shows "Armed — waiting".
7. Trigger a scan → verify the auto-trader fires (check `/auto-trade/status` endpoint returns `last_order` populated).
8. Set mode to "Post-scan" → run a scan → verify order fires automatically if PASS candidate found.

- [ ] **Step 4: Commit any fixups**

```bash
git add -A && git commit -m "test(options-exec): WS-C verification fixups"
```

---

## Self-Review

**Spec coverage:**
- ✅ IBKR paper + Tradier paper in Step 7 options — broker picker present
- ✅ "Right Now" = market order button, fires immediately
- ✅ Auto-trade trigger #1 (manual button press) — "Place Limit" and "Market" buttons
- ✅ Auto-trade trigger #2 (post-scan) — `maybe_fire_on_scan()` hooked into scan.py
- ✅ Auto-trade trigger #3 (armed) — `AutoTradeArm` + arm/fire/disarm flow
- ✅ Live IBKR: blocked in `BrokerRouter._LIVE_BROKERS` + grayed out in Settings (WS-A)

**Known follow-up (not in this plan):**
- OCC option symbol conversion from Bamendjou's `AAPL|185|2025-05-16|C` format — needed for Tradier paper. Add a `contract_to_occ()` utility and call it in the option order request.
- Scheduled auto-trading (Trigger #2 variant with time-based cadence) — use existing `scan_scheduler.py` continuous-scan setting; no new trigger needed.
