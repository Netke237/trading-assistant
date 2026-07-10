# Horizon-Driven DTE — Design

Date: 2026-07-10
Status: Approved
Branch: `wip/screener-refinements`

## Problem

The holding horizon has no effect on which option expiries the screener surfaces.

Three different DTE numbers exist today, none of which is the user's input:

| DTE window | Value | Source |
|---|---|---|
| What the user types (Custom) | e.g. 60–185 | Discarded, never sent to backend |
| What the scan log displays | 14–90 | Frontend cosmetic default, display only |
| What the backend enforces | 21–90 | `contract_rules.yaml`, fixed, horizon-agnostic |

Root causes:

1. `frontend/components/organisms/RunScanButton/index.tsx:106-109` collapses `Custom` to a preset name by regex-parsing a display string (`"Custom (60–185d)"`), then discards the day numbers. Only the word `"Position"` reaches the backend.
2. `backend/app/scoring/contract_validator.py` reads a single fixed `hard_reject.min_dte/max_dte` block. `validate_contract()` takes no `horizon` argument, so horizon cannot influence the expiry window.
3. `frontend/app/(frame)/screener/step-3-direction/page.tsx:841-842,1063-1064` renders the log's DTE readout from a static frontend preset default, disconnected from both the user's input and the enforced window.

Consequence: a scan requested with a 60–185 day holding horizon returned contracts expiring in ~22 days (31.07.2026), because 22 falls inside the fixed 21–90 window.

Horizon **is** honoured everywhere else. `scoring_rules.yaml` carries full per-horizon parameter sets (`horizons.swing` / `.intraday` / `.position`), plus per-horizon `regime:` and `confidence_backtest:` blocks. `score_stock()` loads `horizons[horizon]`. Only the option DTE window ignores it.

## Decisions

Recorded from the design conversation:

- **D1.** New long-dated presets reuse the existing **Position** stock-scoring parameter set. They differ only in the DTE window. (No new `scoring_rules.yaml` horizon blocks.)
- **D2.** Three separate preset buttons, not one preset with a sub-range.
- **D3.** **Model B** — the button expresses a *holding period*; DTE is derived as `holding × multiplier`. The button is not a DTE window.
- **D4.** Custom is also a holding period, doubled into DTE. Typing 60–185 yields expiries 120–370 days out.
- **D5.** Intraday uses a bottom clamp (`max(1, …)`) rather than a special case or a redefined band.

## Core model

One rule. Seven buttons. One code path. A single bottom clamp that only ever engages for Intraday.

```
min_dte = max(1, round(hold_min × k))
max_dte = round(hold_max × k)
k = 2.0        # contract_rules.yaml: dte_holding_multiplier
```

Every preset — Custom included — is the same struct:

```
preset = { key, label, hold_min, hold_max, scoring_horizon }
```

| Preset | Hold (input) | → DTE (derived) | Scoring horizon |
|---|---|---|---|
| Intraday | 0–2 | 1–4 | Intraday |
| Swing | 5–15 | 10–30 | Swing |
| Position | 15–45 | 30–90 | Position |
| Quarterly *(new)* | 45–60 | 90–120 | Position |
| Semi-annual *(new)* | 90–105 | 180–210 | Position |
| Annual *(new)* | 165–200 | 330–400 | Position |
| Custom | typed | 2× typed | derived from `hold_max` |

Custom's scoring horizon is derived from `hold_max` using the existing thresholds:
`hold_max <= 4 → Intraday`, `hold_max <= 20 → Swing`, else `Position`.

Rationale for the multiplier: an option should never be held to expiry, because theta decay accelerates in the final weeks. DTE must exceed the intended hold so the position can be exited with time value remaining. `k = 2.0` reproduces the existing Position band (15–45 hold → 30–90 DTE) exactly.

## Architecture

### DTE is computed on the backend

The backend is the single source of truth. If the frontend computed the window and sent it, the scan log would only echo what the frontend *guessed*, not what was *enforced* — which is precisely the class of bug being fixed.

Data flow:

1. Frontend sends `hold_min_days`, `hold_max_days`, and `horizon` (the scoring horizon).
2. Backend computes the DTE window via a pure function.
3. Backend enforces it by passing `min_dte`/`max_dte` into `validate_contract()`.
4. Backend returns the computed window in the scan response.
5. Frontend renders the returned window in the scan log.

### New unit: `backend/app/scoring/dte_window.py`

Pure function, no I/O, independently testable.

```python
def dte_window(hold_min: int, hold_max: int, multiplier: float) -> tuple[int, int]:
    """Derive the (min_dte, max_dte) contract window from a holding period."""
```

Contract:
- Returns `(max(1, round(hold_min * multiplier)), round(hold_max * multiplier))`.
- If the resulting `max_dte < min_dte`, clamp `max_dte = min_dte`.
- Raises `ValueError` on negative input or `multiplier <= 0`.

Depends on nothing. Consumers: `scan.py` only.

### Override isolation

`scan.py` currently passes one `overrides` dict to both `score_stock()` and `validate_contract()`. The derived `min_dte`/`max_dte` must **not** leak into `score_stock()`.

Therefore the DTE keys are merged into a separate dict at the `validate_contract()` call site:

```python
contract_overrides = {**overrides, "min_dte": lo, "max_dte": hi}
scored = [(validate_contract(c, card.score, overrides=contract_overrides), c) for c in augmented]
```

`validate_contract()` already supports `min_dte`/`max_dte` overrides (`contract_validator.py:217-218`). The enforcement path exists and is tested; this change only feeds it correctly.

## Changes

### Backend

| File | Change |
|---|---|
| `backend/config/contract_rules.yaml` | Add `dte_holding_multiplier: 2.0`. `hard_reject.min_dte/max_dte` (21/90) demote to fallback, used only when hold days are absent. |
| `backend/app/scoring/dte_window.py` | **New.** Pure `dte_window()` function. |
| `backend/app/schemas/__init__.py` | `ScanRequest` gains `hold_min_days: Optional[int]`, `hold_max_days: Optional[int]`. New `DteWindow` model. `ScanResult` gains `dte_window: Optional[DteWindow]`. |
| `backend/app/routers/scan.py` | Compute the window once per scan; pass into `validate_contract()` via a merged dict; attach to `ScanResult`. |

`Horizon` remains the existing 3-value Literal. The new presets map to `Position`, so no enum change.

### Frontend

| File | Change |
|---|---|
| `frontend/app/(frame)/screener/step-3-direction/page.tsx` | `HORIZON_PRESETS` → 7 entries with `holdMin`/`holdMax`/`scoringHorizon`. New preset param defaults spread the Position block (D1) rather than duplicating it. Remove `min_dte`/`max_dte` from editable params. |
| `frontend/components/organisms/RunScanButton/index.tsx` | Send `hold_min_days`/`hold_max_days`. Stop sending `min_dte`/`max_dte` overrides. Delete the display-string regex parsing. |
| `frontend/lib/api.ts` | `postScan` signature accepts hold days. |
| `frontend/lib/scanStore.ts` | Replace the stringly-typed `context.horizon` with structured `{ preset, holdMin, holdMax }`. Persist `version` bump + `migrate()` branch. |
| `frontend/types/domain.ts` | `DteWindow` type on the scan result. |

**Unwiring the DTE parameters.** In Execution Parameters → OPTIONS → Contract, `Min DTE` and `Max DTE` become read-only derived rows (`type: 'display'`) showing the computed window. They can no longer contradict the selected horizon.

**Structural fix.** The horizon currently round-trips as the display string `"Custom (60–185d)"`, which `RunScanButton` regex-parses. That string parsing *is* the root cause of the original bug. It is replaced with structured state in `scanStore`. This is in-scope because it is the defect being fixed, not adjacent refactoring.

### Scan log

Renders `scanResult.dte_window` — the window the backend actually enforced. Shows `—` before the first scan, never a static default.

## Testing

**Backend**
- `dte_window()` unit tests: the Intraday clamp (`0 → 1`), rounding, inverted input (`max < min`), invalid input raises, and each of the 7 preset bands.
- Integration: a scan with hold 15–45 **rejects** a 22-DTE contract (the reported 31.07.2026 case) and **accepts** a 60-DTE one.
- `ScanResult.dte_window` is populated in the response.
- Regression: `min_dte`/`max_dte` do not appear in the dict passed to `score_stock()`.
- Existing `tests/test_overrides.py` must stay green — the override path is unchanged, only its caller.

**Frontend**
- `RunScanButton` sends `hold_min_days`/`hold_max_days` and omits `min_dte`/`max_dte`.
- Each of the 7 presets maps to the expected hold band and scoring horizon.
- The scan log renders the returned `dte_window`, and `—` before the first scan.
- `scanStore` migration: a persisted v-old string horizon upgrades to the structured shape without data loss.
- `npm run typecheck` clean.

## Behaviour changes accepted

| | Before | After |
|---|---|---|
| Intraday | 1–7 DTE | **1–4** |
| Swing | 14–45 DTE | **10–30** |
| Position | 30–90 nominal (21–90 enforced) | 30–90, enforced |
| Custom | silently ignored | **honoured** |
| Backend 21–90 | always enforced | fallback only |

Swing and Intraday genuinely change. Existing Swing scans will surface shorter-dated contracts than before. This is the harmonisation that was requested: one rule across all presets, at the cost of two presets moving.

## Out of scope

- Per-horizon parameter sets for the three new presets (D1 defers this).
- Tuning the multiplier per preset. `k` is one global constant.
- Any change to stock-mode (`screenerMode === 'stocks'`) — DTE is options-only.
