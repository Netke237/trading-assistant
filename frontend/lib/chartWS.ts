import type { Candle } from './indicators';
import type { StructureSignal } from '@/types/structure';
import type { AlertHistory } from '@/types/alerts';

export type ConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'error';

export type WSMessage =
  | { type: 'history'; candles: Candle[] }
  | { type: 'tick'; data: { symbol: string; price: number; volume: number; timestamp: string } }
  | { type: 'ping' }
  | { type: 'error'; message: string }
  | { type: 'structure'; symbol: string; interval: string; signals: StructureSignal[] }
  | { type: 'alert_triggered'; entry: AlertHistory };

export type MessageHandler = (msg: WSMessage) => void;

const BASE_URL =
  typeof window !== 'undefined'
    ? `ws://${window.location.hostname}:8000`
    : 'ws://localhost:8000';

export class ChartWSClient {
  private ws: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private backoff = 1000;
  private destroyed = false;
  private handlers = new Set<MessageHandler>();
  private stateHandler?: (s: ConnectionState) => void;

  constructor(
    public readonly symbol: string,
    public readonly interval: string = '15min',
    private readonly baseUrl: string = BASE_URL,
  ) {}

  connect(): void {
    if (this.destroyed) return;
    this.stateHandler?.('connecting');
    const url = `${this.baseUrl}/chart/stream/${encodeURIComponent(this.symbol)}?interval=${this.interval}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.backoff = 1000;
      this.stateHandler?.('connected');
    };

    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data as string) as WSMessage;
        this.handlers.forEach(h => h(msg));
      } catch { /* ignore malformed messages */ }
    };

    this.ws.onclose = () => {
      if (!this.destroyed) {
        this.stateHandler?.('reconnecting');
        this.timer = setTimeout(() => {
          this.backoff = Math.min(this.backoff * 2, 30_000);
          this.connect();
        }, this.backoff);
      }
    };

    this.ws.onerror = () => {
      this.stateHandler?.('error');
      this.ws?.close();
    };
  }

  onStateChange(fn: (s: ConnectionState) => void): void {
    this.stateHandler = fn;
  }

  onMessage(fn: MessageHandler): () => void {
    this.handlers.add(fn);
    return () => this.handlers.delete(fn);
  }

  destroy(): void {
    this.destroyed = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    this.ws = null;
  }
}
