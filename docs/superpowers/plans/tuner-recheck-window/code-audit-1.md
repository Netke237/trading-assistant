# Independent code audit: continuous round 4 (code round 1)

**Phase:** TUNER-RECHECK-WINDOW (#638), code stage round 1 of 3. The plan stage closed clean at round 3.

**Reviewer:** `tuner_code_audit_1`, a fresh `gate-auditor` subagent. It had no implementation context and is not the coordinator or an implementer. It applied `.claude/skills/bmad-review-adversarial-general/SKILL.md` against the gate: a wrong number in front of a user or on a broker order, or corrupted persisted data. The audit ran on 2026-11-16.

**Exact reviewed diff:** `git diff 45c95660..b5e4c385`, which is the phase's net change against the merged `origin/main`. The reviewer confirmed the worktree HEAD was `b5e4c3857e4e`. The plan checked against is `docs/superpowers/plans/2026-11-12-tuner-recheck-window-plan.md`, including both amendments. The round covered the whole target and nothing in the repo or on GitHub was edited.

**GATE FINDINGS: 0.** Below is what the reviewer checked.

## Re-check parity (`signals.py`, `report.py`)

- **Default behaviour is unchanged.** With no window, the generator uses `lo,hi = 0,len(bars)`, which is the same loop as before. The trailing slice, `n=t+1`, the float conversions, effective params and direction normalization are all kept. Setup strategies still go through the unchanged `setup_series`.
- **The scoped window covers exactly the bars the simulator reads.** `simulate_trades` reads `signals[i]` only when `entry_start <= dates[i] < entry_end` (`simulate.py:212`, with sorted dates enforced). `simulate_window` slices the full-index series, so the indices read are exactly the window `report.py` builds with `bisect_left` on each symbol's own `bar_dates`.
- **Warm-up and event guards cannot cause a difference.** The relative warm-up check only skips bars at or after the absolute warm-up. `event_allowed` and `setup_age` apply only to `market` signals, which only setup strategies produce, and those stay on full series.
- **Final parameters and protected files are unchanged.** Final-parameter fire counts and the held-out year still use full series. Gate mask, `_LEAD_BARS`, hold days and commissions are untouched. `simulate.py`, `walk_forward_cell.py`, `setup_entries.py` and `strategy_engine.py` are not in the diff.
- **Dedup and the pool path.** Requests are deduped only on exact `(params, window)` and are never widened. The pool prewarm runs the same plan into the disk cache, and the parent then reads it in sorted symbol order, so trade accumulation order is unchanged.

## Cache (`cache.py`)

- **The scoped key covers the full identity.** It hashes the full `signal_key` (symbol, strategy, direction, effective params, OHLCV hash, basis and signal sources) together with the normalized `lo` and `hi`.
- **Scoped entries are kept separate.** They live in their own `signal_windows/` folder, and setup strategies always take the full path.
- **A bad scoped entry is caught.** If a cached scoped payload has a signal outside its window, the code raises `ValueError` and recomputes it.

## Export (`export_tuning_bars.py`)

- **No database writes.**
  - Reads happen in one transaction: read-only REPEATABLE READ on PostgreSQL, an explicit BEGIN on SQLite, and any other database is refused.
  - That transaction is always rolled back.
  - The confidence-cache import is isolated.
- **No overwrite or partial publish.**
  - An existing destination is refused.
  - Symbol filenames are validated.
  - Files are staged in a fresh sibling folder, written with exclusive-create and fsync.
  - Publishing uses a no-replace rename: `os.rename` on Windows, `renameat2` NOREPLACE on Linux, and other platforms are refused.
  - Cleanup removes only the validated staging folder.
- **Tampered bars invalidate resume.** `run_identity` includes `data_hash`, which covers every symbol's `ohlcv_hash`, the benchmarks, sample, universes and sectors. If anything changes, the run key changes and the affected cells are recomputed.

## Projections and run-book

- **Projections cannot affect tuning.** The projection code calls the signal and simulation functions directly, never writes the cache, and passes nothing to `tune_cell` or the re-check.
- **The run-book matches the code.** The cell filenames, `--cells` tokens and strategy/horizon names agree with the code. The group-level `--resume` pass recomputes every cell whose identity does not match before it writes the group report.

## Tests run by the reviewer

Under Python 3.11, the reviewer ran `test_tuner_recheck_window`, `test_export_tuning_bars`, `test_tuner_projection` and `test_horizon_tuning_report`: **169 passed**, 0 failed.

## The 7 reported deviations

None of the seven is a gate finding:

1. **Preflight folds from the sample calendar.** This affects the projection only, and it matches what `tune_cell` uses.
2. **The `--probe-json` flag.** It writes a probe-only summary file and touches no tuning output or database.
3. **Zero work projected for cells with no valid parameters or no folds.** This is a model figure, and it matches the code: `final_params` is None and the re-check is empty.
4. **Simulation timed per pair, gate timed per direction.** These are time estimates only.
5. **Probe uses the trade and fire-rate universes.** These are the universes the re-check actually covers, and the result is a model figure.
6. **The wrapper skips existing cell files without checking their identity.** The group `--resume` pass over all 5 cells recomputes any mismatched cell before the reports are written. The worst case is a group pass that runs past the quiet window, which is a scheduling problem, not a wrong number.
7. **The final-parameter count includes evidence-only symbols.** This matches the code, which builds full final series for fire-universe symbols too.

## Frontend test-only changes (Task 2a)

- **Scoping only narrows queries.** Each change narrows the parent scope of a role query, or moves `confirmReview` into `frontend/test-utils/tradeCardQueries.ts`. A narrower scope can only find fewer elements, so it cannot turn a failing assertion into a pass. No assertion, payload check, order-count check or timeout was removed or loosened.
- **The "Send to …" button is still found the same way.** Production renders it only inside the "Broker order review" region (`BrokerOrderReview/index.tsx:106–202`). On Step 7 the TradeCard default label is always overridden by "Track basket…" (`page.tsx:1570/1898`). So the old global query and the new scoped one find the same element.
- **The try/finally change only adds isolation.** The actions and assertions are the same.

## Outcome

There were no fixes and there are no outstanding findings. The code stage is clean at round 1, so `audit_clean: true`. Any later commit beyond `b5e4c385` must be limited to what `board.md` step 7 condition 3 allows: `git merge origin/main` with conflicts only in `PROJECT_STATE.json`, or documentation-only records of this verdict or the pending merge.
