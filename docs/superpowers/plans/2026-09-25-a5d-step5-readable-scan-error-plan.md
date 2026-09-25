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

`frontend/app/(frame)/screener/step-5-strategy/page.tsx` `runScan` (`:212-262`):

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
   and throws. Step 5 renders `TypeError: Cannot read properties of null (reading '…')`. A
   non-null but malformed gate (e.g. `{ enabled: true }` with no `atrMult`) throws the same way in
   `atrMultForHorizon` whenever Step 3 has no full ATR override. Before A5b, Step 5 never read the
   gate, so this is a regression A5b introduced. [R1-1] `scanStore.scanOverrides` is NOT a reachable
   source: it is not in `scanStore`'s `partialize` (`scanStore.ts:684-724`), and a null there would
   crash the page's render (`page.tsx:122-123`) before `runScan` ever ran. Other persisted fields
   (e.g. a non-string `scanStore.context.horizon`, `.split` at `page.tsx:228`) can also throw before
   the request; they get the same message, which names the likely cause, not the only one.
2. **A request failure shows an `Error: ` prefix and no hint.** `String(new Error('API
   /api/stock-scan → 422: …'))` is `Error: API /api/stock-scan → 422: …`; a transport failure is a
   bare `TypeError: Failed to fetch` without Step 3/4's "could not reach the backend at …" hint.

Why the message cannot say "Settings → Strategy scan": the gate is edited in Settings → **Scan**
(`ScanForm`, `settings/page.tsx:232`), which itself reads `confidenceGate.cautionBelow` during
render, so it would crash on the same null. The one reset that works is the footer **Reset**
(`resetToDefaults`, `settings/page.tsx:84`), which the page renders regardless of section.
[R2-10] The recovery path works because `SettingsPage` opens on `'brokers'`
(`settings/page.tsx:44`) and `BrokersForm` does not read the gate; clicking Scan first crashes the
page into `(frame)/error.tsx`. Changing the default section would silently break this path.

[R2-1/R2-2] What Reset restores (`settingsStore.ts:441-462`) is the `settingsStore` values only:
broker config and the paper/live broker accounts (ids, tokens), `markov` (regime), the confidence
and fundamentals gates, contract/shortlist limits, premium stop / target profit, spreads, alert
dedup, and the dead `scheduleConfig` (no reader outside the store). It does NOT touch backend
scheduled scans (`ScheduledScansSection`), Risk (`riskStore` + backend), Strategy-scan params
(`scanParamsStore`), theme, backend broker credentials, the ingestion schedule or tuning. The
message names the user-visible parts: broker accounts, regime and gate settings.

## 2. Change

### 2a. `frontend/lib/stockScan.ts` — one exported constant, next to `stockScanFailureReason`

```ts
/** What a manual scan shows when building its request from the saved stores
 *  threw — nothing was sent. The likely cause (not the only possible one) is a
 *  malformed persisted setting, e.g. `confidenceGate: null`. Points at the
 *  footer Reset because the Settings → Scan form reads the same gate while
 *  rendering. Reset also restores the broker accounts, regime and gate
 *  settings, so the message says so. A5d. */
export const STOCK_SCAN_SETTINGS_INVALID =
  "Couldn't read your saved scan settings. Open Settings and press Reset to restore the defaults (this also resets your broker accounts, regime and gate settings).";
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
button is clicked, the test waits for the loading state to clear. [R2-5] Malformed gates are set
with `as never` (the sibling's style, `a5bSharedRequest.test.tsx:68`); ts-jest type-checks the
file, so an uncast `confidenceGate: null` fails the compile.

- **T1 — `confidenceGate: null`.** The rendered error is exactly `STOCK_SCAN_SETTINGS_INVALID`;
  no text matching `/TypeError|Cannot read/` is in the document; `postStockScan` was never called;
  `console.error` was called once with the page's prefix and a `TypeError`.
- **T2 — a non-null malformed gate** `{ enabled: true }` (no `atrMult`), with `scanOverrides`
  carrying no `confidence_atr_mult_*` keys so the builder reaches `atrMultForHorizon` → same
  message, no post, `console.error` once. [R1-1: replaces the unreachable `scanOverrides: null`.]
- **T3 — API error after the request.** `postStockScan` rejects
  `new Error('API /api/stock-scan → 422: universe is empty')` → the rendered error is exactly
  `API /api/stock-scan → 422: universe is empty` (no `Error: ` prefix, not the settings message);
  `console.error` NOT called.
- **T4 — transport failure after the request.** `postStockScan` rejects
  `new TypeError('Failed to fetch')` → the rendered error is exactly `stockScanFailureReason(new
  TypeError('Failed to fetch'))`, and contains `could not reach the backend at
  http://localhost:8000`. A `TypeError` after the post is NOT the settings message (this pins the
  `reachedRequest` boundary from the other side); `console.error` NOT called.
- **T5 — recovery.** After T1's failure, restore a valid gate and click again: the post happens,
  the error line is gone (the existing `setError(null)` at the start of `runScan`). [R2-4] The test
  waits for `getLastStockScanStatus` to have been called TWICE (the first failing run's `finally`
  already called it once), then for the button to be enabled again, so no success-path work runs
  after the console spy is restored.

### Mutation checks (each must turn at least one test red, then be reverted)

| # | Mutation | Expected red |
|---|---|---|
| M1 | restore `setError(String(e))` | T1, T2, T3, T4 |
| M2 | `reachedRequest = true` moved above `buildStockScanRequestBody` | T1, T2 |
| M3 | `reachedRequest = true` moved after the `await` | T3, T4 [R2-7] |
| M4 | always `STOCK_SCAN_SETTINGS_INVALID` | T3, T4 |
| M5 | always `stockScanFailureReason(e, reachedRequest)` | T1, T2 |
| M6 | drop the `console.error` | T1, T2 |
| M7 | drop the `if (!reachedRequest)` guard on the `console.error` | T3, T4 |

## 4. Verification

`npm run typecheck`, the full Jest suite (count = main's + 5), `python3 scripts/state.py` exit 0.
Backend untouched.

## 5. State

New phase `A5D-STEP5-READABLE-SCAN-ERROR`, `depends_on: [A5B-STEP5-SHARED-REQUEST]`, verify
`defect_marker` on `setError\(String\(e\)\)` in the Step-5 page while unbuilt; switched to a
presence probe on `STOCK_SCAN_SETTINGS_INVALID` in that page by the build commit. [R2-3] The same
commit moves `status` off `planned` (to `built`, then `shipped` at the clean code round) and
updates `audit_rounds` and the note — a present probe with status `planned` is drift
(`state.py:626-636`). `active_phase` points at it.

## 6. Out of scope — logged, not fixed

- **Hydration repair**: `settingsStore` accepts a non-object `confidenceGate` from storage; the
  Settings → Scan form crashes on it too. Replacing a malformed gate with
  `DEFAULT_CONFIDENCE_GATE` at load would fix both, but touches every reader (Kenneth chose the
  message-only option).
- **Step 3/4 parity**: `runStockScan`'s pre-request failure still shows the raw text. No
  `runStockScan` test drives a malformed gate (`stockScan.test.ts:451` unit-tests
  `stockScanFailureReason(…, false)` only), so giving Step 3/4 the same message is cheap; it is
  outside Kenneth's Step-5-only decision, so it is logged for him.
- [R2-8] **A saved search profile can reinstate a malformed gate after Reset.**
  `searchProfileSnapshot.ts:31` snapshots `{ ...settings.confidenceGate }` (`{}` for a null gate);
  applying the profile (`:105`) writes it back, and scheduled runs of that profile read it
  (`scanScheduleResolve.ts:89/123`).
- [R2-9] **A malformed gate can silently disable the gate (pre-existing).** `{}` /
  `{ enabled: undefined }` with a full Step-3 ATR override does not throw; the builder sends no
  `confidence_*_below`, so the scan runs ungated (`resolveStockScanRequest.ts:128-129`), against
  the spirit of "no fallback to scan without a gate". A5d does not change it.

## 7. What this changes for the user

A Step-5 scan with corrupted saved settings says "Couldn't read your saved scan settings. Open
Settings and press Reset… (this also resets your broker accounts, regime and gate settings)" instead of a JavaScript error. A backend error reads the same as it does
on Steps 3/4 ("API /api/stock-scan → 422: …", or "…could not reach the backend at …").

## Audit record

- Round 1 (plan, fresh subagent): 1 blocking — T2 (`scanOverrides: null`) unreachable and crashes
  the render; replaced by a malformed non-null gate [R1-1]. Non-blocking, all folded in: line ref
  `:212-262`; §6 "pinned" overstated; message now says Reset restores all settings (Reset wipes
  schedules, gates, spreads, not just brokers); M7 + `console.error` not-called in T3/T4; T5 waits
  for `finally`; the constant's comment says "likely cause".
- Round 2 (plan, fresh subagent, prototyped T1/T3/T4/T5 against a scratch copy): 1 blocking — the
  owner-confirmed wording said Reset clears scheduled scans; it does not (backend schedules; the
  only schedule field it clears, `scheduleConfig`, is dead). Kenneth re-chose the wording
  (decision A5D-READABLE-MESSAGE-2026-09-25, amended): "…(this also resets your broker accounts,
  regime and gate settings)." [R2-1]. Round 1's "Reset wipes schedules" was wrong. Non-blocking,
  all folded in: what Reset does/does not reset [R2-2]; §5 status move [R2-3]; T5 counts calls
  [R2-4]; `as never` casts [R2-5]; `:228` [R2-6]; M3 also reddens T3 [R2-7]; search-profile
  reinstatement and silent ungated scan logged in §6 [R2-8, R2-9]; recovery path depends on the
  default Brokers section [R2-10].
