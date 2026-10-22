# 13: Plan Tradier-wide rate-limiter coverage

**What to build:** Route all relevant Tradier requests through a coherent shared limiter.

**Blocked by:** Existing TG-1 in NLQ map; NLQ-3 clearance.

**Status:** draft — awaiting breakdown approval and applicable plan/design gates

**Owner category:** agent design.

- [ ] Reuse TG-1 rather than create a competing implementation task; inventory all call paths.
- [ ] Specify concurrency, retry/cooldown and broker-dispatch semantics with mocked tests and an independent plan audit.
