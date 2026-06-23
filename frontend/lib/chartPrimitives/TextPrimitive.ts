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

class TextRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const p = this.d.points[0];
      const x = this.chart.timeScale().timeToCoordinate(p.time as unknown as Time);
      const y = this.series.priceToCoordinate(p.price);
      if (x === null || y === null) return;

      const label = this.d.text ?? '';
      ctx.font = '12px sans-serif';
      const w = ctx.measureText(label).width;

      ctx.fillStyle = 'rgba(20,24,40,0.85)';
      ctx.fillRect(x, y - 16, w + 10, 18);
      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = 1;
      ctx.strokeRect(x, y - 16, w + 10, 18);

      ctx.fillStyle = '#fff';
      ctx.fillText(label, x + 5, y - 3);
    });
  }
}

class TextPaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new TextRenderer(this.d, this.chart, this.series);
  }
}

export class TextPrimitive implements UpdatablePrimitive {
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
    return [new TextPaneView(this.d, this.chart, this.series)];
  }
}
