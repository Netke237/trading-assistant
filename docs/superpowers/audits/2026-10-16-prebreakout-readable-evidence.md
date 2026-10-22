# Pre-Breakout readable evidence

Target: `PREBREAKOUT-READABLE-EVIDENCE`.
Base: `27fe5182a90ae1b40bee53bdf01484b92dab136c`.
Branch: `fix/prebreakout-readable-evidence`.
Status: built, independently audited, unmerged at record time.
Code rounds: 2 of maximum 3. `audit_clean: true`.

## Scope

Pre-Breakout, Fibonacci Pullback and Pullback to EMA shared setup evidence
rendered nested objects as JSON in ordinary disclosures. Nested records and
arrays now render labeled, recursively expandable fields. Zero, false, null
and absent values remain distinct. Complete returned records stay available
under explicit, collapsed Raw data disclosures. Raw JSON uses a bounded,
scrollable viewport, shared with supplementary selected-stock context.

Changing evidence closes its raw disclosure. Ordinary same-source rerenders
preserve the user's open state. Existing displayed formulas, scoring numbers,
requests, persistence and broker payloads are unchanged. This is a presentation
fix, not the whole-app or end-to-end setup audit requested separately.

## Independent audit

Both fresh reviewers applied the required adversarial skill, numeric/persistence
gate and the user's additional functional/presentation scope.

Round 1: `/root/prebreakout_evidence_audit_r1` reviewed the full seven-file
application/test diff against the base; SHA-256
`7e21586e58988f871f0d265a62aaf11e0b2be8dc358f21760e118f7071220307`.
Zero numeric/persistence findings. One functional finding: inline projected
supplementary evidence had a new object reference on unchanged-source rerenders,
so the new Raw disclosure effect closed an already open disclosure unnecessarily.
The reviewer independently reproduced the behavior and passed 33 focused tests.

Fix: memoize the projected evidence by its actual source identities and
qualification; add a regression proving unchanged source stays open and new
source closes with the exact new recorded data.

Round 2: `/root/prebreakout_evidence_audit_r2` reviewed that fix and its
interactions. Final full frontend diff SHA-256
`89ccb6b1e0b8d0359622abd6256a77215a057947767d7deb6815101d8b66d3e4`.
Zero numeric/persistence or functional UI findings after recheck. Independent
verification: two suites / 28 tests passed. Implementer verified frozen/live
diff identity. One finding fixed; none deferred or outstanding in this scope.

## Verification

- TypeScript check passed.
- All ten Pre-Breakout page suites passed: 84 tests.
- Production build passed (existing unrelated lint warnings).
- Production Chromium fixtures cover all three sub-modes at 1440 and 1920px,
  light and dark themes: 12 cases. They expand ordinary nested evidence,
  verify no visible JSON/object coercion, open Raw via keyboard, compare exact
  returned JSON, verify 320px scrolling and no page overflow, and verify same-
  symbol reruns close Raw while retaining ordinary setup evidence.
- Unit coverage includes missing legacy evidence, empty arrays, nested zero /
  false / null, source replacement and stable source rerenders.
- Browser verification uses isolated intercepted API fixtures; it does not
  establish live provider, broker, or Windows-local behavior.

## Broader audit programme

The user separately requested parallel whole-app audit tickets. Programme #348
contains independent phases #349–#358 and integration #359, with native
sub-issues and integration blockers. Plan review round 1 found two coverage
gaps (computed market regime and setup-origin original/fresh chart backtests);
round 2 verified both ownership fixes clean. See the programme issue for exact
reviewer/hash records and estimates. Those audits have not run. This fix does
not satisfy #353's end-to-end setup verification criteria.
