# 02: Coherent prefix backfill

**Parent:** #113

**Blocked by:** 01

**Status:** pending

**What to build:** Older bars and current bars are validated and committed atomically with floor/seam metadata.

- [ ] Adjusted overlap catches equal raw closes with mismatched adjustment factors.
- [ ] Partial/error/mismatch writes preserve prior bars and proof; successful observed floors suppress only safe redundant prefix probes.
