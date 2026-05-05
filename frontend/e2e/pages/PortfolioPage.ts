import { Page, Locator } from '@playwright/test';

export class PortfolioPage {
  constructor(private page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto('/portfolio');
  }

  get emptyStateText(): Locator {
    return this.page.getByText(/no positions|empty|nothing here/i).first();
  }

  get positionsTable(): Locator {
    return this.page.getByRole('table');
  }
}
