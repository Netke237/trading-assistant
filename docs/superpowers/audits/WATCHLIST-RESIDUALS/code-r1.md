# Code Audit Round 1: WATCHLIST-RESIDUALS (#168)

**Reviewer:** Independent Subagent (Adversarial General Reviewer) (`65695e43-9c8e-4d19-a9de-1d60ccf341b1`)
**Target Diff:** `origin/main` (`c0328c56`) .. HEAD (`300d894d`)
**Plan:** `docs/superpowers/plans/2026-10-22-watchlist-residuals-plan.md`
**Tracking Issue:** #168 (`WATCHLIST-RESIDUALS: Watchlist validation and refresh residuals (ticket 21)`)
**Skill Applied:** `bmad-review-adversarial-general` (`.agents/skills/bmad-review-adversarial-general/SKILL.md`)
**The Gate:** A finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA, or misstate mechanism such that a competent reader acting on it would write a wrong change.

---

## 1. Audit Analysis of Verification Checkpoints

### 1. Canonical Strike Validation & Group Taint Elimination
- **Boundary & Schema Alignment:**
  In `frontend/lib/contractGrading.ts`, `STRIKE_RE` was tightened to `/^[0-9]{1,5}(\.[0-9]{1,3})?$/`, coupled with `if (!Number.isFinite(strike) || strike <= 0) return null;`.
  - Strictly conforms to the OCC specification and backend contract requirements:
    - Backend `backend/app/data/strike.py`: `_STRIKE_TEXT = re.compile(r"[0-9]{1,5}(?:\.[0-9]{1,3})?")` and `canonical_strike` (`round(float(raw), 3)` with `value > 0`).
    - Backend `backend/app/routers/contracts.py`: `_parse_strikes` raises HTTP 422 for any item refused by `parse_strike_text`.
  - Rejection coverage verified:
    - Oversized integer strikes (>5 integer digits, e.g. `AAPL|100000|...`, `AAPL|9999999999|...`) -> `null`.
    - Oversized fractional strikes (>3 decimals, e.g. `AAPL|187.1234|...`) -> `null`.
    - Non-positive strikes (`0`, `0.000`, negative) -> `null`.
    - Malformed formats (leading/trailing garbage, non-digits, signs, exponents) -> `null`.
    - Canonical valid strikes (`185`, `187.5`, `22.50`, `99999.999`) -> accurately parsed without truncation.
- **Group Taint Elimination:**
  - In `planContractGroups`, when `parseContractId(id)` returns `null`, `parsed.set(id, null)` is recorded and the loop executes `continue`.
  - The oversized/malformed ID is excluded from `groupOf` and its strike is never added to `group.strikes`.
  - When `refreshContracts` fires `api.getContracts(g.symbol, g.right, { strikes: g.strikes, ... })`, the query param `strikes` contains only valid sibling strikes. The backend returns 200 instead of 422.
- **Watched Row Isolation:**
  - In `resolveWatchedRows`, an unparseable ID maps immediately to `{ kind: 'invalid', id }`.
  - In `WatchlistPage`'s `MissingContractRow`, this renders note `"Unreadable contract id"` (`INVALID_NOTE`) with dashes (`—`) across all price, delta, theta, IV, and score cells. No bogus numbers are shown, and the star remains interactive (`ContractStar`) so the user can unstar/remove it.
  - Sibling contracts in the same symbol/expiry group resolve to live quotes and scores without degradation.

### 2. Deep Sanitization & Orphan Storage Cleanup
- **Orphan Key Elimination:**
  - `sanitizePersisted` in `frontend/lib/watchedContractsStore.ts` constructs `idSet = new Set(ids)`.
  - In `for (const [k, v] of Object.entries(rawGrading))`, entries are retained if and only if `idSet.has(k) && isValidGrading(v)`.
  - Orphan keys in `grading` that do not exist in `ids` are cleanly dropped, eliminating localStorage bloat.
- **Corrupt Grading Dropping & Fallback:**
  - Stored grading objects with invalid or corrupted values (e.g. non-finite rule values, non-integer or inverted hold days, out-of-bounds `stock_score`) fail `isValidGrading(v)` and are dropped from `grading`.
  - When `grading[id]` is absent, `isYamlGraded(grading[id])` evaluates to `true`, and `contractGrading.ts` cleanly falls back to grading against `contract_rules.yaml` with the `YAML_MARKER` notice rather than crashing or using corrupted values.
- **Defensive Non-Array / Missing `ids` Handling:**
  - If `persisted.ids` is missing, null, or a non-array value, `Array.isArray(p.ids)` evaluates to `false`, setting `ids: []`.
  - `idSet` is empty, causing `grading` to evaluate to `{}`. The function safely returns `{ ids: [], grading: {} }` without throwing.

### 3. Unmount Abort of In-flight Contracts Fetch
- In `frontend/app/(frame)/watchlist/page.tsx`:
  ```tsx
  useEffect(() => {
    refreshContracts();
    return () => {
      contractsAbortRef.current?.abort();
    };
  }, [refreshContracts]);
  ```
  - When navigating away from `/watchlist` while a multi-group contract fetch is in-flight:
    - `contractsAbortRef.current?.abort()` aborts the active `AbortController`.
    - Active `fetch` HTTP requests in `Promise.allSettled` are cancelled.
    - Inside `refreshContracts`, `if (controller.signal.aborted) return;` skips `setKept`, `setContractsOffline`, and the `finally` block skips `setRefreshingContracts`, preventing state updates on an unmounted component.

### 4. Tab-Scoped Offline Banner Isolation
- In `frontend/app/(frame)/watchlist/page.tsx`:
  ```tsx
  {tab === 'stocks' && offline ? (
    <Text size={13} tone="dim">Backend not running — start it (uvicorn app.main:app --port 8000) to load live data.</Text>
  ) : tab === 'contracts' && contractsOffline ? (
    <Text size={13} tone="dim">Could not load option chains — retry</Text>
  ) : null}
  ```
  - Stocks offline banner renders ONLY when `tab === 'stocks'`. Switching to Contracts or Composite does not display the Stocks offline warning.
  - Contracts offline banner renders ONLY when `tab === 'contracts'`. Switching to Stocks or Composite does not display the Contracts chain warning.

---

## 2. Adversarial Trace & Verification Check

1. **Numeric & Broker Order Gate Verification:**
   - Watchlist contracts table is a monitoring surface and does not place broker orders.
   - Strike regex and numeric bounds enforce the exact OCC canonical boundaries (`0 < strike <= 99999.999` with max 3 decimals). No valid strikes are altered or corrupted.
2. **Storage Invariants & Persistence Safety:**
   - Rehydration and migrations safely run `sanitizePersisted`.
   - Valid starred contracts and valid grading maps are preserved with zero corruption.
3. **Execution Evidence:**
   - `python scripts/state.py`: No drift detected. Presence probe `test_oversized_strike_isolation` in `frontend/lib/__tests__/contractGrading.test.ts` verified.
   - `npm run typecheck`: 0 errors.
   - Jest tests:
     - `lib/__tests__/contractGrading.test.ts` (PASS, 77 passed)
     - `lib/__tests__/watchedContractsStore.test.ts` (PASS)
     - `app/(frame)/watchlist/__tests__/page.test.tsx` (PASS)
   - Pytest tests:
     - `pytest tests/test_watched_contracts_grading.py tests/test_strike.py` (PASS, 150 passed in 17.76s).

---

## 3. Findings Summary

All five checkpoints and adversarial traces were thoroughly tested and verified. No gate violations exist:
- No reachable scenario presents a wrong number to the user.
- No reachable scenario submits a wrong broker order.
- No reachable scenario corrupts persisted localStorage or backend database state.
- No mechanism claims in comments or docs misstate code behavior.

**GATE FINDINGS: 0**
