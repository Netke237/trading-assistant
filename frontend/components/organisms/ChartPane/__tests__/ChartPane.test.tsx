import { render } from '@testing-library/react';
import { createChart } from 'lightweight-charts';
import ChartPane from '@/components/organisms/ChartPane';
import { useThemeStore } from '@/lib/theme';

const TOKENS: Record<string, string> = {
  '--bg-surface': '#FFFFFF',
  '--border-subtle': '#DDE1F0',
  '--text-secondary': '#5A6070',
  '--pass': '#1A9188',
  '--reject': '#D32F2F',
};

function mockComputedStyle(tokens: Record<string, string>) {
  jest.spyOn(window, 'getComputedStyle').mockReturnValue({
    getPropertyValue: (name: string) => tokens[name] ?? '',
  } as unknown as CSSStyleDeclaration);
}

describe('ChartPane — theme token colors', () => {
  beforeEach(() => {
    (createChart as jest.Mock).mockClear();
  });

  it('reads chart background/grid/text colors from CSS tokens instead of hardcoded hex', () => {
    mockComputedStyle(TOKENS);
    render(<ChartPane series={[]} />);

    const [, options] = (createChart as jest.Mock).mock.calls[0];
    expect(options.layout.background.color).toBe('#FFFFFF');
    expect(options.layout.textColor).toBe('#5A6070');
    expect(options.grid.vertLines.color).toBe('#DDE1F0');
    expect(options.grid.horzLines.color).toBe('#DDE1F0');
  });

  it('applies pass/reject tokens to a candlestick series instead of hardcoded green/red', () => {
    mockComputedStyle(TOKENS);
    render(
      <ChartPane
        series={[{ id: 'main', type: 'Candlestick', data: [] }]}
      />,
    );

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const [, seriesOptions] = chart.addSeries.mock.calls[0];
    expect(seriesOptions.upColor).toBe('#1A9188');
    expect(seriesOptions.downColor).toBe('#D32F2F');
  });

  it('falls back to the dark default palette when a token is unset', () => {
    mockComputedStyle({});
    render(<ChartPane series={[]} />);

    const [, options] = (createChart as jest.Mock).mock.calls[0];
    expect(options.layout.background.color).toBe('#0b0b14');
  });

  it('live-restyles the existing chart on a theme toggle instead of recreating it', () => {
    mockComputedStyle(TOKENS);
    useThemeStore.setState({ theme: 'dark' });
    const { rerender } = render(
      <ChartPane series={[{ id: 'main', type: 'Candlestick', data: [] }]} />,
    );
    const chart = (createChart as jest.Mock).mock.results[0].value;
    const candleSeries = chart.addSeries.mock.results[0].value;

    mockComputedStyle({ ...TOKENS, '--pass': '#00FF00', '--reject': '#FF0000' });
    useThemeStore.setState({ theme: 'light' });
    rerender(<ChartPane series={[{ id: 'main', type: 'Candlestick', data: [] }]} />);

    // No teardown/recreate — ChartWorkspace's overlays/drawings/drag-handlers
    // stay bound to this exact chart+series instance across a theme toggle.
    expect(createChart).toHaveBeenCalledTimes(1);
    expect(chart.remove).not.toHaveBeenCalled();
    expect(chart.applyOptions).toHaveBeenCalledWith(
      expect.objectContaining({
        layout: expect.objectContaining({ background: { color: TOKENS['--bg-surface'] } }),
      }),
    );
    expect(candleSeries.applyOptions).toHaveBeenCalledWith(
      expect.objectContaining({ upColor: '#00FF00', downColor: '#FF0000' }),
    );
  });

  it('restyles an uncolored Line series on theme toggle but leaves an explicitly-colored one alone', () => {
    mockComputedStyle(TOKENS);
    useThemeStore.setState({ theme: 'dark' });
    const { rerender } = render(
      <ChartPane
        series={[
          { id: 'default-line', type: 'Line', data: [] },
          { id: 'custom-line', type: 'Line', data: [], color: '#AB12CD' },
        ]}
      />,
    );
    const chart = (createChart as jest.Mock).mock.results[0].value;
    const defaultLineSeries = chart.addSeries.mock.results[0].value;
    const customLineSeries = chart.addSeries.mock.results[1].value;

    mockComputedStyle({ ...TOKENS, '--pass': '#00FF00' });
    useThemeStore.setState({ theme: 'light' });
    rerender(
      <ChartPane
        series={[
          { id: 'default-line', type: 'Line', data: [] },
          { id: 'custom-line', type: 'Line', data: [], color: '#AB12CD' },
        ]}
      />,
    );

    expect(defaultLineSeries.applyOptions).toHaveBeenCalledWith(
      expect.objectContaining({ color: '#00FF00' }),
    );
    expect(customLineSeries.applyOptions).not.toHaveBeenCalled();
  });
});
