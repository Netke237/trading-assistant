# 02: Coherent prefix backfill

**Parent:** #113

**Blocked by:** 01

**Status:** done; independent code round 3 clean, PR #130 unmerged

**What to build:** Older bars and current bars are validated and committed atomically with floor/seam metadata.

- [x] Adjusted overlap catches equal raw closes with mismatched adjustment factors.
- [x] Partial/error/mismatch writes preserve prior bars and proof; successful observed floors suppress only safe redundant prefix probes.

- [x] Require actual complete adjusted counterparts; strict mode rejects an incomplete symbol and permits whole-window fallback.
- [x] Successful older-bar updates evict stock backtests as well as confidence, with the existing in-flight generation guard.

**GitHub issue:** #125

Final audit: code rounds 1/2 found one defect each, fixed; fresh round 3 zero gate findings. Exact scopes and verification: docs/superpowers/audits/2026-10-09-stocks-horizon-history-code.md. Merge approval remains outstanding; no D3 execution.
