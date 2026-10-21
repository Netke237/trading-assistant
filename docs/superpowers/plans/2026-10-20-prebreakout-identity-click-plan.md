# Pre-Breakout Identity-Cell Selection Click Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow clicking whitespace inside the Symbol/Company identity cell on Pre-Breakout screener candidate rows to select the candidate, while preserving control isolation for WatchStar and Chart buttons (#364).

**Architecture:** Remove `event.stopPropagation()` from the `styles.identity` container div in `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx` so non-button clicks bubble to `selectionProps(row.symbol).onClick`. Add explicit `event.stopPropagation()` to the chart button.

**Tech Stack:** Next.js 15, React 19, TypeScript, Jest, React Testing Library.

**Spec / Issue:** Issue #364 (`Pre-Breakout identity-cell whitespace swallows candidate selection clicks`), originating from audit phase #353 / #358.

## Global Constraints
- Node/TypeScript: strict typing, clean `npm run typecheck` (`tsc --noEmit`).
- No changes to scoring algorithms, pricing, or persisted state.
- Button controls (`WatchStar`, `chartBtn`, `alertBtn`) must maintain independent action handling and not trigger candidate selection.
- All three sub-modes (`pullback`, `fib`, `prebreakout`) share the `identity(row)` helper and must support whitespace clicking.

---

## Target & Problem Statement
- **Issue**: #364 (`Pre-Breakout identity-cell whitespace swallows candidate selection clicks`)
- **Phase ID**: `APP-AUDIT-PREBREAKOUT-IDENTITY-CLICK`
- **Location**: `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx:237-241`
- **Root Cause**:
  `const identity = (row: ...) => <div className={styles.identity} aria-label={`Identity for ${row.symbol}`} onClick={event => event.stopPropagation()}>`
  The `onClick={event => event.stopPropagation()}` handler on the identity cell wrapper intercepts all pointer events. While `styles.identityText` had an inner `onClick={() => setSelectedSymbol(row.symbol)}`, any click on cell whitespace (around the text, between controls, or cell padding) was stopped before reaching the row's `selectionProps(row.symbol).onClick`.
- **Expected Behavior**:
  1. Pointer click on any non-control whitespace within the identity cell selects the candidate (`selectedSymbol === symbol`, `aria-pressed="true"`, selected setup chart renders).
  2. Pointer click on `WatchStar` toggles watchlist status and does NOT select candidate.
  3. Pointer click on `chartBtn` opens chart tab and does NOT select candidate.
  4. Pointer click on `alertBtn` opens alert modal and does NOT select candidate.
  5. Keyboard interaction (Enter / Space on row) continues to work.

---

## Detailed Implementation Plan

### Task 1: Fix Identity Cell Event Propagation in `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`

- [ ] **Step 1: Remove `onClick={event => event.stopPropagation()}` on `styles.identity` container**
  In `identity(row)`:
  ```tsx
  const identity = (row: BacktestArtifactReference & {symbol: string; company?: string}) => (
    <div className={styles.identity} aria-label={`Identity for ${row.symbol}`}>
      <WatchStar symbol={row.symbol} size="sm" />
      <button
        type="button"
        className={styles.chartBtn}
        title="Open in Chart"
        aria-label={`Open ${row.symbol} chart in a new tab`}
        onClick={event => {
          event.stopPropagation();
          window.open(buildCandidateChartHref(row, scanMode), '_blank');
        }}
      >
        ↗
      </button>
      <div className={styles.identityText} onClick={() => setSelectedSymbol(row.symbol)}>
        <Text size={13} weight={500}>{row.symbol}</Text>
        <Text size={11} tone="dim">
          {row.company || (selectedContext.live?.data.symbol === row.symbol ? selectedContext.live.data.company : null) || 'Company unavailable'}
        </Text>
      </div>
    </div>
  );
  ```
  - `styles.identity` no longer stops propagation.
  - Clicks on whitespace bubble to `<div {...selectionProps(row.symbol)} className={...}>`.
  - `selectionProps(symbol).onClick` checks `if (!(event.target as HTMLElement).closest('button')) setSelectedSymbol(symbol);`, correctly invoking `setSelectedSymbol(symbol)` when whitespace or non-button elements are clicked.
  - `chartBtn` explicitly stops event propagation on click (`event.stopPropagation()`), ensuring no row selection occurs when opening the chart.
  - `WatchStar` already calls `e.stopPropagation()` in `components/atoms/WatchStar/index.tsx`.

---

### Task 2: Component Regression Suite in `frontend/app/(frame)/screener/step-4-prebreakout/__tests__/PreBreakoutIdentityClick.test.tsx`

**Files:**
- Create: `frontend/app/(frame)/screener/step-4-prebreakout/__tests__/PreBreakoutIdentityClick.test.tsx`

- [ ] **Step 1: Write comprehensive pointer interaction tests**
  - Render `PreBreakout` page with mocked scan results for `pullback`, `fib`, and `prebreakout` modes.
  - Verify clicking `aria-label="Identity for <SYMBOL>"` container element directly (simulating cell whitespace click) sets `aria-pressed="true"` on the candidate row and displays the selected symbol in "Selected setup".
  - Verify clicking `WatchStar` does NOT select the candidate (row remains `aria-pressed="false"`).
  - Verify clicking `chartBtn` does NOT select the candidate.
  - Verify clicking `alertBtn` opens alert modal and does NOT select the candidate.
  - Verify keyboard Enter/Space continues to select the candidate.

---

## Gate & Risk Analysis
- **Wrong Numbers**: None. This is purely a UI pointer event bubbling fix in table cell rendering. No score, indicator, price, or sizing computation is modified.
- **Corrupt Persisted Data**: None. No persisted Zustand stores or localStorage keys are touched.
- **Scope**: Exactly 1 production file (`page.tsx`) and 1 test file.

---

## Verification Steps
1. Run `npm run test -- frontend/app/(frame)/screener/step-4-prebreakout/__tests__/PreBreakoutIdentityClick.test.tsx`
2. Run `npm run typecheck` (`tsc --noEmit`).
3. Run `python scripts/state.py` to confirm zero drift.
