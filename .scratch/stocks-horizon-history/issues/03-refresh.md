# 03: Adjustment refresh and evidence

**Parent:** #113

**Blocked by:** 02

**Status:** done; independent code round 3 clean, PR #130 unmerged

**What to build:** Post-action adjustment refresh rewrites older dates and only exact verified seams avoid false stale flags.

- [x] Old segment is refreshed with current adjustments; missing dates fail without partial commits.
- [x] Jump, action-age, NULL factor and unrecorded source mixtures still flag; full-span evidence stays SELECT-only.

**GitHub issue:** #126

Final audit: code rounds 1/2 found one defect each, fixed; fresh round 3 zero gate findings. Exact scopes and verification: docs/superpowers/audits/2026-10-09-stocks-horizon-history-code.md. Merge approval remains outstanding; no D3 execution.
