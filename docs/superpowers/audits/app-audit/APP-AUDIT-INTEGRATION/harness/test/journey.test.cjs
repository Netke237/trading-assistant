'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const INTEGRATION_DIR = path.resolve(__dirname, '../..');
const EVIDENCE_JOURNEYS_DIR = path.join(INTEGRATION_DIR, 'evidence/journeys');

const {
  runJourney1Options,
  runJourney2Stocks,
  runJourney3PreBreakout,
  runJourney4CrossStoreIsolation,
  runAllJourneys,
  STRATEGIES_7,
  PREBREAKOUT_SUBMODES,
  PERSISTENCE_KEYS,
} = require('../journey.cjs');

test('journey 1: Options Mode executes Steps 1-7, verifies manual basket booking, broker payload, and alert emission', async () => {
  const result = await runJourney1Options();

  assert.equal(result.journey_id, 'journey_1_options');
  assert.equal(result.verdict, 'PASS');
  assert.ok(result.steps.length >= 7, 'Must execute all 7 steps');

  // Step 1: Regime
  const s1 = result.steps.find((s) => s.step === 1);
  assert.ok(s1, 'Step 1 must exist');
  assert.match(s1.direction, /^(Bullish|Bearish)$/);
  assert.match(s1.regime_status, /^(PASS|CAUTION|REJECT)$/);

  // Step 2: Universe
  const s2 = result.steps.find((s) => s.step === 2);
  assert.ok(s2, 'Step 2 must exist');
  assert.match(s2.universe, /^(SP500|NDX100|DOW30)$/);

  // Step 3: Direction & Horizon
  const s3 = result.steps.find((s) => s.step === 3);
  assert.ok(s3, 'Step 3 must exist');
  assert.equal(s3.direction, 'Bullish');
  assert.equal(s3.horizonPreset, 'Swing');

  // Step 4: Ranking
  const s4 = result.steps.find((s) => s.step === 4);
  assert.ok(s4, 'Step 4 must exist');
  assert.ok(Array.isArray(s4.candidates) && s4.candidates.length > 0, 'Ranked candidates must be present');
  assert.ok(s4.candidates[0].score > 0, 'Candidate must have positive score');

  // Step 5: Vol / Events
  const s5 = result.steps.find((s) => s.step === 5);
  assert.ok(s5, 'Step 5 must exist');
  assert.ok(s5.iv_rank_threshold != null, 'IV rank threshold must be defined');
  assert.ok(s5.event_window != null, 'Event proximity window must be defined');
  assert.ok(s5.event_window.reject_days != null, 'Reject days window must be defined');

  // Step 6: Contracts Selection
  const s6 = result.steps.find((s) => s.step === 6);
  assert.ok(s6, 'Step 6 must exist');
  assert.ok(s6.selected_contract, 'Contract must be selected');
  assert.ok(s6.contract_columns.includes('strike'), '12-col contract table must include strike');
  assert.ok(s6.contract_columns.includes('delta'), '12-col contract table must include delta');
  assert.equal(s6.contract_columns.length, 12, 'Must feature exact 12-column sortable table');

  // Step 7: Trade Card, Basket SendToBrokerDialog, Broker Order Stub & Alert Emission
  const s7 = result.steps.find((s) => s.step === 7);
  assert.ok(s7, 'Step 7 must exist');
  assert.ok(s7.basket_booking, 'Basket booking must be recorded');
  assert.equal(s7.basket_booking.source, 'manual', "Basket booking in SendToBrokerDialog MUST have source: 'manual'");
  assert.ok(s7.broker_order, 'Direct trade card broker order must be present');
  assert.equal(s7.broker_order.broker, 'tradier_paper');
  assert.equal(s7.broker_order.action, 'BUY');
  assert.equal(s7.broker_order.effect, 'OPEN');
  assert.equal(s7.broker_order.order_type, 'LMT');
  assert.ok(s7.broker_order.limit_price > 0);
  assert.ok(s7.position_booked, 'Portfolio position must be booked');
  assert.match(s7.position_booked.sourceLabel, /Tradier.*Limit.*ID:/);
  assert.ok(s7.alert_emitted, 'Alert must be emitted');
  assert.ok(s7.alert_emitted.recId, 'Emitted alert must have recId');
  assert.match(s7.alert_emitted.alertType, /^(STOP_REACHED|PREMIUM_STOP|TP_HIT|TIME_STOP)$/);
});

test('journey 2: Stocks Mode executes 6-step workflow, verifies 7 strategies, step-5 redirect, backtest and execution', async () => {
  const result = await runJourney2Stocks();

  assert.equal(result.journey_id, 'journey_2_stocks');
  assert.equal(result.verdict, 'PASS');

  // Step 1: Regime check
  const s1 = result.steps.find((s) => s.step === 1);
  assert.ok(s1 && s1.regime_status, 'Step 1 regime check');

  // Step 2: Universe
  const s2 = result.steps.find((s) => s.step === 2);
  assert.ok(s2 && s2.universe, 'Step 2 universe');

  // Step 3: Direction & Position Horizon
  const s3 = result.steps.find((s) => s.step === 3);
  assert.ok(s3, 'Step 3 must exist');
  assert.equal(s3.direction, 'Bullish');
  assert.equal(s3.horizonPreset, 'Position');

  // Step 4: Stock scan candidates & 7 strategies
  const s4 = result.steps.find((s) => s.step === 4);
  assert.ok(s4, 'Step 4 must exist');
  assert.ok(Array.isArray(s4.strategies), 'Strategies list must be present');
  assert.equal(s4.strategies.length, 7, 'Must expose all 7 stock strategies');

  const expected7 = [
    'pullback_ema',
    'breakout_base',
    'ma_crossover',
    'mean_reversion_rsi',
    'mean_reversion_bb',
    'mean_reversion_vwap',
    'mean_reversion_multi',
  ];
  for (const stratKey of expected7) {
    assert.ok(s4.strategies.some((st) => st.key === stratKey), `Strategy ${stratKey} must be present`);
  }
  assert.ok(s4.strategy_params_panel, 'StrategyParamsPanel parameters must be verified');
  assert.equal(s4.strategy_params_panel.pullbackEmaPeriod, 20);

  // Step 5: Verification that /screener/step-5-strategy acts as redirect
  const s5 = result.steps.find((s) => s.step === 5);
  assert.ok(s5, 'Step 5 check must exist');
  assert.equal(s5.is_redirect, true, 'Step 5 must act as redirect');
  assert.equal(s5.target_route, '/screener/step-4-stocks', 'Step 5 redirects to step-4-stocks');

  // Step 6: Backtest metrics & confidence gate evaluation
  const s6 = result.steps.find((s) => s.step === 6);
  assert.ok(s6, 'Step 6 must exist');
  assert.ok(s6.backtest_metrics, 'Backtest metrics must be present');
  assert.ok(s6.backtest_metrics.win_rate != null);
  assert.ok(s6.backtest_metrics.expectancy != null);
  assert.equal(s6.confidence_gate.evaluated, true);
  assert.equal(s6.confidence_gate.passes_gate, true);

  // Step 7: Position card preview -> broker order stub
  const s7 = result.steps.find((s) => s.step === 7);
  assert.ok(s7, 'Step 7 must exist');
  assert.ok(s7.position_card_data, 'PositionCardData preview must exist');
  assert.ok(s7.broker_order, 'Stock broker order stub must exist');
  assert.equal(s7.broker_order.broker, 'alpaca_paper');
  assert.equal(s7.broker_order.side, 'buy');
  assert.equal(s7.broker_order.type, 'limit');
  assert.ok(s7.broker_order.qty > 0);
  assert.ok(s7.position_booked, 'Stock position must be booked to portfolioStore');
  assert.match(s7.position_booked.sourceLabel, /Alpaca.*Limit.*ID:/);
});

test('journey 3: Pre-Breakout / Setup Mode verifies 3 sub-modes, metrics, WatchStar, CompositeAlertDialog & Chart handoff', async () => {
  const result = await runJourney3PreBreakout();

  assert.equal(result.journey_id, 'journey_3_prebreakout');
  assert.equal(result.verdict, 'PASS');

  // Shared steps 1-3
  const s1 = result.steps.find((s) => s.step === 1);
  const s2 = result.steps.find((s) => s.step === 2);
  const s3 = result.steps.find((s) => s.step === 3);
  assert.ok(s1 && s2 && s3, 'Shared Steps 1-3 must execute');

  // Step 4 Sub-modes
  const s4 = result.steps.find((s) => s.step === 4);
  assert.ok(s4, 'Step 4 setup scanner must exist');
  assert.ok(s4.submodes, 'Submodes must exist');
  assert.ok(s4.submodes.prebreakout, 'prebreakout submode must be evaluated');
  assert.ok(s4.submodes.pullback, 'pullback submode must be evaluated');
  assert.ok(s4.submodes.fib, 'fib submode must be evaluated');

  // Verify metrics per sub-mode
  const pb = s4.submodes.prebreakout;
  assert.ok(pb.metrics.atr_pct != null, 'ATR % must be present');
  assert.ok(pb.metrics.consolidation_days != null, 'Consolidation days must be present');
  assert.ok(pb.metrics.tightness_ratio != null, 'Tightness ratio must be present');
  assert.ok(pb.metrics.volume_contraction_ratio != null, 'Volume contraction ratio must be present');

  const pull = s4.submodes.pullback;
  assert.ok(pull.metrics.distance_to_ema != null, 'Distance to EMA must be present');
  assert.ok(pull.metrics.bounce_confirmed != null, 'Bounce confirmed must be present');

  const fib = s4.submodes.fib;
  assert.ok(fib.metrics.anchor_swing_range != null, 'Anchor swing range must be present');
  assert.ok(fib.metrics.fib_level_hit != null, 'Fib level hit must be present (e.g. 0.618)');
  assert.ok(fib.metrics.reversal_tolerance_pct != null, 'Reversal tolerance % must be present');

  // Verify inline actions & handoffs
  assert.ok(s4.watch_star_action, 'WatchStar toggle must be executed');
  assert.equal(s4.watch_star_action.starred, true);
  assert.ok(s4.composite_alert_dialog, 'CompositeAlertDialog must be triggered');
  assert.ok(s4.composite_alert_dialog.symbol);
  assert.ok(s4.composite_alert_dialog.price_level);

  // Standalone chart workspace deep-dive handoff
  assert.ok(s4.chart_workspace_handoff, 'Chart workspace handoff must exist');
  assert.match(s4.chart_workspace_handoff.href, /^\/chart\?symbol=/);
  assert.ok(s4.chart_workspace_handoff.href.includes('setup='));
});

test('journey 4: Cross-Store Concurrency, Mode Switching & Stale Async Isolation', async () => {
  const result = await runJourney4CrossStoreIsolation();

  assert.equal(result.journey_id, 'journey_4_cross_store_isolation');
  assert.equal(result.verdict, 'PASS');

  // Concurrency & mode switching
  const ms = result.mode_switching;
  assert.ok(ms, 'Mode switching test must exist');
  assert.equal(ms.modes_tested.length, 3);
  assert.equal(ms.parameters_cross_contaminated, false, 'Strategy parameters must NOT cross-contaminate');
  assert.equal(ms.filter_constraints_leaked, false, 'Filter constraints must NOT leak across modes');

  // Stale async isolation
  const sai = result.stale_async_isolation;
  assert.ok(sai, 'Stale async isolation test must exist');
  assert.equal(sai.simulated_scenario, 'late_options_response_arriving_in_stocks_mode');
  assert.equal(sai.scan_result_updated, true, 'scanResult must receive options payload');
  assert.equal(sai.stock_scan_result_corrupted, false, 'stockScanResult must NOT be overwritten or corrupted');
  assert.equal(sai.stock_scan_result_preserved, true, 'stockScanResult must preserve its original state');

  // Persistence reload test
  const pr = result.persistence_reload;
  assert.ok(pr, 'Persistence reload test must exist');
  const expectedKeys = [
    'bamendjou:theme',
    'bamendjou-settings',
    'bamendjou-watchlist-v1',
    'bamendjou-portfolio-v1',
    'bamendjou-risk-v1',
    'bamendjou-alerts-v2',
    'bamendjou:drawings',
  ];
  for (const key of expectedKeys) {
    assert.ok(pr.rehydrated_stores[key], `Store key ${key} must rehydrate successfully`);
    assert.equal(pr.rehydrated_stores[key].parse_error, null, `Store ${key} must have zero parse errors`);
    assert.equal(pr.rehydrated_stores[key].integrity_verified, true, `Store ${key} integrity must be verified`);
  }
});

test('runAllJourneys writes structured JSON evidence files for all 4 journeys', async () => {
  const summary = await runAllJourneys();

  assert.equal(summary.journeys_run, 4);
  assert.equal(summary.all_passed, true);

  const expectedEvidenceFiles = [
    'journey_1_options.json',
    'journey_2_stocks.json',
    'journey_3_prebreakout.json',
    'journey_4_cross_store_isolation.json',
  ];

  for (const filename of expectedEvidenceFiles) {
    const fullPath = path.join(EVIDENCE_JOURNEYS_DIR, filename);
    assert.ok(fs.existsSync(fullPath), `Evidence file must exist on disk: ${filename}`);
    const data = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
    assert.ok(data.journey_id, `${filename} must have journey_id`);
    assert.equal(data.verdict, 'PASS', `${filename} verdict must be PASS`);
    assert.ok(data.timestamp, `${filename} must have timestamp`);
  }
});
