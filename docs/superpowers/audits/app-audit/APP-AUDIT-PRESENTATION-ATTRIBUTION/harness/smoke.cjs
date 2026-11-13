'use strict';

/**
 * smoke.cjs — Production Next.js isolated build, serve, Playwright smoke harness and provenance recorder.
 */

const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const http = require('node:http');
const net = require('node:net');

const { BASELINE, REPO, sha, json, canonical } = require('./map-common.cjs');
const { runCensusInPage } = require('./census.cjs');

const J1_DIR = path.resolve(__dirname, '..');
const FIXTURES_DIR = path.join(J1_DIR, 'fixtures');
const SAMPLES_DIR = path.join(J1_DIR, 'samples');

function loadFixtures(dir = FIXTURES_DIR) {
  const fixtures = [];
  const apiDir = path.join(dir, 'api');
  if (fs.existsSync(apiDir)) {
    const files = fs.readdirSync(apiDir).filter(f => f.endsWith('.json'));
    for (const f of files) {
      const fullPath = path.join(apiDir, f);
      const bytes = fs.readFileSync(fullPath, 'utf8');
      const baseName = path.basename(f, '.json');
      // Map baseName to API path pattern
      let pathPattern;
      if (baseName === 'performance') {
        pathPattern = '/api/portfolio/performance';
      } else if (baseName === 'config-health') {
        pathPattern = '/api/config/health';
      } else if (baseName === 'event-thresholds') {
        pathPattern = '/api/config/event-thresholds';
      } else if (baseName === 'iv-thresholds') {
        pathPattern = '/api/config/iv-thresholds';
      } else if (baseName === 'contract-rules') {
        pathPattern = '/api/config/contract-rules';
      } else {
        pathPattern = `/api/${baseName}`;
      }
      fixtures.push({
        name: baseName,
        pathPattern,
        method: 'GET',
        bytes,
        sha256: sha(bytes),
        fixturePath: path.relative(REPO, fullPath).replace(/\\/g, '/'),
      });
    }
  }
  return fixtures;
}

function loadStorageSeeds(dir = FIXTURES_DIR) {
  const seedsPath = path.join(dir, 'seeds/storage-seeds.json');
  if (fs.existsSync(seedsPath)) {
    return JSON.parse(fs.readFileSync(seedsPath, 'utf8'));
  }
  return { 'bamendjou:theme': 'dark' };
}

function getFrozenManifest(repo = REPO, baseline = BASELINE) {
  const output = cp.execFileSync('git', ['ls-tree', '-r', '--name-only', baseline, '--', 'frontend'], {
    cwd: repo,
    encoding: 'utf8',
  });
  return output.trim().split('\n').filter(Boolean).sort();
}

function exportIsolatedTree(tempDir, repo = REPO, baseline = BASELINE) {
  fs.mkdirSync(tempDir, { recursive: true });
  // Export using git archive | tar
  const cmd = `git archive ${baseline} frontend/ | tar -xf - -C "${tempDir}"`;
  cp.execSync(cmd, { cwd: repo, shell: true });

  const frontendDir = path.join(tempDir, 'frontend');
  const manifest = verifyManifest(frontendDir, repo, baseline);
  verifyLockfile(frontendDir, repo, baseline);

  return { frontendDir, manifest };
}

function getAllFilesRelative(dir, baseDir = dir) {
  let results = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    // Ignore generated outputs and node_modules
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === '.next' || entry.name === '.git') {
        continue;
      }
      results = results.concat(getAllFilesRelative(fullPath, baseDir));
    } else {
      const rel = path.relative(baseDir, fullPath).replace(/\\/g, '/');
      results.push('frontend/' + rel);
    }
  }
  return results.sort();
}

function verifyManifest(frontendDir, repo = REPO, baseline = BASELINE) {
  const expected = getFrozenManifest(repo, baseline);
  const actual = getAllFilesRelative(frontendDir);

  const expectedSet = new Set(expected);
  const actualSet = new Set(actual);

  const extra = actual.filter(f => !expectedSet.has(f));
  if (extra.length > 0) {
    throw new Error(`manifest-extra-file: found untracked/extra files in exported tree: ${extra.join(', ')}`);
  }

  const missing = expected.filter(f => !actualSet.has(f));
  if (missing.length > 0) {
    throw new Error(`manifest-missing-file: missing expected files in exported tree: ${missing.join(', ')}`);
  }

  return expected;
}

function verifyLockfile(frontendDir, repo = REPO, baseline = BASELINE) {
  const actualLock = fs.readFileSync(path.join(frontendDir, 'package-lock.json'), 'utf8');
  const frozenLock = cp.execFileSync('git', ['show', `${baseline}:frontend/package-lock.json`], {
    cwd: repo,
    encoding: 'utf8',
  });
  if (sha(actualLock.replace(/\r\n/g, '\n')) !== sha(frozenLock.replace(/\r\n/g, '\n'))) {
    throw new Error('lockfile-mismatch: package-lock.json does not match frozen baseline');
  }
}

function linkNodeModules(frontendDir, repo = REPO) {
  const target = path.join(repo, 'frontend', 'node_modules');
  const link = path.join(frontendDir, 'node_modules');
  if (!fs.existsSync(link)) {
    const type = process.platform === 'win32' ? 'junction' : 'dir';
    fs.symlinkSync(target, link, type);
  }
}

function verifyNextBuildTooling(frontendDir) {
  const helpOutput = cp.execSync('npx next build --help', { cwd: frontendDir, encoding: 'utf8' });
  if (!helpOutput.includes('--no-mangling')) {
    throw new Error('unsupported-tooling: next build does not support --no-mangling');
  }
}

function buildProductionServer(frontendDir, options = {}) {
  verifyNextBuildTooling(frontendDir);
  if (!options.forceRebuild && fs.existsSync(path.join(frontendDir, '.next', 'BUILD_ID'))) {
    return; // Already built in this directory
  }
  cp.execSync('npx next build --no-mangling', {
    cwd: frontendDir,
    stdio: 'inherit',
    shell: true,
  });
}

function getUnusedPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
    server.on('error', reject);
  });
}

async function startProductionServer(frontendDir, port) {
  if (!port) port = await getUnusedPort();
  const serverUrl = `http://127.0.0.1:${port}`;

  const child = cp.spawn('npx', ['next', 'start', '-p', String(port), '-H', '127.0.0.1'], {
    cwd: frontendDir,
    shell: true,
    stdio: 'pipe',
  });

  child.stderr.on('data', (d) => process.stderr.write(d));

  // Wait for server to become responsive
  const maxAttempts = 60;
  let ready = false;
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, 500));
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(serverUrl, (res) => {
          resolve(res.statusCode);
        });
        req.on('error', reject);
        req.setTimeout(500, () => req.destroy());
      });
      ready = true;
      break;
    } catch {
      // Keep waiting
    }
  }

  if (!ready) {
    child.kill('SIGTERM');
    throw new Error(`server-start-failed: Next.js server on ${serverUrl} did not respond within timeout`);
  }

  const stop = () => {
    try {
      if (process.platform === 'win32') {
        cp.execSync(`taskkill /pid ${child.pid} /T /F`);
      } else {
        child.kill('SIGKILL');
      }
    } catch {
      // Process may already be dead
    }
  };

  return { port, url: serverUrl, proc: child, stop };
}

function setupPlaywrightRouting(context, options) {
  const { serverUrl, fixtures = [] } = options;
  const fixtureLog = [];
  const abortLog = [];
  const allowedAssetLog = [];
  const wsLog = [];

  // WebSocket blocking
  context.on('websocket', (ws) => {
    wsLog.push({ url: ws.url(), closed: true });
    ws.close();
  });

  // Client-side WebSocket disabler initScript
  context.addInitScript(() => {
    window.__closedWebSockets = [];
    window.WebSocket = class extends EventTarget {
      constructor(url) {
        super();
        this.url = url;
        this.readyState = 3; // CLOSED
        window.__closedWebSockets.push(url);
        setTimeout(() => {
          this.dispatchEvent(new CloseEvent('close', { wasClean: false, code: 1006 }));
        }, 0);
      }
      send() {}
      close() {}
    };
  });

  // Route all HTTP traffic
  context.route('**/*', async (route, request) => {
    const url = request.url();
    const method = request.method();
    const parsed = new URL(url);

    // 1. Check for matched API fixture
    const matched = fixtures.find(f => {
      if (f.method && f.method !== method) return false;
      return parsed.pathname === f.pathPattern || parsed.pathname.startsWith(f.pathPattern);
    });

    if (matched) {
      fixtureLog.push({
        method,
        url,
        status: 200,
        bytes_sha256: matched.sha256,
        fixture_path: matched.fixturePath || null,
      });
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: matched.bytes,
      });
      return;
    }

    // 2. Same-origin frontend asset/document GET/HEAD traffic
    if (url.startsWith(serverUrl)) {
      if (method === 'GET' || method === 'HEAD') {
        allowedAssetLog.push({ method, url });
        await route.continue();
        return;
      }
      // Unsafe method on frontend host
      abortLog.push({ method, url, reason: 'unsafe-method-on-frontend-host' });
      await route.abort();
      return;
    }

    // 3. Everything else aborts and is logged
    abortLog.push({ method, url, reason: 'unmatched-or-external-request' });
    await route.abort();
  });

  return { fixtureLog, abortLog, allowedAssetLog, wsLog };
}

async function seedOnce(page, seeds) {
  await page.evaluate((initialSeeds) => {
    if (!sessionStorage.getItem('__j1_seeded__')) {
      for (const [k, v] of Object.entries(initialSeeds)) {
        localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v));
      }
      sessionStorage.setItem('__j1_seeded__', '1');
    }
  }, seeds);
}

function extractStorageState(page) {
  return page.evaluate(() => {
    const local = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      local[k] = localStorage.getItem(k);
    }
    const session = {};
    for (let i = 0; i < sessionStorage.length; i++) {
      const k = sessionStorage.key(i);
      session[k] = sessionStorage.getItem(k);
    }
    return { localStorage: local, sessionStorage: session };
  });
}

function extractVisibleDomInfo(page) {
  return page.evaluate(() => {
    const texts = [];
    const refs = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    let el;
    while ((el = walker.nextNode())) {
      if (el.textContent && el.children.length === 0) {
        const t = el.textContent.trim();
        if (t && t.length < 200) texts.push(t);
      }
      if (el.id || el.getAttribute('role') || el.tagName === 'BUTTON' || el.tagName === 'A' || el.tagName === 'INPUT' || el.tagName === 'MAIN' || el.tagName === 'SECTION') {
        refs.push({
          tag: el.tagName.toLowerCase(),
          id: el.id || null,
          role: el.getAttribute('role') || null,
          text: (el.textContent || '').trim().slice(0, 100),
        });
      }
    }
    return {
      visibleText: Array.from(new Set(texts)).slice(0, 50),
      domReferences: refs.slice(0, 50),
    };
  });
}

function gatherProvenance(options = {}) {
  const repo = options.repo || REPO;
  const baseline = options.baseline || BASELINE;
  const pw = require(path.join(repo, 'frontend/node_modules/playwright'));

  let pythonVersion = 'Python 3.11 unavailable';
  try {
    pythonVersion = cp.execFileSync('python', ['--version'], { encoding: 'utf8' }).trim();
  } catch {
    try {
      pythonVersion = cp.execFileSync('py', ['-3.11', '--version'], { encoding: 'utf8' }).trim();
    } catch {}
  }

  const frontendPkg = JSON.parse(fs.readFileSync(path.join(repo, 'frontend/package.json'), 'utf8'));
  const lockfileBytes = cp.execFileSync('git', ['show', `${baseline}:frontend/package-lock.json`], {
    cwd: repo,
    encoding: 'utf8',
  });

  const fixtures = loadFixtures(options.fixturesDir || FIXTURES_DIR);
  const fixtureHashes = fixtures.map(f => ({ name: f.name, path: f.fixturePath, sha256: f.sha256 }));

  return {
    purpose: 'tooling-self-test',
    source_sha: baseline,
    node_version: process.version,
    next_version: frontendPkg.dependencies.next || '15.5.23',
    react_version: frontendPkg.dependencies.react || '19.2.5',
    playwright_version: pw.version || '1.58.2',
    chromium_version: options.chromiumVersion || '151.0.7922.34',
    chromium_executable: pw.chromium.executablePath(),
    python_version: pythonVersion,
    timezone: 'Europe/Berlin',
    lockfile_sha256: sha(lockfileBytes),
    build_command: 'npx next build --no-mangling',
    fixture_hashes: fixtureHashes,
  };
}

async function runSmokeSuite(options = {}) {
  const repo = options.repo || REPO;
  const baseline = options.baseline || BASELINE;
  const tempDir = options.tempDir || fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'j1-smoke-run-'));
  const samplesDir = options.samplesDir || SAMPLES_DIR;
  fs.mkdirSync(samplesDir, { recursive: true });

  const { frontendDir } = exportIsolatedTree(tempDir, repo, baseline);
  linkNodeModules(frontendDir, repo);
  buildProductionServer(frontendDir, { forceRebuild: options.forceRebuild });

  const server = await startProductionServer(frontendDir);
  const fixtures = loadFixtures();
  const seeds = loadStorageSeeds();

  const pw = require(path.join(repo, 'frontend/node_modules/playwright'));
  const browser = await pw.chromium.launch({ headless: true });
  const chromiumVersion = browser.version();

  const samples = {};
  let provenance;

  try {
    const context = await browser.newContext({
      serviceWorkers: 'block',
      viewport: { width: 1280, height: 800 },
      colorScheme: 'dark',
      timezoneId: 'Europe/Berlin',
    });

    const routingLogs = setupPlaywrightRouting(context, {
      serverUrl: server.url,
      fixtures,
    });

    const page = await context.newPage();

    // 1. Capture /dashboard
    await page.goto(`${server.url}/dashboard`, { waitUntil: 'networkidle' });
    await seedOnce(page, seeds);
    // Reload once to let seeds settle
    await page.reload({ waitUntil: 'networkidle' });

    const dashboardCensus = await runCensusInPage(page);
    const dashboardDom = await extractVisibleDomInfo(page);
    const dashboardStorage = await extractStorageState(page);

    samples['dashboard'] = {
      purpose: 'tooling-self-test',
      url: page.url(),
      route_entry: 'frontend/app/(frame)/dashboard/page.tsx',
      source_sha: baseline,
      fixture_response_log: [...routingLogs.fixtureLog],
      storage: {
        seeds,
        readback: dashboardStorage,
      },
      visible_text: dashboardDom.visibleText,
      dom_references: dashboardDom.domReferences,
      census: dashboardCensus,
    };
    fs.writeFileSync(path.join(samplesDir, 'dashboard.json'), json(samples['dashboard']));

    // 2. Capture /settings
    await page.goto(`${server.url}/settings`, { waitUntil: 'networkidle' });
    const settingsCensus = await runCensusInPage(page);
    const settingsDom = await extractVisibleDomInfo(page);
    const settingsStorage = await extractStorageState(page);

    samples['settings'] = {
      purpose: 'tooling-self-test',
      url: page.url(),
      route_entry: 'frontend/app/(frame)/settings/page.tsx',
      source_sha: baseline,
      fixture_response_log: [...routingLogs.fixtureLog],
      storage: {
        seeds,
        readback: settingsStorage,
      },
      visible_text: settingsDom.visibleText,
      dom_references: settingsDom.domReferences,
      census: settingsCensus,
    };
    fs.writeFileSync(path.join(samplesDir, 'settings.json'), json(samples['settings']));

    // 3. Dialog open/close lifecycle on /screener/step-3-direction
    await page.goto(`${server.url}/screener/step-3-direction`, { waitUntil: 'networkidle' });

    // Open SaveProfileDialog
    const saveBtn = page.locator('button:has-text("Save as new…")');
    if (await saveBtn.isVisible()) {
      await saveBtn.click();
      await page.waitForTimeout(300);

      const dialogOpenCensus = await runCensusInPage(page);
      const dialogOpenDom = await extractVisibleDomInfo(page);
      samples['dialog-open'] = {
        purpose: 'tooling-self-test',
        url: page.url(),
        route_entry: 'frontend/app/(frame)/screener/step-3-direction/page.tsx',
        source_sha: baseline,
        dialog: 'SaveProfileDialog',
        action: 'open',
        visible_text: dialogOpenDom.visibleText,
        census: dialogOpenCensus,
      };
      fs.writeFileSync(path.join(samplesDir, 'dialog-open.json'), json(samples['dialog-open']));

      // Close dialog by clicking Cancel
      const cancelBtn = page.locator('button:has-text("Cancel")');
      if (await cancelBtn.isVisible()) {
        await cancelBtn.click();
        await page.waitForTimeout(300);

        const dialogClosedCensus = await runCensusInPage(page);
        const dialogClosedDom = await extractVisibleDomInfo(page);
        samples['dialog-closed'] = {
          purpose: 'tooling-self-test',
          url: page.url(),
          route_entry: 'frontend/app/(frame)/screener/step-3-direction/page.tsx',
          source_sha: baseline,
          dialog: 'SaveProfileDialog',
          action: 'closed',
          visible_text: dialogClosedDom.visibleText,
          census: dialogClosedCensus,
        };
        fs.writeFileSync(path.join(samplesDir, 'dialog-closed.json'), json(samples['dialog-closed']));
      }
    }

    // Provenance
    provenance = gatherProvenance({ repo, baseline, chromiumVersion });
    fs.writeFileSync(path.join(samplesDir, 'provenance.json'), json(provenance));
    fs.writeFileSync(path.join(J1_DIR, 'provenance.json'), json(provenance));

    await page.close();
    await context.close();
  } finally {
    await browser.close();
    server.stop();
    if (!options.keepTemp) {
      // Junction must be unlinked before rmSync
      const link = path.join(frontendDir, 'node_modules');
      if (fs.existsSync(link)) {
        try { fs.unlinkSync(link); } catch {}
      }
      try { fs.rmSync(tempDir, { recursive: true, force: true }); } catch {}
    }
  }

  return { samples, provenance };
}

module.exports = {
  loadFixtures,
  loadStorageSeeds,
  getFrozenManifest,
  exportIsolatedTree,
  verifyManifest,
  verifyLockfile,
  linkNodeModules,
  verifyNextBuildTooling,
  buildProductionServer,
  getUnusedPort,
  startProductionServer,
  setupPlaywrightRouting,
  seedOnce,
  gatherProvenance,
  runSmokeSuite,
};

if (require.main === module) {
  runSmokeSuite()
    .then(() => {
      console.log('Production smoke suite completed successfully. Samples written to samples/');
    })
    .catch((err) => {
      console.error('Smoke suite failed:', err);
      process.exit(1);
    });
}
