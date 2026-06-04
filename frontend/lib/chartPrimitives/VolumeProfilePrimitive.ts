import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  ISeriesApi,
  SeriesAttachedParameter,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { VolumeProfile } from '@/types/overlays';

class VPRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly vp: VolumeProfile,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ mediaSize, context: ctx }) => {
      const toY = (p: number) => this.series.priceToCoordinate(p);
      const maxV = Math.max(...this.vp.bins.map((b) => b.volume), 1);
      const maxW = mediaSize.width * 0.25;
      const binPx =
        this.vp.bins.length > 1
          ? Math.abs(
              (toY(this.vp.bins[1].price) ?? 0) -
                (toY(this.vp.bins[0].price) ?? 0),
            )
          : 4;
      for (const b of this.vp.bins) {
        const y = toY(b.price);
        if (y === null) continue;
        const w = (b.volume / maxV) * maxW;
        const isPoc =
          this.vp.poc !== null && Math.abs(b.price - this.vp.poc) < 1e-9;
        ctx.fillStyle = isPoc
          ? 'rgba(224,160,48,0.55)'
          : 'rgba(90,106,207,0.45)';
        ctx.fillRect(
          mediaSize.width - w,
          y - binPx / 2,
          w,
          Math.max(1, binPx - 1),
        );
      }
    });
  }
}

class VPView implements IPrimitivePaneView {
  constructor(
    private readonly vp: VolumeProfile,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new VPRenderer(this.vp, this.series);
  }
}

export class VolumeProfilePrimitive implements ISeriesPrimitive {
  private series: ISeriesApi<'Candlestick'> | null = null;

  constructor(private readonly vp: VolumeProfile) {}

  attached(param: SeriesAttachedParameter): void {
    this.series = param.series as ISeriesApi<'Candlestick'>;
    param.requestUpdate();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.series) return [];
    return [new VPView(this.vp, this.series)];
  }
}
