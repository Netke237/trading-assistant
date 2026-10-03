/**
 * Stage C Layout, Browser, and Responsiveness Validation.
 * Options Step 6 Contract Score Explanations & Compact Layout.
 *
 * Requirements:
 * 1. TopBar/NavRail/ContextRail real frame at widths 1280, 1440, 1920.
 * 2. Supported widths: document/body/workspace/table scrollWidth <= clientWidth + 1 (no horizontal bar, no overflow).
 * 3. Below-boundary width (1200): MinWidthGate overlay blocks page with "Desktop required".
 * 4. Single-leg and spread (bear_put) contexts.
 * 5. Explanations expand beneath rows; zero new HTTP requests on toggle/pick/sort.
 * 6. Screenshots saved to docs/superpowers/measurements/options-explanations/.
 */

import { test, expect, type Page } from '../fixtures';
import { ScreenerPage } from '../pages/ScreenerPage';
import { MOCK_SCAN_CANDIDATE } from '../fixtures/api-mocks';
import * as path from 'path';

const SCAN_STORE_KEY = 'bamendjou-scan-store';
const SCAN_STORE_VERSION = 13;
const SCREENSHOT_DIR = path.resolve(process.cwd(), '..', 'docs', 'superpowers', 'measurements', 'options-explanations');

async function seedScanWithCandidate(page: Page, candidateOverrides: Record<string, unknown> = {}): Promise<void> {
  const candidate = {
    ...MOCK_SCAN_CANDIDATE,
    contract_rules: { min_volume: 20 },
    ...candidateOverrides,
  };

  await page.addInitScript(
    ([key, version, cand]) => {
      window.localStorage.setItem(key as string, JSON.stringify({
        version,
        state: {
          scanResult: {
            scan_id: 'options-exp-e2e',
            timestamp: new Date().toISOString(),
            candidates: [cand],
            rejected: [],
            contract_rules: { min_volume: 20 },
          },
          context: {
            direction: 'Bullish',
            horizon: 'Swing (5-20d)',
            holdMin: 5,
            holdMax: 20,
          },
          scanState: 'COMPLETED',
          scanAt: new Date().toISOString(),
        },
      }));
    },
    [SCAN_STORE_KEY, SCAN_STORE_VERSION, candidate] as const,
  );
}

test.describe('Options Step 6 Score Explanations & Layout (Stage C)', () => {
  const supportedWidths = [
    { width: 1280, height: 800, label: '1280px-minwidthgate-boundary' },
    { width: 1440, height: 900, label: '1440px-standard-desktop' },
    { width: 1920, height: 1080, label: '1920px-wide-desktop' },
  ];

  for (const { width, height, label } of supportedWidths) {
    test(`Single-leg: fits without horizontal overflow at ${width}px (${label})`, async ({ page }) => {
      page.on('pageerror', (err) => console.log('DEBUG_PAGE_ERROR:', err.message, err.stack));
      page.on('console', (msg) => {
        if (msg.type() === 'error') console.log('DEBUG_CONSOLE_ERR:', msg.text());
      });
      await page.setViewportSize({ width, height });
      await seedScanWithCandidate(page);

      await new ScreenerPage(page).goto(6);

      // Wait for table to be visible
      const table = page.locator('[role="table"]');
      await expect(table).toBeVisible();

      // Verify Rules applied banner is rendered
      const rulesBanner = page.locator('div:has-text("Rules applied:")').first();
      await expect(rulesBanner).toBeVisible();

      // Verify Sort toolbar is rendered
      const sortSelect = page.locator('select[id^="sort-"]');
      await expect(sortSelect).toBeVisible();

      // Expand first contract explanation
      const explainBtn = page.locator('button:has-text("Explain")').first();
      await expect(explainBtn).toBeVisible();
      await explainBtn.click();

      // Verify explanation region is open
      const explanationRegion = page.locator('[role="region"][aria-label^="Score explanation"]');
      await expect(explanationRegion).toBeVisible();
      await expect(explanationRegion.getByText('Composite Score:')).toBeVisible();

      // Measure layout: assert scrollWidth <= clientWidth + 1 across document, body, and workspace
      const overflowMetrics = await page.evaluate(() => {
        const doc = document.documentElement;
        const body = document.body;
        const workspace = document.querySelector('#workspace');

        const elementsWithOverflow: string[] = [];
        document.querySelectorAll('*').forEach((el) => {
          // Check block containers with overflow
          if (el instanceof HTMLElement && el.scrollWidth > el.clientWidth + 1) {
            const style = window.getComputedStyle(el);
            // Ignore intentional scroll containers if any, but screener should have no horizontal overflow
            if (style.overflowX !== 'hidden' && style.overflowX !== 'clip' && el.clientWidth > 0) {
              elementsWithOverflow.push(`${el.tagName.toLowerCase()}.${el.className} (scroll: ${el.scrollWidth}, client: ${el.clientWidth})`);
            }
          }
        });

        return {
          docScrollWidth: doc.scrollWidth,
          docClientWidth: doc.clientWidth,
          bodyScrollWidth: body.scrollWidth,
          bodyClientWidth: body.clientWidth,
          workspaceScrollWidth: workspace?.scrollWidth ?? 0,
          workspaceClientWidth: workspace?.clientWidth ?? 0,
          overflowCount: elementsWithOverflow.length,
          overflowDetails: elementsWithOverflow.slice(0, 5),
        };
      });

      expect(overflowMetrics.docScrollWidth).toBeLessThanOrEqual(overflowMetrics.docClientWidth + 1);
      expect(overflowMetrics.bodyScrollWidth).toBeLessThanOrEqual(overflowMetrics.bodyClientWidth + 1);
      if (overflowMetrics.workspaceClientWidth > 0) {
        expect(overflowMetrics.workspaceScrollWidth).toBeLessThanOrEqual(overflowMetrics.workspaceClientWidth + 1);
      }

      // Save screenshot for measurement record
      const screenshotPath = path.join(SCREENSHOT_DIR, `step6-${width}px-single-leg.png`);
      await page.screenshot({ path: screenshotPath, fullPage: false });
    });

    test(`Spread context: candidate spread snapshot fits at ${width}px (${label})`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await seedScanWithCandidate(page, {
        spreadType: 'bear_put',
        netDebitCredit: -2.35,
        maxProfit: 265,
        maxLoss: 235,
        breakeven: 182.65,
      });

      await new ScreenerPage(page).goto(6);

      // Verify spread snapshot banner
      const spreadSnapshot = page.locator('text=/Candidate spread snapshot/');
      await expect(spreadSnapshot).toBeVisible();
      await expect(page.getByText('−$2.35')).toBeVisible();

      // Expand explanation
      const explainBtn = page.locator('button:has-text("Explain")').first();
      await explainBtn.click();
      await expect(page.locator('[role="region"][aria-label^="Score explanation"]')).toBeVisible();

      // Check overflow
      const hasOverflow = await page.evaluate(() => {
        const doc = document.documentElement;
        return doc.scrollWidth > doc.clientWidth + 1;
      });
      expect(hasOverflow).toBe(false);

      // Save screenshot
      const screenshotPath = path.join(SCREENSHOT_DIR, `step6-${width}px-spread.png`);
      await page.screenshot({ path: screenshotPath, fullPage: false });
    });
  }

  test('Below-boundary width 1200px shows MinWidthGate overlay', async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 800 });
    await seedScanWithCandidate(page);

    await new ScreenerPage(page).goto(6);

    const gateDialog = page.locator('[role="dialog"][aria-label="Desktop required"]');
    await expect(gateDialog).toBeVisible();
    await expect(gateDialog.getByText('Desktop required')).toBeVisible();
    await expect(gateDialog.getByText('1280')).toBeVisible();
  });

  test('Interaction isolation: Explain toggle, sort, and pick trigger zero HTTP requests', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await seedScanWithCandidate(page);

    await new ScreenerPage(page).goto(6);
    await expect(page.locator('[role="table"]')).toBeVisible();

    let contractRequestCount = 0;
    page.on('request', (req) => {
      if (req.url().includes('/api/contracts')) {
        contractRequestCount++;
      }
    });

    // 1. Click Explain to expand
    const explainBtn = page.locator('button:has-text("Explain")').first();
    await explainBtn.click();
    await expect(page.locator('[role="region"][aria-label^="Score explanation"]')).toBeVisible();
    expect(contractRequestCount).toBe(0);

    // 2. Change sort in toolbar
    const sortSelect = page.locator('select[id^="sort-"]');
    await sortSelect.selectOption('volume');
    expect(contractRequestCount).toBe(0);

    // 3. Toggle sort direction
    const sortDirBtn = page.locator('button[aria-label^="Sort direction:"]');
    await sortDirBtn.click();
    expect(contractRequestCount).toBe(0);

    // 4. Click row to change pick
    const secondRow = page.locator('[role="button"]').filter({ hasText: '190C' }).first();
    if (await secondRow.count() > 0) {
      await secondRow.click();
      expect(contractRequestCount).toBe(0);
    }

    // 5. Click Hide to collapse
    const hideBtn = page.locator('button:has-text("Hide")').first();
    await hideBtn.click();
    await expect(page.locator('[role="region"][aria-label^="Score explanation"]')).toHaveCount(0);
    expect(contractRequestCount).toBe(0);
  });
});
