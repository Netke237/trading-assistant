import { test, expect, type Page } from '../fixtures';
import { MOCK_SCAN_CANDIDATE } from '../fixtures/api-mocks';
import wire from '../fixtures/generate_contract_boundaries.json';
import type { OptionContract } from '../../types/domain';

async function seed(page: Page, contract: OptionContract, spreadType?: 'bear_put' | 'bear_call') {
  const candidate = { ...MOCK_SCAN_CANDIDATE, contract: contract.id, spreadType,
    company: 'A very long company and event context '.repeat(8),
    netDebitCredit: -2.35, maxProfit: 265, maxLoss: 235, breakeven: 182.65,
    contractDetails: { ...MOCK_SCAN_CANDIDATE.contractDetails, expiry: contract.expiry, strike: contract.strike },
  };
  await page.route('**/api/contracts**', r => r.fulfill({ json: [contract] }));
  await page.addInitScript(c => localStorage.setItem('bamendjou-scan-store', JSON.stringify({ version: 13, state: {
    scanResult: { scan_id: 'contract-boundary', timestamp: new Date().toISOString(), candidates: [c], rejected: [] },
    context: { direction: c.contract.endsWith('|P') ? 'Bearish' : 'Bullish', horizon: 'Swing (5-20d)', holdMin: 5, holdMax: 20 }, scanState: 'COMPLETED',
  } })), candidate);
  await page.goto('/screener/step-6-contracts');
  await page.getByRole('button', { name: /^Explain score/ }).click();
}

test('real scorer wire keeps the hard spread inequality true', async ({ page }) => {
  await seed(page, wire.hard_boundary as OptionContract);
  await expect(page.getByText('0.04761904761904767 > 0.04761', { exact: true })).toBeVisible();
});
test('preferred ceiling preserves 5.55 percent and wide spreads preserve ratio units', async ({ page }) => {
  await seed(page, wire.preferred_boundary as OptionContract);
  await expect(page.getByText(/≤5\.55%/)).toBeVisible();
  await page.unroute('**/api/contracts**');
  await page.route('**/api/contracts**', r => r.fulfill({ json: [wire.wide_spread] }));
  await page.reload();
  await page.getByRole('button', { name: /^Explain score/ }).click();
  await expect(page.getByText(/160\.0%/)).toBeVisible();
});
for (const width of [1280, 1440, 1920]) {
  for (const spreadType of ['bear_put', 'bear_call'] as const) {
    test(`exact comparisons and long blocker labels fit ${spreadType} at ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const contract = JSON.parse(JSON.stringify(wire.hard_boundary)) as OptionContract;
      contract.explanation!.blockers[0].label = 'LongUnbrokenReason'.repeat(15);
      await seed(page, contract, spreadType);
      const panel = page.getByRole('region', { name: /^Score explanation/ });
      await expect(panel).toBeVisible();
      const overflow = await page.evaluate(() => {
        const elements = [document.documentElement, document.body,
          ...document.querySelectorAll('[role="table"], [role="region"][aria-label^="Score explanation"]')];
        return elements.filter(el => el.scrollWidth > el.clientWidth + 1).map(el => ({tag: el.tagName, role: el.getAttribute('role'), scroll: el.scrollWidth, client: el.clientWidth}));
      });
      expect(overflow).toEqual([]);
      const clipped = await panel.evaluate(p => {
        const box = p.getBoundingClientRect();
        return [...p.querySelectorAll('*')].filter(el => {
          const b = el.getBoundingClientRect();
          return b.width > 0 && (b.left < box.left - 1 || b.right > box.right + 1 ||
            (el instanceof HTMLElement && el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1));
        }).map(el => el.textContent);
      });
      expect(clipped).toEqual([]);
      await page.screenshot({ path: test.info().outputPath(`step6-boundary-${width}-${spreadType}.png`) });
    });
  }
}

test('normal put wire identity is accepted and below-minimum zoom width stays gated', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await seed(page, wire.put_boundary as OptionContract, 'bear_put');
  await expect(page.getByRole('region', { name: /Score explanation.*P$/ })).toBeVisible();
  // Effective CSS viewport of a 1600px display at 125% zoom is 1280px;
  // below that supported width the same gate must block the page.
  await page.setViewportSize({ width: 1200, height: 800 });
  await expect(page.getByRole('dialog', { name: 'Desktop required' })).toBeVisible();
});
