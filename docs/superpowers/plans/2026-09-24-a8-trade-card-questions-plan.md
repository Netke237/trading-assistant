# A8 — the trade-card questions (plan)

Date: 2026-09-24. Planned against main at `22c4942`. Frontend only, one layer.

Kenneth's decisions (2026-09-24), all on the recommendation put to him:

| # | open_questions entry | Decision |
|---|---|---|
| 1 | [64] Step-7 context rail describes the auto-picked contract after a Step-6 pick | **Bug, no decision needed — goes first** |
| 2 | [68] a new scan does not clear `orderContractsBySymbol` | Clear it |
| 3 | [61] basket dropped-stop notices die on Prev/Next | Keep them until the next send |
| 4 | [51] `structuralBySymbol` caches a contract-specific `stopCost` under a symbol key; docstring false | Re-key by contract + fix the docstring |
| 5 | [50] `stopPremiumThresholdsStore` has no reader | Delete store + bootstrap |
| 6 | [52] two `horizon_preset` mutants survive on TradeCard | Add the two assertions |
| 7 | [60] stop-cost readout priced on the stale scan mid | **Superseded by B2** — close, no code (see §7) |

---

## 1. The rail (open_questions[64]) — its own commit, first

### Defect, verified on today's tree

`app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx` builds every gate from
`scanResult.candidates.find(c => c.symbol === selectedSymbol)` — the **raw scan candidate**. Step 7's card
is `effectiveCard` = `applyPickedContract(raw, picked)` then `mergePlan(...)` with the recomputed plan
(`page.tsx:588-624`). So after a Step-6 pick the rail's gates read the auto-pick's:

- **IV acceptable** — `resolveIv(candidate.contractDetails)` → auto-pick's IV;
- **Score ≥ 55** — `candidate.contractScore` → auto-pick's contract score;
- **Spread** — `candidate.contractBreakdown.spread` → auto-pick's;
- **R:R ≥ 2.0** — `candidate.rrRatio` → the auto-pick's plan (the override's plan is recomputed
  asynchronously into Step7Page's local `plansBySymbol`).

Four wrong numbers, each a PASS/CAUTION/REJECT dot beside the card showing the picked contract.

### Why the rail cannot fix this by itself

It is a separate parallel-route component (same reason as `portfolioUiStore` / `watchlistUiStore`).
It could redo `applyPickedContract` from `scanStore.pickedContracts` + `contractsBySymbol`, but the
recomputed **plan** (R:R) lives only in Step7Page's `useState`. Two derivations of "the card" is the
defect shape this repo keeps catching; one is published instead.

### Change

- **New `lib/tradeCardUiStore.ts`** (not persisted, ephemeral, same shape/comment style as
  `portfolioUiStore`):
  `activeCard: { card: TradeCardData; rrPending: boolean } | null`, `setActiveCard`.
- **Step7Page** publishes, in an effect on `[effectiveCard, planReady]`:
  `setActiveCard(effectiveCard ? { card: effectiveCard, rrPending: !planReady } : null)`.
  `planReady` is `!isOverride || !!planForThisContract`, so `rrPending` is true while the override's
  plan loads AND when it failed (`planErrors`), which is exactly when `effectiveCard.rrRatio` still
  holds the auto-pick's figure. A separate mount-only effect clears it on unmount
  (`return () => setActiveCard(null)`), so returning to Step 7 after picking another contract in
  Step 6 never shows the previous visit's card before the first publish.
  No render loop: Step7Page does not subscribe to this store. `effectiveCard` changes identity every
  render for an overridden card (documented at `page.tsx:669-680`), so the rail re-renders with the
  page; that is the cost, and it is bounded by the page's own render rate.
- **The rail** reads `activeCard` and nothing from `scanResult.candidates`. It drops the
  `?? candidates[0]` fallback (the page's `card` already falls back to `cards[0]`, and publishes
  that). The section title uses the published card's symbol, not `selectedSymbol`, so title and
  gates cannot name different symbols. With no published card: "Run a scan to populate the
  checklist." (unchanged text). `nextEventDays`/`nextEventLabel`/company come from the published card
  (symbol-level, identical on the raw and the overridden card).
- **R:R gate when `rrPending`**: CAUTION, detail "R:R not yet recomputed for the contract picked in
  Step 6." — never the stale ratio. Same principle as the IV gate's no-data CAUTION: unknown is not
  PASS.

Unchanged: regime gate, horizon key, IV-threshold logic, earnings gate, thresholds. The spread gate
inherits `applyPickedContract`'s `picked.breakdown ?? card.contractBreakdown` fallback — the rail
now agrees with the card in every case, including that one (pre-existing on the card, round 6
finding 8, out of scope).

### Tests

- `app/(frame)/@contextRail/screener/step-7-trade-card/__tests__/rail.test.tsx` (new):
  (a) published overridden card → the IV dot's `title` names the picked contract's IV and the score
  dot's names the picked `contractScore`; the spread dot's status follows the picked breakdown;
  (b) scanResult holds a candidate but nothing is published → the rail shows the empty-state text
  and no gates (pins that it no longer reads the raw candidate);
  (c) `rrPending: true` → R:R dot is CAUTION with the "not yet recomputed" detail even when the
  card's `rrRatio` would PASS.
- Step7Page (in the existing `__tests__` harness): with a Step-6 pick set in `scanStore`,
  `useTradeCardUiStore.getState().activeCard.card.contract` is the picked id and `rrPending` is
  true until the plan resolves, false after; unmount → `activeCard` null.
- Mutation checks (each must make a test fail): rail back to `scanResult` candidate; drop the
  publish effect; publish `rrPending: false` always; drop the unmount clear.

## 2. Clear the contract count on a new scan (open_questions[68])

`page.tsx` scanResult effect (≈`:540`): add `setOrderContractsBySymbol({})` beside the three fetched
caches it already clears, with the same "belt-and-suspenders" framing (a new scan today requires
leaving the page). On mount the map is already `{}`, so the mount run changes nothing.
Test: mount with a scan, change the count via the card, `setScanResult(newScan)` → the card's
`contracts` resets to 1. Mutation: remove the line → fails.

## 3. Basket notices survive Prev/Next (open_questions[61])

`page.tsx`: a second list `basketNotes` (state), written only by `handleSubmit` (the basket path,
`:1176` today writes symbol-qualified dropped-stop notes via `addSaveNote`). Cleared at the START of
every send — `handleSubmit`, `placeLimitPaper`, `placeMarketNow` — and NOT by the `[active]` effect.
Rendered with the same `Text tone="caution"` right after `saveNotes`. `saveNotes` keeps its current
lifecycle for the two direct paths (per-card; cleared on navigate).
Out of scope, stated: the basket's `orderError` banner still clears on navigate — Kenneth's question
was the notices; logged as a follow-up, not widened.
Test: basket submit with `premiumStopDropped` → note shown → Next → still shown → a direct send
clears it. Mutation: clear `basketNotes` in the `[active]` effect → fails.

## 4. Structural cache keyed by contract (open_questions[51])

- Rename `structuralBySymbol` → `structuralByContract`, keyed by `contractKeyFor(card)` like
  `estimatesByContract` / `exitPlanByContract`.
- Writer: `onStructuralStopChange={(stop, px) => handleStructuralStopChange(contractKey, stop, px)}`
  (same closure pattern as the two sibling callbacks at `page.tsx:1305-1306`);
  `handleStructuralStopChange(key: string | null, …)` returns `prev` when `key` is null.
- Readers (all four): `withCachedEstimate(...)` input, `buildPaperPosition` (`:960`),
  basket `handleSubmit` (`:1140`), `AutoTradeArm structuralStop` (`:1436`) — via one local helper
  `structuralStopPriceFor(card)` = `structuralByContract[contractKeyFor(card)]?.stop?.price ?? null`.
  In practice equivalent to today for the send paths (a contract change unmounts the page), and it
  removes the latent hazard: contract A's `stopCost` can no longer be spliced onto contract B.
- `cacheStructural(prev, key, …)` parameter rename; `CachedStructural` docstring in
  `lib/tradeCardOverride.ts` and the page comment (`:174-187`) corrected: the level is stock-level
  but the cached response carries a contract-priced `stopCost`, hence the contract key.
- Tests: existing `tradeCardOverride` unit tests updated for the rename; one new page test: a stop
  checked on the auto-pick is NOT restored onto a card whose contract key differs.

## 5. Delete `stopPremiumThresholdsStore` (open_questions[50])

Delete `lib/stopPremiumThresholdsStore.ts`, `lib/__tests__/stopPremiumThresholdsStore.test.ts`,
`components/atoms/StopPremiumThresholdsBootstrap/`, its import + element in `app/(frame)/layout.tsx`,
and `api.getStopPremiumThresholds` (+ any `__mocks__` entry). Backend endpoint
`/api/config/stop-premium-thresholds` stays (backend layer, harmless, has its own tests). CLAUDE.md
store-table row removed. Verification: `grep -r stopPremiumThresholds frontend` empty; typecheck.

## 6. Pin the two `horizon_preset` call sites (open_questions[52])

`TradeCard.test.tsx`, beside the existing Custom→Position test at `:911`: Compute Exit Plan with a
Custom 60–185d context → `api.getExitPlan` called with `horizon_preset: 'Position'`; Estimate with no
fresh structural stop → the `api.getStructuralStop` sub-fetch carries `'Position'`. Mutation: revert
each of `index.tsx:871` and `:1034` to `horizonPreset` → the matching test fails.

## 7. open_questions[60] — superseded, closed without code

The readout it describes (client arithmetic on `contractDetails.mid`) no longer exists: since B2 the
stop cost is priced server-side from `contractQuote?.price ?? cd.mid` (`TradeCard/index.tsx:862,
974, 1432`) and the response echoes the premium it used (`stop_cost.py` docstring). Moved to
closed_questions with that reason.

## 8. Verification

`npm run typecheck`, full `npm run test`, full backend `pytest` (unchanged layer, but required);
`state.py` exit 0; phase entry `A8-TRADE-CARD-QUESTIONS` in PROJECT_STATE.json; open_questions
[50,51,52,60,61,64,68] moved to closed_questions with their resolution.
