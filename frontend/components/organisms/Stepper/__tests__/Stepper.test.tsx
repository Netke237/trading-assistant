import { SCREENER_STEPS_STOCKS, SCREENER_STEPS_PREBREAKOUT, getSteps } from '@/components/organisms/Stepper';

describe('SCREENER_STEPS_STOCKS', () => {
  it('has exactly 7 steps ending at step-7-position-card', () => {
    expect(SCREENER_STEPS_STOCKS).toHaveLength(7);
    expect(SCREENER_STEPS_STOCKS.map((s) => s.slug)).toEqual([
      'step-1-regime',
      'step-2-universe',
      'step-3-direction',
      'step-4-stocks',
      'step-5-strategy',
      'step-6-backtest',
      'step-7-position-card',
    ]);
  });

  it('getSteps("stocks") returns the 7-step sequence', () => {
    expect(getSteps('stocks')).toBe(SCREENER_STEPS_STOCKS);
  });
});

describe('SCREENER_STEPS_PREBREAKOUT', () => {
  it('has exactly 4 steps ending at step-4-prebreakout', () => {
    expect(SCREENER_STEPS_PREBREAKOUT).toHaveLength(4);
    expect(SCREENER_STEPS_PREBREAKOUT.map((s) => s.slug)).toEqual([
      'step-1-regime',
      'step-2-universe',
      'step-3-direction',
      'step-4-prebreakout',
    ]);
  });

  it('getSteps("prebreakout") returns the prebreakout sequence', () => {
    expect(getSteps('prebreakout')).toBe(SCREENER_STEPS_PREBREAKOUT);
  });
});
