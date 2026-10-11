# 33: Reconcile non-finite numeric API inputs

**What to build:** Identify API inputs that can produce wrong displayed or broker values.

**Blocked by:** Current schema and existing numeric audit inventory.

**Status:** approved for agent work by Kenneth 2026-10-09; not started. Applicable plan/design gates still apply.

**Owner category:** agent discovery.

- [ ] Use bounded mocked requests to distinguish already-rejected values from reachable unsafe ones.
- [ ] Define consistent validation outcomes and independently audit a concrete plan before code.
