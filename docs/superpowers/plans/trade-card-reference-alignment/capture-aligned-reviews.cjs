// #609 concise basket/broker destination reviews acceptance, adapted from #608 capture-decision.cjs.
// Every API call is answered inside the browser's route layer; nothing reaches a
// server. The guard (registered last, so it runs first) rejects every write that
// is not on its allow-list, and answers the allow-listed ones itself.
const fs = require('fs');
const path = require('path');
const args = require('util').parseArgs({ options: {
  'repo-root': { type: 'string' }, output: { type: 'string' },
  'base-url': { type: 'string', default: 'http://127.0.0.1:3098' }, browser: { type: 'string' },
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

const STATES = ['submission', 'basket-review', 'broker-review', 'broker-stale'];

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
  const GROUPS = ['Destination and request', 'Position settings', 'Target alert basis'];
  const checkReview = async (root, label) => {
    for (const g of GROUPS) assert(await root.getByRole('group', { name: g, exact: true }).first().isVisible(), `${label}: "${g}" group visible`);
    const det = root.locator('details[data-review-details]');
    assert(await det.count() >= 1 && await det.first().evaluate((d) => !d.open), `${label}: technical details present and closed`);
    const tops = await Promise.all(GROUPS.map((g) => root.getByRole('group', { name: g, exact: true }).first().evaluate((e) => e.getBoundingClientRect().top)));
    const detTop = await det.first().evaluate((e) => e.getBoundingClientRect().top);
    assert(tops.every((t, i) => i === 0 || t > tops[i - 1]) && detTop > tops[2], `${label}: destination → settings → target, technical details after`);
  };

  // pick a method + row so the review has a recorded choice
  await dec.getByRole('radiogroup', { name: 'Exit method for this trade' }).getByRole('radio', { name: 'Ladder', exact: true }).click();
  await dec.getByRole('radiogroup', { name: 'Target row' }).getByRole('radio').first().click();
  await page.waitForTimeout(300);

  // Submission review (inline)
  const inlineDetails = page.locator('[data-submission-details]');
  assert(await inlineDetails.evaluate(d => !d.open), 'inline submission details closed by default');
  assert(await page.locator('[data-submission-notices]').isVisible(), 'essential submission notices remain outside closed details');
  await inlineDetails.locator('summary').first().click();
  const sub = page.getByRole('region', { name: 'Submission review', exact: true });
  await checkReview(sub, 'submission review');
  assert(await page.getByText(/Final Recommendation/).count() === 0, 'no stale "Final Recommendation" wording');
  assert(await sub.getByText(/No protective stop-loss or take-profit order is sent to a broker/).first().isVisible(), 'submission review: no-protective-order note visible');
  assert(await sub.getByText(/no broker order/i).first().isVisible(), 'submission review: Track basket says no broker order');
  await shot('submission'); await text('submission');
  await sub.locator('details[data-review-details] > summary').first().click(); await page.waitForTimeout(150);
  assert(await sub.getByText(/Draft generation/).first().isVisible(), 'draft generation reachable in technical details');
  await sub.locator('details[data-review-details] > summary').first().click();

  await inlineDetails.locator('summary').first().click();

  // Basket tracking review (dialog) — reviewed by the server mock, never confirmed
  await page.getByRole('button', { name: /pin to basket/i }).first().click();
  await page.getByRole('button', { name: /track basket \(1\)/i }).click();
  const dlg = page.getByRole('dialog', { name: 'Track basket in Portfolio' });
  await dlg.getByText(/Portfolio tracking · no broker order/).first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(300);
  const row = dlg.getByRole('region', { name: /^Server review / }).first();
  await checkReview(row, 'basket review');
  assert(await row.locator('[data-adjusted]').count() >= 1, 'basket review: requested vs server-resolved values kept');
  assert(await dlg.getByText(/No protective stop-loss or take-profit order is sent to a broker/).first().isVisible(), 'basket review: no-protective-order note visible');
  await dlg.screenshot({ path: path.join(output, `${tag}-basket-review.png`) }).catch(() => {});
  await shot('basket-review');
  await dlg.getByRole('button', { name: 'Cancel' }).click(); await page.waitForTimeout(200);

  // Broker order review (direct send preview) — never confirmed
  await page.getByRole('button', { name: /ibkr paper/i }).first().click();
  const lim = page.getByRole('button', { name: /place limit @/i });
  await lim.waitFor(); await page.waitForTimeout(400);
  await lim.click();
  const br = page.getByRole('region', { name: 'Broker order review' });
  await br.waitFor({ timeout: 30000 }); await page.waitForTimeout(300);
  await checkReview(br, 'broker review');
  assert(/Review before sending to/.test(await br.textContent()), 'broker review names the destination');
  assert(await br.getByText(/No stop-loss or take-profit order is sent to the broker/).first().isVisible(), 'broker review: only the opening order goes to the broker');
  assert(await br.getByTestId('broker-request').isHidden(), 'exact broker request JSON inside closed technical details');
  assert(/2026-12-18/.test(await br.getByRole('group', { name: 'Destination and request', exact: true }).textContent()), 'broker review shows the contract expiry');
  await shot('broker-review'); await text('broker-review'); await shot('broker-panel',br);
  // change a reviewed value: the review must go stale and refuse to confirm
  await page.getByRole('button', { name: 'Edit Contracts', exact: true }).click();
  const qty = page.getByRole('textbox', { name: 'Edit Contracts', exact: true });
  await qty.fill('2'); await qty.press('Enter'); await page.waitForTimeout(300);
  assert(await br.getByText(/Changed since this review/).first().isVisible(), 'changed value: stale warning visible');
  const confirm = br.getByRole('button', { name: /^Confirm/ });
  assert(await confirm.count() === 0 || await confirm.first().isDisabled(), 'changed value: confirm refused');
  await shot('broker-stale');
  await br.getByRole('button', { name: 'Cancel' }).click();
  log.layout.final = await measure('final');
  assert(!log.layout.final.horizontalPageOverflow, 'no page overflow');

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
