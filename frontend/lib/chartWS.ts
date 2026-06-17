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

const _apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const _wsBase = _apiUrl.replace(/^http/, 'ws');
const BASE_URL = typeof window !== 'undefined' ? _wsBase : 'ws://localhost:8000';

export class ChartWSClient {
  private ws: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private backoff = 1000;
  private destroyed = false;
  /** True after the server sends type:"error" (data unavailable). Stops auto-reconnect. */
  private dataError = false;
  private handlers = new Set<MessageHandler>();
  private stateHandler?: (s: ConnectionState) => void;

  constructor(
    public readonly symbol: string,
    public readonly interval: string = '15min',
    private readonly baseUrl: string = BASE_URL,
  ) {}

  connect(): void {
    if (this.destroyed || this.dataError) return;
    this.stateHandler?.('connecting');
    const url = `${this.baseUrl}/chart/stream/${encodeURIComponent(this.symbol)}?interval=${encodeURIComponent(this.interval)}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      // Do NOT reset backoff here — the connection opens even when data is unavailable.
      // Backoff only resets after a successful history load (see onmessage).
      this.stateHandler?.('connected');
    };

    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data as string) as WSMessage;
        if (msg.type === 'history') {
          // Real data received — connection is healthy, reset backoff.
          this.backoff = 1000;
        }
        if (msg.type === 'error') {
          // Backend signals no data is available for this symbol/interval.
          // Stop reconnecting so we don't hammer the server.
          this.dataError = true;
          this.stateHandler?.('error');
        }
        this.handlers.forEach(h => h(msg));
      } catch { /* ignore malformed messages */ }
    };

    this.ws.onclose = () => {
      if (!this.destroyed && !this.dataError) {
        this.stateHandler?.('reconnecting');
        this.timer = setTimeout(() => {
          this.backoff = Math.min(this.backoff * 2, 30_000);
          this.connect();
        }, this.backoff);
      }
    };

    this.ws.onerror = () => {
      if (!this.dataError) this.stateHandler?.('error');
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
    this.stateHandler = undefined;
    this.handlers.clear();
  }
}
