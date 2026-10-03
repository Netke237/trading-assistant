# Options explanation corrections

Correction commit: `283c2cbbb8d6593ff8bacbe7c37b39f49ed24e85`, parent integration commit `66561e26`. Existing implementation heads: Step5 `9b8a2971`, Contracts `ac39b841`; both histories were integrated in the existing checkout on `codex/options-explanation-fixes`. This branch has not been merged into main.

## Corrected behavior

- Step5 renders the exact IV observation in collapsed rows, native tooltip text and expanded explanations. `34.01%` and rank `34.001` stay distinguishable from the34 ceiling; classifiers and persisted scan data are unchanged.
- Header, rules strip and disclosure use the same IV interval formatter. Null caution goes directly from PASS to REJECT. Coincident or above-caution effective pass limits explicitly have no reachable CAUTION interval.
- All event descriptions retain strict comparisons and explicitly show the empty CAUTION interval when boundaries coincide.
- Contracts reads backend weight key `iv_rank`, displays15% with default payloads and preserves fractional weights such as15.25%.
- Spread observations/comparisons consistently convert ratios to percentages, including2 →200%; the absolute IV formatting path remains distinct.

## Verification

New literal regression assertions initially failed against delivered code:8 failures across3 targeted suites. The existing null-caution literal pin encoded the defective sentence and was corrected to assert direct REJECT after PASS.

Final checks on the integrated correction commit:
- Typecheck: passed.
- Targeted frontend:12 suites /169 tests passed.
- Full frontend:188 suites /4541 tests passed.
- Chromium:23 checks passed, covering new boundary regressions, both pages at1280/1440/1920, dark/light Step5 layouts,20 disclosures, keyboard/network isolation, below-minimum overlay and IV-basis smoke. Original tracked screenshot artifacts were restored byte-for-byte after running existing tests.
- Python3.11:87 tests passed in explanation, validator, scoring and Step6 rule suites.
- Production build: passed with allowed Google Fonts destinations.
- State probe: exit0; unrelated pre-existing STATE-PROBE audit warnings remain.

No gate/scorer, dependency, lockfile or persistence-schema changes were made in the correction commit. Existing React act warnings in inherited suites were not counted as numeric gate findings. The200-contract performance benchmark was not re-certified for these presentation corrections.

## Independent reviews and cap

Step5's historical code rounds remain4 with findings13,12,6,0. Its current clean flag is false because the new fixes were not independently reviewed. No fifth round was silently run, and no history was reset. The user was asked for one explicit exception after the corrections and checks were concrete. Pending approval is not approval.

Contracts historical completed count remains1. An earlier independent reviewer died on a model usage limit before returning a verdict; that aborted review is not clean and does not increment completed audit rounds. A fresh correction reviewer `/root/contracts_fix_audit` was commissioned for Contracts only against `66561e26..283c2cbb`: Step6 page, contractExplanation helper and their regression tests, plus scorer wire/presentation interactions. It returned one gate finding: expanded component cards rounded the same `iv_rank: 0.1525` to `Weight: 15%` while the corrected banner showed `15.25%`. The reviewer independently reproduced the discrepancy by rendering the real component. The follow-up fix removes integer rounding from component weights and adds a literal rendered-card regression. Three targeted Jest suites / 16 tests passed after this fix. Code round 3 will review only that fix and its interactions; Step5 remains excluded.

The shipping gate remains open until the respective independent review is complete. Project state is authoritative for current verdicts; this document records evidence and scope.
