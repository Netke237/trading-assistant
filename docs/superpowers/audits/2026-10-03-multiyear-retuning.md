# Multi-year retuning audit

Target: exact parallel execution of the existing optimizer against captured adjusted settled history; no production algorithm or active parameter change.

PLAN round1 retune_plan_audit1 found two financial-evidence defects: live exit config could drift across workers/OOS; expectancy/Sharpe were incorrectly called net of configured costs. Captured immutable complete configuration, redirected parent/workers to snapshot, and corrected cost labels: window return/consistency adjusted, Sharpe/expectancy before configured costs; adjustment is not per-trade simulation. Reviewer independently verified60symbols753finite uniqueascendingrows each andsevenfolds.

PLAN round2 retune_plan_audit2 reviewed only fixes/interactions:zero gate findings. Reviewed plan SHA256 a1200b7872040b4982177a4e5b9ae1767c3fe368e1b9a13bd25e1f6ca8dde988 before this audit note. Plan stage clean after two rounds.

CODE and final evidence review pending. No full search or parameter adoption claimed.

CODE round1 retune_code_audit1 interrupted by usage limit without final scoped verdict. Counted, not clean. Interim finding: production catches Backtest.run failure, logs a warning and returns empty result; harness did not capture that logger in training workers or parent OOS, reporting zero diagnostic errors for failed windows. Reproduction and fix in progress. Next fresh code review is round2 of3, confined to this fix and interactions; no counter reset. Full search has not started.

CODE round2 retune_code_audit2 completed the originally declared full scope and swallowed-failure fix:zero gate findings. Independent12tests passed, including exact realAAPL training and nonemptyOOSproposal parity with two spawnedworkers and logged training/OOS failure capture, cache preservation and loggercleanup. Gitblobs: script1f9a70e839d97e5f00e0547254b6ac60afe993d1; tests6273d6bc7d15586b537de2da7bcca42f185da209. Plan two rounds (two findings fixed, clean); code two rounds (round1 interrupted/counted, one interim finding fixed; round2 complete/clean). No fourth round or reset. Harness complete. Full search and financial report are separate unfinished evidence work.

Whole retuning branch validation: 4,809 backend tests passed, one skipped, zero failed in 1,022.86 seconds while the full search ran concurrently. Frontend typecheck passed. Frontend source is unchanged from PR30's validated 183 suites/4,486 tests and production build. The full configured search remains unfinished; these software checks do not certify its eventual financial evidence.

Final evidence artifact round1 retune_evidence_audit1 applied BMad and the numeric/persistence gate: zero findings after recheck. Independently verified all25 numeric table cells; all60 input SHA hashes, 61-file tar exact set/noSPY, snapshot/source hashes; 35 nonempty fold winners/checkpoint integrity; seven date windows; grid arithmetic; aggregation, cost limitations, five ineligible proposals/three skipped grids; warning totals357718training/566OOS and zero errors. Parent process session64467 completed exit0 (tool result chunk699430); persisted completion marker completed, matching identity. This is one round for the separately planned financial artifact, not a reset of the clean harness counters. No deferred findings.

Reviewed report SHA2568453819207ad05ccc674ec9cafb2ec1ae4157adc3c9370f9c58cebc394a67392; manifest4db1645b4575933d2079f89acc6351e222441c6777b970ec688a6a333a5fb8b1; proposalscf0f0ad568f1ed2846fa04f7c83e9c3dfc7ae54f7fe9099e0efcb82e0bf1795e; snapshot3e70c704a4e7c54999ad4b8c6f8201f1cad0f4e28258650486d617db1b629a24; completion2d83a35d12ce7f6ebb0dcdb98d96e2f13cd7fa3954cf7345e33757b4656ed471; inputstar694f3f750a0fe8267860a40c839f46120db3000b9e41f0b49a59d0c94c7699ef. Run identity75d6b33219e65ff3ed67e7b6584d49e955c7caeffc52c21608c01ea0d9c673e8.

For exact reproduction, check out computation revision cf4729a5571520bb6fe050a0c7f9f72310961e95 before using the report's command, copy the committed snapshot into the fresh output directory, and match recorded Python/package versions. The manifest's source hashes pin this historical computation even after later integration. No active parameter changes.
