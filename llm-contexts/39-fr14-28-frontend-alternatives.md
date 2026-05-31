# Context Doc 39 — FR-14/28 Frontend: AlternativeContract UI in Steps 6 and 7

**Workstream:** WT-7b — Display `alternatives[]` from `TradeCardData` in the Step 7 TradeCard and show an alternatives count badge in the Step 6 contracts table
**Conflict class:** Low — touches TradeCard organism, Step 6 page, and adds one new molecule

---

## 1. Mission

The `AlternativeContract` type and mock data already exist (from WT-6). The backend scanner will produce real `alternatives[]` arrays (WT-7a, running in parallel). This workstream builds the UI that displays them:

1. **Step 7 (TradeCard):** A collapsible "Alternatives" section below the contract-details block. Each alternative shows its key metrics and the `reason` string. Read-only — no editing, no selection, no basket changes.
2. **Step 6 (contracts table):** A small count badge ("2 alt") in the table when the currently-selected candidate has alternatives.

Build and test against the existing mock data in `frontend/mocks/tradecards.ts`. When the backend lands, `GET /api/tradecards` returns the real data and nothing in this worktree needs to change.

---

## 2. Owned files

| File | Action |
|---|---|
| `frontend/components/molecules/AlternativeContractRow/index.tsx` | New — one row per alternative |
| `frontend/components/molecules/AlternativeContractRow/AlternativeContractRow.module.css` | New |
| `frontend/components/organisms/TradeCard/index.tsx` | Add collapsible Alternatives section |
| `frontend/components/organisms/TradeCard/TradeCard.module.css` | Add styles for the new section |
| `frontend/app/(frame)/screener/step-6-contracts/page.tsx` | Add count badge |

Do not touch any other file.

---

## 3. Read-only references

| File | Why |
|---|---|
| `frontend/types/domain.ts` lines 171–187 | `AlternativeContract` interface — your props must match it exactly |
| `frontend/types/domain.ts` lines 90–135 | `TradeCardData` interface — `alternatives?: AlternativeContract[]`, `alternativesCount?: number` |
| `frontend/mocks/tradecards.ts` | Contains 2–3 alternatives per candidate — use this for dev/testing |
| `frontend/components/primitives/` | `<Text>`, `<Data>` — use these, never `<p>` or `<span>` with raw text |
| `frontend/components/atoms/StatusBadge/index.tsx` | Use for `contractConfidence` display |
| `frontend/lib/status.ts` | `statusForScore(score): Status` — use for score → status mapping |
| `frontend/app/globals.css` | All CSS variable tokens — never hardcode colours |
| `frontend/components/organisms/TradeCard/index.tsx` | Existing TradeCard — add the alternatives section here |
| `frontend/app/(frame)/screener/step-6-contracts/page.tsx` | Existing Step 6 — add count badge here |
| `frontend/lib/scanStore.ts` | `useScanStore` — `(s) => s.scanResult?.candidates` to find the current candidate |

---

## 4. AlternativeContract type (for reference)

```typescript
// frontend/types/domain.ts — read-only, do not modify

export interface AlternativeContract {
  symbol:             string;
  strike:             number;
  expiry:             string;
  right:              'C' | 'P';
  dte:                number;
  mid:                number;         // premium, $
  delta:              number;
  theta:              number;         // $/day
  ivRank:             number;         // 0–100
  score:              number;         // 0–100
  contractConfidence: Status;
  contractBreakdown:  ContractScoreBreakdown;
  rrRatio:            number;
  rrModel:            'Heston repriced' | 'Delta approximation';
  reason:             string;
}
```

---

## 5. Component to build: AlternativeContractRow (molecule)

**Location:** `frontend/components/molecules/AlternativeContractRow/index.tsx`

**Props:**
```typescript
interface AlternativeContractRowProps {
  alt:   AlternativeContract;
  rank:  number;           // 1-based display index ("Alt 1", "Alt 2")
}
```

**Layout (single card, full width):**

```
┌─────────────────────────────────────────────────────────────┐
│ Alt 1   AAPL 185C 05/23   DTE 31             [CAUTION] 72  │
│ Mid $4.80  Δ 0.63  θ −0.06  IV rank 42   R/R 2.0×         │
│ Lower strike, higher delta — more directional exposure       │
└─────────────────────────────────────────────────────────────┘
```

**Rules:**
- "Alt N" label: `<Text size={11} tone="dim">` — top-left
- Contract ID: `{symbol} {strike}{right} {expiry}` — `<Text size={12} tone="primary">`
- DTE: `<Text size={11} tone="secondary">`
- Score badge: `<StatusBadge status={alt.contractConfidence} />` + `<Data size={12}>{alt.score}</Data>`
- Mid, delta, theta, ivRank: `<Data size={12}>` for numbers, `<Text size={11} tone="secondary">` for labels
- R/R: `<Data size={12} tone="pass|caution|reject">` — use `statusForScore(alt.score)` for tone
- `reason`: `<Text size={11} tone="secondary">` — bottom row, italic-style via CSS (use `font-style: italic` in module)
- Background: `var(--bg-surface)`, border: `1px solid var(--border-subtle)`
- No card shadows (project rule)
- No Tailwind, no inline style objects

---

## 6. Changes to TradeCard organism

**File:** `frontend/components/organisms/TradeCard/index.tsx`

### 6a. Add collapsible Alternatives section

Below the existing contract-details block (the `contractDetails` section), add:

```tsx
{data.alternatives && data.alternatives.length > 0 && (
  <div className={styles.altSection}>
    <button
      type="button"
      className={styles.altToggle}
      onClick={() => setAltOpen((v) => !v)}
      aria-expanded={altOpen}
    >
      <Text size={11} tone="dim">ALTERNATIVES ({data.alternatives.length})</Text>
      <Text size={11} tone="dim">{altOpen ? '▲' : '▼'}</Text>
    </button>
    {altOpen && (
      <div className={styles.altList}>
        {data.alternatives.map((alt, i) => (
          <AlternativeContractRow key={alt.strike + alt.expiry} alt={alt} rank={i + 1} />
        ))}
      </div>
    )}
  </div>
)}
```

### 6b. useState for open/closed

Add `const [altOpen, setAltOpen] = useState(false);` alongside the existing state declarations.

### 6c. Import

```typescript
import { AlternativeContractRow } from '@/components/molecules/AlternativeContractRow';
```

### 6d. CSS additions (TradeCard.module.css)

```css
.altSection {
  margin-top: 12px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 8px;
}

.altToggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px 0;
  gap: 8px;
}

.altList {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
```

---

## 7. Changes to Step 6 contracts table

**File:** `frontend/app/(frame)/screener/step-6-contracts/page.tsx`

### Goal

Show a small `"N alt"` badge in the table header area (or next to the "Contracts" title) when the currently selected symbol's `TradeCardData` has `alternativesCount > 0`.

### How to get alternativesCount

```typescript
const candidates = useScanStore((s) => s.scanResult?.candidates ?? []);
const activeCandidateAlts = useMemo(
  () => candidates.find((c) => c.symbol === selectedSymbol)?.alternativesCount ?? 0,
  [candidates, selectedSymbol]
);
```

Add this after the existing `useScanStore` call.

### Where to render

In the page header, next to the title or the selected-symbol display, add:

```tsx
{activeCandidateAlts > 0 && (
  <span className={tbl.altBadge}>
    <Text size={11} tone="secondary">{activeCandidateAlts} alt{activeCandidateAlts > 1 ? 's' : ''}</Text>
  </span>
)}
```

### CSS addition (contracts.module.css)

```css
.altBadge {
  display: inline-flex;
  align-items: center;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-surface);
}
```

---

## 8. Conventions (must follow exactly)

- **CSS Modules only.** No Tailwind. No inline style objects except one-offs (e.g. `style={{ width: '40px' }}`).
- **Atoms → Molecules → Organisms.** `AlternativeContractRow` is a molecule — it may use atoms (`StatusBadge`, `Text`, `Data`) but not other molecules.
- **No new Zustand store changes.** All state is local `useState` or derived from existing `useScanStore`.
- **No hardcoded colours.** Every colour via `var(--token)` from `globals.css`.
- **No card shadows** — `border: 1px solid var(--border-subtle)` instead.
- Font weight 400 on any label-like text (project rule).
- `<Data>` for all numeric values (monospace, tabular-nums).
- `<Text>` for all label/prose content.

---

## 9. Typecheck gate

```bash
cd frontend
npm run typecheck    # must be zero errors before any commit
```

The `AlternativeContract` type is already in `frontend/types/domain.ts` — do not redefine it. Import it from there.

---

## 10. Mock data verification

The mocks in `frontend/mocks/tradecards.ts` already have `alternatives` populated for AAPL and NVDA (2 alternatives each). Use the existing Step 7 dev flow to verify:

1. `npm run dev` → `localhost:3001`
2. Run a screener workflow through Steps 1–6, arrive at Step 7.
3. Each candidate's TradeCard should show an "ALTERNATIVES (2)" toggle.
4. Clicking the toggle expands the list of two `AlternativeContractRow` components.
5. Step 6 table header should show "2 alts" badge.

If Step 7 is loading from the backend (`GET /api/tradecards`) and the backend doesn't have alternatives yet (WT-7a not yet merged), the `alternatives` field will be absent — the section simply won't render (guarded by `data.alternatives && data.alternatives.length > 0`). This is correct.

---

## 11. Acceptance criteria

- `npm run typecheck` → zero errors.
- Step 7 TradeCard: no crash when `alternatives` is `undefined` or `[]`.
- Step 7 TradeCard: "ALTERNATIVES (N)" toggle appears and is collapsed by default.
- Step 7 TradeCard: expanding the toggle shows N `AlternativeContractRow` cards, each with correct data from the mock.
- Step 6: "N alts" badge visible when the selected symbol's candidate has `alternativesCount > 0`.
- Step 6: no crash when `alternativesCount` is `0` or `undefined`.
- No new Tailwind classes, no hardcoded colours, no new global state.
