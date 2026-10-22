# Shared controls and Search Profiles — observed findings

Audit baseline: `880c8441841cc22d5090cdc5f984e4cf7e3d9a8d`. Evidence-only work;
no product fixes or calibration. All findings below remain **not retested after
fix**. Coordinator owns publication and issue numbers. Numeric/persistence
findings are separated from presentation. [Coverage](coverage.md) records limits.

## Numbers and persistence

### C1 — Options million-dollar market-cap input uses dollars (#368)

Owner: Lane B; shared UI presentation: Lane J. Set Step 2 cap unit M and minimum
cap 25; run Options. Expected `min_cap_usd: 25000000`; actual `25`. The same
saved-profile resolver sends 25. `resolveOptionsScanRequest.ts:98` uses 1 for M,
while B uses 1e9. The UI request, source request and independent USD-unit oracle
agree on this defect: `browser-output.json` check `million cap conversion`,
`source-output.json` check `scheduled million cap`. This is conversion, not
threshold calibration (#187). Retest both min/max and M/B through manual and
saved requests, reload and a backend read-back filter fixture.

### C2 — Stocks drops all Step 2 price/cap filters

Owner: Lane B. Apply a Stocks profile with Custom `aapl, AAPL; msft\nBRK.B`,
minimum price `0`, minimum cap `25 M`. Both manual `runStockScanWithContinuation`
and scheduled `resolveProfileToScanRequest` omit `min_price` and `min_cap_usd`;
expected 0 and 25000000. The backend StockScanRequest supports these fields, but
ResolvedStockScanContext/buildStockScanRequestBody has no filter inputs.
`source-output.json` records manual and scheduled requests plus four failed
price/cap checks. The manual `['Custom']` universe is the **existing #343**,
recorded separately; the scheduled request resolves the three tickers correctly.
Do not open another Custom-universe defect. Retest all four filter fields in both
Stocks entry paths and preserve explicit zero versus absent. No backend scan of
real providers was run.

### C3 — A malformed current-version profile can crash Step 3

Owner: Lane B; visible failure: Lane J. In isolated localStorage, put a version-5
profile array containing two otherwise committed profiles, with the first
`updatedAt: null`; open Step 3. Expected invalid metadata rejected/skipped with
safe UI; actual Search Profile control disappears and the page reports a client
error. SearchProfileBar sorts via `b.updatedAt.localeCompare(a.updatedAt)` without
shape validation (`SearchProfileBar/index.tsx:38`). A one-profile store probe
also retains invalid metadata. See `browser-output.json`, separately seeded
`browser-continuation-output.json`, `source-output.json`, and
`malformed-profile.png`. This requires a malformed local payload; supported
unmodified pack operations do not generate that payload. Retest parseable
invalid shape, null timestamps, two rows, unknown versions, and a valid-profile
recovery path. Unparseable JSON retains previous in-memory state; the restore
script backs it up and recovers the committed pack.

### C4 — Score-weight percent inputs reach the scorer as multipliers

Owner: Lane B; owning scoring lane should be coordinated by parent programme.
Step 3 labels weight inputs `%` with bounds 0–100. Set Trend weight 40 in
Options; request sends `overrides.weight_trend: 40`. The backend assigns it
straight to the weight (`stock_scorer.py:1131`). Its YAML weights are fractions.
With explicitly fixed component scores Trend 80, Pullback 60, Trigger 40, Event
20, Vol 100, the real scorer's untouched Swing sum is 59. Changing Trend to 40%
should contribute 32, giving 67 with other weights unchanged; actual score is
3235 (Trend contribution 3200). This is unit propagation, not a proposal for
recalibrating weights. `parameter-output.json` captures the request;
`backend-parameters-output.json.weightFixture` contains actual full explanations
and the independent arithmetic. The fixture stubs component outputs to isolate
unit conversion; it is not an indicator-accuracy test. Stocks renormalizes its
non-event weights, so literal 40 also changes their relative proportions; the
3235 example is specifically Options. Retest all five controls with explicit
0/100/default/custom and independent contribution arithmetic in each mode.

### C5 — Stocks ignores the Step 3 confidence caution/reject edits

Owner: Lane B. Keep the Settings confidence gate enabled at 50/35 and set the
panel's `confidence_caution_below` or `confidence_reject_below` override to 0.
Expected request uses 0; actual Stocks request still uses 50/35. The overrides
are excluded from STOCKS_SCORER_KEYS; the top-level fields are copied from
`ctx.confidenceGate` instead of the panel values
(`resolveStockScanRequest.ts`, return fields). `parameter-output.json` records
both failures and complete profile/request pairs, with backend-parsed read-back
in `backend-parameters-output.json.requestTrace`. Options handles these overrides.
Retest non-default, zero, absent, gate-disabled and saved-profile/manual parity.
The backend applies the request thresholds; this finding is the frontend's
incorrect effective request, not a claim about confidence calibration.

### C6 — All three Entry Quality controls are inert at the backend plan

Owner: Lane B; coordinate scoring ownership. Set Options Entry Quality minimum
premium 5, slippage 0 and spread tolerance 0. The valid ScanRequest retains the
three values in `overrides`, but no backend app consumer reads those key names.
`trade_plan.py:155` calls `assess_entry` without EntryConfig and its function
signature has no entry override input. For bid .99/ask 1.01/mid 1, the actual
shared trade plan returns PASS and max fill 1.03 under YAML .10/.03/.10. Applying
the user's independent thresholds requires a premium rejection and max fill
1.00. `backend-parameters-output.json.entryFixture` records actual/default and
explicitly edited EntryConfig outcomes; `parameter-output.json` records payload.
The fixture invokes the same production plan helper, not the provider-facing
scan endpoint. Retest all three controls through endpoint-to-card behavior,
including zero, absent/default and saved profile read-back. No threshold changes
are proposed here.

## Presentation and usability

### C7 — Stop percentages display fractions with a percent unit

Owner: Lane J presentation; Lane B owns the affected controls. Both Bullish and
Bearish stop defaults render text `0.03%` with input `0.03`, while the backend
uses the value as a fraction, meaning **3%**. The hint also says default 3%.
`browser-parameters-output.json.rows[0]` records both exact row texts;
`backend-parameters-output.json` maps the fraction to reward-risk configuration.
`page.tsx` defines `%` as the unit but ParamRow prints the raw value. A user
entering `3` for 3% is clamped to `1`, which means 100% in the backend. Retest
consistent label/input/default/payload units on both directions, including
.005/1 boundary values; changes must preserve the intentional stop distances.

## Observed limitation, not a new defect

A stale mounted tab overwrites a profile added externally to localStorage when
it next saves from its stale in-memory array. Measured expected-preservation
check fails, but `docs/search-profiles/import-search-profiles.js` and its
instructions require closing/reloading screener tabs for the external import.
This unsupported stale-writer scenario is recorded openly in browser evidence;
it is not a new supported-import failure. Restore merge-by-id, exact backup,
custom preservation, and corrupt-JSON recovery pass under the supported workflow.

The committed 18-pack is Options-only. Stocks profile calibration/pack creation
belongs to #188; Options calibration belongs to #187. Their future values were
not substituted into this audit. Existing #343 is reused, not fixed here.
