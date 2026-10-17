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
const output = path.join(__dirname, '../integrated-evidence');
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
  const harnessHashes = Object.fromEntries(['integrated-probe.cjs','integrated-actions.cjs'].filter(f=>fs.existsSync(path.join(__dirname,f))).map(f=>[f,sha(fs.readFileSync(path.join(__dirname,f)))]));
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
  await require('./integrated-actions.cjs')({page,goto,mode,capture,attempt,settled,storage,json,surface,inventory});
  write('network.json', network); write('mock-payloads.json', payloads); write('page-errors.json', errors);
  write('provenance.json', {source_baseline:inventory.source_baseline, browser:browser.version(), playwright:req('@playwright/test/package.json').version,next:req('next/package.json').version,node:process.version,date:new Date().toISOString(),harness_start_sha256:harnessHashes,real_backend_requests_allowed:0});
  await browser.close();
}
main().catch(e=>{write('fatal.json',{error:e.stack});console.error(e);process.exitCode=1;});
