# LLM Context — Step 2 Direction + Horizon Wiring (Workstream 12)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `frontend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream modifies exactly one file. It does not create any new file, does not touch any shared store interface, and does not modify any CSS.

**Goal:**
Step 2 currently holds direction (`dir`) and horizon (`hz`, `minDays`, `maxDays`) in `useState`. These selections are lost when the user navigates away. The fix is to read initial values from `scanStore.context` and call `scanStore.setContext()` on every change, so the TopBar reflects the live selection and the values survive navigation.

The existing `scanStore.setContext()` already accepts `{ universe, direction, horizon }` — no store modification is needed. Step 2 only writes `direction` and `horizon`; it must preserve the existing `universe` from `scanStore.context`.

**What NOT to touch:**
- `frontend/lib/scanStore.ts` — read-only; do NOT change its interface
- `frontend/app/(frame)/screener/step-2-direction/page.module.css` — read-only
- Any other file

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `frontend/app/(frame)/screener/step-2-direction/page.tsx` | **Modify** | Replace `useState` with `scanStore.context` reads; call `setContext()` on every direction/horizon change |

---

## Section 3 — Read-only references

| File | Reason |
|---|---|
| `frontend/lib/scanStore.ts` | Understand `ScanContext` shape and `setContext` signature |
| `frontend/app/(frame)/screener/step-2-direction/page.module.css` | Verify CSS class names |
| `frontend/app/(frame)/screener/screener.module.css` | Shared step layout classes |

---

## Section 4 — Integration constraints

### scanStore interface (read-only — do NOT modify)

```ts
// frontend/lib/scanStore.ts
export type ScanState = 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED';

export interface ScanContext {
  universe:  string;    // e.g. "SP500"
  direction: Direction; // 'Bullish' | 'Bearish'
  horizon:   string;    // e.g. "Swing (5–15d)"
}

interface ScanStoreState {
  scanState:  ScanState;
  scanAt:     string | null;
  context:    ScanContext | null;
  regime:     Status;
  setScanState: (s: ScanState, at?: string) => void;
  setContext:   (c: ScanContext | null) => void;
  setRegime:    (r: Status) => void;
}

// Default seed:
// scanState: 'COMPLETED'
// scanAt: '2026-04-20T09:42:00'
// context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' }
// regime: 'PASS'
```

### Import pattern
```ts
import { useScanStore } from '@/lib/scanStore';

// Inside Step2Page:
const context    = useScanStore((s) => s.context);
const setContext = useScanStore((s) => s.setContext);
```

### Horizon label format

The `horizon` field of `ScanContext` is a human-readable string that the TopBar displays.
Use these exact formats — they must match what the TopBar already expects:

| HorizonKey | Label written to scanStore |
|---|---|
| `'Intraday'` | `'Intraday (0–2d)'` |
| `'Swing'` | `'Swing (5–15d)'` |
| `'Position'` | `'Position (15–45d)'` |
| `'Custom'` | `\`Custom (${minDays}–${maxDays}d)\`` |

Use a helper:
```ts
function horizonLabel(hz: HorizonKey, minDays: number, maxDays: number): string {
  if (hz === 'Intraday') return 'Intraday (0–2d)';
  if (hz === 'Swing')    return 'Swing (5–15d)';
  if (hz === 'Position') return 'Position (15–45d)';
  return `Custom (${minDays}–${maxDays}d)`;
}
```

### Parsing context back to local state

On mount, initialize `dir` and `hz` from `scanStore.context`:

```ts
// Derive initial direction — fall back to 'Bullish'
const initDir: Direction = context?.direction ?? 'Bullish';

// Derive initial HorizonKey from context?.horizon string
function parseHorizonKey(h: string | undefined): HorizonKey {
  if (!h) return 'Swing';
  if (h.startsWith('Intraday')) return 'Intraday';
  if (h.startsWith('Swing'))    return 'Swing';
  if (h.startsWith('Position')) return 'Position';
  if (h.startsWith('Custom'))   return 'Custom';
  return 'Swing';
}

// Derive minDays / maxDays from a Custom horizon string like "Custom (3–12d)"
function parseCustomDays(h: string | undefined): [number, number] {
  if (!h?.startsWith('Custom')) return [5, 15];
  const m = h.match(/(\d+)–(\d+)/);
  return m ? [Number(m[1]), Number(m[2])] : [5, 15];
}
```

Use these for initial `useState` values — the state itself stays local for the custom day inputs (they are derived display values, not stored directly). The source of truth for direction + horizon key is `scanStore.context`.

### setContext call pattern

Call `setContext` whenever `dir`, `hz`, `minDays`, or `maxDays` changes:
```ts
function syncToStore(
  newDir: Direction,
  newHz: HorizonKey,
  newMin: number,
  newMax: number,
) {
  setContext({
    universe:  context?.universe ?? 'SP500',   // preserve existing universe
    direction: newDir,
    horizon:   horizonLabel(newHz, newMin, newMax),
  });
}
```

Call `syncToStore` inside each setter:
```ts
const handleDirChange = (d: Direction) => {
  setDir(d);
  syncToStore(d, hz, minDays, maxDays);
};
const handleHzChange = (h: HorizonKey) => {
  setHz(h);
  syncToStore(dir, h, minDays, maxDays);
};
const handleMinChange = (v: number) => {
  setMinDays(v);
  syncToStore(dir, hz, v, maxDays);
};
const handleMaxChange = (v: number) => {
  const clamped = Math.max(minDays, v);
  setMaxDays(clamped);
  syncToStore(dir, hz, minDays, clamped);
};
```

**Keep** `dir`, `hz`, `minDays`, `maxDays` as local `useState` (they drive the custom inputs). The store is the persistent source of truth; local state is the render source.

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
<Data  size={11..24} weight={500|600} tone="pass|caution|reject" />
```

This workstream uses only `Text` and `Title` primitives (already imported in page.tsx).

---

## Section 7 — Domain types (relevant subset)

```ts
// types/domain.ts
type Direction = 'Bullish' | 'Bearish';
```

---

## Section 8 — Zustand stores (relevant stores only)

### `scanStore.ts` (read-only — see full interface in Section 4)

Key facts:
- `context` is `ScanContext | null`
- Default seed: `{ universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' }`
- `setContext(c: ScanContext | null)` — replaces the whole context object
- When preserving `universe` in Step 2, always use `context?.universe ?? 'SP500'`

---

## Section 9 — Mock data (exact values)

No mock data changes. The horizon preset hints shown in the UI:

| Key | Label | Hint shown in button |
|---|---|---|
| `'Intraday'` | `Intraday` | `0–2 days` |
| `'Swing'` | `Swing` | `5–15 days` |
| `'Position'` | `Position` | `15–45 days` |
| `'Custom'` | `Custom` | `Set range` |

These strings are already correct in `HORIZON_PRESETS` — do not change them.

---

## Section 10 — Task spec

### Acceptance criteria

1. After selecting "Bearish" in Step 2 and navigating to Step 3 then back, "Bearish" is still highlighted.
2. After selecting "Position" horizon and navigating away and back, "Position" is still highlighted.
3. After setting a Custom range (e.g. 3–12 days) and navigating away and back, Custom is still selected and the day inputs show 3 and 12.
4. The TopBar context string (fed by `scanStore.context`) updates immediately when direction or horizon is changed in Step 2. For example, selecting "Bearish + Swing" updates the TopBar to show `… · Bearish · Swing (5–15d)`.
5. The `universe` field of `scanStore.context` is never overwritten by Step 2 (always preserved from existing value, defaulting to `'SP500'`).
6. `npm run typecheck` is clean.

### What changes in page.tsx

**Add** two imports:
```ts
import { useScanStore } from '@/lib/scanStore';
import type { Direction } from '@/types/domain';
```
(Direction is already imported; add scanStore import)

**Add** store reads at the top of `Step2Page`:
```ts
const context    = useScanStore((s) => s.context);
const setContext = useScanStore((s) => s.setContext);
```

**Change** `useState` initial values to derive from store:
```ts
const [dir,     setDir]     = useState<Direction>(() => context?.direction ?? 'Bullish');
const [hz,      setHz]      = useState<HorizonKey>(() => parseHorizonKey(context?.horizon));
const [minDays, setMinDays] = useState<number>(() => parseCustomDays(context?.horizon)[0]);
const [maxDays, setMaxDays] = useState<number>(() => parseCustomDays(context?.horizon)[1]);
```

**Add** helper functions `horizonLabel`, `parseHorizonKey`, `parseCustomDays`, `syncToStore` (see Section 4).

**Replace** inline setter calls in JSX with the new handlers `handleDirChange`, `handleHzChange`, `handleMinChange`, `handleMaxChange`.

**Keep** all CSS class names, JSX structure, and layout unchanged.

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
10. **Workstream-specific**: Do NOT modify `scanStore.ts` — its interface is fixed.
11. **Workstream-specific**: Preserve `context?.universe` when calling `setContext()` — never overwrite it from Step 2.
12. **Workstream-specific**: Do NOT add `useEffect` to sync state — call `syncToStore` directly in handlers.

---

## Section 12 — Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001
npm run typecheck    # must be clean after every edit
```

Manual verification: navigate to Step 2, select "Bearish" → TopBar should immediately show "Bearish" in the context string. Navigate to Step 3 via Next, then press Back — Step 2 should show "Bearish" still selected.

---

## Section 13 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-12-direction-wiring.

Read `llm-contexts/12-step2-direction-wiring.md` fully before writing any code.
It is your single source of truth.

You are implementing the Step 2 direction/horizon wiring for the Bamendjou options
screener (Next.js 15, TypeScript strict, CSS Modules).

Your owned files:
  - frontend/app/(frame)/screener/step-2-direction/page.tsx  (MODIFY)

Do not modify any file outside this list.

Task: Replace Step 2's local useState with reads from scanStore.context and calls
to scanStore.setContext() on every direction/horizon change, so selections survive
navigation and the TopBar reflects the live selection.

After every file edit, run `npm run typecheck` from `frontend/`. Must stay clean.
Commit after all changes are complete.
```
