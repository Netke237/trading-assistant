# Trade Card Profit-Target & Structure Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Options-mode Trade Card from throwing away a Profit-Targets (Monte Carlo first-passage) estimate and a "Check structure" result the moment the user navigates to another candidate via CandidateNav and back. The estimate must be restored — numbers, R:R-vs-structural-stop column, and the T1/T2/T3 % inputs it was run at — without re-firing any network request, and must be invalidated only when (a) a new scan is executed or (b) the user re-runs "Estimate" for that same contract.

**Scope of "survives", precisely:** the cache lives in the Step 7 page component's own `useState`, so it survives everything that happens *inside* a Step 7 session — CandidateNav Prev/Next/Select, pinning to the basket, a Step 6 contract override remount, any parent re-render. It does **not** survive leaving the route (Step 7 → Step 6 → Step 7 unmounts the page and takes the cache with it) or a browser reload. That is a deliberate non-goal, not an oversight — see the Self-Review Notes at the bottom. The reported bug is specifically the in-page CandidateNav round trip, which this does fix completely.

**Architecture:** A parent-owned, in-memory cache in `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`, populated by callback props from `TradeCard` and read back by splicing the cached values into the `TradeCardData.exit.*` fields that `TradeCard` **already** reads as its initial state. Two cache maps with deliberately different granularity: profit-target estimates keyed by **full contract** (`contractKeyFor` — symbol|strike|expiry|right, since the estimate is priced off that contract's premium), structure checks keyed by **symbol** (the structural stop describes the underlying, not the contract — and the page already keeps a symbol-keyed structural cache today for order-send). No new store, no persistence, no backend change, no new architectural concept: this reuses `contractKeyFor` (already used for `plansBySymbol`), the `data.exit.*`-as-injection-point mechanism (already how `structuralStop`/`firstPassage` reach `TradeCard`'s state), and the `onStructuralStopChange` write-back pattern (already implemented, with its documented ref + bail-out discipline).

**Tech Stack:** Next.js 15 / React (client components), TypeScript (strict), Zustand (read-only here), Jest + Testing Library.

---

## Background (read this before touching code)

### The bug

`TradeCard/index.tsx:235-252` holds one reset effect that fires whenever `data.symbol` or `data.contract` changes:

```js
setStructuralStop(data.exit.structuralStop);
setStructuralStopStockPrice(null);
setTargetPct(defaultTargetPct);
setFirstPassage(data.exit.firstPassage);
setFirstPassageContext(null);
```

`data.exit.structuralStop` / `data.exit.firstPassage` are documented in `types/domain.ts:294-297` as *"Populated only after the user presses … — never set by the scan itself"*, i.e. the backend never sends them, so today they are always `undefined` and the reset is a wipe. Navigating away and back genuinely destroys the result; the user has to click "Estimate" again (a Monte Carlo round-trip) to get back what they were just looking at.

### Conflicts and design hazards found, and how this plan resolves each

**1. Granularity — contract vs symbol.** A first-passage estimate is priced off *that contract's* premium (`optionPrice = premium * (1 + pct)`, see `backend/app/scoring/first_passage.py`) and its `dte`/`strike`; caching it per symbol would show contract A's premiums while the card displays contract B. → Keyed by `contractKeyFor(pickedCard)` (`lib/tradeCardOverride.ts:48-52`), the same helper `plansBySymbol` already tags its entries with.
A structural stop, by contrast, is a function of `(symbol, direction, stock_price)` only — `api.getStructuralStop` never sees the contract. Within one scan a symbol has exactly one direction, so a symbol-level key is semantically exact, and the page already keeps a symbol-keyed structural cache (`structuralStopBySymbol`, `page.tsx:126`) feeding the order-send path. → Structure stays **symbol**-keyed. Consequence (an intentional improvement, not a side effect): a structure check now also survives switching between two contracts of the *same* symbol, and `estimateFirstPassage`'s auto-trigger block (`index.tsx:322`) correctly skips its extra `getStructuralStop` call because `structuralStop !== undefined` after a restore.

**2. Companion state has no home on `TradeCardData`.** The displayed numbers are not just `firstPassage`. `structuralRR` (`index.tsx:385-405`) needs **all four** of `structuralStop`, `structuralStopStockPrice`, `firstPassage`, `firstPassageContext`. Restoring only `firstPassage` + `structuralStop` would leave `firstPassageContext`/`structuralStopStockPrice` null → `structuralRR` returns `null` → every row's "R:R vs. structural stop" cell falls through `ProfitTargetRow`'s branch chain to the defensive `'—'`. That is exactly the false-positive scenario the 2026-08-20 plan's self-review flagged as its MEDIUM finding ("a future contract arriving with `data.exit.structuralStop`/`data.exit.firstPassage` pre-populated but `structuralStopStockPrice`/`firstPassageContext` still null post-reset"). This plan is what makes that scenario real, so it must ship the companions too. → Two new **client-only** optional fields on `TradeCardData.exit` (`structuralStopStockPrice`, `firstPassageContext`), documented exactly like the two client-only fields already there.

**3. `targetPct` consistency.** The T1/T2/T3 % inputs are reset to the settings default on navigation. Restoring an estimate run at custom percentages (e.g. T1 = 10%) while the inputs show 20/35/50 is internally inconsistent, and a subsequent Estimate click would silently re-run at different percentages than the rows on screen. → `targetPct` is captured **at request time** into `firstPassageContext` (which becomes `{ premium, delta, targetPct }`) rather than surfaced as a separate value. This makes the pairing exact by construction — no extra ref, no extra domain field, no possibility of caching a `targetPct` the estimate wasn't run at because the user edited the input while the request was in flight.

**4. Stale-response races must not be reintroduced.** `firstPassageRequestRef`/`structuralRequestRef` already abort in-flight requests on a contract switch, and every `.then` returns early on `signal.aborted`. The cache write path never touches those handlers: it is driven **only** by a `useEffect` keyed on the local state values, reading the parent callback out of a ref — the identical split-effect discipline documented at `index.tsx:258-283` and covered by the "does not surface the previous candidate's structural stop to the new one after switching" regression test. Consequences, all verified against that structure:
   - An aborted request for contract A never calls `setFirstPassage`, so it is never cached and never displayed for B. (A navigated-away-from, still-in-flight estimate is simply lost — the user re-clicks. Out of scope; unchanged from today.)
   - On the nav commit, `data`/callback change but `firstPassage` state does **not**, so the value-surfacing effect does not fire; it fires one commit later, after the reset effect has set the new contract's value, by which point the callback ref holds the new contract's closure. A's value can never be written into B's slot, and B's live display can never be clobbered.
   - Re-clicking Estimate sets `firstPassage` to `undefined` first; the handler early-returns on `undefined`/`null`, so a re-estimate (or a failed one) leaves the previous cached value intact until a new one actually lands, then overwrites that contract's slot — the same overwrite-on-change behaviour `structuralStopBySymbol` has today.

**5. The render-loop hazard.** `page.tsx:127-136` documents why `handleStructuralStopChange` bails out by returning the identical `prev` object when nothing changed: the callback prop is a fresh inline closure every render, so an unconditional `setState` would re-render the parent → re-create the prop → … The new `handleFirstPassageChange` follows the same discipline, with one addition: its cached value is an *object*, so the bail-out compares the stored `firstPassage` **and** `context` by reference. That works because (a) `setFirstPassage`/`setFirstPassageContext` each store one object per successful estimate, stable until the next one, and (b) on restore the parent splices *the very same object references* back in, so the post-restore effect fire compares equal and bails. No `useCallback` is introduced — matching this file's existing style, and because the bail-out (not memoization) is what actually breaks the cascade, as that comment states.

**6. `mergePlan` replaces `exit` wholesale.** `mergePlan` (`lib/tradeCardOverride.ts:57-59`) does `{ ...card, exit: plan.exit, … }`, so anything spliced into `exit` *before* the merge is discarded. → The splice happens **after** `effectiveCard` is computed, in its own memo, and the result is passed **only** to `<TradeCard data=…>`. `placeLimitPaper`/`placeMarketNow`/`buildPaperPosition`/`AutoTradeArm`/`SendToBrokerDialog` keep using `effectiveCard` untouched.

**7. Nothing else consumes these fields.** Verified by grep: `exit.firstPassage` and `exit.structuralStop` (the `StructuralStop` object form) are referenced **only** in `types/domain.ts` and `components/organisms/TradeCard/index.tsx`. `PortfolioPosition.structuralStop` is a different, `number`-typed field. `SendToBrokerDialog` and `AutoTradeArm` never read `card.exit.firstPassage`/`structuralStop`. So populating these fields for a candidate the backend didn't compute them for cannot surprise another consumer — which is what makes `data.exit.*` the right injection point rather than a new prop: `TradeCard`'s `useState` initializers (`index.tsx:193-195`, `212-214`) read them too, so a **remount** (which really happens — the page unmounts `TradeCard` whenever `isOverride && !planReady`, `page.tsx:672-698`) restores from the cache with zero extra code.

**8. Basket / pinned candidates.** Only one `TradeCard` instance is ever rendered (the active card); `resolveBasketCards` feeds `SendToBrokerDialog`, which renders its own rows and never reads these fields. The cache therefore only needs to serve the active card — no per-basket-item plumbing.

**9. Orphaned entries from a contract override.** If the user picks a different Step 6 contract for the same symbol after estimating, the old estimate stays under the old contract key. That entry is keyed by a genuine contract identity, so it is *correct* if the user switches back, and otherwise harmless: the whole map is cleared on the next scan. No active cleanup. (Re-checked in audit round 2: this scenario is in fact **unreachable within one Step 7 session** — `pickedContracts` is only written from the `step-6-contracts` page, and routing to Step 6 unmounts Step 7 and destroys these caches outright. The reasoning above is kept because it is the reasoning that *would* apply if the caches were ever lifted into a store, and because it is what makes the contract-level key the right choice regardless; it is documented here as belt-and-braces, not as a live mitigation.) (The recompute-plan flow does not re-fire on re-navigation either — `requestedPlanKeysRef` dedups per contract key — so `exit.invalidation`, which the estimate was computed against, is stable across navigation within a scan. The only way it can shift for an unchanged contract key is an explicit `retryPlan()` after a failure, which is a rare, user-initiated action; the accepted mitigation is "click Estimate again".)

**10. Invalidation on a new scan is a behaviour change for the order-send path.** Clearing the structure cache on a new scan means a structural stop captured before the scan no longer gets attached to a position sent after it. That is the user-requested invalidation rule and is the correct behaviour (a level checked against pre-scan prices should not silently ride along into a new position), but it *is* a change to `buildPaperPosition`/`handleSubmit` inputs — called out here so it is not mistaken for an accident.

**11a. A failed *re*-check of structure leaves a stale level in the cache.** `checkStructure` sets `structuralStop` to `undefined` before fetching; on failure it stays `undefined` and the card shows the error. The cache write handler ignores `undefined` (by design — see #4), so the *previous* level stays cached. Navigating away and back then restores that previous level and displays it as if it were current. This is exactly today's behaviour for `structuralStopBySymbol` on the order-send path (a failed re-check already leaves the old level attached to a position sent afterwards), so it is not a regression — but this plan makes it *visible in the UI* where today it is invisible. Accepted deliberately: the alternative (clearing the cache on failure) would mean a transient network blip silently destroys a level the user checked minutes ago, which is worse. Manual verification step 8 pins the behaviour so it is a known, chosen state rather than a surprise.

**11. Test-suite assumptions.** No existing test asserts that `data.exit.firstPassage`/`structuralStop` are only ever populated by the scan payload; the fixture simply omits them. Two existing assertions in `TradeCard.test.tsx` (lines 288 and 300) **do** depend on `onStructuralStopChange`'s current arity — `toHaveBeenCalledWith(x)` fails against a two-argument call, and the `.not.toHaveBeenCalledWith(x)` companion would start passing vacuously (silently un-testing the regression it guards). Both are fixed in **Task 6 Step 1** (not Task 5, which touches only `page.tsx`).

**11b. The Jest mocks in `TradeCard.test.tsx` are NEVER cleared between tests.** `jest.config.ts` sets no `clearMocks`/`resetMocks`/`restoreMocks`, `jest.setup.ts` only registers jest-dom + a ResizeObserver stub, and the file's `beforeEach` (line 154) re-arms `mockResolvedValue` **without** calling `jest.clearAllMocks()`. Call history on `api.getStockQuote` / `getStructuralStop` / `getFirstPassageEstimate` therefore accumulates across every test in the file. The two existing `expect(api.X).not.toHaveBeenCalled()` assertions (lines 172 and ~360) only pass because they happen to sit before any test that calls that particular mock — pure declaration-order luck. **Any new "nothing was refetched" assertion added later in the file must snapshot the call count and compare, never use `not.toHaveBeenCalled()`.** Task 6 Step 2 does exactly that. There is no page-level test file for `step-7-trade-card`; none is added (it would need the whole scan/portfolio/auto-trade store surface mocked for little value) — the parent wiring is covered by the pure-helper unit tests in Task 4 plus the manual verification in Task 7.

---

## File Structure

No new files. Modified:
- `frontend/types/domain.ts` — two new optional, client-only fields on `TradeCardData.exit`, plus one exported `FirstPassageContext` interface.
- `frontend/lib/tradeCardOverride.ts` — two cache-entry types and one pure `withCachedEstimate()` splice helper.
- `frontend/components/organisms/TradeCard/index.tsx` — initial state + reset effect read the two new fields; `targetPct` folded into `firstPassageContext`; `onStructuralStopChange` widened with the stock price; new `onFirstPassageChange` prop surfaced via the existing ref + state-keyed effect pattern.
- `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` — the two cache maps, their write handlers, the new-scan clear, the spliced `cardForDisplay`, and the two callback props.
- `frontend/lib/__tests__/tradeCardOverride.test.ts` — unit tests for `withCachedEstimate`.
- `frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx` — two arity fixes plus three new tests.

---

### Task 1: Add the two client-only companion fields to `TradeCardData.exit`

**Files:**
- Modify: `frontend/types/domain.ts:158-169` (add `FirstPassageContext`)
- Modify: `frontend/types/domain.ts:292-298` (`TradeCardData.exit`)

- [ ] **Step 1: Add the `FirstPassageContext` interface next to the other first-passage types**

Find (lines 158-169):

```typescript
export interface FirstPassageTarget {
  pct:          number;          // profit target as a fraction of premium (0.20 = 20%)
  stockPrice:   number | null;   // display-only Stage-1 approximation; null if unreachable
  optionPrice:  number;          // premium * (1 + pct)
  probability:  number;          // 0-1, hit probability before expiry
  expectedDays: number | null;   // median days to hit; null if probability is 0
}

export interface FirstPassageEstimate {
  targets:      FirstPassageTarget[];
  invalidation: { probability: number; expectedDays: number | null };
}
```

Replace with:

```typescript
export interface FirstPassageTarget {
  pct:          number;          // profit target as a fraction of premium (0.20 = 20%)
  stockPrice:   number | null;   // display-only Stage-1 approximation; null if unreachable
  optionPrice:  number;          // premium * (1 + pct)
  probability:  number;          // 0-1, hit probability before expiry
  expectedDays: number | null;   // median days to hit; null if probability is 0
}

export interface FirstPassageEstimate {
  targets:      FirstPassageTarget[];
  invalidation: { probability: number; expectedDays: number | null };
}

/** The inputs a `FirstPassageEstimate` was actually computed against — captured
 *  at request time, not re-read afterwards. `premium`/`delta` are the FRESH
 *  quote values (not `contractDetails.mid`/`.delta`, which are scan-time
 *  snapshots), so a later R:R-vs-structural-stop calc subtracts the matching
 *  baseline; `targetPct` is the T1/T2/T3 fraction trio the request carried, so
 *  a restored estimate's rows and its % inputs can never disagree. */
export interface FirstPassageContext {
  premium:   number;
  delta:     number;
  targetPct: { t1: number; t2: number; t3: number };
}
```

(The `targetPct` shape is written structurally rather than importing `TargetProfitPct` from `lib/settingsStore` — `types/domain.ts` must not depend on a Zustand store. The two shapes are structurally identical, so values flow both ways without a cast.)

- [ ] **Step 2: Add the two companion fields to `TradeCardData.exit`**

Find (lines 292-298):

```typescript
  exit:   {
    invalidation: number; premiumStop: number; timeStopDays: number; target: number; targets: TargetLevel[];
    /** Populated only after the user presses "Check structure" — never set by the scan itself. */
    structuralStop?: StructuralStop | null;
    /** Populated only after the user presses "Estimate" — never set by the scan itself. */
    firstPassage?: FirstPassageEstimate | null;
  };
```

Replace with:

```typescript
  exit:   {
    invalidation: number; premiumStop: number; timeStopDays: number; target: number; targets: TargetLevel[];
    /** Populated only after the user presses "Check structure" — never set by the scan itself. */
    structuralStop?: StructuralStop | null;
    /** Populated only after the user presses "Estimate" — never set by the scan itself. */
    firstPassage?: FirstPassageEstimate | null;
    /** The fresh underlying price `structuralStop` above was derived from. Client-only,
     *  like `structuralStop` itself: spliced in by step-7-trade-card/page.tsx when it
     *  restores a cached "Check structure" result on candidate re-navigation, so
     *  TradeCard's R:R-vs-structural-stop calc has the matching price and not a null.
     *  Never sent by the backend. */
    structuralStopStockPrice?: number | null;
    /** The inputs `firstPassage` above was computed against. Client-only, same
     *  restore-on-re-navigation path as `structuralStopStockPrice`. Never sent by
     *  the backend. */
    firstPassageContext?: FirstPassageContext | null;
  };
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean. (Both fields are optional, so no existing `TradeCardData` literal breaks.)

- [ ] **Step 4: Commit**

```bash
git add frontend/types/domain.ts
git commit -m "types(trade-card): add client-only first-passage/structural companion fields to exit"
```

---

### Task 2: Fold `targetPct` into `firstPassageContext` and restore both companions in TradeCard

**Files:**
- Modify: `frontend/components/organisms/TradeCard/index.tsx:16` (type import)
- Modify: `frontend/components/organisms/TradeCard/index.tsx:193-224` (state declarations)
- Modify: `frontend/components/organisms/TradeCard/index.tsx:235-252` (reset effect)
- Modify: `frontend/components/organisms/TradeCard/index.tsx:366` (context capture in `estimateFirstPassage`)

- [ ] **Step 1: Import `FirstPassageContext`**

Find (line 16):

```typescript
import type { TradeCardData, TargetLevel, StructuralStop, FirstPassageEstimate, FirstPassageTarget } from '@/types/domain';
```

Replace with:

```typescript
import type { TradeCardData, TargetLevel, StructuralStop, FirstPassageEstimate, FirstPassageContext, FirstPassageTarget } from '@/types/domain';
```

- [ ] **Step 2: Seed `structuralStopStockPrice` from `data.exit`**

Find (lines 198-203):

```typescript
  // The fresh stock price checkStructure fetched to derive structuralStop —
  // persisted (not just used transiently) so a later R:R-vs-structural-stop
  // calc can reuse the SAME fresh price the backend actually used, instead of
  // falling back to data.price (the scan-time snapshot checkStructure was
  // specifically written to avoid).
  const [structuralStopStockPrice, setStructuralStopStockPrice] = useState<number | null>(null);
```

Replace with:

```typescript
  // The fresh stock price checkStructure fetched to derive structuralStop —
  // persisted (not just used transiently) so a later R:R-vs-structural-stop
  // calc can reuse the SAME fresh price the backend actually used, instead of
  // falling back to data.price (the scan-time snapshot checkStructure was
  // specifically written to avoid). Seeded from data.exit alongside
  // structuralStop above, so a cached structure check the parent splices back
  // in on re-navigation restores BOTH halves — restoring the stop alone would
  // leave structuralRR null and every row's R:R cell showing the defensive '—'.
  const [structuralStopStockPrice, setStructuralStopStockPrice] = useState<number | null>(
    data.exit.structuralStopStockPrice ?? null,
  );
```

- [ ] **Step 3: Seed `targetPct` and `firstPassageContext` from `data.exit`**

Find (lines 210-224):

```typescript
  const defaultTargetPct = useSettingsStore((s) => s.targetProfitPct);
  const [targetPct, setTargetPct] = useState(defaultTargetPct);
  const [firstPassage, setFirstPassage] = useState<FirstPassageEstimate | null | undefined>(
    data.exit.firstPassage,
  );
  const [firstPassageLoading, setFirstPassageLoading] = useState(false);
  const [firstPassageError, setFirstPassageError] = useState(false);
  // The fresh premium/delta estimateFirstPassage fetched — optionPrice in
  // each firstPassage.targets entry is premium*(1+pct) computed off THIS
  // premium (see first_passage.py), not data.contractDetails.mid, which can
  // differ once a fresh quote has been fetched. Persisted so a later R:R
  // calc subtracts the matching baseline instead of a stale one.
  const [firstPassageContext, setFirstPassageContext] = useState<{ premium: number; delta: number } | null>(null);
  // Same stale-response guard as structuralRequestRef above.
  const firstPassageRequestRef = useRef<AbortController | null>(null);
```

Replace with:

```typescript
  const defaultTargetPct = useSettingsStore((s) => s.targetProfitPct);
  // Seeded from the restored estimate's own context when the parent splices a
  // cached estimate back in — otherwise the % inputs would show the settings
  // default while the restored rows show the percentages the estimate was
  // actually run at, and a follow-up Estimate click would silently re-run at
  // different percentages than the numbers on screen.
  const [targetPct, setTargetPct] = useState(data.exit.firstPassageContext?.targetPct ?? defaultTargetPct);
  const [firstPassage, setFirstPassage] = useState<FirstPassageEstimate | null | undefined>(
    data.exit.firstPassage,
  );
  const [firstPassageLoading, setFirstPassageLoading] = useState(false);
  const [firstPassageError, setFirstPassageError] = useState(false);
  // The inputs estimateFirstPassage actually used — optionPrice in each
  // firstPassage.targets entry is premium*(1+pct) computed off THIS premium
  // (see first_passage.py), not data.contractDetails.mid, which can differ
  // once a fresh quote has been fetched. Persisted so a later R:R calc
  // subtracts the matching baseline instead of a stale one, and seeded from
  // data.exit so a restored estimate carries its baseline with it.
  const [firstPassageContext, setFirstPassageContext] = useState<FirstPassageContext | null>(
    data.exit.firstPassageContext ?? null,
  );
  // Same stale-response guard as structuralRequestRef above.
  const firstPassageRequestRef = useRef<AbortController | null>(null);
```

- [ ] **Step 4: Restore the companions in the contract-change reset effect**

Find (lines 235-252):

```typescript
  useEffect(() => {
    if (data.symbol !== prevSymbolRef.current || data.contract !== prevContractRef.current) {
      structuralRequestRef.current?.abort();
      firstPassageRequestRef.current?.abort();
      setOverlay({ ...defaultOverlay(data), contracts: initialContracts });
      setStructuralStop(data.exit.structuralStop);
      setStructuralStopStockPrice(null);
      setStructuralError(false);
      setStructuralLoading(false);
      setTargetPct(defaultTargetPct);
      setFirstPassage(data.exit.firstPassage);
      setFirstPassageContext(null);
      setFirstPassageError(false);
      setFirstPassageLoading(false);
      prevSymbolRef.current = data.symbol;
      prevContractRef.current = data.contract;
    }
  }, [data.symbol, data.contract, initialContracts, defaultTargetPct]);
```

Replace with:

```typescript
  useEffect(() => {
    if (data.symbol !== prevSymbolRef.current || data.contract !== prevContractRef.current) {
      structuralRequestRef.current?.abort();
      firstPassageRequestRef.current?.abort();
      setOverlay({ ...defaultOverlay(data), contracts: initialContracts });
      // Every one of these five reads data.exit — for a candidate nothing has
      // been run on they are all absent and this is still a full reset (the
      // pre-existing behaviour). When the parent has a cached result for the
      // incoming contract it splices all of them in together, so the estimate,
      // its baseline premium/delta, its % inputs, the structural stop and the
      // price that stop was measured against are restored as ONE consistent
      // set — never a half-restore that would leave structuralRR null.
      setStructuralStop(data.exit.structuralStop);
      setStructuralStopStockPrice(data.exit.structuralStopStockPrice ?? null);
      setStructuralError(false);
      setStructuralLoading(false);
      setTargetPct(data.exit.firstPassageContext?.targetPct ?? defaultTargetPct);
      setFirstPassage(data.exit.firstPassage);
      setFirstPassageContext(data.exit.firstPassageContext ?? null);
      setFirstPassageError(false);
      setFirstPassageLoading(false);
      prevSymbolRef.current = data.symbol;
      prevContractRef.current = data.contract;
    }
  }, [data.symbol, data.contract, initialContracts, defaultTargetPct]);
```

The dependency array is deliberately unchanged: it still keys on the two primitives that define "the card switched". `data.exit.*` is read inside the guarded branch only, and the parent's cache write changes `data`'s object identity without changing `data.symbol`/`data.contract`, so a cache write can never re-trigger this reset (which is what would otherwise wipe live state mid-session).

- [ ] **Step 5: Capture `targetPct` at request time in `estimateFirstPassage`**

Find (lines 362-366):

```typescript
      setFirstPassage({ targets: res.targets, invalidation: res.invalidation });
      // optionPrice in each target is premium*(1+pct) built from THIS
      // premium (first_passage.py) — persist it so a later R:R calc
      // subtracts the matching baseline, not data.contractDetails.mid.
      setFirstPassageContext({ premium, delta });
```

Replace with:

```typescript
      setFirstPassage({ targets: res.targets, invalidation: res.invalidation });
      // optionPrice in each target is premium*(1+pct) built from THIS
      // premium (first_passage.py) — persist it so a later R:R calc
      // subtracts the matching baseline, not data.contractDetails.mid.
      // targetPct is snapshotted here (not read back later) so the trio
      // stored alongside the estimate is exactly the trio the request above
      // carried, even if the user edited an input while it was in flight.
      setFirstPassageContext({ premium, delta, targetPct: { ...targetPct } });
```

`targetPct` is already in `estimateFirstPassage`'s dependency array (line 373) — no dependency change needed. `structuralRR` (lines 385-405) reads only `firstPassageContext.premium` / `.delta`, so the widened shape is purely additive there.

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/organisms/TradeCard/index.tsx
git commit -m "feat(trade-card): restore first-passage/structure companion state from data.exit"
```

---

### Task 3: Surface both results to the parent (widened `onStructuralStopChange`, new `onFirstPassageChange`)

**Files:**
- Modify: `frontend/components/organisms/TradeCard/index.tsx:152-165` (props interface)
- Modify: `frontend/components/organisms/TradeCard/index.tsx:177-186` (destructuring)
- Modify: `frontend/components/organisms/TradeCard/index.tsx:258-283` (surfacing effects)

- [ ] **Step 1: Widen the props interface**

Find (lines 152-165):

```typescript
interface TradeCardProps {
  data: TradeCardData;
  recId?: string;
  onSendToBroker?: () => void;
  sendLabel?: string;
  sendDisabled?: boolean;
  contracts?: number;
  onEditsChange?: (overlay: EditOverlay) => void;
  /** Fired whenever the "Check structure" result changes for the current contract
   *  (including being reset to `undefined` on a contract switch, or `null` when no
   *  structural level was found) — lets the parent capture the level so it can be
   *  attached to the position if/when this trade is sent to the broker. */
  onStructuralStopChange?: (stop: StructuralStop | null | undefined) => void;
}
```

Replace with:

```typescript
interface TradeCardProps {
  data: TradeCardData;
  recId?: string;
  onSendToBroker?: () => void;
  sendLabel?: string;
  sendDisabled?: boolean;
  contracts?: number;
  onEditsChange?: (overlay: EditOverlay) => void;
  /** Fired whenever the "Check structure" result changes for the current contract
   *  (including being reset to `undefined` on a contract switch, or `null` when no
   *  structural level was found) — lets the parent capture the level so it can be
   *  attached to the position if/when this trade is sent to the broker, AND cache it
   *  per symbol so re-navigating to this candidate restores it instead of wiping it.
   *  `stockPrice` is the fresh underlying price the level was measured against
   *  (`null` whenever `stop` is `undefined`); the parent must cache it alongside the
   *  level or a restored stop cannot produce an R:R-vs-structural-stop figure. */
  onStructuralStopChange?: (stop: StructuralStop | null | undefined, stockPrice: number | null) => void;
  /** Fired whenever the "Estimate" (first-passage) result changes for the current
   *  contract, including the reset to `undefined` on a contract switch and the
   *  reset to `undefined` at the start of a re-estimate. The parent caches the
   *  pair per CONTRACT (not per symbol — the estimate is priced off this
   *  contract's premium) and must ignore an `undefined`/`null` estimate rather
   *  than clearing its slot, so an in-flight or failed re-estimate never destroys
   *  the value already on screen. */
  onFirstPassageChange?: (
    estimate: FirstPassageEstimate | null | undefined,
    context: FirstPassageContext | null,
  ) => void;
}
```

- [ ] **Step 2: Destructure the new prop**

Find (lines 177-186):

```typescript
export function TradeCard({
  data,
  recId: propRecId,
  onSendToBroker,
  sendLabel,
  sendDisabled,
  contracts: initialContracts = 1,
  onEditsChange,
  onStructuralStopChange,
}: TradeCardProps) {
```

Replace with:

```typescript
export function TradeCard({
  data,
  recId: propRecId,
  onSendToBroker,
  sendLabel,
  sendDisabled,
  contracts: initialContracts = 1,
  onEditsChange,
  onStructuralStopChange,
  onFirstPassageChange,
}: TradeCardProps) {
```

- [ ] **Step 3: Widen the structural surfacing effect and add the first-passage one**

Find (lines 258-283):

```typescript
  // Surface every structuralStop change (including the reset to `undefined`/`null`
  // above) to the parent, so it can attach the level to the position if/when this
  // trade is sent to the broker — TradeCard itself never writes back to `data`.
  //
  // Deliberately split into two effects (a ref sync + a ref-reading effect)
  // instead of one effect depending on both `structuralStop` and
  // `onStructuralStopChange`: the parent (step-7-trade-card/page.tsx) passes a
  // fresh inline closure on every render, bound to whatever symbol is active
  // AT THAT RENDER. On a Prev/Next contract switch, `data`/`onStructuralStopChange`
  // update in one commit, but `structuralStop` itself doesn't reset until the
  // contract-change effect ABOVE schedules it — a full render later. A single
  // effect keyed on both would fire in that in-between commit using THIS
  // render's (new-symbol) callback together with the STALE (old-symbol)
  // structuralStop value still sitting in state, silently attaching the old
  // candidate's structural stop price to the new one. Keying the
  // value-surfacing effect on `structuralStop` ALONE — reading the callback
  // out of a ref that a separate, harmless effect keeps current — means it
  // only ever fires when the state itself genuinely changes, by which point
  // the ref has already caught up to the current symbol's callback.
  const onStructuralStopChangeRef = useRef(onStructuralStopChange);
  useEffect(() => {
    onStructuralStopChangeRef.current = onStructuralStopChange;
  }, [onStructuralStopChange]);
  useEffect(() => {
    onStructuralStopChangeRef.current?.(structuralStop);
  }, [structuralStop]);
```

Replace with:

```typescript
  // Surface every structuralStop change (including the reset to `undefined`/`null`
  // above) to the parent, so it can attach the level to the position if/when this
  // trade is sent to the broker — TradeCard itself never writes back to `data`.
  //
  // Deliberately split into two effects (a ref sync + a ref-reading effect)
  // instead of one effect depending on both `structuralStop` and
  // `onStructuralStopChange`: the parent (step-7-trade-card/page.tsx) passes a
  // fresh inline closure on every render, bound to whatever symbol is active
  // AT THAT RENDER. On a Prev/Next contract switch, `data`/`onStructuralStopChange`
  // update in one commit, but `structuralStop` itself doesn't reset until the
  // contract-change effect ABOVE schedules it — a full render later. A single
  // effect keyed on both would fire in that in-between commit using THIS
  // render's (new-symbol) callback together with the STALE (old-symbol)
  // structuralStop value still sitting in state, silently attaching the old
  // candidate's structural stop price to the new one. Keying the
  // value-surfacing effect on the VALUES ALONE — reading the callback out of a
  // ref that a separate, harmless effect keeps current — means it only ever
  // fires when the state itself genuinely changes, by which point the ref has
  // already caught up to the current symbol's callback.
  //
  // `structuralStopStockPrice` is a dependency as well as `structuralStop`
  // because the parent caches the pair: the two are always set in the same
  // batch, so this normally fires once with a matched pair, and if they ever
  // landed in separate commits the second fire would correct the first rather
  // than leaving a half-written cache entry.
  const onStructuralStopChangeRef = useRef(onStructuralStopChange);
  useEffect(() => {
    onStructuralStopChangeRef.current = onStructuralStopChange;
  }, [onStructuralStopChange]);
  useEffect(() => {
    onStructuralStopChangeRef.current?.(structuralStop, structuralStopStockPrice);
  }, [structuralStop, structuralStopStockPrice]);

  // Same two-effect discipline, same reasoning, for the first-passage estimate —
  // the parent caches it per contract so re-navigating to this candidate restores
  // the Profit Targets rows instead of forcing another Monte Carlo round-trip.
  // `firstPassage` and `firstPassageContext` are BOTH dependencies because the
  // pair is what the cache stores; `targetPct` deliberately is NOT, because it
  // already travels inside `firstPassageContext` (snapshotted at request time),
  // so editing a % input after an estimate can never rewrite that estimate's
  // cached percentages.
  const onFirstPassageChangeRef = useRef(onFirstPassageChange);
  useEffect(() => {
    onFirstPassageChangeRef.current = onFirstPassageChange;
  }, [onFirstPassageChange]);
  useEffect(() => {
    onFirstPassageChangeRef.current?.(firstPassage, firstPassageContext);
  }, [firstPassage, firstPassageContext]);
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: **clean — zero errors.** This is counter-intuitive and worth stating plainly so nobody concludes the change didn't take: TypeScript lets a *lower*-arity function be assigned to a *higher*-arity function type, so the existing one-parameter call site at `page.tsx:696` (`(stop) => handleStructuralStopChange(effectiveCard.symbol, stop)`) is still perfectly assignable to the new two-parameter prop type, and `onFirstPassageChange` is optional so its absence is fine too. **The compiler will not point you at the work Task 5 still has to do.** The things that actually catch it are (a) Jest's `toHaveBeenCalledWith`, which *is* arity-strict — hence Task 6 Step 1 — and (b) the fact that without Task 5 the second argument simply arrives as `undefined` and no cache entry ever gets a `stockPrice`. Do not skip Task 5 on the strength of a green typecheck here.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/TradeCard/index.tsx
git commit -m "feat(trade-card): surface first-passage estimate and structural stock price to the parent"
```

---

### Task 4: Add the pure `withCachedEstimate` splice helper

**Files:**
- Modify: `frontend/lib/tradeCardOverride.ts:9` (imports) and end of file (append)
- Modify: `frontend/lib/__tests__/tradeCardOverride.test.ts` (new describe block)

This is the read side of the cache, kept as a pure function in the same module as `applyPickedContract`/`mergePlan`/`resolveBasketCards` so the "which values does the rendered card actually carry" logic stays unit-testable — the same reasoning that module's header comment already gives.

- [ ] **Step 1: Widen the type import**

Find (line 9):

```typescript
import type { TradeCardData, OptionContract } from '@/types/domain';
```

Replace with:

```typescript
import type {
  TradeCardData, OptionContract, StructuralStop, FirstPassageEstimate, FirstPassageContext,
} from '@/types/domain';
```

- [ ] **Step 2: Append the cache-entry types and the splice helper at the end of the file**

Append after `rrOverridesFrom`'s closing brace (currently line 115):

```typescript
/** One cached "Estimate" result, keyed by CONTRACT (contractKeyFor) — the
 *  estimate is priced off that contract's premium/strike/dte, so a symbol-level
 *  key would show contract A's numbers on contract B's card. */
export type CachedFirstPassage = {
  estimate: FirstPassageEstimate;
  context:  FirstPassageContext | null;
};

/** One cached "Check structure" result, keyed by SYMBOL — the structural level is
 *  a function of (symbol, direction, stock_price) only; the contract never reaches
 *  api.getStructuralStop. `stop: null` is a real, cacheable answer ("checked, no
 *  order block or swing level found"), distinct from "never checked" (no entry). */
export type CachedStructural = {
  stop:       StructuralStop | null;
  stockPrice: number | null;
};

/**
 * Splice cached "Estimate" / "Check structure" results into the card's
 * `exit.*` fields — the same fields TradeCard already reads for its initial
 * state and its contract-change reset, so restoring costs TradeCard no extra
 * code and works for a re-render AND a remount alike.
 *
 * MUST be applied AFTER mergePlan: mergePlan replaces `exit` wholesale with the
 * recomputed plan's, which would silently discard anything spliced in earlier.
 * Returns the card unchanged (same reference) when there is nothing cached, so
 * it never invents object churn for the common case.
 */
export function withCachedEstimate<T extends TradeCardData>(
  card: T | undefined,
  estimate: CachedFirstPassage | undefined,
  structural: CachedStructural | undefined,
): T | undefined {
  if (!card || (!estimate && !structural)) return card;
  return {
    ...card,
    exit: {
      ...card.exit,
      ...(estimate
        ? { firstPassage: estimate.estimate, firstPassageContext: estimate.context }
        : {}),
      ...(structural
        ? { structuralStop: structural.stop, structuralStopStockPrice: structural.stockPrice }
        : {}),
    },
  };
}
```

- [ ] **Step 3: Add unit tests**

In `frontend/lib/__tests__/tradeCardOverride.test.ts`, widen the import on line 1:

```typescript
import { applyPickedContract, contractKeyFor, mergePlan, resolveBasketCards } from '../tradeCardOverride';
```

to:

```typescript
import {
  applyPickedContract, contractKeyFor, mergePlan, resolveBasketCards, withCachedEstimate,
} from '../tradeCardOverride';
```

and append this describe block at the end of the file:

```typescript
describe('withCachedEstimate', () => {
  const estimate = {
    estimate: {
      targets: [{ pct: 0.2, stockPrice: 340, optionPrice: 25.94, probability: 0.62, expectedDays: 12 }],
      invalidation: { probability: 0.18, expectedDays: 40 },
    },
    context: { premium: 21.62, delta: 0.5, targetPct: { t1: 0.2, t2: 0.35, t3: 0.5 } },
  };
  const structural = {
    stop: { price: 294.5, source: 'order_block' as const, confidence: 71, distancePct: 7.6 },
    stockPrice: 318.9,
  };

  it('returns the same card reference when nothing is cached', () => {
    const card = makeCard();
    expect(withCachedEstimate(card, undefined, undefined)).toBe(card);
  });

  it('returns undefined for an undefined card', () => {
    expect(withCachedEstimate(undefined, estimate, structural)).toBeUndefined();
  });

  it('splices both cached results into exit without touching the rest of exit', () => {
    const card = makeCard();
    const out = withCachedEstimate(card, estimate, structural)!;
    expect(out.exit.firstPassage).toBe(estimate.estimate);
    expect(out.exit.firstPassageContext).toBe(estimate.context);
    expect(out.exit.structuralStop).toBe(structural.stop);
    expect(out.exit.structuralStopStockPrice).toBe(318.9);
    // Untouched plan fields.
    expect(out.exit.invalidation).toBe(card.exit.invalidation);
    expect(out.exit.premiumStop).toBe(card.exit.premiumStop);
    expect(out.entry).toBe(card.entry);
    // The input card is never mutated.
    expect(card.exit.firstPassage).toBeUndefined();
  });

  it('splices only the half that is cached', () => {
    const out = withCachedEstimate(makeCard(), undefined, structural)!;
    expect(out.exit.structuralStop).toBe(structural.stop);
    expect(out.exit.firstPassage).toBeUndefined();
    expect(out.exit.firstPassageContext).toBeUndefined();
  });

  it('preserves a cached "checked, nothing found" structural result as null, not absent', () => {
    const out = withCachedEstimate(makeCard(), undefined, { stop: null, stockPrice: 318.9 })!;
    expect(out.exit.structuralStop).toBeNull();
    expect(out.exit.structuralStopStockPrice).toBe(318.9);
  });

  it('preserves _userOverride on an overridden card', () => {
    const overridden = { ...makeCard(), _userOverride: true };
    const out = withCachedEstimate(overridden, estimate, undefined)!;
    expect(out._userOverride).toBe(true);
  });
});
```

- [ ] **Step 4: Run the helper tests**

Run: `cd frontend && npm run test -- --testPathPattern=tradeCardOverride`
Expected: all PASS (including the pre-existing `applyPickedContract`/`mergePlan`/`resolveBasketCards` blocks).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/tradeCardOverride.ts frontend/lib/__tests__/tradeCardOverride.test.ts
git commit -m "feat(step-7): add pure withCachedEstimate splice helper for cached trade-card results"
```

---

### Task 5: Wire the two caches into the Step 7 page

**Files:**
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:23` (type import)
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:28-31` (helper import)
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:119-141` (cache state + write handlers)
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:181-189` (new-scan invalidation)
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:241` (spliced `cardForDisplay`)
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:490` (`buildPaperPosition` read site)
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:592` (`handleSubmit` read site)
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:690-697` (`<TradeCard>` props)

- [ ] **Step 1: Widen the two imports**

Find (line 23):

```typescript
import type { PortfolioPosition, TradeCardData } from '@/types/domain';
```

Replace with:

```typescript
import type {
  PortfolioPosition, TradeCardData, StructuralStop, FirstPassageEstimate, FirstPassageContext,
} from '@/types/domain';
```

Find (lines 28-31):

```typescript
import {
  applyPickedContract, contractKeyFor, mergePlan, resolveBasketCards, rrOverridesFrom,
  type OverriddenCard, type RecomputedPlanShape,
} from '@/lib/tradeCardOverride';
```

Replace with:

```typescript
import {
  applyPickedContract, contractKeyFor, mergePlan, resolveBasketCards, rrOverridesFrom, withCachedEstimate,
  type OverriddenCard, type RecomputedPlanShape, type CachedFirstPassage, type CachedStructural,
} from '@/lib/tradeCardOverride';
```

- [ ] **Step 2: Replace the narrow `structuralStopBySymbol` state with the two caches and their write handlers**

Find (lines 119-141):

```typescript
  // Structural stop price captured per symbol from the active TradeCard's "Check
  // structure" — attached to the position if/when that symbol is sent to the
  // broker. Only ever populated for whichever symbol is/was the active card, since
  // "Check structure" is a single-card, user-triggered action (see TradeCard's
  // onStructuralStopChange doc comment). Undefined (never fetched/reset) leaves a
  // symbol's entry untouched rather than clearing it, so navigating away and back
  // to an already-checked candidate doesn't lose its captured level.
  const [structuralStopBySymbol, setStructuralStopBySymbol] = useState<Record<string, number | null>>({});
  // The onStructuralStopChange prop passed to TradeCard below is a fresh inline
  // closure every render (matching this file's existing style for onSendToBroker
  // etc.), and TradeCard's own effect depends on that prop reference — so calling
  // this on every invocation, unconditionally, would re-trigger a parent render
  // every time TradeCard re-renders for ANY reason, which re-creates the prop,
  // which re-fires the effect... an infinite loop once structuralStop first
  // settles to a non-undefined value. Bailing out (returning the SAME `prev`
  // object) when the value hasn't actually changed breaks that cascade: React
  // skips the re-render on an identical state reference, so a no-op call here
  // is genuinely a no-op, not just a smaller one.
  const handleStructuralStopChange = (symbol: string, stop: { price: number } | null | undefined) => {
    if (stop === undefined) return;
    const next = stop?.price ?? null;
    setStructuralStopBySymbol((prev) => (prev[symbol] === next ? prev : { ...prev, [symbol]: next }));
  };
```

Replace with:

```typescript
  // "Check structure" results captured from the active TradeCard, per SYMBOL — the
  // structural level is a function of (symbol, direction, stock_price) only, so the
  // contract never enters the key. Serves two readers: the order-send path (which
  // needs just `.stop.price`) and the TradeCard restore path (which needs the whole
  // level plus the price it was measured against, or the R:R-vs-structural-stop
  // column can't be recomputed after a re-navigation). Only ever populated for
  // whichever symbol is/was the active card, since "Check structure" is a
  // single-card, user-triggered action (see TradeCard's onStructuralStopChange doc
  // comment). Undefined (never fetched/reset) leaves a symbol's entry untouched
  // rather than clearing it, so navigating away and back to an already-checked
  // candidate doesn't lose its captured level.
  const [structuralBySymbol, setStructuralBySymbol] = useState<Record<string, CachedStructural>>({});
  // "Estimate" (Monte Carlo first-passage) results, per CONTRACT — unlike the
  // structural stop these ARE contract-specific (every optionPrice is
  // premium*(1+pct) off that contract's own premium), so they're keyed by
  // contractKeyFor, the same identity plansBySymbol tags its entries with.
  const [estimatesByContract, setEstimatesByContract] = useState<Record<string, CachedFirstPassage>>({});
  // Both handlers below: the callback props passed to TradeCard are fresh inline
  // closures every render (matching this file's existing style for onSendToBroker
  // etc.), and TradeCard keeps a ref synced to them via its own effect — so calling
  // these on every invocation, unconditionally, would re-trigger a parent render
  // every time TradeCard re-renders for ANY reason, which re-creates the props,
  // which re-fires that sync effect... an infinite loop once a value first settles
  // to a non-undefined value. Bailing out (returning the SAME `prev` object) when
  // nothing actually changed breaks that cascade: React skips the re-render on an
  // identical state reference, so a no-op call here is genuinely a no-op, not just
  // a smaller one. For the estimate the comparison is by REFERENCE on both halves,
  // which is exactly right: TradeCard stores one object per successful estimate and
  // holds it until the next one, and on a restore we splice those very same objects
  // back in — so the post-restore effect fire compares equal and bails.
  const handleStructuralStopChange = (
    symbol: string,
    stop: StructuralStop | null | undefined,
    stockPrice: number | null,
  ) => {
    if (stop === undefined) return;
    setStructuralBySymbol((prev) => {
      const cur = prev[symbol];
      if (cur && cur.stop === stop && cur.stockPrice === stockPrice) return prev;
      return { ...prev, [symbol]: { stop, stockPrice } };
    });
  };
  // `key` is null only when the card has no resolvable contract (contractDetails
  // missing) — in which case the Estimate button is disabled anyway. An
  // undefined/null estimate is the "reset on contract switch" or "cleared at the
  // start of a re-estimate" sentinel: ignored, never written, so an in-flight or
  // failed re-estimate leaves the previously cached value intact rather than
  // destroying what the user could still see a moment ago.
  const handleFirstPassageChange = (
    key: string | null,
    estimate: FirstPassageEstimate | null | undefined,
    context: FirstPassageContext | null,
  ) => {
    if (!key || estimate == null) return;
    setEstimatesByContract((prev) => {
      const cur = prev[key];
      if (cur && cur.estimate === estimate && cur.context === context) return prev;
      return { ...prev, [key]: { estimate, context } };
    });
  };
```

- [ ] **Step 3: Invalidate both caches when a new scan lands**

Find (lines 181-189):

```typescript
  useEffect(() => {
    if (scanResult?.candidates?.length) {
      setCards(scanResult.candidates);
      if (scanResult.candidates[0]) setActive(scanResult.candidates[0].symbol);
    } else {
      setCards([]);
      setActive('');
    }
  }, [scanResult]);
```

Replace with:

```typescript
  useEffect(() => {
    // A new scan invalidates every cached "Estimate" and "Check structure"
    // result: both were computed against the previous run's prices (and, for
    // the estimate, against that run's recomputed invalidation level), so
    // carrying them forward would show pre-scan numbers on post-scan cards.
    // NOTE this also clears the levels the order-send path reads — a structural
    // stop checked before a scan no longer rides along into a position opened
    // after it, which is the intended behaviour, not a side effect.
    setEstimatesByContract({});
    setStructuralBySymbol({});
    if (scanResult?.candidates?.length) {
      setCards(scanResult.candidates);
      if (scanResult.candidates[0]) setActive(scanResult.candidates[0].symbol);
    } else {
      setCards([]);
      setActive('');
    }
  }, [scanResult]);
```

- [ ] **Step 4: Build the spliced `cardForDisplay`**

Find (lines 240-241):

```typescript
  // Merge the recomputed Entry/Exit/RR into the overridden card once it arrives.
  const effectiveCard = pickedCard && planForThisContract ? mergePlan(pickedCard, planForThisContract) : pickedCard;
```

Replace with:

```typescript
  // Merge the recomputed Entry/Exit/RR into the overridden card once it arrives.
  const effectiveCard = pickedCard && planForThisContract ? mergePlan(pickedCard, planForThisContract) : pickedCard;

  // The card actually handed to <TradeCard>, with any cached "Estimate" /
  // "Check structure" result for this contract spliced into exit.* — the same
  // fields TradeCard reads for its initial state and its contract-change reset,
  // so a Prev/Next round trip restores the Profit Targets rows (and the R:R
  // column, and the T1/T2/T3 inputs) without re-firing a single request.
  // DELIBERATELY applied after mergePlan (which replaces `exit` wholesale and
  // would otherwise discard the splice) and DELIBERATELY not used anywhere else:
  // ordering, sizing and the order-send path all keep reading `effectiveCard`,
  // so nothing about what gets sent to a broker depends on this display-only
  // enrichment.
  const cardForDisplay = useMemo(
    () => withCachedEstimate(
      effectiveCard,
      contractKey ? estimatesByContract[contractKey] : undefined,
      effectiveCard ? structuralBySymbol[effectiveCard.symbol] : undefined,
    ),
    [effectiveCard, contractKey, estimatesByContract, structuralBySymbol],
  );
```

A note on what this `useMemo` does and does not buy, so nobody later builds on a false assumption: for a NON-overridden card `effectiveCard` is a stable reference (it is `cardIndex[symbol]` passed straight through `applyPickedContract`), so the memo genuinely holds `cardForDisplay` stable across renders. For an OVERRIDDEN card `applyPickedContract` builds a fresh object every render, so `effectiveCard` — and therefore `cardForDisplay` — changes identity on every render regardless of the memo. That is already true of `effectiveCard` today and is safe here because **no effect inside `TradeCard` depends on the `data` object's identity**: the reset effect keys on `data.symbol`/`data.contract` (primitives, `index.tsx:252`), `estimateFirstPassage` on primitives plus the stable `data.contractDetails` sub-reference (`:373`), `checkStructure` on primitives (`:437`), and the only whole-`data` dependencies (`dirty` at `:460` and `editedRR` at `:465`) are `useMemo`s that merely recompute and set no state. So a new `data` reference costs a recompute and nothing else — it can never re-trigger the reset that wipes the restored values.

- [ ] **Step 5: Update the two order-send read sites for the widened cache shape**

Find (line 490, inside `buildPaperPosition`):

```typescript
      structuralStop: structuralStopBySymbol[card.symbol] ?? null,
```

Replace with:

```typescript
      structuralStop: structuralBySymbol[card.symbol]?.stop?.price ?? null,
```

Find (line 592, inside `handleSubmit`):

```typescript
      const structuralStop = structuralStopBySymbol[o.card.symbol] ?? null;
```

Replace with:

```typescript
      const structuralStop = structuralBySymbol[o.card.symbol]?.stop?.price ?? null;
```

Both preserve the existing semantics exactly: no entry, or an entry whose level came back "nothing found", yields `null`.

- [ ] **Step 6: Pass the display card and both callbacks to `<TradeCard>`**

Find (lines 690-697):

```typescript
            <TradeCard
              data={effectiveCard}
              recId={recIdMap[effectiveCard.symbol]}
              onSendToBroker={() => !basketEmpty && !basketPlansPending && setDialogOpen(true)}
              sendLabel={sendLabel}
              sendDisabled={basketEmpty || basketPlansPending}
              onStructuralStopChange={(stop) => handleStructuralStopChange(effectiveCard.symbol, stop)}
            />
```

Replace with:

```typescript
            <TradeCard
              data={cardForDisplay ?? effectiveCard}
              recId={recIdMap[effectiveCard.symbol]}
              onSendToBroker={() => !basketEmpty && !basketPlansPending && setDialogOpen(true)}
              sendLabel={sendLabel}
              sendDisabled={basketEmpty || basketPlansPending}
              onStructuralStopChange={(stop, stockPrice) => handleStructuralStopChange(effectiveCard.symbol, stop, stockPrice)}
              onFirstPassageChange={(estimate, context) => handleFirstPassageChange(contractKey, estimate, context)}
            />
```

(`cardForDisplay ?? effectiveCard` rather than a bare `cardForDisplay`: this JSX sits inside `{effectiveCard && (…)}`, which narrows `effectiveCard` but not the separately-declared memo, and `withCachedEstimate` returns the same reference when nothing is cached, so the fallback is only ever a type-level formality.)

- [ ] **Step 7: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean — including the Task 3 error, which this task resolves.

- [ ] **Step 8: Commit**

```bash
git add "frontend/app/(frame)/screener/step-7-trade-card/page.tsx"
git commit -m "feat(step-7): cache profit-target estimates per contract and structure checks per symbol"
```

---

### Task 6: Update and extend the TradeCard tests

**Files:**
- Modify: `frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx`

- [ ] **Step 1: Fix the two `onStructuralStopChange` arity assertions**

The callback now takes `(stop, stockPrice)`. `toHaveBeenCalledWith(x)` requires an exact argument-list match, so the positive assertion breaks outright and the negative one would start passing vacuously (silently un-testing the regression it exists for).

In `'does not surface the previous candidate\'s structural stop to the new one after switching'` (around lines 287-289), find:

```typescript
    await waitFor(() => {
      expect(onChangeForAAPL).toHaveBeenCalledWith(expect.objectContaining({ price: 178.5 }));
    });
```

Replace with:

```typescript
    await waitFor(() => {
      // Second arg is the fresh stock price the level was measured against —
      // 185.2 here, from the default getStockQuote mock in beforeEach. The
      // parent caches the pair, so this assertion pins both halves.
      expect(onChangeForAAPL).toHaveBeenCalledWith(expect.objectContaining({ price: 178.5 }), 185.2);
    });
```

Then, at the end of the same test (around line 300), find:

```typescript
    expect(onChangeForMSFT).not.toHaveBeenCalledWith(expect.objectContaining({ price: 178.5 }));
  });
```

Replace with:

```typescript
    // Asserted over the recorded calls rather than with `.not.toHaveBeenCalledWith`,
    // which matches on the full argument list and would therefore pass vacuously
    // for any future arity change — the exact way this regression test could go
    // quietly dead.
    const sawAaplStop = onChangeForMSFT.mock.calls.some(
      ([stop]) => (stop as { price?: number } | null | undefined)?.price === 178.5,
    );
    expect(sawAaplStop).toBe(false);
  });
```

- [ ] **Step 2: Add a test that a cached estimate spliced into `data.exit` is restored on a contract switch, with no refetch**

Add after the existing `'does not apply a stale first-passage response after the contract changes'` test (which ends around line 419):

```typescript
  it('restores a cached first-passage estimate from data.exit on a contract switch, without refetching', async () => {
    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    // The api mocks in this file are NEVER cleared between tests (no
    // clearMocks in jest.config.ts, no jest.clearAllMocks() in beforeEach), so
    // `expect(api.X).not.toHaveBeenCalled()` would fail here purely because
    // EARLIER tests in this file already called all three. Snapshot the counts
    // and assert they don't move — which is the real claim anyway: restoring
    // from the cache issues no NEW request.
    const callsBefore = {
      firstPassage:   (api.getFirstPassageEstimate as jest.Mock).mock.calls.length,
      structuralStop: (api.getStructuralStop as jest.Mock).mock.calls.length,
      stockQuote:     (api.getStockQuote as jest.Mock).mock.calls.length,
    };

    // Simulate CandidateNav switching to a contract the parent HAS a cached
    // estimate for — the parent splices it (and its context) into exit.*, the
    // exact fields TradeCard's contract-change reset already reads.
    const cachedCard: TradeCardData = {
      ...mockTradeCard,
      symbol: 'MSFT',
      contract: 'MSFT 300C 06/19',
      exit: {
        ...mockTradeCard.exit,
        firstPassage: {
          targets: [{ pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 }],
          invalidation: { probability: 0.30, expectedDays: 4 },
        },
        firstPassageContext: { premium: 2.75, delta: 0.42, targetPct: { t1: 0.10, t2: 0.35, t3: 0.50 } },
        structuralStop: { price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6 },
        structuralStopStockPrice: 190.0,
      },
    };
    rerender(<TradeCard data={cachedCard} />);

    // Rows are back. The restore happens inside the contract-change useEffect,
    // whose setState schedules a further render — waitFor rather than a bare
    // sync assertion, matching how every other post-effect assertion in this
    // file is written.
    await waitFor(() => {
      expect(screen.getByText('T20%')).toBeInTheDocument();
    });
    expect(screen.getByText('$3.30')).toBeInTheDocument();
    // ...the % inputs show the percentages the estimate was RUN at (10, not the
    // 20 the settings default would reset them to)...
    expect(screen.getByLabelText('T1 profit target %')).toHaveValue(10);
    // ...and the structural R:R column is computed, not stuck on the
    // "not yet checked" placeholder: stockMove = |178.5 - 190| = 11.5,
    // deltaEst = 0.42, risk = min(11.5 * 0.42, 2.75) = min(4.83, 2.75) = 2.75
    // (clamped to premium), reward = 3.3 - 2.75 = 0.55 -> rr = 0.2.
    expect(screen.getByText('0.2×')).toBeInTheDocument();
    // Nothing was re-fetched to get any of that back.
    expect((api.getFirstPassageEstimate as jest.Mock).mock.calls.length).toBe(callsBefore.firstPassage);
    expect((api.getStructuralStop as jest.Mock).mock.calls.length).toBe(callsBefore.structuralStop);
    expect((api.getStockQuote as jest.Mock).mock.calls.length).toBe(callsBefore.stockQuote);
  });
```

(If the computed `0.2×` differs once run, recompute it from the formula in `structuralRR` — `reward / min(|stop - stockPrice| * max(|delta|, 0.05), premium)`, rendered with `toFixed(1)` — and correct the expected string. Do **not** change the production formula to match the assertion.)

- [ ] **Step 3: Add a test that a successful Estimate is surfaced to `onFirstPassageChange` with its context**

Add directly after the test from Step 2:

```typescript
  it('surfaces a completed first-passage estimate and its context to onFirstPassageChange', async () => {
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    const estimate = {
      targets: [{ pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 }],
      invalidation: { probability: 0.30, expectedDays: 4 },
    };
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce(estimate);

    const onFirstPassageChange = jest.fn();
    render(<TradeCard data={mockTradeCard} onFirstPassageChange={onFirstPassageChange} />);
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));

    await waitFor(() => {
      expect(onFirstPassageChange).toHaveBeenCalledWith(
        expect.objectContaining({ targets: estimate.targets }),
        // Fresh quote values, plus the % trio the request actually carried —
        // this pair is what the parent caches per contract.
        { premium: 2.75, delta: 0.42, targetPct: { t1: 0.20, t2: 0.35, t3: 0.50 } },
      );
    });
  });
```

- [ ] **Step 4: Add the mirror of the structural-stop cross-contamination regression test**

Add directly after the test from Step 3:

```typescript
  it('never surfaces the previous candidate\'s estimate under the new contract\'s callback', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [{ pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 }],
      invalidation: { probability: 0.30, expectedDays: 4 },
    });
    const onChangeForAAPL = jest.fn();
    const { rerender } = render(<TradeCard data={mockTradeCard} onFirstPassageChange={onChangeForAAPL} />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    });
    await waitFor(() => {
      expect(onChangeForAAPL).toHaveBeenCalledWith(
        expect.objectContaining({ targets: expect.any(Array) }),
        expect.objectContaining({ premium: expect.any(Number) }),
      );
    });

    // Switch to a never-estimated candidate with a fresh callback, exactly as
    // the real parent does — the new contract's callback must only ever see the
    // reset sentinel, never AAPL's estimate (which would cache AAPL's premiums
    // under MSFT's contract key).
    const nextCard: TradeCardData = { ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT 300C 06/19' };
    const onChangeForMSFT = jest.fn();
    rerender(<TradeCard data={nextCard} onFirstPassageChange={onChangeForMSFT} />);

    await waitFor(() => {
      expect(onChangeForMSFT).toHaveBeenCalled();
    });
    const sawAaplEstimate = onChangeForMSFT.mock.calls.some(([estimate]) => estimate != null);
    expect(sawAaplEstimate).toBe(false);
  });
```

- [ ] **Step 5: Run the TradeCard suite**

Run: `cd frontend && npm run test -- --testPathPattern=TradeCard`
Expected: all PASS. If `'does not apply a stale first-passage response after the contract changes'` (which rerenders with a `nextCard` built from `mockTradeCard`, whose `exit` carries no cached fields) fails, that is a real signal — the restore path must never invent a value the parent didn't splice in.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx
git commit -m "test(trade-card): cover estimate/structure restore-from-cache and callback surfacing"
```

---

### Task 7: Typecheck, full test suite, and manual verification

**Files:** none (verification only)

- [ ] **Step 1: Full frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean, no errors.

- [ ] **Step 2: Full frontend test suite**

Run: `cd frontend && npm run test`
Expected: all PASS. Pay particular attention to `portfolioStore` / `alertEngine` suites: they exercise `PortfolioPosition.structuralStop` (a `number`, a different field from `TradeCardData.exit.structuralStop`) and must be unaffected — if either moves, the `buildPaperPosition` / `handleSubmit` read sites in Task 5 Step 5 were changed incorrectly.

- [ ] **Step 3: Manual browser verification**

Start the dev server (`cd frontend && npm run dev`, default port 3001) and run the Options screener through to Step 7 with at least two candidates, then verify each of these:

1. **The reported bug is fixed.** On candidate A, click "Estimate". Note the rows. Press Next to candidate B, then Prev back to A — the Profit Targets rows, the "R:R vs. structural stop" column, and the T1/T2/T3 inputs are all exactly as you left them, and the browser devtools Network tab shows **no** new `/api/contracts/first-passage` or `/api/contracts/structural-stop` request on the way back.
2. **Custom percentages survive.** On candidate B, set T1 to 10, click "Estimate", navigate away and back — the rows show T10% and the T1 input still reads 10.
3. **No cross-contamination.** Candidate B (never estimated) shows an empty Profit Targets section while A shows its cached one; switching between them never shows A's numbers under B's header.
4. **Structure alone caches too.** On candidate C, click only "Check structure", navigate away and back — the structural stop line is still in the Exit Plan, with no refetch.
5. **Re-estimate overwrites.** Back on candidate A, change T2 and click "Estimate" again — the rows update, and navigating away and back restores the NEW estimate, not the old one.
6. **A new scan invalidates.** Go back to Step 3, run a fresh scan, return to Step 7 — every candidate's Profit Targets section is empty again and "Estimate"/"Check structure" behave as first-run.
7. **Nothing regressed in the send path.** With a structural stop checked for a candidate, send it to a paper broker and confirm the resulting Portfolio row still carries the structural stop value.
8. **Known-and-accepted: a failed re-check keeps the old level** (design note 11a). On a candidate with a checked structure, force the next `/api/contracts/structural-stop` call to fail (devtools request blocking, or stop the backend for one click), click "Check structure" again — the card shows the error and no level. Navigate away and back: the PREVIOUS level reappears. Confirm this matches note 11a rather than filing it as a bug.
9. **Known-and-accepted: leaving the route clears the cache** (see "Scope of survives"). With an estimate on screen, go Back to Step 6 and forward to Step 7 again — the Profit Targets section is empty and "Estimate" behaves as first-run. This is the documented boundary of the fix, not a failure of it.

Take a screenshot of a restored Profit Targets card for the record.

- [ ] **Step 4: Final commit (only if manual verification found something to fix)**

```bash
git add -A
git commit -m "fix(trade-card): address issues found in manual verification of the estimate cache"
```
(Skip this step entirely if Step 3 found nothing to fix.)

---

## Self-Review Notes (completed by the plan author, not a task for the implementer)

- **Relationship to the 2026-08-20 plan:** that plan is fully implemented in this worktree (verified against the live code, not the document: `normalizeStructuralStopResponse`, `ProfitTargetRow`, the `.fullWidth` Profit Targets section, the `premiumStop` risk basis in `rrContribution`/`computeEditedRR`, and the Estimate-triggered structural fetch are all present). This plan touches none of its formulas or markup. It does directly retire that plan's recorded MEDIUM self-review finding — the hypothetical "what if a card ever arrived with `exit.structuralStop`/`exit.firstPassage` pre-populated but the companions null" — by making that case real and making the companions travel with the values, so `ProfitTargetRow`'s `structuralZeroRisk` branch keeps its exact meaning.
- **Blocker check:** none found. The three things that looked like blockers on first pass all resolve cleanly: (a) `mergePlan` discarding a spliced `exit` → splice after the merge, in a display-only memo; (b) the companions having no home on `TradeCardData` → two optional client-only fields, following the convention the two existing client-only `exit` fields already established; (c) the write path reintroducing the stale-response race → it can't, because the write is driven by a state-keyed effect reading a ref'd callback, the same construction whose correctness is already pinned by an existing regression test.
- **Granularity decision, justified:** contract-keyed for the estimate (premium-dependent, so a symbol key would be actively wrong), symbol-keyed for the structural stop (`api.getStructuralStop` takes only symbol/direction/stock_price, and the page already keys its structural cache by symbol). The one visible consequence — a structure check now surviving a contract switch within a symbol — is a correctness improvement, and it makes `estimateFirstPassage`'s auto-trigger correctly skip a redundant fetch.
- **Loop-hazard coverage:** every new write path bails out by returning the identical `prev` object; both surfacing effects key on state values only and read their callback from a ref; the reset effect's dependency array is unchanged (primitives), so a parent cache write cannot re-trigger it. No `useCallback` introduced, matching the file's existing style and the existing comment's own explanation of what actually breaks the cascade.
- **Placeholder scan:** no TBD / "similar to Task N" / "handle it appropriately" language; every step carries full before/after code. The single computed expectation that could need adjustment at run time (the `0.2×` structural R:R in Task 6 Step 2) is called out with the exact formula to re-derive it from, and with an explicit instruction not to bend production code to it.
- **Type consistency:** `withCachedEstimate<T extends TradeCardData>(card, estimate, structural)` is called at exactly one site with `(OverriddenCard | undefined, CachedFirstPassage | undefined, CachedStructural | undefined)` and its `T | undefined` return is consumed as `cardForDisplay ?? effectiveCard`. `CachedFirstPassage.estimate`/`.context` and `CachedStructural.stop`/`.stockPrice` line up field-for-field with what the two handlers write and what the splice reads. `FirstPassageContext` is defined once in `types/domain.ts`, imported by `TradeCard/index.tsx`, `lib/tradeCardOverride.ts` and `page.tsx`, and its `targetPct` is structurally identical to `settingsStore`'s `TargetProfitPct` so `setTargetPct(data.exit.firstPassageContext?.targetPct ?? defaultTargetPct)` typechecks without a cast.
- **Deliberate non-goals:** an estimate whose request was aborted by navigating away is not cached (the user re-clicks — unchanged from today); the caches are plain component `useState`, so they are lost on a browser reload **and** on any route change out of Step 7 (Next.js App Router unmounts the page — a Step 7 → Step 6 → Step 7 round trip starts fresh), which is why the Goal is scoped to "within a Step 7 session"; a failed *re*-check of structure leaves the previously cached level in place and it will reappear on re-navigation (design note 11a); no page-level test file is added for `step-7-trade-card` (none exists, and standing one up would require mocking the whole scan/portfolio/auto-trade store surface for coverage the pure-helper tests and manual pass already give).
- **Audit-round corrections (2026-08-22, adversarial round 1):** four factual/logic defects were found in the version of this plan committed as `8a65d51` and are fixed above — (1) Task 3 Step 4 claimed the typecheck would report one error at `page.tsx:696`; it will not, because TypeScript accepts a lower-arity function for a higher-arity function type, so the expectation is now "clean" with an explicit warning not to skip Task 5; (2) Task 6 Step 2's three `expect(api.X).not.toHaveBeenCalled()` assertions would have failed outright, because this Jest project clears no mocks between tests (design note 11b) — they are now call-count snapshots; (3) the Goal implied the cache survives anything short of a new scan, when in fact any route change out of Step 7 unmounts it — now stated up front and in the non-goals; (4) the failed-re-check-resurrects-a-stale-level consequence was unexamined — now design note 11a plus manual step 8. A fifth, smaller fix: Task 6 Step 2's post-`rerender` assertions were synchronous and are now wrapped in `waitFor`, matching the rest of the file. Also corrected: note 11 mis-attributed the two arity fixes to Task 5 (they are Task 6 Step 1). All line-number references in the plan were re-verified against the live files and are accurate.
- **Audit-round corrections (round 2):** two further items, both documentation-level rather than code-level — (1) design note 9's orphaned-entry scenario is unreachable within a session (changing the Step 6 pick requires leaving the route, which destroys the caches); the note now says so instead of presenting it as a live mitigation; (2) the `cardForDisplay` `useMemo` was presented as if it kept the display card referentially stable, which it does only for non-overridden cards — the plan now states this and, more importantly, records the verification that no `TradeCard` effect keys on `data`'s identity, which is the property that actually makes an unstable `data` reference harmless. Round 2 found no logic, race, or invalidation defect: the mount-time firing of both surfacing effects, the bail-out-by-reference on restore, the abort-on-switch path, the `structuralZeroRisk` branch after a restore, and the completeness of the `[scanResult]` invalidation point (verified: `setScanResult` has exactly two production callers, `RunScanButton` and `StoreHydration`, and both flow through that one effect) were all re-derived from the live code and hold.
- **Post-implementation independent audit (2026-08-22) — one HIGH finding, fixed.** After implementation, a genuinely independent review (a fresh subagent with no prior involvement, auditing the diff cold) found that `estimateFirstPassage`'s auto-trigger for the structural-stop fetch gated on `structuralStop === undefined` — a condition that was true only for "genuinely never fetched" *before* this plan, but which this plan's own restore-from-cache path can now make false for a value that is actually hours or days old. Concretely: check structure on candidate A at 09:30 (stock $190, stop $178.50), navigate away, return at 11:30 (stock $180) and click Estimate — the auto-trigger saw `structuralStop` already populated (restored from cache) and skipped the refetch entirely, so `structuralRR` computed risk from an 11.5-point stale move instead of the real 1.5-point one, and the Exit Plan's "% away" line rendered a stale figure — a silently wrong R:R-vs-structural-stop number, not a crash or a blank cell, which is the worst kind of bug for a screen a trade decision gets made from. Fixed by adding `structuralIsFreshRef` (`TradeCard/index.tsx`): a plain ref, not state, tracking whether the *current* `structuralStop` value was obtained by a fetch performed in this mount, set `false` whenever the contract-change reset effect restores a value (cached or absent) and `false` at the start of every `checkStructure` call, set `true` only when a fetch — manual or auto-triggered — actually resolves. The auto-trigger's gate is now `!structuralIsFreshRef.current && !structuralLoading`, so a restored value still renders immediately (no blank flash) but a background refresh always fires on the next Estimate click, landing a same-vintage `(structuralStop, structuralStopStockPrice)` pair before `structuralRR` reads them again. The pre-existing caveat that Check-structure and Estimate are independent, user-triggered fetches that can legitimately disagree if clicked minutes apart (the comment above `structuralRR`'s `useMemo`) still applies to genuinely fresh clicks within one mount — that tradeoff is unchanged and intentional; this fix only removes the NEW failure mode where a *cache restore*, not a user's own click cadence, was the source of the staleness. The same audit's other two findings (a claimed "new scan invalidates the cache" effect that is in practice unreachable while the page stays mounted, since routing to the only place a new scan can be started already unmounts the page and its caches with it; and a failed re-estimate leaving a previously-typed-but-never-submitted `targetPct` edit reverted on the next navigation) were reviewed and are not code defects — the first is now an explicit comment on that effect in `page.tsx` rather than a silent redundancy, and the second is consistent with this component's pre-existing convention that any unsaved edit not yet reflected in a successful request is discarded on navigation (the `overlay` fields already behave identically), so it was left as-is.
- **Post-implementation independent audit (2026-08-22, round 2 — confirming pass on the round-1 fix) — one MEDIUM found, fixed; two LOW reviewed and left as-is; one NIT reviewed and left as-is.** A fresh independent reviewer (no prior involvement, cold read of the branch) re-verified the round-1 `structuralIsFreshRef` fix — state-machine completeness across four interleavings, ref-vs-state correctness, and that the round-1 regression test genuinely fails on a faithful revert — and found it sound, but caught an incomplete case: the auto-trigger's **error path** left the stale, unconfirmed `structuralStop`/`structuralStopStockPrice` pair in place on a failed refresh, while `firstPassageContext` had by then already moved to that click's fresh premium/delta — so `structuralRR` could still render a mixed-vintage number, just via the failure branch instead of the "never refetched" branch round 1 closed. Fixed: the auto-trigger's `.catch()` now also clears `structuralStop`/`structuralStopStockPrice` to `undefined`/`null` on failure, matching what `checkStructure` already does on retry — since this refresh only ever runs when the current value wasn't confirmed fresh, a failure means there is no trustworthy pair to show, and `structuralRR`'s existing `!structuralStop` guard then falls back to the defensive `'—'` placeholder instead of a wrong number. A second regression test covers this exact scenario (restore → Estimate → structural refresh rejects, estimate itself succeeds → stale level gone, error banner shown, R:R cell shows `'—'`, not a computed ratio). The same round also flagged, and this fix incidentally closes, a related LOW (a transient mixed-vintage render if the estimate call resolves before the structural one on the *success* path) — the cleared-on-failure and not-yet-updated-on-still-pending states now converge on the same safe `!structuralStop` fallback. Two further items were reviewed and intentionally left as-is: a pre-existing LOW ("fresh" means "confirmed this mount," not "recent" — a manually-checked value from hours earlier in the same mount is never re-verified until the user acts again; already acknowledged in the `structuralRR` comment) and a NIT (`page.tsx`'s `cardForDisplay ?? effectiveCard` fallback is provably unreachable given `withCachedEstimate`'s contract, but removing it risks a TypeScript narrowing fight across a `useMemo` boundary for zero runtime benefit).
- **Post-implementation independent audit (2026-08-22, round 3 — confirming pass on the round-2 fix) — one MEDIUM found, fixed (which also resolved a LOW and a NIT from the same report as side effects).** A third fresh reviewer verified round 2's local-render fix was itself correct (`structuralIsFreshRef` never strands `true`, manual "Check structure" still recovers, the round-2 regression test genuinely fails on a faithful revert of just the `.catch` fix) but found the fix incomplete one layer up: clearing to `undefined` fixed the CURRENT render, but `undefined` is precisely the sentinel `cacheStructural` (`lib/tradeCardOverride.ts:161`) is designed to ignore, by intent, so a transient failure never wipes a good cached value elsewhere. Here that same protection meant the stale, cache-restored entry was **never actually cleared in the parent** — only hidden for the current render — so the very next navigate-away-and-back restored the stale pair again, this time silently, with no error banner (the reset effect clears `structuralError` on every contract switch) and no automatic refetch until the user manually clicked Estimate again. The auditor's harness reproduced it precisely: after a second re-navigation, the R:R cell showed a computed `0.4×` from the stale $178.50/$190 pair against a newer $5.00 premium. The same staleness also reached `page.tsx`'s order-send path (`structuralBySymbol[symbol]?.stop?.price`, read at two call sites), which shares this exact cache — so a broker order could have carried the stale level forward too. Fixed with a one-line, single-root-cause change: the `.catch()` handler now clears to `null` instead of `undefined`. `null` is not a "don't touch" sentinel to this cache — it is the identical shape a genuine "checked, found nothing" result already produces (`checkStructure`'s own success path), so writing it forces a real overwrite of the stale entry, closing the display bug, the order-send divergence, and (as a side effect the auditor separately flagged as a NIT) making the `'—'` catch-all placeholder unreachable again in this path, since `structuralUnavailable` now correctly matches instead. A new regression test asserts the write-back callback's LAST call after a failed refresh carries `(null, null)`, not `(undefined, null)` — the one distinction the parent's reducer actually branches on — and the existing round-2 test's expected placeholder text was updated from `'—'` to `'No structural stop found'` to match the now-correct `structuralUnavailable` branch.
- **Post-implementation independent audit (2026-08-22, round 4 — confirming pass on round 3, going one layer further) — one MEDIUM found and fixed (round 3's own scenario itself re-verified sound), one LOW found and fixed, one LOW found and accepted as a documented trade-off.** A fourth fresh reviewer reproduced round 3's exact multi-navigation scenario by hand and confirmed it holds (the stale level never returns, the new test genuinely fails on a revert), then found the mixed-vintage hazard is symmetric — every prior round only ever protected `structuralStop` from being the stale half of the pair:
  - **MEDIUM, fixed:** nothing protected the OTHER direction. A restored (never-refreshed-this-visit) `firstPassage`/`firstPassageContext` sitting next to a genuinely fresh `structuralStop` — obtained via a MANUAL "Check structure" click alone, without "Estimate" — combines exactly as readily as the already-fixed cases, and structuralRR has no way to know the estimate half is the old one. First attempt at a fix (auto-firing `estimateFirstPassage()` from `checkStructure`'s success, symmetric to the existing reverse direction) was implemented, found to add two unwanted network calls to a "Check structure"-only click and to break six pre-existing tests whose shared, never-reset mocks assumed no such call, and was reverted. The actual fix instead gates `structuralRR` itself: a new `firstPassageIsFreshRef` (mirroring `structuralIsFreshRef`) and `pairRestoredTogetherRef` (true only while both halves still hold what a single cache restore, or the initial absence of either, last wrote together) — `structuralRR` now requires EITHER the pair to still be an untouched restore, OR both halves independently confirmed fresh this mount. A fresh "Check structure" against a stale estimate now shows no R:R at all (rather than a wrong one) until the user's own next "Estimate" click brings both sides current — conservative on convenience, never wrong on the number. `ProfitTargetRow`'s `structuralZeroRisk` label ("N/A (stop = price)") needed the same gate added, or it would have claimed the blocked-for-staleness case meant something it doesn't (the stop resolving to exactly the current price) — that specific mislabeling was caught before shipping, not by a separate audit round.
  - **LOW, fixed:** `cacheFirstPassage`'s guard was `estimate == null` (loosely ignoring BOTH `undefined` and `null`), unlike `cacheStructural`'s strict `=== undefined` — so even after `estimateFirstPassage`'s own outer failure path was made to write `null` (mirroring round 3), the parent's cache still silently kept the stale entry, because the guard threw the `null` away regardless. Fixed by widening `CachedFirstPassage.estimate` to `FirstPassageEstimate | null` and tightening the guard to `=== undefined`, exactly mirroring `cacheStructural`'s existing convention — verified nothing in this codebase ever produced a legitimate `null` estimate before this change, so nothing relied on it being ignored.
  - **LOW, fixed:** the MANUAL "Check structure" button's own failure path never got round 3's fix at all — round 3 only touched the AUTO-triggered structural sub-fetch inside `estimateFirstPassage`. A manual re-check that fails still left `structuralStop` at the `undefined` it was set to when the fetch started, which `cacheStructural` ignores, so a manually-re-checked-and-failed stale level also survived in the parent and silently returned on the next navigation — exactly round 3's symptom, reached via the other button. Fixed identically: the manual path's `catch` now also writes `(null, null)`.
  - **LOW, reviewed and accepted, not fixed:** a failure-sourced `null` renders as "No order block or swing level found nearby" (structural) once `structuralError` resets on the next navigation, an affirmative "checked, nothing there" for a check that actually errored. Same trade-off round 3's own note already accepted for the R:R cell's wording; extending precise failure-vs-not-found labeling to every place a cleared value renders would mean widening the cached shape itself (a third field marking provenance) for a purely cosmetic distinction that never produces a wrong number or a wrong trade decision — the check failing is still visibly true one render earlier (the error banner shows before any navigation), and re-running "Check structure" costs one click.
  - Reproduced round 4's own new scenario end-to-end after the fix (restore a cached estimate, click "Check structure" fresh with a very different stock price) and confirmed no `0.2×`-style wrong ratio, no `N/A (stop = price)` mislabel, and the structural level itself still displays correctly — codified as a new regression test, verified to fail on a revert of just the new gate.
- **Post-implementation independent audit (2026-08-22, round 5 — confirming pass on round 4's fix) — one MEDIUM found and fixed by REMOVING the mechanism it was found in, rather than patching it further.** A fifth independent reviewer traced round 4's `pairRestoredTogetherRef` exemption (letting a restored pair compute an R:R immediately, since both halves came from the same restore) across two navigations instead of one, and found the exemption's core assumption false: `structuralBySymbol` (symbol-keyed) and `estimatesByContract` (contract-keyed), the two PARENT caches in `step-7-trade-card/page.tsx`, are independent and can each be refreshed on their own schedule. Concretely: restore a pair from 09:30 → click "Check structure" only (not Estimate) at 11:30, getting a genuinely fresh stop that correctly shows no R:R (round 4 working) — but that fresh stop also lands in the parent's structural cache. Navigate away and back a SECOND time: the reset effect restores this now-fresh-but-different-vintage stop alongside the STILL-09:30 estimate, `pairRestoredTogetherRef` sets `true` unconditionally on any restore, and the gate passes — producing a real, wrong, silent number (traced: `0.2×` shown, `~0.13×` honest). "Restored together" described the local component's own two `setState` calls in one commit, not the two independent caches upstream of them, and there is no cheap way to make it describe that without threading pairing metadata (a paired-with backreference, checked bidirectionally) through both cache shapes and both write-back callback signatures — sketched, and rejected as a sixth layer of increasingly intricate state tracking on what is, after four prior rounds each finding a real but narrower gap in the same "trust a restored pair" idea, better recognized as a flawed idea rather than one needing a fifth patch.

  **Fix: removed `pairRestoredTogetherRef` and the "restored pair" exemption entirely.** `structuralRR`'s gate is now unconditionally `structuralIsFreshRef.current && firstPassageIsFreshRef.current` — computing the derived R:R-vs-structural-stop figure requires BOTH sides independently reconfirmed fresh this mount, full stop, with no restore-based shortcut to reintroduce a gap in. This is strictly less code than what it replaces, not more. The cost is a real, deliberate UX regression from the original Goal's promise: after restoring a cached candidate, the R:R-vs-structural-stop cell now shows the defensive `'—'` placeholder (not `'No structural stop found'` — the actual structural stop, when one was cached, still restores and displays correctly in the Exit Plan section; only the DERIVED combination is withheld) until the user's next Estimate click recomputes both sides together — one click, not a re-navigation, and the same cost every fresh (non-cached) candidate already paid before this whole caching feature existed. The raw Profit Targets estimate itself — targets, probabilities, option prices, the T1/T2/T3 % inputs — is completely unaffected and still restores instantly from cache with no refetch, which was the user's original ask. Updated the round-1 regression test's final assertions to match (was: `0.2×` appears immediately on restore; now: `'—'` appears, `0.2×` does not, the restored structural stop level itself still renders in the Exit Plan section, and the raw estimate/targets/% inputs are unaffected).
- **Post-implementation independent audit (2026-08-22, round 6 — confirming pass on round 5's simplification) — no functional defects; six stale comments and two pre-existing (not introduced by this work) design notes flagged.** A sixth fresh reviewer wrote round 5's exact two-navigation repro as a real test, confirmed it passes at HEAD, then reapplied a faithful revert of the round-5 gate and confirmed the test (and the round-1 test) fails — the fix is genuinely load-bearing. Traced every path that sets either `isFreshRef` and found no stuck-`false` regression (a fresh mount → one Estimate click still renders a real ratio); confirmed the raw cache restore (targets, `$3.30`, T1=10, zero refetch) is completely unaffected by the simplification; confirmed the label chain correctly renders `'—'`, not `'No structural stop found'`, in the post-restore state. Findings, all LOW/NIT, none functional: (1) six comments across `page.tsx`, `TradeCard/index.tsx`, `types/domain.ts` and the test file still described the deleted `pairRestoredTogetherRef` mechanism or claimed `'—'` is an unreachable defensive catch-all — corrected in place; (2) `structuralBySymbol[symbol]?.stop?.price`, which feeds `alert_generator.py`'s stop-breach alerting, still ships with no freshness check even though the UI now refuses to *display* an R:R computed from that same value without one — pre-existing, but this round's stricter display-side invariant makes the asymmetry more visible; left as-is (fixing it means deciding a genuinely new freshness/TTL policy for the order-send path, a separate design question, not a defect in what this plan built); (3) no test pins the "one Estimate click recovers" claim specifically, though it was verified by hand; (4) `structuralStopStockPrice` is dead data once restored (nothing reads a restored value — only a live fetch's own value is ever used) — comment corrected to say so rather than invent a consumer; (5) an out-of-diff adjacent finding, `backend/app/routers/portfolio.py`'s `structuralStop` reanchoring, noted for awareness, not acted on here (out of this plan's scope). Comments and this plan doc's own round ordering fixed; no code changes required.
