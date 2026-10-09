# 24: Plan bounded deep-YAML handling

**What to build:** Handle pathological alias/depth input without crashing or partially persisting configuration.

**Blocked by:** Existing configuration integrity contracts.

**Status:** draft — awaiting breakdown approval and applicable plan/design gates

**Owner category:** agent design.

- [ ] Reproduce reachable recursion failure with bounded fixtures and identify safe rejection semantics.
- [ ] Preserve atomic persistence and schema behaviour; exclude the already-fixed isdigit/isdecimal task.
