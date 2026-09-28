# CHART-RULE-OFFLINE-SAVE-MARK — plan

- Phase: `CHART-RULE-OFFLINE-SAVE-MARK` (PROJECT_STATE.json)
- Decision: `CHART-WS-1D-1W-L3-OFFLINE-MARK-2026-09-28` (option 1, display only)
- Branch: `claude/clever-planck-rpz8yh`, off main `d46a7cd`
- Closes gap L3 of `CHART-WS-1D-1W-RULES`
  (`docs/superpowers/plans/2026-09-27-chart-ws-1d-1w-rules-plan.md`)

## The gap

Since CHART-WS-1D-1W-RULES the browser no longer judges 1D/1W rules
(`browserJudgesInterval`, `frontend/lib/chartAlertEngine.ts`); only the server
does. A rule whose POST never reached the server (network error or 5xx, the
`offline` outcome of `pushRuleToAPI`) exists only in the browser, so a 1D/1W
rule in that state is judged by nobody — and today the user is not told:
`addRule` sets the `unsavedRules` mark only on `refused`, and `syncRules`
keeps an offline mark only if one already existed.

## Severity gate (PROJECT_STATE.json `audit_rule`, clause 1, verbatim)

> (1) THE GATE IS THE ONLY THING THAT COUNTS, AND THE REVIEWER IS TOLD SO. A
> finding blocks only if it can put a WRONG NUMBER in front of a user or on a
> broker order, or CORRUPT PERSISTED DATA. Everything else -- wording,
> comments, test hygiene, dead code, stale records, latent defects with no
> reachable path -- is not a finding for this purpose, and the audit brief
> must instruct the reviewer NOT TO REPORT IT AT ALL. Round 6 returned 16
> findings of which 5 were real bugs; the other 11 cost triage time and are
> now recorded forever. An adversarial reviewer with no severity floor ALWAYS
> finds something, so 'clean' was unreachable by construction.

For this display-only phase the only thing that can be wrong in front of the
user is the rule's saved/not-saved state. A mark missing on a rule the server
does not hold, or a mark left on a rule the server does hold (after a sync that
proved it), is treated as gate-level. Persisted data: `unsavedRules` is not
persisted, and nothing here changes what is persisted (`partialize`) or sent.

Caps: plan stage ≤ 3 rounds, code stage ≤ 3 rounds (AUDIT-CAP-PER-STAGE-2026-09-25).

## Scope

Frontend only: `frontend/lib/chartAlertStore.ts` and tests. No backend change.
No page code change: the Alerts page already renders
`Not saved to server: <reason>` for any key in `unsavedRules`
(`frontend/app/(frame)/alerts/page.tsx:572-576`).

## Changes

**C1. Reason text.** Export
`OFFLINE_SAVE_REASON = 'could not reach the server; retried when the Alerts page or a chart next opens'`.
`syncRules` runs only on those two mounts (`alerts/page.tsx:264`,
`ChartWorkspace/index.tsx:257`), so the sentence is accurate. It covers a 5xx
too: the server was reached but did not confirm the save; the reason text does
not distinguish the two (acceptable — both mean "not saved, will retry").

**C2. `addRule`.** When the POST settles:
- `refused` → mark with the server's detail (unchanged);
- `offline` → mark with `OFFLINE_SAVE_REASON`;
- `ok` → nothing (unchanged; a fresh id has no mark).
Either mark is written only if a rule with that id is still in `rules` when the
POST settles, so a rule deleted mid-POST leaves no stale key.

**C3. `syncRules`.** For a local-only rule whose re-POST is `offline`: keep an
existing mark verbatim (a previous refusal reason is more informative), else
mark `OFFLINE_SAVE_REASON`. `ok` (201/409) clears; `refused` stores the detail
(both unchanged). A failed GET still returns early and changes nothing — the
store cannot tell which rules are local-only without it.

**C4. Doc comments** on `unsavedRules` and `PostOutcome` updated (they say an
offline outcome marks nothing).

## Checked, not changed

- **`updateRule` / `putRuleToAPI`.** PUT to a rule the server lacks returns 404
  (`backend/app/routers/chart_alerts.py` `replace_rule`); the rule keeps the
  mark its `addRule`/`syncRules` left and the next sync re-POSTs it with its
  current fields. An offline PUT to a rule the server HAS leaves the server's
  previous version — stale but still judged, so not L3. Logged as **L3-a**.
- **Reload.** `unsavedRules` is not persisted (P4a, pinned by a test). After a
  reload the mark comes back on the first sync whose GET succeeds and whose
  re-POST fails. If the server is wholly down the GET fails and no mark shows;
  but then nothing can be proven either way. Logged as **L3-b**.
- **Race: sync and add in flight together.** `syncRules` sets `unsavedRules`
  from a map built during its loop; an `addRule` mark written in between for a
  rule that was not yet in the sync's `localRules` snapshot would be dropped by
  that `set`. To close it, C3's final `set` merges: marks for ids that are not
  in the sync's `localOnly` list and are still in `rules` are carried over
  from the current state (they were not examined by this sync). Ids the sync
  examined take the sync's verdict; ids the server returned are cleared.

## Tests (`frontend/lib/__tests__/p4aChartAlertStore.test.ts`)

- T1. `addRule` + network error → `{ n1: OFFLINE_SAVE_REASON }`; + 503 → same.
- T2. `syncRules` offline (throw and 503), no prior mark → marked
  `OFFLINE_SAVE_REASON` (replaces the old "marks nothing new" assertion); a
  prior refusal mark is kept verbatim.
- T3. An offline mark, then a sync whose POST gets 201 / 409 → cleared; a sync
  whose GET returns the rule → cleared.
- T4. `addRule`, rule deleted before the POST settles → no key (offline and
  refused).
- T5. An `addRule` mark written while a `syncRules` is in flight, for a rule
  the sync did not examine, survives the sync's `set`.
- T6. Page test (`alerts/__tests__/page.test.tsx`): the offline reason renders
  as `Not saved to server: could not reach the server; …`.

## Verification

`cd frontend && npx tsc --noEmit && npx jest --silent` clean. Backend untouched
(no backend run needed; state.py exit 0). After the build the phase probe is
re-pointed from the defect marker to `present` on `OFFLINE_SAVE_REASON`.
