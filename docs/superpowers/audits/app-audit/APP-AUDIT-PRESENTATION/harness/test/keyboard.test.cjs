'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const PRESENTATION_DIR = path.resolve(__dirname, '../..');
const EVIDENCE_KEYBOARD_DIR = path.join(PRESENTATION_DIR, 'evidence/keyboard');
const EVIDENCE_SPECIALIZED_DIR = path.join(PRESENTATION_DIR, 'evidence/specialized');

const {
  INTERACTION_FAMILIES,
  K_PROCEDURES,
  isEditableTarget,
  simulateTabTraversal,
  simulateVisibleFocus,
  simulateOperateAction,
  simulateEscapeReturn,
  simulateGlobalShortcuts,
  simulateCanvasFallback,
  runSubGateViewportAudit,
  runSeedOnceStorageAudit,
  runStaleAsyncAudit,
  executeKeyboardSuite,
} = require('../keyboard.cjs');

test('keyboard: interaction families contain all 10 required interaction categories', () => {
  assert.ok(INTERACTION_FAMILIES, 'INTERACTION_FAMILIES must be defined');
  const expectedFamilies = [
    'dialogs',
    'drawers',
    'aria_expanded_toggles',
    'details_disclosures',
    'tabs',
    'switches_radios',
    'tooltips',
    'selectable_table_rows',
    'global_shortcuts',
    'chart_canvas_fallback',
  ];

  for (const family of expectedFamilies) {
    assert.ok(
      INTERACTION_FAMILIES[family],
      `INTERACTION_FAMILIES must define configuration for ${family}`
    );
    assert.ok(
      Array.isArray(INTERACTION_FAMILIES[family].components) &&
        INTERACTION_FAMILIES[family].components.length > 0,
      `${family} must list representative components`
    );
  }
});

test('keyboard: K_PROCEDURES defines K1 through K6 audit definitions', () => {
  assert.ok(K_PROCEDURES, 'K_PROCEDURES must be defined');
  const expectedCodes = ['K1', 'K2', 'K3', 'K4', 'K5', 'K6'];
  for (const code of expectedCodes) {
    assert.ok(K_PROCEDURES[code], `Procedure ${code} must be defined`);
    assert.ok(K_PROCEDURES[code].name, `Procedure ${code} must have a name`);
    assert.ok(K_PROCEDURES[code].description, `Procedure ${code} must have a description`);
  }
});

test('keyboard: isEditableTarget correctly identifies editable form controls', () => {
  assert.equal(isEditableTarget({ tagName: 'INPUT' }), true);
  assert.equal(isEditableTarget({ tagName: 'TEXTAREA' }), true);
  assert.equal(isEditableTarget({ isContentEditable: true }), true);
  assert.equal(isEditableTarget({ tagName: 'DIV' }), false);
  assert.equal(isEditableTarget({ tagName: 'BUTTON' }), false);
  assert.equal(isEditableTarget(null), false);
});

test('keyboard: K1 Reach verifies tab reachability and flags unkeyboardable click handlers', () => {
  const accessibleNodes = [
    { tag: 'button', role: 'button', tabIndex: 0, onClick: true },
    { tag: 'a', role: 'link', tabIndex: 0, href: '/screener' },
    { tag: 'input', role: 'textbox', tabIndex: 0 },
  ];
  const reachResult = simulateTabTraversal(accessibleNodes);
  assert.equal(reachResult.status, 'passed');
  assert.equal(reachResult.reachable_count, 3);
  assert.equal(reachResult.unkeyboardable_count, 0);

  const flawedNodes = [
    { tag: 'div', onClick: true }, // missing tabIndex, role, and keydown
    { tag: 'span', onClick: true, tabIndex: -1 }, // tabIndex -1 not reachable via Tab
  ];
  const flawedResult = simulateTabTraversal(flawedNodes);
  assert.equal(flawedResult.status, 'flagged');
  assert.equal(flawedResult.unkeyboardable_count, 2);
  assert.equal(flawedResult.flags.length, 2);
});

test('keyboard: K2 Visible focus verifies outline/box-shadow change inside viewport', () => {
  const focusedInView = {
    unfocused: { outline: 'none', boxShadow: 'none' },
    focused: { outline: '2px solid rgb(59, 130, 246)', boxShadow: '0 0 0 2px rgba(59,130,246,0.5)' },
    bounds: { top: 100, left: 100, bottom: 140, right: 200, width: 100, height: 40 },
    viewport: { width: 1280, height: 800 },
  };
  const passRes = simulateVisibleFocus(focusedInView);
  assert.equal(passRes.status, 'passed');
  assert.equal(passRes.focus_indicator_visible, true);
  assert.equal(passRes.inside_viewport, true);

  const noIndicator = {
    unfocused: { outline: 'none', boxShadow: 'none' },
    focused: { outline: 'none', boxShadow: 'none' },
    bounds: { top: 50, left: 50, bottom: 90, right: 150, width: 100, height: 40 },
    viewport: { width: 1280, height: 800 },
  };
  const failRes = simulateVisibleFocus(noIndicator);
  assert.equal(failRes.status, 'flagged');
  assert.equal(failRes.focus_indicator_visible, false);

  const outOfView = {
    unfocused: { outline: 'none', boxShadow: 'none' },
    focused: { outline: '2px solid blue', boxShadow: 'none' },
    bounds: { top: 900, left: 100, bottom: 940, right: 200, width: 100, height: 40 },
    viewport: { width: 1280, height: 800 },
  };
  const outRes = simulateVisibleFocus(outOfView);
  assert.equal(outRes.status, 'flagged');
  assert.equal(outRes.inside_viewport, false);
});

test('keyboard: K3 Operate activates controls with Enter, Space, and Arrow keys', () => {
  const buttonOp = simulateOperateAction({ role: 'button', key: 'Enter' });
  assert.equal(buttonOp.status, 'passed');
  assert.equal(buttonOp.action_performed, true);

  const disclosureOp = simulateOperateAction({ role: 'disclosure', key: ' ' });
  assert.equal(disclosureOp.status, 'passed');
  assert.equal(disclosureOp.toggled, true);

  const tabOp = simulateOperateAction({ role: 'tab', key: 'ArrowRight' });
  assert.equal(tabOp.status, 'passed');
  assert.equal(tabOp.selection_changed, true);
});

test('keyboard: K4 Escape & Return closes overlays and returns focus to opener', () => {
  const dialogResult = simulateEscapeReturn({
    overlayType: 'dialog',
    openerId: 'btn-open-confirm',
    focusedInside: 'dialog-cancel-btn',
  });
  assert.equal(dialogResult.status, 'passed');
  assert.equal(dialogResult.closed_on_escape, true);
  assert.equal(dialogResult.focus_restored_to_opener, true);
  assert.equal(dialogResult.restored_target_id, 'btn-open-confirm');

  const drawerResult = simulateEscapeReturn({
    overlayType: 'drawer',
    openerId: 'btn-inspect-pipeline',
    focusedInside: 'drawer-search-input',
  });
  assert.equal(drawerResult.status, 'passed');
  assert.equal(drawerResult.closed_on_escape, true);
  assert.equal(drawerResult.focus_restored_to_opener, true);
});

test('keyboard: K5 Shortcuts verifies global navigation and suppression in editable inputs', () => {
  // Idle state: shortcuts fire
  const idleShortcuts = simulateGlobalShortcuts({
    activeElement: { tagName: 'BODY' },
    events: [
      { key: '1', pathname: '/screener' },
      { key: 'g' },
      { key: 'd' },
      { key: '?' },
    ],
  });
  assert.equal(idleShortcuts.status, 'passed');
  assert.equal(idleShortcuts.dispatched_count, 3); // 1, g+d, ?
  assert.equal(idleShortcuts.suppressed_count, 0);

  // Editable input focused: shortcuts suppressed
  const typingShortcuts = simulateGlobalShortcuts({
    activeElement: { tagName: 'INPUT' },
    events: [
      { key: '1', pathname: '/screener' },
      { key: 'g' },
      { key: 'd' },
      { key: '?' },
    ],
  });
  assert.equal(typingShortcuts.status, 'passed');
  assert.equal(typingShortcuts.dispatched_count, 0);
  assert.equal(typingShortcuts.suppressed_count, 4);
  assert.equal(typingShortcuts.suppression_reason, 'active-element-editable');
});

test('keyboard: K6 Chart canvas fallback verifies accessible text alternative exists', () => {
  const chartWithSummary = {
    hasCanvas: true,
    accessibleName: 'S&P 500 Daily Candlestick Chart',
    hasSummaryTable: true,
    hasTooltip: true,
  };
  const passCanvas = simulateCanvasFallback(chartWithSummary);
  assert.equal(passCanvas.status, 'passed');
  assert.equal(passCanvas.accessible_alternative_present, true);

  const bareCanvas = {
    hasCanvas: true,
    accessibleName: '',
    hasSummaryTable: false,
    hasTooltip: false,
  };
  const failCanvas = simulateCanvasFallback(bareCanvas);
  assert.equal(failCanvas.status, 'flagged');
  assert.equal(failCanvas.accessible_alternative_present, false);
});

test('keyboard: specialized state sub-gate viewports verify MinWidthGate triggers at 1199px and 1279px', () => {
  const subGateResult = runSubGateViewportAudit();
  assert.equal(subGateResult.status, 'passed');
  assert.ok(Array.isArray(subGateResult.checks), 'checks array must be present');
  assert.equal(subGateResult.checks.length, 2);

  const gate1199 = subGateResult.checks.find((c) => c.width === 1199);
  assert.ok(gate1199, 'check for 1199px must exist');
  assert.equal(gate1199.gate_triggered, true);
  assert.equal(gate1199.gate_message_detected, true);

  const gate1279 = subGateResult.checks.find((c) => c.width === 1279);
  assert.ok(gate1279, 'check for 1279px must exist');
  assert.equal(gate1279.gate_triggered, true);
  assert.equal(gate1279.gate_message_detected, true);
});

test('keyboard: specialized state reload-restart verifies seed-once sessionStorage guard', () => {
  const seedOnceResult = runSeedOnceStorageAudit();
  assert.equal(seedOnceResult.status, 'passed');
  assert.equal(seedOnceResult.seed_once_guard_verified, true);
  assert.equal(seedOnceResult.reloads_tested, 3);
  assert.equal(seedOnceResult.dirty_state_preserved_on_reload, true);
  assert.equal(seedOnceResult.corrupted_storage_handled, true);
});

test('keyboard: specialized state stale-async verifies out-of-order response discard', () => {
  const staleAsyncResult = runStaleAsyncAudit();
  assert.equal(staleAsyncResult.status, 'passed');
  assert.equal(staleAsyncResult.out_of_order_discarded, true);
  assert.equal(staleAsyncResult.newest_response_retained, true);
  assert.equal(staleAsyncResult.unmounted_discarded, true);
});

test('keyboard: executeKeyboardSuite generates evidence records for all families and specialized states', async () => {
  const res = await executeKeyboardSuite({
    evidenceKeyboardDir: EVIDENCE_KEYBOARD_DIR,
    evidenceSpecializedDir: EVIDENCE_SPECIALIZED_DIR,
  });

  assert.equal(res.status, 'ok');
  assert.ok(res.total_files > 0, 'must generate evidence files');
  assert.equal(res.families_covered, 10, 'must cover all 10 interaction families');
  assert.equal(res.specialized_covered, 3, 'must cover all 3 specialized states');

  // Verify files exist on disk
  const expectedFamilyFiles = [
    'dialogs.json',
    'drawers.json',
    'aria_expanded_toggles.json',
    'details_disclosures.json',
    'tabs.json',
    'switches_radios.json',
    'tooltips.json',
    'selectable_table_rows.json',
    'global_shortcuts.json',
    'chart_canvas_fallback.json',
    'summary.json',
  ];
  for (const f of expectedFamilyFiles) {
    const p = path.join(EVIDENCE_KEYBOARD_DIR, f);
    assert.ok(fs.existsSync(p), `evidence file ${f} must exist in keyboard evidence dir`);
    const parsed = JSON.parse(fs.readFileSync(p, 'utf8'));
    assert.ok(parsed, `file ${f} must contain valid JSON`);
  }

  const expectedSpecializedFiles = [
    'sub-gate.json',
    'reload-restart.json',
    'stale-async.json',
  ];
  for (const f of expectedSpecializedFiles) {
    const p = path.join(EVIDENCE_SPECIALIZED_DIR, f);
    assert.ok(fs.existsSync(p), `evidence file ${f} must exist in specialized evidence dir`);
    const parsed = JSON.parse(fs.readFileSync(p, 'utf8'));
    assert.ok(parsed, `file ${f} must contain valid JSON`);
  }
});
