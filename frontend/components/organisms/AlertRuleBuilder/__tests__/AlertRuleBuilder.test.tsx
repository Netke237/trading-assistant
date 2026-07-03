import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import AlertRuleBuilder from '@/components/organisms/AlertRuleBuilder';
import { useChartStore } from '@/lib/chartStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import type { AlertRule } from '@/types/alerts';

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
