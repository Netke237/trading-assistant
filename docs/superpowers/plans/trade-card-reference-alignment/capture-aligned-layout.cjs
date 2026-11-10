// #607 Arithmetic/Ladder target tables and two/three-method comparison acceptance, adapted from #606 capture-mc-race.cjs.
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

const STATES = ['initial', 'calculated', 'mc+arithmetic', 'barrier-race', 'selected-target'];

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

  const computeReqs = () => page.evaluate(() => performance.getEntriesByType('resource').filter((r) => /\/first-passage|\/exit-plan/.test(r.name)).length);
  const TABLES = ['Monte Carlo targets', 'Arithmetic targets', 'Ladder targets'];
  const tables = () => page.evaluate((names) => names.map((n) => {
    const t = document.querySelector(`table[aria-label="${n}"]`);
    if (!t || !t.getBoundingClientRect().width) return { name: n, present: false };
    const w = t.parentElement; const card = t.closest('[data-method-card]');
    return { name: n, present: true, heads: [...t.querySelectorAll('thead th')].map((h) => h.textContent.trim()), rows: t.querySelectorAll('tbody tr').length,
      scrolls: w.scrollWidth > w.clientWidth + 1, overflowCard: t.getBoundingClientRect().right > card.firstElementChild.getBoundingClientRect().right + 1 && !(w.scrollWidth > w.clientWidth + 1),
      cardWidth: Math.round(card.firstElementChild.getBoundingClientRect().width) };
  }), TABLES);
  const ORDER = [/^Target/, /^Stock/, /^Option/, /^Probab/, /time/i];
  const checkLayout = async (label) => {
    const m = await measure(label);
    assert(!m.horizontalPageOverflow, `${label}: no horizontal page overflow`);
    assert(m.rowHeightsEqual, `${label}: cards sharing a row have equal height`);
    for (const [name, rows] of Object.entries(m.slots)) {
      const byRow = {}; for (const r of rows) (byRow[r.row] ??= []).push(r.top);
      const offset = Math.max(...Object.values(byRow).map((t) => Math.max(...t) - Math.min(...t)));
      assert(offset <= 8, `${label}: slot ${name} aligned across a row (max offset ${offset}px)`);
    }
    const ts = (await tables()).filter((t) => t.present);
    log.layout[`${label}-tables`] = ts;
    assert(ts.every((t) => !t.overflowCard), `${label}: no target table spills outside its card`);
    log.results.push(`${label}: rows ${JSON.stringify(m.cardRows)}; scrolling tables ${JSON.stringify(ts.filter((t) => t.scrolls).map((t) => `${t.name}@${t.cardWidth}px`))}`);
    return { m, ts };
  };

  assert(await computeReqs() === 0, 'initial load runs no Monte Carlo or Arithmetic calculation');
  const initialLayout = await checkLayout('initial');
  assert(initialLayout.m.cards.length === 1 && initialLayout.m.cards[0].method === 'monte_carlo', 'Monte Carlo alone on initial load');
  assert(initialLayout.m.details.every(d => !d.open), 'initial explanatory details closed');
  const timeBounds = await page.locator('[aria-label="Exit Plan"]').evaluate(section => {
    const e = [...section.querySelectorAll('span')].find(e => /^\d+ days to expiry$/.test(e.textContent.trim()));
    if (!e) throw new Error('Time threshold not found');
    const range = document.createRange(); range.selectNodeContents(e); const rects = [...range.getClientRects()]; const outer=section.getBoundingClientRect();
    return { text:e.textContent, bounds:rects.map(r=>({left:r.left,right:r.right,width:r.width})), section:{left:outer.left,right:outer.right}, visible:rects.every(r=>r.left>=outer.left&&r.right<=outer.right) };
  });
  log.timeBounds=timeBounds; assert(timeBounds.visible, 'complete time-exit threshold fits inside Exit Plan');
  await shot('initial');
  await shot('identity',page.getByRole('region',{name:'Selected stock and contract',exact:true}));
  await shot('exit-plan',page.getByRole('region',{name:'Exit Plan',exact:true}));
  await page.getByRole('button',{name:/Run Monte Carlo Estimate/i}).click();
  await page.getByRole('table',{name:'Monte Carlo targets',exact:true}).waitFor({timeout:60000});
  await shot('monte-carlo',page.locator('[data-method-card="monte_carlo"] > section'));
  const race=page.locator('[data-method-card="monte_carlo"] details').filter({has:page.locator('summary',{hasText:'Barrier Race · graphical outcomes & details'})}).first();
  await race.locator('summary').first().click();
  await shot('barrier-race',race);
  await race.locator('summary').first().click();
  await page.getByRole('checkbox',{name:'Arithmetic',exact:true}).click();
  await page.getByRole('button',{name:/Compute Arithmetic Plan/i}).click();
  await page.getByRole('table',{name:'Arithmetic targets',exact:true}).waitFor({timeout:60000});
  await checkLayout('mc+arithmetic');
  await shot('comparison',page.getByRole('region',{name:'Profit-target methods',exact:true}));
  log.comparisonTables=await page.locator('[data-method-card] table').evaluateAll(ts=>ts.filter(t=>t.getBoundingClientRect().width>0).map(t=>({name:t.getAttribute('aria-label'),tableWidth:Math.round(t.getBoundingClientRect().width),wrapperWidth:t.parentElement.clientWidth,scrolls:t.parentElement.scrollWidth>t.parentElement.clientWidth+1})));
  await page.getByRole('checkbox',{name:'Arithmetic',exact:true}).click();
  const choice=page.getByRole('radio',{name:'Monte Carlo',exact:true});
  if(await choice.count())await choice.check();
  const tp=page.getByRole('radio',{name:'T20%',exact:true});
  if(await tp.count())await tp.check();
  const broker=page.getByRole('button',{name:/^IBKR Paper$/i});
  if(await broker.count())await broker.click();
  await shot('decision',page.getByRole('region',{name:'Decision and execution',exact:true}));
  await shot('calculated');
  const needed=await page.evaluate(()=>Math.min(9000,Math.max(...[...document.querySelectorAll('main,main *,div')].filter(e=>/(auto|scroll)/.test(getComputedStyle(e).overflowY)).map(e=>e.scrollHeight+160),1000)));
  await page.setViewportSize({width,height:needed});await page.waitForTimeout(300);
  const bounds=await page.evaluate(()=>{const b=e=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom}};return{title:b(document.querySelector('h1')),card:b(document.querySelector('[data-presentation="options-v2"]')),methods:b(document.querySelector('[aria-label="Profit-target methods"]')),decision:b(document.querySelector('[aria-label="Decision and execution"]'))}});
  const x=Math.floor(bounds.card.x),w=Math.ceil(bounds.card.width);
  const spans=[['part1-top',Math.max(0,bounds.title.y-12),bounds.methods.y-12],['part2-methods-entry',bounds.methods.y,bounds.decision.y-12],['part3-decision',bounds.decision.y,bounds.card.bottom+8]];
  for(const[name,y,end]of spans)await page.screenshot({path:path.join(output,`${tag}-${name}.png`),clip:{x,y:Math.floor(y),width:w,height:Math.ceil(end-y)}});
  log.sectionBounds=bounds;
  log.captureRevision=require('child_process').execFileSync('git',['rev-parse','HEAD'],{cwd:repoRoot,encoding:'utf8'}).trim();log.scope='Approved remaining preview layout; source frozen, no real writes';
  log.layout.current=await measure('current');
  log.previewPanels=await page.evaluate(()=>[...document.querySelectorAll('[data-selected-target-review],[aria-label="Entry & position size"],[data-decision-part="actions"]')].map(e=>({label:e.getAttribute('aria-label')||e.dataset.decisionPart,top:e.getBoundingClientRect().top,height:e.getBoundingClientRect().height})));
  log.disclosureDefaults=await page.locator('[data-recorded-decision-details],[data-submission-details],[data-size-details],[data-execution-details],[data-race-assumptions]').evaluateAll(es=>es.map(e=>({summary:e.querySelector('summary')?.textContent,open:e.open})));

  assert(log.disclosureDefaults.every(d=>!d.open), 'record, size, submission, execution and race assumptions default closed');
  if(log.pageErrors.length)throw new Error(JSON.stringify(log.pageErrors));
  if(log.mockedWrites.length||log.blockedWrites.length)throw new Error('Unexpected save/order attempt');
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
