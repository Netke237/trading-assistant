import { Page, Locator } from '@playwright/test';

export class ScreenerPage {
  constructor(private page: Page) {}

  async goto(step: number): Promise<void> {
    const stepNames: Record<number, string> = {
      1: 'step-1-regime',
      2: 'step-2-universe',
      3: 'step-3-direction',
      4: 'step-4-ranking',
      5: 'step-5-vol-events',
      6: 'step-6-contracts',
      7: 'step-7-trade-card',
    };
    await this.page.goto(`/screener/${stepNames[step]}`);
    // A screener step page is an empty server shell: ScreenerStepGate renders
    // children only once the persisted store has hydrated on the client, and
    // React attaches click handlers at that same moment. A click dispatched
    // before then is silently swallowed — Playwright's actionability checks
    // cannot see a missing React handler, so the button looks clickable and the
    // click does nothing. That is what made the Next-navigation tests flaky.
    // The step header is rendered by the page itself, so its appearance is a
    // reliable "the client tree is live" signal. (The REJECT test waits on the
    // nav's data-regime attribute for the same reason.)
    await this.page.getByText(/STEP \d+ OF \d+/).first().waitFor({ state: 'visible' });
  }

  get nextButton(): Locator {
    return this.page.locator('nav[aria-label="Screener step navigation"] button').filter({ hasText: /next/i });
  }

  get backButton(): Locator {
    return this.page.getByRole('button', { name: /back/i });
  }

  async clickNext(): Promise<void> {
    await this.nextButton.click();
  }

  async clickBack(): Promise<void> {
    await this.backButton.click();
  }

  // Step 1
  get universeTiles(): Locator {
    return this.page.locator('[role="button"], button').filter({ hasText: /SP 500|NASDAQ|DOW/i });
  }

  get runScanButton(): Locator {
    return this.page.getByRole('button', { name: /run scan/i });
  }

  async clickRunScan(): Promise<void> {
    await this.runScanButton.click();
  }

  async selectUniverse(name: string): Promise<void> {
    // Anchor to start of accessible name to avoid matching card descriptions
    // (e.g. SPY desc contains "S&P 500 ETF", which would otherwise match an "S&P 500" query)
    const cleanName = name.replace(/\\/g, '');
    await this.page.getByRole('button', { name: new RegExp(`^${cleanName}`, 'i') }).click();
  }

  // Step 2
  get bullishButton(): Locator {
    return this.page.getByRole('button', { name: /bullish/i });
  }

  get bearishButton(): Locator {
    return this.page.getByRole('button', { name: /bearish/i });
  }

  async selectDirection(direction: 'Bullish' | 'Bearish'): Promise<void> {
    if (direction === 'Bullish') {
      await this.bullishButton.click();
    } else {
      await this.bearishButton.click();
    }
  }

  // Step 1
  get regimeBanner(): Locator {
    return this.page.getByTestId('regime-banner');
  }

  get spxChart(): Locator {
    return this.page.getByTestId('spx-chart').locator('canvas').first();
  }

  get ndxChart(): Locator {
    return this.page.getByTestId('ndx-chart').locator('canvas').first();
  }

  get metricGrid(): Locator {
    return this.page.getByTestId('regime-metric-grid');
  }

  get sectorHeatmap(): Locator {
    return this.page.getByTestId('sector-heatmap');
  }

  get rejectDialog(): Locator {
    return this.page.getByRole('dialog');
  }

  get proceedAnywayButton(): Locator {
    return this.page.getByRole('button', { name: /proceed anyway/i });
  }

  // Step 4
  get rankingTable(): Locator {
    return this.page.getByRole('table');
  }

  // Step 5.
  // These specs navigate straight to the step with NO scan seeded, so this is
  // the empty state. It used to be matched on /iv rank/, which the page printed
  // unconditionally because the sentence came from the horizon alone; since the
  // Phase A basis split the sentence comes from the rows on screen and there are
  // none here (PHASE-A-NULL-IVRANK-2026-09-06).
  get ivSection(): Locator {
    return this.page.getByText(/run a scan to see the volatility and event gates/i).first();
  }

  // Step 6
  get contractsTable(): Locator {
    return this.page.getByRole('table');
  }

  // Step 7
  get tradeCardEmptyState(): Locator {
    return this.page.getByText(/no trade cards|empty|run a scan/i).first();
  }
}
