import { test, expect } from '@playwright/test';
import fs from 'fs';
import { setupApiMocks } from '../fixtures/api-mocks';

// Generate these from the real detailed engine with the validation fixture script.
const fixturePath = process.env.BACKTEST_BROWSER_FIXTURES;
const fixtures = fixturePath ? JSON.parse(fs.readFileSync(fixturePath, 'utf8')) : null;
test.skip(!fixtures, 'Manual integration suite: generate engine fixtures and set BACKTEST_BROWSER_FIXTURES.');
for (const direction of ['Bullish', 'Bearish']) for (const theme of ['dark', 'light']) for (const width of [1280, 1920]) {
  test(`${direction} ${theme} ${width}: frozen fills and indexed panes`, async ({page}) => {
    const artifact = fixtures[`${direction}-${width === 1280 ? '15m' : '1d'}`];
    await page.setViewportSize({width, height: 1000});
    await page.addInitScript(theme => localStorage.setItem('bamendjou:theme', JSON.stringify({state:{theme},version:0})), theme);
    await setupApiMocks(page);
    let artifactReads = 0;
    const writes: string[] = [];
    page.on('request', request => {if (request.method() !== 'GET' && request.url().includes('/api/')) writes.push(request.url());});
    await page.route('**/api/backtest-artifacts/**', async route => {artifactReads++; await route.fulfill({json:artifact});});
    await page.goto(`/chart?symbol=AAA&source=stocks&backtest_artifact_status=available&backtest_artifact_id=${artifact.artifact_id}`);
    await expect(page.getByLabel('Historical candles', {exact:true})).toBeVisible();
    await expect(page.getByLabel('Indexed equity comparison', {exact:true})).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    const trade = artifact.detail.trades[0];
    const inspect = page.getByRole('button',{name:`Inspect trade ${trade.id}`,exact:true});
    await inspect.focus(); await page.keyboard.press('Enter');
    const details = page.getByLabel('Trade inspector', {exact:true});
    await expect(details).toContainText(String(trade.entry_price));
    await expect(details).toContainText(String(trade.exit_price));
    await expect(details).toContainText(String(trade.net_return_pct));
    await expect(details).toContainText('Unknown (not recorded by engine)');
    await page.getByText('Recorded configuration and provenance', {exact:true}).click();
    await expect(page.getByText(`Artifact ${artifact.artifact_id}`,{exact:false})).toBeVisible();
    await expect(page.getByText('Long buy-and-hold (gross; excludes fees)',{exact:false}).first()).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({path:`/tmp/backtest-${direction}-${theme}-${width}.png`,fullPage:true});
    await page.getByLabel('Evidence interval',{exact:true}).selectOption('1h');
    await expect(page.getByLabel('Historical candles',{exact:true})).toHaveCount(0);
    expect(artifactReads).toBe(1);
    expect(writes).toEqual([]);
  });
}

test('successful zero trades keep curves; unsupported setup stays unavailable', async ({page}) => {
  await page.setViewportSize({width:1280,height:1000});
  await setupApiMocks(page);
  const artifact=fixtures.zero;
  await page.route('**/api/backtest-artifacts/**', route => route.fulfill({json:artifact}));
  await page.goto(`/chart?symbol=AAA&source=stocks&backtest_artifact_status=available&backtest_artifact_id=${artifact.artifact_id}`);
  await expect(page.getByText(/Successful result: zero closed trades/)).toBeVisible();
  await expect(page.getByLabel('Indexed equity comparison',{exact:true})).toBeVisible();
  await page.goto('/chart?symbol=AAA&source=fib&backtest_artifact_status=unsupported');
  await expect(page.getByLabel('Historical candles',{exact:true})).toHaveCount(0);
  await expect(page.getByText(/unsupported/i).first()).toBeVisible();
});

test('explicit fresh run stays separate and preserves original evidence and scan inputs', async ({page}) => {
  await page.setViewportSize({width:1280,height:1000});
  await setupApiMocks(page);
  const original=fixtures['Bearish-1d'];
  const fresh=fixtures.fresh;
  let submitted: any=null;
  const writes: string[]=[];
  page.on('request', request => {if(request.method()!=='GET'&&request.url().includes('/api/'))writes.push(new URL(request.url()).pathname);});
  await page.route('**/api/backtest-artifacts/**', async route => {
    const path=new URL(route.request().url()).pathname;
    if(path.endsWith('/fresh/configuration'))return route.fulfill({json:{strategies:['pullback_ema'],parameters:{pullback_ema:{ema_period:'int'}},multi_fields:[]}});
    if(path.endsWith('/fresh')){submitted=route.request().postDataJSON();return route.fulfill({json:{status:'success',artifact:fresh}});}
    return route.fulfill({json:original});
  });
  await page.goto(`/chart?symbol=AAA&source=stocks&backtest_artifact_status=available&backtest_artifact_id=${original.artifact_id}`);
  await expect(page.getByLabel('Historical candles',{exact:true})).toBeVisible();
  const savedScan=await page.evaluate(()=>localStorage.getItem('bamendjou-scan-store'));
  await page.getByRole('button',{name:'Configure a fresh run',exact:true}).click();
  await page.getByLabel('Evaluation start',{exact:true}).fill('2024-04-20');
  await page.getByLabel('Evaluation end (exclusive)',{exact:true}).fill('2024-05-30');
  await page.getByLabel('Commission per leg (fraction)',{exact:true}).fill('0.002');
  await page.getByLabel('Maximum hold days (null for none)',{exact:true}).fill('10');
  await page.getByLabel('Minimum closed trades',{exact:true}).fill('5');
  await page.getByLabel('Minimum win rate (fraction)',{exact:true}).fill('0.5');
  await page.getByLabel('Complete strategy parameters (JSON)',{exact:true}).fill(JSON.stringify(fresh.detail.effective_params));
  await page.getByLabel(/I reviewed the strategy/).check();
  await page.getByRole('button',{name:'Run fresh backtest',exact:true}).click();
  await expect(page.getByRole('heading',{name:'AAA — Fresh backtest (separate result)',exact:true})).toBeVisible();
  expect(submitted).toMatchObject({symbol:'AAA',strategy:'pullback_ema',direction:'Bearish',commission:.002,start:'2024-04-20',end:'2024-05-30',order_size:.9999999999999998,confirmed:true});
  expect(submitted.params).toEqual(fresh.detail.effective_params);
  await page.getByRole('button',{name:'Show original backtest',exact:true}).click();
  await expect(page.getByRole('heading',{name:'AAA — Original backtest',exact:true})).toBeVisible();
  await page.getByText('Recorded configuration and provenance',{exact:true}).click();
  await expect(page.getByText(`Artifact ${original.artifact_id}`,{exact:false})).toBeVisible();
  expect(await page.evaluate(()=>localStorage.getItem('bamendjou-scan-store'))).toBe(savedScan);
  expect(writes).toEqual(['/api/backtest-artifacts/fresh']);
});
