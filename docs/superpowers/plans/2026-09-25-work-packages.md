# Work packages — backlog clarified with Kenneth, 2026-09-25

Source: the verified backlog audit (228 entries against main 8d6741d) and Kenneth's answers Q1-Q28 (decision BACKLOG-DECISIONS-2026-09-25 in PROJECT_STATE.json). Every still-open entry belongs to exactly one package. Entries are quoted by their opening words, because positions in PROJECT_STATE.json shift as items close.

## Rules for every package session

1. Start: `python3 scripts/state.py` must exit 0. Branch off the latest `origin/main`.
2. Work only on your package. Touch only its **owned files**. If you need a file another package owns, stop and ask Kenneth.
3. Loop: plan (in docs/superpowers/plans/) -> adversarial round (fresh subagent, bmad-review-adversarial-general) -> build with tests + mutation checks -> code round. Nothing is done until a round is clean. Cap: 3 rounds per stage; at the cap, stop and tell Kenneth.
4. Kenneth's decisions below are settled; do not re-ask them. A NEW question: stop, ask Kenneth, record the answer as a decision in PROJECT_STATE.json. Never decide for him.
5. PROJECT_STATE.json: add ONE phase entry for your package (with a verify probe), edit only your own entries, move each backlog entry you finish into closed_questions with evidence.
6. Merge: merge `origin/main` into your branch first, resolve PROJECT_STATE.json conflicts by keeping both sides, re-run the full suites, then merge --no-ff to main and push. Tests must never write backend/config/*.yaml or run the real app lifespan.
7. Verify: backend `cd backend && .venv/bin/python -m pytest -q`; frontend `cd frontend && npx tsc --noEmit && npx jest`; `python3 scripts/state.py` exit 0.

## Overview

| Package | Title | Wave | Money impact | Size | Entries |
|---|---|---|---|---|---|
| P1 | Order & booking safety | 1 | HIGH — an order can exist with no tracked position; the size cap can be exceeded | M | 12 |
| P2 | Premium stop, position editing & trade-card display | 1 | HIGH — stops that cannot fire or show the wrong value | L | 23 |
| P3a | Scan sizing & signal correctness | 1 | HIGH — share counts and which trades are proposed | M | 8 |
| P3b | Auto-trader hardening | 1 | HIGH — the automated path that places real orders | M | 12 |
| P3c | Scan & sizing leftovers (orphans of P3a/P3b) | 1 (added 2026-09-25) | HIGH — options-scan picks the auto-trader would refuse; the fire path can stall the server | M | 7 |
| P4a | Chart alert rules: sync, toggle, missed candles | 1 | MEDIUM — missed or corrupted alerts | M | 2 |
| P4b | Strategy & composite watches | 1 | MEDIUM — watches that never fire, fire on wrong data, or go silent | M | 9 |
| P5 | Step-5 display & end-to-end tests | 2 | LOW — wording and test coverage | S | 2 |
| P6 | Validation, method-pick & state-tool hygiene | 2 | LOW-MEDIUM — bad inputs accepted; a lost Monte Carlo pick blocks a send | M | 19 |
| W2-INTERVAL | One interval vocabulary (5m -> 5min) | 2 | MEDIUM — rules invisible on the chart, wrong labels | M | 1 |
| W2-STRUCT | OrderBlock / FVG / Divergence rules can fire | 2 | MEDIUM — these alert kinds never fire today | M | 1 |
| W2-HESTON | Heston fit quality | 2 | LOW — Black-Scholes is a sound fallback today | L | 11 |
| W2-DOCC | Config validation (Document C / YAML-CONFIG-INTEGRITY) | 2 | MEDIUM — a bad config edit should fail loudly, not silently | L | 3 |
| MEAS | Market-data measurement (runs on Kenneth's machine) | anytime | HIGH — thresholds decide which trades are proposed and how they are sized | S of code, days of calendar | 9 |

Wave 1 runs in parallel (6 sessions: P1, P2, P3a, P3b, P4a, P4b). Wave 2 starts as wave-1 packages merge (W2-INTERVAL after P4a+P4b; W2-STRUCT after P4a; P5, P6, W2-HESTON anytime in wave 2; W2-DOCC after its decisions round). MEAS runs anytime on Kenneth's machine. P3c (added 2026-09-25) joins wave 1; it takes over the orphaned P3a/P3b deferrals.

## P1 — Order & booking safety

- **Wave:** 1  **Money impact:** HIGH — an order can exist with no tracked position; the size cap can be exceeded  **Size:** M
- **Owned files:** frontend/app/(frame)/screener/step-7-trade-card/page.tsx; backend/app/services/position_writer.py; backend/app/services/portfolio_risk.py; their tests.
- **Do not touch:** TradeCard component, EditDrawer, portfolioStore.ts (P2); auto_trader.py (P3b).

**Kenneth's decisions to implement:**

- Q12: a wrong-side stop booked with gates off sends an alert (not only a log line).
- Q18: with gates on, the card path REFUSES a quantity above the 5-contract clamp, with a clear message (never books above it).

**Backlog entries (verified still open at 8d6741d):**

- Direct-call writer tests still patch a module global that the bound default fetcher ignores, so they make real network calls. — *evidence:* position_writer.py:126-127 defaults bound at def; tests/test_position_writer.py:55-56,:130-131 — *entry begins:* "LOGGED BY O4 STEP 1 ROUND 1 (2026-09-24), NOT FIXED, below the gate (tests only; production unaffected) -- AND…"
- The docstring still claims over_exposure is False when gates are on. The card path still books qty above the clamp; behaviour change is Kenneth's call. — *evidence:* position_writer.py:99-101, :349-353; portfolio_risk.py:60 clamp — *entry begins:* "LOGGED BY O4 STEP 2 ROUND 2 (2026-09-24), NOT FIXED, below the gate: FALSE CLAIM IN THIS STEP'S OWN DOCSTRING,…"
- The contract cap is still applied to stock share counts in the writer and in check_position_risk. Unreachable today. — *evidence:* position_writer.py:360-362; portfolio_risk.py:60 — *entry begins:* "LOGGED BY O4 STEP 2 ROUND 2 (2026-09-24), NOT FIXED, below the gate: the gates-off clamp term applies a CONTRA…"
- The writer still rebuilds the clamp from a private config; there is no judged_size on RiskCheckResult. — *evidence:* position_writer.py:360 portfolio_risk._load_config()['sizing']['max_contracts_per_trade'] — *entry begins:* "LOGGED BY O4 STEP 2 ROUND 2 (2026-09-24), NOT FIXED, below the gate: the writer RECONSTRUCTS the check's clamp…"
- The portfolio snapshot is still read without a lock, so two concurrent bookings can each pass the cap and breach it together. — *evidence:* position_writer.py: no lock/with_for_update; check_position_risk call at ~:335 — *entry begins:* "LOGGED BY O4 STEP 2 ROUND 2 (2026-09-24), NOT FIXED, below the gate: CONCURRENCY, for step 4's re-plan: the po…"
- Writer test gaps remain, and log prefixes are still inconsistent ('create_position:' vs 'add_position:'). — *evidence:* position_writer.py:296,:368 vs :199,:316 — *entry begins:* "LOGGED BY O4 STEP 2 ROUND 1/2 (2026-09-24), NOT FIXED, below the gate: test gaps: no test trips both gates in …"
- Part 2 (do plan rounds count) is answered: they count separately. Test items 3-4 are still open. — *evidence:* decision AUDIT-CAP-PER-STAGE-2026-09-25; tests/test_o4_step3_arm_fields.py:128 'name in resp.text'; no PortfolioPositionCreate.model_validat — *entry begins:* "LOGGED BY O4 STEP 3 ROUND 2 (2026-09-24), NOT FIXED, below the gate: (1) plan s7 says 'an already_shipped phas…"
- Booking residuals remain: undashed expiry accepted, 409 text says 'add it by hand', whitespace order id treated as real, rollback tests missing. — *evidence:* auto_trade_booking.py:132 date.fromisoformat (accepts YYYYMMDD on 3.11), :217 'Add it by hand', :93 _order_label — *entry begins:* "LOGGED BY O4 STEPS 4+5 ROUND 2 (2026-09-24), NOT FIXED, below the gate (code correct; mostly unpinned guards):…"
- placeLimitPaper and placeMarketNow still post the broker order before persisting the position. — *evidence:* step-7-trade-card/page.tsx:1065 postOptionOrder then :1078 persistPosition (same :1116/:1129) — *entry begins:* "placeLimitPaper posts to the broker BEFORE persisting, so a 1% adverse tick between the card's bound and the r…"
- Both mid chains still use ??, which lets a literal 0 contractDetails.mid through as the entryPrice. — *evidence:* step-7-trade-card/page.tsx:114-115 (cd?.mid ??), :978 (livePrice ?? cd?.mid ??) — *entry begins:* "entryPrice gt=0 closes the schema and leaves the producer open: both mid chains use ?? which does not catch a …"
- Contracts is still min=1 with no max, and the broker order is still posted before persisting. — *evidence:* TradeCard/index.tsx:2300-2307; step-7 page.tsx:1065/1078 — *entry begins:* "F9 TradeCard/index.tsx:1861-1868 (PRE-EXISTING at dc051a58, verified by git show) -- Contracts is min={1} with…"
- The direct paths still never clear paperOrderId, so a stale green 'Order placed' can show above a failed order. A basket submit still wipes it. — *evidence:* step-7 page.tsx:1057,1107 (no setPaperOrderId(null)); :1180 in handleSubmit — *entry begins:* "R2-11 step-7-trade-card/page.tsx:985-994 -- the comment says setPaperOrderId(null) matches placeLimitPaper and…"

## P2 — Premium stop, position editing & trade-card display

- **Wave:** 1  **Money impact:** HIGH — stops that cannot fire or show the wrong value  **Size:** L
- **Owned files:** frontend/components/organisms/TradeCard/**; EditDrawer; AutoTradeArm; frontend/lib/portfolioStore.ts; frontend/lib/premiumStop.ts; frontend/lib/alertEngine.ts; frontend/lib/risk.ts; Settings page (premium stop field); backend risk_settings; their tests; docs schematic.
- **Do not touch:** step-7-trade-card/page.tsx (P1); position_writer.py (P1).

**Kenneth's decisions to implement:**

- Q6: "worthless" goes through Close at $0; a typed Current price of 0 stays refused.
- Q7: global premium stop capped at 99% (UI and backend risk_settings).
- Q8: the card relabels the time stop to the real rule ("Time exit: 3 DTE").
- Q9: a stored ratio outside 10-99% is accepted as typed (dollar is the truth); show a warning.
- Q15: an edit-drawer rejection message is cleared only by the user's own edits, never by background syncs.

**Backlog entries (verified still open at 8d6741d):**

- Max fill and Time stop still have no consumer. Threading them is a deferred build, and they stay read-only on the card. — *evidence:* decision MAXFILL-TIMESTOP-2026-09-05; TradeCard/index.tsx:68-71; lib/tradeCardEdits.ts:35-36 — *entry begins:* "Thread the card's Max fill and Time stop through to a send path? Deferred, and NOT a wiring fix: neither field…"
- Step-6 residuals remain, e.g. the green 'Auto-trade fired -- Order ID' line still shows beside a not-booked caution. — *evidence:* frontend/components/organisms/AutoTradeArm/index.tsx:565-569 — *entry begins:* "LOGGED BY O4 STEP 6 ROUND 2 (2026-09-24), NOT FIXED, below the gate: (1) a dollar premium stop >= the entry pe…"
- All four tests that cannot fail are still there unchanged. — *evidence:* frontend/lib/__tests__/premiumStop.test.ts:50-56, :231-238, :282, :306-313 — *entry begins:* "Four tests in premiumStop.test.ts cannot fail: an arity assertion; a 'contract switch' test that looks up a ke…"
- The schematic still prints the non-reconciling '$401 ... $651 premium, $251 left'. — *evidence:* docs/superpowers/specs/2026-09-02-trade-card-schematic.html:278 — *entry begins:* "The schematic (2026-09-02-trade-card-schematic.html:277-278) prints '$401 ... of the $651 premium, $251 left' …"
- All three sites still adopt the server's entryPrice while keeping the client's currentPrice/pnlDollar/pnlPct. — *evidence:* frontend/lib/portfolioStore.ts:506-509, :946-948, :1227-1229 — *entry begins:* "portfolioStore.ts:452-461 and :874-889 adopt the server's entryPrice while leaving currentPrice/pnlDollar/pnlP…"
- The arm path still passes premiumStopPctFromDollars' undefined through silently and never reports the fallback to the global. — *evidence:* components/organisms/AutoTradeArm/index.tsx:352 (no dropped-stop notice in file) — *entry begins:* "AutoTradeArm (index.tsx:106-142) drops the per-trade premium stop to the 60% global when the typed dollar is >…"
- An untouched Premium stop row still shows the scan-seeded dollar (data.exit.premiumStop), not the value against the live fill. — *evidence:* TradeCard/index.tsx:416, :2812-2820 — *entry begins:* "TradeCard's untouched Premium stop row (index.tsx:2288-2296) renders round(scan_mid x global, 2) as a dollar: …"
- lastPremiumStopDropped is still first-wins and is cleared only by the user dismissing it. — *evidence:* frontend/lib/portfolioStore.ts:1207, :822 — *entry begins:* "portfolioStore.ts:1140-1150 lastPremiumStopDropped is first-wins ACROSS retry cycles, not just within one loop…"
- stockAnchor still falls back to scanStockPrice when there is no live underlying. — *evidence:* app/(frame)/portfolio/EditDrawer.tsx:330-332 — *entry begins:* "EditDrawer's stockAnchor falls back to scanStockPrice, so on a position whose underlying has moved 2-3x the ra…"
- The v2->v3 and v3->v4 migration steps still run regardless of version. Only the v5 IV strip is gated. — *evidence:* frontend/lib/portfolioStore.ts:738-795 (only :795 checks version) — *entry begins:* "migratePortfolioPersist (portfolioStore.ts:697-742) ignores its version argument -- both the v2->v3 and v3->v4…"
- The skipPost and ok-path promotions still mark a row synced without deleting premiumStopDollar. — *evidence:* frontend/lib/portfolioStore.ts:889-896, :913-920 — *entry begins:* "portfolioStore.ts:838-842 and :858-864 promote a row to syncStatus 'synced' with premiumStopDollar still on it…"
- fromBackend still drops stopIsUserSet and scanStockPrice, while toBackendPayload still sends them. — *evidence:* portfolioStore.ts:59-113 (absent), :256,:263 (sent) — *entry begins:* "F1 portfolioStore.ts:48-87 -- fromBackend drops stopIsUserSet and scanStockPrice while toBackendPayload sends …"
- The typed route is closed, but a 100% global stop is still allowed, so previews show $0.00 and the stop never fires. open_questions[52] awaits Kenneth. — *evidence:* settings/page.tsx:1435-1438 max 1.0; risk_settings.py:47-51 le=1.0 — *entry begins:* "F2 premiumStop.ts:88-102 via EditDrawer.tsx:1281-1285 -- when entry*(1-pct) < 0.005 the preview prints 'Fires …"
- EditableKV still stores at 2dp for any non-zero decimals prop. It is inert today because no field uses 3dp. — *evidence:* TradeCard/index.tsx:3398 vs :3442-3446 — *entry begins:* "F3 TradeCard/index.tsx:2811 -- EditableKV commits at 2dp (Math.round(parsed*100)/100) regardless of its decima…"
- The Invalidation and Premium stop editors still sit inside the collapsed 'Fixed % Ladder Plan' section. — *evidence:* TradeCard/index.tsx:2785-2820 (defaultCollapsed) — *entry begins:* "F5 TradeCard/index.tsx:2269-2273 -- Invalidation and Premium stop sit inside <CollapsibleSection title='Fixed …"
- The frontend rounds half-up while the backend uses Python's half-to-even round(...,4), yet the comment still says 'literally what the backend stores'. — *evidence:* frontend/lib/alertEngine.ts:283-288; alert_generator.py:311-313 — *entry begins:* "F6 alertEngine.ts:283 -- writes Math.round(x*10000)/10000 (half-up) to match alert_generator.py's round(thresh…"
- A stock position's level is still labelled 'Premium stop' while alertFiresAgainst calls the same level 'stock $'. — *evidence:* EditDrawer.tsx:1261 vs :1591 — *entry begins:* "F7 EditDrawer.tsx:1130 vs :1281 -- the drawer labels a STOCK position's level 'Premium stop -- 45%' two rows a…"
- The bounds still fall back to {min:0.01, max:undefined} when there is no anchor. The backend limit_price is only gt=0. — *evidence:* TradeCard/index.tsx:1683,1720,1747; routers/broker.py:191,212 — *entry begins:* "F8 TradeCard/index.tsx:1493/:1524/:1555 -- all three field bounds degrade to {min:0.01, max:undefined} with no…"
- The global premium stop can still be set to 100%, making a stop that can never fire. Bounds are unchanged in the UI and the backend. — *evidence:* settings/page.tsx:1435,1438; risk_settings.py:47-51; open_questions[52] — *entry begins:* "R1-10 settings/page.tsx:1404-1411 + risk_settings.py:47-51 -- the GLOBAL premium stop is offered at 100% (step…"
- The 'leaves a real edit alone' test is still not labelled as documentation-of-intent, even though it passes against the old code. — *evidence:* app/(frame)/portfolio/__tests__/EditDrawer.test.tsx:1440 — *entry begins:* "R1-13 EditDrawer.test.tsx -- of the 13 tests the first commit added, three pass unchanged against the pre-comm…"
- At a $0.01 mid the field still offers one dollar that produces no stop. The code comment says it was logged, not fixed. — *evidence:* frontend/lib/premiumStop.ts:86-102; premiumStop.test.ts:390-399 — *entry begins:* "R2-6 premiumStop.ts -- at a $0.01 mid the band collapses to one dollar, and that dollar is 100% of the mid, wh…"
- The comment still calls a typed Current price a transient, but persist still saves all position fields to localStorage. — *evidence:* EditDrawer.tsx:408-412; portfolioStore.ts:1300 partialize {positions} — *entry begins:* "R2-8 EditDrawer.tsx:400-407 -- the comment (and R1-8, and the 'Should Current price accept 0?' open question) …"
- Re-running Monte Carlo in the drawer still restamps resolvedTpPrice from targets[0], which overwrites a T2/T3 pick with T1. — *evidence:* frontend/app/(frame)/portfolio/EditDrawer.tsx:267 and :292 restampIfActive('monte_carlo', targets[0]?.price) — *entry begins:* "G1-11 EditDrawer.tsx:292 -- a Monte Carlo re-estimate restamps resolvedTpPrice from targets[0] UNCONDITIONALLY…"

## P3a — Scan sizing & signal correctness

- **Wave:** 1  **Money impact:** HIGH — share counts and which trades are proposed  **Size:** M
- **Owned files:** backend/app/routers/stock_scan.py; backend/app/scoring/stock_scorer.py; backend/app/services/strategy_engine.py (target ladder only); backend/app/routers/scan.py (comments only); frontend/lib/stockScan.ts; frontend/lib/analysisStore.ts; screener step-3/4/5 pages; ScanFunnel; scanParamsStore.
- **Do not touch:** auto_trader.py, conviction_sizing.py (P3b); strategy_engine VWAP functions (P4b reads them).

**Kenneth's decisions to implement:**

- Q2: every manual scan path (Steps 3/4, Analysis, Step 5) reads portfolioValue and maxLossPerTradePct from settings; no hard-coded 50k / 1%.
- Q5: add a min_stock_score field to the Step-3 Execution Parameters panel.
- Q11: the scorer marks a trend score as measured/unmeasured; the direction gate treats unmeasured separately and the funnel says "no data", not "no conviction".

**Backlog entries (verified still open at 8d6741d):**

- Outer handler fixed; stop_pct is now resolved once (Q2 shipped clean). Several original below-gate items remain: misleading hints, a stale line comment, and an unguarded scan loader. — *evidence:* phase AUTOTRADE-Q2-STOP-PCT-RESOLVED-ONCE clean; still open: conviction_sizing.py:239 & :301 hints, stock_scan.py:1328 cites :1167 (gather n — *entry begins:* "*** CORRECTED 2026-09-23 AGAINST origin/main e5e669f5. THE LINE NUMBERS BELOW ARE FROM THE OLD ~600-LINE FILE …"
- Half (a) done: Analysis now flags the direction-conviction drop. Half (b) open: no config endpoint or store shows the threshold; funnel still unnumbered. — *evidence:* (a) stock_scan.py:621-622 (A5C). (b) routers/config.py only /iv-thresholds,/event-thresholds; ScanFunnel/index.tsx:139,191 'no conviction' w — *entry begins:* "THE DIRECTION-CONVICTION GATE IS STILL INVISIBLE TO THE USER, raised by the same 2026-09-16 audit and NOT fixe…"
- Negative bearish backtest price unfixed (fallback target rung has no >0 check; split hypothesis unverified). Misleading 'market structure' empty-scan banner unchanged. — *evidence:* strategy_engine.py _build_target_ladder fallback (~:327) unguarded for <=0; strategy_backtest.py:133 self.sell(tp=...); stock_scan.py:1381-1 — *entry begins:* "FOUND 2026-09-18 BY THE MARKET-HOURS BEARISH STOCK SCANS, NOT FIXED, CAUSE A HYPOTHESIS: the bearish pullback_…"
- The options scan's bar-window comment is still wrong (says 252 trading days). Scan regime series length still depends on the data source. — *evidence:* scan.py:1515 '# ~440 calendar days = 252 trading days'; auto_trader.py:848-857 still names the source-length residual — *entry begins:* "LOGGED AGAINST MAIN by 2B round 1 (2026-09-21), NOT fixed -- outside this phase's eight paths: `backend/app/ro…"
- No test pins the stock scan card's conviction input frame. Existing tests call _conviction_mult directly. — *evidence:* stock_scan.py:1131; tests/test_stock_scan_regime.py only calls the helper directly — *entry begins:* "LOGGED BY SIZING-3 ROUND 1 (2026-09-24), NOT FIXED, below the gate: TEST GAP -- no test pins the scan card's I…"
- If neither risk_pct nor fixed risk is set, the card falls back to a flat 1% and the conviction multiplier is lost. — *evidence:* stock_scan.py:1141-1142 (mult applied only if set), :896 risk_pct or 0.01 — *entry begins:* "LOGGED BY SIZING-3 ROUND 1 (2026-09-24), NOT FIXED, below the gate, pre-existing: with risk_pct null and no ri…"
- The A4 tests still use a MagicMock semaphore, so nothing asserts the intraday fetch runs under the scan semaphore. — *evidence:* tests/test_a4_intraday_regime_bars.py:35-39 _sem() MagicMock — *entry begins:* "LOGGED BY A4 CODE ROUND (2026-09-24), NOT FIXED, test gap: tests use a MagicMock `sem`, so nothing asserts the…"
- Analysis still fetches 80 days of 15-minute bars while the scans and fire path fetch 55. — *evidence:* stock_scan.py:562 ('15min', 80) vs :933,:968; auto_trader.py:803 (55) — *entry begins:* "LOGGED BY A4b CODE ROUND (2026-09-24), pre-existing, out of scope: the Analysis page fetches 80 days of 15-min…"

## P3b — Auto-trader hardening

- **Wave:** 1  **Money impact:** HIGH — the automated path that places real orders  **Size:** M
- **Owned files:** backend/app/services/auto_trader.py; backend/app/services/conviction_sizing.py; backend/app/services/notifications/alert_notifier.py; backend/app/data/ibkr_paper.py; backend/config/scoring_rules.yaml (comments only); backend/tests/test_auto_trader.py.
- **Do not touch:** stock_scan.py (P3a); tests/conftest.py (P4b).

**Kenneth's decisions to implement:**

- Phase AUTOTRADE-DAILY-LOSS-FAULT-TEST (already queued; test name fixed by its probe).
- The unclassified-refusal wording stays as is (decision UNCLASSIFIED-ALERT-WORDING-KEPT-2026-09-24).

**Backlog entries (verified still open at 8d6741d):**

- IBKR reply with an id and an empty message list is still not flagged as awaiting confirmation (fails safe). — *evidence:* backend/app/data/ibkr_paper.py:164-168 requires bool(data.get('message')) — *entry begins:* "LOGGED BY MANUAL-IBKR-CONFIRM-AS-ERROR (2026-09-25), NOT FIXED, fails safe: an IBKR order reply carrying an `i…"
- No test pins _check_daily_loss's catch-all writing a risk_check_failed row; only the exposure half is pinned. — *evidence:* test_auto_trader.py:3350 mocks _check_exposure only; FOLLOWUPS-QUEUE (5) awaits a go — *entry begins:* "LOGGED AGAINST MAIN by 2A-GATE round 6, NOT fixed (test hygiene, explicitly outside the severity floor): only …"
- Regime-gate config refusal alert still blames scoring_rules.yaml even when the threshold came from the arm request. — *evidence:* auto_trader.py:1600 message; routers/auto_trade.py:154 unbounded regime_headwind_reject_pct overlay — *entry begins:* "LOGGED AGAINST MAIN by target 2a ROUND 4, NOT fixed (below the gate, and audit_rule forbids fixing a non-gate …"
- _save_dedup still swallows failures, so forget_alerts cannot report an on-disk hold that survives. — *evidence:* notifications/alert_notifier.py:91-92 except->logger.warning; forget_alerts :303 no propagation — *entry begins:* "LOGGED AGAINST MAIN by target 2a ROUND 4, NOT fixed (no wrong number today; a blind spot, not a defect): `forg…"
- Docstring and fired-row comment still list four gate outcomes; fifth 'passed:caution-band-disabled' exists. — *evidence:* auto_trader.py:1032, :2494 vs :1285 — *entry begins:* "LOGGED AGAINST MAIN by target 2a ROUND 4, NOT fixed (prose, no wrong number): `fire()`'s fired-row comment (au…"
- full_conviction_pct 0 still logs an ERROR on every resolve, so duplicate lines appear per fire or scan. This is log noise only. — *evidence:* backend/app/scoring/conviction_sizing.py:218-226 logger.error inside resolve_sizing — *entry begins:* "LOGGED BY SIZING-FAIL-CLOSED ROUND 1, NOT FIXED (log noise, no wrong number): resolve_sizing runs twice per fi…"
- On a timeout or no bars, the fire-path gate still abstains instead of dropping like the scan. The 8s deadline is still shorter than the 10s provider timeout. — *evidence:* auto_trader.py:528 _REGIME_FETCH_DEADLINE_S=8.0, :904-911, :925 return None; market.py:178 timeout=10 — *entry begins:* "LOGGED AGAINST MAIN by 2B round 1 (2026-09-21), NOT fixed and BELOW THE GATE as judged -- recorded because it …"
- The stale 'fires ungated at full armed quantity' comments were moved (A4g), not corrected; one 'full size' remains in auto_trader. — *evidence:* market_session.py:60,:101; auto_trader.py:684 — *entry begins:* "LOGGED BY SIZING-4 ROUND 1 (2026-09-24), NOT FIXED, below the gate: three comments still say an abstaining gat…"
- A malformed regime.<horizon> block still has no shape check, so bad config can raise outside the try. — *evidence:* auto_trader.py:493-501 _load_regime_cfg has no validation; :925 len(bars) < min_obs outside the try; phase YAML-CONFIG-INTEGRITY not_started — *entry begins:* "LOGGED BY SIZING-4 ROUND 1 (2026-09-24), NOT FIXED, below the gate (no order is sent): with the gate DISABLED …"
- Comment still says _apply_regime_gate refuses a -80 trade, but that holds only in a Stable regime. — *evidence:* auto_trader.py:1387-1390 'The `_apply_regime_gate` call above refuses it.' — *entry begins:* "LOGGED BY SIZING-3 ROUND 1 (2026-09-24), NOT FIXED, outside the target: auto_trader.py ~:1424-1427 says a trad…"
- Contract sizing still uses Python round(), which rounds halves to even (banker's rounding). — *evidence:* auto_trader.py:1392 max(1, round(strategy.quantity * mult)) — *entry begins:* "LOGGED BY SIZING-3 ROUND 1 (2026-09-24), NOT FIXED, below the gate, pre-existing: max(1, round(qty*mult)) uses…"
- The YAML comment still says a trade below -40 survives at min_mult. It ignores regime_filter drops and Step-3 overrides. — *evidence:* config/scoring_rules.yaml:476-478 — *entry begins:* "LOGGED BY SIZING-3 ROUND 2 (2026-09-24), NOT FIXED, below the gate: the regime_sizing comment's 'survives and …"

## P3c — Scan & sizing leftovers (orphans of P3a/P3b)

Added 2026-09-25 (decision P3C-PACKAGE-CREATED-2026-09-25). P3a and P3b are merged; these items were deferred by them into files no package owned.

- **Wave:** 1 (added late)  **Money impact:** HIGH — an options candidate the auto-trader would refuse is still proposed; the fire endpoint can block the event loop  **Size:** M
- **Owned files:** backend/app/routers/scan.py (code, not only comments); backend/app/scoring/conviction_sizing.py; frontend/lib/scanScheduleResolve.ts; backend/app/routers/auto_trade.py (the /fire path only — ArmRequest stays P6's); their tests.
- **Shared with P6:** the one new `schemas/__init__.py` field the options direction gate needs (a measured/unmeasured trend flag). P3c may add that single field; coordinate through PROJECT_STATE.json so P6 does not collide.
- **Do not touch:** stock_scan.py, stock_scorer.py (P3a, merged — reuse `_regime_data_drop` and `RuleResult.measured` by calling them); auto_trader.py (P3b, merged — call, do not edit, unless Kenneth widens this).

**Kenneth's decisions to implement:**

- P3A-INTRADAY-REFUSAL-MATCHES-FIRE-2026-09-25 applies to the options scan too: drop an Intraday options name whose 15-min regime fetch failed when the fire would refuse it.
- P3A-STORED-ZERO-RISK-RUNS-AT-DEFAULT-2026-09-25 stands for schedules unless Kenneth changes it (open: should a 0% schedule stop like the manual paths? ask at plan time, do not decide).

**Backlog entries:**

1. Options scan keeps an Intraday name whose 15-min regime fetch failed; the auto-trader fire refuses it (P3B-REGIME-BARS-MISSING-REFUSES). — *entry begins:* "LOGGED BY P3a (2026-09-25), NOT FIXED, outside P3a's files: the OPTIONS scan (routers/scan.py) has no item-12 equivalent…"
2. Options direction-conviction gate reads stockBreakdown.trend as an int, cannot see RuleResult.measured, judges a placeholder 0/50. — *entry begins:* "LOGGED BY P3a (2026-09-25), NOT FIXED: the options direction-conviction gate (routers/scan.py)…"
3. scanScheduleResolve.ts still sends maxLossPerTradePct as-is (0% runs at the 1% default by decision). — *entry begins:* "LOGGED BY P3a (2026-09-25), NOTE: frontend lib/scanScheduleResolve.ts…"
4. conviction_sizing.py items (3) inverted min_mult refusal message for negatives, (4) `min_mult / 100` hint misleads just above 1, (5) `full * 100` hint can suggest a refused value, (10) the ERROR line is logged once per resolve (~501 lines per 500-symbol scan). — *entry begins:* "P3a (2026-09-25) FIXED the stock_scan.py items (6)… STILL OPEN: items (3)(4)(5)(10) in conviction_sizing.py. || *** CORRECTED 2026-09-23…"
5. Negative bearish backtest price — the stock-split hypothesis is unverified (data-side). Investigate first; fix only what the evidence shows. — *entry begins:* "P3a (2026-09-25) FIXED (a) _build_target_ladder returns []… STILL OPEN: (b) the split hypothesis…"
6. Options scan regime series length still depends on the data source (bar-count difference). Investigate first. — *entry begins:* "P3a (2026-09-25) FIXED the comment (441 calendar days ~ 306 trading days). STILL OPEN: the source-length residual (scan.py code)…"
7. POST /auto-trade/fire runs `fire()` on the event loop, so a stalled regime fetch can block the server for up to ~25s (P3b deferral). — *entry begins:* "LOGGED BY P3c SETUP (2026-09-25), P3b DEFERRAL…"

Items 5 and 6 are investigate-first: the plan states what is measured and how before any code change.

## P4a — Chart alert rules: sync, toggle, missed candles

- **Wave:** 1  **Money impact:** MEDIUM — missed or corrupted alerts  **Size:** M
- **Owned files:** frontend/lib/chartAlertStore.ts; frontend/app/(frame)/alerts/**; ChartWorkspace (alert parts only); backend/app/routers/chart_alerts.py; backend/app/data/chart_cache.py; backend/app/services/chart_alert_scheduler.py; backend/app/services/alert_evaluator.py; backend/app/services/market_session.py.
- **Do not touch:** CompositeAlertDialog and market.py interval aliases (W2-INTERVAL); composite_trigger_evaluator.py (P4b).

**Kenneth's decisions to implement:**

- Q1: syncRules re-sends local-only rules with rule_type/composite_def; a refused rule stays local, marked "not saved to server" (phase ALERTS-SYNC-LOCAL-ONLY-COMPOSITE).
- Toggle and last_triggered_at use PATCH (phase ALERTS-RULE-TOGGLE-PATCH).
- Q14: the chart-alert check must not skip a closed candle (fresh fetch instead of a stale cached snapshot).

**Backlog entries (verified still open at 8d6741d):**

- crosses_above/below still compare a None previous value, raising TypeError that evaluate_rules does not catch. — *evidence:* alert_evaluator.py:224-232 (prev_value unchecked); evaluate_rules :371 no try — *entry begins:* "LOGGED BY A4e (2026-09-25), pre-existing on main: alert_evaluator._evaluate_condition's crosses_above/crosses_…"
- Items checked still hold: no two-forming-bar test, no _NYSE_CLOSE mirror test, stale docstring, and the guard test freezes only market_session.datetime. — *evidence:* market_session.py:188,103,233-278; tests/test_a4g_forming_daily_weekly_bar.py (no multi-trailing test); test_auto_trader.py:4089 — *entry begins:* "LOGGED BY A4g ROUND 2 (2026-09-25), ALL BELOW THE GATE, not fixed in-branch per audit_rule: (1) completed_sess…"

## P4b — Strategy & composite watches

- **Wave:** 1  **Money impact:** MEDIUM — watches that never fire, fire on wrong data, or go silent  **Size:** M
- **Owned files:** backend/app/services/strategy_watch_evaluator.py; composite_trigger_evaluator.py; strategy_watch_store.py; strategy_watch_scheduler.py; backend/app/routers/strategy_watch.py; frontend strategy-watch page; backend/tests/conftest.py.
- **Do not touch:** strategy_engine.py (P3a owns it; call existing signals, do not edit); chart_alerts.py (P4a).

**Kenneth's decisions to implement:**

- Phase VWAP-CONFIRMATION-LIKE-REGIME-MODELS (completed bars of the own interval; same answer on watch and rule paths; 1D/1W use mean_reversion_vwap_daily_signal on completed daily bars).
- Phase HMM-INTRADAY-4H-HISTORY (~180 days for 4h).
- Phase TESTS-PIN-STRATEGY-WATCHES-PATH (conftest pin).
- Q17: evaluate_all isolates each watch; one failure skips only that watch.

**Backlog entries (verified still open at 8d6741d):**

- State is still written before delivery succeeds, and there's no lock against overlapping manual/scheduled evaluations. — *evidence:* strategy_watch_evaluator.py:404-413 ignores delivered, no Lock in evaluator/scheduler — *entry begins:* "LOGGED BY COMPOSITE-WATCH-KEYERROR round 2 (2026-09-25), PARITY, NOT FIXED: (a) strategy AND composite watches…"
- VWAP-confirmation redesign decided in principle, not built: signal still called without interval, on raw bars. — *evidence:* composite_trigger_evaluator.py:168 `fn(slice_bars, direction=direction)`; strategy_watch_evaluator.py:265 days=55 at watch interval — *entry begins:* "DECIDED IN PRINCIPLE 2026-09-25 (Kenneth): the mean_reversion_vwap confirmation must BEHAVE LIKE THE REGIME MO…"
- conftest still does not pin BAMENDJOU_STRATEGY_WATCHES_PATH; only two individual tests set it. — *evidence:* backend/tests/conftest.py pins CREDS/SCAN_SCHEDULE only (:72,:86) — *entry begins:* "LOGGED BY A4f-rules plan round 2 (2026-09-25), ~1 line: backend/tests/conftest.py does not pin BAMENDJOU_STRAT…"
- Decided to raise 4h history, not built: evaluator still fetches 55 days for every interval. — *evidence:* strategy_watch_evaluator.py:265 days=55; decision FOLLOWUPS-QUEUE-2026-09-25 (1) — *entry begins:* "LOGGED BY A4f PLAN ROUND 1 (2026-09-25), PRE-EXISTING, KENNETH'S CALL: an HMM_intraday composite watch on '4h'…"
- conftest docstring still says two leaked refusal keys; the four-key measurement was never reconciled. — *evidence:* backend/tests/conftest.py:191 'two auto-trade refusal keys' — *entry begins:* "MEASURED DISCREPANCY, UNRECONCILED, logged by target 2a ROUND 4 and NOT edited away: conftest's `_isolate_aler…"
- Indicators and structure now use the closed candle (A4e). The composite VWAP confirmation still reads forming intraday bars; the redesign is decided but not built. — *evidence:* phase A4E shipped; composite_trigger_evaluator.py:161,:212-213,:282 bars_intraday; open_questions[5] (VWAP decided in principle) — *entry begins:* "ANSWERED 2026-09-24 -- see decision A4C-FOLLOWUPS-LOCKED-2026-09-24 (locked; queued as A4d-A4g). // LOGGED BY …"
- Composite momentum confirmations still compare an indicator series (list) to a number. The TypeError is caught and the rule is skipped. — *evidence:* composite_trigger_evaluator.py:114-116; chart_alerts.py:905,998-1004; indicator_compute.py:11-14 returns series — *entry begins:* "LOGGED BY A4e (2026-09-25), unverified by test: composite 'momentum' confirmations in the live chart path read…"
- evaluate_all has no per-watch try/except around the whole body, so one watch's exception still aborts the tick. Kenneth decides whether this robustness fix is wanted. — *evidence:* strategy_watch_evaluator.py:95-230 (only get_bars/signal calls are wrapped, :109,:119) — *entry begins:* "LOGGED BY claude/optimistic-wozniak-nwe8nz (COMPOSITE-WATCH-STRATEGY-KEY-CRASH, superseded by COMPOSITE-WATCH-…"
- GET /api/strategy-watch/ still returns composite rows unfiltered. The page still lists them with an empty Strategy cell. — *evidence:* backend/app/routers/strategy_watch.py:42-44; frontend/app/(frame)/strategy-watch/page.tsx:158 — *entry begins:* "LOGGED BY claude/optimistic-wozniak-nwe8nz (2026-09-25), OBSERVATION, NOT FIXED: GET /api/strategy-watch/ retu…"

## P5 — Step-5 display & end-to-end tests

- **Wave:** 2  **Money impact:** LOW — wording and test coverage  **Size:** S
- **Owned files:** screener step-5-vol-events page; frontend/lib/statusTooltips.ts; MarketSentiment; frontend e2e specs.
- **Do not touch:** —

**Kenneth's decisions to implement:**

- Q4: the Step-5 banner matches the row tooltip; a row with no IV reading counts under both causes.
- Q10: rewrite ws-g-happy-path-mocked.spec.ts (both tests currently test.fixme).

**Backlog entries (verified still open at 8d6741d):**

- The IV-basis e2e spec still covers only the absolute basis. The rank basis has no e2e test. — *evidence:* frontend/e2e/tests/iv-basis-rendering.spec.ts:56,81 (absolute-only tests) — *entry begins:* "Phase A e2e coverage is now real but NARROW, and the component half of round 1's FOLLOW-UP is untouched: iv-ba…"
- MarketSentiment still labels avg_regime_duration in days, but the value is in lookback strides. — *evidence:* frontend/components/molecules/MarketSentiment/index.tsx:32 '~{s.avg_regime_duration}d' — *entry begins:* "LOGGED BY A4 CODE ROUND (2026-09-24), pre-existing, carried not created: MarketSentiment shows `~{avg_regime_d…"

## P6 — Validation, method-pick & state-tool hygiene

> Note (2026-09-25): P3c may add ONE field to schemas/__init__.py (measured/unmeasured trend flag for the options direction gate). Coordinate via PROJECT_STATE.json.

- **Wave:** 2  **Money impact:** LOW-MEDIUM — bad inputs accepted; a lost Monte Carlo pick blocks a send  **Size:** M
- **Owned files:** backend/app/schemas/__init__.py; backend/app/routers/portfolio.py (PATCH); backend/app/routers/auto_trade.py (ArmRequest); backend/app/services/picked_method.py; frontend/lib/cardEdits.ts; frontend/lib/scanStore.ts; StockPositionCard; MethodPickSelector; scripts/state.py; docs/superpowers/STATE_TRACKING.md; tests/test_alternatives.py.
- **Do not touch:** —

**Kenneth's decisions to implement:**

- Q3: the state probe's rename hole is accepted — document it in docs/superpowers/STATE_TRACKING.md (no code change).

**Backlog entries (verified still open at 8d6741d):**

- If git log fails, the round scan still returns None, so the probe prints 'No drift' instead of a warning. — *evidence:* scripts/state.py:197-198 `if proc.returncode != 0: return None` — *entry begins:* "LOGGED BY STATE-PROBE-MERGED-MAIN-ROUNDS round 2 (2026-09-25), NOT FIXED, below the gate: in scripts/state.py,…"
- A hand-edited string audit_rounds still raises TypeError in the comparison. There is no coercion. — *evidence:* scripts/state.py:609-610 declared = target.get('audit_rounds') or 0; if git_max > declared — *entry begins:* "BELOW THE GATE, found by STATE-PROBE-REVIVAL round 1 and NOT fixed in-branch (needs a hand-edit to reach, and …"
- STATE_TRACKING.md still never mentions the audit-bookkeeping probe: commit-subject rounds, the hard cap, base-ref and scoping. — *evidence:* docs/superpowers/STATE_TRACKING.md: no 'bookkeeping'/'git_max'/'hard cap'/commit-subject text; only audit_rounds at :75,:88 — *entry begins:* "RAISED BY STATE-PROBE-REVIVAL round 1 as a DOCUMENTATION hole rather than a defect, and it is the same shape a…"
- test_alternatives.py is still vacuous. It uses a flat candle fixture and loops over possibly empty candidate lists without asserting they are non-empty. — *evidence:* backend/tests/test_alternatives.py:7 flat fixture; :50,:84,:96,:125 'for c in data["candidates"]' — *entry begins:* "FOUND WHILE BUILDING B3, logged against main and NOT fixed in-branch (no wrong number -- a coverage void, and …"
- The overclaiming test name is still there. — *evidence:* StockPositionCard/__tests__/StockPositionCard.concentration.test.tsx:190 — *entry begins:* "BELOW THE GATE, found by CONCENTRATION-FLAG round 1 and NOT fixed (wording only, no wrong number): the test na…"
- picked_method comment still says routers/portfolio.py guards the config load; that guard now lives in position_writer. — *evidence:* services/picked_method.py:183 — *entry begins:* "LOGGED BY O4 STEP 1 ROUND 1 (2026-09-24), NOT FIXED, stale location pointer outside the diff: backend/app/serv…"
- The PATCH path still handles activeTpMethod and resolvedTpPrice in separate ifs, so half the pair can be written. The product's own client cannot reach it. — *evidence:* backend/app/routers/portfolio.py:258-266 — *entry begins:* "G1-5 routers/portfolio.py:623-635 -- THE PATCH PATH CAN STILL WRITE HALF THE PAIR. `if "activeTpMethod" in upd…"
- Picked prices and entryPrice still use bare gt=0 with no allow_inf_nan, so Infinity is accepted. No handler fixes the NaN-in-422 encoding 500 either. — *evidence:* backend/app/schemas/__init__.py:1019-1020 (gt=0 only; no allow_inf_nan anywhere in app/); no RequestValidationError handler in backend/app — *entry begins:* "G1-6 schemas/__init__.py -- `gt=0` ACCEPTS `Infinity`. A pickedRowStockPrice of inf stores as resolved_tp_pric…"
- pickedAt is still a free string with no format validator, stored in a plain String column. — *evidence:* schemas/__init__.py:1022 Optional[str] no validator; models/portfolio.py:60 Column(String) — *entry begins:* "G1-9 schemas/__init__.py -- `pickedAt` has NO format validation and is a String column, so a 650-char garbage …"
- _rr_ratio_for_row still returns the first row within tolerance and never reports ambiguity. The entry itself rates this below the gate. — *evidence:* backend/app/services/picked_method.py:154-165 (first isclose match returned) — *entry begins:* "G1-8 services/picked_method.py:161-172 -- _rr_ratio_for_row takes the FIRST row within abs_tol=0.005 and never…"
- normalizeCardEdits only checks the shape of picks and maxLossOverride, not their values. maxLossOverride is no longer persisted, so only picks reach rehydrate. — *evidence:* frontend/lib/cardEdits.ts:338 and :342 asRecord(...) casts only — *entry begins:* "G2-4-RESIDUAL frontend/lib/cardEdits.ts -- normalizeCardEdits is now value-checked for the three PRICE maps bu…"
- The fallback key format SYMBOL|<label> still exists, and the cardEdits header still documents only SYMBOL|strike|expiry|right. — *evidence:* step-7-trade-card/page.tsx:319-324 editKeyFor fallback; cardEdits.ts:39-41 doc — *entry begins:* "G2-7 frontend/lib/cardEdits.ts vs step-7-trade-card/page.tsx -- TWO KEY FORMATS live in the contract-scoped ma…"
- clearPicksForSymbol still compares the symbol prefix case-sensitively against the raw symbol, while pick keys are uppercased by contractId(). No live mismatch today. — *evidence:* frontend/lib/cardEdits.ts:250-253; scanStore.ts:490 — *entry begins:* "G2-8 frontend/lib/cardEdits.ts -- clearPicksForSymbol compares the key's symbol prefix CASE-SENSITIVELY agains…"
- writeCardEdit still uses `key in slice[field]`, which walks the prototype chain, instead of hasOwnProperty. No live consequence. — *evidence:* frontend/lib/cardEdits.ts:217 (also :371 in clearCardPick) — *entry begins:* "G2-10 frontend/lib/cardEdits.ts -- writeCardEdit's `key in slice[field]` walks the prototype chain, so 'constr…"
- The scanStore persist storage is plain localStorage with no try/catch, so a QuotaExceededError still throws from set(). It is guarded only inside runStockScan. — *evidence:* frontend/lib/scanStore.ts:535-538 createJSONStorage(()=>localStorage); guards only in lib/stockScan.ts:341-351 — *entry begins:* "G2-12 PRE-EXISTING, noted only because `partialize` grew: zustand v5 has no try/catch around storage.setItem, …"
- The gate finding is fixed (via round 2/3). A below-gate cosmetic item is unfixed: the store action clearCardPick shares its name with the imported clearCardPick function. — *evidence:* scanStore.ts:15 import + :464-467 property calling clearCardPick(...); TradeCard/index.tsx:1884-1885 pickEstimateIsFresh fix — *entry begins:* "{'scope': "git diff 3d7bbfe4 42e6c6c3 -- step 3's own build plus 8f9769a2, per 42e6c6c3's instruction to audit…"
- Stale comments still mention a nonexistent `pickSettled` guard in MethodPickSelector and StockPositionCard. — *evidence:* MethodPickSelector/index.tsx:26; StockPositionCard/index.tsx:482 — *entry begins:* "frontend/components/organisms/StockPositionCard/index.tsx:477 and frontend/components/molecules/MethodPickSele…"
- StockPositionCard still holds estimate/plan only in local useState, and the row unmounts when collapsed, so a Monte Carlo pick is lost with a generic 'Method pick required' refusal. — *evidence:* StockPositionCard/index.tsx:358,364 useState(null); step-4-stocks/page.tsx:453 {open && <StockPositionCard .../>}; lib/risk.ts:329-331 gener — *entry begins:* "G4-1 frontend/components/organisms/StockPositionCard/index.tsx -- StockPositionCard has no page-level cache fo…"
- G5-1 is open: ArmRequest has no extra='forbid', so misspelled picked_* keys are still silently dropped. G5-2 is obsolete because the tripwire test was replaced. — *evidence:* routers/auto_trade.py:27 class ArmRequest (no model_config); test_phase_g_arm_pick.py:14-22 tripwire replaced — *entry begins:* "["G5-1 backend/app/routers/auto_trade.py — ArmRequest inherits pydantic's default `extra='ignore'`, so a camel…"

## W2-INTERVAL — One interval vocabulary (5m -> 5min)

- **Wave:** 2  **Money impact:** MEDIUM — rules invisible on the chart, wrong labels  **Size:** M
- **Owned files:** CompositeAlertDialog; backend/app/data/market.py (aliases); rule + watch migrations.
- **Do not touch:** Start only after P4a and P4b are merged.

**Kenneth's decisions to implement:**

- Phase INTERVAL-SPELLING-CHART-VOCABULARY (Kenneth confirmed): the dialog saves chart spellings; stored 5m/15m rules AND watches migrate, reported.

**Backlog entries (verified still open at 8d6741d):**

- Decided (use chart spellings + migrate) but not built: dialog still offers 5m/15m and no alias exists. — *evidence:* decision FOLLOWUPS-QUEUE-2026-09-25 (1); CompositeAlertDialog/index.tsx:232; market.py:247 aliases lack 5m — *entry begins:* "LOGGED BY A4f-rules (2026-09-25), KENNETH'S CALL: '5m' vs '5min'. CompositeAlertDialog offers 5m/15m/30m/1h/4h…"

## W2-STRUCT — OrderBlock / FVG / Divergence rules can fire

- **Wave:** 2  **Money impact:** MEDIUM — these alert kinds never fire today  **Size:** M
- **Owned files:** backend/app/services/alert_evaluator.py; market_structure signal times; AlertRuleBuilder.
- **Do not touch:** Start only after P4a is merged.

**Kenneth's decisions to implement:**

- Q16: do NOT hide them; fix with a per-kind "confirmed at" time. Q16b (a "not firing yet" note until then) awaits Kenneth.

**Backlog entries (verified still open at 8d6741d):**

- Standard structure rules on OrderBlock/FVG/Divergence still require signal time >= closed candle, so they never fire. Kenneth also has to decide whether to keep offering these kinds. — *evidence:* backend/app/services/alert_evaluator.py:246-249 (signal_time >= candle_time) — *entry begins:* "LOGGED BY A4e (2026-09-25), below the gate for A4e, against main: a STANDARD chart rule with a structure condi…"

## W2-HESTON — Heston fit quality

- **Wave:** 2  **Money impact:** LOW — Black-Scholes is a sound fallback today  **Size:** L
- **Owned files:** backend/app/services/heston_*.py; backend/app/scoring/reward_risk.py (Heston parts); scan.py Heston section.
- **Do not touch:** —

**Kenneth's decisions to implement:**

- Q19b: keep the Heston items; one low-priority phase so Heston wins more often (overpricing, grid-boundary fits, missing tests/logs).

**Backlog entries (verified still open at 8d6741d):**

- The full-grid plus rejected-fit case is still untested, so a mutation of best_params to result.params survives. Heston is parked. — *evidence:* app/models/heston_cache.py:391; tests/test_heston_calibration.py has no full-grid rejected-fit test — *entry begins:* "LOGGED AGAINST MAIN by the boundary-log round 2, NOT fixed (a coverage void on PRE-EXISTING code, not on the c…"
- The rung gate still counts rungs rather than distinct rungs. It is latent and unreachable, and was left as is. — *evidence:* app/models/heston_cache.py:280 if len(grid) < 3 — *entry begins:* "LOGGED AGAINST MAIN by the boundary-log round 2, NOT fixed (latent, unreachable, and deliberately left as writ…"
- An accepted Heston fit still logs nothing, so quality loss is silent. The fix shapes are only proposals, and Kenneth left Heston as-is. — *evidence:* app/models/heston_cache.py:413 if hits or result.method != 'heston_grid'; pending_kenneth[15] — *entry begins:* "LOGGED AGAINST MAIN by BOUNDARY-LOG-GATE-ON-GRID-2026-09-13, CREATED BY that change and deliberately NOT fixed…"
- The scan.py semaphore comment still claims the runtime is Python 3.14. The project runs 3.11. — *evidence:* backend/app/routers/scan.py:284 — *entry begins:* "LOGGED AGAINST MAIN 2026-09-14 by the GIL costing, NOT fixed (a comment, and the behaviour it describes is unr…"
- Heston fits still overprice the candidate contract, with winning fits on grid boundaries. It is parked under the 'leave Heston as-is' decision, and the grid has not been widened. — *evidence:* heston_cache.py unchanged since 2026-09-17; pending_kenneth[15] — *entry begins:* "LOGGED AGAINST MAIN by TIMEOUT-DELETE-INNER's round 2, NOT fixed and NOT attributable to that change (measured…"
- The thin-chain boundary (len<3) is still unpinned. The only test uses a 1-strike chain, so a <2 mutation survives. — *evidence:* heston_cache.py:440; tests/test_heston_calibration.py:728-735 — *entry begins:* "LOGGED AGAINST MAIN by TIMEOUT-DELETE-INNER's round 2, NOT fixed (pre-existing line the diff does not touch, c…"
- The two surviving mutations (baseline on the whole chain; the mid<=0 recheck) are still unpinned by any test. — *evidence:* heston_cache.py:338 recheck and baseline chain selection unchanged; no new tests — *entry begins:* "LOGGED AGAINST MAIN by F2 round 2, NOT fixed (untested behaviour, both unreachable today): TWO MUTATIONS SURVI…"
- The inaccurate F2 comments and tests remain: the eval count says 46 (actually 47), the bracket floor differs, the unreachable branch is untested, and the uvicorn test is weak. — *evidence:* heston_cache.py:71-72 '46 evals', :85 bracket 0.01, :369 baseline_rmse None branch — *entry begins:* "LOGGED AGAINST MAIN by F2 rounds 1 and 2, NOT fixed (comments and tests, no wrong number): FOUR CLAIMS THE F2 …"
- calibrate_cached still returns a shared mutable cached CalibrationResult. It is latent, and nothing mutates it. — *evidence:* app/models/heston_cache.py:430-445 lru_cache-backed return — *entry begins:* "LOGGED AGAINST MAIN by F2 round 2, NOT fixed (latent, nothing mutates them today): calibrate_cached returns a …"
- heston_price still clamps at 0 rather than at forward intrinsic. The two-line fix has not been applied. — *evidence:* backend/app/models/heston.py:208-211 max(..., 0.0) — *entry begins:* "BELOW THE GATE, found by F1 round 1 and deliberately NOT fixed (spec section 4 scopes heston_price's put-call …"
- heston_price still catches Exception, so warnings escalated to errors silently fall back to BS. — *evidence:* backend/app/models/heston.py:204 except Exception -> bs_price — *entry begins:* "LATENT TRAP, pre-existing and NOT introduced by F1, logged rather than fixed (the spec scopes the except -> bs…"

## W2-DOCC — Config validation (Document C / YAML-CONFIG-INTEGRITY)

- **Wave:** 2  **Money impact:** MEDIUM — a bad config edit should fail loudly, not silently  **Size:** L
- **Owned files:** backend config loading (config_loader.py, atomic_yaml.py), a config_health surface.
- **Do not touch:** —

**Kenneth's decisions to implement:**

- Q23: keep, after the defect packages. Its section-9 decisions (9.1, 9.2b, 9.3b, 9.4, 9.5, 9.6, 9.8, 9.9) must be put to Kenneth FIRST, before any plan.

**Backlog entries (verified still open at 8d6741d):**

- Doc A (regime sizing) shipped and Doc B (atomic YAML writes) built, but Doc C (config validation/surface) never started. — *evidence:* phase YAML-CONFIG-INTEGRITY not_started (probe: config_health absent in main.py); app/services/atomic_yaml.py exists — *entry begins:* "AGREED BY KENNETH 2026-09-17 AND THIS IS THE ORDER OF WORK: build DOCUMENT A (docs/superpowers/plans/2026-09-1…"
- No RecursionError catch for deep alias chains, and a non-mapping YAML root still crashes on cfg.get with AttributeError. — *evidence:* backend/app/services/config_loader.py:108-165 (unbounded recursion), :168-215 (no RecursionError handler), :198 cfg.get with no dict check — *entry begins:* "LOGGED BY Q3B ROUND 3 (2026-09-24), below the gate (fails loudly, no wrong number, needs a hand-crafted file):…"
- Atomic writes shipped separately (ATOMIC-CONFIG-WRITES, not audit-clean). Document C's validation/config_health is unbuilt, and its section 9 decisions still await Kenneth. — *evidence:* config_health absent from backend/app; services/atomic_yaml.py:77 exists; phase status not_started; s9.1/9.2b/9.3b/9.4/9.5/9.6/9.8/9.9 open — *entry begins:* "{"id": "YAML-CONFIG-INTEGRITY", "name": "YAML config integrity -- an edit either takes effect, or fails loudly…"

## MEAS — Market-data measurement (runs on Kenneth's machine)

- **Wave:** anytime  **Money impact:** HIGH — thresholds decide which trades are proposed and how they are sized  **Size:** S of code, days of calendar
- **Owned files:** docs only (a measurement protocol + results template); config changes only after Kenneth approves the proposed values.
- **Do not touch:** Everything else.

**Kenneth's decisions to implement:**

- Q20/Q28: the session prepares exact scan settings + a results sheet; Kenneth runs the scans during market hours on >= 2 different days (different regimes); the session proposes values (bearish floors, min_mult, IV rank/percentile thresholds, ivAbsThreshold) from the results. No threshold changes without Kenneth's yes.

**Backlog entries (verified still open at 8d6741d):**

- Plan of record only partly done: bearish scans measured once, probe rounds not clean, vf056m branch not deleted, below-gate sweep not done. — *evidence:* measurements/scans has only 2026-09-18; state.py shows STATE-PROBE-REVIVAL/TARGET-SCOPING none clean; origin/claude/session-retrieval-contin — *entry begins:* "PLAN OF RECORD, AGREED BY KENNETH 2026-09-16 -- HE ACCEPTED ALL FOUR RECOMMENDATIONS AND THEIR ORDER. Work the…"
- Only one day of bearish measurement; floors 30/40 not tuned. Banner still blames market structure whenever any gate reject exists. — *evidence:* scan-funnel.jsonl 6 rows, one date; routers/stock_scan.py:1381-1384 (`not candidates and _dir_filtered > 0`) — *entry begins:* "MEASURED 2026-09-18, 19:37-19:57 CEST, US REGULAR HOURS -- THE MEASUREMENT HALF OF THIS ITEM IS DONE; TUNING 3…"
- Phases E/F/G and the two removals all done; only the parked ivAbsThreshold/percentile measurement is still open. — *evidence:* phases E,F1,F2,G shipped; open_questions[58] 'ivAbsThreshold ... UNMEASURED' — *entry begins:* "DONE 2026-09-09: DIRECT-SEND-STOP-GATE merged to main at ebf5296 with a --no-ff merge commit, verified on the …"
- Phase E merged, concentration flag built; only the parked ivAbsThreshold measurement remains open. — *evidence:* StockPositionCard/index.tsx:66 concentrationFlag; open_questions[58] — *entry begins:* "DONE 2026-09-09: PHASE E (piece 6, the stocks arithmetic plan) IS BUILT, CLEAN AFTER 2 ROUNDS, PUSHED and UNME…"
- Scans were read, but whether to move min_mult is still undecided. All data comes from one day at one conviction value, so a different regime must be measured first. — *evidence:* docs/superpowers/measurements/scan-funnel.jsonl holds only the 6 rows from 2026-09-18; scoring_rules.yaml:463 regime_sizing unchanged — *entry begins:* "ANSWERED 2026-09-19 BY READING THEM -- this is sequencing condition (b) of AUTOTRADE-SIZING-SPLIT-THREE-WAYS-2…"
- The absolute-IV (ivAbsThreshold) half has never been measured. Every recorded row is on the rank basis, so a deliberate scan with the percentile source off is still needed. — *evidence:* iv-basis-samples.jsonl: all 10 rows contract_basis='rank', zero absolute rows — *entry begins:* "RESCUED 2026-09-17 FROM claude/gracious-mayer-g738w8, WHICH WAS THE ONLY BRANCH HOLDING IT and is on the appro…"
- The timing wall is gone, but bearish scans are still starved by the confidence gate and the contract floors. One day of data, so no floor has moved yet. — *evidence:* contract_rules.yaml:18-19,43 (min_volume 50, min_OI 200, min_stock_score 55); settingsStore.ts:78 rejectBelow 35 — *entry begins:* "RESCUED 2026-09-17 FROM claude/gracious-mayer-g738w8, WHICH WAS THE ONLY BRANCH HOLDING IT and is on the appro…"
- The percentile thresholds are still unmeasured seeds. The broker question is effectively answered, because rank-basis rows exist, but too few to set thresholds. — *evidence:* backend/config/scoring_rules.yaml:132 'UNMEASURED — seeded'; iv-basis-samples.jsonl 10 rank rows — *entry begins:* "Phase A percentile thresholds are UNMEASURED: iv_rank_pass_max/caution_max were seeded from the absolute set (…"
- ivAbsThreshold is still the default 50 and unmeasured. There are zero absolute-basis rows. — *evidence:* frontend/lib/settingsStore.ts:180 ivAbsThreshold: 50; iv-basis-samples.jsonl no absolute rows — *entry begins:* "ivAbsThreshold (spread picker, default 50) is UNMEASURED, the second seeded threshold in Phase A alongside the…"

## Closed as accepted (Kenneth Q13, Q21)

- Latent mixed-basis config case still unhandled; unreachable with the shipped YAML.
- Positional 'decisions[0]' references remain throughout the state file, deliberately not rewritten.
- By design, a bad regime_sizing value stays cached until the backend restarts. This is documented and accepted under section 9.2 (no reload endpoint), and not fixed.
- The asymmetry remains: entries without audit_rounds declare 0 and drift at round 1, while having no pointer gets a warn grace. This is deliberate and only revisited if the grace is.
- portfolioValue still has no upper bound, so an absurd value could overflow the Decimal math in recommendedShares. Not realistically reachable.
- Nothing ties full_conviction_pct to headwind_reject_pct or its Step-3 overrides. No wrong number, just no coupling.
- The moved add_position warnings log under app.services.position_writer. This is informational and harmless: nothing sets a level on the old logger name.
- completed_intraday_bars still requires a plain int time, so numpy.int64 is rejected (fails closed; no source produces it today).
- The warning branch for a zero entry price is still present and still untested. It is now in position_writer.py and intentionally kept as a defensive fallback.
- The 900s sandbox feed lag stays (Q13).
