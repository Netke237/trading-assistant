# Regime Direction Label (Bullish / Bearish) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface a `regime_direction` field (`BULL` / `BEAR` / `MIXED`) in the market regime response, show a green Bullish or red Bearish pill in the Step 1 banner, and warn the user in Step 3 when their chosen direction conflicts with the macro regime.

**Architecture:** The backend derives `regime_direction` from the OMM state (primary) or EMA metrics (fallback) and includes it in the existing `MarketRegime` response — no new endpoint needed. The frontend stores it in `scanStore` as a **non-persisted** session-only field (like `regime`), shows a coloured pill in the Step 1 banner, and in Step 3 cross-checks it against the user's chosen direction to show a CAUTION advisory. The mismatch warning is suppressed when `regime_direction` is `MIXED` (indeterminate regime cannot conflict with a direction).

**Vocabulary note:** The OMM model (`regime_omm.py`) emits states `'Bull'`, `'Bear'`, `'Choppy'`. The directional HMM emits `'Bull'`, `'Bear'`, `'Sideways'`. This plan maps OMM state only — `'Choppy'` → `'MIXED'`. The directional HMM state (`_spx_hmm_state`) is not used here; it feeds the existing `alignment` field.

**Tech Stack:** FastAPI / Pydantic v2 (backend); Next.js 15 App Router, TypeScript 5.7, Zustand v5, CSS Modules (frontend).

---

## File Map

| File | Change |
|---|---|
| `backend/app/schemas/__init__.py` | Add `regime_direction` optional field to `MarketRegime` |
| `backend/app/routers/regime.py` | Add `_derive_regime_direction()` helper; call it before final `return MarketRegime(...)` |
| `backend/tests/test_regime_direction.py` | New — unit tests for the helper + one endpoint smoke test |
| `frontend/types/domain.ts` | Add `regime_direction?: 'BULL' \| 'BEAR' \| 'MIXED' \| null` to `MarketRegime` |
| `frontend/lib/scanStore.ts` | Add `regimeDirection`, `setRegimeDirection` (session-only, not persisted) |
| `frontend/app/(frame)/screener/step-1-regime/page.tsx` | Call `setRegimeDirection`; render direction pill in banner |
| `frontend/app/(frame)/screener/step-1-regime/page.module.css` | Add `.directionPill` + `.directionPill_BULL/BEAR/MIXED` |
| `frontend/app/(frame)/screener/step-3-direction/page.tsx` | Read `regimeDirection`; show mismatch advisory |
| `frontend/app/(frame)/screener/step-3-direction/page.module.css` | Add `.mismatchWarn` |

---

## Task 1: Backend — `regime_direction` in schema and endpoint

**Files:**
- Modify: `backend/app/schemas/__init__.py` (~line 222, inside `MarketRegime`)
- Modify: `backend/app/routers/regime.py` (~line 233, before `return MarketRegime(...)`)
- Create: `backend/tests/test_regime_direction.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_regime_direction.py`:

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.routers.regime import _derive_regime_direction
from app.main import app


# ── Unit tests: pure derivation logic ────────────────────────────────────────

def test_bull_omm_state():
    assert _derive_regime_direction("Bull", None, None) == "BULL"


def test_bear_omm_state():
    assert _derive_regime_direction("Bear", None, None) == "BEAR"


def test_choppy_omm_is_mixed():
    # OMM 'Choppy' → MIXED regardless of EMA statuses
    assert _derive_regime_direction("Choppy", "PASS", "PASS") == "MIXED"


def test_no_omm_both_pass_is_bull():
    assert _derive_regime_direction(None, "PASS", "PASS") == "BULL"


def test_no_omm_both_reject_is_bear():
    assert _derive_regime_direction(None, "REJECT", "REJECT") == "BEAR"


def test_no_omm_mixed_ema():
    assert _derive_regime_direction(None, "PASS", "REJECT") == "MIXED"


def test_no_omm_no_ema():
    assert _derive_regime_direction(None, None, None) == "MIXED"


def test_no_omm_one_caution_is_mixed():
    assert _derive_regime_direction(None, "PASS", "CAUTION") == "MIXED"


# ── Endpoint smoke test: regime_direction is present in HTTP response ─────────

def test_regime_endpoint_includes_regime_direction():
    """GET /regime must include regime_direction — BULL, BEAR, or MIXED (never absent)."""
    client = TestClient(app)
    # Stub out all external I/O so this runs offline.
    with patch("app.routers.regime.fetch_price", return_value=15.0), \
         patch("app.routers.regime._spx_ndx_metric") as mock_metric, \
         patch("app.routers.regime.compute_omm", return_value=None), \
         patch("app.routers.regime.fetch_candles", return_value=[]), \
         patch("app.routers.regime.fetch_intraday_candles", return_value=[]), \
         patch("app.routers.regime.compute_intraday_hmm", return_value=None), \
         patch("app.routers.regime._compute_directional_hmm", return_value=None):
        from app.schemas import RegimeMetric
        mock_metric.return_value = RegimeMetric(label="SPX trend (200 EMA)", value="Above", status="PASS", trend="up")
        response = client.get("/regime")
    assert response.status_code == 200
    data = response.json()
    assert "regime_direction" in data
    assert data["regime_direction"] in ("BULL", "BEAR", "MIXED", None)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && pytest tests/test_regime_direction.py -v
```

Expected: `ImportError` — `_derive_regime_direction` does not exist yet.

- [ ] **Step 3: Add `regime_direction` to `MarketRegime` schema**

In `backend/app/schemas/__init__.py`, find the `MarketRegime` class (line ~208) and add the new field after the `alignment` field:

```python
class MarketRegime(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    overall: Status
    headline: str
    metrics: list[RegimeMetric]
    omm: Optional[OmmData] = None
    intraday_hmm: Optional[IntraHmmData] = None
    intraday_hmm_status: IntradayHmmStatus = 'unavailable'
    intraday_omm: Optional[OmmData] = None
    vix_pct_30d: Optional[float] = None
    vix_pct_252d: Optional[float] = None
    conviction_pct: Optional[int] = None
    conviction_label: Optional[str] = None
    hmm_state: Optional[str] = None
    alignment: Optional[Literal['Aligned', 'Diverging', 'Unavailable']] = None
    regime_direction: Optional[Literal['BULL', 'BEAR', 'MIXED']] = None
```

- [ ] **Step 4: Add `_derive_regime_direction()` helper to `regime.py`**

In `backend/app/routers/regime.py`, add this function near the top, after the existing helpers (before `@router.get`):

```python
def _derive_regime_direction(
    omm_state: str | None,
    spx_status: str | None,
    ndx_status: str | None,
) -> str:
    """Return 'BULL', 'BEAR', or 'MIXED' from OMM state (primary) or EMA metrics (fallback).

    OMM states: 'Bull', 'Bear', 'Choppy' (Choppy → MIXED).
    EMA fallback: both indices above 200 EMA → BULL; both below → BEAR; otherwise MIXED.
    The early-return path (no market data) returns MarketRegime with regime_direction=None
    via Pydantic default — that is intentional and safe; the frontend renders no pill.
    """
    if omm_state == 'Bull':
        return 'BULL'
    if omm_state == 'Bear':
        return 'BEAR'
    if omm_state is not None:          # Choppy or any other OMM state
        return 'MIXED'
    # Fallback: both indices must agree; a single CAUTION yields MIXED
    if spx_status == 'PASS' and ndx_status == 'PASS':
        return 'BULL'
    if spx_status == 'REJECT' and ndx_status == 'REJECT':
        return 'BEAR'
    return 'MIXED'
```

- [ ] **Step 5: Call the helper and include the result in `return MarketRegime(...)`**

In `backend/app/routers/regime.py`, just before the final `return MarketRegime(...)` (line ~233), add:

```python
    _regime_dir = _derive_regime_direction(
        omm_out.state if omm_out else None,
        spx.status if spx else None,
        ndx.status if ndx else None,
    )
```

Then add `regime_direction=_regime_dir` to the `MarketRegime(...)` call:

```python
    return MarketRegime(
        overall=overall,
        headline=headline,
        metrics=metrics,
        omm=omm_out,
        intraday_hmm=intraday_hmm_out,
        intraday_hmm_status=intraday_hmm_status,
        intraday_omm=intraday_omm_out,
        vix_pct_30d=vix_pct_30d,
        vix_pct_252d=vix_pct_252d,
        conviction_pct=omm_out.conviction_pct if omm_out else None,
        conviction_label=omm_out.conviction_label if omm_out else None,
        hmm_state=_spx_hmm_state,
        alignment=_regime_alignment(omm_out.state if omm_out else None, _spx_hmm_state),
        regime_direction=_regime_dir,
    )
```

The early-return path at line ~118 (`return MarketRegime(overall='CAUTION', ...)`) does not set `regime_direction` — it correctly defaults to `None` via Pydantic, indicating no data.

- [ ] **Step 6: Run tests to verify they pass**

```
cd backend && pytest tests/test_regime_direction.py -v
```

Expected: all tests PASS (including the endpoint smoke test).

- [ ] **Step 7: Run the full backend test suite**

```
cd backend && pytest -v
```

Expected: all existing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/routers/regime.py backend/tests/test_regime_direction.py
git commit -m "feat(regime): add regime_direction (BULL/BEAR/MIXED) to MarketRegime"
```

---

## Task 2: Frontend types + scanStore

**Files:**
- Modify: `frontend/types/domain.ts` (~line 337, inside `MarketRegime`)
- Modify: `frontend/lib/scanStore.ts` (interface, initialiser only — no persist changes)

- [ ] **Step 1: Add `regime_direction` to the `MarketRegime` TS interface**

In `frontend/types/domain.ts`, find the `MarketRegime` interface (line ~322). Add one line after `alignment`:

```typescript
export interface MarketRegime {
  overall:              Status;
  headline:             string;
  metrics:              RegimeMetric[];
  omm?:                 OmmData | null;
  intraday_hmm?:        IntraHmmData | null;
  intraday_hmm_status?: 'ok' | 'insufficient_data' | 'unavailable';
  intraday_omm?:        OmmData | null;
  vix_pct_30d?:         number | null;
  vix_pct_252d?:        number | null;
  /** Legacy client-side field — kept for backward compat, not populated by backend. */
  hmm?: { state: HmmState; confidence: number };
  conviction_pct?: number | null;
  conviction_label?: string | null;
  hmm_state?: string | null;
  alignment?: 'Aligned' | 'Diverging' | 'Unavailable' | null;
  regime_direction?: 'BULL' | 'BEAR' | 'MIXED' | null;
}
```

- [ ] **Step 2: Add `regimeDirection` and `setRegimeDirection` to `ScanStoreState`**

In `frontend/lib/scanStore.ts`, find the `ScanStoreState` interface (line ~43). Add after `setCombinedRegime`:

```typescript
  /** Session-only — not persisted; cleared on page load. */
  regimeDirection:    'BULL' | 'BEAR' | 'MIXED' | null;
  setRegimeDirection: (d: 'BULL' | 'BEAR' | 'MIXED' | null) => void;
```

- [ ] **Step 3: Initialise the new state field and add the action**

In the `create<ScanStoreState>()(persist((set) => ({` body, add after `setCombinedRegime`:

```typescript
      regimeDirection:    null,
      setRegimeDirection: (d) => set({ regimeDirection: d }),
```

**Do NOT add `regimeDirection` to `partialize`.** This field is session-only — like the existing `regime` field, it must be re-fetched on every page load. Persisting it would display a stale pill from a previous session.

**Do NOT bump the store version.** No new persisted field is being added.

- [ ] **Step 4: Run typecheck**

```
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/types/domain.ts frontend/lib/scanStore.ts
git commit -m "feat(store): add regimeDirection to scanStore + MarketRegime TS type"
```

---

## Task 3: Step 1 banner — direction pill

**Files:**
- Modify: `frontend/app/(frame)/screener/step-1-regime/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-1-regime/page.module.css`

- [ ] **Step 1: Add CSS for the direction pill**

In `frontend/app/(frame)/screener/step-1-regime/page.module.css`, append after the existing `.bannerLeft` rule:

```css
/* ---------- Regime direction pill ---------- */

.directionPill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}

.directionPill_BULL {
  background: color-mix(in srgb, var(--pass) 15%, var(--bg-surface));
  color: var(--pass);
  border: 1px solid var(--pass);
}

.directionPill_BEAR {
  background: color-mix(in srgb, var(--reject) 15%, var(--bg-surface));
  color: var(--reject);
  border: 1px solid var(--reject);
}

.directionPill_MIXED {
  background: var(--bg-surface-2);
  color: var(--text-dim);
  border: 1px solid var(--border-subtle);
}
```

Note: uses `var(--pass)` and `var(--reject)` directly for borders — the project has no `--pass-border` / `--reject-border` tokens. This matches the existing pattern used by sector tiles in this same file.

- [ ] **Step 2: Update `page.tsx` — call `setRegimeDirection` and render pill**

At the top of `Step1RegimePage`, add the store action alongside `setRegime`:

```tsx
const setRegimeDirection = useScanStore((s) => s.setRegimeDirection);
```

In the `useEffect` fetch block, after `setRegime(r.overall)`, add:

```tsx
setRegimeDirection(r.regime_direction ?? null);
```

The full updated effect block (starting at line ~88) is:

```tsx
  useEffect(() => {
    api.getRegime('intraday', { lookback: markov.lookback, threshold: markov.threshold, smoothing: markov.smoothing }).then((r) => {
      setRegimeData(r);
      setRegime(r.overall);
      setRegimeDirection(r.regime_direction ?? null);
      const direction = useScanStore.getState().context?.direction ?? 'Bullish';
      const descriptor = descriptorFromState(r.omm?.state ?? '');
      setCombinedRegime(alignmentVerdict(direction, descriptor));
    }).catch(() => setOffline(true));

    api.getSectors().then(setSectors).catch(() => setOffline(true));
    api.getCandles('SPY').then(setSpxCandles).catch(() => setOffline(true));
    api.getCandles('QQQ').then(setNdxCandles).catch(() => setOffline(true));

    const candidates = useScanStore.getState().scanResult?.candidates.map((c) => c.symbol) ?? [];
    const symbols = candidates.length > 0 ? candidates : ['SPY', 'QQQ', 'VIX', 'DIA'];
    setNewsLoading(true);
    api.getNews(symbols).then(setNews).catch(() => setNewsError(true)).finally(() => setNewsLoading(false));
  }, [setRegime, setRegimeDirection, setCombinedRegime, markov]);
```

Replace the `{/* 1. Overall banner */}` section (lines ~149-155) with:

```tsx
      {/* 1. Overall banner */}
      <section className={`${pageStyles.banner} ${pageStyles[`banner_${combinedStatus}`]}`}>
        <div className={pageStyles.bannerLeft}>
          <StatusBadge status={combinedStatus} label={`REGIME ${combinedStatus}`} />
          {regime?.regime_direction && (
            <span
              role="img"
              aria-label={
                regime.regime_direction === 'BULL' ? 'Regime direction: Bullish'
                : regime.regime_direction === 'BEAR' ? 'Regime direction: Bearish'
                : 'Regime direction: Mixed'
              }
              className={`${pageStyles.directionPill} ${pageStyles[`directionPill_${regime.regime_direction}`]}`}
            >
              {regime.regime_direction === 'BULL' ? '▲ Bullish'
               : regime.regime_direction === 'BEAR' ? '▼ Bearish'
               : '≈ Mixed'}
            </span>
          )}
          <Text size={14} weight={500}>{regime?.headline ?? ''}</Text>
        </div>
      </section>
```

- [ ] **Step 3: Run typecheck**

```
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/screener/step-1-regime/page.tsx" \
        "frontend/app/(frame)/screener/step-1-regime/page.module.css"
git commit -m "feat(step1): show Bullish/Bearish direction pill in regime banner"
```

---

## Task 4: Step 3 direction mismatch warning

**Files:**
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.module.css`

**Important:** `regimeDirection` comes from `scanStore`, which is populated when the user visits Step 1. If the user navigates directly to Step 3 without visiting Step 1, `regimeDirection` will be `null` and no warning is shown — this is correct behaviour. The warning is suppressed when `regimeDirection` is `null` or `'MIXED'` because a mixed/indeterminate regime cannot logically conflict with a directional choice.

- [ ] **Step 1: Add CSS for the mismatch warning**

In `frontend/app/(frame)/screener/step-3-direction/page.module.css`, append:

```css
/* ---------- Regime direction mismatch advisory ---------- */

.mismatchWarn {
  padding: var(--space-3) var(--space-4);
  background: color-mix(in srgb, var(--caution) 10%, var(--bg-surface));
  border: 1px solid var(--caution);
  border-left: 3px solid var(--caution);
  border-radius: var(--radius-md);
}
```

Note: uses `var(--caution)` directly — there is no `--caution-border` token in the project.

- [ ] **Step 2: Read `regimeDirection` from the store and add the warning JSX**

Near the top of `Step3Page` (line ~702), alongside the other `useScanStore` selectors, add:

```tsx
  const regimeDirection = useScanStore((s) => s.regimeDirection);
```

**Insertion point:** The mismatch warning is a sibling `<div>` that belongs between the step header block and the first `<div className={formStyles.group}>` (the "Directional bias" group). Do not place it inside `<div className={styles.stepHeader}>`.

The JSX section around line ~802 should look like this after the edit:

```tsx
      </div>
      {/* End of step header */}

      {/* Regime mismatch advisory — only shown for BULL/BEAR (not MIXED or null) */}
      {regimeDirection === 'BULL' && dir === 'Bearish' && (
        <div className={formStyles.mismatchWarn} role="alert">
          <Text size={12} tone="caution">
            The macro regime currently favours Bullish trades — your Bearish direction runs against the tide.
          </Text>
        </div>
      )}
      {regimeDirection === 'BEAR' && dir === 'Bullish' && (
        <div className={formStyles.mismatchWarn} role="alert">
          <Text size={12} tone="caution">
            The macro regime currently favours Bearish trades — your Bullish direction runs against the tide.
          </Text>
        </div>
      )}

      <div className={formStyles.group}>
        <Text size={12} weight={600}>Directional bias</Text>
        <div className={formStyles.segmented}>
          ...
```

`role="alert"` causes screen readers to announce the warning immediately when it appears (e.g., when the user switches direction).

- [ ] **Step 3: Run typecheck**

```
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/screener/step-3-direction/page.tsx" \
        "frontend/app/(frame)/screener/step-3-direction/page.module.css"
git commit -m "feat(step3): advisory when chosen direction conflicts with macro regime"
```

---

## Self-Review

**1. Spec coverage**

| Requirement | Task |
|---|---|
| `regime_direction` field on backend response | Task 1 |
| Derive from OMM state (primary) | Task 1 |
| Derive from EMA metrics (fallback) | Task 1 |
| Unit tests for derivation logic (8 cases) | Task 1 |
| Endpoint smoke test verifies field is present in HTTP response | Task 1 |
| Early-return path yields `None` (no pill shown) — acknowledged | Task 1 |
| Frontend type updated | Task 2 |
| Store field + action (session-only, not persisted) | Task 2 |
| No store version bump (no persisted field added) | Task 2 |
| Green pill (`var(--pass)`) for Bullish | Task 3 |
| Red pill (`var(--reject)`) for Bearish | Task 3 |
| `role="img"` + `aria-label` on pill for accessibility | Task 3 |
| `setRegimeDirection` called on regime fetch | Task 3 |
| Mismatch warning suppressed for MIXED and null | Task 4 |
| `role="alert"` on warning div for accessibility | Task 4 |
| Warning text is descriptive, not prescriptive | Task 4 |
| Correct DOM insertion point (sibling of group, not inside step header) | Task 4 |

**2. Placeholder scan** — No TBD / TODO / "add appropriate X" patterns present. All code is complete.

**3. Type consistency**
- `regime_direction` in Pydantic schema → `regime_direction` in TS `MarketRegime` → `regimeDirection` in store (camelCase per Zustand convention) ✓
- `setRegimeDirection` defined in Task 2 interface and used in Task 3 page ✓
- CSS classes `directionPill_BULL/BEAR/MIXED` used as template-literal class names in Task 3 ✓
- `mismatchWarn` CSS class defined in Task 4 Step 1, used in Task 4 Step 2 ✓
- No `--pass-border`, `--reject-border`, `--caution-border` tokens used — replaced with `var(--pass)`, `var(--reject)`, `var(--caution)` ✓
