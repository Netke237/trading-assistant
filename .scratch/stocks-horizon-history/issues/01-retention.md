# 01: Retention contract

**Parent:** #113

**Blocked by:** D1 #112 clean

**Status:** implemented and verified; awaiting phase code audit

**What to build:** Nightly and manual ingestion preserve the configured OHLCV horizon; effective years are visible.

- [ ] Default 17, validated 1..20, and shorter requests cannot prune below configured retention.
- [ ] Legacy timezone-only saves preserve retention and unrelated keys.

**GitHub issue:** #124

Verification: 32 retention/API/scheduler tests passed in network-disabled Python 3.11 container; frontend typecheck clean.
