# 26: Reproduce and isolate remaining flaky tests

**What to build:** Identify reproducible failures separately from provider/font restrictions and runtime mismatches.

**Blocked by:** Exact current-main baseline and runtime.

**Status:** approved for agent work by Kenneth 2026-10-09; not started. Applicable plan/design gates still apply.

**Owner category:** agent evidence.

- [ ] Record interpreter, working directory, failure signatures and deterministic reproductions.
- [ ] Propose narrow fixes only where supported by evidence; keep golden numeric pins and assertions intact.
