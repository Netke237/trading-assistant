# LLM Context — Trade Card Completeness (Workstream 26)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `frontend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream modifies three frontend files. It does not touch any `.css` file, any component file, the backend, or any store other than `scanStore.ts`.

**Goal:**
Wire Step 7 (Trade Card) to consume real scan results from `POST /api/scan` when available, falling back to the existing `GET /api/tradecards` fixture. Also add `postScan()` to the API client and add `scanResult` state to `scanStore`.

WS-27 (RunScanButton) will later call `postScan()` and redirect to Step 4. WS-26 only adds the method and wires Step 7 — it does not touch the RunScanButton.

**What NOT to touch:**
- Any `.css` file
- Any component file (TradeCard, CandidateNav, etc.) — the TradeCard already displays all fields
- `backend/` — no backend changes
- Any store other than `frontend/lib/scanStore.ts`
- Any page other than `step-7-trade-card/page.tsx`

---

## Section 2 — Owned files

| File path | Create / Modify | What changes |
|---|---|---|
| `frontend/lib/api.ts` | **Modify** | Add `postScan()` method |
| `frontend/lib/scanStore.ts` | **Modify** | Add `scanResult` state + `setScanResult` |
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` | **Modify** | Read candidates from `scanStore.scanResult` when available |

---

## Section 3 — Read-only references

| File | Reason |
|---|---|
| `frontend/types/domain.ts` | `TradeCardData` shape — do not modify |
| `frontend/mocks/tradecards.ts` | Fallback data source — do not modify |

**Current `TradeCardData` in `frontend/types/domain.ts`:**
```ts
export interface TradeCardData {
  symbol:        string;
  company:       string;
  price:         number;
  direction:     Direction;
  status:        Status;
  stockScore:    number;
  stockConfidence: Status;
  stockBreakdown:  ScoreBreakdown;
  contract:      string;
  contractScore: number;
  contractConfidence: Status;
  contractBreakdown: ContractScoreBreakdown;
  contractDetails?: {
    strike: number; expiry: string; right: 'C' | 'P';
    mid: number; delta: number; theta: number; ivRank: number; dte: number;
  };
  entry:  { limit: number; maxFill: number; orderType: OrderType };
  exit:   { invalidation: number; premiumStop: number; timeStopDays: number; target: number };
  rrRatio:  number;
  rrModel:  'Heston repriced' | 'Delta approximation';
  finalStatus: Status;
}
```

---

## Section 4 — Changes

### 4.1 `frontend/lib/api.ts` — add `postScan`

Add a `post` helper and the `postScan` method.

Current file ends with:
```ts
export const api = {
  getWatchlist:  () => get<WatchlistRow[]>('/api/watchlist'),
  ...
  getCandles:    (symbol: string) => get<Candle[]>(`/api/candles/${encodeURIComponent(symbol)}`),
};
```

**Changes:**

1. Add a new type import at the top. After the existing import line, add:
```ts
// No new import needed — ScanResult uses existing TradeCardData
```

2. Add a `post` helper after `get`:
```ts
async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}
```

3. Add `postScan` to the `api` object:
```ts
postScan: (universe: string[], direction: string, horizon: string) =>
  post<{ scan_id: string; timestamp: string; candidates: TradeCardData[]; rejected: { symbol: string; reason: string }[] }>(
    '/api/scan',
    { universe, direction, horizon, overrides: {} },
  ),
```

---

### 4.2 `frontend/lib/scanStore.ts` — add `scanResult`

Current state interface ends at `setRegime`. Extend it:

**Add to `interface ScanStoreState`:**
```ts
  scanResult: { scan_id: string; timestamp: string; candidates: TradeCardData[] } | null;
  setScanResult: (r: { scan_id: string; timestamp: string; candidates: TradeCardData[] } | null) => void;
```

**Add to the `create` initializer:**
```ts
  scanResult: null,
  setScanResult: (r) => set({ scanResult: r }),
```

**Add import** at the top of `scanStore.ts` (after existing imports):
```ts
import type { TradeCardData } from '@/types/domain';
```

---

### 4.3 `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` — use scan result

The current page fetches candidates from `api.getTradecards()`. After this change it should:
- If `scanStore.scanResult?.candidates` has items → use those
- Otherwise → fall back to `api.getTradecards()`

**Read the existing page first** to understand its current data-loading pattern (it calls `api.getTradecards()` in a `useEffect`).

**Changes:**

1. Add import for `useScanStore`:
```ts
import { useScanStore } from '@/lib/scanStore';
```

2. In the component, read scan result from store:
```ts
const scanResult = useScanStore((s) => s.scanResult);
```

3. In the `useEffect` that loads tradecards, prefer scan result:
```ts
useEffect(() => {
  if (scanResult?.candidates?.length) {
    setCards(scanResult.candidates);
    return;
  }
  api.getTradecards().then(setCards).catch(() => {});
}, [scanResult]);
```

The `setCards` state setter already exists (it's the current setter for the candidates array — check the exact variable name in the file and use that instead of `setCards` if different).

---

## Section 5 — Type compatibility note

The backend `TradeCardData` schema (Pydantic) and the frontend `TradeCardData` type (TypeScript) must match field-for-field. They already do — both were designed together. The only risk is camelCase vs snake_case. The backend Pydantic model already uses camelCase field names (`stockScore`, `rrRatio`, etc.) via `model_config = ConfigDict(populate_by_name=True)`, so no transformation needed on the frontend.

---

## Section 6 — Task spec

### Acceptance criteria

1. `api.postScan(["AAPL"], "Bullish", "Swing")` is a valid call (TypeScript does not error).
2. `useScanStore.getState().setScanResult(...)` accepts a valid `ScanResult`-shaped object.
3. Step 7 page reads from `scanStore.scanResult.candidates` when non-empty, from `api.getTradecards()` when null/empty.
4. `npm run typecheck` is clean (0 errors).

### Verify

```bash
cd frontend
npm run typecheck
# Expected: 0 errors
```

---

## Section 7 — Hard rules

1. Do NOT touch any `.css` file.
2. Do NOT touch any component file.
3. Do NOT touch the backend.
4. `npm run typecheck` must remain clean.
5. Do NOT add `async`/`await` to the `postScan` export — it returns a Promise that the caller handles.
6. If the exact state variable name in `step-7-trade-card/page.tsx` differs from `setCards`, use whatever name is there — do not rename it.

---

## Section 8 — Dev workflow

```bash
cd frontend
npm run typecheck  # must be clean
```

---

## Section 9 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-26-trade-card.

Read `llm-contexts/26-trade-card-completeness.md` fully before writing any code.
It is your single source of truth.

You are wiring the Step 7 trade card page to consume real scan results in the
Bamendjou options screener (Next.js 15 / TypeScript 5.7 / Zustand v5).

Your owned files:
  - frontend/lib/api.ts                                       (MODIFY)
  - frontend/lib/scanStore.ts                                 (MODIFY)
  - frontend/app/(frame)/screener/step-7-trade-card/page.tsx  (MODIFY)

Read each file before modifying it.
Do not touch any other file.
Run `npm run typecheck` from `frontend/` after all changes. Must be clean.
Commit after typecheck passes.
```
