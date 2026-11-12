import { test, expect } from '../fixtures';
import type { StockExitPlan } from '@/types/stockDomain';
function makePlan(overrides: Partial<StockExitPlan> = {}): StockExitPlan {
  return {
    stop: {
      price: 144.0,
      source: 'atr_widened',
      structuralSource: 'swing_low',
      structuralConfidence: 60,
      structuralPrice: 147.0,
      atrFloorPrice: 144.0,
      distanceDollar: 3.0,
      riskPerShare: 6.0,
      probability: 0.34,
      expectedDays: 6,
    },
    targets: [
      {
        rrRatio: 2, arithmeticPrice: 162.0, price: 162.0, tpSource: 'arithmetic',
        structuralPrice: 170.0, distanceDollar: 8.0, toleranceDollar: 0.9,
        rewardPerShare: 12.0, probability: 0.41, expectedDays: 7,
        qualityGood: false, qualityReasons: ['stop_widened'],
      },
      {
        rrRatio: 3, arithmeticPrice: 168.0, price: 170.0, tpSource: 'structural_snap',
        structuralPrice: 170.0, distanceDollar: 2.0, toleranceDollar: 2.5,
        rewardPerShare: 20.0, probability: 0.19, expectedDays: 9,
        qualityGood: false, qualityReasons: ['stop_widened'],
      },
    ],
    atr: 3.0,
    recommendedShares: 625,
    riskBudget: 3750.0,
    daysBasis: 'trading',
    horizonDays: 10,
    modelCaveat: null,
    race: {
      outcomes: [
        {
          targetPrice: 162.0, pTargetFirst: 0.4, pStopFirst: 0.34, pNeither: 0.26,
          daysTarget: 7, daysStop: 6,
          weightTarget: 0.4, weightStop: 0.34, weightNeither: 0.26,
          terminalMean: 152.4,
        },
        {
          targetPrice: 170.0, pTargetFirst: 0.19, pStopFirst: 0.34, pNeither: 0.47,
          daysTarget: 9, daysStop: 6,
          weightTarget: 0.19, weightStop: 0.34, weightNeither: 0.47,
          terminalMean: 154.1,
        },
      ],
      stopPrice: 144.0,
      nPaths: 2000,
    },
    ...overrides,
  };
}



const candidate = (symbol = 'AAPL', direction: 'Bullish' | 'Bearish' = 'Bullish') => ({
  symbol, company: symbol === 'AAPL' ? 'Apple Inc.' : 'Microsoft Corporation', price: 150, direction,
  strategy: { strategy: 'pullback_ema', entry_price: 150, stop_price: direction === 'Bullish' ? 145 : 155, target_price: direction === 'Bullish' ? 160 : 140, targets: direction === 'Bullish' ? [160, 165, 170] : [140, 135, 130], rr_ratio: 2, atr: 3, detail: {} },
  backtest: { n_trades: 20, win_rate: .6, total_return_pct: 12, max_drawdown_pct: 5, expectancy: .4, sharpe: 1.2, confidence: 70, passes_gate: true, summary_text: 'Recorded backtest' },
  sentiment: { horizon: 'Swing', timeframe: 'daily', state: 'Bullish', p_stay: .8, stability: 'Stable', regime_age_days: 3, avg_regime_duration: 8, conviction_pct: 25, conviction_label: 'Bullish', interpretation: 'Recorded sentiment', alignment: 'Aligned' },
  fundamentals: { score: 72, quality_label: 'Strong', risk_label: 'Low', growth_score: 70, quality_score: 75, risk_score: 68, safety_flags: [], detail: {} },
  stock_score: 80, stock_status: 'CAUTION', shares: 30, dollar_risk: 150, dollar_size: 4500, confidence: 70, confidence_text: 'Recorded confidence',
  stock_explanation: { status: 'PASS', components: Object.fromEntries(['trend', 'pullback', 'trigger', 'event', 'volatility'].map(name => [name, { name, raw_score: 80, measured: true, weight: .2, contribution: 16 }])) },
});

for (const width of [1200, 1366, 1920]) for (const theme of ['dark', 'light'] as const) for (const direction of ['Bullish', 'Bearish'] as const) test(`Position workspace preserves ${direction} save payload at ${width}px in ${theme}`, async ({ page }, testInfo) => {
  const bullish = direction === 'Bullish';
  const stockTarget = bullish ? 160 : 140;
  const executionStop = bullish ? 145 : 155;
  const plan = makePlan();
  if (!bullish) {
    plan.stop = { ...plan.stop, price: 156, structuralSource: 'swing_high', structuralPrice: 153, atrFloorPrice: 156 };
    plan.targets = plan.targets.map((row, i) => ({ ...row, price: i === 0 ? 138 : 130, arithmeticPrice: i === 0 ? 138 : 132, structuralPrice: 130 }));
    plan.race = plan.race ? { ...plan.race, stopPrice: 156, outcomes: plan.race.outcomes.map((row, i) => ({ ...row, targetPrice: i === 0 ? 138 : 130, terminalMean: 148 })) } : null;
  }
  plan.targets[0].expectedDays = 7.5;
  test.setTimeout(90_000);
  await page.setViewportSize({ width, height: 1080 });
  const saves: Record<string, unknown>[] = [];
  const calculations: string[] = [];
  await page.route('**/api/portfolio', async route => {
    if (route.request().method() === 'POST') {
      saves.push(route.request().postDataJSON());
      await route.fulfill({ json: { ok: true, adjusted_qty: 30 } });
    } else await route.fulfill({ json: [] });
  });
  await page.route('**/api/**', async route => {
    const url = route.request().url();
    if (url.endsWith('/api/portfolio')) return route.fallback();
    if (url.includes('/quote')) return route.fulfill({ json: { price: 151 } });
    if (url.includes('exit-plan')) { calculations.push('arithmetic'); return route.fulfill({ json: plan }); }
    if (url.includes('first-passage')) { calculations.push('monte-carlo'); return route.fulfill({ json: { targets: [{ price: stockTarget, probability: .62, expectedDays: 4.5 }], invalidation: { probability: .28, expectedDays: 6 }, horizonDays: 10, modelCaveat: 'Mock model evidence' } }); }
    if (route.request().method() !== 'GET') return route.fulfill({ status: 500, json: { detail: 'Unexpected test mutation' } });
    return route.fallback();
  });
  await page.addInitScript(({ cards, theme, direction }) => {
    localStorage.setItem('bamendjou:theme', JSON.stringify({ version: 0, state: { theme } }));
    localStorage.setItem('bamendjou-scan-store', JSON.stringify({ version: 19, state: {
      screenerMode: 'stocks', selectedSymbol: 'AAPL', stockScanResult: { scan_id: 'position-browser', timestamp: new Date().toISOString(), candidates: cards, rejected: [] },
      stockScanRequest: { bt_min_trades: 20, bt_min_win_rate: .5, horizon: 'Swing' }, context: { direction, horizon: 'Swing (5–15d)', holdMin: 5, holdMax: 15 }, scanState: 'COMPLETED',
    } }));
  }, { cards: [candidate('AAPL', direction), candidate('MSFT', direction)], theme, direction });
  await page.goto('/screener/step-7-position-card');
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
  await expect(page.getByRole('heading', { name: 'Your decision' })).toBeVisible();
  const views = page.getByRole('group', { name: 'View method results' });
  const ladder = page.getByRole('region', { name: 'Original ladder evidence' });
  const mc = page.getByRole('region', { name: 'Monte Carlo evidence' });
  const arithmetic = page.getByRole('region', { name: 'Arithmetic evidence' });
  await expect(views.getByRole('button', { name: 'Ladder', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(ladder).toBeVisible();
  await expect(mc).toBeHidden();
  await expect(arithmetic).toBeHidden();
  await page.screenshot({ path: testInfo.outputPath(`position-${direction}-${theme}-${width}-initial.png`), fullPage: true });
  await views.getByRole('button', { name: 'Monte Carlo', exact: true }).click();
  await expect(mc).toBeVisible();
  await views.getByRole('button', { name: 'Compare', exact: true }).click();
  await expect(mc).toBeVisible();
  await expect(arithmetic).toBeVisible();
  await expect(ladder).toBeHidden();
  expect(calculations).toEqual([]);
  const checkPair = async () => {
    const left = await mc.boundingBox();
    const right = await arithmetic.boundingBox();
    expect(left).not.toBeNull(); expect(right).not.toBeNull();
    expect(Math.abs(left!.width - right!.width)).toBeLessThanOrEqual(1);
    expect(Math.abs(left!.height - right!.height)).toBeLessThanOrEqual(1);
    expect(Math.abs(left!.y - right!.y)).toBeLessThanOrEqual(1);
    const leftHeader = await mc.getByRole('columnheader', { name: 'Conditional median', exact: true }).boundingBox();
    const rightHeader = await arithmetic.getByRole('columnheader', { name: 'Conditional median', exact: true }).boundingBox();
    expect(Math.abs(leftHeader!.y - rightHeader!.y)).toBeLessThanOrEqual(1);
  };
  await checkPair();
  await views.getByRole('button', { name: 'Ladder', exact: true }).click();
  await expect(page.getByTestId('visible-method-card')).toHaveCount(3);
  const third = await arithmetic.boundingBox();
  const first = await ladder.boundingBox();
  const second = await mc.boundingBox();
  expect(Math.abs(first!.width - third!.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(first!.width - second!.width)).toBeLessThanOrEqual(1);
  expect(third!.y).toBeGreaterThan(first!.y);
  const firstHeader = await ladder.getByRole('columnheader', { name: 'Conditional median', exact: true }).boundingBox();
  const secondHeader = await mc.getByRole('columnheader', { name: 'Conditional median', exact: true }).boundingBox();
  expect(Math.abs(firstHeader!.y - secondHeader!.y)).toBeLessThanOrEqual(1);
  await views.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath(`position-${direction}-${theme}-${width}-compare-three.png`), fullPage: true });
  await views.getByRole('button', { name: 'Ladder', exact: true }).click();
  await page.locator('summary').filter({ hasText: /^Stock Qualification/ }).click();
  await page.locator('summary').filter({ hasText: /^Backtest Evidence/ }).click();
  await expect(page.getByText('Final verdict: CAUTION')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Backtest evidence' }).getByText('70%', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByText('Microsoft Corporation')).toBeVisible();
  await page.getByRole('button', { name: 'Prev', exact: true }).click();
  // Candidate navigation remounts local viewing state; reveal both methods again.
  await views.getByRole('button', { name: 'Compare', exact: true }).click();
  await page.getByText('How this page works', { exact: true }).focus();
  await page.keyboard.press('Enter');
  await page.getByText('Auto-trade execution', { exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('Auto-trade mode', { exact: true })).toBeVisible();
  await page.getByText('Auto-trade execution', { exact: true }).focus();
  await page.keyboard.press('Enter');
  await page.getByRole('link', { name: 'Calculations', exact: true }).click();
  await page.locator('summary').filter({ hasText: /^Latest calculation$/ }).click();
  await page.getByRole('button', { name: 'Estimate', exact: true }).click();
  await expect(page.getByText('Latest: Monte Carlo')).toBeVisible();
  await page.getByRole('button', { name: 'Arithmetic plan', exact: true }).click();
  await expect(page.getByText('Latest: Arithmetic')).toBeVisible();
  expect(calculations).toEqual(['monte-carlo', 'arithmetic']);
  await checkPair();
  await expect(mc.getByRole('table').first()).toContainText('$300.00');
  await expect(arithmetic.getByRole('table').first()).toContainText('$360.00');
  await expect(arithmetic.getByRole('table').first()).toContainText('~7.5 trading days');
  await views.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath(`position-${direction}-${theme}-${width}-compare-two.png`), fullPage: true });
  const summary = page.getByRole('region', { name: 'Selected stock plan' });
  await page.getByRole('radio', { name: 'Arithmetic', exact: true }).click();
  await page.getByRole('radio', { name: '2R', exact: true }).click();
  await expect(summary).toContainText('$360.00');
  await expect(summary).toContainText('7.5 trading days');
  await expect(summary).toContainText('Arithmetic final stop');
  await page.locator('summary').filter({ hasText: /^Structure & Stops$/ }).click();
  await expect(page.getByRole('region', { name: 'Entered execution stop' })).toContainText(`$${executionStop.toFixed(2)}`);
  await page.getByRole('radio', { name: 'Ladder', exact: true }).click();
  await expect(summary).toContainText('Choose a target');
  await page.getByRole('radio', { name: 'T1', exact: true }).click();
  await expect(summary).toContainText(`$${stockTarget.toFixed(2)}`);
  await expect(summary).toContainText('$300.00');
  await summary.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath(`position-${direction}-${theme}-${width}-decision.png`) });
  await page.getByRole('region', { name: 'Structure & Stops' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath(`position-${direction}-${theme}-${width}-stops.png`) });
  await page.getByRole('button', { name: 'Add to Portfolio', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Added to Portfolio' })).toBeVisible();
  expect(saves).toHaveLength(1);
  expect(saves[0]).toMatchObject({ symbol: 'AAPL', qty: 30, entryPrice: 150, stop: executionStop, pickedMethod: 'ladder', pickedRowStockPrice: stockTarget });
  expect(saves[0].targets).toEqual((bullish ? [160, 165, 170] : [140, 135, 130]).map((price, i) => ({ id: `T${i + 1}`, stockPrice: price, targetPrice: price, contractsToSell: 10, status: 'PENDING' })));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.evaluate(() => document.querySelectorAll('*').forEach(el => { el.scrollTop = 0; }));
  await page.screenshot({ path: testInfo.outputPath(`position-${direction}-${theme}-${width}.png`), fullPage: true });
  await page.getByRole('link', { name: 'Which comes first', exact: true }).click();
  await page.locator('summary').filter({ hasText: /^Which comes first · graphical outcomes & full details$/ }).click();
  await page.screenshot({ path: testInfo.outputPath(`position-${direction}-${theme}-${width}-calculations.png`), fullPage: true });
  await page.getByRole('link', { name: 'Qualification', exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath(`position-${direction}-${theme}-${width}-qualification.png`), fullPage: true });
});
