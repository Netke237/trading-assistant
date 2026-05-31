# LLM Context — Round 5: Step Reorder (CR-01)

**Workstream:** CR-01 — Move Market Regime to Step 1 of the 7-step screener workflow.
**Conflict class:** Infrastructure — renames 3 step folders, updates routing constants, and updates text labels in 3 pages. Touches no shared stores or organisms beyond `Stepper`.

**Prerequisite:** All previous rounds (CR-03/07, CR-02) must be merged before starting. This is the last CR and its folder renames would invalidate any open branch targeting those paths.

---

## 1. Mission

Reorder the 7-step screener so Market Regime is first. Users must see market conditions before selecting a universe and direction. The new order:

| New Step | Screen | Old Step |
|---|---|---|
| 1 | Market Regime | 3 |
| 2 | Universe | 1 |
| 3 | Direction + Horizon | 2 |
| 4 | Stock Ranking | 4 (unchanged) |
| 5 | Vol + Events | 5 (unchanged) |
| 6 | Contracts | 6 (unchanged) |
| 7 | Trade Card | 7 (unchanged) |

**The single most important constraint:** Only rename the three folders that change numbers. Do NOT move or modify steps 4–7.

---

## 2. Owned files

| File path | Status | Purpose |
|---|---|---|
| `frontend/app/(frame)/screener/step-3-regime/` | Rename to `step-1-regime/` | Market Regime becomes Step 1 |
| `frontend/app/(frame)/screener/step-1-universe/` | Rename to `step-2-universe/` | Universe becomes Step 2 |
| `frontend/app/(frame)/screener/step-2-direction/` | Rename to `step-3-direction/` | Direction + Horizon becomes Step 3 |
| `frontend/app/(frame)/screener/step-1-regime/page.tsx` | Modify | Update "STEP 3 OF 7" → "STEP 1 OF 7" |
| `frontend/app/(frame)/screener/step-2-universe/page.tsx` | Modify | Update "STEP 1 OF 7" → "STEP 2 OF 7" |
| `frontend/app/(frame)/screener/step-3-direction/page.tsx` | Modify | Update "STEP 2 OF 7" → "STEP 3 OF 7" |
| `frontend/components/organisms/Stepper/index.tsx` | Modify | Update `SCREENER_STEPS` array slug order |
| `frontend/components/organisms/StepNavBar/index.tsx` | Modify | Update `current === 3` regime gate → `current === 1` |
| `frontend/e2e/tests/ws-e-step-reorder.spec.ts` | Create | Playwright spec (5 tests) |

---

## 3. Read-only references

| File | Why |
|---|---|
| `frontend/components/organisms/Stepper/index.tsx` | Read existing SCREENER_STEPS before modifying |
| `frontend/components/organisms/StepNavBar/index.tsx` | Read existing regime gate condition before modifying |
| `frontend/components/KeyboardShortcuts/index.tsx` | Imports SCREENER_STEPS — verify no slug references after rename |
| `frontend/styles/tokens.css` | CSS variables |

---

## 4. Integration constraints

### `Stepper/index.tsx` — SCREENER_STEPS

Current array (before this workstream):

```ts
export const SCREENER_STEPS: ScreenerStep[] = [
  { index: 1, slug: 'step-1-universe',    label: 'Universe'             },
  { index: 2, slug: 'step-2-direction',   label: 'Direction + Horizon'  },
  { index: 3, slug: 'step-3-regime',      label: 'Market Regime'        },
  { index: 4, slug: 'step-4-ranking',     label: 'Stock Ranking'        },
  { index: 5, slug: 'step-5-vol-events',  label: 'Vol + Events'         },
  { index: 6, slug: 'step-6-contracts',   label: 'Contracts'            },
  { index: 7, slug: 'step-7-trade-card',  label: 'Trade Card'           },
];
```

After this workstream, change to:

```ts
export const SCREENER_STEPS: ScreenerStep[] = [
  { index: 1, slug: 'step-1-regime',      label: 'Market Regime'        },
  { index: 2, slug: 'step-2-universe',    label: 'Universe'             },
  { index: 3, slug: 'step-3-direction',   label: 'Direction + Horizon'  },
  { index: 4, slug: 'step-4-ranking',     label: 'Stock Ranking'        },
  { index: 5, slug: 'step-5-vol-events',  label: 'Vol + Events'         },
  { index: 6, slug: 'step-6-contracts',   label: 'Contracts'            },
  { index: 7, slug: 'step-7-trade-card',  label: 'Trade Card'           },
];
```

`currentStepFromPath` uses `/screener\/step-(\d)/` regex — this still works because the digit is in position 6 of each slug. No change needed.

### `StepNavBar/index.tsx` — regime gate condition

Current condition (before this workstream):

```ts
if (current === 3 && regime === 'REJECT') {
  setShowConfirm(true);
  return;
}
```

After this workstream, Regime is Step 1 → the NEXT button on Step 1 (Regime) should trigger the confirmation when regime is REJECT:

```ts
if (current === 1 && regime === 'REJECT') {
  setShowConfirm(true);
  return;
}
```

Also update the dialog text. Current text:
> "Market conditions are unfavourable for new directional positions. Step 4 will still rank your candidates — but consider waiting for a better regime before trading."

Update to:
> "Market conditions are unfavourable for new directional positions. Step 4 (Stock Ranking) will still rank your candidates — but consider waiting for a better regime before trading."

(Unchanged in substance — step 4 is still Stock Ranking after the reorder.)

### Page text updates ("STEP X OF 7")

Each step page has a hardcoded label. After renames:

| File (after rename) | Change |
|---|---|
| `step-1-regime/page.tsx` | `STEP 3 OF 7` → `STEP 1 OF 7` |
| `step-2-universe/page.tsx` | `STEP 1 OF 7` → `STEP 2 OF 7` |
| `step-3-direction/page.tsx` | `STEP 2 OF 7` → `STEP 3 OF 7` |

### How to rename folders (use git mv to preserve history)

```bash
cd "frontend/app/(frame)/screener"

git mv step-3-regime    step-1-regime
git mv step-1-universe  step-2-universe
git mv step-2-direction step-3-direction
```

**Important:** Do all three renames in a single `git mv` pass before running typecheck. The old folder names will be unresolvable as soon as the first rename happens.

**Order matters:** Rename `step-3-regime` first (it doesn't conflict with either target), then `step-1-universe` (frees step-1- for regime), then `step-2-direction`.

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
--accent:           #2962FF;
--accent-hover:     #1E53E5;
--accent-dim:       #142B7A;
--accent-text:      #FFFFFF;
--space-1:  4px;
--space-2:  8px;
--space-3:  12px;
--space-4:  16px;
--space-6:  24px;
--radius-sm: 4px;
--radius-md: 6px;
--radius-lg: 10px;

/* Light theme overrides */
--bg-base:        #F0F3FA;
--bg-surface:     #FFFFFF;
--bg-surface-2:   #F5F7FF;
--border-subtle:  #DDE1F0;
--text-primary:   #131722;
--text-secondary: #5A6070;
--text-dim:       #9BA3B8;
```

---

## 6. Primitives & component reference

```tsx
<Text size={11|12|13|14} tone="primary|secondary|dim|pass|caution|reject" weight={400|500|600} />
<Title as="h1|h2|h3" size={18|20|24} />
<Data size={11|12|13|14|16|18|20|24} weight={500|600} />
```

---

## 7. Domain types

No new types. This workstream is pure folder renames + text + routing constant updates.

---

## 8. Zustand stores

No store changes. `Stepper/index.tsx` is an organism component, not a store.

---

## 9. Task spec

### Step 1: Rename folders (git mv)

```bash
cd "frontend/app/(frame)/screener"
git mv step-3-regime    step-1-regime
git mv step-1-universe  step-2-universe
git mv step-2-direction step-3-direction
```

### Step 2: Update SCREENER_STEPS in Stepper

File: `frontend/components/organisms/Stepper/index.tsx`

Replace the existing SCREENER_STEPS array with the new order shown in Section 4.

### Step 3: Update StepNavBar regime gate

File: `frontend/components/organisms/StepNavBar/index.tsx`

Change `current === 3` to `current === 1` in the handleNext callback.

### Step 4: Update step labels in pages

- `step-1-regime/page.tsx`: find `STEP 3 OF 7`, replace with `STEP 1 OF 7`
- `step-2-universe/page.tsx`: find `STEP 1 OF 7`, replace with `STEP 2 OF 7`
- `step-3-direction/page.tsx`: find `STEP 2 OF 7`, replace with `STEP 3 OF 7`

### Step 5: Verify no other step-slug references

After renaming, grep for old slugs to catch stray references:

```bash
grep -r "step-1-universe\|step-2-direction\|step-3-regime" frontend/app frontend/components frontend/lib --include="*.tsx" --include="*.ts"
```

Expected output: empty (zero hits). If anything shows up, fix it.

### Step 6: Typecheck

```bash
cd frontend && npm run typecheck
```

---

## 10. Hard rules

1. Only rename the three folders in Section 2.
2. Steps 4–7 folder names do NOT change.
3. Do not add new pages, stores, or components.
4. `npm run typecheck` must be clean after all changes.
5. Run the grep check in Step 5 before claiming done.
6. Do NOT commit.

---

## 12a. Playwright spec

Create `frontend/e2e/tests/ws-e-step-reorder.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

async function stubApis(page: import('@playwright/test').Page) {
  await page.route('**/api/regime',    (r) => r.fulfill({ json: { overall: 'PASS', headline: 'Test', metrics: [] } }));
  await page.route('**/api/watchlist', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/alerts',    (r) => r.fulfill({ json: [] }));
  await page.route('**/api/news*',     (r) => r.fulfill({ json: [] }));
  await page.route('**/api/portfolio', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/candles/*', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/sector*',   (r) => r.fulfill({ json: [] }));
}

test.describe('WS-E: Step Reorder (CR-01)', () => {

  test('step-1-regime URL renders Market Regime page', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-1-regime');
    await expect(page.getByText('STEP 1 OF 7')).toBeVisible();
    await expect(page.getByRole('heading', { name: /Market Regime/i })).toBeVisible();
  });

  test('step-2-universe URL renders Universe page', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-2-universe');
    await expect(page.getByText('STEP 2 OF 7')).toBeVisible();
    await expect(page.getByRole('heading', { name: /Universe/i })).toBeVisible();
  });

  test('step-3-direction URL renders Direction + Horizon page', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-3-direction');
    await expect(page.getByText('STEP 3 OF 7')).toBeVisible();
    await expect(page.getByRole('heading', { name: /Direction/i })).toBeVisible();
  });

  test('old URLs (step-1-universe, step-3-regime) no longer resolve (404)', async ({ page }) => {
    const r1 = await page.goto('/screener/step-1-universe');
    expect(r1?.status()).not.toBe(200);
    const r2 = await page.goto('/screener/step-3-regime');
    expect(r2?.status()).not.toBe(200);
  });

  test('Next from step-1-regime navigates to step-2-universe', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-1-regime');
    await page.getByRole('button', { name: /Next/i }).click();
    await page.waitForURL('**/step-2-universe**');
    await expect(page.getByText('STEP 2 OF 7')).toBeVisible();
  });

});
```

---

## 12b. Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001
npm run typecheck    # must be 0 errors

# Grep check — must return empty
grep -r "step-1-universe\|step-2-direction\|step-3-regime" app components lib --include="*.tsx" --include="*.ts"

npx playwright test e2e/tests/ws-e-step-reorder.spec.ts --reporter=list
```

---

## 13. Completion report

```
## CR-01 Completion Report

### Files changed
[paste: git diff --stat HEAD]

### Grep check for old slugs (must be empty)
[paste: output of grep command from Section 12b]

### Typecheck
[paste: full output of `npm run typecheck` from frontend/]

### Playwright results
[paste: full output of `npx playwright test e2e/tests/ws-e-step-reorder.spec.ts --reporter=list`]

### Known issues / deviations
[any deviations from spec]
```

**Iron law:** You may NOT write "done", "passing", or "complete" without pasting the actual command output above.

---

## 14. Copy/paste prompt

```
Read `llm-contexts/05-step-reorder.md` fully before writing any code.
It is your single source of truth — do not rely on memory or assumptions.

You are implementing Round 5 (CR-01) for the Bamendjou options screener
(Next.js 15, TypeScript strict, CSS Modules).

PREREQUISITE: Rounds 3 and 4 (CR-03/07 and CR-02) must already be merged.
This is the LAST change request. Read the current state of all owned files first.

Your owned files (after renaming):
- frontend/app/(frame)/screener/step-1-regime/page.tsx      (was step-3-regime)
- frontend/app/(frame)/screener/step-2-universe/page.tsx    (was step-1-universe)
- frontend/app/(frame)/screener/step-3-direction/page.tsx   (was step-2-direction)
- frontend/components/organisms/Stepper/index.tsx
- frontend/components/organisms/StepNavBar/index.tsx

Also create (do not modify any other file):
- frontend/e2e/tests/ws-e-step-reorder.spec.ts   ← Playwright spec from Section 12a

Task: Rename the three step folders using `git mv`, update SCREENER_STEPS in Stepper,
update the StepNavBar regime gate from current===3 to current===1, and update the
"STEP X OF 7" text labels in the three renamed pages.

VERIFICATION RULES (non-negotiable):
1. Run `npm run typecheck` from `frontend/` after ALL renames + edits. Must stay 0 errors.
2. Run the grep check from Section 12b — output must be empty.
3. When all changes are done, run the Playwright spec from Section 12a.
4. You may NOT claim anything is "done", "passing", or "complete" without pasting
   the actual command output. "Should work" is not evidence.
5. Produce the completion report from Section 13 with all outputs pasted inline.
6. Do NOT commit. Kenneth reviews the report and commits manually.
```
