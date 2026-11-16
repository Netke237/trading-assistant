# Step 7 Trade Card (Options): visual conformity review against the frozen reference

Reviewer: independent visual design reviewer (fresh context, read-only). Ticket #610, phase TRADE-CARD-REFERENCE-ALIGNMENT.
Branch reviewed: `claude/ui-layout-information-design-1n94si` @ `d952045` (working tree clean), served by the local mocked dev server on :3097.
Reference: `d8245e66:docs/superpowers/specs/2026-11-09-trade-card-reference/` (README, IMPLEMENTATION-GAPS D01–D12 and placement amendment, preview.html, reference.css/js, rendered evidence).

The supplied captures were taken at deviceScaleFactor 0.5, which makes small type unreadable. I re-ran the repo's own capture scripts at deviceScaleFactor 1, with only that change, the same mocks and write guard, and 1366px dark and light. Output is in `visual-review/hi/{methods,decision,race,reviews}/` and those are the files cited below. All paths are under
`/tmp/claude-0/-home-user-trading-assistant/34857055-8b5f-5a56-bdd2-4698e5d222a9/scratchpad/visual-review/`.

## 1. Verdict: PARTLY

The structure now follows the reference. Monte Carlo opens alone by default. Market Sentiment, then Fundamental Health, then identity, then Contract Details, then a collapsed Stock Qualification, then one Exit Plan, then methods, then entry/size, then Decision & execution. The Barrier Race sits in a default-closed disclosure inside Monte Carlo. Target tables share one column order. Final Recommendation is gone. Strike/right and expiry are about 30px and 25px. The D01–D12 information moves have mostly happened.

The page still does not look like the agreed design. It reads as a long wall of low-contrast microtext:
- About 140 explanatory lines in TradeCard/BarrierRaceCard/MethodPickSelector use `Text size={10}`. That size forces UPPERCASE with 0.08em tracking, and most use `tone="dim"`. Measured contrast of `--text-dim` on `--bg-surface` is 1.66:1 in dark and 2.52:1 in light. The reference's muted text is about 8:1.
- The method switch is a checkbox fieldset, not the reference's segmented buttons.
- The Monte Carlo inputs and Run button do not match the reference layout. The "T 1" label breaks onto two lines, the inputs stretch, and Run is not a primary button.
- Order inputs are two unequal cards with large empty space. The reference has one compact three-column Entry & position size card.
- Target-table and Barrier-Race cells wrap badly, including mid-word header breaks.
- A full submission review (~1,000px) is always open inside Decision & execution, and the broker review is a ~20-row single column. The reference has a compact choice / selected-target / one-row actions block and grouped three-column reviews.

The initial page is 4,483px tall in an 846px content column. The reference is 2,896px in 1,160px. Rail widths differ, but the extra length is mostly avoidable prose and padding, not information.

## 2. Gap list

Severity: **BLOCKS** = a reader would clearly see the page does not match the agreed design. **MINOR** = polish. Every fix is presentation only. No number, formula, payload, persistence, freshness or alert rule changes, and nothing is deleted: long prose moves into existing default-closed disclosures, and actionable warnings stay visible.

### G1. Explanatory text is uppercase microtext at near-invisible contrast (whole page, both themes)
- **Reference:** sentence-case notes at 12–13px in a muted colour with strong contrast (`.note`, `.hint`, `.detailbody`: 12–13px `--muted #a8b4b9` on `#191e21`). Uppercase is used only for short eyebrows such as "UNDERLYING", "SELECTED CONTRACT" and "CHOOSE THE METHOD FOR THIS TRADE".
- **App:**
  - `primitives/Text.module.css .s10` forces `text-transform: uppercase; letter-spacing: .08em`.
  - TradeCard uses `size={10}` 80 times, BarrierRaceCard 43, SendToBrokerDialog 15, MethodPickSelector 5. Most are `tone="dim"` (`--text-dim #434651` on `#1E2335`, 1.66:1; light `#9BA3B8` on white, 2.52:1).
  - Examples: the "SHOWING OR COMPARING METHODS IS DISPLAY ONLY…" paragraph, "MONTE CARLO ESTIMATE — INDEPENDENT…", "T1/T2/T3 ARE EDITABLE…", the MC/Arithmetic table footnotes, "CURRENT-TIME STOP COST…", the whole Barrier Race prose block, "SCAN MID × ENTERED CONTRACTS…", "A RECORD OF WHICH STOP…", "RECORDED CHOICE · STORED WITH THE TRADE", "SENDING STAYS BLOCKED UNTIL A METHOD IS CHOSEN".
  - See `hi/methods/1366-dark-calculated.png`, `hi/race/1366-dark-race-open.png`, `hi/decision/1366-dark-mc-selected.png` and `sbs-05`, `sbs-06`, `sbs-07`.
- **Severity:** BLOCKS. It is the single most visible difference, and it hides material caveats.
- **Fix:** do not change the shared primitive, because `.s10` is used app-wide. In these components:
  - Change every sentence or paragraph rendered with `<Text size={10} tone="dim">` to `<Text size={12} tone="secondary">`. Keep `tone="caution"`/`"reject"` where they are, but at `size={12}`.
  - Keep `size={10}` only for one- to three-word eyebrows (section labels like "Target row", "Judged on"). Give those `tone="secondary"`, never `dim`.
  - Use `tone="dim"` only for disabled-control text.
  - Move long prose that is not a material caveat into the card's existing default-closed disclosure. Examples: the "display only" paragraph, "independent of the other methods", the "Probability is each target's touch…" footnote beyond its first sentence, the "Current-time stop cost…" paragraph, and the Barrier Race "same simulation…" text.
  - Keep visible, in sentence case: stale/changed-barrier warnings, "This stop price is not automatically monitored by alerts unless copied…", "Sending stays blocked until a method is chosen", the "not a protective broker order" notice, and spread-basis cautions.

### G2. Identity block layout and font (D02 / reference identity)
- **Reference:** a two-column grid (`.identity` 1fr / 1.6fr). Left: "UNDERLYING" eyebrow, ticker 32px bold sans with chart icon and direction badge, then "Apple Inc. · Stock $200.00", then the Final status badge. Right: an accent left border (`border-left:2px solid mint`) with a "SELECTED CONTRACT" eyebrow, "$205 CALL" at 30px/600 sans, "Expires 18 December 2026" at 25px/500 on its own line, and "43 days to expiry · Option mid $5.00 / share" at 14px muted. Candidate navigation is a thin inline text row with Pin to basket on the right (`ref/reference-initial.png`).
- **App:**
  - Everything is in a single column: the ticker in 24px **monospace**, then company, price, PASS and BULLISH, then "Final Status PASS" on its own row.
  - Then "$185 Call" in **mono** 30px sits inline with "Expires 18 Dec 2026" in 25px sans. The fonts are mixed, the expiry month is abbreviated, and the two wrap together.
  - Then six more lines before Contract Details: the snapshot note, "Stock score 82/100 · PASS", "Backtested confidence: 72%", the raw ID `AAPL|185|2026-12-18|C`, "Contract score 78/100 · PASS" and "$2.15 mid / share · 75d DTE · $215 CaR".
  - Candidate nav is its own bordered card with Prev/Next buttons and a dim uppercase "BASKET — empty" line (`hi/methods/1366-dark-initial.png` y≈390–1000, `sbs-01`).
- **Severity:** BLOCKS.
- **Fix:** in `TradeCard/index.tsx` header section (~l.2498–2575) and `TradeCard.module.css` `.headerCard/.contractHeadline*`:
  - Make the header a two-column grid (`grid-template-columns: minmax(0,1fr) minmax(0,1.6fr)`, collapsing to one column under ~900px). Put SymbolHeader plus Final Status on the left. Put the contract on the right with `border-left: 2px solid var(--accent)`.
  - Render strike/right with `Text weight={600}` (sans), not `Data`, keeping the 30px class. Put the expiry on its own line (`.contractHeadlineMain { flex-direction: column }`) using `readableExpiry`'s long month if available.
  - Under it, show one 13–14px secondary metadata line: "75 days to expiry · Option mid $2.15 / share". The values already exist.
  - Move the remaining identity facts without deleting them:
    - stock score and backtested confidence go into the Stock Qualification summary title, e.g. "Stock qualification · 82/100 PASS · backtested 72%";
    - contract score goes into the Contract Qualification summary title;
    - the raw contract ID and CaR go into the Contract Details header meta (raw ID as secondary evidence, per D02);
    - the snapshot note becomes Contract Details' right-aligned header meta.
  - Restyle the candidate nav (page.tsx) as a borderless inline row: "‹ Previous · AAPL 1/2 · Next ›" on the left; "Pin to basket" and the "Basket — empty" text in 12px secondary sentence case on the right.

### G3. Contract Details legibility
- **Reference:** its own bordered panel with a header row ("Contract Details" at 19px, meta "Contract snapshot · always visible", divider). Below, a 5-column grid of 12–13px secondary sentence-case labels ("Strike", "Theta / day", "IV rank", "Capital at risk") over bold 15px values.
- **App:**
  - Contract Details is a sub-block of the header card.
  - Its labels are `DetailCell` → `<Text size={10} tone="dim">{label.toUpperCase()}</Text>`, which renders "STRIKE", "Δ", "Θ / DAY", "CAR" at 1.66:1 contrast, so the labels are effectively invisible in dark.
  - Values are 13px, with mono and sans mixed in one grid. Theta shows as "$-0.05" (`hi/methods/1366-dark-initial.png`, `sbs-01`).
- **Severity:** BLOCKS. The reference calls these "visible", and today they are not readable.
- **Fix:**
  - `DetailCell` (index.tsx ~l.4563): label becomes `<Text size={12} tone="secondary">` without `toUpperCase`. Write the labels out: "Delta", "Theta / day", "Capital at risk" (keep the Δ/Θ symbols in a `title` if wanted). Value becomes `size={14} weight={600}` with one family, sans or mono, used consistently.
  - Wrap the section as a bordered sub-panel with a header row (title left, meta right, `border-bottom: 1px solid var(--border-subtle)`).
  - Display-format theta as "−$0.05", sign before the currency symbol. The value is unchanged.

### G4. Qualification / Alternatives placement and disclosure style
- **Reference:** Stock qualification is a full-width bordered disclosure directly under Contract Details, closed. Contract qualification and Alternative contracts are separate full-width bordered disclosures **after Decision & execution**, just above the "View chart · Export JSON" footer. Summary rows are 13px with an accent "›" chevron.
- **App:**
  - Stock Qualification is correctly right under Contract Details and collapsed.
  - Contract Qualification follows it immediately, inside the identity card, before the Exit Plan.
  - Alternatives is a different control: a dim 11px uppercase "ALTERNATIVES (1)" button with a ▼ glyph (`hi/methods/1366-dark-initial.png` y≈1000–1120, `sbs-01`).
- **Severity:** MINOR for Contract Qualification placement: it is closed, so the cost is two rows before the Exit Plan, but it is a reading-order difference from the reference. MINOR for the Alternatives control style.
- **Fix:**
  - Move the Contract Qualification `CollapsibleSection` and the Alternatives block out of the header section to after the Decision & execution section, at the end of the card. Render Alternatives with the same `CollapsibleSection` (title "Alternative contracts (1)", default collapsed) instead of the bespoke `.altToggle` uppercase button.
  - Make the `CollapsibleSection` chevron use `var(--accent)` "›", consistent with the summary style in G13.
  - Do not touch `storageKey`s.

### G5. Exit Plan is not compact (D04)
- **Reference** (`sbs-02`): panel header with divider, then three columns.
  - Invalidation: label "Invalidation · stock price" plus an EDITABLE tag, and a 21px input.
  - Premium stop: "Premium stop · loss / share", the input with an inline caution "60% loss", then one bold line "Remaining: $2.00 / share · $200.00 / contract" and one line "Loss: $300.00 / contract".
  - Time exit: "3 days to expiry" in 21px mono on **one line**.
  - Then **one** full-width disclosure row, "Exit Plan explanation · stop basis, premium & time exit". About 255px tall.
- **App** (`hi/methods/1366-dark-initial.png` y≈1163–1613, `sbs-02`):
  - Under the premium input are "(GLOBAL 60%)" in uppercase dim and "Loss amount per option share" in dim.
  - Then a divider and a 2×2 KV grid: "Premium-loss %", "Remaining option value per share", "Loss per contract (×100 shares)", "Remaining option value per contract (×100 shares)". The labels wrap to 2–3 lines and the values are 16px.
  - Then a nested "Premium basis & quantity breakdown" disclosure, and two more full-width disclosures, "How these exit settings are resolved" and "Structure evidence · ATR, pricing & Check structure".
  - "3 days to expiry" wraps onto two lines.
  - The invalidation hint "Stock price · execution invalidation" is dim.
  - About 450px tall.
- **Severity:** BLOCKS.
- **Fix** (index.tsx ~l.2694–2830, CSS `.exitEssentials/.exitColumn`):
  - Fold the descriptions into the labels ("Invalidation · stock price", "Premium stop · loss / share").
  - Render the loss % as a caution/secondary chip next to the input ("60% loss", with "global" as `title` or in the explanation).
  - Replace the 2×2 KV grid with two summary lines: `<Text size={12} weight={600}>Remaining: $0.86 / share · $86.00 / contract</Text>` and `<Text size={12} tone="secondary">Loss: $129.00 / contract</Text>`. These are the same values, and the D04 "succinct remaining value / per-contract loss" requirement is kept.
  - Merge "Premium basis & quantity breakdown", "How these exit settings are resolved" and "Structure evidence…" into **one** default-closed "Exit Plan explanation · stop basis, premium, structure & time exit". Inside it, use three sub-disclosures or headed blocks so Check structure stays reachable.
  - Time exit: `white-space: nowrap` and about 21–22px (or `font-size: clamp(18px, 2vw, 22px)`), with "Alert at ≤3 DTE · no automatic close" in 12px secondary.
  - Keep any conditional missing/invalid warnings visible above the explanation row.

### G6. Method switch control (D01 presentation)
- **Reference:** heading "Method results" at 21px, with a right-aligned **segmented button group** [Monte Carlo] [Arithmetic] [Ladder] [Compare]. The active button has an accent border and text. A one-line sentence-case hint appears only while comparing.
- **App:**
  - "Profit-target methods" at 16px, with a bordered fieldset legend "Show side by side" holding three checkboxes (Monte Carlo is checked and disabled).
  - Below them is a three-line UPPERCASE dim paragraph ("SHOWING OR COMPARING METHODS IS DISPLAY ONLY…") (`hi/methods/1366-dark-initial.png` y≈1640–1745, `sbs-03`).
- **Severity:** BLOCKS. This is the agreed primary interaction.
- **Fix** (`molecules/MethodCompareSelector`):
  - Keep the same controlled multi-select semantics, but render toggle buttons (`<button aria-pressed>` styled like `.btn`, with the active state `border-color: var(--accent); color: var(--accent)`). Use labels "Monte Carlo", "Arithmetic", "Ladder", and, optionally, a "Compare" button that sets all three.
  - It must never run, select or apply anything, as today.
  - Drop the fieldset border and legend, or make the legend visually hidden for a11y.
  - Rename the heading to "Method results", or keep the name but at 18–20px to match the other section titles.
  - Move the "display only…" paragraph to sentence-case 12px secondary text shown only when more than one method is open, or into the "How this page works" disclosure.

### G7. Monte Carlo card, unrun state: inputs, Run button and stop context
- **Reference:**
  - Panel header "Monte Carlo" with right meta "Your percentage targets".
  - Three 82px inputs with labels above ("T1 profit % · editable"), and a **primary** accent "Run Monte Carlo Estimate" button inline on the same row.
  - One sentence: "Run the estimate to see target values, probabilities and times."
  - Then three full-width disclosure rows: Structural level & availability; Barrier Race; Model explanations.
- **App** (`sbs-03`, `hi/methods/1366-dark-initial.png` y≈1755–2250):
  - The header "Monte Carlo Profit Target" is followed by two uppercase dim lines.
  - The labels "T"/"1" **break onto two lines** beside each input, because `.targetPctInput` is a row flex and the input is `width: 100%`. The inputs stretch to about 220px each.
  - "Run Monte Carlo Estimate" is a full-width plain outlined bar, not a primary button.
  - Then a dim paragraph and "Captured request premium (rounded to cents): Not yet estimated".
  - Then the stop-context grid with the same "Unavailable — run or re-run estimate to confirm barriers" repeated four times in bold 13px mono.
- **Severity:** BLOCKS.
- **Fix** (index.tsx ~l.3069–3160, CSS `.targetPctRow/.targetPctInput/.structuralStop`):
  - `.targetPctInput { flex-direction: column; align-items: flex-start; }` with label `<Text size={12} tone="secondary">T1 profit %</Text>` and the input `width: 80px` (keep the % suffix inside the label).
  - Put the Run button in the same flex row (`.targetPctRow { align-items: flex-end; flex-wrap: wrap }`) with `className={`${styles.btn} ${styles.btnPrimary}`}`. Disabled logic is unchanged.
  - Replace the two header uppercase lines with a right-aligned header meta ("Your percentage targets"). Move "independent of the other methods" and "1–500%" into the model disclosure, or into input `title`/helper text at 12px.
  - Unrun: show the stop-context labels with "—" values and **one** 12px secondary line under the grid: "Unavailable — run or re-run the estimate to confirm barriers". Same text, once. Keep the per-cell text unchanged in the stale/changed-barrier state if that is the actionable case.
  - Show "Captured request premium" in the stop/basis area only after a run, or as one short line ("Premium basis: not yet estimated").

### G8. Target tables: wrapping and header legibility (D07)
- **Reference:** a shaded header row (`th` 11px muted normal-case on a darker band), `td` 14px mono, `white-space: nowrap`, one line per row, time as "~4d", probability in accent. A single short sentence-case footnote follows the table.
- **App** (compare state, `hi/methods/1366-dark-calculated.png` y≈2250–2900, `sbs-05`):
  - Headers are 11px `--text-dim` (1.66:1) and wrap to three lines ("Probability (independent touch)", "Stock price (resolved target)").
  - "~7 calendar days" wraps to three lines and "2:1 target" to two, so each row is about 80px.
  - A 5–6-line uppercase dim footnote follows.
  - In MC-only full width (`hi/race/1366-dark-race-open.png`) the table is fine apart from header contrast.
  - The Ladder table in `hi/methods/1366-dark-calculated.png` y≈3420–3600 wraps "Not supplied" and the uppercase "1 CONTRACTS × 100 SHARES" sub-lines.
- **Severity:** BLOCKS. Compare is a required state, and its rows are hard to scan.
- **Fix** (`TradeCard.module.css .mcTargetTable`):
  - `td { white-space: nowrap }`, and rely on the existing `.mcTableScroll` horizontal scroll when the card is too narrow. Allow header wrap only.
  - `thead th { color: var(--text-secondary); background: color-mix(in srgb, var(--bg-base) 50%, var(--bg-surface)); padding: 8px; }`.
  - Display time as "~7d" and move the unit into the header: "Conditional time (calendar days)". This is the same value with presentation-only formatting.
  - Put the long qualifier text ("independent touch", "resolved target", "before expiry") in a second header line at 10–11px secondary, or in the footnote.
  - Shorten "2:1 target" to "2:1" in the cell; the header already says Target.
  - Footnotes: keep the first sentence (the probability meaning) visible at 12px secondary sentence case, and move the rest into the method's disclosure.
  - Ladder rung sub-line: 11px secondary, not uppercase.

### G9. Barrier Race inside Monte Carlo (D09)
- **Reference** (`ref/reference-race.png`, `sbs-06`):
  - Legend first, then **one large stacked bar per target**: full width, 32px tall, percentages printed inside each segment, labelled "T1 · +20% · $6.00 option".
  - Then a table with target buttons ("T1 · +20% / $6.00"), Target first / Stock stop / Premium stop / Neither / Median columns.
  - One sentence-case footnote, then a nested "Stop medians, risk arithmetic & assumptions" disclosure.
- **App** (`hi/race/1366-dark-race-open.png` y≈2400–3520; compare width in `hi/methods/1366-dark-details-open.png`):
  - Nesting and default-closed state are correct.
  - Inside, it opens with about 400px of uppercase dim prose and the "three barriers" table before the graphic.
  - The bars are `.bar { height: 10px; max-width: 180px }` with no in-bar labels.
  - Column headers break mid-word ("TARG/ET FIRST", "STOC/K STOP", "PREMI/UM STOP", "NEIT/HER").
  - Each target cell stacks "20% / $2.58 / ESTIMATED DOLLAR OUTCOME / $43.00 / Use target".
  - In the compare card the race table is clipped at the right edge, and the barrier table breaks words per character ("Profi/t/targ/et", "Pre/miu/m/stop").
- **Severity:** BLOCKS. The graphic is the point of D09.
- **Fix** (`organisms/BarrierRaceCard`):
  - Order the content as: legend, then per-target labelled bars, then the outcomes table, then a one-line footnote ("2,000 paths · each row sums to 100% · medians conditional · IV unchanged · edge before commissions"). Put "The three barriers" table and all paragraphs into the existing nested "Stop medians, full risk / R:R / edge…" disclosure, or a second "Barriers & assumptions" disclosure. Keep the stale/changed-barrier caution visible at the top.
  - Bars: render them as their own row above the table (one per target) with `height: 28–32px; max-width: none; width: 100%`. Print `40%` inside a segment when the segment is wide enough, `font: 11–12px var(--font-mono); color: #fff` (or `--text-primary` on the tint).
  - Table: `th { white-space: nowrap }` at 11px secondary (not size-10 uppercase), `td { white-space: nowrap }`, inside an `overflow-x: auto` wrapper. Do not use `overflow-wrap: anywhere` on this table: the MC slot's inherited `overflow-wrap: anywhere` is what breaks the words, so set `overflow-wrap: normal` on the race card root.
  - Target cell: one line "T20% · $2.58", with the dollar outcome as its own column ("Est. dollar outcome") and the "Use target" button kept in the cell.

### G10. Entry & position size
- **Reference** (`sbs-04`): one panel, "Entry & position size", with header meta "Existing fields" and three columns:
  - "Limit · order type LIMIT" + EDITABLE, a 21px input, and "Max fill $5.10";
  - "Contracts" + EDITABLE, an input, and "Capital at risk $500.00";
  - "Max-loss budget" "$300", "Account default".
  - Then one default-closed "Risk-derived size & budget override" row. About 245px tall.
- **App** (`hi/methods/1366-dark-initial.png` y≈2260–2730):
  - A section title "Order inputs & risk budget" plus a two-line paragraph.
  - Then two cards. "Order Entry" is a KV list with right-aligned inputs and about 230px of empty space below. "Trade loss budget & sizing" has an uppercase "MAX LOSS BUDGET" eyebrow, a "Set trade loss budget" button, "Entered quantity", "Full-premium exposure", three uppercase dim paragraphs and, after calculation, "Risk-derived size … Apply". About 470px tall.
- **Severity:** BLOCKS.
- **Fix** (index.tsx ~l.3636–3800, CSS `.orderStrip/.handlingGrid`):
  - Use one `planCard` titled "Entry & position size" with a 3-column grid: Limit (input plus Order type in the label, "Max fill $2.20" as a hint), Contracts (input, plus "Full-premium exposure $215" as the hint — the reference labels this "Capital at risk"; keep the app's own label), and Max-loss budget ("$3,750", "Account default").
  - Move "Set trade loss budget", "Entered quantity", the Arithmetic stop-loss estimate, "Risk-derived size … Apply" and the three explanatory paragraphs into one default-closed "Risk-derived size & budget override" disclosure. An active override or an over-budget warning, if any, stays visible.
  - Drop the separate section title paragraph, or reduce it to header meta.

### G11. Decision & execution: choices and selected-target review (D10/D11)
- **Reference** (`sbs-07`, `ref/reference-decision.png`):
  - A panel header with a divider.
  - Left column: an uppercase eyebrow "CHOOSE THE METHOD FOR THIS TRADE" and **one row** of equal compact buttons (Monte Carlo, Arithmetic, Ladder, Barrier Race, Clear). Then "CHOOSE A TARGET ROW" and **target cards** in a 3-column grid, each card showing "T2 · +40%", bold 17px "$206.10 stock", and "$7.00 option · ~7d". Then "JUDGED ON" buttons and a sentence-case note.
  - Right column: "Your selected target · preview", a 2-column grid of 8 facts with 22px mono values (method/target, contracts, stock TP, option at TP, probability, time, full-position profit, full-position value), and one footnote.
- **App** (`hi/decision/1366-dark-mc-selected.png` y≈2975–3600):
  - The method buttons wrap unevenly (Ladder + Arithmetic, then Monte Carlo + Barrier Race), each with a dim uppercase sub-label ("COMPUTE ARITHMETIC PLAN FIRST", "3 TARGETS").
  - "Clear" is a dim 10px uppercase underlined link in the corner.
  - Target chips show only "T35%" plus a dim "$2.90".
  - The selected-target panel is a 16-row KV list at 12–13px with dim uppercase group labels, a raw ISO timestamp "2026-11-09T18:16:28.402Z" and long wrapped values. Its values are no larger than the labels.
  - Two separate paragraphs below repeat the "doesn't apply / set once in the Exit Plan" message.
- **Severity:** BLOCKS.
- **Fix:**
  - `MethodPickSelector`: method buttons as a single non-wrapping row of equal `min-width` buttons (label 12–13px). Show the unavailable reason as the button `title` plus a 12px secondary line under the row only for the disabled ones ("Arithmetic: compute the Arithmetic plan first"), not as uppercase sub-labels. Render Clear as a normal `.btn` at the end of the row.
  - Target rows: render as cards in `grid-template-columns: repeat(auto-fill, minmax(150px,1fr))` with label 12px, primary price 15–16px weight 600, and secondary 12px. If `MethodPickRow` carries only `displayPrice`, either show that larger, or pass the already-displayed stock price, option value and time of the same result row through as additional display props. No new computation.
  - Group labels: `size={11} tone="secondary"` eyebrows.
  - Selected-target panel: lead with a 2-column grid of the essentials (Method / target, Contracts, Stock target, Option at target, Probability, Conditional time, Est. dollar outcome, Applicable quantity), each with a 12px secondary label and a 18–22px mono value. Move "Recorded choice · stored with the trade", "Decision timestamp", "Result pricing model", "computed via…" and the long gross-before-costs note into a default-closed "Recorded decision details" disclosure. Display-format the timestamp (e.g. "9 Nov 2026, 18:16:28 UTC"); the stored value is unchanged.
  - Merge the two paragraphs under the selector into the reference's single line: "Review the single Exit Plan above ↑ — selecting a method or target does not replace those settings or run a calculation."

### G12. Inline submission review and action row (D11/D12)
- **Reference:** after the decision grid comes the Exit Plan link line, then **one action row** with "Execute via [broker select]" on the left and three buttons on the right: Review broker limit order, Review broker market order, Review basket tracking. Then a default-closed "Execution requirements, tracking & auto-trade" row. The "what will be sent" review appears only after clicking a review button (`sbs-08` left).
- **App** (`hi/decision/1366-dark-mc-selected.png` y≈3600–4700, `sbs-08`):
  - A full "Submission review" (~950px: Destination & request, Position settings, Recorded decision & target alert, 20+ KV rows in 13px mono with long wrapped strings) is **always open** inside Decision & execution.
  - Then "Track basket / View chart / Export JSON".
  - Then a separate "Broker execution & auto-trade" block with "Live mid", "Live stock", a dim "Execute via", broker chips, Place Limit and Right Now — Market buttons, and the auto-trade mode.
- **Severity:** BLOCKS. It roughly doubles the decision area and splits the actions.
- **Fix** (`step-7-trade-card/page.tsx` ~l.1641 and ~l.1927, `SubmissionReview`):
  - Put `<SubmissionReview>` inside a default-closed disclosure ("What Track basket and direct sends will submit"), **keeping visible** next to the buttons any blocking or actionable line: "Sending stays blocked until a method is chosen", re-review / changed-server-value warnings, and "provisional — server re-quotes at save".
  - Lay out one action row: broker picker (the existing chips are acceptable; a select is not required), then Place Limit, Right Now — Market and Track basket as peers aligned right. View chart and Export JSON go to the page footer, as in the reference.
  - Move Live mid/stock into the broker picker hint at 12px secondary. Move auto-trade mode into the default-closed "Execution requirements, tracking & auto-trade" disclosure, keeping the Armed state visible when active.
  - Server review, fingerprint and staleness logic are unchanged.

### G13. Disclosure (summary) rows are inconsistent and weak
- **Reference:** every disclosure is a full-width row with `border-top: 1px solid var(--line)`, 12×22px padding, 13px light-muted text and an accent "›" that rotates when open.
- **App:** there are three styles.
  - `CollapsibleSection`: bordered rounded boxes with a dim ▸ on the right.
  - Native `<details>`: 12px secondary with a ▶ glyph and no divider ("How these exit settings are resolved", "Monte Carlo model, inputs & provenance").
  - Links in blue accent ("Technical details and provenance", "Stop medians, full risk…").
  - See `hi/methods/1366-dark-initial.png` and `hi/race/1366-dark-race-open.png`.
- **Severity:** MINOR, but fixing it does much of the "card with expansion rows" look.
- **Fix:** add one shared class in `TradeCard.module.css` (e.g. `.disclosureRow > summary`): `list-style: none; padding: 10px 0; border-top: 1px solid var(--border-subtle); font-size: 13px; color: var(--text-secondary)`, plus `::before { content: '›'; color: var(--accent); margin-right: 10px }` that rotates 90° when `[open]`. Apply it to all the card-level `<details>`, and bleed it to the card edges with negative horizontal margins to match the reference. Leave `CollapsibleSection` for the Stock/Contract Qualification boxes.

### G14. Section and card heading hierarchy
- **Reference:** every panel has a header bar (19–21px title, optional right meta, bottom divider). Section titles are consistent: Contract Details, Exit Plan, Method results, Monte Carlo, Entry & position size, Decision & execution.
- **App:** sizes are inconsistent. Exit Plan uses `Title size={20}`; "Profit-target methods" is 16px; method cards 14px/600; "Order Entry"/"Trade loss…" 14px; "Decision & execution" about 14px. There are no header dividers, and the Arithmetic card's right meta is "Bullish".
- **Severity:** MINOR.
- **Fix:**
  - Give every top-level card the same header row: Title 18–20px, right meta `Text size={11} tone="secondary"`, `padding-bottom: var(--space-3); border-bottom: 1px solid var(--border-subtle)`.
  - Shorten the method card titles to "Monte Carlo", "Arithmetic", "Ladder", with meta "Your percentage targets", "Structure + ATR", "Fixed-formula ladder".
  - Drop the Ladder card's extra "Sell-to-Close Plan" sub-heading, or make it the meta.

### G15. Editable affordance labels
- **Reference:** a small accent "EDITABLE" tag after each editable field's label. Inputs are a consistent size (21px for Exit Plan / Limit, 14px for small ones).
- **App:** tint and border are present (good). There are no EDITABLE tags. The Exit Plan editables are 24px mono boxes sized to content, while Limit/Contracts are 28px-tall full-width right-aligned bars.
- **Severity:** MINOR.
- **Fix:** add `<Text size={10} tone="accent">Editable</Text>` (the eyebrow use of size 10 is fine) after editable labels. Give Limit and Contracts the same left-aligned fixed-width (about 150px / 80px) treatment as the Exit Plan inputs.

### G16. Destination reviews (basket dialog and broker review)
- **Reference** (`ref/reference-basket-review.png`, `ref/reference-broker-review.png`): a sticky header ("Add to Portfolio tracking" / "Send to IBKR Paper", eyebrow "REVIEW BEFORE CONFIRMING") and three groups — Destination & request, Position settings, Decision & supporting estimate. Each group is a **3-column fact grid**: 12px muted label over an 18px bold value. Short sentence-case notes follow, and a footer has Back / Confirm.
- **App, basket** (`hi/reviews/1366-dark-basket.png`, `sbs-09`): a dense Field / Requested / Server-resolved table in 12–13px with dim uppercase group labels ("POSITION SETTINGS · IN-APP ALERTS", "TARGET ALERT BASIS"). The requested-vs-resolved columns are a good addition. There is no "Decision & supporting estimate" group (method/target/judgement/probability/time).
- **App, broker** (`hi/reviews/1366-dark-broker.png`, `sbs-10`, page context in `tc609/1366-dark-broker-review.png`): an inline panel with **one long single column** of about 20 label/value pairs in 13px mono, dim 12px labels, and long parenthetical values, followed by Send / Cancel.
- **Severity:** BLOCKS for the broker review (layout clearly unlike the agreed grouped grid). MINOR for the basket dialog (structured, but small and low-contrast).
- **Fix:**
  - `BrokerOrderReview`: wrap each group (`role=group` already exists) in a `display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 16px 22px` (2 columns under ~700px). Labels `Text size={12} tone="secondary"`, values `size={14–16} weight={600}`. Long qualifiers ("— as entered in Settings → Brokers…", "a buy limit fills at or below it…") become a 12px secondary hint line under the value, not part of it. Group headings become `Text size={13} weight={600}`. Keep the no-protective-order and estimate-not-fill notes visible in sentence case.
  - Basket dialog (`SendToBrokerDialog`): group labels become `size={11} tone="secondary"` sentence case, not size-10 dim. Row text 13px, values in primary colour, and the "ADJUSTED — SAVE-TIME LIVE QUOTE" caution in 12px sentence case.
  - In both, if the submission draft already carries the recorded method/target/judged-on/probability/time (SubmissionReview shows them), present them as a "Decision & supporting estimate" group. These are display-only copies of already-reviewed fields; do not add any computation.

### G17. Page length and spacing (summary metric)
- **Reference:** about 2,896px initial at 1,160px content width.
- **App:** 4,483px initial, 5,955px with three methods calculated, 4,848px with a method selected, at 846px content width (`hi/*`).
- **Severity:** follows from G1, G5, G7, G10, G11 and G12. After those, expect roughly 3,200–3,500px initial within the shell.
- **Fix:** none beyond those items. Do not compress padding below the token scale.

## 3. Already matches: do not disturb

- Monte Carlo is the only method open on load; opening or comparing runs and selects nothing (capture checks confirm). All three methods can be compared. Equal-height cards share a row with aligned slots (0px offsets measured), and the third card wraps to full width.
- Market Sentiment, then Fundamental Health (badges, colours, safety-flag chip, definitions disclosure) above the card.
- Strike/right about 30px and expiry about 25px with the year (only the font family and line break differ: G2).
- Stock Qualification directly under Contract Details, collapsed by default. Contract Qualification is kept as a distinct section.
- The single Exit Plan with three columns (Invalidation / Premium stop / Time exit), tinted editable boxes versus a read-only time exit, and Check structure reachable.
- Monte Carlo stop context as a four-fact grid (stock barrier, option barrier, value and loss at stock stop at barrier time), matching the reference; it is correctly hidden behind the caution in the stale state (`hi/methods/1366-dark-stale.png`).
- The stale/changed-barrier warning is visible in caution next to the affected figures. Only its type style changes under G1.
- Target tables share the same column order across Monte Carlo, Arithmetic and Ladder, with all rows visible, "Not supplied" for genuinely missing Ladder probability/time, and full-position and rung outcomes kept separate.
- The Barrier Race is nested in Monte Carlo's default-closed disclosure. Its "Use target" actions and full risk explanations exist.
- Final Recommendation is removed. Final Status sits in the identity. The selected-target review sits beside the choices in a two-column grid. The Judged-on control and its alert-semantics note are present.
- The basket review's requested-versus-server-resolved columns and adjusted-value caution, the server review/fingerprint/staleness flow, "Within risk limits", and the no-protective-order notices. These are stronger than the demo reference; keep the content.
- Light theme: tokens apply cleanly and surfaces, borders and accents are correct. Only the dim/uppercase legibility issue (G1) carries over at 2.52:1.

## 4. Side-by-side crops (reference left, app right; same device scale)

All are under `/tmp/claude-0/-home-user-trading-assistant/34857055-8b5f-5a56-bdd2-4698e5d222a9/scratchpad/visual-review/`:
- `sbs-01-identity-details.png`: G2, G3, G4
- `sbs-02-exit-plan.png`: G5
- `sbs-03-method-switch-mc-unrun.png`: G6, G7
- `sbs-04-entry-size.png`: G10
- `sbs-05-compare-tables.png`: G8, G1 (dark, compare)
- `sbs-06-barrier-race.png`: G9
- `sbs-07-decision.png`: G11
- `sbs-08-submission-inline.png`: G12
- `sbs-09-basket-review.png`: G16 (basket)
- `sbs-10-broker-review.png`: G16 (broker)
- `sbs-11-light-methods.png`: G1, G8 in light theme

Full-scale app captures are in `hi/methods/`, `hi/decision/`, `hi/race/` and `hi/reviews/`. They were made by copies of the repo capture scripts in `scripts/`, with deviceScaleFactor changed from 0.5 to 1 and nothing else.
