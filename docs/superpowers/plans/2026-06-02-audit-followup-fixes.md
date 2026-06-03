# Audit Follow-up Fixes

Small correctness fixes found in the 2026-06-02 code audit. S1 (secrets) is
resolved — the Telegram token was rotated and `settings.yaml` is gitignored.

## Fixes

### C1 — EVENT_RISK missing from the notifier's default enabled-types (medium)
`alert_notifier._DEFAULT_ENABLED_TYPES` omits `EVENT_RISK`, but
`notification_settings._SUPPORTED_TYPES` and `settings.example.yaml` include it.
If `settings.yaml` ever lacks an `enabledTypes` key, the headless monitor
silently drops earnings/dividend alerts. Add `EVENT_RISK` to the default list.
- Test: config without `enabledTypes` still dispatches EVENT_RISK.

### C2 — settingsStore migrate() branches are non-cumulative (low, latent)
Each `if (version < N) return …` short-circuits, so a user on v7/v8 jumping to
v10 runs only one branch and skips later fields. Masked today by the default
merge, but contradicts the cumulative-migration convention. Extract migrate
into an exported pure `migrateSettings()` and make the branches stack.
- Test: migrating from v8 yields maxContractsPerChain, maxContractPrice, premiumStopPct.

### C4 — unrounded exit premium on early-return path (trivial)
`estimate_rr` rounds `estimated_exit_premium` on success but not on the
zero-reward / zero-risk early return. Round both.
- Test: a zero-reward case returns a 2-decimal premium.

### C3 — dead `invalidation_price` parameter (low) — DOCUMENT ONLY
`estimate_rr` no longer uses `invalidation_price` (risk = premium ×
premium_stop_pct). Full removal would break 13 tests and 3 scan call sites for
no behavior gain. Keep the param, add a comment marking it reserved.

### C5 — `_first_seen` grows unbounded (low) — NO CHANGE
Only pruned by `forget_alerts`, which the monitor already calls when positions
disappear. Bounded by open positions in practice. The only "fix" (pruning keys
whose `_fired` expired) would break reminder timestamps. Left intentionally.

## Verification
- `cd backend && pytest tests/test_alert_notifier.py tests/test_reward_risk.py`
- `cd frontend && npm run test -- --testPathPattern=settingsStore && npm run typecheck`
