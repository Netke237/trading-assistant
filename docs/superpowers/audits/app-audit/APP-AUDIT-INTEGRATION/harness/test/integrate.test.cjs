'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const INTEGRATION_DIR = path.resolve(__dirname, '../..');
const REPO = path.resolve(INTEGRATION_DIR, '../../../../..');
const J1_DIR = path.resolve(INTEGRATION_DIR, '../APP-AUDIT-PRESENTATION-ATTRIBUTION');
const PRESENTATION_DIR = path.resolve(INTEGRATION_DIR, '../APP-AUDIT-PRESENTATION');
const INV_DIR = path.resolve(INTEGRATION_DIR, '../APP-AUDIT-INVENTORY');

const RECONCILIATION_PATH = path.join(INTEGRATION_DIR, 'reconciliation.json');
const REPORT_PATH = path.join(INTEGRATION_DIR, 'report.md');
const README_PATH = path.join(INTEGRATION_DIR, 'README.md');
const DEFECTS_PATH = path.join(INTEGRATION_DIR, 'integrated-defects.json');

const {
  expandInventory,
  validateReconciliation,
  VALID_DISPOSITIONS,
} = require(path.join(J1_DIR, 'harness/verify-coverage.cjs'));

const {
  loadAuditInputs,
  reconcileIntegration,
  generateReportMd,
  generateReadmeMd,
  executeIntegrationSuite,
} = require('../integrate.cjs');

test('integrate: inventory expansion recomputes exactly 52,308 requirements across all 10 levels', () => {
  const inputs = loadAuditInputs();
  const expansion = expandInventory(inputs.inventory, inputs.supplemental);

  assert.equal(expansion.counts.route_entries, 45, '45 route entries');
  assert.equal(expansion.counts.definitions, 283, '283 definitions');
  assert.equal(expansion.counts.component_instances, 2269, '2,269 component instances');
  assert.equal(expansion.counts.component_states, 20421, '20,421 component states');
  assert.equal(expansion.counts.native_instances, 2900, '2,900 native instances');
  assert.equal(expansion.counts.native_states, 26100, '26,100 native states');
  assert.equal(expansion.counts.supplemental_capabilities, 4, '4 supplemental capabilities');
  assert.equal(expansion.counts.supplemental_capability_states, 77, '77 supplemental capability states');
  assert.equal(expansion.counts.supplemental_route_instances, 11, '11 supplemental route instances');
  assert.equal(expansion.counts.supplemental_route_state_requirements, 198, '198 supplemental route states');
  assert.equal(expansion.counts.total_requirements, 52308, '52,308 total inventory requirement rows');
});

test('integrate: reconciliation.json contains exactly 52,308 rows and passes validateReconciliation cleanly', () => {
  assert.ok(fs.existsSync(RECONCILIATION_PATH), 'reconciliation.json must exist');
  const recon = JSON.parse(fs.readFileSync(RECONCILIATION_PATH, 'utf8'));

  assert.equal(recon.rows.length, 52308, 'reconciliation must contain exactly 52,308 rows');

  const inputs = loadAuditInputs();
  const result = validateReconciliation({
    inventory: inputs.inventory,
    supplemental: inputs.supplemental,
    reconciliation: recon,
    sourceMap: inputs.sourceMap,
    evidenceRoot: PRESENTATION_DIR,
    expectedSourceSha: inputs.sourceSha,
    expectedInventorySha: inputs.inventorySha,
  });

  assert.equal(result.valid, true, 'validateReconciliation must succeed');

  // Verify multi-dimensional attribution: every row carries domain ownership
  for (const row of recon.rows) {
    assert.ok(row.id, 'row must have id');
    assert.ok(VALID_DISPOSITIONS.has(row.disposition), `valid disposition on ${row.id}`);
    assert.ok(row.owners, `owners object required on ${row.id}`);
    assert.ok(row.owners.numeric, `owners.numeric required on ${row.id}`);
    assert.ok(row.owners.persistence, `owners.persistence required on ${row.id}`);
    assert.ok(row.owners.presentation, `owners.presentation required on ${row.id}`);
    assert.ok(row.owners.navigation, `owners.navigation required on ${row.id}`);
  }
});

test('integrate: strict predicate enforcement guarantees zero non-normal/native/server verified rows', () => {
  assert.ok(fs.existsSync(RECONCILIATION_PATH), 'reconciliation.json must exist');
  const recon = JSON.parse(fs.readFileSync(RECONCILIATION_PATH, 'utf8'));
  const inputs = loadAuditInputs();
  const expansion = expandInventory(inputs.inventory, inputs.supplemental);
  const rowsById = new Map(recon.rows.map(r => [r.id, r]));

  for (const req of expansion.allRows) {
    const r = rowsById.get(req.id);
    assert.ok(r, `row ${req.id} must exist in reconciliation`);

    if (r.disposition === 'observed-verified') {
      // Must only be route-entry, definition, component-instance, or normal component-state
      assert.ok(
        req.kind === 'route-entry' ||
        req.kind === 'definition' ||
        req.kind === 'component-instance' ||
        (req.kind === 'component-state' && req.state_key === 'normal'),
        `verified disposition forbidden on kind ${req.kind} (${req.id})`
      );

      // Natives must never be verified
      assert.notEqual(req.kind, 'native-instance', `native-instance must never be observed-verified (${req.id})`);
      assert.notEqual(req.kind, 'native-state', `native-state must never be observed-verified (${req.id})`);

      // Supplemental states must never be verified
      assert.notEqual(req.kind, 'supplemental-state', `supplemental-state must never be observed-verified (${req.id})`);
      assert.notEqual(req.kind, 'supplemental-route-state', `supplemental-route-state must never be observed-verified (${req.id})`);
    }
  }
});

test('integrate: exact disposition counts verified (4577 verified, 33330 asserted, 14261 ambiguous, 140 not-run)', () => {
  assert.ok(fs.existsSync(RECONCILIATION_PATH), 'reconciliation.json must exist');
  const recon = JSON.parse(fs.readFileSync(RECONCILIATION_PATH, 'utf8'));

  const counts = {
    'observed-verified': 0,
    'observed-asserted': 0,
    'observed-ambiguous': 0,
    'not-run': 0,
  };

  for (const row of recon.rows) {
    counts[row.disposition] = (counts[row.disposition] || 0) + 1;
  }

  assert.equal(counts['observed-verified'], 4577, '4,577 observed-verified rows');
  assert.equal(counts['observed-asserted'], 33330, '33,330 observed-asserted rows');
  assert.equal(counts['observed-ambiguous'], 14261, '14,261 observed-ambiguous rows');
  assert.equal(counts['not-run'], 140, '140 not-run rows');
  assert.equal(
    counts['observed-verified'] + counts['observed-asserted'] + counts['observed-ambiguous'] + counts['not-run'],
    52308,
    'Total 52,308 rows'
  );
});

test('integrate: report.md contains exact heading # APP-AUDIT-INTEGRATION, 3 verdicts, and references all 48 defects', () => {
  assert.ok(fs.existsSync(REPORT_PATH), 'report.md must exist');
  const content = fs.readFileSync(REPORT_PATH, 'utf8');

  // Exact heading to satisfy presence probe
  assert.match(content, /^# APP-AUDIT-INTEGRATION/m, 'must contain exact presence probe heading');
  assert.match(content, /52,?308/, 'must cite 52,308 total inventory rows');

  // Verdict 1 (Numeric & Persistence Gate)
  assert.match(content, /Verdict 1.*Numeric.*Persistence/i, 'must state Verdict 1');
  assert.match(content, /PASS/, 'Verdict 1 must be PASS');
  assert.match(content, /18 code defects identified in earlier lanes have been fully resolved/, 'must cite 18 resolved defects in Verdict 1');
  assert.ok(!content.includes('29 code defects'), 'must not misstate resolved defect count as 29');

  // Verdict 2 (Presentation & Usability Gate)
  assert.match(content, /Verdict 2.*Presentation.*Usability/i, 'must state Verdict 2');
  assert.match(content, /PASS with residual findings/i, 'Verdict 2 must be PASS with residual findings');

  // Verdict 3 (Operational Reality & Dependencies)
  assert.match(content, /Verdict 3.*Operational Reality/i, 'must state Verdict 3');

  // 4 Journeys
  assert.match(content, /journey_1_options|Journey 1.*Options/i, 'must report Journey 1');
  assert.match(content, /journey_2_stocks|Journey 2.*Stocks/i, 'must report Journey 2');
  assert.match(content, /journey_3_prebreakout|Journey 3.*Pre-Breakout/i, 'must report Journey 3');
  assert.match(content, /journey_4_cross_store_isolation|Journey 4.*Cross-Store Concurrency/i, 'must report Journey 4');

  // All 48 defects referenced
  const defects = JSON.parse(fs.readFileSync(DEFECTS_PATH, 'utf8'));
  assert.equal(defects.length, 48, 'Must have 48 defects in registry');
  for (const d of defects) {
    assert.ok(
      content.includes(d.defect_id),
      `report.md must cite defect ${d.defect_id} (${d.title})`
    );
  }
});

test('integrate: README.md documents architecture and reproduction commands', () => {
  assert.ok(fs.existsSync(README_PATH), 'README.md must exist');
  const content = fs.readFileSync(README_PATH, 'utf8');

  assert.match(content, /integrate\.cjs/, 'must reference integrate.cjs');
  assert.match(content, /node --test docs\/superpowers\/audits\/app-audit\/APP-AUDIT-INTEGRATION\/harness\/test\/\*\.test\.cjs/, 'must document test reproduction command');
  assert.match(content, /Programme #348/i, 'must reference Programme #348 closure');
});
