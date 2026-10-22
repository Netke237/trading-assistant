/* Report-only runtime evidence. No live backend is permitted. Run from repo root. */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { createRequire } = require('module');
const root = path.resolve(__dirname, '../../../../../..');
const req = createRequire(path.join(root, 'frontend/package.json'));
req('ts-node').register({ transpileOnly: true, compilerOptions: { module: 'CommonJS', moduleResolution: 'node' } });
const { chromium } = req('@playwright/test');
const inventory = require('../inventory.json');
const output = path.join(__dirname, process.env.RUNTIME_STAGE === 'followup' ? 'followup-evidence' : process.env.RUNTIME_STAGE === 'details' ? 'interactive-evidence' : 'evidence');
fs.mkdirSync(output, { recursive: true });
const base = 'http://127.0.0.1:3017';
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const write = (name, value) => fs.writeFileSync(path.join(output, name), JSON.stringify(value, null, 2) + '\n');
const results = [], network = [], errors = [], payloads = {};
let current = 'setup';
function payload(body) { const value = String(body ?? ''); const hash = sha(value); payloads[hash] = { sha256: hash, body: value }; return hash; }
function routeId(url) { return inventory.route_entries.find(r => r.route === url && ['url-page', 'redirect', 'private-folder-source'].includes(r.classification))?.id; }
function surface(name) { return inventory.definitions.find(d => d.component === name)?.id; }
async function storage(page) { return page.evaluate(() => ({ local: Object.fromEntries(Object.entries(localStorage)), session: Object.fromEntries(Object.entries(sessionStorage)) })); }
async function capture(page, id, details = {}) {
  const state = await page.evaluate(() => ({ url: location.pathname + location.search, title: document.title, text: document.body.innerText,
    headings: Array.from(document.querySelectorAll('h1,h2,h3')).map(n => n.textContent),
    rails: Array.from(document.querySelectorAll('aside')).map(n => ({ class: n.className, text: n.innerText })),
    controls: Array.from(document.querySelectorAll('button,a,input,select,[role="dialog"],details,canvas')).map(n => ({ tag: n.tagName, role: n.getAttribute('role'), label: n.getAttribute('aria-label'), text: (n.innerText || '').slice(0, 220), title: n.getAttribute('title'), href: n.getAttribute('href'), disabled: n.disabled ?? null })) }));
  const result = { id, route_id: routeId(state.url.split('?')[0]) ?? null, status: 'observed', ...details, state, storage: await storage(page), network_indices: network.map((n, i) => n.probe === current ? i : -1).filter(i => i >= 0) };
  results.push(result); write('observations.json', results); write('network.json', network); write('mock-payloads.json', payloads); write('page-errors.json', errors); console.log(id + ': ' + state.url + ' [' + state.text.length + ' chars]'); return result;
}
async function attempt(id, operation) { current = id; try { await operation(); } catch (e) { results.push({ id, status: 'unavailable', error: String(e.message).slice(0, 1800) }); write('observations.json', results); console.log(id + ': UNAVAILABLE ' + String(e.message).slice(0, 160)); } }
async function settled(page) { await page.waitForLoadState('domcontentloaded'); await page.waitForTimeout(900); }
async function main() {
  const harnessHashes = Object.fromEntries(['probe.cjs','details.cjs','extras.cjs','followup.cjs'].filter(f=>fs.existsSync(path.join(__dirname,f))).map(f=>[f,sha(fs.readFileSync(path.join(__dirname,f)))]));
  process.chdir(path.join(root, 'frontend'));
  const mocksFile = path.join(root, 'frontend/e2e/fixtures/api-mocks.ts');
  const { setupApiMocks, MOCK_SCAN_CANDIDATE, MOCK_OPTION_CHAIN } = req(mocksFile);
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'en-US', timezoneId: 'Europe/Berlin', serviceWorkers: 'block' });
  await context.routeWebSocket(/.*/, socket => { network.push({ probe: current, method: 'WEBSOCKET', path: new URL(socket.url()).pathname, action: 'closed-before-connect' }); socket.close(); });
  await context.route('**/*', async route => {
    const r = route.request(), url = new URL(r.url());
    if (url.origin === base && r.method() === 'GET' && !url.pathname.startsWith('/api/')) return route.continue();
    network.push({ probe: current, method: r.method(), path: url.pathname, query_keys: [...url.searchParams.keys()], action: 'blocked-unmatched' });
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage(); page.setDefaultTimeout(8000); page.setDefaultNavigationTimeout(180000);
  page.on('pageerror', e => errors.push({ probe: current, error: e.message }));
  // Wrap every fixture handler: record only synthetic response payloads and sanitized request metadata.
  const originalRoute = page.route.bind(page);
  page.route = (pattern, handler, options) => originalRoute(pattern, async route => {
    const r = route.request(), url = new URL(r.url());
    const proxy = new Proxy(route, { get(target, key) { if (key === 'continue') return async () => { if (url.origin === base && r.method() === 'GET' && !url.pathname.startsWith('/api/')) return target.continue(); network.push({ probe: current, method: r.method(), path: url.pathname, action: 'blocked-fixture-continue' }); return target.abort('blockedbyclient'); }; if (key === 'fulfill') return async opts => { network.push({ probe: current, method: r.method(), path: url.pathname, query_keys: [...url.searchParams.keys()], action: 'mocked', status: opts.status ?? 200, response_sha256: payload(opts.body), request_body_sha256: r.postData() ? payload(r.postData()) : null }); return target.fulfill(opts); }; return typeof target[key] === 'function' ? target[key].bind(target) : target[key]; } });
    return handler(proxy);
  }, options);
  await setupApiMocks(page);
  const json = (url, body, status = 200) => page.route('**' + url, route => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }));
  await json('/api/scan/last', null); await json('/api/stock-scan/last', null);
  await json('/api/scan/last-run', { status: 'IDLE', updated_at: null });
  await json('/api/stock-scan/last-run', { status: 'IDLE', updated_at: null, strategy: null });
  await page.addInitScript(() => {
    if (location.origin !== 'http://127.0.0.1:3017') return;
    if (!localStorage.getItem('audit-initialized')) { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('audit-initialized', 'synthetic-isolated'); }
    const next = sessionStorage.getItem('audit-next-scan-seed');
    if (next) { localStorage.setItem('bamendjou-scan-store', next); sessionStorage.removeItem('audit-next-scan-seed'); }
  });
  async function goto(url) { await page.goto(base + url); await settled(page); }
  async function mode(value) { await page.evaluate(mode => sessionStorage.setItem('audit-next-scan-seed', JSON.stringify({ version: 19, state: { screenerMode: mode } })), value); }
  if (!['details','followup'].includes(process.env.RUNTIME_STAGE)) {
  await attempt('route:/', async () => { await goto('/'); if (new URL(page.url()).pathname !== '/dashboard') throw Error('root did not redirect to dashboard'); await capture(page, 'route:/', { requested_route_id: routeId('/'), assertion: 'root redirect reached dashboard; actual body recorded' }); });
  const urlEntries = inventory.route_entries.filter(r => ['url-page', 'redirect', 'private-folder-source'].includes(r.classification));
  for (const entry of urlEntries.filter(r => r.route !== '/')) await attempt('hard:' + entry.route, async () => {
    const m = /step-4-prebreakout/.test(entry.route) ? 'prebreakout' : /step-4-stocks|step-5-strategy|step-6-backtest|step-7-position-card/.test(entry.route) ? 'stocks' : 'options';
    await mode(m); const before = await storage(page); await goto(entry.route);
    const body = await page.locator('body').innerText(); if (body.length < 15) throw Error('empty DOM');
    const expected = entry.route === '/screener' ? '/screener/step-1-regime' : entry.route.endsWith('/step-5-strategy') ? '/screener/step-4-stocks' : entry.route;
    if (new URL(page.url()).pathname !== expected) throw Error('Unexpected route: ' + page.url() + ', expected ' + expected);
    if (entry.classification === 'private-folder-source' && !body.includes('Page not found')) throw Error('private page unexpectedly exposed');
    await capture(page, 'hard:' + entry.route, { requested_route_id: entry.id, mode: m, storage_before: before, assertion: entry.classification === 'private-folder-source' ? 'private source URL renders actual root notfound' : 'expected final URL and nonempty DOM; inspect recorded body for data state', arithmetic: 'pending owning lane' });
  });
  await attempt('settings:nine-sections', async () => {
    await goto('/settings');
    for (const section of inventory.settings_sections) {
      const label = section.label || { theme: 'Appearance', scan: 'Scan', strategy: 'Strategy scan', brokers: 'Brokers', risk: 'Risk', regime: 'Regime', notifications: 'Notifications', data: 'Data', tuning: 'Strategy Tuning' }[section.key];
      const button = page.locator('aside button').filter({ has: page.getByText(label, { exact: true }) }); await button.click(); await settled(page);
      await capture(page, 'settings:' + section.key, { surface_ids: [surface(section.component)].filter(Boolean), fixture_identity: 'settings-section:' + section.key, assertion: 'section button clicked; visible section DOM recorded', state_requirement: 'expanded/nested', owners: section.owners });
    }
  });
  await attempt('navigation:primary', async () => {
    await goto('/dashboard'); const links = await page.locator('nav[aria-label="Primary"] a').evaluateAll(nodes => nodes.map(n => ({ text: n.textContent.trim(), href: n.getAttribute('href') })));
    for (const link of links.filter(l => l.href !== '/screener')) { await page.locator('nav[aria-label="Primary"] a').filter({ hasText: link.text }).click(); await settled(page); if (new URL(page.url()).pathname !== link.href) throw Error('primary link failed ' + link.href); await capture(page, 'soft:' + link.href, { surface_ids: [surface('NavItems')], fixture_identity: 'primary-link:' + link.href, assertion: 'real link click reached expected URL; retained rail recorded' }); }
    await page.goBack(); await settled(page); await capture(page, 'history:back'); await page.goForward(); await settled(page); await capture(page, 'history:forward');
    const before = await storage(page); await page.reload(); await settled(page); await capture(page, 'history:reload', { storage_before: before, assertion: 'hard reload after primary soft-navigation sequence' });
  });
  await attempt('boundary:notfound', async () => { await goto('/audit-unrecognized-route'); await page.getByRole('heading', { name: 'Page not found' }).waitFor(); await capture(page, 'boundary:notfound', { surface_ids: [surface('NotFound')], assertion: 'actual visible notfound heading' }); });
  await attempt('boundary:min-width', async () => {
    await goto('/dashboard');
    for (const width of [1279, 1280]) { await page.setViewportSize({ width, height: 1000 }); await page.waitForTimeout(150); const visible = await page.getByRole('dialog', { name: 'Desktop required' }).isVisible(); if (visible !== (width < 1280)) throw Error('default min-width mismatch'); await capture(page, 'min-width:default:' + width, { surface_ids: [surface('MinWidthGate')], assertion: 'Desktop required visible=' + visible }); }
    await mode('options'); await goto('/screener/step-7-trade-card');
    for (const width of [1199, 1200]) { await page.setViewportSize({ width, height: 1000 }); await page.waitForTimeout(150); const visible = await page.getByRole('dialog', { name: 'Desktop required' }).isVisible(); if (visible !== (width < 1200)) throw Error('trade-card min-width mismatch'); await capture(page, 'min-width:trade-card:' + width, { surface_ids: [surface('MinWidthGate')], assertion: 'Desktop required visible=' + visible }); }
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  } else {
    await require(process.env.RUNTIME_STAGE === 'followup' ? './followup.cjs' : './details.cjs')({ page, context, browser, goto, mode, capture, attempt, settled, storage, json, surface, inventory, MOCK_SCAN_CANDIDATE, MOCK_OPTION_CHAIN, results, network, write });
  }
  write('network.json', network); write('mock-payloads.json', payloads); write('page-errors.json', errors);
  const files = ['frontend/e2e/fixtures/api-mocks.ts', ...['AAPL','MSFT','NVDA','SPY'].map(s => 'backend/tests/fixtures/' + s + '_candles.json')];
  write('provenance.json', { source_baseline: inventory.source_baseline, frontend_server: 'isolated Next dev, loopback3017', backend_mode: 'no backend; context deny guard; deterministic repository mocks and null recovery inputs', browser: browser.version(), playwright: req('@playwright/test/package.json').version, next: req('next/package.json').version, node: process.version, date: new Date().toISOString(), harness_start_sha256: harnessHashes, input_hashes: Object.fromEntries(files.filter(f => fs.existsSync(path.join(root, f))).map(f => [f, sha(fs.readFileSync(path.join(root, f)))])), observation_count: results.length, failure_count: results.filter(r => r.status === 'unavailable').length, mock_payload_count: Object.keys(payloads).length, real_backend_requests_allowed: 0 });
  await browser.close();
}
main().catch(e => { write('fatal.json', { error: e.stack }); console.error(e); process.exitCode = 1; });
