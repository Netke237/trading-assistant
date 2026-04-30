# LLM Context — Responsive Audit + Fixes (Workstream 16)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `frontend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream modifies only CSS module files. It does not touch any `.tsx` file, any store, any type definition, or the backend.

**Goal:**
The app has a 1200px minimum width gate (`MinWidthGate.tsx`). Above 1200px, all layouts must be usable. This workstream audits every page at 1200px, 1440px, and 1920px, then fixes any overflow, clipping, wrapping, or alignment issues found. No new components are introduced.

**What NOT to touch:**
- Any `.tsx` or `.ts` file
- Any file under `backend/`
- `frontend/app/globals.css` — read-only (token sheet)
- Any CSS file not listed in Section 2

The fix list in Section 4 is the definitive scope. Do not fix issues not listed there.

---

## Section 2 — Owned files

Only CSS module files. All are **Modify** (fix broken rules, add missing constraints).

| File path | What to fix |
|---|---|
| `frontend/app/(frame)/screener/step-4-ranking/page.module.css` | Table panel minimum width, left panel overflow |
| `frontend/app/(frame)/screener/step-6-contracts/contracts.module.css` | 12-column table horizontal scroll containment |
| `frontend/app/(frame)/screener/screener.module.css` | `.stepBody` overflow containment at 1200px |
| `frontend/app/(frame)/screener/step-7-trade-card/page.module.css` *(if it exists)* | CandidateNav + basket layout at 1200px |
| `frontend/app/(frame)/screener/step-3-regime/page.module.css` | Sector heatmap grid at 1200px |
| `frontend/app/(frame)/settings/page.module.css` | Sub-nav + panel at 1200px |

If a file listed above does not exist, skip it silently.

---

## Section 3 — Read-only references

| File | Reason |
|---|---|
| `frontend/app/globals.css` | CSS token values — use only `var(--…)` references |
| `frontend/app/(frame)/screener/screenerLayout.module.css` | Frame layout constraints |

---

## Section 4 — Fix specifications

### 4.1 Step 4 (`step-4-ranking/page.module.css`)

**Problem:** At 1200px the split panel's left side (`minmax(320px, 40%)`) may collide with the right panel. The table inside `.leftPanel` can overflow horizontally.

**Fix:**
```css
/* Add to existing .leftPanel rule */
.leftPanel {
  overflow-x: auto;
  min-width: 0;
}

/* Add to existing .split rule */
.split {
  min-width: 0;
  overflow: hidden;
}
```

### 4.2 Step 6 contracts (`contracts.module.css`)

**Problem:** The 12-column contracts table at 1200px overflows its container, pushing page width past the viewport.

**Fix:** Wrap the table in a horizontally-scrollable container. Since we cannot touch `.tsx` files, the fix goes on the outermost table container class. Identify the class applied to the table's wrapping div (read the file to find it — likely `.tableWrap` or `.table`) and add:

```css
/* Add to the outermost table wrapper class (verify the name in contracts.module.css) */
.tableWrap {   /* or whatever the class is called */
  overflow-x: auto;
  min-width: 0;
}
```

Also ensure the header row uses `min-content` for narrow columns:
```css
.headerRow {
  min-width: max-content;  /* add this */
}
```

### 4.3 Shared screener layout (`screener.module.css`)

**Problem:** `.stepBody` has no overflow constraint, so wide content pushes through at 1200px.

**Fix:**
```css
/* Add to existing .stepBody rule */
.stepBody {
  overflow-x: auto;
  min-width: 0;
}
```

### 4.4 Step 7 trade card (`step-7-trade-card/page.module.css` — if it exists)

**Problem:** CandidateNav basket at 1200px may clip or overflow the available width.

**Fix:** Add `min-width: 0` to any flex or grid child containers that hold the basket or nav controls. Read the file and apply this pattern to any container that uses `flex: 1` without `min-width: 0`.

### 4.5 Step 3 regime (`step-3-regime/page.module.css`)

**Problem:** The sector heatmap `grid-template-columns: repeat(11, 1fr)` is too wide at 1200px.

**Fix:**
```css
/* Find the sector grid class and update to auto-fill */
.sectorGrid {   /* verify the class name — may differ */
  grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
}
```

### 4.6 Settings (`settings/page.module.css`)

**Problem:** Settings sub-nav + content panel may be too wide at 1200px.

**Fix:** Ensure the outer layout container uses `min-width: 0` on flex children:
```css
/* Find the main content flex child and add */
.content {   /* verify the class name */
  min-width: 0;
  overflow-x: auto;
}
```

---

## Section 5 — CSS tokens (reference only)

```css
--bg-base:          #131722;
--bg-surface:       #1E2335;
--bg-surface-2:     #252B43;
--border-subtle:    #2A2E42;
--space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
--space-5: 20px; --space-6: 24px; --space-8: 32px;
--radius-sm: 4px; --radius-md: 6px; --radius-lg: 10px;
```

Do not hardcode any colour or spacing value. Use `var(--…)` only.

---

## Section 6 — Task spec

### Process for each file

1. Read the existing CSS module file fully.
2. Identify the class names mentioned in Section 4 (verify they match exactly).
3. Apply the fix — add or update only the properties listed. Do not rewrite unrelated rules.
4. Move to next file.

### Acceptance criteria

1. At viewport width 1200px, no horizontal scroll appears on the `<body>` element for any page.
2. Step 4 left panel scrolls internally if content is too wide — it does not push the page.
3. Step 6 contracts table scrolls internally — it does not overflow the page.
4. Sector heatmap in Step 3 wraps gracefully at 1200px instead of overflowing.
5. `npm run typecheck` remains clean (no `.tsx` changes, so this should always pass).

### Verify

```bash
cd frontend
npm run typecheck
# Expected: 0 errors (no .tsx changes made)
npm run dev   # then open browser at 1200px wide and check each page
```

---

## Section 7 — Hard rules

1. Do NOT modify any `.tsx` or `.ts` file.
2. Do NOT hardcode colours — use `var(--…)` only.
3. Do NOT add new CSS classes unless the fix requires a new wrapper class that has no existing equivalent.
4. Do NOT change layout logic (grid columns, flex direction) beyond the specific fixes listed.
5. `npm run typecheck` must remain clean.

---

## Section 8 — Dev workflow

```bash
cd frontend
npm run dev   # localhost:3001
# Resize browser to 1200px wide
# Check: step-4-ranking, step-6-contracts, step-3-regime, settings
```

---

## Section 9 — Copy/paste prompt

```
Read `llm-contexts/16-responsive-audit.md` fully before touching any file.
It is your single source of truth.

You are fixing responsive layout issues in the Bamendjou options screener
(Next.js 15, CSS Modules). You may ONLY edit CSS module files — no .tsx changes.

Your owned files (CSS modules only — verify each exists before editing):
  - frontend/app/(frame)/screener/step-4-ranking/page.module.css
  - frontend/app/(frame)/screener/step-6-contracts/contracts.module.css
  - frontend/app/(frame)/screener/screener.module.css
  - frontend/app/(frame)/screener/step-7-trade-card/page.module.css (if exists)
  - frontend/app/(frame)/screener/step-3-regime/page.module.css
  - frontend/app/(frame)/settings/page.module.css

Apply only the specific fixes listed in Section 4. Do not rewrite unrelated rules.
After all edits, run `npm run typecheck` from `frontend/`. Must stay clean.
Commit after all changes are complete.
```
