/**
 * Regression test for a real rules-of-hooks bug (fixed 2026-08):
 * ContractRejectionSection called useState() *after* an early `return null`
 * when there were no contract rejections. That's fine on a single render, but
 * React throws "Rendered fewer hooks than expected" the moment the SAME
 * mounted instance re-renders with a different rejected-list shape — e.g. a
 * live scan going from "no contract rejections" to "some contract
 * rejections" without unmounting. This test exercises exactly that
 * transition, which a one-shot render test would not catch.
 */
import { render, act } from '@testing-library/react';
import { ScanLog } from '@/components/organisms/ScanLog';
import { useScanStore } from '@/lib/scanStore';
import type { ScanContext, ScanResult, RejectedEntry } from '@/lib/scanStore';

const context: ScanContext = {
  universe: 'SP500',
  direction: 'Bullish',
  horizon: 'Swing',
  horizonPreset: 'Swing',
  holdMin: 5,
  holdMax: 15,
};

function scanResult(rejected: RejectedEntry[]): ScanResult {
  return {
    scan_id: 'test-scan',
    timestamp: new Date().toISOString(),
    candidates: [],
    rejected,
  };
}

const noContractRejections: RejectedEntry[] = [
  { symbol: 'AAPL', reason: 'score below threshold' },
];

const withContractRejections: RejectedEntry[] = [
  { symbol: 'AAPL', reason: 'score below threshold' },
  { symbol: 'MSFT', reason: 'all contracts rejected: spread too wide' },
];

beforeEach(() => {
  act(() => {
    useScanStore.setState({ context: null, scanResult: null });
  });
});

test('renders with no contract rejections without crashing', () => {
  act(() => {
    useScanStore.setState({ context, scanResult: scanResult(noContractRejections) });
  });
  expect(() => render(<ScanLog />)).not.toThrow();
});

test('renders with contract rejections without crashing', () => {
  act(() => {
    useScanStore.setState({ context, scanResult: scanResult(withContractRejections) });
  });
  expect(() => render(<ScanLog />)).not.toThrow();
});

test('re-rendering from no-contract-rejections to has-contract-rejections does not throw a hooks-order error', () => {
  act(() => {
    useScanStore.setState({ context, scanResult: scanResult(noContractRejections) });
  });
  const { rerender } = render(<ScanLog />);

  expect(() => {
    act(() => {
      useScanStore.setState({ context, scanResult: scanResult(withContractRejections) });
    });
    rerender(<ScanLog />);
  }).not.toThrow();
});

test('re-rendering from has-contract-rejections back to none does not throw a hooks-order error', () => {
  act(() => {
    useScanStore.setState({ context, scanResult: scanResult(withContractRejections) });
  });
  const { rerender } = render(<ScanLog />);

  expect(() => {
    act(() => {
      useScanStore.setState({ context, scanResult: scanResult(noContractRejections) });
    });
    rerender(<ScanLog />);
  }).not.toThrow();
});
