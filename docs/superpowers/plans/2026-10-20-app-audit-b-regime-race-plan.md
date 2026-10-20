# Implementation Plan: APP-AUDIT-B-REGIME-RACE (#386)

**Phase ID:** `APP-AUDIT-B-REGIME-RACE`
**Issue:** #386 (remediation from #350, `regime/findings.md` B3-1)
**Branch:** `board/app-audit-b-regime-race-8d580f0a`
**Touches:** `frontend/lib/regimeFetchOrder.ts` (new), `frontend/app/(frame)/screener/step-1-regime/page.tsx`, `frontend/app/(frame)/screener/step-2-universe/page.tsx`, `frontend/app/(frame)/screener/step-3-direction/page.tsx`, their `__tests__/`

---

## 1. Problem

The shared regime gate lives in `scanStore`: `regime` (raw overall status, TopBar dot),
`regimeDirection` (Step 3's "regime is Bull/Bear vs your direction" banner) and
`combinedRegime` (the direction-aligned verdict read by StepNavBar's Step-1 REJECT
confirmation, RunScanButton's REJECT confirmation, Step 4 Stocks' regime-fit column and
the Step 7 pre-trade rail). Three screener pages fetch `/api/regime` and write it:

| Writer | When | Writes today |
|---|---|---|
| Step 1 `fetchRegime` | every mount, every `markov` settings change, Retry | `regime`, `regimeDirection`, `combinedRegime` unguarded; `regimeSentiment` guarded by the module-level `regimeSentimentRequestSeq`; local `regime` data, `offline`, `regimeFetchFailed` unguarded |
| Step 2 `handleRefresh` | Refresh button | `regime` unguarded |
| Step 3 mount effect | every mount | `regime`, `combinedRegime` unguarded; local `descriptorRef`, `regimeLoadedRef` |

The callbacks deliberately keep running after the page unmounts (the shared reading must
land even when the user moves on). So a request started on an earlier mount can answer
after a later mount's request answered, and its unguarded writes overwrite the newer
reading. Reproduced by the audit (`docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/regime/stale-response.cjs`):
Step 1 Bear request held pending → Step 2 → Step 1 (new Bull request answers, gate PASS) →
old Bear released → page still shows Bull, but `combinedRegime` becomes REJECT and Next
opens the REJECT confirmation. The same overwrite is reachable across pages (Step 1's old
request answering after Step 3's newer one) and across Step 3 mounts.

This is a wrong-verdict-in-front-of-the-user defect (gate-level).

## 2. Rule after the fix

1. **Shared gate fields** (`regime`, `regimeDirection`, `combinedRegime`): only the
   **most recently started** regime fetch from any of Steps 1–3 writes them from its
   response. One module-level counter, shared by all three pages, decides "most recently
   started". An older request answering (or failing) later writes nothing to them.
2. **Every regime response writes all three gate fields together**, through one helper,
   so they never come from different responses. This is a deliberate change for Steps 2
   and 3: Step 3 now also writes `regimeDirection`, and Step 2's Refresh now also writes
   `regimeDirection` and `combinedRegime`. Without it, a Step 2 Refresh or Step 3 fetch
   that supersedes a pending Step 1 request would leave `combinedRegime` /
   `regimeDirection` at a reading older than `regime` (or at PENDING, blocking Next).
   The verdict is computed exactly as today: `alignmentVerdict(context.direction ??
   'Bullish', descriptorFromState(r.omm?.state ?? ''))`, direction read at write time.
3. **Step 1's own reading** (`regimeSentiment`, the page's local regime data, the
   `offline` flag and the Retry banner set by the regime fetch) keeps Step 1's own counter
   (`regimeSentimentRequestSeq`, renamed `step1RegimeRequestSeq`): only the latest Step 1
   request writes them, whether it succeeds or fails. It is separate from the shared
   counter on purpose: sentiment comes only from Step 1, so a later Step 2/3 fetch must
   not stop the latest Step 1 response from delivering it (that would leave the Stocks
   Strategy strip empty after Step 1 → Step 3 navigation, a regression).
4. Step 3's local `descriptorRef` / `regimeLoadedRef` and Step 2's local
   `lastRefreshed` / `refreshError` / `refreshing` are page-local; they are set only when
   that page's request is still the latest shared request, except `refreshing`, which is
   always cleared in `finally` (the button must not stay disabled). A superseded request
   on a mounted page can only happen if another page started a fetch, which needs this
   page unmounted, so in practice these local writes go to an unmounted component; the
   guard keeps the rule uniform.
5. Nothing new resets the gate to PENDING when a request starts (unchanged behaviour:
   the previous verdict stays until the latest response answers).

Synchronous verdict recomputes on a direction change (Step 1's `[direction, regime]`
effect, Step 3's `handleDirChange` and `[context]` effect) are not responses and are
unchanged.

## 3. Changes

### 3.1 `frontend/lib/regimeFetchOrder.ts` (new)

```ts
// Which /api/regime request may write the shared regime gate (APP-AUDIT-B-REGIME-RACE).
// Module-level, not React state: requests outlive the page that started them.
let latestRegimeFetch = 0;

/** Call when a Step 1–3 regime fetch starts; returns its ticket. */
export function beginRegimeFetch(): number { return ++latestRegimeFetch; }

/** True while no later regime fetch has started. */
export function isLatestRegimeFetch(ticket: number): boolean { return ticket === latestRegimeFetch; }

/** Writes regime, regimeDirection and combinedRegime from one response,
 *  only if `ticket` is still the latest regime fetch. Returns whether it wrote. */
export function applyRegimeResponse(ticket: number, r: MarketRegime): boolean
```

`applyRegimeResponse` reads `useScanStore.getState()` at call time, sets
`regime = r.overall`, `regimeDirection = r.regime_direction ?? null`,
`combinedRegime = alignmentVerdict(context?.direction ?? 'Bullish', descriptorFromState(r.omm?.state ?? ''))`.

### 3.2 Step 1 (`step-1-regime/page.tsx`)

In `fetchRegime`: take `ticket = beginRegimeFetch()` and `seq = ++step1RegimeRequestSeq`
at start (keep `setRegimeSentiment(null)` at start, unchanged). On response: return
immediately unless `seq` is the latest Step 1 request; then `setRegimeData(r)`,
`setRegimeSentiment(...)`, `applyRegimeResponse(ticket, r)`. On failure: only if `seq`
is latest: `setOffline(true)`, `setRegimeFetchFailed(true)`, `setRegimeSentiment(null)`.
`setRegimeFetchFailed(false)` at the start of a call is unchanged. Remove the now-unused
`setRegime` / `setRegimeDirection` / `setCombinedRegime` selectors from `fetchRegime`'s
dependencies (the `[direction, regime]` effect keeps `setCombinedRegime`).

### 3.3 Step 2 (`step-2-universe/page.tsx`)

`handleRefresh`: `ticket = beginRegimeFetch()` before the request; on success
`if (applyRegimeResponse(ticket, regime)) setLastRefreshed(...)`; on failure
`if (isLatestRegimeFetch(ticket)) setRefreshError(true)`; `finally setRefreshing(false)`.

### 3.4 Step 3 (`step-3-direction/page.tsx`)

Mount effect: `ticket = beginRegimeFetch()`; on response, return unless
`isLatestRegimeFetch(ticket)`; then set `descriptorRef`, `regimeLoadedRef`, and
`applyRegimeResponse(ticket, r)` (replaces the two direct store writes; adds
`regimeDirection`). `.catch(() => {})` unchanged.

## 4. Tests (written first; each must fail on current `main` code where marked ✱)

New `step-1-regime/__tests__/staleRegimeResponse.test.tsx` (same mocking style as
`regimeSentimentWrite.test.tsx`, deferred promises):

1. ✱ Issue repro: mount A (request Bear, pending) → unmount → mount B (Bull) answers →
   gate PASS, `regimeDirection` B's → A answers Bear → `combinedRegime` PASS, `regime`,
   `regimeDirection` unchanged, banner/headline still B's.
2. ✱ Stale failure: A pending → unmount → B answers → A rejects → no "Regime check
   failed" banner, no offline line, gate unchanged, sentiment unchanged.
3. ✱ In-mount supersede: change `useSettingsStore` `markov` while request A pending
   (new `fetchRegime`, request B) → B answers → A answers → visible headline and gate
   are B's.
4. Newer pending, older answers: A answers while B still pending → gate keeps its prior
   value (not A's) → B answers → B's.
5. Cross-page: Step 1 request A pending → unmount → Step 3 mounts, its request answers
   Bull → A answers Bear → gate is Step 3's; `regimeSentiment` is A's (latest Step 1).

New `step-3-direction/__tests__/staleRegimeResponse.test.tsx`:

6. ✱ Mount A pending → unmount → mount B answers Bull → A answers Bear → gate PASS;
   then `handleDirChange('Bearish')` on B → REJECT (B's descriptor, not A's).
7. Step 3 response writes `regimeDirection`.

New `step-2-universe/__tests__/refreshRegime.test.tsx` (mock heavy children/API as needed):

8. ✱ Refresh on mount A pending → unmount → mount B Refresh answers → A answers → gate
   is B's.
9. Refresh writes all three gate fields and clears `refreshing` even when superseded.

Existing suites stay green unchanged: `regimeSentimentWrite`, `verdictFollowsDirection`,
`vixPercentileDisplay`, `verdictFollowsRestoredContext`, StepNavBar, RunScanButton.

Mutation check (coordinator, before code audit): removing each guard
(`applyRegimeResponse` ticket check; Step 1 `seq` early return; Step 3 early return)
makes at least one ✱ test fail.

## 5. Verification

- `cd frontend && npm run typecheck` clean; `npm run test` full suite green.
- Browser retest of the audit reproduction: run a local copy of `stale-response.cjs`
  (only `executablePath` and port changed) against a dev server on a free port (never
  3001). Expected after fix: `actual_after: "PASS"`, no REJECT dialog. Repeat with mode
  set to Stocks and Pre-Breakout (Steps 1–3 are shared; StepNavBar reads the same
  `combinedRegime`). Evidence saved under
  `docs/superpowers/audits/APP-AUDIT-B-REGIME-RACE/`.

## 6. Out of scope (logged, not fixed here)

- Steps 2 and 3 call `getRegime()` with default Markov parameters while Step 1 passes the
  Settings values (already logged as pre-existing by an earlier reviewer). The ordering
  rule above makes the latest request win regardless; it does not make their
  parameters agree.
- Step 3's `handleDirChange` before Step 3's own regime answers computes a verdict on the
  `'Choppy'` default descriptor (pre-existing, not a stale-response race).
- The gate keeps the previous verdict while a new request is pending or after it fails
  (pre-existing; the failure banner text "Next is blocked" is only true on a first load).

## 7. Tickets

One build ticket (the helper and its three adopters are inseparable: the rule only holds
when all writers share the counter). Size S, complexity 4.
