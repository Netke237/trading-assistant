# Multi-year retuning audit

Target: exact parallel execution of the existing optimizer against captured adjusted settled history; no production algorithm or active parameter change.

PLAN round1 retune_plan_audit1 found two financial-evidence defects: live exit config could drift across workers/OOS; expectancy/Sharpe were incorrectly called net of configured costs. Captured immutable complete configuration, redirected parent/workers to snapshot, and corrected cost labels: window return/consistency adjusted, Sharpe/expectancy before configured costs; adjustment is not per-trade simulation. Reviewer independently verified60symbols753finite uniqueascendingrows each andsevenfolds.

PLAN round2 retune_plan_audit2 reviewed only fixes/interactions:zero gate findings. Reviewed plan SHA256 a1200b7872040b4982177a4e5b9ae1767c3fe368e1b9a13bd25e1f6ca8dde988 before this audit note. Plan stage clean after two rounds.

CODE and final evidence review pending. No full search or parameter adoption claimed.

CODE round1 retune_code_audit1 interrupted by usage limit without final scoped verdict. Counted, not clean. Interim finding: production catches Backtest.run failure, logs a warning and returns empty result; harness did not capture that logger in training workers or parent OOS, reporting zero diagnostic errors for failed windows. Reproduction and fix in progress. Next fresh code review is round2 of3, confined to this fix and interactions; no counter reset. Full search has not started.

CODE round2 retune_code_audit2 completed the originally declared full scope and swallowed-failure fix:zero gate findings. Independent12tests passed, including exact realAAPL training and nonemptyOOSproposal parity with two spawnedworkers and logged training/OOS failure capture, cache preservation and loggercleanup. Gitblobs: script1f9a70e839d97e5f00e0547254b6ac60afe993d1; tests6273d6bc7d15586b537de2da7bcca42f185da209. Plan two rounds (two findings fixed, clean); code two rounds (round1 interrupted/counted, one interim finding fixed; round2 complete/clean). No fourth round or reset. Harness complete. Full search and financial report are separate unfinished evidence work.
