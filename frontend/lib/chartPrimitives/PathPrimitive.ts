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

class PathRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const toX = (t: number) => this.chart.timeScale().timeToCoordinate(t as unknown as Time);
      const toY = (p: number) => this.series.priceToCoordinate(p);

      const pts = this.d.points
        .map((pt) => ({ x: toX(pt.time), y: toY(pt.price) }))
        .filter(
          (pt): pt is { x: ReturnType<typeof toX>; y: ReturnType<typeof toY> } =>
            pt.x != null && pt.y != null,
        );

      if (pts.length < 2) return;

      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = this.d.width;
      ctx.beginPath();
      ctx.moveTo(pts[0].x as unknown as number, pts[0].y as unknown as number);
      for (let i = 1; i < pts.length; i++) {
        ctx.lineTo(pts[i].x as unknown as number, pts[i].y as unknown as number);
      }
      ctx.stroke();
    });
  }
}

class PathPaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}
  renderer(): IPrimitivePaneRenderer | null {
    return new PathRenderer(this.d, this.chart, this.series);
  }
}

export class PathPrimitive implements UpdatablePrimitive {
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
    return [new PathPaneView(this.d, this.chart, this.series)];
  }
}
