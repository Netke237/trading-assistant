# STATE-MULTI-PLAN-STAGE validation

This records verification for #301 (T2), not an independent audit verdict or
shipping approval. The checker implementation is T1 commit `5594f99d`;
T2 verified merged source at `8c4cb42f` (which includes main `f655b7e2`).
No phase counters, original decisions or application source were changed by T2.

## CLI end-to-end proof

On 2026-10-14, `/tmp/prebreakout-venv/bin/python` (Python 3.11.16) reran
`/tmp/verify-multi-stage-cli.py`. This verification-only script creates three
fresh real-git repositories with a `main` base, `origin/main`, feature branch,
target-introduction commit, presence-probe file and actual audit subjects. It
copies the implemented `scripts/state.py` and invokes its CLI `main` in a
subprocess with `--quiet`; this is not a helper-only assertion. It loads the
original TRADIER opening decision from the state file without changing it.
Results were written to `/tmp/multi-stage-cli-results.json`.

| Case | Actual recorded conditions | Expected / actual exit |
|---|---|---|
| Authorized two stages | `audit_rounds: 6`, overall clean false; stages 3+3, first closed by the actual opening decision, second opened by it and closed clean; plan subjects 1–5 findings, positive plan round 6 clean | 0 / 0 |
| Missing authorization | Same subjects and stage record, but synthetic root decisions empty | 1 / 1 |
| Code cap | Same closed plan stages; total 9, overall clean false; additional paired continuous rounds 7–9 / code rounds 1–3 findings | 1 / 1 |

Both failure cases also asserted the CLI output contains `DRIFT`. Each case
contains a valid presence probe so the exit tests bookkeeping rather than a
missing source symbol. Synthetic changes exist only inside temporary
repositories; no historical TRADIER target was rewritten.

## Verification results

T1's pre-main-integration results, supplied by the coordinator:

- Python 3.11.16 focused state suites: 342 passed (254 legacy, 88 new).
- Full backend: 8,298 passed, 9 skipped, 859.20 seconds.
- Frontend: 241 suites, 5,158 tests passed; typecheck passed.
- Production build passed using verification-only official cached font
  responses at `/tmp/prebreakout-fonts/responses.js`.

T2 on merged source `8c4cb42f`:

- CLI three-case proof above passed.
- `npm run typecheck` passed (exit 0).
- `npm run test -- --maxWorkers=2 --silent` passed (exit 0): 252 suites,
  5,254 tests, 146.352 seconds; log `/tmp/multi-stage-t2-frontend.log`.
- Integrated full backend: pending coordinator completion; log
  `/tmp/multi-stage-integrated-backend.log`. The pre-integration count above
  is not a substitute for this result.

The `frontend/node_modules` symlink and all `/tmp` verification artifacts are
environment-only and excluded from the commit. Independent integrated code
audit and shipping remain coordinator responsibilities.

## Scope and limitations

T2 changed only this validation record and `docs/superpowers/STATE_TRACKING.md`.
No new tests were needed: T1 contains real-git regression coverage and the CLI
proof directly exercises observable exit statuses. Legacy singular metadata,
subject-only evidence, ownership/introduction scoping and accepted historical
identity-reset holes remain unchanged. A green CLI result does not certify
independent reviewer behavior or approve another phase's merge.

## Post-fix integrated verification

Fresh implementer `/root/multi_stage_fix_c1`, commit `7a91533cca130f0ee054f8ae4b3780122ffa496f`: all three real-git wrong-cap cases were RED, then complete opening suffix and target ownership guards passed 371 focused tests (254 legacy +117 plural). Frozen source/tests fingerprints remained unchanged through Python3.11.16 full backend: **8,431 passed,9 skipped**,890.40s. Frontend **252 suites /5,254 tests** and typecheck passed. An initial post-fix run was explicitly stopped before a mixed-case interaction correction; this final refrozen run is the full proof. Prior merged-source pre-fix baseline was8,402/9 and is not substituted for this result. Independent code round2 is pending; nothing merged.

## Independent code stage — paused, not clean

Fresh `/root/multi_stage_code_r2` reviewed only fixes/interactions `3fe29695..5c65e5d8`, continuous round4/code round2. Two real-git numeric gate findings remain: **C2-G1** at `scripts/state.py:903` accepts `plan rounds4-6: if approved` / `plan rounds4-6 -- is not authorized`; **C2-G2** at `scripts/state.py:919` accepts suffix `for other` / `for other-target` when q names only the active target. Each falsely treats unauthorized overall plan round4 as local stage round1. No fixes applied after this review. User requested immediate stop and chat-only Session Handoff. Built/tested source remains unmerged and audit_clean=false. Plan2clean; code2notclean; only one code review round remains. No counter reset, no fourth code round.

## Recovered C2 fix verification — #308

Fresh `/root/recover_308` recovered the unpushed continuation fix from581cbedd. Scoped commit `7099cd77e22fcdfda0fbea96f5d922bf1de75944` changes only scripts/state.py and its plural-stage tests. RED:14 original C2,4 indirect/chained suffix,8 trailing-owner forms falsely accepted authorization before their guards. GREEN:Python3.11.16 focused401; backend8799passed/9skip in1077.58s; frontend typecheck and252suites/5254tests in227.389s. Initial frontend six failures followed a timeout; isolated31/31 passed, then complete rerun passed. Initial backend run stopped before final interaction adjustment; only final frozen-source result claimed. Source/test SHA256:8b0c21aa7a3b86f4a81c07d0e17b0989231b4632134fc2deafa29fe0dc4d3214 /14a45006ed8111685a2a798006e97df008a57f3b11f85e1409d53afbbcd00f79.

Coordinator synthetic real-git CLI proof: canonical/historical approvals exit0; colon conditional, dash negative, lowercase other and other-target exit1 with STATE DRIFT. Current main472bb1b0 integrated; original code2 findings/counters preserved. Independent final code3 pending; nothing merged.

## Authorized C3-G1 bounded follow-up — #314

User explicitly approved a new bounded code stage, cap3, preserving previous5 rounds and original code stage3notclean. Fresh `/root/fix_c3_clause` commit `c6ae59d84d68f6709d82fd8f618e0f211ab2928a` validates the entire excluded policy tail against complete recognized wording. Unknown suffixes, punctuation-chained denials/conditions, conflicting owners and round ranges fail closed; actual historical Tradier wording remains accepted. Only scripts/state.py and plural-stage tests changed. RED32 real-git false openings. GREENPython3.11 focused460/41.77s; backend8858passed9skip/1032.22s; frontend252suites5254tests/255.577s and typecheck. Source/test SHA256:f4dca7fa7ce06f29f9304f4512f21f94458595fba88131252e28a04ee50b7151 /2b2db3ebe3d9a9dee13417ab282a95289cb40b095a7ca2011257183fe8106f66 unchanged through full checks. Coordinator26synthetic real-git CLI proof:20unauthorizedexit1 with drift,6validexit0 inclhistoricalapproval.

Original singular checker cannot model the explicitly authorized additional code stage; its historical cap alarm remains explained, no counters reset or acknowledgement flag used. Fresh independent stage2 round1 pending; audit_cleanfalse, no PR/merge.

## Shallow CI correction and current main integration — #317

Resumed from published PR #316 head `3c7d8b78` in a replacement workspace. Unpublished checkpoint `86e71ca8` and its portable handoff were unavailable. No claim is made to have recovered or published that payload.

Test-only commit `9f79bfe2` replaces both historical `git show origin/main` JSON reads with checked-in UTF-8 file reads and removes the unused subprocess import. Historical approval selection and assertions remain unchanged; no parser or workflow change. A depth-1, single-branch checkout without `origin/main` reproduced all four affected failures before correction. Corrected shallow state suites: **460 passed in 37.58s**, Python 3.11.16.

Current main `625d8f77` integrated at frozen head `e5a4b737d5f154f6964a14784890e090f25a04f5`. The conflict only involved the active phase pointer; #214 remains active. All existing decisions, all six prior audit records and the original capped stage were preserved. Imported frontend files and unrelated phases match main.

Fresh independent `/root/state214_stage2_round2` reviewed the test correction and its interactions with the parser, historical decision and main integration, twice: **zero gate findings**. Independent changed-case verification: integrated 4 passed in 2.91s; depth-1 checkout without `origin/main` 4 passed in 3.27s. State checker exit 0, no drift. This is continuous round 7, overall code round 5, authorized stage 2 local round 2. One round remains under the original follow-up cap; no history reset.

Final integrated validation on unchanged reviewed source:

| Check | Result |
| --- | --- |
| Backend, Python 3.11.16 | 8,858 passed, nine skipped; 851.45s |
| Frontend Jest | 255 suites / 5,273 tests passed; 286.315s |
| Frontend typecheck | Passed |
| Production build | Passed, including font loading |
| Shallow focused state suites | 460 passed; 37.58s |
| State checker / diff check | Passed |

Backend emitted 1,136 warnings, including aiosqlite worker callbacks after event-loop closure; the run exited 0. These unrelated test-runtime warnings were not fixed in this test-only scope. The independent reviewer did not rerun the full suites; the coordinator did.

Frozen parser/test SHA256: `f4dca7fa7ce06f29f9304f4512f21f94458595fba88131252e28a04ee50b7151` / `89e05797a6509309a7fa1ea7ac365464f54ba8f3eb69e871e74ed24179e09909`. Only audit/validation records changed afterward. Publication approval and exact-head CI remain pending. Nothing merged.
