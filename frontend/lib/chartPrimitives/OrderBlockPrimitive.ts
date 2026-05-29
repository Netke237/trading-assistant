import type {
  ISeriesPrimitive, IPrimitivePaneView, IPrimitivePaneRenderer,
  IChartApi, ISeriesApi, SeriesAttachedParameter, Time,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { ZoneSignal } from '@/types/structure';

class OrderBlockRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly signal: ZoneSignal,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ mediaSize: _ms, context: ctx }) => {
      const toX = (t: string) => this.chart.timeScale().timeToCoordinate(t as Time);
      const toY = (p: number) => this.series.priceToCoordinate(p);

      const x1 = toX(this.signal.time_start);
      const x2 = this.signal.time_end ? toX(this.signal.time_end) : _ms.width;
      const yHigh = toY(this.signal.price_high);
      const yLow  = toY(this.signal.price_low);

      if (x1 === null || x2 === null || yHigh === null || yLow === null) return;

      const isBullish = this.signal.direction === 'bullish';
      const isMitigated = this.signal.mitigated;
      const alpha = isMitigated ? 0.08 : 0.22;

      // Amber (bullish OB) vs Purple (bearish OB) — distinct from FVG green/red
      const fillColor   = isBullish ? `rgba(255, 193, 7, ${alpha})`  : `rgba(156, 39, 176, ${alpha})`;
      const strokeColor = isBullish ? 'rgba(255, 193, 7, 0.9)'       : 'rgba(156, 39, 176, 0.9)';

      ctx.fillStyle   = fillColor;
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = this.signal.mtf_aligned ? 2.5 : 1.5;
      if (isMitigated) ctx.setLineDash([4, 4]);

      ctx.fillRect(x1, Math.min(yHigh, yLow), x2 - x1, Math.abs(yHigh - yLow));
      ctx.strokeRect(x1, Math.min(yHigh, yLow), x2 - x1, Math.abs(yHigh - yLow));
      ctx.setLineDash([]);

      // "OB" label inside the box at the left edge
      if (!isMitigated) {
        ctx.font = 'bold 9px sans-serif';
        ctx.fillStyle = strokeColor;
        const midY = (Math.min(yHigh, yLow) + Math.max(yHigh, yLow)) / 2 + 3;
        ctx.fillText('OB', x1 + 3, midY);
      }
    });
  }
}

class OrderBlockPaneView implements IPrimitivePaneView {
  constructor(
    private readonly signal: ZoneSignal,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}
  renderer() { return new OrderBlockRenderer(this.signal, this.chart, this.series); }
}

export class OrderBlockPrimitive implements ISeriesPrimitive {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<'Candlestick'> | null = null;
  constructor(private readonly signal: ZoneSignal) {}
  attached(param: SeriesAttachedParameter): void {
    this.chart = param.chart;
    this.series = param.series as ISeriesApi<'Candlestick'>;
    param.requestUpdate();
  }
  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.chart || !this.series) return [];
    return [new OrderBlockPaneView(this.signal, this.chart, this.series)];
  }
}
