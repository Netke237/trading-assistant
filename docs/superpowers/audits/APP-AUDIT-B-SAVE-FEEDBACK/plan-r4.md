# APP-AUDIT-B-SAVE-FEEDBACK — plan round 4

GATE FINDINGS: **1**. Not clean.

Reviewer: fresh independent agent `/root/save371_plan_stage2_r1`, applying
`.claude/skills/bmad-review-adversarial-general/SKILL.md` and
`.claude/skills/K-adversarial-audit-loop/SKILL.md` with the numeric/persistence
gate. This is authorized plan stage 2, round 1 of 3; continuous plan round 4.
Original rounds 1–3 remain counted and capped/nonclean. The owner answer and
new-stage decision are recorded separately; this review does not reopen the old
stage or authorize implementation.

## Exact scope

- Reviewed HEAD: `8e2c6314d3ae25abc21bbd43486480e40eff1223`.
- Plan: `docs/superpowers/plans/2026-10-20-app-audit-b-save-feedback-plan.md`.
- Plan SHA256: `6214b8dd63488c8fd4e5eea4c492bca232c8ddff39380147608749e2da4ea3fe`.
- Plan git blob: `010a7864d2fc6d0bdad5fd854f8c505c8330fb54`.
- Shrinking review scope: the R3-F1 correction in the plan diff
  `03e5d93c..b6755738`, plus its interactions with the current plan and actual
  Settings save/unmount/remount paths on integrated main `a1811c0e`.

Read AGENTS.md, the audit rule and explicit second-stage decision, board and
ticket contracts, both preceding reports, the actual fix diff, current Settings
components, the shared API POST helper and actual retention save handler.
`python3 scripts/state.py --quiet` exited 0 with only unrelated historical
unaudited-record warnings. No K-session file was present. No source/plan/state,
claim, commit, provider, broker, notification or shared-data mutation was made.

## R4-F1

- **location:** Plan lines 25–27, 29 and 69, interacting with the new R3-F1
  sequence guard and T3. Source reachability: Settings page lines 80–88,
  595–620 and 639; `frontend/lib/api.ts:130` and `:1002`;
  `backend/app/routers/notification_settings.py:112`.
- **trigger_condition:** A new save beginning after discard is allowed to clear
  the discarded marker while an older save is still in flight. Start with
  scheduled-scan retention **90 days**. Submit attempt 1 for **120**, keep its
  request pending before the server commits it, edit to **180**, then leave the
  Scan section: the plan records discarded sequence 1. Return to Scan; the fresh
  GET still returns server value **90**, and the current Save button remains
  enabled. Save that **90** as attempt 2, begun after the discard. Let attempt 2
  commit and return first: sequence 2 is latest and greater than discarded 1,
  so the specified rule clears the marker; the current component's display and
  confirmed baseline are both **90**, with no draft. Then let the independent
  older request commit **120** and return. Its component was unmounted, and the
  ledger explicitly ignores its settlement because it is no longer latest.
  Even if `settleAll` correctly awaits **both** promises, the final outstanding
  set is empty and the footer says **Saved** while displayed **90** differs
  from persisted **120**.
- **guard_snippet:** Serialize each channel's entire `run` callbacks across
  unmount/remount, registering queued attempts synchronously in the ledger but
  starting a newer callback only after all earlier callbacks for that channel
  settle. Preserve the discard-sequence guard and include queued attempts in
  `settleAll`. Add the deferred-server-commit regression above: a newer attempt
  begun after discard must not become confirmed and erase the marker while an
  older write can still finish afterward. An equivalent conservative
  unconfirmed status plus authoritative readback/re-save after older completion
  can also satisfy the contract; silently ignoring that older completion cannot.
- **potential_consequence:** The added after-discard clearing rule certifies a
  stale numeric setting. The user sees **90 days** and **Saved**, but the server
  persists **120 days**. This is a reachable wrong-number/persisted-setting gate
  failure, specifically an interaction of the R3-F1 correction with its permitted
  next save; it is not a new review of generic unrelated save concurrency.

## Falsification and scope check

The current page unmounts the section when its subnav changes, so the older
completion cannot update the newly mounted component's `days` state. Retention
Save has no disabled/in-flight guard, and remounting also resets component-local
guards in other explicit-save forms. The shared POST helper sends independent
fetches with no per-channel queue or version. The actual endpoint accepts each
valid value, writes it, and returns it; it has no attempt sequence/version
guard. Requests can arrive/commit in either order; the reproduction requires
the older **write**, not merely its response, to finish last.

A finite Node assertion model of the plan's stated rules retained **all**
pending promises, discarded the first component, saved 90 in the second
component, committed request 2 then request 1, and produced:

```json
{"pending":0,"discarded":null,"draft":false,"baseline":90,"display":90,"server":120,"footer":"Saved"}
```

This is a plan-mechanism counterexample over frozen synthetic inputs, not a
claim that the not-yet-built ledger was executed. The model deliberately grants
the stronger all-promises interpretation of `settleAll`; latest-only pending
tracking is not needed for the finding. Also checked the original R3 scenario
(older attempt settles after discard with no later save): the strict sequence
guard does preserve its marker as intended. The failing interaction needs the
new, explicitly permitted post-discard attempt followed by the older write.

No unrelated original-plan areas were reopened or reported. Implementation and
code review remain pending.
