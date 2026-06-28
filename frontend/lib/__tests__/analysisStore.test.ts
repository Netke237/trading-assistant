import { useAnalysisStore, _horizonEnum } from '@/lib/analysisStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { analyzeStock: jest.fn() } }));

describe('analysisStore', () => {
  beforeEach(() => {
    useAnalysisStore.setState({ symbol: '', result: null, loading: false, error: null });
    (api.analyzeStock as jest.Mock).mockReset();
  });

  it('maps display horizon labels to the backend enum', () => {
    expect(_horizonEnum('Swing (5–15d)')).toBe('Swing');
    expect(_horizonEnum('Position (1–6m)')).toBe('Position');
    expect(_horizonEnum('Intraday')).toBe('Intraday');
    expect(_horizonEnum('weird')).toBe('Swing');   // safe default
  });

  it('sets result on success and uppercases symbol', async () => {
    (api.analyzeStock as jest.Mock).mockResolvedValue({ symbol: 'AMD', stock_score: 55 });
    await useAnalysisStore.getState().analyze('amd');
    const s = useAnalysisStore.getState();
    expect((api.analyzeStock as jest.Mock).mock.calls[0][0].symbol).toBe('AMD');
    expect(s.result?.stock_score).toBe(55);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it('sets error on failure', async () => {
    (api.analyzeStock as jest.Mock).mockRejectedValue(new Error('404: No usable data for ZZZZ'));
    await useAnalysisStore.getState().analyze('ZZZZ');
    const s = useAnalysisStore.getState();
    expect(s.result).toBeNull();
    expect(s.error).toContain('No usable data');
    expect(s.loading).toBe(false);
  });
});
