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

*(Revised after plan round 1: F1 parameter parity, F2 "newest applied" instead of
"newest started". Round-1 text is in git history at `674ff931`.)*

1. **One request shape.** Steps 1, 2 and 3 all fetch the gate reading the same way:
   `api.getRegime('intraday', { lookback, threshold, smoothing })` with the Markov values
   from `useSettingsStore.getState().markov` at request time. Today Steps 2 and 3 call
   `getRegime()` with the backend defaults (20 / 0.02 / 0) while Step 1 sends the
   Settings values, so a "conservative" or "aggressive" preset gives Steps 2/3 a
   different OMM state, `regime_direction` and verdict than Step 1 (round-1 F1). The
   backend's `horizon` query parameter does not affect the response
   (`backend/app/routers/regime.py:123`, described only), so `'intraday'` is kept for
   all three as Step 1 sends it. After this, every response the ordering rule compares
   comes from the same model.
2. **Shared gate fields** (`regime`, `regimeDirection`, `combinedRegime`): every regime
   fetch from Steps 1–3 takes a ticket from one module-level counter when it **starts**.
   A response writes the gate fields only if its ticket is **newer than the ticket of the
   last response written** (`ticket > lastAppliedTicket`), and then records its ticket.
   So an older response can never replace a newer one that already landed (same mount,
   across mounts, across pages), but it still fills the gate while a newer request is
   pending or if the newer request fails (round-1 F2: "newest started" would have left
   the gate at PENDING or at an even older verdict, losing the REJECT confirmation).
   Failures write nothing to the gate fields (unchanged).
3. **Every response writes all three gate fields together**, through one helper, so they
   never come from different responses. Deliberate change for Steps 2 and 3: Step 3 now
   also writes `regimeDirection`; Step 2's Refresh now also writes `regimeDirection` and
   `combinedRegime`. With rule 1 these are the same reading Step 1 would write, so this
   only keeps the three fields from disagreeing. The verdict is computed exactly as
   today: `alignmentVerdict(context.direction ?? 'Bullish', descriptorFromState(r.omm?.state ?? ''))`,
   direction read at write time.
4. **Step 1's own reading** (`regimeSentiment`, the page's local regime data) uses a
   second, Step-1-only module-level ticket pair (`step1RegimeRequestSeq` and
   `step1LastAppliedSeq`, replacing `regimeSentimentRequestSeq`), with the same "newer
   than last applied" rule. It is separate from the shared counter on purpose:
   sentiment comes only from Step 1, so a later Step 2/3 fetch must not stop a Step 1
   response from delivering it (otherwise the Stocks Strategy strip stays empty after
   Step 1 → Step 3 navigation). `setRegimeSentiment(null)` when a Step 1 request starts
   is unchanged.
5. **Step 1 failure**: the Retry banner, the `offline` line and `regimeSentiment = null`
   are written only if the failing request is the latest Step 1 request **started**
   (`seq === step1RegimeRequestSeq`), as the sentiment write is today. An older request
   failing after a newer one started writes nothing.
6. **Page-local state elsewhere**: Step 3 sets `descriptorRef` / `regimeLoadedRef` only
   when its response was applied to the gate (helper returned true). Step 2 sets
   `lastRefreshed` only when applied; `refreshError` on failure and `refreshing = false`
   in `finally` are unchanged (they describe that button's own request).
7. Nothing new resets the gate to PENDING when a request starts (unchanged).

Synchronous verdict recomputes on a direction change (Step 1's `[direction, regime]`
effect, Step 3's `handleDirChange` and `[context]` effect) are not responses and are
unchanged.

## 3. Changes

### 3.1 `frontend/lib/regimeFetchOrder.ts` (new)

```ts
// Which /api/regime response may write the shared regime gate (APP-AUDIT-B-REGIME-RACE).
// Module-level, not React state: requests outlive the page that started them.
let nextTicket = 0;
let lastAppliedTicket = 0;

/** The gate reading request every screener step sends (Settings Markov values). */
export function fetchGateRegime(): Promise<MarketRegime>   // api.getRegime('intraday', {lookback, threshold, smoothing})

/** Call when a Step 1–3 regime fetch starts; returns its ticket. */
export function beginRegimeFetch(): number

/** Writes regime, regimeDirection and combinedRegime from `r` only if `ticket` is newer
 *  than the last applied ticket; records it. Returns whether it wrote. */
export function applyRegimeResponse(ticket: number, r: MarketRegime): boolean
```

`fetchGateRegime` reads `useSettingsStore.getState().markov` at call time.
`applyRegimeResponse` reads `useScanStore.getState()` at call time.

### 3.2 Step 1 (`step-1-regime/page.tsx`)

`fetchRegime`: `ticket = beginRegimeFetch()`, `seq = ++step1RegimeRequestSeq`,
`setRegimeSentiment(null)`, then `fetchGateRegime()` (replaces the inline
`api.getRegime('intraday', …markov)`; `markov` stays a `useCallback` dependency so a
Settings change still refetches). On response: `applyRegimeResponse(ticket, r)`; then if
`seq > step1LastAppliedSeq`: record it, `setRegimeData(r)`,
`setRegimeSentiment(sentimentFromRegime(r, …))`. On failure: only if
`seq === step1RegimeRequestSeq`: `setOffline(true)`, `setRegimeFetchFailed(true)`,
`setRegimeSentiment(null)`. Remove the now-unused `setRegime` / `setRegimeDirection`
selectors (the `[direction, regime]` effect keeps `setCombinedRegime`).

### 3.3 Step 2 (`step-2-universe/page.tsx`)

`handleRefresh`: `ticket = beginRegimeFetch()`; `regime = await fetchGateRegime()`;
`if (applyRegimeResponse(ticket, regime)) setLastRefreshed(...)`; catch and finally
unchanged.

### 3.4 Step 3 (`step-3-direction/page.tsx`)

Mount effect: `ticket = beginRegimeFetch()`; `fetchGateRegime().then(r => { if
(!applyRegimeResponse(ticket, r)) return; descriptorRef.current = …; regimeLoadedRef.current
= true; })`. `applyRegimeResponse` replaces the two direct store writes and adds
`regimeDirection`. `.catch(() => {})` unchanged.

## 4. Tests (written first; ✱ = must fail on the current code)

Test files reset the module-level counters between tests by `jest.isolateModules` or by
reading only relative order (tickets only ever grow, so tests must not assume absolute
values); `lib/regimeFetchOrder.ts` gets its own unit test.

`frontend/lib/__tests__/regimeFetchOrder.test.ts`:

1. Tickets grow; a response applies only if newer than the last applied; an older one
   arriving after a newer one applied returns false and writes nothing; an older one
   arriving while the newer is pending applies.
2. Writes all three fields; verdict uses the context direction at write time.
3. `fetchGateRegime` sends `'intraday'` and the Settings Markov values (non-default
   preset).

`step-1-regime/__tests__/staleRegimeResponse.test.tsx` (mocking style of
`regimeSentimentWrite.test.tsx`, deferred promises):

4. ✱ Issue repro: mount A (Bear, pending) → unmount → mount B (Bull) answers → gate PASS
   → A answers Bear → `combinedRegime` PASS, `regime`, `regimeDirection` still B's,
   banner headline still B's.
5. ✱ In-mount supersede: change `useSettingsStore` `markov` while request A pending
   (request B) → B answers → A answers → headline, sentiment and gate are B's.
6. ✱ In-mount stale failure: as 5, then A rejects after B answered → no "Regime check
   failed" banner, no offline line, gate and sentiment B's.
7. Newer pending, older answers (F2): A answers Bear while B pending → gate REJECT (A's);
   B answers Bull → PASS. And: A answers, then B rejects → gate stays A's verdict.
8. Cross-page: Step 1 request A pending → unmount → Step 3 mounts, answers Bull → A answers
   Bear → gate is Step 3's (PASS, BULL); `regimeSentiment` is A's.

`step-3-direction/__tests__/staleRegimeResponse.test.tsx`:

9. ✱ Mount A pending → unmount → mount B answers Bull → A answers Bear → gate PASS; then
   clicking the Bearish direction button on B → REJECT (B's descriptor, not A's).
10. ✱ Step 3's request sends `'intraday'` and the Settings Markov values; its response
    writes `regimeDirection`.

`step-2-universe/__tests__/refreshRegime.test.tsx` (mock heavy children/API as needed):

11. ✱ Refresh on mount A pending → unmount → mount B Refresh answers → A answers → gate
    is B's.
12. ✱ Refresh sends the Settings Markov values and writes all three gate fields;
    `refreshing` clears when the request answered but was not applied.

Existing suites stay green unchanged: `regimeSentimentWrite`, `verdictFollowsDirection`,
`vixPercentileDisplay`, `verdictFollowsRestoredContext`, StepNavBar, RunScanButton.

Mutation check (coordinator, before code audit): replacing `>` with `>=` or removing the
ticket check in `applyRegimeResponse`, removing Step 1's `seq` check, and restoring the
argument-less `getRegime()` in Step 2/3 each make at least one test fail.

## 5. Verification

- `cd frontend && npm run typecheck` clean; `npm run test` full suite green.
- Browser retest of the audit reproduction:
  `docs/superpowers/audits/APP-AUDIT-B-REGIME-RACE/stale-response-retest.cjs` (a copy of
  `stale-response.cjs` with a system browser, a base URL, a mode click per run, and a
  fixed settle instead of waiting for REJECT) against a dev server on port 3027 (never
  3001), in Options, Stocks and Pre-Breakout. Baseline on the unfixed branch (recorded in
  `stale-response-baseline-output.json`): PASS → REJECT and the REJECT dialog in all three
  modes. Expected after the fix: PASS stays PASS, no dialog, in all three.

## 6. Out of scope (logged, not fixed here)

- Step 3's `handleDirChange` before Step 3's own regime answers computes a verdict on the
  `'Choppy'` default descriptor (pre-existing; not a response-ordering race and not made
  worse here).
- The gate keeps the previous verdict while a new request is pending or after it fails
  (pre-existing; the failure banner text "Next is blocked" is only true on a first load).
- Step 1's sentiment is cleared when the latest Step 1 request fails even if an older one
  answered meanwhile (matches the visible "Regime check failed" state).

## 7. Tickets

One build ticket (the helper and its three adopters are inseparable: the rule only holds
when all writers share the counter and the request shape). Size M, complexity 4.
