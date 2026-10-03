# ALERT-INDICATOR-SEED-PARITY split target

Scope: the one outstanding seed-arithmetic/runtime issue from the capped `ALERT-INDICATOR-ID-MAP` code stage. The user authorized this split and merge after a qualifying clean audit. Original code-stage history remains three independent rounds with no clean round; it must not be reset or described as clean.

Docker and CI explicitly use Python 3.11. The cloud setup incorrectly used Python 3.12.14, whose compensated float summation changed seed readings and the existing numerical golden checksum. The supported fix is to align this environment with Python 3.11, not to change production arithmetic to match an unintended runtime. `.python-version` now pins 3.11. Backend dependencies are installed in `.venv/cloud-python311`, using Python 3.11.16. The saved cloud install/start instructions select that interpreter explicitly and preserve the dedicated local database.

The pre-change module from main b036a368, executed under Python 3.11.16, produces the original golden SHA `44eb35e07f3080defb457e052ba76c030b5c0a30917ad7551d9dacc768486b6d`. The checksum is restored; the test still normalizes only the deliberate EMA seed-bar addition. The earlier claim that this golden was stale was incorrect: it was a runtime mismatch.

A checked-in fixture generated using the supported backend verifies exact timestamped browser/backend readings across 13 references and seven histories: empty, short, the independently reported seed and recurrence boundaries, cent decay, flat, and randomized cent prices. Both test suites consume the same fixture. The generator refuses an unintended Python runtime. A separate comparison of 100 cent-price histories matched 92,000 readings exactly under Python 3.11.16.

Initial checkpoint: focused backend97 and frontend150 passed; typecheck clean. The independent review and final integration results are recorded below. Cloud install/start drafts were saved with the corrected Python interpreter.

Original `ALERT-INDICATOR-ID-MAP` evidence remains in `2026-10-03-alert-indicator-id-map.md`; its unresolved seed finding is the sole subject of this split. Final closure must link to the independently audited split without inventing a fourth original-stage audit.


## Independent split code round 1

Fresh reviewer `seed_parity_audit_1` explicitly applied both audit skills and the project gate. Actual scope: diff against `8281668f`, runtime pin, generator, shared fixture, saved cloud install/start drafts and their interactions with production arithmetic. Zero gate findings after first-round scope recheck. Reviewer independently confirmed the EMA(8) seed is 100.0238 under Docker/CI Python 3.11, matching the browser; backend97 and frontend31 checks passed.

## Independent split code round 2

After the first review, the production build identified a prohibited require() import in the new fixture test. The import was changed to an ES JSON import; no production arithmetic changed. Fresh reviewer `seed_parity_final_import_audit` reviewed precisely this adjustment and its shared-fixture interactions. Zero gate findings; backend32, frontend31, and targeted ESLint passed.

The narrower target is independently clean after two qualifying reviews. Full merged-main frontend validation: 178 suites/4395 tests passed; typecheck and production build passed. Production `/alerts` returned HTTP200 and Python3.11 backend health/rule-list endpoints responded correctly. Full backend Python3.11 run completed:4590 passed,1 skipped,1 failed. The failure is test_stock_shortlist::test_the_frontend_prefix_matches_the_backend_constant, caused by an inherited duplicate literal in parsePipelineDiagnostics.ts. It reproduces on an untouched archive of origin/main68ac3292 (1 failed); all relevant files are identical to main. Post-integration targeted backend run:120 passed and the same inherited failure. This is outside the numeric/persistence audit gate and remains recorded as an open question; no passing full-backend claim is made. Latest-main production rebuild passed. Original capped-stage record is preserved unchanged (three rounds, not clean) in PROJECT_STATE.json's archived_round_records and resolves through this separately authorized split; no fourth original-stage round is claimed.

Final latest-main integration: frontend183 suites/4462 tests passed, typecheck and production build passed. Main code merged without conflicts; PROJECT_STATE.json structurally preserves both sessions records. The inherited prefix failure is separately claimed as SHORTLIST-PREFIX-DRIFT by another branch; it was not modified in this task. User explicitly authorized the following main merge.
