import type {
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  ISeriesApi,
  SeriesAttachedParameter,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { Drawing } from '@/types/overlays';
import type { UpdatablePrimitive } from './types';

class HorizontalLineRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ mediaSize, context: ctx }) => {
      const y = this.series.priceToCoordinate(this.d.points[0].price);
      if (y === null) return;
      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = this.d.width;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(mediaSize.width, y);
      ctx.stroke();
    });
  }
}

class HorizontalLinePaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new HorizontalLineRenderer(this.d, this.series);
  }
}

export class HorizontalLinePrimitive implements UpdatablePrimitive {
  private series: ISeriesApi<'Candlestick'> | null = null;
  private requestUpdateFn?: () => void;

  constructor(private d: Drawing) {}

  attached(param: SeriesAttachedParameter): void {
    this.series = param.series as ISeriesApi<'Candlestick'>;
    this.requestUpdateFn = param.requestUpdate;
    param.requestUpdate();
  }

  update(drawing: Drawing): void {
    this.d = drawing;
    this.requestUpdateFn?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.series) return [];
    return [new HorizontalLinePaneView(this.d, this.series)];
  }
}
