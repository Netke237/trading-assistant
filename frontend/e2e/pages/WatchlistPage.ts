import { Page, Locator } from '@playwright/test';

export class WatchlistPage {
  constructor(private page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto('/watchlist');
  }

  get stocksTab(): Locator {
    return this.page.getByRole('tab', { name: /stocks/i }).or(this.page.getByText(/stocks/i).first());
  }

  get contractsTab(): Locator {
    return this.page.getByRole('tab', { name: /contracts/i }).or(this.page.getByText(/contracts/i).first());
  }

  get emptyStateText(): Locator {
    return this.page.getByText(/no starred|empty|nothing here/i).first();
  }

  async switchToContractsTab(): Promise<void> {
    await this.contractsTab.click();
  }
}
