# TradeCard R:R Fix & Profit Targets Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix a risk-basis bug in two client-side R:R calculations on the Options-mode Trade Card, then redesign the "Profit Targets" (Monte Carlo) section to span full card width, show probability/duration as their own columns, and always include the R:R-vs-structural-stop figure once an estimate has been run — without changing when the underlying network fetches fire (still click-gated, never auto-fired on candidate navigation).

**Architecture:** All changes are confined to `frontend/components/organisms/TradeCard/index.tsx`, its CSS module, and its test file. No backend changes — the backend already returns every field this plan uses (`optionPrice`, `probability`, `expectedDays` on `FirstPassageTarget`; `premiumStop` on `TradeCardData.exit`). Two pure-function fixes (Task 1, Task 2), one fetch-orchestration change extracted into a shared helper (Task 4), one CSS + JSX redesign (Task 5, Task 6), and the corresponding test updates (Task 3, Task 7).

**Tech Stack:** Next.js 15 / React (client component), TypeScript, CSS Modules, Jest + Testing Library.

---

## Background (read this before touching code)

Two *different* client-side "R:R" numbers exist on this card today, and this plan only touches specific ones:

1. **Main "Risk / Reward" badge** (bottom of card, `editedRR.rr`) — when the card is unedited, this is a straight pass-through of the backend's `data.rrRatio`/`data.rrModel` (genuinely Heston-priced when calibration succeeded). **Not touched by this plan.**
2. **`computeEditedRR()`** (`index.tsx:67-95`) — recomputes the *same* badge's number client-side once the user edits any field (entry limit, targets, contracts, etc.). Currently uses `risk = overlay.entryLimit` (the full premium) as the R:R denominator. **Bug: should use the premium-stop dollar risk, matching the backend's own definition.** Fixed in Task 2.
3. **`rrContribution()`** (`index.tsx:115-129`) — the per-target "R:R" shown on each Sell-to-Close Plan row (`EditableTargetRow`). Currently uses `risk = entryLimit` (full premium) too. Same bug. Fixed in Task 1.
4. **`structuralRR`** (`index.tsx:291-311`) — the "R:R vs. structural stop" figures. This is a genuinely *different*, already-correct metric: it estimates dollar risk as `min(|structuralStopPrice - currentStockPrice| * deltaEstimate, premiumPaid)` — a delta-approximated dollar loss if the stock actually hits the structural support level, capped at what you could ever lose. **Do not touch this formula** — only its *rendering location* changes (Task 6), from a separate block below the Estimate button into a column on each Profit Targets row.

The confusion the user hit was that (2) and (3) look like "the same kind of number as the real R:R" but use the wrong denominator (full premium instead of premium × stop%). Fixing the denominator to `premiumStop` (already computed and displayed elsewhere on the card as "Premium stop $X.XX") makes them consistent with the backend's own `estimate_rr()`/`estimate_targets()` in `backend/app/scoring/reward_risk.py`, so no label rename is needed — they'll actually mean what "R:R" implies once fixed.

---

## File Structure

No new files. Modified://
- `frontend/components/organisms/TradeCard/index.tsx` — two formula fixes, one new shared fetch helper, one new presentational component (`ProfitTargetRow`), restructured Profit Targets section JSX.
- `frontend/components/organisms/TradeCard/TradeCard.module.css` — no edits to this file. Listed here only because Task 5 reuses its existing `.fullWidth` class (`.module.css:37-39`) on the Profit Targets section's `className` in the TSX — no new CSS rules are added.
- `frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx` — updated expected values (Task 3) and updated/replaced DOM queries (Task 7) to match the new formula outputs and new markup.

---

### Task 1: Fix the Sell-to-Close per-target R:R risk basis

**Files:**
- Modify: `frontend/components/organisms/TradeCard/index.tsx:115-129` (`rrContribution` function)
- Modify: `frontend/components/organisms/TradeCard/index.tsx:823-839` (`EditableTargetRow` props)
- Modify: `frontend/components/organisms/TradeCard/index.tsx:867-871` (where `rrContribution` is called)
- Modify: `frontend/components/organisms/TradeCard/index.tsx:706-719` (where `<EditableTargetRow>` is rendered, to pass the new prop)

- [ ] **Step 1: Rewrite `rrContribution()` to take an explicit risk basis instead of reusing entry price as risk**

Replace lines 115-129:

```typescript
function rrContribution(
  targetStockPrice: number,
  estOptionPrice: number,
  entryLimit: number,
): number {
  // Mirrors the backend's reward_risk.py M2 fix: a negative reward's sign/
  // magnitude is preserved, not flattened to 0 — a target priced below entry
  // is a real loss the trader should see, not an indistinguishable "no data".
  // Only risk<=0 (a degenerate/missing entry price) is genuinely not
  // computable.
  const risk = entryLimit;
  const reward = estOptionPrice - risk;
  if (risk <= 0) return 0;
  return Math.round((reward / risk) * 10) / 10;
}
```

with:

```typescript
function rrContribution(
  estOptionPrice: number,
  entryLimit: number,
  riskBasis: number,
): number {
  // Risk basis is the planned dollar stop (entryLimit * premium_stop_pct,
  // already computed backend-side and surfaced as overlay.premiumStop) —
  // NOT the full entry price. Matches the backend's own reward_risk.py
  // estimate_targets(): risk_basis = current_premium * premium_stop_pct.
  // Mirrors the backend's reward_risk.py M2 fix: a negative reward's sign/
  // magnitude is preserved, not flattened to 0 — a target priced below entry
  // is a real loss the trader should see, not an indistinguishable "no data".
  // Guards both operands (not just riskBasis) for symmetry with
  // computeEditedRR's equivalent guard, even though today's UI already
  // clamps entryLimit to a positive minimum before it can reach here.
  if (riskBasis <= 0 || entryLimit <= 0) return 0;
  const reward = estOptionPrice - entryLimit;
  return Math.round((reward / riskBasis) * 10) / 10;
}
```

Note the parameter order changed (dropped the unused `targetStockPrice` parameter — it was never read in the function body) and a `riskBasis` parameter was added. `estOptionPrice - entryLimit` is unchanged (reward is still "what you'd get back minus what you paid") — only the divisor changes.

- [ ] **Step 2: Add `premiumStop` to `EditableTargetRow`'s props**

Replace lines 823-839:

```typescript
function EditableTargetRow({
  target,
  index,
  editedStockPrice,
  entryLimit,
  data,
  onStockPriceChange,
  totalContracts,
}: {
  target: TargetLevel;
  index: number;
  editedStockPrice: number;
  entryLimit: number;
  data: TradeCardData;
  onStockPriceChange: (v: number) => void;
  totalContracts: number;
}) {
```

with:

```typescript
function EditableTargetRow({
  target,
  index,
  editedStockPrice,
  entryLimit,
  premiumStop,
  data,
  onStockPriceChange,
  totalContracts,
}: {
  target: TargetLevel;
  index: number;
  editedStockPrice: number;
  entryLimit: number;
  premiumStop: number;
  data: TradeCardData;
  onStockPriceChange: (v: number) => void;
  totalContracts: number;
}) {
```

- [ ] **Step 3: Update the `rrContribution()` call site inside `EditableTargetRow`**

Replace (around line 871):

```typescript
  const rr = rrContribution(editedStockPrice, estOptionPrice, entryLimit);
```

with:

```typescript
  const rr = rrContribution(estOptionPrice, entryLimit, premiumStop);
```

- [ ] **Step 4: Pass `premiumStop` at the `<EditableTargetRow>` render call site**

Find the render call (around lines 706-719, inside the "Sell-to-close plan" section):

```typescript
              <EditableTargetRow
                key={t.id ?? i}
                target={t}
                index={i}
                editedStockPrice={overlay.targets[i] ?? t.targetPrice ?? t.stockPrice}
                entryLimit={overlay.entryLimit}
                data={data}
                onStockPriceChange={(v) => {
                  const next = [...overlay.targets];
                  next[i] = v;
                  patch({ targets: next });
                }}
                totalContracts={overlay.contracts}
              />
```

Add `premiumStop={overlay.premiumStop}` right after `entryLimit={overlay.entryLimit}`:

```typescript
              <EditableTargetRow
                key={t.id ?? i}
                target={t}
                index={i}
                editedStockPrice={overlay.targets[i] ?? t.targetPrice ?? t.stockPrice}
                entryLimit={overlay.entryLimit}
                premiumStop={overlay.premiumStop}
                data={data}
                onStockPriceChange={(v) => {
                  const next = [...overlay.targets];
                  next[i] = v;
                  patch({ targets: next });
                }}
                totalContracts={overlay.contracts}
              />
```

`overlay.premiumStop` already exists in `EditOverlay` (`index.tsx:35`) and is already editable via the Exit Plan's "Premium stop" field — this reuses it, no new state.

- [ ] **Step 5: Update the R:R cell's render gate to also check `premiumStop`, matching `rrContribution`'s own guard**

Inside `EditableTargetRow` (around `index.tsx:928`), the R:R `KV` is currently gated on `estOptionPrice > 0 && entryLimit > 0` — a leftover from when `entryLimit` was also the risk denominator. Now that the denominator is `premiumStop`, this gate should check that too, so the cell can't render a value `rrContribution` would itself have guarded against (`riskBasis <= 0`).

Find:

```typescript
          {estOptionPrice > 0 && entryLimit > 0 && (
            <KV label="R:R" value={`${rr.toFixed(1)}x`} mono tone={rr < 0 ? 'reject' : undefined} />
          )}
```

Replace with:

```typescript
          {estOptionPrice > 0 && entryLimit > 0 && premiumStop > 0 && (
            <KV label="R:R" value={`${rr.toFixed(1)}x`} mono tone={rr < 0 ? 'reject' : undefined} />
          )}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/TradeCard/index.tsx
git commit -m "fix(trade-card): use premium-stop risk basis for per-target R:R"
```

---

### Task 2: Fix the edited/"dirty" main R:R badge risk basis

**Files:**
- Modify: `frontend/components/organisms/TradeCard/index.tsx:67-95` (`computeEditedRR`)

- [ ] **Step 1: Split "entry price used for the delta-approx price extrapolation" from "risk basis used for the R:R denominator"**

Replace lines 67-95:

```typescript
function computeEditedRR(
  overlay: EditOverlay,
  data: TradeCardData,
): { rr: number; model: string } {
  const risk = overlay.entryLimit;
  if (risk <= 0) return { rr: 0, model: 'Edit (delta approx)' };
  if (overlay.targets.length === 0) return { rr: data.rrRatio, model: data.rrModel };

  const cd = data.contractDetails;
  if (!cd) return { rr: data.rrRatio, model: data.rrModel };

  const isCall = cd.right === 'C';
  const strike = cd.strike;
  const currentStockPrice = data.price;
  const targetStockPrice = overlay.targets[0];
  const delta =
    (isCall && targetStockPrice > strike) || (!isCall && targetStockPrice < strike)
      ? 0.5
      : 0.3;
  const priceMove = Math.abs(targetStockPrice - currentStockPrice);
  const estOptionPrice = Math.max(0.01, risk + delta * priceMove);
  const reward = estOptionPrice - risk;
  // Mirrors the backend's reward_risk.py M2 fix: a negative reward's sign/
  // magnitude is preserved, not flattened to 0 (risk<=0 above is the only
  // genuinely not-computable case).
  const rr = Math.round((reward / risk) * 100) / 100;

  return { rr, model: 'Edit (delta approx)' };
}
```

with:

```typescript
function computeEditedRR(
  overlay: EditOverlay,
  data: TradeCardData,
): { rr: number; model: string } {
  const entryPrice = overlay.entryLimit;
  const riskBasis = overlay.premiumStop;
  if (entryPrice <= 0 || riskBasis <= 0) return { rr: 0, model: 'Edit (delta approx)' };
  if (overlay.targets.length === 0) return { rr: data.rrRatio, model: data.rrModel };

  const cd = data.contractDetails;
  if (!cd) return { rr: data.rrRatio, model: data.rrModel };

  const isCall = cd.right === 'C';
  const strike = cd.strike;
  const currentStockPrice = data.price;
  const targetStockPrice = overlay.targets[0];
  const delta =
    (isCall && targetStockPrice > strike) || (!isCall && targetStockPrice < strike)
      ? 0.5
      : 0.3;
  const priceMove = Math.abs(targetStockPrice - currentStockPrice);
  const estOptionPrice = Math.max(0.01, entryPrice + delta * priceMove);
  const reward = estOptionPrice - entryPrice;
  // Risk basis is the planned dollar stop (premiumStop), not the full entry
  // price — matches the backend's estimate_rr(): risk = current_premium *
  // premium_stop_pct. Mirrors the backend's reward_risk.py M2 fix: a
  // negative reward's sign/magnitude is preserved, not flattened to 0
  // (entryPrice<=0 or riskBasis<=0 above are the only genuinely
  // not-computable cases).
  const rr = Math.round((reward / riskBasis) * 100) / 100;

  return { rr, model: 'Edit (delta approx)' };
}
```

`entryPrice` still anchors the delta-approximation's option-price extrapolation (unchanged behavior — you extrapolate off what you actually paid), only the R:R *denominator* changes to `riskBasis` (`overlay.premiumStop`).

- [ ] **Step 2: Commit**

```bash
git add frontend/components/organisms/TradeCard/index.tsx
git commit -m "fix(trade-card): use premium-stop risk basis for edited R:R badge recompute"
```

---

### Task 3: Update existing tests for the Task 1 / Task 2 formula change

**Files:**
- Modify: `frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx`

The fixture `mockTradeCard` (lines 40-92) has `entry.limit = 2.5` and `exit.premiumStop = 1.5`. Two existing tests assert numbers computed with the *old* `risk = entryLimit` formula and must be updated to the *new* `risk = premiumStop` formula.

- [ ] **Step 1: Fix the M2-parity test's expected value**

The test at lines 95-111 uses `estimatedOptionPrice: 1.0` against `entry.limit: 2.5`. Old formula: `reward = 1.0 - 2.5 = -1.5`, `rr = -1.5 / 2.5 = -0.6`. New formula: `reward = 1.0 - 2.5 = -1.5`, `rr = -1.5 / 1.5 (premiumStop) = -1.0`.

Replace:

```typescript
  it('shows a negative per-target R:R instead of hiding the row (M2 parity)', () => {
    // Mirrors the backend's reward_risk.py M2 fix: a target priced below
    // entry (estimatedOptionPrice=1.0 < entry.limit=2.5, reward=-1.5,
    // rr=-1.5/2.5=-0.6) is a real loss the trader should see, not silently
    // omitted the way `rr > 0`-gated rendering used to.
    const dataWithLosingTarget: TradeCardData = {
      ...mockTradeCard,
      exit: {
        ...mockTradeCard.exit,
        targets: [
          { id: 'tp1', stockPrice: 195.0, targetPrice: 195.0, estimatedOptionPrice: 1.0, contractsToSell: 1, status: 'PENDING', rrContribution: -0.6 },
        ],
      },
    };
    render(<TradeCard data={dataWithLosingTarget} />);
    expect(screen.getByText('-0.6x')).toBeInTheDocument();
  });
```

with:

```typescript
  it('shows a negative per-target R:R instead of hiding the row (M2 parity)', () => {
    // Mirrors the backend's reward_risk.py M2 fix: a target priced below
    // entry (estimatedOptionPrice=1.0 < entry.limit=2.5, reward=-1.5,
    // rr=-1.5/premiumStop(1.5)=-1.0) is a real loss the trader should see,
    // not silently omitted the way `rr > 0`-gated rendering used to.
    const dataWithLosingTarget: TradeCardData = {
      ...mockTradeCard,
      exit: {
        ...mockTradeCard.exit,
        targets: [
          { id: 'tp1', stockPrice: 195.0, targetPrice: 195.0, estimatedOptionPrice: 1.0, contractsToSell: 1, status: 'PENDING', rrContribution: -1.0 },
        ],
      },
    };
    render(<TradeCard data={dataWithLosingTarget} />);
    expect(screen.getByText('-1.0x')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Fix the "does not affect the original R:R card or the sell-to-close R:R column" test's expected value**

This test (lines 538-567) uses `mockTradeCard`'s default target (`estimatedOptionPrice: 5.0`, `entry.limit: 2.5`, `exit.premiumStop: 1.5`). Old formula: `reward = 5.0 - 2.5 = 2.5`, `rr = 2.5 / 2.5 = 1.0`. New formula: `reward = 2.5`, `rr = 2.5 / 1.5 = 1.666... → rounds to 1.7`.

Replace the last two lines of that test:

```typescript
    // The top Risk/Reward card (fixed ladder) is untouched.
    expect(screen.getByText('2.5×')).toBeInTheDocument();
    // The Sell-to-Close-Plan's own per-target R:R (rrContribution: 1.0 in the fixture) is untouched.
    expect(screen.getByText('1.0x')).toBeInTheDocument();
  });
```

with:

```typescript
    // The top Risk/Reward card (fixed ladder) is untouched.
    expect(screen.getByText('2.5×')).toBeInTheDocument();
    // The Sell-to-Close-Plan's own per-target R:R now uses premiumStop (1.5)
    // as its risk basis: reward=5.0-2.5=2.5, rr=2.5/1.5=1.666...→1.7.
    expect(screen.getByText('1.7x')).toBeInTheDocument();
  });
```

Also update the test's own title/rename is not required (the test still verifies the top badge and the sell-to-close column are two independent numbers) — leave the `it(...)` title as-is.

- [ ] **Step 3: Run the affected tests to confirm the new expected values**

Run: `cd frontend && npm run test -- --testPathPattern=TradeCard -t "M2 parity|does not affect the original"`
Expected: both tests PASS with the new values. (They will still fail at this point if Task 1/Task 2 haven't been implemented yet — this step is here for after Tasks 1-2 land; if executing tasks in order, Task 1 and 2 must be done first.)

- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx
git commit -m "test(trade-card): update R:R expectations for premium-stop risk basis fix"
```

---

### Task 4: Auto-trigger the structural-stop fetch from Estimate, reusing its already-fetched stock quote

**Files:**
- Modify: `frontend/components/organisms/TradeCard/index.tsx` (add a small module-level pure function; modify `checkStructure` at lines 313-348 to use it; modify `estimateFirstPassage` at lines 231-279 to also call it)
- Modify: `frontend/lib/api.ts` (two stale doc comments)

Today, "Check structure" (Exit Plan section) and "Estimate" (Profit Targets section) are two independently-clickable buttons, each fetching its own fresh stock quote. The user wants the Profit Targets card's structural-R:R column to always be populated once you've clicked "Estimate" — without requiring you to separately remember to click "Check structure" first, and without turning either fetch into something that auto-fires on candidate navigation (both remain click-gated).

The approach: `estimateFirstPassage` already fetches a fresh stock quote for its own use (`stockQuote?.price ?? data.price`). Reuse that exact same price for the structural-stop call instead of firing an independent `api.getStockQuote` — this means clicking "Estimate" adds **exactly one** extra network call (`getStructuralStop`), not two, and there's no second competing `getStockQuote` call that could race with (or, in tests, consume the mock queued for) the first-passage fetch's own quote. Only the tiny response-shape-normalization logic is shared between `checkStructure` and `estimateFirstPassage`, as a pure function — no fetch sequence is shared, so each keeps its own abort-check placement exactly as today.

- [ ] **Step 1: Add a small pure normalization helper above the component**

Add this function near the top of the file, after the existing helper functions (`isDirty`, `computeEditedRR`, `recomputeTargetEstOption`, `rrContribution` — i.e. after line 129's closing brace, before `interface TradeCardProps` at line 131):

```typescript
function normalizeStructuralStopResponse(res: {
  available: boolean;
  price: number | null;
  source: 'order_block' | 'swing_low' | 'swing_high' | null;
  confidence: number | null;
  distancePct: number | null;
}): StructuralStop | null {
  return res.available && res.price != null && res.source != null
    && res.confidence != null && res.distancePct != null
    ? { price: res.price, source: res.source, confidence: res.confidence, distancePct: res.distancePct }
    : null;
}
```

This is a verbatim extraction of only the response-mapping expression already inside `checkStructure` (current lines ~335-339) — no behavior change, just named and made callable from two places. `StructuralStop` is already imported (`index.tsx:16`).

- [ ] **Step 2: Use the helper inside `checkStructure` — everything else in this function is untouched**

Replace lines 313-348:

```typescript
  const checkStructure = useCallback(async () => {
    structuralRequestRef.current?.abort();
    const controller = new AbortController();
    structuralRequestRef.current = controller;
    setStructuralLoading(true);
    setStructuralError(false);
    setStructuralStop(undefined);
    setStructuralStopStockPrice(null);
    try {
      // Fetch a fresh stock price rather than reusing data.price (a scan-time
      // snapshot that may be stale, especially for a contract the user never
      // overrode in Step 6, which has nothing else refreshing it). Falls back
      // to data.price only if the live quote fetch itself fails.
      const stockQuote = await api.getStockQuote(data.symbol, controller.signal).catch(() => null);
      if (controller.signal.aborted) return;
      const referenceStockPrice = stockQuote?.price ?? data.price;
      const res = await api.getStructuralStop({
        symbol: data.symbol,
        direction: data.direction,
        stock_price: referenceStockPrice,
      }, controller.signal);
      if (controller.signal.aborted) return;
      setStructuralStop(
        res.available && res.price != null && res.source != null
          && res.confidence != null && res.distancePct != null
          ? { price: res.price, source: res.source, confidence: res.confidence, distancePct: res.distancePct }
          : null,
      );
      setStructuralStopStockPrice(referenceStockPrice);
    } catch {
      if (controller.signal.aborted) return;
      setStructuralError(true);
    } finally {
      if (!controller.signal.aborted) setStructuralLoading(false);
    }
  }, [data.symbol, data.direction, data.price]);
```

with:

```typescript
  const checkStructure = useCallback(async () => {
    structuralRequestRef.current?.abort();
    const controller = new AbortController();
    structuralRequestRef.current = controller;
    setStructuralLoading(true);
    setStructuralError(false);
    setStructuralStop(undefined);
    setStructuralStopStockPrice(null);
    try {
      // Fetch a fresh stock price rather than reusing data.price (a scan-time
      // snapshot that may be stale, especially for a contract the user never
      // overrode in Step 6, which has nothing else refreshing it). Falls back
      // to data.price only if the live quote fetch itself fails.
      const stockQuote = await api.getStockQuote(data.symbol, controller.signal).catch(() => null);
      if (controller.signal.aborted) return;
      const referenceStockPrice = stockQuote?.price ?? data.price;
      const res = await api.getStructuralStop({
        symbol: data.symbol,
        direction: data.direction,
        stock_price: referenceStockPrice,
      }, controller.signal);
      if (controller.signal.aborted) return;
      setStructuralStop(normalizeStructuralStopResponse(res));
      setStructuralStopStockPrice(referenceStockPrice);
    } catch {
      if (controller.signal.aborted) return;
      setStructuralError(true);
    } finally {
      if (!controller.signal.aborted) setStructuralLoading(false);
    }
  }, [data.symbol, data.direction, data.price]);
```

(Both `if (controller.signal.aborted) return;` checks are preserved exactly where they were — this is now a genuinely faithful, minimal refactor.)

- [ ] **Step 3: Make `estimateFirstPassage` also populate structural stop if not already available, reusing its own fresh stock quote**

Replace the body of `estimateFirstPassage` (lines 231-279):

```typescript
  const estimateFirstPassage = useCallback(async () => {
    firstPassageRequestRef.current?.abort();
    const controller = new AbortController();
    firstPassageRequestRef.current = controller;
    setFirstPassageLoading(true);
    setFirstPassageError(false);
    setFirstPassage(undefined);
    setFirstPassageContext(null);
    try {
      const cd = data.contractDetails;
      if (!cd) throw new Error('no contract selected');
      // Fetch fresh stock + contract quotes rather than reusing data.price /
      // data.contractDetails (scan-time snapshots) — same reasoning as
      // checkStructure above, and the same fix applied to the pre-existing
      // recompute-plan flow in step-7-trade-card/page.tsx.
      const [stockQuote, contractQuote] = await Promise.all([
        api.getStockQuote(data.symbol, controller.signal).catch(() => null),
        api.getContractQuote(data.symbol, cd.strike, cd.expiry, cd.right, controller.signal).catch(() => null),
      ]);
      if (controller.signal.aborted) return;
      const premium = contractQuote?.price ?? cd.mid;
      const delta = contractQuote?.delta ?? cd.delta;
      const res = await api.getFirstPassageEstimate({
        symbol: data.symbol,
        direction: data.direction,
        stock_price: stockQuote?.price ?? data.price,
        strike: cd.strike,
        dte: cd.dte,
        premium,
        delta,
        trend_score: data.stockBreakdown.trend,
        invalidation_price: data.exit.invalidation,
        t1_pct: targetPct.t1,
        t2_pct: targetPct.t2,
        t3_pct: targetPct.t3,
      }, controller.signal);
      if (controller.signal.aborted) return;
      setFirstPassage({ targets: res.targets, invalidation: res.invalidation });
      // optionPrice in each target is premium*(1+pct) built from THIS
      // premium (first_passage.py) — persist it so a later R:R calc
      // subtracts the matching baseline, not data.contractDetails.mid.
      setFirstPassageContext({ premium, delta });
    } catch {
      if (controller.signal.aborted) return;
      setFirstPassageError(true);
    } finally {
      if (!controller.signal.aborted) setFirstPassageLoading(false);
    }
  }, [data.symbol, data.direction, data.price, data.contractDetails, data.stockBreakdown.trend, data.exit.invalidation, targetPct]);
```

with (the added block is clearly marked below; note it sits **inside** the `try`, after the `!cd` guard and after `referenceStockPrice` is computed — not before the try block — so an early "no contract selected" throw can never leave `structuralLoading` stuck `true`):

```typescript
  const estimateFirstPassage = useCallback(async () => {
    firstPassageRequestRef.current?.abort();
    const controller = new AbortController();
    firstPassageRequestRef.current = controller;
    setFirstPassageLoading(true);
    setFirstPassageError(false);
    setFirstPassage(undefined);
    setFirstPassageContext(null);
    try {
      const cd = data.contractDetails;
      if (!cd) throw new Error('no contract selected');
      // Fetch fresh stock + contract quotes rather than reusing data.price /
      // data.contractDetails (scan-time snapshots) — same reasoning as
      // checkStructure above, and the same fix applied to the pre-existing
      // recompute-plan flow in step-7-trade-card/page.tsx.
      const [stockQuote, contractQuote] = await Promise.all([
        api.getStockQuote(data.symbol, controller.signal).catch(() => null),
        api.getContractQuote(data.symbol, cd.strike, cd.expiry, cd.right, controller.signal).catch(() => null),
      ]);
      if (controller.signal.aborted) return;
      const referenceStockPrice = stockQuote?.price ?? data.price;
      const premium = contractQuote?.price ?? cd.mid;
      const delta = contractQuote?.delta ?? cd.delta;

      // The Profit Targets card always shows R:R-vs-structural-stop alongside
      // the estimate now. If it hasn't already been fetched separately
      // (structuralStop is still the initial "never fetched" sentinel,
      // undefined), fetch it here too — reusing referenceStockPrice (just
      // obtained above) instead of an independent getStockQuote call, so
      // this adds exactly one extra network call, not two. Fired once per
      // Estimate click, not on every render/navigation — same click-gated
      // model as before, just triggered from one button instead of two.
      // Deliberately not awaited before continuing to the first-passage
      // fetch below — it manages its own loading/error state independently
      // via structuralRequestRef, same as a manual "Check structure" click
      // would, and that ref-swap means the existing contract-change cleanup
      // effect still aborts it correctly if the user navigates away.
      if (structuralStop === undefined && !structuralLoading) {
        structuralRequestRef.current?.abort();
        const structuralController = new AbortController();
        structuralRequestRef.current = structuralController;
        setStructuralLoading(true);
        setStructuralError(false);
        api.getStructuralStop({
          symbol: data.symbol,
          direction: data.direction,
          stock_price: referenceStockPrice,
        }, structuralController.signal)
          .then((res) => {
            if (structuralController.signal.aborted) return;
            setStructuralStop(normalizeStructuralStopResponse(res));
            setStructuralStopStockPrice(referenceStockPrice);
          })
          .catch(() => {
            if (structuralController.signal.aborted) return;
            setStructuralError(true);
          })
          .finally(() => {
            if (!structuralController.signal.aborted) setStructuralLoading(false);
          });
      }

      const res = await api.getFirstPassageEstimate({
        symbol: data.symbol,
        direction: data.direction,
        stock_price: referenceStockPrice,
        strike: cd.strike,
        dte: cd.dte,
        premium,
        delta,
        trend_score: data.stockBreakdown.trend,
        invalidation_price: data.exit.invalidation,
        t1_pct: targetPct.t1,
        t2_pct: targetPct.t2,
        t3_pct: targetPct.t3,
      }, controller.signal);
      if (controller.signal.aborted) return;
      setFirstPassage({ targets: res.targets, invalidation: res.invalidation });
      // optionPrice in each target is premium*(1+pct) built from THIS
      // premium (first_passage.py) — persist it so a later R:R calc
      // subtracts the matching baseline, not data.contractDetails.mid.
      setFirstPassageContext({ premium, delta });
    } catch {
      if (controller.signal.aborted) return;
      setFirstPassageError(true);
    } finally {
      if (!controller.signal.aborted) setFirstPassageLoading(false);
    }
  }, [data.symbol, data.direction, data.price, data.contractDetails, data.stockBreakdown.trend, data.exit.invalidation, targetPct, structuralStop, structuralLoading]);
```

Note `stock_price: stockQuote?.price ?? data.price` was renamed to the reusable local `referenceStockPrice` and is otherwise unchanged — the value passed to `getFirstPassageEstimate` is identical to before.

- [ ] **Step 4: Update the two now-stale doc comments in `frontend/lib/api.ts`**

`getStructuralStop`'s doc comment (around `api.ts:345-346`) currently states it is "fired only by the trade card's 'Check structure' button, never automatically." `getFirstPassageEstimate`'s doc comment (around `api.ts:359-360`) makes the equivalent claim for "Estimate." After this task, `getStructuralStop` can also fire from the "Estimate" button. Update `getStructuralStop`'s comment to say it is fired by either the trade card's "Check structure" button, or its "Estimate" button when a structural stop hasn't been fetched yet for the current candidate — never automatically on navigation. Leave `getFirstPassageEstimate`'s comment as-is (still accurate — only "Estimate" fires it).

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no new errors.

- [ ] **Step 6: Add a default `getStructuralStop` mock to the test file's `beforeEach`, so tests that only click "Estimate" (without configuring `getStructuralStop`) don't hit an unmocked `jest.fn()` returning `undefined`**

In `frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx`, replace the `beforeEach` block (lines 154-159):

```typescript
  beforeEach(() => {
    (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: mockTradeCard.price });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
  });
```

with:

```typescript
  beforeEach(() => {
    (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: mockTradeCard.price });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    // Default: no structural stop found. Estimate now auto-triggers this
    // fetch (Task 4) whenever it hasn't already been fetched, so every test
    // that clicks "Estimate" needs a resolvable mock even if it doesn't care
    // about structural-stop content. Individual tests override with their
    // own mockResolvedValueOnce for the structural-stop-specific assertions.
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: false, price: null, source: null, confidence: null, distancePct: null,
    });
  });
```

- [ ] **Step 7: Commit**

```bash
git add frontend/components/organisms/TradeCard/index.tsx frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx frontend/lib/api.ts
git commit -m "feat(trade-card): auto-include structural stop when Estimate is clicked"
```

---

### Task 5: Give the Profit Targets card full card width

**Files:**
- Modify: `frontend/components/organisms/TradeCard/index.tsx` (the Profit Targets `<section>` opening tag, currently around line 621)

- [ ] **Step 1: Add the existing `.fullWidth` utility class**

Find (around line 621):

```typescript
        {/* 5c. Profit-target first-passage estimate */}
        <section className={styles.planCard}>
```

Replace with:

```typescript
        {/* 5c. Profit-target first-passage estimate */}
        <section className={`${styles.planCard} ${styles.fullWidth}`}>
```

`.fullWidth` (`TradeCard.module.css:37-39`, `grid-column: 1 / -1`) already exists and is exactly what `.targetsCard` uses for the Sell-to-Close Plan section — no new CSS needed.

- [ ] **Step 2: Commit**

```bash
git add frontend/components/organisms/TradeCard/index.tsx
git commit -m "style(trade-card): make Profit Targets card full width"
```

---

### Task 6: Redesign the Profit Targets rows — add option-price/probability/duration columns and fold in the structural R:R

**Files:**
- Modify: `frontend/components/organisms/TradeCard/index.tsx` (add `FirstPassageTarget` to the type import at line 16; add a new `ProfitTargetRow` component; replace the Profit Targets section's results rendering, lines ~659-696; remove the now-obsolete separate `structuralRR` render block)

- [ ] **Step 1: Add `FirstPassageTarget` to the existing type import**

Find (line 16):

```typescript
import type { TradeCardData, TargetLevel, StructuralStop, FirstPassageEstimate } from '@/types/domain';
```

Replace with:

```typescript
import type { TradeCardData, TargetLevel, StructuralStop, FirstPassageEstimate, FirstPassageTarget } from '@/types/domain';
```

- [ ] **Step 2: Add the `ProfitTargetRow` component**

Add this new function near the other row-rendering components — directly after `KV`'s closing brace (`index.tsx:1095-1114`; `KV` is not the last thing in the file — `DetailCell` and the file's `export` statements follow it — "directly after `KV`'s closing brace" is what matters, not "at the end of the file"):

```typescript
function ProfitTargetRow({
  target,
  structuralRRValue,
  structuralPending,
  structuralUnavailable,
  structuralZeroRisk,
}: {
  target: FirstPassageTarget;
  structuralRRValue: number | null;
  structuralPending: boolean;
  structuralUnavailable: boolean;
  structuralZeroRisk: boolean;
}) {
  const label = `T${Math.round(target.pct * 100)}%`;
  // Order matters: a stop that resolved to exactly the current stock price
  // (structuralZeroRisk) is a completed check with an undefined ratio, not
  // "not yet checked" — it must be distinguished from the true not-yet-run
  // fallback ('—', which should be unreachable once every real state above
  // it is covered, kept only as a defensive catch-all).
  const structuralValue = structuralRRValue != null
    ? `${structuralRRValue.toFixed(1)}×`
    : structuralPending
      ? 'Checking…'
      : structuralUnavailable
        ? 'No structural stop found'
        : structuralZeroRisk
          ? 'N/A (stop = price)'
          : '—';

  return (
    <div className={styles.targetRow}>
      <div className={styles.targetMain}>
        <div className={styles.targetId}>
          <Text size={12} weight={600}>{label}</Text>
        </div>
        <div className={styles.targetValues}>
          <KV label="Est. option" value={`$${target.optionPrice.toFixed(2)}`} mono />
          <KV
            label="Stock price"
            value={target.stockPrice != null ? `$${target.stockPrice.toFixed(2)}` : 'not reachable'}
            mono
          />
          <KV label="Probability" value={`${(target.probability * 100).toFixed(0)}%`} mono />
          <KV
            label="Expected time"
            value={target.expectedDays != null ? `~${Math.round(target.expectedDays)}d` : 'unlikely'}
            mono
          />
          <KV label="R:R vs. structural stop" value={structuralValue} mono />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Replace the Profit Targets section's results rendering**

Find the full Profit Targets `<section>` block (approximately lines 621-698 after Task 5's class-name edit already applied):

```typescript
        <section className={`${styles.planCard} ${styles.fullWidth}`}>
          <Text size={14} weight={600}>Profit Targets</Text>
          <Text size={10} tone="dim">Monte Carlo estimate — independent of the Sell-to-Close Plan below; the two can disagree.</Text>
          <div className={styles.targetPctRow}>
            {(['t1', 't2', 't3'] as const).map((key) => (
              <label key={key} className={styles.targetPctInput}>
                <Text size={11} tone="secondary">{key.toUpperCase()}</Text>
                <input
                  type="number"
                  className={styles.editInput}
                  min={1}
                  max={500}
                  step={1}
                  aria-label={`${key.toUpperCase()} profit target %`}
                  value={Math.round(targetPct[key] * 100)}
                  onChange={(e) => {
                    const pct = Math.max(0.01, Math.min(5.0, Number(e.target.value) / 100));
                    setTargetPct((prev) => ({ ...prev, [key]: pct }));
                  }}
                />
                <Text size={11} tone="secondary">%</Text>
              </label>
            ))}
          </div>
          <div className={styles.structuralStop}>
            <button
              type="button"
              className={styles.btn}
              onClick={estimateFirstPassage}
              disabled={firstPassageLoading || !data.contractDetails}
            >
              <Text size={12} weight={500}>
                {firstPassageLoading ? 'Estimating…' : 'Estimate'}
              </Text>
            </button>
            {firstPassageError && (
              <Text size={11} tone="reject">Couldn&apos;t compute an estimate — try again.</Text>
            )}
            {firstPassage && (
              <dl className={styles.kvList}>
                {firstPassage.targets.map((t, i) => (
                  <KV
                    key={`${t.pct}-${i}`}
                    label={`T${Math.round(t.pct * 100)}% — probability of hitting before expiry`}
                    value={
                      t.stockPrice != null
                        ? `$${t.stockPrice.toFixed(2)} · ${(t.probability * 100).toFixed(0)}% · ${t.expectedDays != null ? `~${Math.round(t.expectedDays)}d` : 'unlikely'}`
                        : `not reachable in this timeframe · ${(t.probability * 100).toFixed(0)}%`
                    }
                    mono
                  />
                ))}
                <KV
                  label="Probability of hitting invalidation before expiry"
                  value={`${(firstPassage.invalidation.probability * 100).toFixed(0)}% · ${firstPassage.invalidation.expectedDays != null ? `~${Math.round(firstPassage.invalidation.expectedDays)}d` : 'unlikely'}`}
                  mono
                />
              </dl>
            )}
            {!structuralRR && (structuralStop || firstPassage) && (
              <Text size={11} tone="dim">
                Check structure and Estimate first to see R:R against the structural stop.
              </Text>
            )}
            {structuralRR && (
              <dl className={styles.kvList}>
                {structuralRR.map((r, i) => (
                  <KV
                    key={`${r.pct}-${i}`}
                    label={`T${Math.round(r.pct * 100)}% R:R vs. structural stop`}
                    value={r.rr != null ? `${r.rr.toFixed(1)}×` : '—'}
                    mono
                  />
                ))}
              </dl>
            )}
          </div>
        </section>
```

Replace with:

```typescript
        <section className={`${styles.planCard} ${styles.fullWidth}`}>
          <Text size={14} weight={600}>Profit Targets</Text>
          <Text size={10} tone="dim">Monte Carlo estimate — independent of the Sell-to-Close Plan below; the two can disagree.</Text>
          <div className={styles.targetPctRow}>
            {(['t1', 't2', 't3'] as const).map((key) => (
              <label key={key} className={styles.targetPctInput}>
                <Text size={11} tone="secondary">{key.toUpperCase()}</Text>
                <input
                  type="number"
                  className={styles.editInput}
                  min={1}
                  max={500}
                  step={1}
                  aria-label={`${key.toUpperCase()} profit target %`}
                  value={Math.round(targetPct[key] * 100)}
                  onChange={(e) => {
                    const pct = Math.max(0.01, Math.min(5.0, Number(e.target.value) / 100));
                    setTargetPct((prev) => ({ ...prev, [key]: pct }));
                  }}
                />
                <Text size={11} tone="secondary">%</Text>
              </label>
            ))}
          </div>
          <div className={styles.structuralStop}>
            <button
              type="button"
              className={styles.btn}
              onClick={estimateFirstPassage}
              disabled={firstPassageLoading || !data.contractDetails}
            >
              <Text size={12} weight={500}>
                {firstPassageLoading ? 'Estimating…' : 'Estimate'}
              </Text>
            </button>
            {firstPassageError && (
              <Text size={11} tone="reject">Couldn&apos;t compute an estimate — try again.</Text>
            )}
          </div>
          {firstPassage && (
            <div className={styles.targetsTable}>
              {firstPassage.targets.map((t, i) => (
                <ProfitTargetRow
                  key={`${t.pct}-${i}`}
                  target={t}
                  structuralRRValue={structuralRR?.find((r) => r.pct === t.pct)?.rr ?? null}
                  structuralPending={structuralLoading}
                  structuralUnavailable={structuralStop === null}
                  structuralZeroRisk={
                    structuralStop != null && structuralStopStockPrice != null
                    && firstPassageContext != null && structuralRR == null && !structuralLoading
                  }
                />
              ))}
              <div className={styles.targetRow}>
                <div className={styles.targetMain}>
                  <div className={styles.targetId}>
                    <Text size={12} weight={600}>Invalidation</Text>
                  </div>
                  <div className={styles.targetValues}>
                    <KV
                      label="Probability before expiry"
                      value={`${(firstPassage.invalidation.probability * 100).toFixed(0)}%`}
                      mono
                    />
                    <KV
                      label="Expected time"
                      value={firstPassage.invalidation.expectedDays != null ? `~${Math.round(firstPassage.invalidation.expectedDays)}d` : 'unlikely'}
                      mono
                    />
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>
```

This removes the old "Check structure and Estimate first..." hint entirely (no longer needed — a single Estimate click now populates both), removes the separate `structuralRR`-only `<dl>` block (folded into each `ProfitTargetRow`'s "R:R vs. structural stop" cell instead), and adds the two new columns (`Probability`, `Expected time`) plus the previously-unrendered `Est. option` column, split out of the old single concatenated KV value string.

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no new errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/TradeCard/index.tsx
git commit -m "feat(trade-card): redesign Profit Targets rows with option price, probability, and duration columns"
```

---

### Task 7: Update existing tests for the new Profit Targets markup

**Files:**
- Modify: `frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx`

The old markup rendered one concatenated string per target (e.g. `'$190.50 · 72% · ~5d'`) and a separate hint/list block for structural R:R gated behind two independent clicks. The new markup splits every value into its own cell and always shows the structural R:R cell (with a pending/not-found state) once `firstPassage` exists. The tests below need their queries updated to match.

- [ ] **Step 1: Update "fetches and displays the first-passage estimate on button click, using fresh quotes" (lines 265-309)**

Replace the assertions block:

```typescript
    await waitFor(() => {
      expect(screen.getByText(/T20% — probability of hitting before expiry/)).toBeInTheDocument();
    });
    expect(screen.getByText('$190.50 · 72% · ~5d')).toBeInTheDocument();
    expect(screen.getByText('$193.20 · 55% · ~9d')).toBeInTheDocument();
    expect(screen.getByText('not reachable in this timeframe · 10%')).toBeInTheDocument();
    expect(screen.getByText('30% · ~4d')).toBeInTheDocument();
    // Purely additive: the premium-based invalidation must be untouched.
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('$179.64');
```

with:

```typescript
    await waitFor(() => {
      expect(screen.getByText('T20%')).toBeInTheDocument();
    });
    expect(screen.getByText('$3.30')).toBeInTheDocument();     // T20% Est. option
    expect(screen.getByText('$190.50')).toBeInTheDocument();   // T20% Stock price
    expect(screen.getByText('72%')).toBeInTheDocument();       // T20% Probability
    expect(screen.getByText('~5d')).toBeInTheDocument();       // T20% Expected time
    expect(screen.getByText('$193.20')).toBeInTheDocument();   // T35% Stock price
    expect(screen.getByText('not reachable')).toBeInTheDocument(); // T50% Stock price (null)
    expect(screen.getByText('30%')).toBeInTheDocument();       // Invalidation probability
    expect(screen.getByText('~4d')).toBeInTheDocument();       // Invalidation expected time
    // Purely additive: the premium-based invalidation must be untouched.
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('$179.64');
```

- [ ] **Step 2: Replace "shows a hint instead of R:R vs structural stop until both checks have run" (lines 373-384)**

This test's premise (you must click both buttons separately, and see a hint in between) no longer holds — Estimate alone now populates both. Replace the entire test with one that verifies: clicking "Check structure" alone (without Estimate) shows the structural stop in the Exit Plan section but renders no Profit Targets rows at all (since no estimate has been run yet), and the old hint text no longer exists anywhere in the component.

Replace:

```typescript
  it('shows a hint instead of R:R vs structural stop until both checks have run', async () => {
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Check structure and Estimate first to see R:R/)).toBeInTheDocument();
    expect(screen.queryByText(/R:R vs\. structural stop/)).not.toBeInTheDocument();
  });
```

with:

```typescript
  it('shows no Profit Targets rows (and no stale two-click hint) until Estimate has been run', async () => {
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });
    // Check structure alone (no Estimate click yet) — no Profit Targets rows,
    // no leftover "click both" hint text (removed as part of this redesign).
    expect(screen.queryByText(/Check structure and Estimate first/)).not.toBeInTheDocument();
    expect(screen.queryByText(/R:R vs\. structural stop/)).not.toBeInTheDocument();
    expect(screen.queryByText('T20%')).not.toBeInTheDocument();
  });
```

- [ ] **Step 3: Update "computes R:R vs structural stop using the FRESH quotes, not the stale scan-time values" (lines 386-427)**

The label text search changes from the old `'T20% R:R vs. structural stop'` (one combined string) to plain `'R:R vs. structural stop'` (now a per-row KV label repeated for T20/T35/T50, so no longer unique — assert on the row instead). Replace:

```typescript
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => {
      expect(screen.getByText('T20% R:R vs. structural stop')).toBeInTheDocument();
    });

    // stockMove = |190 - 200| = 10; deltaEst = 0.5; risk = 5.0
    // T1: reward = 15.0 - 5.0 = 10.0 -> rr = 2.0
    // T2: reward = 18.0 - 5.0 = 13.0 -> rr = 2.6
    // T3: reward = 21.0 - 5.0 = 16.0 -> rr = 3.2
    expect(screen.getByText('2.0×')).toBeInTheDocument();
    expect(screen.getByText('2.6×')).toBeInTheDocument();
    expect(screen.getByText('3.2×')).toBeInTheDocument();
  });
```

with:

```typescript
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => {
      expect(screen.getAllByText('R:R vs. structural stop').length).toBe(3);
    });

    // stockMove = |190 - 200| = 10; deltaEst = 0.5; risk = 5.0
    // T1: reward = 15.0 - 5.0 = 10.0 -> rr = 2.0
    // T2: reward = 18.0 - 5.0 = 13.0 -> rr = 2.6
    // T3: reward = 21.0 - 5.0 = 16.0 -> rr = 3.2
    expect(screen.getByText('2.0×')).toBeInTheDocument();
    expect(screen.getByText('2.6×')).toBeInTheDocument();
    expect(screen.getByText('3.2×')).toBeInTheDocument();
  });
```

- [ ] **Step 4: Update the two other tests that search for `'T20% R:R vs. structural stop'`**

Both "shows a negative structural-stop R:R instead of '—' (M2 parity)" (lines 429-464) and "clamps structural-stop risk to the option premium..." (lines 466-504) contain:

```typescript
    await waitFor(() => {
      expect(screen.getByText('T20% R:R vs. structural stop')).toBeInTheDocument();
    });
```

Replace both occurrences with:

```typescript
    await waitFor(() => {
      expect(screen.getAllByText('R:R vs. structural stop').length).toBeGreaterThanOrEqual(1);
    });
```

(The clamp test passes 3 targets so this becomes exactly 3; the M2-parity test passes only 1 target so this becomes exactly 1 — `toBeGreaterThanOrEqual(1)` is correct for both without needing per-test-specific counts.)

- [ ] **Step 5: Update "shows — instead of dividing by zero when the structural stop equals the fresh stock price" (lines 506-536)**

Replace:

```typescript
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => {
      expect(screen.getByText(/T20% — probability of hitting before expiry/)).toBeInTheDocument();
    });

    expect(screen.queryByText(/R:R vs\. structural stop/)).not.toBeInTheDocument();
  });
```

with:

```typescript
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => {
      expect(screen.getByText('T20%')).toBeInTheDocument();
    });

    // structuralRR is null when stockMove is 0 (division guard in the
    // useMemo), but the structural stop WAS found and both checks HAVE
    // completed — ProfitTargetRow's structuralZeroRisk branch distinguishes
    // this from "not checked yet", so every row shows the explicit
    // "N/A (stop = price)" placeholder rather than an actual ratio. (Not
    // asserting a page-wide absence of "×" text here — the top Risk/Reward
    // badge legitimately renders its own unrelated ratio, e.g. "2.5×".)
    expect(screen.getAllByText('N/A (stop = price)').length).toBe(3);
  });
```

Note: this test's `it(...)` title still describes the old "— instead of dividing by zero" behavior; leave the title as-is since the underlying guard (division-by-zero protection in the `structuralRR` `useMemo`) is unchanged — only the placeholder text changed from `'—'` to the more specific `'N/A (stop = price)'` as part of Task 6's `structuralZeroRisk` handling. (Implementation note: an earlier draft of this step also asserted `expect(screen.queryByText(/×$/)).not.toBeInTheDocument()` — dropped because it's over-broad and fails against the unrelated top Risk/Reward badge, which legitimately renders its own ratio like "2.5×" on the same page; the positive `getAllByText('N/A (stop = price)')` assertion alone already proves the fix.)

- [ ] **Step 6: Update "does not affect the original R:R card or the sell-to-close R:R column" (lines 538-567) for the new structural-stop label text**

This test was already updated for the formula fix in Task 3 Step 2. It also contains the old label pattern:

```typescript
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => screen.getByText('T20% R:R vs. structural stop'));
```

Replace with:

```typescript
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => screen.getAllByText('R:R vs. structural stop'));
```

- [ ] **Step 7: Fix "does not apply a stale first-passage response after the contract changes" (lines 341-371) — its assertion targets label text that no longer exists**

This test's only assertion (`expect(screen.queryByText(/T20% — probability of hitting before expiry/)).not.toBeInTheDocument()`) checks for the OLD combined label text. Task 6 changes the label to plain `"T20%"` — the old regex can never match again regardless of whether the staleness guard still works, so left unmodified this test would silently stop testing anything (it would pass even if the staleness guard were deleted).

Replace:

```typescript
    expect(screen.queryByText(/T20% — probability of hitting before expiry/)).not.toBeInTheDocument();
  });
```

with:

```typescript
    expect(screen.queryByText('T20%')).not.toBeInTheDocument();
  });
```

`'T20%'` only appears as a `ProfitTargetRow` label once `firstPassage` is populated — the `targetPct` % input labels render as plain `'T1'`/`'T2'`/`'T3'` (no `%` suffix, no percentage value), so there's no collision with those.

- [ ] **Step 8: Run the full TradeCard test file**

Run: `cd frontend && npm run test -- --testPathPattern=TradeCard`
Expected: all tests PASS. If any test not explicitly covered above fails because of the markup change, fix that specific assertion the same way (split concatenated-string queries into per-field queries; scope repeated labels with `getAllByText`/`within`) — do not change production code to make a stale assertion pass without first confirming the new behavior is actually correct per this plan's intent.

- [ ] **Step 9: Commit**

```bash
git add frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx
git commit -m "test(trade-card): update Profit Targets tests for redesigned row markup"
```

---

### Task 8: Typecheck, full test suite, and manual verification

**Files:** none (verification only)

- [ ] **Step 1: Full frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean, no errors.

- [ ] **Step 2: Full frontend test suite**

Run: `cd frontend && npm run test`
Expected: all tests PASS (not just TradeCard — confirm no other suite imports/relies on `rrContribution`'s old 3-arg signature or the removed hint text). The auto-triggered structural-stop fetch inside `estimateFirstPassage` (Task 4) is deliberately fire-and-forget relative to the function's own `await` chain, so a console warning about a state update outside `act(...)` is possible on some test runs even when assertions pass — this repo's Jest config has no fail-on-console-error setup, so it won't fail the suite; if one appears and bothers you, it can be silenced by awaiting a `waitFor(() => {})` tick after clicking "Estimate" in the affected test(s), but that's optional polish, not a correctness requirement.

- [ ] **Step 3: Manual browser verification**

Start the dev server (`cd frontend && npm run dev`, default port 3001), navigate to the Options screener flow through to Step 7 (Trade Card) for any candidate with a contract selected, and verify:
- The "Profit Targets" card spans the full card width (same width as "Sell-to-Close Plan" below it), not half.
- Clicking "Estimate" (without first clicking "Check structure") populates rows showing Est. option / Stock price / Probability / Expected time / R:R vs. structural stop all at once — the last column should show either a real multiplier, "Checking…", or "No structural stop found", never blank.
- The Sell-to-Close Plan's per-target "R:R" and the bottom "Risk / Reward" badge (after editing any field, e.g. Limit) both changed as expected — take a screenshot of the redesigned card for the record.

- [ ] **Step 4: Final commit (if any manual-verification fixes were needed)**

```bash
git add -A
git commit -m "fix(trade-card): address issues found in manual verification"
```
(Skip this step entirely if Step 3 found nothing to fix.)

---

## Self-Review Notes (completed by the plan author, not a task for the implementer)

- **Spec coverage:** Item 1 (rename to avoid errors) → resolved via formula fix per user's chosen option, covered by Tasks 1-3 (no rename needed once correct). Item 2a (full width) → Task 5. Item 2b (probability + duration columns) → Task 6 (plus the previously-requested option-price column, folded in since it uses the same `firstPassage.targets[i]` data already being restructured). Item 2c (structural R:R always present) → Task 4 + Task 6. Item 3 (no auto-fetch-on-navigation) → explicitly preserved; Task 4's trigger is still inside the click handler, not an effect keyed on `data.contract`/`data.symbol`.
- **Placeholder scan:** no TBD/"handle it"/"similar to Task N" language; every step shows full before/after code.
- **Type consistency:** `rrContribution(estOptionPrice, entryLimit, riskBasis)` signature is used consistently at its one call site (Task 1 Step 3). `normalizeStructuralStopResponse`'s return shape (`StructuralStop | null`) matches both call sites' usage (Task 4 Steps 2 and 3 — `checkStructure` passes it straight to `setStructuralStop`; `estimateFirstPassage`'s `.then` does the same). `ProfitTargetRow`'s 5 props (`target`, `structuralRRValue`, `structuralPending`, `structuralUnavailable`, `structuralZeroRisk`) all match what's passed at its render call site (Task 6 Step 3).
- **Second-round audit fixes (2026-08-20):** a second adversarial pass caught one HIGH (a pre-existing test, "does not apply a stale first-passage response after the contract changes", asserted against label text Task 6 removes — now fixed in Task 7 Step 7) and one MEDIUM (`structuralZeroRisk`'s guard could false-positive if a future contract ever arrived with `data.exit.structuralStop`/`data.exit.firstPassage` pre-populated but `structuralStopStockPrice`/`firstPassageContext` still null post-reset — now requires both non-null in Task 6 Step 3's call site). Both are reflected in the task bodies above; this line records that the self-review already accounts for them.
