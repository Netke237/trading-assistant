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
