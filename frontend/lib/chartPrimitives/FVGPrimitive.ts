import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  IChartApi,
  ISeriesApi,
  SeriesAttachedParameter,
  Time,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { ZoneSignal } from '@/types/structure';

class FVGRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly signal: ZoneSignal,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ mediaSize, context: ctx }) => {
      const toX = (t: string) => this.chart.timeScale().timeToCoordinate(t as Time);
      const toY = (p: number) => this.series.priceToCoordinate(p);

      const x1 = toX(this.signal.time_start);
      const x2 = this.signal.time_end ? toX(this.signal.time_end) : mediaSize.width;
      const yHigh = toY(this.signal.price_high);
      const yLow = toY(this.signal.price_low);

      if (x1 === null || yHigh === null || yLow === null || x2 === null) return;

      const isBullish = this.signal.direction === 'bullish';
      const isMitigated = this.signal.mitigated;
      const isOB = this.signal.kind === 'OrderBlock';
      const alpha = isMitigated ? 0.1 : 0.25;
      const mtfBoost = this.signal.mtf_aligned ? 2 : 1;

      ctx.fillStyle = isBullish
        ? `rgba(76, 175, 80, ${alpha})`
        : `rgba(224, 80, 80, ${alpha})`;

      ctx.strokeStyle = isBullish ? 'rgba(76, 175, 80, 0.6)' : 'rgba(224, 80, 80, 0.6)';
      ctx.lineWidth = mtfBoost;

      if (isMitigated) {
        ctx.setLineDash([4, 4]);
      }

      ctx.fillRect(x1, Math.min(yHigh, yLow), x2 - x1, Math.abs(yHigh - yLow));
      ctx.strokeRect(x1, Math.min(yHigh, yLow), x2 - x1, Math.abs(yHigh - yLow));
      ctx.setLineDash([]);

      if (isOB && !isMitigated) {
        ctx.lineWidth = ctx.lineWidth + 1;
        ctx.strokeRect(x1, Math.min(yHigh, yLow), x2 - x1, Math.abs(yHigh - yLow));
      }
    });
  }
}

class FVGPaneView implements IPrimitivePaneView {
  constructor(
    private readonly signal: ZoneSignal,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new FVGRenderer(this.signal, this.chart, this.series);
  }
}

export class FVGPrimitive implements ISeriesPrimitive {
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
    return [new FVGPaneView(this.signal, this.chart, this.series)];
  }
}
