# LLM Context — Step 4 Scan Result Wiring (Workstream 28)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `frontend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream modifies one file only. It does not touch any backend file, any CSS file, any component, or any store file.

**Goal:**
Wire Step 4 (Stock Ranking) to consume real scan candidates from `scanStore.scanResult` when available, falling back to the existing `GET /api/watchlist` fixture. After a scan completes and the user lands on Step 4, the ranking table should show the scan candidates — not mock data.

**What NOT to touch:**
- Any file under `backend/`
- Any `.css` file
- Any component file
- Any store file
- Any page other than `step-4-ranking/page.tsx`
- `frontend/lib/api.ts` — read-only

---

## Section 2 — Owned files

| File path | Create / Modify | What changes |
|---|---|---|
| `frontend/app/(frame)/screener/step-4-ranking/page.tsx` | **Modify** | Read candidates from `scanStore.scanResult`; fall back to `api.getWatchlist()` |

---

## Section 3 — Read-only references

| File | What to use |
|---|---|
| `frontend/lib/scanStore.ts` | `useScanStore` — reads `scanResult`, `context` |
| `frontend/types/domain.ts` | `WatchlistRow`, `TradeCardData`, `ScoreBreakdown` — shapes only |

**Relevant store fields (do not import types from stores):**

```ts
// useScanStore
scanResult: { scan_id: string; timestamp: string; candidates: TradeCardData[] } | null
context:    { universe: string; direction: 'Bullish' | 'Bearish'; horizon: string } | null
```

**Current Step 4 data-loading (read before modifying):**

The page currently loads data with two `useEffect` calls:

```ts
// Line ~116 — loads the ranking table
useEffect(() => { api.getWatchlist().then(setWatchlist).catch(() => {}); }, []);

// Line ~125 — loads candles for the selected symbol (do NOT change this one)
useEffect(() => {
  if (!selected) return;
  api.getCandles(selected.symbol).then(setCandles).catch(() => {});
}, [selected?.symbol]);
```

State variables (exact names from the file — use these, do not rename):

```ts
const [watchlist, setWatchlist]       = useState<WatchlistRow[]>([]);
const [selectedSym, setSelectedSym]   = useState<string>('AAPL');
```

`selected` is derived (not state):
```ts
const selected = sorted.find((r) => r.symbol === selectedSym) ?? sorted[0];
```

---

## Section 4 — Type mapping

`TradeCardData` must be converted to `WatchlistRow` before it can populate the ranking table. The shapes are compatible — only the field names differ.

### `WatchlistRow` shape (from `frontend/types/domain.ts`)

```ts
interface WatchlistRow {
  symbol:       string;
  company:      string;
  price:        number;
  direction:    Direction;        // 'Bullish' | 'Bearish'
  horizon:      Horizon;          // 'Swing' | 'Position'
  score:        number;
  rankDelta:    number;
  scoreDelta?:  number;
  status:       Status;
  breakdown:    ScoreBreakdown;   // { trend, pullback, trigger, event, volatility }
  nextEventDays?:  number;
  nextEventLabel?: string;
}
```

### Mapping from `TradeCardData`

```ts
function cardToRow(c: TradeCardData, horizon: 'Swing' | 'Position'): WatchlistRow {
  return {
    symbol:    c.symbol,
    company:   c.company,
    price:     c.price,
    direction: c.direction,
    horizon,
    score:     c.stockScore,
    rankDelta: 0,
    status:    c.status,
    breakdown: c.stockBreakdown,
  };
}
```

`rankDelta` is 0 because a fresh scan has no previous rank to compare against.
Optional fields (`scoreDelta`, `nextEventDays`, `nextEventLabel`) are omitted — they default to `undefined`.

### Horizon normalisation

`scanStore.context.horizon` is a human label like `"Swing (5–15d)"` or `"Position (15–45d)"`. `WatchlistRow.horizon` only accepts `'Swing' | 'Position'`:

```ts
function normalizeHorizon(h: string): 'Swing' | 'Position' {
  return h.startsWith('Position') ? 'Position' : 'Swing';
}
```

---

## Section 5 — Changes to `step-4-ranking/page.tsx`

### 5.1 Add imports

After the existing `import { api } from '@/lib/api';` line, add:

```ts
import { useScanStore } from '@/lib/scanStore';
import type { TradeCardData } from '@/types/domain';
```

### 5.2 Add helper functions

Add these two pure functions inside the module, before the page component function. Place them near the existing `signalFor` / `signalLabel` helpers:

```ts
function normalizeHorizon(h: string): 'Swing' | 'Position' {
  return h.startsWith('Position') ? 'Position' : 'Swing';
}

function cardToRow(c: TradeCardData, horizon: 'Swing' | 'Position'): WatchlistRow {
  return {
    symbol:    c.symbol,
    company:   c.company,
    price:     c.price,
    direction: c.direction,
    horizon,
    score:     c.stockScore,
    rankDelta: 0,
    status:    c.status,
    breakdown: c.stockBreakdown,
  };
}
```

### 5.3 Read scan state in the component

Inside the page component, after the existing `useState` declarations, add:

```ts
const scanResult = useScanStore((s) => s.scanResult);
const context    = useScanStore((s) => s.context);
```

### 5.4 Replace the watchlist `useEffect`

**Current** (line ~116):
```ts
useEffect(() => { api.getWatchlist().then(setWatchlist).catch(() => {}); }, []);
```

**Replace with:**
```ts
useEffect(() => {
  if (scanResult?.candidates?.length) {
    const horizon = normalizeHorizon(context?.horizon ?? 'Swing');
    const rows = scanResult.candidates.map((c) => cardToRow(c, horizon));
    setWatchlist(rows);
    if (rows[0]) setSelectedSym(rows[0].symbol);
    return;
  }
  api.getWatchlist().then((data) => {
    setWatchlist(data);
    if (data[0]) setSelectedSym(data[0].symbol);
  }).catch(() => {});
}, [scanResult]);
```

Do **not** change the candles `useEffect` — it already reacts to `selected?.symbol` and will update automatically.

---

## Section 6 — Task spec

### Acceptance criteria

1. When `scanStore.scanResult` is null (no scan run yet), Step 4 shows the mock watchlist as before.
2. When `scanStore.scanResult.candidates` has items, Step 4 shows those candidates ranked by score.
3. The first candidate is auto-selected (right panel shows its chart and breakdown).
4. `npm run typecheck` is clean (0 errors).

### Verify

```bash
cd frontend
npm run typecheck
# Expected: 0 errors
```

Manual smoke test (requires WS-27 RunScanButton and backend on port 8000):
1. Complete Steps 1 and 2.
2. Click "Run Scan".
3. App navigates to Step 4 — ranking table shows scan candidates, not mock data.
4. Click a different row — right panel updates to that symbol's chart and breakdown.

---

## Section 7 — Hard rules

1. Do NOT touch any `.css` file.
2. Do NOT touch any component file.
3. Do NOT touch any store file.
4. Do NOT touch the candles `useEffect` — only the watchlist `useEffect` changes.
5. Exact state variable names from the file: `watchlist`, `setWatchlist`, `selectedSym`, `setSelectedSym`. Do not rename them.
6. `npm run typecheck` must remain clean.
7. `TradeCardData` import must come from `'@/types/domain'` — not from a store or backend schema file.

---

## Section 8 — Dev workflow

```bash
cd frontend
npm run typecheck
```

---

## Section 9 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-28-step4-scan-wiring.

Read `llm-contexts/28-step4-scan-wiring.md` fully before writing any code.
It is your single source of truth.

You are wiring Step 4 (Stock Ranking) to consume real scan results in the
Bamendjou options screener (Next.js 15 / TypeScript 5.7 / Zustand v5).

Your owned files:
  - frontend/app/(frame)/screener/step-4-ranking/page.tsx  (MODIFY)

Read the file before modifying it. Do not touch any other file.
Run `npm run typecheck` from `frontend/` after all changes. Must be clean.
Commit after typecheck passes.
```
