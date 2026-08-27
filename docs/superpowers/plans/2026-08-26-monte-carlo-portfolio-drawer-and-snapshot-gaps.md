# Portfolio EditDrawer Monte Carlo + Remaining Buy-Snapshot Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the last two real gaps in the stock Monte Carlo / buy-time-snapshot feature: (1) three stock buy paths still place a broker order without ever creating a local `PortfolioPosition`, so those positions carry no "why was this bought" record and nothing for a later Monte Carlo estimate to work from; (2) the Portfolio `EditDrawer` (open positions) has no Monte Carlo "Estimate" affordance at all, unlike `StockPositionCard` (pre-trade), which already has one.

**Architecture:** Reuses existing, already-shipped, already-audited machinery end to end — no new backend code, no new endpoints, no new `api.ts` functions. `stockCardSnapshotOf()`/`buildPaperStockPosition()`/`pristineLevels()` in `frontend/lib/paperTrade.ts` and `frontend/components/organisms/StockSendDialog/index.tsx` already do exactly what the three broken buy paths need — they're just not called there yet. `StockPositionCard`'s `onEstimate()` and its result-row JSX are the exact template for what the `EditDrawer` needs; this plan mirrors that pattern rather than inventing a new one. The one small, deliberate net-new addition is a `horizon` field on the stock buy-time snapshot (`stockCardSnapshotOf()` doesn't carry one today), because a Monte Carlo call on an already-open position has no live scan context to read it from the way `StockPositionCard` does.

**Tech Stack:** Next.js 15 / TypeScript strict, Zustand, Jest + Testing Library. No backend changes.

---

## Investigation summary — why this plan exists and what it does NOT rebuild

A much larger "Phase 3" plan was drafted and audited earlier in this session, then discarded mid-implementation: the first implementer subagent discovered that `origin/main` already ships a fully-built stock-native Monte Carlo estimator (`estimate_stock_first_passage()` in `backend/app/scoring/first_passage.py`, `POST /api/stocks/first-passage`, `api.getStockFirstPassage()`, and an "Estimate" button already wired into `StockPositionCard`) via a separate, already-merged initiative — [`docs/superpowers/plans/2026-08-22-stock-exit-targets-plan.md`](docs/superpowers/plans/2026-08-22-stock-exit-targets-plan.md), 5 audit rounds, merged as `e96ecb0`. That work is materially better than the discarded plan's reconstruction (real per-strategy `trend_score`, a `horizon_days` window sourced from `scoring_rules.yaml`'s existing confidence-backtest config, a full target ladder, and an explicit `modelCaveat` for mean-reversion strategies where the drift model is a poor fit). **None of that is rebuilt here.**

What was verified, by reading the real current code (not assumed), to still be genuinely missing:

1. **Three stock buy paths still never create a local `PortfolioPosition`.** The exit-targets plan explicitly scoped itself to "the four sites that mint a stock `PortfolioPosition`" (its own plan doc, §"The four sites") — `StockSendDialog`'s manual branch, `StockPositionCard`'s `onAddToPortfolio`, `step-4-stocks`'s after-scan auto-execute loop, and `ChartWorkspace`'s chart-click buy. It deliberately did not touch the **broker-order** paths, because those don't mint a position at all — they only call `api.postStockOrder(...)` and show an order ID:
   - `frontend/components/organisms/StockSendDialog/index.tsx`, the `else if (broker !== 'recommendation')` branch (lines 127-143) — confirmed unchanged, no `addPosition` call.
   - `frontend/components/organisms/StockPositionCard/index.tsx`'s own `submit()` (lines 308-329) — a DIFFERENT function from `onAddToPortfolio` (line ~425) in the SAME file. Confirmed unchanged, no `addPosition` call.
   - `frontend/app/(frame)/screener/step-7-position-card/page.tsx`'s `submit()` (lines 85-106) — confirmed unchanged, no `addPosition` call.

   A user who buys via any of these three paths ends up with a real (paper) broker fill and zero local record — no snapshot, no stop/targets, nothing for Task 2's Monte Carlo estimate to read.

2. **The Portfolio `EditDrawer` has no Monte Carlo wiring.** `frontend/app/(frame)/portfolio/page.tsx`'s `EditDrawer` (lines 461-534) — read in full, confirmed unchanged from before this session started: `Stop`, `Structural stop`, `TargetEditor`, `Contracts`, `Current price` fields, nothing calling `api.getStockFirstPassage`/`api.getFirstPassageEstimate`. `StockPositionCard` (pre-trade, scan results) has this; the open-positions page does not.

3. **The stock buy-time snapshot has no `horizon`.** `stockCardSnapshotOf()` (`frontend/lib/paperTrade.ts`) captures `stock_score`, `stock_status`, `strategy`, `backtest`, `confidence`, `confidence_text`, `sector_rs_pct`, `fundamentals`, and optionally `edited` — no horizon. `StockPositionCard`'s own `onEstimate()` gets away without storing it because it reads `useScanStore().context.horizon` live, at estimate time — which works there because the scan that produced the card is still the active one. An **open position** has no such guarantee: by the time a user opens its `EditDrawer`, the scan context could be showing a completely different symbol/horizon, or nothing at all. Task 1 adds `horizon` to the snapshot at buy time (the one genuinely new field this plan introduces) so Task 2's estimate call has a real answer instead of a guess.

4. **The option buy-time snapshot still has no `strike`.** `tradeCardSnapshotOf()` (`frontend/app/(frame)/screener/step-7-trade-card/page.tsx`, lines 60-71) — confirmed unchanged, no `strike` field. `PortfolioPosition` has no dedicated strike/right fields either (only a display label `contract: "AAPL 220C 05/16"` and a real `expiry`). The options side of this feature (`api.getFirstPassageEstimate`, unrelated to and untouched by the exit-targets merge) needs a numeric strike to call. Fixed the same way Task 3 (options) below does it — into the existing generic snapshot blob, no schema change.

---

## Task 1: Capture the buy-time snapshot on the 3 remaining broker-order paths

**Files:**
- Modify: `frontend/lib/paperTrade.ts`
- Modify: `frontend/components/organisms/StockSendDialog/index.tsx`
- Modify: `frontend/components/organisms/StockPositionCard/index.tsx`
- Modify: `frontend/app/(frame)/screener/step-7-position-card/page.tsx`
- Read only, NOT modified: `frontend/app/(frame)/screener/step-4-stocks/page.tsx` (Step 9 below confirms its auto-execute loop is deliberately left as-is)
- Test: `frontend/lib/paperTrade.test.ts` (pre-existing — see note below, NOT a new `__tests__/` file)
- Test: `frontend/components/organisms/StockSendDialog/__tests__/StockSendDialog.test.tsx`
- Test: `frontend/components/organisms/StockPositionCard/__tests__/StockPositionCard.submit.test.tsx` (new file)
- Test: `frontend/app/(frame)/screener/step-7-position-card/__tests__/page.test.tsx` (new file)

### Step 1: Add `horizon` to `stockCardSnapshotOf` — write the failing test first

`frontend/lib/paperTrade.test.ts` **already exists** (it tests `buildPaperStockPosition`, `stockPositionLevels`, and `invalidTargetRungs` from this same module, shipped by the earlier exit-targets plan) — add to it, do not create a second, differently-located file for the same module. Its current import line (line 1) is `import { buildPaperStockPosition, stockPositionLevels, invalidTargetRungs } from './paperTrade';` — add `stockCardSnapshotOf` to it:

```ts
import { buildPaperStockPosition, stockPositionLevels, invalidTargetRungs, stockCardSnapshotOf } from './paperTrade';
import type { PositionCardData } from '@/types/stockDomain';
```

Append a new `describe` block at the END of the file (after the existing `describe('invalidTargetRungs', ...)` block):

```ts
describe('stockCardSnapshotOf', () => {
  function makeCard(overrides: Partial<PositionCardData> = {}): PositionCardData {
    return {
      symbol: 'AAPL', company: 'Apple Inc.', price: 190, direction: 'Bullish',
      strategy: {
        strategy: 'pullback_ema', entry_price: 190, stop_price: 182,
        target_price: 205, rr_ratio: 1.9, atr: 3.2, detail: {},
      },
      backtest: {
        n_trades: 40, win_rate: 0.55, total_return_pct: 12, max_drawdown_pct: 8,
        expectancy: 0.4, sharpe: 1.1, confidence: 70, passes_gate: true, summary_text: 'ok',
      },
      stock_score: 78, stock_status: 'PASS', shares: 10, dollar_risk: 80, dollar_size: 1900,
      confidence: 70, confidence_text: 'Solid',
      ...overrides,
    };
  }

  it('includes the horizon label passed in', () => {
    const snap = stockCardSnapshotOf(makeCard(), 'Swing (5–15d)');
    expect(snap.horizon).toBe('Swing (5–15d)');
    expect(snap.stock_score).toBe(78);
  });

  it('still carries the edited overlay when one is passed', () => {
    const snap = stockCardSnapshotOf(makeCard(), 'Swing (5–15d)', {
      entry: 191, stop: 183, targets: [206, 212, 218], shares: 12,
    });
    expect(snap.edited).toEqual({ entry: 191, stop: 183, targets: [206, 212, 218], shares: 12 });
  });
});
```

Run: `cd frontend && npm run test -- --testPathPattern=paperTrade`
Expected: FAIL on the 2 new tests (`stockCardSnapshotOf` doesn't accept a `horizon` positional argument yet — the `edited` object lands in the `horizon` slot and the assertions on `snap.horizon`/`snap.edited` fail); the ~18 pre-existing tests in this file continue to PASS unaffected.

### Step 2: Implement — extend `stockCardSnapshotOf`'s signature

Modify `frontend/lib/paperTrade.ts` — `horizon` becomes the new 2nd positional parameter (before the existing optional `edited`), since a real horizon is available at every real call site (all read from `useScanStore().context.horizon`, same source `StockPositionCard`'s own `onEstimate()` already uses live) whereas `edited` is genuinely optional:

```ts
export function stockCardSnapshotOf(
  c: PositionCardData,
  horizon: string,
  edited?: { entry: number; stop: number; targets: number[]; shares: number },
): Record<string, unknown> {
  return {
    ...(edited ? { edited } : {}),
    horizon,
    stock_score: c.stock_score,
    stock_status: c.stock_status,
    strategy: c.strategy,
    backtest: c.backtest,
    confidence: c.confidence,
    confidence_text: c.confidence_text,
    sector_rs_pct: c.sector_rs_pct,
    fundamentals: c.fundamentals,
  };
}
```

Run: `cd frontend && npm run test -- --testPathPattern=paperTrade`
Expected: PASS (all tests in the file, pre-existing + the 2 new ones)

### Step 3: Update the 3 EXISTING `stockCardSnapshotOf` call sites for the new signature

These already work today and must keep working — this step is a mechanical signature update, not a behavior change beyond now also storing `horizon`.

Modify `frontend/components/organisms/StockSendDialog/index.tsx` — add a `useScanStore` import (it has none today):

```ts
import { useScanStore } from '@/lib/scanStore';
```

Add a hook read inside `StockSendDialog`, alongside its other store selectors (after `const tradierPaper = useSettingsStore((s) => s.tradierPaper);`, around line 62):

```ts
  const scanHorizon = useScanStore((s) => s.context?.horizon ?? 'Swing');
```

Update BOTH `stockCardSnapshotOf(c)` call sites (lines 122 and 148 — the manual branch and the auto-send-falls-back-to-recommendation branch) to:

```ts
            stockCardSnapshotOf(c, scanHorizon), pristineLevels(c),
```

Modify `frontend/components/organisms/StockPositionCard/index.tsx` — `useScanStore` and `scanHorizonLabel` are ALREADY present here (line 260: `const scanHorizonLabel = useScanStore((s) => s.context?.horizon ?? null);`, used by the existing `onEstimate()`). Reuse it — do not add a second selector. Update the ONE `stockCardSnapshotOf(card, { entry: ..., ... })` call site (inside `onAddToPortfolio`, around line 436) to insert the horizon argument:

```ts
          stockCardSnapshotOf(card, scanHorizonLabel ?? 'Swing', {
            entry: overlay.entry,
            stop: overlay.stop,
            targets: [overlay.t1, overlay.t2, overlay.t3],
            shares: overlay.shares,
          }),
```

Run: `cd frontend && npm run typecheck`
Expected: clean — this confirms no other call site was missed. If it isn't clean, `grep -rn "stockCardSnapshotOf(" frontend --include=*.tsx --include=*.ts` to find what else needs updating before continuing.

### Step 4: Fix the auto-send branch in `StockSendDialog` — write the failing tests first

Read `frontend/components/organisms/StockSendDialog/__tests__/StockSendDialog.test.tsx` in full first (both existing tests, `"only resubmits symbols that failed on the previous attempt"` and `"does not permanently disable Submit when one row is queued and another hard-failed"`) — Step 6 below modifies the first one, and both must keep passing.

Append at the END of the file's `describe` block (a sibling to the two existing `it()`s, not interspersed). **Click "IBKR Paper," not "Tradier Paper"** — the file's shared `beforeEach` (lines 41-49) only configures `useSettingsStore`'s `ibkrPaper`, never `tradierPaper` (`DEFAULT_TRADIER_PAPER` is `{ token: '', accountId: '' }`), so a "Tradier Paper" button click would be a no-op on a `disabled` button, `broker` state would stay `'recommendation'`, and the test would silently fall through to the UNRELATED "auto-send but broker = recommendation → fall back to paper" branch instead of the one this test exists to exercise:

```ts
  it('creates a local position with a snapshot after a successful auto-send broker order', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1', status: 'filled', broker: 'ibkr_paper' });
    const addPosition = jest.fn().mockResolvedValue({ status: 'ok' });
    usePortfolioStore.setState({ addPosition } as any);

    render(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByText(/Submit 1 order/));

    await waitFor(() => expect(addPosition).toHaveBeenCalled());
    const created = addPosition.mock.calls[0][0];
    expect(created.source).toBe('broker');
    expect(created.tradeCardSnapshot).toBeDefined();
    expect(created.tradeCardSnapshot.strategy.strategy).toBe('pullback_ema');
    expect(created.stop).toBe(95);
  });

  it('does NOT re-submit the broker order on retry when the order succeeded but local tracking failed', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-2', status: 'filled', broker: 'ibkr_paper' });
    const addPosition = jest.fn().mockResolvedValueOnce({ status: 'rejected', detail: 'exposure limit' });
    usePortfolioStore.setState({ addPosition } as any);

    render(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByText(/Submit 1 order/));
    await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(1));

    // A local-tracking failure must not put the symbol back in the retryable
    // error set — `errors`/`queued` are both still empty, only `warnings` is
    // set. The button reflects this: it relabels to "Placed — close to
    // continue" and becomes disabled (the same treatment `hasQueued` already
    // gets), so there is nothing left to click that could re-fire the broker
    // order — a stronger guarantee than relying solely on the retry-target
    // filter (`errors`-only) to make a stray click safe.
    const btn = await screen.findByRole('button', { name: /Placed — close to continue/ });
    expect(btn).toBeDisabled();
    expect(api.postStockOrder).toHaveBeenCalledTimes(1);

    // The failure must still be VISIBLE — silently swallowing it (computing
    // `warn` and never rendering it) would mean a real broker order succeeds
    // with zero local record and zero indication anything needs attention.
    expect(await screen.findByText(/not yet tracked in Portfolio/)).toBeInTheDocument();
  });
```

Run: `cd frontend && npm run test -- --testPathPattern=StockSendDialog`
Expected: FAIL — `addPosition` never called on the auto-send path (first new test); the second may pass vacuously today (no `warn`-relevant code exists yet) — re-check it after Step 5.

### Step 5: Implement the auto-send fix

**Design note on the retry-safety invariant:** `submit()` deliberately retries only `cards.filter(c => c.symbol in errors)` on a re-click, specifically to avoid double-placing a broker order (its own comment, lines 98-101). A broker order that already succeeded must never end up back in `errs` — if it did, a retry click would fire `api.postStockOrder` a second time for an order that already filled. So below, once `postStockOrder` resolves successfully, a failure to mirror it into the local portfolio (`addPosition`) is tracked in a separate, non-blocking `warn` bucket — never added to `errs`/`q`, which are what actually mark a symbol "not yet fully placed" for the retry logic and the "stay open" gate.

Add a `warnings` state near the other `useState` declarations (after `const [queued, setQueued] = useState<Record<string, string>>({});`, around line 55):

```ts
  const [warnings, setWarnings] = useState<Record<string, string>>({});
```

Add a `warn` local alongside the existing `errs`/`q` locals inside `submit()` (right after `const q: Record<string, string> = hasSubmittedOnce ? { ...queued } : {};`, around line 114):

```ts
    const warn: Record<string, string> = hasSubmittedOnce ? { ...warnings } : {};
```

Replace the `else if (broker !== 'recommendation')` branch (lines 127-143):

```ts
      } else if (broker !== 'recommendation') {
        // Auto-send → broker, then mirror the fill into the local portfolio
        // (same pattern as the manual branch just above) so this position
        // carries a tradeCardSnapshot and real stop/target too — without
        // this, a broker-executed stock position has no local record at all
        // and the Portfolio EditDrawer's Monte Carlo estimate has nothing to
        // work from.
        try {
          const res = await api.postStockOrder({
            broker,
            symbol: c.symbol,
            action: c.direction === 'Bullish' ? 'BUY' : 'SELL',
            effect: 'OPEN',
            quantity: r.shares,
            order_type: 'LMT',
            limit_price: c.strategy.entry_price,
            tif: 'DAY',
          });
          // The broker order has ALREADY succeeded at this point — a failure
          // below must never be written to `errs`/`q` (those drive the retry
          // set; retrying here would resubmit an already-filled order). It's
          // tracked in `warn` instead, purely informational.
          try {
            const addRes = await addPosition({
              ...buildPaperStockPosition(
                c.symbol, c.strategy.entry_price, r.shares, c.direction as Direction,
                stockCardSnapshotOf(c, scanHorizon), pristineLevels(c),
              ),
              source: 'broker',
              sourceLabel: `${broker} — Limit (ID: ${res.order_id})`,
              orderedAt: new Date().toISOString(),
            });
            if (addRes.status === 'rejected' || addRes.status === 'pending') {
              warn[c.symbol] = 'Order placed but not yet tracked in Portfolio — check there directly.';
            }
          } catch {
            warn[c.symbol] = 'Order placed but not yet tracked in Portfolio — check there directly.';
          }
        } catch (e) {
          errs[c.symbol] = String(e);
        }
      } else {
```

Update the end of `submit()` to persist `warn` (find `setSubmitting(false); setErrors(errs); setQueued(q);` and add a line):

```ts
    setSubmitting(false);
    setErrors(errs);
    setQueued(q);
    setWarnings(warn);
```

**The "stay open" gate MUST also include `warn`, or the warning is computed and never seen.** `submit()` calls `onSubmit(orders)` immediately after this gate when it's false, and the only real caller (`frontend/app/(frame)/screener/step-4-stocks/page.tsx`) unmounts the dialog in that same render pass. A `warn`-only symbol is never in `errors`/`queued`, so without this change the dialog closes immediately and the warning is never painted even once. Change the gate (`if (Object.keys(errs).length > 0 || Object.keys(q).length > 0) return;`) to:

```ts
    if (Object.keys(errs).length > 0 || Object.keys(q).length > 0 || Object.keys(warn).length > 0) return;
```

This does NOT reintroduce the double-order hazard: retry-target-selection (`hasSubmittedOnce ? cards.filter(c => c.symbol in errors) : cards`) still keys off `errors` alone, so a `warn`-only symbol is excluded from `targets` on any later submit click regardless of whether the dialog stayed open. The user dismisses via the existing Cancel/× button (`onClose`, unaffected by this gate) once they've read the warning — same UX as a `queued` row today.

**Render the warning** — find this block in the row rendering (inside `cards.map((c) => { ... })`, around lines 282-291):

```tsx
                {hasErr && (
                  <span className={styles.errCell}>
                    <Text size={11} tone="reject">{errors[c.symbol]}</Text>
                  </span>
                )}
                {isQueued && !hasErr && (
                  <span className={styles.errCell}>
                    <Text size={11} tone="caution">{queued[c.symbol]}</Text>
                  </span>
                )}
```

Add a third branch immediately after it:

```tsx
                {warnings[c.symbol] && !hasErr && !isQueued && (
                  <span className={styles.errCell}>
                    <Text size={11} tone="caution">{warnings[c.symbol]}</Text>
                  </span>
                )}
```

**The footer Submit button must also reflect a warn-only outcome, or it keeps inviting the user to "Submit" orders that already succeeded.** `hasQueued`/`hasRetryableErrors` (lines 182-183) drive that button's `disabled` prop and label — a `warn`-only state leaves both `false`, so today's code would show the button fully enabled with its ORIGINAL "Submit N order(s)" text, as if nothing had happened, right next to the warning text that says otherwise. Add a third computed flag alongside the existing two:

```ts
  const hasWarnings = Object.keys(warnings).length > 0;
```

Update the footer button (`disabled` prop and label ternary):

```tsx
            <button
              type="button"
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={submit}
              disabled={cards.length === 0 || submitting || (hasQueued && !hasRetryableErrors) || (hasWarnings && !hasRetryableErrors && !hasQueued)}
            >
              <Text size={13}>
                {submitting
                  ? 'Submitting…'
                  : hasRetryableErrors
                    ? `Retry ${Object.keys(errors).length} failed order${Object.keys(errors).length === 1 ? '' : 's'}`
                    : hasQueued
                      ? 'Queued — close to continue'
                      : hasWarnings
                        ? 'Placed — close to continue'
                        : `Submit ${cards.length} order${cards.length === 1 ? '' : 's'}`}
              </Text>
            </button>
```

Run: `cd frontend && npm run test -- --testPathPattern=StockSendDialog`
Expected: the two NEW tests PASS; the pre-existing `"only resubmits..."` test now FAILS — proceed to Step 6, this is expected and explained there.

### Step 6: Fix the regression this causes in the pre-existing `"only resubmits symbols that failed on the previous attempt"` test

That test selects `IBKR Paper` (auto-send) for all 3 cards and mocks only `api.postStockOrder`, never `addPosition`. Before Step 5, the auto-send branch never called `addPosition`, so this didn't matter. After Step 5, every successful `postStockOrder` now also calls the REAL (unmocked) `usePortfolioStore.addPosition`, which hits a real `fetch` this test never mocks — in the `npm run test` environment (no backend running), that `fetch` fails, `addPosition` resolves `status: 'pending'`, and Step 5's code treats `'pending'` as warn-worthy. With nothing clearing `warnings`, all three symbols end up permanently in `warn` after the retry succeeds — the "stay open" gate (now including `warn`) stays true forever, `onSubmit` is never called, and `await waitFor(() => expect(onSubmit).toHaveBeenCalled())` times out.

Fix it by making `addPosition` succeed in THIS test only, restoring the real implementation afterward so the SECOND pre-existing test (`"does not permanently disable Submit..."`) still exercises the real `addPosition` → its own mocked-to-reject `global.fetch` → `'pending'` path it depends on (that test already restores what it overrides — `global.fetch = originalFetch;`, line 151 — this needs the equivalent for `addPosition`).

Add near the top of the `describe('StockSendDialog — partial basket failure retry', ...)` block, right after its opening brace, before the existing `beforeEach`:

```ts
  const realAddPosition = usePortfolioStore.getState().addPosition;

  afterEach(() => {
    usePortfolioStore.setState({ addPosition: realAddPosition });
  });
```

Add the override at the top of the `it('only resubmits symbols that failed on the previous attempt', ...)` test body, before `render(...)`:

```ts
    usePortfolioStore.setState({ addPosition: jest.fn().mockResolvedValue({ ok: true, status: 'ok' as const }) });
```

Run: `cd frontend && npm run test -- --testPathPattern=StockSendDialog`
Expected: PASS — all 4 tests in the file (2 pre-existing + 2 new).

### Step 7: Fix `StockPositionCard/index.tsx`'s OWN `submit()` the same way

This is a DIFFERENT function from `onAddToPortfolio` (fixed in Step 3 above) in the SAME file — `submit()` (lines 308-329, wired to "Section 5 — Order buttons") places a real broker order and has never called `addPosition` at all. This is the highest-risk part of this task — a second write path into the user's real portfolio state — so it gets the same test-first treatment as `StockSendDialog` did in Steps 4-6, not just a typecheck.

**Step 7a: Write the failing tests first.** Create `frontend/components/organisms/StockPositionCard/__tests__/StockPositionCard.submit.test.tsx`, following the exact mocking convention the sibling test file `StockPositionCard.pending.test.tsx` already establishes for this component (mock `@/lib/api` as a module; drive `addPosition`'s real success/failure via `global.fetch`, not by replacing `addPosition` itself — this component's existing tests never mock the store, only `fetch`):

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({
  api: {
    postStockOrder: jest.fn(),
    getBrokerStatus: jest.fn().mockResolvedValue({}),
  },
}));
jest.mock('@/components/organisms/StockAutoTradeArm', () => ({ StockAutoTradeArm: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => null }));

function makeCard(): PositionCardData {
  return {
    symbol: 'AAPL', company: 'Apple Inc.', price: 150, direction: 'Bullish',
    strategy: {
      strategy: 'pullback_ema', entry_price: 150, stop_price: 145,
      target_price: 160, rr_ratio: 2, atr: 3, detail: {},
    },
    backtest: {
      n_trades: 20, win_rate: 0.6, total_return_pct: 12, max_drawdown_pct: 5,
      expectancy: 0.4, sharpe: 1.2, confidence: 0.7, passes_gate: true, summary_text: 'ok',
    },
    stock_score: 80, stock_status: 'PASS',
    shares: 30, dollar_risk: 150, dollar_size: 4500,
    confidence: 0.7, confidence_text: 'High',
    sentiment: null, fundamentals: null,
  };
}

const originalFetch = global.fetch;

describe('StockPositionCard — broker order submit()', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState({
      ibkrPaper: { baseUrl: 'https://localhost:7499/v1/api', accountId: 'ACC' },
    } as any);
    jest.clearAllMocks();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('creates a local position with a snapshot after a successful broker order', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1' });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;

    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /limit @/i }));

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const pos = usePortfolioStore.getState().positions[0];
    expect(pos.source).toBe('broker');
    expect(pos.tradeCardSnapshot).toBeDefined();
    expect(pos.stop).toBe(145);
  });

  it('shows a non-blocking warning (not an error) and permanently disables the order buttons when the order succeeds but local tracking fails', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-2' });
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;

    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /limit @/i }));

    expect(await screen.findByText(/not yet tracked in Portfolio/)).toBeInTheDocument();
    // The order genuinely succeeded — clicking again must not be possible, since
    // that would fire a second broker order for shares already bought.
    expect(screen.getByRole('button', { name: /limit @/i })).toBeDisabled();
  });
});
```

Run: `cd frontend && npm run test -- --testPathPattern=StockPositionCard.submit`
Expected: FAIL — `submit()` never calls `addPosition`, so the first test's `positions` array stays empty and times out; the second test's warning text never renders.

**Step 7b: Implement.** Add a `warning` state alongside the component's other `useState` declarations (near line 276):

```ts
  const [warning, setWarning] = useState<string | null>(null);
```

Replace `submit()` (lines 308-329). Mirror `onAddToPortfolio`'s exact levels construction (overlay values + any captured `structural` stop) so a broker-executed position carries the identical fidelity a manually-added one does. Nothing here disables the order buttons after a *successful* placement (only `placingType !== null`, which resets in `finally`) — a local-tracking failure must go through `warning`, never `err` (whose existing JSX render, `{err && <Text ... tone="reject">{err}</Text>}`, uses the same "this failed" tone a genuine order failure uses):

```ts
  async function submit(orderType: 'LMT' | 'MKT') {
    if (execMode === 'recommendation' || orderId !== null) return;
    setPlacingType(orderType);
    setErr(null);
    setWarning(null);
    try {
      const res = await api.postStockOrder({
        broker: execMode,
        symbol: card.symbol,
        action: card.direction === 'Bullish' ? 'BUY' : 'SELL',
        effect: 'OPEN',
        quantity: overlay.shares,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? overlay.entry : null,
        tif: 'DAY',
      });
      setOrderId(res.order_id);
      try {
        const addRes = await addPosition({
          ...buildPaperStockPosition(
            card.symbol, overlay.entry, overlay.shares, card.direction as Direction,
            stockCardSnapshotOf(card, scanHorizonLabel ?? 'Swing', {
              entry: overlay.entry,
              stop: overlay.stop,
              targets: [overlay.t1, overlay.t2, overlay.t3],
              shares: overlay.shares,
            }),
            {
              stop: overlay.stop,
              targets: [
                { price: overlay.t1, shares: overlay.sharesT1 },
                { price: overlay.t2, shares: overlay.sharesT2 },
                { price: overlay.t3, shares: overlay.sharesT3 },
              ],
              structuralStop: structural?.price ?? null,
            },
          ),
          source: 'broker',
          sourceLabel: `${execMode} — ${orderType} (ID: ${res.order_id})`,
          orderedAt: new Date().toISOString(),
        });
        if (addRes.status === 'rejected' || addRes.status === 'pending') {
          setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
        }
      } catch {
        setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setPlacingType(null);
    }
  }
```

Add `orderId !== null` to both order buttons' `disabled` props (lines ~740 and ~748, currently `disabled={placingType !== null}`):

```tsx
            disabled={placingType !== null || orderId !== null}
```

Add a `warning` display next to the existing `orderId`/`err`/`queued` display (Section 6, around line 756-758):

```tsx
      {warning && <Text size={12} tone="caution">{warning}</Text>}
```

Add `setWarning(null);` to the existing `card.symbol`-change cleanup effect (around line 162-168), alongside its other resets.

Run: `cd frontend && npm run test -- --testPathPattern=StockPositionCard`
Expected: PASS (all tests across all `StockPositionCard/__tests__/*` files — the 2 new ones from Step 7a plus the pre-existing `.pending.test.tsx`/`.exits.test.tsx`)

Run: `cd frontend && npm run typecheck`
Expected: clean

### Step 8: Fix `step-7-position-card/page.tsx`'s `submit()` the same way

This page has no per-position level editor — it shows the pristine `card.strategy` levels directly (no `overlay` state exists here), so use `card.strategy`/`pristineLevels`-equivalent construction, not an edited one. Like Step 7, this is a second write path into real portfolio state and gets the same test-first treatment — this page currently has no test file at all.

**Step 8a: Write the failing tests first.** Create `frontend/app/(frame)/screener/step-7-position-card/__tests__/page.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Step7PositionCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import type { StockScanResult } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({
  api: {
    postStockOrder: jest.fn(),
    getBrokerStatus: jest.fn().mockResolvedValue({}),
    getStockQuote: jest.fn().mockResolvedValue({ price: 150 }),
  },
}));

function makeScanResult(): StockScanResult {
  return {
    scan_id: 'S1', timestamp: '2026-08-01T00:00:00Z',
    candidates: [{
      symbol: 'AAPL', company: 'Apple Inc.', price: 150, direction: 'Bullish',
      strategy: {
        strategy: 'pullback_ema', entry_price: 150, stop_price: 145,
        target_price: 160, rr_ratio: 2, atr: 3, detail: {},
      },
      backtest: {
        n_trades: 20, win_rate: 0.6, total_return_pct: 12, max_drawdown_pct: 5,
        expectancy: 0.4, sharpe: 1.2, confidence: 0.7, passes_gate: true, summary_text: 'ok',
      },
      stock_score: 80, stock_status: 'PASS',
      shares: 30, dollar_risk: 150, dollar_size: 4500,
      confidence: 0.7, confidence_text: 'High',
    }],
    rejected: [],
  };
}

const originalFetch = global.fetch;

describe('step-7-position-card — broker order submit()', () => {
  beforeEach(() => {
    useScanStore.setState({ stockScanResult: makeScanResult(), selectedSymbol: 'AAPL' } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState({
      ibkrPaper: { baseUrl: 'https://localhost:7499/v1/api', accountId: 'ACC' },
    } as any);
    jest.clearAllMocks();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('creates a local position with a snapshot after a successful broker order', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1' });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;

    render(<Step7PositionCardPage />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /place limit order/i }));

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const pos = usePortfolioStore.getState().positions[0];
    expect(pos.source).toBe('broker');
    expect(pos.tradeCardSnapshot).toBeDefined();
    expect(pos.stop).toBe(145);
  });

  it('shows a non-blocking warning and permanently disables the order buttons when the order succeeds but local tracking fails', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-2' });
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;

    render(<Step7PositionCardPage />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /place limit order/i }));

    expect(await screen.findByText(/not yet tracked in Portfolio/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /place limit order/i })).toBeDisabled();
  });
});
```

Run: `cd frontend && npm run test -- --testPathPattern=step-7-position-card`
Expected: FAIL — `submit()` never calls `addPosition`.

**Step 8b: Implement.** Add imports (after line 9):

```ts
import { usePortfolioStore } from '@/lib/portfolioStore';
import { buildPaperStockPosition, stockCardSnapshotOf } from '@/lib/paperTrade';
```

Add hook reads and a `warning` state inside `Step7PositionCardPage` (near the other hooks, around line 45):

```ts
  const addPosition = usePortfolioStore((s) => s.addPosition);
  const scanHorizon = useScanStore((s) => s.context?.horizon ?? 'Swing');
  const [warning, setWarning] = useState<string | null>(null);
```

Replace `submit()` (lines 85-106). Same duplicate-order reasoning as Step 7 above: nothing here disables the buttons after a *successful* placement — only `placingType !== null` — so this needs the same `orderId !== null` guard and `warning`/`error` separation:

```ts
  async function submit(orderType: 'LMT' | 'MKT') {
    if (!card || execMode === 'recommendation' || orderId !== null) return;
    setPlacingType(orderType);
    setError(null);
    setWarning(null);
    try {
      const res = await api.postStockOrder({
        broker: execMode,
        symbol: card.symbol,
        action: card.direction === 'Bullish' ? 'BUY' : 'SELL',
        effect: 'OPEN',
        quantity: card.shares,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? card.strategy.entry_price : null,
        tif: 'DAY',
      });
      setOrderId(res.order_id);
      try {
        const addRes = await addPosition({
          ...buildPaperStockPosition(
            card.symbol, card.strategy.entry_price, card.shares, card.direction as 'Bullish' | 'Bearish',
            stockCardSnapshotOf(card, scanHorizon),
            {
              stop: card.strategy.stop_price,
              targets: (card.strategy.targets?.length ? card.strategy.targets : [card.strategy.target_price])
                .map((price) => ({ price })),
            },
          ),
          source: 'broker',
          sourceLabel: `${execMode} — ${orderType} (ID: ${res.order_id})`,
          orderedAt: new Date().toISOString(),
        });
        if (addRes.status === 'rejected' || addRes.status === 'pending') {
          setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
        }
      } catch {
        setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setPlacingType(null);
    }
  }
```

Add `orderId !== null` to both order buttons' `disabled` props (lines 178 and 182):

```tsx
          <button type="button" className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={() => submit('LMT')} disabled={placingType !== null || orderId !== null}>
            {placingType === 'LMT' ? 'Placing…' : `Place Limit Order @ $${card.strategy.entry_price}`}
          </button>
          <button type="button" className={`${styles.btn} ${styles.btnMarket}`}
            onClick={() => submit('MKT')} disabled={placingType !== null || orderId !== null}>
            {placingType === 'MKT' ? 'Placing…' : 'Right Now — Market Order'}
          </button>
```

Add a `warning` display alongside `{orderId && ...}` / `{error && ...}` (lines 188-189):

```tsx
      {warning && <Text size={12} tone="caution">{warning}</Text>}
```

Add `setWarning(null);` to the candidate-nav `onClick={() => { setSelectedIdx(i); setOrderId(null); setError(null); }}` (line 119).

Run: `cd frontend && npm run test -- --testPathPattern=step-7-position-card`
Expected: PASS (both new tests)

Run: `cd frontend && npm run typecheck`
Expected: clean

### Step 9: Leave `step-4-stocks/page.tsx`'s auto-execute loop alone — do not add a snapshot call here

`frontend/app/(frame)/screener/step-4-stocks/page.tsx`'s after-scan auto-execute loop (`onRun`, lines 188-207) calls `buildPaperStockPosition(c.symbol, c.strategy.entry_price, c.shares, c.direction as Direction, undefined, {...})` — the 5th argument (`snapshot`) is explicitly `undefined`. This is confirmed, by reading the code's own comment at lines 190-193, to be a **deliberate** decision already made by the exit-targets plan's authors, not an oversight: "this path also did not attach a snapshot before; it still does not, deliberately (the scan result it came from is already persisted in scanStore)." **Do not touch this call site.** It is out of scope for this task, and adding a snapshot here would be relitigating a decision that isn't this plan's to make.

One consequence worth knowing for Task 2: a position bought through THIS specific path will have `tradeCardSnapshot: undefined`, so its Monte Carlo estimate (Task 2) will fall back to a generic strategy guess and the default trend_score/horizon — Task 2's fallback handling already covers this gracefully (no crash, just a less-precise estimate for auto-executed positions specifically). This is an accepted, pre-existing limitation inherited from the upstream decision above, not something this plan needs to fix.

### Step 10: Full typecheck and test pass for this task

Run: `cd frontend && npm run typecheck && npm run test -- --testPathPattern="paperTrade|StockSendDialog|StockPositionCard|step-7-position-card"`
Expected: clean / PASS

### Step 11: Commit

```bash
git add frontend/lib/paperTrade.ts frontend/lib/paperTrade.test.ts \
  frontend/components/organisms/StockSendDialog/index.tsx \
  frontend/components/organisms/StockSendDialog/__tests__/StockSendDialog.test.tsx \
  frontend/components/organisms/StockPositionCard/index.tsx \
  frontend/components/organisms/StockPositionCard/__tests__/StockPositionCard.submit.test.tsx \
  "frontend/app/(frame)/screener/step-7-position-card/page.tsx" \
  "frontend/app/(frame)/screener/step-7-position-card/__tests__/page.test.tsx"
git commit -m "fix(portfolio): capture buy-time snapshot on every stock broker-order path"
```

---

## Task 2: Wire Monte Carlo Estimate into the Portfolio EditDrawer

**Files:**
- Modify: `frontend/app/(frame)/portfolio/page.tsx`
- Modify: `frontend/app/(frame)/portfolio/page.module.css`
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` (options snapshot only)
- Test: `frontend/app/(frame)/portfolio/__tests__/EditDrawer.test.tsx` (new file)

### Step 1: Extend `tradeCardSnapshotOf` (options) with `strike`

Modify `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:60-71`:

```ts
function tradeCardSnapshotOf(card: TradeCardData): Record<string, unknown> {
  return {
    stockScore: card.stockScore,
    stockConfidence: card.stockConfidence,
    stockBreakdown: card.stockBreakdown,
    contractScore: card.contractScore,
    contractConfidence: card.contractConfidence,
    contractBreakdown: card.contractBreakdown,
    rrRatio: card.rrRatio,
    rrModel: card.rrModel,
    strike: card.contractDetails?.strike ?? null,
  };
}
```

Run: `cd frontend && npm run typecheck`
Expected: clean

### Step 2: Export `EditDrawer` so it's testable in isolation

Modify `frontend/app/(frame)/portfolio/page.tsx:461` — change `function EditDrawer({` to `export function EditDrawer({`.

### Step 3: Write the failing tests

Create `frontend/app/(frame)/portfolio/__tests__/EditDrawer.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EditDrawer } from '../page';
import { api } from '@/lib/api';
import type { PortfolioPosition } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getFirstPassageEstimate: jest.fn(),
    getStockFirstPassage: jest.fn(),
  },
}));

function makeStockPosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL|STOCK', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '', dteRemaining: 0, dteTotal: 0,
    entryPrice: 190, currentPrice: 195, pnlDollar: 50, pnlPct: 2.6,
    stop: 182, targets: [
      { id: 'T1', stockPrice: 205, targetPrice: 205, status: 'PENDING' },
      { id: 'T2', stockPrice: 215, targetPrice: 215, status: 'PENDING' },
    ],
    status: 'PASS', contracts: 10, recId: 'REC-1',
    tradeCardSnapshot: { stock_score: 78, horizon: 'Swing (5–15d)', strategy: { strategy: 'pullback_ema' } },
    ...overrides,
  };
}

function makeOptionPosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL 220C 05/16', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '2026-09-16', dteRemaining: 20, dteTotal: 30,
    entryPrice: 4.2, currentPrice: 4.5, currentStockPrice: 195,
    pnlDollar: 30, pnlPct: 7.1, stop: 3.0, targets: [], status: 'PASS',
    delta: 0.5, contracts: 2, recId: 'REC-2',
    tradeCardSnapshot: { strike: 220, stockBreakdown: { trend: 72 } },
    ...overrides,
  };
}

describe('EditDrawer Monte Carlo estimate', () => {
  const noop = () => {};

  it('calls getStockFirstPassage with target/stop prices and horizon from the snapshot for a stock position', async () => {
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      targets: [
        { price: 205, probability: 0.6, expectedDays: 8 },
        { price: 215, probability: 0.3, expectedDays: 15 },
      ],
      invalidation: { probability: 0.15, expectedDays: null },
      horizonDays: 10,
      modelCaveat: null,
    });
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    // `runEstimate` always passes a real AbortSignal as the 2nd argument (see
    // Task 2 Step 4's AbortController pattern) — `toHaveBeenCalledWith` fails
    // outright on an unexpected extra argument, not just a mismatched one, so
    // the 2nd matcher below is required, not optional decoration.
    await waitFor(() => expect(api.getStockFirstPassage).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'AAPL', direction: 'Bullish', horizon: 'Swing', strategy: 'pullback_ema',
      stock_price: 195, stop_price: 182, targets: [205, 215], trend_score: 78,
    }), expect.any(AbortSignal)));
    expect(await screen.findByText('60%')).toBeInTheDocument();
    expect(await screen.findByText('30%')).toBeInTheDocument();
    expect(screen.getByText(/10 trading days/)).toBeInTheDocument();
  });

  it('renders modelCaveat when the backend flags a poor model fit', async () => {
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      targets: [{ price: 205, probability: 0.4, expectedDays: 10 }],
      invalidation: { probability: 0.2, expectedDays: null },
      horizonDays: 10,
      modelCaveat: 'This model assumes directional drift; mean-reversion strategies may not fit well.',
    });
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    expect(await screen.findByText(/may not fit well/)).toBeInTheDocument();
  });

  it('calls getFirstPassageEstimate with strike/trend from the snapshot and settings-store target percents for an option position', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.2, stockPrice: 215, optionPrice: 5.4, probability: 0.6, expectedDays: 5 },
        { pct: 0.5, stockPrice: 230, optionPrice: 6.75, probability: 0.4, expectedDays: 10 },
        { pct: 1.0, stockPrice: 250, optionPrice: 9.0, probability: 0.35, expectedDays: 18 },
      ],
      invalidation: { probability: 0.10, expectedDays: null },
    });
    render(<EditDrawer position={makeOptionPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'AAPL', direction: 'Bullish', stock_price: 195, strike: 220,
      dte: 20, premium: 4.5, delta: 0.5, trend_score: 72, invalidation_price: 3.0,
      t1_pct: expect.any(Number), t2_pct: expect.any(Number), t3_pct: expect.any(Number),
    }), expect.any(AbortSignal)));
    expect(await screen.findByText('60%')).toBeInTheDocument();
    expect(await screen.findByText('40%')).toBeInTheDocument();
    expect(await screen.findByText('35%')).toBeInTheDocument();
    expect(await screen.findByText('10%')).toBeInTheDocument();
  });

  it('disables Estimate for a stock position with no targets captured', () => {
    render(<EditDrawer position={makeStockPosition({ targets: [] })} onClose={noop} onChange={noop} onRemove={noop} />);
    // NOT screen.getByText('Estimate').toBeDisabled() — the button's label is
    // rendered via <Text> (defaults to a nested <span>), and jest-dom's
    // toBeDisabled() does not see through an ancestor <button disabled> to a
    // descendant element the way a naive read might suggest; only the queried
    // element itself (or a `<fieldset disabled>` ancestor) counts. Query the
    // actual <button> via its accessible role/name instead.
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeDisabled();
  });

  it('disables Estimate for an option position missing strike in its snapshot', () => {
    render(<EditDrawer position={makeOptionPosition({ tradeCardSnapshot: {} })} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeDisabled();
  });
});
```

Run: `cd frontend && npm run test -- --testPathPattern=EditDrawer`
Expected: FAIL — no "Estimate" button exists yet.

### Step 4: Implement the Monte Carlo section

Modify `frontend/app/(frame)/portfolio/page.tsx`. Line 10 currently reads `import { useEffect, useState } from 'react';` — `useRef` is not imported; change it to:

```ts
import { useEffect, useRef, useState } from 'react';
```

Add ONE import (after line 16, `import { usePortfolioStore, flushPendingPositionPatches } from '@/lib/portfolioStore';`):

```ts
import { api } from '@/lib/api';
```

`useSettingsStore` is ALREADY imported at line 21 (`import { useSettingsStore } from '@/lib/settingsStore';`) — do NOT add it again, or `npm run typecheck` fails with "Duplicate identifier 'useSettingsStore'" (TS2300). The `defaultTargetPct` hook read below reuses that existing import.

Add a `_horizonEnum`-compatible import for the stock branch — reuse the existing helper rather than reimplementing horizon-label parsing:

```ts
import { _horizonEnum } from '@/lib/analysisStore';
```

Inside `EditDrawer`, right after the existing `useEffect` cleanup block (`flushPendingPositionPatches`, lines 476-478), add the Monte Carlo state and handler:

```ts
  const isStock = position.contract.endsWith('|STOCK');
  const snapshot = position.tradeCardSnapshot ?? {};
  const stockTargetPrices = position.targets.map((t) => t.targetPrice ?? t.stockPrice).filter((p): p is number => typeof p === 'number' && p > 0);
  const optionStrike = typeof snapshot.strike === 'number' ? snapshot.strike : null;
  const optionTrend = (snapshot.stockBreakdown as { trend?: number } | undefined)?.trend;
  const defaultTargetPct = useSettingsStore((s) => s.targetProfitPct);

  // Mirrors backend/app/routers/stock_scan.py's own directional validation for
  // /api/stocks/first-passage (stop and every target must be on the correct
  // side of the current price for the trade's direction) — without this, a
  // normal winning position (current price has already run past a target that
  // hasn't had its `targets[].status` synced to HIT yet) hits a 422 that the
  // single catch{} below collapses into "try again," which can never succeed
  // no matter how many times the user clicks it.
  const stockDirectionValid = isStock && position.stop
    ? position.direction === 'Bullish'
      ? position.stop < position.currentPrice && stockTargetPrices.every((p) => p > position.currentPrice)
      : position.stop > position.currentPrice && stockTargetPrices.every((p) => p < position.currentPrice)
    : true;

  const estimateDisabled = isStock
    ? stockTargetPrices.length === 0 || !position.stop || !stockDirectionValid
    : optionStrike == null || position.currentStockPrice == null || !position.stop;

  // Same AbortController pattern as StockPositionCard's onEstimate/estimateReq
  // (the template this section mirrors): abort a still-in-flight request when
  // the button is re-fired or this drawer instance goes away (closing the
  // drawer, or the parent switching `editing` to a different row), so a late
  // response for a request the user has already moved on from can never land.
  const estimateReq = useRef<AbortController | null>(null);
  useEffect(() => {
    return () => { estimateReq.current?.abort(); };
  }, [position.recId]);

  const [mcLoading, setMcLoading] = useState(false);
  const [mcError, setMcError] = useState<string | null>(null);
  const [mcResult, setMcResult] = useState<{
    targets: { label: string; price: number; probability: number; expectedDays: number | null }[];
    invalidation: { probability: number; expectedDays: number | null };
    horizonNote?: string;
    modelCaveat?: string | null;
  } | null>(null);

  const runEstimate = async () => {
    estimateReq.current?.abort();
    const ctrl = new AbortController();
    estimateReq.current = ctrl;
    setMcLoading(true);
    setMcError(null);
    setMcResult(null);
    try {
      if (isStock) {
        if (stockTargetPrices.length === 0 || !position.stop || !stockDirectionValid) throw new Error('missing target/stop');
        // A position minted with no snapshot (the after-scan auto-execute path
        // deliberately omits one — see paperTrade.ts/step-4-stocks's own
        // comment) has no real strategy name to send. An empty string just
        // never matches the backend's mean-reversion caveat check, which is a
        // safe under-trigger — a wrong HARDCODED guess here would misrepresent
        // which strategy this trade actually came from.
        const strategy = (snapshot.strategy as { strategy?: string } | undefined)?.strategy ?? '';
        const horizonLabel = typeof snapshot.horizon === 'string' ? snapshot.horizon : undefined;
        const res = await api.getStockFirstPassage({
          symbol: position.symbol,
          direction: position.direction,
          horizon: _horizonEnum(horizonLabel),
          strategy,
          stock_price: position.currentPrice,
          stop_price: position.stop,
          targets: stockTargetPrices,
          trend_score: typeof snapshot.stock_score === 'number' ? snapshot.stock_score : 50,
        }, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setMcResult({
          targets: res.targets.map((t, i) => ({ label: `T${i + 1}`, price: t.price, probability: t.probability, expectedDays: t.expectedDays })),
          invalidation: res.invalidation,
          horizonNote: `${res.horizonDays} trading days`,
          modelCaveat: res.modelCaveat,
        });
      } else {
        if (optionStrike == null || position.currentStockPrice == null || !position.stop) {
          throw new Error('missing option context');
        }
        const res = await api.getFirstPassageEstimate({
          symbol: position.symbol,
          direction: position.direction,
          stock_price: position.currentStockPrice,
          strike: optionStrike,
          dte: position.dteRemaining,
          premium: position.currentPrice,
          delta: position.delta ?? 0.45,
          trend_score: optionTrend ?? 50,
          invalidation_price: position.stop,
          t1_pct: defaultTargetPct.t1,
          t2_pct: defaultTargetPct.t2,
          t3_pct: defaultTargetPct.t3,
        }, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setMcResult({
          targets: res.targets.map((t) => ({ label: `T${Math.round(t.pct * 100)}%`, price: t.stockPrice ?? 0, probability: t.probability, expectedDays: t.expectedDays })),
          invalidation: res.invalidation,
        });
      }
    } catch (e) {
      if (ctrl.signal.aborted) return;
      // Mirrors StockPositionCard's onEstimate, which captures the real
      // error (setEstimateErr(String(e))) rather than a single static
      // message — a genuine backend rejection (bad symbol, missing candle
      // data, a 500) reads very differently from "try again" being useless
      // forever after the directional-guard case above.
      setMcError(String(e));
    } finally {
      if (estimateReq.current === ctrl) {
        estimateReq.current = null;
        setMcLoading(false);
      }
    }
  };
```

Add the section markup between the closing `</div>` of `.editGrid` (line 522) and the `.editFooter` div (line 524). Note `.dteRemaining` — a non-optional `number` on `PortfolioPosition` (`types/domain.ts:208`), never `null`/`undefined` — is deliberately absent from `estimateDisabled`'s option branch above; an earlier draft checked `position.dteRemaining == null` there, which can never be true and was dead code:

```tsx
      <div className={styles.mcSection}>
        <Text size={12} weight={500}>Monte Carlo estimate</Text>
        <div className={styles.mcRow}>
          <button type="button" className={styles.mcBtn} onClick={runEstimate} disabled={mcLoading || estimateDisabled}>
            <Text size={12} weight={500}>{mcLoading ? 'Estimating…' : 'Estimate'}</Text>
          </button>
          {mcError && <Text size={11} tone="reject">{mcError}</Text>}
        </div>
        {isStock && !stockDirectionValid && (
          <Text size={11} tone="dim">
            Stop or a target is already on the wrong side of the current price — sync the position&apos;s targets before estimating.
          </Text>
        )}
        {mcResult?.horizonNote && (
          <Text size={10} tone="dim">Chance of reaching each target within {mcResult.horizonNote}</Text>
        )}
        {mcResult && (
          <div className={styles.mcResultRow}>
            {mcResult.targets.map((t, i) => (
              <div key={`${t.label}-${i}`}>
                <Text size={10} tone="dim">{t.label.toUpperCase()}</Text>
                <Data size={14} weight={500} tone="pass">{`${Math.round(t.probability * 100)}%`}</Data>
                <Text size={10} tone="dim">{t.expectedDays != null ? `~${Math.round(t.expectedDays)}d` : 'unlikely'}</Text>
              </div>
            ))}
            <div>
              <Text size={10} tone="dim">STOP HIT</Text>
              <Data size={14} weight={500} tone="reject">{`${Math.round(mcResult.invalidation.probability * 100)}%`}</Data>
              <Text size={10} tone="dim">{mcResult.invalidation.expectedDays != null ? `~${Math.round(mcResult.invalidation.expectedDays)}d` : 'unlikely'}</Text>
            </div>
          </div>
        )}
        {mcResult?.modelCaveat && (
          <Text size={11} tone="caution">{mcResult.modelCaveat}</Text>
        )}
      </div>
```

### Step 5: Add the CSS classes

Add to `frontend/app/(frame)/portfolio/page.module.css`, near the existing `.editGrid`/`.editField` rules:

```css
.mcSection {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px dashed var(--border-subtle);
}

.mcRow {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.mcBtn {
  height: 30px;
  padding: 0 var(--space-4);
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  border-radius: var(--radius-md);
  font-family: var(--font-dm);
  font-size: 12px;
  cursor: pointer;
  transition: background 120ms, color 120ms;
}

.mcBtn:hover:not(:disabled) {
  background: var(--bg-surface);
}

.mcBtn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mcResultRow {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
  gap: var(--space-3);
}
```

### Step 6: Run the tests to verify they pass

Run: `cd frontend && npm run test -- --testPathPattern=EditDrawer`
Expected: PASS (5 tests)

### Step 7: Typecheck

Run: `cd frontend && npm run typecheck`
Expected: clean

### Step 8: Commit

```bash
git add "frontend/app/(frame)/portfolio/page.tsx" "frontend/app/(frame)/portfolio/page.module.css" \
  "frontend/app/(frame)/portfolio/__tests__/EditDrawer.test.tsx" \
  "frontend/app/(frame)/screener/step-7-trade-card/page.tsx"
git commit -m "feat(portfolio): wire Monte Carlo estimate into the EditDrawer for stock and option positions"
```

---

## Task 3: Full verification pass

### Step 1: Full frontend test suite

Run: `cd frontend && npm run test`
Expected: PASS, no regressions

### Step 2: Full typecheck

Run: `cd frontend && npm run typecheck`
Expected: clean

### Step 3: Manual smoke check (if a browser/dev server is available in this session)

Start the backend and `npm run dev` (localhost:3001), open Portfolio with at least one open stock position and one option position, open each one's edit drawer, click "Estimate," confirm both branches return a result without a console error. If no dev environment is available in this session, state that explicitly instead of claiming it was checked.
