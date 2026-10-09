import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import AlertRuleBuilder from '@/components/organisms/AlertRuleBuilder';
import { useChartStore } from '@/lib/chartStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import type { AlertRule } from '@/types/alerts';
import {
  REGIME_STATES_OMM, REGIME_STATES_HMM, REGIME_STATES_HMM_DIRECTIONAL, REGIME_STATES_ANY,
} from '@/components/organisms/AlertRuleBuilder/regimeStates';

const AAPL_RULE: AlertRule = {
  id: 'rule-1',
  name: 'AAPL breakout',
  symbol: 'AAPL',
  interval: '1D',
  enabled: true,
  group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 100 }] },
  cooldown_minutes: 60,
  expiry_date: null,
  created_at: '2026-01-01T00:00:00.000Z',
  last_triggered_at: null,
};

beforeEach(() => {
  // Chart is currently showing MSFT, NOT the rule's own symbol (AAPL).
  useChartStore.setState({ symbol: 'MSFT', interval: '5m', activeIndicators: [] } as any);
});

describe('AlertRuleBuilder edit mode', () => {
  it('displays the rule\'s own symbol/interval, not the currently charted symbol', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={AAPL_RULE} />);
    expect(screen.getByText('Symbol: AAPL')).toBeInTheDocument();
    expect(screen.getByText('Interval: 1D')).toBeInTheDocument();
  });

  it('new-rule mode still uses the active chart symbol/interval', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    expect(screen.getByText('Symbol: MSFT')).toBeInTheDocument();
    expect(screen.getByText('Interval: 5m')).toBeInTheDocument();
  });

  it('saving an edit persists the rule\'s OWN symbol, not the active chart symbol', () => {
    const updateRuleSpy = jest.fn();
    useChartAlertStore.setState({ updateRule: updateRuleSpy } as any);
    render(<AlertRuleBuilder onClose={() => {}} editRule={AAPL_RULE} />);
    fireEvent.click(screen.getByText('Save'));
    expect(updateRuleSpy).toHaveBeenCalledWith(
      'rule-1',
      expect.objectContaining({ symbol: 'AAPL', interval: '1D' }),
    );
  });
});

describe('AlertRuleBuilder duplicate mode', () => {
  it('pre-fills from duplicateFrom but creates a new rule on save (not an update)', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} duplicateFrom={{ ...AAPL_RULE, name: 'AAPL breakout (copy)' }} />);
    expect(screen.getByText('Symbol: AAPL')).toBeInTheDocument();
    expect(screen.getByDisplayValue('AAPL breakout (copy)')).toBeInTheDocument();
    // Header must say "New Alert" (create path), not "Edit Alert" — duplicateFrom is not editRule.
    expect(screen.getByText('New Alert')).toBeInTheDocument();
  });

  it('saving a duplicate calls addRule with a NEW id, not updateRule on the original', () => {
    const addRuleSpy = jest.fn().mockReturnValue(true);
    const updateRuleSpy = jest.fn();
    useChartAlertStore.setState({ addRule: addRuleSpy, updateRule: updateRuleSpy } as any);
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} duplicateFrom={{ ...AAPL_RULE, name: 'AAPL breakout (copy)' }} />);
    fireEvent.click(screen.getByText('Create Alert'));
    expect(updateRuleSpy).not.toHaveBeenCalled();
    expect(addRuleSpy).toHaveBeenCalledTimes(1);
    const savedRule = addRuleSpy.mock.calls[0][0];
    expect(savedRule.id).not.toBe('rule-1'); // must be a fresh id, not the original rule's id
    expect(savedRule.symbol).toBe('AAPL');
    expect(savedRule.name).toBe('AAPL breakout (copy)');
  });
});

describe('AlertRuleBuilder regime condition state options', () => {
  it('offers Bull/Bear states when model is switched to "any", not just HMM states', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    fireEvent.click(screen.getByText('+ Regime'));

    // The builder starts with one default price condition (idx 0); "+ Regime"
    // appends the regime condition as the second row (idx 1), so its aria-labels
    // are indexed "2" — labels are per-row-unique so multiple regime conditions
    // in the same rule don't collide.
    const modelSelect = screen.getByLabelText('Regime model 2');
    fireEvent.change(modelSelect, { target: { value: 'any' } });

    const stateSelect = screen.getByLabelText('Regime state 2') as HTMLSelectElement;
    const optionValues = Array.from(stateSelect.options).map((o) => o.value);
    expect(optionValues).toContain('Bull');
    expect(optionValues).toContain('Bear');
    expect(optionValues).toContain('Trending');
    expect(optionValues).toContain('Choppy');
    expect(optionValues).toContain('Mean-reverting');
  });
});

describe('AlertRuleBuilder directional HMM regime model', () => {
  it('offers HMM_directional as a model choice with Bull/Bear/Sideways states', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    fireEvent.click(screen.getByText('+ Regime'));

    const modelSelect = screen.getByLabelText('Regime model 2') as HTMLSelectElement;
    const modelValues = Array.from(modelSelect.options).map((o) => o.value);
    expect(modelValues).toContain('HMM_directional');

    fireEvent.change(modelSelect, { target: { value: 'HMM_directional' } });
    const stateSelect = screen.getByLabelText('Regime state 2') as HTMLSelectElement;
    const stateValues = Array.from(stateSelect.options).map((o) => o.value);
    expect(stateValues).toEqual(['any', 'Bull', 'Bear', 'Sideways']);
  });

  it('labels the conviction input P(stay)% for HMM models, Conv% for OMM', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    fireEvent.click(screen.getByText('+ Regime'));

    const modelSelect = screen.getByLabelText('Regime model 2') as HTMLSelectElement;

    // Default model is OMM.
    expect(screen.getByPlaceholderText('Conv%')).toBeInTheDocument();

    fireEvent.change(modelSelect, { target: { value: 'HMM_directional' } });
    expect(screen.getByPlaceholderText('P(stay)%')).toBeInTheDocument();

    fireEvent.change(modelSelect, { target: { value: 'HMM' } });
    expect(screen.getByPlaceholderText('P(stay)%')).toBeInTheDocument();
  });
});

describe('AlertRuleBuilder condition row keys', () => {
  it('gives every new condition a stable, generated id (not array index)', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    fireEvent.click(screen.getByText('+ Price'));
    useChartStore.setState({ activeIndicators: [{ id: 'ema-custom', type: 'EMA',
      params: { period: 7 }, pane: 'main', color: '#fff' }] });
    fireEvent.click(screen.getByText('+ Indicator'));
    const indicatorOption = screen.getByRole('option', { name: 'EMA(7)' });
    fireEvent.change(indicatorOption.parentElement!, { target: { value: 'EMA(7)' } });

    const addRuleSpy = jest.fn().mockReturnValue(true);
    useChartAlertStore.setState({ addRule: addRuleSpy } as any);
    fireEvent.change(screen.getByPlaceholderText('e.g. AAPL breakout'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('Create Alert'));

    const savedConditions = addRuleSpy.mock.calls[0][0].group.conditions;
    expect(savedConditions).toHaveLength(3); // default price condition + 2 added
    const ids = savedConditions.map((c: any) => c.id);
    expect(new Set(ids).size).toBe(3); // all unique
    expect(ids.every((id: string) => typeof id === 'string' && id.length > 0)).toBe(true);
  });

  it('backfills an id for legacy conditions loaded from a rule with none', () => {
    const legacyRule = {
      ...AAPL_RULE,
      group: { logic: 'AND' as const, conditions: [{ kind: 'price' as const, operator: '>' as const, value: 100 }] },
    };
    const updateRuleSpy = jest.fn();
    useChartAlertStore.setState({ updateRule: updateRuleSpy } as any);
    render(<AlertRuleBuilder onClose={() => {}} editRule={legacyRule} />);
    fireEvent.click(screen.getByText('Save'));

    const savedConditions = updateRuleSpy.mock.calls[0][1].group.conditions;
    expect(savedConditions[0].id).toEqual(expect.any(String));
    expect(savedConditions[0].id.length).toBeGreaterThan(0);
  });

  it('does not remount the condition row when its kind is switched', () => {
    // Regenerating the id on a kind switch would change key={c.id} on the row and
    // force React to unmount/remount it (including the very <select> the user just
    // used, dropping its focus). Capture the row's DOM node before the switch and
    // confirm it's still the SAME node (not detached/replaced) afterward — a direct
    // proof of id (and thus key) stability, not just that some id exists.
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);

    const kindSelect = screen.getByDisplayValue('Price') as HTMLSelectElement;
    // The kind <select> is a direct child of the condition row <div key={c.id}>.
    const rowNode = kindSelect.parentElement as HTMLElement;
    expect(rowNode).toBeTruthy();

    fireEvent.change(kindSelect, { target: { value: 'regime' } });

    expect(rowNode.isConnected).toBe(true);
  });

  it('keeps keyboard focus on the kind <select> after switching kind', () => {
    // Stronger than node-identity: proves the user's focus ring is not dropped.
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    const kindSelect = screen.getByDisplayValue('Price') as HTMLSelectElement;
    kindSelect.focus();
    expect(document.activeElement).toBe(kindSelect);

    fireEvent.change(kindSelect, { target: { value: 'regime' } });

    // Same element instance, still connected, still focused — no remount stole focus.
    const kindSelectAfter = screen.getByDisplayValue('Regime (OMM/HMM)') as HTMLSelectElement;
    expect(kindSelectAfter).toBe(kindSelect);   // node identity (superset of the remount test)
    expect(kindSelectAfter.isConnected).toBe(true);
    expect(document.activeElement).toBe(kindSelectAfter);  // focus specifically survived
  });
});

describe('AlertRuleBuilder N-of-M threshold seeding (two-sided clamp)', () => {
  // Mirrors the component's seed-time clamp: Math.max(1, Math.min(conditions.length, seed?.group.n_of_m_threshold ?? 1)).
  // A corrupted/legacy stored rule can have n_of_m_threshold <= 0 (lower bound) or
  // greater than its own condition count (upper bound, now also rejected by the
  // backend's 422 validator) -- both must be clamped when the editor is first opened,
  // not just on the input's own onChange.
  const twoConditionRule = (n_of_m_threshold: number): AlertRule => ({
    ...AAPL_RULE,
    group: {
      logic: 'N_OF_M',
      n_of_m_threshold,
      conditions: [
        { kind: 'price', operator: '>', value: 100 },
        { kind: 'price', operator: '<', value: 200 },
      ],
    },
  });

  // The N-of-M number input has no unique label/placeholder, so it's located via its
  // fixed DOM position next to the "of N conditions met" text within the same row.
  const getThresholdInput = (): HTMLInputElement => {
    const metLabel = screen.getByText(/conditions met/);
    return metLabel.parentElement!.querySelector('input') as HTMLInputElement;
  };

  it('seeding with n_of_m_threshold: 0 initializes the input at 1', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={twoConditionRule(0)} />);
    expect(getThresholdInput().value).toBe('1');
  });

  it('seeding with a threshold negative also clamps up to 1', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={twoConditionRule(-3)} />);
    expect(getThresholdInput().value).toBe('1');
  });

  it('seeding with a threshold greater than the condition count clamps down to the count', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={twoConditionRule(5)} />);
    expect(getThresholdInput().value).toBe('2');
  });

  it('seeding with a valid in-range threshold leaves it unchanged', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={twoConditionRule(2)} />);
    expect(getThresholdInput().value).toBe('2');
  });
});

describe('regime dropdown fireability', () => {
  it('each model offers exactly its real emittable states (guards the old "Sideways" phantom bug)', () => {
    // Hard-coded expectations, independent of the consts under test — a phantom state
    // added to any list (e.g. re-adding "Sideways" to HMM) makes the corresponding
    // assertion fail, which a tautological self-comparison could not catch.
    expect(REGIME_STATES_OMM).toEqual(['any', 'Bull', 'Bear', 'Choppy']);
    expect(REGIME_STATES_HMM).toEqual(['any', 'Trending', 'Choppy', 'Mean-reverting']);
    expect(REGIME_STATES_HMM_DIRECTIONAL).toEqual(['any', 'Bull', 'Bear', 'Sideways']);
  });

  it('the "any" state list is exactly the de-duplicated union of the three model lists', () => {
    // Under model='any' the backend checks every model, so every union state is
    // producible by at least one model — none are un-fireable. This asserts ANY has
    // no extra (un-fireable) state and omits none.
    const union = Array.from(new Set([
      ...REGIME_STATES_OMM, ...REGIME_STATES_HMM, ...REGIME_STATES_HMM_DIRECTIONAL,
    ]));
    expect(REGIME_STATES_ANY).toEqual(union);
  });
});

describe('stable indicator references', () => {
  it('saves parameters in semantic order rather than a chart id', () => {
    const addRule = jest.fn().mockReturnValue(true);
    useChartAlertStore.setState({ addRule } as any);
    useChartStore.setState({ activeIndicators: [{ id: 'macd-12345', type: 'MACD',
      params: { signal: 4, slow: 12, fast: 5 }, pane: 'sub', color: '#fff' }] });
    render(<AlertRuleBuilder onClose={() => {}} duplicateFrom={{ ...AAPL_RULE,
      group: { logic: 'AND', conditions: [{ kind: 'indicator', indicator: '', operator: '>', value: 0 }] } }} />);
    const option = screen.getByRole('option', { name: 'MACD(5,12,4)' });
    fireEvent.change(option.parentElement!, { target: { value: 'MACD(5,12,4)' } });
    fireEvent.click(screen.getByText('Create Alert'));
    expect(addRule.mock.calls[0][0].group.conditions[0].indicator).toBe('MACD(5,12,4)');
  });

  it('keeps saved parameters selectable after the chart indicator is removed', () => {
    const updateRule = jest.fn();
    useChartAlertStore.setState({ updateRule } as any);
    render(<AlertRuleBuilder onClose={() => {}} editRule={{ ...AAPL_RULE,
      group: { logic: 'AND', conditions: [{ kind: 'indicator', indicator: 'EMA(7)', operator: '>', value: 0 }] } }} />);
    expect(screen.getByRole('option', { name: 'EMA(7)' })).toBeInTheDocument();
    fireEvent.click(screen.getByText('Save'));
    expect(updateRule.mock.calls[0][1].group.conditions[0].indicator).toBe('EMA(7)');
  });
});


test('empty indicator selections cannot create an inert rule', () => {
  const addRule = jest.fn().mockReturnValue(true);
  useChartAlertStore.setState({ addRule } as any);
  render(<AlertRuleBuilder onClose={() => {}} duplicateFrom={{ ...AAPL_RULE,
    group: { logic: 'AND', conditions: [{ kind: 'indicator', indicator: '', operator: '>', value: 0 }] } }} />);
  fireEvent.click(screen.getByText('Create Alert'));
  expect(addRule).not.toHaveBeenCalled();
  expect(screen.getByText('Select a supported indicator for every indicator condition')).toBeInTheDocument();
});
