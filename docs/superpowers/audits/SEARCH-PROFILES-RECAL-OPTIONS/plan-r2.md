# Adversarial Plan Audit (Round 2): SEARCH-PROFILES-RECAL-OPTIONS (#187)

**Plan Under Review:** `docs/superpowers/plans/2026-10-22-search-profiles-recal-options-plan.md`  
**Diff Reviewed:** `git diff 33c93a17..5e13a440` (Commit `5e13a440`)  
**Prior Audit:** `docs/superpowers/audits/SEARCH-PROFILES-RECAL-OPTIONS/plan-r1.md`  
**Reviewer:** Fresh independent subagent `e96c3550-f301-40f7-b360-e5f3dc1e2047`  
**Standard Applied:** `.agents/skills/bmad-review-adversarial-general/SKILL.md` under `AUDIT-RULE-V2`  
**Date:** 2026-10-22  

---

## Audit Evaluation & Scope Checks

### 1. Verification of Fix for Finding F-1 (Lines 55–56)
- **`event_reject_days` (Line 55):**
  - Baseline column specifies `21 Swing (inherited) / 7 SemiAnnual (explicit)`.
  - Restrictive and Loose columns specify `Same (Intraday/Swing) / 7 (SemiAnnual)`.
  - Evidence/Rationale explicitly explains: *"SemiAnnual hold of 90-105d crosses earnings; all 6 SemiAnnual profiles (Baseline included) explicitly override 7/30 to avoid scoring_rules.yaml Position default (30/60) which blocks viable long holds."*
- **`event_caution_days` (Line 56):**
  - Baseline column specifies `45 Swing (inherited) / 30 SemiAnnual (explicit)`.
  - Restrictive and Loose columns specify `Same (Intraday/Swing) / 30 (SemiAnnual)`.
  - Evidence/Rationale explicitly notes: *"30d caution window for SemiAnnual across all 6 profiles (Baseline, Restrictive, Loose)."*
- **Cross-check Consistency:**
  - Fully consistent with Section 2, Line 38 (`scanOverrides: {} except SemiAnnual event windows`).
  - Cross-checked against `backend/config/scoring_rules.yaml:381-382`: Position default is `reject_days: 30`, `caution_days: 60`. Swing default (lines 111–112) is `reject_days: 21`, `caution_days: 45`. The rationale correctly identifies that inheriting Position defaults would apply 30/60 rather than the intended 7/30.
  - Cross-checked against `docs/search-profiles/README.md:34-43`: Confirmed that all 6 SemiAnnual profiles explicitly carry `event_reject_days: 7` and `event_caution_days: 30`.
  - Cross-checked against `docs/search-profiles/search-profiles-export.json`: Confirmed that all 6 SemiAnnual profiles (`mu2n6wtt37o9`, `mu2n6x4w0gb9`, `mu2n6xcbasfh`, `mu2n6xjqcewd`, `mu2n6xtffvnn`, `mu2n6y1r5fyf`) carry `scanOverrides: {"event_reject_days": 7, "event_caution_days": 30}`, whereas Intraday and Swing Baseline profiles carry `{}`.

### 2. Citation Correction in Line 49
- **`max_bid_ask_spread_pct` (Line 49):**
  - The evidence citation was corrected from *"MEAS Day 1 & 2 C6 liquidity observations"* to *"Design judgement (commit `ab705ea7` / 2026-09-29): 0.08 enforces tight institutional quotes; 0.30 accommodates wider retail spreads."*
  - Cross-checked against git history: Commit `ab705ea7` (PR #213 / branch `claude/options-scan-liquidity-profiles`, merged 2026-09-29) introduced these liquidity thresholds and documentation. They represent design judgements rather than empirical measurements from MEAS Days 1 & 2 (which eliminated liquidity floors). This citation correction prevents an implementer from searching MEAS Day 1 & 2 reports for non-existent empirical spread measurements.

### 3. Interactions & Newly Introduced Contradictions
- Verified the entire plan document for any unintended interactions:
  - All 18 profile IDs remain intact and referenced accurately.
  - The parameter table is completely aligned internally across tiers and horizons.
  - Task 1 (Mini PC script `run_options_profiles_measurement.py`), Task 2 (export sync to Schema Version 5), and Task 3 (test suites) remain compatible and uncompromised.
  - No new ambiguities, contradictory mechanism statements, or reachable failure paths have been introduced.

---

## Gate Assessment

The audit gate states:
> A finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA. A comment counts only if a competent reader acting on it would write a wrong change (it misstates mechanism).

All changes in commit `5e13a440` accurately reflect the domain models, configuration defaults, and existing export artifacts. A competent reader implementing this plan will produce the correct parameter configurations across all 18 profiles without regression or misconfiguration.

GATE FINDINGS: 0
