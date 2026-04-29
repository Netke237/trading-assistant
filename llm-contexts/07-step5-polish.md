# Step 5 — Volatility + Events Gate: Polish Workstream

> **How to use this file**
> You are working on the Bamendjou options screener (Next.js 15, TypeScript 5.7, CSS Modules).
> Read this document fully before touching any code. It is self-contained — do not assume knowledge of other context files.
> All work lives in `frontend/`. Project root: `F:\Git\GitHub\Trading assistant`.

---

## 1. Mission

**Conflict class: Medium** — owns only `step-5-vol-events/` files.

- `screener.module.css` is **read-only** (shared with all 7 steps). Import it, do not modify it.
- `lib/date.ts` and `lib/status.ts` are **read-only** unless you find a clear bug. If you fix a bug there, document: the exact line you changed, what was wrong, and what you changed it to.
- `mocks/watchlist.ts` and `mocks/events.ts` are **read-only** (mock data).

**Goal:** Review and polish Step 5 to fix the three issues identified in LLM_CONTEXT.md section 15:

1. **IV rank bar width bug** — the current `page.tsx` uses `style={{ width: \`${rank}%\` }}` (percentage of `.ivTrack` container width). The spec requires the bar to fill exactly `(ivRank / 100) * 120px` inside a fixed-width 120px track. The fix is `style={{ width: \`${(rank / 100) * 120}px\` }}`.
2. **Gate logic verification** — confirm the computed `gate` (= worst of IV status and event-proximity status) is correct for all 10 `MOCK_WATCHLIST` rows. The pre-computed acceptance table is in Section 9.
3. **NEXT EVENT column alignment at 1200px** — the minimum viewport width (enforced by `MinWidthGate.tsx`). Verify the column does not overflow or collapse at 1200px.

---

## 2. Owned files

The implementing LLM may create or modify **only** these files:

| File | Status |
|---|---|
| `frontend/app/(frame)/screener/step-5-vol-events/page.tsx` | **Modify** |
| `frontend/app/(frame)/screener/step-5-vol-events/page.module.css` | **Modify** |

No other files should be created or modified unless a bug is found in a read-only file (document it per Section 1 constraints).

---

## 3. Read-only references

These files must be read before starting. Do not modify them.

| File | Purpose |
|---|---|
| `frontend/app/(frame)/screener/screener.module.css` | Shared layout classes (`.main`, `.stepHeader`, `.stepBody`, `.stepBody_noPad`) — import only |
| `frontend/lib/date.ts` | `eventProximity(days)` → `'distant' \| 'near' \| 'imminent'`; read-only unless bug found |
| `frontend/lib/status.ts` | `worstStatus(...statuses)`, `statusForScore(value)`, `type Status`; read-only |
| `frontend/mocks/watchlist.ts` | The 10-row `MOCK_WATCHLIST` array — read-only |
| `frontend/mocks/events.ts` | `nextEventFor(symbol)` and `MOCK_EVENTS` — read-only |
| `frontend/types/domain.ts` | `WatchlistRow` type — read-only |

---

## 4. Integration constraints

### Current imports in page.tsx

```tsx
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { EventFlag } from '@/components/atoms/EventFlag';
import { WatchStar } from '@/components/atoms/WatchStar';
import { MOCK_WATCHLIST } from '@/mocks/watchlist';
import { eventProximity } from '@/lib/date';
import { worstStatus, type Status } from '@/lib/status';
import styles from '../screener.module.css';
import pageStyles from './page.module.css';
```

### Column layout

```ts
const COLUMNS = '32px 72px 1fr 120px 70px 110px 80px';
// Column order: [star] [symbol] [name] [IV rank+bar] [IV pctl] [next event] [gate]
```

Do not change the `COLUMNS` string without documenting why and what layout problem it solves.

### IV rank computation (deterministic hash)

```ts
function ivRankFor(symbol: string): number {
  let h = 0;
  for (let i = 0; i < symbol.length; i++) h = (h * 31 + symbol.charCodeAt(i)) >>> 0;
  return 20 + (h % 70);  // range: 20–89
}
```

### IV percentile computation

```ts
function ivPctlFor(symbol: string): number {
  let h = 0;
  for (let i = 0; i < symbol.length; i++) h = (h * 17 + symbol.charCodeAt(i)) >>> 0;
  return Math.max(5, Math.min(95, ivRankFor(symbol) + ((h % 21) - 10)));
}
```

### Event proximity mapping (from lib/date.ts)

```ts
// days <= 3  → 'imminent' → proxStatus = 'REJECT'
// days <= 7  → 'near'     → proxStatus = 'CAUTION'
// days > 7   → 'distant'  → proxStatus = 'PASS'
```

### What screener.module.css provides

```css
.main        { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-6); max-width: none; }
.stepHeader  { display: flex; flex-direction: column; gap: var(--space-1); }
.stepBody    { display: flex; flex-direction: column; gap: var(--space-3);
               padding: var(--space-5); background: var(--bg-surface);
               border: 1px solid var(--border-subtle); border-radius: var(--radius-lg);
               min-height: 280px; }
.stepBody_noPad { padding: 0; }
```

### Important: nextEventDays comes from mocks/events.ts

`MOCK_WATCHLIST` calls `nextEventFor(symbol)` from `mocks/events.ts`. That function matches both symbol-specific events AND global market events (symbol `'—'`). At reference date `2026-04-20`, the FOMC on `2026-04-23` (3 days away) is the nearest event for any symbol that does not have a sooner specific event. This means every row except NVDA (1d Earnings) and TSLA (0d Earnings) shows `nextEventDays = 3` with label `'FOMC'`. All are 'imminent' (days <= 3) → proxStatus = 'REJECT'. This is correct and expected behavior — it reflects real pre-FOMC risk.

> **Cross-document note:** `llm-contexts/06-watchlist.md` lists AAPL at `nextEventDays=8, Earnings`. That document was generated for the Watchlist page and uses a DIFFERENT lookup logic (it may read the watchlist mock directly rather than calling `nextEventFor`). For Step 5 specifically, the value comes from `nextEventFor('AAPL')` at runtime, which returns the FOMC at 3 days because FOMC is sooner than AAPL Earnings (Apr 28). If you are unsure, read `mocks/events.ts` → `nextEventFor()` directly and trust the computed result over any static table.

---

## 5. CSS tokens

Complete token set. Never hardcode colors — always use these variables.

### Dark theme (default — `:root` and `[data-theme="dark"]`)

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

## 6. Primitives and component reference

### Primitive components

```tsx
// Text — body copy, labels, descriptions
<Text
  size={11 | 12 | 13 | 14}
  tone={'primary' | 'secondary' | 'dim' | 'pass' | 'caution' | 'reject'}
  weight={400 | 500 | 600}
/>
// Default: size=13, tone="primary", weight=400
// Do NOT use weight=600 on form labels.

// Title — headings
<Title as={'h1' | 'h2' | 'h3'} size={18 | 20 | 24} />

// Data — monospace, tabular-nums (prices, scores, percentages)
<Data
  size={11 | 12 | 13 | 14 | 16 | 18 | 20 | 24}
  weight={500 | 600}
  tone={'pass' | 'caution' | 'reject'}   // optional
/>
```

### Key atoms used in Step 5

| Component | Props | Notes |
|---|---|---|
| `StatusBadge` | `status: Status`, `label?: string` | Renders the GATE column badge |
| `EventFlag` | `days: number`, `title?: string` | Calendar icon + days count; colored by proximity |
| `WatchStar` | `symbol: string`, `size?: 'sm' \| 'md'` | Star column; writes to watchlistStore |

### Key molecules used in Step 5

| Component | Props | Notes |
|---|---|---|
| `TableRow` | `status: Status`, `columns: string`, `selected?: boolean`, `onClick?: () => void` | Status-tinted grid row; uses COLUMNS string for layout |

### Component folder convention

Each component lives in: `ComponentName/index.tsx` + `ComponentName.module.css`. Never import from a file path that skips a level.

---

## 7. Domain types

### Status type (from `lib/status.ts`)

```ts
type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA';
```

Valid display labels:

| Status | Display |
|---|---|
| PASS | "PASS" |
| CAUTION | "CAUTION" |
| REJECT | "REJECT" |
| PENDING | "PENDING" |
| NO_DATA | "NO DATA" |

Do NOT invent labels like "LONG", "SHORT", "Active".

### EventProximity type (from `lib/date.ts`)

```ts
export type EventProximity = 'distant' | 'near' | 'imminent';
```

### WatchlistRow (from `types/domain.ts`)

```ts
interface WatchlistRow {
  symbol:          string;
  company:         string;
  price:           number;
  direction:       'Bullish' | 'Bearish';
  horizon:         'Swing' | 'Position';
  score:           number;          // 0–100
  rankDelta:       number;          // position change vs last scan
  scoreDelta?:     number;          // score pts change
  status:          Status;
  breakdown:       ScoreBreakdown;
  nextEventDays?:  number;          // days to next earnings/FOMC/etc
  nextEventLabel?: string;          // "Earnings", "FOMC"
}
```

Step 5 reads `symbol`, `company`, `nextEventDays`, `nextEventLabel` from each row. It does not read `score`, `rankDelta`, `breakdown`, etc.

---

## 8. Zustand stores

Step 5 reads from `watchlistStore` (via `WatchStar`) but **writes nothing** directly to any store. `WatchStar` handles its own store interaction internally.

### watchlistStore — read interface only

```ts
// What WatchStar reads internally (you do not call this directly):
const starred: Set<string>   // set of starred symbol strings
const toggle: (symbol: string) => void
const isStarred: (symbol: string) => boolean
```

Step 5 does not need to import `watchlistStore` directly. Passing `symbol` to `<WatchStar symbol={r.symbol} size="sm" />` is sufficient.

---

## 9. Mock data — pre-computed acceptance table

Reference date for `nextEventFor`: `2026-04-20` (matches `scanStore.scanAt`).

**Key insight:** The FOMC event on `2026-04-23` (3 days from reference date) is a global event (symbol `'—'`) and fires for every symbol as their nearest event, unless the symbol has a sooner specific event. This makes all rows 'imminent' → `proxStatus = REJECT`.

The bar fill width formula: `barWidth = (ivRank / 100) * 120` pixels, inside a fixed 120px track.

| # | Symbol | ivRank | barWidth (px) | ivPctl | ivStatus | nextEventDays | nextEventLabel | eventProx | proxStatus | **gate** |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | AAPL | 86 | 103.2 | 93 | PASS | 3 | FOMC | imminent | REJECT | **REJECT** |
| 2 | NVDA | 47 | 56.4 | 57 | CAUTION | 1 | Earnings | imminent | REJECT | **REJECT** |
| 3 | MSFT | 74 | 88.8 | 69 | PASS | 3 | FOMC | imminent | REJECT | **REJECT** |
| 4 | META | 55 | 66.0 | 45 | CAUTION | 3 | FOMC | imminent | REJECT | **REJECT** |
| 5 | GOOGL | 56 | 67.2 | 47 | CAUTION | 3 | FOMC | imminent | REJECT | **REJECT** |
| 6 | AMZN | 30 | 36.0 | 23 | REJECT | 3 | FOMC | imminent | REJECT | **REJECT** |
| 7 | AMD | 50 | 60.0 | 42 | CAUTION | 3 | FOMC | imminent | REJECT | **REJECT** |
| 8 | TSLA | 38 | 45.6 | 46 | CAUTION | 0 | Earnings | imminent | REJECT | **REJECT** |
| 9 | NFLX | 62 | 74.4 | 59 | PASS | 3 | FOMC | imminent | REJECT | **REJECT** |
| 10 | INTC | 72 | 86.4 | 65 | PASS | 3 | FOMC | imminent | REJECT | **REJECT** |

**All 10 rows gate to REJECT.** This is correct given the mock data: FOMC is 3 days away (boundary value, `days <= 3` is 'imminent'), and every row is dominated by `proxStatus = REJECT`. The bar colors (ivFill_PASS / ivFill_CAUTION / ivFill_REJECT) still vary per row and reflect the individual IV status.

**TSLA note:** `nextEventDays = 0` because the TSLA Earnings event is on `2026-04-20` — the same day as the reference date. `daysUntil` returns 0 (`Math.ceil(0) = 0`). `d >= 0` is true so it qualifies. This is correct and expected.

---

## 10. Task spec — review checklist

Work through each item in order. Check, verify, and fix if needed.

---

### Item 1 — IV rank bar fill width (BUG CONFIRMED)

**What to check:** In `page.tsx`, the inline style on the `.ivFill` div.

**Current (buggy):**
```tsx
style={{ width: `${rank}%` }}
```

**Problem:** `rank` is a raw 0–89 number. Using it as a percentage makes the bar fill `rank%` of the container width — but the container (`.ivTrack`) has no fixed pixel width defined in CSS, so the fill is proportional to whatever `1fr` or surrounding layout gives. The spec requires an exact pixel fill within a fixed 120px track.

**Correct fix:**
```tsx
style={{ width: `${(rank / 100) * 120}px` }}
```

**How to verify:** With `rank = 86` (AAPL), the bar should be exactly `103.2px` wide inside a 120px track. Visually this is ~86% of the track. With `rank = 30` (AMZN), bar = `36px` = 30% of track.

**CSS check:** `.ivTrack` in `page.module.css` must have `width: 120px` (or `min-width: 120px`). Currently `.ivTrack` has no explicit width — the width comes from the COLUMNS grid allocation (`120px` for the IV rank column). The track fills the column. If the column is exactly 120px, percentage and pixel produce the same visual at 1440px. At 1200px however, if the column shrinks, percentage fills proportionally but the spec says bars should be fixed-scale. **Add `width: 120px` to `.ivTrack`** so the bar is always anchored to 120px regardless of viewport width. Then the pixel formula is strictly correct.

---

### Item 2 — Gate logic correctness

**What to check:** That `gate = worstStatus(ivSt, proxStatus)` is computed correctly for all 10 rows.

**How to verify:** Compare the rendered StatusBadge status against the acceptance table in Section 9. All 10 rows must show REJECT.

**If it fails:** The logic in `page.tsx` is:
```tsx
const prox = r.nextEventDays !== undefined ? eventProximity(r.nextEventDays) : 'distant';
const proxStatus: Status =
  prox === 'imminent' ? 'REJECT'
  : prox === 'near'   ? 'CAUTION'
  : 'PASS';
const gate: Status = worstStatus(ivSt, proxStatus);
```
This logic is correct. If the rendered output does not match, the issue is upstream in `MOCK_WATCHLIST` data or in `worstStatus` — check the read-only files for correctness first before touching page.tsx.

**ivFill class:** Verify the CSS class applied is `pageStyles[`ivFill_${ivSt}`]` (ivStatus, not gate). The bar color reflects IV status; the row tint and gate badge reflect the gate. This distinction is intentional and correct.

---

### Item 3 — All 10 rows present

**What to check:** `MOCK_WATCHLIST.map(...)` renders 10 `<TableRow>` elements.

**How to verify:** Count rendered rows in browser or grep for `MOCK_WATCHLIST` length (`MOCK_WATCHLIST.length === 10`).

**If it fails:** `MOCK_WATCHLIST` in `mocks/watchlist.ts` should have exactly 10 entries. Verify the import is `import { MOCK_WATCHLIST } from '@/mocks/watchlist'`. Do not modify the mock.

---

### Item 4 — NEXT EVENT column alignment at 1200px viewport

**What to check:** At exactly 1200px viewport width, the NEXT EVENT column (110px in COLUMNS) shows the `EventFlag` without overflow, truncation, or column bleed.

**COLUMNS string:** `'32px 72px 1fr 120px 70px 110px 80px'`

At 1200px the available content width is approximately:
`1200px - NavRail(64px) - ContextRail(0 if hidden) - padding(48px) = ~1088px`

The fixed columns total: `32 + 72 + 120 + 70 + 110 + 80 = 484px`. The `1fr` name column gets `1088 - 484 = 604px`. This is generous — the NEXT EVENT column (110px) should be fine.

**How to verify:** In browser DevTools, resize to 1200px wide. Check:
1. No horizontal scrollbar appears on the table
2. The NEXT EVENT column content (`EventFlag`) does not overflow into adjacent columns
3. Text in all columns is readable (not clipped by `overflow: hidden`)

**Potential fix if NEXT EVENT clips:** Add to `.tableHeader` and ensure `TableRow` uses `overflow: hidden` per cell. If `EventFlag` has a fixed width wider than 110px, that is a bug in the EventFlag atom (read-only) — document it as a known issue rather than hacking around it in page.tsx.

**Check `min-width` on `.ivTrack`:** If the IV rank column content overflows due to the fixed `120px` track, add `overflow: hidden` to `.ivRankCell` or ensure the track respects the column boundary.

---

### Item 5 — TypeScript errors

**What to check:** `npm run typecheck` exits with 0 errors.

**How to verify:**
```bash
cd frontend
npm run typecheck
```

**Common failure modes to look for:**
- `pageStyles[\`ivFill_${ivSt}\`]` — TypeScript may complain about template literal index into CSS module type. If so, cast: `(pageStyles as Record<string, string>)[\`ivFill_${ivSt}\`]`
- Any use of `any` — avoid; use proper types from `lib/status.ts` and `types/domain.ts`

---

### Item 6 — `.ivTrack` width anchoring (CSS fix)

**What to check:** `.ivTrack` in `page.module.css` must have an explicit `width: 120px` so the pixel-based fill formula is always anchored correctly, independent of layout context.

**Current state:** `.ivTrack` only has `height`, `background`, `border-radius`, `overflow`. It relies on its parent `.ivRankCell` (which is in a `120px` grid column) for width. This works at large viewports but is fragile.

**Fix:** Add `width: 120px` to `.ivTrack` in `page.module.css`.

---

## 11. Hard rules

These rules are absolute. Do not violate them.

1. Do not add Tailwind, styled-components, or any CSS-in-JS library.
2. Do not add inline `style={{}}` for anything other than computed one-off values (e.g. `style={{ width: \`${(rank/100)*120}px\` }}`). The IV rank bar fill IS the allowed one-off exception — use it.
3. Do not hardcode colours — always use CSS custom properties from `tokens.css` (listed in Section 5).
4. Do not invent new Status labels. The only valid values are `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. Do not use font-weight 600 on form labels.
6. Do not add card box-shadows — use `border: 1px solid var(--border-subtle)`.
7. Do not skip component hierarchy levels (atom → molecule → organism).
8. Do not commit with a failing `npm run typecheck`.
9. Do not touch `node_modules/` or `package-lock.json` unless explicitly asked.
10. **Do not modify `screener.module.css`** — it is shared across all 7 steps.
11. **Do not change the `COLUMNS` string** without documenting why and what specific layout problem requires the change.
12. **The IV rank bar fill MUST use** `style={{ width: \`${(rank / 100) * 120}px\` }}` — this is the allowed one-off inline style. Do not use a CSS class for the fill width.

---

## 12. Dev workflow

```bash
cd frontend
npm run dev          # Starts at localhost:3001 — navigate to /screener/step-5-vol-events
npm run typecheck    # Must exit clean (0 errors) before any commit
```

**Visual verification steps:**
1. Open `http://localhost:3001/screener/step-5-vol-events`
2. Confirm 10 rows render
3. Confirm all GATE badges show REJECT (because FOMC is 3 days away in mock data)
4. Confirm IV rank bars are visually proportional to their rank values (AAPL bar longest at 86, AMZN shortest at 30)
5. Confirm bar colors: AAPL/MSFT/NFLX/INTC bars are `--pass` color; NVDA/META/GOOGL/AMD/TSLA bars are `--caution` color; AMZN bar is `--reject` color
6. Open DevTools → resize to exactly 1200px wide → confirm no horizontal scroll and NEXT EVENT column is readable

---

## 13. Copy/paste prompt

Paste exactly this text to the implementing LLM session:

---

Read `llm-contexts/07-step5-polish.md` first. Then read the files listed in Section 2 and 3.

You are polishing Step 5 (Volatility + Events gate) of the Bamendjou options screener.

**Owned files (modify only these):**
- `frontend/app/(frame)/screener/step-5-vol-events/page.tsx`
- `frontend/app/(frame)/screener/step-5-vol-events/page.module.css`

**Two confirmed bugs to fix:**

**Bug 1 — IV rank bar fill uses percentage instead of pixels.**
In `page.tsx`, line 89:
```tsx
style={{ width: `${rank}%` }}
```
Change to:
```tsx
style={{ width: `${(rank / 100) * 120}px` }}
```
This is the allowed one-off inline style exception per the project rules.

**Bug 2 — `.ivTrack` has no explicit width.**
In `page.module.css`, the `.ivTrack` rule does not have `width: 120px`. Add it:
```css
.ivTrack {
  width: 120px;
  height: 3px;
  background: var(--bg-surface-2);
  border-radius: 2px;
  overflow: hidden;
}
```

**Then verify:**
1. 10 rows render. All 10 GATE badges must show REJECT (FOMC is 3 days away in mock data — all rows are 'imminent').
2. IV rank bars have correct pixel fill per the acceptance table below.
3. At 1200px viewport width, no horizontal scroll and NEXT EVENT column (110px) is readable.
4. `npm run typecheck` exits clean.

**Acceptance table — all 10 rows (pre-computed):**

| # | Symbol | ivRank | barWidth (px) | ivPctl | ivStatus | nextEventDays | nextEventLabel | gate |
|---|---|---|---|---|---|---|---|---|
| 1 | AAPL | 86 | 103.2 | 93 | PASS | 3 | FOMC | REJECT |
| 2 | NVDA | 47 | 56.4 | 57 | CAUTION | 1 | Earnings | REJECT |
| 3 | MSFT | 74 | 88.8 | 69 | PASS | 3 | FOMC | REJECT |
| 4 | META | 55 | 66.0 | 45 | CAUTION | 3 | FOMC | REJECT |
| 5 | GOOGL | 56 | 67.2 | 47 | CAUTION | 3 | FOMC | REJECT |
| 6 | AMZN | 30 | 36.0 | 23 | REJECT | 3 | FOMC | REJECT |
| 7 | AMD | 50 | 60.0 | 42 | CAUTION | 3 | FOMC | REJECT |
| 8 | TSLA | 38 | 45.6 | 46 | CAUTION | 0 | Earnings | REJECT |
| 9 | NFLX | 62 | 74.4 | 59 | PASS | 3 | FOMC | REJECT |
| 10 | INTC | 72 | 86.4 | 65 | PASS | 3 | FOMC | REJECT |

**Bar fill colors (ivStatus, not gate):**
- PASS (rank >= 60): AAPL, MSFT, NFLX, INTC → `var(--pass)` #26A69A
- CAUTION (35 <= rank < 60): NVDA, META, GOOGL, AMD, TSLA → `var(--caution)` #F59F00
- REJECT (rank < 35): AMZN → `var(--reject)` #EF5350

Do not modify `screener.module.css`, `lib/date.ts`, `lib/status.ts`, `mocks/watchlist.ts`, or `mocks/events.ts`.

After making changes, run `npm run typecheck` and confirm 0 errors. Report what you changed and any issues found.

---
