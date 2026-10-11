# OPTIONS-UNDERLYING-FLOOR-45

User requested the options contract-selection underlying-score floor change
from 55 to 45, preserving the stock scanner's PASS threshold.

## Code round 1 of 3 — clean

Fresh independent reviewer: `/root/options_floor_audit_r1`, applying
`.claude/skills/bmad-review-adversarial-general/SKILL.md`, briefed on the
PROJECT_STATE numeric/persistence gate and bounded mechanism-comment exception.

Reviewed the complete four-file implementation diff against
`6ebb14bd4eb21d9376978e1a1220a4072e5360ef`:

- `backend/config/contract_rules.yaml`
- `backend/app/scoring/contract_validator.py`
- `backend/tests/test_contract_validator.py`
- `backend/tests/test_reproducibility.py`

Reviewer's exact diff SHA256:
`1b884ffa563905fa19b682031b8c650a3ae170250b9d7f101e83dcc3206bdd81`.

Reviewed file Git blob hashes, in the order above:

```
6c25c93e30db11bacae4f1ad771d0275aaf9e22a
a00d87a496e729f89893b1fce62db52ef7a2d587
dfd67c5da783b510abfa283f7029c1278dc431cf
03cbcca131d69481c4fbbdff75320c6d99eb2d2f
```

Scope verified from the reviewer's actual validator, options selection,
scheduled core, stock threshold and auto-trader trigger traces. Zero gate
findings after recheck; no gate fixes or outstanding findings. The reviewer
caught a test-only config-key error during the round; it was corrected to
`stock_score_thresholds` and included in the final reviewed diff above.

The validator rejects underlying scores below 45; 45 is inclusive. Scheduled
options scans use the same core and strip obsolete stocks-only overrides.
Stock PASS remains 55 and CAUTION remains 35. Scores 45–54 remain CAUTION;
the automatic scan trigger still requires at least one PASS candidate.
Scheduled scans do not auto-fire. This broadens contract selection available
for arming and preserves independent auto-trader safety gates.

## Validation

Frontend `npm run typecheck`: passed. Backend focused tests run using the
repository's prepared Python 3.11.9 environment: 60 passed in 17.28s across
`test_contract_validator.py`, `test_reproducibility.py`, `test_scan_schedule.py`.
System Python test attempts failed in setup on missing timezone data
and pandas; no application behavior was exercised by those attempts.

The validator caches YAML configuration, so a running backend needs a restart
to adopt the new default. Explicit contract-floor overrides keep precedence.
