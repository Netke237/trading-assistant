# Plan Audit Round 1: SEARCH-PROFILES-RECAL-OPTIONS (#187)

**Plan Under Review:** `docs/superpowers/plans/2026-10-22-search-profiles-recal-options-plan.md`  
**Reviewer:** Fresh independent subagent `bfea578d-7245-454d-8caf-081078f99078`  
**Standard Applied:** `.agents/skills/bmad-review-adversarial-general/SKILL.md` under `AUDIT-RULE-V2`  
**Date:** 2026-10-22  

---

### Gate Findings

#### Finding F-1: Parameter Matrix Table Contradicts Baseline SemiAnnual Event Window and Misstates Position Event Default
- **Location:** `docs/superpowers/plans/2026-10-22-search-profiles-recal-options-plan.md:55-56`
- **Trigger Condition:** The Parameter Evidence Table under Section 2 lists the `Baseline` column for `event_reject_days` as `21 Swing / 45 SemiAnnual (inherited)` and `event_caution_days` as `45 Swing / 60 SemiAnnual (inherited)`.
- **Concrete Failing Scenario:**  
  1. An implementer following the Section 2 table calibrates `SemiAnnual_Baseline_Bullish` (`mu2n6wtt37o9`) and `SemiAnnual_Baseline_Bearish` (`mu2n6xjqcewd`) with `scanOverrides: {}`, believing that Baseline profiles inherit backend defaults for SemiAnnual.  
  2. In reality, as specified in `docs/search-profiles/README.md:34-43`, `docs/search-profiles/README.md:119-121`, line 38 of this plan itself, and the committed `search-profiles-export.json`, all 6 SemiAnnual profiles (Baseline included) explicitly set `event_reject_days: 7` and `event_caution_days: 30`.  
  3. Furthermore, the Position default in `backend/config/scoring_rules.yaml:381-382` is `reject_days: 30` and `caution_days: 60` (not 45 days).  
  4. If an implementer clears the event overrides from `SemiAnnual_Baseline` profiles to match the table's `(inherited)` declaration, a scan executed with `SemiAnnual_Baseline` will fall back to `scoring_rules.yaml`'s 30-day reject window. For a 90–105 day holding period, any candidate with earnings within 30 days is marked REJECT on the event rule (0 points on a 20% weighted component). This severely depresses candidate scores below `min_stock_score: 45` or flags them REJECT, dropping viable long-cycle candidates and displaying wrong scores and wrong candidate rankings to the user.
- **Why it meets the Gate:** A competent implementer acting on the table would write a wrong change (stripping the 7/30 event override from Baseline SemiAnnual profiles), resulting in wrong candidate scores and corrupted scan results in front of the user.
- **Suggested Fix:**  
  Update lines 55–56 in the Section 2 table:
  - `event_reject_days`: Baseline column should read `21 Swing (inherited) / 7 SemiAnnual (explicit)`. (Note in Rationale that the Position default is 30, not 45).
  - `event_caution_days`: Baseline column should read `45 Swing (inherited) / 30 SemiAnnual (explicit)`.
  - Harmonize the table with line 38 (`scanOverrides: {} except SemiAnnual event windows: 7/30`).
  - Correct the evidence vs judgement citation in line 49: spread ceilings 0.08 (Restrictive) and 0.30 (Loose) plus SemiAnnual volume 50 were design judgements from `ab705ea7` / 2026-09-29 baseline run.

---

### Non-Gate Clarifications / Observations
- **Evidence vs Judgement:** Clarified that spread ceilings (0.08 / 0.30) and SemiAnnual volume (50) are design judgements originating in `ab705ea7` and the 2026-09-29 baseline run, not MEAS Day 1 & 2 C6 (which removed liquidity floors entirely).
- **Harness Path Resolution:** Script `run_options_profiles_measurement.py` should resolve paths relative to `Path(__file__).resolve().parents[2]` (repo root) rather than current working directory, and `--live` should support connecting via HTTP or direct FastAPI TestClient.

---

### GATE FINDINGS: 1
