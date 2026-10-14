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
