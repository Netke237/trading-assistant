# Server-owned account value audit

Target: B1 of TRADING-REVIEW-PHASE-B, based on main 93cd14130c313a87835957c10f49c509c9a2aaa6. Scope: server account denominator, invalid-config refusals, post-broker booking, stock exit sizing and manual OPEN boundary. Durable daily reservations are separate B2.

PLAN round 1: account_plan_audit1 found two gate issues: stock exit sizing kept its zero fallback; raw manual OPEN bypassed invalid account configuration. Added both boundaries to the plan.

PLAN round 2: account_plan_audit2 reviewed the fixes and interactions, zero gate findings. Plan stage clean.

CODE round 1: account_code_audit1 found two gate issues. Manual OPEN validated before worker queuing; unusable configuration arriving while queued still allowed dispatch. Settings GET converted missing/empty documents into an invented $100000 account. Both fixed: worker checks immediately before execute; GET reads preserve failures and unusable documents. Six reproductions failed before and passed after. Reviewer independently ran 118 tests. Reviewed backend diff SHA256 8d8f17c64cdde1c0ef305d1463f32f1a0d37374f79691fdecf54684bc5b36727 and account test SHA256 9cd22d3f3c3593f500da4faa9b8bf9d7f804a6d1c88a0c02bcf092723f0eef5c.

CODE round 2: account_code_audit2 reviewed only the prior fixes and interactions: zero gate findings, 28 account tests passed independently. Verified reviewed blobs: broker.py 5658f0001ca5c1f57fea24085eb047ad385eab06; risk_settings.py ff93e690e61e4682f55303181e73be20cc532df9; portfolio_risk.py b03e346b3594b5fcd59a88cdbe088cc5d5534c8c; test_account_value.py 27fd1f7d32743326e59f5f66c3462950ae02eaa9. B2 excluded. Plan: two rounds, two findings fixed, clean. Code: two rounds, two findings fixed, clean. No outstanding findings.

Validation before round 1: 407 focused tests passed. Fix validation: 45 passed. Frontend typecheck passed. Full backend suite still running; branch does not yet include the separately merged shortlist prefix fix.

Broad validation completed from repository root: 4726 passed, 1 skipped, 12 failed. Two failures were inherited cwd-dependent config probes and one was the pre-integration shortlist prefix. Rechecked all three from backend after main integration: 74 passed. The remaining nine failures were tests relying on client account values or requiring omitted client values; configured intended server account values and replaced missing-client refusal with invalid-server refusal. Numeric assertions preserved. All five affected modules: 85 passed. These are test fixture changes only; B1 production code did not change after clean review. Final whole-suite validation follows B2 integration.
