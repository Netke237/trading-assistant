import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  SeriesAttachedParameter,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';

export interface PreviewState {
  kind: 'trendline' | 'rect' | 'arrow' | 'circle' | null;
  origin: { x: number; y: number } | null; // pixels
  cursor: { x: number; y: number } | null; // pixels
}

class PreviewRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly state: PreviewState) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const { origin, cursor, kind } = this.state;
      if (!origin) return;

      // origin cross
      ctx.strokeStyle = 'rgba(255,255,255,0.9)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(origin.x - 6, origin.y);
      ctx.lineTo(origin.x + 6, origin.y);
      ctx.moveTo(origin.x, origin.y - 6);
      ctx.lineTo(origin.x, origin.y + 6);
      ctx.stroke();

      if (!cursor || !kind) return;

      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = 'rgba(255,255,255,0.6)';

      if (kind === 'trendline' || kind === 'arrow' || kind === 'circle') {
        ctx.beginPath();
        ctx.moveTo(origin.x, origin.y);
        ctx.lineTo(cursor.x, cursor.y);
        ctx.stroke();
      } else {
        // rect
        const x = Math.min(origin.x, cursor.x);
        const y = Math.min(origin.y, cursor.y);
        ctx.strokeRect(x, y, Math.abs(cursor.x - origin.x), Math.abs(cursor.y - origin.y));
      }

      ctx.setLineDash([]);
    });
  }
}

class PreviewPaneView implements IPrimitivePaneView {
  constructor(private readonly state: PreviewState) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new PreviewRenderer(this.state);
  }
}

export class PreviewPrimitive implements ISeriesPrimitive {
  private requestUpdate?: () => void;

  state: PreviewState = { kind: null, origin: null, cursor: null };

  attached(param: SeriesAttachedParameter): void {
    this.requestUpdate = param.requestUpdate;
  }

  setState(next: PreviewState): void {
    this.state = next;
    this.requestUpdate?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.state.origin) return [];
    return [new PreviewPaneView(this.state)];
  }
}
