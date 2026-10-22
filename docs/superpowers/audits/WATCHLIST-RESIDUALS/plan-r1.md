# Plan Audit Round 1: WATCHLIST-RESIDUALS (#168)

**Reviewer:** Independent Subagent (Adversarial General Reviewer `c8a7ad62-b616-4304-8010-01d2530b614b`)
**Plan Document:** `docs/superpowers/plans/2026-10-22-watchlist-residuals-plan.md`
**Tracking Issue:** #168 (`Watchlist: validation and refresh residuals (ticket 21)`)
**Phase:** `WATCHLIST-RESIDUALS`
**Review Skill:** `bmad-review-adversarial-general` (`.agents/skills/bmad-review-adversarial-general/SKILL.md`)
**Gate Criterion:** Only findings that can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA, or misstate mechanism such that a competent reader would implement a wrong change.

---

## 1. Audit Analysis of Specified Checkpoints

### 1. Section 3.A: Strike Validation & Group Taint Elimination (`frontend/lib/contractGrading.ts`)
- **Strike boundary alignment:** Updating `STRIKE_RE = /^[0-9]{1,5}(\.[0-9]{1,3})?$/` and adding `if (!Number.isFinite(strike) || strike <= 0) return null;` strictly matches the OCC strike resolution and backend's canonical strike rules (`_STRIKE_TEXT = re.compile(r"[0-9]{1,5}(?:\.[0-9]{1,3})?")` and `canonical_strike` in `backend/app/data/strike.py`).
  - Oversized strikes (>5 integer digits, e.g. `AAPL|100000|...` or >3 decimals, e.g. `AAPL|187.1234|...`) and non-positive strikes (`0`, `0.000`, negative) are rejected upfront and return `null`.
  - Canonical positive integer (`185`, `190`) and fractional strikes (`187.5`, `22.50`, `99999.999`) continue to parse cleanly.
- **Group taint elimination:**
  - In `planContractGroups`, when `parseContractId(id)` returns `null`, the function sets `parsed.set(id, null)` and executes `continue`. It does not add the contract to `groupOf` or append its strike to `group.strikes`.
  - In `resolveWatchedRows`, `!p` resolves the contract immediately to `{ kind: 'invalid', id }`, which renders with `INVALID_NOTE` ("Unreadable contract id") and retains its `ContractStar` button for unstarring.
  - The API call `/api/contracts` for that symbol/expiry/grading is made using only the valid strikes in `group.strikes`. Sibling contracts (e.g. `AAPL 180C`) in the same group are never 422'd and never marked `fetch_failed` ("Could not load the chain") because of an invalid sibling. Live quotes and scores load cleanly.

### 2. Section 3.B: Deep Sanitization & Orphan Cleanup (`frontend/lib/watchedContractsStore.ts`)
- **Orphan key elimination:**
  - `const idSet = new Set(ids);` constructs a set of valid, non-empty string IDs.
  - In `for (const [k, v] of Object.entries(rawGrading))`, the check `idSet.has(k) && isValidGrading(v)` strictly drops any grading entry whose key is not present in `ids`.
- **Corrupt entry elimination & fallback:**
  - Each grading entry is checked with `isValidGrading(v)`. Corrupted objects (e.g. non-finite rule values, inverted/negative hold bounds, out-of-range `stock_score`) are excluded from the returned `grading` map.
  - When a starred contract has no entry in `grading`, `contractGrading.ts`'s `isYamlGraded` treats it as YAML-graded and renders the `YAML_MARKER` notice without throwing or displaying broken calculations.
- **Defensive handling of non-array / missing `ids`:**
  - If `p.ids` is missing, undefined, or non-array, `Array.isArray(p.ids)` evaluates to `false`, yielding `ids = []`.
  - Consequently, `idSet` is empty, which causes `grading` to evaluate to `{}`. The function returns `{ ids: [], grading: {} }` safely without throwing.

### 3. Section 3.C: Unmount Abort of In-flight Contracts Fetch (`frontend/app/(frame)/watchlist/page.tsx`)
- Returning `() => { contractsAbortRef.current?.abort(); }` from the `refreshContracts` `useEffect` hook ensures that when `WatchlistPage` unmounts while `Promise.allSettled(api.getContracts)` is in-flight:
  - The in-flight `fetch` requests receive the abort signal and cancel network connections.
  - `controller.signal.aborted` evaluates to `true`, preventing calls to `setKept`, `setContractsOffline`, and `setRefreshingContracts` on an unmounted component.
  - No stale responses overwrite future navigations.

### 4. Section 3.D: Tab-Scoped Offline Banner Isolation (`frontend/app/(frame)/watchlist/page.tsx`)
- Scoping the banner conditional to:
  `{tab === 'stocks' && offline ? (...) : tab === 'contracts' && contractsOffline ? (...) : null}`
  strictly decouples tab failure states:
  - If `api.getWatchlist` fails (`offline: true`), the "Backend not running" banner renders ONLY when `tab === 'stocks'`. Switching to `tab === 'contracts'` will not show the Stocks offline banner.
  - If `api.getContracts` fails (`contractsOffline: true`), "Could not load option chains — retry" renders ONLY when `tab === 'contracts'`.
  - On `tab === 'composite'`, neither banner displays.

---

## 2. Adversarial Trace & Verification Check

1. **Broker order & numeric path integrity:**
   - The Watchlist is a monitoring interface; it does not issue broker orders.
   - The contract strike regex `/^[0-9]{1,5}(\.[0-9]{1,3})?$/` enforces the exact numeric bounds established by `EXACT-STRIKE` and OCC specifications; no valid strikes are truncated or modified.
2. **Persistence & storage safety:**
   - `sanitizePersisted` runs during Zustand rehydration (`merge` and `migrate`). It operates strictly as a sanitizer, preserving all valid `ids` and valid `grading` records while purging orphan keys and malformed objects.
   - Unstarring invalid contract IDs (`remove(contractId)`) properly invokes `api.removeWatchedContract`, which deletes the row from the backend SQLite/PostgreSQL `watched_contracts` table without error.
3. **Presence Probe & State Verification:**
   - `docs/superpowers/PROJECT_STATE.json` pins `test_oversized_strike_isolation` in `frontend/lib/__tests__/contractGrading.test.ts`. The plan explicitly includes this probe in Section 4.A.3.
   - Current codebase state via `python scripts/state.py` reports 0 drift.

---

## 3. Findings Summary

No gate-level findings:
- No reachable scenario produces a wrong number displayed to the user.
- No reachable scenario sends an incorrect broker order.
- No reachable scenario corrupts persisted localStorage or backend database state.
- All mechanism descriptions in the plan accurately reflect existing and proposed code paths.

**GATE FINDINGS: 0**
