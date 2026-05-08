# Bamendjou — LLM Context: Calendar Page

> **How to use this file**
> You are working on one specific page of the Bamendjou options screener (Next.js 15, TypeScript).
> Read every section before touching any code. This document is self-contained — you do not need any other file to complete the task.
> All work lives in `frontend/`. The project root only contains config and documentation files.

---

## Section 1 — Mission

**Conflict class: Zero conflict.** This workstream owns only the two calendar page files listed below. No other page, store, or shared file is touched.

**Goal:** Build a polished Calendar page that displays upcoming market events (earnings, FOMC, expirations, macro releases, etc.) in a month-grid layout. The page shows 6 months side-by-side, with event dots colored by proximity status. Clicking a day reveals a detail panel listing that day's events. Navigation controls allow stepping forward/backward one month at a time plus a "Today" shortcut.

**What NOT to touch:**
- `frontend/styles/tokens.css` or `frontend/app/globals.css`
- `frontend/types/domain.ts`
- Any file outside the owned list below
- Any other page (`dashboard/`, `watchlist/`, `portfolio/`, `settings/`, screener steps)
- Any Zustand store
- Any component in `components/` (read-only — use as-is)
- Any mock file (read-only — import only)

**No ContextRail slot for this page.** The frame layout already renders TopBar and NavRail — the calendar page content fills the remaining space directly.

---

## Section 2 — Owned files

| File path | Create/Modify | Purpose |
|---|---|---|
| `frontend/app/(frame)/calendar/page.tsx` | Modify | Implement full calendar page content (month grids, navigation, day detail panel) |
| `frontend/app/(frame)/calendar/page.module.css` | Modify | All calendar-specific CSS; no styles bleed into other pages |

Both files already exist (the page has a stub). Rewrite them fully to implement the spec in Section 10.

---

## Section 3 — Read-only references

These files are imported and used but never modified.

| File | How it is used |
|---|---|
| `frontend/mocks/events.ts` | Import `MOCK_EVENTS` (the event array) — display data only |
| `frontend/types/domain.ts` | Import the `UpcomingEvent` interface |
| `frontend/components/atoms/EventFlag/index.tsx` | Import `EventFlag` atom — calendar icon + days display |
| `frontend/components/atoms/StatusDot/index.tsx` | Import `StatusDot` atom — colored circle in the detail panel |
| `frontend/components/atoms/StatusBadge/index.tsx` | Import `StatusBadge` atom — status pill in the detail panel |
| `frontend/components/primitives/index.ts` | Import `Text`, `Title`, `Data` primitives |
| `frontend/lib/status.ts` | Import `Status` type |
| `frontend/lib/date.ts` | Import `eventProximity` helper (used internally by `EventFlag`) |

---

## Section 4 — Integration constraints

### Exact import statements

```tsx
// Types
import type { UpcomingEvent } from '@/types/domain';
import type { Status } from '@/lib/status';

// Primitives (all from the barrel)
import { Title, Text, Data } from '@/components/primitives';

// Atoms
import { EventFlag }    from '@/components/atoms/EventFlag';
import { StatusBadge }  from '@/components/atoms/StatusBadge';
import { StatusDot }    from '@/components/atoms/StatusDot';

// Mock data
import { MOCK_EVENTS }  from '@/mocks/events';

// CSS module
import styles from './page.module.css';
```

### What the frame layout provides

The `(frame)/layout.tsx` already renders:
- **TopBar** (48px, fixed top)
- **NavRail** (64px, fixed left)

The calendar page content fills the remaining viewport area. There is **no ContextRail slot** for the calendar route — do not add one.

### Event proximity status derivation

The `UpcomingEvent.status` field on each mock event is pre-computed from its date relative to a reference date. The rules that produced those values (and that you must apply when computing proximity for display) are:

| Days until event | Proximity label | Status color |
|---|---|---|
| `days <= 3` | `'imminent'` | `REJECT` — use `var(--reject)` |
| `days <= 7` | `'near'` | `CAUTION` — use `var(--caution)` |
| `days > 7` | `'distant'` | `PASS` — use `var(--pass)` |

The `EventFlag` atom already encodes this logic internally via `eventProximity(days)` from `lib/date.ts`. You only need to pass it the `days` prop.

When computing days for the **detail panel's EventFlag**, calculate days from the session anchor date (`TODAY`) to the selected date using UTC arithmetic:

```ts
const days = Math.round((selectedDate.getTime() - TODAY.getTime()) / 86_400_000);
```

The session anchor is `new Date('2026-04-18T00:00:00Z')` — this matches the rest of the app. Do not use `new Date()` (wall clock) because the mock data is anchored to April 2026.

---

## Section 5 — CSS tokens

All CSS custom properties come from `frontend/styles/tokens.css` (imported via `frontend/app/globals.css`). **Never hardcode colors or spacing.** Use only the variables listed below.

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

### `<Text>`

```tsx
<Text
  size={11 | 12 | 13 | 14}
  tone={'primary' | 'secondary' | 'dim' | 'pass' | 'caution' | 'reject'}
  weight={400 | 500 | 600}
/>
```

Default: `size=13`, `tone="primary"`, `weight=400`. Renders as a `<span>`.

### `<Title>`

```tsx
<Title as={'h1' | 'h2' | 'h3'} size={18 | 20 | 24} />
```

Use `as="h1" size={24}` for the page title.

### `<Data>`

```tsx
<Data
  size={11 | 12 | 13 | 14 | 16 | 18 | 20 | 24}
  weight={500 | 600}
  tone={'pass' | 'caution' | 'reject'}   // optional
/>
```

Monospace, tabular-nums. Use for day numbers, date labels, counts.

### Key atoms for this page

#### `EventFlag`

```tsx
import { EventFlag } from '@/components/atoms/EventFlag';

// Props:
interface EventFlagProps {
  days: number;      // Days until event. Negative → renders nothing.
  title?: string;    // Optional tooltip / a11y label.
  className?: string;
}

// Example:
<EventFlag days={3} title="3 days to FOMC" />
```

`EventFlag` internally calls `eventProximity(days)` from `lib/date.ts` and applies a CSS class (`distant` / `near` / `imminent`) that colors the calendar icon and the "Nd" text. You do not need to pass a color — just pass the number of days.

#### `StatusBadge`

```tsx
import { StatusBadge } from '@/components/atoms/StatusBadge';

// Props:
interface StatusBadgeProps {
  status: Status;      // 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA'
  label?: string;      // Override the default label string
  className?: string;
}

// Example:
<StatusBadge status="CAUTION" />
// renders: "CAUTION" pill with caution tint
```

#### `StatusDot`

```tsx
import { StatusDot } from '@/components/atoms/StatusDot';

// Props:
interface StatusDotProps {
  tone: Status | 'ACCENT';
  size?: 'sm' | 'md';   // default 'md'
  className?: string;
}

// Example (used in the existing detail panel):
<StatusDot tone={ev.status} size="sm" />
```

### Component conventions

- **Atoms → Molecules → Organisms** — never skip levels. The calendar page uses atoms (`EventFlag`, `StatusBadge`, `StatusDot`) directly inside the page component, which is correct for a page-level layout.
- Each component lives in its own folder: `ComponentName/index.tsx` + `ComponentName.module.css`.
- **No card shadows** — use `border: 1px solid var(--border-subtle)` instead.
- Status tints use `color-mix(in srgb, var(--pass/caution/reject) N%, var(--bg-surface))`.

---

## Section 7 — Domain types

### `Status` (from `frontend/lib/status.ts`)

```ts
export type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA';

export const STATUS_LABEL: Record<Status, string> = {
  PASS:    'PASS',
  CAUTION: 'CAUTION',
  REJECT:  'REJECT',
  PENDING: 'PENDING',
  NO_DATA: 'NO DATA',
};
```

### `UpcomingEvent` (from `frontend/types/domain.ts`)

```ts
export interface UpcomingEvent {
  date:    string;   // ISO date string, e.g. "2026-04-20"
  symbol:  string;   // Ticker, e.g. "AAPL", or "—" for market-wide events
  label:   string;   // Human-readable event label, e.g. "Earnings", "FOMC"
  status:  Status;   // Pre-computed proximity gate: 'PASS' | 'CAUTION' | 'REJECT'
}
```

`status` is pre-set in the mock data based on proximity to the reference date. It reflects the event gate status that was computed at scan time (not live from wall clock).

---

## Section 8 — Zustand stores

**This workstream does not use any Zustand store.**

The Calendar page is read-only and display-only. It imports mock data directly and holds only local React state (selected date, month anchor). No store reads or writes are needed.

---

## Section 9 — Mock data (exact values)

File: `frontend/mocks/events.ts`

The mock exports `MOCK_EVENTS: UpcomingEvent[]` plus two utility functions (`daysUntil`, `nextEventFor`). Import only `MOCK_EVENTS` in the calendar page.

The reference date used internally by the mock utilities is `'2026-04-20'`. The session anchor for the calendar UI (`TODAY`) is `'2026-04-18'` — this is a deliberate 2-day offset matching the rest of the app's mock setup.

### Complete mock data (every event, every field)

```ts
// --- April 2026 (near-term) ---
{ date: '2026-04-20', symbol: 'TSLA',  label: 'Earnings',           status: 'REJECT'  },
{ date: '2026-04-21', symbol: 'NVDA',  label: 'Earnings',           status: 'CAUTION' },
{ date: '2026-04-23', symbol: '—',     label: 'FOMC',               status: 'CAUTION' },
{ date: '2026-04-28', symbol: 'AAPL',  label: 'Earnings',           status: 'CAUTION' },
{ date: '2026-04-29', symbol: 'META',  label: 'Earnings',           status: 'PASS'    },
{ date: '2026-04-30', symbol: 'MSFT',  label: 'Earnings',           status: 'CAUTION' },

// --- May 2026 ---
{ date: '2026-05-01', symbol: 'AMZN',  label: 'Earnings',           status: 'PASS'    },
{ date: '2026-05-06', symbol: '—',     label: 'ISM Services PMI',   status: 'PASS'    },
{ date: '2026-05-14', symbol: '—',     label: 'CPI release',        status: 'CAUTION' },
{ date: '2026-05-15', symbol: '—',     label: 'Monthly expiration', status: 'CAUTION' },
{ date: '2026-05-21', symbol: 'NVDA',  label: 'Earnings (Q1)',      status: 'REJECT'  },
{ date: '2026-05-28', symbol: 'CRM',   label: 'Earnings',           status: 'CAUTION' },

// --- June 2026 ---
{ date: '2026-06-04', symbol: '—',     label: 'ECB rate decision',  status: 'PASS'    },
{ date: '2026-06-11', symbol: '—',     label: 'CPI release',        status: 'CAUTION' },
{ date: '2026-06-17', symbol: '—',     label: 'FOMC + dot plot',    status: 'REJECT'  },
{ date: '2026-06-19', symbol: '—',     label: 'Triple witching',    status: 'CAUTION' },
{ date: '2026-06-25', symbol: 'NKE',   label: 'Earnings',           status: 'PASS'    },
{ date: '2026-06-30', symbol: 'MU',    label: 'Earnings',           status: 'CAUTION' },

// --- July 2026 ---
{ date: '2026-07-02', symbol: '—',     label: 'NFP jobs report',    status: 'CAUTION' },
{ date: '2026-07-14', symbol: 'JPM',   label: 'Earnings',           status: 'PASS'    },
{ date: '2026-07-15', symbol: '—',     label: 'CPI release',        status: 'CAUTION' },
{ date: '2026-07-17', symbol: '—',     label: 'Monthly expiration', status: 'CAUTION' },
{ date: '2026-07-22', symbol: 'TSLA',  label: 'Earnings',           status: 'REJECT'  },
{ date: '2026-07-23', symbol: 'GOOGL', label: 'Earnings',           status: 'CAUTION' },
{ date: '2026-07-29', symbol: '—',     label: 'FOMC',               status: 'REJECT'  },
{ date: '2026-07-30', symbol: 'AAPL',  label: 'Earnings',           status: 'CAUTION' },
{ date: '2026-07-30', symbol: 'AMZN',  label: 'Earnings',           status: 'CAUTION' },
{ date: '2026-07-31', symbol: 'XOM',   label: 'Earnings',           status: 'PASS'    },

// --- August 2026 ---
{ date: '2026-08-06', symbol: '—',     label: 'BoE rate decision',  status: 'PASS'    },
{ date: '2026-08-12', symbol: '—',     label: 'CPI release',        status: 'CAUTION' },
{ date: '2026-08-21', symbol: '—',     label: 'Monthly expiration', status: 'CAUTION' },
{ date: '2026-08-27', symbol: 'NVDA',  label: 'Earnings (Q2)',      status: 'REJECT'  },
{ date: '2026-08-28', symbol: '—',     label: 'Jackson Hole close', status: 'CAUTION' },

// --- September 2026 ---
{ date: '2026-09-04', symbol: '—',     label: 'NFP jobs report',    status: 'CAUTION' },
{ date: '2026-09-10', symbol: '—',     label: 'ECB rate decision',  status: 'PASS'    },
{ date: '2026-09-11', symbol: '—',     label: 'CPI release',        status: 'CAUTION' },
{ date: '2026-09-16', symbol: '—',     label: 'FOMC + projections', status: 'REJECT'  },
{ date: '2026-09-18', symbol: '—',     label: 'Triple witching',    status: 'CAUTION' },
{ date: '2026-09-24', symbol: 'COST',  label: 'Earnings',           status: 'PASS'    },
```

**Total: 39 events across 6 months (April–September 2026).**

Note: `symbol: '—'` (em-dash) denotes market-wide events not tied to a single ticker.

`UpcomingEvent.status` is set in the mock to reflect the pre-computed proximity at scan time. For the dot colors on the calendar grid, use `ev.status` directly — do not recompute from wall clock. For the `EventFlag` in the detail panel header, compute days from `TODAY` to the selected date and pass as `days` prop.

---

## Section 10 — Task spec

### What the Calendar page must show

#### 1. Page header

```tsx
<Title as="h1" size={24}>Calendar</Title>
<Text size={13} tone="secondary">
  {totalEventsInView} event{n === 1 ? '' : 's'} · earnings, FOMC, expirations
</Text>
```

`totalEventsInView` is the count of events whose dates fall within any of the 6 currently-visible month grids (counting only in-month days that have events).

#### 2. Month navigation bar

A full-width bar containing:
- Left arrow button `←` (Previous month)
- Center label: range from first to last displayed month, e.g. `"April 2026  –  September 2026"` using `<Data size={14} weight={500}>`
- Right side: `"Today"` button + right arrow button `→` (Next month)

Clicking Previous/Next shifts the 6-month window by 1 month. Clicking Today resets the anchor to the current month.

Style: `background: var(--bg-surface)`, `border: 1px solid var(--border-subtle)`, `border-radius: var(--radius-lg)`.

#### 3. Month grid (6 month cards, side-by-side)

Display 6 months in a responsive grid (`repeat(auto-fit, minmax(260px, 1fr))`).

Each month card contains:
- **Month header**: month + year label on the left, event-day count on the right (e.g. `"3 days with events"`)
- **Week day labels row**: Mon Tue Wed Thu Fri Sat Sun (7 columns, `<Text size={11} tone="dim">`)
- **Day grid**: 42 cells (6 weeks × 7 days), week starts Monday. Leading/trailing days from adjacent months are included but visually dimmed and non-interactive.

**Day cell states:**
- Default: transparent background
- Hover (in-month): `background: var(--bg-surface-2)`
- Today: `border-color: var(--accent)` ring
- Selected: `box-shadow: inset 0 0 0 2px var(--accent)`, `background: var(--bg-surface-2)`
- Out-of-month: `opacity: 0.4`, `cursor: default`, `disabled`

**Event dot:**
When a day has events, show a small colored dot (5×5px circle) below the day number. Color is determined by the highest-severity status among the day's events:
- Any REJECT event → `var(--reject)`
- Any CAUTION (no REJECT) → `var(--caution)`
- All PASS → `var(--pass)`

If there are 2+ events, show a second dot at 50% opacity.

#### 4. Day detail panel

A panel below the month grids (full width). Initially shows today's date and any events on it.

**Header:** formatted date on the left (e.g. `"Friday, Apr 18, 2026"`) using `<Data size={14} weight={500}>`. If the selected day has events, show an `<EventFlag days={...} />` on the right, where `days` is the number of days from `TODAY` to `selectedDate`.

**Event list:** When events exist, render a `<ul>` with one `<li>` per event:
```
[StatusDot tone={ev.status} size="sm"]  [symbol]  [label]
```
Using a 3-column grid: `14px 72px 1fr`.

Separate event rows with a `border-bottom: 1px solid var(--border-subtle)` (last row has no border).

**Empty state:** When no events on the selected day:
```
<Text size={13} tone="dim">No events on this day.</Text>
```
When no day is selected:
```
<Text size={13} tone="dim">Pick a day to see its events.</Text>
```

The detail panel has `min-height: 360px` and uses `aria-live="polite"` for accessibility.

**Out-of-range navigation:** MOCK_EVENTS covers April–September 2026. When the user navigates to a month outside that range (e.g. October 2026 or March 2026), the month grids render normally with no event dots. The subtitle reads "0 events" for that view window. Do NOT hide the grids or throw an error — just show empty calendars. The month-header event-day count shows "0 days with events".

### Acceptance criteria

- All 39 events from `MOCK_EVENTS` render in the correct month/day cells.
- Month grids correctly build 6-week (42-cell) grids, week starts Monday.
- Leading/trailing out-of-month days are dimmed and non-interactive.
- Today's cell has an accent-colored border ring.
- Selected cell has an inset accent box-shadow.
- Event dots appear on days with events, colored by highest-severity status.
- Detail panel updates when a day is selected.
- `EventFlag` atom is used in the detail panel header (not custom markup).
- `StatusDot` atom is used in each event row in the detail panel.
- Proximity coloring is correct: REJECT events → red dots, CAUTION → amber, PASS → green.
- `npm run typecheck` passes with zero errors.
- No TypeScript `any` casts introduced.

---

## Section 11 — Hard rules

1. Do not add Tailwind, styled-components, or any CSS-in-JS library.
2. Do not add inline `style={{}}` for anything other than computed one-off values (e.g. `style={{ opacity: 0.5 }}`).
3. Do not hardcode colors — always use CSS custom properties from `tokens.css`.
4. Do not invent new Status labels. The only valid values are `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. Do not use font-weight 600 on form labels.
6. Do not add card box-shadows — use `border: 1px solid var(--border-subtle)`.
7. Do not skip component hierarchy levels (atom → molecule → organism).
8. Do not commit with a failing `npm run typecheck`.
9. Do not touch `node_modules/` or `package-lock.json` unless explicitly asked.
10. Event proximity status (`ev.status`) is pre-set in the mock data — use it directly for dot/badge colors; do not recompute status from dates.
11. The session anchor `TODAY` must be `new Date('2026-04-18T00:00:00Z')` — do not use `new Date()` (wall clock). The mock data is anchored to April 2026 and using wall clock will break all proximity calculations.
12. The `EventFlag` atom's `days` prop should be computed from `TODAY` to `selectedDate` using UTC arithmetic. Pass the result to `<EventFlag days={days} />` — do not write a custom days-display widget.
13. `StatusBadge` receives a `Status` value (e.g. `ev.status`), not a raw string or a derived label.
14. Do not add a Zustand store for this page. All state is local (`useState`).
15. All UTC date math must use `getUTCFullYear()`, `getUTCMonth()`, `getUTCDate()` — never the local-time variants — to avoid timezone-shifted day boundaries.

---

## Section 12 — Dev workflow

```bash
cd frontend
npm run dev       # localhost:3001 — navigate to /calendar
npm run typecheck # tsc --noEmit — must be clean before committing
npm run lint      # next lint — check for ESLint issues
```

The frame layout (`app/(frame)/layout.tsx`) renders `TopBar` and `NavRail` automatically for all routes under `(frame)/`. You only need to write the page content; the shell is already in place.

Min-width gate: the app shows a "rotate / resize" message for viewports below 1200px. This is handled globally — you do not need to add it.

---

## Section 13 — Copy/paste prompt

Paste the following block verbatim to the implementing LLM as its first message:

---

```
You are implementing the Calendar page for the Bamendjou options screener (Next.js 15, TypeScript strict).

Your complete specification is in:
  llm-contexts/04-calendar.md

Read that file in full before writing any code.

OWNED FILES (only these two):
  frontend/app/(frame)/calendar/page.tsx        — rewrite with full implementation
  frontend/app/(frame)/calendar/page.module.css — rewrite with all needed styles

KEY CONSTRAINTS:
  - Add 'use client'; at the top of page.tsx (uses useState/useMemo)
  - Session anchor: const TODAY = new Date('2026-04-18T00:00:00Z');  — never new Date()
  - All date math uses UTC methods (getUTCFullYear, getUTCMonth, getUTCDate)
  - Import MOCK_EVENTS from '@/mocks/events'; — read-only, never modify
  - Import UpcomingEvent from '@/types/domain';
  - Import Status from '@/lib/status';
  - Import primitives: { Title, Text, Data } from '@/components/primitives';
  - Import EventFlag from '@/components/atoms/EventFlag';
  - Import StatusBadge from '@/components/atoms/StatusBadge';
  - Import StatusDot from '@/components/atoms/StatusDot';
  - CSS Modules only — no Tailwind, no inline styles except one-off computed values
  - All colors via CSS custom properties from tokens.css — no hardcoded hex values
  - No Zustand stores — local useState only

LAYOUT TO IMPLEMENT:
  1. Page header: <Title> "Calendar" + <Text> event count subtitle
  2. Month nav bar: ← Prev | "April 2026 – September 2026" | Today | → Next
  3. Six month grids side-by-side (responsive, auto-fit minmax 260px 1fr)
     - Each month: 42-cell 6-week grid, week starts Monday
     - Day cells: today border ring (--accent), selected inset ring, out-of-month dimmed+disabled
     - Event dots (5×5px circles) colored by highest-severity status on that day
  4. Day detail panel (full width, min-height 360px):
     - Header: formatted date + EventFlag atom (days from TODAY to selected)
     - Event list rows: StatusDot + symbol + label (grid 14px 72px 1fr)
     - Empty state text when no events

ACCEPTANCE:
  - All 39 mock events visible in correct cells (MOCK_EVENTS has exactly 39 entries — verify count).
  - Event proximity coloring correct: ≤3 days from TODAY → reject, ≤7 → caution, >7 → pass.
  - Navigating to a month with no mock events shows an empty grid with no dots; the subtitle
    should read "0 events" for that month view rather than crashing or hiding the grid.
  - npm run typecheck passes clean.
```

---
