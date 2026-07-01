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

export const ARROW_MARKER_S = 10;     // half-base of triangle in pixels
export const ARROW_MARKER_H = 16;     // height of triangle in pixels
export const ARROW_MARKER_OFFSET = 6; // gap between price pixel and triangle base

class ArrowUpRenderer implements IPrimitivePaneRenderer {
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

      // Triangle points upward, rendered above the price point
      const tipY  = y - ARROW_MARKER_OFFSET - ARROW_MARKER_H;
      const baseY = y - ARROW_MARKER_OFFSET;
      ctx.fillStyle = this.d.color;
      ctx.beginPath();
      ctx.moveTo(x, tipY);
      ctx.lineTo(x - ARROW_MARKER_S, baseY);
      ctx.lineTo(x + ARROW_MARKER_S, baseY);
      ctx.closePath();
      ctx.fill();
    });
  }
}

class ArrowUpPaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}
  renderer(): IPrimitivePaneRenderer | null {
    return new ArrowUpRenderer(this.d, this.chart, this.series);
  }
}

export class ArrowUpPrimitive implements UpdatablePrimitive {
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
    return [new ArrowUpPaneView(this.d, this.chart, this.series)];
  }
}
