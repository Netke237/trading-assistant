# TEXT-CONTRAST-AA — plan (board item #659, umbrella #656 row 72)

**Phase id:** `TEXT-CONTRAST-AA` · **Branch:** `board/text-contrast-aa-58bf2d7a` · **Tracking issue:** #659 (board item)
**Date:** 2026-11-17 · **Coordinator:** Claude session that holds the claim.

## 1. Goal

Make every colour that is used **as text** on `--bg-base` / `--bg-surface` meet WCAG 2.x AA (≥ 4.5:1) in both
themes, keeping each colour's hue, and change **nothing else**: no layout, no font sizes, no fill, border, chart
series, bar or dot colour. Kenneth approved the dark-theme greys `#A3A6B4` / `#8B8FA1` and the red `#FF6B68` in the
Portfolio preview on 2026-11-17.

Out of scope (item body): layout, font sizes, light-theme colours that already pass, text on coloured fills
(`--accent-text` on `--accent`, `color: var(--bg-base)` on an accent button), text on `--bg-surface-2/3`
(measured as information only, §2), every non-text use of any token.

## 2. Measurement (before)

Script: `scripts/text_contrast.py` (committed with this plan, §7.1). `python scripts/text_contrast.py measure`
on `origin/main` 8268d4c7 (WCAG 2.x relative luminance, `(L1+0.05)/(L2+0.05)`):

| Theme | Token | Value | vs `--bg-base` | vs `--bg-surface` | AA |
|---|---|---|---|---|---|
| dark (`#131722` / `#1E2335`) | `--text-primary` | `#D1D4DC` | 12.07 | 10.51 | pass |
| dark | `--text-secondary` | `#787B86` | 4.24 | 3.69 | **fail** |
| dark | `--text-dim` | `#434651` | 1.90 | 1.66 | **fail** |
| dark | `--pass` (as text) | `#26A69A` | 5.97 | 5.20 | pass |
| dark | `--caution` (as text) | `#F59F00` | 8.39 | 7.31 | pass |
| dark | `--reject` (as text) | `#EF5350` | 5.13 | 4.47 | **fail** |
| dark | `--accent` (as text) | `#2962FF` | 3.65 | 3.18 | **fail** |
| dark | `--accent-hover` (as hover text) | `#1E53E5` | 2.92 | 2.54 | **fail** |
| dark | `--neutral` (as text) | `#4A5568` | 2.38 | 2.07 | **fail** |
| light (`#F0F3FA` / `#FFFFFF`) | `--text-primary` | `#131722` | 16.11 | 17.90 | pass |
| light | `--text-secondary` | `#5A6070` | 5.66 | 6.28 | pass |
| light | `--text-dim` | `#9BA3B8` | 2.27 | 2.52 | **fail** |
| light | `--pass` (as text) | `#1A9188` | 3.47 | 3.85 | **fail** |
| light | `--caution` (as text) | `#D4890A` | 2.56 | 2.84 | **fail** |
| light | `--reject` (as text) | `#D32F2F` | 4.48 | 4.98 | **fail** |
| light | `--accent` (as text) | `#2962FF` | 4.41 | 4.90 | **fail** |
| light | `--accent-hover` (as hover text) | `#1E53E5` | 5.52 | 6.13 | pass |
| light | `--neutral` (as text) | `#64748B` | 4.28 | 4.76 | **fail** |

The item listed four dark failures; the measurement finds five more in dark/light (dark `--neutral`,
`--accent-hover`; light `--text-dim`, `--pass`, `--caution`, `--reject`, `--accent`, `--neutral`). The item's scope
("the light theme beyond what fails" is out → what fails is in) covers them.

## 3. Design

### 3.1 Why text-only tokens

`--pass`, `--caution`, `--reject`, `--accent`, `--neutral` drive ~430 non-text uses (backgrounds, `color-mix` tints,
borders, outlines, `accent-color`, chart candles/series via `token()`); `python scripts/text_contrast.py usages`
lists them (§5). Changing those tokens would change fills, so they **keep their values**. New text-only tokens carry
the text colour and every text usage switches to them.

Naming: `--text-<role>` (not `--reject-text` as the item's "e.g." suggests) because `--accent-text` already exists
and means *white text on an accent fill*; `--accent-text` keeps that meaning and value.

### 3.2 Why graphic tokens for the greys

`--text-secondary` / `--text-dim` are used ~230 times as text and 25 times as non-text (§5.2). Switching 230 text
usages to new names would be a far larger, riskier edit than changing the two values and pinning the 25 non-text
usages to new tokens that keep the old values: `--graphic-secondary`, `--graphic-dim`.

### 3.3 Values (after)

Rule: dark greys and dark red use the values Kenneth approved in the preview. Every other failing colour moves along
HSL lightness only (hue and saturation fixed) to the smallest step that gives ≥ 4.6:1 (0.1 margin over AA) against
both backgrounds; passing colours are copied unchanged. Computed with the binary search in §7.2.

| Token | dark | dark min ratio | light | light min ratio |
|---|---|---|---|---|
| `--text-primary` | `#D1D4DC` (unchanged) | 10.51 | `#131722` (unchanged) | 16.11 |
| `--text-secondary` | **`#A3A6B4`** (was `#787B86`, hue 227→229) | 6.44 | `#5A6070` (unchanged) | 5.66 |
| `--text-dim` | **`#8B8FA1`** (was `#434651`, hue 227→229) | 4.86 | **`#626D8B`** (was `#9BA3B8`, hue 223.4→223.9) | 4.63 |
| `--text-pass` (new) | `#26A69A` (= `--pass`) | 5.20 | `#167A73` (hue 175.5→175.8) | 4.65 |
| `--text-caution` (new) | `#F59F00` (= `--caution`) | 7.31 | `#986207` (hue 37.7) | 4.63 |
| `--text-reject` (new) | `#FF6B68` (approved; hue 1.1→1.2) | 5.61 | `#D12C2C` (hue 0.0) | 4.60 |
| `--text-accent` (new) | `#5885FF` (hue 224.0) | 4.61 | `#235DFF` (hue 224.2) | 4.63 |
| `--text-accent-hover` (new) | `#7A9DFF` (hue 224.0; lighter than `--text-accent`, as hover goes lighter on dark) | 6.01 | `#1E53E5` (= `--accent-hover`, darker than `--text-accent`) | 5.52 |
| `--text-neutral` (new) | `#7F8DA4` (hue 218.0) | 4.64 | `#606F85` (hue 215.7) | 4.60 |
| `--graphic-secondary` (new) | `#787B86` (old `--text-secondary`) | n/a | `#5A6070` (old) | n/a |
| `--graphic-dim` (new) | `#434651` (old `--text-dim`) | n/a | `#9BA3B8` (old) | n/a |

Hierarchy check: dark primary 10.5 > secondary 6.4 > dim 4.9; light primary 16.1 > secondary 5.7 > dim 4.6 —
dim stays lighter than secondary in both themes.

Unchanged (pinned by T1's test): every other token in both theme blocks — `--bg-*`, `--border-*`, `--pass`,
`--pass-bg`, `--pass-border`, `--caution*`, `--reject*`, `--neutral*`, `--accent`, `--accent-hover`, `--accent-dim`,
`--accent-text`, spacing, radius, shadows, frame sizes, density.

Information only (not changed, logged as a follow-up): on `--bg-surface-2` (`#252B43`) dark `--text-dim` `#8B8FA1`
reaches ≈ 4.4:1; text on surface-2/3 is outside the item's two backgrounds.

### 3.4 What "a text usage" is

- **CSS:** a declaration whose property is exactly `color`. Everything else (`background*`, `border*`, `outline`,
  `box-shadow`, `accent-color`, `fill`, `stroke`, meter pseudo-elements) is non-text.
- **TSX/TS:** an inline-style `color:` that a DOM element renders as text, and the lightweight-charts
  `layout.textColor` (axis labels). Chart series/line/marker `color:` values and anything passed to `background`
  are non-text.
- **Icons drawn in `currentColor`** (WatchStar, ContractStar, EventFlag, AlertRow, StepIndicator, Toast,
  RunScanButton, ModeToggle, NavItems, MarketClock dot `background: currentColor`, step-5 and portfolio inline SVGs)
  follow their element's text colour by design: when that element's `color:` switches to a `--text-*` token, the
  glyph follows its label. This is intended (glyphs read as text) and is the only non-text effect of the change.

## 4. #657 / #658 file boundary

#657 (PORTFOLIO-NUMBERS, running in parallel) owns `frontend/app/(frame)/portfolio/page.tsx`,
`frontend/app/(frame)/@contextRail/portfolio/page.tsx`, `frontend/lib/portfolioTotals.ts`,
`frontend/lib/portfolioFormat.ts` (new), `frontend/components/organisms/ClosePositionDrawer/` and their tests.
#658 is backend-only. The inventory finds **no text-usage switch in any #657 file**: those files contain no
`var(--pass|caution|reject|accent|neutral)` text usage and no non-text grey usage. The only token use there that
this phase affects is `ClosePositionDrawer.module.css:4` `color: var(--text-secondary)`, which changes through the
token value with no edit. **This phase edits no #657 file**, so no follow-up note is needed.
`frontend/app/(frame)/portfolio/page.module.css` is not in #657's Touches; this phase edits it (9 status text
switches + one grey pin, §5).

## 5. Usage inventory (grep)

`python scripts/text_contrast.py usages` (CSS/TS/TSX under `frontend/`, excluding `node_modules`, `.next`,
`coverage`, `__tests__`, `__mocks__`, comment lines and `styles/tokens.css`) at 8268d4c7:

| Token | TEXT (switch / value change) | NON-TEXT (keep) | MANUAL (hand-classified below) |
|---|---|---|---|
| `--text-secondary` | 150 | 4 | 6 |
| `--text-dim` | 80 | 15 | 0 |
| `--pass` | 38 | 73 | 8 |
| `--caution` | 29 | 75 | 1 |
| `--reject` | 43 | 80 | 11 |
| `--accent` | 44 | 194 | 5 |
| `--neutral` | 3 | 5 | 0 |

The script's TSX heuristic labels any `color:` key as TEXT; §5.3 overrides the chart rows it gets wrong. The full
row list is regenerated by the command; the implementer of each ticket uses it as the work list and the auditor
re-runs it.

### 5.1 Status text switches (T2)

Every CSS declaration `color: var(--pass|--caution|--reject|--accent|--neutral)` (145 rows in 58 CSS files: the
script's TEXT rows minus the 12 TSX rows, which §5.1/§5.3 classify by hand) becomes `color: var(--text-pass|…)` with the same role; the two
`color: var(--accent-hover)` hover rules (`app/(frame)/screener/step-4-ranking/page.module.css:189`,
`components/molecules/SectionCard/SectionCard.module.css:51`) become `var(--text-accent-hover)`. Includes the
primitives `components/primitives/Text.module.css:27-30` and `Data.module.css` tone classes, and
`components/atoms/StatusBadge/StatusBadge.module.css:42` / `components/organisms/TopBar/TopBar.module.css:49,80`
(`--neutral`). A `color:` whose value is a `color-mix(...)` containing a status token is MANUAL in the script; the
inventory has none.

TSX text switches (all in `frontend/app/(frame)/settings/page.tsx`, not a #657 file):
- `:3082` `color: 'var(--pass)'` → `var(--text-pass)`; `:3087`, `:3094` `var(--reject)` → `var(--text-reject)`;
- `:3126` `degColor` (rendered as text at `:3185 color: degColor`) → `--text-reject` / `--text-caution` / `--text-pass`;
- `:3141` `proposal.eligible ? 'var(--pass)' : 'var(--reject)'` (text) → text tokens;
- `:3191` `'var(--pass)'` branch of the OOS Sharpe text → `var(--text-pass)` (the `--text-secondary` branch stays).

### 5.2 Grey non-text pins (T1) — `var(--text-secondary|--text-dim)` → `var(--graphic-secondary|--graphic-dim)`

CSS (19):
- `app/(frame)/portfolio/page.module.css:115` background color-mix (secondary)
- `app/(frame)/screener/step-2-universe/page.module.css:369` border-color (secondary)
- `components/molecules/TiingoBudget/TiingoBudget.module.css:60` background (secondary)
- `components/organisms/CandidateBacktestWorkspace/CandidateBacktestWorkspace.module.css:39` border-top (secondary)
- `app/(frame)/alerts/page.module.css:240` background (dim)
- `app/(frame)/analysis/page.module.css:99` background (dim)
- `app/(frame)/dashboard/page.module.css:164` `.newsDot_neutral` background (dim)
- `app/(frame)/screener/step-4-ranking/page.module.css:357` background (dim)
- `app/(frame)/screener/step-5-vol-events/page.module.css:119,120` `.ivFill_*` background (dim)
- `app/(frame)/strategy-watch/page.module.css:13` border-color (dim); `:17` `.pillIdle` background color-mix (dim) —
  only the `background` part of that line; its `color:` stays text
- `components/atoms/RiskBadge/RiskBadge.module.css:30,35` border-left-color (dim)
- `components/atoms/StatusDot/StatusDot.module.css:14` background (dim)
- `components/organisms/BarrierRaceCard/BarrierRaceCard.module.css:186` background color-mix (dim)
- `components/organisms/ContextRail/QuickLook.module.css:38` background (dim)
- `components/organisms/StockPositionCard/StockPositionCard.module.css:160,163` meter bar background (dim)

TSX chart series (5, `token('--text-…')` → `token('--graphic-…')`, fallback hex unchanged):
- `components/molecules/IndicatorPanel/index.tsx:56,62` RSI 30/70 lines (`--text-dim` → `--graphic-dim`)
- `components/molecules/IndicatorPanel/index.tsx:84` MACD histogram (`--text-secondary` → `--graphic-secondary`)
- `components/organisms/CandlestickChart/index.tsx:184` fallback inside `token('--accent') || token('--text-secondary')`
  → `--graphic-secondary`
- `components/organisms/CandidateBacktestWorkspace/index.tsx:141` `muted` (exit-marker colour) → `--graphic-secondary`

### 5.3 Hand classification of the script's TSX TEXT/MANUAL rows (keep as is)

- Chart **text** that follows the new grey value with no edit (intended): `layout.textColor` from
  `token('--text-secondary')` in `CandlestickChart/index.tsx:76`, `ChartPane/index.tsx:56`, `PnlChart/index.tsx:92`,
  `EarningsChart/index.tsx:44`, `CandidateBacktestWorkspace/index.tsx:154` (`text`).
- Chart **series/markers** (non-text, keep base token): `IndicatorPanel/index.tsx:44,72,78,144-145,155-156`,
  `CandlestickChart/index.tsx:77,78,184` (`--accent` part), `ChartPane/index.tsx:57,58,64`,
  `EarningsChart/index.tsx:55,58`, `PnlChart/index.tsx:114`, `CandidateBacktestWorkspace/index.tsx:141` (`accent`),
  `:148`, `:154` (`accent`, `reject`).
- Fills (keep): `PnlHeatmap/index.tsx:27,159,160,162,163`; `settings/page.tsx:3064,3151,3210` backgrounds.
- Settings greys used as text (`:3043,3077,3152,3165,3172-3206,3233,3245,3247,3254`) change through the value.

## 6. Tickets

T1 blocks T2 (they share `strategy-watch/page.module.css`, `RiskBadge.module.css`, `alerts/page.module.css`,
`step-5-vol-events/page.module.css`, `BarrierRaceCard.module.css`, `portfolio/page.module.css`,
`step-4-ranking/page.module.css`, `IndicatorPanel/index.tsx`, `CandlestickChart/index.tsx`,
`CandidateBacktestWorkspace/*`, and the guard test). T3 is the coordinator's own work.

### T1 — tokens, measurement script, grey pins

Files: `frontend/styles/tokens.css`, `frontend/styles/__tests__/textContrast.test.ts`
(new), `frontend/styles/__tests__/textTokenUsage.test.ts` (new), and the 19 CSS + 3 TSX files of §5.2.

Tests first:
1. `textContrast.test.ts` parses `styles/tokens.css` with `fs` (dark block = `[data-theme="dark"] {…}`, light block
   = `[data-theme="light"] {…}`, same regex as the script) and asserts:
   - each of `--text-primary`, `--text-secondary`, `--text-dim`, `--text-pass`, `--text-caution`, `--text-reject`,
     `--text-accent`, `--text-accent-hover`, `--text-neutral` is defined in both blocks as a 6-digit hex and has
     contrast ≥ 4.5 against `--bg-base` and `--bg-surface` of the same block (same luminance formula as §7.1);
   - the exact §3.3 values (table-driven), so a later edit cannot silently drift;
   - every other token listed in §3.3 "Unchanged" equals its 8268d4c7 value in both blocks (table of the current
     values copied from `tokens.css`), and `--graphic-secondary` / `--graphic-dim` equal the old
     `--text-secondary` / `--text-dim` per theme.
   RED before the change: missing `--text-pass` etc. and `--text-secondary` 3.69 < 4.5.
2. `textTokenUsage.test.ts` walks `frontend/` (`.css`, `.ts`, `.tsx`; skip `node_modules`, `.next`, `coverage`,
   `__tests__`, `__mocks__`, `styles/tokens.css`) and asserts **grey rule**: no CSS declaration whose property is not
   exactly `color` references `var(--text-secondary)` or `var(--text-dim)` (split each line on `;`/`{`, property =
   text before the last `:` of the declaration, as §7.1 does), and no `.ts/.tsx` line contains
   `token('--text-dim')` or `token('--text-secondary')` except the five `layout.textColor` lines of §5.3 (allowlist by
   file path + the variable name `textDim` / `text`, documented in the test). RED: the 19 CSS rows and 5 TSX rows of §5.2.

Change: add the new tokens and the three value changes to both theme blocks of `tokens.css` (comment block
"Text-only colours — WCAG AA ≥ 4.5:1 on --bg-base/--bg-surface; TEXT-CONTRAST-AA" and "Non-text greys — old text
values, keep fills/lines unchanged"); apply the §5.2 pins. Commit
`feat(tokens): TEXT-CONTRAST-AA AA text tokens + grey pins (T1)`.

### T2 — status text switches

Files: the 58 CSS files of §5.1, `frontend/app/(frame)/settings/page.tsx`, and `textTokenUsage.test.ts` (extend).

Test first: extend `textTokenUsage.test.ts` with the **status rule**: no CSS declaration whose property is exactly
`color` references `var(--pass|--caution|--reject|--accent|--neutral|--accent-hover)`; no `.tsx` line matches
`color:\s*[^,}]*var\(--(pass|caution|reject|accent|neutral)\)`; and `settings/page.tsx` contains no
`'var(--(pass|caution|reject))'` literal in the `degColor` assignment. RED: the 145 CSS `color:` rows, the 2 `--accent-hover` hover rows and the settings rows.

Change: the §5.1 switches, nothing else. A mechanical regex on CSS (`(^|[;{\s])color:\s*var\(--(pass|caution|reject|accent|neutral)\)`
→ `color: var(--text-$2)`, `color:\s*var\(--accent-hover\)` → `color: var(--text-accent-hover)`) is allowed only if
the implementer then diffs it and confirms every hunk changes only a `color:` value (no `border-color`,
`background-color`, `outline-color`, `accent-color`). Commit `feat(tokens): TEXT-CONTRAST-AA switch status text to text tokens (T2)`.

### T3 — coordinator: screenshots, checks, audit, PR

- Before screenshots are taken on 8268d4c7 code (this branch before T1), after screenshots after T2, both on a
  `next dev` server on port **3005** from this worktree (never 3001). Pages: `/dashboard`, `/screener/step-7-trade-card`,
  `/portfolio`, `/settings`, each in dark and light theme. Stored under
  `docs/superpowers/plans/text-contrast-aa/screenshots/{before,after}/<page>-<theme>.png` and linked in the PR.
- `python scripts/text_contrast.py measure` after T2: exit 0, table pasted into the PR.
- Full `npm run typecheck` and `npm run test` (frontend). No backend change, so backend tests are not required.
- `git merge origin/main` → code audit rounds → PR `Closes #659` → board.md step 7.

## 7. Scripts

### 7.1 `scripts/text_contrast.py` (committed with this plan)

Committed in the same commit as this plan, so the auditor can run it; no ticket edits it (it is read-only: `measure` prints the §2 table and exits 1 while any text token fails; `usages` prints §5's counts
and row list).

### 7.2 Value search (used once to pick §3.3; not committed)

```python
import colorsys, sys
sys.path.insert(0, 'scripts'); from text_contrast import contrast as cr
def hx(r, g, b): return '#%02X%02X%02X' % tuple(round(x * 255) for x in (r, g, b))
def adjust(c, bgs, target=4.6, lighter=True):
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)); H, L, S = colorsys.rgb_to_hls(r, g, b)
    lo, hi = (L, 1.0) if lighter else (0.0, L)
    for _ in range(40):
        m = (lo + hi) / 2; ok = min(cr(hx(*colorsys.hls_to_rgb(H, m, S)), x) for x in bgs) >= target
        if lighter: hi, lo = (m, lo) if ok else (hi, m)
        else: lo, hi = (m, hi) if ok else (lo, m)
    return hx(*colorsys.hls_to_rgb(H, hi if lighter else lo, S))
# dark bgs ['#131722', '#1E2335'] lighter=True; light bgs ['#F0F3FA', '#FFFFFF'] lighter=False
```

## 8. Acceptance (item #659)

- [ ] Every text token ≥ 4.5:1 on both backgrounds in both themes — `measure` exit 0, table in the PR.
- [ ] No fill/border colour changed unintentionally — §5 inventory; T1 test pins every non-text token value and the
      guard test forbids grey tokens in non-text declarations and status tokens in text declarations.
- [ ] Before/after screenshots of Dashboard, Screener step 7, Portfolio, Settings in the PR.
- [ ] Typecheck + full frontend tests green; plan audit and code audit clean (`audit_rule`).

## 9. Gate note for auditors

This phase changes only colours. The repo gate (wrong number in front of a user or on a broker order; corrupt
persisted data) is met only if a change makes a number read as something else — e.g. a loss rendered in the pass
colour or a reject state rendered in a neutral colour (a role swap in §5.1), or a status that is conveyed only by
colour becoming indistinguishable. Same-role, same-hue lightness changes are below the gate.

## 10. Ratings

Re-rated at plan time: **size M** (4–8 h: ~175 mechanical edits across ~65 files, two guard tests, 16 screenshots,
audits) · **complexity 2** (single-mechanism change; the risk is a missed or role-swapped usage, guarded by tests).
Completion 10% (plan drafted; independent plan audit pending).

## 11. Logged, not in scope

- Text on `--bg-surface-2/3` and text on coloured fills (`--accent-text`, `color: var(--bg-base)` on accent buttons)
  are not measured against AA here.
- `--neutral` and `--accent-hover` as non-text keep their values.
