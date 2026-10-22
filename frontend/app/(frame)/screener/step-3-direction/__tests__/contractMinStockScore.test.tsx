import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import Step3Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useContractRulesStore } from '@/lib/contractRulesStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    getLatestScanReport: jest.fn().mockResolvedValue(null),
    getRegime: jest.fn().mockResolvedValue(null),
    getScanStatus: jest.fn().mockResolvedValue(null),
    getLastScanStatus: jest.fn().mockResolvedValue({ status: null, updated_at: null }),
    getEventThresholds: jest.fn().mockResolvedValue(null),
    getContractRules: jest.fn().mockResolvedValue({ min_stock_score: 45 }),
  },
}));

jest.mock('@/components/organisms/RunScanButton', () => ({
  RunScanButton: () => null,
}));

jest.mock('@/components/organisms/SearchProfileBar', () => ({
  SearchProfileBar: () => null,
}));

jest.mock('@/components/organisms/SavedScanReportInspector', () => ({
  SavedScanReportInspector: () => null,
}));

describe('Step 3 — Contract Min Stock Score Override (#389)', () => {
  beforeEach(async () => {
    act(() => {
      useScanStore.setState({
        context: {
          universe: 'SP500',
          direction: 'Bullish',
          horizon: 'Swing',
          horizonPreset: 'Swing',
          holdMin: 5,
          holdMax: 20,
        },
        screenerMode: 'options',
        scanOverrides: {},
        scanResult: null,
      });
      useContractRulesStore.setState({
        minStockScore: 45,
        status: 'ready',
        error: null,
      });
    });
  });

  it('renders the contract floor parameter with default value from contract rules store', async () => {
    await act(async () => {
      render(<Step3Page />);
    });

    fireEvent.click(screen.getByText('Execution Parameters'));

    const input = screen.getByLabelText('Min underlying score (contract floor)') as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe('45');
  });

  it('updates scanOverrides when user changes the value to 30', async () => {
    await act(async () => {
      render(<Step3Page />);
    });

    fireEvent.click(screen.getByText('Execution Parameters'));

    const input = screen.getByLabelText('Min underlying score (contract floor)') as HTMLInputElement;
    act(() => {
      fireEvent.change(input, { target: { value: '30' } });
    });

    expect(useScanStore.getState().scanOverrides.contract_min_stock_score).toBe(30);
  });

  it('clearing the input removes contract_min_stock_score from scanOverrides', async () => {
    act(() => {
      useScanStore.setState({
        scanOverrides: { contract_min_stock_score: 30 },
      });
    });

    await act(async () => {
      render(<Step3Page />);
    });

    fireEvent.click(screen.getByText('Execution Parameters'));

    const input = screen.getByLabelText('Min underlying score (contract floor)') as HTMLInputElement;
    expect(input.value).toBe('30');

    act(() => {
      fireEvent.change(input, { target: { value: '' } });
    });

    expect(useScanStore.getState().scanOverrides).not.toHaveProperty('contract_min_stock_score');
  });

  it('setting the input back to default 45 removes contract_min_stock_score from scanOverrides', async () => {
    act(() => {
      useScanStore.setState({
        scanOverrides: { contract_min_stock_score: 30 },
      });
    });

    await act(async () => {
      render(<Step3Page />);
    });

    fireEvent.click(screen.getByText('Execution Parameters'));

    const input = screen.getByLabelText('Min underlying score (contract floor)') as HTMLInputElement;
    act(() => {
      fireEvent.change(input, { target: { value: '45' } });
    });

    expect(useScanStore.getState().scanOverrides).not.toHaveProperty('contract_min_stock_score');
  });
});
