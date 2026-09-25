# A5d — a Step-5 scan that fails says why in plain English (plan)

Date: 2026-09-25. Planned against main at `e2bf498` (branch `claude/peaceful-ritchie-b59i77`,
restarted from main). Frontend only, one build commit.

Origin: the follow-up logged by the parallel A5b build (round-3 note 5 on this branch, superseded
by main's A5b per decision `A5B-KEEP-MAIN-2026-09-25`). It applies unchanged to main's A5b:
`step-5-strategy/page.tsx` `runScan` builds the body with `buildStockScanRequestBody(...)` inside
its `try`, and the `catch` renders `String(e)`.

Kenneth's decision `A5D-READABLE-MESSAGE-2026-09-25`: a Step-5 scan whose saved settings cannot be
read shows a plain-English message pointing at Settings → Reset; a failure after the request was
sent reuses `stockScanFailureReason`, the Step-3/4 formatter. Step 5 only. No fallback to "scan
without a gate".

---

## 1. Defect, verified on today's tree

`frontend/app/(frame)/screener/step-5-strategy/page.tsx` `runScan` (`:211-261`):

```ts
try {
  ...
  const requestBody = buildStockScanRequestBody({ ..., scanOverrides: scan.scanOverrides,
    confidenceGate: useSettingsStore.getState().confidenceGate, ... });
  const result = await api.postStockScan(requestBody);
  ...
} catch (e) {
  setError(String(e));
}
```

Two user-visible faults, both from `String(e)`:

1. **A corrupted persisted setting shows a raw JS error.** `settingsStore` is persisted at
   version 24; `migrate()` only runs on a version bump, and `persist()`'s default merge is shallow,
   so a stored `confidenceGate: null` survives hydration as `null`.
   `buildStockScanRequestBody` then reads `atrMultForHorizon(null, …)` / `confidenceGate.enabled`
   and throws. Step 5 renders `TypeError: Cannot read properties of null (reading '…')`. Same for a
   null `scanStore.scanOverrides` (`scan.scanOverrides.pullback_require_reversal` in the page, then
   `Object.entries(null)` in the builder). Before A5b, Step 5 never read the gate, so this is a
   regression A5b introduced.
2. **A request failure shows an `Error: ` prefix and no hint.** `String(new Error('API
   /api/stock-scan → 422: …'))` is `Error: API /api/stock-scan → 422: …`; a transport failure is a
   bare `TypeError: Failed to fetch` without Step 3/4's "could not reach the backend at …" hint.

Why the message cannot say "Settings → Strategy scan": the gate is edited in Settings → **Scan**
(`ScanForm`, `settings/page.tsx:232`), which itself reads `confidenceGate.cautionBelow` during
render, so it would crash on the same null. The one reset that works is the footer **Reset**
(`resetToDefaults`, `settings/page.tsx:84`), which the page renders regardless of section, and
which also resets broker settings. The message says so.

## 2. Change

### 2a. `frontend/lib/stockScan.ts` — one exported constant, next to `stockScanFailureReason`

```ts
/** What a manual scan shows when building its request from the saved stores
 *  threw — nothing was sent, the fault is a malformed persisted setting
 *  (e.g. `confidenceGate: null`). Points at the footer Reset because the
 *  Settings → Scan form reads the same gate while rendering. A5d. */
export const STOCK_SCAN_SETTINGS_INVALID =
  "Couldn't read your saved scan settings. Open Settings and press Reset to restore the defaults (this also resets broker settings).";
```

`stockScanFailureReason` and `runStockScan` are unchanged (Step 3/4 keep showing the raw
pre-request text their existing test pins — see §6).

### 2b. `step-5-strategy/page.tsx` `runScan`

- `let reachedRequest = false;` declared before the `try`.
- `reachedRequest = true;` on the line immediately before `const result = await
  api.postStockScan(requestBody);` — the same boundary `runStockScan` uses (`stockScan.ts:320`).
- `catch (e)`:
  ```ts
  if (!reachedRequest) console.error('Step 5: building the stock-scan request failed', e);
  setError(reachedRequest ? stockScanFailureReason(e) : STOCK_SCAN_SETTINGS_INVALID);
  ```
  The raw error goes to the console so the detail is not lost to whoever debugs it.
- Imports: `stockScanFailureReason`, `STOCK_SCAN_SETTINGS_INVALID` from `@/lib/stockScan`.
- Everything else unchanged: the A5/A5b comments and body, `setStockScanResult`, `router.push`,
  `finally` (loading cleared, last-status refresh). The error still renders at `:316` as
  `<Text size={12} tone="reject">`.

Not changed: `buildStockScanRequestBody`, `settingsStore` (no hydration repair — logged, §6),
`runStockScan`, the backend. No persisted shape change.

## 3. Tests — new file `frontend/app/(frame)/screener/step-5-strategy/__tests__/a5dReadableScanError.test.tsx`

Harness: the mocks and `reset()` fixture of the sibling `a5bSharedRequest.test.tsx` (next/navigation,
`@/lib/api` with `postStockScan`, `getLastStockScanStatus`, `getLastDataRefresh`, `API_BASE_URL:
'http://localhost:8000'`). `console.error` spied and silenced per test; the page renders, a strategy
button is clicked, the test waits for the loading state to clear.

- **T1 — `confidenceGate: null`.** The rendered error is exactly `STOCK_SCAN_SETTINGS_INVALID`;
  no text matching `/TypeError|Cannot read/` is in the document; `postStockScan` was never called;
  `console.error` was called once with the page's prefix and a `TypeError`.
- **T2 — `scanOverrides: null`** (the other store the builder reads) → same message, no post.
- **T3 — API error after the request.** `postStockScan` rejects
  `new Error('API /api/stock-scan → 422: universe is empty')` → the rendered error is exactly
  `API /api/stock-scan → 422: universe is empty` (no `Error: ` prefix, not the settings message).
- **T4 — transport failure after the request.** `postStockScan` rejects
  `new TypeError('Failed to fetch')` → the rendered error is exactly `stockScanFailureReason(new
  TypeError('Failed to fetch'))`, and contains `could not reach the backend at
  http://localhost:8000`. A `TypeError` after the post is NOT the settings message (this pins the
  `reachedRequest` boundary from the other side).
- **T5 — recovery.** After T1's failure, restore a valid gate and click again: the post happens,
  the error line is gone (the existing `setError(null)` at the start of `runScan`).

### Mutation checks (each must turn at least one test red, then be reverted)

| # | Mutation | Expected red |
|---|---|---|
| M1 | restore `setError(String(e))` | T1, T2, T3, T4 |
| M2 | `reachedRequest = true` moved above `buildStockScanRequestBody` | T1, T2 |
| M3 | `reachedRequest = true` moved after the `await` | T4 |
| M4 | always `STOCK_SCAN_SETTINGS_INVALID` | T3, T4 |
| M5 | always `stockScanFailureReason(e, reachedRequest)` | T1, T2 |
| M6 | drop the `console.error` | T1 |

## 4. Verification

`npm run typecheck`, the full Jest suite (count = main's + 5), `python3 scripts/state.py` exit 0.
Backend untouched.

## 5. State

New phase `A5D-STEP5-READABLE-SCAN-ERROR`, `depends_on: [A5B-STEP5-SHARED-REQUEST]`, verify
`defect_marker` on `setError\(String\(e\)\)` in the Step-5 page while unbuilt; switched to a
presence probe on `STOCK_SCAN_SETTINGS_INVALID` in that page by the build commit. `active_phase`
points at it.

## 6. Out of scope — logged, not fixed

- **Hydration repair**: `settingsStore` accepts a non-object `confidenceGate` from storage; the
  Settings → Scan form crashes on it too. Replacing a malformed gate with
  `DEFAULT_CONFIDENCE_GATE` at load would fix both, but touches every reader (Kenneth chose the
  message-only option).
- **Step 3/4 parity**: `runStockScan`'s pre-request failure still shows the raw text (pinned by
  `stockScan.test.ts` "withholds the hint from a TypeError thrown before the request was sent").
  Giving it the same message is a one-liner but changes a pinned, shipped behaviour — Kenneth's call.

## 7. What this changes for the user

A Step-5 scan with corrupted saved settings says "Couldn't read your saved scan settings. Open
Settings and press Reset…" instead of a JavaScript error. A backend error reads the same as it does
on Steps 3/4 ("API /api/stock-scan → 422: …", or "…could not reach the backend at …").
