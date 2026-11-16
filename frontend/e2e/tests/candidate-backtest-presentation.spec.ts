import { test, expect, type Page, type Locator } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { setupApiMocks } from '../fixtures/api-mocks';

/*
 * Integrated presentation of the recorded backtest report (BACKTEST-REVIEW-VISUALISATION T5).
 * Manual suite, skipped unless BACKTEST_BROWSER_FIXTURES points at the recorded-engine fixture file
 * (docs/superpowers/plans/backtest-review-visualisation/fixtures/recorded-engine.json).
 *
 * Every expected number below is read from the artifact served to the page, never hardcoded: the
 * display contract (index - 100 for Return %, raw index for Index 100, two-decimal display rounding)
 * is restated here and applied to the recorded values. Only fixture API routes are intercepted;
 * any other /api request and the live quote websocket are blocked so no real broker/data service
 * is exercised. Optional BACKTEST_EVIDENCE_DIR also writes the representative screenshots there.
 */
const fixturePath = process.env.BACKTEST_BROWSER_FIXTURES;
const fixtures = fixturePath ? JSON.parse(fs.readFileSync(fixturePath, 'utf8')) : null;
const evidenceDir = process.env.BACKTEST_EVIDENCE_DIR;
test.skip(!fixtures, 'Manual integration suite: generate engine fixtures and set BACKTEST_BROWSER_FIXTURES.');

type Artifact = any;
type Theme = 'dark' | 'light';
type Unit = 'percent' | 'index';
const PRICE = 'Historical candles', PERFORMANCE = 'Indexed equity comparison', DRAWDOWN = 'Sampled strategy drawdown';
const SUMMARY = 'Full-period performance summary';
const BENCHMARK = 'Long buy-and-hold (gross; excludes fees)';

// --- display contract restated over recorded values ---
const fixed = (v: number | null | undefined) => v != null && Number.isFinite(v) ? v.toFixed(2) : 'Unavailable';
const signed = (v: number) => {const t = fixed(v); return t !== 'Unavailable' && v > 0 ? `+${t}` : t;};
const pct = (v: number) => {const t = signed(v); return t === 'Unavailable' ? t : `${t}%`;};
const plainPct = (v: number) => {const t = fixed(v); return t === 'Unavailable' ? t : `${t}%`;};
const iso = (t: number) => new Date(t * 1000).toISOString();
const minute = (t: number) => iso(t).slice(0, 16).replace('T', ' ');
const json = <T>(v: T): T => JSON.parse(JSON.stringify(v));
const finalRow = (a: Artifact) => a.detail.equity.at(-1);
const curve = (row: any, key: 'strategy_index' | 'benchmark_index', unit: Unit) => unit === 'percent' ? pct(row[key] - 100) : fixed(row[key]);
const expectedCards = (a: Artifact) => {
 const s = a.detail.summary, last = finalRow(a);
 return [
  ['Strategy return (engine)', pct(s.total_return_pct)],
  ['Buy & hold return', pct(last.benchmark_index - 100)],
  ['Strategy minus holding', signed(last.strategy_index - last.benchmark_index)],
  ['Engine max drawdown', plainPct(s.max_drawdown_pct)],
  ['Winning closed trades', plainPct(s.win_rate * 100)],
  ['Closed trades', String(s.n_trades)],
 ];
};
const recordedBounds = (a: Artifact) => {
 const times = [...a.detail.candles, ...a.detail.equity].map((r: any) => r.time);
 return {from: Math.min(...times), to: Math.max(...times)};
};
const exitLabel = (reason: string) => reason === 'time' ? 'Time exit (holding limit)' : 'Unknown (not recorded by engine)';

// --- harness ---
interface Harness {writes: string[]; freshCalls: string[]; artifactReads: number; blocked: string[]; served: Artifact; pristine: Artifact}
/** Blocks every /api request no fixture route answers, and the live quote stream. */
async function isolate(page: Page, blocked: string[]) {
 await page.route(url => url.pathname.startsWith('/api/'), route => {blocked.push(new URL(route.request().url()).pathname); return route.abort('blockedbyclient');});
 await page.routeWebSocket(/\/chart\/stream\//, ws => {ws.close();});
}
async function prepare(page: Page, theme: Theme, width: number, height = 1000) {
 await page.setViewportSize({width, height});
 await page.addInitScript(t => localStorage.setItem('bamendjou:theme', JSON.stringify({state: {theme: t}, version: 0})), theme);
 const blocked: string[] = [];
 await isolate(page, blocked);
 await setupApiMocks(page);
 return blocked;
}
function track(page: Page, h: Pick<Harness, 'writes' | 'freshCalls'>) {
 page.on('request', request => {
  const url = new URL(request.url());
  if (!url.pathname.startsWith('/api/')) return;
  if (request.method() !== 'GET') h.writes.push(`${request.method()} ${url.pathname}`);
  if (url.pathname.includes('/backtest-artifacts/fresh')) h.freshCalls.push(`${request.method()} ${url.pathname}`);
 });
}
const reportUrl = (a: Artifact) => `/chart?symbol=${a.identity.symbol}&source=stocks&backtest_artifact_status=available&backtest_artifact_id=${a.artifact_id}`;
async function openReport(page: Page, artifact: Artifact, theme: Theme, width: number): Promise<Harness> {
 const blocked = await prepare(page, theme, width);
 const h: Harness = {writes: [], freshCalls: [], artifactReads: 0, blocked, served: artifact, pristine: structuredClone(artifact)};
 track(page, h);
 await page.route('**/api/backtest-artifacts/**', async route => {h.artifactReads++; await route.fulfill({json: h.served});});
 await page.goto(reportUrl(artifact));
 await expect(page.getByLabel(PERFORMANCE, {exact: true})).toBeVisible();
 await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
 return h;
}

// --- readers ---
const readCards = (page: Page) => page.getByLabel(SUMMARY, {exact: true}).evaluate(el => [...el.children].map(card => [card.children[0]?.textContent ?? '', card.children[1]?.textContent ?? '']));
/** The supporting disclosure's recorded JSON blocks and provenance line, parsed from the rendered page. */
const readRecorded = (page: Page) => page.locator('details').filter({has: page.locator('summary', {hasText: 'Recorded configuration and provenance'})}).evaluate(el => {
 const block = (title: string) => {const h = [...el.querySelectorAll('h3')].find(x => x.textContent === title); return JSON.parse(h?.nextElementSibling?.textContent ?? 'null');};
 return {provenance: el.querySelector('p')?.textContent, configuration: block('Full recorded engine configuration'), effective_params: block('Effective strategy parameters'), identity: block('Run identity'), summary: block('Recorded summary')};
});
const expectedRecorded = (a: Artifact) => json({
 provenance: `Provenance: ${a.provenance} · Artifact ${a.artifact_id} · Run ${a.identity.scan_id} · Created ${iso(a.created_at)}`,
 configuration: a.detail.configuration, effective_params: a.detail.effective_params, identity: a.identity, summary: a.detail.summary,
});
async function expectReportMatches(page: Page, a: Artifact) {
 expect(await readCards(page)).toEqual(expectedCards(a));
 expect(await readRecorded(page)).toEqual(expectedRecorded(a));
}
const legendBox = (page: Page) => page.locator('label', {has: page.getByRole('checkbox', {name: /^Strategy equity/})}).locator('..');
const readout = (page: Page) => legendBox(page).evaluate(el => el.lastElementChild?.textContent ?? '');
async function expectLegend(page: Page, row: any, unit: Unit) {
 await expect(page.getByRole('checkbox', {name: `Strategy equity ${curve(row, 'strategy_index', unit)}`, exact: true})).toBeVisible();
 await expect(page.getByRole('checkbox', {name: `${BENCHMARK} ${curve(row, 'benchmark_index', unit)}`, exact: true})).toBeVisible();
}
/** Crosshair readout: hover the performance pane, then compare the legend to the exact recorded sample at the hovered time. */
async function expectCrosshairReadout(page: Page, a: Artifact, unit: Unit) {
 const box = (await page.getByLabel(PERFORMANCE, {exact: true}).boundingBox())!;
 await page.mouse.move(box.x + 5, box.y + box.height / 2);
 await page.mouse.move(box.x + box.width * 0.45, box.y + box.height / 2, {steps: 8});
 await expect.poll(() => readout(page)).not.toMatch(/^Period end/);
 const text = await readout(page);
 const time = Date.parse(text.split(' · ')[0]) / 1000;
 const row = a.detail.equity.find((r: any) => r.time === time);
 expect(row, `hovered ${text} must be an exact recorded equity timestamp`).toBeTruthy();
 expect(text).toBe(iso(time));
 await expectLegend(page, row, unit);
 await page.mouse.move(2, 2);
 await expect.poll(() => readout(page)).toBe(`Period end · ${iso(finalRow(a).time)}`);
}
const pane = (page: Page, label: string) => page.getByLabel(label, {exact: true});
const shot = (locator: Locator) => locator.screenshot({animations: 'disabled'});
const noHorizontalScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
const caption = (page: Page) => page.getByText(/Baseline is unchanged; summary cards describe the full period\./);
async function evidence(page: Page, name: string, scrollTo?: Locator) {
 if (scrollTo) await scrollTo.scrollIntoViewIfNeeded(); else await page.evaluate(() => window.scrollTo(0, 0));
 await page.mouse.move(2, 2);
 const file = test.info().outputPath(`${name}.png`);
 await page.screenshot({path: file, animations: 'disabled'});
 if (evidenceDir) {fs.mkdirSync(evidenceDir, {recursive: true}); fs.copyFileSync(file, path.join(evidenceDir, `${name}.png`));}
}
const keepEvidence = (theme: Theme, width: number) => (width === 1366 && theme === 'dark') || (width === 1920 && theme === 'light');

// Directions/intervals rotate across widths so daily, intraday and the Bearish long benchmark are all covered.
const MATRIX: {width: number; key: string}[] = [{width: 1280, key: 'Bearish-15m'}, {width: 1366, key: 'Bullish-1d'}, {width: 1920, key: 'Bearish-1d'}];
for (const theme of ['dark', 'light'] as Theme[]) for (const {width, key} of MATRIX) {
 test(`${key} ${theme} ${width}: display controls are local and the recorded report is unchanged`, async ({page}) => {
  test.setTimeout(180_000);
  const a = fixtures[key];
  const h = await openReport(page, a, theme, width);
  const last = finalRow(a);
  // Recorded identity and full-period summary first.
  await expect(page.getByRole('heading', {name: `${a.identity.symbol} — Original backtest`, exact: true})).toBeVisible();
  await expect(page.getByText(`Recorded period ${minute(a.detail.candles[0].time)} → ${minute(a.detail.candles.at(-1).time)} UTC`, {exact: false})).toBeVisible();
  await expectReportMatches(page, a);
  // Frozen-data meaning, evaluation period and cost basis come from the recorded detail.
  await expect(page.getByText(`Frozen historical evidence. Live overlays are separate. Time basis: ${a.detail.time_basis}.`, {exact: true})).toBeVisible();
  await expect(page.getByText(`Evaluation: ${iso(a.detail.candles[0].time)} — ${iso(a.detail.candles.at(-1).time)}.`, {exact: true})).toBeAttached();
  await expect(page.getByText(`Strategy commission: ${a.detail.configuration.commission} (${a.detail.configuration.commission_basis}). Benchmark is gross and excludes fees. Currency was not recorded.`, {exact: true})).toBeAttached();
  await expect(page.getByRole('button', {name: 'Return %', exact: true})).toHaveAttribute('aria-pressed', 'true');
  await expectLegend(page, last, 'percent');
  expect(await readout(page)).toBe(`Period end · ${iso(last.time)}`);
  await expect(page.getByText('Cumulative return (%) · recorded baseline of 100 shown as 0%', {exact: true})).toBeVisible();
  await expect(page.getByText(`Recorded strategy equity returned ${pct(last.strategy_index - 100)}; long buy-and-hold returned ${pct(last.benchmark_index - 100)}; difference ${signed(last.strategy_index - last.benchmark_index)} percentage points over the full recorded period.`, {exact: false})).toBeVisible();
  // The benchmark is the recorded LONG buy-and-hold for either direction.
  await expect(page.getByRole('checkbox', {name: new RegExp(`^${BENCHMARK.replace(/[()]/g, '\\$&')}`)})).toBeChecked();
  expect(await noHorizontalScroll(page)).toBe(true);
  if (keepEvidence(theme, width)) await evidence(page, `report-default-${width}-${theme}`);
  await expectCrosshairReadout(page, a, 'percent');

  // Return % <-> Index 100: index - 100 versus the raw recorded index, same timestamps.
  await page.getByRole('button', {name: 'Index 100', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Index 100', exact: true})).toHaveAttribute('aria-pressed', 'true');
  await expectLegend(page, last, 'index');
  await expect(page.getByText('Equity index · recorded baseline is 100', {exact: true})).toBeVisible();
  await expectCrosshairReadout(page, a, 'index');
  if (keepEvidence(theme, width)) await evidence(page, `index100-${width}-${theme}`, page.getByRole('heading', {name: 'Strategy versus buying & holding'}));
  await page.getByRole('button', {name: 'Return %', exact: true}).click();
  await expectLegend(page, last, 'percent');

  // Last year / All history change only the display bounds; the full-period cards stay.
  await page.getByRole('button', {name: 'Last year', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Last year', exact: true})).toHaveAttribute('aria-pressed', 'true');
  await expect(caption(page)).toContainText(`Showing the last UTC calendar year to ${iso(recordedBounds(a).to)}.`);
  expect(await readCards(page)).toEqual(expectedCards(a));
  await expectLegend(page, last, 'percent');
  await page.getByRole('button', {name: 'All history', exact: true}).click();
  await expect(caption(page)).toContainText('Showing all recorded history.');

  // Expand / reduce the performance chart in place.
  const height = async () => (await pane(page, PERFORMANCE).boundingBox())!.height;
  const normal = await height();
  await page.getByRole('button', {name: 'Expand chart', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Reduce chart', exact: true})).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(height).toBeGreaterThan(normal + 100);
  expect(await noHorizontalScroll(page)).toBe(true);
  await page.getByRole('button', {name: 'Reduce chart', exact: true}).click();
  await expect.poll(height).toBeCloseTo(normal, 0);

  // Hiding each and both series; both hidden gives guidance; nothing else changes.
  const strategyBox = page.getByRole('checkbox', {name: /^Strategy equity/});
  const benchmarkBox = page.getByRole('checkbox', {name: new RegExp(`^${BENCHMARK.replace(/[()]/g, '\\$&')}`)});
  const guidance = page.getByText('Both curves are hidden. Select a series above to display it.', {exact: true});
  await page.mouse.move(2, 2);
  const bothShown = await shot(pane(page, PERFORMANCE));
  await strategyBox.uncheck();
  await expect(guidance).toHaveCount(0);
  await expect.poll(async () => (await shot(pane(page, PERFORMANCE))).equals(bothShown)).toBe(false);
  await benchmarkBox.uncheck();
  await expect(guidance).toBeVisible();
  await strategyBox.check();
  await expect(guidance).toHaveCount(0);
  await benchmarkBox.check();
  await expect.poll(async () => (await shot(pane(page, PERFORMANCE))).equals(bothShown)).toBe(true);
  await expectLegend(page, last, 'percent');

  // Candles / OHLC bars / Line replace the price series without adding chart instances.
  const canvases = () => pane(page, PRICE).locator('canvas').count();
  const canvasCount = await canvases();
  for (const label of ['OHLC bars', 'Line', 'Candles']) {
   await page.getByRole('button', {name: label, exact: true}).click();
   await expect(page.getByRole('button', {name: label, exact: true})).toHaveAttribute('aria-pressed', 'true');
   expect(await canvases()).toBe(canvasCount);
  }

  // Trade markers toggle draws/removes the markers only.
  await page.mouse.move(2, 2);
  const withMarkers = await shot(pane(page, PRICE));
  const markers = page.getByRole('checkbox', {name: 'Trade markers', exact: true});
  await markers.uncheck();
  await expect.poll(async () => (await shot(pane(page, PRICE))).equals(withMarkers)).toBe(false);
  await markers.check();
  await expect.poll(async () => (await shot(pane(page, PRICE))).equals(withMarkers)).toBe(true);

  // Keyboard Inspect zooms every pane to the trade; Escape restores each pane exactly.
  const trade = a.detail.trades[0];
  const panes = [PRICE, PERFORMANCE, DRAWDOWN];
  await page.mouse.move(2, 2);
  const before = await Promise.all(panes.map(label => shot(pane(page, label))));
  const inspect = page.getByRole('button', {name: `Inspect trade ${trade.id}`, exact: true});
  await inspect.focus();
  await page.keyboard.press('Enter');
  const inspector = page.getByLabel('Trade inspector', {exact: true});
  await expect(inspector).toBeVisible();
  for (const value of [trade.direction, iso(trade.entry_time), String(trade.entry_price), iso(trade.exit_time), String(trade.exit_price), exitLabel(trade.exit_reason), String(trade.net_return_pct), String(trade.size), String(trade.commission)]) await expect(inspector).toContainText(value);
  await expect(caption(page)).toContainText('Showing the selected trade and surrounding dates.');
  await expect(page.getByRole('button', {name: `Inspect trade ${trade.id}`, exact: true}).locator('xpath=ancestor::tr')).toHaveAttribute('aria-current', 'true');
  for (const [i, label] of panes.entries()) await expect.poll(async () => (await shot(pane(page, label))).equals(before[i]), {message: `${label} zoomed`}).toBe(false);
  expect(await noHorizontalScroll(page)).toBe(true);
  await page.keyboard.press('Escape');
  await expect(inspector).toHaveCount(0);
  await expect(inspect).toBeFocused();
  await expect(caption(page)).toContainText('Showing all recorded history.');
  for (const [i, label] of panes.entries()) await expect.poll(async () => (await shot(pane(page, label))).equals(before[i]), {message: `${label} restored`}).toBe(true);
  // The Clear selection button is the pointer equivalent.
  await inspect.click();
  await expect(inspector).toBeVisible();
  await page.getByRole('button', {name: 'Clear selection', exact: true}).click();
  await expect(inspector).toHaveCount(0);

  // Representative evidence: Line style with an inspected trade.
  if (keepEvidence(theme, width)) {
   await page.getByRole('button', {name: 'Line', exact: true}).click();
   await inspect.click();
   await expect(inspector).toBeVisible();
   await evidence(page, `line-inspected-${width}-${theme}`, page.getByRole('heading', {name: 'Where did the strategy enter and exit?'}));
   await page.keyboard.press('Escape');
  }

  // After every interaction: same summary, same recorded blocks, untouched served artifact, one read, no writes.
  await expectReportMatches(page, a);
  expect(h.served).toEqual(h.pristine);
  expect(h.artifactReads).toBe(1);
  expect(h.writes).toEqual([]);
  expect(h.freshCalls).toEqual([]);
 });
}

/**
 * Display-only derived fixture: the recorded Bullish-1d artifact with its two recorded trades repeated at
 * later exact candle timestamps (new ids), one off-candle exit and one open position. It exercises
 * pagination, sorting and the open-position/off-candle disclosures that the small engine fixture lacks.
 * It is not engine output and never enters application code; its summary stays the recorded one.
 */
function derivedReview(base: Artifact): Artifact {
 const a = structuredClone(base);
 a.artifact_id = '0f0f0f0f-0000-4000-8000-00000000d0e1';
 const candles = a.detail.candles;
 a.detail.trades = Array.from({length: 8}, (_, n) => {
  const template = base.detail.trades[n % base.detail.trades.length];
  return {...template, id: `derived-${n}`, entry_time: candles[10 + 15 * n].time, exit_time: candles[12 + 15 * n].time};
 });
 a.detail.trades[3].exit_time += 3600; // off-candle exit: recorded, never snapped
 const opened = candles[140];
 a.detail.open_positions = [{id: 'open-derived', direction: base.identity.direction, entry_time: opened.time, entry_price: opened.close, size: base.detail.trades[0].size, unrealized_pnl: 123.45}];
 return a;
}

test('derived review: sorting and pagination keep the selected trade; open position and off-candle fill stay truthful', async ({page}) => {
 test.setTimeout(120_000);
 const a = derivedReview(fixtures['Bullish-1d']);
 const h = await openReport(page, a, 'dark', 1366);
 await expectReportMatches(page, a);
 const table = page.getByRole('table', {name: 'Closed trades'});
 await expect(page.getByText(`1–6 of ${a.detail.trades.length} trades`, {exact: true})).toBeVisible();
 // Oldest first: the last trade sits on page 2.
 const lastTrade = a.detail.trades.at(-1);
 await expect(table.getByRole('button', {name: `Inspect trade ${lastTrade.id}`})).toHaveCount(0);
 await page.getByRole('button', {name: 'Page 2', exact: true}).click();
 const inspectLast = table.getByRole('button', {name: `Inspect trade ${lastTrade.id}`, exact: true});
 await inspectLast.focus();
 await page.keyboard.press('Enter');
 const inspector = page.getByLabel('Trade inspector', {exact: true});
 await expect(inspector).toContainText(`Trade ${lastTrade.id}`);
 // Newest first moves the selected trade to page 1 and keeps it selected.
 await page.getByLabel('Order', {exact: true}).selectOption('newest');
 await expect(page.getByText(`1–6 of ${a.detail.trades.length} trades`, {exact: true})).toBeVisible();
 await expect(table.getByRole('button', {name: `Inspect trade ${lastTrade.id}`, exact: true}).locator('xpath=ancestor::tr')).toHaveAttribute('aria-current', 'true');
 await expect(table.locator('tbody tr').first()).toContainText(`Trade #${lastTrade.id}`);
 // Paging away keeps the inspector on the selected trade.
 await page.getByRole('button', {name: 'Page 2', exact: true}).click();
 await expect(table.getByRole('button', {name: `Inspect trade ${lastTrade.id}`})).toHaveCount(0);
 await expect(inspector).toContainText(`Trade ${lastTrade.id}`);
 // Lowest net return first is stable by id for equal recorded returns; the selection still holds.
 await page.getByLabel('Order', {exact: true}).selectOption('worst');
 await expect(table.getByRole('button', {name: `Inspect trade ${lastTrade.id}`, exact: true}).locator('xpath=ancestor::tr')).toHaveAttribute('aria-current', 'true');
 await expect(inspector).toContainText(`Trade ${lastTrade.id}`);
 await page.keyboard.press('Escape');
 // Off-candle exit: recorded timestamp shown, not marked, explained.
 const offCandle = a.detail.trades[3];
 await page.getByLabel('Order', {exact: true}).selectOption('oldest');
 await page.getByRole('button', {name: 'Page 1', exact: true}).click();
 await table.getByRole('button', {name: `Inspect trade ${offCandle.id}`, exact: true}).click();
 await expect(inspector).toContainText(iso(offCandle.exit_time));
 await expect(inspector).toContainText('Not marked: no candle has this exact timestamp');
 await expect(page.getByText(/Some fills have no exact original candle timestamp/)).toBeVisible();
 // Open position: listed with its recorded values, never a closed-trade row or an invented exit.
 const open = a.detail.open_positions[0];
 await expect(page.getByText(`${open.id} · ${open.direction} · Entry ${iso(open.entry_time)} @ ${open.entry_price} · Size ${open.size} · Unrealized P&L ${open.unrealized_pnl}`, {exact: true})).toBeVisible();
 await expect(page.getByRole('button', {name: `Inspect trade ${open.id}`})).toHaveCount(0);
 await expect(page.getByText('Equity includes mark-to-market of open positions; closed-trade counts exclude them. No exit is assumed.', {exact: true})).toBeVisible();
 expect(await noHorizontalScroll(page)).toBe(true);
 await expectReportMatches(page, a);
 expect(h.served).toEqual(h.pristine);
 expect(h.artifactReads).toBe(1);
 expect(h.writes).toEqual([]);
});

test('zero-trade recorded result keeps curves and summary, with no fabricated rows or pagination', async ({page}) => {
 const a = fixtures.zero;
 const h = await openReport(page, a, 'light', 1366);
 await expectReportMatches(page, a);
 await expect(page.getByText('Successful result: zero closed trades. The recorded equity and benchmark remain visible.', {exact: true})).toBeVisible();
 await expect(page.getByText('No closed trades recorded for this run.', {exact: true})).toBeVisible();
 await expect(page.getByRole('navigation', {name: 'Pagination'})).toHaveCount(0);
 await expect(page.getByText('No recorded open positions.', {exact: true})).toBeVisible();
 await expectLegend(page, finalRow(a), 'percent');
 await page.getByRole('button', {name: 'Index 100', exact: true}).click();
 await expectLegend(page, finalRow(a), 'index');
 await page.getByRole('button', {name: 'Line', exact: true}).click();
 await page.getByRole('button', {name: 'Last year', exact: true}).click();
 await expectReportMatches(page, a);
 expect(h.served).toEqual(h.pristine);
 expect(h.artifactReads).toBe(1);
 expect(h.writes).toEqual([]);
});

const NO_REPORT = [PRICE, PERFORMANCE, DRAWDOWN, SUMMARY, 'Trade inspector'];
async function expectUnavailable(page: Page, reason: string) {
 await expect(page.getByRole('status').filter({hasText: 'Original backtest unavailable'})).toContainText(`Original backtest unavailable: ${reason} (`);
 await expect(page.getByText('no historical result has been substituted', {exact: false})).toBeVisible();
 await expect(page.getByText('No original result', {exact: true})).toBeVisible();
 for (const label of NO_REPORT) await expect(page.getByLabel(label, {exact: true})).toHaveCount(0);
 await expect(page.getByRole('heading', {name: /Original backtest$/})).toHaveCount(0);
}

test('every unavailable reason is disclosed and no recorded curve is substituted', async ({page}) => {
 test.setTimeout(180_000);
 const blocked = await prepare(page, 'dark', 1366);
 const h = {writes: [] as string[], freshCalls: [] as string[]};
 track(page, h);
 // Reasons carried by the candidate route itself, across every screener source.
 const routed: [string, string][] = [['fib', 'unsupported'], ['prebreakout', 'unsupported'], ['pullback', 'unsupported'], ['stocks', 'insufficient_history'], ['stocks', 'capture_unavailable'], ['stocks', 'original_unavailable'], ['stocks', 'storage_unavailable'], ['stocks', 'invalid_input'], ['stocks', 'failed'], ['stocks', 'invalid_evidence']];
 for (const [source, status] of routed) {
  await page.goto(`/chart?symbol=AAA&source=${source}&backtest_artifact_status=${status}`);
  await expectUnavailable(page, status);
 }
 // Reasons only the artifact read can reveal: HTTP status, and evidence that fails the identity check.
 const a = fixtures['Bullish-1d'];
 let reply: (route: any) => Promise<void> = async () => {};
 await page.route('**/api/backtest-artifacts/**', route => reply(route));
 const replies: [string, (route: any) => Promise<void>][] = [
  ['missing', route => route.fulfill({status: 404, json: {detail: 'missing'}})],
  ['expired', route => route.fulfill({status: 410, json: {detail: 'expired'}})],
  ['storage_unavailable', route => route.fulfill({status: 503, json: {detail: 'storage'}})],
  ['invalid_input', route => route.fulfill({status: 422, json: {detail: 'invalid'}})],
  ['failed', route => route.fulfill({status: 500, json: {detail: 'failed'}})],
  ['invalid_evidence', route => route.fulfill({json: {...a, provenance: 'fresh'}})],
  ['invalid_evidence', route => route.fulfill({json: {...a, identity: {...a.identity, symbol: 'BBB'}}})],
  ['invalid_evidence', route => route.fulfill({json: {...a, detail: {...a.detail, status: 'failed'}}})],
 ];
 for (const [i, [reason, respond]] of replies.entries()) {
  reply = respond;
  await page.goto(reportUrl(a));
  await expectUnavailable(page, reason);
  if (i === 1) await evidence(page, 'unavailable-expired-1366-dark');
 }
 // A route whose artifact symbol differs from the candidate symbol never shows the report either.
 expect(h.writes).toEqual([]);
 expect(h.freshCalls).toEqual([]);
 expect(blocked.filter(p => p.includes('backtest'))).toEqual([]);
});

test('unavailable state at 1920 light keeps the labelled live fallback only', async ({page}) => {
 await prepare(page, 'light', 1920);
 await page.goto('/chart?symbol=AAA&source=fib&backtest_artifact_status=unsupported');
 await expectUnavailable(page, 'unsupported');
 await expect(page.getByText('Pre-Breakout screener · fib / Backtest review / AAA', {exact: true})).toBeVisible();
 expect(await noHorizontalScroll(page)).toBe(true);
 await evidence(page, 'unavailable-unsupported-1920-light');
});

for (const [theme, width] of [['light', 1366], ['dark', 1920]] as [Theme, number][]) {
 test(`fresh result ${theme} ${width}: display controls stay local and each result keeps its identity`, async ({page}) => {
  test.setTimeout(120_000);
  const blocked = await prepare(page, theme, width);
  const original = fixtures['Bearish-1d'], fresh = fixtures.fresh;
  const pristine = structuredClone({original, fresh});
  const h = {writes: [] as string[], freshCalls: [] as string[]};
  track(page, h);
  let originalReads = 0;
  await page.route('**/api/backtest-artifacts/**', async route => {
   const p = new URL(route.request().url()).pathname;
   if (p.endsWith('/fresh/configuration')) return route.fulfill({json: {strategies: ['pullback_ema'], parameters: {pullback_ema: {ema_period: 'int'}}, multi_fields: []}});
   if (p.endsWith('/fresh')) return route.fulfill({json: {status: 'success', artifact: fresh}});
   originalReads++;
   return route.fulfill({json: original});
  });
  await page.goto(reportUrl(original));
  await expect(page.getByLabel(PRICE, {exact: true})).toBeVisible();
  await expectReportMatches(page, original);
  await page.getByRole('button', {name: 'Separate fresh run', exact: true}).click();
  await page.getByLabel('Evaluation start', {exact: true}).fill('2024-04-20');
  await page.getByLabel('Evaluation end (exclusive)', {exact: true}).fill('2024-05-30');
  await page.getByLabel('Commission per leg (fraction)', {exact: true}).fill('0.002');
  await page.getByLabel('Maximum hold days (null for none)', {exact: true}).fill('10');
  await page.getByLabel('Minimum closed trades', {exact: true}).fill('5');
  await page.getByLabel('Minimum win rate (fraction)', {exact: true}).fill('0.5');
  await page.getByLabel('Complete strategy parameters (JSON)', {exact: true}).fill(JSON.stringify(fresh.detail.effective_params));
  await page.getByLabel(/I reviewed the strategy/).check();
  await page.getByRole('button', {name: 'Run fresh backtest', exact: true}).click();
  await expect(page.getByRole('heading', {name: `${fresh.identity.symbol} — Fresh backtest (separate result)`, exact: true})).toBeVisible();
  await expect(page.getByText('Fresh run', {exact: true})).toBeVisible();
  await expectReportMatches(page, fresh);
  const writesAfterRun = [...h.writes];
  expect(writesAfterRun).toEqual(['POST /api/backtest-artifacts/fresh']);
  // Display controls on the fresh result: no further calls of any kind.
  await page.getByRole('button', {name: 'Separate fresh run', exact: true}).click(); // close the configuration
  await page.getByRole('button', {name: 'Index 100', exact: true}).click();
  await expectLegend(page, finalRow(fresh), 'index');
  await page.getByRole('button', {name: 'Line', exact: true}).click();
  await page.getByRole('checkbox', {name: 'Trade markers', exact: true}).uncheck();
  await page.getByRole('checkbox', {name: 'Trade markers', exact: true}).check();
  await page.getByRole('button', {name: `Inspect trade ${fresh.detail.trades[0].id}`, exact: true}).click();
  await expect(page.getByLabel('Trade inspector', {exact: true})).toContainText(String(fresh.detail.trades[0].net_return_pct));
  expect(await noHorizontalScroll(page)).toBe(true);
  await evidence(page, `fresh-shown-${width}-${theme}`);
  await page.keyboard.press('Escape');
  // Switching results keeps each identity and its own recorded values.
  await page.getByRole('button', {name: 'Show original backtest', exact: true}).click();
  await expect(page.getByRole('heading', {name: `${original.identity.symbol} — Original backtest`, exact: true})).toBeVisible();
  await expectReportMatches(page, original);
  await page.getByRole('button', {name: 'Show fresh backtest', exact: true}).click();
  await expectReportMatches(page, fresh);
  expect(h.writes).toEqual(writesAfterRun);
  expect(originalReads).toBe(1);
  expect({original, fresh}).toEqual(pristine);
  expect(blocked.filter(p => p.includes('backtest'))).toEqual([]);
 });
}

test('/chart keeps the 1280px desktop gate: 1200px shows the overlay, not a usable chart claim', async ({page}) => {
 const a = fixtures['Bullish-1d'];
 await openReport(page, a, 'dark', 1200);
 const gate = page.getByRole('dialog', {name: 'Desktop required'});
 await expect(gate).toBeVisible();
 await expect(gate).toContainText('1280');
 await expect(gate).toContainText('Current width: 1200');
 await evidence(page, 'min-width-gate-1200-dark');
 await page.setViewportSize({width: 1280, height: 1000});
 await expect(gate).toHaveCount(0);
 await expect(page.getByLabel(PERFORMANCE, {exact: true})).toBeVisible();
});

/*
 * Regression: after the chart containers widen (a 1920px first load, or a 1366 -> 1920 window resize)
 * every pane must refit to the chosen range, so "All history" (still pressed) fills each pane. Before
 * the fix the panes kept their old bar spacing and the left part of a pane stayed blank until a range
 * button was clicked again. Pixel equality with an explicit re-fit pins the expected behaviour.
 */
for (const start of [1920, 1366]) {
 test(`All history fills every pane after the containers widen (start ${start}px, end 1920px)`, async ({page}) => {
  const a = fixtures['Bearish-1d'];
  await openReport(page, a, 'dark', start);
  if (start !== 1920) await page.setViewportSize({width: 1920, height: 1000});
  await page.mouse.move(2, 2);
  const panes = [PRICE, PERFORMANCE, DRAWDOWN];
  await expect.poll(() => pane(page, PERFORMANCE).evaluate(el => el.clientWidth)).toBeGreaterThan(1400);
  await page.waitForTimeout(500);
  const shown = await Promise.all(panes.map(label => shot(pane(page, label))));
  await page.getByRole('button', {name: 'Last year', exact: true}).click();
  await page.getByRole('button', {name: 'All history', exact: true}).click();
  await page.mouse.move(2, 2);
  for (const [i, label] of panes.entries()) expect((await shot(pane(page, label))).equals(shown[i]), `${label} already showed all history`).toBe(true);
 });
}
