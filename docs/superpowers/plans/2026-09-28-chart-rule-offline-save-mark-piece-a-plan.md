# CHART-RULE-OFFLINE-SAVE-MARK (piece A) — plan

- Phase: `CHART-RULE-OFFLINE-SAVE-MARK` (PROJECT_STATE.json), piece A of the split
  `CHART-RULE-OFFLINE-SAVE-MARK-SPLIT-2026-09-28`
- Decisions: `CHART-WS-1D-1W-L3-OFFLINE-MARK-2026-09-28` (option 1, display
  only); `CHART-RULE-OFFLINE-SAVE-MARK-PIECE-A-SCOPE-2026-09-28` (Kenneth
  confirmed the split boundary, and chose to keep the small late-reply guard in A)
- Branch: `claude/clever-planck-rpz8yh`, off main `d46a7cd`
- Source: `docs/superpowers/plans/2026-09-28-chart-rule-offline-save-mark-plan.md`
  (the capped r1–r3 plan). This plan is fresh; its rounds restart at 0.

## The gap

Since CHART-WS-1D-1W-RULES the browser no longer judges 1D/1W rules
(`browserJudgesInterval`, `frontend/lib/chartAlertEngine.ts`); only the server
does. A rule whose POST never reached the server (network error or 5xx — the
`offline` outcome of `pushRuleToAPI`) exists only in the browser, so a 1D/1W
rule in that state is judged by nobody, and the user is not told: `addRule`
marks `unsavedRules` only on `refused`, and `syncRules` keeps an offline mark
only if one already existed.

## Severity gate (PROJECT_STATE.json `audit_rule`, clause 1, verbatim)

> (1) THE GATE IS THE ONLY THING THAT COUNTS, AND THE REVIEWER IS TOLD SO. A
> finding blocks only if it can put a WRONG NUMBER in front of a user or on a
> broker order, or CORRUPT PERSISTED DATA. Everything else -- wording,
> comments, test hygiene, dead code, stale records, latent defects with no
> reachable path -- is not a finding for this purpose, and the audit brief
> must instruct the reviewer NOT TO REPORT IT AT ALL.

For this display-only phase, the only thing that can be wrong in front of the
user is a rule's saved/not-saved mark. Gate-level means that **this change**
leaves a mark missing on a rule the server does not hold, or leaves a mark on a
rule the server does hold after a sync proved it. Nothing here changes what is
persisted (`partialize`) or what is sent.

**Out of scope, owned by piece B `CHART-RULES-SYNC-CONCURRENCY`, not a finding
here:** anything caused by `syncRules`/`addRule`/`deleteRule` interleaving that
exists today and that this change neither introduces nor makes worse. That
covers a rule added during a sync being dropped from `rules`, a rule deleted
during a sync coming back, two overlapping `syncRules` runs, and a fetch that
never settles. The single exception kept in A (Kenneth's choice) is C2(ii): a
late offline reply to `addRule` must not mark a rule that a sync has proved saved.

Caps: plan stage ≤ 3 rounds, code stage ≤ 3 rounds (AUDIT-CAP-PER-STAGE-2026-09-25).

## Scope

Frontend only: `frontend/lib/chartAlertStore.ts` and tests. No backend change,
no page change: the Alerts page already renders `Not saved to server: <reason>`
for any key in `unsavedRules` (`frontend/app/(frame)/alerts/page.tsx:572-576`).

## Changes

**C1. Reason text.** Export
`OFFLINE_SAVE_REASON = 'could not reach the server; retried when the Alerts page or a chart next opens'`.
`syncRules` runs only on those two mounts (`alerts/page.tsx:264`,
`ChartWorkspace/index.tsx:257`), so the sentence is accurate. A 5xx reached
the server, but the server did not confirm the save. Both cases mean "not
saved, will retry", so they share the text.

**C2. `addRule`.** When the POST settles:
- `refused` → mark with the server's detail (unchanged);
- `offline` → mark with `OFFLINE_SAVE_REASON` (new);
- `ok` (201/409) → delete any `unsavedRules[rule.id]` key, unconditionally
  (no (i)/(ii) check). A 201/409 proves the server holds the rule whatever the
  ordering, and a mark CAN exist here: a `syncRules` that ran while this POST
  was in flight may have re-POSTed the rule, got `offline` and marked it under
  C3 (r1 finding 1). Today's code writes nothing on `ok`. It also bumps a
  module-level `okGen = new Map<string, number>()` for that id (r2 finding 1,
  see C3).

Either mark (`refused`/`offline`) is written inside a functional `set((s) => …)`, and only if both
hold:

- (i) a rule with that id is still in `s.rules` when the POST settles. A rule
  deleted mid-POST then leaves no stale key.
- (ii) no `syncRules` has ruled on that id since this POST started.

For (ii), a module-level `syncGen = new Map<string, number>()` sits beside the
store, not in Zustand state, like `notesStore`'s timer map. `addRule` reads
`syncGen.get(id) ?? 0` before its POST. At its final write, `syncRules` bumps
`syncGen` for every id it ruled on: each id in `serverIds` and each
`localOnly` id it re-POSTed. A late offline answer to the original POST
therefore cannot re-mark a rule that a sync has just proved saved (on the
server list, or re-POSTed → ok). If the sync's own re-POST was offline, the
sync has already marked the rule itself, so skipping the late `addRule` write
loses nothing.

**C3. `syncRules`.** For a local-only rule whose re-POST is `offline`, keep an
existing mark verbatim, since a previous refusal reason says more. With no
existing mark, set `OFFLINE_SAVE_REASON`. `ok` (201/409) clears the mark and
`refused` stores the detail, both unchanged. A failed GET still returns early
and changes nothing, because without it the store cannot tell which rules are
local-only.

**C3-ok (r2 finding 1).** `syncRules` copies `okGen` (`new Map(okGen)`)
when it starts, before its GET. In its final write it drops the `unsaved`
entry, whatever kind it is, for every id whose `okGen` value has moved since
that copy. An `addRule` 201/409 that settles during the sync proves the
server holds the rule. This covers the ordering r1's fix misses: `addRule`
settles `ok` first, then the sync's final `set` writes an offline mark. That
offline mark can come from the sync's own re-POST, whose same-id insert
races `addRule`'s POST and gets a 500.

The final write otherwise keeps today's shape: one `set` with
`rules: merged`, `unsavedRules: unsaved` and `migrated: true`. The `syncGen`
bump happens right after that `set`. No other change is made to
`syncRules`' ordering (piece B).

**C4. Doc comments.** Update the comments on `unsavedRules` and `PostOutcome`,
which today say an offline outcome marks nothing, and comment `syncGen`/`okGen` too.
A test-only reset `__resetChartAlertSyncGenForTests()` (clears both maps) is exported and called
in the store test's `beforeEach`.

## Checked, not changed

- **`updateRule` / `putRuleToAPI`.** A PUT to a rule the server lacks returns
  404 (`backend/app/routers/chart_alerts.py` `replace_rule`). The rule keeps
  whatever mark `addRule`/`syncRules` gave it, and the next sync re-POSTs it
  with its current fields. An offline PUT to a rule the server does hold leaves
  the server's previous version, which is stale but still judged, so it is not
  L3. Logged as **L3-a**.
- **Reload.** `unsavedRules` is not persisted (P4a, pinned by a test). After a
  reload the mark comes back on the first sync whose GET succeeds and whose
  re-POST fails. If the server is wholly down, the GET fails and no mark
  shows, but then nothing can be proven either way. Logged as **L3-b**.
- **Interleavings owned by piece B** are listed under the gate above.

## Tests

`frontend/lib/__tests__/p4aChartAlertStore.test.ts`:
- T1. `addRule` + network error → `{ n1: OFFLINE_SAVE_REASON }`; + 503 → same.
- T2. `syncRules` offline (throw, and 503) with no prior mark → marked
  `OFFLINE_SAVE_REASON`. This replaces the old "marks nothing new" assertion.
  A prior refusal mark is kept verbatim.
- T3. An offline mark, then a sync whose re-POST gets 201 or 409 → cleared.
  A sync whose GET returns the rule → cleared.
- T4. `addRule`, then the rule is deleted before the POST settles → no key
  (offline and refused).
- T5c. `addRule`'s POST is pending; a sync's GET returns n1 (and, second case,
  a sync re-POSTs n1 and gets 201); the `addRule` POST then settles offline →
  no mark. Control: with no sync in between, the same late offline answer
  does mark.
- T5d (r1). `addRule`'s POST is pending; a sync's GET omits n1 and its re-POST
  of n1 is offline (n1 marked `OFFLINE_SAVE_REASON`); the `addRule` POST then
  settles 201 → no key. Same with 409, and with a prior refusal mark.
- T5e (r2). `addRule`'s POST is pending; a sync's GET omits n1, and its re-POST
  of n1 returns 500. A second local-only rule's re-POST is held open, so the
  sync has not written yet. `addRule` then settles 201, and the held re-POST
  is released → no key for n1. Control: without the `addRule` 201, n1 is
  marked.

`frontend/app/(frame)/alerts/__tests__/page.test.tsx`:
- T6. The offline reason renders as
  `Not saved to server: could not reach the server; …`.

## Verification

`cd frontend && npx tsc --noEmit && npx jest --silent` must be clean. The
backend is untouched, so no backend run is needed. `state.py` must exit 0.
After the build, the phase probe is re-pointed from the defect marker to a
`present` probe on `OFFLINE_SAVE_REASON`.

## Audit record

- **Plan r1** (2026-09-28): 1 gate-level finding, fixed in this plan. C3's new
  offline mark could be set by a sync while `addRule`'s POST was in flight;
  that POST then succeeding left the mark on a rule the server holds, because
  C2's `ok` branch wrote nothing. Fix: `ok` clears the key unconditionally (C2,
  T5d). Reviewer confirmed C2(ii), C2(i), the bump placement and
  persisted/sent data clean.
- **Plan r2** (2026-09-28, reviewing only the r1 fix): the unconditional clear is
  confirmed safe. 1 gate-level finding, fixed in this plan: the reverse order,
  where `addRule` settles `ok` before the sync's final `set` writes an offline
  mark. That mark can come from the sync's own re-POST racing the server's
  check-then-insert and getting a 500. Fix: C3-ok (`okGen`, copied at sync
  start, drops the mark), test T5e.
- **Plan r3** (2026-09-28, reviewing only the r2 fix): **ZERO GATE-LEVEL
  FINDINGS — plan stage CLEAN.** The reviewer traced every order in which
  `addRule`'s ok can land against the sync's GET, its re-POST and its final
  set. It also checked the offline and refused paths against `syncGen`, and
  that persisted and sent data are untouched.
