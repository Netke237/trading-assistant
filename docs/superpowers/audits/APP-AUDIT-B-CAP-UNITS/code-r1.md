# APP-AUDIT-B-CAP-UNITS — independent code audit, round 1 of 3

GATE FINDINGS: **0**. Clean after an independent second pass over the whole target.

Reviewer: fresh independent agent `/root/cap368_code_r1`, applying
`.claude/skills/bmad-review-adversarial-general/SKILL.md` and
`.claude/skills/K-adversarial-audit-loop/SKILL.md`, with the repository
numeric/persistence gate. This is code round 1, continuous phase round 3;
the two completed plan rounds remain preserved. No implementation changes,
claim mutations, commits, pushes, providers, orders or notifications were made.

## Exact scope

Reviewed frozen range
`55519e05a198eb7c646a13245242f722c11c3610..d86e80d1b983f44fe4fd97b7e87f13d4098cb1dd`.
SHA256 of the complete `git diff` for that range:
`61937ca2db284d9dd0bccc6632dc76b8de289f966307bf461faf2dddbcc487f7`.
The source and test working trees matched the frozen reviewed head when checked.
The coordinator's subsequent uncommitted validation paragraph is documentation
of rerun results; it does not change this source scope or this verdict.

Read the actual production/test diff, approved plan and prior plan findings,
request schema, actual candidate cap filter, manual RunScanButton, profile
resolver, profile update/resync, schedule routes/schema/store/scheduler and
Settings run-error display. Reconciled the current-main schedule-store recovery
and Stocks filter/confidence additions. The state JSON's semantic changes are
limited to this phase, active phase, update date and updater; other phase values
and the backlog remain identical to the base.

## Second-pass falsification checks

No qualifying finding was established, so there are no location/trigger/guard/
consequence finding entries. After the initial clean pass, specifically checked:

1. Both live manual state and saved Options profiles reach the same corrected
   builder; neither introduces another conversion, and both bounds use USD.
2. Millions use `1e6`, billions retain `1e9`; fractional values, explicit zero,
   blank omission and existing finite-input checks retain their intended paths.
3. The marker is a top-level request field emitted by the corrected builder,
   not an ignored scoring override; backend validation recognizes it.
4. Direct manual USD requests remain valid without the marker. Unsupported
   explicit marker versions fail schedule validation before store mutation.
5. A marker survives real schedule schema/model dumping and YAML roundtrip.
   A legacy missing-marker record still appears in GET/list and can be resynced.
6. Fixed-time, loop and run-now dispatch converge on the guarded function.
   Either nonzero bound without marker 1 refuses before reported scan/core;
   absent and zero-only legacy bounds retain their existing behavior.
7. The refusal does not infer lost unit intent, rewrite a request, disable a
   schedule or replace a previous successful result with fabricated counts.
8. The dedicated error survives the broad exception handler, is persisted in
   the existing run-error field and reaches the existing Settings error text.
9. Re-saving a profile invokes the actual shared resolver and full PUT resync,
   carrying fresh amounts and marker 1; a failed resync cannot certify old values.
10. Current-main store recovery preserves the raw nested request and does not
    migrate Options cap units. Stocks filter/confidence resolution stays in its
    separate branch and does not acquire the Options schedule-only refusal.
11. Actual backend filtering receives `req.min_cap_usd`/`req.max_cap_usd`
    unchanged and compares literal USD, including equality and zero boundaries.

## Independent verification and limits

- Verified the prepared interpreter is **Python 3.11.16**.
- Independently ran `.venv/bin/python -m pytest -q tests/test_options_cap_units.py`
  from backend: **31 passed in 1.88 seconds**. Tests isolate providers, reporting,
  notifications and storage; cover refusal/recovery and actual cap boundaries.
- Independently ran the direct-builder and saved-profile-resolver Jest suites:
  **35 passed, 2 suites passed**, in 3.03 seconds.
- `python3 scripts/state.py --quiet` exited 0. It retains the expected pending
  code-audit warning and unrelated historical unaudited-record warnings.

The recorded earlier backend total is qualified segmented coverage, including
48 unchanged endpoint cases with temporary offline prefetch mocks. It is **not**
an unmodified full-suite pass. This audit does not replace the required complete
unmodified CI checks, exact-head mergeability/ownership checks or a verified
merge. The clean verdict concerns the numeric/persistence code gate only.
