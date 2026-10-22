# Independent artifact/code review — round 1

Reviewer: `/root/settings_profiles_artifact_r1`, fresh independent subagent.
Date: 2026-10-16. Applied the repository adversarial-review skill and numeric /
persistence gate, with requested coverage reviewed separately.

**Verdict: zero artifact gate findings; zero concealed coverage or evidence
integrity findings after scope recheck.** No fixes required. Application
acceptance remains open; discovered product defects are not artifact defects.

## Exact scope

Base `00b4ab54069e2a43e0a66cd1f183f5fa2347f336`, reviewed head
`c3945a4024f8bc767c8608a99ee0b59988fac03e` after conflict-free main merge.
`git diff --binary <base>...<head>` SHA256:
`470b9005769f51f65856d1416aea74c3d0725005d6e8fd8fcfad334140eee602`.
All 74 changed files are in this lane directory. The reviewer independently
regenerated the diff/hash and verified scope. [File hashes](review-code-r1.json)
pin the exact reviewed content. The working tree stayed clean during review.

## Independent checks

The reviewer inspected every executable evidence script, captured outputs,
family reports, defect registry, provenance, reconciliation and limitations.
82 hashes matched across controls/regime manifests, frozen source inputs and
inventory-baseline compatibility sets. All 36 inventory IDs matched the
reconciliation and all evidence references resolved. Controls totals matched:
312 authoritative observations, 297 pass and 15 overlapping failure checks.

Source tracing covered cap conversion, weight handling, ignored confidence and
Entry Quality overrides, Settings save feedback, schedule rollback, stale regime
writes and mode-specific Run Scan paths. Selected screenshots corroborated the
false Saved feedback, notification text and stale-regime contradiction.

Temporary-copy replays used Python 3.11.16 and preserved frozen artifacts:

| Probe | Independent observation |
| --- | --- |
| Controls source | All 69 check records matched. |
| Controls parameter | All 59 check records matched. |
| Backend controls | All 18 checks/numerical outputs matched, excluding evaluation timestamps. |
| Settings persistence | 10 passes and identical restart API/config results. |
| Settings families | 13 passes/four known rollback failures; API/disk/restart divergence matched. |
| Regime numerical subset | All 12 captured fields through supplied-model inference and actual daily-fixture fits matched. |

Browser evidence was inspected against scripts/source; browser runs were not
duplicated. The full regime replay stalled on restricted local wakeup sockets.
Automatic approval review rejected its broad network-enabled retry because
network behavior was not sufficiently established. The reviewer completed the
safe numerical subset and source/output inspection. This limits replay breadth;
it is not a passing full replay. No repository or GitHub writes were made by
the reviewer.

## Requested coverage still open

These were already disclosed obligations, not new artifact findings:

- `regime/coverage.md`: no frozen real 15-minute provider fixture. Daily/synthetic
  bars and supplied models do not certify real intraday model accuracy. Require
  provenance, completed-bar selection and independent inference expectations.
- `settings/coverage.md` and `controls/coverage.md`: conditional Settings states,
  schedule rows, storage-write failures, concurrent recovery and integration
  consumers remain not run or assigned to other lanes. Preserve those states
  until owner evidence supplies the missing checks.
- `reconciliation.json`: the 36 definitions belong to Lane A's incomplete
  structural increment. Final runtime/state reconciliation is required before
  closing #350.

The original backend run remains **3 failed / 88 passed**; supplemental passes
with exclusions do not establish a fully green backend suite. No product fixes
or recalibration are authorized by this evidence review.
