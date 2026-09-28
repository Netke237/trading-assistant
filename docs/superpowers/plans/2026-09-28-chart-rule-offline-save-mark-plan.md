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
Either mark is written only if (i) a rule with that id is still in `rules`
when the POST settles, so a rule deleted mid-POST leaves no stale key, and
(ii) no `syncRules` has ruled on that id since this POST started (r1 finding
2): a module-level `Map<string, number>` generation counter (not Zustand state,
like `notesStore`'s timer map) is read by `addRule` before its POST; every
`syncRules` bumps it, at its final write, for every id it ruled on (each id in
`serverIds` and each re-POSTed `localOnly` id). A late offline answer to the
original POST can then not re-mark a rule a sync has just proved saved.

**C3. `syncRules`.** For a local-only rule whose re-POST is `offline`: keep an
existing mark verbatim (a previous refusal reason is more informative), else
mark `OFFLINE_SAVE_REASON`. `ok` (201/409) clears; `refused` stores the detail
(both unchanged). A failed GET still returns early and changes nothing — the
store cannot tell which rules are local-only without it.

The final write becomes a functional `set((s) => …)` computed against the
state at that moment, not the snapshot taken before the awaits (r1 finding 1:
today a rule added while the sync awaits its re-POSTs is dropped from `rules`,
and so from localStorage, silently). With `snapshot` = the ids in `localRules`
and `current` = `s.rules`:
- **rules** = the server rules, then the snapshot's `localOnly` rules, each
  kept only if its id is not "deleted mid-sync" (in `snapshot` but no longer
  in `current`); then every rule in `current` whose id is neither in
  `snapshot` nor in `serverIds` (added mid-sync), appended in `current` order.
- **unsavedRules** = the sync's verdicts for the ids it re-POSTed and kept,
  plus, for each rule added mid-sync, its current mark if any. Ids in
  `serverIds` have no mark.

**C3-deleted.** Deletions are recorded, not inferred (r2 finding 2). A
module-level sequence number goes up on every `deleteRule`, which stores
`deletedAt[id] = seq`. Each sync reads `seq` when it starts; its final write
drops any id deleted since then (`deletedAt[id] > startSeq`) that is not in
`current`, whichever list it came from (server or snapshot). Without this a
rule the user deleted while the sync awaited comes back from a GET that
predated the DELETE, unmarked, although the server no longer holds it. A server
rule not in the snapshot and not deleted (created elsewhere) is kept as today.

**C3-serial.** `syncRules` never runs twice at once (r2 finding 1). A
module-level in-flight promise: a call while one runs does not start a second
concurrent run; it waits for the running one, then runs once more (several
calls during one run share that single follow-up run), so a mount that comes
second still gets a fresh GET. Two overlapping runs otherwise let the older
run's final write, carrying an older verdict, overwrite a newer run's (e.g. an
older offline verdict re-marking a rule a newer sync proved saved). With runs
serial, every final write is the newest verdict, and C2's counter needs only
to order `addRule` against a sync.

**C3-bound.** A run can never wedge the queue (r3 finding): each fetch inside
`syncRules` (the GET and each re-POST) gets an AbortController timeout of 15s; a
timed-out re-POST is `offline` (so the rule is marked `OFFLINE_SAVE_REASON`),
a timed-out GET returns early as a failed GET does today; the in-flight slot is
cleared in a `finally`, so a thrown run (e.g. a localStorage write error in the
final `set`) cannot block later runs. Module-level state (in-flight promise,
deletion seq, generation map) gets a test-only reset used in `beforeEach`.

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
- **Edit mid-sync.** An `updateRule` while the sync awaits is overwritten by the
  server's version in `merged` (as today); its PUT still lands on the server,
  and the next sync shows it. Not a saved/not-saved state error; unchanged.

## Tests (`frontend/lib/__tests__/p4aChartAlertStore.test.ts`)

- T1. `addRule` + network error → `{ n1: OFFLINE_SAVE_REASON }`; + 503 → same.
- T2. `syncRules` offline (throw and 503), no prior mark → marked
  `OFFLINE_SAVE_REASON` (replaces the old "marks nothing new" assertion); a
  prior refusal mark is kept verbatim.
- T3. An offline mark, then a sync whose POST gets 201 / 409 → cleared; a sync
  whose GET returns the rule → cleared.
- T4. `addRule`, rule deleted before the POST settles → no key (offline and
  refused).
- T5. `addRule` of n1 while a `syncRules` is awaiting a re-POST, n1's POST
  offline: after the sync, n1 is in `rules` AND marked `OFFLINE_SAVE_REASON`.
- T5b. Deleted while the sync awaits, for (i) a local-only snapshot rule,
  (ii) a server snapshot rule, and (iii) a rule the GET returned that was not in
  the snapshot but entered `rules` and was deleted during the sync: none is in
  `rules` after the sync, and none has a key in `unsavedRules`.
- T5c. `addRule` POST pending → a sync re-POSTs n1 and gets 201 → the `addRule`
  POST then settles offline → no mark.
- T7. Two `syncRules` calls back to back: the second GET is not sent until
  the first run's final write; a third call during the first run shares the
  second's follow-up run (exactly two GETs).
- T8. The r2 scenario: first run's n1 re-POST offline while a second call is
  queued; the queued run's re-POST gets 201 → n1 ends unmarked.
- T9. The first run's GET never resolves: after the 15s timeout (fake timers)
  the queued call sends its own GET and marks the offline rule; a run whose
  final `set` throws does not block the next call.
- T6. Page test (`alerts/__tests__/page.test.tsx`): the offline reason renders
  as `Not saved to server: could not reach the server; …`.

## Verification

`cd frontend && npx tsc --noEmit && npx jest --silent` clean. Backend untouched
(no backend run needed; state.py exit 0). After the build the phase probe is
re-pointed from the defect marker to `present` on `OFFLINE_SAVE_REASON`.

## Audit record

- **Plan r1** (2026-09-28): 2 gate-level findings, both fixed in this plan.
  (1) a rule added while `syncRules` awaits was dropped from `rules` and never
  marked (pre-existing drop; C3's functional final `set`, T5); (2) a late
  offline answer to `addRule`'s POST could re-mark a rule a sync had just
  proved saved (C2's generation counter, T5c). The reverse of (1), a rule
  deleted mid-sync coming back unmarked, was added as C3-deleted/T5b.
- **Plan r2** (2026-09-28): 2 gate-level findings, both from two `syncRules`
  runs overlapping, fixed in this plan: (1) an older run's offline verdict
  could re-mark a rule a newer run proved saved (C3-serial, T7/T8); (2) a rule
  another run brought in, then deleted, could come back unmarked (C3-deleted
  now records deletions, T5b(iii)).
- **Plan r3** (2026-09-28): 1 gate-level finding: under C3-serial a run whose
  GET or re-POST never settles would block every later sync for the life of
  the tab (worse than today). Fix written in as C3-bound/T9. **PLAN-STAGE CAP
  REACHED (3 rounds, none clean): auditing stopped, decision asked of Kenneth.**
