import '@testing-library/jest-dom';

// jsdom does not implement ResizeObserver. Components that watch their
// container size (ChartPane, CandlestickChart, PnlChart, EarningsChart) call
// `new ResizeObserver(...)` unconditionally on mount, which throws under
// jsdom without this stub.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
global.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
