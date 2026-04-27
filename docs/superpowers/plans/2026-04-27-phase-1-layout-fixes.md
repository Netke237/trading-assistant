# Phase 1: Critical Layout Fixes - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix critical layout issues causing horizontal overflow and column misalignment across the screener steps.

**Architecture:** Reduce fixed-width constraints, align table header/row spacing, and synchronize minimum viewport thresholds.

**Tech Stack:** Next.js 15, CSS Modules, TypeScript

---

## Task 1: Fix Step 6 Contracts Table Overflow

**Problem:** The 12-column contracts table has a minimum width of 980px (fixed columns) + 200px (minmax symbol column) = 1180px, but only ~760px is available at the minimum 1280px viewport.

**Files:**
- Read: `frontend/app/(frame)/screener/step-6-contracts/page.tsx`
- Read: `frontend/app/(frame)/screener/step-6-contracts/contracts.module.css`
- Modify: `frontend/app/(frame)/screener/step-6-contracts/page.tsx`

### Step 1: Analyze current column layout

Current COLUMNS constant (line 22):
```typescript
const COLUMNS = '28px minmax(200px, 1fr) 120px 64px 70px 70px 70px 72px 64px 70px 104px 48px';
```

Minimum width calculation:
- Fixed: 28+120+64+70+70+70+72+64+70+104+48 = 780px
- Variable min: 200px
- **Total: 980px minimum**

### Step 2: Redesign column layout for 760px workspace

New responsive strategy:
- Symbol column: `minmax(120px, 1fr)` (reduced from 200px min)
- Remove or combine less critical columns
- Reduce fixed column widths where possible

New COLUMNS constant:
```typescript
const COLUMNS = '28px minmax(120px, 1fr) 90px 56px 60px 60px 60px 64px 56px 60px 90px 44px';
```

New minimum: 28+90+56+60+60+60+64+56+60+90+44 = 668px + 120px = **788px** (fits in 760px with minor overflow acceptable)

### Step 3: Update page.tsx

```typescript
// Line 22 - Replace COLUMNS constant
const COLUMNS = '28px minmax(120px, 1fr) 90px 56px 60px 60px 60px 64px 56px 60px 90px 44px';
```

### Step 4: Verify column header text fits

Check each column header in the JSX (around lines 80-100):
- Ensure abbreviated headers for reduced widths
- "Strike" → "Strk" if needed (90px)
- "Bid/Ask/Mid" remain at 56-64px (abbreviated already)
- "Expires" → "Exp" if needed (90px)

### Step 5: Run typecheck

```bash
cd frontend
npm run typecheck
```

Expected: Clean (no errors)

### Step 6: Commit

```bash
git add frontend/app/(frame)/screener/step-6-contracts/page.tsx
git commit -m "fix(contracts): reduce column widths to prevent overflow at 1280px viewport

- Reduced minmax from 200px to 120px for symbol column
- Tightened fixed column widths throughout
- Minimum width now ~788px vs available ~760px (minor overflow acceptable)"
```

---

## Task 2: Fix Step 4 Ranking Split Panel Rigidity

**Problem:** The left panel is fixed at 420px, leaving only ~340px for the right panel (chart + score card) at minimum viewport.

**Files:**
- Read: `frontend/app/(frame)/screener/step-4-ranking/page.module.css`
- Modify: `frontend/app/(frame)/screener/step-4-ranking/page.module.css`

### Step 1: Analyze current layout

Current CSS (line 12):
```css
.split {
  display: grid;
  grid-template-columns: 420px 1fr;
  gap: var(--space-5);
}
```

### Step 2: Implement responsive split

Replace with percentage-based minimum that scales:
```css
.split {
  display: grid;
  grid-template-columns: minmax(320px, 40%) 1fr;
  gap: var(--space-5);
}
```

This allows:
- Minimum: 320px (table still usable)
- At 760px workspace: 320px left + 420px right (comfortable)
- At wider widths: 40% left grows proportionally

### Step 3: Run typecheck

```bash
cd frontend
npm run typecheck
```

Expected: Clean

### Step 4: Commit

```bash
git add frontend/app/(frame)/screener/step-4-ranking/page.module.css
git commit -m "fix(ranking): make split panel responsive to prevent right panel squeeze

- Changed from fixed 420px to minmax(320px, 40%)
- Ensures minimum table width while allowing flexibility
- Right panel now gets adequate space at 1280px viewport"
```

---

## Task 3: Fix Table Header/Row Gap Mismatch

**Problem:** Header uses 8px gap, rows use 12px gap, causing column misalignment across all screener tables.

**Files:**
- Read: `frontend/app/(frame)/screener/step-4-ranking/page.module.css`
- Read: `frontend/app/(frame)/screener/step-5-vol-events/page.module.css`
- Read: `frontend/components/molecules/TableRow/TableRow.module.css`
- Modify: Multiple files

### Step 3.1: Fix Step 4 Ranking

**Modify:** `frontend/app/(frame)/screener/step-4-ranking/page.module.css`

Current (line 25):
```css
.tableHeader {
  display: grid;
  gap: var(--space-2);  /* 8px */
  /* ... */
}
```

Change to:
```css
.tableHeader {
  display: grid;
  gap: var(--space-3);  /* 12px - matches TableRow */
  /* ... */
}
```

### Step 3.2: Fix Step 5 Vol-Events

**Modify:** `frontend/app/(frame)/screener/step-5-vol-events/page.module.css`

Current:
```css
.tableHeader {
  display: grid;
  gap: var(--space-2);  /* 8px */
  /* ... */
}
```

Change to:
```css
.tableHeader {
  display: grid;
  gap: var(--space-3);  /* 12px - matches TableRow */
  /* ... */
}
```

### Step 3.3: Fix Step 6 Contracts

**Modify:** `frontend/app/(frame)/screener/step-6-contracts/contracts.module.css`

Current:
```css
.tableHeader {
  display: grid;
  gap: var(--space-2);  /* 8px */
  /* ... */
}
```

Change to:
```css
.tableHeader {
  display: grid;
  gap: var(--space-3);  /* 12px - matches TableRow */
  /* ... */
}
```

### Step 3.4: Run typecheck

```bash
cd frontend
npm run typecheck
```

Expected: Clean

### Step 3.5: Commit

```bash
git add frontend/app/(frame)/screener/step-4-ranking/page.module.css
 git add frontend/app/(frame)/screener/step-5-vol-events/page.module.css
 git add frontend/app/(frame)/screener/step-6-contracts/contracts.module.css
git commit -m "fix(tables): align header gap with row gap (12px) across all screener steps

- Changed tableHeader gap from space-2 (8px) to space-3 (12px)
- Matches TableRow.module.css gap setting
- Fixes column misalignment between headers and data rows"
```

---

## Task 4: Align MinWidthGate with Frame Minimum

**Problem:** MinWidthGate triggers at 1200px but Frame enforces 1280px minimum, creating a confusing gap.

**Files:**
- Read: `frontend/components/MinWidthGate.tsx`
- Read: `frontend/components/organisms/Frame.module.css`
- Modify: `frontend/components/MinWidthGate.tsx`

### Step 1: Update MinWidthGate threshold

Current (around line 8):
```typescript
const mediaQuery = '(max-width: 1199px)';
```

Change to:
```typescript
const mediaQuery = '(max-width: 1279px)';
```

### Step 2: Update message to reflect actual minimum

Current message:
```typescript
<h2>Desktop View Required</h2>
<p>This application is optimized for desktop screens.</p>
```

Update to:
```typescript
<h2>Desktop View Required</h2>
<p>This application requires a minimum width of 1280px.</p>
```

### Step 3: Run typecheck

```bash
cd frontend
npm run typecheck
```

Expected: Clean

### Step 4: Commit

```bash
git add frontend/components/MinWidthGate.tsx
git commit -m "fix(layout): align MinWidthGate threshold with Frame minimum (1280px)

- Changed media query from 1199px to 1279px
- Updated message to specify 1280px minimum
- Eliminates confusing gap between gate and frame constraints"
```

---

## Verification Tasks

### Task 5: Visual Verification (Manual)

**Files:** All modified screener pages

### Step 1: Start dev server

```bash
cd frontend
npm run dev
```

### Step 2: Test Step 4 at 1280px

- Open browser at `http://localhost:3001/screener/step-4-ranking`
- Resize viewport to exactly 1280px width
- **Verify:** Left panel ~320px, right panel ~420px, no horizontal scroll
- **Verify:** Table columns align with headers

### Step 3: Test Step 5 at 1280px

- Navigate to step-5-vol-events
- **Verify:** Table columns align with headers
- **Verify:** IV rank bars visible, Next Event column readable

### Step 4: Test Step 6 at 1280px

- Navigate to step-6-contracts
- **Verify:** Table fits within workspace (minor horizontal scroll acceptable if <50px)
- **Verify:** All 12 columns visible or easily scrollable
- **Verify:** Table columns align with headers

### Step 5: Test MinWidthGate

- Resize viewport to 1279px
- **Verify:** Gate overlay appears with "1280px" message
- Resize to 1280px
- **Verify:** Gate overlay disappears

### Task 6: Final Typecheck and Lint

```bash
cd frontend
npm run typecheck
npm run lint
```

Expected: Both clean

### Task 7: Final Commit

```bash
git add .
git commit -m "chore(phase-1): complete critical layout fixes

- Fixed Step 6 contracts table overflow
- Fixed Step 4 split panel rigidity  
- Fixed table header/row alignment across Steps 4, 5, 6
- Aligned MinWidthGate threshold with Frame (1280px)

All typecheck and lint passing."
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `step-6-contracts/page.tsx` | Reduced column widths: `minmax(200px,1fr)` → `minmax(120px,1fr)`, tightened fixed columns |
| `step-4-ranking/page.module.css` | Split panel: `420px 1fr` → `minmax(320px, 40%) 1fr` |
| `step-4-ranking/page.module.css` | Table header gap: `space-2` → `space-3` |
| `step-5-vol-events/page.module.css` | Table header gap: `space-2` → `space-3` |
| `step-6-contracts/contracts.module.css` | Table header gap: `space-2` → `space-3` |
| `MinWidthGate.tsx` | Threshold: `1199px` → `1279px`, updated message |

**Estimated time:** 30-45 minutes
**Risk:** Low - only CSS/constant changes, no logic changes
**Testing:** Visual verification at 1280px viewport required
