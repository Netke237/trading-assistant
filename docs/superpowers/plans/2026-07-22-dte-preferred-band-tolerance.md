# DTE Preferred-Band Tolerance Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The DTE fit score's "preferred window" (used by `_score_dte()` in `contract_validator.py`, already fixed in the prior commit on this branch to decay gradually instead of flat-25 outside the window) is derived per-scan from the holding horizon, but does **not** get the same `DTE_WINDOW_TOLERANCE_DAYS` (10-day) grace that the **hard-reject** `min_dte`/`max_dte` bounds already get at the exact same call sites. That existing tolerance exists specifically because listed option expirations are spaced ~30-35 days apart and rarely land exactly on a computed ideal boundary (e.g. 180-210 days) — the hard-reject bound already forgives a contract landing a few days short/over, but the soft score does not, so a completely normal expiration-cycle miss (e.g. DAL's 177-DTE contract vs. a 180-210d ideal window) still takes a real scoring penalty it arguably shouldn't. This plan extends the same, already-defined tolerance constant into the preferred band, at both places that currently compute it.

**Scope decision (confirmed with Kenneth):** extend the existing `DTE_WINDOW_TOLERANCE_DAYS` grace to the preferred band — do not invent a new/different tolerance value, and do not touch the in-window centre-peaked taper shape or any YAML config.

**Architecture:** Two independent router functions currently duplicate the same 4-line override-assembly logic (the surrounding comments differ in wording between the two files, but the actual override-key assignments are functionally identical) — `backend/app/routers/scan.py:483-499` (used by the scan pipeline) and `backend/app/routers/contracts.py:63-81` (used by the `/api/contracts` recompute endpoint the Trade Card/Contracts step calls). Both already widen `min_dte`/`max_dte` by `DTE_WINDOW_TOLERANCE_DAYS` (via `widened_min_dte()` and a flat `+ DTE_WINDOW_TOLERANCE_DAYS`) but leave `preferred_dte_min`/`preferred_dte_max` at the raw, unwidened `lo`/`hi`. This exact duplication is itself part of the risk being fixed: patching the widening logic inline in one file and not the other would silently reintroduce the same "wired in one place, forgotten in the other" bug class the previous plan on this branch just fixed. So rather than pasting the same 2-line change into two files, this plan extracts the shared override-assembly logic into one function in `backend/app/scoring/dte_window.py` (which both `min_dte`/`max_dte`'s existing tolerance logic already lives in, via `widened_min_dte`/`DTE_WINDOW_TOLERANCE_DAYS`) and has both routers call it. This is not new abstraction for its own sake — it collapses two already-identical, already-duplicated blocks into one, in the same module the underlying tolerance constant is already defined in.

**Tech Stack:** FastAPI + Pydantic v2, pytest (`backend/`, run via `.venv/Scripts/python.exe`). No frontend changes in this plan.

**Root cause (verified against the running code):**
- `backend/app/scoring/dte_window.py:25` defines `DTE_WINDOW_TOLERANCE_DAYS = 10`, with a docstring explicitly about monthly option cycle spacing: *"a fixed-width DTE window can straddle a real expiration by a handful of days on either side."*
- `backend/app/routers/scan.py:483-499`: `contract_overrides["min_dte"] = widened_min_dte(lo, hold_max_days)`, `contract_overrides["max_dte"] = hi + DTE_WINDOW_TOLERANCE_DAYS` — both widened. But `contract_overrides["preferred_dte_min"] = lo` and `contract_overrides["preferred_dte_max"] = hi` — both left at the raw, unwidened values. The comment at `:493-495` explicitly states this was intentional at the time ("Soft-scoring still favours the true window via preferred_dte_min/max, so contracts inside [lo, hi] keep ranking above the tolerance-band ones") — this plan revises that specific intent, per Kenneth's confirmation, not correcting an accidental bug in that one line.
- `backend/app/routers/contracts.py:63-81`: byte-for-byte the same pattern, same unwidened `preferred_dte_min`/`preferred_dte_max = dte_bounds[0], dte_bounds[1]`, same rationale in its own comment (`:74-76`).
- Concretely for Kenneth's DAL example: the Semi-annual preset (90-105 day hold — the codebase's own `test_semi_annual_preset` and `horizonPresets.ts` call this preset "Semi-annual"; it scores under the shared `Position` scoring bucket, which is why the UI and this plan both also call it "Position horizon" — same scenario, two names in use across the codebase) → `dte_window(90, 105, 2.0)` → `lo=180, hi=210`. DAL's contract is 177 DTE — 3 days short of `lo`. Today: hard bounds are `min_dte=widened_min_dte(180, 105)=170` (well below 177, so not hard-rejected — correctly forgiven) but `preferred_dte_min=180` (unwidened), so the soft scorer still treats 177 as 3 days *outside* its preferred band and applies the decay-taper penalty from the previous fix (~20/100), even though the hard-reject logic already treats 177 as a perfectly normal, forgiven contract.
- No existing test asserts the specific unwidened `preferred_dte_min == lo` behavior as a requirement — checked `backend/tests/test_horizon_dte.py` in full; the tests that exercise this code path (`test_get_contracts_applies_hold_day_dte_window`, `test_get_contracts_does_not_hard_reject_a_tolerance_fallback_expiry`, `test_get_contracts_still_rejects_a_too_short_contract_for_a_narrow_horizon`, `test_get_contracts_without_hold_days_keeps_legacy_behaviour`) only assert which contracts are *returned*, hard-reject status, or a non-zero overall `score` — none assert an exact `dte_score` value or the presence/absence of the `dte_outside_preferred` flag for a near-miss contract, so none break under this change (traced by hand immediately above; confirmed empirically in Task 1 Step 8). `backend/tests/test_scan_endpoint.py` also exercises this same floor-clamp scenario end-to-end through `scan.py` itself — `test_scan_swing_hold_rejects_a_contract_expiring_before_the_hold_ends` and `test_scan_swing_hold_accepts_a_contract_within_the_widened_window` (Swing 5-15d hold, the same lo=10/hi=30/hold_max_days=15 numbers as this plan's own floor-clamp test in Task 1 Step 2) — both assert only hard-reject/candidate-presence outcomes, not exact soft-score values, so they also survive this change (confirmed empirically in Task 1 Step 8, which runs them explicitly rather than relying on "the full suite" to incidentally cover them).

---

## Branch setup

- [ ] **Step 0: Confirm the branch state before starting**

The prior two commits on this branch (`fix(screener): vol+events gate...` and `fix(contracts): DTE fit score decays...`) have already been merged into `main` (merge commit visible in `git log`) — this is a direct continuation of that same work, now on `main` itself:

```bash
cd "F:/Git/GitHub/Trading assistant"
git log --oneline -3        # expect the merge commit for fix/vol-events-gate-and-dte-decay at or near the top
git branch --show-current   # expect: main
git status --short          # expect: only pre-existing untracked scratch files at the repo
                             # root (Feddback.docx, pre_merge_backup.dump, other plan docs,
                             # etc.) — no unrelated tracked changes
```

If `git log` does NOT show that merge commit, the local `main` is out of date — run `git pull --ff-only origin main` first (or check with Kenneth before proceeding, since something unexpected has happened to the branch history). Do not check out or continue work on the old `fix/vol-events-gate-and-dte-decay` branch name — it has already been merged and continuing on it separately from `main` risks a redundant/confusing second merge later.

---

## Task 1: Extract the shared DTE-override-assembly helper and widen the preferred band

**Files:**
- Modify: `backend/app/scoring/dte_window.py` (add new function)
- Modify: `backend/app/routers/scan.py` (lines 483-499)
- Modify: `backend/app/routers/contracts.py` (lines 63-81)
- Test (new): `backend/tests/test_dte_window.py` — check whether this file already exists first; if it does, add to it instead of creating a duplicate

- [ ] **Step 1: `backend/tests/test_dte_window.py` already exists — add to it**

Confirmed: this file already exists (16 tests covering `dte_window`/`resolve_dte_bounds`). Its established convention is a single top-level `from app.scoring.dte_window import dte_window` import, with every other function (`resolve_dte_bounds`, etc.) imported inline inside each test that needs it, rather than added to the top-level import line. Match that convention for the new tests below — do not edit the existing top-level import line.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_dte_window.py`:

```python
def test_widen_contract_overrides_widens_both_hard_and_preferred_bounds_identically():
    """Position horizon: 90-105 day hold -> dte_window gives lo=180, hi=210.
    Both min_dte/max_dte (hard) and preferred_dte_min/max (soft score) must get
    the identical +/-10 day tolerance -- this is the core of the fix."""
    from app.scoring.dte_window import widen_contract_overrides_for_dte
    overrides = widen_contract_overrides_for_dte({}, lo=180, hi=210, hold_max_days=105)
    assert overrides["min_dte"] == overrides["preferred_dte_min"] == 170
    assert overrides["max_dte"] == overrides["preferred_dte_max"] == 220


def test_widen_contract_overrides_applies_the_same_narrow_horizon_floor_clamp():
    """Swing-like narrow horizon: lo=10, hold_max_days=15. widened_min_dte's
    floor clamp (hold_max_days+1=16) must apply to preferred_dte_min the exact
    same way it already applies to min_dte -- a contract can't be scored as
    'ideal' at a DTE that would expire before the hold is even over."""
    from app.scoring.dte_window import widen_contract_overrides_for_dte
    overrides = widen_contract_overrides_for_dte({}, lo=10, hi=30, hold_max_days=15)
    assert overrides["min_dte"] == overrides["preferred_dte_min"] == 16
    assert overrides["max_dte"] == overrides["preferred_dte_max"] == 40


def test_widen_contract_overrides_preserves_unrelated_keys():
    """Must merge into (not replace) whatever overrides dict is already in
    progress -- e.g. an unrelated max_price key from a prior step."""
    from app.scoring.dte_window import widen_contract_overrides_for_dte
    overrides = widen_contract_overrides_for_dte({"max_price": 50.0}, lo=180, hi=210, hold_max_days=105)
    assert overrides["max_price"] == 50.0
    assert overrides["min_dte"] == 170


def test_widen_contract_overrides_matches_the_existing_widened_min_dte_helper():
    """Direct equivalence check against the already-tested widened_min_dte() /
    DTE_WINDOW_TOLERANCE_DAYS building blocks, so this test fails if the new
    helper's arithmetic ever drifts from the primitives it's built on."""
    from app.scoring.dte_window import widen_contract_overrides_for_dte, widened_min_dte, DTE_WINDOW_TOLERANCE_DAYS
    overrides = widen_contract_overrides_for_dte({}, lo=180, hi=210, hold_max_days=105)
    assert overrides["min_dte"] == widened_min_dte(180, 105)
    assert overrides["max_dte"] == 210 + DTE_WINDOW_TOLERANCE_DAYS
```

Also add to `backend/tests/test_contract_validator.py` (append, reusing the `_contract_with_expiry` helper added in the previous commit on this branch):

```python
def test_dal_style_near_miss_scores_in_window_once_preferred_band_is_widened():
    """Reproduces Kenneth's reported DAL case directly: Position horizon
    (90-105d hold -> ideal window 180-210), contract at 177 DTE (3 days short
    of the ideal floor). Once preferred_dte_min/max are widened by the same
    10-day tolerance as the hard-reject bounds, 177 falls INSIDE the widened
    170-220 preferred band (in-window taper), not in the out-of-window decay
    branch -- so it must no longer carry the dte_outside_preferred flag."""
    from app.scoring.dte_window import widen_contract_overrides_for_dte

    overrides = widen_contract_overrides_for_dte({}, lo=180, hi=210, hold_max_days=105)
    card = validate_contract(_contract_with_expiry(177), stock_score=70, overrides=overrides)
    assert "dte_outside_preferred" not in card.soft_flags
    # centre=(170+220)/2=195, half_range=25 -> 100*(1-|177-195|/25) = 100*(1-18/25) = 28
    assert card.breakdown.dte_score == 28
```

- [ ] **Step 3: Run the tests to verify they fail as expected**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_dte_window.py tests/test_contract_validator.py -v`

Expected: all five new tests fail — the four in `test_dte_window.py` plus `test_dal_style_near_miss_scores_in_window_once_preferred_band_is_widened` in `test_contract_validator.py` — with the same `ImportError`/`AttributeError` (`widen_contract_overrides_for_dte` doesn't exist until Step 4 adds it, and every one of these five tests imports it). Once Step 4 adds the function, `test_dal_style_near_miss_scores_in_window_once_preferred_band_is_widened` would additionally have failed on its assertion even with the import resolved (current code still flags `dte_outside_preferred` and scores ~20, not 28) — but at this checkpoint, before Step 4, all five should show the identical import-error failure mode. Confirm that before proceeding.

- [ ] **Step 4: Add the shared helper**

In `backend/app/scoring/dte_window.py`, add this function after `widened_min_dte` (i.e., after the current end of that function, before `dte_window`):

```python
def widen_contract_overrides_for_dte(
    overrides: dict, lo: int, hi: int, hold_max_days: int | None,
) -> dict:
    """Merge DTE hard-reject and soft-score preferred-band overrides into
    `overrides` (mutated in place and returned), both widened by the same
    DTE_WINDOW_TOLERANCE_DAYS.

    Both bounds get IDENTICAL widened values: min_dte/max_dte (hard-reject)
    already forgive a contract landing a few days short/over the ideal [lo, hi]
    window, because listed option expirations rarely land exactly on it (see
    DTE_WINDOW_TOLERANCE_DAYS's docstring). Previously preferred_dte_min/max
    (which drive the soft DTE-fit SCORE, not the hard reject/accept decision)
    stayed at the raw lo/hi, so a contract already forgiven by the hard-reject
    check (e.g. 177 DTE against a 180-210 window) still took a real scoring
    penalty for being "outside" a boundary the hard-reject logic had already
    decided was close enough. Widening both identically removes that
    inconsistency — a contract that isn't hard-rejected for being close to the
    window is no longer penalized as if it were far outside it either.

    Single source of truth for both callers of this logic (scan.py's scan
    pipeline and contracts.py's /api/contracts recompute endpoint) — kept here
    specifically so the two don't drift out of sync the way they already had
    (identical duplicated blocks, only one of which would get patched by a
    caller applying this fix inline instead of through one shared function).
    """
    widened_min = widened_min_dte(lo, hold_max_days)
    widened_max = hi + DTE_WINDOW_TOLERANCE_DAYS
    overrides["min_dte"] = widened_min
    overrides["max_dte"] = widened_max
    overrides["preferred_dte_min"] = widened_min
    overrides["preferred_dte_max"] = widened_max
    return overrides
```

- [ ] **Step 5: Wire `scan.py` to use the shared helper**

In `backend/app/routers/scan.py`, find (currently lines 483-499):

```python
    contract_overrides = dict(overrides or {})
    if dte_bounds is not None:
        lo, hi = dte_bounds
        # Hard-reject bounds are widened by the same tolerance the chain fetch
        # uses (_nearest_expiration_in_window) — otherwise a contract the fetch
        # accepted as "close enough" (e.g. 179d for a 180-210d window) would be
        # hard-rejected here as dte_too_short. widened_min_dte floors the widened
        # min at hold_max_days+1 so short horizons (Swing, Position) can't accept
        # a contract that expires before the intended hold is even over — a flat
        # tolerance is safe for wide windows (Semi-annual/Annual) but would gut
        # that safety margin for narrow ones. Soft-scoring still favours the true
        # window via preferred_dte_min/max, so contracts inside [lo, hi] keep
        # ranking above the tolerance-band ones.
        contract_overrides["min_dte"] = widened_min_dte(lo, hold_max_days)
        contract_overrides["max_dte"] = hi + DTE_WINDOW_TOLERANCE_DAYS
        contract_overrides["preferred_dte_min"] = lo
        contract_overrides["preferred_dte_max"] = hi
```

Replace with:

```python
    contract_overrides = dict(overrides or {})
    if dte_bounds is not None:
        lo, hi = dte_bounds
        # Hard-reject AND soft-score preferred-band bounds are both widened by
        # the same DTE_WINDOW_TOLERANCE_DAYS -- see widen_contract_overrides_for_dte's
        # docstring for why the two must move together, not just the hard bound.
        contract_overrides = widen_contract_overrides_for_dte(contract_overrides, lo, hi, hold_max_days)
```

Add `widen_contract_overrides_for_dte` to the existing import from `app.scoring.dte_window` at the top of the file (find the existing `from app.scoring.dte_window import resolve_dte_bounds, DTE_WINDOW_TOLERANCE_DAYS, widened_min_dte` line, currently `:58`, and add the new name to it). Before making the edit, grep the file for other uses of `DTE_WINDOW_TOLERANCE_DAYS` and `widened_min_dte` as actual calls/references (e.g. `widened_min_dte(`, not just the bare word) — the new comment text this step introduces mentions `DTE_WINDOW_TOLERANCE_DAYS` by name in prose, so a grep for the bare name run *after* the edit will false-positive on that comment. If either had no other real use site, drop it from the import; if either is still used elsewhere, leave it.

- [ ] **Step 6: Wire `contracts.py` to use the shared helper**

In `backend/app/routers/contracts.py`, find (currently lines 63-81):

```python
        dte_bounds = resolve_dte_bounds(
            hold_min_days, hold_max_days, dte_holding_multiplier,
            log_context="GET /api/contracts",
        )
        if dte_bounds is not None:
            # Hard-reject bounds are widened by the same tolerance the chain
            # fetch uses (fetch_option_chain's _nearest_expiration_in_window) —
            # otherwise a contract the fetch accepted as "close enough" (e.g.
            # 179d for a 180-210d window) gets hard-rejected here as
            # dte_too_short. widened_min_dte floors the widened min at
            # hold_max_days+1 so short horizons can't accept a contract that
            # expires before the intended hold is even over. preferred_dte_min/max
            # stay at the true window so scoring still favours contracts closer
            # to the intended hold.
            contract_overrides = {
                "min_dte": widened_min_dte(dte_bounds[0], hold_max_days),
                "max_dte": dte_bounds[1] + DTE_WINDOW_TOLERANCE_DAYS,
                "preferred_dte_min": dte_bounds[0], "preferred_dte_max": dte_bounds[1],
            }
```

Replace with:

```python
        dte_bounds = resolve_dte_bounds(
            hold_min_days, hold_max_days, dte_holding_multiplier,
            log_context="GET /api/contracts",
        )
        if dte_bounds is not None:
            # Hard-reject AND soft-score preferred-band bounds are both widened
            # by the same DTE_WINDOW_TOLERANCE_DAYS -- see
            # widen_contract_overrides_for_dte's docstring for why the two must
            # move together, not just the hard bound.
            contract_overrides = widen_contract_overrides_for_dte({}, dte_bounds[0], dte_bounds[1], hold_max_days)
```

Add `widen_contract_overrides_for_dte` to the existing import at the top of the file (currently `:14`, `from app.scoring.dte_window import resolve_dte_bounds, DTE_WINDOW_TOLERANCE_DAYS, widened_min_dte`). Same check as Step 5, and same caveat: grep for actual calls (`widened_min_dte(`), not the bare name, before deciding whether to drop either from the import, since this step's own new comment also mentions `DTE_WINDOW_TOLERANCE_DAYS` in prose.

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_dte_window.py tests/test_contract_validator.py -v`
Expected: all pass, including `test_dal_style_near_miss_scores_in_window_once_preferred_band_is_widened`.

- [ ] **Step 8: Run the full horizon/DTE and contracts regression suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_horizon_dte.py tests/test_contract_validator.py tests/test_dte_window.py tests/test_scan_endpoint.py -v`
Expected: all pass. Pay particular attention to `test_get_contracts_applies_hold_day_dte_window`, `test_get_contracts_does_not_hard_reject_a_tolerance_fallback_expiry`, `test_get_contracts_still_rejects_a_too_short_contract_for_a_narrow_horizon`, and `test_scan_endpoint.py`'s `test_scan_swing_hold_rejects_a_contract_expiring_before_the_hold_ends`/`test_scan_swing_hold_accepts_a_contract_within_the_widened_window` — all traced by hand in the root-cause section above as unaffected, but confirm empirically.

- [ ] **Step 9: Full backend suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q`
Expected: no new failures versus the baseline already established on this branch (1141 passed, 1 skipped, 1 xpassed after the prior two commits). Note: `tests/test_governor.py::test_circuit_closes_after_cooldown` is a pre-existing flaky/timing-sensitive test that occasionally fails under the full suite but passes in isolation — unrelated to DTE scoring. If it's the *only* failure, re-run it in isolation (`pytest tests/test_governor.py::test_circuit_closes_after_cooldown -v`) before treating it as a regression from this change.

- [ ] **Step 10: Commit**

```bash
git add backend/app/scoring/dte_window.py backend/app/routers/scan.py backend/app/routers/contracts.py backend/tests/test_dte_window.py backend/tests/test_contract_validator.py
git commit -m "fix(contracts): DTE preferred-band score gets the same tolerance as the hard-reject bound

min_dte/max_dte (hard-reject) already forgive a contract landing a few
days short/over the ideal DTE window, since listed option expirations
rarely land exactly on a computed boundary. preferred_dte_min/max (the
soft DTE-fit score) did not get that same DTE_WINDOW_TOLERANCE_DAYS
grace, so a contract the hard-reject check already accepted as close
enough (e.g. 177 DTE against a 180-210d Position window) still took a
real scoring penalty for being 'outside' the unwidened band. Extracts
the previously-duplicated override-assembly block (identical in
scan.py and contracts.py) into one shared helper so both stay in sync."
```

---

## Task 2: Full verification pass

- [ ] **Step 1: Full backend suite via the project's venv**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q`
Expected: no new failures. Note: `tests/test_governor.py::test_circuit_closes_after_cooldown` is a pre-existing flaky/timing-sensitive test that occasionally fails under the full suite but passes in isolation — unrelated to DTE scoring (same caveat as Task 1 Step 9). If it's the *only* failure, re-run it in isolation (`pytest tests/test_governor.py::test_circuit_closes_after_cooldown -v`) before treating it as a regression from this change.

- [ ] **Step 2: Frontend typecheck + test suite (no frontend files touched, but confirm nothing else on the branch regressed)**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: clean, matching the state already verified after the previous commit on this branch.

- [ ] **Step 3: Report** the verification output, and restate the concrete before/after for Kenneth's DAL example (177 DTE, Position horizon): `dte_outside_preferred` flag no longer set, `dte_score` 20 → 28.

---

## Notes / deliberate non-goals

- **Not changing `DTE_WINDOW_TOLERANCE_DAYS`'s value (10 days).** Reusing the existing constant as-is, per Kenneth's confirmation — this plan extends *where* it's applied, not what it's set to.
- **Not touching the in-window centre-peaked-to-zero-at-edges taper shape**, or the out-of-window linear-decay formula added in the previous commit on this branch. Both are unchanged; only the `lo`/`hi` values fed into `_score_dte()` via `preferred_dte_min`/`preferred_dte_max` are now widened before they reach it.
- **Not touching the flat, no-override default (`contract_rules.yaml`'s static `preferred_dte_min: 21`/`preferred_dte_max: 60`, used only when no horizon/hold-days override is supplied at all).** That path never had a tolerance concept to extend — it's a separate, non-horizon-derived fallback and out of scope here.
