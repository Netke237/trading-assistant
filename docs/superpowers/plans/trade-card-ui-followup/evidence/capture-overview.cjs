const { chromium } = require(process.cwd() + '/node_modules/playwright');
const { setupApiMocks, MOCK_SCAN_CANDIDATE } = require(process.cwd() + '/e2e/fixtures/api-mocks.ts');
(async () => {
 const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox'] });
 for (const width of [1200, 1920]) {
  const page=await browser.newPage({viewport:{width,height:1000}});
  await setupApiMocks(page);
  await page.route('**/api/quote/stock?*',r=>r.fulfill({json:{symbol:'AAPL',price:185.2}}));
  await page.route('**/api/quote/option?*',r=>r.fulfill({json:{symbol:'AAPL',price:2.15}}));
  await page.route('**/broker/status',r=>r.fulfill({json:{}}));
  await page.addInitScript(c=>localStorage.setItem('bamendjou-scan-store',JSON.stringify({version:18,state:{scanResult:{scan_id:'overview',timestamp:new Date().toISOString(),candidates:[c],rejected:[]},context:{direction:'Bullish',horizon:'Swing (5-15d)'},screenerMode:'options',scanState:'COMPLETED'}})),MOCK_SCAN_CANDIDATE);
  await page.goto('http://localhost:3001/screener/step-7-trade-card');
  await page.getByRole('button',{name:/Stock & contract scores/}).waitFor();
  await page.screenshot({path:`test-results/trade-card-ui-overview-${width}.png`});
  await page.close();
 }
 await browser.close();
})().catch(error=>{process.stderr.write(String(error));process.exit(1)});
