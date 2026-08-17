import '@testing-library/jest-dom';
import { render, screen, waitFor, act } from '@testing-library/react';
import { ScreenerStepGate } from '@/components/organisms/ScreenerStepGate';
import { useScanStore } from '@/lib/scanStore';

const mockReplace = jest.fn();
const mockPathname = '/screener/step-5-strategy';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => mockPathname,
}));

// Runs in its own file so the gate's module-scope hydration store starts
// false, exactly like a real first load. This test exercises the production
// sequence the other test files cannot: the gate mounts BEFORE StoreHydration
// rehydrates, and the onHydrate/onFinishHydration listeners — not a lucky
// pre-hydrated initial state — must flip it.
describe('ScreenerStepGate — hydration listener path', () => {
  beforeEach(() => {
    mockReplace.mockClear();
    localStorage.clear();
    useScanStore.setState({ screenerMode: 'options' });
  });

  it('mounts blank, then redirects once rehydrate completes', async () => {
    localStorage.setItem(
      'bamendjou-scan-store',
      JSON.stringify({ state: { screenerMode: 'prebreakout' }, version: 11 }),
    );

    // Mount BEFORE rehydrating — the gate must hold (blank) while unhydrated.
    render(
      <ScreenerStepGate>
        <div>strategy page</div>
      </ScreenerStepGate>,
    );
    expect(screen.queryByText('strategy page')).not.toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();

    // Now StoreHydration's rehydrate runs — the listeners must release the
    // gate and trigger the redirect.
    await act(async () => {
      await useScanStore.persist.rehydrate();
    });

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/screener/step-4-prebreakout'));
    expect(screen.queryByText('strategy page')).not.toBeInTheDocument();
  });
});
