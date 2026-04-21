# Bamendjou Frontend — Implementation Plan

## Overview

This plan builds the Bamendjou frontend as a Next.js App Router project in six phases. The plan is executable by Claude Code in follow-up sessions, but every decision is explained so a non-coder can read along.

The guiding principle: **the spec and the drift log are the contract**. Every architectural choice below exists to make a drifted Stitch item impossible to recreate in React.

---

## Phase 1 — Project Foundation

### 1.1 Scaffold

- **Tool**: `create-next-app` with TypeScript, ESLint, App Router, Tailwind CSS off by default. We will NOT use Tailwind — the spec is token-driven and Tailwind would dilute token enforcement. We use CSS Modules + CSS custom properties.
- **Trade-off called out**: Tailwind would speed up class-level styling but it encourages ad-hoc color/font/spacing values (exactly what Stitch did). Our job is to make the wrong value hard to type. Plain CSS custom properties + CSS Modules wins here.
- **Node**: pin to an LTS (20.x or 22.x) via `.nvmrc`.

### 1.2 Directory structure (App Router)

```
/app
  layout.tsx              ← root layout: fonts, theme attr, global CSS
  page.tsx                ← redirects to /dashboard
  globals.css             ← all design tokens
  (frame)/                ← route group — everything that lives inside the persistent frame
    layout.tsx            ← persistent frame (top bar + nav rail + context rail)
    dashboard/page.tsx
    watchlist/page.tsx
    portfolio/page.tsx
    calendar/page.tsx
    settings/page.tsx
    screener/
      layout.tsx          ← overrides nav rail with stepper
      step-1-universe/page.tsx
      step-2-direction/page.tsx
      step-3-regime/page.tsx
      step-4-ranking/page.tsx
      step-5-vol-events/page.tsx
      step-6-contracts/page.tsx
      step-7-trade-card/page.tsx
/components
  atoms/
  molecules/
  organisms/
  primitives/             ← Text, Data, Mono (font-enforcement components — see Phase 2.3)
/lib
  tokens.ts               ← typed token name constants (for autocomplete)
  status.ts               ← PASS/CAUTION/REJECT type + helpers
  date.ts                 ← DTE math for progress bars
  theme.ts                ← theme provider (client component)
/styles
  tokens.css              ← imported into globals.css — dark + light tokens
  reset.css
/types
  domain.ts               ← Symbol, Contract, Alert, Position types
/mocks
  dashboard.ts, watchlist.ts, portfolio.ts, tradecard.ts  ← fixture data for v1
```

**Why App Router + route groups**: The `(frame)` route group lets the persistent top bar/nav rail/context rail live in one layout that wraps every page. The `screener/layout.tsx` can nest and override just the nav rail region. That is exactly what the spec calls for (rail-to-stepper transform, G4) without any manual state syncing.

### 1.3 Font loading via `next/font`

In `app/layout.tsx`:

```ts
import { Sora, DM_Sans, JetBrains_Mono } from 'next/font/google'

const sora = Sora({ subsets: ['latin'], weight: ['700'], variable: '--font-sora' })
const dm   = DM_Sans({ subsets: ['latin'], weight: ['400','500','600'], variable: '--font-dm' })
const mono = JetBrains_Mono({ subsets: ['latin'], weight: ['400','500'], variable: '--font-mono' })
```

Classes are attached to `<html>` so the three `--font-*` variables are available everywhere. No FOUT, no arbitrary `font-family` strings anywhere else in the app.

### 1.4 Deliverable
Empty project that renders a blank page in dark mode with all three fonts loaded. Tokens import compiles without errors.

---

## Phase 2 — Design System Foundation

### 2.1 Token encoding — CSS custom properties driven by `data-theme`

**Recommendation**: CSS custom properties in `styles/tokens.css`, switched by a `data-theme="dark|light"` attribute on `<html>`.

```css
:root, [data-theme="dark"] {
  --bg-base: #131722;
  --bg-surface: #1E2335;
  /* ...all dark tokens verbatim from spec Section 1... */
}
[data-theme="light"] {
  --bg-base: #F0F3FA;
  /* ...all light tokens verbatim from spec Section 1... */
}
```

**Why not other approaches**:
- **Tailwind theme config**: couples tokens to utility class names; harder to read spec → code.
- **CSS-in-JS (styled-components / Emotion)**: runtime cost, plus App Router RSC friction.
- **Separate stylesheets per theme**: requires a full reload to toggle; custom properties swap instantly.

The `data-theme` attribute is the simplest switch and can be persisted to localStorage by a tiny client-side `ThemeProvider`.

Token names are **exact** copies from spec Section 1 — no renaming. That means any contributor can Ctrl-F the spec token name and find it in CSS.

### 2.2 Typed token constants

`lib/tokens.ts` re-exports every token name as a string constant so TypeScript autocomplete offers only valid tokens:

```ts
export const TOKENS = {
  bg: { base: 'var(--bg-base)', surface: 'var(--bg-surface)', /* ... */ },
  text: { primary: 'var(--text-primary)', /* ... */ },
  status: { pass: 'var(--pass)', caution: 'var(--caution)', /* ... */ },
} as const
```

Used only when a component needs to compute a style in JS (e.g. chart candle colors).

### 2.3 Three-font rule enforcement — THE KEY DECISION

**Chosen approach**: Three typed primitive components — `<Text>`, `<Data>`, `<Title>` — in `/components/primitives/`. All text in the app goes through exactly one of these. Raw `<div>Hello</div>` with string content is caught by an ESLint rule.

```tsx
// Title — Sora 700 only. H1/wordmark.
<Title as="h1" size={24}>Dashboard</Title>

// Text — DM Sans. UI, labels, nav, body, buttons.
<Text size={13} weight={500}>Run Scan</Text>

// Data — JetBrains Mono. ALL numeric/tickers/timestamps.
<Data size={12}>$185.20</Data>
```

Each primitive hard-codes its font family via a CSS module class — you cannot pass a different font. `size` and `weight` are constrained to values that exist in the spec size table (Section 2). Passing `size={17}` is a TypeScript error.

**Why this over alternatives**:
- **Utility classes (`className="font-mono"`)**: easy to forget or misuse. Developer has to actively think "is this data?"
- **ESLint rule against bare text nodes**: a good backstop, not a substitute.
- **Typed components**: the React tree reads as a statement of intent — `<Data>185.20</Data>` is self-documenting. Reviewer can scan a file and see every font decision at a glance.

**Supplementary ESLint rule**: `no-restricted-syntax` blocking bare JSX text of more than a few characters outside primitive components. Not perfect but catches 90% of slip-ups.

This addresses drift items **G1, Screen 0 #5/6/7, Screen 6 #4**.

### 2.4 Deliverable
Working dark/light toggle on a blank page. The three primitives render. An ESLint lint catches a raw text node in a page.

---

## Phase 3 — Atoms and Molecules (Component Library, Bottom-Up)

Build in order so each component's dependencies already exist. Every component is a folder: `ComponentName/index.tsx` + `ComponentName.module.css` + `ComponentName.stories.tsx` (if we add Storybook later — optional for v1).

### 3.1 Atoms (spec Section 5)

1. **StatusBadge** — PASS/CAUTION/REJECT/PENDING/NO DATA pills. Props: `status`, `children`. Addresses Screen 1 #5 (correct labels), Screen 3 #6 (scorecard confidence badges).
2. **ScoreBar** — Label + track + fill + value. Fill color computed from value ranges (spec: <50 reject, 50-70 caution, >70 pass). Addresses **G5**, Screen 1 #6.
3. **EventFlag** — Calendar icon + Nd text. Color from day count thresholds. Addresses EVENT FLAG spec + Watchlist Event column.
4. **RankDelta** — Arrow + number in mono, color from sign. Addresses Screen 4 #4.
5. **StatusDot** — Small colored dot used for regime and alert type. (Implicit in top bar + nav rail scan status.)
6. **IconButton** — Ghost button with icon. Used in close buttons, actions.
7. **ModeToggle** — Sun/moon icon button that flips `data-theme`.

### 3.2 Molecules

1. **TableRow** — The status-tinted row. Takes `status` and applies `bg-pass-bg` + `border-left pass` etc. Addresses **G3**, Screen 1 watchlist/portfolio rows.
2. **SectionCard** — Bento card with header (title + count badge + action link) and body slot. Used by Dashboard Bento rows.
3. **StepIndicator** — Circle with one of 3 states: completed (checkmark `--pass`), current (`--accent` filled), future (outline `--border-strong`). Addresses Screen 2 #4, Screen 3 #1/#2.
4. **ScoreCardPanel** — Title + N ScoreBars + total score + confidence badge. Used in TradeCard and right rail.
5. **DTEProgressBar** — Thin inline bar. Takes `daysRemaining` and `totalDays`, computes fill %. Addresses **G6**.
6. **AlertRow** — Small left-border colored row for dashboard alerts list.
7. **SymbolHeader** — Ticker + company + price + status badge + direction pill. Used in Screener Step 4 right panel and TradeCard. Addresses Screen 2 #8.

### 3.3 Deliverable
A `/dev/components` route (dev-only) that lists all atoms + molecules rendered with every prop permutation. A visual smoke test catches regressions early.

---

## Phase 4 — Organisms & Persistent Frame

### 4.1 Persistent Frame (`app/(frame)/layout.tsx`)

```tsx
<html data-theme="dark">
  <body>
    <ThemeProvider>
      <TopBar />
      <div className="shell">
        <NavRail />                 ← reads route, swaps to Stepper inside /screener
        <main className="workspace">{children}</main>
        <ContextRail>{contextRailSlot}</ContextRail>
      </div>
    </ThemeProvider>
  </body>
</html>
```

Addresses drift items **Screen 0 #1 (empty workspace enforced)**, Screen 2/4 #1 (persistent top bar cannot be replaced by horizontal tabs — it's a layout, not a page element).

**Right rail content problem**: the rail content changes per page. Two options:

- **Option A — React Context + Portal**: the page registers its rail content via a `useContextRail(<MyRailContent />)` hook; the frame renders it in a portal.
- **Option B — Parallel routes** (`@contextRail` slot in App Router): `app/(frame)/layout.tsx` takes `children` and `contextRail` props, each page has both a `page.tsx` and a `@contextRail/page.tsx`.

**Recommendation: Option B (parallel routes)**. It's the idiomatic App Router solution, no client context, SSR-friendly, and keeps each page's rail content co-located with its main content on the filesystem. Slight learning curve but pays off.

### 4.2 TopBar

Hardcoded layout with three zones. Reads scan state from a lightweight store (Zustand for v1 — one store for scan state, theme, and selected symbol is enough; no Redux). Addresses Screen 1 #1, Screen 5 #2, Screen 6 #3 (remove non-spec icons).

### 4.3 NavRail

Reads `usePathname()`. If path starts with `/screener/`, renders `<Stepper>` instead of nav items. Addresses **G4** without any manual state. The "active" step is derived from the current path (e.g. `/screener/step-4-ranking` → step 4). This is the cleanest solution because:
- No state to get out of sync with the URL.
- Refreshing the page keeps the user on the right step.
- The back button works naturally.

**Recommendation: route-driven over context-driven**. Use React state only for transient UI (selected symbol, chart panel open).

### 4.4 Stepper (organism)

7 `StepIndicator` molecules + labels + connecting vertical line + "← Exit Workflow" link at the bottom. Addresses Screen 2 #2/#3/#5, Screen 3 #1/#2.

### 4.5 ContextRail

A styled container with section headers (DM Sans 10px uppercase 0.08em letter-spacing — enforced via CSS module class). Consumes the `@contextRail` parallel route slot.

### 4.6 StepNavBar

Used only inside `/screener/*` pages. Back button + "Step X of 7" center + Next accent button. Sits at the bottom of the workspace, sticky.

### 4.7 TradeCard (the biggest organism)

7 sections per spec Section 5. Stacked vertically (addresses Screen 3 #3). Every number goes through `<Data>` (enforcing mono). Every confidence badge is a `StatusBadge` (addresses Screen 3 #6). Approve button + Skip link (addresses Screen 3 #5).

### 4.8 InlineChartPanel

Framer Motion `motion.div` with `initial={{ y: '100%' }}` and `animate={{ y: 0 }}` (addresses **G7**). Contains the chart component + tabs + close button.

### 4.9 Deliverable
Persistent frame renders on every page. NavRail swaps to Stepper automatically inside `/screener/`. Both themes look correct. All organisms render with mock data on `/dev/components`.

---

## Phase 5 — Charts & Page Implementations

### 5.1 Chart library decision

**Recommendation: TradingView Lightweight Charts.**

| Library | Pros | Cons |
|---|---|---|
| **Lightweight Charts** | Purpose-built for financial candlesticks + volume; tiny (~45KB); matches our palette (same company as TradingView); native support for `--pass`/`--reject` candle coloring | Less React-idiomatic; needs a small wrapper to re-create chart on theme change |
| Recharts | React-native, composable | Not designed for OHLC candlesticks; building real candles is painful; looks amateur next to pro tools |
| Apache ECharts | Full-featured candlesticks | Big bundle (~300KB); enterprise styling clashes with dark trader aesthetic |
| Highcharts | Excellent financial charts | Commercial license; overkill |

Lightweight Charts is the right answer. The Screen 2 drift specifically calls for a real candlestick chart (Screen 4 #6, Screen 2 #10 volume subplot), and Lightweight Charts has native volume pane support.

Wrap it in `<CandlestickChart symbol={...} theme={...} />` and pass theme colors from `lib/tokens.ts` at mount; on theme change, dispose and re-init.

### 5.2 Animation library

**Framer Motion** for the InlineChartPanel slide-up (G7). That's the only non-trivial animation the spec calls for — we don't need it elsewhere in v1. A small bundle cost is acceptable.

### 5.3 Page build order

Ordered to maximize component reuse and surface problems early:

1. **Dashboard** — uses the most atoms (StatusBadge, EventFlag, RankDelta, SectionCard, TableRow, AlertRow, StatusDot). Finishing this validates roughly 70% of the component library. Addresses Screen 1 drift items #2/#3/#4 (render all rows from data, not hardcoded 2-4).

2. **Watchlist** — exercises InlineChartPanel, chart integration, row selection state, Framer Motion. First real chart. Addresses Screen 4 all drift items.

3. **Portfolio** — DTEProgressBar + footer totals + P&L coloring. Shorter than Watchlist because most components are reused. Addresses Screen 5 drift.

4. **Screener Step 4 (Stock Ranking)** — split-panel layout, Stepper active, rule table, right-rail scorecard. Pulls in SymbolHeader + Chart from Watchlist work. Addresses Screen 2 drift.

5. **Screener Step 7 (Trade Card)** — Finally build the TradeCard organism against real layout. Addresses Screen 3 drift.

6. **Screener Steps 1, 2, 3, 5, 6** — simpler screens (forms + selections). Lower priority because design-similar to Settings.

7. **Settings** — standalone form page with sub-nav. Minimal component reuse. Addresses Screen 6 drift (sticky Save/Reset footer, regular-weight labels).

8. **Calendar** — deferred (see Phase 6).

### 5.4 Data layer for v1

**No backend wiring in v1**. Each page imports fixtures from `/mocks/*.ts` typed against `/types/domain.ts`. This keeps the frontend buildable and reviewable in parallel with the FastAPI backend. Later, fixtures are swapped for `fetch()` calls with the same return types.

### 5.5 Deliverable
All 4 high-priority pages (Dashboard, Watchlist, Portfolio, Step 4, Step 7) render with mock data, both themes, all drift items closed.

---

## Phase 6 — Polish, Out-of-Scope, and Risks

### 6.1 Out of scope for v1

Explicitly deferred:

- **Light mode polish** — tokens are wired and the toggle works, but every screen should be reviewed in light mode in a later pass. Some shadows and borders may need per-theme tweaks.
- **Calendar page** — spec exists but is the thinnest (one screen, no drift log entry). Defer until Dashboard's upcoming-events rail proves the calendar data shape.
- **Alerts full page** — spec mentions it (section 8, reference from top bar or rail) but no screen spec exists yet. Right-rail + dashboard alerts card cover the v1 need.
- **Real backend wiring** — mocks only in v1.
- **Real-time updates / WebSocket** — not in current spec.
- **Authentication** — single user, local deployment.
- **Screener Steps 1, 2, 3, 5, 6** — build after the hero path (Step 4 → Step 7) to prove the workflow end-to-end; intermediate steps are mostly form UI.
- **Storybook / Chromatic** — `/dev/components` route covers the need for v1.
- **E2E tests** — defer until backend is wired.

### 6.2 Architectural trade-offs recap

| Decision | Alternative | Why we chose this |
|---|---|---|
| CSS Modules + custom properties | Tailwind | Tokens are the design law; ad-hoc utility classes undermine that |
| Typed `<Text>`/`<Data>`/`<Title>` primitives | ESLint rule only | Makes wrong font a type error, not a lint warning |
| Parallel routes for context rail | React Context | Idiomatic App Router, no hydration issues, co-located |
| Route-driven stepper active state | React state | URL is the source of truth; refresh-safe |
| Lightweight Charts | Recharts | Real candlesticks matter for trader credibility |
| Zustand (small scope) | Redux | Only need theme + scan state + selected symbol |
| Mocks in `/mocks/` | Storybook mocks | Same fixtures feed pages AND future tests |

### 6.3 Risks and unknowns

1. **Lightweight Charts theme switching**: library isn't reactive; on theme change we must dispose and re-instantiate. Need to prototype early to confirm no flicker.
2. **Framer Motion + RSC**: motion components are client-only; InlineChartPanel must be `"use client"`. Not a blocker but a thing to remember.
3. **Font-rule enforcement in third-party chart labels**: Lightweight Charts axis labels are rendered in canvas, not DOM — we pass `fontFamily: 'JetBrains Mono'` as a config option. Need to confirm this works on both themes.
4. **Parallel route slot + nested layouts**: when inside `/screener/`, we have two nested layouts and a parallel slot. This is supported but edge-case heavy; we should build Dashboard (simpler) first to validate the pattern before Screener.
5. **Next.js version churn**: pin Next.js to a specific minor (e.g. 15.x). Do not track canary.
6. **Desktop-only**: spec says desktop web. We will NOT add responsive breakpoints for tablet/mobile in v1 — the persistent frame assumes ≥1280px width. Add a minimum-width warning in `app/layout.tsx` rather than building responsive variants.
7. **Accessibility**: spec doesn't mention a11y requirements but dark-mode contrast looks acceptable. We should run axe on Dashboard once before calling v1 done.

---

## Critical Files List (top 10)

1. `F:/Git/GitHub/Trading assistant/app/layout.tsx` — root layout, font loading, theme attr
2. `F:/Git/GitHub/Trading assistant/app/(frame)/layout.tsx` — persistent frame (top bar + nav rail + context rail + workspace)
3. `F:/Git/GitHub/Trading assistant/styles/tokens.css` — all design tokens (dark + light)
4. `F:/Git/GitHub/Trading assistant/components/primitives/Text.tsx` + `Data.tsx` + `Title.tsx` — three-font enforcement
5. `F:/Git/GitHub/Trading assistant/components/organisms/NavRail/index.tsx` — nav ↔ stepper swap (G4)
6. `F:/Git/GitHub/Trading assistant/components/organisms/TopBar/index.tsx` — persistent top bar
7. `F:/Git/GitHub/Trading assistant/components/molecules/TableRow/index.tsx` — status-tinted row (G3)
8. `F:/Git/GitHub/Trading assistant/components/atoms/ScoreBar/index.tsx` — score bar with value-range color logic (G5)
9. `F:/Git/GitHub/Trading assistant/components/organisms/TradeCard/index.tsx` — Screen 3 hero component
10. `F:/Git/GitHub/Trading assistant/components/organisms/InlineChartPanel/index.tsx` — Lightweight Charts + Framer Motion (G6, G7)

Plus these existing files, which are the specification and drift contract and should never be edited to "match" the implementation — the code matches them:

- `F:/Git/GitHub/Trading assistant/docs/design/bamendjou-design-spec.md`
- `F:/Git/GitHub/Trading assistant/docs/design/stitch-drift-log.md`
