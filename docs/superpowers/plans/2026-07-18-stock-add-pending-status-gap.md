# StockPositionCard / StockSendDialog Pending-Status Gap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every stock-mode consumer of `portfolioStore.addPosition` that treats the `'pending'` (backend-unreachable) result as success. When the backend is down, `addPosition` optimistically keeps the row in local state, returns `{ ok: false, status: 'pending' }`, and lets `syncFromBackend`'s ~30s poll retry it — but `StockPositionCard`, `StockSendDialog`, **and the Step-4 after-scan auto-execute loop** only branch on `status === 'rejected'`, so a `'pending'` result falls through to the success path. The user is told the position was *saved* when it was only *queued*, with no indication the backend never confirmed it. (These three are all of stock mode's `addPosition` callers — verified by grep; the Options-mode callers in `step-7-trade-card` and `ChartWorkspace` already handle `'pending'`.)

**The bug, precisely:**
- `frontend/components/organisms/StockPositionCard/index.tsx` — `onAddToPortfolio` (`:197-211`): `if (res.status === 'rejected') { setErr(...); return; } setAdded(true);`. A `'pending'` result skips the guard and hits `setAdded(true)`, so the button flips to the confirmed-success label **"Added to Portfolio"** even though the backend never acknowledged the write.
- `frontend/components/organisms/StockSendDialog/index.tsx` — `submit` (`:77-123`), **two** `addPosition` call sites (`:87`, `:106` — the `:89-103` branch is an `api.postStockOrder` call, not `addPosition`): only `res.status === 'rejected'` writes into `errs`. A `'pending'` result records nothing, so the loop finishes with an empty `errs`, `onSubmit(orders)` fires, and the dialog closes reporting full success while some rows only ever reached local state.
- `frontend/app/(frame)/screener/step-4-stocks/page.tsx` — `onRun`'s after-scan auto-execute loop (`:161-166`): `if (addRes.status === 'rejected') failures.push(...)`. A `'pending'` auto-executed position is silently dropped from `failures` and never surfaced.

**This gap is already documented in the codebase** at `frontend/components/organisms/ChartWorkspace/index.tsx:845-846`: *"(StockPositionCard/StockSendDialog do NOT yet check res.status === 'pending' — a separate, pre-existing gap, not this fix's scope.)"* — deferred during the portfolio single-source-of-truth loop, and again in the deferred-audit-followups diff audit. This plan closes it. Update that comment as part of the work (Task 4) so it no longer describes the gap as open.

**Reference implementations to match (already shipped, part of the same prior fix cycles):**
- `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:526-532` — the Options-mode basket submit. `'pending'` increments a distinct `queued` counter (separate from `auto`/`manual`), is deliberately NOT counted toward the daily cap or written to the APPROVE audit log until it actually lands, and surfaces via a toast with the queued count shown distinctly from placed and rejected orders.
- `frontend/components/organisms/ChartWorkspace/index.tsx:854-860` — the standalone chart quick-buy. `'pending'` pushes a caution toast: *"{symbol} queued — backend unreachable, will sync automatically."*

The shared principle across both: **`'pending'` is neither success nor failure — it is a distinct third state ("queued, not yet confirmed") and must be shown as such**, in a tone distinct from the red rejected-error tone.

**Tech Stack:** Next.js 15 + TypeScript (strict) + Zustand + CSS Modules. Frontend-only change. `npm run typecheck` must be clean before every commit. Tests are Jest + React Testing Library, run via `cd frontend && npx jest`. Dev server: `cd frontend && npm run dev` → `localhost:3001`.

**Design principle — behavioural parity with the existing `rejected` path:** for both components, the new `'pending'` handling mirrors the *control flow* of the existing `'rejected'` handling (surface a note, do not advance to the confirmed-success state / do not fire the terminal `onSubmit`), differing only in tone (caution, not reject) and message (queued/will-sync, not failed). This keeps the change small, keeps it consistent with code Kenneth has already reviewed, and does not alter the backend-up happy path at all.

---

## Out of scope (conscious boundaries — not oversights)

These were considered and deliberately excluded. Documented here so a reviewer sees the boundary was chosen, not missed:

1. **Non-deterministic `recId` in `buildPaperStockPosition`** (`frontend/lib/paperTrade.ts:22`): `recId: 'PAPER-' + Date.now().toString(36)` is minted fresh on every call and is not a stable function of the position, which drives two related problems left unfixed here: (a) two different symbols added within the same millisecond collide, making `addPosition`'s `idxByRecId` path *replace* the first symbol's row with the second's; and (b) a queued add that is re-submitted **after the dialog/card is closed and re-opened** gets a new `recId`, so it merges (`idxByKey`) and doubles `contracts` — the remount vector Task 2's guard cannot cover. The proper fix is a deterministic, position-derived `recId` (so a re-add of the same contract reuses the same id and the store dedupes it), but that touches the merge/dedupe logic three prior audited cycles stabilised. Left as a named follow-up — **do not fix in this cycle.** Task 2's re-submit guard mitigates the common same-mount trigger; it does not close the remount vector.

2. **Double-add-on-retry for the *rejected* path**: the existing `rejected` path in `StockSendDialog.submit` already re-adds the rows that succeeded on a first click if the user fixes an error and re-submits (each retry re-runs the whole loop; same-contract rows merge and bump quantity in the store). This is a pre-existing property of the rejected path and is left as-is for parity. **The queued path does NOT inherit it** — Task 2 explicitly disables Submit once any row is queued (see finding-driven change below), because with the backend down there is nothing for the user to "fix," so a re-click would be pure duplication. Fixing the rejected-path variant too is a larger change left out of scope.

---

## Branch setup (do this first)

- [ ] **Step 0: Create a working branch off a clean `main`**

```bash
cd "F:/Git/GitHub/Trading assistant"
git status --short          # see what's here before branching
git checkout main
git pull --ff-only origin main
git checkout -b fix/stock-add-pending-status-gap
```
Expected: branches from a clean, up-to-date `main`. Pre-existing UNTRACKED files (stray `.docx`/`.zip`, other plan `.md` files) are fine — `git checkout -b` carries them forward harmlessly. Only stop if you see `M` (modified tracked) lines that indicate someone else's in-progress work.

---

## Task 1: StockPositionCard — surface a queued (pending) add distinctly from success

**Files:**
- Modify: `frontend/components/organisms/StockPositionCard/index.tsx`
- Add: `frontend/components/organisms/StockPositionCard/__tests__/StockPositionCard.pending.test.tsx`

### Behaviour to implement

`onAddToPortfolio` currently has two terminal outcomes: rejected (red error, button stays "Add to Portfolio") and success (`setAdded(true)`, button becomes "Added to Portfolio"). Add a **third**: pending/queued.

- On `res.status === 'pending'`: set a new `queued` state, do **not** call `setAdded(true)`, and return.
- The row is already in the store optimistically and is being retried by `syncFromBackend`, so **re-clicking must be prevented** (another click would merge/duplicate). The Add button's `disabled` and label must account for `queued`.
- Render a **caution-tone** message (not the existing red `err` slot) when queued: `Queued — backend unreachable, will sync automatically.`

### State reset on symbol change

The existing `useEffect(..., [card.symbol])` (`:129-132`) resets only the `overlay`. The per-symbol outcome states — `added`, `err`, the new `queued`, and `orderId` (the green "Order placed — ID: …" line from the broker `submit()` flow, `:189`/`:396`) — are **not** reset when the user selects a different candidate, so a stale confirmation can show under a different symbol. Since introducing `queued` makes this staleness directly relevant, reset these outcome states together in that same effect: `setAdded(false); setErr(null); setQueued(false); setOrderId(null);`. This is a small, correct improvement entailed by the new state, not unrelated scope creep — call it out in the commit message. (`placingType` is a transient in-flight flag cleared by the `submit()` `finally`, so it is intentionally NOT reset here.)

### TDD steps — test convention

**Follow the repo's established component-test convention (real stores + `setState`), NOT `jest.mock` of the Zustand stores.** The reference is `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx`: it imports the real `usePortfolioStore`/`useScanStore`, resets them via `useStore.setState(...)` in `beforeEach`, and only module-mocks `@/lib/api`. (Note: that test only uses `addPosition` to seed a row and asserts on `conflictedSymbols`, not on the returned `status` — so it is the precedent for the *real-store + setState* mechanics, not proof of the pending return. These new tests must assert on **rendered output** — the queued message and the disabled state — which is what actually exercises the fix.)

**Drive the outcome explicitly via `global.fetch` — do not rely on jsdom lacking `fetch`.** `addPosition` → `postPosition` calls `fetch`; the outcome is entirely determined by that fetch. This repo's `jest.setup.ts` currently provides no `fetch` polyfill, so an unstubbed `fetch` happens to throw → `'pending'` today — but that is brittle (a Node/jest upgrade or a future polyfill could make an unstubbed fetch hit the real `localhost:8000` and flip the result). So make the stub **required and self-contained** in every test:
- `'pending'`: `global.fetch = jest.fn().mockRejectedValue(new Error('offline'))`
- `'ok'`: `global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) })`
- `'rejected'`: `global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'risk check failed' }) })` (any non-`ok`, non-409 status)
Restore/replace `global.fetch` per-test (set it in each `it` or reset in `beforeEach`/`afterEach`).

**Two ts-jest / async gotchas to pre-empt (this repo uses `ts-jest`, which type-checks test sources and fails on type errors):**
- **Await the state settle, don't assert synchronously after `act`.** The click fires a floating async handler and `addPosition` awaits several microtask ticks (`postPosition` → `fetch` → catch → `setQueued`) before the DOM updates. A single `await Promise.resolve()` (as the RunScanButton reference uses for a different purpose) is not guaranteed to cover it. Use async queries — `expect(await screen.findByText(/queued/i)).toBeInTheDocument()` — or await the resolved `addPosition` promise, rather than a synchronous `getByText` immediately after `await act(...)`. Assert *absence* (e.g. no "Added to Portfolio") only after the positive async query has resolved.
- **The `PositionCardData` fixture must satisfy the full TYPE, not just the fields the card reads.** `PositionCardData` (and nested `backtest`) has many required fields the component never touches (`company`, `price`, `stock_score`, `stock_status`, `dollar_risk`, `dollar_size`, `confidence`, `confidence_text`, and `backtest.{n_trades,total_return_pct,max_drawdown_pct,expectancy,sharpe,confidence,passes_gate,summary_text}` — check `stockDomain.ts` for the current exact set). Either populate all required fields or cast the fixture `as PositionCardData` (the RunScanButton reference uses `as any` for the same reason). A "minimal" object typed as `PositionCardData` without a cast will fail ts-jest compilation before the test runs.

- [ ] **Step 1.1 (RED): Write the failing test first.**

Create `frontend/components/organisms/StockPositionCard/__tests__/StockPositionCard.pending.test.tsx`. Module-mock `@/lib/api` and the heavy child components (these are NOT stores — mocking modules is correct here):
```tsx
jest.mock('@/lib/api', () => ({ api: { getBrokerStatus: jest.fn().mockResolvedValue({}) } }));
jest.mock('@/components/organisms/StockAutoTradeArm', () => ({ StockAutoTradeArm: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => null }));
```
Use the **real** `usePortfolioStore` (and `useScanStore`, `useSettingsStore` — the card reads `scanStore.stockBasket`, `settingsStore.ibkrPaper`/`tradierPaper`; their real defaults are fine). In `beforeEach`, reset the portfolio store: `usePortfolioStore.setState({ positions: [] })`. For the pending test, set the **required** rejecting stub `global.fetch = jest.fn().mockRejectedValue(new Error('offline'))` so `addPosition` resolves `'pending'` (see the fetch-stub table above).

Provide a minimal valid `PositionCardData` fixture — check `frontend/types/stockDomain.ts` for the exact type; it must satisfy everything the card reads: `strategy.entry_price/stop_price/target_price`, `direction`, `shares`, `symbol`, `backtest.win_rate`, plus whatever `MarketSentiment`/`FundamentalHealthCard` need (those are mocked to `null`, so their props are not deref'd — a minimal `sentiment`/`fundamentals` stub or even the real shape is fine).

Wrap the click + async resolution in `await act(async () => { ... })` (per the RunScanButton reference) so the store update and re-render flush. Assertions:
1. The queued caution message (`/queued/i`) is in the document.
2. The success label **"Added to Portfolio"** is **not** present.
3. The Add button is disabled (no duplicate add possible).

Run `npx jest StockPositionCard.pending` and confirm it FAILS against the current code (it will: current code shows "Added to Portfolio" and no queued message).

- [ ] **Step 1.2 (GREEN): Implement the minimal change.**

In `frontend/components/organisms/StockPositionCard/index.tsx`:

1. Add state near the other add-flow state (`:157-158`):
```tsx
const [queued, setQueued] = useState(false);
```

2. In the symbol-change effect (`:129-132`), also reset the per-symbol outcome states:
```tsx
useEffect(() => {
  setOverlay(defaultOverlay(card));
  setAdded(false);
  setErr(null);
  setQueued(false);
  setOrderId(null);
// eslint-disable-next-line react-hooks/exhaustive-deps
}, [card.symbol]);
```

3. In `onAddToPortfolio` (`:197-211`), insert the pending branch. Note: do NOT add `setQueued(false)` at the top — the `queued` guard in the first line already returns whenever `queued` is true, so an entry-reset there is dead code; `queued` is cleared only by the symbol-change effect above.
```tsx
async function onAddToPortfolio() {
  if (adding || added || queued) return; // guards against a double-click firing two adds
  setAdding(true);
  setErr(null);
  try {
    const res = await addPosition(buildPaperStockPosition(card.symbol, overlay.entry, overlay.shares));
    if (res.status === 'rejected') {
      setErr(res.detail ?? 'Portfolio rejected this position.');
      return;
    }
    if (res.status === 'pending') {
      // Optimistically added but not confirmed by the backend — syncFromBackend's
      // poll will retry. Show it as queued, NOT as saved, and block re-clicks
      // (the row is already in the store; another add would merge/duplicate).
      setQueued(true);
      return;
    }
    setAdded(true);
  } finally {
    setAdding(false);
  }
}
```

4. Update the Add button (`:341-348`) to reflect the queued state and stay disabled while queued:
```tsx
<button
  type="button"
  className={styles.actionBtn}
  onClick={onAddToPortfolio}
  disabled={added || adding || queued}
>
  <Text size={12}>
    {added ? 'Added to Portfolio' : queued ? 'Queued — will sync' : adding ? 'Adding…' : 'Add to Portfolio'}
  </Text>
</button>
```

5. Render the caution message. Extend the existing result/error block (`:395-397`) — the `err` line stays red (`tone="reject"`); add a caution line for queued:
```tsx
{orderId && <Text size={12} tone="pass">Order placed — ID: {orderId}</Text>}
{err      && <Text size={12} tone="reject">{err}</Text>}
{queued   && <Text size={12} tone="caution">Queued — backend unreachable, will sync automatically.</Text>}
```

Run `npx jest StockPositionCard.pending` — confirm it now PASSES.

- [ ] **Step 1.3 (VERIFY): No regression to the existing success/reject flows.**

The same test file should also assert (or add sibling `it()` blocks), each with its own `global.fetch` stub from the table above:
- `status: 'ok'` (ok-stub) → shows "Added to Portfolio", button disabled, no queued/err message.
- `status: 'rejected'` (rejected-stub, `422` + `detail`) → shows the red detail text, button label back to "Add to Portfolio" (NOT disabled, so the user can retry), no queued message.

---

## Task 2: StockSendDialog — record queued rows and stop reporting them as fully submitted

**Files:**
- Modify: `frontend/components/organisms/StockSendDialog/index.tsx`
- Modify: `frontend/components/organisms/StockSendDialog/StockSendDialog.module.css` (add a caution-tone row/cell style, mirroring the existing `.rowErr`/`.errCell`)
- Add: `frontend/components/organisms/StockSendDialog/__tests__/StockSendDialog.pending.test.tsx`

### Behaviour to implement

`submit` (`:77-123`) classifies each card into ok / rejected today (rejected → `errs[sym]`). Add a third bucket, `queued`, for `status === 'pending'`. The parent `onSubmit` merely closes the dialog and **discards** the orders (`step-4-stocks/page.tsx:348-350`), and the dialog has **no toast channel** — so the queued information has nowhere to go if the dialog closes. Therefore, when there are queued rows (and no hard errors), the dialog must **stay open** and show the queued rows in a caution tone, exactly as it stays open today for rejected rows — rather than calling `onSubmit` and closing on what is not actually a confirmed full success.

Control-flow after the loop:
- Always `setErrors(errs)` and `setQueued(queuedMap)` so both sets of per-row notes render.
- If `errs` has entries **or** `queued` has entries → `return` (stay open; do **not** call `onSubmit`). Rejected rows render red (existing `.rowErr`), queued rows render caution.
- Only when both are empty (every row confirmed `ok`) → `onSubmit(orders)` (closes, unchanged happy path).

This means: backend up → identical behaviour to today (closes on success). Backend down → dialog stays open, every queued row shows "queued — will sync", user closes manually via Cancel. The silent-success path is eliminated.

**Re-submit guard (required — the primary same-mount protection).** Today, when the backend is down, the dialog *closes* (empty `errs` → `onSubmit` → parent closes it), so no re-submit is possible. Keeping the dialog open with Submit still enabled would let a second click *within the same open dialog* re-run the whole loop while every queued row is already in the store as a `pending` row. Because `buildPaperStockPosition` mints a **fresh `recId`** each call (`paperTrade.ts:22`), the re-add misses `addPosition`'s `idxByRecId` path and hits `idxByKey` → **merge → `contracts` doubled** (`portfolioStore.ts:279-291`). With the backend down there is nothing for the user to "fix," so a re-click is pure duplication. Therefore: **once any row is queued, disable the Submit button.** Compute `const hasQueued = Object.keys(queued).length > 0;` and add it to the Submit button's `disabled`.

**Scope of the guard — be precise, do NOT overclaim.** `queued` is component `useState`, and this dialog *unmounts* when the parent sets `showSendDialog=false` (Cancel/close). So the guard blocks only the **same-mount** repeat-Submit. A user who Cancels and re-opens the dialog while the backend is still down gets a fresh mount with Submit re-enabled, and a second submit *would* still double `contracts` (fresh `recId` → merge). Fully closing that remount vector requires the deterministic-`recId` change listed in Out-of-scope #1, which this cycle does not make. The guard is the right, cheap mitigation for the common case (double-click / immediate retry); it is not a categorical fix. Word the tests and DoD as "same-mount re-submit is blocked," never "the doubling is impossible."

**Mixed rejected+queued baskets.** Because the guard keys on `hasQueued` (not on `errors`), a basket containing *both* a hard-rejected row and a queued row will also disable Submit — so a pure-rejected basket keeps today's re-enabled retry, but a mixed basket does not. This is acceptable (with the backend down, retrying the rejected row is moot anyway), but state it rather than claiming blanket rejected-path parity.

### TDD steps — test convention

Same convention as Task 1: **real stores + `setState`, module-mock only `@/lib/api`.** `StockSendDialog` reads `usePortfolioStore` (`addPosition`) and `useSettingsStore` (`ibkrPaper.accountId/baseUrl`, `tradierPaper.token/accountId`, `:47-48`) — use the real stores (defaults are fine; the broker picker just shows those brokers as disabled, irrelevant to the `recommendation` path under test). It has no heavy child components to mock. Reset the portfolio store in `beforeEach` (`usePortfolioStore.setState({ positions: [] })`). Pending is driven by letting `fetch` fail in jsdom; the `'ok'` path by stubbing `global.fetch` to resolve `{ ok: true, json: async () => ({}) }`.

- [ ] **Step 2.1 (RED): Write the failing test first.**

Create `frontend/components/organisms/StockSendDialog/__tests__/StockSendDialog.pending.test.tsx`. Module-mock `@/lib/api`: `jest.mock('@/lib/api', () => ({ api: { getBrokerStatus: jest.fn().mockResolvedValue({}), postStockOrder: jest.fn() } }))`. Render with a **single** `PositionCardData` card (row defaults to `autoSend: true`; with `broker` left at its `'recommendation'` initial value, the auto-send branch falls through to the paper `addPosition` at `:106`, so it exercises the pending path — `postStockOrder` is not hit). **Use one card, not two**: `buildPaperStockPosition` gives both cards the same `PAPER-<ms>` `recId` in a tight loop, so a two-card test would collide `recId` and collapse the store to one row (`idxByRecId` replace path) — harmless to these assertions but muddies the scenario. Provide `onSubmit`/`onClose` jest fns. Wrap the click + resolution in `await act(async () => { ... })`.

For the pending case, use the **required** rejecting stub `global.fetch = jest.fn().mockRejectedValue(new Error('offline'))` so `addPosition` → `'pending'`. Assertions after clicking **Submit**:
1. `onSubmit` was **NOT** called (dialog did not report success).
2. A queued/will-sync caution note (`/queued|will sync/i`) is rendered for the affected row.
3. `onClose` was not auto-called (dialog stayed open).
4. The Submit button is now **disabled** (re-submit guard — proves *same-mount* re-submit is blocked; the remount vector is out of scope, see Out-of-scope #1).

Also add a companion happy-path test: stub `global.fetch` to resolve `{ ok: true, json: async () => ({}) }` so `addPosition` → `'ok'` → clicking Submit **does** call `onSubmit` (proves the backend-up path is untouched). Reset `global.fetch` between tests.

Run `npx jest StockSendDialog.pending` and confirm the pending test FAILS against current code (current code calls `onSubmit`, shows no queued note, and leaves Submit enabled).

- [ ] **Step 2.2 (GREEN): Implement the minimal change.**

In `frontend/components/organisms/StockSendDialog/index.tsx`:

1. Add queued state alongside `errors` (`:39`):
```tsx
const [queued, setQueued] = useState<Record<string, string>>({});
```

2. In `submit` (`:77-123`), reset and populate the queued bucket. At the top, alongside `setErrors({})` (`:80`), add `setQueued({})`. Build a local `q: Record<string, string> = {}`. At each of the two paper `addPosition` call sites (`:87-88` and `:106-107`), branch on pending:
```tsx
const res = await addPosition(buildPaperStockPosition(c.symbol, c.strategy.entry_price, r.shares));
if (res.status === 'rejected') errs[c.symbol] = res.detail ?? 'not saved';
else if (res.status === 'pending') q[c.symbol] = 'queued — backend unreachable, will sync';
```
(Apply to BOTH paper-add sites: the explicit-manual branch `:85-88` and the recommendation-fallback branch `:104-108`. The broker auto-send branch `:89-103` is an `api.postStockOrder` call, not `addPosition`, and keeps its own try/catch — do not touch it.)

3. Replace the terminal block (`:111-122`):
```tsx
setSubmitting(false);
setErrors(errs);
setQueued(q);

// Stay open on ANY unconfirmed row — hard rejections (red) OR queued/pending
// (caution). Only a fully-confirmed submit advances to onSubmit + close.
if (Object.keys(errs).length > 0 || Object.keys(q).length > 0) return;

const orders: StockDraftOrder[] = cards.map((c) => {
  const r = rows[c.symbol] ?? { shares: c.shares, autoSend: true };
  return { card: c, shares: Math.max(1, Math.round(r.shares)), autoSend: r.autoSend };
});
onSubmit(orders);
```

4. In the table body row render (`:192-225`), compute `const isQueued = !!queued[c.symbol];`, apply the caution row style, and render the queued note (in addition to the existing `hasErr` red note). Reuse the existing `.errCell` span (it is `grid-column: 1 / -1` and the `!hasErr` gate means the two notes never collide) — the only NEW css is `.rowQueued`; do not add a redundant `.queuedCell`.
```tsx
const hasErr   = !!errors[c.symbol];
const isQueued = !!queued[c.symbol];
// ...
<div key={c.symbol} className={`${styles.row} ${hasErr ? styles.rowErr : ''} ${isQueued ? styles.rowQueued : ''}`}>
  {/* ...existing cells... */}
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
</div>
```

5. **Re-submit guard (required).** Just before the `return` statement of the render, or inline in the footer, compute `const hasQueued = Object.keys(queued).length > 0;` and add it to the Submit button's `disabled` (currently `disabled={cards.length === 0 || submitting}`, `:244`):
```tsx
disabled={cards.length === 0 || submitting || hasQueued}
```
This blocks the *same-mount* backend-down repeat-Submit that would double `contracts` via the store's merge path. (See "Re-submit guard" and "Scope of the guard" in the design section above — it is not a categorical fix; a Cancel→reopen remount re-enables it.) A pure-rejected basket keeps today's re-enabled retry; a *mixed* rejected+queued basket is also disabled by `hasQueued` (acceptable — see the "Mixed rejected+queued" note above).

6. In `StockSendDialog.module.css`, add `.rowQueued` mirroring `.rowErr` but using the caution token (find the existing `.rowErr` rule and copy it, swapping the reject colour for `var(--caution)` via the same `color-mix` pattern the codebase uses — check how `.rowErr` references its colour and match it).

Run `npx jest StockSendDialog.pending` — confirm both tests now PASS.

---

## Task 3: step-4-stocks after-scan auto-execute — surface queued positions

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.tsx`

**Why in scope:** this is the third stock-mode `addPosition` caller with the identical `rejected`-only gap (`:161-166`). A `'pending'` auto-executed position is silently dropped from `failures`. Closing the two components while leaving this one open would make the plan's Goal false. The fix is small but must NOT reuse the red `error` banner for queued rows (that would mislabel a queued position as a failure).

**Behaviour:** collect queued symbols separately from `failures` and surface them via a distinct caution-tone notice, keeping the red `error` banner exclusively for genuine rejections and scan failures.

- [ ] **Step 3.1: Add a caution-tone `notice` state and populate it from the loop.**

1. Add state alongside `error` (`:108`): `const [notice, setNotice] = useState<string | null>(null);`
2. In `onRun`, reset it at the top next to `setError(null)` (`:153`): add `setNotice(null);`
3. In the after-scan loop (`:160-166`), collect queued symbols and branch on pending:
```tsx
const failures: string[] = [];
const queued: string[] = [];
for (const c of res.candidates) {
  if (afterScanArmedSymbols.has(c.symbol)) {
    const addRes = await addPosition(buildPaperStockPosition(c.symbol, c.strategy.entry_price, c.shares));
    if (addRes.status === 'rejected') failures.push(`${c.symbol}: ${addRes.detail ?? 'not saved'}`);
    else if (addRes.status === 'pending') queued.push(c.symbol);
  }
}
if (failures.length) {
  setError(`Some auto-executed positions were not saved — ${failures.join('; ')}`);
}
if (queued.length) {
  setNotice(`Queued — backend unreachable, will sync automatically: ${queued.join(', ')}`);
}
```
4. Render the notice next to the error line (`:241`), in caution tone:
```tsx
{error  && <Text size={12} tone="reject">{error}</Text>}
{notice && <Text size={12} tone="caution">{notice}</Text>}
```

**Why no new automated test here:** this page (`step-4-stocks`) has no existing test harness and pulls in the full scan pipeline, multiple stores, and `runStockScan`; standing up a render test for a two-branch string-surface change is disproportionate. The `addPosition` return contract it depends on is already directly covered by the Task 1/2 tests. Verify this one live in Step 4.2 (arm a symbol for after-scan, run a scan with the backend unreachable, confirm the caution notice — not the red banner — appears). If the environment can't run the scan live, this task's change is a mechanical mirror of Tasks 1–2 and is covered by typecheck.

---

## Task 4: Full frontend verification

- [ ] **Step 4.1: Typecheck + full Jest suite.**
```bash
cd frontend
npx jest 2>&1 | tail -5   # FIRST: capture the actual pre-change baseline on this branch
# ...then implement Tasks 1–2, then:
npm run typecheck         # must be clean
npx jest                  # full suite
```
Do **not** trust a remembered baseline figure — run `npx jest` once on the branch *before* writing the new tests and record the real "N passed" total, then confirm after the change that the total is `N + (new tests) passed` with zero previously-passing tests now failing. If any pre-existing test regresses, stop and treat it as a regression.

- [ ] **Step 4.2: Live browser verification of the pending path (the behaviour tests can't fully prove the UX).**

Use the Browser pane (`preview_start` with the `frontend` dev-server config, or start `npm run dev` and open `localhost:3001`). To simulate the backend being unreachable without stopping it, the cleanest lever is to make the POST fail: temporarily point `NEXT_PUBLIC_API_URL` at a dead port, OR block `/api/portfolio` in the browser devtools. Then:
  - **StockPositionCard**: run a stock scan → open a candidate's position card → click **Add to Portfolio**. Confirm the button reads **"Queued — will sync"** (not "Added to Portfolio") and the caution line appears. Confirm re-clicking does nothing.
  - **StockSendDialog**: pin ≥1 candidate to the basket → open the send dialog with broker = Recommendation → **Submit**. Confirm the dialog **stays open**, the row shows the caution "queued — will sync" note, Submit is now disabled, and it did NOT report success/close.
  - **step-4-stocks after-scan**: arm ≥1 candidate for after-scan, re-run the scan with the backend unreachable, and confirm the **caution** notice (not the red error banner) lists the queued symbol.
  - **Restore** `NEXT_PUBLIC_API_URL` / unblock the route, repeat once with the backend reachable, and confirm the happy path is unchanged (StockPositionCard → "Added to Portfolio"; StockSendDialog → closes).

Capture a screenshot of each queued state as proof. Skip this step's *proof capture* only if the environment genuinely cannot run the dev server, but still run the Jest suite in 4.1 regardless.

---

## Task 5: Update the stale in-code comment

- [ ] **Step 5.1: Correct the ChartWorkspace comment that describes this gap as open.**

`frontend/components/organisms/ChartWorkspace/index.tsx:845-846` currently reads:
```
// (StockPositionCard/StockSendDialog do NOT yet check res.status ===
// 'pending' — a separate, pre-existing gap, not this fix's scope.)
```
Update it to reflect that both now handle `'pending'` — e.g.:
```
// (StockPositionCard and StockSendDialog now handle res.status === 'pending'
// too — StockPositionCard shows a "Queued — will sync" state, StockSendDialog
// keeps the dialog open with a per-row queued note.)
```
Do not otherwise alter that block. Confirm `npm run typecheck` still clean (comment-only change, so it will be).

---

## Commit

- [ ] **Step 6: Commit on the feature branch.**

Only after Tasks 1–5 are done and Step 4.1 is green:
```bash
cd "F:/Git/GitHub/Trading assistant"
git add frontend/components/organisms/StockPositionCard/ \
        frontend/components/organisms/StockSendDialog/ \
        frontend/app/\(frame\)/screener/step-4-stocks/page.tsx \
        frontend/components/organisms/ChartWorkspace/index.tsx
git status --short   # confirm ONLY the intended files are staged
```
Commit message (body notes the entailed outcome-state reset and the two named out-of-scope follow-ups so the decision is on record):
```
fix(portfolio): surface queued (pending) adds across stock-mode addPosition callers

All three stock-mode consumers of addPosition previously treated a 'pending'
(backend-unreachable) result as success — StockPositionCard flipped to "Added to
Portfolio", StockSendDialog fired onSubmit and closed, and step-4-stocks'
after-scan loop silently dropped it — even though the backend never confirmed
the write. Now 'pending' is shown as a distinct queued state (caution tone,
"will sync"), matching the Step-7 trade-card and ChartWorkspace patterns.
StockSendDialog also disables Submit once any row is queued, preventing a
backend-down re-submit from doubling contracts via the store's merge path.
StockPositionCard resets its per-symbol outcome state (added/err/queued/orderId)
on symbol change. Updates the stale ChartWorkspace comment that described this
as an open gap.

Out of scope (named follow-ups): buildPaperStockPosition recId can collide
within a millisecond; the rejected-path double-add-on-retry in StockSendDialog
is left as-is for parity.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
Do NOT push yet — the K-adversarial-audit-loop runs a diff audit over this branch first; push/merge happens only after a clean audit round, per Kenneth's workflow.

---

## Definition of done

- [ ] `StockPositionCard` shows a distinct "Queued — will sync" state (caution, button disabled) on `status: 'pending'`, and no longer shows "Added to Portfolio" for an unconfirmed add.
- [ ] `StockSendDialog` records queued rows, keeps the dialog open, shows a per-row caution note, disables Submit (same-mount) when any row is queued, and does NOT call `onSubmit` when any row is queued or rejected.
- [ ] `step-4-stocks` after-scan auto-execute surfaces queued positions in a caution notice, distinct from the red error banner.
- [ ] The happy path (`status: 'ok'`) is **provably** unchanged for the two unit-tested components (StockPositionCard, StockSendDialog) and **live-verified** unchanged for step-4-stocks (no unit harness there — Task 3 rationale).
- [ ] New Jest tests cover pending/ok/rejected for StockPositionCard and pending/ok for StockSendDialog; full suite green; `npm run typecheck` clean.
- [ ] The stale ChartWorkspace comment is corrected.
- [ ] Committed on `fix/stock-add-pending-status-gap`, not pushed.
