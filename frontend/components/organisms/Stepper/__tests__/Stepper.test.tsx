import {
  SCREENER_STEPS_OPTIONS,
  SCREENER_STEPS_STOCKS,
  SCREENER_STEPS_PREBREAKOUT,
  SCREENER_STEPS,
  getSteps,
  currentStepFromPath,
} from '@/components/organisms/Stepper';

describe('SCREENER_STEPS_OPTIONS (T5)', () => {
  it('has exactly 7 steps ending at step-7-trade-card', () => {
    expect(SCREENER_STEPS_OPTIONS).toHaveLength(7);
    expect(SCREENER_STEPS_OPTIONS.map((s) => s.slug)).toEqual([
      'step-1-regime',
      'step-2-universe',
      'step-3-direction',
      'step-4-ranking',
      'step-5-vol-events',
      'step-6-contracts',
      'step-7-trade-card',
    ]);
  });

  it('getSteps("options") returns the 7-step sequence', () => {
    expect(getSteps('options')).toBe(SCREENER_STEPS_OPTIONS);
  });

  it('SCREENER_STEPS backward-compat alias points at SCREENER_STEPS_OPTIONS', () => {
    expect(SCREENER_STEPS).toBe(SCREENER_STEPS_OPTIONS);
  });

  it('getSteps falls back to SCREENER_STEPS_OPTIONS for an unrecognized mode', () => {
    expect(getSteps('bogus-mode' as any)).toBe(SCREENER_STEPS_OPTIONS);
  });
});

describe('SCREENER_STEPS_STOCKS', () => {
  it('has exactly 6 steps: Step 5 (Strategy) merged into Step 4 (STOCKS-STEP-MERGE-S1)', () => {
    expect(SCREENER_STEPS_STOCKS).toHaveLength(6);
    expect(SCREENER_STEPS_STOCKS.map((s) => s.slug)).toEqual([
      'step-1-regime', 'step-2-universe', 'step-3-direction',
      'step-4-stocks', 'step-6-backtest', 'step-7-position-card',
    ]);
    expect(SCREENER_STEPS_STOCKS.map((s) => s.index)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(SCREENER_STEPS_STOCKS[3].label).toBe('Strategy');
  });

  it('getSteps("stocks") returns the 6-step sequence', () => {
    expect(getSteps('stocks')).toBe(SCREENER_STEPS_STOCKS);
  });
});

describe('currentStepFromPath — resolves the step INDEX by slug in the active list', () => {
  it('Stocks: step-6-backtest is step 5, step-7-position-card is step 6', () => {
    expect(currentStepFromPath('/screener/step-6-backtest', SCREENER_STEPS_STOCKS)).toBe(5);
    expect(currentStepFromPath('/screener/step-7-position-card', SCREENER_STEPS_STOCKS)).toBe(6);
    expect(currentStepFromPath('/screener/step-4-stocks', SCREENER_STEPS_STOCKS)).toBe(4);
  });

  it('Options: step-6-contracts is still step 6', () => {
    expect(currentStepFromPath('/screener/step-6-contracts', SCREENER_STEPS_OPTIONS)).toBe(6);
  });

  it('with no list (or a slug not in it), falls back to the slug digit', () => {
    expect(currentStepFromPath('/screener/step-6-backtest')).toBe(6);
    expect(currentStepFromPath('/screener/step-7-position-card')).toBe(7);
    expect(currentStepFromPath('/screener/step-5-vol-events', SCREENER_STEPS_STOCKS)).toBe(5);
  });

  it('returns 1 for a null or non-step pathname', () => {
    expect(currentStepFromPath(null, SCREENER_STEPS_STOCKS)).toBe(1);
    expect(currentStepFromPath('/dashboard', SCREENER_STEPS_STOCKS)).toBe(1);
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
