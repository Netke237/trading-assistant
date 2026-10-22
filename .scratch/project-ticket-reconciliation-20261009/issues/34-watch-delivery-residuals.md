# 34: Reconcile per-channel watch delivery and stuck-alert policy

**What to build:** Separate missing delivery checks from an unresolved repeated-stuck-alert policy.

**Blocked by:** Existing completed resend phases and live-owner check.

**Status:** draft — awaiting breakdown approval and applicable plan/design gates

**Owner category:** agent discovery / Kenneth decision.

- [ ] Preserve shipped per-channel/expiry behaviour and reproduce remaining cases.
- [ ] Present only the unresolved policy choice, then write independently audited implementation slices.
