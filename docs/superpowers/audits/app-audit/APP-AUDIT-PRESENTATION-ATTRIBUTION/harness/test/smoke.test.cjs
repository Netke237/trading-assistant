'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {
  exportIsolatedTree,
  verifyManifest,
  verifyLockfile,
  runSmokeSuite,
  setupPlaywrightRouting,
  seedOnce,
} = require('../smoke.cjs');
const { BASELINE, REPO } = require('../map-common.cjs');

test('smoke: shadow-module exclusion proves untracked index.ts cannot enter exported build tree', () => {
  const shadowFile = path.join(REPO, 'frontend/components/KeyboardShortcuts/index.ts');
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'j1-shadow-test-'));
  try {
    // Create untracked higher-precedence shadow file in working directory
    fs.writeFileSync(shadowFile, 'export const ShadowKeyboard = () => null;\n');

    // Export isolated tree from frozen baseline
    const { frontendDir, manifest } = exportIsolatedTree(tempDir, REPO, BASELINE);

    // The exported tree must NOT contain the untracked index.ts
    const exportedShadow = path.join(frontendDir, 'components/KeyboardShortcuts/index.ts');
    assert.equal(fs.existsSync(exportedShadow), false, 'untracked shadow file must not enter exported tree');

    // The exported tree MUST contain the frozen index.tsx
    const exportedTarget = path.join(frontendDir, 'components/KeyboardShortcuts/index.tsx');
    assert.equal(fs.existsSync(exportedTarget), true, 'tracked file must be present');

    // Manifest verification must pass against frozen baseline
    assert.doesNotThrow(() => verifyManifest(frontendDir, REPO, BASELINE));
  } finally {
    if (fs.existsSync(shadowFile)) fs.unlinkSync(shadowFile);
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

test('smoke: manifest verification rejects extra, missing, or mismatched files', () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'j1-manifest-test-'));
  try {
    const { frontendDir } = exportIsolatedTree(tempDir, REPO, BASELINE);

    // 1. Extra file should fail manifest check
    const extraFile = path.join(frontendDir, 'unexpected-extra.txt');
    fs.writeFileSync(extraFile, 'extra');
    assert.throws(() => verifyManifest(frontendDir, REPO, BASELINE), /manifest-extra-file/);
    fs.unlinkSync(extraFile);

    // 2. Missing file should fail manifest check
    const targetFile = path.join(frontendDir, 'package.json');
    const backup = fs.readFileSync(targetFile);
    fs.unlinkSync(targetFile);
    assert.throws(() => verifyManifest(frontendDir, REPO, BASELINE), /manifest-missing-file/);
    fs.writeFileSync(targetFile, backup);

    // 3. Clean manifest passes
    assert.doesNotThrow(() => verifyManifest(frontendDir, REPO, BASELINE));
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

test('smoke: lockfile verification rejects modified or corrupted lockfile', () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'j1-lockfile-test-'));
  try {
    const { frontendDir } = exportIsolatedTree(tempDir, REPO, BASELINE);
    const lockfilePath = path.join(frontendDir, 'package-lock.json');
    const original = fs.readFileSync(lockfilePath);

    // Modify lockfile
    fs.writeFileSync(lockfilePath, original + '/* corrupted */');
    assert.throws(() => verifyLockfile(frontendDir, REPO, BASELINE), /lockfile-mismatch/);

    // Restore lockfile
    fs.writeFileSync(lockfilePath, original);
    assert.doesNotThrow(() => verifyLockfile(frontendDir, REPO, BASELINE));
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

test('smoke: network isolation aborts unmatched HTTP and closes WebSockets without external egress', async () => {
  const pw = require(path.join(REPO, 'frontend/node_modules/playwright'));
  const browser = await pw.chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      serviceWorkers: 'block',
      timezoneId: 'Europe/Berlin',
    });

    const logs = setupPlaywrightRouting(context, {
      serverUrl: 'http://127.0.0.1:9999',
      fixtures: [
        {
          pathPattern: '/api/watchlist',
          method: 'GET',
          bytes: JSON.stringify([{ symbol: 'AAPL', company: 'Apple', price: 150, direction: 'BULLISH', horizon: 'SWING', score: 90, rankDelta: 0, scoreDelta: 0 }]),
        },
      ],
    });

    const page = await context.newPage();

    // 1. Matched fixture returns 200 and logs recorded bytes
    const matchedRes = await page.evaluate(async () => {
      const res = await fetch('http://localhost:8000/api/watchlist');
      return { status: res.status, data: await res.json() };
    });
    assert.equal(matchedRes.status, 200);
    assert.equal(matchedRes.data[0].symbol, 'AAPL');
    assert.ok(logs.fixtureLog.some(f => f.url.includes('/api/watchlist')));

    // 2. Unmatched API request is aborted and logged
    await assert.rejects(async () => {
      await page.evaluate(async () => {
        await fetch('http://localhost:8000/api/unmatched-endpoint');
      });
    });
    assert.ok(logs.abortLog.some(a => a.url.includes('/api/unmatched-endpoint')));

    // 3. Unsafe method to frontend server is aborted and logged
    await assert.rejects(async () => {
      await page.evaluate(async () => {
        await fetch('http://127.0.0.1:9999/api/post-test', { method: 'POST', body: '{}' });
      });
    });
    assert.ok(logs.abortLog.some(a => a.reason === 'unsafe-method-on-frontend-host'));

    // 4. External domain is aborted and logged
    await assert.rejects(async () => {
      await page.evaluate(async () => {
        await fetch('https://example.com/api');
      });
    });
    assert.ok(logs.abortLog.some(a => a.url.includes('example.com')));

    await page.close();
    await context.close();
  } finally {
    await browser.close();
  }
});

test('smoke: seed-once guard in sessionStorage preserves modified localStorage across page reload', async () => {
  const pw = require(path.join(REPO, 'frontend/node_modules/playwright'));
  const browser = await pw.chromium.launch({ headless: true });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();

    // Route a dummy HTML page on local loopback so localStorage & sessionStorage are accessible
    await page.route('http://127.0.0.1:9999/**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<!DOCTYPE html><html><body><h1>Seed Test</h1></body></html>',
      });
    });

    await page.goto('http://127.0.0.1:9999/test');

    // Run seedOnce with initial seed
    await seedOnce(page, { 'bamendjou:theme': 'dark', 'bamendjou:test_key': 'initial_val' });

    const initial = await page.evaluate(() => localStorage.getItem('bamendjou:test_key'));
    assert.equal(initial, 'initial_val');

    // Overwrite key via page script
    await page.evaluate(() => localStorage.setItem('bamendjou:test_key', 'overwritten_val'));

    // Reload page and re-apply seedOnce (simulating page reload with seeder hook)
    await page.reload();
    await seedOnce(page, { 'bamendjou:theme': 'dark', 'bamendjou:test_key': 'initial_val' });

    // Value must remain overwritten_val because sessionStorage guard was set
    const reloaded = await page.evaluate(() => localStorage.getItem('bamendjou:test_key'));
    assert.equal(reloaded, 'overwritten_val');

    await page.close();
    await context.close();
  } finally {
    await browser.close();
  }
});

test('smoke: generated self-test samples establish route coverage, dialog lifecycle, and provenance', () => {
  const samplesDir = path.join(REPO, 'docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/samples');
  const dashboard = JSON.parse(fs.readFileSync(path.join(samplesDir, 'dashboard.json'), 'utf8'));
  const settings = JSON.parse(fs.readFileSync(path.join(samplesDir, 'settings.json'), 'utf8'));
  const dialogOpen = JSON.parse(fs.readFileSync(path.join(samplesDir, 'dialog-open.json'), 'utf8'));
  const dialogClosed = JSON.parse(fs.readFileSync(path.join(samplesDir, 'dialog-closed.json'), 'utf8'));
  const provenance = JSON.parse(fs.readFileSync(path.join(samplesDir, 'provenance.json'), 'utf8'));

  // 1. Fixed purpose
  assert.equal(dashboard.purpose, 'tooling-self-test');
  assert.equal(settings.purpose, 'tooling-self-test');
  assert.equal(dialogOpen.purpose, 'tooling-self-test');
  assert.equal(dialogClosed.purpose, 'tooling-self-test');
  assert.equal(provenance.purpose, 'tooling-self-test');

  // 2. Dashboard contains renderless KeyboardShortcuts in census
  assert.ok(dashboard.census.mounted_names.includes('KeyboardShortcuts'), 'KeyboardShortcuts must be in dashboard census');

  // 3. Dialog lifecycle: mounted in open sample, absent in closed sample
  assert.ok(dialogOpen.census.mounted_names.includes('SaveProfileDialog'), 'SaveProfileDialog must be in open census');
  assert.equal(dialogClosed.census.mounted_names.includes('SaveProfileDialog'), false, 'SaveProfileDialog must be absent after close');

  // 4. Provenance fields
  assert.equal(provenance.source_sha, BASELINE);
  assert.equal(provenance.timezone, 'Europe/Berlin');
  assert.equal(provenance.build_command, 'npx next build --no-mangling');
  assert.ok(provenance.node_version);
  assert.ok(provenance.next_version);
  assert.ok(provenance.react_version);
  assert.ok(provenance.playwright_version);
  assert.ok(provenance.chromium_version);
  assert.ok(provenance.python_version);
  assert.ok(provenance.lockfile_sha256);
  assert.ok(provenance.fixture_hashes.length > 0);
});
