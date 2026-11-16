# Setup Scanner — local acceptance

Tracking #622, build #626. Application commit `47c229a1ab85d9bdf2ffca0f2697506475039d57`, baseline `0a453f1940a077015949e760d02ef5a6d921f62a`. This record verifies local implementation/tests/preservation. Independent code review and remote CI/merge remain separate gates.

**SETUP-SCANNER-REFERENCE-ALIGNMENT-LOCAL-VERIFIED**

## Implemented behavior

All three modes retain controls/errors before selected context, sentiment above fundamentals, the existing candidates/chart grid and complete setup evidence. Qualification and news now have default-closed, always-mounted page-level disclosures. Complete existing parameter panels follow qualification. Confidence headings identify setup, historical signal and Fib proximity meanings. The original/supplementary source summary is visible; supplementary analysis explicitly does not qualify the selected Pre-Breakout/Fib setup.

No API, backend, store, persistence schema, model, scan/order request, context/news hook, chart evidence or execution behavior changed. Shared shell and the scanner's existing 1280px desktop gate are preserved; see validation-addendum.md for the corrected testing widths.

## Preservation

`node docs/superpowers/plans/setup-scanner-reference-alignment/verify-preservation.cjs` passes. Its source-bound report covers 1,153 baseline records: seven non-page modules byte-identical, the whole page controller/selection prefix byte-identical, all 21 original handler attributes present, and all 124 unique JSX text units retained. Generic confidence headings are made explicit; no numeric source expression is replaced. Full existing context/qualification/news bodies and all nested raw records remain unchanged and reachable in disclosures. This is source accounting, not an independent audit or proof of every possible server response.

## Checks

- Initial RED: all three new mode-specific reference tests failed on the missing explicit confidence headings before implementation; existing ownership/numeric assertions retained.
- Earlier focused route run: 13 suites / 102 tests passed. Its temporary log was lost during the interruption; the resumed full suite below includes those cases.
- Resumed frontend typecheck passed, including the final browser fixture/report assertions. `git diff --check` passed.
- `npm run test -- --maxWorkers=2`: **346 suites / 6,368 tests passed**, 368.951 seconds. Summary retained in evidence/jest-summary.txt. No backend changes; no local backend test run claimed.
- Final mocked browser acceptance: **28/28 passed in 1.6 minutes**. Eighteen combinations cover three modes × 1280/1366/1920px × dark/light. Nine cases cover empty results, unavailable analysis/news and late previous-symbol replies; one preserves the 1200px guard and resize behavior. Actual response delivery is awaited before stale-data absence assertions.
- Browser assertions include explicit confidence meanings and zero/absent values, context order, native closed disclosures, unchanged requests/selection on expansion, source labels, chart-line semantics, safe news link, current table/saved-report matching, parameter-change invalidation without a new scan, retained frozen report, and no page-level horizontal overflow. Scan/context/news/candles/reports are synthetic API fixtures; unexpected mutation endpoints are refused. No real scan, save, order, alert or news request is performed.
- The final fixture reproduces the backend's CORS exposed report headers and captures the mocked request snapshot; current table identity is checked before edits and becomes explicitly unbound from the retained saved report after edits. Earlier stopped/partial browser runs are not counted as final passes; validation-addendum.md records the selector/width corrections.

## Retained visual evidence

Final run generated 36 initial/expanded matrix screenshots; six representative images are retained: Pre-Breakout 1366px dark, EMA Pullback 1366px light and Fib Pullback 1920px dark, initial and expanded. Paths, mode/theme/width and hashes are in evidence/acceptance-report.json; final run log is evidence/browser-acceptance.log. Other generated screenshots remain temporary. The unchanged application shell/data source semantics explain differences from standalone illustrative reference values.

## Audit and release status

Independent plan round 1 is clean with zero gate findings (exact SHA in plan-audit-1.md). Code stage has not yet run at this local-acceptance checkpoint. No historical audit counters were reset. Phase is built/local-verified at the 70% milestone, size L / complexity 3; build ticket is locally verified at 70%, size M / complexity 3. Independent phase-wide code audit is the next gate; this record does not establish merge readiness or shipped status.

## Independent code result

Fresh reviewer `scanner_code_audit_1` audited the full integrated phase range `0a453f19..1fdecb73`, including the validation addendum, and returned zero gate findings after re-check. See code-audit-1.md. Phase is built, 85% (clean code-audit milestone), size L / complexity 3. Plan 1 / code 1 clean, continuous rounds 2; remote exact-head CI and verified merge remain outstanding.
