import type { Candle } from './indicators';

export type WSMessage =
  | { type: 'history'; candles: Candle[] }
  | { type: 'tick'; data: { symbol: string; price: number; volume: number; timestamp: string } }
  | { type: 'ping' }
  | { type: 'error'; message: string };

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

  constructor(
    public readonly symbol: string,
    public readonly interval: string = '15min',
    private readonly baseUrl: string = BASE_URL,
  ) {}

  connect(): void {
    if (this.destroyed) return;
    const url = `${this.baseUrl}/chart/stream/${encodeURIComponent(this.symbol)}?interval=${this.interval}`;
    this.ws = new WebSocket(url);

    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data as string) as WSMessage;
        this.handlers.forEach(h => h(msg));
      } catch { /* ignore malformed messages */ }
    };

    this.ws.onclose = () => {
      if (!this.destroyed) {
        this.timer = setTimeout(() => {
          this.backoff = Math.min(this.backoff * 2, 30_000);
          this.connect();
        }, this.backoff);
      }
    };

    this.ws.onerror = () => this.ws?.close();
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
