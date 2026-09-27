import '@testing-library/jest-dom';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { CompositeAlertDialog } from '@/components/organisms/CompositeAlertDialog';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    getCompositeWatchDefaults: jest.fn(),
    getSymbolRegimeSnapshot: jest.fn(),
    addCompositeWatch: jest.fn(),
    addCompositeAlertRule: jest.fn(),
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

describe('CompositeAlertDialog — delivery mode', () => {
  it('defaults to Watch mode and calls addCompositeWatch on save', async () => {
    mockApi.getSymbolRegimeSnapshot.mockResolvedValue(SNAPSHOT as any);
    mockApi.addCompositeWatch.mockResolvedValue({} as any);

    await act(async () => {
      render(<CompositeAlertDialog symbol="AAPL" direction="Bullish" onClose={() => {}} />);
    });

    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    await act(async () => {});

    expect(mockApi.addCompositeWatch).toHaveBeenCalled();
    expect(mockApi.addCompositeAlertRule).not.toHaveBeenCalled();
  });

  it('in Rule mode calls addCompositeAlertRule with a name', async () => {
    mockApi.getSymbolRegimeSnapshot.mockResolvedValue(SNAPSHOT as any);
    mockApi.addCompositeAlertRule.mockResolvedValue({} as any);

    await act(async () => {
      render(<CompositeAlertDialog symbol="AAPL" direction="Bullish" onClose={() => {}} />);
    });

    fireEvent.click(screen.getByRole('button', { name: /Rule \(live\)/ }));
    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    await act(async () => {});

    expect(mockApi.addCompositeAlertRule).toHaveBeenCalledWith(
      expect.any(String), 'AAPL', expect.any(String), expect.any(Object),
    );
  });

  it('includes the alert direction inside trigger_def for both Watch and Rule modes', async () => {
    // Regression: the backend's strategy_confirmations gate reads direction from
    // INSIDE trigger_def (td.get("direction") or "Bullish"), not from a sibling
    // API param. Omitting it here silently forces every mean-reversion
    // confirmation to evaluate as Bullish regardless of the alert's real direction.
    mockApi.getSymbolRegimeSnapshot.mockResolvedValue(SNAPSHOT as any);
    mockApi.addCompositeWatch.mockResolvedValue({} as any);

    await act(async () => {
      render(<CompositeAlertDialog symbol="TSLA" direction="Bearish" onClose={() => {}} />);
    });

    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    await act(async () => {});

    const triggerDef = mockApi.addCompositeWatch.mock.calls[0][1];
    expect(triggerDef.direction).toBe('Bearish');
  });
});

describe('CompositeAlertDialog — A4f interval follows the model', () => {
  async function renderDialog() {
    mockApi.getSymbolRegimeSnapshot.mockResolvedValue(SNAPSHOT as any);
    mockApi.addCompositeWatch.mockResolvedValue({} as any);
    mockApi.addCompositeAlertRule.mockResolvedValue({} as any);
    await act(async () => {
      render(<CompositeAlertDialog symbol="AAPL" direction="Bullish" onClose={() => {}} />);
    });
  }
  const modelSelect = () => screen.getAllByRole('combobox')[0] as HTMLSelectElement;
  const intervalSelect = () => screen.getAllByRole('combobox')[1] as HTMLSelectElement;
  async function pickModel(v: string) {
    await act(async () => { fireEvent.change(modelSelect(), { target: { value: v } }); });
  }
  async function save() {
    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    await act(async () => {});
  }

  it('FE1 watch: HMM_intraday untouched displays and saves 5min (was: displayed 5m, saved 1D; W2-INTERVAL: chart spelling)', async () => {
    await renderDialog();
    await pickModel('HMM_intraday');
    expect(intervalSelect().value).toBe('5min');
    await save();
    expect(mockApi.addCompositeWatch.mock.calls[0][3]).toBe('5min');
  });

  it('FE1 rule: HMM_intraday untouched saves the rule at 5min', async () => {
    await renderDialog();
    fireEvent.click(screen.getByRole('button', { name: /Rule \(live\)/ }));
    await pickModel('HMM_intraday');
    await save();
    expect(mockApi.addCompositeAlertRule.mock.calls[0][2]).toBe('5min');
  });

  it('FE2: switching HMM_intraday back to OMM saves 1D', async () => {
    await renderDialog();
    await pickModel('HMM_intraday');
    fireEvent.change(intervalSelect(), { target: { value: '1h' } });
    await pickModel('OMM');
    await save();
    expect(mockApi.addCompositeWatch.mock.calls[0][3]).toBe('1D');
  });

  it('FE3: the snapshot after switching to HMM_intraday is fetched at 5min', async () => {
    await renderDialog();
    await pickModel('HMM_intraday');
    expect(mockApi.getSymbolRegimeSnapshot).toHaveBeenLastCalledWith('AAPL', 'HMM_intraday', 'Bullish', '5min');
  });

  it('W2-INTERVAL: the Interval select offers exactly the chart spellings', async () => {
    await renderDialog();
    await pickModel('HMM_intraday');
    const values = Array.from(intervalSelect().options).map((o) => o.value);
    expect(values).toEqual(['5min', '15min', '30min', '1h', '4h']);
  });

  it('W2-INTERVAL: a picked 15min is saved as 15min on the rule', async () => {
    await renderDialog();
    fireEvent.click(screen.getByRole('button', { name: /Rule \(live\)/ }));
    await pickModel('HMM_intraday');
    await act(async () => { fireEvent.change(intervalSelect(), { target: { value: '15min' } }); });
    await save();
    expect(mockApi.addCompositeAlertRule.mock.calls[0][2]).toBe('15min');
  });

  it('FE4: a user-picked interval is saved as picked', async () => {
    await renderDialog();
    await pickModel('HMM_intraday');
    await act(async () => { fireEvent.change(intervalSelect(), { target: { value: '1h' } }); });
    expect(intervalSelect().value).toBe('1h');
    await save();
    expect(mockApi.addCompositeWatch.mock.calls[0][3]).toBe('1h');
  });
});
