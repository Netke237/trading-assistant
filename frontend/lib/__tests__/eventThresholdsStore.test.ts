import { useEventThresholdsStore, FALLBACK } from '@/lib/eventThresholdsStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { getEventThresholds: jest.fn() } }));

describe('eventThresholdsStore', () => {
  beforeEach(() => {
    (api.getEventThresholds as jest.Mock).mockReset();
    useEventThresholdsStore.setState({ thresholds: FALLBACK, loaded: false });
  });

  it('adopts the fetched thresholds on a successful fetch', async () => {
    const live = { Swing: { reject_days: 5, caution_days: 10 } };
    (api.getEventThresholds as jest.Mock).mockResolvedValue(live);

    await useEventThresholdsStore.getState().fetch();

    expect(useEventThresholdsStore.getState().thresholds).toEqual(live);
    expect(useEventThresholdsStore.getState().loaded).toBe(true);
  });

  it('keeps serving FALLBACK when the fetch fails, and still marks loaded', async () => {
    // This is the entire reason FALLBACK exists — if this silently stopped
    // being exercised, a network failure would leave the store's `thresholds`
    // in whatever state a broken fetch left it in, not the safe default.
    (api.getEventThresholds as jest.Mock).mockRejectedValue(new Error('network down'));

    await useEventThresholdsStore.getState().fetch();

    expect(useEventThresholdsStore.getState().thresholds).toEqual(FALLBACK);
    expect(useEventThresholdsStore.getState().loaded).toBe(true);
  });
});
