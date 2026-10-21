import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';

// Mock RailQuickLook so we can observe its invocation and props across all rail slots
jest.mock('@/components/organisms/ContextRail/QuickLook', () => ({
  RailQuickLook: (props: { showPortfolio?: boolean }) => (
    <div
      data-testid="rail-quick-look"
      data-show-portfolio={props.showPortfolio !== false ? 'true' : 'false'}
    >
      QuickLook Default Rail
    </div>
  ),
}));

// Fallback slot components under test
import CalendarDefaultRail from '../calendar/default';
import CalendarPageRail from '../calendar/page';
import SettingsDefaultRail from '../settings/default';
import SettingsPageRail from '../settings/page';
import JournalDefaultRail from '../journal/default';
import JournalPageRail from '../journal/page';
import StrategyWatchDefaultRail from '../strategy-watch/default';
import StrategyWatchPageRail from '../strategy-watch/page';
import ValidationDefaultRail from '../validation/default';
import ValidationPageRail from '../validation/page';
import AlertsDefaultRail from '../alerts/default';
import AlertsPageRail from '../alerts/page';
import RootDefaultRail from '../default';

// Dedicated custom rail slots for comparison
import PortfolioContextRail from '../portfolio/page';
import WatchlistContextRail from '../watchlist/page';
import DashboardContextRail from '../dashboard/page';

// Mock store state for dedicated rails so they render cleanly in tests
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useWatchlistStore } from '@/lib/watchlistStore';

describe('Context Rail Destination Parity (#395)', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [] });
    useWatchlistStore.setState({ added: [] });
  });

  describe('Fallback destination slots export RailQuickLook', () => {
    const fallbackSlots = [
      { name: 'calendar (default)', Component: CalendarDefaultRail },
      { name: 'calendar (page)', Component: CalendarPageRail },
      { name: 'settings (default)', Component: SettingsDefaultRail },
      { name: 'settings (page)', Component: SettingsPageRail },
      { name: 'journal (default)', Component: JournalDefaultRail },
      { name: 'journal (page)', Component: JournalPageRail },
      { name: 'strategy-watch (default)', Component: StrategyWatchDefaultRail },
      { name: 'strategy-watch (page)', Component: StrategyWatchPageRail },
      { name: 'validation (default)', Component: ValidationDefaultRail },
      { name: 'validation (page)', Component: ValidationPageRail },
      { name: 'alerts (default)', Component: AlertsDefaultRail },
      { name: 'alerts (page)', Component: AlertsPageRail },
      { name: 'root @contextRail (default)', Component: RootDefaultRail },
    ];

    test.each(fallbackSlots)('$name renders RailQuickLook with showPortfolio=true', ({ Component }) => {
      const { unmount } = render(<Component />);
      const quickLook = screen.getByTestId('rail-quick-look');
      expect(quickLook).toBeInTheDocument();
      expect(quickLook).toHaveAttribute('data-show-portfolio', 'true');
      unmount();
    });
  });

  describe('Dedicated rails preserve their custom content', () => {
    it('portfolio rail renders custom Totals and showPortfolio=false', () => {
      const { unmount } = render(<PortfolioContextRail />);
      expect(screen.getByText(/Totals/i)).toBeInTheDocument();
      expect(screen.getByText(/Aggregate Greeks/i)).toBeInTheDocument();
      // PortfolioContextRail passes showPortfolio={false} to RailQuickLook
      const quickLook = screen.getByTestId('rail-quick-look');
      expect(quickLook).toHaveAttribute('data-show-portfolio', 'false');
      unmount();
    });

    it('watchlist rail renders custom Status breakdown and Flags', () => {
      const { unmount } = render(<WatchlistContextRail />);
      expect(screen.getByText(/Status breakdown/i)).toBeInTheDocument();
      expect(screen.getByText(/Flags/i)).toBeInTheDocument();
      unmount();
    });

    it('dashboard rail renders Last Scan and Market Regime sections', () => {
      const { unmount } = render(<DashboardContextRail />);
      expect(screen.getByText(/Last Scan/i)).toBeInTheDocument();
      expect(screen.getByText(/Market Regime/i)).toBeInTheDocument();
      unmount();
    });
  });

  describe('Destination slot parity prevents stale context retention', () => {
    it('simulated transition from Portfolio to Calendar replaces Greeks with QuickLook', () => {
      // 1. Mount Portfolio rail
      const { unmount: unmountPortfolio } = render(<PortfolioContextRail />);
      expect(screen.getByText(/Totals/i)).toBeInTheDocument();
      expect(screen.getByText(/Aggregate Greeks/i)).toBeInTheDocument();
      unmountPortfolio();

      // 2. Mount Calendar rail (destination slot)
      const { unmount: unmountCalendar } = render(<CalendarPageRail />);
      expect(screen.queryByText(/Totals/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Aggregate Greeks/i)).not.toBeInTheDocument();
      expect(screen.getByTestId('rail-quick-look')).toHaveAttribute('data-show-portfolio', 'true');
      unmountCalendar();
    });

    it('simulated transition from Watchlist to Settings replaces Status Breakdown with QuickLook', () => {
      // 1. Mount Watchlist rail
      const { unmount: unmountWatchlist } = render(<WatchlistContextRail />);
      expect(screen.getByText(/Status breakdown/i)).toBeInTheDocument();
      expect(screen.getByText(/Flags/i)).toBeInTheDocument();
      unmountWatchlist();

      // 2. Mount Settings rail (destination slot)
      const { unmount: unmountSettings } = render(<SettingsPageRail />);
      expect(screen.queryByText(/Status breakdown/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Flags/i)).not.toBeInTheDocument();
      expect(screen.getByTestId('rail-quick-look')).toHaveAttribute('data-show-portfolio', 'true');
      unmountSettings();
    });
  });
});
