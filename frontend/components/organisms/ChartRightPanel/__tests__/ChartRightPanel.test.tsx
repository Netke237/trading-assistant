import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import ChartRightPanel from '@/components/organisms/ChartRightPanel';
import { mainSeriesId } from '@/lib/chart/mainSeriesId';

// Regression test for a duplicated-literal bug: this panel used to filter
// the main price series out of the crosshair "indicator values" list via a
// hardcoded `id.startsWith('candles-')`, independently of ChartPane's
// isMainSeriesId — the one place meant to own that convention. The fixture
// below builds the main-series id via mainSeriesId() rather than hardcoding
// the string, so this test actually exercises (and would catch drift in)
// the shared isMainSeriesId this component imports, not just a coincidence
// of two literals matching.
describe('ChartRightPanel — Data tab indicator filtering', () => {
  it('filters the main price series out of the indicator-values list but keeps real indicators', () => {
    render(
      <ChartRightPanel
        crosshairData={{
          time: '2024-01-05',
          open: 100, high: 105, low: 99, close: 102,
          indicators: {
            [mainSeriesId('candle')]: 999.99,
            'ema-20': 50,
          },
        }}
        symbol="AAPL"
        indicatorLabels={{ 'ema-20': 'EMA(20)' }}
      />,
    );

    fireEvent.click(screen.getByText('Data'));

    expect(screen.getByText('EMA(20)')).toBeInTheDocument();
    expect(screen.getByText('50.00')).toBeInTheDocument();
    expect(screen.queryByText('999.99')).not.toBeInTheDocument();
  });
});
