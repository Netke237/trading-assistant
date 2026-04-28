# LLM Context — RegimeIndicator + ScanIndicator molecules

> Self-contained workstream document. Read this fully before touching any code.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `frontend/`.

---

## 1. Mission

**Conflict class: Medium** — owns only the two molecule folders listed in Section 2.

`TopBar/index.tsx` and `NavRail/index.tsx` are **read-only** in this workstream: they are referenced here solely to understand integration. If either host component needs changes (e.g., to pass different props), document the required change as a note but do **not** modify those files. Make that change in a separate PR.

**Goal:** Complete and polish two molecules:

- **RegimeIndicator** — shown in `TopBar`. Displays a colored dot (via `StatusDot`) plus a regime label that reflects `scanStore.regime` (`'PASS' | 'CAUTION' | 'REJECT' | ...`). Must read from `useScanStore()` directly rather than receiving props, so the TopBar does not need to plumb the value down manually (see Section 10 for current state vs. target state).
- **ScanIndicator** — shown in `NavRail` footer. Displays a colored dot plus a text label that reflects `scanStore.scanState` (`'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED'`) and, when `COMPLETED`, formats `scanStore.scanAt` into a readable timestamp. Must read from `useScanStore()` directly.

Both molecules currently receive their data via props (driven by the host component). The target state is **store-driven**: each molecule calls `useScanStore()` itself, so the host components simplify to `<RegimeIndicator />` and `<ScanIndicator />` with no props.

---

## 2. Owned files

```
frontend/components/molecules/RegimeIndicator/index.tsx
frontend/components/molecules/RegimeIndicator/RegimeIndicator.module.css
frontend/components/molecules/ScanIndicator/index.tsx
frontend/components/molecules/ScanIndicator/ScanIndicator.module.css
```

---

## 3. Read-only references

| File | Why you need it |
|---|---|
| `frontend/lib/scanStore.ts` | Source of `regime`, `scanState`, `scanAt` — both molecules read from this store |
| `frontend/components/atoms/StatusDot/index.tsx` | Atom used by both molecules for the colored dot |
| `frontend/components/atoms/StatusDot/StatusDot.module.css` | Dot size + tone classes |
| `frontend/components/primitives/Text.tsx` | Used for labels |
| `frontend/lib/status.ts` | `Status` type definition |
| `frontend/components/organisms/TopBar/index.tsx` | Shows how RegimeIndicator is currently called; read but do not modify |
| `frontend/components/organisms/NavRail/index.tsx` | Shows how ScanIndicator is currently called; read but do not modify |

---

## 4. Integration constraints

### RegimeIndicator

**Current call site (TopBar/index.tsx, line 87):**
```tsx
<RegimeIndicator status={regime} />
```
The host reads `regime` from `useScanStore` itself and passes it as a prop.

**Current component signature:**
```tsx
interface RegimeIndicatorProps {
  status: Status;
  label?: string;
}
export function RegimeIndicator({ status, label }: RegimeIndicatorProps)
```

**Target (store-driven, no props):**
```tsx
// No props needed — reads scanStore.regime internally
export function RegimeIndicator()
```
The TopBar would then simplify to `<RegimeIndicator />`. Note: updating TopBar is a **separate PR** — document the required change here but do not touch `TopBar/index.tsx`.

**What it reads from scanStore:**
```ts
const regime = useScanStore((s) => s.regime);  // type: Status
```

**What it renders:**
- `StatusDot` atom with `tone={regime}` and `size="sm"`
- `Text` label: the `STATUS_LABEL` display name for `regime` (e.g. `'PASS'`, `'CAUTION'`, `'REJECT'`, `'NO DATA'`)
- Optional prefix label: `"Regime: "` or similar — see Section 10 for the exact output

---

### ScanIndicator

**Current call site (NavRail/index.tsx, lines 21–37):**
```tsx
// NavRail maps ScanState → Status | 'ACCENT' before passing to ScanIndicator
const SCAN_DOT: Record<ScanState, Status | 'ACCENT'> = {
  IDLE:      'PENDING',
  SCANNING:  'ACCENT',
  COMPLETED: 'PASS',
  FAILED:    'REJECT',
};
// ...
const scanState = useScanStore((s) => s.scanState);
// ...
<ScanIndicator status={SCAN_DOT[scanState]} />
```

**Current component signature:**
```tsx
interface ScanIndicatorProps {
  status: Status | 'ACCENT';
}
export function ScanIndicator({ status }: ScanIndicatorProps)
```

**Target (store-driven, no props):**
```tsx
// No props needed — reads scanStore.scanState and scanStore.scanAt internally
export function ScanIndicator()
```
The SCAN_DOT mapping and `useScanStore` call in NavRail would be removed; the molecule owns that logic. Note: updating NavRail is a **separate PR**.

**What it reads from scanStore:**
```ts
const scanState = useScanStore((s) => s.scanState);  // type: ScanState
const scanAt    = useScanStore((s) => s.scanAt);      // type: string | null
```

**Dot tone mapping (internal to molecule):**
```ts
const SCAN_DOT: Record<ScanState, StatusDotTone> = {
  IDLE:      'PENDING',
  SCANNING:  'ACCENT',
  COMPLETED: 'PASS',
  FAILED:    'REJECT',
};
```

**What it renders:**
- `StatusDot` atom with `tone={SCAN_DOT[scanState]}` and `size="sm"`
- Text label derived from `scanState` and `scanAt` — see Section 9 for exact format

---

## 5. CSS tokens

All colors come from `frontend/styles/tokens.css`. Never hardcode hex values.

### Dark theme (default — `:root` / `[data-theme="dark"]`)

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

/* Status — NEUTRAL / PENDING */
--neutral:          #4A5568;
--neutral-bg:       #1A202C;

/* Accent */
--accent:           #2962FF;
--accent-hover:     #1E53E5;
--accent-dim:       #142B7A;
--accent-text:      #FFFFFF;

/* Spacing (4px base) */
--space-1:  4px;
--space-2:  8px;
--space-3:  12px;
--space-4:  16px;
--space-5:  20px;
--space-6:  24px;
--space-8:  32px;
--space-12: 48px;

/* Radius */
--radius-sm: 4px;
--radius-md: 6px;
--radius-lg: 10px;

/* Frame sizes */
--frame-topbar-h:            48px;
--frame-navrail-w:           64px;
--frame-navrail-w-expanded:  200px;
--frame-contextrail-w:       300px;
--frame-stepnav-h:           52px;
```

### Light theme override (`[data-theme="light"]`)

```css
--bg-base:        #F0F3FA;
--bg-surface:     #FFFFFF;
--bg-surface-2:   #F5F7FF;
--bg-surface-3:   #EBF0FF;
--border-subtle:  #DDE1F0;
--border-strong:  #C5CCE6;
--text-primary:   #131722;
--text-secondary: #5A6070;
--text-dim:       #9BA3B8;
--pass:           #1A9188;
--pass-bg:        #EDF7F6;
--pass-border:    #B3E0DC;
--caution:        #D4890A;
--caution-bg:     #FEF6E6;
--caution-border: #F5D38A;
--reject:         #D32F2F;
--reject-bg:      #FEECEC;
--reject-border:  #F5BCBC;
--neutral:        #64748B;
--neutral-bg:     #F1F5F9;
```

---

## 6. Primitives & component reference

### Primitive: `<Text>`

```tsx
// frontend/components/primitives/Text.tsx
<Text
  as={'span' | 'p' | 'div' | 'label' | 'small' | 'strong' | 'li'}  // default: 'span'
  size={10 | 11 | 12 | 13 | 14 | 16}                                 // default: 13
  weight={400 | 500 | 600}                                            // default: 400
  tone={'primary' | 'secondary' | 'dim' | 'accent' | 'pass' | 'caution' | 'reject'}  // default: 'primary'
  className?: string
>
  {children}
</Text>
```

Use for: nav items, labels, body text. Do NOT use for numeric data or timestamps — use `<Data>` for those.

### Primitive: `<Data>`

```tsx
// frontend/components/primitives/Data.tsx
<Data
  as={'span' | 'p' | 'div' | 'td' | 'strong'}                       // default: 'span'
  size={10 | 11 | 12 | 13 | 14 | 16 | 18 | 24}                      // default: 12
  weight={500 | 600}                                                  // no weight={400} for Data — use Text/primitive for lighter weight
  tone={'pass' | 'caution' | 'reject'}                               // optional; omit for default primary
  className?: string
>
  {children}
</Data>
```

JetBrains Mono, tabular-nums. Use for prices, scores, percentages, tickers, timestamps, DTE counts.

### Primitive: `<Title>`

```tsx
<Title as={'h1' | 'h2' | 'h3'} size={18 | 20 | 24} />
```

### Atom: `StatusDot`

```tsx
// frontend/components/atoms/StatusDot/index.tsx
export type StatusDotTone = Status | 'ACCENT';

<StatusDot
  tone={'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA' | 'ACCENT'}
  size={'sm' | 'md'}   // sm = 8px, md = 12px; default: 'md'
  className?: string
/>
```

Renders a `<span aria-hidden="true">` circle. Colors map to CSS tokens via `.pass`, `.caution`, `.reject`, `.pending`, `.noData`, `.accent` classes. No hardcoded colors.

### Atoms used by each molecule

| Molecule | Atoms used | Primitives used |
|---|---|---|
| `RegimeIndicator` | `StatusDot` (colored dot) | `Text` (regime label) |
| `ScanIndicator` | `StatusDot` (scan state dot) | `Text` (state label), `Data` (timestamp — monospace) |

---

## 7. Domain types

### From `frontend/lib/status.ts`

```ts
export type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA';

export const STATUS_LABEL: Record<Status, string> = {
  PASS:    'PASS',
  CAUTION: 'CAUTION',
  REJECT:  'REJECT',
  PENDING: 'PENDING',
  NO_DATA: 'NO DATA',
};

export function statusForScore(value: number, max = 100): Status { ... }
export function worstStatus(...statuses: Status[]): Status { ... }
```

### From `frontend/lib/scanStore.ts`

```ts
export type ScanState = 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED';

export interface ScanContext {
  universe:  string;    // "SP500" | "NAS100" | ...
  direction: Direction; // 'Bullish' | 'Bearish'
  horizon:   string;    // "Swing (5–15d)"
}
```

### From `frontend/types/domain.ts`

```ts
type Direction = 'Bullish' | 'Bearish';
```

---

## 8. Zustand stores

### `useScanStore` — full interface

```ts
// frontend/lib/scanStore.ts
interface ScanStoreState {
  scanState:    ScanState;
  /** ISO-ish local timestamp, e.g. "2026-04-21T09:42:00" (no TZ suffix). */
  scanAt:       string | null;
  context:      ScanContext | null;
  regime:       Status;
  setScanState: (s: ScanState, at?: string) => void;
  setContext:   (c: ScanContext | null) => void;
  setRegime:    (r: Status) => void;
}

// Default seed values:
// scanState: 'COMPLETED'
// scanAt:    '2026-04-20T09:42:00'
// context:   { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' }
// regime:    'PASS'
```

### Selector patterns for each molecule

Both molecules READ from the store. They must NOT call any write actions (`setScanState`, `setContext`, `setRegime`).

```ts
// RegimeIndicator — reads regime only
const regime = useScanStore((s) => s.regime);

// ScanIndicator — reads scanState + scanAt
const scanState = useScanStore((s) => s.scanState);
const scanAt    = useScanStore((s) => s.scanAt);
```

Use granular selectors (one per value) rather than destructuring the entire store object, to minimize re-renders.

---

## 9. Mock data — exact render output

### Seed values (what you see on first load)

```
scanState: 'COMPLETED'
scanAt:    '2026-04-20T09:42:00'
regime:    'PASS'
```

### RegimeIndicator with `regime = 'PASS'`

- StatusDot: green dot (8px, `tone="PASS"`)
- Text label: `"PASS"` (from `STATUS_LABEL['PASS']`)
- Combined visual: `● PASS`

The label must use `STATUS_LABEL` from `lib/status.ts`, not a hardcoded string. This ensures `'NO_DATA'` renders as `"NO DATA"` and future statuses are covered automatically.

### ScanIndicator with `scanState = 'COMPLETED'`, `scanAt = '2026-04-20T09:42:00'`

Since today is `2026-04-27` and the scan was on `2026-04-20` (7 days ago, not yesterday, not today), the timestamp format used by TopBar's existing `labelWithDate()` helper would produce:

```
Apr 20 09:42
```

(`sameYear` path: `${mon} ${day} ${hhmm}` where `mon = 'Apr'`, `day = 20`, `hhmm = '09:42'`)

**ScanIndicator target output:** `● Scan complete · Apr 20, 09:42`

Or a simpler variant consistent with what the NavRail footer needs: `● COMPLETED Apr 20 09:42`

The exact label format is a polish decision — see Section 10. The timestamp extraction logic from TopBar can be copied/referenced:

```ts
/** Extracts HH:mm from a local-ISO string. Safe during SSR (no Date object). */
function hhmmFrom(iso: string): string {
  return iso.slice(11, 16);  // "2026-04-20T09:42:00" → "09:42"
}

/** Returns a date-prefixed time label (client-only — uses new Date()). */
function labelWithDate(iso: string, now: Date): string {
  const hhmm = hhmmFrom(iso);
  const scan = new Date(iso);
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diffDays = Math.round((startOfDay(now) - startOfDay(scan)) / 86_400_000);
  if (diffDays === 0) return hhmm;
  if (diffDays === 1) return `Yesterday ${hhmm}`;
  const mon = scan.toLocaleString(undefined, { month: 'short' });
  const day = scan.getDate();
  const sameYear = scan.getFullYear() === now.getFullYear();
  return sameYear
    ? `${mon} ${day} ${hhmm}`
    : `${mon} ${day} ${scan.getFullYear()} ${hhmm}`;
}
```

SSR safety: render `hhmmFrom(scanAt)` on the server, then replace with the full `labelWithDate()` output after client mount (use a `mounted` state flag, same pattern as TopBar).

### All four ScanState render outputs

| `scanState` | Dot tone | Label |
|---|---|---|
| `'IDLE'` | `PENDING` (grey) | `"Idle"` or `"IDLE"` |
| `'SCANNING'` | `ACCENT` (blue, pulsing) | `"Scanning…"` or `"SCANNING"` |
| `'COMPLETED'` | `PASS` (green) | `"Scan complete · Apr 20 09:42"` (or similar) |
| `'FAILED'` | `REJECT` (red) | `"Failed"` or `"FAILED"` |

The exact label strings are a polish decision. Pick a consistent casing convention and stick to it.

---

## 10. Task spec

### Current state (as of this document)

**RegimeIndicator (`frontend/components/molecules/RegimeIndicator/index.tsx`):**

```tsx
// CURRENT — receives status as a prop from TopBar
interface RegimeIndicatorProps {
  status: Status;
  label?: string;
}
export function RegimeIndicator({ status, label }: RegimeIndicatorProps) {
  return (
    <div className={styles.root}>
      <StatusDot tone={status} size="sm" />
      <Text size={12} tone="secondary">{label ?? 'Regime'}</Text>
    </div>
  );
}
```

Issues:
1. Reads from props, not from `useScanStore()` — the molecule is passive; the host manages the data.
2. Label is always `"Regime"` (the fallback). It does not show the actual regime value (`'PASS'`, `'CAUTION'`, `'REJECT'`).
3. Missing `'use client'` directive (required since the target uses a hook).
4. CSS module has only `.root` — minimal but acceptable; no changes needed there unless you want a `.label` class.

**ScanIndicator (`frontend/components/molecules/ScanIndicator/index.tsx`):**

```tsx
// CURRENT — receives a pre-mapped Status | 'ACCENT' from NavRail
interface ScanIndicatorProps {
  status: Status | 'ACCENT';
}
export function ScanIndicator({ status }: ScanIndicatorProps) {
  return (
    <div className={styles.root}>
      <StatusDot tone={status} size="sm" />
      <Text size={10} tone="secondary">Scan</Text>
    </div>
  );
}
```

Issues:
1. Reads from props, not from `useScanStore()`.
2. Label is always the static string `"Scan"` — does not reflect state or timestamp.
3. Does not format `scanAt` — no timestamp display for `COMPLETED` state.
4. Missing `'use client'` directive.
5. The `SCAN_DOT` mapping currently lives in NavRail — it belongs in this molecule.

### Tasks

1. **RegimeIndicator — make store-driven:**
   - Add `'use client';` at the top.
   - Remove props interface (or keep it for backward-compat with a deprecated overload — your choice, but store-driven is the target).
   - Add `const regime = useScanStore((s) => s.regime);` inside the component.
   - Change the label to show `STATUS_LABEL[regime]` (from `lib/status.ts`), so it reads `"PASS"`, `"CAUTION"`, `"REJECT"`, etc.
   - Optional: add a dim `"Regime"` prefix label before the dot, e.g. `Regime ● PASS`.

2. **ScanIndicator — make store-driven + add timestamp:**
   - Add `'use client';` at the top.
   - Remove props interface.
   - Move the `SCAN_DOT` mapping into the molecule.
   - Add selectors for `scanState` and `scanAt` from `useScanStore`.
   - Add a `mounted` state flag for SSR safety (same pattern as TopBar).
   - Render the appropriate label for each state, with a formatted timestamp when `COMPLETED`.
   - Use `<Data>` for the timestamp (monospace, tabular-nums).

3. **Note for separate PR — TopBar update:**
   TopBar currently does:
   ```tsx
   const regime = useScanStore((s) => s.regime);
   // ...
   <RegimeIndicator status={regime} />
   ```
   After RegimeIndicator becomes store-driven, TopBar should be updated to:
   ```tsx
   // Remove: const regime = useScanStore((s) => s.regime);
   <RegimeIndicator />
   ```
   Do not make this change now — it belongs in a separate PR that updates TopBar.

4. **Note for separate PR — NavRail update:**
   NavRail currently does:
   ```tsx
   const SCAN_DOT: Record<ScanState, Status | 'ACCENT'> = { ... };
   const scanState = useScanStore((s) => s.scanState);
   // ...
   <ScanIndicator status={SCAN_DOT[scanState]} />
   ```
   After ScanIndicator becomes store-driven, NavRail should be updated to:
   ```tsx
   // Remove: SCAN_DOT mapping
   // Remove: const scanState = useScanStore((s) => s.scanState);
   // Remove: import type { ScanState } from '@/lib/scanStore';
   // Remove: import type { Status } from '@/lib/status';
   <ScanIndicator />
   ```
   Do not make this change now — it belongs in a separate PR.

### Acceptance criteria

- [ ] RegimeIndicator renders a `StatusDot` (8px, colored by `regime`) + label showing the regime value (`"PASS"` / `"CAUTION"` / `"REJECT"` etc.)
- [ ] RegimeIndicator reads `regime` from `useScanStore()` internally — not from props
- [ ] ScanIndicator renders a `StatusDot` (8px, colored by scan state) + label showing the state
- [ ] ScanIndicator shows a formatted timestamp next to `"COMPLETED"` label, using `<Data>` for the time portion
- [ ] ScanIndicator reads `scanState` and `scanAt` from `useScanStore()` internally
- [ ] Both components have `'use client';` at the top
- [ ] No TypeScript errors (`npm run typecheck` is clean)
- [ ] CSS module files use only token variables — no hardcoded hex or rgb values
- [ ] Neither component calls any write action on scanStore

---

## 11. Hard rules

1. Do not add Tailwind, styled-components, or any CSS-in-JS library.
2. Do not add `style={{}}` inline props for anything other than computed one-off values (e.g. `style={{ width: \`${pct}%\` }}`).
3. Do not hardcode colors — always use CSS custom properties from `tokens.css`.
4. Do not invent new Status labels. The only valid values are `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. Do not use font-weight 600 on form labels.
6. Do not add card box-shadows — use `border: 1px solid var(--border-subtle)`.
7. Do not skip component hierarchy levels (atom → molecule → organism).
8. Do not commit with a failing `npm run typecheck`.
9. Do not touch `node_modules/` or `package-lock.json` unless explicitly asked.
10. **RegimeIndicator must NOT hardcode colors** — the dot color is entirely determined by `StatusDot`'s `tone` prop, which maps to CSS tokens via `StatusDot.module.css`. Do not add any color-related CSS to `RegimeIndicator.module.css`.
11. **ScanIndicator must NOT import from any page-level file** — only import from `lib/`, `components/atoms/`, `components/primitives/`, and `types/`.
12. **Do not add any actions to scanStore** — both molecules are read-only consumers of the store.
13. **Both molecules must have `'use client'`** — they call React hooks (`useScanStore`, `useState`, `useEffect`).

---

## 12. Dev workflow

```bash
cd frontend
npm run dev       # localhost:3001 — navigate to any page to see TopBar (RegimeIndicator)
                  # navigate to any page to see NavRail footer (ScanIndicator)
npm run typecheck # tsc --noEmit — must be clean before committing
npm run lint      # next lint
```

To verify live rendering:
- Open `http://localhost:3001/screener/step-1-universe` to see both TopBar and NavRail simultaneously.
- The TopBar right-hand side shows `RegimeIndicator` (should read `● PASS` with seed data).
- The NavRail footer shows `ScanIndicator` (should read `● COMPLETED Apr 20 09:42` or similar with seed data).
- Toggle theme (dark/light) via the `ModeToggle` in the top-right to verify token-based colors adapt correctly.

---

## 13. Copy/paste prompt

Use this prompt verbatim to start a new session on this workstream:

---

You are working on the Bamendjou options screener (Next.js 15, TypeScript, CSS Modules).

Read `llm-contexts/10-molecule-regime-scan.md` in full before doing anything else. That file is the complete specification for this task.

**Your task:** Polish and complete the `RegimeIndicator` and `ScanIndicator` molecules.

Both molecules currently receive their data via props from their host components (TopBar and NavRail). The goal is to make them **store-driven**: each molecule calls `useScanStore()` internally, removing the need for the host to pass props.

**Owned files** (the only files you may modify):
- `frontend/components/molecules/RegimeIndicator/index.tsx`
- `frontend/components/molecules/RegimeIndicator/RegimeIndicator.module.css`
- `frontend/components/molecules/ScanIndicator/index.tsx`
- `frontend/components/molecules/ScanIndicator/ScanIndicator.module.css`

**Do not modify** TopBar, NavRail, scanStore, or any other file. If those files need changes as a follow-on, document what needs to change as a note in your response.

After making changes, run `npm run typecheck` (from the `frontend/` directory) and confirm it is clean. Report exactly what you changed and why.

---
