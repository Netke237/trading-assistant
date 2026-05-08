# LLM Context — Step 5 Scan Result Wiring (Workstream 29)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `frontend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream modifies one file only. It does not touch any backend file, any CSS file, any component, or any store file.

**Goal:**
Wire Step 5 (Volatility + Events) to consume real scan candidates from `scanStore.scanResult` when available, falling back to the existing `GET /api/watchlist` fixture. IV rank and event proximity continue to be computed on-the-fly from the candidate list — only the candidate source changes.

**What NOT to touch:**
- Any file under `backend/`
- Any `.css` file
- Any component file
- Any store file
- Any page other than `step-5-vol-events/page.tsx`
- `frontend/lib/api.ts` — read-only
- `frontend/lib/date.ts` — read-only
- `frontend/lib/status.ts` — read-only

---

## Section 2 — Owned files

| File path | Create / Modify | What changes |
|---|---|---|
| `frontend/app/(frame)/screener/step-5-vol-events/page.tsx` | **Modify** | Read candidates from `scanStore.scanResult`; fall back to `api.getWatchlist()` |

---

## Section 3 — Read-only references

| File | What to use |
|---|---|
| `frontend/lib/scanStore.ts` | `useScanStore` — reads `scanResult`, `context` |
| `frontend/types/domain.ts` | `WatchlistRow`, `TradeCardData` — shapes only |

**Relevant store fields:**

```ts
// useScanStore
scanResult: { scan_id: string; timestamp: string; candidates: TradeCardData[] } | null
context:    { universe: string; direction: 'Bullish' | 'Bearish'; horizon: string } | null
```

**Current Step 5 data-loading (read the file before modifying):**

```ts
// Current — line ~50
const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
useEffect(() => { api.getWatchlist().then(setWatchlist).catch(() => {}); }, []);
```

The rest of the page (IV rank hash, IV percentile hash, `ivStatus`, `eventProximity`, gate logic) is untouched — it all operates on `WatchlistRow[]` and will work correctly once the source of that array changes.

---

## Section 4 — Type mapping

Same mapping as WS-28. `TradeCardData` → `WatchlistRow`:

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
    // nextEventDays and nextEventLabel intentionally omitted:
    // Step 5 already guards `r.nextEventDays !== undefined` before calling
    // eventProximity(), so undefined is handled as 'distant' (no event concern).
  };
}
```

---

## Section 5 — Changes to `step-5-vol-events/page.tsx`

### 5.1 Add imports

After the existing `import { api } from '@/lib/api';` line, add:

```ts
import { useScanStore } from '@/lib/scanStore';
import type { TradeCardData } from '@/types/domain';
```

### 5.2 Add helper functions

Add these two pure functions inside the module, before the page component function. Place them near the existing `ivRankFor` / `ivStatus` helpers:

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

**Current:**
```ts
useEffect(() => { api.getWatchlist().then(setWatchlist).catch(() => {}); }, []);
```

**Replace with:**
```ts
useEffect(() => {
  if (scanResult?.candidates?.length) {
    const horizon = normalizeHorizon(context?.horizon ?? 'Swing');
    setWatchlist(scanResult.candidates.map((c) => cardToRow(c, horizon)));
    return;
  }
  api.getWatchlist().then(setWatchlist).catch(() => {});
}, [scanResult]);
```

No other changes. IV rank, IV percentile, event proximity, and gate logic all continue to operate on `WatchlistRow[]` without modification.

---

## Section 6 — Task spec

### Acceptance criteria

1. When `scanStore.scanResult` is null, Step 5 shows the mock watchlist as before.
2. When `scanStore.scanResult.candidates` has items, Step 5 shows those candidates with their computed IV rank and event gate.
3. `nextEventDays` being absent on scan candidates renders no event flag and sets proximity to `'distant'` — no crash.
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
3. Do NOT touch any store file.
4. Do NOT modify `ivRankFor`, `ivPctlFor`, `ivStatus`, or any of the existing Step 5 logic — only the `useEffect` that loads the candidate list changes.
5. Exact state variable name: `watchlist` / `setWatchlist`. Do not rename.
6. `npm run typecheck` must remain clean.
7. `TradeCardData` import must come from `'@/types/domain'`.

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
branching from feature/1-api-integration, branch name feature/ws-29-step5-scan-wiring.

Read `llm-contexts/29-step5-scan-wiring.md` fully before writing any code.
It is your single source of truth.

You are wiring Step 5 (Volatility + Events) to consume real scan results in the
Bamendjou options screener (Next.js 15 / TypeScript 5.7 / Zustand v5).

Your owned files:
  - frontend/app/(frame)/screener/step-5-vol-events/page.tsx  (MODIFY)

Read the file before modifying it. Do not touch any other file.
Run `npm run typecheck` from `frontend/` after all changes. Must be clean.
Commit after typecheck passes.
```
