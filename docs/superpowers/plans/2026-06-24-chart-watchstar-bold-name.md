# Chart WatchStar + Bold Company Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Display the company name in bold inside the watchlist inline chart panel header, and (2) add a WatchStar toggle to the left of the symbol search box in `ChartTopBar` so any stock analysed on the chart page can be added to / removed from the watchlist, behaving identically to the star on the screener Step 4 table.

**Architecture:** Both changes are purely additive UI edits with no new state, no new API calls, and no new stores. `WatchStar` already writes to `useWatchlistStore` and calls `api.addWatchlist` / `api.removeWatchlist` with optimistic rollback — dropping it into `ChartTopBar` gives full watchlist behaviour for free. The bold-name fix is a single `weight` prop change on the `<Text>` primitive that renders the `label` prop in `ChartPanelHeader`; `label` receives the company name from `InlineChartPanel` (which already wires `companyName` → `label` as of the prior session).

**Tech Stack:** Next.js 15, TypeScript 5.7, CSS Modules, Zustand v5, `@testing-library/react`, Jest.

**Test note:** `styleMock.js` returns `{}`, so all CSS Module class names resolve to `undefined` in jsdom — `toHaveStyle()` and class-name assertions for weight/size WILL NOT work. Tests verify content and structure only; visual weight is enforced by TypeScript (`weight` on `<Text>` accepts `400 | 500 | 600`).

---

## File map

| File | Change |
|---|---|
| `frontend/components/molecules/ChartPanelHeader/index.tsx` | `weight={500}` → `weight={600}` on the `<Text>` that renders `{label}` (line 19) |
| `frontend/components/molecules/ChartPanelHeader/__tests__/ChartPanelHeader.test.tsx` | New — verifies label and symbol render correctly |
| `frontend/components/organisms/ChartTopBar/index.tsx` | Import `WatchStar`; add `<WatchStar symbol={symbol} size="sm" />` as first child of `.bar`, before `<input>` |
| `frontend/components/organisms/ChartTopBar/__tests__/ChartTopBar.test.tsx` | New — verifies WatchStar is present and precedes the input in the DOM |

---

### Task 1: Bold company name in ChartPanelHeader

The `ChartPanelHeader` `label` prop receives the company name from `InlineChartPanel` via:
```
watchlist onSelect → setChartSymbolName(company) → InlineChartPanel companyName prop → ChartPanelHeader label prop → <Text>{label}</Text>
```
Changing `weight={500}` → `weight={600}` on that `<Text>` makes the company name bold.

**Files:**
- Modify: `frontend/components/molecules/ChartPanelHeader/index.tsx:19`
- Test: `frontend/components/molecules/ChartPanelHeader/__tests__/ChartPanelHeader.test.tsx`

- [ ] **Step 1: Create the `__tests__` directory and write the test**

The `__tests__` directory does not yet exist — create it first:

```bash
mkdir "frontend/components/molecules/ChartPanelHeader/__tests__"
```

Then create `frontend/components/molecules/ChartPanelHeader/__tests__/ChartPanelHeader.test.tsx`:

```tsx
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { ChartPanelHeader } from '@/components/molecules/ChartPanelHeader';

// WatchStar uses Zustand + api — isolate ChartPanelHeader
jest.mock('@/components/atoms/WatchStar', () => ({
  WatchStar: ({ symbol }: { symbol: string }) => (
    <button aria-label={`Add ${symbol} to watchlist`} />
  ),
}));

// IconButton is a thin wrapper — mock to avoid any import side-effects
jest.mock('@/components/atoms/IconButton', () => ({
  IconButton: ({
    children,
    onClick,
    ...rest
  }: React.HTMLAttributes<HTMLButtonElement>) => (
    <button onClick={onClick} {...rest}>{children}</button>
  ),
}));

describe('ChartPanelHeader', () => {
  it('renders the company name text', () => {
    render(
      <ChartPanelHeader
        symbol="MSFT"
        label="Microsoft Corp"
        onClose={() => {}}
      />
    );
    expect(screen.getByText('Microsoft Corp')).toBeInTheDocument();
  });

  it('renders the ticker symbol', () => {
    render(
      <ChartPanelHeader
        symbol="MSFT"
        label="Microsoft Corp"
        onClose={() => {}}
      />
    );
    expect(screen.getByText('MSFT')).toBeInTheDocument();
  });

  it('falls back to "Chart" when label prop is omitted', () => {
    render(<ChartPanelHeader symbol="AAPL" onClose={() => {}} />);
    expect(screen.getByText('Chart')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to confirm it passes against current code**

```bash
cd frontend && npm test -- --testPathPattern=ChartPanelHeader 2>&1 | tail -15
```

Expected: all 3 tests PASS. (These are not "fail-first" TDD tests because they verify content rendering — the change being made is visual. The tests serve as a regression guard.)

- [ ] **Step 3: Change weight from 500 to 600**

In `frontend/components/molecules/ChartPanelHeader/index.tsx` line 19, change:

```tsx
// Before
<Text size={14} weight={500}>{label}</Text>

// After
<Text size={14} weight={600}>{label}</Text>
```

`TextWeight` is typed as `400 | 500 | 600` (confirmed in `Text.tsx:14`) so this is a valid prop value. The rule "No font-weight 600 on form labels" in CLAUDE.md does not apply here — `label` is a panel header title displaying the company name, not a form label.

- [ ] **Step 4: Run tests to confirm they still pass**

```bash
cd frontend && npm test -- --testPathPattern=ChartPanelHeader 2>&1 | tail -10
```

Expected: PASS — 3 tests pass.

- [ ] **Step 5: Typecheck**

```bash
cd frontend && npm run typecheck 2>&1
```

Expected: no output (clean).

- [ ] **Step 6: Commit**

```bash
git add "frontend/components/molecules/ChartPanelHeader/index.tsx" "frontend/components/molecules/ChartPanelHeader/__tests__/ChartPanelHeader.test.tsx"
git commit -m "feat(chart): bold company name in InlineChartPanel header"
```

---

### Task 2: WatchStar in ChartTopBar

`WatchStar` is a self-contained atom: it reads from `useWatchlistStore`, renders a filled/hollow star, and on click calls `api.addWatchlist` or `api.removeWatchlist` with optimistic rollback. Placing it before the `<input>` in `ChartTopBar` requires only an import and a JSX line.

The project's established test pattern (confirmed in `RunScanButton.test.tsx`) is to call `useStore.setState({...})` directly rather than mocking the store module.

**Files:**
- Modify: `frontend/components/organisms/ChartTopBar/index.tsx`
- Test: `frontend/components/organisms/ChartTopBar/__tests__/ChartTopBar.test.tsx`

- [ ] **Step 1: Create the `__tests__` directory and write the failing test**

The `__tests__` directory does not yet exist — create it first:

```bash
mkdir "frontend/components/organisms/ChartTopBar/__tests__"
```

Then create `frontend/components/organisms/ChartTopBar/__tests__/ChartTopBar.test.tsx`:

```tsx
import '@testing-library/jest-dom';
import { render, screen, act } from '@testing-library/react';
import ChartTopBar from '@/components/organisms/ChartTopBar';
import { useChartStore } from '@/lib/chartStore';

// Mock WatchStar atom to avoid watchlist store + api deps in this test
jest.mock('@/components/atoms/WatchStar', () => ({
  WatchStar: ({ symbol }: { symbol: string }) => (
    <button data-testid="watch-star" aria-label={`Add ${symbol} to watchlist`} />
  ),
}));

// Mock api — ChartTopBar fires getSymbolInfo on mount
jest.mock('@/lib/api', () => ({
  api: {
    getSymbolInfo: jest.fn().mockResolvedValue({ symbol: 'AAPL', name: 'Apple Inc.' }),
  },
}));

beforeEach(() => {
  // Set chart store state directly (project pattern: useStore.setState, cast as any for partial)
  useChartStore.setState({
    symbol: 'AAPL',
    symbolName: 'Apple Inc.',
    interval: '1D',
    chartType: 'candle',
  } as any);
});

describe('ChartTopBar', () => {
  const noop = () => {};

  it('renders WatchStar for the active symbol', async () => {
    await act(async () => {
      render(<ChartTopBar onToggleIndicators={noop} onToggleStructure={noop} />);
    });
    const star = screen.getByTestId('watch-star');
    expect(star).toBeInTheDocument();
    expect(star).toHaveAttribute('aria-label', 'Add AAPL to watchlist');
  });

  it('renders WatchStar before the symbol input in the DOM', async () => {
    await act(async () => {
      render(<ChartTopBar onToggleIndicators={noop} onToggleStructure={noop} />);
    });
    const input = screen.getByRole('textbox', { name: 'Symbol' });
    const bar = input.parentElement!;
    const children = Array.from(bar.children);
    const starIdx  = children.findIndex(
      (el) => el.getAttribute('data-testid') === 'watch-star',
    );
    const inputIdx = children.indexOf(input);
    expect(starIdx).toBeGreaterThanOrEqual(0);
    expect(inputIdx).toBeGreaterThanOrEqual(0);
    expect(starIdx).toBeLessThan(inputIdx);
  });
});
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd frontend && npm test -- --testPathPattern=ChartTopBar 2>&1 | tail -20
```

Expected: FAIL — `Unable to find an element by: [data-testid="watch-star"]`.

- [ ] **Step 3: Add WatchStar to ChartTopBar**

In `frontend/components/organisms/ChartTopBar/index.tsx`:

**Add import** (after existing imports, before `const INTERVALS`):
```tsx
import { WatchStar } from '@/components/atoms/WatchStar';
```

**Add WatchStar** as the very first child inside `<div className={styles.bar}>`, directly before `<input>`:
```tsx
// Before (the bar's opening is currently):
    <div className={styles.bar}>
      <input
        className={styles.symbolInput}
        defaultValue={symbol}
        key={symbol}
        onKeyDown={handleSymbolKeyDown}
        onBlur={(e) => setSymbol(e.target.value.toUpperCase().trim())}
        aria-label="Symbol"
      />

// After:
    <div className={styles.bar}>
      <WatchStar symbol={symbol} size="sm" />
      <input
        className={styles.symbolInput}
        defaultValue={symbol}
        key={symbol}
        onKeyDown={handleSymbolKeyDown}
        onBlur={(e) => setSymbol(e.target.value.toUpperCase().trim())}
        aria-label="Symbol"
      />
```

No CSS changes needed — `.bar` already uses `display: flex; gap: 6px; align-items: center;` (confirmed in `ChartTopBar.module.css`). The 6px gap separates WatchStar from the input automatically; `WatchStar` manages its own internal size via the `size="sm"` prop (12px icon).

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd frontend && npm test -- --testPathPattern=ChartTopBar 2>&1 | tail -10
```

Expected: PASS — 2 tests pass.

- [ ] **Step 5: Run full test suite for regressions**

```bash
cd frontend && npm test -- --passWithNoTests 2>&1 | tail -10
```

Expected: all existing tests pass.

- [ ] **Step 6: Typecheck**

```bash
cd frontend && npm run typecheck 2>&1
```

Expected: no output (clean).

- [ ] **Step 7: Commit**

```bash
git add "frontend/components/organisms/ChartTopBar/index.tsx" "frontend/components/organisms/ChartTopBar/__tests__/ChartTopBar.test.tsx"
git commit -m "feat(chart): add WatchStar left of symbol search box in ChartTopBar"
```

---

## Self-review checklist

| Requirement | Covered by |
|---|---|
| Company name displayed bold in inline chart panel | Task 1 — `weight={500}` → `weight={600}` on `<Text>{label}</Text>` |
| WatchStar on left of search box on chart | Task 2 — `<WatchStar>` before `<input>` |
| Add/remove from watchlist (same behaviour as Step 4) | Free via `WatchStar` atom — same atom used everywhere |
| Stock behaves like any other watchlist stock | `api.addWatchlist` persists to backend; watchlist page reads `syncFromBackend` |
| No new stores, no new API endpoints | Confirmed — reuses existing infrastructure |
| Typecheck clean | Steps 5 and 6 in each task |
| Tests exist for both changes | ChartPanelHeader.test.tsx, ChartTopBar.test.tsx |
| Commits are atomic | Separate commit per task |
| `toHaveStyle` avoided (CSS Modules return `{}` in Jest) | Replaced with content/structure assertions |
| Store mocking uses project's `setState` pattern | Task 2 uses `useChartStore.setState({...})` |
| Async `useEffect` handled | Task 2 wraps renders in `act(async () => {...})` |
