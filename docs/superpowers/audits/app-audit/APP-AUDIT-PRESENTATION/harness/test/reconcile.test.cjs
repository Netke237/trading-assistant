'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const PRESENTATION_DIR = path.resolve(__dirname, '../..');
const REPO = path.resolve(PRESENTATION_DIR, '../../../../..');
const J1_DIR = path.resolve(PRESENTATION_DIR, '../APP-AUDIT-PRESENTATION-ATTRIBUTION');
const INVENTORY_DIR = path.resolve(PRESENTATION_DIR, '../APP-AUDIT-INVENTORY');

const TRIAGE_PATH = path.join(PRESENTATION_DIR, 'triage.json');
const DEFECTS_PATH = path.join(PRESENTATION_DIR, 'defects.json');
const HANDOFFS_PATH = path.join(PRESENTATION_DIR, 'handoffs.json');
const RECONCILIATION_PATH = path.join(PRESENTATION_DIR, 'reconciliation.json');
const REPORT_PATH = path.join(PRESENTATION_DIR, 'report.md');
const README_PATH = path.join(PRESENTATION_DIR, 'README.md');

const {
  expandInventory,
  validateReconciliation,
  VALID_DISPOSITIONS,
} = require(path.join(J1_DIR, 'harness/verify-coverage.cjs'));

const {
  reconcilePresentation,
  loadAuditInputs,
  generateReportMd,
  executeReconciliationSuite,
} = require('../reconcile.cjs');

test('reconcile: inventory expansion recomputes exactly 52,308 requirements across all 10 levels', () => {
  const { inventory, supplemental } = loadAuditInputs();
  const expansion = expandInventory(inventory, supplemental);

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

test('reconcile: triage.json, defects.json, and handoffs.json conform to schema and requirements', () => {
  assert.ok(fs.existsSync(TRIAGE_PATH), 'triage.json must exist');
  assert.ok(fs.existsSync(DEFECTS_PATH), 'defects.json must exist');
  assert.ok(fs.existsSync(HANDOFFS_PATH), 'handoffs.json must exist');

  const triage = JSON.parse(fs.readFileSync(TRIAGE_PATH, 'utf8'));
  const defects = JSON.parse(fs.readFileSync(DEFECTS_PATH, 'utf8'));
  const handoffs = JSON.parse(fs.readFileSync(HANDOFFS_PATH, 'utf8'));

  assert.ok(Array.isArray(triage.candidates), 'triage must have candidates array');
  assert.ok(triage.candidates.length > 0, 'triage candidates populated');
  for (const c of triage.candidates) {
    assert.ok(c.candidate_id, 'candidate_id required');
    assert.ok(['finding', 'not-a-finding'].includes(c.verdict), 'verdict must be finding or not-a-finding');
    assert.ok(typeof c.justification === 'string' && c.justification.trim(), 'justification required');
  }

  assert.ok(Array.isArray(defects), 'defects must be an array');
  assert.ok(defects.length > 0, 'defects must record confirmed defects');
  for (const d of defects) {
    assert.match(d.id, /^J-\d{3}$/, 'defect ID must match J-NNN format');
    assert.ok(d.title, 'title required');
    assert.ok(Array.isArray(d.affected_routes), 'affected_routes must be array');
    assert.ok(d.reproduction_command, 'reproduction_command required');
    assert.ok(d.expected, 'expected required');
    assert.ok(d.actual, 'actual required');
    assert.ok(['blocks-use', 'misleading', 'degraded', 'cosmetic'].includes(d.severity_class), 'severity class valid');
    assert.ok(d.proposed_owning_remediation_lane, 'proposed lane required');
  }

  assert.ok(Array.isArray(handoffs), 'handoffs must be an array');
  assert.ok(handoffs.length > 0, 'handoffs must record domain anomalies');
  for (const h of handoffs) {
    assert.ok(h.id, 'handoff id required');
    assert.ok(h.title, 'title required');
    assert.match(h.domain_lane, /^Lane [B-I]/, 'domain_lane must be one of lanes B-I');
    assert.ok(h.anomaly_type, 'anomaly_type required');
  }
});

test('reconcile: reconcilePresentation generates exactly 52,308 rows and passes validateReconciliation', () => {
  const inputs = loadAuditInputs();
  const recon = reconcilePresentation(inputs);

  assert.equal(recon.rows.length, 52308, 'reconciliation must contain exactly 52,308 rows');

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
  assert.ok(result.counts_by_disposition['observed-verified'] > 0, 'must have verified rows');
  assert.ok(result.counts_by_disposition['observed-asserted'] > 0, 'must have asserted rows');
});

test('reconcile: strict predicate enforcement guarantees zero non-normal/native/server verified rows', () => {
  const inputs = loadAuditInputs();
  const recon = reconcilePresentation(inputs);
  const expansion = expandInventory(inputs.inventory, inputs.supplemental);
  const rowsById = new Map(recon.rows.map(r => [r.id, r]));

  for (const req of expansion.allRows) {
    const r = rowsById.get(req.id);
    assert.ok(r, `row ${req.id} must exist in reconciliation`);

    if (r.disposition === 'observed-verified') {
      // Must only be route-entry or definition/component-instance/component-state with normal state
      assert.ok(
        req.kind === 'route-entry' ||
        req.kind === 'definition' ||
        req.kind === 'component-instance' ||
        (req.kind === 'component-state' && req.state_key === 'normal'),
        `verified disposition forbidden on kind ${req.kind}`
      );

      // Natives must never be verified
      assert.notEqual(req.kind, 'native-instance', 'native-instance must never be observed-verified');
      assert.notEqual(req.kind, 'native-state', 'native-state must never be observed-verified');

      // Supplemental states must never be verified
      assert.notEqual(req.kind, 'supplemental-state', 'supplemental-state must never be observed-verified');
      assert.notEqual(req.kind, 'supplemental-route-state', 'supplemental-route-state must never be observed-verified');
    }
  }
});

test('reconcile: report.md contains exact presence probe APP-AUDIT-PRESENTATION-EXECUTION and summary', () => {
  assert.ok(fs.existsSync(REPORT_PATH), 'report.md must exist');
  const content = fs.readFileSync(REPORT_PATH, 'utf8');

  assert.match(content, /^# APP-AUDIT-PRESENTATION-EXECUTION/m, 'must contain exact presence probe heading');
  assert.match(content, /52,?308/, 'must cite 52,308 total requirement rows');
  assert.match(content, /observed-verified/i, 'must cite observed-verified count');
  assert.match(content, /observed-asserted/i, 'must cite observed-asserted count');
});

test('reconcile: README.md documents architecture and reproduction commands', () => {
  assert.ok(fs.existsSync(README_PATH), 'README.md must exist');
  const content = fs.readFileSync(README_PATH, 'utf8');

  assert.match(content, /reconcile\.cjs/, 'must reference reconcile.cjs');
  assert.match(content, /node --test/, 'must document test reproduction command');
});
