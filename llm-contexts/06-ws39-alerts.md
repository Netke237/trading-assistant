---
workstream: WS-39
branch: feat/ws-39-alert-engine
phase: 2
depends_on: WS-34 (must be merged to main)
conflict_class: Zero — only touches alertEngine.ts, alertStore.ts, settingsStore.ts (one new field), backend alert_generator.py and alerts.py router.
---

# WS-39: Alert Engine — Real Implementation

## Mission

Replace the hardcoded fixture-based alert generation in `alert_generator.py` with real portfolio-driven alerts. Add deduplication (composite key `recId-alertType` with configurable window) and conflict suppression (skip alerts for symbols in `scanStore.conflictedSymbols`). Wire `GET /api/alerts` to the real alert pipeline.

**PRD coverage:** B3, G4, FR-37, FR-43

---

## Owned Files

| File | Action | Purpose |
|---|---|---|
| `frontend/lib/alertEngine.ts` | Modify | Add deduplication, direction-aware suppression, `recId` assignment |
| `frontend/lib/alertStore.ts` | Modify | Dedup by `recId + alertType` composite key with eviction |
| `frontend/lib/settingsStore.ts` | Modify | Add `alertDeduplicationHours: number = 24` field |
| `backend/app/services/alert_generator.py` | Modify | Replace hardcoded fixture with real portfolio-based generation |
| `backend/app/routers/alerts.py` | Modify | Wire `GET /api/alerts` to real `generate_alerts(portfolio)` |
| `backend/tests/test_alerts.py` | Create | Tests for alert generation, deduplication, conflict suppression |

**Do NOT touch any other files.**

---

## Read-Only References

Read these for patterns — do not modify:

- `frontend/lib/alertEngine.ts` — current `scanPortfolio()`, `AlertPosition`, `AlertReason` types
- `frontend/lib/alertStore.ts` — current `useAlertStore`, `addToast`, `ToastItem` types
- `frontend/lib/settingsStore.ts` — current `SettingsState` interface, `CustomWeights`, `BrokerConfig` (do NOT remove any field)
- `frontend/lib/scanStore.ts` — `conflictedSymbols` field (may need to be added to scanStore)
- `frontend/types/domain.ts` — `AlertKind`, `AlertType`, `AlertItem`, `ToastItem`, `PortfolioPosition` types
- `backend/app/services/alert_generator.py` — current implementation to extend
- `backend/app/routers/alerts.py` — current router to modify
- `backend/app/routers/portfolio.py` (after WS-34) — `PortfolioPosition` schema shape

---

## Alert Generation Rules (Backend)

Implement these exact rules in `backend/app/services/alert_generator.py`. For each `PortfolioPosition` in the portfolio:

```python
from app.schemas import PortfolioPositionSchema

def generate_alerts(
    positions: list[PortfolioPositionSchema],
    current_prices: dict[str, float],
    current_option_prices: dict[str, float] | None = None,
) -> list[dict]:
    """
    Generate alerts for all portfolio positions.

    For each position:
      TP_HIT:       current_price >= position.targets[0].stockPrice
      STOP_REACHED: current_price <= position.stop
      PREMIUM_STOP: current_option_price <= position.entryPrice * 0.60
      TIME_STOP:    position.dteRemaining <= 3
      EVENT_RISK:   position.nextEventDays exists and <= 3
    """
```

Rules in detail:

| Alert Type | Condition | Kind |
|---|---|---|
| `TP_HIT` | `current_price >= first_target.stockPrice` | Action |
| `STOP_REACHED` | `current_price <= position.stop` | Critical |
| `PREMIUM_STOP` | `current_option_price <= position.entryPrice * 0.60` | Critical |
| `TIME_STOP` | `dteRemaining <= 3` | Action |
| `EVENT_RISK` | `nextEventDays <= 3` | Action |

The function must return a list of alert dicts with: `{ recId, symbol, alertType, kind, reason, timestamp }`.

---

## Deduplication (Frontend)

### Dedup Key

Composite key: `${recId}-${alertType}`

Format: `"REC-20260508-A3F2B1C9-TP_HIT"`

This key uniquely identifies one specific alert for one specific position.

### Dedup Window

Configurable via `settingsStore.alertDeduplicationHours` (default: 24 hours).

Any alert with the same composite key that fired within the dedup window must be suppressed.

### Implementation in alertStore.ts

Replace the current string-based `makeDedupKey` with a composite key approach:

```typescript
// In alertStore.ts — add to state:
interface AlertStoreState {
  // ... existing fields ...
  firedAlerts: Map<string, number>;  // key: `${recId}-${alertType}`, value: Date.now() when fired
  isDuplicate: (recId: string, alertType: string) => boolean;
  evictExpiredAlerts: () => void;
}
```

The `addToast` action must:
1. Call `evictExpiredAlerts()` before checking
2. Build composite key from the incoming alert's `recId` and `alertType`
3. Check if key exists in `firedAlerts` — if yes, skip (duplicate)
4. If not duplicate, add to `firedAlerts` with current timestamp, then add the toast

Eviction: on every `addToast` or `evictExpiredAlerts()` call, remove entries from `firedAlerts` where `Date.now() - timestamp > settingsStore.alertDeduplicationHours * 3600_000`.

**Note on Zustand persist:** `Map` is not directly serializable. Store `firedAlerts` as a `Record<string, number>` instead of `Map<string, number>` for JSON compatibility, or exclude it from persistence (alerts that fired before a page refresh don't need to be remembered across sessions).

### Changes to alertEngine.ts

The `scanPortfolio()` function must:
1. Accept `positions` with `recId` on each `AlertPosition`
2. Return alerts that include the `recId` in the output
3. **Skip** any symbol that appears in `scanStore.conflictedSymbols`

Updated `AlertPosition` type:
```typescript
export interface AlertPosition {
  recId: string;       // NEW — from PortfolioPosition
  symbol: string;
  contract: string;
  currentPrice: number;
  entryPrice: number;
  stop: number;
  targets: TargetLevel[];
  dteRemaining: number;
  dteTotal: number;
  pnlPct: number;
  nextEventDays?: number;
  nextEventLabel?: string;
}

export interface AlertReason {
  recId: string;       // NEW — for dedup key construction
  kind: AlertKind;
  symbol: string;
  alertType: string;   // NEW — 'TP_HIT' | 'STOP_REACHED' | etc.
  reason: string;
}
```

### Conflict Suppression

In `scanPortfolio()`, add as the first check inside the loop:

```typescript
import { useScanStore } from '@/lib/scanStore';

// Inside scanPortfolio, before processing each position:
const conflicted = useScanStore.getState().conflictedSymbols;
if (conflicted && conflicted.includes(p.symbol)) continue;
```

**Note:** `scanStore` does not currently have a `conflictedSymbols` field. You must **add it** to `frontend/lib/scanStore.ts`:

```typescript
// In ScanStoreState interface, add:
conflictedSymbols: string[];
setConflictedSymbols: (symbols: string[]) => void;

// In create() initial state:
conflictedSymbols: [],
setConflictedSymbols: (symbols) => set({ conflictedSymbols: symbols }),
```

This field gets populated by the scan process when symbols are flagged as conflicted (CAUTION + REJECT status). Adding it to scanStore is part of this workstream since WS-39 needs it.

---

## settingsStore.ts — Add alertDeduplicationHours

Add ONE field to `SettingsState`:

```typescript
interface SettingsState {
  // ... existing fields (customW, customParams, broker) — DO NOT REMOVE ANY ...
  alertDeduplicationHours: number;
  setAlertDeduplicationHours: (hours: number) => void;
}
```

Initial value: `24`. Add a `setAlertDeduplicationHours` setter.

Update `persist` config:
- Increment `version` to `3`
- Add `alertDeduplicationHours: 24` to the `migrate` function for version < 3
- Include `alertDeduplicationHours` in `partialize` (must be persisted)

Update `resetToDefaults` to also reset `alertDeduplicationHours: 24`.

---

## Backend — alert_generator.py

Current `alert_generator.py` likely returns hardcoded fixture data. Replace with:

```python
async def generate_alerts(
    db: AsyncSession,
    current_prices: dict[str, float],
    current_option_prices: dict[str, float] | None = None,
) -> list[dict]:
    """Generate alerts for all open portfolio positions."""
    from app.models.portfolio import PortfolioPositionModel
    from sqlalchemy import select

    result = await db.execute(select(PortfolioPositionModel))
    positions = result.scalars().all()

    alerts = []
    for pos in positions:
        symbol = pos.symbol
        price = current_prices.get(symbol)
        opt_price = (current_option_prices or {}).get(pos.contract) if current_option_prices else None
        targets = pos.targets or []

        # TP_HIT
        if targets and price is not None and price >= targets[0].get("stockPrice", 0):
            alerts.append({
                "recId": pos.rec_id,
                "symbol": symbol,
                "alertType": "TP_HIT",
                "kind": "Action",
                "reason": f"Target reached — {symbol} at ${price:.2f}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # STOP_REACHED
        if pos.stop is not None and price is not None and price <= pos.stop:
            alerts.append({
                "recId": pos.rec_id,
                "symbol": symbol,
                "alertType": "STOP_REACHED",
                "kind": "Critical",
                "reason": f"Stop breached — {symbol} below ${pos.stop:.2f}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # PREMIUM_STOP
        if opt_price is not None and opt_price <= pos.entry_price * 0.60:
            alerts.append({
                "recId": pos.rec_id,
                "symbol": symbol,
                "alertType": "PREMIUM_STOP",
                "kind": "Critical",
                "reason": f"Premium stop — {symbol} option at ${opt_price:.2f}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # TIME_STOP
        if pos.dte_total is not None and pos.dte_total - pos.dte_total <= 3:  # approximate
            alerts.append({
                "recId": pos.rec_id,
                "symbol": symbol,
                "alertType": "TIME_STOP",
                "kind": "Action",
                "reason": f"Time stop — {symbol} {pos.dte_total} DTE",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    return alerts
```

**Use the actual schema field names from WS-34** — the portfolio model uses snake_case (`rec_id`, `entry_price`, `dte_total`). Map these correctly.

---

## Backend — alerts.py router

Update the router to call `generate_alerts()` instead of returning mock data:

```python
@router.get('/alerts')
async def get_alerts(db: AsyncSession = Depends(get_db)) -> list[dict]:
    # Fetch current prices from Tradier (or use mock prices for tests)
    # For MVP: use a placeholder price fetcher, return empty if unavailable
    from app.services.alert_generator import generate_alerts
    from app.services.market_data import fetch_current_prices  # if exists

    try:
        prices = await fetch_current_prices(db)  # or mock with {}
    except Exception:
        prices = {}

    alerts = await generate_alerts(db, prices)
    return alerts
```

If `fetch_current_prices` doesn't exist yet, use `{}` as fallback and add a `# TODO: wire to Tradier price feed` comment.

---

## CRITICAL WARNING

```
settingsStore.ts is shared across workstreams. Add alertDeduplicationHours: number = 24
alongside the existing fields (customW, customParams, broker). Do NOT remove or rename
any existing field — WS-41 will later add ivPassThreshold and ivCautionThreshold to this
same store.
```

Also: do NOT change any existing function signatures in `alertEngine.ts` or `alertStore.ts` unless adding a new required parameter (like `recId` to `AlertPosition`). Existing callers of `scanPortfolio()` will need updating to pass `recId` — handle this carefully.

---

## Tasks

- [ ] 1. Add `alertDeduplicationHours: number = 24` to `settingsStore.ts` — update `SettingsState` interface, initial state, `setAlertDeduplicationHours` action, `resetToDefaults`, `partialize`, version bump to 3, and migrate function.
- [ ] 2. Add `conflictedSymbols: string[]` and `setConflictedSymbols` to `scanStore.ts` — new field needed for conflict suppression.
- [ ] 3. Update `alertEngine.ts` — add `recId` and `alertType` to `AlertPosition` and `AlertReason` types. Add conflict suppression check (skip if `scanStore.conflictedSymbols.includes(symbol)`). Ensure `recId` propagates from `PortfolioPosition` through to each alert output.
- [ ] 4. Update `alertStore.ts` — replace simple string dedup with composite key `${recId}-${alertType}`. Use `Record<string, number>` keyed by composite key with timestamp. Add `evictExpiredAlerts()` that respects `settingsStore.alertDeduplicationHours`. Integrate into `addToast` flow.
- [ ] 5. Replace `alert_generator.py` with real portfolio-based generation — fetch positions from DB, evaluate each against the 5 rules, return alert list with `recId` on each.
- [ ] 6. Update `alerts.py` router to call `generate_alerts()` with real portfolio data instead of mock/fixture data.
- [ ] 7. Write `backend/tests/test_alerts.py` — test cases:
  - TP alert fires when price >= first target stockPrice
  - Stop alert fires when price <= stop
  - Premium stop fires when option price <= 60% of entry
  - Same alert type for same recId does NOT fire twice within dedup window
  - Conflicted symbol produces no automatic alert
  - Alert carries correct `recId` field
- [ ] 8. Run `pytest tests/test_alerts.py -v` — all pass. Run `cd frontend && npm run typecheck` — clean.

---

## Acceptance Criteria

- [ ] `GET /api/alerts` returns real alerts based on current portfolio positions, not hardcoded fixture data
- [ ] Same alert type for same position does not fire twice within the dedup window (24h default)
- [ ] Conflicted symbols produce no automatic alert
- [ ] `pytest tests/test_alerts.py` — pass; `npm run typecheck` clean

---

## Handover Prompt (copy-paste to start worker)

```
You are implementing WS-39 (Alert Engine — Real Implementation) for the Bamendjou options screener.

Working directory: F:\Git\GitHub\Trading assistant
Branch: feat/ws-39-alert-engine (create from main — WS-34 must already be merged)
Phase: 2
Depends: WS-34 (Backend Persistence) only — must be merged to main

Read the full context doc before writing any code:
  F:\Git\GitHub\Trading assistant\llm-contexts\06-ws39-alerts.md

Key files to read first (do not modify):
- frontend/lib/alertEngine.ts — current scanPortfolio, AlertPosition, AlertReason types
- frontend/lib/alertStore.ts — current dedup logic, ToastItem, addToast
- frontend/lib/settingsStore.ts — current SettingsState (add field, don't remove existing)
- frontend/lib/scanStore.ts — add conflictedSymbols field
- frontend/types/domain.ts — AlertKind, AlertType, AlertItem types
- backend/app/services/alert_generator.py — current implementation to replace
- backend/app/routers/alerts.py — current router to modify
- backend/app/routers/portfolio.py (after WS-34) — position schema shape

CRITICAL: settingsStore.ts is shared across workstreams. Add alertDeduplicationHours: number = 24
alongside the existing fields (customW, customParams, broker). Do NOT remove or rename
any existing field — WS-41 will later add ivPassThreshold and ivCautionThreshold to this
same store.

Also: add conflictedSymbols: string[] and setConflictedSymbols to scanStore.ts —
alertEngine.ts needs this for conflict suppression.

Tasks in order:
1. Add alertDeduplicationHours: 24 to settingsStore (bump version to 3, update migrate, partialize, resetToDefaults)
2. Add conflictedSymbols field to scanStore
3. Update alertEngine.ts: add recId/alertType to types, add conflict suppression
4. Update alertStore.ts: composite dedup key (recId-alertType), Map/Record-based, eviction
5. Replace alert_generator.py with real portfolio-based rules (5 alert types)
6. Wire alerts.py router to call generate_alerts()
7. Write test_alerts.py (6 test cases)
8. Run: cd backend && pytest tests/test_alerts.py -v (all pass)
9. Run: cd frontend && npm run typecheck (must be clean)

Return: one-paragraph summary of what you implemented, pytest output, and typecheck output.
```
