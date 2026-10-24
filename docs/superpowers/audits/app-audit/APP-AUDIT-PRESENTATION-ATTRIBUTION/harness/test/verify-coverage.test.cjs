'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');

const {
  expandInventory,
  validateReconciliation,
  reconcileSamples,
  generateToolingReport,
  VALID_DISPOSITIONS
} = require('../verify-coverage.cjs');

const { loadFrozen, sha, BASELINE } = require('../map-common.cjs');

// Minimal synthetic inventory for deterministic, fast unit and mutation tests
function createMinimalFixture() {
  const inventory = {
    schema_version: 1,
    phase: 'APP-AUDIT-INVENTORY',
    source_baseline: BASELINE,
    counts: {
      source_route_entry_files: 2,
      component_definitions: 3,
      component_route_requirement_instances: 3,
      component_state_requirement_ids: 27,
      native_surface_candidates: 4,
      native_route_requirement_instances_normalized: 4,
      native_state_requirement_ids_normalized: 36
    },
    state_matrix_templates: {
      'conservative-nine-state-v1': [
        { key: 'normal' },
        { key: 'expanded-nested' },
        { key: 'empty' },
        { key: 'loading' },
        { key: 'failed-cancelled' },
        { key: 'legacy-unsupported' },
        { key: 'zero-false-null-absent' },
        { key: 'stale-async' },
        { key: 'reload-restart' }
      ]
    },
    route_entries: [
      {
        id: 'route:frontend/app/(frame)/dashboard/page.tsx',
        source: 'frontend/app/(frame)/dashboard/page.tsx',
        route: '/dashboard',
        kind: 'page',
        classification: 'url-page',
        source_sha256: 'mock-dashboard-sha'
      },
      {
        id: 'route:frontend/app/(frame)/@contextRail/dashboard/default.tsx',
        source: 'frontend/app/(frame)/@contextRail/dashboard/default.tsx',
        route: '/dashboard',
        kind: 'default',
        classification: 'parallel-slot-fallback',
        parallel_slot: 'contextRail',
        source_sha256: 'mock-rail-sha'
      }
    ],
    definitions: [
      {
        id: 'surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage',
        source: 'frontend/app/(frame)/dashboard/page.tsx',
        component: 'DashboardPage',
        state_matrix_template: 'conservative-nine-state-v1',
        native_surfaces: [
          {
            id: 'surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::native:div:1',
            tag: 'div',
            parent_definition_id: 'surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage'
          },
          {
            id: 'surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::native:span:1',
            tag: 'span',
            parent_definition_id: 'surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage'
          }
        ]
      },
      {
        id: 'surface:frontend/components/Widget/index.tsx#Widget',
        source: 'frontend/components/Widget/index.tsx',
        component: 'Widget',
        state_matrix_template: 'conservative-nine-state-v1',
        native_surfaces: [
          {
            id: 'surface:frontend/components/Widget/index.tsx#Widget::native:button:1',
            tag: 'button',
            parent_definition_id: 'surface:frontend/components/Widget/index.tsx#Widget'
          }
        ]
      },
      {
        id: 'surface:frontend/components/ServerBox/index.tsx#ServerBox',
        source: 'frontend/components/ServerBox/index.tsx',
        component: 'ServerBox',
        state_matrix_template: 'conservative-nine-state-v1',
        native_surfaces: [
          {
            id: 'surface:frontend/components/ServerBox/index.tsx#ServerBox::native:aside:1',
            tag: 'aside',
            parent_definition_id: 'surface:frontend/components/ServerBox/index.tsx#ServerBox'
          }
        ]
      }
    ],
    route_instances: [
      {
        id: 'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage',
        route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
        definition_id: 'surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage',
        state_ids: [
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:normal',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:expanded-nested',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:empty',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:loading',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:failed-cancelled',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:legacy-unsupported',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:zero-false-null-absent',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:stale-async',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:reload-restart'
        ]
      },
      {
        id: 'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/components/Widget/index.tsx#Widget',
        route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
        definition_id: 'surface:frontend/components/Widget/index.tsx#Widget',
        state_ids: [
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/components/Widget/index.tsx#Widget::state:normal',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/components/Widget/index.tsx#Widget::state:expanded-nested',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/components/Widget/index.tsx#Widget::state:empty',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/components/Widget/index.tsx#Widget::state:loading',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/components/Widget/index.tsx#Widget::state:failed-cancelled',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/components/Widget/index.tsx#Widget::state:legacy-unsupported',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/components/Widget/index.tsx#Widget::state:zero-false-null-absent',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/components/Widget/index.tsx#Widget::state:stale-async',
          'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/components/Widget/index.tsx#Widget::state:reload-restart'
        ]
      },
      {
        id: 'instance:frontend/app/(frame)/@contextRail/dashboard/default.tsx::surface:frontend/components/ServerBox/index.tsx#ServerBox',
        route_entry_id: 'route:frontend/app/(frame)/@contextRail/dashboard/default.tsx',
        definition_id: 'surface:frontend/components/ServerBox/index.tsx#ServerBox',
        state_ids: [
          'instance:frontend/app/(frame)/@contextRail/dashboard/default.tsx::surface:frontend/components/ServerBox/index.tsx#ServerBox::state:normal',
          'instance:frontend/app/(frame)/@contextRail/dashboard/default.tsx::surface:frontend/components/ServerBox/index.tsx#ServerBox::state:expanded-nested',
          'instance:frontend/app/(frame)/@contextRail/dashboard/default.tsx::surface:frontend/components/ServerBox/index.tsx#ServerBox::state:empty',
          'instance:frontend/app/(frame)/@contextRail/dashboard/default.tsx::surface:frontend/components/ServerBox/index.tsx#ServerBox::state:loading',
          'instance:frontend/app/(frame)/@contextRail/dashboard/default.tsx::surface:frontend/components/ServerBox/index.tsx#ServerBox::state:failed-cancelled',
          'instance:frontend/app/(frame)/@contextRail/dashboard/default.tsx::surface:frontend/components/ServerBox/index.tsx#ServerBox::state:legacy-unsupported',
          'instance:frontend/app/(frame)/@contextRail/dashboard/default.tsx::surface:frontend/components/ServerBox/index.tsx#ServerBox::state:zero-false-null-absent',
          'instance:frontend/app/(frame)/@contextRail/dashboard/default.tsx::surface:frontend/components/ServerBox/index.tsx#ServerBox::state:stale-async',
          'instance:frontend/app/(frame)/@contextRail/dashboard/default.tsx::surface:frontend/components/ServerBox/index.tsx#ServerBox::state:reload-restart'
        ]
      }
    ]
  };

  const supplemental = {
    schema_version: 1,
    source_baseline: BASELINE,
    capability_state_contracts: [
      {
        capability_id: 'capability:frontend/components/Widget/index.tsx#SpecialCap',
        states: [
          { id: 'capability:frontend/components/Widget/index.tsx#SpecialCap/state:normal', key: 'normal' },
          { id: 'capability:frontend/components/Widget/index.tsx#SpecialCap/state:custom-action', key: 'custom-action' }
        ]
      }
    ],
    route_instances: [
      {
        id: 'route:frontend/app/(frame)/dashboard/page.tsx::capability:frontend/components/Widget/index.tsx#SpecialCap',
        route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
        capability_id: 'capability:frontend/components/Widget/index.tsx#SpecialCap',
        state_requirement_ids: [
          'route:frontend/app/(frame)/dashboard/page.tsx::capability:frontend/components/Widget/index.tsx#SpecialCap/state:normal',
          'route:frontend/app/(frame)/dashboard/page.tsx::capability:frontend/components/Widget/index.tsx#SpecialCap/state:custom-action'
        ]
      }
    ],
    route_state_requirements: [
      {
        id: 'route:frontend/app/(frame)/dashboard/page.tsx::capability:frontend/components/Widget/index.tsx#SpecialCap/state:normal',
        route_instance_id: 'route:frontend/app/(frame)/dashboard/page.tsx::capability:frontend/components/Widget/index.tsx#SpecialCap',
        route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
        capability_state_id: 'capability:frontend/components/Widget/index.tsx#SpecialCap/state:normal'
      },
      {
        id: 'route:frontend/app/(frame)/dashboard/page.tsx::capability:frontend/components/Widget/index.tsx#SpecialCap/state:custom-action',
        route_instance_id: 'route:frontend/app/(frame)/dashboard/page.tsx::capability:frontend/components/Widget/index.tsx#SpecialCap',
        route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
        capability_state_id: 'capability:frontend/components/Widget/index.tsx#SpecialCap/state:custom-action'
      }
    ]
  };

  const sourceMap = {
    definitions: [
      {
        id: 'surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage',
        component: 'DashboardPage',
        source: 'frontend/app/(frame)/dashboard/page.tsx',
        environment_candidates: ['client'],
        module_membership: { explicit_client: true },
        host_marker: { eligible: false },
        natives: [
          {
            id: 'surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::native:div:1',
            authorship: 'lexical-definition',
            signature_hash: 'sig-div-1',
            signature: { tag: 'div', attributes: [], text: 'dashboard content' }
          },
          {
            id: 'surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::native:span:1',
            authorship: 'lexical-definition',
            signature_hash: 'sig-span-1',
            signature: { tag: 'span', attributes: [], text: 'label' }
          }
        ]
      },
      {
        id: 'surface:frontend/components/Widget/index.tsx#Widget',
        component: 'Widget',
        source: 'frontend/components/Widget/index.tsx',
        environment_candidates: ['client'],
        module_membership: { explicit_client: true },
        host_marker: { eligible: false },
        natives: [
          {
            id: 'surface:frontend/components/Widget/index.tsx#Widget::native:button:1',
            authorship: 'children-slot', // children-slot native candidate
            signature_hash: 'sig-btn-1',
            signature: { tag: 'button', attributes: [], text: 'Click me' }
          }
        ]
      },
      {
        id: 'surface:frontend/components/ServerBox/index.tsx#ServerBox',
        component: 'ServerBox',
        source: 'frontend/components/ServerBox/index.tsx',
        environment_candidates: ['server'],
        module_membership: { explicit_client: false },
        host_marker: { eligible: false },
        natives: [
          {
            id: 'surface:frontend/components/ServerBox/index.tsx#ServerBox::native:aside:1',
            authorship: 'lexical-definition',
            signature_hash: 'sig-aside-1',
            signature: { tag: 'aside', attributes: [], text: 'sidebar' }
          }
        ]
      }
    ],
    signature_collisions: []
  };

  const sampleJson = {
    purpose: 'tooling-self-test',
    url: 'http://127.0.0.1:61700/dashboard',
    route_entry: 'frontend/app/(frame)/dashboard/page.tsx',
    source_sha: BASELINE,
    census: {
      status: 'ok',
      component_counts: {
        DashboardPage: 1,
        Widget: 2 // duplicate in census!
      },
      duplicate_names: ['Widget'],
      mounted_names: ['DashboardPage', 'Widget'],
      host_nodes: [
        {
          id: 'node:1',
          tag: 'div',
          is_connected: true,
          component_name: 'DashboardPage',
          text: 'dashboard content'
        },
        {
          id: 'node:2',
          tag: 'button',
          is_connected: true,
          component_name: 'Widget',
          text: 'Click me'
        },
        {
          id: 'node:3',
          tag: 'span',
          is_connected: true,
          component_name: 'DashboardPage',
          text: 'label'
        }
      ]
    }
  };

  return { inventory, supplemental, sourceMap, sampleJson };
}

// Helper to build a clean baseline reconciliation covering all expanded IDs
function buildCleanReconciliation(expansion, evidenceRoot, sampleRelPath, sampleBytes, inventoryBytes) {
  const artifactSha = crypto.createHash('sha256').update(sampleBytes).digest('hex');
  const inventorySha = crypto.createHash('sha256').update(inventoryBytes).digest('hex');

  const rows = [];
  for (const item of expansion.allRows) {
    if (item.id === 'surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage') {
      rows.push({
        id: item.id,
        disposition: 'observed-verified',
        evidence: {
          artifact: sampleRelPath,
          artifact_sha256: artifactSha,
          source_sha: BASELINE,
          inventory_sha256: inventorySha,
          route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
          explanation: 'Mounted client page definition uniquely present in census',
          runtime_adapter: 'module-export'
        }
      });
    } else if (item.id === 'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage') {
      rows.push({
        id: item.id,
        disposition: 'observed-verified',
        evidence: {
          artifact: sampleRelPath,
          artifact_sha256: artifactSha,
          source_sha: BASELINE,
          inventory_sha256: inventorySha,
          route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
          explanation: 'Component instance mounted in census',
          runtime_adapter: 'module-export'
        }
      });
    } else if (item.id === 'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:normal') {
      rows.push({
        id: item.id,
        disposition: 'observed-verified',
        evidence: {
          artifact: sampleRelPath,
          artifact_sha256: artifactSha,
          source_sha: BASELINE,
          inventory_sha256: inventorySha,
          route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
          state_key: 'normal',
          explanation: 'Normal state observed on dashboard'
        }
      });
    } else if (item.id === 'instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::native:div:1') {
      rows.push({
        id: item.id,
        disposition: 'observed-verified',
        evidence: {
          artifact: sampleRelPath,
          artifact_sha256: artifactSha,
          source_sha: BASELINE,
          inventory_sha256: inventorySha,
          route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
          node_id: 'node:1',
          explanation: 'Visible connected div native matching unique authored signature'
        }
      });
    } else if (item.id === 'surface:frontend/components/ServerBox/index.tsx#ServerBox') {
      // Server definition without proven marker downgrades to asserted
      rows.push({
        id: item.id,
        disposition: 'observed-asserted',
        evidence: {
          artifact: sampleRelPath,
          artifact_sha256: artifactSha,
          source_sha: BASELINE,
          inventory_sha256: inventorySha,
          route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
          explanation: 'Server component present via layout without client fiber census entry'
        }
      });
    } else if (item.id === 'surface:frontend/components/Widget/index.tsx#Widget') {
      // Widget is duplicate in census
      rows.push({
        id: item.id,
        disposition: 'observed-ambiguous',
        evidence: {
          artifact: sampleRelPath,
          artifact_sha256: artifactSha,
          source_sha: BASELINE,
          inventory_sha256: inventorySha,
          route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
          explanation: 'Multiple instances in census make bare component identity ambiguous'
        }
      });
    } else {
      // All unrun rows
      rows.push({
        id: item.id,
        disposition: 'not-run',
        reason: 'unexecuted-in-tooling-self-test'
      });
    }
  }

  return {
    schema_version: 1,
    purpose: 'tooling-self-test',
    source_sha: BASELINE,
    inventory_sha256: inventorySha,
    rows
  };
}

test('unit: expandInventory correctly expands IDs and validates joins on minimal inventory', () => {
  const { inventory, supplemental } = createMinimalFixture();
  const expansion = expandInventory(inventory, supplemental);

  assert.equal(expansion.route_entries.length, 2);
  assert.equal(expansion.definitions.length, 3);
  assert.equal(expansion.component_instances.length, 3);
  assert.equal(expansion.component_states.length, 27);
  assert.equal(expansion.native_instances.length, 4);
  assert.equal(expansion.native_states.length, 36);
  assert.equal(expansion.supplemental_capabilities.length, 1);
  assert.equal(expansion.supplemental_capability_states.length, 2);
  assert.equal(expansion.supplemental_route_instances.length, 1);
  assert.equal(expansion.supplemental_route_state_requirements.length, 2);

  // Total expanded requirement rows = 2 + 3 + 3 + 27 + 4 + 36 + 1 + 2 + 1 + 2 = 81
  assert.equal(expansion.allRows.length, 81);

  // Check ID formats
  assert.ok(expansion.requirementsById.has('route:frontend/app/(frame)/dashboard/page.tsx'));
  assert.ok(expansion.requirementsById.has('surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage'));
  assert.ok(expansion.requirementsById.has('instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage'));
  assert.ok(expansion.requirementsById.has('instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::state:normal'));
  assert.ok(expansion.requirementsById.has('instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::native:div:1'));
  assert.ok(expansion.requirementsById.has('instance:frontend/app/(frame)/dashboard/page.tsx::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::surface:frontend/app/(frame)/dashboard/page.tsx#DashboardPage::native:div:1::state:normal'));
  assert.ok(expansion.requirementsById.has('capability:frontend/components/Widget/index.tsx#SpecialCap'));
  assert.ok(expansion.requirementsById.has('capability:frontend/components/Widget/index.tsx#SpecialCap/state:normal'));
  assert.ok(expansion.requirementsById.has('route:frontend/app/(frame)/dashboard/page.tsx::capability:frontend/components/Widget/index.tsx#SpecialCap'));
  assert.ok(expansion.requirementsById.has('route:frontend/app/(frame)/dashboard/page.tsx::capability:frontend/components/Widget/index.tsx#SpecialCap/state:normal'));
});

test('unit: expandInventory rejects invalid joins, duplicate IDs and inconsistent declared counts', () => {
  const { inventory, supplemental } = createMinimalFixture();

  // Invalid join: route instance pointing to nonexistent route entry
  const badJoinInv = JSON.parse(JSON.stringify(inventory));
  badJoinInv.route_instances[0].route_entry_id = 'route:nonexistent.tsx';
  assert.throws(() => expandInventory(badJoinInv, supplemental), /invalid-join/i);

  // Duplicate definition ID
  const dupDefInv = JSON.parse(JSON.stringify(inventory));
  dupDefInv.definitions.push({ ...dupDefInv.definitions[0] });
  assert.throws(() => expandInventory(dupDefInv, supplemental), /duplicate/i);

  // Inconsistent declared counts in inventory.counts
  const badCountsInv = JSON.parse(JSON.stringify(inventory));
  badCountsInv.counts.component_definitions = 999;
  assert.throws(() => expandInventory(badCountsInv, supplemental), /inconsistent.*count/i);
});

test('unit: an all-not-run reconciliation passes validation and reports zero verified UI results', (t) => {
  const { inventory, supplemental, sourceMap } = createMinimalFixture();
  const expansion = expandInventory(inventory, supplemental);

  const reconciliation = {
    schema_version: 1,
    purpose: 'tooling-self-test',
    source_sha: BASELINE,
    inventory_sha256: 'mock-inv-sha',
    rows: expansion.allRows.map(r => ({
      id: r.id,
      disposition: 'not-run',
      reason: 'unexecuted-tooling-self-test'
    }))
  };

  const result = validateReconciliation({
    inventory,
    supplemental,
    reconciliation,
    sourceMap,
    evidenceRoot: __dirname,
    expectedSourceSha: BASELINE,
    expectedInventorySha: 'mock-inv-sha'
  });

  assert.equal(result.valid, true);
  assert.equal(result.counts_by_disposition['observed-verified'], 0);
  assert.equal(result.counts_by_disposition['observed-asserted'], 0);
  assert.equal(result.counts_by_disposition['observed-ambiguous'], 0);
  assert.equal(result.counts_by_disposition['not-run'], 81);
  assert.equal(result.coverage_claim, 'tooling-samples-only; zero-whole-app-coverage-claim');
});

test('unit: valid reconciliation with verified, asserted and ambiguous rows succeeds', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-test-'));
  try {
    const samplePath = path.join(tmpDir, 'dashboard.json');
    const sampleBytes = JSON.stringify(sampleJson, null, 2);
    fs.writeFileSync(samplePath, sampleBytes);

    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    const result = validateReconciliation({
      inventory,
      supplemental,
      reconciliation: recon,
      sourceMap,
      evidenceRoot: tmpDir,
      expectedSourceSha: BASELINE,
      expectedInventorySha: crypto.createHash('sha256').update(invBytes).digest('hex')
    });

    assert.equal(result.valid, true);
    assert.equal(result.counts_by_disposition['observed-verified'], 4);
    assert.equal(result.counts_by_disposition['observed-asserted'], 1);
    assert.equal(result.counts_by_disposition['observed-ambiguous'], 1);
    assert.equal(result.counts_by_disposition['not-run'], 75);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

// 13 Required Mutation Tests
test('mutation 1: remove ID must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m1-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Remove an ID
    recon.rows.shift();

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /missing.*row|missing.*id/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 2: duplicate ID must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m2-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Duplicate an ID
    recon.rows.push({ ...recon.rows[0] });

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /duplicate/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 3: add unknown ID must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m3-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Add unknown ID
    recon.rows.push({
      id: 'instance:frontend/app/unknown.tsx::surface:unknown',
      disposition: 'not-run',
      reason: 'bogus'
    });

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /unknown/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 4: forge route must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m4-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Row cites evidence claiming route_entry_id for settings on a dashboard row
    const targetRow = recon.rows.find(r => r.id.startsWith('instance:frontend/app/(frame)/dashboard/page.tsx'));
    targetRow.evidence.route_entry_id = 'route:frontend/app/(frame)/settings/page.tsx';

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /route.*mismatch|route/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 5: forge state must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m5-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Component state row is for normal, but evidence specifies state_key: 'loading'
    const stateRow = recon.rows.find(r => r.id.endsWith('::state:normal'));
    stateRow.evidence.state_key = 'loading';

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /state.*mismatch|state/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 6: forge hash must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m6-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Forge artifact hash
    const targetRow = recon.rows.find(r => r.evidence?.artifact_sha256);
    targetRow.evidence.artifact_sha256 = '0000000000000000000000000000000000000000000000000000000000000000';

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /hash.*mismatch|hash/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 7: forge source must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m7-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Forge source SHA
    const targetRow = recon.rows.find(r => r.evidence?.source_sha);
    targetRow.evidence.source_sha = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef';

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /source.*mismatch|source/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 8: reuse a node for two natives must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m8-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Two native rows claim the same node_id 'node:1'
    const nativeRow1 = recon.rows.find(r => r.id.includes('::native:div:1'));
    const nativeRow2 = recon.rows.find(r => r.id.includes('::native:span:1'));
    nativeRow2.disposition = 'observed-verified';
    nativeRow2.evidence = {
      ...nativeRow1.evidence,
      node_id: 'node:1' // reuse node:1!
    };

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /node.*reused|reuse/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 9: claim a colliding/children-slot native verified must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m9-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Button native is marked children-slot in sourceMap, but claims observed-verified
    const buttonRow = recon.rows.find(r => r.id.includes('::native:button:1'));
    buttonRow.disposition = 'observed-verified';
    buttonRow.evidence = {
      artifact: 'dashboard.json',
      artifact_sha256: crypto.createHash('sha256').update(sampleBytes).digest('hex'),
      source_sha: BASELINE,
      route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
      node_id: 'node:2',
      explanation: 'claims verified despite children-slot'
    };

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /children-slot|unresolved.*slot/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 10: forge server absence must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m10-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Server definition without proven marker claims absence/not-run without justification
    // or claims verified without proven marker
    const serverRow = recon.rows.find(r => r.id === 'surface:frontend/components/ServerBox/index.tsx#ServerBox');
    serverRow.disposition = 'observed-verified';
    serverRow.evidence = {
      artifact: 'dashboard.json',
      artifact_sha256: crypto.createHash('sha256').update(sampleBytes).digest('hex'),
      source_sha: BASELINE,
      route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
      explanation: 'Unproven server component claims verified'
    };

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /server.*adapter|downgrade.*asserted|unproven.*server/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 11: assert unsupported verified state must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m11-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Non-normal state (e.g. loading) marked observed-verified
    const loadingRow = recon.rows.find(r => r.id.endsWith('::state:loading'));
    loadingRow.disposition = 'observed-verified';
    loadingRow.evidence = {
      artifact: 'dashboard.json',
      artifact_sha256: crypto.createHash('sha256').update(sampleBytes).digest('hex'),
      source_sha: BASELINE,
      route_entry_id: 'route:frontend/app/(frame)/dashboard/page.tsx',
      state_key: 'loading',
      explanation: 'claims loading verified'
    };

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /unsupported-state-predicate/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 12: cite another scenario/slot must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m12-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);
    const recon = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);

    // MUTATION: Parallel slot row cites standard page sample without slot evidence
    const slotRow = recon.rows.find(r => r.id.includes('@contextRail'));
    slotRow.disposition = 'observed-verified';
    slotRow.evidence = {
      artifact: 'dashboard.json', // URL page, not parallel slot!
      artifact_sha256: crypto.createHash('sha256').update(sampleBytes).digest('hex'),
      source_sha: BASELINE,
      route_entry_id: 'route:frontend/app/(frame)/@contextRail/dashboard/default.tsx',
      explanation: 'cites wrong slot entry'
    };

    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: recon, sourceMap, evidenceRoot: tmpDir }),
      /slot.*evidence|slot|entry.*mismatch|route-mismatch/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('mutation 13: corrupt artifact paths must fail', () => {
  const { inventory, supplemental, sourceMap, sampleJson } = createMinimalFixture();
  const tmpDir = fs.mkdtempSync(path.join(__dirname, 'tmp-m13-'));
  try {
    const sampleBytes = JSON.stringify(sampleJson);
    fs.writeFileSync(path.join(tmpDir, 'dashboard.json'), sampleBytes);
    const invBytes = JSON.stringify(inventory);
    const expansion = expandInventory(inventory, supplemental);

    // Case A: Traversal path
    const reconA = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);
    const targetA = reconA.rows.find(r => r.evidence);
    targetA.evidence.artifact = '../escaped.json';
    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: reconA, sourceMap, evidenceRoot: tmpDir }),
      /traversal|path/i
    );

    // Case B: Absolute path
    const reconB = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);
    const targetB = reconB.rows.find(r => r.evidence);
    targetB.evidence.artifact = path.resolve(tmpDir, 'dashboard.json');
    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: reconB, sourceMap, evidenceRoot: tmpDir }),
      /absolute|path/i
    );

    // Case C: Nonexistent file
    const reconC = buildCleanReconciliation(expansion, tmpDir, 'dashboard.json', sampleBytes, invBytes);
    const targetC = reconC.rows.find(r => r.evidence);
    targetC.evidence.artifact = 'nonexistent.json';
    assert.throws(
      () => validateReconciliation({ inventory, supplemental, reconciliation: reconC, sourceMap, evidenceRoot: tmpDir }),
      /not found|exist/i
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('integration: real frozen inputs expand cleanly and exactly match declared inventory counts', () => {
  const input = loadFrozen();
  const expansion = expandInventory(input.inventory, input.supplemental);

  assert.equal(expansion.route_entries.length, input.inventory.counts.source_route_entry_files);
  assert.equal(expansion.definitions.length, input.inventory.counts.component_definitions);
  assert.equal(expansion.component_instances.length, input.inventory.counts.component_route_requirement_instances);
  assert.equal(expansion.component_states.length, input.inventory.counts.component_state_requirement_ids);
  assert.equal(expansion.native_instances.length, input.inventory.counts.native_route_requirement_instances_normalized);
  assert.equal(expansion.native_states.length, input.inventory.counts.native_state_requirement_ids_normalized);

  // Supplemental counts
  assert.equal(expansion.supplemental_capabilities.length, input.supplemental.capability_state_contracts.length);
  assert.equal(expansion.supplemental_route_instances.length, input.supplemental.route_instances.length);
  assert.equal(expansion.supplemental_route_state_requirements.length, input.supplemental.route_state_requirements.length);
});
