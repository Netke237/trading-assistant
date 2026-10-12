# 18 options-mode search profiles

3 horizon groups (`Intraday`, `Swing`, `SemiAnnual`) x 3 tiers (`Baseline`,
`Restrictive`, `Loose`) x 2 directions (`Bullish`, `Bearish`), named
`<Group>_<Tier>_<Direction>`. Universe: SP500 for all 18. All 18 are
**Options-mode** profiles: the Step-3 profile dropdown only lists profiles
whose mode matches the screener mode, so none of them appear in Stocks mode.
A Stocks profile is saved from Stocks mode.

## Corrections of 2026-09-29 (after an adversarial review)

- `PositionPlus_*` (Custom, 15-200d hold) became `SemiAnnual_*` (Semi-annual
  preset, 90-105d hold, DTE 180-210). A contract must outlive the maximum hold,
  so a 200-day max hold forced every contract past 200 DTE: the group never
  covered Position/Quarterly/Annual, and together with a backend bug in the
  expiry pick (fixed in the same change, `market.py`
  `_nearest_expiration_in_window` now honours the validator's DTE floor) it
  rejected whole symbols as `dte_too_short`. The profile **ids are unchanged**.
  A schedule entry built from a PositionPlus profile still runs its own saved
  copy of the old request (Custom 15-200) until you open the profile in the
  app and click Update, which re-syncs the entry; the import script cannot do
  that for you.
- `SemiAnnual_Restrictive_*`: an explicit min volume of 50 (the Baseline floor is now 0, off) instead of
  200, because a single ~200-DTE strike rarely trades 200 contracts a day.
  That is a judgement from the measured Baseline Semi-annual run (3 of 518
  candidates, with 101 contract rejects mostly on liquidity and spread), not a
  measured Restrictive run: whether 50/1000/8% returns anything on a given day
  is unverified. It still requires OI >= 1000 and spread <= 8%, so every
  contract it accepts Baseline accepts too; its candidates are a subset of
  Baseline's before the shortlist cap (after the cap, a name Baseline trimmed
  can appear in Restrictive's shorter list).
- `*_Loose_*`: shortlist cap 20 instead of 10, so the cap no longer hides how
  many candidates really pass.
- `SemiAnnual_*` (all 6): event window 7 / 30 (`event_reject_days` /
  `event_caution_days`; the Position default is 30 / 60). An earnings or
  ex-dividend date fewer than 7 days away grades the event rule REJECT, fewer
  than 30 days away CAUTION. That rule is a weighted part of the stock score (20% at Position),
  not a veto: the scan marks the stock down, and Step 5 flags it REJECT or
  CAUTION. A 90-105-day hold crosses an earnings date anyway, so the 30-day
  window mainly shrank the list; the short one still flags entries in the last
  week before a report. Every scan result now carries the window its scorer
  applied (`event_window`), and Step 5 gates on that, so it matches the scan
  even after a reload or a later Step-3 edit.
- `*_Bearish` (all 6): fundamentals debt/equity reject 10 instead of 3 (10 is
  the Settings page maximum). The rule protects a bullish buyer from
  over-leveraged companies; for a put buyer the loss is capped at the premium
  and heavy debt is often part of the bearish case. Negative equity is still
  rejected, and Intraday skips fundamentals entirely. Loading a Bearish
  profile writes 10 into Settings, where it stays for manual scans (Bullish
  too) until another profile is loaded.
- Schedule entries already built from any of these profiles keep their saved
  request (without these changes) until the profile is opened in the app and
  Updated. There were none in Kenneth's setup when this was written.
- Intraday profiles were rejecting every contract from Wednesday to Friday
  (Friday's weekly sat below the DTE floor of 3). That was the same backend
  bug; no profile value changed for it.

The original design rationale and tier numbers are in the
`docs/superpowers/scratchpad` history for branch
`claude/options-scan-liquidity-profiles` (merged to `main` at `ab705ea7`) —
this folder holds the *output*, not the design discussion.

## Files

- `Bamendjou_Options_Search_Profiles.xlsx` — human-readable table of all 18
  profiles and their filter values (hard-reject + soft-rank/preferred), with
  a Legend & Notes tab.
- `search-profiles-export.json` — the raw `bamendjou:search-profiles`
  localStorage payload. Originally a real save; the 2026-09-29 corrections
  were applied to it by script (renamed profiles; each edited profile's
  `updatedAt` is a 2026-09-29 timestamp, untouched ones keep 2026-09-15), in
  the same shape the app writes.
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
4. Reload every open Bamendjou tab. The 18 profiles now appear in the Search
   Profile dropdown on Step 3 (Options mode).

The script **merges by profile id**: each of the 18 replaces the profile with
the same id, and any profile you saved yourself is kept. The previous value is
backed up first under `bamendjou:search-profiles:backup-<timestamp>`. Reload
every open app tab afterwards: a tab left open still holds the old list in
memory and would write it back on its next profile save. An unreadable
existing value is kept in the backup key and only the 18 are imported. The
stored schema version is kept, so the app still migrates your own profiles.
Each run adds a backup key; delete old ones by hand if they pile up.

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
2. **`Restrictive`/`Loose` freeze specific liquidity numbers, `Baseline`
   doesn't.** `Baseline` profiles carry no liquidity overrides, so their
   liquidity and scoring parameters track whatever
   `contract_rules.yaml`/`scoring_rules.yaml` currently ship as default. The
   one exception is the earnings window, which all `SemiAnnual_*` profiles,
   Baseline included, set to 7 / 30. All
   18, Baseline included, do freeze `scanSettings` (confidence gate,
   fundamentals gate, shortlist cap, spreads), and loading any profile writes
   those into Settings, where they stay after the scan. `Restrictive`/`Loose`
   bake in fixed values (0.08/200/1000, except `SemiAnnual_Restrictive` at
   0.08/50/1000; and 0.30/0/75) — if the app's own defaults change later, these two tiers
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
