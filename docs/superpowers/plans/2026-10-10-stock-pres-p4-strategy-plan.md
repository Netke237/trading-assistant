# STOCK-PRES-P4-STRATEGY — Strategy page (Stocks Step 4 of 6) in the Options layout

Phase id: `STOCK-PRES-P4-STRATEGY` · Board item / tracking issue: **#149** · Programme: #144
Branch: `board/stock-pres-p4-strategy-c81620d9` (cut from `main` `6ebb14bd`)
Design: `docs/superpowers/specs/2026-10-10-stock-presentation/` (`preview.html` → Strategy view, README D1–D14)
Decision: `STOCK-PRESENTATION-2026-10-10` + Kenneth's answers on #149 (2026-10-10, quoted below)

## Why

The Stocks Strategy page still has the pre-redesign layout. Kenneth approved proposal 02 (D9): the
same page in the Options layout, **every existing item kept with today's text and behaviour**, plus four
approved NEW items. This phase is presentation only.

## Kenneth's answers on #149 (2026-10-10) — they amend the item's limits

> 1. Option (a). OK to add a non-persisted `regimeSentiment` field to scanStore and to have Step 1 write
>    it. You may touch `frontend/lib/scanStore.ts` and `frontend/app/(frame)/screener/step-1-regime/page.tsx`
>    for this, in addition to step-4-stocks. If Step 1 has not loaded, hide the strip and show
>    "Market sentiment loads on Step 1".
> 2. Bearish "Looks for" wording approved as proposed in the table.

## The gate (audit_rule)

A finding blocks only if it can put a **wrong number in front of a user or on a broker order**, or
**corrupt persisted data**. A comment blocks only if it misstates mechanism.

## Scope

**Files this phase may change (nothing else):**
- `frontend/app/(frame)/screener/step-4-stocks/page.tsx`, `page.module.css`, `__tests__/**` (new test files)
- `frontend/lib/scanStore.ts` — one non-persisted field + its setter (T1 only)
- `frontend/app/(frame)/screener/step-1-regime/page.tsx` — write that field (T1 only)
- `frontend/app/(frame)/screener/step-1-regime/__tests__/**` (new test file, T1 only)
- this plan and `docs/superpowers/PROJECT_STATE.json` (coordinator only)

**Out:** backend, `frontend/types/` (the existing `SentimentData` type is imported, not changed),
`MarketSentiment` (used as is, `compact`), `HistoryPrefetchRow.tsx`, `StrategyParamsPanel`,
`MeanReversionConfirmPanel`, `DirectSendNotesPanel`, `lib/stockScan.ts`, persistence (no new persisted
key, no `version` bump), every P1/P2/P3/P5 file, the scan request, the strategy texts' meaning.

## Mechanism today (verified on `6ebb14bd`)

- `step-4-stocks/page.tsx` renders, top to bottom: header (STEP 4 OF 6, `Strategy`, "Pick a strategy and
  run a scan. Review the results on Backtest.", "Scanning full {universe} universe for stock setups");
  a `.grid` of 7 strategy `<button>` cards (label from `strategyLabel` with the profile-derived periods,
  `when`, regime-fit badge with `regimeFitTooltip`, Entry from `entryLabel` / Stop / Exit);
  `StrategyParamsPanel`; for `mean_reversion_multi` the `MeanReversionConfirmPanel` or the caution
  "profile unavailable" text, and "Reset signal confirmation to profile" when overridden; the run row
  (Run Stock Scan with `disabled` + `title` reasons, "Running backtest scan…", "Last stock scan: …" after
  mount); `HistoryPrefetchRow`; feedback `error` (reject) / `notice` (caution); `DirectSendNotesPanel`;
  "View Backtest results" when a stock result exists. `onRun` → `runStockScanWithContinuation` → on a
  current success `router.push('/screener/step-6-backtest')`; on a throw it writes feedback + error and
  `FAILED`.
- `scanStore` persists through an **allowlist** `partialize` (`frontend/lib/scanStore.ts` ~L882): a field
  not listed there is never written to localStorage. It holds `regime` / `combinedRegime` (status
  strings) and `regimeDirection` only — no sentiment numbers.
- Step 1 (`step-1-regime/page.tsx`) keeps the regime response in local `useState<MarketRegime>` and builds
  `pageSentiment: SentimentData | null` inline at render (~L140; `null` when there is no `regime.omm`),
  passed to the full `<MarketSentiment s={pageSentiment} />`. A failed fetch sets `regimeFetchFailed`.
- `scanStore.stockAfterScanIntent: Record<string, boolean>` (not persisted; reset in `merge`) is set per
  symbol by the position card's after-scan toggle. `runStockScanWithContinuation` would book, after the
  next scan, armed candidates whose `stock_status === 'PASS'` to the paper portfolio — **but only when
  `stockExecutionBlock()` returns null, and today it never does**: `lib/stockExecutionSession.ts` L109-111
  returns `STOCK_VALIDATION_UNAVAILABLE` ("Unvalidated — research only. Strategy validation is unavailable;
  broker sending and automatic arming are blocked.") unconditionally, so every armed PASS candidate is
  skipped (`lib/stockScan.ts` ~L372-376) and nothing is booked. The position card's after-scan mode already
  says so (`StockAutoTradeArm` L121-126: "After-scan intent saved for {symbol}. {stockExecutionBlock()}").
  (Plan round 1 finding P4-A1.)
- The Options "How this page works" pattern: `<details className={…pageExplanation}><summary>How this page
  works</summary>…</details>` (`step-7-trade-card/page.tsx` ~L1455, styles in its `page.module.css` L10-12).
- Step 4 shows the default screener context rail (`@contextRail/screener/default.tsx`, QuickLook), so the
  page's own content area at the 1280px minimum is roughly 900px wide.

## Target layout (preview.html → Strategy)

```
Header (unchanged text)
How this page works (NEW, collapsed)
Market Sentiment strip (NEW: compact MarketSentiment | "Market sentiment loads on Step 1")
┌ main column ─────────────────────────────┐ ┌ side column (aside, ~300px) ────────┐
│ Card "Choose a strategy": 7 cards         │ │ Card "Run scan": Run Stock Scan,     │
│   (+ NEW "Looks for: …" line per card)    │ │   last scan time, error / notice,    │
│ Card "Parameters": StrategyParamsPanel,   │ │   View Backtest results              │
│   Multi-Signal confirm panel / note,      │ │ Card "Pre-warm history":             │
│   Reset signal confirmation               │ │   HistoryPrefetchRow                 │
└───────────────────────────────────────────┘ │ Card "After-scan" (NEW, only if ≥1)  │
                                              │ DirectSendNotesPanel                 │
                                              └──────────────────────────────────────┘
```

Cards: `border: 1px solid var(--border-subtle)`, no shadow, `var(--bg-surface)`, existing tokens only.
Card titles: `<h2 className={styles.cardTitle}><Text size={14} weight={500}>…</Text></h2>`
(`.cardTitle { margin: 0; }`). Two columns (`grid-template-columns: minmax(0, 1fr) 300px; gap: 16px;
align-items: start`) at every width the app allows (≥1280px).

## Acceptance — this phase's slice of the mapping (nothing removed)

| # | Item today | Where it goes | Kind |
|---|---|---|---|
| M1 | Header: STEP 4 OF 6, title, "Pick a strategy…", "Scanning full … universe" | Page head, same text | EXISTING |
| M2 | 7 strategy cards: label, when, regime-fit badge + tooltip, Entry / Stop / Exit (bullish + bearish) | "Choose a strategy" card, same text, same click → `setActiveStrategy` | MOVED |
| M3 | — | "Looks for" line per card (bullish + bearish wording below) | NEW |
| M4 | StrategyParamsPanel (all props as today) | "Parameters" card, unchanged inside | MOVED |
| M5 | Multi-Signal MeanReversionConfirmPanel + its Reset + unavailable note | "Parameters" card, Multi-Signal only, same conditions | EXISTING |
| M6 | Run Stock Scan, disabled reasons (`title`), running label, last scan time | Side "Run scan" card, same conditions, same `onRun` | MOVED |
| M7 | HistoryPrefetchRow | Side "Pre-warm history" card, component unchanged | MOVED |
| M8 | Scan error / notice text | Side "Run scan" card, same tones | MOVED |
| M9 | DirectSendNotesPanel | Side column | MOVED |
| M10 | — | Market Sentiment strip | NEW |
| M11 | — | After-scan armed count | NEW |
| M12 | — | "How this page works" | NEW |
| M13 | "View Backtest results" (shown when a stock result exists; not in the drawn mapping, kept anyway) | Side "Run scan" card, same condition and route | MOVED |

Plus: Run → Backtest navigation and failure handling unchanged (all existing `step-4-stocks` tests green
without edits); typecheck + full Jest green; plan audit and code audit clean.

## Tasks (test-first; one ticket each; T1 → T2 → T3, serial — T2 and T3 both edit `page.tsx`)

### Task 1 — `scanStore.regimeSentiment`, written by Step 1

**Files:** `frontend/lib/scanStore.ts`, `frontend/app/(frame)/screener/step-1-regime/page.tsx`,
new `frontend/lib/__tests__/scanStoreRegimeSentiment.test.ts` (next to the existing `scanStore*.test.ts`), new
`frontend/app/(frame)/screener/step-1-regime/__tests__/regimeSentimentWrite.test.tsx`.

**Change:**
1. `ScanStoreState` gets `regimeSentiment: SentimentData | null` and
   `setRegimeSentiment: (s: SentimentData | null) => void` (import the type from `@/types/domain`), with a
   doc comment: written only by Step 1 from the regime response it already fetched, read by the Stocks
   Strategy page's strip; **deliberately not in `partialize`** (a stored sentiment would show stale
   numbers after a reload — the strip then shows "loads on Step 1" instead). Initial value `null`. Do
   **not** add it to `partialize`; do **not** bump `version`; `merge` keeps `current`'s value, which is
   already what a field absent from the persisted blob gets — verify, do not change `merge`.
2. Step 1: move the existing `pageSentiment` object literal into one module-level pure function in the
   same file, `sentimentFromRegime(r: MarketRegime, horizon: string): SentimentData | null` (returns `null`
   when `!r.omm`; otherwise exactly today's fields and values, with `horizon` as given). The page computes
   `pageSentiment = useMemo(() => (regime ? sentimentFromRegime(regime, context?.horizon ?? 'Swing') :
   null), [regime, context?.horizon])` — the full `MarketSentiment` shows exactly what it shows today.
   The store is written **inside `fetchRegime`, not by an effect** (the fetch's callbacks still run after
   the user leaves Step 1, as `setRegime` / `setCombinedRegime` already do; an effect on local state would
   not, leaving the strip on an older reading than the regime verdict — plan round 1 finding P4-A2):
   - at the start of `fetchRegime` (next to `setRegimeFetchFailed(false)`): `setRegimeSentiment(null)` —
     the strip never shows a reading older than the latest request;
   - in `.then(r => …)`, next to `setRegime(r.overall)`:
     `setRegimeSentiment(sentimentFromRegime(r, useScanStore.getState().context?.horizon ?? 'Swing'))`;
   - in `.catch`: `setRegimeSentiment(null)`.
   Add `setRegimeSentiment` to `fetchRegime`'s `useCallback` deps. No effect writes the store. No other
   Step 1 change.

**Tests first (must fail before the change):**
- store: initial `regimeSentiment` is `null`; `setRegimeSentiment(x)` stores `x`;
  `useScanStore.persist.getOptions().partialize!(useScanStore.getState())` has **no** `regimeSentiment` key
  after setting a value.
- Step 1 (harness of `step-1-regime/__tests__/verdictFollowsDirection.test.tsx`: mock `next/navigation`,
  `CandlestickChart`, `RunScanButton`, `NewsCard`, `MarketSentiment`, `@/lib/api`): with
  `getRegime` resolving `{ overall: 'PASS', regime_direction: 'BULL', omm: { state: 'Bull', p_stay: 0.8,
  stability: 'Stable', regime_age_days: 12, avg_regime_duration: 20, transition_row: [0.8, 0.1, 0.1],
  state_order: ['Bull', 'Bear', 'Choppy'] }, conviction_pct: 42,
  conviction_label: 'Moderate', alignment: 'Aligned', hmm_state: 'Trending' }` and context horizon
  `'Swing (5–15d)'`, the store ends with `regimeSentiment` equal to
  `{ horizon: 'Swing (5–15d)', timeframe: 'daily', state: 'Bull', p_stay: 0.8, stability: 'Stable',
  regime_age_days: 12, avg_regime_duration: 20, conviction_pct: 42, conviction_label: 'Moderate',
  interpretation: 'Market conviction: Moderate', hmm_state: 'Trending', alignment: 'Aligned',
  insufficient_data: false }`;
  a response without `omm` (store pre-seeded with a non-null value) ends with `null`;
  a rejected `getRegime` (pre-seeded non-null) ends with `null`;
  while `getRegime` is pending (store pre-seeded with reading A) `regimeSentiment` is `null`;
  **unmount before the response** (pre-seeded with reading A; render, `unmount()`, then resolve the pending
  promise with reading B): the store ends with B's sentiment, not A;
  the full `MarketSentiment` (mocked; capture its `s` prop) receives the same object Step 1 passed before.

**Commit:** `feat(step1): share the regime sentiment with the Stocks Strategy page (non-persisted)`

### Task 2 — Strategy page in the Options layout + How this page works + Looks for + after-scan count

**Files:** `frontend/app/(frame)/screener/step-4-stocks/page.tsx`, `page.module.css`, new
`frontend/app/(frame)/screener/step-4-stocks/__tests__/presentationLayout.test.tsx` and
`__tests__/afterScanUnblocked.test.tsx`.

**Change (no logic change; every M-row element keeps its JSX, props, conditions and handlers):**
1. Restructure the JSX into the target layout above. The side column is
   `<aside className={styles.side} aria-label="Scan actions">`; the main column
   `<div className={styles.stack}>`. Move elements; do not rewrite their conditions. The run row keeps
   `.runRow`; error / notice stay `<Text size={12} tone="reject|caution">`; `HistoryPrefetchRow` is
   rendered unchanged inside its card (add `flex-wrap: wrap` to `.prefetchRow` so it fits the narrow
   column — the only CSS change to an existing class besides layout classes).
2. **How this page works** (M12), directly under the header, collapsed:
   `<details className={styles.pageExplanation}><summary>How this page works</summary><Text size={12}
   tone="secondary">Click a card to select a strategy (saved at once; the floating Run button on Steps 1–3
   uses it). Adjust parameters, then Run Stock Scan. A successful scan opens Backtest; a failed scan stays
   here with its reason.</Text></details>` — text verbatim from `preview.html`; CSS copied from the
   Options `pageExplanation` rules (font-size 12px, `--text-secondary`, summary `--accent`, pointer).
3. **Looks for** (M3): add `looksFor` to each entry of `STRATEGIES_BULLISH` / `STRATEGIES_BEARISH` and
   render `<Text size={11} tone="secondary">Looks for: {s.looksFor}</Text>` as the first line of
   `.cardBody` (above Entry). Wording (approved, verbatim):

   | key | Bullish | Bearish |
   |---|---|---|
   | `pullback_ema` | an uptrend that dips to its moving average | a downtrend that bounces to its moving average |
   | `breakout_base` | a quiet range that breaks out on volume | a quiet range that breaks down on volume |
   | `ma_crossover` | a fast average crossing a slow one | a fast average crossing a slow one |
   | `mean_reversion_rsi` | an oversold dip inside a longer uptrend | an overbought pop inside a longer downtrend |
   | `mean_reversion_bb` | a lower-band touch that turns back up | an upper-band touch that turns back down |
   | `mean_reversion_vwap` | an intraday stretch below VWAP | an intraday stretch above VWAP |
   | `mean_reversion_multi` | several oversold signals agreeing | several overbought signals agreeing |

4. **After-scan armed count** (M11): `const armedCount = useScanStore((s) =>
   Object.values(s.stockAfterScanIntent).filter(Boolean).length);` (a number selector — no new object per
   render). Only when `armedCount > 0`, a side card titled "After-scan" with one
   `<Text size={12} tone="secondary">` whose text depends on the existing execution block
   (`import { stockExecutionBlock } from '@/lib/stockExecutionSession'`, called at render, never cached):
   - `block = stockExecutionBlock()` non-null (**always, today**) →
     `` `${armedCount} ${noun} armed. ${block} Arming itself stays on the position card.` ``
     — the block sentence is the same text the position card's after-scan mode shows;
   - `block` null (only once the block is lifted) → the approved preview sentence
     `` `${armedCount} ${noun} armed — booked to the paper portfolio only if they PASS on the next scan. Arming itself stays on the position card.` ``
   with `noun = armedCount === 1 ? 'symbol' : 'symbols'`. Kenneth chose this in the working session's chat,
   2026-10-10, after plan round 1 finding P4-A1 ("Truthful, both cases"). Nothing is shown at 0 (no
   unapproved empty-state text).
5. CSS: `.layout` (two columns), `.stack` and `.side` (`display: flex; flex-direction: column; gap: 16px`),
   `.panel` (card: `padding: 16px; border: 1px solid var(--border-subtle); border-radius: 8px;
   background: var(--bg-surface); display: flex; flex-direction: column; gap: 12px`), `.cardTitle`,
   `.pageExplanation` (+ summary rules). Keep `.grid`, `.card`, `.cardActive`, badge, `.runBtn`,
   `.sendBtn`, `.resetProfileBtn`, `.prefetch*` as they are. `.runBtn` may get `width: 100%` inside the
   side card; nothing else about the buttons changes.

**Tests first (must fail before the change)** — harness of `__tests__/pickerSelection.test.tsx`
(mock `next/navigation`, `@/lib/stockScan`, `@/lib/api`):
- "How this page works" is a `<summary>` and the explanation text above is in the document.
- Bullish context: each of the 7 bullish "Looks for: …" lines is present; Bearish context
  (`context.direction: 'Bearish'`): each of the 7 bearish lines is present and no bullish-only line is.
- Real `stockExecutionBlock` (today's block): `stockAfterScanIntent: { AAPL: true, MSFT: true, TSLA: false }`
  → exactly "2 symbols armed. Unvalidated — research only. Strategy validation is unavailable; broker sending
  and automatic arming are blocked. Arming itself stays on the position card." (build the expected string
  from the exported `STOCK_VALIDATION_UNAVAILABLE`), and the text "booked to the paper portfolio" is absent;
  `{ AAPL: true }` → starts "1 symbol armed. "; `{}` and `{ AAPL: false }` → no "After-scan" heading.
- In a separate test file (so the module mock does not leak),
  `jest.mock('@/lib/stockExecutionSession', () => ({ ...jest.requireActual('@/lib/stockExecutionSession'),
  stockExecutionBlock: () => null }))` with `{ AAPL: true, MSFT: true }` → "2 symbols armed — booked to the
  paper portfolio only if they PASS on the next scan. Arming itself stays on the position card."
- Inside `screen.getByRole('complementary', { name: 'Scan actions' })`: the "Run Stock Scan" button, the
  "Pre-warm history" button (unmocked `HistoryPrefetchRow`), a stock-feedback error and notice set via
  `useScanStore.setState({ stockScanFeedback: { error: 'Scan failed — x', notice: 'n' } })`, and "View
  Backtest results" when `stockScanResult` is set. The 7 strategy cards and "Parameters" are **not**
  inside it.
- Existing `step-4-stocks/__tests__/*` stay green **without edits — with one exception** (build-time amendment,
  2026-10-10, implementer-reported plan defect): `__tests__/readableScanError.test.tsx` T5's last assertion
  sweeps the **whole page** for `/could not|failed|Error|API \//i` after a clean success; the approved
  How-this-page-works text ("…a failed scan stays here with its reason.") is always in the DOM (a closed
  `<details>` keeps its text), so that sweep would match it. Scope only that assertion to the side column,
  where the scan feedback now lives: `expect(within(screen.getByRole('complementary', { name: 'Scan actions'
  })).queryByText(/could not|failed|Error|API \//i)).toBeNull();` (import `within`). No other assertion in
  that file changes; T5's intent — no failure text survives a clean success — is unchanged. Test-only; no app
  behaviour or approved wording changes.

**Commit:** `feat(step4-stocks): Strategy page in the Options layout — how-to, Looks for, after-scan count`

### Task 3 — Market Sentiment strip

**Files:** `frontend/app/(frame)/screener/step-4-stocks/page.tsx`, `page.module.css`, new
`frontend/app/(frame)/screener/step-4-stocks/__tests__/marketSentimentStrip.test.tsx`.

**Change:** read `const regimeSentiment = useScanStore((s) => s.regimeSentiment);`. Between "How this page
works" and the two columns:
- `regimeSentiment` non-null → `<MarketSentiment s={stripSentiment} compact />`, where
  `stripSentiment = useMemo(() => regimeSentiment && { ...regimeSentiment, horizon: context?.horizon ??
  regimeSentiment.horizon }, [regimeSentiment, context?.horizon])` — every number comes from Step 1's
  reading unchanged; only the horizon label follows the current scan context (Step 1 may have run before
  the horizon was chosen on Step 3).
- `regimeSentiment` null → `<Text size={12} tone="dim">Market sentiment loads on Step 1</Text>` (Kenneth's
  wording) and no `MarketSentiment` (its own null state reads "insufficient history", which would be wrong
  here).
No fetch, no store write, no change to `MarketSentiment`.

**Tests first (must fail before the change)** — real `MarketSentiment` (not mocked):
- `regimeSentiment: null` → "Market sentiment loads on Step 1" present; "Market Sentiment" heading absent;
  "insufficient history" absent.
- `regimeSentiment` = the Task 1 object with `conviction_pct: 42`, context horizon `'Position (45–60d)'`
  → "Market Sentiment" heading, "+42%", "Moderate — Market conviction: Moderate", "OMM/HMM Aligned" present;
  the horizon line reads "Position (45–60d) · daily" (not the stored "Swing (5–15d)").
- Setting `regimeSentiment` to `null` after render (act) swaps the strip for the note.
- All earlier tests (T2 and the existing suites) stay green.

**Commit:** `feat(step4-stocks): Market Sentiment strip from the Step 1 regime reading`

## Coordinator checks after the build (not tickets)

1. Walk M1–M13 against the built page (code reading + tests); record the result on #149.
2. `cd frontend && npm run typecheck && npm run test` (full); no backend change, so no pytest.
3. Visual check against `preview.html` at 1280 / 1440 / 1920, light + dark: no browser in this container
   → listed under "Needs Kenneth" on #149 unless a headless run is possible (`run` skill).
4. `git merge origin/main`, re-run 2, then code audit round 1 on `origin/main..HEAD`.

## Code round 1 fix (P4-C1) — Task 1 follow-up, one fresh implementer

**Finding:** two Step 1 mounts can overlap: fetch A (slow) starts, the user leaves Step 1 mid-fetch, returns,
fetch B starts and answers first; A answers last and its `.then` overwrites `regimeSentiment` with the older
reading, so the Strategy strip shows numbers Step 1 no longer shows. The comment in `fetchRegime` ("never
older than the latest request") misstates this.

**Change (`frontend/app/(frame)/screener/step-1-regime/page.tsx` only, plus its test):** a module-level
request counter — it must outlive the component, so not a ref: `let regimeSentimentRequestSeq = 0;`. In
`fetchRegime`: `const seq = ++regimeSentimentRequestSeq;` before `setRegimeSentiment(null)`; in `.then` and
`.catch`, call `setRegimeSentiment(...)` **only when `seq === regimeSentimentRequestSeq`**. Nothing else in
the callbacks changes (`setRegimeData`, `setRegime`, `setRegimeDirection`, `setCombinedRegime`,
`setOffline`, `setRegimeFetchFailed` keep their current unguarded behaviour — guarding them is outside this
phase). Correct the comment to say the latest request wins.

**Test first** (add to `step-1-regime/__tests__/regimeSentimentWrite.test.tsx`): two deferred `getRegime`
promises A then B; render (A starts), `unmount()`, render again (B starts), resolve B with reading B, then
resolve A with reading A → store holds B's sentiment; and the same with A **rejecting** last → store still
holds B (an older failure must not clear a newer reading). Must fail before the change.

**Commit:** `fix(step1): only the latest regime request writes the shared sentiment`

