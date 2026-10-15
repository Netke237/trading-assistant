# Legacy and related scan report presentation

Target: `LEGACY-SCAN-REPORT-LAYOUT`.
Base: `9abffcb1ec4f98922d87e8127362b23a7ab01718`.
Branch: `fix/legacy-scan-report-layout`.
Status: built, independently audited, unmerged at record time.
Code rounds: 2 of maximum 3. `audit_clean: true`.

## Scope and behavior

The first compact-report fix left expanded legacy records as JSON-only views.
This follow-up gives each legacy record saved metadata and a candidate-symbol
table, keeping the original category unclassified. Incomplete candidate lists
have unavailable totals, not a fabricated zero; safe partial rows remain visible.

The related-path check also found JSON-only saved exclusions and unsaved-run
details, raw inputs retaining open state between saved runs, and drawer focus
wrapping into hidden legacy controls. Those paths now have readable summaries,
run-specific disclosure state and visible-control focus wrapping. Every report
JSON disclosure is explicitly labelled Raw and starts collapsed. Complete raw
evidence remains accessible, with bounded scrolling. No persistence or broker
payload changes.

## Independent audits

Each reviewer was a fresh subagent applying
`.claude/skills/bmad-review-adversarial-general/SKILL.md` and the numeric /
persistence gate. The brief additionally requested functional UI findings in
the user's explicitly requested same-class display-error scope.

Round 1 reviewer: `/root/legacy_report_audit_r1`.
Full nine-file application/test diff against the base above:
SHA-256 `901dfe8a889f1d2d79be5b3b637cb318cb07d5faabbd5cc0c8ab5d92bd284c55`.

One gate finding: `get_legacy/project` can omit unsupported candidate elements,
returning a shorter or empty candidates array with direct unavailable paths.
Ignoring those paths understated the total or displayed a false zero. The
reviewer reproduced the backend envelope with Python 3.11.16. No additional
functional UI findings after rechecking all five category mappings, legacy
provenance, raw disclosures, exclusions, unsaved summaries and drawer behavior.
Independent focused check: 3 suites / 39 tests passed.

Fix: honor direct result/candidate unavailable paths and candidate-unavailable
markers, show unavailable cardinality, suppress the false empty assertion, and
retain valid partial rows. Nested field omissions preserve a known record count.

Round 2 reviewer: `/root/legacy_report_audit_r2`.
Scope: only the round 1 fix and interactions in `LegacyReport.tsx` and
`__tests__/LegacyReport.test.tsx`, including the test enumeration correction.
Final full component diff SHA-256:
`8dc86c3a42a2b0c14f318496f1edd605622e944498743b84f0b3fd4285004b4d`.

Zero findings after recheck. Reviewer confirmed exact snapshot/live-file parity
and traced backend completeness envelopes; an additional 11-case boundary probe
passed. The implementing agent verified the final diff hash matches the reviewed
snapshot. One finding fixed; none deferred or outstanding.

## Verification

- Focused results-table, saved-report, legacy and terminal-outcomes tests:
  4 suites / 51 tests passed. Includes all five categories in page and drawer
  views, malformed/omitted legacy candidates, original JSON preservation,
  unavailable versus measured zero, report switching, exclusions, unsaved
  counts and collapsed-section keyboard navigation.
- Final production build and its typecheck passed (existing lint warnings).
- Chromium exercised the final production build with isolated API fixtures:
  51 cases. The five categories plus expanded legacy records were checked in
  page and drawer views at 1440 and 1920 pixels, in light and dark themes.
  Additional cases covered an unsaved scan dispatched through the real client
  API code and wholly/partially omitted legacy candidate lists.
- No browser runtime errors or report/page horizontal overflow. Opening normal
  report sections exposed no JSON. Explicit raw disclosures were bounded to
  320 px and parsed back to the exact fixture payload. Drawer keyboard wrapping
  skipped controls inside collapsed legacy records.
- Fixtures were used; this did not access the user's Windows localhost or
  establish that unrelated application features contain no errors.

This audit record is bookkeeping added after the frozen component diff.
