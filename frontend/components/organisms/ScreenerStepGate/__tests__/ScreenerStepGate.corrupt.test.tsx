import '@testing-library/jest-dom';
import { render, screen, act, waitFor } from '@testing-library/react';
import { ScreenerStepGate } from '@/components/organisms/ScreenerStepGate';
import { useScanStore } from '@/lib/scanStore';

const mockReplace = jest.fn();
const mockPathname = '/screener/step-5-vol-events';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => mockPathname,
}));

// Runs in its own file so the module registry (and therefore the gate's
// module-scope hydration store) is fresh — hydStore must start false, exactly
// as it would on a real first load whose rehydrate fails.
describe('ScreenerStepGate — corrupt persisted storage fallback', () => {
  beforeEach(() => {
    mockReplace.mockClear();
    localStorage.clear();
    useScanStore.setState({ screenerMode: 'options' });
  });

  it('falls back to shared Step 1 when persisted JSON is unparseable', async () => {
    jest.useFakeTimers();
    try {
      localStorage.setItem('bamendjou-scan-store', '{not valid json');
      await useScanStore.persist.rehydrate();
      useScanStore.setState({ screenerMode: 'options' });

      render(
        <ScreenerStepGate>
          <div>should not render wrong-mode content</div>
        </ScreenerStepGate>,
      );

      // Hydration never completes on corrupt JSON (onFinishHydration is not
      // fired by zustand's error path) — the gate must hold until the timer.
      expect(screen.queryByText('should not render wrong-mode content')).not.toBeInTheDocument();

      act(() => {
        // One tick past the gate's 1500ms grace timer.
        jest.advanceTimersByTime(1501);
      });

      expect(screen.queryByText('should not render wrong-mode content')).not.toBeInTheDocument();
      await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/screener/step-1-regime'));
    } finally {
      jest.useRealTimers();
    }
  });
});
