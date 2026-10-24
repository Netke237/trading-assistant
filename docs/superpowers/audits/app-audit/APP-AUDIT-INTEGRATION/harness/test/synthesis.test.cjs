'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const INTEGRATION_DIR = path.resolve(__dirname, '../..');
const REPO_ROOT = path.resolve(INTEGRATION_DIR, '../../../../..');

const PROVENANCE_PATH = path.join(INTEGRATION_DIR, 'provenance.json');
const DEFECTS_PATH = path.join(INTEGRATION_DIR, 'integrated-defects.json');
const COVERAGE_MATRIX_PATH = path.join(INTEGRATION_DIR, 'coverage-matrix.json');

const EXPECTED_ARTIFACTS = {
  // 6 reconciliation.json files
  'docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/reconciliation.json':
    '3f63aea88b309213cff4a2397558d010033c2a1faf389cb09f8c3f2cbd0228d0',
  'docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/reconciliation.json':
    '4d54ca733139808b53fb4fda3bf47fea7606e684fc148a8180b8aad93645a181',
  'docs/superpowers/audits/app-audit/APP-AUDIT-STOCKS/reconciliation.json':
    '75f2c25079ccfeadab7ae70c3fa3a0757acc0d7e86b30e00f069e9566df7254e',
  'docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/reconciliation.json':
    'b4ba9cbc9b9ef67d26b30809c15d5b118bf9ac7a21814c465afeee6050e9ed48',
  'docs/superpowers/audits/app-audit/APP-AUDIT-PERSISTENCE/reconciliation.json':
    'cfc6e8773f5162756feb027e51ee8c704af3dfe1ed21c9d19effeae2bfcc78b5',
  'docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION/reconciliation.json':
    'b33ca0fd0465e9f9f8fd2795c128ee2baa1ffc6146d5aa9942cd2344ae0126c9',

  // 8 defects.json files
  'docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/defects.json':
    '7c23951667201f6360c9d4f0255ea954d969ab5c15233b7a7424fc73e9fa8539',
  'docs/superpowers/audits/app-audit/APP-AUDIT-OPTIONS/defects.json':
    'a9438a8c69c42f1e621b0b3eef195a0de42bd7cee2eb31ce784faabfc44016dd',
  'docs/superpowers/audits/app-audit/APP-AUDIT-STOCKS/defects.json':
    '3b9be601a5e7e5ffc7a1f6814d23a25725ce6b4e02459e460c89031c2c3bf281',
  'docs/superpowers/audits/app-audit/APP-AUDIT-PREBREAKOUT/defects.json':
    '6b317a0c02d420744730ae54a7e3e4deb776fb8c4737f890cf8cad49ab4acc18',
  'docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/defects.json':
    '56e35697dce09ac7ea5904001db37b3a131ef01d4aa0ae6249a61b374eed5031',
  'docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/defects.json':
    '5019dbaf2ba973da9f3c36f4ed4091673cc9a07f1aa4d4a603e50904d9a80871',
  'docs/superpowers/audits/app-audit/APP-AUDIT-PERSISTENCE/defects.json':
    'a5d1ab3521b7f17be48c802f9ed03db60be8d59e52c3e85fdbe3a0b56777561a',
  'docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION/defects.json':
    'fa37e3ae331a88046bbe5d9487d17a3ca54894414ab40a3705e8b07bd95fdf38',

  // Lane A findings.json
  'docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/findings.json':
    '93c67866263fe1a7a47b213c59249c160c790775999bcfa15d0ecad26d3c49ca',

  // Lane H report.md
  'docs/superpowers/audits/app-audit/APP-AUDIT-ANALYTICS-DATA/report.md':
    'a5c305af38eb7fa733d64e2e06874b52484a7c285931b795cfb5347e65e7c78e',
};

test('synthesis: provenance.json exists and conforms to required schema and digests', () => {
  assert.ok(fs.existsSync(PROVENANCE_PATH), 'provenance.json must exist');
  const prov = JSON.parse(fs.readFileSync(PROVENANCE_PATH, 'utf8'));

  assert.equal(prov.source_commit, '500fa563da47ea2dcd001b9ac1e87aa8f2c1055f', 'pinned commit SHA');
  assert.match(prov.environment.node_version, /^v?20\./, 'Node version v20.x');
  assert.equal(prov.environment.nextjs_version, '15.5.23', 'Next.js 15.5.23');
  assert.equal(prov.environment.react_version, '19.2.5', 'React 19.2.5');
  assert.equal(prov.environment.python_version, '3.11.9', 'Python 3.11.9');
  assert.match(prov.environment.playwright_version, /^1\.51\./, 'Playwright 1.51.x');
  assert.equal(prov.environment.chromium_build, '151.0.7922.34', 'Chromium build 151.0.7922.34');
  assert.equal(prov.timezone, 'Europe/Berlin', 'System timezone Europe/Berlin');
  assert.ok(prov.fixed_clock_timestamp, 'Fixed clock timestamp must be set');

  assert.ok(prov.artifact_digests, 'artifact_digests must exist');
  assert.equal(Object.keys(prov.artifact_digests).length, 16, 'Exactly 16 artifact digests');

  for (const [relPath, expectedSha] of Object.entries(EXPECTED_ARTIFACTS)) {
    const recordedSha = prov.artifact_digests[relPath];
    assert.equal(recordedSha, expectedSha, `SHA-256 for ${relPath} in provenance.json`);

    // Verify against actual file on disk
    const fullPath = path.resolve(REPO_ROOT, relPath);
    assert.ok(fs.existsSync(fullPath), `Preceding artifact file must exist on disk: ${relPath}`);
    const actualData = fs.readFileSync(fullPath);
    const actualSha = crypto.createHash('sha256').update(actualData).digest('hex');
    assert.equal(recordedSha, actualSha, `Recorded SHA matches disk SHA for ${relPath}`);
  }
});

test('synthesis: integrated-defects.json contains all 48 defects across Lanes A-J', () => {
  assert.ok(fs.existsSync(DEFECTS_PATH), 'integrated-defects.json must exist');
  const defects = JSON.parse(fs.readFileSync(DEFECTS_PATH, 'utf8'));

  assert.ok(Array.isArray(defects), 'integrated-defects.json must be an array');
  assert.equal(defects.length, 48, 'Must contain exactly 48 cataloged defects across Lanes A-J');

  const laneCounts = {};
  const defectIds = new Set();
  const validSeverities = new Set(['blocks-use', 'misleading', 'degraded', 'cosmetic']);
  const validStatuses = new Set(['resolved', 'residual']);

  for (const d of defects) {
    assert.ok(d.defect_id && typeof d.defect_id === 'string', `defect_id must be non-empty string in ${JSON.stringify(d)}`);
    assert.ok(!defectIds.has(d.defect_id), `defect_id must be unique: duplicate ${d.defect_id}`);
    defectIds.add(d.defect_id);

    assert.ok(d.originating_lane && typeof d.originating_lane === 'string', `originating_lane required in ${d.defect_id}`);
    assert.match(d.originating_lane, /^Lane [A-J]$/, `originating_lane must be Lane A-J in ${d.defect_id}`);
    laneCounts[d.originating_lane] = (laneCounts[d.originating_lane] || 0) + 1;

    assert.ok(d.title && typeof d.title === 'string', `title required in ${d.defect_id}`);
    assert.ok(validSeverities.has(d.severity), `severity '${d.severity}' invalid in ${d.defect_id}`);
    assert.ok(validStatuses.has(d.status), `status '${d.status}' invalid in ${d.defect_id}`);
    assert.ok(d.remediation_reference === null || typeof d.remediation_reference === 'string', `remediation_reference invalid in ${d.defect_id}`);
    assert.ok(d.verification && typeof d.verification === 'string', `verification required in ${d.defect_id}`);
  }

  // Verify per-lane defect counts
  assert.equal(laneCounts['Lane A'], 2, 'Lane A: exactly 2 findings');
  assert.equal(laneCounts['Lane B'], 18, 'Lane B: exactly 18 defects');
  assert.equal(laneCounts['Lane C'], 5, 'Lane C: exactly 5 defects');
  assert.equal(laneCounts['Lane D'], 2, 'Lane D: exactly 2 defects');
  assert.equal(laneCounts['Lane E'], 3, 'Lane E: exactly 3 defects');
  assert.equal(laneCounts['Lane F'], 3, 'Lane F: exactly 3 defects');
  assert.equal(laneCounts['Lane G'], 3, 'Lane G: exactly 3 defects');
  assert.equal(laneCounts['Lane H'], 2, 'Lane H: exactly 2 findings');
  assert.equal(laneCounts['Lane I'], 4, 'Lane I: exactly 4 defects');
  assert.equal(laneCounts['Lane J'], 6, 'Lane J: exactly 6 defects');

  // Verify specific anchor IDs
  assert.ok(defectIds.has('A-UI-RAIL-CALENDAR'), 'A-UI-RAIL-CALENDAR present');
  assert.ok(defectIds.has('A-UI-RAIL-SETTINGS'), 'A-UI-RAIL-SETTINGS present');
  assert.ok(defectIds.has('DEFECT-OPTIONS-1'), 'DEFECT-OPTIONS-1 present');
  assert.ok(defectIds.has('DEFECT-OPTIONS-5'), 'DEFECT-OPTIONS-5 present');
  assert.ok(defectIds.has('DEFECT-STOCKS-1'), 'DEFECT-STOCKS-1 present');
  assert.ok(defectIds.has('DEFECT-STOCKS-2'), 'DEFECT-STOCKS-2 present');
  assert.ok(defectIds.has('DEFECT-PREBREAKOUT-1'), 'DEFECT-PREBREAKOUT-1 present');
  assert.ok(defectIds.has('DEFECT-PREBREAKOUT-3'), 'DEFECT-PREBREAKOUT-3 present');
  assert.ok(defectIds.has('DEFECT-BROKER-1'), 'DEFECT-BROKER-1 present');
  assert.ok(defectIds.has('DEFECT-BROKER-3'), 'DEFECT-BROKER-3 present');
  assert.ok(defectIds.has('DEFECT-MONITORING-1'), 'DEFECT-MONITORING-1 present');
  assert.ok(defectIds.has('DEFECT-MONITORING-3'), 'DEFECT-MONITORING-3 present');
  assert.ok(defectIds.has('DISP-1'), 'DISP-1 present');
  assert.ok(defectIds.has('NAV-1'), 'NAV-1 present');
  assert.ok(defectIds.has('DEFECT-PERSIST-1'), 'DEFECT-PERSIST-1 present');
  assert.ok(defectIds.has('DEFECT-PERSIST-4'), 'DEFECT-PERSIST-4 present');
  assert.ok(defectIds.has('J-001'), 'J-001 present');
  assert.ok(defectIds.has('J-006'), 'J-006 present');

  // Verify Lane B remediated items have resolved status and remediation references
  const resolvedLaneB = defects.filter(d => d.originating_lane === 'Lane B' && d.status === 'resolved');
  assert.ok(resolvedLaneB.length >= 7, 'At least 7 Lane B defects are resolved');
  const remediatedRefs = resolvedLaneB.map(d => d.remediation_reference).filter(Boolean);
  assert.ok(remediatedRefs.length >= 7, 'Remediated Lane B defects reference their PR/issue');
});

test('synthesis: coverage-matrix.json joins Lane A inventory with Lanes B-I domain ownership and Lane J dispositions', () => {
  assert.ok(fs.existsSync(COVERAGE_MATRIX_PATH), 'coverage-matrix.json must exist');
  const matrix = JSON.parse(fs.readFileSync(COVERAGE_MATRIX_PATH, 'utf8'));

  assert.ok(matrix.high_level_summary, 'high_level_summary must exist');
  const summary = matrix.high_level_summary;
  assert.equal(summary.total_routes, 45, '45 routes');
  assert.equal(summary.total_definitions, 283, '283 definitions');
  assert.equal(summary.total_requirements, 52308, '52,308 total requirement rows');

  assert.deepEqual(summary.presentation_dispositions, {
    'observed-verified': 4577,
    'observed-asserted': 33330,
    'observed-ambiguous': 14261,
    'not-run': 140
  }, 'presentation dispositions match Lane J counts exactly');

  assert.ok(Array.isArray(matrix.routes), 'routes must be an array');
  assert.equal(matrix.routes.length, 45, 'matrix has 45 route entries');

  for (const r of matrix.routes) {
    assert.ok(r.route_id, `route_id required in route`);
    assert.ok(r.route, `route required in route`);
    assert.ok(r.owners, `owners required in ${r.route_id}`);
    assert.ok(r.owners.numeric, `numeric owner required in ${r.route_id}`);
    assert.ok(r.owners.persistence, `persistence owner required in ${r.route_id}`);
    assert.ok(r.disposition_counts, `disposition_counts required in ${r.route_id}`);
  }

  assert.ok(Array.isArray(matrix.definitions), 'definitions must be an array');
  assert.equal(matrix.definitions.length, 283, 'matrix has 283 definition entries');

  for (const d of matrix.definitions) {
    assert.ok(d.definition_id, `definition_id required in definition`);
    assert.ok(d.component, `component required in definition`);
    assert.ok(d.owners, `owners required in ${d.definition_id}`);
    assert.ok(d.owners.numeric, `numeric owner required in ${d.definition_id}`);
    assert.ok(d.owners.persistence, `persistence owner required in ${d.definition_id}`);
  }

  assert.ok(matrix.domain_lanes, 'domain_lanes summary must exist');
  assert.equal(Object.keys(matrix.domain_lanes).length, 10, '10 domain lanes (A through J)');
});
