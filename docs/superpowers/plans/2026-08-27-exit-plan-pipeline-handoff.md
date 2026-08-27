# Session Handoff — Exit-Plan Pipeline, Phase 4 (Feature D)
**Date:** 2026-08-27
**Branch:** `claude/resume-previous-session-n2fg9g` (pushed to `origin`)
**HEAD:** `c9a850e`
**Plan:** `docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md`

---

## What Was Done This Session

This session resumed work interrupted by a session limit and implemented **Phase 4 / Feature D** — the
last unimplemented phase of the exit-plan pipeline plan.

> **Note on the resume.** The container was re-cloned at session start, so the interrupted session's
> *uncommitted* edits (in-progress `portfolio/page.tsx` and `alertEngine.test.ts` work) were gone.
> Everything it had committed was intact on the branch. Feature D was rebuilt from the plan, not
> recovered. Nothing was lost that had been committed.

### Feature D — Active TP method

One method per position drives that position's `TP_HIT` alert: `ladder | monte_carlo | exit_plan_2r |
exit_plan_3r`. Picked via a new segmented control in the Portfolio `EditDrawer` showing the price each
method resolves to; a method whose price can't be resolved yet renders **disabled** rather than
stamping a null snapshot the alert engine would silently ignore.

`ladder` deliberately stores **no** snapshot and keeps reading `targets[0]` live — those targets are
edited in the same drawer, so a snapshot would go stale on the next keystroke. Every other method
snapshots into `resolvedTpPrice`, refreshed only when the user re-runs its source (`runEstimate` for
Monte Carlo, `ExitPlanEditor.compute` for the 2R/3R rows, each re-stamping only when its own method is
active). A non-ladder method with no snapshot **falls back to the ladder** rather than going silent.

### Feature D — Per-position alert overrides

`alertOverrides` / `alert_overrides` resolves as `override ?? global`, absent key = inherit. Implemented
in both engines, which are documented mirrors of each other: `alertEngine.effectiveEnabled` and
`alert_generator.effective_enabled`.

Only the six **position-scoped** types are overridable. A stray key for an account-wide type
(`REGIME_CHANGE`, `SCAN_*`) is ignored so it can't defeat the user's global setting, as is a non-bool
stored value.

The backend splits the resolution across the two gates that **already existed** rather than duplicating
the global list:

| Override state | `generate_alerts` | `notify_alert` |
|---|---|---|
| explicit `false` | drops it up front — no alert row, no WS broadcast, no history entry, sustain clock cleared | never reached |
| explicit `true` | generates normally | `type_enabled=True` replaces the global `enabledTypes` check |
| absent (inherit) | generates normally | global `enabledTypes` decides, exactly as before |

`masterEnabled` is **never** bypassed — it stays the account-wide kill switch. History rows keep being
written for a type muted only *globally*, preserving the existing "why did this alert fire" audit trail.

### Toast-gating bugfix (bundled in, per the plan)

`enabledTypes` previously gated only outbound email/Telegram, so a type switched off in Settings still
popped an in-app toast. It is now threaded into `scanPortfolio` at both call sites (`portfolio/page.tsx`,
`dashboard/page.tsx` ×2). Left undefined the engine still treats every type as enabled, so a caller that
is never updated **fails open** rather than going silent.

### Bug fixed in passing

A TP price of `0` was read as a real level, making `price >= 0` true on **every tick** for a bullish
position — a permanently-firing `TP_HIT`. Two ways to reach it: the option-side Monte Carlo mapping's
`t.stockPrice ?? 0` fallback (introduced by this feature, caught on self-review before commit), and a
ladder target row carrying no usable stock price (**pre-existing**). All four layers now apply the same
"0 is never a real stock price" rule the stop handling already used via `floorStop` / `_floor_stop`.

### No migration needed

Phase 0's `bbb04a057515` already added every Feature D column (`active_tp_method`, `resolved_tp_price`,
`resolved_tp_updated_at`, `alert_overrides`), as did the ORM fields, the `TpMethod` literal, the
Pydantic schemas and the PATCH router plumbing. Phase 4 was business logic + frontend only.

---

## Current State

### Branch
`claude/resume-previous-session-n2fg9g` — 21 commits ahead of `main`, 50 files, +4043/−97. Pushed to
`origin`. **No PR opened** (none was requested).

### Test Results (verified this session, after all fixes)

| Suite | Result |
|---|---|
| `npm run typecheck` | Clean — `tsc --noEmit` exits 0 |
| `npm run test` (Jest) | **848 passed**, 82 suites, 0 failed |
| `pytest` (backend) | **1669 passed**, 1 skipped |

### Environment caveat for the next session

This is a remote container. Neither `frontend/node_modules` nor the backend Python packages ship with
the clone — both had to be installed before anything could be verified. **`npm run typecheck` silently
reports only a `tsconfig` deprecation and validates nothing when `node_modules` is absent**, so it looks
like it passed when it did not. Install first:

```bash
cd frontend && npm install
cd backend  && pip install -r requirements.txt
```

`npm install` adds one incidental `"dev": true` line to `frontend/package-lock.json`; it was reverted
here and should be reverted again rather than committed.

---

## What's Next

### Immediate — the outstanding audit obligation
The plan states, per explicit user instruction, that `K-adversarial-audit-loop` (audit-only mode) runs
at **every** ✅ checkpoint, not just at the end. Neither has been run:

- [ ] **Phase 4 checkpoint audit** — `K-adversarial-audit-loop` (audit-only) over the Feature D diff
- [ ] **Final full-diff audit** — the same loop end-to-end across all 21 commits

These were deliberately left for the user to invoke rather than fired off unasked.

### Then
- [ ] **Manual smoke test** per the plan's Verification section — switch a position's active TP method
      and confirm the alert-driving price updates; toggle one alert type off for a single position and
      confirm others are unaffected globally
- [ ] **Merge to `main`** (or open a PR if remote review is wanted)

### Known gaps (deliberate, not defects)
- `TIME_STOP` fires at `dteRemaining <= 3`, and a stock position's `dteRemaining` is `0` — so it is
  permanently true for stock legs. **Pre-existing**, out of Feature D's scope, and now individually
  mutable per position as a workaround.
- Two stock-position create paths remain snapshotless by design (the after-scan auto-execute loop and
  the `ChartWorkspace` chart-click buy) — see the Feature E section of the plan.

---

## Key Files Reference

| Layer | File | Notes |
|-------|------|-------|
| Frontend types | `frontend/types/domain.ts` | `TpMethod`, `AlertOverrides`, `PositionAlertType`, `POSITION_ALERT_TYPES` |
| Frontend engine | `frontend/lib/alertEngine.ts` | `effectiveEnabled`, resolved-TP resolution, `TP_METHOD_LABEL` |
| Frontend store | `frontend/lib/portfolioStore.ts` | `fromBackend` normalisation + `toUpdatePayload` PATCH plumbing |
| Frontend UI | `frontend/app/(frame)/portfolio/page.tsx` | `TpMethodSelector`, `AlertOverridesEditor`, `tpMethodPatch`, `alertFiresAgainst` |
| Toast gating | `frontend/app/(frame)/dashboard/page.tsx` | Two `scanPortfolio` call sites now passing `enabledTypes` |
| Backend engine | `backend/app/services/alert_generator.py` | `effective_enabled`, `_muted`, resolved-TP `TP_HIT` basis |
| Backend dispatch | `backend/app/services/notifications/alert_notifier.py` | `notify_alert(type_enabled=...)` global-gate replacement |
| Backend monitor | `backend/app/services/portfolio_alert_monitor.py` | `overrides_by_rec_id` map → per-alert dispatch decision |
| Backend router | `backend/app/routers/alerts.py` | Browser POST path honours the same override |
| Tests | `backend/tests/test_alert_overrides.py` | **New** — 16 tests, mirror of the frontend Feature D block |
| Tests | `frontend/lib/__tests__/alertEngine.test.ts` | Feature D block — gating, overrides, resolved TP, zero-price |
| Tests | `frontend/app/(frame)/portfolio/__tests__/EditDrawer.test.tsx` | Selector + override UI, `tpMethodPatch` |
