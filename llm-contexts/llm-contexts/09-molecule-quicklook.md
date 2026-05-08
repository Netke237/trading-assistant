# LLM Context — QuickLookRow + LabeledStatusBadge molecules

> Self-contained workstream document. Read this fully before touching any code.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `frontend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.** This workstream owns only the two molecule folders listed in Section 2. It does not touch any file that merely imports these molecules.

**Goal:** Complete, polish, and document `QuickLookRow` and `LabeledStatusBadge`.

These two molecules serve distinct but related purposes in the same display context:

- `QuickLookRow` — a dense, single-line row for the right-rail watchlist widget. Composes `StatusDot` + two `Data` primitives.
- `LabeledStatusBadge` — a label-and-badge pair. Composes a `Text` primitive + `StatusBadge` atom. Used on the TradeCard final-status section.

They are **not** nested inside each other. They are peers with similar `status: Status` prop signatures, created for different visual slots in the app.

Verify the current implementation of each component, identify any missing polish (accessibility, token usage, typography, missing props), complete any gaps, and ensure both render without TypeScript errors.

**Do NOT modify any file that uses these molecules** — only the molecules themselves.

---

## Section 2 — Owned files

| File | Action |
|---|---|
| `frontend/components/molecules/QuickLookRow/index.tsx` | Modify / complete |
| `frontend/components/molecules/QuickLookRow/QuickLookRow.module.css` | Modify / complete |
| `frontend/components/molecules/LabeledStatusBadge/index.tsx` | Modify / complete |
| `frontend/components/molecules/LabeledStatusBadge/LabeledStatusBadge.module.css` | Modify / complete |

No other files may be modified.

---

## Section 3 — Read-only references

These files import one or both molecules. Read them for context; do not modify them.

| File | Imports |
|---|---|
| `frontend/components/organisms/ContextRail/QuickLook.tsx` | `QuickLookRow` |
| `frontend/components/organisms/TradeCard/index.tsx` | `LabeledStatusBadge` |

No other `.tsx` or `.ts` file in the project currently imports either molecule.

---

## Section 4 — Integration constraints

### QuickLookRow

**Import path used by hosts:**
```ts
import { QuickLookRow } from '@/components/molecules/QuickLookRow';
```

**Current props type (read from `index.tsx`):**
```ts
interface QuickLookRowProps {
  symbol: string;
  score:  number;
  status: Status;
}
```

**Atoms / primitives composed internally:**
- `StatusDot` (atom) — `tone={status}` `size="sm"` — renders the 8px colored circle
- `Data` (primitive) — `size={12}` `weight={500}` — renders the symbol ticker
- `Data` (primitive) — `size={12}` `tone="secondary"` — renders the score number (current state: hardcoded `tone="secondary"`; task is to change this to derive from `statusForScore(score)` so PASS scores render in `--pass`, etc.)

**How the host passes props** (`QuickLook.tsx`):
```tsx
<QuickLookRow
  key={r.symbol}
  symbol={r.symbol}
  score={r.score}
  status={r.status}
/>
```
Props come from `WatchlistRow` mock data sorted by score descending, sliced to top 5.

**CSS layout:** 3-column grid — `10px 1fr auto` with `var(--space-2)` gap.

---

### LabeledStatusBadge

**Import path used by hosts:**
```ts
import { LabeledStatusBadge } from '@/components/molecules/LabeledStatusBadge';
```

**Current props type (read from `index.tsx`):**
```ts
interface LabeledStatusBadgeProps {
  label:  string;
  status: Status;
}
```

**Atoms / primitives composed internally:**
- `Text` (primitive) — `size={12}` `tone="secondary"` — renders the label string
- `StatusBadge` (atom) — `status={status}` — renders the colored pill badge

**How the host passes props** (`TradeCard/index.tsx`):
```tsx
<LabeledStatusBadge label="Final Status" status={data.finalStatus} />
```
Placed inside a `<section>` with class `styles.finalCard` and a dynamic class `styles[`final_${data.finalStatus}`]`.

**Relationship to StatusBadge:** `LabeledStatusBadge` is a thin wrapper that adds a text label before a `StatusBadge`. It does NOT reimplement status coloring — all coloring logic lives in `StatusBadge`.

---

## Section 5 — CSS tokens

All tokens come from `frontend/styles/tokens.css`. Never hardcode colors.

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

## Section 6 — Primitives & component reference

### Primitives

```tsx
// Text — readable copy, labels, secondary info
<Text
  size={11 | 12 | 13 | 14}
  tone={'primary' | 'secondary' | 'dim' | 'pass' | 'caution' | 'reject'}
  weight={400 | 500 | 600}
/>
// Default: size=13, tone="primary", weight=400

// Data — monospace, tabular-nums; use for prices, scores, percentages
<Data
  size={11 | 12 | 13 | 14 | 16 | 18 | 20 | 24}
  weight={500 | 600}
  tone={'pass' | 'caution' | 'reject'}  // optional
/>
```

### Atoms composed by these molecules

**`StatusDot`** — used by QuickLookRow
```tsx
interface StatusDotProps {
  tone: Status | 'ACCENT';  // StatusDotTone
  size?: 'sm' | 'md';       // 'sm' = 8px, 'md' = 12px
  className?: string;
}
// Renders a solid colored circle. aria-hidden="true".
// Import: import { StatusDot } from '@/components/atoms/StatusDot';
```

**`StatusBadge`** — used by LabeledStatusBadge
```tsx
interface StatusBadgeProps {
  status: Status;
  label?: string;     // optional override of default STATUS_LABEL[status]
  className?: string;
}
// Renders a pill badge: 11px, 600 weight, uppercase, 2px 8px padding, 4px radius, 1px border.
// Colors come from token pairs: --pass/--pass-bg/--pass-border, etc.
// Import: import { StatusBadge } from '@/components/atoms/StatusBadge';
```

### Status type and helpers

```ts
// frontend/lib/status.ts
export type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA';

export const STATUS_LABEL: Record<Status, string> = {
  PASS: 'PASS',
  CAUTION: 'CAUTION',
  REJECT: 'REJECT',
  PENDING: 'PENDING',
  NO_DATA: 'NO DATA',
};

export function statusForScore(value: number, max = 100): Status { ... }
export function worstStatus(...statuses: Status[]): Status { ... }
```

---

## Section 7 — Domain types

Neither molecule imports from `types/domain.ts`. They both consume `Status` from `lib/status.ts`.

Relevant type chain for understanding the data that flows into them:

```ts
// From types/domain.ts (relevant subset)
interface WatchlistRow {
  symbol:  string;
  score:   number;   // 0–100 — passed to QuickLookRow.score
  status:  Status;   // passed to QuickLookRow.status
  // ... other fields not used by QuickLookRow
}

interface TradeCardData {
  finalStatus: Status;  // passed to LabeledStatusBadge.status
  // ... other fields not used by LabeledStatusBadge
}
```

`QuickLookRow` receives `symbol`, `score`, and `status` extracted from `WatchlistRow`.
`LabeledStatusBadge` receives a literal `label` string and `status` from `TradeCardData.finalStatus`.

---

## Section 8 — Zustand stores

Neither molecule uses any Zustand store. Both are purely presentational — they receive all data via props and render output. No store reads, no dispatches, no side effects.

---

## Section 9 — Mock data (exact values)

### QuickLookRow — example props (top 5 from MOCK_WATCHLIST sorted by score desc)

```tsx
// Row 1
<QuickLookRow symbol="AAPL"  score={82} status="PASS" />
// Row 2
<QuickLookRow symbol="NVDA"  score={79} status="PASS" />
// Row 3
<QuickLookRow symbol="MSFT"  score={74} status="PASS" />
// Row 4
<QuickLookRow symbol="META"  score={71} status="PASS" />
// Row 5
<QuickLookRow symbol="GOOGL" score={68} status="CAUTION" />
```

The host renders these in a `flex-direction: column; gap: var(--space-2)` stack inside a `RailSection` titled `"Watchlist · Top 5"`.

### LabeledStatusBadge — example props (from TradeCard)

```tsx
// Used once per trade card, in the "Final Status" section
<LabeledStatusBadge label="Final Status" status="PASS" />
<LabeledStatusBadge label="Final Status" status="CAUTION" />
<LabeledStatusBadge label="Final Status" status="REJECT" />
```

From `mocks/tradecards.ts`, `finalStatus` is derived from each candidate's overall score, so all three Status values can appear in practice.

---

## Section 10 — Task spec

### Current state assessment

**QuickLookRow** — minimally functional but thin:

1. **Complete:** Basic layout renders correctly. StatusDot, symbol Data, score Data all present.
2. **Missing — score tone:** The score `Data` renders with no `tone`, so it always shows in `--text-primary`. Consider deriving a tone from `statusForScore(score)` so 82 → pass-colored, 68 → caution-colored, 42 → reject-colored. This would make the row self-consistent with the rest of the app's score display convention.
3. **Missing — accessibility:** No `role` or `aria-label` on the root `div`. For screen readers, the row is meaningless — the symbol and score are bare numbers with no context. Consider `role="row"` + `aria-label={`${symbol} score ${score} ${status}`}` on the root.
4. **Missing — score display format:** The score `Data` renders as a raw integer (e.g. `82`). The rail context is narrow; consider whether a suffix `/100` or `%` is needed for clarity, or if the host context makes this obvious. Keep consistent with the rest of the app (Step 4 table uses bare integers).
5. **Polish — padding:** The root has no vertical padding, relying on the parent `gap: var(--space-2)`. This is acceptable for the dense rail context. Verify at 300px rail width that the grid doesn't collapse.

**LabeledStatusBadge** — clean and complete:

1. **Complete:** Correctly wraps `StatusBadge` with a `Text` label. No status coloring reimplemented. CSS uses only custom properties.
2. **No missing pieces:** Props are fully typed, no `any`. The single use-site passes `label="Final Status"` and `status={data.finalStatus}`.
3. **Polish — alignment:** The `flex` root with `align-items: center` is correct. Consider `justify-content: space-between` if the host's `finalCard` section wants label left, badge right. Currently both items pack left with `gap: var(--space-2)`.
4. **Polish — label weight:** `Text size={12} tone="secondary"` uses default `weight={400}`. This is correct — do not raise to 600 on a display label.

### Acceptance criteria

- Both components render without TypeScript errors (`npm run typecheck` clean)
- All props typed — no `any`
- CSS modules use only CSS custom properties — no hardcoded hex values
- `LabeledStatusBadge` uses `StatusBadge` atom internally — does not reimplement status coloring
- `QuickLookRow` correctly colors the score `Data` by status (if you add the tone improvement)
- `QuickLookRow` has a meaningful `aria-label` on its root element
- Neither component introduces new external dependencies

---

## Section 11 — Hard rules

1. **No Tailwind, styled-components, or CSS-in-JS.** CSS Modules only.
2. **No inline `style={{}}` for color or spacing** — only for computed one-off values (e.g. `style={{ width: \`${pct}%\` }}`).
3. **No hardcoded colors** — always use CSS custom properties from `tokens.css`.
4. **No card shadows** — use `border: 1px solid var(--border-subtle)` instead.
5. **No invented Status labels** — only `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
6. **No font-weight 600 on labels** — use `weight={400}` for `Text` in form/display labels.
7. **Atoms → Molecules → Organisms** — never skip hierarchy levels.
8. **`npm run typecheck` must be clean before any commit.**
9. **Do not touch `node_modules/` or `package-lock.json`.**
10. **No `any` types in props** — all props must be explicitly typed.
11. **Do not modify any file that imports these molecules** — only the molecules themselves.
12. **`LabeledStatusBadge` must use the `StatusBadge` atom internally** — do not reimplement status coloring logic (background, border, text color) in the molecule.

---

## Section 12 — Dev workflow

```bash
cd frontend
npm run typecheck          # must be clean — run after every edit
npm run dev                # localhost:3001

# To see QuickLookRow:
# Navigate to any screener step or dashboard page.
# The ContextRail on the right shows the "Watchlist · Top 5" section.
# QuickLookRow renders 5 rows there.

# To see LabeledStatusBadge:
# Navigate to Step 7 (step-7-trade-card).
# The TradeCard's "Final Status" section uses LabeledStatusBadge.
# It appears once per candidate, showing the finalStatus badge with a label.
```

---

## Section 13 — Copy/paste prompt

```
You are working on the Bamendjou options screener (Next.js 15 / TypeScript).
Read the full context document at:
  llm-contexts/09-molecule-quicklook.md

Your task: complete and polish the QuickLookRow and LabeledStatusBadge molecules.

Owned files (the ONLY files you may modify):
  frontend/components/molecules/QuickLookRow/index.tsx
  frontend/components/molecules/QuickLookRow/QuickLookRow.module.css
  frontend/components/molecules/LabeledStatusBadge/index.tsx
  frontend/components/molecules/LabeledStatusBadge/LabeledStatusBadge.module.css

Read-only references (read for context; do not modify):
  frontend/components/organisms/ContextRail/QuickLook.tsx
  frontend/components/organisms/TradeCard/index.tsx
  frontend/components/atoms/StatusDot/index.tsx
  frontend/components/atoms/StatusBadge/index.tsx
  frontend/components/primitives/index.tsx (or whichever file exports Text, Data)
  frontend/lib/status.ts

Steps:
1. Read the context doc fully.
2. Read every owned file and every read-only reference.
3. For QuickLookRow:
   a. Add score tone — derive it from statusForScore(score) and pass it to the score Data primitive so the score integer is colored PASS/CAUTION/REJECT.
   b. Add accessibility — add aria-label={`${symbol}, score ${score}, ${status}`} to the root div.
   c. Verify the CSS grid (10px 1fr auto, gap var(--space-2)) is correct for the 300px rail context.
4. For LabeledStatusBadge:
   a. Verify it correctly composes StatusBadge (not reimplementing color logic).
   b. Consider whether justify-content: space-between would improve alignment in its host context (TradeCard finalCard section).
   c. Confirm label Text uses tone="secondary" and weight={400}.
5. Run npm run typecheck — fix any errors before stopping.
6. Do not modify any file outside the owned files list.
7. Report what you changed and confirm typecheck is clean.
```
