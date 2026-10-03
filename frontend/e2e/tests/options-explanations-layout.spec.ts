import { test, expect, type Page } from '../fixtures';
import { ScreenerPage } from '../pages/ScreenerPage';

const SCAN_STORE_KEY = 'bamendjou-scan-store';
const SCAN_STORE_VERSION = 13;

function createCandidate(symbol: string, overrides: Record<string, unknown> = {}) {
  return {
    symbol,
    company: `${symbol} LongNameVeryLongWordWithoutSpacesCorporation`,
    price: 150.5,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 82,
    stockConfidence: 'PASS',
    stockBreakdown: {
      trend: 85,
      pullback: 78,
      trigger: 80,
      event: 90,
      volatility: 75,
    },
    nextEventDays: 30,
    nextEventLabel: 'SupercalifragilisticexpialidociousEventLabelWithoutSpaces',
    contract: `${symbol}|150|2026-12-01|C`,
    contractScore: 78,
    contractConfidence: 'PASS',
    contractBreakdown: {
      dteFit: 80,
      delta: 75,
      ivAttractiveness: 70,
      liquidity: 85,
      spread: 80,
    },
    contractDetails: {
      strike: 150,
      expiry: '2026-12-01',
      right: 'C',
      mid: 2.15,
      delta: 0.52,
      theta: -0.05,
      ivRank: 25,
      ivPercentile: 25,
      iv: null,
      dte: 45,
    },
    entry: { limit: 2.1, maxFill: 2.2, orderType: 'Limit' },
    exit: {
      invalidation: 140,
      premiumStop: 1.0,
      timeStopDays: 30,
      targets: [],
    },
    rrRatio: 2.5,
    rrModel: 'BS repriced',
    finalStatus: 'PASS',
    ...overrides,
  };
}

async function seedScan(page: Page, candidates: unknown[], theme = 'dark'): Promise<void> {
  await page.addInitScript(
    ([key, version, candidatesList, activeTheme]) => {
      window.localStorage.setItem('bamendjou:theme', activeTheme as string);
      window.localStorage.setItem(
        key as string,
        JSON.stringify({
          version,
          state: {
            scanResult: {
              scan_id: 'layout-e2e',
              timestamp: new Date().toISOString(),
              event_window: { reject_days: 21, caution_days: 45 },
              candidates: candidatesList,
              rejected: [],
            },
            context: {
              direction: 'Bullish',
              horizon: 'Swing (5-15d)',
            },
            scanState: 'COMPLETED',
            scanAt: new Date().toISOString(),
          },
        }),
      );
    },
    [SCAN_STORE_KEY, SCAN_STORE_VERSION, candidates, theme] as const,
  );
}

const VIEWPORTS = [
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
];

const THEMES = ['dark', 'light'] as const;

test.describe('Options Volatility + Events layout & responsiveness (AC7 & AC8)', () => {
  for (const vp of VIEWPORTS) {
    for (const theme of THEMES) {
      test(`Zero horizontal overflow at ${vp.width}x${vp.height} (${theme} theme)`, async ({ page }) => {
        await page.setViewportSize(vp);

        const candidates = [
          createCandidate('AAPL', {
            contractDetails: { ivRank: 20, ivPercentile: 20, iv: null },
            nextEventDays: 15, // CAUTION by event
          }),
          createCandidate('MSFT', {
            contractDetails: { ivRank: null, ivPercentile: null, iv: 58.5 }, // CAUTION by absolute IV
            nextEventDays: 50, // PASS by event
          }),
          createCandidate('NVDA', {
            contractDetails: { ivRank: null, ivPercentile: null, iv: null }, // Unreadable
            nextEventDays: null,
          }),
        ];

        await seedScan(page, candidates, theme);
        await new ScreenerPage(page).goto(5);

        // Verify page root is visible
        const step5 = page.getByTestId('step-5');
        await expect(step5).toBeVisible();

        // Bounding box checks
        const step5Box = await step5.boundingBox();
        expect(step5Box).not.toBeNull();
        if (step5Box) {
          expect(step5Box.x).toBeGreaterThanOrEqual(0);
          expect(step5Box.x + step5Box.width).toBeLessThanOrEqual(vp.width + 1);
        }

        // Check horizontal overflow on document
        const isDocOverflowing = await page.evaluate(() => {
          return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
        });
        expect(isDocOverflowing).toBe(false);

        // Check horizontal overflow on step-5 table
        const isTableOverflowing = await page.evaluate(() => {
          const el = document.querySelector('[data-testid="step-5"]') as HTMLElement | null;
          if (!el) return false;
          return el.scrollWidth > el.clientWidth + 1;
        });
        expect(isTableOverflowing).toBe(false);

        // Hover gate badge tooltip and verify no overflow
        const firstBadge = page.locator('[data-cell="gate"]').first();
        await firstBadge.hover();
        const isOverflowingOnTooltip = await page.evaluate(() => {
          return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
        });
        expect(isOverflowingOnTooltip).toBe(false);

        // Expand first row disclosure
        const firstExplainBtn = page.locator('[data-cell="disclosure"] button').first();
        await firstExplainBtn.click();

        // Verify disclosure panel is open
        const panel = page.locator('[data-disclosure-panel]').first();
        await expect(panel).toBeVisible();

        // Panel bounding box containment
        const panelBox = await panel.boundingBox();
        expect(panelBox).not.toBeNull();
        if (panelBox) {
          expect(panelBox.x).toBeGreaterThanOrEqual(0);
          expect(panelBox.x + panelBox.width).toBeLessThanOrEqual(vp.width + 1);
        }

        // Verify zero overflow after disclosure expansion
        const isDocOverflowingAfterExpand = await page.evaluate(() => {
          return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
        });
        expect(isDocOverflowingAfterExpand).toBe(false);

        const isTableOverflowingAfterExpand = await page.evaluate(() => {
          const el = document.querySelector('[data-testid="step-5"]') as HTMLElement | null;
          if (!el) return false;
          return el.scrollWidth > el.clientWidth + 1;
        });
        expect(isTableOverflowingAfterExpand).toBe(false);

        // Capture layout screenshot
        await page.screenshot({
          path: `test-results/layout-${vp.width}x${vp.height}-${theme}.png`,
        });
      });
    }
  }

  test('AC5: Failed threshold fetch shows wrapped error message and zero horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });

    await page.route('**/api/config/event-thresholds', async (route) => {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'Server error' }) });
    });

    const candidates = [createCandidate('ERR1')];
    await seedScan(page, candidates, 'dark');
    await new ScreenerPage(page).goto(5);

    await expect(page.getByTestId('step-5')).toBeVisible();
    await expect(page.locator('[data-part="thresholds-unavailable"]')).toBeVisible();

    const isDocOverflowing = await page.evaluate(() => {
      return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
    });
    expect(isDocOverflowing).toBe(false);
  });

  test('AC8: 20 candidates render without console errors and disclosures toggle without API calls', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });

    const twentyCandidates = Array.from({ length: 20 }, (_, i) =>
      createCandidate(`SYM${i}`, {
        contractDetails: {
          ivRank: i % 2 === 0 ? 10 + i * 2 : null,
          ivPercentile: 10 + i * 2,
          iv: i % 2 !== 0 ? 30 + i : null,
        },
        nextEventDays: i % 3 === 0 ? 10 + i : i % 3 === 1 ? 30 + i : null,
      }),
    );

    let apiCallCount = 0;
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error' && !msg.text().includes('ERR_CONNECTION_REFUSED')) {
        consoleErrors.push(msg.text());
      }
    });
    page.on('pageerror', (err) => {
      consoleErrors.push(err.message);
    });
    page.on('request', (req) => {
      if (req.url().includes('/api/')) {
        apiCallCount++;
      }
    });

    await seedScan(page, twentyCandidates, 'dark');
    await new ScreenerPage(page).goto(5);

    await expect(page.getByTestId('step-5')).toBeVisible();

    // Verify all 20 rows render
    const rows = page.locator('[data-cell="symbol"]');
    await expect(rows).toHaveCount(20);

    const toggleRequests: string[] = [];
    const onToggleReq = (req: any) => {
      toggleRequests.push(req.url());
    };
    page.on('request', onToggleReq);
    const errorsBeforeToggles = consoleErrors.length;

    // Toggle all 20 disclosures
    const buttons = page.locator('[data-cell="disclosure"] button');
    for (let i = 0; i < 20; i++) {
      await buttons.nth(i).click();
    }
    await expect(page.locator('[data-disclosure-panel]')).toHaveCount(20);

    page.off('request', onToggleReq);

    // Expanding rows must trigger ZERO console errors
    expect(consoleErrors.slice(errorsBeforeToggles)).toEqual([]);

    // Expanding rows must trigger ZERO contract, greeks, or volatility API requests (AC8)
    const disclosureApiRequests = toggleRequests.filter((url) =>
      url.includes('/api/contracts') ||
      url.includes('/api/chains') ||
      url.includes('/api/greeks') ||
      url.includes('/api/historical-volatility') ||
      url.includes('/api/config') ||
      url.includes('/api/iv')
    );
    expect(disclosureApiRequests).toEqual([]);

    // Verify keyboard interaction (Enter / Space) on disclosure button
    await buttons.nth(0).focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('[data-disclosure-panel]')).toHaveCount(19);
    await page.keyboard.press('Space');
    await expect(page.locator('[data-disclosure-panel]')).toHaveCount(20);

    // Close them back
    for (let i = 0; i < 20; i++) {
      await buttons.nth(i).click();
    }
    await expect(page.locator('[data-disclosure-panel]')).toHaveCount(0);
  });
});
