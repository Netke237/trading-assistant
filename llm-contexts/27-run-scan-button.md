# LLM Context — Run Scan Button (Workstream 27)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `frontend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates two new files and modifies one existing file. It does not touch any backend file, any existing component outside `TopBarActions`, any store other than reading from three existing ones, or any step page.

**Goal:**
Add a "Run Scan" button to the TopBar that calls `POST /api/scan`, shows a loading state, stores the result in `scanStore`, and navigates to Step 4 on success.

**What NOT to touch:**
- Any file under `backend/`
- Any `.css` file other than the new `RunScanButton.module.css` you create
- Any component other than `TopBarActions/index.tsx`
- Any Zustand store file — read from them, do not modify them
- Any step page
- `frontend/lib/api.ts` — read-only
- `frontend/lib/scanStore.ts` — read-only
- `frontend/lib/universeStore.ts` — read-only
- `frontend/lib/watchlistStore.ts` — read-only

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `frontend/components/molecules/RunScanButton/index.tsx` | **Create** | Button component — calls postScan, drives scan state |
| `frontend/components/molecules/RunScanButton/RunScanButton.module.css` | **Create** | Button styles |
| `frontend/components/molecules/TopBarActions/index.tsx` | **Modify** | Add RunScanButton next to ModeToggle |

---

## Section 3 — Read-only references

| File | What to use |
|---|---|
| `frontend/lib/api.ts` | `api.postScan(universe, direction, horizon)` |
| `frontend/lib/scanStore.ts` | `useScanStore` — reads `scanState`, `context`; calls `setScanState`, `setScanResult` |
| `frontend/lib/universeStore.ts` | `useUniverseStore` — reads `pick`, `customRaw` |
| `frontend/lib/watchlistStore.ts` | `useWatchlistStore` — reads `added` (string[]) |
| `frontend/components/atoms/ModeToggle/index.tsx` | Reference only — do not modify |
| `frontend/components/molecules/TopBarActions/TopBarActions.module.css` | Reference only — do not modify |

**Current `TopBarActions/index.tsx`** (full file — replace it):
```tsx
import { ModeToggle } from '@/components/atoms/ModeToggle';
import styles from './TopBarActions.module.css';

export function TopBarActions() {
  return (
    <div className={styles.root}>
      <ModeToggle />
    </div>
  );
}
```

**Relevant store shapes (do not import types from stores — derive from usage):**

```ts
// useScanStore — from frontend/lib/scanStore.ts
scanState:    'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED'
context:      { universe: string; direction: 'Bullish' | 'Bearish'; horizon: string } | null
setScanState: (s: ScanState, at?: string) => void
setScanResult:(r: { scan_id: string; timestamp: string; candidates: TradeCardData[] } | null) => void

// useUniverseStore — from frontend/lib/universeStore.ts
pick:      'SP500' | 'NDX100' | 'DOW30' | 'RUSSELL2000' | 'STOXX600' | 'DAX40' | 'Watchlist' | 'Custom'
customRaw: string   // raw textarea — parse to symbols when pick === 'Custom'

// useWatchlistStore — from frontend/lib/watchlistStore.ts
added: string[]    // symbol list — use directly when pick === 'Watchlist'
```

**`api.postScan` signature:**
```ts
api.postScan(
  universe:  string[],   // list of ticker symbols
  direction: string,     // 'Bullish' | 'Bearish'
  horizon:   string,     // 'Swing' | 'Position'
) => Promise<{ scan_id: string; timestamp: string; candidates: TradeCardData[]; rejected: { symbol: string; reason: string }[] }>
```

---

## Section 4 — Implementation

### 4.1 Symbol resolution

The universe store holds a preset label, not a symbol list. Resolve it with this static map before calling `postScan`:

```ts
const UNIVERSE_SYMBOLS: Record<string, string[]> = {
  SP500:       ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'JPM'],
  NDX100:      ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AVGO'],
  DOW30:       ['AAPL', 'MSFT', 'JPM', 'GS', 'UNH', 'HD', 'V', 'AXP'],
  RUSSELL2000: ['SMCI', 'MARA', 'RIOT', 'CLSK', 'SOUN', 'AI', 'RKLB', 'LUNR'],
  STOXX600:    ['ASML', 'SAP', 'NESN', 'NOVO', 'MC', 'SIE', 'LVMH', 'AZN'],
  DAX40:       ['SAP', 'SIE', 'BAYN', 'BMW', 'DTE', 'MBG', 'ADS', 'DBK'],
};

/** Parse raw text → unique uppercased tickers. */
function parseSymbols(raw: string): string[] {
  return Array.from(new Set(
    raw.split(/[\s,;\n]+/)
      .map((s) => s.trim().toUpperCase())
      .filter((s) => /^[A-Z][A-Z0-9.\-]{0,5}$/.test(s)),
  ));
}

function resolveSymbols(
  pick: string,
  customRaw: string,
  watchlist: string[],
): string[] {
  if (pick === 'Custom')     return parseSymbols(customRaw);
  if (pick === 'Watchlist')  return watchlist.slice(0, 20);
  return UNIVERSE_SYMBOLS[pick] ?? UNIVERSE_SYMBOLS['SP500']!;
}
```

### 4.2 Horizon normalisation

`scanStore.context.horizon` is a human label like `"Swing (5–15d)"` or `"Position (15–45d)"`. The backend only accepts `"Swing"` or `"Position"`. Normalise with:

```ts
function normalizeHorizon(h: string): 'Swing' | 'Position' {
  return h.startsWith('Position') ? 'Position' : 'Swing';
}
```

### 4.3 Local ISO timestamp helper

`setScanState('COMPLETED', at)` expects a local-timezone ISO-ish string so the TopBar can display "HH:mm". Use:

```ts
function nowISOLocal(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
```

### 4.4 Full `RunScanButton/index.tsx`

```tsx
'use client';

import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import styles from './RunScanButton.module.css';

const UNIVERSE_SYMBOLS: Record<string, string[]> = {
  SP500:       ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'JPM'],
  NDX100:      ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AVGO'],
  DOW30:       ['AAPL', 'MSFT', 'JPM', 'GS', 'UNH', 'HD', 'V', 'AXP'],
  RUSSELL2000: ['SMCI', 'MARA', 'RIOT', 'CLSK', 'SOUN', 'AI', 'RKLB', 'LUNR'],
  STOXX600:    ['ASML', 'SAP', 'NESN', 'NOVO', 'MC', 'SIE', 'LVMH', 'AZN'],
  DAX40:       ['SAP', 'SIE', 'BAYN', 'BMW', 'DTE', 'MBG', 'ADS', 'DBK'],
};

function parseSymbols(raw: string): string[] {
  return Array.from(new Set(
    raw.split(/[\s,;\n]+/)
      .map((s) => s.trim().toUpperCase())
      .filter((s) => /^[A-Z][A-Z0-9.\-]{0,5}$/.test(s)),
  ));
}

function resolveSymbols(pick: string, customRaw: string, watchlist: string[]): string[] {
  if (pick === 'Custom')    return parseSymbols(customRaw);
  if (pick === 'Watchlist') return watchlist.slice(0, 20);
  return UNIVERSE_SYMBOLS[pick] ?? UNIVERSE_SYMBOLS['SP500']!;
}

function normalizeHorizon(h: string): 'Swing' | 'Position' {
  return h.startsWith('Position') ? 'Position' : 'Swing';
}

function nowISOLocal(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function RunScanButton() {
  const router       = useRouter();
  const scanState    = useScanStore((s) => s.scanState);
  const context      = useScanStore((s) => s.context);
  const setScanState = useScanStore((s) => s.setScanState);
  const setScanResult = useScanStore((s) => s.setScanResult);

  const pick       = useUniverseStore((s) => s.pick);
  const customRaw  = useUniverseStore((s) => s.customRaw);
  const watchlist  = useWatchlistStore((s) => s.added);

  const symbols  = resolveSymbols(pick, customRaw, watchlist);
  const scanning = scanState === 'SCANNING';
  const disabled = scanning || !context || symbols.length === 0;

  async function handleClick() {
    if (!context || symbols.length === 0) return;
    setScanState('SCANNING');
    try {
      const result = await api.postScan(symbols, context.direction, normalizeHorizon(context.horizon));
      setScanResult({ scan_id: result.scan_id, timestamp: result.timestamp, candidates: result.candidates });
      setScanState('COMPLETED', nowISOLocal());
      router.push('/screener/step-4-ranking');
    } catch {
      setScanState('FAILED');
    }
  }

  return (
    <button
      type="button"
      className={`${styles.btn}${scanning ? ` ${styles.scanning}` : ''}`}
      disabled={disabled}
      onClick={handleClick}
    >
      {scanning ? 'Scanning…' : 'Run Scan'}
    </button>
  );
}
```

### 4.5 Full `RunScanButton.module.css`

```css
.btn {
  padding: 0 var(--space-3);
  height: 28px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: var(--bg-base);
  font-family: var(--font-dm);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.01em;
  cursor: pointer;
  white-space: nowrap;
  transition: opacity 120ms ease;
}

.btn:hover:not(:disabled) {
  opacity: 0.85;
}

.btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.btn.scanning {
  background: transparent;
  color: var(--accent);
}
```

### 4.6 Modified `TopBarActions/index.tsx`

```tsx
import { ModeToggle } from '@/components/atoms/ModeToggle';
import { RunScanButton } from '@/components/molecules/RunScanButton';
import styles from './TopBarActions.module.css';

export function TopBarActions() {
  return (
    <div className={styles.root}>
      <RunScanButton />
      <ModeToggle />
    </div>
  );
}
```

---

## Section 5 — Behaviour spec

| Condition | Button state | Label |
|---|---|---|
| `context === null` (Steps 1–2 not completed) | disabled | Run Scan |
| `pick === 'Custom'` and `customRaw` is empty | disabled | Run Scan |
| `scanState === 'SCANNING'` | disabled | Scanning… |
| Otherwise | enabled | Run Scan |

- On click: set `scanState → 'SCANNING'`, call `api.postScan`, await result.
- On success: call `setScanResult({scan_id, timestamp, candidates})`, set `scanState → 'COMPLETED'` with local ISO timestamp, navigate to `/screener/step-4-ranking`.
- On error (any throw): set `scanState → 'FAILED'`. Do not rethrow.
- The button never modifies any store other than via `setScanState` and `setScanResult`.

---

## Section 6 — Task spec

### Acceptance criteria

1. "Run Scan" button appears in the TopBar to the left of the dark-mode toggle.
2. Button is disabled when `scanStore.context` is null.
3. Button label changes to "Scanning…" while the request is in-flight and the button is non-interactive.
4. On success: `scanStore.scanResult.candidates` is populated, `scanState === 'COMPLETED'`, app navigates to `/screener/step-4-ranking`.
5. On failure (backend unreachable): `scanState === 'FAILED'`, no crash.
6. `npm run typecheck` is clean (0 errors).

### Verify

```bash
cd frontend
npm run typecheck
# Expected: 0 errors
```

Manual smoke test (backend must be running on port 8000):
1. Complete Steps 1 and 2 in the screener (sets `scanStore.context`).
2. Click "Run Scan" — button shows "Scanning…".
3. App navigates to Step 4 — trade cards populated from scan result.
4. TopBar scan pill shows "COMPLETED HH:mm".

---

## Section 7 — Hard rules

1. Do NOT touch any file under `backend/`.
2. Do NOT modify any store file (`scanStore.ts`, `universeStore.ts`, `watchlistStore.ts`).
3. Do NOT touch any existing `.css` file — only create the new `RunScanButton.module.css`.
4. Do NOT touch any step page.
5. `async`/`await` is correct and required inside `handleClick` — this is a click handler, not a hook or export.
6. `npm run typecheck` must remain clean.
7. The `UNIVERSE_SYMBOLS` fallback for unknown pick values must be `UNIVERSE_SYMBOLS['SP500']` (never undefined).

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
branching from feature/1-api-integration, branch name feature/ws-27-run-scan-button.

Read `llm-contexts/27-run-scan-button.md` fully before writing any code.
It is your single source of truth.

You are adding a Run Scan button to the TopBar of the Bamendjou options screener
(Next.js 15 / TypeScript 5.7).

Your owned files:
  - frontend/components/molecules/RunScanButton/index.tsx        (CREATE)
  - frontend/components/molecules/RunScanButton/RunScanButton.module.css  (CREATE)
  - frontend/components/molecules/TopBarActions/index.tsx        (MODIFY)

Do not modify any other file.
Implement exactly as specified in Section 4.
Run `npm run typecheck` from `frontend/` after all changes. Must be clean.
Commit after typecheck passes.
```
