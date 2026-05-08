# LLM Context — Workstream F: Risk Management (FR-42)

> **Self-contained.** Read this document fully before touching any code.
> Project root: `F:\Git\GitHub\Trading assistant`. Work in `.worktrees/feature-risk-management`.
> Do not modify any file outside the owned-files list.

---

## 1. Mission

**Conflict class: Medium** — modifies shared files (`types/domain.ts`, `dashboard/page.tsx`, `settings/page.tsx`) but only appends new content. Does not change existing logic or existing tab structures.

Build frontend risk management integration for the Bamendjou options screener. Every trade card must show explicit invalidation level and capital-at-risk. The `SendToBrokerDialog` must check risk limits before approval, show warnings, and allow the user to **override** the limit (not hard-block). The invalidation-stop check **is** a hard gate — no approval without a defined invalidation. Portfolio-level risk state is visible on the dashboard.

---

## 2. Owned files

| File path | Create/Modify | Purpose |
|---|---|---|
| `frontend/lib/riskStore.ts` | **Create** | Zustand store: risk limits, portfolio risk metrics, trade-check action |
| `frontend/lib/risk.ts` | **Create** | Pure helpers: capital-at-risk, exposure %, invalidation check |
| `frontend/components/atoms/RiskBadge/index.tsx` | **Create** | Risk status badge atom |
| `frontend/components/atoms/RiskBadge/RiskBadge.module.css` | **Create** | Styles for RiskBadge |
| `frontend/components/molecules/RiskPanel/index.tsx` | **Create** | Dashboard panel: exposure, concurrent count, concentration |
| `frontend/components/molecules/RiskPanel/RiskPanel.module.css` | **Create** | Styles for RiskPanel |
| `frontend/lib/__tests__/risk.test.ts` | **Create** | Unit tests for risk.ts helpers |
| `frontend/lib/__tests__/riskStore.test.ts` | **Create** | Unit tests for riskStore |
| `frontend/types/domain.ts` | **Modify** | Append `RiskLimits`, `RiskCheckResult`, `PortfolioRiskMetrics` |
| `frontend/app/(frame)/dashboard/page.tsx` | **Modify** | Add `<RiskPanel />` to bento row |
| `frontend/app/(frame)/settings/page.tsx` | **Modify** | Add `'risk'` section + `RiskForm` |
| `frontend/components/organisms/TradeCard/index.tsx` | **Modify** | Add invalidation + capital-at-risk row |
| `frontend/components/organisms/SendToBrokerDialog/index.tsx` | **Modify** | Risk gate with override |

---

## 3. Read-only references

| File | Reason |
|---|---|
| `frontend/types/domain.ts` | Read existing types before appending |
| `frontend/lib/portfolioStore.ts` | Read interface to know position shape |
| `frontend/lib/settingsStore.ts` | Read to align risk limit persistence |
| `frontend/mocks/portfolio.ts` | Fixture positions for testing |
| `frontend/app/(frame)/dashboard/page.tsx` | Read layout before inserting RiskPanel |
| `frontend/app/(frame)/settings/page.tsx` | Read tab structure before adding Risk tab |
| `frontend/components/organisms/TradeCard/index.tsx` | Read current card layout |
| `frontend/components/organisms/SendToBrokerDialog/index.tsx` | Read current dialog layout |
| `backend/app/services/portfolio_risk.py` | Reference for rule logic |
| `backend/config/risk_rules.yaml` | Reference for limit values |

---

## 4. Integration constraints

### Shared stores you consume

**`usePortfolioStore`** (from `@/lib/portfolioStore`)
```ts
const positions = usePortfolioStore((s) => s.positions);
const addPosition = usePortfolioStore((s) => s.addPosition);
```
- `PortfolioPosition` fields used: `symbol`, `contract`, `currentPrice`, `entryPrice`, `contracts`, `stop`, `targets`, `status`, `recId`

**`useSettingsStore`** (from `@/lib/settingsStore`)
```ts
const { customW, broker } = useSettingsStore();
```
- Add `riskLimits: RiskLimits` to the store interface and persist it.

### Components you consume

- `<Text size={11|12|13|14} tone="primary|secondary|dim|pass|caution|reject" weight={400|500|600} />`
- `<Data size={11..24} weight={500|600} tone="pass|caution|reject" />`
- `<StatusBadge status={Status} label?: string />`
- `<SectionCard title count? action? />` (molecule)

### Backend integration (optional but recommended)

Create `backend/app/routers/risk.py`:
```python
from fastapi import APIRouter
from app.services.portfolio_risk import check_position_risk, PortfolioPosition
from app.schemas import RiskCheckResult

router = APIRouter(prefix='/api', tags=['risk'])
```
This is a thin wrapper. The frontend should work with local `risk.ts` even if the backend endpoint isn't called yet.

---

## 5. CSS tokens (full list)

Copy these exact values. Never hardcode colors.

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
Key molecules: `SectionCard`, `TableRow`.

---

## 7. Domain types to append in `types/domain.ts`

Add these **at the end** of `frontend/types/domain.ts` (after the `NewsItem` interface). Do not modify existing types.

```ts
// --- Risk management ---

export interface RiskLimits {
  maxSingleTradeExposurePct: number;  // e.g. 0.05 = 5%
  maxTotalExposurePct: number;        // e.g. 0.25 = 25%
  maxConcurrentPositions: number;     // e.g. 10
  maxDailyRecommendations: number;    // e.g. 5
  portfolioValue: number;             // user's total portfolio value in $
}

export interface RiskCheckResult {
  approved: boolean;
  reasons: string[];
  adjustedContracts?: number;
  singleExposurePct: number;
  totalExposurePct: number;
  capitalAtRisk: number;
}

export interface PortfolioRiskMetrics {
  totalExposurePct: number;
  concurrentPositions: number;
  dailyRecommendations: number;
  largestConcentrationPct: number;
  largestConcentrationSymbol: string;
  status: Status;  // PASS if all within limits, CAUTION if near, REJECT if breached
}
```

---

## 8. Zustand stores

### `riskStore.ts` (new)

```ts
interface RiskState {
  limits: RiskLimits;
  dailyRecommendations: number;  // count today
  lastResetDate: string;         // ISO date
  metrics: PortfolioRiskMetrics;
  setLimits: (l: RiskLimits) => void;
  checkTrade: (card: TradeCardData, proposedContracts: number) => RiskCheckResult;
  incrementDaily: () => void;
  computeMetrics: (positions: PortfolioPosition[]) => void;
}
```

Default limits (mirror `backend/config/risk_rules.yaml`):
```ts
const DEFAULT_LIMITS: RiskLimits = {
  maxSingleTradeExposurePct: 0.05,
  maxTotalExposurePct: 0.25,
  maxConcurrentPositions: 10,
  maxDailyRecommendations: 5,
  portfolioValue: 50000,
};
```

Use `persist` middleware with key `bamendjou-risk-v1`.

---

## 9. Mock data

Use `frontend/mocks/portfolio.ts` (`MOCK_PORTFOLIO`) for testing.

| Symbol | Contracts | Entry | Current | P&L |
|---|---|---|---|---|
| AAPL | 2 | 4.15 | 5.02 | +870 |
| NVDA | 1 | 12.80 | 14.25 | +725 |
| MSFT | 2 | 8.20 | 8.85 | +325 |
| META | 1 | 9.40 | 8.10 | -390 |
| TSLA | 3 | 3.10 | 3.78 | +340 |

Total notional (contracts * 100 * currentPrice):
- AAPL: 2 * 100 * 5.02 = 1004
- NVDA: 1 * 100 * 14.25 = 1425
- MSFT: 2 * 100 * 8.85 = 1770
- META: 1 * 100 * 8.10 = 810
- TSLA: 3 * 100 * 3.78 = 1134
Total = 6143

Portfolio value default = 50000, so total exposure = 6143 / 50000 = 12.3%.

---

## 10. Task spec

### Acceptance criteria

1. `riskStore.checkTrade()` returns `approved=false` with `"single_trade_exposure_too_high"` when a trade would exceed `maxSingleTradeExposurePct`.
2. `riskStore.checkTrade()` returns `approved=false` with `"total_exposure_limit_reached"` when adding the trade would exceed `maxTotalExposurePct`.
3. `riskStore.checkTrade()` returns `approved=false` with `"max_concurrent_positions_reached"` when portfolio already has `maxConcurrentPositions` open.
4. `riskStore.checkTrade()` returns `approved=false` with `"duplicate_symbol"` when the symbol already exists in the portfolio.
5. `riskStore.checkTrade()` returns `approved=false` with `"missing_invalidation"` if `card.exit.invalidation` is 0 or undefined.
6. `riskStore.checkTrade()` returns `approved=true` for a clean trade within limits with a valid invalidation.
7. `RiskPanel` on dashboard shows: total exposure %, concurrent positions / max, largest concentration % + symbol, and an overall status badge.
8. `TradeCard` displays the invalidation level and estimated capital-at-risk (`mid * contracts * 100`).
9. `SendToBrokerDialog` shows risk warnings in a summary block before the Submit button; clicking Submit with warnings shows an "Override limit" confirmation. If invalidation is missing, the Submit button is disabled with a tooltip.
10. Settings page has a new **Risk** tab with inputs for: portfolio value, max single exposure %, max total exposure %, max concurrent positions, max daily recommendations.
11. All tests pass (`npm test -- --testPathPattern=risk`).
12. `npm run typecheck` is clean after every edit.

### Component details

**RiskBadge atom**
- Props: `status: Status`, `label?: string`
- Renders a small pill with border-left color matching status.

**RiskPanel molecule**
- Props: none (reads from `riskStore` and `portfolioStore`)
- Layout: 2x2 grid of stats + overall status on the right.
- Stats: "Exposure" (Data), "Positions" (Data), "Largest" (Data), "Daily" (Data).

**SendToBrokerDialog risk gate**
- Before the footer, add a `RiskSummary` block:
  - If clean: green text "Within risk limits".
  - If warnings: yellow text listing reasons + "Click Submit again to override".
  - If missing invalidation: red text "Invalidation stop required" + disabled Submit.
- The `onSubmit` callback should include a `riskOverridden: boolean` flag.

### Settings Risk tab

Add to `SECTIONS` array in `settings/page.tsx`:
```ts
{ key: 'risk', label: 'Risk', desc: 'Exposure limits and portfolio value' }
```

`RiskForm` uses `Row` component (already in settings/page.tsx) with numeric inputs.

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
10. **Override is allowed** for exposure limits — do not hard-block submission.
11. **Invalidation stop is a hard gate** — disable Submit if `invalidation === 0`.
12. Only append to `types/domain.ts` — do not modify existing interfaces.

---

## 12. Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001
npm run typecheck    # must be clean after every edit
npm test -- --testPathPattern=risk
```

---

## 13. Copy/paste prompt

```
Read `llm-contexts/31-risk-management.md` fully before writing any code.
It is your single source of truth.

You are implementing Workstream F (Risk Management, FR-42) for the Bamendjou options screener.
Your worktree: .worktrees/feature-risk-management

Your owned files:
- frontend/lib/riskStore.ts                      (CREATE)
- frontend/lib/risk.ts                           (CREATE)
- frontend/components/atoms/RiskBadge/index.tsx  (CREATE)
- frontend/components/atoms/RiskBadge/RiskBadge.module.css (CREATE)
- frontend/components/molecules/RiskPanel/index.tsx (CREATE)
- frontend/components/molecules/RiskPanel/RiskPanel.module.css (CREATE)
- frontend/lib/__tests__/risk.test.ts            (CREATE)
- frontend/lib/__tests__/riskStore.test.ts       (CREATE)
- frontend/types/domain.ts                       (MODIFY — append only)
- frontend/app/(frame)/dashboard/page.tsx        (MODIFY — add RiskPanel)
- frontend/app/(frame)/settings/page.tsx         (MODIFY — add Risk tab)
- frontend/components/organisms/TradeCard/index.tsx (MODIFY — add invalidation + CaR)
- frontend/components/organisms/SendToBrokerDialog/index.tsx (MODIFY — risk gate)

Do not modify any file outside this list.

Task: Build frontend risk management integration.
Key behaviors:
- riskStore.checkTrade() validates exposure, concurrency, duplicate symbol, and invalidation stop.
- RiskPanel shows portfolio risk metrics on the dashboard.
- TradeCard shows invalidation level and capital-at-risk estimate.
- SendToBrokerDialog shows risk warnings and allows override for limit breaches, but HARD-BLOCKS if invalidation stop is missing.
- Settings page has a Risk tab with editable limits.

After every file edit, run `npm run typecheck` from `frontend/`. Must stay clean.
Commit after each file is complete.
```
