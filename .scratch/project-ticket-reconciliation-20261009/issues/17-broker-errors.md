# 17: Plan truthful post-submit broker error handling

**What to build:** Distinguish refused, uncertain and completed submissions without encouraging duplicate orders.

**Blocked by:** Coordinate with FIRE and active broker-path owners.

**Status:** draft — awaiting breakdown approval and applicable plan/design gates

**Owner category:** agent design.

- [ ] Reproduce parse/transport/error-classification cases and orphan approval logging with mocks.
- [ ] Specify truthful outcome messaging and reconciliation without automatic retry; independently audit the plan.
