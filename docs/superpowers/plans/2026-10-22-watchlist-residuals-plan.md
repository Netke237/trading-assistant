# WATCHLIST-RESIDUALS Implementation Plan

**Phase:** `WATCHLIST-RESIDUALS`
**Tracking Issue:** #168 (`Watchlist: validation and refresh residuals (ticket 21)`)
**Date:** 2026-10-22
**Status:** Planned (Round 1 Plan Audit pending)
**Branch:** `board/watchlist-residuals-45225aff`
**Touches:**
- `frontend/lib/contractGrading.ts`
- `frontend/lib/watchedContractsStore.ts`
- `frontend/app/(frame)/watchlist/page.tsx`
- `frontend/lib/__tests__/contractGrading.test.ts`
- `frontend/lib/__tests__/watchedContractsStore.test.ts`
- `frontend/app/(frame)/watchlist/__tests__/page.test.tsx`
- `docs/superpowers/PROJECT_STATE.json`

---

## 1. Problem Statement & Historical Context

Following the merge of `WATCHLIST-SCAN-CONTRACT-RULES` (PR #23) and `EXACT-STRIKE` (PR #512, Issue #162), several validation, sanitizer, and refresh/banner residuals remained logged-not-fixed in `PROJECT_STATE.json` and ticket 21 (`.scratch/project-ticket-reconciliation-20261009/issues/21-watchlist-residuals.md`):

1. **Group Tainting from Oversized/Malformed Strikes:**
   In `frontend/lib/contractGrading.ts`, `STRIKE_RE = /^\d+(\.\d+)?$/` accepts any number of digits (e.g. 10 or 100 digits, or zero `0`). The backend `parse_strike_text` (in `backend/app/data/strike.py`) accepts only `[0-9]{1,5}(\.[0-9]{1,3})?` (> 0). If a starred contract contains an oversized strike (e.g. `AAPL|100000|2026-12-18|C` or `AAPL|9999999999|2026-12-18|C`), `parseContractId` treats it as valid and `planContractGroups` includes it in the group's `strikes` array alongside valid sibling contracts (e.g. `AAPL 180C`). When `api.getContracts` fires, `/api/contracts` rejects the request with HTTP 422 (`strikes must be comma-separated strikes, e.g. 187 or 187.5`). The whole group fails, and the valid sibling contract is erroneously marked as `fetch_failed` ("Could not load the chain") instead of rendering live quotes and scores.

2. **Shallow Sanitization & Orphan Storage in `watchedContractsStore.ts`:**
   In `frontend/lib/watchedContractsStore.ts`, `sanitizePersisted` checks that `grading` is an object, but does not sanitize its entries. If `grading` contains orphan keys (contracts that were unstarred or never existed in `ids`) or malformed/corrupted grading entries, they remain in persisted localStorage indefinitely, bloating storage. Furthermore, if `ids` is not an array, `sanitizePersisted` sets `ids: []` but leaves `grading` untouched.

3. **Missing Unmount Abort in `WatchlistPage`:**
   In `frontend/app/(frame)/watchlist/page.tsx`, `refreshContracts` uses an `AbortController` (`contractsAbortRef.current`) during re-renders, but the `useEffect` hook has no cleanup function returning `() => { contractsAbortRef.current?.abort(); }`. When the user navigates away from `/watchlist` while a multi-group contract fetch is in-flight, the fetch continues running in the background and sets state after unmount.

4. **Tab-Bleeding Offline Banners:**
   In `frontend/app/(frame)/watchlist/page.tsx`, the Stocks offline banner `{offline ? <Text>Backend not running...</Text> : ...}` does not check `tab === 'stocks'`. If `api.getWatchlist` fails, the Stocks offline message renders even when the user is viewing the Contracts tab (where contracts may be loading or loaded successfully).

---

## 2. Invariants & Numeric Gate Integrity

1. **Zero Gate Violations:**
   - No wrong numbers or incorrect prices/greeks displayed on watchlist rows.
   - Valid sibling contracts in a group must NEVER fail or be marked unavailable due to another star having an oversized/malformed strike.
2. **Backward Compatibility & Exact Strikes:**
   - Canonical strikes conforming to `EXACT-STRIKE` (`STRIKE_RE = /^[0-9]{1,5}(\.[0-9]{1,3})?$/` with `strike > 0`) continue to parse exactly, preserving fractional strikes (e.g. `182.5`, `22.50`) and integer strikes (`185`).
3. **Storage & Sanitizer Safety:**
   - `sanitizePersisted` must drop orphan keys from `grading` that do not exist in `ids`.
   - `sanitizePersisted` must validate each grading entry using `isValidGrading`, dropping corrupted entries so they fall back to YAML-graded rather than crashing or keeping invalid objects.
4. **Clean Abort & Zero Leakage:**
   - Unmounting `WatchlistPage` immediately aborts any in-flight contracts fetch via `contractsAbortRef.current?.abort()`.
   - Tab-specific offline banners only display when their corresponding tab is active.

---

## 3. Detailed Technical Design & Code Changes

### A. Strike Validation & Group Taint Elimination (`frontend/lib/contractGrading.ts`)

Update `STRIKE_RE` and `parseContractId` to enforce the canonical strike boundary:
- Reject any strike that does not match `^[0-9]{1,5}(\.[0-9]{1,3})?$`.
- Reject non-positive strikes (`strike <= 0`).

```ts
const SYMBOL_RE = /^[A-Z][A-Z0-9.\-]*$/;
const STRIKE_RE = /^[0-9]{1,5}(\.[0-9]{1,3})?$/;
const EXPIRY_RE = /^\d{4}-\d{2}-\d{2}$/;

export function parseContractId(id: string): ParsedContractId | null {
  const parts = id.split('|');
  if (parts.length !== 4) return null;
  const [symbol, strikeText, expiry, right] = parts as [string, string, string, string];
  if (!SYMBOL_RE.test(symbol)) return null;
  if (!STRIKE_RE.test(strikeText)) return null;
  if (!EXPIRY_RE.test(expiry)) return null;
  if (right !== 'C' && right !== 'P') return null;
  const strike = parseFloat(strikeText);
  if (!Number.isFinite(strike) || strike <= 0) return null;
  return { id, symbol, strike, expiry, right };
}
```

**Consequence for `planContractGroups` and `resolveWatchedRows`:**
- A contract ID with an oversized strike (e.g. `AAPL|100000|2026-12-18|C`) returns `null` from `parseContractId`.
- `planContractGroups` records `parsed.set(id, null)`. It does not create or append to `group.strikes`.
- `resolveWatchedRows` sees `!p` and produces `{ kind: 'invalid', id }`, which renders with `INVALID_NOTE` ("Unreadable contract id").
- The valid sibling contracts in that group (e.g. `AAPL|180|2026-12-18|C`) have their request sent cleanly without 422 and load their live quotes without failure.

### B. Deep Sanitization & Orphan Cleanup (`frontend/lib/watchedContractsStore.ts`)

Update `sanitizePersisted` in `frontend/lib/watchedContractsStore.ts` to clean orphan keys and validate individual grading entries:

```ts
function sanitizePersisted(persisted: unknown): Persisted {
  const p = (persisted ?? {}) as { ids?: unknown; grading?: unknown };
  const ids = Array.isArray(p.ids) ? p.ids.filter(isId) : [];
  const g = p.grading;
  const rawGrading = g && typeof g === 'object' && !Array.isArray(g) ? (g as Record<string, unknown>) : {};
  const idSet = new Set(ids);
  const grading: Record<string, ContractGrading> = {};
  for (const [k, v] of Object.entries(rawGrading)) {
    if (idSet.has(k) && isValidGrading(v)) {
      grading[k] = v;
    }
  }
  return { ids, grading };
}
```

- When `ids` contains `[A]`, and `grading` contains `{ [A]: G, [B]: G2, [C]: 'bad' }`:
  - `B` is dropped because it is an orphan key not in `idSet`.
  - `C` is dropped because `'bad'` is not a valid grading.
  - `A` is retained because it is in `idSet` and `isValidGrading(G)` is true.
- If `ids` is missing or not an array, `idSet` is empty, so `grading` becomes `{}`.

### C. Unmount Abort of In-flight Contracts Fetch (`frontend/app/(frame)/watchlist/page.tsx`)

In `frontend/app/(frame)/watchlist/page.tsx`:
```tsx
  useEffect(() => {
    refreshContracts();
    return () => {
      contractsAbortRef.current?.abort();
    };
  }, [refreshContracts]);
```
- When navigating away from `/watchlist`, `contractsAbortRef.current?.abort()` immediately cancels all pending HTTP requests in `Promise.allSettled`.
- Prevents unmounted state updates and network waste.

### D. Tab-scoped Offline Banner Isolation (`frontend/app/(frame)/watchlist/page.tsx`)

In `frontend/app/(frame)/watchlist/page.tsx`:
```tsx
        {tab === 'stocks' && offline ? (
          <Text size={13} tone="dim">Backend not running — start it (uvicorn app.main:app --port 8000) to load live data.</Text>
        ) : tab === 'contracts' && contractsOffline ? (
          <Text size={13} tone="dim">Could not load option chains — retry</Text>
        ) : null}
```
- Stocks offline banner only displays when `tab === 'stocks'`.
- Contracts offline banner only displays when `tab === 'contracts'`.
- On `composite` tab, neither banner displays.

---

## 4. Test & Verification Plan

### A. Unit Tests: `frontend/lib/__tests__/contractGrading.test.ts`
1. **Oversized Strike Rejection**:
   - `AAPL|100000|${E}|C` (6 integer digits) -> `null`.
   - `AAPL|9999999999|${E}|C` (10 integer digits) -> `null`.
   - `AAPL|187.1234|${E}|C` (>3 fractional digits) -> `null`.
   - `AAPL|0|${E}|C` (zero strike) -> `null`.
   - `AAPL|0.000|${E}|C` (zero fractional strike) -> `null`.
2. **Valid Strike Acceptance**:
   - `AAPL|187|${E}|C` -> valid (187).
   - `AAPL|187.5|${E}|C` -> valid (187.5).
   - `AAPL|99999.999|${E}|C` -> valid (5 digits + 3 decimals).
3. **Group Taint Isolation (`test_oversized_strike_isolation`)**:
   - Presence probe: `test_oversized_strike_isolation`.
   - Group containing both `AAPL|187|${E}|C` and `AAPL|100000|${E}|C`.
   - `planContractGroups` must create group with `strikes: [187]` only.
   - `resolveWatchedRows` returns `{ kind: 'live' }` (or missing loading/not_listed) for `187C`, and `{ kind: 'invalid' }` for `100000C`.

### B. Unit Tests: `frontend/lib/__tests__/watchedContractsStore.test.ts`
1. **Deep Sanitization**:
   - Stored blob with orphan keys in `grading` that are not in `ids`: verify orphan keys are dropped.
   - Stored blob with invalid grading entries (e.g. non-object, invalid rules, bad hold bounds): verify corrupt entries are dropped.
   - Stored blob with non-array `ids`: verify both `ids` and `grading` are sanitized to `ids: [], grading: {}`.

### C. Component Integration Tests: `frontend/app/(frame)/watchlist/__tests__/page.test.tsx`
1. **Unmount Abort**:
   - Render `WatchlistPage` with pending `getContracts` call.
   - Unmount component: verify `AbortSignal.aborted` is true.
2. **Tab-Scoped Banners**:
   - When `api.getWatchlist` fails (`offline: true`): Stocks tab shows "Backend not running"; switching to Contracts tab does NOT show "Backend not running".
   - When `getContracts` fails (`contractsOffline: true`): Contracts tab shows "Could not load option chains — retry"; switching to Stocks tab does NOT show "Could not load option chains".

### D. Full Regressions & Presence Probe:
- Python 3.11 backend tests: `backend/tests/test_watched_contracts_grading.py` (all 15 pass).
- TypeScript typecheck: `npm run typecheck` clean.
- Jest test suite: all 104+ tests pass.
- State probe: `scripts/state.py` reports 0 drift with presence probe `test_oversized_strike_isolation`.

---

## 5. Audit Rules & Verification

In accordance with `AGENTS.md` and `docs/agents/ticket-orchestration.md`:
- Plan Audit (Round 1): Fresh independent subagent evaluating this plan against the gate (wrong numbers, data corruption, mechanism errors).
- Implement only after Plan Audit is clean.
- Code Audit (Round 1): Fresh independent subagent evaluating the diff against this plan and target issue #168.
- Self-merge under `board.md` step 7 only after exact-head CI is 100% green.
