// Task 1 presentation capture only; not full phase acceptance or an independent audit.
const fs = require('fs');
const path = require('path');
const Module = require('module');
const root = path.resolve(__dirname, '../../../..');
const frontend = path.join(root, 'frontend');
process.chdir(frontend);
const projectRequire = Module.createRequire(path.join(frontend, 'package.json'));
const ts = projectRequire('typescript');
const { chromium } = projectRequire('playwright');
function load(source, filename) {
  const module = new Module(filename);
  module.filename = filename;
  module._compile(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
  } }).outputText, filename);
  return module.exports;
}
const specPath = path.join(frontend, 'e2e/tests/stock-position-presentation.spec.ts');
const spec = fs.readFileSync(specPath, 'utf8');
const ast = ts.createSourceFile(specPath, spec, ts.ScriptTarget.Latest, true);
const candidateSource = ast.statements.find(node => ts.isVariableStatement(node)
  && node.declarationList.declarations.some(d => d.name.getText(ast) === 'candidate')).getText(ast);
const { candidate } = load(candidateSource + '\nmodule.exports = {candidate};', specPath + '.fixtures.cjs');
const mocksPath = path.join(frontend, 'e2e/fixtures/api-mocks.ts');
const { setupApiMocks } = load(fs.readFileSync(mocksPath, 'utf8'), mocksPath + '.cjs');
const output = path.join(__dirname, 'evidence');
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true,
    args: ['--no-sandbox'] });
  const report = { scope: 'Task 1 initial capture; no calculation/save/order actions', captures: [] };
  for (const theme of ['dark', 'light']) {
    const page = await browser.newPage({ viewport: { width: 1366, height: 1080 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    // Intercept every API before the more specific existing fixture routes.
    await page.route('**/api/**', route => route.fulfill({ json: {} }));
    await setupApiMocks(page);
    await page.route('**/api/market/quote/**', route => route.fulfill({ json: { price: 151 } }));
    await page.addInitScript(({ cards, theme }) => {
      localStorage.setItem('bamendjou:theme', JSON.stringify({ version: 0, state: { theme } }));
      localStorage.setItem('bamendjou-scan-store', JSON.stringify({ version: 19, state: {
        screenerMode: 'stocks', stockScanResult: { scan_id: 'reference-task1-capture',
          timestamp: '2026-11-11T20:00:00Z', candidates: cards, rejected: [] },
        stockScanRequest: { bt_min_trades: 20, bt_min_win_rate: .5, horizon: 'Swing' },
        context: { direction: 'Bullish', horizon: 'Swing (5–15d)', holdMin: 5, holdMax: 15 },
        scanState: 'COMPLETED',
      } }));
    }, { cards: [candidate(), candidate('MSFT')], theme });
    await page.goto('http://127.0.0.1:3001/screener/step-7-position-card');
    await page.getByRole('heading', { name: 'Your decision', exact: true }).waitFor();
    const file = `first-build-initial-1366-${theme}.png`;
    await page.screenshot({ path: path.join(output, file), fullPage: true });
    report.captures.push({ file, theme, pageErrors: errors,
      openDetails: await page.locator('details[open]').count(),
      horizontalOverflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth) });
    await page.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(output, 'first-build-captures.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report));
})().catch(error => { console.error(error); process.exitCode = 1; });
