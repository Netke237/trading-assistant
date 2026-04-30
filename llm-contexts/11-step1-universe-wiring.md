# LLM Context — Step 1 Universe Wiring (Workstream 11)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `frontend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates one new file and modifies one existing page file.
It does not touch any shared store interface, any CSS token, any type definition, or any other page.

**Goal:**
Step 1 currently holds all its selections in `useState` — the chosen universe (`pick`), custom symbols (`raw`), and four filter fields (`minPriceRaw`, `maxPriceRaw`, `minCapRaw`, `maxCapRaw`, `capUnit`). These are lost when the user navigates away (e.g. goes to Step 2 and returns). The fix is to lift this local state into a new `universeStore.ts` (Zustand, **no** `persist` middleware — scan state is ephemeral).

Additionally, the "My Watchlist" universe card currently shows a hardcoded count of `10`. It must instead read the live count from `useWatchlistStore((s) => s.added.length)`.

**What NOT to touch:**
- `frontend/lib/scanStore.ts` — do NOT call `setContext()` from Step 1; that is Step 2's responsibility
- `frontend/lib/watchlistStore.ts` — read-only (read `added.length` only)
- `frontend/app/(frame)/screener/step-1-universe/page.module.css` — read-only; the UI layout is correct
- Any other page, store, component, or type file not listed in Section 2

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `frontend/lib/universeStore.ts` | **Create** | New Zustand store holding universe selection and filter state |
| `frontend/app/(frame)/screener/step-1-universe/page.tsx` | **Modify** | Replace all `useState` calls with `useUniverseStore` reads/writes; make "My Watchlist" count dynamic |

---

## Section 3 — Read-only references

| File | Reason |
|---|---|
| `frontend/lib/watchlistStore.ts` | Read `useWatchlistStore((s) => s.added.length)` for the Watchlist card count |
| `frontend/lib/scanStore.ts` | Understand `ScanContext` shape — do NOT import or call from Step 1 |
| `frontend/app/(frame)/screener/step-1-universe/page.module.css` | Verify CSS class names used in page.tsx |
| `frontend/app/(frame)/screener/screener.module.css` | Shared step layout classes (`.main`, `.stepHeader`, `.stepBody`) |

---

## Section 4 — Integration constraints

### watchlistStore import (read-only)
```ts
import { useWatchlistStore } from '@/lib/watchlistStore';

// Inside Step1Page:
const watchlistCount = useWatchlistStore((s) => s.added.length);
```
Use this value for the "My Watchlist" card's count — replace the hardcoded `10`.

### universeStore interface (what you must create)
```ts
// frontend/lib/universeStore.ts
import { create } from 'zustand';

type Universe = 'SP500' | 'NDX100' | 'DOW30' | 'RUSSELL2000' | 'STOXX600' | 'DAX40' | 'Watchlist' | 'Custom';
type CapUnit  = 'M' | 'B';

interface UniverseState {
  pick:        Universe;
  customRaw:   string;
  minPriceRaw: string;
  maxPriceRaw: string;
  minCapRaw:   string;
  maxCapRaw:   string;
  capUnit:     CapUnit;
  setPick:        (v: Universe) => void;
  setCustomRaw:   (v: string)   => void;
  setMinPriceRaw: (v: string)   => void;
  setMaxPriceRaw: (v: string)   => void;
  setMinCapRaw:   (v: string)   => void;
  setMaxCapRaw:   (v: string)   => void;
  setCapUnit:     (v: CapUnit)  => void;
  clearFilters:   ()            => void;
}

export const useUniverseStore = create<UniverseState>((set) => ({
  pick:        'SP500',
  customRaw:   '',
  minPriceRaw: '',
  maxPriceRaw: '',
  minCapRaw:   '',
  maxCapRaw:   '',
  capUnit:     'B',
  setPick:        (v) => set({ pick: v }),
  setCustomRaw:   (v) => set({ customRaw: v }),
  setMinPriceRaw: (v) => set({ minPriceRaw: v }),
  setMaxPriceRaw: (v) => set({ maxPriceRaw: v }),
  setMinCapRaw:   (v) => set({ minCapRaw: v }),
  setMaxCapRaw:   (v) => set({ maxCapRaw: v }),
  setCapUnit:     (v) => set({ capUnit: v }),
  clearFilters:   ()  => set({ minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '' }),
}));
```

**No `persist` middleware.** Universe selection is ephemeral within a scan session.

### page.tsx wiring pattern
```ts
// Replace the 6 useState calls with:
const {
  pick, customRaw, minPriceRaw, maxPriceRaw, minCapRaw, maxCapRaw, capUnit,
  setPick, setCustomRaw, setMinPriceRaw, setMaxPriceRaw, setMinCapRaw, setMaxCapRaw,
  setCapUnit, clearFilters,
} = useUniverseStore();

// Replace all existing local setters inline. Example:
// was: const [pick, setPick] = useState<Universe>('SP500');
// now: pick and setPick come from the store above.

// Dynamic watchlist count:
const watchlistCount = useWatchlistStore((s) => s.added.length);
```

The `OPTIONS` array entry for `Watchlist` must become:
```ts
{ key: 'Watchlist', label: 'My Watchlist', count: watchlistCount, desc: 'Only symbols on your personal watchlist.' },
```
Since `watchlistCount` is a number, the existing render logic (`typeof o.count === 'number' ? \`${o.count} symbols\` : o.count`) handles it correctly — no template changes needed.

---

## Section 5 — CSS tokens (full list)

```css
/* Dark theme (default) */
--bg-base:          #131722;
--bg-surface:       #1E2335;
--bg-surface-2:     #252B43;
--bg-surface-3:     #2A3152;
--border-subtle:    #2A2E42;
--border-strong:    #363B54;
--text-primary:     #D1D4DC;
--text-secondary:   #787B86;
--text-dim:         #434651;
--pass:             #26A69A;
--pass-bg:          #0D201F;
--pass-border:      #1A3533;
--caution:          #F59F00;
--caution-bg:       #1F1A0D;
--caution-border:   #352E1A;
--reject:           #EF5350;
--reject-bg:        #1F0E0D;
--reject-border:    #352020;
--neutral:          #4A5568;
--neutral-bg:       #1A202C;
--accent:           #2962FF;
--accent-hover:     #1E53E5;
--accent-dim:       #142B7A;
--accent-text:      #FFFFFF;
--space-1:  4px;  --space-2:  8px;  --space-3:  12px; --space-4:  16px;
--space-5:  20px; --space-6:  24px; --space-8:  32px; --space-12: 48px;
--radius-sm: 4px; --radius-md: 6px; --radius-lg: 10px;
--frame-topbar-h:           48px;
--frame-navrail-w:          64px;
--frame-navrail-w-expanded: 200px;
--frame-contextrail-w:      300px;
--frame-stepnav-h:          52px;
```

---

## Section 6 — Primitives & component reference

```tsx
<Text  size={11|12|13|14} tone="primary|secondary|dim|pass|caution|reject" weight={400|500|600} />
<Title as="h1|h2|h3" size={18|20|24} />
<Data  size={11..24} weight={500|600} tone="pass|caution|reject" />  // monospace, tabular-nums
```

This workstream uses only `Text` and `Data` primitives (already imported in page.tsx).

---

## Section 7 — Domain types (relevant subset)

```ts
// types/domain.ts
type Direction = 'Bullish' | 'Bearish';
```

The `Universe` and `CapUnit` types are defined locally in `step-1-universe/page.tsx` and must also be defined in `universeStore.ts`. Keep them identical:

```ts
type Universe = 'SP500' | 'NDX100' | 'DOW30' | 'RUSSELL2000' | 'STOXX600' | 'DAX40' | 'Watchlist' | 'Custom';
type CapUnit  = 'M' | 'B';
```

---

## Section 8 — Zustand stores (relevant stores only)

### `watchlistStore.ts` (read-only)
```ts
interface WatchlistState {
  added: string[];           // all watched symbols, uppercased; seeded with 10 symbols
  addSymbol:    (sym: string) => void;
  removeSymbol: (sym: string) => void;
  isWatched:    (sym: string) => boolean;
}
// Storage key: 'bamendjou:watchlist'
// Persisted to localStorage with version: 1
// Default seed: ['AAPL', 'NVDA', 'MSFT', 'META', 'GOOGL', 'AMZN', 'AMD', 'TSLA', 'NFLX', 'INTC']
```
**Only read** `added.length` from this store. Do not call any setter.

### `universeStore.ts` (create — see Section 4)
No `persist` middleware. Default `pick: 'SP500'`, all filter strings empty, `capUnit: 'B'`.

---

## Section 9 — Mock data (exact values)

The OPTIONS array in page.tsx must remain exactly as-is, except the `Watchlist` entry's `count` becomes dynamic:

```ts
const OPTIONS = [
  { key: 'SP500',       label: 'S&P 500',      count: 503,             desc: 'Large-cap US equities. Recommended for most users.' },
  { key: 'NDX100',      label: 'Nasdaq-100',   count: 100,             desc: 'Tech-heavy large caps. Higher vol, higher signal.' },
  { key: 'DOW30',       label: 'Dow 30',       count: 30,              desc: 'Blue-chip US industrials. Narrow but liquid.' },
  { key: 'RUSSELL2000', label: 'Russell 2000', count: 2000,            desc: 'US small caps. Broader breadth, thinner liquidity.' },
  { key: 'STOXX600',    label: 'STOXX 600',    count: 600,             desc: 'European large/mid caps.' },
  { key: 'DAX40',       label: 'DAX 40',       count: 40,              desc: 'German blue chips. Liquid European single-stock options.' },
  { key: 'Watchlist',   label: 'My Watchlist', count: watchlistCount,  desc: 'Only symbols on your personal watchlist.' },
  { key: 'Custom',      label: 'Custom list',  count: '—',             desc: 'Paste or type your own tickers (stocks / ETFs).' },
];
```

`watchlistCount` is `useWatchlistStore((s) => s.added.length)`. The render template already handles both `number` and `string` counts — no JSX changes needed for this entry.

---

## Section 10 — Task spec

### Acceptance criteria

1. Selecting a universe in Step 1, navigating to Step 2, then pressing Back returns to Step 1 with the same universe card still highlighted.
2. Typing filter values in Step 1, navigating away, and returning shows the same filter values.
3. The "My Watchlist" card shows `added.length` (default: 10 from seed), not a hardcoded `10`.
4. The "Clear filters" button works (calls `clearFilters()` from the store).
5. The Custom symbols textarea persists across navigation.
6. All visual behaviour, validation logic (`priceInvalid`, `capInvalid`), and layout is identical to before.
7. `npm run typecheck` is clean.

### What changes in page.tsx

**Remove** these 6 `useState` declarations:
```ts
const [pick, setPick] = useState<Universe>('SP500');
const [raw, setRaw]   = useState('');
const [minPriceRaw, setMinPriceRaw] = useState<string>('');
const [maxPriceRaw, setMaxPriceRaw] = useState<string>('');
const [minCapRaw,   setMinCapRaw]   = useState<string>('');
const [maxCapRaw,   setMaxCapRaw]   = useState<string>('');
const [capUnit,     setCapUnit]     = useState<CapUnit>('B');
```

**Replace** with a single destructured `useUniverseStore()` call (see Section 4).

**Add** `useWatchlistStore` import + `watchlistCount` selector.

**Update** the `OPTIONS` array `Watchlist` entry: `count: watchlistCount`.

**Remove** the local `clearFilters` function — use the store action instead.

**Keep** unchanged:
- All helper functions (`parseSymbols`, `parseNumOrNull`, `fmtPrice`, `fmtCap`, `rangeSummary`)
- All derived values (`symbols`, `isCustom`, `minPrice`, `maxPrice`, `minCap`, `maxCap`, `priceInvalid`, `capInvalid`, `priceSummary`, `capSummary`, `hasFilters`)
- The entire JSX return — no template changes needed

---

## Section 11 — Hard rules

1. No Tailwind, styled-components, or CSS-in-JS.
2. No `style={{}}` except computed one-off values.
3. No hardcoded colors — always use CSS custom properties.
4. No invented Status labels — only `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. No font-weight 600 on form labels — use `weight={400}`.
6. No card box-shadows — use `border: 1px solid var(--border-subtle)`.
7. Never skip component hierarchy: atom → molecule → organism.
8. `npm run typecheck` must be clean before every commit.
9. Do not touch `node_modules/` or `package-lock.json`.
10. **Workstream-specific**: Do not add `persist` middleware to `universeStore` — scan state is ephemeral.
11. **Workstream-specific**: Do not call `scanStore.setContext()` from Step 1 — that is Step 2's job.
12. **Workstream-specific**: Do not modify `watchlistStore.ts` or `scanStore.ts`.

---

## Section 12 — Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001
npm run typecheck    # must be clean after every edit
```

After editing, navigate to Step 1, select a universe, type a filter value, navigate to Step 2 via the StepNavBar "Next" button, then press "Back" — the Step 1 selections must be intact.

---

## Section 13 — Copy/paste prompt

```
Read `llm-contexts/11-step1-universe-wiring.md` fully before writing any code.
It is your single source of truth.

You are implementing the Step 1 universe wiring for the Bamendjou options screener
(Next.js 15, TypeScript strict, CSS Modules).

Your owned files:
  - frontend/lib/universeStore.ts          (CREATE)
  - frontend/app/(frame)/screener/step-1-universe/page.tsx  (MODIFY)

Do not modify any file outside this list.

Task: Lift Step 1's local useState into a new Zustand store (universeStore.ts)
so universe/filter selections survive step navigation. Also make the
"My Watchlist" card count dynamic (read from watchlistStore.added.length).

After every file edit, run `npm run typecheck` from `frontend/`. Must stay clean.
Commit after all changes are complete.
```
