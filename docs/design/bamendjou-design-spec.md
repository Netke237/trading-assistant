# Bamendjou — Design Specification
**Version**: 1.0  
**Status**: Approved for implementation  
**Product**: Options Screener & Trade Planning Assistant  
**Stack**: Next.js (React) frontend, FastAPI backend  
**Target user**: Single discretionary swing options trader, high IT affinity, limited screen time

---

## Design Decisions Log

| Decision | Choice | Reason |
|---|---|---|
| Background | Dark navy #131722, not pure black | Pure black causes eye strain in long sessions; navy is more professional |
| Typography split | 3 fonts with strict rules | Monospace for data only improves scannability at density |
| Row color tinting | Status tints entire row, not just badge | Unusual Whales proved this: pass/caution/reject scannable before reading a word |
| Score bars | Visual bars, not raw numbers | NFR-02 mandates explainability; bars show component breakdown |
| Event flags | Inline on every row | Market Chameleon pattern; earnings proximity is first-class concern (FR-13) |
| Single accent | #2962FF only | TradingView pattern: one accent guides action, prevents visual noise |
| Charts | Accessible from Watchlist + Portfolio via inline panel | Not only in Screener; clicking any symbol opens chart |
| Journal | Embedded in Trade Card approval step | Attached to trade record, not separate nav item (FR-16 extension) |
| Alerts | Dedicated page + right rail | Right rail alone insufficient for real alert management |
| Screener nav | Rail transforms into 7-step stepper | Standard nav hides, workflow stepper takes over when inside Screener |
| Top bar | Read-only scan context, not editable controls | Universe/timeframe belong to the scan workflow, not global state |
| Dark/Light mode | Both required, token-driven | User requirement; token system makes this maintainable |

---

## Section 1 — Design Tokens

### Dark Mode (default)

```css
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
```

### Light Mode

```css
--bg-base:          #F0F3FA;
--bg-surface:       #FFFFFF;
--bg-surface-2:     #F5F7FF;
--bg-surface-3:     #EBF0FF;
--border-subtle:    #DDE1F0;
--border-strong:    #C5CCE6;
--text-primary:     #131722;
--text-secondary:   #5A6070;
--text-dim:         #9BA3B8;

--pass:             #1A9188;
--pass-bg:          #EDF7F6;
--pass-border:      #B3E0DC;
--caution:          #D4890A;
--caution-bg:       #FEF6E6;
--caution-border:   #F5D38A;
--reject:           #D32F2F;
--reject-bg:        #FEECEC;
--reject-border:    #F5BCBC;
--neutral:          #64748B;
--neutral-bg:       #F1F5F9;

--accent:           #2962FF;
--accent-hover:     #1E53E5;
--accent-dim:       #EEF2FF;
--accent-text:      #FFFFFF;
```

---

## Section 2 — Typography

### Rules (STRICT — must not deviate)

| Context | Font | Weight | Size range |
|---|---|---|---|
| Brand wordmark, H1 page titles ONLY | Sora | 700 Bold | 20–32px |
| All UI: nav, labels, body, buttons, descriptions, form fields | DM Sans | 400 / 500 / 600 | 10–16px |
| ALL data values: prices, scores, %, tickers, contracts, timestamps, DTE, numeric values | JetBrains Mono | 400 / 500 | 10–14px |

### Size Scale

| Use | Size | Font | Weight |
|---|---|---|---|
| Micro label / column header | 10px | DM Sans | 500 Medium, uppercase, letter-spacing 0.08em |
| Table data, secondary | 11px | DM Sans or JetBrains Mono | 400 |
| Secondary label | 12px | DM Sans | 400 |
| Body, form | 13px | DM Sans | 400 |
| Primary body, nav items | 14px | DM Sans | 500 |
| Section title | 16px | DM Sans | 600 |
| Page title / H1 | 20–24px | Sora | 700 |
| Score display (large) | 18–24px | JetBrains Mono | 500 |
| Brand wordmark | 20px | Sora | 700 |

---

## Section 3 — Spacing & Shape

```
Spacing scale (4px base): 4 / 8 / 12 / 16 / 20 / 24 / 32 / 48px

Border radius:
  Default elements:    6px
  Small (badges, tags): 4px
  Large (modals):      10px

Shadows (dark mode):
  Card:     0 1px 3px rgba(0,0,0,0.4)
  Elevated: 0 4px 16px rgba(0,0,0,0.5)
```

---

## Section 4 — Persistent Frame

**This frame appears identically on EVERY screen. It is never modified per page.**

```
┌──[TOP BAR 48px, full width, --bg-surface, bottom border 1px --border-subtle]──┐
│  [BAMENDJOU wordmark]  [Scan context read-only]  [Regime dot]  [Mode toggle]  │
├──[NAV RAIL 64px]──┬──[CENTRAL WORKSPACE flex:1]──┬──[CONTEXT RAIL 300px]──────┤
│  icon + label     │   PAGE CONTENT               │  Context-aware panel       │
│  6 items          │                              │  always visible            │
└───────────────────┴──────────────────────────────┴────────────────────────────┘
```

### Top Bar (48px)

- Background: `--bg-surface`
- Bottom border: `1px --border-subtle`
- **Left zone**: "BAMENDJOU" in Sora Bold 20px `--text-primary` + "Options Screener" in DM Sans 11px `--text-secondary`
- **Center-left zone**: "Last scan: SP500 · Bullish · Swing (5–15d)" in DM Sans 12px `--text-secondary`. Hidden if no scan has run.
- **Center-right zone**: Scan state pill badge:
  - `IDLE` — `--neutral-bg` / `--neutral` text
  - `SCANNING` — `--accent` bg / white text / subtle pulse animation
  - `COMPLETED 09:42` — `--pass-bg` / `--pass` text
  - `FAILED` — `--reject-bg` / `--reject` text
- **Right zone**: 12px circle dot (colored by regime status) + "Regime: PASS" in DM Sans 12px + dark/light toggle icon

### Left Nav Rail

- Background: `--bg-surface`
- Right border: `1px --border-subtle`
- **Collapsed**: 64px wide — icon centered + label below in DM Sans 10px
- **Expanded**: 200px wide — icon + label beside in DM Sans 14px
- **Nav items** (top to bottom): Dashboard · Screener · Watchlist · Portfolio · Calendar · Settings
- Item height: 56px
- **Active**: 3px left border `--accent` + `--accent-dim` background + `--accent` icon/label color
- **Hover**: `--bg-surface-2` background
- **Inactive**: `--text-secondary` icon and label
- **Bottom of rail**: scan status dot + "Scan" label in DM Sans 10px

#### Screener Mode Exception

When the user is inside the Screener workflow, nav items are **replaced** by a 7-step vertical stepper:

```
  ✓  1  Universe           (completed: --pass checkmark circle)
  ✓  2  Direction + Horizon
  ✓  3  Market Regime
  ●  4  Stock Ranking      (current: --accent filled circle)
  ○  5  Vol + Events       (future: outline circle --border-strong)
  ○  6  Contracts
  ○  7  Trade Card
```

- Connecting vertical line between steps: `--border-subtle`
- Step labels: DM Sans 12px
- Below stepper: "← Exit Workflow" text link, DM Sans 11px `--text-secondary`

### Right Context Rail (300px)

- Background: `--bg-surface`
- Left border: `1px --border-subtle`
- Section headers: DM Sans 10px 500 uppercase letter-spacing 0.08em `--text-secondary`, 12px 16px padding, bottom border `--border-subtle`

**Content by page context:**

| Page | Rail Content |
|---|---|
| Dashboard | Upcoming events (next 7 days, watchlist + portfolio) + Portfolio risk summary |
| Screener Steps 1–3 | Step guidance text + current selections summary |
| Screener Steps 4–7 (symbol selected) | Stock Scorecard bars + Contract Scorecard bars (Step 6+) + Final Status badge |
| Watchlist / Portfolio (row selected) | Symbol summary (price, status) + last 3 alerts for that symbol |
| Calendar | Selected date event details |
| Settings | Help text for active settings section |

---

## Section 5 — Component Library

All components must be implemented exactly as specified. Do not introduce visual variations.

### STATUS BADGE
```
Shape:    pill, border-radius 4px
Font:     DM Sans 11px SemiBold uppercase
Padding:  2px 8px
Border:   1px

PASS:    bg --pass-bg    | text --pass    | border --pass-border
CAUTION: bg --caution-bg | text --caution | border --caution-border
REJECT:  bg --reject-bg  | text --reject  | border --reject-border
PENDING: bg --neutral-bg | text --neutral | border --neutral
NO DATA: bg --neutral-bg | text --text-dim| border --border-subtle
```

### SCORE BAR
```
Layout:  full-width row, flex horizontal
Left:    label — DM Sans 12px --text-secondary (e.g. "Trend")
Center:  horizontal bar — height 6px, border-radius 3px
         Track: --border-subtle
         Fill:  <50% = --reject | 50–70% = --caution | >70% = --pass
Right:   value — JetBrains Mono 12px --text-primary (e.g. "22/30")
```

### EVENT FLAG
```
Content:  calendar icon + "Nd" (e.g. "3d", "14d")
Font:     DM Sans 11px
Colors:
  > 7 days:  --text-dim
  ≤ 7 days:  --caution
  ≤ 3 days:  --reject
Placement: inline in table row, Event column
```

### RANK DELTA
```
▲ +2  →  --pass color
▼ -1  →  --reject color
—     →  --text-dim
Font: JetBrains Mono 11px
```

### TABLE ROW (status-tinted)
```
Height:           44px
Bottom border:    1px --border-subtle
Left border:      2px, colored by status

PASS:    bg --pass-bg    | left border --pass
CAUTION: bg --caution-bg | left border --caution
REJECT:  bg transparent  | left border --border-subtle | opacity 0.6
PENDING: bg --neutral-bg | left border --neutral
Hover:   --bg-surface-2 overlay (all rows)
```

### SECTION CARD (bento card)
```
Background:    --bg-surface
Border:        1px --border-subtle
Border-radius: 6px
Shadow:        card

Header row (16px padding):
  Left:  DM Sans 14px SemiBold --text-primary + count badge
  Right: action link DM Sans 12px --accent

Content: 0 top padding, 16px horizontal padding
```

### INLINE CHART PANEL
```
Trigger:    clicking any symbol from Watchlist or Portfolio
Behavior:   slides up from bottom of central workspace
Height:     360px
Background: --bg-surface
Top border: 1px --border-strong
Shadow:     elevated

Header: symbol name + close button (×) right-aligned
Tabs:   Price | RSI | MACD — DM Sans 13px, --accent underline on active
Chart background: --bg-base
Axis labels:      JetBrains Mono 10px --text-dim
Candle up:        --pass
Candle down:      --reject
```

### STEP NAVIGATION BAR (Screener only)
```
Height:     52px
Background: --bg-surface
Top border: 1px --border-subtle
Padding:    0 24px
Layout:     flex, space-between

Left:   "← Back" — ghost button, DM Sans 14px --text-secondary,
        border 1px --border-subtle, border-radius 6px, padding 8px 16px
Center: "Step 4 of 7" — DM Sans 12px --text-secondary
Right:  "Next: Vol + Events →" — accent button, DM Sans 14px white,
        bg --accent, border-radius 6px, padding 8px 20px
```

### TRADE CARD
```
Container: full-width, --bg-surface, border 1px --border-subtle,
           border-radius 6px, padding 24px
Sections separated by 1px --border-subtle horizontal rule

[Symbol Header]
  Ticker:       JetBrains Mono 24px Bold --text-primary
  Company name: DM Sans 14px --text-secondary
  Status badge: STATUS BADGE component
  Direction tag: small pill, DM Sans 11px

[Stock Scorecard]
  Title: DM Sans 14px SemiBold "Stock Score"
  5 × SCORE BAR: Trend | Pullback | Trigger | Event | Volatility
  Total: "Score: 87" JetBrains Mono 18px + confidence badge

[Contract Scorecard]
  Title: DM Sans 14px SemiBold "Contract Score"
  5 × SCORE BAR: DTE Fit | Delta | IV Attractiveness | Liquidity | Spread
  Total: contract score + contract confidence badge

[Entry Plan]
  3-column grid:
    Recommended Limit | Max Acceptable Fill | Order Type
  Values: JetBrains Mono 16px --text-primary
  Labels: DM Sans 12px --text-secondary above each value

[Exit Plan]
  4-column grid:
    Invalidation Level | Premium Stop | Time Stop | Target Price
  Values: JetBrains Mono 14px
  Labels: DM Sans 12px --text-secondary

[Reward-Risk]
  Ratio display: "R/R: 2.4 : 1" — Sora Bold 24px --text-primary
  Pass/fail badge vs configured minimum
  Model indicator: "Heston repriced" or "Delta approximation"
  — DM Sans 11px --text-secondary

[Entry Journal]
  Label:       "Why are you taking this trade?"
               DM Sans 13px --text-secondary
  Textarea:    border 1px --border-strong, bg --bg-base,
               border-radius 6px, DM Sans 13px --text-primary
  Placeholder: "Document your entry rationale..."
               DM Sans 13px --text-dim

[Actions]
  "Approve Trade": accent button, full width, DM Sans 14px white,
                   bg --accent, border-radius 6px, height 44px
  "Skip":          ghost text link below, DM Sans 13px --text-secondary,
                   centered
```

---

## Section 6 — Screen Specifications

### Screen 0: Persistent Frame (shell only)
Top bar + nav rail + empty central workspace + context rail.
No page content. Both dark and light mode. This is the base shell.

### Screen 1: Dashboard

Central workspace content (frame always wraps it):

**[A] Regime Banner** — full width, 48px strip
- Background tinted by regime status
- Left border 4px colored by regime status
- "Market Regime: PASS · SPY above 200MA · VIX 18.2 (Normal) · Breadth Expanding" — DM Sans 13px
- Right: "Updated 09:42" — JetBrains Mono 11px `--text-dim`

**[B] Bento Row 1** — two SECTION CARDs side by side
- Left (60%): WATCHLIST
  - 8 rows, TABLE ROW component, tinted by status
  - Columns: Symbol (JetBrains Mono 13px Bold) | Direction | Score (score + mini bar) | Status badge | Next Event (EVENT FLAG) | Actions
- Right (40%): PORTFOLIO
  - 5 rows
  - Columns: Symbol | Contract (JetBrains Mono 11px) | P&L (JetBrains Mono, `--pass` if positive, `--reject` if negative) | Expiry DTE | Status

**[C] Bento Row 2** — two SECTION CARDs side by side
- Left (50%): ALERTS
  - 5 items as list rows
  - Left border 2px colored by alert type
  - Content: alert icon | symbol (JetBrains Mono) | short reason (DM Sans 13px) | time (JetBrains Mono 11px `--text-dim`)
  - "View All Alerts" link bottom, DM Sans 12px `--accent`
- Right (50%): UPCOMING EVENTS
  - Calendar list grouped by day
  - Date group header: DM Sans 10px SemiBold uppercase `--text-secondary`
  - Each event: date (JetBrains Mono 11px) | symbol | event type | risk dot

**[D] Floating Action Button** — bottom-right of central workspace
- "▶ Run Scan" — Sora SemiBold 14px white, `--accent` bg, shadow elevated, border-radius 6px, padding 12px 24px

Right context rail shows: Upcoming events + Portfolio risk summary.

---

### Screen 2: Screener — Step 4 Stock Ranking (active example)

Nav rail: stepper visible, steps 1–3 checked, step 4 current (accent), steps 5–7 outline.

Central workspace splits:

**Left sub-panel (280px)**
- Header: "Candidates (12)" + filter icon + Export Excel link
- Group: PASS (3 tinted rows)
- Group: CAUTION (2 tinted rows)
- Group: REJECT (2 dim rows)
- Each row: symbol (JetBrains Mono Bold) | score | status dot | R flag | S flag
- Bottom: "↓ Export Excel" ghost button full width

**Right sub-panel (flex:1)**
- Symbol header: "AAPL · Apple Inc · $185.20" + status badge + score + direction
- Inline chart (360px height): candlestick + volume
- Rule validation table below chart:
  - Columns: Rule | Result (badge) | Key Metrics | Confidence (SCORE BAR)
  - 5 rows: Trend / Pullback / Trigger / Event / Volatility

Right context rail: Stock Scorecard bars + Final Status badge for selected symbol.

Step navigation bar at bottom of workspace.

---

### Screen 3: Screener — Step 7 Trade Card

Nav rail: stepper, steps 1–6 checked, step 7 current.

Central workspace: full-width TRADE CARD component. Show all sections filled with realistic data:
- Symbol: AAPL | Score: 87 | Contract: AAPL 220C 05/16
- Entry: Limit $4.20 | Max Fill $4.50 | Order: Limit
- Exit: Invalidation $178 | Stop $2.10 | Time stop 10d | Target $198
- R/R: 2.4:1 | Model: Heston repriced
- Journal textarea: empty, showing placeholder

Right context rail: both scorecards + PASS final status.

---

### Screen 4: Watchlist

Full workspace table. No sub-panels.

Columns: Symbol | Direction | Horizon | Score | Δ Score | Status | Trend | Pullback | Trigger | Event | Vol | Actions

- 8 rows, mixed statuses
- TABLE ROW tinting applied
- EVENT FLAG in Event column
- RANK DELTA in Δ Score column
- One row selected state: `--bg-surface-3` background
- INLINE CHART PANEL open at bottom for selected row symbol
- Actions column: "Detail" | "Remove" — DM Sans 11px ghost small buttons

Right context rail: selected symbol summary + last 3 alerts.

---

### Screen 5: Portfolio

Full workspace table.

Columns: Symbol | Contract | Direction | Entry Date | Expiry | DTE | Entry $ | Current $ | P&L $ | P&L % | Stop | Target | Status | Actions

- DTE column: thin colored progress bar in cell (full=`--pass`, ~50%=`--caution`, <20%=`--reject`)
- P&L columns: JetBrains Mono, `--pass` positive, `--reject` negative
- Footer row: `--bg-surface-3` background, totals: capital deployed | total P&L | positions count
- Actions column: "Card" | "Journal" | "Close" — DM Sans 11px ghost small buttons

---

### Screen 6: Settings

Left sub-nav within workspace (200px panel):
- Vertical tabs: Scan Defaults | Direction + Horizon | Stock Rules | Contract Rules | Scoring + Weights | Entry + Exit Rules | Alerts | Display
- Active tab: `--accent` left border 3px + `--accent-dim` bg

Right form area (flex:1): show "Scoring + Weights" as active example.
- Group header: DM Sans 14px SemiBold `--text-primary`
- Field layout: two columns — left (label DM Sans 13px + description DM Sans 12px `--text-secondary`) | right (input, border `--border-strong`, bg `--bg-base`, border-radius 6px)
- Bottom: "Save Changes" (accent button) + "Reset to Defaults" (ghost button) side by side

---

## Section 7 — Stitch Compliance Checklist

Use this to review Stitch output before accepting any screen.

### Per-screen checks
- [ ] Persistent frame present (top bar + nav rail + context rail)
- [ ] Top bar has wordmark, scan context, regime dot, mode toggle
- [ ] Nav rail shows correct active item
- [ ] Context rail shows correct content for this page
- [ ] Dark mode tokens used (not generic greys/blues)
- [ ] Table rows are color-tinted by status (not just badge in a column)
- [ ] Data values in JetBrains Mono (prices, scores, tickers, DTE)
- [ ] Labels and nav in DM Sans (not monospace)
- [ ] Wordmark and H1 only in Sora
- [ ] Status badges use pill shape with correct color pair
- [ ] EVENT FLAG present on stock rows where applicable
- [ ] No decorative gradients, illustrations, or unauthorized colors

### Known Stitch limitations (fix in Next.js implementation)
- Font mixing rules: Stitch may render all text in one font. Enforce the 3-font rule in CSS.
- Exact hex values: Stitch may approximate colors. Replace with exact tokens in CSS variables.
- Row tinting: Stitch may not fully tint rows. Implement via className logic in React.
- Rail-to-stepper transform: Stitch cannot simulate this interaction. Implement in component state.
- Inline chart panel slide-up animation: Implement in Next.js with Framer Motion.
- Score bar fill logic (color by value range): Implement in React with conditional className.
- DTE progress bar in Portfolio: Implement in React, calculate fill % from DTE remaining/total.

---

## Section 8 — Page Map Summary

| Page | Nav Item | PRD References |
|---|---|---|
| Dashboard | Dashboard | FR-34, FR-43 |
| Screener — Step 1: Universe | Screener | FR-07 |
| Screener — Step 2: Direction + Horizon | Screener | FR-08, FR-09 |
| Screener — Step 3: Market Regime | Screener | FR-10 |
| Screener — Step 4: Stock Ranking | Screener | FR-11, FR-12, FR-29 |
| Screener — Step 5: Vol + Events | Screener | FR-13 |
| Screener — Step 6: Contracts | Screener | FR-14, FR-23–FR-28 |
| Screener — Step 7: Trade Card | Screener | FR-15, FR-16, FR-39–FR-41 |
| Watchlist | Watchlist | FR-17, FR-34 |
| Portfolio | Portfolio | FR-17, FR-42, FR-43 |
| Calendar | Calendar | FR-36 |
| Settings | Settings | FR-31, FR-45 |
| Alerts | (from top bar or right rail) | FR-37, FR-43 |
