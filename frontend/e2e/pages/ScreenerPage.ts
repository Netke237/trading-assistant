import { Page, Locator } from '@playwright/test';

export class ScreenerPage {
  constructor(private page: Page) {}

  async goto(step: number): Promise<void> {
    const stepNames: Record<number, string> = {
      1: 'step-1-universe',
      2: 'step-2-direction',
      3: 'step-3-regime',
      4: 'step-4-ranking',
      5: 'step-5-vol-events',
      6: 'step-6-contracts',
      7: 'step-7-trade-card',
    };
    await this.page.goto(`/screener/${stepNames[step]}`);
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

  async selectUniverse(name: string): Promise<void> {
    await this.page.getByRole('button', { name: new RegExp(name, 'i') }).click();
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

  // Step 3
  get regimeBanner(): Locator {
    return this.page.locator('section').first();
  }

  get spxChart(): Locator {
    return this.page.locator('canvas').first();
  }

  get ndxChart(): Locator {
    return this.page.locator('canvas').nth(1);
  }

  get metricGrid(): Locator {
    return this.page.locator('[class*="grid"]').first();
  }

  get sectorHeatmap(): Locator {
    return this.page.locator('[class*="sectors"]').first();
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

  // Step 5
  get ivSection(): Locator {
    return this.page.getByText(/iv rank|implied volatility/i).first();
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
