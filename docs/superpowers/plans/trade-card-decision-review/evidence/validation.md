# Pinned-source inventory validation — 2026-11-07

Source inventory is complete against the user-authorized current-main baseline `c8f3b8a2cb5f0fa7e74fc0da407d1716a381fc6b`. Mini-PC URL/revision remain unknown; comparison is **user-deferred, not verified, not an implementation blocker**. No running-build equivalence, per-field runtime completion or independent implementation audit is claimed. This ticket changes documentation/evidence only, so no artificial red behavioral test was added.

| Check | Result / scope |
|---|---|
| `npm run typecheck` from `frontend/` | Passed (`tsc --noEmit`) before the inventory commit |
| `node --check docs/superpowers/plans/trade-card-decision-review/capture-local-baseline.cjs` | Passed; harness unchanged |
| `python3 docs/superpowers/plans/trade-card-decision-review/validate-evidence.py` | Passed: 520 individually source-inspected historical contracts, 67 current-region/new-field supplements, 38 shared render/helper contracts, 61 immutable source-file hashes, exact contract/caller excerpts, four original PNG/body hashes, original 15 and portable 16 named checks |
| Source snapshot validation | Reads `git show c8f3b8a2cb5f0fa7e74fc0da407d1716a381fc6b:<path>`; later application edits do not invalidate baseline evidence. It validates immutable evidence integrity, not current implementation behavior. |
| `git diff --check` and staged whitespace check | Passed before commit |
| Source inventory contract attributes | Every historical entry has source binding, formatter, mutability, units, time basis, conditional state, source evidence, proposed destination and explicit pending #584 preservation/retest obligation; no null/open source-contract attributes |
| Historical region continuity | Earlier 60 exact-region  / 460 changed-region observations retained as provenance only; individual source verification is the new curated contract, not generic region matching |
| Captures / browser checks | Existing four initial/calculated/stale/restored captures and15 original/16 portable named checks retained unchanged; no rerun needed because baseline application SHA and harness are unchanged |
| Full Jest/backend suites | Not run for documentation-only inventory. Required integrated behavior coverage remains #584. |
| Mini-PC running-build comparison | Not run; user-deferred, not verified, not a dependent-implementation blocker |

The original captures are representative 1440×1100 dark scrolled viewports, previously visually inspected. Body text only had trailing line whitespace stripped and a final newline ensured; original/normalized hashes remain in the manifest. The portable harness was separately run during earlier hardening: 16 named checks, no page errors, no blocked unexpected writes and four permitted mocked calculation POSTs. Those are historical run results retained as evidence, not a new run or 520 distinct runtime assertions. Tracking was opened and cancelled; no order, arm, fire or position-create request occurred.

The earlier partial inventory's blocked status and source-only 33 supplements / 35 hashes described that earlier milestone. The user subsequently authorized the immutable main baseline and deferred the mini-PC comparison. Historical audit/plan records remain historical; current README, register and manifests now reflect that decision consistently. The previous coordinator 1920px-dark Chromium smoke result remains supporting provenance, not additional coverage claimed by this implementer.

The current register records unresolved source-copy differences: immediate stop-cost is implemented as unchanged-DTE Black-Scholes, unlike stale delta-linear/capped prose; race stop repricing uses the resolved standalone any-stop-touch horizon, distinct from per-target first-event medians; raw bar shares and allocated label/edge weights are currently different. Later presentation tickets must reconcile their copy/presentation without changing the three pricing bases or inventing runtime proof. Obsolete fixed-row placeholders and warning labels are also recorded explicitly.

All final source-to-destination preservation checks, behavioral regression tests, both-theme/width captures and the independent phase audit remain pending #584. This implementer did not close issues, push, change application code or edit PROJECT_STATE/audit/plan files. The coordinator owns dependency progression and independent audit records.
