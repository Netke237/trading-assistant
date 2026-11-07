# Partial source evidence validation — 2026-11-07

Actual trader running URL/revision: **unknown, comparison blocked**. This is docs/evidence work only. No red behavioral test was required or invented. No independent implementation audit is claimed.

| Check | Result / scope |
|---|---|
| `npm run typecheck` from `frontend/` | Passed (`tsc --noEmit`) before commit |
| `node --check docs/superpowers/plans/trade-card-decision-review/capture-local-baseline.cjs` | Passed |
| `python3 docs/superpowers/plans/trade-card-decision-review/validate-evidence.py` | Passed: 520 historical IDs/items, open preservation states, 33 source-contract ranges/attributes, 35 current source hashes, four inspected PNG hashes/body texts, original 15 and portable 16 named checks |
| Portable harness run (command in source manifest) | Passed: 16 named checks, `errors: []`, `blockedWrites: []`; four permitted mocked calculation POSTs. Global unsafe-method guard active before fixture routes, including non-API broker paths. |
| `git diff --check` plus staged diff whitespace check | Passed |
| Historical region comparison | 60 of 520 entries retain the complete historical rendering-region snippet(s) in current source; source continuity only, no per-entry semantic/browser completion |
| Four PNG inspection | Each original initial/calculated/stale/restored PNG inspected with `view_image`; 1440×1100 dark viewport captures of relevant scrolled content |
| Full frontend Jest/backend suites | Not run for documentation-only change; no application source changed |
| Actual trader build/browser comparison | Not run: URL/revision unavailable |

The original 15-check PNG captures remain unchanged; body text only has trailing line whitespace stripped and a final newline ensured (both hashes recorded). The final portable harness was separately rerun after path and transport-guard changes; its [checks](portable-checks.json) are separate so the old captures are not presented as output of the new harness. During harness hardening, a same-origin-only calculation allowlist blocked the local API on its separate port; the final loopback-host allowlist matches the explicitly mocked paths and passed. This was harness validation, not an application defect or live API test.

The coordinator previously reported a Chromium smoke test (`trade-card-ui-followup.spec.ts`, `1920px-dark`) passing once. It is historical supporting context in the coordinator-owned provenance, not a test rerun or additional per-field coverage from this implementer.

No #576 closure, application implementation, state/audit-field modification, GitHub write or push was performed by this implementer. Running-build comparison and individual historical contracts remain open.
