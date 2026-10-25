# Code Audit Round 1 Report: `OHLCV-ALPACA-DAY-HOLES`

- **Phase:** `OHLCV-ALPACA-DAY-HOLES` (#535)
- **Branch:** `board/ohlcv-alpaca-day-holes-598af15f`
- **Auditor:** Independent Subagent `a0d6517f-d971-4c35-9d45-65065f704cd0` (applying `bmad-review-adversarial-general` under numeric/persistence gate)
- **Reviewed Diff:** `git diff origin/main..HEAD` (diff `56f12789..aa598459`)

---

## Gate Findings Reported

1. **`HOLES-CODE-01`**: `backend/scripts/backfill_alpaca_holes.py:280-281`
   - *Issue:* When Alpaca returned raw bar but missing adjusted bar (`adj_bar is None`), `adj_close` defaulted to raw `close_val`, computing `adj_factor = 1.0` and committing invented factors (+132% jump) to `ohlcv_daily`.
   - *Fix:* Check `if not adj_bar or not adj_bar.get("c") or float(adj_bar["c"]) <= 0: continue`. Strictly skip bar rather than inventing factor 1.0.

2. **`HOLES-CODE-02`**: `backend/app/services/history_gap_detector.py:14-29`
   - *Issue:* National Day of Mourning for President Jimmy Carter (January 9, 2025) was omitted from `SPECIAL_CLOSURES`, falsely flagging 533 universe symbols with missing trading day holes and forcing `history_gap_detector.py` to exit 1 on clean 2025 databases.
   - *Fix:* Added `date(2025, 1, 9)` to `SPECIAL_CLOSURES`. Added test assertion. Regenerated `m1_gaps_before.json`.

3. **`HOLES-CODE-03`**: `backend/scripts/backfill_alpaca_holes.py:249-250, 257-258`
   - *Issue:* Fallback `if not raw_bar and len(raw_bars) == 1: raw_bar = raw_bars[0]` bypassed date matching, allowing an adjacent day's OHLCV prices to be stored under `target_date`.
   - *Fix:* Removed single-element fallbacks. Strictly require `b.get("t", "")[:10] == target_iso`.

---

## Verification & Fix Commit

- **Fix Commit:** `54c44542`
- **Tests Added:**
  - `test_carter_national_day_of_mourning_is_non_trading_day`
  - `test_missing_adj_bar_causes_backfill_symbol_to_skip`
  - `test_mismatched_date_in_single_element_raw_bars_skips`
- All 54 tests passing green.
