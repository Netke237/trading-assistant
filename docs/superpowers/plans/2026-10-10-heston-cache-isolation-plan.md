# HESTON-CACHE-ISOLATION — Board #166

## Goal and evidence

Each public calibration call owns its returned `CalibrationResult` and nested `HestonParams`. A caller may mutate either without changing a later calibration or a result already handed to another caller. Preserve numeric calibration, labels, cache keys, cache capacity and mutable dataclass API.

Source: Board #166 and ticket-22 reconciliation. Checked F1/F2 calibration spec, current cache callers and prior audit records. Production calls `calibrate_heston` from scan.py, which retains `.params` and uses `.method == "heston_grid"` to select the pricing path. The private `_run_calibration` is also called directly by tests and probe scripts, but production accesses it only through `calibrate_cached`.

Reproduction on main 13c8b52c with Python 3.11.16: ten strikes 180..225, spot 201.86, r .05, 45 days, BS mids rounded to cents with sigma = .345 + .45*(-log(K/S)) + 1.6*log(K/S)^2. Two `calibrate_heston` calls return the same result and params. Mutating the first result's v0 to .81 changes the second result's 210C price from 6.512151104274864 to 21.78421364529183; the next cache hit retains v0=.81. No production consumer currently writes these fields; this closes the shared ownership hazard requested by the item.

## Task 1 — detach the public return from the private cached value

Files: `backend/app/models/heston_cache.py`, new `backend/tests/test_heston_cache_isolation.py`.

1. Write regression tests first and run them on unchanged code. Use the real calibrator with the ten-strike skew chain above; clear `_run_calibration` cache before and after each test. Assert heston_grid and unmodified params/rmse/method equality on repeated calls. Capture an unmodified real `heston_price` value before mutation. Change every params field plus rmse and method on one returned result; the already-returned second result and a later result must retain the original values and price. Assert result and nested params identities differ. Both `calibrate_cached` and its public `calibrate_heston` wrapper must be exercised. The expected red is shared identity or changed values, not a numerical fit failure.
2. Return a new `CalibrationResult` with a new `HestonParams` at the `calibrate_cached` cache-return boundary, using `dataclasses.replace` for both levels. No freezing, no recalibration, no key/grid/baseline changes. Thin-chain fallback already creates fresh result and params; keep it unchanged.
3. Include thin-chain fallback independence, real bs_flat independence, and a cache hit/miss assertion showing copy-on-return retains caching (one miss then hits). For bs_flat use three or more BS-priced strikes with constant volatility; do not force the method via a stub. Verify cached numeric values remain equal, not only identities. Keep expensive calibrations bounded and tests independent of order.
4. Run targeted isolation and all existing Heston tests. Run frontend typecheck + full Jest suite and full backend suite under Python 3.11. Record any baseline failures without unrelated changes.
5. Commit `fix(heston): isolate cached calibration results` with `Co-authored-by: Codex <noreply@openai.com>`.

## Acceptance and audit

Plan: fresh independent gate auditor against this document and real source; cap three rounds. Only after clean plan review create Task 1 as native sub-issue of #166, then fresh implementer. Ownership renewal and `(you)` check precede every helper, push and GitHub write.

Before code round 1 fetch/merge origin/main, resolve any conflicts and rerun checks. Code audit covers the full integrated origin/main..HEAD diff; later rounds review fixes/interactions only; cap three code rounds. Gate: wrong user/broker number or corrupted persisted data, mechanism comments only; no other findings reported. Cache key precision, calibration fit quality, async scheduling and broader pricing audits are outside this isolated ownership change.

Coordinator records audits and evidence in PROJECT_STATE.json and item comments, pushes, opens PR with `Closes #166`, sets waiting-merge, notifies Board #151 and board_notify.py, then releases claim. Never merge. Private `_run_calibration` remains cache-owned; callers that bypass the public API must treat its value as read-only.
