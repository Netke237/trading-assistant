# Context Doc 37 — Toast Shadow Token

**Workstream:** Add `--shadow-overlay` CSS token and fix Toast hardcoded rgba
**Conflict class:** Infrastructure — adds one token to the shared token sheet

---

## 1. Mission

`Toast.module.css` has a hardcoded `box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35)` — the only CSS convention violation in the WS-42 batch. This workstream adds a `--shadow-overlay` token to `frontend/app/styles/tokens.css` for both themes, and replaces the hardcoded value in the Toast. No other component or file changes.

---

## 2. Owned files

| File path | Status | Purpose |
|---|---|---|
| `frontend/app/styles/tokens.css` | Modify | Add `--shadow-overlay` token under both themes |
| `frontend/components/molecules/Toast/Toast.module.css` | Modify | Replace hardcoded rgba with `var(--shadow-overlay)` |

---

## 3. Read-only references

| File | Reason |
|---|---|
| `frontend/app/globals.css` | Understand how tokens.css is imported |
| `frontend/components/molecules/Toast/index.tsx` | Confirm no inline style uses box-shadow |

---

## 4. Token values

**Dark theme** (`[data-theme="dark"]` or `:root` block):
```css
--shadow-overlay: 0 4px 16px rgba(0, 0, 0, 0.35);
```

**Light theme** (`[data-theme="light"]` block):
```css
--shadow-overlay: 0 4px 16px rgba(0, 0, 0, 0.12);
```

The light-theme value uses a lighter opacity — dark overlays look too heavy on white backgrounds.

---

## 5. Full token reference (dark theme)

```css
/* Backgrounds */
--bg-base:          #131722;
--bg-surface:       #1E2335;
--bg-surface-2:     #252B43;
--bg-surface-3:     #2A3152;

/* Borders */
--border-subtle:    #2A2E42;
--border-strong:    #363B54;

/* Text */
--text-primary:     #D1D4DC;
--text-secondary:   #787B86;
--text-dim:         #434651;

/* Status */
--pass:             #26A69A;
--caution:          #F59F00;
--reject:           #EF5350;
--neutral:          #4A5568;

/* Accent */
--accent:           #2962FF;
--accent-hover:     #1E53E5;
--accent-dim:       #142B7A;
--accent-text:      #FFFFFF;

/* Spacing */
--space-1: 4px;  --space-2: 8px;  --space-3: 12px;  --space-4: 16px;
--space-5: 20px; --space-6: 24px; --space-8: 32px;  --space-12: 48px;

/* Radius */
--radius-sm: 4px;  --radius-md: 6px;  --radius-lg: 10px;

/* NEW — add after Radius */
--shadow-overlay: 0 4px 16px rgba(0, 0, 0, 0.35);
```

---

## 6. Current Toast.module.css (line 12 — the only change needed)

```css
/* BEFORE */
box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);

/* AFTER */
box-shadow: var(--shadow-overlay);
```

---

## 7. Task spec

**Step 1:** In `frontend/app/styles/tokens.css`:
- Find the dark theme block (`:root` or `[data-theme="dark"]`).
- After the `--radius-*` variables, add: `--shadow-overlay: 0 4px 16px rgba(0, 0, 0, 0.35);`
- Find the light theme block (`[data-theme="light"]`).
- Add: `--shadow-overlay: 0 4px 16px rgba(0, 0, 0, 0.12);`

**Step 2:** In `frontend/components/molecules/Toast/Toast.module.css`:
- Replace `box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);` with `box-shadow: var(--shadow-overlay);`

**Acceptance criteria:**
- `npm run typecheck` is clean.
- No other `.module.css` or `.tsx` file is touched.
- `--shadow-overlay` appears in both the dark and light theme blocks of `tokens.css`.
- Toast still renders a visible shadow in dark mode; shadow is lighter in light mode.

---

## 8. Hard rules

1. No Tailwind, styled-components, or CSS-in-JS.
2. No `style={{}}` — this is a CSS file change only.
3. No hardcoded colors anywhere — the token value contains rgba() which is fine *inside* tokens.css.
4. Do not touch any other component, store, or page file.
5. `npm run typecheck` must be clean after every edit (CSS changes can't break typecheck, but run it to confirm nothing else is broken).

---

## 9. Dev workflow

```bash
cd frontend
npm run typecheck    # must be clean
npm run dev          # verify Toast renders correctly in both themes
```

---

## 10. Copy/paste prompt

```
Read `llm-contexts/37-toast-shadow-token.md` fully before writing any code. It is your single source of truth.

You are fixing a CSS convention violation in the Bamendjou options screener (Next.js 15, CSS Modules only).

Your owned files:
- frontend/app/styles/tokens.css  (MODIFY — add --shadow-overlay token)
- frontend/components/molecules/Toast/Toast.module.css  (MODIFY — replace hardcoded rgba)

Do not modify any file outside this list.

Task: Add a --shadow-overlay CSS custom property to tokens.css (dark: rgba(0,0,0,0.35), light: rgba(0,0,0,0.12)), then replace the hardcoded box-shadow in Toast.module.css with var(--shadow-overlay).

After editing, run: npm run typecheck from frontend/
Must be clean. Commit when done.
```
