# 18 options-mode search profiles

3 horizon groups (`Intraday`, `Swing`, `PositionPlus`) x 3 tiers (`Baseline`,
`Restrictive`, `Loose`) x 2 directions (`Bullish`, `Bearish`), named
`<Group>_<Tier>_<Direction>`. Universe: SP500 for all 18. Full rationale and
the finalized tier numbers are in `docs/superpowers/scratchpad` history for
branch `claude/options-scan-liquidity-profiles` (merged to `main` at
`ab705ea7`) — this folder holds the *output*, not the design discussion.

## Files

- `Bamendjou_Options_Search_Profiles.xlsx` — human-readable table of all 18
  profiles and their filter values (hard-reject + soft-rank/preferred), with
  a Legend & Notes tab.
- `search-profiles-export.json` — the raw `bamendjou:search-profiles`
  localStorage payload, byte-for-byte what a real save produced.
- `import-search-profiles.js` — the same JSON embedded in a paste-into-
  DevTools-console script (see below).

## Why this isn't just "available" to another user automatically

`searchProfilesStore` (`frontend/lib/searchProfilesStore.ts`) is **client-side
localStorage only** — no backend sync, no in-app import/export UI (see
CLAUDE.md's Zustand stores table). Committing these files to the repo makes
the *data* reachable by anyone with repo access, but it does **not** put the
profiles into anyone's running app by itself — each browser has its own,
separate `localStorage`. To actually load them into a browser:

1. Open the Bamendjou app in that browser.
2. Open DevTools → Console.
3. Paste the full contents of `import-search-profiles.js`, press Enter.
4. Reload the page. The 18 profiles now appear in the Search Profile
   dropdown on Step 3 (Options mode).

This **replaces** whatever that browser already had under the
`bamendjou:search-profiles` key — back up first with
`copy(localStorage.getItem("bamendjou:search-profiles"))` if it isn't empty.

## Is reuse guaranteed?

Not unconditionally. Two concrete dependencies:

1. **Requires `main` at or after commit `ab705ea7`.** The `Restrictive`/
   `Loose` tiers rely on `preferred_volume_min`/`preferred_oi_min`/
   `preferred_spread_pct_max` being overridable in
   `backend/app/scoring/contract_validator.py` — support that did not exist
   before this work (commits `9952a890`, `b6ccc320`, `ab705ea7`, all on
   `main`). Against an older backend, the extra `preferred_*` keys in a
   profile's `scanOverrides` are silently ignored (unrecognized keys aren't
   applied), so `Loose` profiles would keep their widened hard-reject floor
   but lose the matching soft-rank widening — contracts could still fall to
   `too_many_soft_failures` that the intended "Loose" behavior was meant to
   let through.
2. **`Restrictive`/`Loose` freeze specific numbers, `Baseline` doesn't.**
   `Baseline` profiles carry empty `scanOverrides` (`{}`), so they always
   track whatever `contract_rules.yaml`/`executionParamDefaults.ts` currently
   ship as default. `Restrictive`/`Loose` bake in fixed values (0.08/200/1000
   and 0.30/20/75) — if the app's own defaults change later, these two tiers
   won't auto-rescale relative to the new baseline; they'd need to be
   re-derived and re-saved.

Structurally, the export itself is stable: `searchProfilesStore` is at
schema `version: 3` with a `migrate()` path, so an older-shaped profile
loads fine going forward — but that's a statement about today's code, not a
promise about all future schema changes to that store.

## Using one for a scheduled/background scan

Bamendjou has a separate scheduled-scan mechanism
(`backend/app/services/scan_scheduler.py` + a schedule-entry API) that can
reference a saved profile by id and keep its `resolved_request` in sync
whenever the profile is saved or updated
(`searchProfilesStore.ts`'s `resyncScheduleEntriesForProfile`). Wiring one of
these 18 profiles into that isn't done by this export — it requires loading
the profile into a real browser (via the console script above) and creating
a schedule entry in Settings → Scan, picking the profile, cadence, and
scan window.
