# Codebase Audit Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all confirmed bugs and maintenance traps surfaced by the Winston audit (June 2026), leaving the codebase consistent between frontend and backend.

**Architecture:** The screener has a FastAPI backend (scoring rules driven by `backend/config/scoring_rules.yaml`) and a Next.js frontend. The core problem class is _threshold divergence_ — the same conceptual value (e.g. "what score counts as PASS?") is defined in multiple places that can silently drift. Fix strategy: make YAML the single source of truth for every threshold, surface it via the API where the frontend needs it, and delete all redundant copies.

**Tech Stack:** TypeScript 5.7 / Next.js 15, Python 3 / FastAPI, Zustand v5, pytest, Jest

---

## Winston Audit — Verified Findings

After reading every cited file, here is the corrected finding list. False positives are documented so future reviews don't re-raise them.

### CONFIRMED — will fix

| ID | Severity | Description |
|----|----------|-------------|
| C1 | HIGH | `statusForScore()` uses ≥70=PASS / ≥50=CAUTION but backend `score_thresholds` uses pass:55 / caution:35. Score of 60 passes the scan but shows CAUTION in the UI score bar. |
| C4 | MEDIUM | `ivThresholds.ts` hardcodes `IV_PASS_MAX = {Swing:34, Position:44}` but backend YAML has `iv_rank_pass_max: null`. Frontend colourises rows "green" for IV ≤34 using a threshold the backend doesn't enforce. |
| C3 | MEDIUM | Fundamentals gate defaults live in THREE places: `fundamentals_scorer.py _DEFAULT_CFG`, `scoring_rules.yaml`, and `settingsStore.ts DEFAULT_FUNDAMENTALS_GATE`. Values currently match but are a maintenance trap. |
| R1 | LOW | `RunScanButton:149` has a dead fallback `fundamentalsGate ?? { ... }`. `fundamentalsGate` is never `undefined`: settingsStore has `skipHydration: true`, initial state sets `fundamentalsGate: { ...DEFAULT_FUNDAMENTALS_GATE }`, and migration v16 guards old persisted states. |
| C2 | LOW | Confidence badge `data-tier="medium"` for scores 50–70, but the backend gate passes (no demotion) at confidence ≥50. Users see a yellow-toned badge on stocks the backend already approved. Fix: rename tier to `'moderate'`; add tooltip. |
| I3 | LOW | `score_thresholds: {pass:55, caution:35}` in `scoring_rules.yaml` has no comment clarifying it's backend-only. Looks like dead config — add a comment. |

### FALSE POSITIVES — do NOT fix

Verified by reading the actual source files noted below.

| Winston ID | Why it is not a real issue | Evidence location |
|------------|---------------------------|-------------------|
| E1 (regimeConfirmedRef stale) | Ref is set `true` synchronously before `onClick()` runs; regime check at line 106 is synchronous; ref reset to `false` after — all before the async API call. Pattern is correct. | `RunScanButton/index.tsx:207–213` |
| E2 (result.rejected ?? []) | `ScanResult.rejected` is typed `RejectedEntry[]` (not optional). The `?? []` is harmless dead code, not an unsafe type path. | `frontend/lib/scanStore.ts:39` |
| E3 (alertStore void fetch) | `notifyBackend()` wraps `void fetch()` in a `try/catch` and the promise has `.catch(() => {})`. Already fully guarded. | `frontend/lib/alertStore.ts:82–98` |
| I1 (combinedRegime persisted) | `partialize` in `scanStore.ts:185–202` does NOT include `regime` or `combinedRegime`. Both reset to `'PENDING'` on every page load. Confirmed: grep `combinedRegime` in partialize returns no match. | `frontend/lib/scanStore.ts:185–202` |
| P2 (signalFor/signalLabel recreated) | Both functions are at module scope (`step-4-ranking/page.tsx:51–59`), not inside the component function. They are never recreated on render. | `step-4-ranking/page.tsx:51–59` |

---

## Files Modified

| File | Change |
|------|--------|
| `frontend/lib/status.ts` | Update `statusForScore` thresholds to 55/35 |
| `frontend/__tests__/status.test.ts` | Replace test assertions to match new thresholds |
| `backend/config/scoring_rules.yaml` | Add `iv_rank_pass_max` to Swing/Position vol sections; clarify `score_thresholds` comment |
| `frontend/lib/ivThresholds.ts` | Add sync comment only — values are already correct |
| `backend/app/scoring/fundamentals_scorer.py` | Remove `_DEFAULT_CFG`; load from YAML via `signal_confidence._cfg` |
| `frontend/components/organisms/RunScanButton/index.tsx` | Remove dead `?? {...}` fallback on line 149 |
| `frontend/lib/confidenceText.ts` | Rename `'medium'` tier → `'moderate'` in `ConfidenceTier` type and `confidenceTier()` |
| `frontend/components/atoms/ConfidenceBadge/index.tsx` | Add `title` prop for moderate tier; no label text change (badge renders `${confidence}%`) |
| `backend/tests/test_vol_scorer.py` | Add test for `iv_rank_pass_max` with iv_rank above/below threshold |

---

## Task 1 — Fix score threshold mismatch (C1)

**Files:**
- Modify: `frontend/lib/status.ts:24-28`
- Replace: `frontend/__tests__/status.test.ts` (file already exists with old 70/50 thresholds — full replacement required)

**Context:** The backend `score_thresholds` in `scoring_rules.yaml` defines pass:55, caution:35.
The frontend `statusForScore()` currently uses 70/50. A stock at score=60 passes the backend scan
but is displayed as CAUTION in every score bar in the UI.

The existing `frontend/__tests__/status.test.ts` tests `>= 70` for PASS and `>= 50` for CAUTION.
These assertions will fail after the fix — which is correct TDD behaviour. The file MUST be
replaced, not appended to, because the old assertions directly contradict the new thresholds.

- [ ] **Step 1: Replace the entire contents of `frontend/__tests__/status.test.ts`**

```typescript
import { statusForScore } from '@/lib/status';

describe('statusForScore', () => {
  it('returns PASS for score >= 55', () => {
    expect(statusForScore(55)).toBe('PASS');
    expect(statusForScore(60)).toBe('PASS');
    expect(statusForScore(100)).toBe('PASS');
  });

  it('returns CAUTION for score 35–54', () => {
    expect(statusForScore(35)).toBe('CAUTION');
    expect(statusForScore(54)).toBe('CAUTION');
  });

  it('returns REJECT for score < 35', () => {
    expect(statusForScore(0)).toBe('REJECT');
    expect(statusForScore(34)).toBe('REJECT');
  });

  it('respects max parameter — percentage is computed then compared', () => {
    // (55 / 200) * 100 = 27.5% → REJECT (< 35)
    expect(statusForScore(55, 200)).toBe('REJECT');
    // (110 / 200) * 100 = 55% → PASS (>= 55)
    expect(statusForScore(110, 200)).toBe('PASS');
  });
});
```

- [ ] **Step 2: Run test to confirm it fails (OLD code, NEW assertions)**

```bash
cd "F:\Git\GitHub\Trading assistant\frontend"
npm run test -- --testPathPattern=status.test
```

Expected: FAIL — current thresholds are 70/50. `statusForScore(55)` returns `'CAUTION'`, not `'PASS'`.

- [ ] **Step 3: Update `statusForScore` in `frontend/lib/status.ts`**

Replace the function body (lines 24–28):

```typescript
export function statusForScore(value: number, max = 100): Status {
  const pct = (value / max) * 100;
  if (pct >= 55) return 'PASS';
  if (pct >= 35) return 'CAUTION';
  return 'REJECT';
}
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
npm run test -- --testPathPattern=status.test
```

Expected: all 4 tests PASS

- [ ] **Step 5: Run typecheck**

```bash
npm run typecheck
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/status.ts frontend/__tests__/status.test.ts
git commit -m "fix(status): align statusForScore thresholds with backend score_thresholds (55/35)"
```

---

## Task 2 — Add iv_rank_pass_max to backend YAML (C4)

**Files:**
- Modify: `backend/config/scoring_rules.yaml` — Swing vol section (~line 98), Position vol section (~line 239)
- Modify: `frontend/lib/ivThresholds.ts` — add sync comment (values already correct)
- Add: `backend/tests/test_vol_scorer.py` — new test for pass_max gate

**Context:** `ivThresholds.ts` defines `IV_PASS_MAX = {Swing:34, Position:44}` with correct values.
The bug is that backend YAML has `iv_rank_pass_max: null` for these horizons — the scorer skips the
pass gate entirely when null. Adding the values to YAML makes the backend enforce the same boundary
the frontend already displays.

Key insight: with `iv_rank_pass_max: null`, `stock_scorer.py` line 819–822 returns `PASS 90`
unconditionally, bypassing the IV comparison. So the "before" test must use `iv_rank > 34` to detect
a case where pass_max matters — after adding `34` to YAML, that iv_rank gets CAUTION instead of PASS.

- [ ] **Step 1: Confirm scorer already reads iv_rank_pass_max**

```bash
grep -n "iv_rank_pass_max" "F:\Git\GitHub\Trading assistant\backend\app\scoring\stock_scorer.py"
```

Expected output includes lines 819 (`if vc["iv_rank_pass_max"] is None:`), 826 (`pass_max = vc["iv_rank_pass_max"]`), 831 (`if iv_rank <= pass_max:`), and 950 (override handler). The scorer already handles non-null values — no scorer code changes needed.

- [ ] **Step 2: Write the backend test**

The repo loads OHLCV bars via `candles_for(symbol)` from `app.fixtures.candles`, which reads
`backend/tests/fixtures/{SYMBOL}_candles.json` and returns `list[Candle]`. Convert to dicts
with `.model_dump(by_alias=False)` — this is the same pattern used in `conftest.py:230`.

Create `backend/tests/test_vol_scorer.py`:

```python
"""Tests for vol scoring rule — iv_rank_pass_max gate."""
from app.scoring.stock_scorer import score_stock
from app.fixtures.candles import candles_for


def _bars(symbol: str = "AAPL") -> list[dict]:
    """Load fixture candles as plain dicts (same pattern as conftest.py:229–230)."""
    return [c.model_dump(by_alias=False) for c in candles_for(symbol)]


def test_iv_rank_above_pass_max_returns_caution_after_yaml_update():
    """With iv_rank_pass_max=34 in YAML (Swing), iv_rank=40 must return CAUTION on vol component."""
    result = score_stock(
        symbol="TEST",
        direction="Bullish",
        horizon="Swing",
        bars=_bars(),
        iv_rank=40.0,           # above pass_max=34, below caution_max=55 → CAUTION
    )
    vol_status = result.breakdown.get("vol", {}).get("status") or result.breakdown.get("vol", "UNKNOWN")
    assert vol_status == "CAUTION", (
        f"Expected vol=CAUTION for iv_rank=40 (above pass_max=34), got {vol_status}. "
        "Did you add iv_rank_pass_max: 34 to scoring_rules.yaml Swing vol section?"
    )


def test_iv_rank_below_pass_max_returns_pass_after_yaml_update():
    """With iv_rank_pass_max=34 in YAML (Swing), iv_rank=20 must return PASS on vol component."""
    result = score_stock(
        symbol="TEST",
        direction="Bullish",
        horizon="Swing",
        bars=_bars(),
        iv_rank=20.0,           # below pass_max=34 → PASS
    )
    vol_status = result.breakdown.get("vol", {}).get("status") or result.breakdown.get("vol", "UNKNOWN")
    assert vol_status == "PASS", (
        f"Expected vol=PASS for iv_rank=20 (below pass_max=34), got {vol_status}."
    )
```

- [ ] **Step 3: Run the test BEFORE the YAML change — confirm it fails**

```bash
cd "F:\Git\GitHub\Trading assistant\backend"
pytest tests/test_vol_scorer.py -v 2>&1 | tail -20
```

Expected: `test_iv_rank_above_pass_max_returns_caution_after_yaml_update` FAILS because with
`iv_rank_pass_max: null` the scorer returns `PASS 90` regardless of `iv_rank=40`.

- [ ] **Step 4: Update scoring_rules.yaml — Swing vol section (~line 98)**

```yaml
    vol:
      iv_rank_compressed_caution: 5
      iv_rank_pass_max: 34     # IV rank <= this -> PASS; mirrors frontend ivThresholds.ts
      iv_rank_caution_max: 55
```

- [ ] **Step 5: Update scoring_rules.yaml — Position vol section (~line 239)**

```yaml
    vol:
      iv_rank_compressed_caution: 5
      iv_rank_pass_max: 44     # IV rank <= this -> PASS; mirrors frontend ivThresholds.ts
      iv_rank_caution_max: 65
```

- [ ] **Step 6: Add clarifying comment to score_thresholds (I3 fix — low cost here)**

Find `score_thresholds` at the top of `scoring_rules.yaml` (lines 3–5) and add comment:

```yaml
# score_thresholds: used by the backend scan pipeline to classify candidates.
# The frontend statusForScore() mirrors these values — see frontend/lib/status.ts.
score_thresholds:
  pass: 55
  caution: 35
```

- [ ] **Step 7: Run the test AFTER the YAML change — confirm both tests pass**

```bash
pytest tests/test_vol_scorer.py -v 2>&1 | tail -20
```

Expected: PASS for both tests. The CAUTION test now works because `pass_max=34` is set and `iv_rank=40 > 34`.

- [ ] **Step 8: Run full backend test suite**

```bash
pytest tests/ -v -x 2>&1 | tail -30
```

Expected: all tests pass

- [ ] **Step 9: Update ivThresholds.ts comment (frontend — values unchanged)**

Replace the content of `frontend/lib/ivThresholds.ts`:

```typescript
// Per-horizon IV rank thresholds — mirrors scoring_rules.yaml horizons[N].vol section.
// iv_rank_pass_max and iv_rank_caution_max MUST stay in sync with the YAML.
// To change these thresholds, update the YAML first, then update values here.
// Intraday vol gate is disabled (null) — options screener uses its own IV logic for intraday.
export const IV_PASS_MAX: Record<string, number | null> = {
  Intraday: null,
  Swing:    34,
  Position: 44,
};

export const IV_CAUTION_MAX: Record<string, number | null> = {
  Intraday: null,
  Swing:    55,
  Position: 65,
};
```

- [ ] **Step 10: Run frontend typecheck**

```bash
cd "F:\Git\GitHub\Trading assistant\frontend"
npm run typecheck
```

Expected: no errors

- [ ] **Step 11: Commit**

```bash
git add backend/config/scoring_rules.yaml frontend/lib/ivThresholds.ts backend/tests/test_vol_scorer.py
git commit -m "fix(iv-thresholds): add iv_rank_pass_max to YAML (Swing:34, Position:44); add regression tests; clarify score_thresholds comment"
```

---

## Task 3 — Consolidate fundamentals gate defaults (C3 + R1)

**Files:**
- Modify: `backend/app/scoring/fundamentals_scorer.py` — remove `_DEFAULT_CFG`; import `_cfg` from `signal_confidence`
- Modify: `frontend/components/organisms/RunScanButton/index.tsx:149` — remove dead `?? {...}` fallback

**Context:** `_DEFAULT_CFG` in `fundamentals_scorer.py` duplicates `scoring_rules.yaml`. The YAML is
already cached by `signal_confidence._cfg()` (with `@lru_cache(maxsize=1)`). Reuse that same cached
loader rather than adding a second cache — avoids a dual-cache problem where test monkeypatching
would need to clear two separate lru_cache instances.

Side-effect to document: `_DEFAULT_CFG` does NOT include the `cautionAbove`/`rejectAbove` keys
present in the YAML (lines 270–271). After the fix, `score_fundamentals(cfg=None)` will receive
these extra keys. They are harmless — `score_fundamentals` only calls `cfg.get("weights", ...)`,
`cfg.get("safety", {})`, and `cfg.get("thresholds", {})` — but the change is documented here
so a future reviewer doesn't assume the cfg dict shape is identical to the old `_DEFAULT_CFG`.

- [ ] **Step 1: Confirm _DEFAULT_CFG has only one caller**

```bash
grep -rn "_DEFAULT_CFG" "F:\Git\GitHub\Trading assistant\backend\app" | grep -v "__pycache__"
```

Expected: only `fundamentals_scorer.py` lines 30 (definition) and 104 (usage). If other files
reference it, add them to the modification list before proceeding.

- [ ] **Step 2: Check that signal_confidence._cfg() is importable**

```bash
python -c "from app.scoring.signal_confidence import _cfg; print(_cfg()['confidence_gate'])" 2>&1
```

Run from `backend/`. Expected: prints the confidence_gate dict from the YAML.
If this fails (e.g. module not found), check that you're running from the `backend/` directory.

- [ ] **Step 3: Write a regression test for the default-cfg path**

Add to `backend/tests/test_fundamentals_scorer.py` (create if absent):

```python
"""Regression: score_fundamentals(cfg=None) must load config from YAML, not _DEFAULT_CFG."""
from app.scoring.fundamentals_scorer import score_fundamentals
from app.data.edgar import FundamentalsSnapshot


def _snap(**kwargs) -> FundamentalsSnapshot:
    defaults = dict(
        revenue_growth_yoy=0.20, eps_growth_yoy=0.20,
        gross_margin=0.50, operating_margin=0.20,
        debt_to_equity=0.4, current_ratio=2.5, share_growth_yoy=0.0,
        total_equity=1e9, staleness_days=10,
    )
    defaults.update(kwargs)
    return FundamentalsSnapshot(**defaults)


def test_score_fundamentals_cfg_none_returns_valid_score():
    """Passing cfg=None must not raise and must return a score in 0–100."""
    result = score_fundamentals(_snap(), direction="Bullish", cfg=None)
    assert 0 <= result.score <= 100


def test_score_fundamentals_cfg_none_uses_yaml_weights():
    """Weights from YAML (growth:0.35, quality:0.35, risk:0.30) must be applied, not hard-coded."""
    result_via_none = score_fundamentals(_snap(), direction="Bullish", cfg=None)
    # Pass explicit cfg matching YAML defaults — scores must match.
    explicit_cfg = {
        "weights": {"growth": 0.35, "quality": 0.35, "risk": 0.30},
        "safety": {"reject_on_negative_equity": True, "debt_to_equity_reject": 3.0},
        "thresholds": {},
    }
    result_via_explicit = score_fundamentals(_snap(), direction="Bullish", cfg=explicit_cfg)
    assert result_via_none.score == result_via_explicit.score, (
        f"cfg=None returned {result_via_none.score} but explicit cfg returned "
        f"{result_via_explicit.score} — YAML weights are not being applied."
    )
```

- [ ] **Step 4: Run test BEFORE the change — confirm it passes (baseline)**

```bash
cd "F:\Git\GitHub\Trading assistant\backend"
pytest tests/test_fundamentals_scorer.py -v 2>&1 | tail -20
```

Expected: PASS (baseline — current _DEFAULT_CFG must also produce correct scores)

- [ ] **Step 5: Update fundamentals_scorer.py**

Add the import at the top of `backend/app/scoring/fundamentals_scorer.py` (after existing imports):

```python
from app.scoring.signal_confidence import _cfg as _load_yaml_cfg
```

Then remove `_DEFAULT_CFG` and update its usage. Use content-anchored edits (not line numbers, which
can shift). Find and delete the entire block starting with `_DEFAULT_CFG: dict = {` down to and
including its closing `}` on its own line (~20 lines of dict content). Then:

**Replace this block (the cfg-None fallback in `score_fundamentals`):**

```python
    if cfg is None:
        cfg = _DEFAULT_CFG
```

**With:**

```python
    if cfg is None:
        # Load from scoring_rules.yaml[fundamentals_gate] — same cached loader as signal_confidence.
        # The YAML dict includes extra keys (cautionAbove, rejectAbove) not in the old _DEFAULT_CFG;
        # these are unused by score_fundamentals but harmless.
        cfg = _load_yaml_cfg()["fundamentals_gate"]
```

- [ ] **Step 6: Run the regression test AFTER the change**

```bash
pytest tests/test_fundamentals_scorer.py -v 2>&1 | tail -20
```

Expected: PASS — scores unchanged because YAML values match the old `_DEFAULT_CFG` values.

- [ ] **Step 7: Run full backend test suite**

```bash
pytest tests/ -v -x 2>&1 | tail -30
```

Expected: all pass

- [ ] **Step 8: Remove dead fundamentalsGate fallback from RunScanButton (R1)**

Open `frontend/components/organisms/RunScanButton/index.tsx` and find line 149:

```typescript
const fGate = fundamentalsGate ?? { enabled: true, cautionBelow: 45, rejectBelow: 30, deReject: 3.0 };
```

Replace with:

```typescript
const fGate = fundamentalsGate;
```

Rationale: `useSettingsStore` initialises with `fundamentalsGate: { ...DEFAULT_FUNDAMENTALS_GATE }`
and has `skipHydration: true`, so SSR gets the default value. Migration v16 ensures persisted states
also have the field. `fundamentalsGate` is typed `FundamentalsGate` (non-optional) in `SettingsState`.
The `?? {...}` is provably dead code containing magic numbers that could silently diverge.

- [ ] **Step 9: Run frontend typecheck**

```bash
cd "F:\Git\GitHub\Trading assistant\frontend"
npm run typecheck
```

Expected: no errors. TypeScript already types `fundamentalsGate` as `FundamentalsGate` (non-optional),
so removing `?? {...}` has no type impact — `fGate` stays typed as `FundamentalsGate`.

- [ ] **Step 10: Commit**

```bash
git add backend/app/scoring/fundamentals_scorer.py backend/tests/test_fundamentals_scorer.py frontend/components/organisms/RunScanButton/index.tsx
git commit -m "fix(fundamentals): remove _DEFAULT_CFG; load from YAML via signal_confidence._cfg; remove dead RunScanButton fallback"
```

---

## Task 4 — Fix confidence tier naming (C2)

**Files:**
- Modify: `frontend/lib/confidenceText.ts` — rename `'medium'` → `'moderate'` in `ConfidenceTier` type and `confidenceTier()` return
- Modify: `frontend/components/atoms/ConfidenceBadge/index.tsx` — add tooltip for moderate tier
- Update: any test files that reference the string `'medium'` as a ConfidenceTier value

**Context:** The `ConfidenceBadge` renders `${confidence}%` (e.g. "55%"), not a text tier label.
The tier name (`'medium'`) surfaces only via the `data-tier` attribute and the caution tone colour.
Renaming to `'moderate'` fixes the conceptual confusion (backend gate passes at ≥50, but "medium"
sounds bad) while adding a tooltip to explain "moderate confidence still passes the gate."

`ConfidenceTier` is defined in `confidenceText.ts` and used by `ConfidenceBadge` via the `data-tier`
attribute. There is no user-visible text label to change — only the tier string value and CSS/data attribute.

- [ ] **Step 1: Find all usages of the string 'medium' as a ConfidenceTier**

```bash
grep -rn "'medium'\|\"medium\"" "F:\Git\GitHub\Trading assistant\frontend" --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".next"
```

Write down every file and line. You must update each one.

- [ ] **Step 2: Write the failing test**

Create `frontend/__tests__/confidenceText.test.ts`:

```typescript
import { confidenceTier, confidenceTone, type ConfidenceTier } from '@/lib/confidenceText';

describe('confidenceTier', () => {
  it('returns "high" for confidence >= 70', () => {
    expect(confidenceTier(70)).toBe('high');
    expect(confidenceTier(100)).toBe('high');
  });

  it('returns "moderate" (not "medium") for confidence 50–69', () => {
    expect(confidenceTier(50)).toBe('moderate');
    expect(confidenceTier(69)).toBe('moderate');
    expect(confidenceTier(55)).toBe('moderate');
  });

  it('returns "low" for confidence < 50', () => {
    expect(confidenceTier(49)).toBe('low');
    expect(confidenceTier(0)).toBe('low');
  });

  it('returns "unknown" for null/undefined', () => {
    expect(confidenceTier(null)).toBe('unknown');
    expect(confidenceTier(undefined)).toBe('unknown');
  });
});

describe('confidenceTone', () => {
  it('returns "caution" for moderate tier', () => {
    expect(confidenceTone('moderate')).toBe('caution');
  });
});
```

- [ ] **Step 3: Run test to confirm it fails**

```bash
cd "F:\Git\GitHub\Trading assistant\frontend"
npm run test -- --testPathPattern=confidenceText.test
```

Expected: FAIL — `confidenceTier(55)` currently returns `'medium'`, not `'moderate'`.

- [ ] **Step 4: Update confidenceText.ts**

Replace the entire file `frontend/lib/confidenceText.ts`:

```typescript
import type { DataTone } from '@/components/primitives';

export type ConfidenceTier = 'unknown' | 'low' | 'moderate' | 'high';

export function confidenceTier(confidence: number | null | undefined): ConfidenceTier {
  if (confidence === null || confidence === undefined) return 'unknown';
  if (confidence >= 70) return 'high';
  if (confidence >= 50) return 'moderate';
  return 'low';
}

export function confidenceTone(tier: ConfidenceTier): DataTone {
  switch (tier) {
    case 'high':     return 'pass';
    case 'moderate': return 'caution';
    case 'low':      return 'reject';
    default:         return 'dim';
  }
}
```

- [ ] **Step 5: Update ConfidenceBadge to add tooltip for moderate tier**

Replace the content of `frontend/components/atoms/ConfidenceBadge/index.tsx`:

```typescript
import { Data } from '@/components/primitives';
import { confidenceTier, confidenceTone } from '@/lib/confidenceText';
import styles from './ConfidenceBadge.module.css';

const MODERATE_TOOLTIP = 'Moderate — confidence ≥50 still passes the gate; treat with normal care';

export function ConfidenceBadge({
  confidence,
  title,
}: {
  confidence: number | null | undefined;
  title?: string;
}) {
  const tier = confidenceTier(confidence);
  const tone = confidenceTone(tier);
  const label = confidence === null || confidence === undefined ? '—' : `${confidence}%`;
  const resolvedTitle = title ?? (tier === 'moderate' ? MODERATE_TOOLTIP : undefined);
  return (
    <span className={styles.badge} data-tier={tier} title={resolvedTitle}>
      <Data size={12} weight={500} tone={tone}>
        {label}
      </Data>
    </span>
  );
}
```

- [ ] **Step 6: Fix all callers that reference 'medium' as a ConfidenceTier**

For each file found in Step 1 that uses `'medium'` as a tier value:
- Replace `'medium'` with `'moderate'`
- If any CSS module uses `[data-tier="medium"]`, rename the selector to `[data-tier="moderate"]`

Check the CSS module:

```bash
grep -n "medium" "F:\Git\GitHub\Trading assistant\frontend\components\atoms\ConfidenceBadge\ConfidenceBadge.module.css"
```

If found, rename `[data-tier="medium"]` → `[data-tier="moderate"]`.

- [ ] **Step 7: Run all tests**

```bash
npm run test -- --testPathPattern="confidenceText|ConfidenceBadge"
```

Expected: all pass

- [ ] **Step 8: Run typecheck**

```bash
npm run typecheck
```

Expected: no errors. TypeScript will catch any remaining `'medium'` usage via the `ConfidenceTier` type.

- [ ] **Step 9: Commit**

```bash
git add frontend/lib/confidenceText.ts \
        frontend/components/atoms/ConfidenceBadge/index.tsx \
        frontend/components/atoms/ConfidenceBadge/ConfidenceBadge.module.css \
        frontend/__tests__/confidenceText.test.ts
git commit -m "fix(confidence): rename tier 'medium' -> 'moderate'; add tooltip clarifying gate-pass status"
```

Note: `ConfidenceBadge.module.css` is included even if Step 6 finds no `[data-tier="medium"]` selector
(the add is a no-op if the file was not modified). This prevents accidentally shipping a commit where
the data-tier rename is applied in TSX but the CSS selector was missed.

---

## Self-Review

**Spec coverage check:**

| Winston finding | Plan task | Adversarial correction |
|-----------------|-----------|------------------------|
| C1 score threshold | Task 1 | Step 1 now says "replace" not "create if absent" |
| C4 IV_PASS_MAX | Task 2 | Test rewritten to use named `iv_rank=` param; fail-before logic fixed |
| I3 dead score_thresholds comment | Task 2, Step 6 | — |
| C3 triple fundamentals defaults | Task 3 | Reuses `signal_confidence._cfg` — no duplicate lru_cache |
| R1 dead RunScanButton fallback | Task 3, Step 8 | Added SSR verification rationale; confirmed safe |
| C2 confidence badge UX | Task 4 | Retargeted to `confidenceText.ts` (correct file); test uses `data-tier`, not `getByText` |
| All FALSE POSITIVES | Documented in header with evidence locations | — |

**Placeholder scan:** No TBDs, no vague steps. Every step shows exact code or exact commands.

**Type consistency:**
- `statusForScore` signature unchanged — callers unaffected.
- `ConfidenceTier` changes from `'medium'` to `'moderate'` — TypeScript enforces this at compile time, so all missed callsites become type errors caught by `npm run typecheck`.
- `FundamentalsGate` interface unchanged — `fGate` in RunScanButton stays typed correctly.

**Order dependency:** Tasks 1, 2, 3, 4 are independent and can run in parallel or any order.
Task 3 Step 8 (RunScanButton) should run after Task 3 Steps 1–7 (backend) are confirmed passing.
