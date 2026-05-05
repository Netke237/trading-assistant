import { Page, Locator } from '@playwright/test';

export class DashboardPage {
  readonly regimeBanner: Locator;
  readonly watchlistSection: Locator;
  readonly portfolioSection: Locator;
  readonly alertsSection: Locator;
  readonly navRail: Locator;

  constructor(private page: Page) {
    this.regimeBanner = page.getByRole('banner');
    this.watchlistSection = page.getByRole('region', { name: /watchlist/i }).or(page.getByText(/watchlist/i).first());
    this.portfolioSection = page.getByRole('region', { name: /portfolio/i }).or(page.getByText(/portfolio/i).first());
    this.alertsSection = page.getByRole('region', { name: /alerts/i }).or(page.getByText(/alerts/i).first());
    this.navRail = page.getByRole('navigation');
  }

  async goto(): Promise<void> {
    await this.page.goto('/');
  }

  get navLinkScreener(): Locator {
    return this.page.getByRole('link', { name: /screener/i });
  }

  get navLinkWatchlist(): Locator {
    return this.page.getByRole('link', { name: /watchlist/i });
  }

  get navLinkPortfolio(): Locator {
    return this.page.getByRole('link', { name: /portfolio/i });
  }

  get navLinkCalendar(): Locator {
    return this.page.getByRole('link', { name: /calendar/i });
  }

  get navLinkSettings(): Locator {
    return this.page.getByRole('link', { name: /settings/i });
  }
}
