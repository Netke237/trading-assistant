# APP-AUDIT-B-VIX-WINDOW — independent plan round 1 of 3

Reviewer: fresh independent `/root/fix369_plan_r1`, applying `.claude/skills/bmad-review-adversarial-general/SKILL.md` and the repository numeric/persistence gate. GATE FINDINGS: **0**.

Exact reviewed artifact: `/workspace/fix-369/docs/superpowers/plans/2026-10-17-app-audit-b-vix-window-plan.md`, lines 1–52, SHA256 `42b4a2aa3072118bdeecf864f61a5e13242f8a7f3ddba4a346b2669fd3e98e83`.

Source baseline: worktree HEAD and origin/main both `93d5c484a38588b7f0dee13b361dc997b7e8a618`. Reviewed actual `backend/app/routers/regime.py` (helper lines 67–72; endpoint lines 122–318, especially 179–189 and 308–309), `backend/app/data/market.py:336–398`, backend schema fields 430–431, frontend domain fields 1019–1020, API getRegime mapping, and Step 1 page field reads at 179–180 and Swing/Position display paths at 386–387 and 416–417. Reviewed existing Step 1 rendering-test setup and the frozen regime calculation/output/findings evidence, plus issue snapshot `/tmp/350-fix-369-issue.json`. Router source SHA256 `67401b378945d0efb12b36c61f07f9843c25debb5a6db3c3431ac51608d25f25` matches frozen evidence.

Findings: none meeting the gate. No location/trigger/guard/consequence entries are required because no blocking defect was established.

Meaningful zero-finding recheck against actual source:

- Current endpoint requests 260 VIX bars, reads the independently fetched quote as the ranking value, and passes all prior returned closes to the 252d helper. Plan explicitly preserves quote lookup and requests while replacing only reference selection.
- `[-253:-1]` takes indices `max(0, n-253)` through `n-2`: exactly 252 prior entries at n>=253, fewer available prior entries otherwise. At n=260 it discards precisely seven old entries. Exactly 253 entries retains all 252 prior entries. The last returned bar remains excluded.
- Existing `[-31:-1]` 30d selection remains unchanged, including last-entry exclusion and short-history behavior.
- Strict `< current` comparison keeps ties out of the numerator, and helper rounding remains one decimal. No calibration, threshold, quote or alternate rank convention is introduced.
- The endpoint's quote-None guard and len>=2 guard retain None for unavailable quote, empty history and one-entry history. Plan does not accidentally expose the helper's standalone empty-history 50.0 fallback to those endpoint cases.
- Existing exception handling and available-history policy remain untouched; no new minimum-252 policy is implied.
- Task 1 requires the actual asynchronous endpoint response regression and explicit RED cause, rather than a sliced helper test claiming endpoint coverage.
- The Step 1 instruction requires a mocked UI display assertion or relevant rendering regression. Actual page consumes `vix_pct_252d`, rounds it for both Swing and Position labels, and requires non-null OMM to render those labels. This is feasible with a mocked response containing OMM and the corrected percentile; the plan does not require frontend production changes.
- Re-read the entire plan for adjacent-path changes: it limits implementation to the 252d history bound and owned regression tests. OMM/HMM, providers, status/order logic and persistence remain outside the change.

Executed independent check `/tmp/350-fix369-plan-r1-check.py`: 508 slice-boundary/actual-helper cases passed, covering lengths 0–500, ties, below/above ranges and rounding. Extracted the unchanged helper AST directly from actual router source. Frozen input independently reproduces current helper/selection 2.7, intended selection 0.0, and unchanged 30d 0.0. This is source-helper/slice validation, not full endpoint or browser execution. An attempted full-router import run was terminated after stalling; no result from it is claimed.

No repository, GitHub, implementation, audit-state, commit or push mutations were made. Only temporary audit artifacts were written under `/tmp`. The application defect is still unimplemented; this result qualifies the reviewed plan scope only.
