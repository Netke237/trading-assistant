# Options explanation corrections

Initial correction commit: `283c2cbbb8d6593ff8bacbe7c37b39f49ed24e85`, parent integration commit `66561e26`. Follow-up correction: `b89a1db65f589d215abfb43ce2796840b38b150d`. Existing implementation heads: Step 5 `9b8a2971`, Contracts `ac39b841`; both histories were integrated in the existing checkout on `codex/options-explanation-fixes`. This branch has not been merged into main.

## Corrected behavior

- Step 5 renders the exact IV observation in collapsed rows, native tooltip text and expanded explanations. `34.01%` and rank `34.001` stay distinguishable from the 34 ceiling; classifiers and persisted scan data are unchanged.
- Header, rules strip and disclosure use the same IV interval formatter. Null caution goes directly from PASS to REJECT. Coincident or above-caution effective pass limits explicitly have no reachable CAUTION interval.
- All event descriptions retain strict comparisons and explicitly show the empty CAUTION interval when boundaries coincide.
- Contracts reads backend weight key `iv_rank`, displays 15% with default payloads and preserves fractional weights such as 15.25%.
- Spread observations/comparisons consistently convert ratios to percentages, including 2 → 200%; the absolute IV formatting path remains distinct.
- Expanded Contracts component cards preserve the same fractional weight as the banner, including `0.1525` → `15.25%`.

## Verification

New literal regression assertions initially failed against delivered code: 8 failures across 3 targeted suites. The existing null-caution literal pin encoded the defective sentence and was corrected to assert direct REJECT after PASS.

Checks on initial correction commit `283c2cbb`:

- Typecheck: passed.
- Targeted frontend: 12 suites / 169 tests passed.
- Full frontend: 188 suites / 4,541 tests passed.
- Chromium: 23 checks passed, covering new boundary regressions, both pages at 1280/1440/1920, dark/light Step 5 layouts, 20 disclosures, keyboard/network isolation, below-minimum overlay and IV-basis smoke. Original tracked screenshot artifacts were restored byte-for-byte after running existing tests.
- Python 3.11: 87 tests passed in explanation, validator, scoring and Step 6 rule suites.
- Production build: passed.
- State probe: exit 0; unrelated pre-existing STATE-PROBE audit warnings remain.

After the additional component-weight fix in `b89a1db6`, typecheck and 6 related frontend suites / 46 tests passed. The final independent reviewer separately ran 5 component tests successfully. The complete suite, browser suite and production build were not repeated for this final one-expression formatting change.

No gate/scorer, dependency, lockfile or persistence-schema changes were made in the correction commits. Existing React act warnings in inherited suites were not counted as numeric gate findings. The 200-contract performance benchmark was not re-certified for these presentation corrections.

## Independent reviews and cap

Step 5's historical code rounds remain 4 with findings 13, 12, 6, 0. Its current clean flag is false because the new fixes were not independently reviewed. No fifth round was silently run, and no history was reset. The user was asked for one explicit exception after the corrections and checks were concrete. No approval has been received; pending approval is not approval.

Contracts retains its historical completed round 1 (zero findings). An earlier independent reviewer died on a model usage limit before returning a verdict; that aborted review is not clean and does not increment completed audit rounds.

| Contracts code round | Fresh reviewer | Exact reviewed diff | Gate findings | Result |
| --- | --- | --- | --- | --- |
| 2 | `/root/contracts_fix_audit` | `66561e26..283c2cbb`, Contracts corrections and their interactions only | 1 | Fixed in `b89a1db6` |
| 3 | `/root/contracts_final_audit` | `283c2cbb..b89a1db6`, component-weight fix and its interactions only | 0 | CLEAN |

Round 2 independently reproduced the card displaying `Weight: 15%` while the corrected banner showed `15.25%` for `iv_rank: 0.1525`. The follow-up removes integer rounding from component weights and adds a literal rendered-card regression. Round 3 verified that backend supplies the same effective weight to both paths, and both now display `15.25%`. Both rounds excluded Step 5 entirely. Round 3 was checked against its intended scope and closes the Contracts correction audit at the three-round cap.

Contracts is `ready_to_merge`; Step 5 remains `awaiting_audit` pending an explicit cap exception. The integrated branch therefore remains unapproved for merge. Project state is authoritative for current verdicts; this document records evidence and scope.
