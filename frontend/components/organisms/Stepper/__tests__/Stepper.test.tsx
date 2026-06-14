import { SCREENER_STEPS_STOCKS, getSteps } from '@/components/organisms/Stepper';

describe('SCREENER_STEPS_STOCKS', () => {
  it('has exactly 4 steps ending at step-4-stocks', () => {
    expect(SCREENER_STEPS_STOCKS).toHaveLength(4);
    expect(SCREENER_STEPS_STOCKS.map((s) => s.slug)).toEqual([
      'step-1-regime',
      'step-2-universe',
      'step-3-direction',
      'step-4-stocks',
    ]);
  });

  it('getSteps("stocks") returns the 4-step sequence', () => {
    expect(getSteps('stocks')).toBe(SCREENER_STEPS_STOCKS);
  });
});
