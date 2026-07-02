import '@testing-library/jest-dom';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { CompositeAlertDialog } from '@/components/organisms/CompositeAlertDialog';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    getCompositeWatchDefaults: jest.fn(),
    getSymbolRegimeSnapshot: jest.fn(),
    addCompositeWatch: jest.fn(),
  },
}));

const mockApi = api as jest.Mocked<typeof api>;

const SNAPSHOT = {
  model: 'OMM',
  state: 'Bull',
  p_stay: 0.812,
  conviction_pct: 74,
  conviction_label: 'High',
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockApi.getCompositeWatchDefaults.mockResolvedValue({
    conviction_min: 60,
    p_transition_min: 0.3,
    p_stay_min: 0.7,
    min_confirmations: 1,
  });
});

describe('CompositeAlertDialog — live regime snapshot', () => {
  it('fetches the snapshot on mount with the default OMM model and shows a loading state first', async () => {
    const { promise, resolve } = deferred<typeof SNAPSHOT>();
    mockApi.getSymbolRegimeSnapshot.mockReturnValue(promise as any);

    render(<CompositeAlertDialog symbol="AAPL" direction="Bullish" onClose={() => {}} />);

    expect(mockApi.getSymbolRegimeSnapshot).toHaveBeenCalledWith('AAPL', 'OMM', 'Bullish', '1D');
    expect(screen.getByText('Loading current regime…')).toBeInTheDocument();

    await act(async () => {
      resolve(SNAPSHOT);
      await promise;
    });
  });

  it('displays state, conviction, and P(stay) once the snapshot resolves', async () => {
    mockApi.getSymbolRegimeSnapshot.mockResolvedValue(SNAPSHOT as any);

    await act(async () => {
      render(<CompositeAlertDialog symbol="AAPL" direction="Bullish" onClose={() => {}} />);
    });

    expect(
      screen.getByText('Currently: Bull · Conviction 74% (High) · P(stay) 0.81'),
    ).toBeInTheDocument();
  });

  it('shows an error message when the snapshot fetch rejects', async () => {
    mockApi.getSymbolRegimeSnapshot.mockRejectedValue(new Error('network error'));

    await act(async () => {
      render(<CompositeAlertDialog symbol="TSLA" direction="Bullish" onClose={() => {}} />);
    });

    expect(screen.getByText('Live regime unavailable for TSLA')).toBeInTheDocument();
  });

  it('skips the snapshot fetch and hides the snapshot box when the model is switched to "any"', async () => {
    mockApi.getSymbolRegimeSnapshot.mockResolvedValue(SNAPSHOT as any);

    await act(async () => {
      render(<CompositeAlertDialog symbol="AAPL" direction="Bullish" onClose={() => {}} />);
    });

    expect(mockApi.getSymbolRegimeSnapshot).toHaveBeenCalledTimes(1);
    mockApi.getSymbolRegimeSnapshot.mockClear();

    const modelSelect = screen.getByDisplayValue('OMM (daily)');
    await act(async () => {
      fireEvent.change(modelSelect, { target: { value: 'any' } });
    });

    expect(mockApi.getSymbolRegimeSnapshot).not.toHaveBeenCalled();
    expect(screen.queryByText(/Currently:/)).not.toBeInTheDocument();
    expect(screen.queryByText('Loading current regime…')).not.toBeInTheDocument();
    expect(screen.queryByText(/Live regime unavailable/)).not.toBeInTheDocument();
  });
});
