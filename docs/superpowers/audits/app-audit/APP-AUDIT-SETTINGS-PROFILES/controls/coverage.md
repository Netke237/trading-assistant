# Shared control and Search Profile coverage

Source baseline `880c8441841cc22d5090cdc5f984e4cf7e3d9a8d`; no product-file
changes. Node probes use real frontend stores/request builders with in-memory
localStorage; browser probes use isolated Chromium storage and **fulfill every
/api request locally**. These are deterministic UI/request checks, not live scan
or provider checks. Python 3.11.16 invokes real backend schemas and helpers
without a server, database, provider calls, or writes to config. Source/config
SHA256 values are in `source-output.json.hashes` and
`backend-parameters-output.json.hashes`. Browser/Next/Playwright versions are in
`browser-output.json` and `browser-parameters-output.json`.

## Reproduction

From repository root, with prepared frontend node_modules and Python 3.11 venv:

```sh
node docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/source-probe.cjs
node docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/parameter-probe.cjs
backend/.venv/bin/python docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/backend-parameters.py
node docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/browser-probe.cjs
node docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/browser-parameters.cjs
```

Browser commands need an existing isolated Next dev server at
`http://127.0.0.1:3027` (or AUDIT_ORIGIN; the second-origin restart check is
explicitly localhost:3027). No backend needs to run because all API boundaries
are mocked. Chromium executable `/usr/bin/chromium` is used. Server was restarted
after an unresponsive earlier server. The lifecycle reload wait also needed a
harness correction: wait for the preceding Step2 Next navigation to commit
before reloading, otherwise reload cancels the navigation and opens Step2.
`browser-initial-output.json` preserves the
original 44-check run, including its reload timeout, without absolute stack
paths. Its later steps were **not run**. `browser-continuation.cjs` is a separate
follow-up seeded with the pack and a synthetic Stocks profile; it independently
checks ten late operations and is **not** evidence of an uninterrupted earlier
custom lifecycle. The completed `browser-probe.cjs` run is the lifecycle authority;
it preserves the actual UI-created Stocks and stale-writer custom profiles
through supported restore, then checks exact read-back after browser restart.

## Exact result scope

- `source-output.json`: 69 assertions, 62 pass / 7 fail, no fatal. Failures:
  million conversion, malformed current profile retained, existing #343 manual
  Custom universe, and missing manual/scheduled Stocks price/cap fields.
- `parameter-output.json`: 59 assertions, 57 pass / 2 fail, no fatal. Includes
  56 editable definitions captured through real stores and profile snapshots;
  the two failures are Stocks confidence edits. Its matrix inventories **all
  66 definitions**, defaults for seven preset keys, per-mode requests for absent,
  null, zero, min/max and custom numeric values; boolean false/true and every
  select option. These injected store cases are broader than supported typed UI
  input; they are not all backend-valid or claimed numeric successes. The source
  Stocks strategy-tolerance zero is explicitly rejected by backend validation
  (`unsupportedStrategyZero`); preserving zero in transport does not mean it is
  a valid strategy value.
- `backend-parameters-output.json`: 18 assertions, 15 pass / 3 fail. Failures:
  percent-weight unit, Entry Quality premium verdict, Entry Quality max fill.
  Captures all 66 definitions' effective backend reader/config paths or explicit
  read-only/unused route; final scorer config for Intraday/Swing/Position and
  custom values, contract cast semantics, shared gates, reward-risk null/zero.
  Only weight aggregation uses mocked component outputs; expected arithmetic is
  separately specified. Other readers use shipped YAML and actual helpers.
- `browser-parameters-output.json`: 110 assertions, 110 pass, no fatal. Observed
  66 unique definition keys across additive/crossover/relative-strength views;
  edited all 55 controls other than trend-method plus exercised all three trend
  methods. Saved snapshot checks cover those 55 edits. Numeric below-min/zero/
  above-max/empty behavior covers 13 representative controls, plus section
  collapse/expand and reset. Preferred Liquidity has UI custom edits and backend
  0/.5/min/max fixtures rather than a separate browser clamp loop.
- `browser-continuation-output.json`: 10 assertions, 8 pass / 2 observed fail,
  no fatal. Malformed-profile crash is a defect; stale-tab overwrite is the
  documented unsupported limitation. This separate seed is disclosed above.
- `browser-output.json`: 56 assertions, 53 pass / 3 observed fail, no fatal.
  Failures are million conversion, malformed metadata crash, and the documented
  unsupported stale-tab preservation case. A stale-tab preservation failure
  records a documented unsupported operation, not a supported restore defect.

## Surface and state reconciliation

| Surface / state | Result and evidence |
| --- | --- |
| Step 1 regime numerical/probability gates, loading/stale data, all modes | Separate `../regime/` evidence; not independently duplicated here. |
| Step 2 preset/custom universe | SP500, Custom normalization/dedupe, empty Custom and empty Watchlist UI exercised. Manual Stocks Custom failure reuses #343. NDX100/DOW30 individual UI clicks not run; source preset resolution is direct pass-through. |
| Step 2 min/max price/cap, clear, M/B | Raw fields frozen in profile and request inputs; zero/absent source and zero-price/M-cap UI captured. Clear filters empties inputs. M conversion fails C1; Stocks drops filters C2. B source multiplier inspected; separate real-provider filtering and all pair-order validation not run. |
| Step 3 direction/horizon/presets/custom | All six presets plus Custom, Bullish/Bearish pack paths and explicit rounded custom hold read-back. Requests retain holding preset and collapse Quarterly/SemiAnnual/Annual to Position scoring. |
| Execution panel expanded/nested/conditional | 66 unique rows observed across three methods; both STOCKS/OPTIONS sections and subgroup values captured, section collapse/expand tested. Read-only/redundant rows carry no direct editing. Same all-section rows can render twice; inventory counts unique keys. |
| Execution number normal/default/custom/zero/empty/boundary | Full source map + 55 UI custom snapshots + 13 representative browser clamp loops. Empty resets to default; zero clamps where min>0. Confidence/Entry/weight defects recorded; passing UI transport is not backend correctness. |
| Execution null/absent | Source requests explicitly record null and absence for every editable definition. Null is injected into untyped persisted/profile data, not enterable through number input. Backend null semantics executed for event/IV/RR/regime/fundamentals; arbitrary scorer nulls are unsupported, not claimed passed. |
| Profile pack | All 18 stable IDs, modes, store update/rename/delete/apply and UI request fields exercised. Pack is Options-only; mode filtering and hidden Pre-Breakout bar verified. No Stocks pack exists (#188). |
| UI custom CRUD | Trimmed create; disabled blank save; rounded custom hold/update; rename retains ID; delete cancel/confirm; actual custom Stocks profile created. |
| Restore / backups / legacy | Merge-by-id restores pack names, preserves custom Stocks, backs up exact pre-import bytes. Unreadable JSON backed up and pack recovered. Store versions 0/2/3/4 migration checked. Parsed current-v5 bad metadata retained/crashes (C3). Unknown future versions not run. |
| Profile loading / empty / cancel / failure | Empty list exercised; save is local synchronous state so network loading/HTTP failure N/A. Delete cancel tested. Quota-exceeded/localStorage write failure not run. |
| Scan loading / error / stale mutation | Mock 503 leaves retry enabled; pending scan disables profile apply but direction remains mutable. Captured frozen request direction versus live direction. Result-card gate/display interpretation of stale async data belongs to regime/results evidence; not claimed passed by this check. There is no Step3 cancel action, so cancel UI N/A. |
| Same-origin reload / browser process restart | Completed browser lifecycle checks reload and a real persistent Chromium process close/reopen with exact saved profile data. Additional origin has null Search Profile key. These are browser-local profiles, not backend-persisted accounts. |
| Current versus frozen | Saved snapshot remains at prior shortlist 10 when current Settings becomes37; saved schedule resolves10. Current universe store and scanOverrides are non-persisted; saved profiles capture them explicitly. Stored result request and current controls are distinct; no claim that all current controls survive reload. |
| Backend restart / failed config save rollback | N/A to localStorage-only Search Profiles; Settings isolated real-backend restart/rollback is in `../settings/`. No backend account profile synchronization exists in audited code. |
| Real provider, live model, broker, notifications | Not run here; provider access isn't needed for deterministic UI/request audit. No order or notification sent. |

## Per-family UI → store → wire → backend map

All editable definitions use `scanStore.scanOverrides`; the Search Profile
snapshot copies that map and its JSON persists in `bamendjou:search-profiles`
version5. The current override map itself does **not** persist across reload.
See `parameter-output.json.matrix` for every individual definition and exact
before/after route, and `backend-parameters-output.json.effective` for field
paths/defaults/custom observations. A wire route does not prove an effect.

| Family (definition count) | Request route and backend effective reader |
| --- | --- |
| Score Weights (5) | `overrides.weight_*` → `stock_scorer.score_stock` weights; C4 unit failure. Stocks excludes event weight and normalizes the rest. |
| Score Gate (1) | Stocks top-level `min_stock_score` → `stock_scan._min_score_drop`; Options intentionally strips it. |
| Trend (17) | `overrides` → scorer `trend.method`, `trend.crossover`, `trend.additive`, `trend.relative_strength`; ma_type controls crossover MA function. Method-specific rows shown conditionally. |
| Pullback (4) | Lookback/ATR through scorer pullback cfg; rsi_period read-only Trigger default. Require reversal bool routes top-level in Stocks → stock_scan strategy mapping `require_reversal`; Options forwards an unused scorer override (Stocks strategy control). |
| Trigger (6) | MACD/RSI edits through scorer trigger cfg; volume baseline/multiplier read-only. |
| Event (5) | Two overrides → `stock_scorer.effective_event_window`; earnings/FOMC/dividend redundant rows read-only. Stocks event score weight0; earnings veto still uses event/holding window. |
| Volatility (4) | Options two override ceilings → scorer vol cfg, rank/absolute selected by basis. Intraday N/A; Stocks resolver excludes options IV ceilings. Lookback/HV rows read-only. |
| Confidence (4) | Top-level caution/reject + ATR pair. Options reads edits; Stocks caution/reject reads Settings instead (C5). ATR both-or-neither → scan and stock_scan confidence calls. |
| Contract (7) | Five editable `overrides` → `contract_validator` hard-reject fields; min/maxDTE read-only from hold range → scan DTE window. Stocks intentionally excludes option-contract fields. |
| Preferred Liquidity (3) | `overrides` → contract soft-rank rules; fractional .5 preference becomes1, zero means no preference. |
| Regime Gate (2) | Top-level headwind fields → shared `services.regime_gate.resolve_regime_gate`, zero explicit, null uses YAML. |
| Fundamentals Bearish (2) | Top-level fields → shared `resolve_fundamentals_gate`, applied only for Bearish direction; zero preserved. |
| Entry Quality (3) | Options forwards `overrides.entry_*`, but backend plan ignores them (C6). |
| Reward/Risk (3) | `overrides.rr_*` → config_loader merge/target resolver; null skips, invalid zero stop/target rejected; fractions stay fractions. UI percent representation fails C7. |

Evidence is ready for coordinator review, **not an independent clean audit**.
The parent phase records independent reviews and exact scope. Missing real
integration checks and the findings above remain explicit residuals.
