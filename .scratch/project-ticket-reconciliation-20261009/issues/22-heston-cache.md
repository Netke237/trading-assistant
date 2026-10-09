# 22: Plan isolation of Heston cached results

**What to build:** Prevent a consumer mutation from changing another consumer's pricing inputs or result.

**Blocked by:** Check current cache users and existing pricing audits.

**Status:** draft — awaiting breakdown approval and applicable plan/design gates

**Owner category:** agent design.

- [ ] Reproduce shared-mutation behaviour and trace numerical consequences.
- [ ] Specify cache ownership and independent numeric regression evidence before implementation.
