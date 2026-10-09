# 01: Retention contract

**Parent:** #113

**Blocked by:** D1 #112 clean

**Status:** done; independent code round 3 clean, PR #130 unmerged

**What to build:** Nightly and manual ingestion preserve the configured OHLCV horizon; effective years are visible.

- [x] Default 17, validated 1..20, and shorter requests cannot prune below configured retention.
- [x] Legacy timezone-only saves preserve retention and unrelated keys.

**GitHub issue:** #124

Verification: 32 retention/API/scheduler tests passed in network-disabled Python 3.11 container; frontend typecheck clean.

Final audit: code rounds 1/2 found one defect each, fixed; fresh round 3 zero gate findings. Exact scopes and verification: docs/superpowers/audits/2026-10-09-stocks-horizon-history-code.md. Merge approval remains outstanding; no D3 execution.
