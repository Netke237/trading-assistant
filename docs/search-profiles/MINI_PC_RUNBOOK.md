# Mini PC Runbook: Options Search Profiles Recalibration & Measurement

This runbook guides running measurement scans across the 18 recalibrated Options search profiles on the mini PC or local development environment.

Target: Issue #187 (`SEARCH-PROFILES-RECAL-OPTIONS`).

---

## 1. Prerequisites & Environment

1. **Python 3.11 Environment:**
   Ensure the Python 3.11 virtual environment is activated:
   - On Windows (PowerShell / cmd):
     ```powershell
     .\backend\.venv\Scripts\Activate.ps1
     ```
   - On Linux / macOS:
     ```bash
     source backend/.venv/bin/activate
     ```
   Verify Python version:
   ```bash
   python --version
   # Expected: Python 3.11.x
   ```

2. **Market Data Credentials (`.env`):**
   Ensure `backend/.env` has valid market data credentials:
   - `TRADIER_API_TOKEN`: Active Tradier production or sandbox token.
   - `TIINGO_API_TOKEN`: Active Tiingo token for underlying history.

3. **Backend Service:**
   - If running `--live` against a running backend instance:
     Start the backend server in a separate terminal:
     ```bash
     cd backend
     uvicorn app.main:app --port 8000
     ```

---

## 2. Dry-Run Verification (Off-Market Hours / Static Validation)

Before running scans, verify that the 18 profiles conform strictly to Schema Version 5 and that all scan request payloads pass Pydantic validation:

```bash
python backend/scripts/run_options_profiles_measurement.py --dry-run
```

Expected output:
- Loads 18 profiles from `docs/search-profiles/search-profiles-export.json`.
- Validates all 18 profiles (schema v5 compliance).
- Displays validation status `✓ [1/18] ... [18/18]` and exits with code 0.

You can also test a single profile by ID:
```bash
python backend/scripts/run_options_profiles_measurement.py --profile-id mu2n6u2bxt11 --dry-run
```

---

## 3. Live Measurement Run (Market Hours)

During US market hours (09:30 – 16:00 ET / 15:30 – 22:00 German time), run the live measurement harness across all 18 profiles:

```bash
python backend/scripts/run_options_profiles_measurement.py \
  --live \
  --api-url http://localhost:8000 \
  --output docs/superpowers/measurements/options_profiles_run_$(date +%Y%m%d).json \
  --markdown docs/superpowers/measurements/options_profiles_run_$(date +%Y%m%d).md
```

### Running on a Specific Symbol Subset:
To test quickly with a representative subset (e.g., 5 mega-cap names):
```bash
python backend/scripts/run_options_profiles_measurement.py \
  --live \
  --api-url http://localhost:8000 \
  --symbols AAPL,MSFT,NVDA,AMZN,GOOGL
```

---

## 4. Output Artifacts & Inspection

The harness generates two artifacts:
1. **JSON Measurement Report:**
   - Saved to `docs/superpowers/measurements/options_profiles_measurement_<timestamp>.json` (or the custom path specified via `--output`).
   - Contains exact timestamps, full request payloads, total evaluated symbols, passing candidates count, rejected candidates count, tally of rejection reasons, and top 3 candidates per profile.
2. **Markdown Summary Table:**
   - Saved to `docs/superpowers/measurements/options_profiles_measurement_<timestamp>.md` (or custom `--markdown` path).
   - Formatted in the standard MEAS table format for immediate review and comparison against MEAS Days 1 & 2 baselines.

---

## 5. Troubleshooting

- **HTTP 422 Unprocessable Entity:**
  Ensure the backend is up-to-date with PR #384 (Entry Quality overrides) and PR #452 (Universe filters).
- **Network / Provider Timeout:**
  If Tradier API rate-limits or times out, re-run with `--symbols` or target specific profile IDs using `--profile-id <id>`.
- **Off-Hours / Zero Volume:**
  Tradier returns 0 volume when markets are closed; profiles with `min_volume > 0` (such as Restrictive tiers) will reject strikes unless Tradier off-hours open interest sentinels apply. Run during active market trading hours (ideally after 10:30 ET / 16:30 German time) for accurate volume counts.
