// #608 grouped decision section and single selected-target review acceptance, adapted from #607 capture-method-tables.cjs.
// Every API call is answered inside the browser's route layer; nothing reaches a
// server. The guard (registered last, so it runs first) rejects every write that
// is not on its allow-list, and answers the allow-listed ones itself.
const fs = require('fs');
const path = require('path');
const args = require('util').parseArgs({ options: {
  'repo-root': { type: 'string' }, output: { type: 'string' },
  'base-url': { type: 'string', default: 'http://127.0.0.1:3097' }, browser: { type: 'string' },
  widths: { type: 'string', default: '1200,1366,1920' }, themes: { type: 'string', default: 'dark,light' },
} }).values;
const repoRoot = path.resolve(args['repo-root'] || path.resolve(__dirname, '../../../..'));
const frontendRoot = path.join(repoRoot, 'frontend');
if (!args.output) throw new Error('--output is required');
const output = path.resolve(args.output);
fs.mkdirSync(output, { recursive: true });
const baseUrl = new URL(args['base-url']);
const LOOPBACK = ['127.0.0.1', 'localhost', '[::1]'];
if (!LOOPBACK.includes(baseUrl.hostname)) throw new Error('Only a local mocked app URL is permitted');
if (baseUrl.port === '3001') throw new Error('Port 3001 is the live app and is never used here');
process.chdir(frontendRoot); // the shared fixture resolves candle files relative to frontend/
const ts = require(require.resolve('typescript', { paths: [frontendRoot] }));
const Module = require('module');
const { chromium } = require(require.resolve('playwright', { paths: [frontendRoot] }));
const fixturePath = path.join(frontendRoot, 'e2e/fixtures/api-mocks.ts');
const fixtureMod = new Module(fixturePath); fixtureMod.filename = fixturePath; fixtureMod.paths = Module._nodeModulePaths(frontendRoot);
fixtureMod._compile(ts.transpileModule(fs.readFileSync(fixturePath, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, fixturePath);
const fixture = fixtureMod.exports;

const CALCULATION_POSTS = ['/api/contracts/exit-plan', '/api/contracts/structural-stop', '/api/contracts/first-passage'];

const card = JSON.parse(JSON.stringify(fixture.MOCK_SCAN_CANDIDATE).replaceAll('2025-05-16', '2026-12-18'));
card.contractDetails.dte = 75; card.exit.target = 194.25; card.confidence = 72; card.confidenceText = 'Historical entry signals: 64 samples.';
card.sentiment = { horizon: 'Swing', timeframe: 'Daily', state: 'Bullish', p_stay: 0.73, stability: 0.72, regime_age_days: 8, avg_regime_duration: 12, conviction_pct: 73, conviction_label: 'Bullish', interpretation: 'Measured market context for this horizon.', alignment: 'Aligned' };
card.fundamentals = { score: 74, quality_label: 'Strong', risk_label: 'Low', growth_score: 80, quality_score: 75, risk_score: 65, safety_flags: ['High debt'], detail: {} };
card.alternatives = [{ symbol: 'AAPL', strike: 190, expiry: '2026-12-18', right: 'C', dte: 75, mid: 1.6, delta: 0.41, theta: -0.04, ivRank: null, iv: 40, score: 66, contractConfidence: 'CAUTION', contractBreakdown: card.contractBreakdown, rrRatio: 2.1, rrModel: 'BS repriced (IV-derived)', reason: 'Cheaper premium, lower delta.' }];
const other = { ...card, symbol: 'MSFT', company: 'Microsoft', contract: 'MSFT|185|2026-12-18|C' };

const race = { premiumStopPrice: 1.15, premiumStopPct: 0.465, stockStopPrice: 180, premiumUsed: 2.15, ivSolved: true, nPaths: 2000, outcomes: [0.2, 0.35, 0.5].map((pct, i) => ({ targetPct: pct, targetOptionPrice: Number((2.15 * (1 + pct)).toFixed(2)), pTargetFirst: 0.4, pStockStopFirst: 0.2, pPremiumStopFirst: 0.3, pNeither: 0.1, weightTargetFirst: 0.4, weightStockStopFirst: 0.2, weightPremiumStopFirst: 0.3, weightNeither: 0.1, daysTarget: 7 + i * 3, daysStockStop: 8, daysPremiumStop: 9, daysAnyPathReachedStop: 10, repriceDaysStockStop: 10, terminalMean: 2, rewardDollar: Number((2.15 * pct).toFixed(2)), stopRepricedValue: 0.65, riskStockStop: 1.5, riskPremiumStop: 1, rrStockStop: 2.15 * pct / 1.5, rrPremiumStop: 2.15 * pct, edgePerContract: -30 })) };
const first = { targets: race.outcomes.map((o, i) => ({ pct: o.targetPct, stockPrice: 195 + i * 4, optionPrice: o.targetOptionPrice, probability: 0.5 - i * 0.1, expectedDays: o.daysTarget })), invalidation: { probability: 0.3, expectedDays: 10 }, race };
const exitPlan = { stop: { stopCost: { lossDollar: 1.5, valueAtStop: 0.65, fraction: 0.6977, status: 'CAUTION', passMaxFraction: 0.6, premium: 2.15, stopPrice: 180, basis: 'bs_today' }, price: 180, source: 'atr_widened', contractPrice: 0.65, rrModel: 'Heston repriced', structuralSource: 'order_block', structuralConfidence: 75, structuralPrice: 182, atrFloorPrice: 180, distanceDollar: 2 }, targets: [2, 3].map((rr, i) => ({ rrRatio: rr, arithmeticPrice: 195 + i * 5, price: 195 + i * 5, tpSource: 'arithmetic', structuralPrice: null, contractPrice: 3.7 + i, rrModel: 'Heston repriced', probability: 0.5 - i * 0.1, expectedDays: 9 + i * 4, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 })), atr: 4 };

const mockPreview = (body) => {
  return {
    fingerprint: `mock-fingerprint-${body.recId}`,
    position: { ...body, id: '', createdAt: '', entryPrice: 2.2 },
    adjustedQty: null, premiumStopUnapplied: null, entryFromLiveQuote: true, entryStockPrice: 185.4,
    inheritedPremiumStopPct: 0.6,
    differences: [{ field: 'entryPrice', requested: body.entryPrice, effective: 2.2, reason: 'live_quote' }],
  };
};

const STATES = ['initial', 'mc-selected', 'race-selected', 'stale', 'ladder', 'restored'];

async function runOne(browser, width, theme) {
  const tag = `${width}-${theme}`;
  const context = await browser.newContext({ viewport: { width, height: 1000 }, deviceScaleFactor: 1, colorScheme: theme });
  const page = await context.newPage();
  const log = { width, theme, results: [], layout: {}, blockedWrites: [], mockedWrites: [], unmocked: [], externalAborted: [], pageErrors: [], consoleErrors: [] };
  const assert = (cond, msg) => { if (!cond) throw new Error(`[${tag}] ${msg}`); log.results.push(msg); };
  page.on('pageerror', (e) => log.pageErrors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') log.consoleErrors.push(m.text().slice(0, 200)); });
  await page.routeWebSocket(/.*/, (ws) => ws.close());

  // Registered FIRST, so it runs LAST: anything the mocks did not answer stops here.
  await page.route('**/*', async (route) => {
    const u = new URL(route.request().url());
    if (u.pathname.startsWith('/api/') || u.pathname.startsWith('/broker/') || u.pathname.startsWith('/ws/')) {
      log.unmocked.push(`${route.request().method()} ${u.pathname}`);
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"not mocked"}' });
      return;
    }
    await route.fallback();
  });
  await fixture.setupApiMocks(page);
  await page.route('**/api/**', async (route) => {
    const p = new URL(route.request().url()).pathname;
    let body;
    if (p.includes('/quote/stock')) body = { symbol: 'AAPL', price: 185.2 };
    else if (p.includes('/quote/option')) body = { price: 2.15, delta: 0.52, theta: -0.05, ivRank: null, iv: 42, spread: 0.02, volume: 1250, quoteLive: true };
    else if (p.includes('/structural-stop')) body = { available: true, price: 180, source: 'order_block', confidence: 75, distancePct: 2.8 };
    else if (p.includes('/first-passage')) body = first;
    else if (p.includes('/exit-plan')) body = exitPlan;
    else if (p.includes('/scan/last') || p.includes('/stocks/scan/last')) body = null;
    else { await route.fallback(); return; }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  // Registered LAST, so it runs FIRST. The unsafe-write guard.
  await page.route('**/*', async (route) => {
    const req = route.request(); const u = new URL(req.url()); const m = req.method(); const p = u.pathname;
    if (!LOOPBACK.includes(u.hostname) && !u.protocol.startsWith('data') && !u.hostname.endsWith('fonts.googleapis.com') && !u.hostname.endsWith('fonts.gstatic.com')) {
      log.externalAborted.push(`${m} ${u.origin}${p}`); await route.abort('blockedbyclient'); return;
    }
    if (['GET', 'HEAD', 'OPTIONS'].includes(m)) { await route.fallback(); return; }
    if (m === 'POST' && CALCULATION_POSTS.includes(p)) { await route.fallback(); return; }
    if (m === 'POST' && p === '/api/portfolio/preview') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockPreview(req.postDataJSON())) });
      return;
    }
    if (m === 'POST' && p === '/api/portfolio') {
      // Answered here; never reaches a server. Only the outcome state may do this.
      if (!allowSave) { log.blockedWrites.push({ method: m, path: p }); await route.abort('blockedbyclient'); return; }
      const b = req.postDataJSON(); const hdr = req.headers()['x-review-fingerprint'] ?? null;
      log.mockedWrites.push({ method: m, path: p, fingerprintHeader: hdr, recId: b.recId });
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ ...b, id: 'mock-row', createdAt: new Date().toISOString(), entryPrice: 2.2 }) });
      return;
    }
    if (m === 'POST' && p === '/broker/option-order') {
      if (!allowSave) { log.blockedWrites.push({ method: m, path: p }); await route.abort('blockedbyclient'); return; }
      const b = req.postDataJSON();
      log.mockedWrites.push({ method: m, path: p, body: b });
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ order_id: 'MOCK-ORD-1', status: 'Submitted', broker: b.broker, deduped: false }) });
      return;
    }
    log.blockedWrites.push({ method: m, path: p }); await route.abort('blockedbyclient');
  });
  let allowSave = false;

  await page.addInitScript(({ card, other, theme }) => {
    if (sessionStorage.getItem('__seeded')) return; // keep the same storage across any reload
    sessionStorage.setItem('__seeded', '1');
    localStorage.setItem('bamendjou:theme', JSON.stringify({ state: { theme, density: 'Comfortable' }, version: 1 }));
    localStorage.setItem('bamendjou-settings', JSON.stringify({ version: 24, state: { ibkrPaper: { accountId: 'fixture-account' } } }));
    localStorage.setItem('bamendjou-scan-store', JSON.stringify({ version: 17, state: { scanResult: { scan_id: 'final-verification-fixture', timestamp: new Date().toISOString(), candidates: [card, other], rejected: [], contract_rules: {} }, context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)', horizonPreset: 'Swing', holdMin: 5, holdMax: 15 }, scanState: 'COMPLETED', scanAt: new Date().toISOString(), screenerMode: 'options', pickedContracts: {}, contractsBySymbol: {} } }));
  }, { card, other, theme });

  const shot = async (state, locator) => {
    const file = path.join(output, `${tag}-${state}.png`);
    // The app shell scrolls inside a pane, so grow the viewport to the content.
    const needed = await page.evaluate(() => {
      let best = document.documentElement.scrollHeight;
      for (const e of document.querySelectorAll('main, main *, div')) {
        const st = getComputedStyle(e);
        if (/(auto|scroll)/.test(st.overflowY) && e.scrollHeight > e.clientHeight + 4) best = Math.max(best, e.scrollHeight + 160);
      }
      return Math.min(best, 9000);
    });
    await page.setViewportSize({ width, height: Math.max(1000, needed) });
    await page.waitForTimeout(250);
    if (locator) await locator.screenshot({ path: file }); else await page.screenshot({ path: file });
    await page.setViewportSize({ width, height: 1000 });
    await page.waitForTimeout(150);
  };
  const text = async (state) => {
    if (width === 1366 && theme === 'dark') fs.writeFileSync(path.join(output, `${tag}-${state}.txt`), await page.locator('body').innerText());
  };
  const measure = (state) => page.evaluate((state) => {
    const de = document.documentElement;
    const out = { state, pageScrollW: de.scrollWidth, pageClientW: de.clientWidth, horizontalPageOverflow: de.scrollWidth > de.clientWidth + 1, dataTheme: de.getAttribute('data-theme') };
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const cards = [...document.querySelectorAll('[data-method-card]')].filter((c) => !c.hidden);
    const box = (c) => c.firstElementChild; // the slot wrapper itself is display: contents
    out.cards = cards.map((c) => { const r = box(c).getBoundingClientRect(); return { method: c.dataset.methodCard, top: Math.round(r.top), left: Math.round(r.left), width: Math.round(r.width), height: Math.round(r.height) }; });
    const rows = {};
    for (const c of out.cards) (rows[c.top] ??= []).push(c);
    out.cardRows = Object.values(rows).map((row) => row.map((c) => c.method));
    out.rowHeightsEqual = Object.values(rows).every((row) => new Set(row.map((c) => c.height)).size === 1);
    const slots = {};
    for (const c of cards) for (const s of c.querySelectorAll('[data-slot]')) {
      const name = s.dataset.slot; const cardTop = out.cards.find((x) => x.method === c.dataset.methodCard).top;
      (slots[name] ??= []).push({ method: c.dataset.methodCard, row: cardTop, top: Math.round(s.getBoundingClientRect().top) });
    }
    out.slots = slots;
    out.scrollers = [...document.querySelectorAll('div, main, section')].filter((e) => vis(e) && /(auto|scroll)/.test(getComputedStyle(e).overflowX) && e.scrollWidth > e.clientWidth + 1).slice(0, 6).map((e) => `${e.tagName}.${String(e.className).slice(0, 50)} ${e.scrollWidth}>${e.clientWidth}`);
    out.clippedInMethods = [...document.querySelectorAll('[aria-label="Profit-target methods"] *')]
      .filter((e) => vis(e) && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).display !== 'inline')
      .slice(0, 12).map((e) => `${e.tagName}.${String(e.className).slice(0, 60)} ${e.scrollWidth}>${e.clientWidth} ${getComputedStyle(e).overflowX}`);
    out.beyondViewport = [...document.querySelectorAll('main *, [data-presentation] *')]
      .filter((e) => vis(e) && e.getBoundingClientRect().right > de.clientWidth + 1)
      .slice(0, 8).map((e) => `${e.tagName}.${String(e.className).slice(0, 60)}`);
    out.targetRows = [...document.querySelectorAll('[data-target-row]')].filter(vis).map((row) => ({
      method: row.closest('[data-method-card]')?.dataset.methodCard ?? 'other', table: row.tagName === 'TR',
      rowWidth: Math.round(row.getBoundingClientRect().width),
      children: [...row.children].map((c) => Math.round(c.getBoundingClientRect().width)),
    }));
    out.squeezedTargetRows = out.targetRows.filter((r) => !r.table && r.children[0] < 200).length;
    out.mcTableOverflow = [...document.querySelectorAll('table[aria-label="Monte Carlo targets"]')].map((t) => { const c = t.parentElement; return c.scrollWidth > c.clientWidth + 1 || t.getBoundingClientRect().right > t.closest('[aria-label="Monte Carlo Profit Target"]').getBoundingClientRect().right + 1; });
    const editable = [...document.querySelectorAll('[data-editable="true"]')].filter(vis);
    out.editable = { count: editable.length, cursors: [...new Set(editable.map((e) => getComputedStyle(e).cursor))], borderStyles: [...new Set(editable.map((e) => getComputedStyle(e).borderBottomStyle))] };
    out.details = [...document.querySelectorAll('details')].map((d) => ({ summary: d.querySelector('summary')?.textContent ?? '', open: d.open }));
    out.collapsibles = [...document.querySelectorAll('button[aria-expanded]')].filter(vis).map((b) => ({ text: b.textContent.trim().slice(0, 40), expanded: b.getAttribute('aria-expanded') }));
    return out;
  }, state);

  await page.goto(new URL('/screener/step-7-trade-card', baseUrl).href, { timeout: 420000, waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /Run Monte Carlo Estimate/i }).waitFor({ timeout: 240000 });
  await page.waitForTimeout(800);

  const dec = page.getByRole('region', { name: 'Decision and execution', exact: true });
  const review = dec.getByRole('region', { name: 'Selected target review', exact: true });
  const state = () => review.getAttribute('data-review-state');
  const methods = dec.getByRole('radiogroup', { name: 'Exit method for this trade' });
  const rowsGroup = dec.getByRole('radiogroup', { name: 'Target row' });
  const exitValues = async () => (await page.getByRole('region', { name: 'Exit Plan', exact: true }).locator('[data-editable="true"]').allTextContents()).map((s) => s.trim());
  const reviewText = async () => (await review.textContent()).replace(/\s+/g, ' ');

  // initial
  await shot('initial'); log.layout.initial = await measure('initial');
  assert(log.layout.initial.dataTheme === theme, 'requested theme applied');
  assert(await dec.count() === 1, 'one Decision and execution section');
  assert(await page.getByText('Final Recommendation', { exact: true }).count() === 0, 'duplicate Final Recommendation section removed');
  assert(await page.locator('[data-identity="final-status"]').count() === 1 && await page.locator('[data-identity="final-status"]').isVisible(), 'final status shown in identity');
  const order = await page.evaluate(() => ['Exit Plan', 'Profit-target methods', 'Order Entry', 'Decision and execution'].map((n) => { const e = document.querySelector(`[aria-label="${n}"]`); return e ? Math.round(e.getBoundingClientRect().top) : null; }));
  log.readingOrder = order;
  assert(order.every((t) => t != null) && order.every((t, i) => i === 0 || t > order[i - 1]), 'Exit Plan → methods → Order Entry → Decision order');
  assert(await methods.isVisible(), 'method choices inside the decision section');
  assert(await methods.getByRole('radio').count() === 4, 'all four recorded method choices present');
  assert(await dec.getByRole('group', { name: 'Broker execution and auto-trade' }).count() === 1, 'broker execution and auto-trade inside the decision section');
  assert(await page.getByRole('group', { name: 'Broker execution and auto-trade' }).count() === 1, 'execution panel rendered exactly once');
  assert(await dec.locator('a[href="#exit-plan"]').count() === 1, 'one link to the actual Exit Plan from the decision section');
  for (const n of ['Track basket', 'View chart', 'Export JSON']) assert(await dec.getByRole('button', { name: new RegExp(n) }).count() >= 1, `action "${n}" inside the decision section`);
  const st0 = await state(); log.results.push(`initial review state: ${st0}`);
  assert(st0 !== 'selected', 'nothing presented as selected before a choice');
  const exit0 = await exitValues(); log.results.push(`exit plan editable values: ${JSON.stringify(exit0)}`);
  assert(!log.layout.initial.horizontalPageOverflow, 'no initial page overflow');

  // run MC, pick it and a row
  await page.getByRole('button', { name: /Run Monte Carlo Estimate/i }).click();
  await page.getByRole('table', { name: 'Monte Carlo targets' }).waitFor({ timeout: 60000 });
  await page.waitForTimeout(400);
  await methods.getByRole('radio', { name: 'Monte Carlo', exact: true }).click();
  await page.waitForTimeout(200);
  const st1 = await state(); log.results.push(`MC picked, no row: ${st1}`);
  assert(st1 !== 'selected', 'method without a row is not shown as a selected target');
  const rowRadios = rowsGroup.getByRole('radio');
  assert(await rowRadios.count() === 3, 'three MC target rows offered');
  await rowRadios.nth(1).click(); await page.waitForTimeout(250);
  assert(await state() === 'selected', 'MC row selected');
  let t = await reviewText(); log.results.push(`MC T2 review: ${t.slice(0, 400)}`);
  assert(/\$199\.00/.test(t) && /40%/.test(t), 'review shows the selected MC row stock target and its probability');
  assert(JSON.stringify(await exitValues()) === JSON.stringify(exit0), 'choosing a method/row leaves the actual Exit Plan settings unchanged');
  await shot('mc-selected');
  await rowRadios.nth(2).click(); await page.waitForTimeout(250);
  t = await reviewText();
  assert(/\$203\.00/.test(t) && /30%/.test(t) && !/\$199\.00/.test(t), 'changing the row updates the review (no stale row values)');

  // quantity edit
  await page.getByRole('button', { name: 'Edit Contracts', exact: true }).click();
  const qty = page.getByRole('textbox', { name: 'Edit Contracts', exact: true });
  await qty.fill('3'); await qty.press('Enter'); await page.waitForTimeout(250);
  t = await reviewText(); log.results.push(`after quantity 3: ${t.match(/Applicable quantity[^.;]*/)?.[0]}`);
  assert(/3 entered contracts/.test(t), 'quantity edit reflected in the review');

  // Barrier Race pick
  await methods.getByRole('radio', { name: 'Barrier Race', exact: true }).click();
  await rowsGroup.getByRole('radio').first().click(); await page.waitForTimeout(250);
  t = await reviewText(); log.results.push(`race review: ${t.slice(0, 300)}`);
  assert(await state() === 'selected' && /Barrier Race edge per contract/.test(t), 'Barrier Race target reviewed with its edge');
  await shot('race-selected'); await text('race-selected');

  // stale: moving a barrier must not leave race values in the review
  await page.getByRole('button', { name: 'Edit Premium stop', exact: true }).click();
  await page.getByRole('textbox', { name: 'Edit Premium stop', exact: true }).fill('0.8');
  await page.getByRole('textbox', { name: 'Edit Premium stop', exact: true }).press('Enter');
  await page.waitForTimeout(300);
  const stS = await state(); t = await reviewText(); log.results.push(`stale race review state: ${stS}; ${t.slice(0, 300)}`);
  assert(stS !== 'selected' || !/-\$30\.00/.test(t), 'stale race: review does not show the old race edge as current');
  await shot('stale');
  await page.getByRole('button', { name: 'Edit Premium stop', exact: true }).click();
  await page.getByRole('textbox', { name: 'Edit Premium stop', exact: true }).fill('1');
  await page.getByRole('textbox', { name: 'Edit Premium stop', exact: true }).press('Enter');
  await page.waitForTimeout(300);
  const exit1 = await exitValues(); log.results.push(`exit plan after the test's own premium-stop edit: ${JSON.stringify(exit1)}`);

  // Ladder pick, then clear
  await methods.getByRole('radio', { name: 'Ladder', exact: true }).click();
  await rowsGroup.getByRole('radio').first().click(); await page.waitForTimeout(250);
  t = await reviewText(); log.results.push(`ladder review: ${t.slice(0, 300)}`);
  assert(await state() === 'selected' && /\$194\.25/.test(t), 'Ladder target reviewed');
  const clear = dec.getByRole('button', { name: /^Clear/ });
  if (await clear.count()) { await clear.first().click(); await page.waitForTimeout(250); assert(await state() !== 'selected', 'clearing removes the selected review'); }
  assert(JSON.stringify(await exitValues()) === JSON.stringify(exit1), 'Ladder pick and clear leave the Exit Plan settings unchanged');
  log.layout.final = await measure('final');
  assert(!log.layout.final.horizontalPageOverflow, 'no page overflow after picks');

  // restored
  await page.getByRole('button', { name: 'Next candidate', exact: true }).click();
  await page.getByText('Microsoft', { exact: true }).waitFor();
  assert(await page.getByRole('group', { name: 'Broker execution and auto-trade' }).count() === 1, 'execution panel still single after switching candidate');
  await page.getByRole('button', { name: 'Previous candidate', exact: true }).click();
  await page.getByText('Apple Inc.', { exact: true }).waitFor();
  await page.waitForTimeout(300);
  await shot('restored'); await text('restored');
  log.results.push(`restored review state: ${await state()}`);

  assert(log.mockedWrites.length === 0, 'no save or broker order attempted');
  assert(log.blockedWrites.length === 0, 'no unapproved write attempted');
  await context.close();
  return log;
}

(async () => {
  const browser = await chromium.launch({ ...(args.browser ? { executablePath: path.resolve(args.browser) } : {}), headless: true, args: ['--no-sandbox'] });
  const runs = [];
  try {
    for (const width of args.widths.split(',').map(Number)) {
      for (const theme of args.themes.split(',')) {
        process.stdout.write(`run ${width} ${theme}\n`);
        runs.push(await runOne(browser, width, theme));
      }
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify({ states: STATES, baseUrl: baseUrl.href, runs }, null, 1));
  const failed = runs.flatMap((r) => r.pageErrors);
  process.stdout.write(`done: ${runs.length} runs; page errors ${failed.length}\n`);
})().catch((e) => { console.error(e); process.exit(1); });
