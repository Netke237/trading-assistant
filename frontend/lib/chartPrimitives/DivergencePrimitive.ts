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
import type { DivergenceSignal } from '@/types/structure';

class DivRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly signal: DivergenceSignal,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const toX = (t: string) => this.chart.timeScale().timeToCoordinate(t as Time);
      const toY = (p: number) => this.series.priceToCoordinate(p);

      const x1 = toX(this.signal.time_start);
      const x2 = toX(this.signal.time_end);
      const y1 = toY(this.signal.price_start);
      const y2 = toY(this.signal.price_end);
      if (x1 === null || x2 === null || y1 === null || y2 === null) return;

      const isBullish = this.signal.direction === 'bullish';
      const color = isBullish ? '#4caf50' : '#e05050';
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.font = '10px sans-serif';
      ctx.fillStyle = color;
      ctx.fillText(`${this.signal.indicator} ${this.signal.divergence_type}`, x2 + 5, y2);
    });
  }
}

class DivPaneView implements IPrimitivePaneView {
  constructor(
    private readonly signal: DivergenceSignal,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new DivRenderer(this.signal, this.chart, this.series);
  }
}

export class DivergencePrimitive implements ISeriesPrimitive {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<'Candlestick'> | null = null;

  constructor(private readonly signal: DivergenceSignal) {}

  attached(param: SeriesAttachedParameter): void {
    this.chart = param.chart;
    this.series = param.series as ISeriesApi<'Candlestick'>;
    param.requestUpdate();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.chart || !this.series) return [];
    return [new DivPaneView(this.signal, this.chart, this.series)];
  }
}
