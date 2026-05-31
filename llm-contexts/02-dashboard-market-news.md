# LLM Context — Stream B: Dashboard Market News Card (CR-04)

**Workstream:** CR-04 — Add a "Market News" card to the Dashboard for broad market symbols (SPY, QQQ, VIX, DIA).
**Conflict class:** Zero conflict — all changes are within the dashboard folder plus one new import. No shared stores, no shared organisms modified.

---

## 1. Mission

Add a new "Market News" `SectionCard` to the Dashboard page that fetches and displays market news for the symbols `SPY`, `QQQ`, `VIX`, `DIA` via the existing `GET /api/news?symbols=...` endpoint. Reuse the existing `NewsCard` molecule (already built). Do not modify any component outside the dashboard folder.

**The single most important constraint:** Do NOT touch any file outside the owned-files list below. The `NewsCard` molecule and `SectionCard` molecule already exist — import them, do not recreate them.

---

## 2. Owned files

| File path | Status | Purpose |
|---|---|---|
| `frontend/app/(frame)/dashboard/page.tsx` | Modify | Add market news state + fetch + render new SectionCard |
| `frontend/app/(frame)/dashboard/page.module.css` | Modify | Add `.marketNews` layout class for the new card row |

---

## 3. Read-only references

| File | Why |
|---|---|
| `frontend/components/molecules/NewsCard/index.tsx` | Reuse this molecule — read props interface before importing |
| `frontend/components/molecules/SectionCard/index.tsx` | Reuse this molecule — read props interface before importing |
| `frontend/lib/api.ts` | `api.getNews(symbols: string[])` — exact signature |
| `frontend/types/domain.ts` | `NewsItem` type — needed for state typing |
| `frontend/styles/tokens.css` | All CSS variables — full list in Section 5 below |

---

## 4. Integration constraints

### `api.getNews`
```ts
// From frontend/lib/api.ts:
getNews: (symbols: string[]) => get<NewsItem[]>(
  `/api/news?symbols=${symbols.map(encodeURIComponent).join(',')}`
)

// Call with fixed market symbols:
api.getNews(['SPY', 'QQQ', 'VIX', 'DIA'])
```
Returns `NewsItem[]`. Throws on non-2xx. Handle with `.catch(() => setMarketNewsError(true))`.

### `NewsCard` molecule
```tsx
// From frontend/components/molecules/NewsCard/index.tsx:
interface NewsCardProps {
  items: NewsItem[];
  loading?: boolean;
}

// Import:
import { NewsCard } from '@/components/molecules/NewsCard';

// Usage:
<NewsCard items={marketNews} loading={marketNewsLoading} />
```
Renders a loading skeleton when `loading={true}`, "No news" text when `items` is empty, and a list of news items otherwise.

### `SectionCard` molecule
```tsx
// Props (read the actual file to confirm — this is the expected interface):
interface SectionCardProps {
  title: string;
  count?: number;
  action?: { label: string; onClick: () => void };
  children: React.ReactNode;
}

// Import:
import { SectionCard } from '@/components/molecules/SectionCard';
```

### Existing dashboard state pattern — follow this exactly:
```ts
// All existing state + fetches in DashboardPage follow this pattern:
const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
// ...
useEffect(() => {
  api.getWatchlist().then(setWatchlist).catch(() => setOffline(true));
  // ...
}, []);
```
Add market news state + fetch using the same pattern.

### Error handling
The existing dashboard uses `setOffline(true)` for all fetch failures. For market news, use a **separate** `marketNewsError` boolean state — do not couple it to `offline`. The `offline` state is for mandatory data (regime, alerts, watchlist). Market news is supplemental.

---

## 5. CSS tokens (full list)

```css
/* Dark theme (default) */
--bg-base:          #131722;
--bg-surface:       #1E2335;
--bg-surface-2:     #252B43;
--bg-surface-3:     #2A3152;
--border-subtle:    #2A2E42;
--border-strong:    #363B54;
--text-primary:     #D1D4DC;
--text-secondary:   #787B86;
--text-dim:         #434651;
--pass:             #26A69A;
--pass-bg:          #0D201F;
--pass-border:      #1A3533;
--caution:          #F59F00;
--caution-bg:       #1F1A0D;
--caution-border:   #352E1A;
--reject:           #EF5350;
--reject-bg:        #1F0E0D;
--reject-border:    #352020;
--neutral:          #4A5568;
--neutral-bg:       #1A202C;
--accent:           #2962FF;
--accent-hover:     #1E53E5;
--accent-dim:       #142B7A;
--accent-text:      #FFFFFF;
--space-1:  4px;
--space-2:  8px;
--space-3:  12px;
--space-4:  16px;
--space-5:  20px;
--space-6:  24px;
--space-8:  32px;
--space-12: 48px;
--radius-sm: 4px;
--radius-md: 6px;
--radius-lg: 10px;

/* Light theme overrides */
--bg-base:        #F0F3FA;
--bg-surface:     #FFFFFF;
--bg-surface-2:   #F5F7FF;
--bg-surface-3:   #EBF0FF;
--border-subtle:  #DDE1F0;
--border-strong:  #C5CCE6;
--text-primary:   #131722;
--text-secondary: #5A6070;
--text-dim:       #9BA3B8;
--reject:         #D32F2F;
--reject-bg:      #FEECEC;
--reject-border:  #F5BCBC;
```

---

## 6. Primitives & component reference

```tsx
<Text size={11|12|13|14} tone="primary|secondary|dim|pass|caution|reject" weight={400|500|600} />
<Title as="h1|h2|h3" size={18|20|24} />
<Data size={11|12|13|14|16|18|20|24} weight={500|600} tone="pass|caution|reject" />
```

- `<Text>` default: `size=13`, `tone="primary"`, `weight=400`
- No font-weight 600 on form labels
- No card shadows — `border: 1px solid var(--border-subtle)` (SectionCard already handles this)
- Status tints: `color-mix(in srgb, var(--reject) 10%, var(--bg-surface))`

---

## 7. Domain types (relevant subset)

```ts
// From frontend/types/domain.ts:
export type NewsSentiment = 'bull' | 'bear' | 'neutral';

export interface NewsItem {
  id:        string;
  symbol:    string;     // e.g. "SPY"
  headline:  string;
  source:    string;
  timestamp: string;     // ISO timestamp
  sentiment: NewsSentiment;
}
```

---

## 8. Zustand stores

No store reads or writes for this workstream. The market news data is purely component-local state (`useState`).

---

## 9. Mock data — what the API returns for market symbols

When backend is running, `GET /api/news?symbols=SPY,QQQ,VIX,DIA` returns a `NewsItem[]`. When backend is offline, the fetch throws and `marketNewsError` becomes `true`.

The `NewsCard` molecule handles all display states automatically:
- `loading={true}` → shows 3 skeleton bars
- `items.length === 0` → shows "No news for current candidates."
- `items.length > 0` → shows news list with sentiment accent bars

---

## 10. Task spec

### What to build

Add one new section to `DashboardPage` showing market news for `['SPY', 'QQQ', 'VIX', 'DIA']`.

### Step-by-step changes to `frontend/app/(frame)/dashboard/page.tsx`

**1. Add state variables** (alongside existing state declarations, after line ~51):
```ts
const [marketNews, setMarketNews]           = useState<NewsItem[]>([]);
const [marketNewsLoading, setMarketNewsLoading] = useState(false);
const [marketNewsError, setMarketNewsError] = useState(false);
```

**2. Add fetch** in the first `useEffect` (the one that fetches regime, watchlist, alerts — around line 67):
```ts
setMarketNewsLoading(true);
api.getNews(['SPY', 'QQQ', 'VIX', 'DIA'])
  .then(setMarketNews)
  .catch(() => setMarketNewsError(true))
  .finally(() => setMarketNewsLoading(false));
```

**3. Add import** for `NewsCard` at the top of the file:
```ts
import { NewsCard } from '@/components/molecules/NewsCard';
```

**4. Add the new section** after the closing `</div>` of `.bento2` and before `<RunScanButton />`:
```tsx
<div className={styles.marketNews}>
  <SectionCard title="Market News" count={marketNews.length}>
    {marketNewsError && !marketNewsLoading
      ? <Text size={12} tone="reject">Market news unavailable — backend offline?</Text>
      : <NewsCard items={marketNews} loading={marketNewsLoading} />}
  </SectionCard>
</div>
```

### Changes to `frontend/app/(frame)/dashboard/page.module.css`

Add at the end of the file:
```css
/* Market news — full-width row below bento2 */
.marketNews {
  display: grid;
  grid-template-columns: 1fr;
}
```

### Acceptance criteria

- The "Market News" card appears below the "News — watchlist" + "Contracts" row on the Dashboard.
- While loading, `NewsCard` shows skeleton bars.
- When backend is running and returns news for SPY/QQQ/VIX/DIA, headlines appear with sentiment accent bars.
- When backend is offline, card shows reject-tone error message (not a silent empty state).
- When backend returns no news (empty array), card shows "No news for current candidates." (NewsCard's built-in empty state).
- The existing "News — watchlist" card is unchanged.
- `tsc --noEmit` clean.

---

## 11. Hard rules

1. **No Tailwind, no styled-components, no CSS-in-JS.**
2. **No `style={{}}` except computed one-offs.**
3. **No hardcoded colors** — always CSS custom properties from the token list in Section 5.
4. **No invented Status labels** — only `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. **No card shadows** — `SectionCard` already uses `border: 1px solid var(--border-subtle)`.
6. **Never skip atom → molecule → organism hierarchy.** `NewsCard` is a molecule — use it inside the `SectionCard` organism wrapper.
7. **`npm run typecheck` must be clean after every file edit.**
8. **Do not modify any file outside the owned-files list** (Section 2). Do NOT touch `NewsCard/index.tsx`, `SectionCard/index.tsx`, or any other component.
9. **Do NOT commit.** Produce a completion report for Kenneth to review.

---

## 12. Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001 — keep running while editing
npm run typecheck    # run after EVERY file edit — must stay at 0 errors
```

---

## 12a. Playwright test file (write this before running)

**The tests use Playwright's `route` API to mock the backend — no real backend needed.**

**Create this file exactly as written:**
`frontend/e2e/ws-b-dashboard-market-news.spec.ts`

```typescript
import { test, expect } from '@playwright/test';

const MARKET_NEWS_MOCK = [
  {
    id: 'mn1',
    symbol: 'SPY',
    headline: 'S&P 500 holds gains as Fed signals pause',
    source: 'Reuters',
    timestamp: new Date().toISOString(),
    sentiment: 'bull' as const,
  },
  {
    id: 'mn2',
    symbol: 'QQQ',
    headline: 'Nasdaq tech sector mixed in early trade',
    source: 'Bloomberg',
    timestamp: new Date().toISOString(),
    sentiment: 'neutral' as const,
  },
  {
    id: 'mn3',
    symbol: 'VIX',
    headline: 'Volatility index retreats from recent highs',
    source: 'MarketWatch',
    timestamp: new Date().toISOString(),
    sentiment: 'bear' as const,
  },
];

// Stub all non-news API calls to prevent network errors
async function stubBaseApis(page: import('@playwright/test').Page) {
  await page.route('**/api/watchlist', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/alerts',    (r) => r.fulfill({ json: [] }));
  await page.route('**/api/regime',    (r) => r.fulfill({
    json: { overall: 'PASS', headline: 'Test regime', metrics: [] },
  }));
  await page.route('**/api/portfolio', (r) => r.fulfill({ json: [] }));
}

test.describe('WS-B: Dashboard Market News Card (CR-04)', () => {

  test('Market News card is visible on dashboard', async ({ page }) => {
    await stubBaseApis(page);
    // News for market symbols
    await page.route('**/api/news*', async (route) => {
      const url = route.request().url();
      if (url.includes('SPY') && url.includes('QQQ')) {
        await route.fulfill({ json: MARKET_NEWS_MOCK });
      } else {
        await route.fulfill({ json: [] });
      }
    });
    await page.goto('/');
    await expect(page.getByText('Market News')).toBeVisible();
    await page.screenshot({ path: 'e2e/screenshots/ws-b-market-news-card.png', fullPage: true });
  });

  test('Market News card shows headlines from SPY/QQQ/VIX/DIA', async ({ page }) => {
    await stubBaseApis(page);
    await page.route('**/api/news*', async (route) => {
      const url = route.request().url();
      if (url.includes('SPY') && url.includes('QQQ')) {
        await route.fulfill({ json: MARKET_NEWS_MOCK });
      } else {
        await route.fulfill({ json: [] });
      }
    });
    await page.goto('/');
    await expect(page.getByText('S&P 500 holds gains as Fed signals pause')).toBeVisible();
    await expect(page.getByText('Nasdaq tech sector mixed in early trade')).toBeVisible();
  });

  test('Market News card shows error message when API fails — not silent', async ({ page }) => {
    await stubBaseApis(page);
    await page.route('**/api/news*', async (route) => {
      const url = route.request().url();
      // Fail only the market symbols call; pass the watchlist call
      if (url.includes('SPY') && url.includes('QQQ')) {
        await route.abort('failed');
      } else {
        await route.fulfill({ json: [] });
      }
    });
    await page.goto('/');
    // Must show explicit error — not blank, not "No news"
    await expect(page.getByText(/unavailable/i)).toBeVisible();
    // Must NOT silently show "No news for current candidates"
    const noNewsCount = await page.getByText('No news for current candidates.').count();
    // If multiple NewsCards exist, at most 1 (the watchlist one) can show this
    // The market news section must show the error message instead
    const errorMsg = page.getByText(/unavailable.*backend/i).or(page.getByText(/Market news unavailable/i));
    await expect(errorMsg).toBeVisible();
  });

  test('Market News card is positioned below the watchlist-news + contracts row', async ({ page }) => {
    await stubBaseApis(page);
    await page.route('**/api/news*', (r) => r.fulfill({ json: MARKET_NEWS_MOCK }));
    await page.goto('/');

    const marketNewsHeading   = page.getByText('Market News').first();
    const watchlistNewsHeading = page.getByText('News — watchlist').first();

    const [marketBox, watchlistBox] = await Promise.all([
      marketNewsHeading.boundingBox(),
      watchlistNewsHeading.boundingBox(),
    ]);

    expect(marketBox).not.toBeNull();
    expect(watchlistBox).not.toBeNull();
    // Market News card must start below the bottom of the watchlist-news card heading
    expect(marketBox!.y).toBeGreaterThan(watchlistBox!.y + watchlistBox!.height);
  });

  test('Watchlist news card is unchanged and still visible', async ({ page }) => {
    await stubBaseApis(page);
    await page.route('**/api/news*', (r) => r.fulfill({ json: [] }));
    await page.goto('/');
    await expect(page.getByText('News — watchlist')).toBeVisible();
  });

});
```

**Run the spec:**
```bash
cd frontend
npx playwright test e2e/ws-b-dashboard-market-news.spec.ts --reporter=list
```

---

## 13. Completion report (produce before exiting — do NOT commit)

### Iron law: evidence before claims

**You may not write "PASS", "done", "complete", or any synonym without pasting the actual command output that proves it.**
Saying "tests pass" without showing the output is a false claim. Paste everything.

When all changes are done, produce this report with **actual command output copy-pasted inline**:

---

```
## WS-B Completion Report

### git diff --stat (paste full output)
[paste output of: git diff HEAD --stat]

### typecheck output (paste full tsc output)
[paste output of: npm run typecheck]
→ Error count: [number]

### Playwright test output (paste full --reporter=list output)
[paste output of: npx playwright test e2e/ws-b-dashboard-market-news.spec.ts --reporter=list]
→ Passed: [N] / Failed: [N]

### Screenshots produced
- e2e/screenshots/ws-b-market-news-card.png : EXISTS / MISSING

### Errors or deviations from spec
[describe anything that diverged, or write "None"]

### Ready for Kenneth review: YES / NO
[YES only if: typecheck = 0 errors AND playwright = 5/5 passed AND screenshots exist]
```

---

**If any test fails:** diagnose and fix before submitting the report. Do NOT submit a report with failing tests.
**If typecheck has errors:** fix them before submitting. A non-zero error count = not done.
**Do NOT run `git commit` or `git add`.** Kenneth reviews this report and commits.

---

## 14. Copy/paste prompt

```
Read `llm-contexts/02-dashboard-market-news.md` fully before writing any code.
It is your single source of truth — do not rely on memory or assumptions.

You are implementing Stream B (CR-04) for the Bamendjou options screener
(Next.js 15, TypeScript strict, CSS Modules).

Your owned files:
- frontend/app/(frame)/dashboard/page.tsx
- frontend/app/(frame)/dashboard/page.module.css

Also create (do not modify any other file):
- frontend/e2e/ws-b-dashboard-market-news.spec.ts   ← Playwright spec from Section 12a

Do NOT modify any file outside this list.
The NewsCard and SectionCard molecules already exist — import them, do not recreate them.

Task: Add a "Market News" SectionCard to the Dashboard that fetches
GET /api/news?symbols=SPY,QQQ,VIX,DIA and renders it using the existing NewsCard molecule.

VERIFICATION RULES (non-negotiable):
1. Run `npm run typecheck` from `frontend/` after EVERY file edit. Must stay 0 errors.
2. When all code changes are done, run the Playwright spec from Section 12a.
3. You may NOT claim anything is "done", "passing", or "complete" without pasting
   the actual command output. "Should work" is not evidence.
4. Produce the completion report from Section 13 with all outputs pasted inline.
5. Do NOT commit. Kenneth reviews the report and commits manually.
```
