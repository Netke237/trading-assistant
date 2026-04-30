# LLM Context — Excel Export (Workstream 15)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `frontend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates one new file (`frontend/lib/export.ts`), modifies one existing page (`step-4-ranking/page.tsx`), and adds one npm package. It does not touch any store, any CSS file, any other page, or the backend.

**Goal:**
Add a downloadable Excel export to the Step 4 ranked stock table. The user clicks "Export .xlsx" and gets a spreadsheet with one row per ranked candidate, matching the visible table columns. Uses the `xlsx` package (SheetJS community edition, already the most common Excel library in the JS ecosystem — no account or licence required).

**What NOT to touch:**
- Any file under `backend/`
- Any store (`lib/*.ts`) — read-only
- `step-4-ranking/page.module.css` — read-only
- Any other page or component

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `frontend/lib/export.ts` | **Create** | `exportToXlsx(rows, filename)` helper |
| `frontend/app/(frame)/screener/step-4-ranking/page.tsx` | **Modify** | Add "Export .xlsx" button that calls `exportToXlsx` |
| `frontend/package.json` | **Modify** | Add `xlsx` dependency |

---

## Section 3 — Read-only references

| File | Reason |
|---|---|
| `frontend/types/domain.ts` | `WatchlistRow` type — the input to `exportToXlsx` |
| `frontend/app/(frame)/screener/step-4-ranking/page.tsx` | Existing page — understand where to add the button |
| `frontend/app/(frame)/screener/step-4-ranking/page.module.css` | Verify CSS class names — do not add new classes |

---

## Section 4 — Domain type reference

```typescript
// frontend/types/domain.ts
export interface WatchlistRow {
  symbol:         string;
  company:        string;
  price:          number;
  direction:      'Bullish' | 'Bearish';
  horizon:        'Swing' | 'Position';
  score:          number;
  rankDelta:      number;
  scoreDelta?:    number;
  status:         Status;   // 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA'
  breakdown:      ScoreBreakdown;
  nextEventDays?: number;
  nextEventLabel?: string;
}

export interface ScoreBreakdown {
  trend:      number;
  pullback:   number;
  trigger:    number;
  event:      number;
  volatility: number;
}
```

---

## Section 5 — Implementation

### 5.1 Install `xlsx`

```bash
cd frontend
npm install xlsx@0.18.5
```

### 5.2 `frontend/lib/export.ts`

```typescript
import * as XLSX from 'xlsx';
import type { WatchlistRow } from '@/types/domain';

export function exportToXlsx(rows: WatchlistRow[], filename = 'ranked-stocks.xlsx'): void {
  const headers = [
    'Rank', 'Symbol', 'Company', 'Price', 'Direction', 'Horizon',
    'Score', 'Score Δ', 'Rank Δ', 'Status',
    'Trend', 'Pullback', 'Trigger', 'Event', 'Volatility',
    'Next Event', 'Next Event Label',
  ];

  const data = rows.map((row, i) => [
    i + 1,
    row.symbol,
    row.company,
    row.price,
    row.direction,
    row.horizon,
    row.score,
    row.scoreDelta ?? '',
    row.rankDelta,
    row.status,
    row.breakdown.trend,
    row.breakdown.pullback,
    row.breakdown.trigger,
    row.breakdown.event,
    row.breakdown.volatility,
    row.nextEventDays ?? '',
    row.nextEventLabel ?? '',
  ]);

  const ws = XLSX.utils.aoa_to_sheet([headers, ...data]);

  // Column widths
  ws['!cols'] = [
    { wch: 6 },  // Rank
    { wch: 8 },  // Symbol
    { wch: 22 }, // Company
    { wch: 8 },  // Price
    { wch: 10 }, // Direction
    { wch: 10 }, // Horizon
    { wch: 7 },  // Score
    { wch: 8 },  // Score Δ
    { wch: 7 },  // Rank Δ
    { wch: 9 },  // Status
    { wch: 7 },  // Trend
    { wch: 9 },  // Pullback
    { wch: 8 },  // Trigger
    { wch: 7 },  // Event
    { wch: 10 }, // Volatility
    { wch: 11 }, // Next Event
    { wch: 16 }, // Next Event Label
  ];

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Ranked Stocks');
  XLSX.writeFile(wb, filename);
}
```

### 5.3 `step-4-ranking/page.tsx` changes

**Add import** at the top of the import block:
```typescript
import { exportToXlsx } from '@/lib/export';
```

**Add export button** in the JSX — place it in the step header area, to the right of the step title. Look for the existing `<Title>` element for "Ranked Candidates" and add the button alongside it.

Find this pattern in the existing JSX (approximate — verify exact JSX before editing):
```tsx
<Title as="h2" size={18}>Ranked Candidates</Title>
```

Add a button immediately after it:
```tsx
<button
  className={styles.exportBtn}
  onClick={() => exportToXlsx(rows, 'ranked-stocks.xlsx')}
  type="button"
>
  Export .xlsx
</button>
```

Where `rows` is the existing array of `WatchlistRow` items already in the component's state/data.

**Do NOT add a new CSS class.** Check if `styles.exportBtn` already exists in `page.module.css`. If it does not exist, use an inline style one-off — this is the one legitimate case for an inline style:

```tsx
<button
  style={{ marginLeft: 'var(--space-3)', fontSize: 12, cursor: 'pointer' }}
  onClick={() => exportToXlsx(rows, 'ranked-stocks.xlsx')}
  type="button"
>
  Export .xlsx
</button>
```

---

## Section 6 — CSS tokens (reference only)

```css
--space-1:  4px;  --space-2:  8px;  --space-3:  12px; --space-4:  16px;
--space-5:  20px; --space-6:  24px; --space-8:  32px;
--radius-sm: 4px; --radius-md: 6px;
--text-primary:     #D1D4DC;
--text-secondary:   #787B86;
--bg-surface-2:     #252B43;
--border-subtle:    #2A2E42;
```

---

## Section 7 — Task spec

### Acceptance criteria

1. Clicking "Export .xlsx" in Step 4 triggers a browser file download named `ranked-stocks.xlsx`.
2. The downloaded file opens in Excel/LibreOffice with 17 header columns matching the spec in Section 5.2.
3. One row per ranked candidate, in the same order as shown in the table.
4. `npm run typecheck` is clean after all changes.
5. The button is visible and styled consistently with the rest of the page (no garish styling).

### Verify

```bash
cd frontend
npm run typecheck
# Expected: 0 errors
```

Then open `http://localhost:3001/screener/step-4-ranking`, click "Export .xlsx", confirm download.

---

## Section 8 — Hard rules

1. Do NOT use Tailwind, styled-components, or CSS-in-JS.
2. Do NOT add new CSS classes to `page.module.css` unless strictly necessary. Prefer the inline one-off style for the button.
3. Do NOT touch any store, schema, or backend file.
4. Do NOT use `xlsx` version above `0.18.5` — the library has licensing changes in later versions.
5. `npm run typecheck` must be clean before committing.

---

## Section 9 — Dev workflow

```bash
cd frontend
npm install xlsx@0.18.5
npm run typecheck
npm run dev   # verify at http://localhost:3001/screener/step-4-ranking
```

---

## Section 10 — Copy/paste prompt

```
Read `llm-contexts/15-excel-export.md` fully before writing any code.
It is your single source of truth.

You are adding Excel export to the Bamendjou options screener
(Next.js 15, TypeScript strict, CSS Modules).

Your owned files:
  - frontend/lib/export.ts                                              (CREATE)
  - frontend/app/(frame)/screener/step-4-ranking/page.tsx              (MODIFY)
  - frontend/package.json                                               (MODIFY)

Do not modify any file outside this list.

Task: Create exportToXlsx() in lib/export.ts and add an "Export .xlsx"
button to the Step 4 ranking page that calls it.

After every file edit, run `npm run typecheck` from `frontend/`. Must stay clean.
Commit after all changes are complete.
```
