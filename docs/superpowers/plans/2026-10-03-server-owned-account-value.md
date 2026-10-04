# Phase B1 — server-owned account value

Goal: #7 in TRADING_REVIEW.md. Every authoritative trade/exposure/daily-budget check uses portfolio.portfolio_value in risk_rules.yaml, not values on incoming trade requests or an armed snapshot. The Settings Risk endpoint remains the supported way to change the server configuration. One absent-key default is100000, matching checked-in YAML and frontend defaults. Unusable explicit config is refused before a new order; never silently replaced by a larger default.

Scope:
- Add DEFAULT_ACCOUNT_VALUE and account_value(config=None) to portfolio_risk.py. Read cached _load_config normally, optional supplied config for settings GET. Reject bool/non-numeric/nonfinite/nonpositive explicit values with a RuntimeError-derived AccountValueError. No broker balances yet; live brokerage is disabled.
- Keep check_position_risk a pure numerical helper with its explicit portfolio_value parameter, but ALL production callers supply a resolved server value. Inspect all callsites. POST position_writer, PATCH qty-increase, AutoTradeService.fire resolve at actual check time. Remove PATCH's requirement for a client portfolioValue. Existing reductions/close pathways never require account value.
- create_position pretrade config failure maps to422 and no write. Post-broker booking with enforce_pre_trade_gates=False MUST book original quantities despite unreadable config: mark over_exposure=True and warning/WriteOutcome notice; never pretend a fallback produced a valid check. Reuse current risk-warning paths.
- AutoTradeService.fire resolves inside a try after disarm, before exposure/daily gate/broker; on failure write existing risk_check_failed history row and raise AccountValueError. If config changes after arm, use new value; explicit fire portfolio_value override and ArmedStrategy.portfolio_value are compatibility data, never authoritative.
- Align GET risk settings/defaults and deprecated schema/dataclass defaults to100000. Retain old request fields for wire compatibility but label ignored. Settings portfolioValue allows only finite positive numbers. Existing payload-validation semantics unrelated to money unchanged.
- The stock exit-plan endpoint resolves the same server account value for its risk budget/recommended shares, including the absent-key default. Unusable account config maps to a refusal instead of zero/NaN sizing.
- Both manual broker endpoints validate the server account value immediately before an OPEN dispatch, including raw API calls and config changes after portfolio-save prechecks. Account errors return422 with no execute call; CLOSE orders bypass account validation. Preserve existing idempotency cleanup. This checks configuration, not a new raw-endpoint portfolio exposure policy.
- Frontend may continue sending legacy values for compatibility; server-hydrated Risk settings still drive UI estimates. No new server credentials or invented balances.

TDD and validation:
- Spoofed huge create/patch/arm/fire values cannot enlarge caps against server10000; omitted PATCH value works; decrease works despite unusable config.
- Arm at high server value, lower configuration, then fire judges lower value. Rejected config causes no broker call and a refusal history row.
- Absent key defaults100000; NaN/inf/bool/zero/negative/unreadable config refuses pretrade. Settings GET matches server helper and Settings cannot persist nonfinite account value.
- Stock exit-plan missing-key sizing uses100000, invalid config refuses; OPEN broker stock/option calls refuse invalid account config and CLOSE still executes.
- Already-placed auto order still books without resizing when account config is invalid and surfaces warning.
- Update existing endpoint tests to set server config deliberately instead of expecting request values to control caps. Do not rewrite numeric golden fixtures or weaken assertions.
- Run relevant portfolio(create/PATCH/writer/booking), auto-trade risk tests, frontend typecheck and full suites after both Phase B changes. Fresh independent CODE audit scoped to B1, maximum three rounds, shrinking deltas.

Not in this target: durable daily ledger (#9), account balance broker integration, changes to loss/position fractions, or retuning. Daily-ledger gets its own plan/audit stage.

Plan round1: fresh account_plan_audit1 found2 gate findings: stock exit-plan retained a zero fallback; manual OPEN dispatch could still proceed under invalid account config. Both consumers and tests added above. Next review is the fix delta and interactions only.
