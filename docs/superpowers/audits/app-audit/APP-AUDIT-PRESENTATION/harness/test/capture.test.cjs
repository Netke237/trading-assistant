'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const REPO = path.resolve(__dirname, '../../../../../../..');
const PRESENTATION_DIR = path.resolve(__dirname, '../..');
const PROVENANCE_PATH = path.join(PRESENTATION_DIR, 'provenance.json');
const EVIDENCE_DIR = path.join(PRESENTATION_DIR, 'evidence');

const {
  BASELINE,
  NAVIGABLE_URLS,
  ALL_ROUTE_ENTRIES,
  STATE_FAMILIES,
  buildThemeEnvelope,
  resolveRouteAttribution,
  detectC1toC6,
  generateSyntheticRouteEvidence,
  captureUrlRecords,
  getEvidenceFilePath,
  executeCaptureSuite,
} = require('../capture.cjs');

test('capture: provenance.json conforms to schema, versions, and SHA hashes', () => {
  assert.ok(fs.existsSync(PROVENANCE_PATH), 'provenance.json must exist');
  const prov = JSON.parse(fs.readFileSync(PROVENANCE_PATH, 'utf8'));

  assert.ok(prov.source_sha, 'source_sha must be present');
  assert.ok(typeof prov.node_version === 'string' && prov.node_version.includes('v20'), 'node_version must record v20.x');
  assert.equal(prov.next_version, '15.5.23', 'next_version must be 15.5.23');
  assert.equal(prov.react_version, '19.2.5', 'react_version must be 19.2.5');
  assert.ok(typeof prov.playwright_version === 'string' && prov.playwright_version.startsWith('1.'), 'playwright_version must start with 1.');
  assert.equal(prov.chromium_version, '151.0.7922.34', 'chromium_version must be 151.0.7922.34');
  assert.equal(prov.timezone, 'Europe/Berlin', 'timezone must be Europe/Berlin');
  assert.ok(prov.fixed_clock_timestamp, 'fixed_clock_timestamp must be present');
  assert.ok(Array.isArray(prov.fixture_hashes) && prov.fixture_hashes.length > 0, 'fixture_hashes must be populated');
  assert.ok(Array.isArray(prov.harness_hashes) && prov.harness_hashes.length > 0, 'harness_hashes must be populated');

  // Verify SHA-256 format for all hashes
  for (const h of prov.fixture_hashes) {
    assert.match(h.sha256, /^[0-9a-f]{64}$/, `fixture ${h.name} must have valid sha256`);
    assert.ok(fs.existsSync(path.resolve(REPO, h.path)), `fixture file ${h.path} must exist`);
  }
  for (const h of prov.harness_hashes) {
    assert.match(h.sha256, /^[0-9a-f]{64}$/, `harness script ${h.name} must have valid sha256`);
    assert.ok(fs.existsSync(path.resolve(REPO, h.path)), `harness script ${h.path} must exist`);
  }
});

test('capture: 28 navigable URLs map completely to 45 route entries including parallel slots and layouts', () => {
  assert.equal(NAVIGABLE_URLS.length, 28, 'must define exactly 28 navigable URLs');
  assert.equal(ALL_ROUTE_ENTRIES.length, 45, 'must cover all 45 route entries from inventory');

  const coveredRoutes = new Set();

  for (const url of NAVIGABLE_URLS) {
    const attr = resolveRouteAttribution(url);
    assert.ok(attr.page, `URL ${url} must resolve a primary page route entry`);
    coveredRoutes.add(attr.page);

    assert.ok(Array.isArray(attr.layouts) && attr.layouts.length > 0, `URL ${url} must have enclosing layouts`);
    for (const layout of attr.layouts) {
      coveredRoutes.add(layout);
    }

    if (attr.contextRail) {
      coveredRoutes.add(attr.contextRail);
    }
    if (attr.fallbackContextRail) {
      coveredRoutes.add(attr.fallbackContextRail);
    }
  }

  // Also include standalone boundaries in covered routes
  const boundaries = [
    'frontend/app/(frame)/error.tsx',
    'frontend/app/(frame)/loading.tsx',
    'frontend/app/not-found.tsx',
  ];
  for (const b of boundaries) {
    coveredRoutes.add(b);
  }

  for (const route of ALL_ROUTE_ENTRIES) {
    assert.ok(
      coveredRoutes.has(route),
      `route entry ${route} must be attributed across navigable URLs or boundaries`
    );
  }
});

test('capture: Zustand theme envelope correctly formats persist envelope', () => {
  const darkEnvelope = buildThemeEnvelope('dark', 'Comfortable');
  assert.equal(
    darkEnvelope,
    JSON.stringify({ state: { theme: 'dark', density: 'Comfortable' }, version: 1 })
  );

  const lightEnvelope = buildThemeEnvelope('light', 'Comfortable');
  assert.equal(
    lightEnvelope,
    JSON.stringify({ state: { theme: 'light', density: 'Comfortable' }, version: 1 })
  );

  const compactEnvelope = buildThemeEnvelope('dark', 'Compact');
  assert.equal(
    compactEnvelope,
    JSON.stringify({ state: { theme: 'dark', density: 'Compact' }, version: 1 })
  );

  // Parse check to verify layout.tsx pre-hydration script compatibility
  const parsed = JSON.parse(darkEnvelope);
  assert.equal(parsed.state.theme, 'dark');
  assert.equal(parsed.state.density, 'Comfortable');
  assert.equal(parsed.version, 1);
});

test('capture: pure synthetic route/census execution generates valid C1-C8 evidence records', () => {
  const record = generateSyntheticRouteEvidence('frontend/app/(frame)/dashboard/page.tsx', 'normal', {
    theme: 'dark',
    density: 'Comfortable',
    viewport: { width: 1280, height: 800 },
  });

  assert.equal(record.source_sha, BASELINE);
  assert.equal(record.route_entry, 'frontend/app/(frame)/dashboard/page.tsx');
  assert.equal(record.state_key, 'normal');
  assert.ok(record.census, 'record must include React Fiber census');
  assert.ok(Array.isArray(record.census.mounted_names), 'census must list mounted_names');
  assert.ok(record.census.mounted_names.includes('DashboardPage'), 'DashboardPage must be mounted');
  assert.ok(record.c_evidence, 'record must include C1-C8 evidence');
  assert.ok(record.c_evidence.c1, 'must include C1 visible text inspection');
  assert.ok(record.c_evidence.c2, 'must include C2 accessibility / labels inspection');
  assert.ok(record.c_evidence.c3, 'must include C3 zero/null/false inspection');
  assert.ok(record.c_evidence.c4, 'must include C4 visual screenshot/rendering check');
  assert.ok(record.c_evidence.c5, 'must include C5 layout overflow inspection');
  assert.ok(record.c_evidence.c6, 'must include C6 WCAG contrast / axe check');
  assert.ok(record.c_evidence.c7, 'must include C7 React Fiber current census');
  assert.ok(record.c_evidence.c8, 'must include C8 storage and console logs');
  assert.equal(record.storage.seeds['bamendjou:theme'], buildThemeEnvelope('dark', 'Comfortable'));
});

test('capture: parallel slot and layout attribution emits distinct records for URL', () => {
  const records = captureUrlRecords('/dashboard', 'normal', { synthetic: true });

  assert.ok(records.length >= 4, 'should emit records for page, slot, and layouts');

  const pageRecord = records.find(r => r.route_entry === 'frontend/app/(frame)/dashboard/page.tsx');
  const slotRecord = records.find(r => r.route_entry === 'frontend/app/(frame)/@contextRail/dashboard/page.tsx');
  const frameLayoutRecord = records.find(r => r.route_entry === 'frontend/app/(frame)/layout.tsx');
  const rootLayoutRecord = records.find(r => r.route_entry === 'frontend/app/layout.tsx');

  assert.ok(pageRecord, 'must include distinct record for dashboard page');
  assert.ok(slotRecord, 'must include distinct record for dashboard @contextRail slot');
  assert.ok(frameLayoutRecord, 'must include distinct record for Frame layout');
  assert.ok(rootLayoutRecord, 'must include distinct record for Root layout');

  assert.equal(pageRecord.state_key, 'normal');
  assert.equal(slotRecord.state_key, 'normal');
  assert.equal(frameLayoutRecord.state_key, 'normal');
  assert.equal(rootLayoutRecord.state_key, 'normal');
});

test('capture: C1-C6 detectors identify raw interpolation, null/zero mismatch, and overflow', () => {
  const sampleWithDefects = {
    visible_text: ['Total: NaN', 'Status: undefined', 'Items: [object Object]', 'Count: null'],
    dom_references: [{ tag: 'span', text: 'raw null' }],
    overflow_elements: [{ selector: '.table-container', scrollWidth: 1400, clientWidth: 1200 }],
    axe_violations: [{ id: 'color-contrast', impact: 'serious' }],
  };

  const detected = detectC1toC6(sampleWithDefects);
  assert.ok(detected.c1_raw_interpolations.length >= 4, 'should detect NaN, undefined, null, [object Object]');
  assert.ok(detected.c5_overflows.length > 0, 'should detect layout overflow');
  assert.ok(detected.c6_violations.length > 0, 'should detect axe contrast violation');
});

test('capture: evidence records exist on disk for all 45 route entries across 9 states', () => {
  for (const route of ALL_ROUTE_ENTRIES) {
    for (const state of STATE_FAMILIES) {
      const filePath = getEvidenceFilePath(route, state, EVIDENCE_DIR);
      assert.ok(
        fs.existsSync(filePath),
        `evidence file must exist on disk for ${route} in state ${state} at ${filePath}`
      );

      const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      assert.equal(parsed.route_entry, route, `parsed.route_entry must match ${route}`);
      assert.equal(parsed.state_key, state, `parsed.state_key must match ${state}`);
      assert.equal(parsed.source_sha, BASELINE, `parsed.source_sha must match baseline`);
      assert.ok(parsed.census, 'evidence must contain React Fiber census');
      assert.ok(parsed.c_evidence, 'evidence must contain C1-C8 evidence');
    }
  }
});
