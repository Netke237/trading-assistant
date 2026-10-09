# Multi-year retuning readiness

The corrected Phase A optimizer is available. No new strategy parameters or R/R floor have been adopted.

Initial raw Yahoo chart requests returned proxy403 and edge429, and the local database lacked stored daily history. Those requests did not establish whether the supported application fallback worked. The repository yfinance fallback succeeded after assigning a writable cache: SPY753 adjusted daily bars,2023-10-03 through2026-10-02. Verified XDG_CACHE_HOME=/workspace/.cache with a second five-bar fetch; saved that setting in reusable install/start instructions. The environment draft also preserves the earlier additive Yahoo and font domains. Saving it does not publish the environment or change runtime policy.

Captured the full configured60-symbol basket:753 adjusted settled bars each,45,180 rows with identical date bounds. BRK.B maps to the provider's BRK-B alias. Local immutable archive: /workspace/retuning/2026-10-03. Independent plan reviewer verified unique ascending finite rows and seven complete12/3month folds. Full execution plan: docs/superpowers/plans/2026-10-03-multiyear-retuning-plan.md. Data access is no longer a blocker.

A 24-combination MA benchmark on SPY took38.68seconds for seven folds; the full configured grid/basket can take several hours. The benchmark was ineligible (three average OOS trades and28.57%positivefolds). This is a runtime/data check, not the completed basket tune.

Final evidence must preserve input hashes and configuration snapshots, explicit unsupported strategies, proposal eligibility, and cost assumptions. Production expectancy/Sharpe are before configured costs; only window return/consistency receive the configured return adjustment. Eligibility alone is not proof of profitability. min_signal_rr remains0.0 and no parameters are adopted automatically.
