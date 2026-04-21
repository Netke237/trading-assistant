# Bamendjou — Stitch Drift Log
**Purpose**: Track all deviations from the design spec in Stitch output. Items here must be enforced in Next.js implementation.

---

## Screen 0 — Frame Shell
**Status**: Generated with dashboard content (Stitch ignored empty workspace instruction)
**Date**: 2026-04-17

### COMPLIANT
- Top bar present at correct position, dark background
- BAMENDJOU wordmark present, left-aligned
- "Options Screener" subtitle beside wordmark
- Scan context text: "Last scan: SP500 · Bullish · Swing (5-15d)" correct
- COMPLETED 09:42 badge with green tinting
- Green dot + "Regime: PASS" on right
- Mode toggle icon present
- 6 nav items present: Dashboard, Screener, Watchlist, Portfolio, Calendar, Settings
- Dashboard active state with blue left accent border + blue label
- Right context rail present on right side

### DRIFTED
| # | Element | Spec | Stitch Output | Fix in Next.js |
|---|---------|------|---------------|----------------|
| 1 | Central workspace | Empty (Screen 0 is shell only) | Added dashboard content (Market Overview, metric cards, CPI card, Priority Screener Hits) | Enforce empty workspace in shell layout component |
| 2 | Nav rail width | 64px collapsed, icon centered + label below | Appears wider (~80px), labels may be beside icons | Set width: 64px in CSS, flex-direction: column on nav items |
| 3 | Nav bottom | Scan status dot + "Scan" label | Not present | Add scan status indicator at bottom of rail |
| 4 | Floating button | "▶ Run Scan" Sora SemiBold 14px white, accent bg | Lightning bolt icon only, no text | Replace with text button per spec |
| 5 | Wordmark font | Sora Bold 20px | Likely Manrope (from design system generation) | font-family: 'Sora', weight 700 |
| 6 | Body/UI font | DM Sans all UI text | Likely Inter or Manrope | font-family: 'DM Sans' globally |
| 7 | Data values font | JetBrains Mono (prices, scores, %) | Font unverifiable — likely wrong | font-family: 'JetBrains Mono' on all data elements |
| 8 | Right rail content | Empty for Screen 0 | Shows "Context / Analysis Rail / No Selection" | Conditionally render rail content per page |
| 9 | Right rail header | DM Sans 10px 500 uppercase, letter-spacing 0.08em | Style unverifiable | Enforce in CSS |
| 10 | Dashboard content | See Screen 1 spec | Market Overview, SPX/IV/Delta metrics, CPI card — none in spec | Rebuild per spec (Regime Banner + Bento rows) |

### DECISION
Accepted as imperfect Screen 0 base. Moving to Screen 1 correction prompt. Critical drift items #5, #6, #7 (fonts) enforced in Next.js only — Stitch cannot reliably fix these.

---

## Screen 1 — Dashboard
**Status**: Accepted with drift
**Date**: 2026-04-17

### COMPLIANT
- Regime banner: correct color tinting, text, "Updated 09:42" right-aligned
- Watchlist card: correct columns, row tinting by status visible
- Portfolio card: correct columns, green/red P&L coloring
- Alerts card: colored left borders by alert type
- Upcoming Events: grouped by date with colored risk dots
- "▶ Run Scan" button: correct placement, blue bg, white text
- Right context rail: Upcoming Events + Portfolio Risk with Greek values
- 6 nav items, Dashboard active state

### DRIFTED
| # | Element | Spec | Stitch Output | Fix in Next.js |
|---|---------|------|---------------|----------------|
| 1 | Top bar | "Options Screener" subtitle + scan context + mode toggle + regime dot | Lost subtitle and scan context; added Search icon (not in spec); no mode toggle | Rebuild top bar per spec exactly |
| 2 | Watchlist rows | 8 rows | 4 rows shown | Render all 8 rows in React |
| 3 | Portfolio rows | 5 rows | 2 rows shown | Render all 5 rows in React |
| 4 | Alerts rows | 5 rows | 2 rows shown | Render all 5 rows in React |
| 5 | Status badge labels | PASS / CAUTION / REJECT | Ready / Hold / Skip | Use correct labels in StatusBadge component |
| 6 | Score column | Score value + mini bar beside it | Score value only, no mini bar | Add inline ScoreBar component per row |
| 7 | Nav active item | 3px left border #2962FF + #142B7A bg | Blue bg present, left border unclear | border-left: 3px solid #2962FF in CSS |

### DECISION
Accepted as Screen 1 base. Layout and structure correct. Drift items to fix in Next.js implementation.

---

## Screen 2 — Screener Step 4 (Stock Ranking)
**Status**: Accepted with drift
**Date**: 2026-04-17

### COMPLIANT
- Split layout: candidate sub-panel left + symbol detail panel right
- Candidates panel: row tinting by PASS/CAUTION/REJECT status
- Candlestick chart: green up candles (#26A69A), red down candles (#EF5350)
- Rule validation table: correct columns (Rule | Result | Key Metrics | Confidence)
- Confidence bars colored by value range (green/amber)
- Right rail: 5 score bars with correct values and color logic
- FINAL STATUS large PASS badge
- Step nav bar: "Back" | "Step 4 of 7" | "Next: Vol + Events →"

### DRIFTED
| # | Element | Spec | Stitch Output | Fix in Next.js |
|---|---------|------|---------------|----------------|
| 1 | Top bar | Wordmark + scan context + badge + regime dot + mode toggle | Replaced left nav with horizontal tabs; added bell/gear/avatar | Rebuild persistent top bar; remove horizontal tabs |
| 2 | Stepper step names | Universe / Direction+Horizon / Market Regime / Stock Ranking / Vol+Events / Contracts / Trade Card | Selection / Filters / Ranking / Validation / Optimization / Review / Execute | Hardcode correct step names in Stepper component |
| 3 | Stepper current step | Step 4 (Stock Ranking) current | Step 3 shown as current, header says "Step 3 of 7" | Set currentStep=4 in state |
| 4 | Step indicators | Checkmark circles for completed, filled blue for current, outline for future | Plain list icons, no circle indicators | Implement StepIndicator component with 3 states |
| 5 | Exit Workflow link | "← Exit Workflow" below stepper | Not present | Add below last step item |
| 6 | Candidates rows | 7 rows in 3 groups with group headers | 4 rows, no group headers | Render grouped rows with PASS/CAUTION/REJECT group labels |
| 7 | Export Excel button | Ghost button full width at bottom of panel | Not present | Add ExportButton component |
| 8 | Symbol header | AAPL · Apple Inc · $185.20 + PASS badge + "Score: 87" + "Bullish" pill | Missing Score and direction pill | Add to SymbolHeader component |
| 9 | Rule table | 5 rows: Trend/Pullback/Trigger/Event/Volatility | 3 rows shown | Render all 5 rule rows |
| 10 | Chart volume bars | Volume bars below candles | Not present | Add volume subplot below price chart |
| 11 | Save Scan button | Not in spec | Present bottom-left | Remove |

### DECISION
Accepted as Screen 2 base. Layout structure, score bars, and chart are strong. Stepper names and top bar to fix in Next.js.

---

## Screen 3 — Screener Step 7 (Trade Card)
**Status**: Accepted with minor drift
**Date**: 2026-04-17

### COMPLIANT
- Top bar: wordmark + "Options Screener" + scan context + COMPLETED badge + Regime dot + mode toggle
- Stepper: steps 1–6 green checkmarks, step 7 blue filled circle (current)
- Exit Workflow icon present below stepper
- Symbol header: AAPL + Apple Inc + BULLISH pill + PASS badge
- Stock Scorecard: all 5 bars (Trend/Pullback/Trigger/Event/Volatility) with correct values and color logic
- Contract Scorecard: all 5 bars (DTE Fit/Delta/IV Attractiveness/Liquidity/Spread) correct
- Entry Plan: 3-column grid — $4.20 / $4.50 / Limit
- Exit Plan: 4-column grid — $178.00 / $2.10 / 10d / $198.00
- R/R: 2.4:1 large display + PASS badge + "Heston repriced"
- Journal textarea with correct placeholder text
- "Approve Trade" full-width blue button
- Right rail: Stock Scorecard + Contract Scorecard + FINAL STATUS PASS

### DRIFTED
| # | Element | Spec | Stitch Output | Fix in Next.js |
|---|---------|------|---------------|----------------|
| 1 | Stepper labels | Text label beside each step circle | Number only, no text labels | Add step name text in StepperItem component |
| 2 | Stepper connector | Vertical line between steps #2A2E42 | Not visible | Add border-left connector line in CSS |
| 3 | Scorecard layout | Stock then Contract stacked vertically | Rendered side-by-side | Stack sections vertically in TradeCard component |
| 4 | $4.50 color | Same neutral style as other values | Colored amber | Use --text-primary for all entry plan values |
| 5 | Skip link | "Skip" ghost text link centered below button | Not visible | Add below ApproveButton |
| 6 | Confidence badges | PASS/CAUTION/REJECT styled badge | Blue circle badge | Use StatusBadge component |

### DECISION
Accepted as Screen 3 base. Strongest screen generated. All critical data correct.

---

## Screen 4 — Watchlist
**Status**: Accepted with drift
**Date**: 2026-04-17

### COMPLIANT
- Table columns correct (Symbol/Direction/Horizon/Score/ΔScore/Status/Trend/Pullback/Trigger)
- Column headers in small uppercase grey
- Row tinting: PASS rows green border, GOOGL selected blue, PENDING neutral
- Event timing coloring: ≤3d red, ≤7d amber, >7d grey
- Inline chart panel: GOOGL header + Price/RSI/MACD tabs + × close button + correct height
- Right rail: SYMBOL SUMMARY (price + score + badge) + LAST 3 ALERTS with timestamps
- Alert titles color-coded by type

### DRIFTED
| # | Element | Spec | Stitch Output | Fix in Next.js |
|---|---------|------|---------------|----------------|
| 1 | Top bar | Wordmark + scan context + badges + regime + mode toggle | Horizontal nav tabs again; all top bar elements missing | Enforce persistent TopBar component |
| 2 | Row count | 8 rows | 4 rows | Render all 8 rows |
| 3 | Direction labels | Bullish / Bearish / Neutral | LONG / NEUTRAL | Use correct label values |
| 4 | Δ Score format | ▲+2 / ▼-1 / — in monospace | Decimal numbers (+2.4) | Format as rank delta with arrow symbol |
| 5 | Vol + Actions columns | Visible in table | Truncated off screen | Ensure table scrolls horizontally or columns fit |
| 6 | Chart panel | Actual candlestick chart | Placeholder text | Integrate charting library (e.g. Lightweight Charts) |
| 7 | Extra UI | Not in spec | "+ Add Symbol", search bar, "Tech/Mega Cap" tags, "Open Full Analysis" | Remove non-spec elements |

### DECISION
Accepted as Screen 4 base. Right rail and chart panel structure are strong references.

---

## Screen 5 — Portfolio
**Status**: Accepted with minor drift
**Date**: 2026-04-17

### COMPLIANT
- Top bar: wordmark + "Options Screener" + scan context + COMPLETED badge + Regime dot + mode toggle
- Portfolio (5 positions) header + Total P&L green right-aligned
- All 5 rows with correct contract data, dates, and values
- DTE progress bars: correct color per value (green/amber/red)
- P&L values: green positive, red negative, correct formatting
- Row tinting by status
- Footer TOTALS row with correct aggregates
- Right rail: PORTFOLIO SUMMARY (capital + P&L + win rate) + POSITIONS AT RISK (NVDA flagged)

### DRIFTED
| # | Element | Spec | Stitch Output | Fix in Next.js |
|---|---------|------|---------------|----------------|
| 1 | Target/Status/Actions columns | Visible in table | Truncated off screen | Ensure all 14 columns fit or add horizontal scroll |
| 2 | Top bar extra icons | Mode toggle only | Bell + settings icons present | Remove non-spec icons from TopBar component |
| 3 | Nav labels | Icon + label below | Icon only | Add 10px DM Sans labels below each icon |
| 4 | Review Trade Plan button | Not in spec | Present in POSITIONS AT RISK | Remove or make optional |

### DECISION
Accepted as Screen 5 base. DTE bars and P&L coloring are reference-quality for Next.js implementation.

---

## Screen 6 — Settings
**Status**: Accepted with minor drift
**Date**: 2026-04-17

### COMPLIANT
- Top bar: wordmark + "OPTIONS SCREENER" + scan context + COMPLETED badge + Regime dot
- All 8 sub-nav tabs: Scan Defaults / Direction + Horizon / Stock Rules / Contract Rules / Scoring + Weights / Entry + Exit Rules / Alerts / Display
- Active tab "Scoring + Weights" with blue text and left border
- 2-column form layout: label + description left, input field right
- Stock Score Weights: all 5 fields with exact values (Trend 30, Pullback 20, Trigger 20, Event 15, Volatility 15)
- Contract Score Weights: all 5 fields exact (DTE 25, Delta 20, IV 20, Liquidity 20, Spread 15)
- Total: 100% shown below each group
- Right rail: SETTINGS HELP header + explanatory content + Quant Tip callout

### DRIFTED
| # | Element | Spec | Stitch Output | Fix in Next.js |
|---|---------|------|---------------|----------------|
| 1 | Thresholds group | Visible with 3 fields | Below fold, not visible | Render all groups; add scroll or reduce padding |
| 2 | Save/Reset buttons | Visible at bottom | Below fold | Ensure action row always visible (sticky footer or reduce form padding) |
| 3 | Top bar extra icons | Mode toggle only | Bell + question mark + avatar | Remove non-spec icons |
| 4 | Field label weight | DM Sans 13px regular | Bold | font-weight: 400 in CSS |

### DECISION
Accepted as Screen 6 base. Cleanest screen of the set. Form structure is reference-quality.

---

## Global Drift (applies to all screens)
| # | Element | Issue | Fix in Next.js |
|---|---------|-------|----------------|
| G1 | Three-font rule | Stitch uses 1-2 fonts; cannot enforce Sora/DM Sans/JetBrains Mono split | Import all 3 fonts in globals.css; apply via className rules |
| G2 | Exact hex values | Stitch approximates colors | Define all tokens as CSS custom properties in globals.css |
| G3 | Row tinting | Stitch may use badges only | Apply bg + left-border via status-based className in React |
| G4 | Rail-to-stepper transform | Stitch cannot simulate interaction | Implement via React state in NavRail component |
| G5 | Score bar fill color logic | Stitch static; needs conditional color | Implement with conditional className based on value range |
| G6 | DTE progress bar | Stitch cannot compute fill % | Calculate in React from DTE remaining/total |
| G7 | Inline chart panel slide-up | Animation not possible in Stitch | Implement with Framer Motion in Next.js |
