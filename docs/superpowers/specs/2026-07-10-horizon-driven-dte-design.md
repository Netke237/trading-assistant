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

## Addendum — findings from adversarial review (2026-07-10)

A BMAD adversarial audit of the first plan draft surfaced defects severe enough to change the architecture. Recorded here rather than silently folded into the plan, per the project's documentation norms.

### D6 — `ScanContext.horizon` is kept, not removed

The first plan draft deleted the string `horizon` field from `ScanContext` in favour of the structured `{ horizonPreset, holdMin, holdMax }`. Audit found **19 read sites** across TopBar, dashboard, settings, ScanLog, and — critically — stock-mode files (`lib/stockScan.ts`, `step-5-strategy/page.tsx`, `step-4-prebreakout/page.tsx`) that the "options-only, stock-mode untouched" scope explicitly promised not to touch.

Worse: Step 1–3 are shared between the Options and Stocks screener paths (see CLAUDE.md). If a user picks a new preset (Quarterly/Semi-annual/Annual) while in Stocks mode, `stockScan.ts` sends it as a raw `Horizon` value to a backend endpoint whose schema only accepts `'Intraday' | 'Swing' | 'Position'` — a guaranteed 422.

**Fix:** `ScanContext` keeps `horizon: string`, now *derived* rather than hand-typed:

```
horizon = `${scoringHorizon} (${holdMin}–${holdMax}d)`
```

`scoringHorizon` is always one of the three words every existing consumer already knows how to parse (`'Intraday' | 'Swing' | 'Position'`) — for the four Position-scored presets (Position/Quarterly/Semi-annual/Annual) this word is always `"Position"`. This is a deliberate, accepted trade-off: a handful of purely cosmetic breadcrumb strings (TopBar, dashboard summary, `ScanLog` header) will read "Position (90–105d)" rather than "Semi-annual (90–105d)" when a new preset is active. The structured fields drive Step 3's own UI, where the real preset name is shown. No stock-mode file changes.

### D7 — the soft-rank preferred-DTE band must move with the hard band

`contract_validator.py`'s `_score_dte()` reads a **separate**, still-fixed `soft_rank.preferred_dte_min/max` (21–60) that D3/D4's hard `min_dte`/`max_dte` override does not touch. Any contract outside 21–60 scores a flat 25 and gets a `dte_outside_preferred` soft flag. With `max_soft_fail_count: 3`, three soft flags becomes a hard reject.

Left unfixed, every Intraday (1–4 DTE) and every long-dated (90–400 DTE) contract — i.e. the entire feature this plan exists to ship — would be systematically penalised and risk rejection via soft-fail accumulation, while only Position (30–90) would score cleanly by coincidence.

**Fix:** `validate_contract()` gains `preferred_dte_min`/`preferred_dte_max` override keys, alongside the existing `min_dte`/`max_dte`. The caller sets both pairs to the same `(min_dte, max_dte)` derived from the holding window — the soft "sweet spot" becomes the same window as the hard gate, centred scoring intact.

### D8 — the option-chain fetch layer must also respect the window (this is the real root cause)

This is the most consequential finding. `backend/app/data/market.py` — both `fetch_option_chain()` (sync) and `fetch_option_chain_async()` (async, the one `scan.py` actually calls) — does not fetch a *range* of expiries at all. It fetches the list of available expiration dates from Tradier, then picks exactly **one**: the first date that is `>= 21 days` out, hardcoded. Every scan, for every horizon, today, fetches that single nearest-to-21-days expiration and nothing else.

This is the precise mechanism behind the reported bug: 31.07.2026 is simply the nearest available expiration ≥ 21 days from 2026-07-09, not a coincidence of the `21–90` config band. It also means the `min_dte`/`max_dte` override on `validate_contract()` (D3/D4's original fix) is necessary but **not sufficient** — it can only filter contracts within whatever single expiration was already fetched. For any preset whose window doesn't happen to contain "nearest ≥21 days" (Intraday, Quarterly, Semi-annual, Annual — four of the seven presets), the fetch layer hands `validate_contract()` a chain that is *guaranteed* to fail the DTE gate, and the scan returns zero candidates for every symbol.

**Fix:** thread the derived `(min_dte, max_dte)` window into `fetch_option_chain_async()` (and `fetch_option_chain()` for parity) as an optional `dte_bounds` parameter. When present, select the expiration from the available dates closest to the *centre* of the window, filtered to dates that actually fall within it; fall back to `None` (empty chain) if nothing qualifies. When absent (existing callers that predate this feature), behaviour is unchanged — the old `>= 21 days` default is preserved. `_build_spreads()` (bearish spread construction, `scan.py:182-220`), which independently calls `fetch_option_chain_async()` for puts/calls, must receive the same `dte_bounds` so its re-fetched chain lands on the same expiration as the primary contract.

### D9 — hold-day input must be validated, not left to crash

`dte_window()` raises `ValueError` on `hold_max < hold_min` or negative input. Nothing upstream prevented an invalid pair from reaching it: the frontend's `handleMinChange` (Step 3 Custom range) did not clamp against the current max, so typing a min above the max produced an inverted pair, and `ScanRequest` had no ordering constraint — the result would have been an unhandled 500.

**Fix:** `ScanRequest` gets a Pydantic v2 `model_validator` enforcing `0 <= hold_min_days <= hold_max_days` when both are present, returning a clean validation error instead of a 500. `handleMinChange` on the frontend clamps its value to never exceed the current max (mirroring the existing `handleMaxChange` clamp against the min).

### Correction to "override isolation" framing

The original spec (and the first plan draft) claimed `min_dte`/`max_dte` overrides "must not leak into `score_stock()`" as a correctness requirement. This was checked against `stock_scorer.py`'s override handling: it is a strict allow-list `elif` chain with no `min_dte`/`max_dte` branch, so those keys are already silently ignored there today and always have been. Keeping the derived DTE keys in a separate `contract_overrides` dict (not merged into the shared `overrides` used by `score_stock()`) remains good practice for clarity, but it is defensive hygiene, not a bug fix — no observable defect results either way.
