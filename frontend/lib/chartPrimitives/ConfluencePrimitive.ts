import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  ISeriesApi,
  SeriesAttachedParameter,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { ConfluenceSignal } from '@/types/structure';

class ConfluenceRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly signal: ConfluenceSignal,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    if (this.signal.score < 70) return;
    target.useMediaCoordinateSpace(({ mediaSize, context: ctx }) => {
      const toY = (p: number) => this.series.priceToCoordinate(p);
      const yHigh = toY(this.signal.price_high);
      const yLow = toY(this.signal.price_low);
      if (yHigh === null || yLow === null) return;

      const alpha = Math.min(0.4, this.signal.score / 100);
      ctx.fillStyle = `rgba(255, 152, 0, ${alpha})`;
      ctx.fillRect(0, Math.min(yHigh, yLow), mediaSize.width, Math.abs(yHigh - yLow));
      ctx.strokeStyle = 'rgba(255, 152, 0, 0.8)';
      ctx.lineWidth = 2;
      ctx.strokeRect(0, Math.min(yHigh, yLow), mediaSize.width, Math.abs(yHigh - yLow));

      ctx.font = 'bold 11px sans-serif';
      ctx.fillStyle = '#ff9800';
      ctx.fillText(`Confluence ${this.signal.score}`, 8, Math.min(yHigh, yLow) - 4);
    });
  }
}

class ConfluencePaneView implements IPrimitivePaneView {
  constructor(
    private readonly signal: ConfluenceSignal,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new ConfluenceRenderer(this.signal, this.series);
  }
}

export class ConfluencePrimitive implements ISeriesPrimitive {
  private series: ISeriesApi<'Candlestick'> | null = null;

  constructor(private readonly signal: ConfluenceSignal) {}

  attached(param: SeriesAttachedParameter): void {
    this.series = param.series as ISeriesApi<'Candlestick'>;
    param.requestUpdate();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.series) return [];
    return [new ConfluencePaneView(this.signal, this.series)];
  }
}
