import type {
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  IChartApi,
  ISeriesApi,
  SeriesAttachedParameter,
  Time,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { Drawing } from '@/types/overlays';
import type { UpdatablePrimitive } from './types';

class TrendLineRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const toX = (t: number) => this.chart.timeScale().timeToCoordinate(t as unknown as Time);
      const toY = (p: number) => this.series.priceToCoordinate(p);

      const x0 = toX(this.d.points[0].time);
      const y0 = toY(this.d.points[0].price);
      const x1 = toX(this.d.points[1].time);
      const y1 = toY(this.d.points[1].price);

      if (x0 === null || y0 === null || x1 === null || y1 === null) return;

      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = this.d.width;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
    });
  }
}

class TrendLinePaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new TrendLineRenderer(this.d, this.chart, this.series);
  }
}

export class TrendLinePrimitive implements UpdatablePrimitive {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<'Candlestick'> | null = null;
  private requestUpdateFn?: () => void;

  constructor(private d: Drawing) {}

  attached(param: SeriesAttachedParameter): void {
    this.chart = param.chart;
    this.series = param.series as ISeriesApi<'Candlestick'>;
    this.requestUpdateFn = param.requestUpdate;
    param.requestUpdate();
  }

  update(drawing: Drawing): void {
    this.d = drawing;
    this.requestUpdateFn?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.chart || !this.series) return [];
    return [new TrendLinePaneView(this.d, this.chart, this.series)];
  }
}
