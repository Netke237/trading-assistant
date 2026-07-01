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
import { ARROW_MARKER_S as S, ARROW_MARKER_H as H, ARROW_MARKER_OFFSET as OFFSET } from './ArrowUpPrimitive';

class ArrowDownRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const x = this.chart.timeScale().timeToCoordinate(this.d.points[0].time as unknown as Time);
      const y = this.series.priceToCoordinate(this.d.points[0].price);
      if (x == null || y == null) return;

      // Triangle points downward, rendered below the price point
      const tipY  = y + OFFSET + H;
      const baseY = y + OFFSET;
      ctx.fillStyle = this.d.color;
      ctx.beginPath();
      ctx.moveTo(x, tipY);
      ctx.lineTo(x - S, baseY);
      ctx.lineTo(x + S, baseY);
      ctx.closePath();
      ctx.fill();
    });
  }
}

class ArrowDownPaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}
  renderer(): IPrimitivePaneRenderer | null {
    return new ArrowDownRenderer(this.d, this.chart, this.series);
  }
}

export class ArrowDownPrimitive implements UpdatablePrimitive {
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
    return [new ArrowDownPaneView(this.d, this.chart, this.series)];
  }
}
