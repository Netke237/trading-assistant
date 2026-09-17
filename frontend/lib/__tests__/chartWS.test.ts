import { ChartWSClient } from '@/lib/chartWS';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = jest.fn();

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  /** Test helper: simulate the server sending a WSMessage. */
  emit(msg: unknown): void {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

function latestSocket(): MockWebSocket {
  const sockets = MockWebSocket.instances;
  return sockets[sockets.length - 1];
}

describe('ChartWSClient — reconnect behavior', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    MockWebSocket.instances = [];
    (global as unknown as { WebSocket: unknown }).WebSocket = MockWebSocket;
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('keeps retrying after a data-unavailable error instead of stopping forever', () => {
    const client = new ChartWSClient('AAPL', '15min');
    client.connect();
    expect(MockWebSocket.instances).toHaveLength(1);

    latestSocket().emit({ type: 'error', message: 'no data' });
    latestSocket().onclose?.();

    // Not yet — the reconnect is scheduled on the 1000ms initial backoff.
    jest.advanceTimersByTime(999);
    expect(MockWebSocket.instances).toHaveLength(1);

    jest.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(2);

    client.destroy();
  });

  it('resets backoff to the 1000ms floor after a successful history load', () => {
    const client = new ChartWSClient('AAPL', '15min');
    client.connect();

    // First failure cycle: schedules at 1000ms, backoff becomes 2000 after firing.
    latestSocket().emit({ type: 'error', message: 'no data' });
    latestSocket().onclose?.();
    jest.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(2);

    // Real data arrives on the second attempt — backoff should reset to 1000.
    latestSocket().emit({ type: 'history', candles: [] });
    latestSocket().onclose?.();

    // If backoff had NOT reset, this would still be mid-2000ms wait and no
    // third socket would exist yet. It resets, so 1000ms is enough.
    jest.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(3);

    client.destroy();
  });

  it('destroy() prevents any further reconnect after a data error', () => {
    // Guarded twice over — destroy() both clears the pending reconnect timer
    // and flips `destroyed`, which connect() also checks on its own — so
    // this observes the combined outcome rather than isolating either guard.
    const client = new ChartWSClient('AAPL', '15min');
    client.connect();

    latestSocket().emit({ type: 'error', message: 'no data' });
    latestSocket().onclose?.();
    client.destroy();

    jest.advanceTimersByTime(60_000);
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('onerror always reports the error state and closes, regardless of any prior data error', () => {
    // The old `dataError` latch also guarded `onerror` (`if (!this.dataError)
    // this.stateHandler?.('error')`), so a regression that reintroduced a
    // dataError-style guard only inside onerror (leaving onmessage/onclose
    // fixed) would slip past every other test here, since none of them
    // trigger onerror directly.
    const client = new ChartWSClient('AAPL', '15min');
    const stateHandler = jest.fn();
    client.onStateChange(stateHandler);
    client.connect();

    // A prior data error, so a reintroduced latch would have something to gate on.
    latestSocket().emit({ type: 'error', message: 'no data' });
    stateHandler.mockClear();

    const socket = latestSocket();
    socket.onerror?.();

    expect(stateHandler).toHaveBeenCalledWith('error');
    expect(socket.close).toHaveBeenCalled();

    client.destroy();
  });

  it('compounds backoff across repeated errors without resetting in between', () => {
    const client = new ChartWSClient('AAPL', '15min');
    client.connect();
    expect(MockWebSocket.instances).toHaveLength(1);

    const expectedDelays = [1000, 2000, 4000];
    for (const delay of expectedDelays) {
      latestSocket().emit({ type: 'error', message: 'no data' });
      latestSocket().onclose?.();

      jest.advanceTimersByTime(delay - 1);
      expect(MockWebSocket.instances).toHaveLength(
        expectedDelays.indexOf(delay) + 1,
      );

      jest.advanceTimersByTime(1);
      expect(MockWebSocket.instances).toHaveLength(
        expectedDelays.indexOf(delay) + 2,
      );
    }

    client.destroy();
  });
});
