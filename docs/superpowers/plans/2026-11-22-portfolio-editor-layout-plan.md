# PORTFOLIO-EDITOR-LAYOUT plan (#662, umbrella #656)

Layout-only regroup of the Portfolio position editor (`frontend/app/(frame)/portfolio/EditDrawer.tsx`, main `EditDrawer` return at ~line 420). No field, handler, state, validation, save timing, alert logic or wording changes, except new section headings and one new `<details>` summary. Both files use CRLF; preserve it.

## Gate for this phase

The shipping gate is "wrong number in front of a user / broker order, or corrupted persisted data". For a layout move, the reachable risks are: a field dropped or duplicated (a user cannot edit a stop, or edits it twice), a handler rebound to the wrong field when JSX is moved, a conditional (`isStock`, `pendingIncrease`, `quoteUnavailable`) lost on the way, and the Current price field becoming unreachable. The inventory below is the checklist.

## Inventory of today's main `EditDrawer` return (before)

Header/frame (stay exactly as they are, above the sections):
- H1. Header row: "Edit {contract}" + close button (`aria-label="Close editor"`).
- H2. Entry reference card: "Stock at entry" (value or "—"/"not recorded"); option only: "Option at entry" + per share + contract cost line.

Flat `editGrid`, in today's DOM order:
1. `EditField` **Stop** (direction-aware hint, distance text, range)
2. `EditField` **Structural level** (hint, distance, range)
3. `PremiumStopEditor` (Premium stop % inherit/pin + help; its own existing conditions)
4. `TargetEditor` (Targets ladder: id, status, Stock, Est. option, Sell qty input, method line)
5. `ExitPlanEditor` (option only) (Compute Exit Plan + results, ATR-widened stop, 2R/3R rows, probability, warnings, "as of")
6. `MaxLossBanner` (option only) (Max loss at stop, PASS badge, limit line, risk-derived size line, Set override)
7. `PickedMethodRecord` ("Picked at trade" + help)
8. `TpMethodSelector` (Active TP method radiogroup + help; receives `mcTargetPrice={mcRungPrice}`)
9. `AlertOverridesEditor` (six types, Inherit/On/Off, "fires at" lines)
10. `div.addedFill`: `EditField` **Contracts** (zeroClears=false, draftEpoch, onCommit hold), "Average entry $x" text, conditional added-fill row (**Added fill price** input + **Confirm added fill**), `priceRejected` caution text, `exposureBreach` caution text
11. `EditField` **Current price** (quote-unavailable hint, placeholder, zeroMessage, onChange sets pnl fields, `quoteUnavailable:false`, `setPriceEditedSinceEstimate(true)`)

After the grid:
12. `div.mcSection`: heading "Monte Carlo estimate", Estimate button (loading "Estimating…"), `mcError`, no-live-price message (stock), "No stop set", stop-wrong-side message, structural-wrong-side message, every-target-reached message (stock), horizon note, result row (targets + STOP HIT), `modelCaveat`, stale-price notice.
13. `div.targetEditor`: "Notes" + `SymbolNotes`.
14. `div.editFooter`: autosave note + **Close position** button.

## Inventory after (target shape)

Frame H1, H2 unchanged. Then `div.editSections` (`grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))`, wraps on narrow widths), five `<section>` elements each with a heading and a body, then the unchanged footer (14):

| # | Section heading | Contents, in this DOM (= keyboard) order |
|---|---|---|
| S1 | Risk & stops | 1 Stop, 2 Structural level, 3 PremiumStopEditor, 6 MaxLossBanner (option only) |
| S2 | Targets & take-profit | 4 TargetEditor, 8 TpMethodSelector (MOVED up directly under targets), 7 PickedMethodRecord |
| S3 | Exit plan & odds | 5 ExitPlanEditor (option only), 12 Monte Carlo block (all messages; the state/handlers stay in `EditDrawer`) |
| S4 | Alerts for this position | 9 AlertOverridesEditor |
| S5 | Position (full width: `grid-column: 1 / -1`) | 10 Contracts + average entry + added-fill block, closed `<details>` "Manual overrides" holding 11 Current price (MOVED), 13 Notes |

Every numbered element 1–14 appears exactly once after; nothing new except the five headings and the `<details>` summary. Handlers, props and conditionals are cut-and-pasted unchanged. Section S3 for a stock position holds only the Monte Carlo block (ExitPlanEditor is option-only today).

Note on #7/#8 order: today the record sits above the selector (the comment says the two can legitimately disagree and both must be on screen). Both stay in S2 and visible together; only the order changes to match the item ("selector directly under the targets, Picked at trade after").

## Tickets

### T1 — Regroup into five sections (S1–S4 and the S5 shell) — layout, CSS, tests

Files: `EditDrawer.tsx`, `page.module.css` (new rules in one contiguous block labelled `Editor sections (#662)`, no reformatting of other rules, because #663 also edits this file), the three EditDrawer test files (selector updates only).

Tests first (red for the stated reason: no section elements exist):
- `getByRole('region', {name: 'Risk & stops'})` etc. — each `<section aria-labelledby>`. Assert for an option position: Stop, Structural level, Premium stop, Max loss are inside S1; Targets, Active TP method, Picked at trade inside S2 in that DOM order (selector after targets, record after selector); Compute Exit Plan and Monte Carlo Estimate inside S3; the six alert types inside S4; Contracts and Notes inside S5.
- A stock position: no Exit Plan, no Max loss, S3 holds the Monte Carlo block only.
- Inventory test: a rendered option position and a stock position each still render the labelled controls list of today (Stop, Structural level, Contracts, Current price, Estimate, Close position, Notes, etc.) exactly once.
- Keyboard order: `userEvent.tab()` sequence over interactive elements follows section order S1→S5 and, inside each section, DOM order (compare to `compareDocumentPosition`).
Implement; update only selectors in existing tests if a heading text collides with a `getByText` (do not delete behaviour assertions). Heading texts must not break existing `getByText(/position/i)`-style queries; if one collides, tighten that selector.

CSS: `.editSections` grid, `.editSection` (border `1px solid var(--border-subtle)`, no shadow, radius `var(--radius-sm)`, padding `var(--space-3)`, flex column gap), `.editSectionTitle` (font DM, size 11, weight 400/500, `var(--text-secondary)`), `.editSectionFull { grid-column: 1 / -1 }`. Use CSS variables only. The old `.editGrid` rule is left in place if still referenced by tests, else removed with the JSX; `.mcSection` loses nothing.

### T2 — "Manual overrides" fold for Current price, and Position section order

Files: `EditDrawer.tsx`, `page.module.css`, tests.

Tests first: Current price lives inside a `<details>` whose summary reads "Manual overrides" and which is closed by default (`open` false) and is inside S5; Contracts and Notes are not inside it; the existing Current price behaviour tests (typed price, refuse 0, quote-unavailable placeholder, stale-price notice after editing) pass unchanged when the details is closed (jsdom keeps closed content in the DOM and `getByLabelText` still finds it) and also after opening it; opening the details and editing the price sets "Price has changed since this estimate was computed." exactly as today.
Implement: S5 order = Contracts block, `<details className={styles.manualOverrides}><summary>Manual overrides</summary>…Current price EditField…</details>`, Notes. Add `.manualOverrides` rules in the #662 CSS block.

## Verification per ticket (the coordinator runs these itself)

`cd frontend && npm run typecheck`; `npx eslint` on every changed file (errors fail `next build`; warnings fine); the three editor suites plus `portfolio` folder suites run alone; full `npm run test` once at the end (re-run any timeout alone; test files must exit cleanly under `--runInBand` without `--forceExit`). Then `git merge origin/main` before code-audit round 1 and again before the PR.

## Out of scope

Field semantics, validation, save timing, alert logic and wording; the Portfolio table, History tab, `performanceStore` (#663); any change to subcomponent internals (`TargetEditor`, `ExitPlanEditor`, `MaxLossBanner`, `PremiumStopEditor`, `PickedMethodRecord`, `TpMethodSelector`, `AlertOverridesEditor`).

## Ratings

size M, complexity 3 (from the item). Completion milestone: plan written, 15%.
