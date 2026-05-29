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
import type { LineSignal } from '@/types/structure';

class BOSRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly signal: LineSignal,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const toX = (t: string) => this.chart.timeScale().timeToCoordinate(t as Time);
      const toY = (p: number) => this.series.priceToCoordinate(p);

      const xStart = toX(this.signal.time);
      const y = toY(this.signal.price);
      if (xStart === null || y === null) return;

      // Use time_end if provided, else extend a fixed 200px from signal
      const xEnd = this.signal.time_end
        ? (toX(this.signal.time_end) ?? (xStart + 200))
        : (xStart + 200);

      const isBullish = this.signal.direction === 'bullish';
      const isCHoCH = this.signal.kind === 'CHoCH';
      const color = isCHoCH ? (isBullish ? '#ff9800' : '#e65100') : (isBullish ? '#4caf50' : '#e05050');

      ctx.strokeStyle = color;
      ctx.lineWidth = this.signal.mtf_aligned ? 3 : 2;
      ctx.setLineDash([6, 3]);
      ctx.beginPath();
      ctx.moveTo(xStart, y);
      ctx.lineTo(xEnd, y);
      ctx.stroke();
      ctx.setLineDash([]);

      const label = this.signal.kind;
      ctx.font = '10px sans-serif';
      ctx.fillStyle = color;
      ctx.fillText(label, xStart + 4, y - 4);
    });
  }
}

class BOSPaneView implements IPrimitivePaneView {
  constructor(
    private readonly signal: LineSignal,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new BOSRenderer(this.signal, this.chart, this.series);
  }
}

export class BOSPrimitive implements ISeriesPrimitive {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<'Candlestick'> | null = null;

  constructor(private readonly signal: LineSignal) {}

  attached(param: SeriesAttachedParameter): void {
    this.chart = param.chart;
    this.series = param.series as ISeriesApi<'Candlestick'>;
    param.requestUpdate();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.chart || !this.series) return [];
    return [new BOSPaneView(this.signal, this.chart, this.series)];
  }
}
