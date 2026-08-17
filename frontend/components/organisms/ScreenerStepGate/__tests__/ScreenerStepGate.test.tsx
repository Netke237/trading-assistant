import '@testing-library/jest-dom';
import { render, screen, waitFor } from '@testing-library/react';
import { ScreenerStepGate } from '@/components/organisms/ScreenerStepGate';
import { useScanStore } from '@/lib/scanStore';

const mockReplace = jest.fn();
let mockPathname = '/screener/step-5-strategy';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => mockPathname,
}));

const STORE_KEY = 'bamendjou-scan-store';

function seedScanStore(mode: 'options' | 'stocks' | 'prebreakout') {
  localStorage.setItem(STORE_KEY, JSON.stringify({ state: { screenerMode: mode }, version: 11 }));
}

describe('ScreenerStepGate', () => {
  beforeEach(() => {
    mockReplace.mockClear();
    localStorage.clear();
    useScanStore.setState({ screenerMode: 'options' });
  });

  it('redirects a step-5 page to step-4-prebreakout in Pre-Breakout mode', async () => {
    mockPathname = '/screener/step-5-strategy';
    seedScanStore('prebreakout');
    await useScanStore.persist.rehydrate();

    render(
      <ScreenerStepGate>
        <div>strategy page</div>
      </ScreenerStepGate>,
    );

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/screener/step-4-prebreakout'));
    expect(screen.queryByText('strategy page')).not.toBeInTheDocument();
  });

  it('renders children without redirect when the slug matches the active mode', async () => {
    mockPathname = '/screener/step-5-vol-events';
    seedScanStore('options');
    await useScanStore.persist.rehydrate();

    render(
      <ScreenerStepGate>
        <div>vol events page</div>
      </ScreenerStepGate>,
    );

    expect(screen.getByText('vol events page')).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('passes the bare /screener index through without redirect', async () => {
    mockPathname = '/screener';
    seedScanStore('prebreakout');
    await useScanStore.persist.rehydrate();

    render(
      <ScreenerStepGate>
        <div>index page</div>
      </ScreenerStepGate>,
    );

    expect(screen.getByText('index page')).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('renders a cross-mode step-4 page through to the matching step 4 in options mode', async () => {
    mockPathname = '/screener/step-4-stocks';
    seedScanStore('options');
    await useScanStore.persist.rehydrate();

    render(
      <ScreenerStepGate>
        <div>stocks page</div>
      </ScreenerStepGate>,
    );

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/screener/step-4-ranking'));
    expect(screen.queryByText('stocks page')).not.toBeInTheDocument();
  });
});
