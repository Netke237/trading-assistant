# LLM Context — Workstream G: Alerting & Monitoring (FR-37, FR-43)

> **Self-contained.** Read this document fully before touching any code.
> Project root: `F:\Git\GitHub\Trading assistant`. Work in `.worktrees/feature-alerting-monitoring`.
> Do not modify any file outside the owned-files list.

---

## 1. Mission

**Conflict class: Medium** — modifies shared files (`types/domain.ts`, `dashboard/page.tsx`, `settings/page.tsx`, `TopBar/index.tsx`) but only appends new content. Does not change existing logic or existing tab structures.

Build the alerting & monitoring system for the Bamendjou options screener. The system must:
1. Generate alerts from portfolio state (TP hit, stop reached, premium stop, time stop approaching, earnings approaching, expiration approaching).
2. Rate-limit and deduplicate alerts using configurable windows.
3. Deliver alerts via in-app toasts + a badge count on the TopBar.
4. Show recent alerts on the dashboard.
5. Make alert settings configurable (deduplication windows, per-type toggles).

---

## 2. Owned files

| File path | Create/Modify | Purpose |
|---|---|---|
| `frontend/lib/alertStore.ts` | **Create** | Zustand store: alert queue, dedup windows, unread count |
| `frontend/lib/alertEngine.ts` | **Create** | Pure helpers: scan portfolio and generate alert items |
| `frontend/mocks/alerts.ts` | **Create** | Fixture alert data for stories/tests |
| `frontend/components/atoms/AlertBadge/index.tsx` | **Create** | Unread count badge for TopBar |
| `frontend/components/atoms/AlertBadge/AlertBadge.module.css` | **Create** | Styles for AlertBadge |
| `frontend/components/molecules/Toast/index.tsx` | **Create** | Single toast notification |
| `frontend/components/molecules/Toast/Toast.module.css` | **Create** | Styles for Toast |
| `frontend/components/organisms/ToastContainer/index.tsx` | **Create** | Fixed-position container for toasts |
| `frontend/components/organisms/ToastContainer/ToastContainer.module.css` | **Create** | Styles for ToastContainer |
| `frontend/lib/__tests__/alertEngine.test.ts` | **Create** | Unit tests for alert generation logic |
| `frontend/lib/__tests__/alertStore.test.ts` | **Create** | Unit tests for alert store |
| `frontend/types/domain.ts` | **Modify** | Append `AlertConfig`, `AlertRule`, `ToastItem` |
| `frontend/app/(frame)/dashboard/page.tsx` | **Modify** | Wire alert engine interval, add ToastContainer |
| `frontend/app/(frame)/settings/page.tsx` | **Modify** | Add `'alertConfig'` section + `AlertConfigForm` |
| `frontend/components/organisms/TopBar/index.tsx` | **Modify** | Add `<AlertBadge />` |
| `backend/app/services/alert_generator.py` | **Create** | Backend alert generation service |
| `backend/app/routers/alerts.py` | **Modify** | Return generated alerts instead of empty list |

---

## 3. Read-only references

| File | Reason |
|---|---|
| `frontend/types/domain.ts` | Read existing types before appending |
| `frontend/lib/portfolioStore.ts` | Read position shape for alert engine |
| `frontend/lib/watchlistStore.ts` | Read watchlist shape for event alerts |
| `frontend/components/organisms/TopBar/index.tsx` | Read layout before adding badge |
| `frontend/app/(frame)/dashboard/page.tsx` | Read layout before adding ToastContainer |
| `frontend/app/(frame)/settings/page.tsx` | Read tab structure before adding alerts tab |
| `frontend/mocks/portfolio.ts` | Fixture positions |
| `backend/app/services/alert_service.py` | WebSocket broadcast registry |
| `backend/app/routers/alerts.py` | Current empty endpoint |

---

## 4. Integration constraints

### Shared stores you consume

**`usePortfolioStore`** (from `@/lib/portfolioStore`)
```ts
const positions = usePortfolioStore((s) => s.positions);
```
- Fields used: `symbol`, `contract`, `currentPrice`, `entryPrice`, `stop`, `targets`, `dteRemaining`, `dteTotal`, `status`, `nextEventDays`, `nextEventLabel`

**`useWatchlistStore`** (from `@/lib/watchlistStore`)
```ts
const symbols = useWatchlistStore((s) => s.symbols);
```
- Used to generate "new candidate" alerts (not needed for portfolio alerts).

**`useScanStore`** (from `@/lib/scanStore`)
```ts
const { scanState, scanAt } = useScanStore();
```
- Used for scan-complete alerts.

### Components you consume

- `<Text size={11|12|13|14} tone="primary|secondary|dim|pass|caution|reject" weight={400|500|600} />`
- `<Data size={11..24} weight={500|600} tone="pass|caution|reject" />`
- `<AlertRow kind symbol reason timestamp />` (molecule — already exists at `components/molecules/AlertRow/index.tsx`)

### Backend integration

Modify `backend/app/routers/alerts.py` to return fixture/generated alerts:
```python
from fastapi import APIRouter
from app.schemas import AlertItem
from app.services.alert_generator import generate_alerts

router = APIRouter(prefix='/api', tags=['alerts'])

@router.get('/alerts', response_model=list[AlertItem])
async def get_alerts() -> list[AlertItem]:
    return generate_alerts()
```

Create `backend/app/services/alert_generator.py`:
```python
from __future__ import annotations
from datetime import datetime, timezone
from app.schemas import AlertItem

def generate_alerts() -> list[AlertItem]:
    """Generate alerts from current portfolio and watchlist state."""
    return [
        AlertItem(
            id="a1",
            kind="Critical",
            symbol="META",
            reason="Broke trail stop",
            timestamp="09:38",
        ),
        AlertItem(
            id="a2",
            kind="Action",
            symbol="NVDA",
            reason="Earnings in 3 days — roll or close",
            timestamp="09:41",
        ),
    ]
```

---

## 5. CSS tokens (full list)

Same as Workstream F context doc. Copy these exact values.

```css
/* Backgrounds */
--bg-base:          #131722;
--bg-surface:       #1E2335;
--bg-surface-2:     #252B43;
--bg-surface-3:     #2A3152;

/* Borders */
--border-subtle:    #2A2E42;
--border-strong:    #363B54;

/* Text */
--text-primary:     #D1D4DC;
--text-secondary:   #787B86;
--text-dim:         #434651;

/* Status — PASS */
--pass:             #26A69A;
--pass-bg:          #0D201F;
--pass-border:      #1A3533;

/* Status — CAUTION */
--caution:          #F59F00;
--caution-bg:       #1F1A0D;
--caution-border:   #352E1A;

/* Status — REJECT */
--reject:           #EF5350;
--reject-bg:        #1F0E0D;
--reject-border:    #352020;

/* Accent */
--accent:           #2962FF;
--accent-hover:     #1E53E5;
--accent-dim:       #142B7A;
--accent-text:      #FFFFFF;

/* Spacing (4px base) */
--space-1:  4px;  --space-2:  8px;  --space-3: 12px;
--space-4: 16px;  --space-5: 20px;  --space-6: 24px;
--space-8: 32px;  --space-12: 48px;

/* Radius */
--radius-sm: 4px;  --radius-md: 6px;  --radius-lg: 10px;
```

---

## 6. Primitives & component reference

Same as LLM_CONTEXT.md Sections 6 and 7.

Key atoms: `StatusBadge`, `Data`, `Text`.
Key molecules: `AlertRow`, `SectionCard`.

---

## 7. Domain types to append in `types/domain.ts`

Add these **at the end** of `frontend/types/domain.ts` (after the `NewsItem` interface). Do not modify existing types.

```ts
// --- Alerting & monitoring ---

export interface AlertConfig {
  dedupWindowMinutes: number;      // default 15
  enabledTypes: AlertType[];
  soundEnabled: boolean;
}

export type AlertType =
  | 'TP_HIT'
  | 'STOP_REACHED'
  | 'PREMIUM_STOP'
  | 'TIME_STOP_APPROACHING'
  | 'EARNINGS_APPROACHING'
  | 'EXPIRATION_APPROACHING'
  | 'REGIME_CHANGE'
  | 'SCAN_COMPLETE';

export interface AlertRule {
  type: AlertType;
  label: string;
  threshold?: number;  // e.g. DTE threshold for time-stop
}

export interface ToastItem {
  id: string;
  kind: AlertKind;
  symbol: string;
  reason: string;
  dismissed: boolean;
}
```

---

## 8. Zustand stores

### `alertStore.ts` (new)

```ts
interface AlertStoreState {
  toasts: ToastItem[];
  unreadCount: number;
  config: AlertConfig;
  addToast: (item: Omit<ToastItem, 'id' | 'dismissed'>) => void;
  dismissToast: (id: string) => void;
  clearAll: () => void;
  setConfig: (c: AlertConfig) => void;
}
```

Default config:
```ts
const DEFAULT_CONFIG: AlertConfig = {
  dedupWindowMinutes: 15,
  enabledTypes: [
    'TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP', 'TIME_STOP_APPROACHING',
    'EARNINGS_APPROACHING', 'EXPIRATION_APPROACHING',
  ],
  soundEnabled: false,
};
```

Use `persist` middleware with key `bamendjou-alerts-v1`.

**Deduplication logic:**
```ts
function makeDedupKey(item: Omit<ToastItem, 'id' | 'dismissed'>): string {
  return `${item.kind}:${item.symbol}:${item.reason}`;
}
```
Before adding a toast, check if an existing toast with the same `makeDedupKey` was added within `config.dedupWindowMinutes`. If yes, skip.

---

## 9. Mock data

Create `frontend/mocks/alerts.ts`:

```ts
import type { AlertItem } from '@/types/domain';

export const MOCK_ALERTS: AlertItem[] = [
  { id: 'a1', kind: 'Critical', symbol: 'META', reason: 'Broke trail stop', timestamp: '09:38' },
  { id: 'a2', kind: 'Action',   symbol: 'NVDA', reason: 'Earnings in 3 days — roll or close', timestamp: '09:41' },
  { id: 'a3', kind: 'Action',   symbol: 'AAPL', reason: 'Target 80% reached', timestamp: '09:47' },
  { id: 'a4', kind: 'Info',     symbol: 'SPY',  reason: 'Regime flipped to PASS', timestamp: '09:15' },
  { id: 'a5', kind: 'Info',     symbol: 'TSLA', reason: 'IV rank > 70', timestamp: '09:02' },
];
```

---

## 10. Task spec

### Acceptance criteria

1. `alertEngine.scanPortfolio(positions)` returns an array of alert reasons for every portfolio position that meets a trigger condition.
2. `alertEngine` generates `TP_HIT` when `position.currentPrice >= position.targets[0].stockPrice`.
3. `alertEngine` generates `STOP_REACHED` when the stock price (mocked as `currentPrice` proxy) drops below `position.stop`.
4. `alertEngine` generates `TIME_STOP_APPROACHING` when `position.dteRemaining <= Math.ceil(position.dteTotal * 0.3)`.
5. `alertEngine` generates `EARNINGS_APPROACHING` when `position.nextEventDays != undefined && position.nextEventDays <= 3`.
6. `alertEngine` generates `EXPIRATION_APPROACHING` when `position.dteRemaining <= 3`.
7. `alertStore.addToast()` deduplicates: the same `(kind, symbol, reason)` within `dedupWindowMinutes` is not added again.
8. `AlertBadge` on the TopBar shows the unread toast count as a small red circle.
9. `ToastContainer` renders up to 3 active toasts in the top-right corner of the viewport.
10. `Dashboard` runs `alertEngine.scanPortfolio()` every 30 seconds via `useEffect` + `setInterval`, and adds generated alerts to `alertStore`.
11. `Dashboard` alert list (SectionCard "Alerts") renders recent toasts using the existing `AlertRow` molecule.
12. Settings page has an **Alerts** tab with toggles for each `AlertType` and a numeric input for deduplication window minutes.
13. `backend/app/routers/alerts.py` returns `MOCK_ALERTS` instead of an empty list.
14. All tests pass (`npm test -- --testPathPattern=alert`).
15. `npm run typecheck` is clean after every edit.

### Component details

**AlertBadge atom**
- Props: `count: number`
- Renders a small circle with the count. If `count === 0`, render nothing (or a tiny dot).
- Position: absolute, top-right of the bell icon area in TopBar.

**Toast molecule**
- Props: `item: ToastItem; onDismiss: (id: string) => void`
- Layout: icon + symbol + reason + dismiss button.
- Auto-dismiss after 5 seconds unless hovered.
- Uses `AlertRow` internally or mirrors its style.

**ToastContainer organism**
- Fixed position top-right, `z-index: 100`.
- Stacks up to 3 toasts vertically.
- Reads from `alertStore` toasts that are not dismissed.

**TopBar modification**
- Add a bell icon button (reuse existing icon style or add a simple SVG).
- Wrap it with `AlertBadge` showing `alertStore.unreadCount`.
- Clicking the bell clears unread count (`alertStore.clearAll()` or just mark as read).

**Dashboard modification**
- In the `useEffect` that loads data, add a `setInterval(30000)` that calls `alertEngine.scanPortfolio(portfolio)` and feeds results to `alertStore.addToast()`.
- Add `<ToastContainer />` as a fixed overlay inside the page (outside the bento flow).

### Settings Alerts tab

Replace the existing placeholder `AlertsForm` in `settings/page.tsx` with a real implementation:
- Add to `SECTIONS`: `{ key: 'alerts', label: 'Alerts', desc: 'Notification types and deduplication' }` — the section key already exists; modify the `AlertsForm` component.
- Rows:
  - Deduplication window (minutes) — numeric input, default 15.
  - Per-type toggles — use the `Toggle` component already in settings/page.tsx.
  - Sound — toggle, default off.

---

## 11. Hard rules

1. No Tailwind, styled-components, or CSS-in-JS.
2. No `style={{}}` except computed one-off values.
3. No hardcoded colors — always use CSS custom properties.
4. No invented Status labels — only `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. No font-weight 600 on form labels — use `weight={400}`.
6. No card box-shadows — use `border: 1px solid var(--border-subtle)`.
7. Never skip component hierarchy: atom → molecule → organism.
8. `npm run typecheck` must be clean before every commit.
9. Do not touch `node_modules/` or `package-lock.json`.
10. Only append to `types/domain.ts` — do not modify existing interfaces.
11. Toast auto-dismiss must respect `prefers-reduced-motion`.

---

## 12. Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001
npm run typecheck    # must be clean after every edit
npm test -- --testPathPattern=alert
```

---

## 13. Copy/paste prompt

```
Read `llm-contexts/32-alerting-monitoring.md` fully before writing any code.
It is your single source of truth.

You are implementing Workstream G (Alerting & Monitoring, FR-37/FR-43) for the Bamendjou options screener.
Your worktree: .worktrees/feature-alerting-monitoring

Your owned files:
- frontend/lib/alertStore.ts                              (CREATE)
- frontend/lib/alertEngine.ts                             (CREATE)
- frontend/mocks/alerts.ts                                (CREATE)
- frontend/components/atoms/AlertBadge/index.tsx          (CREATE)
- frontend/components/atoms/AlertBadge/AlertBadge.module.css (CREATE)
- frontend/components/molecules/Toast/index.tsx           (CREATE)
- frontend/components/molecules/Toast/Toast.module.css    (CREATE)
- frontend/components/organisms/ToastContainer/index.tsx  (CREATE)
- frontend/components/organisms/ToastContainer/ToastContainer.module.css (CREATE)
- frontend/lib/__tests__/alertEngine.test.ts              (CREATE)
- frontend/lib/__tests__/alertStore.test.ts               (CREATE)
- frontend/types/domain.ts                                (MODIFY — append only)
- frontend/app/(frame)/dashboard/page.tsx                 (MODIFY — add ToastContainer + interval)
- frontend/app/(frame)/settings/page.tsx                  (MODIFY — replace AlertsForm)
- frontend/components/organisms/TopBar/index.tsx          (MODIFY — add AlertBadge)
- backend/app/services/alert_generator.py                 (CREATE)
- backend/app/routers/alerts.py                           (MODIFY)

Do not modify any file outside this list.

Task: Build the alerting & monitoring system.
Key behaviors:
- alertEngine.scanPortfolio() generates alerts for TP hit, stop reached, time stop approaching, earnings approaching, expiration approaching.
- alertStore deduplicates toasts within a configurable window.
- ToastContainer shows up to 3 active toasts in the top-right.
- AlertBadge on TopBar shows unread count.
- Dashboard scans portfolio every 30s and surfaces alerts.
- Settings page has real alert toggles + dedup window config.
- Backend alerts endpoint returns fixture alerts.

After every file edit, run `npm run typecheck` from `frontend/`. Must stay clean.
Commit after each file is complete.
```
