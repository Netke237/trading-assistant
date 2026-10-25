# OHLCV Alpaca Day Holes Remediation Run-Book (Mini PC)

**Phase:** `OHLCV-ALPACA-DAY-HOLES` · **Issue:** #535 / #560  
**Target:** Mini PC production database (`trading` / `TradingAssistantDB`)  
**Operator:** Kenneth  
**Script:** `backend/scripts/backfill_alpaca_holes.py`  
**Gap Detector:** `backend/scripts/history_gap_detector.py`  

---

## 1. Executive Summary & Root Cause

During the #173 bar-alignment audit, systematic missing trading days were discovered in `ohlcv_daily`:
- **2021-04-19** (Monday): 240 symbols missing (all `source = 'alpaca'`)
- **2021-10-25** (Monday): 216 symbols missing (all `source = 'alpaca'`)
- **2022-03-08** (Tuesday): 239 symbols missing (all `source = 'alpaca'`)

### Root Cause
Alpaca previously queried the single-exchange IEX feed (`"feed": "iex"`). For NYSE-listed equities (Tape A/B), IEX volume is thin; on those three dates, zero trades occurred on IEX for ~240 NYSE equities (e.g. SRE, AFL, AIG, XOM), causing Alpaca's IEX endpoint to return no bars. In contrast, querying Alpaca's consolidated tape (`feed="sip"`) returns full trading bars for all three dates.

### Safety Invariants Enforced by `backfill_alpaca_holes.py`
1. **Strict Single-Source Consistency:** Only fills gaps for Alpaca-sourced series (`source = 'alpaca'`). Foreign provider series (Tiingo, yfinance) are never spliced, preserving `history_basis.py` invariants.
2. **Exact Adjustment Factor:** Computes `adj_factor = round(adj_close / raw_close, 8)` directly from the Alpaca SIP bar. Legitimate corporate dividend steps (e.g. AEE, SPG on 2022-03-08) are preserved exactly.
3. **Staleness Guard (`batch_step` Invariant):** The backfilled row pins `fetched_at` to match surrounding retained rows. Because `_fetch_date(prev) == _fetch_date(backfilled)`, `historical_store.py:477` does not trigger false `batch_step` staleness flags.
4. **Candidate Validation:** Rejects any bar without positive OHLCV or where `high < low`.
5. **Atomic Transactions:** Database inserts are committed per symbol within isolated transactions.

---

## 2. Step-by-Step Remediation Instructions (PowerShell)

Execute all commands from the repository root directory on the mini PC:
```powershell
cd C:\GitHub\trading-assistant
```

### Step 1: Pre-Flight Verification
Verify that Python 3.11 is active and Alpaca SIP credentials have entitlement:

```powershell
# 1a. Verify Python 3.11 runtime pin
python --version
# Expected: Python 3.11.x

# 1b. Verify Alpaca SIP feed access
python -c "import sys, asyncio; sys.path.insert(0, 'backend'); from app.data.alpaca import get_alpaca_client; from scripts.backfill_alpaca_holes import verify_alpaca_sip_access; client = asyncio.run(get_alpaca_client(feed='sip')); print('Alpaca SIP Entitlement:', asyncio.run(verify_alpaca_sip_access(client)))"
# Expected output: Alpaca SIP Entitlement: True
```

---

### Step 2: PostgreSQL Backup
Create a compressed snapshot of the `ohlcv_daily` table before making any changes:

```powershell
# Standard PostgreSQL dump of the ohlcv_daily table
pg_dump -U postgres -d trading -t ohlcv_daily -F c -f ohlcv_daily_pre_backfill.dump

# If your database is named TradingAssistantDB on custom port 5433:
# pg_dump -h localhost -p 5433 -U bamendjou -d TradingAssistantDB -t ohlcv_daily -F c -f ohlcv_daily_pre_backfill.dump
```
Verify the dump file was created and is non-empty:
```powershell
Get-Item ohlcv_daily_pre_backfill.dump
```

---

### Step 3: Pre-Backfill Gap Detection
Run the gap detector to record the baseline state of missing dates:

```powershell
python backend/scripts/history_gap_detector.py --json-out docs/superpowers/measurements/2026-10-24-ohlcv-alpaca-day-holes/m1_gaps_before.json --no-exit-code
```
**Expected Baseline:**
- `2021-04-19`: ~240 symbols missing
- `2021-10-25`: ~216 symbols missing
- `2022-03-08`: ~239 symbols missing

---

### Step 4: Dry-Run Backfill Test
Simulate the backfill without executing any database writes:

```powershell
python backend/scripts/backfill_alpaca_holes.py --dry-run
```
**Expected Output:**
- Validates Alpaca SIP entitlement (HTTP 200).
- Identifies ~240 symbols with target gaps.
- Shows `Rows would insert: ~695 (dry run — no writes)`.
- Database remains completely untouched.

---

### Step 5: Live Backfill Execution
Execute the live backfill:

```powershell
python backend/scripts/backfill_alpaca_holes.py
```
**Expected Output:**
- Queries Alpaca SIP bars for each missing target date.
- Copies surrounding `fetched_at` timestamp.
- Commits each symbol atomically.
- Summary report prints:
  - `Symbols with gaps:     ~240`
  - `Symbols backfilled:    ~240`
  - `Symbols skipped:       0`
  - `Rows inserted:         ~695`

*(Optional: To backfill a single test symbol first, run `python backend/scripts/backfill_alpaca_holes.py --symbols SRE`)*

---

### Step 6: Post-Backfill Gap Verification
Re-run the gap detector and capture the post-backfill measurement:

```powershell
python backend/scripts/history_gap_detector.py --json-out docs/superpowers/measurements/2026-10-24-ohlcv-alpaca-day-holes/m2_gaps_after.json --no-exit-code
```
**Verification Criteria:**
- Dates `2021-04-19`, `2021-10-25`, and `2022-03-08` must NO LONGER appear in the missing dates table.
- Total missing bars for those three dates must be **0**.

---

### Step 7: Rollback Procedure (If Needed)
If any unexpected discrepancy occurs, restore `ohlcv_daily` from the backup dump taken in Step 2:

```powershell
# Restore ohlcv_daily from backup
pg_restore -U postgres -d trading --clean --table=ohlcv_daily ohlcv_daily_pre_backfill.dump

# Or with custom port/user:
# pg_restore -h localhost -p 5433 -U bamendjou -d TradingAssistantDB --clean --table=ohlcv_daily ohlcv_daily_pre_backfill.dump
```
After restore, re-run gap detector to verify table is back to baseline:
```powershell
python backend/scripts/history_gap_detector.py --no-exit-code
```
