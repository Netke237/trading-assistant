import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  ISeriesApi,
  SeriesAttachedParameter,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { FibonacciSignal } from '@/types/structure';

class FibRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly signal: FibonacciSignal,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ mediaSize, context: ctx }) => {
      const toY = (p: number) => this.series.priceToCoordinate(p);
      ctx.font = '9px sans-serif';
      for (const level of this.signal.levels) {
        const y = toY(level.price);
        if (y === null) continue;
        const is618 = Math.abs(level.pct - 0.618) < 0.001;
        ctx.strokeStyle = is618 ? 'rgba(41, 98, 255, 0.7)' : 'rgba(41, 98, 255, 0.35)';
        ctx.lineWidth = is618 ? 2 : 1;
        ctx.setLineDash(is618 ? [] : [4, 4]);
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(mediaSize.width, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(41, 98, 255, 0.9)';
        ctx.fillText(`${(level.pct * 100).toFixed(1)}%`, 4, y - 3);
      }
    });
  }
}

class FibPaneView implements IPrimitivePaneView {
  constructor(
    private readonly signal: FibonacciSignal,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new FibRenderer(this.signal, this.series);
  }
}

export class FibPrimitive implements ISeriesPrimitive {
  private series: ISeriesApi<'Candlestick'> | null = null;

  constructor(private readonly signal: FibonacciSignal) {}

  attached(param: SeriesAttachedParameter): void {
    this.series = param.series as ISeriesApi<'Candlestick'>;
    param.requestUpdate();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.series) return [];
    return [new FibPaneView(this.signal, this.series)];
  }
}
