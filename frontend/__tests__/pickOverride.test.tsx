import { useScanStore } from '@/lib/scanStore';

describe('pickedContracts store', () => {
  beforeEach(() => useScanStore.setState({ pickedContracts: {}, contractsBySymbol: {} }));

  it('setPickedContract writes to store', () => {
    useScanStore.getState().setPickedContract('MSFT', 'MSFT|420|2026-06-18|C');
    expect(useScanStore.getState().pickedContracts['MSFT']).toBe('MSFT|420|2026-06-18|C');
  });

  it('clearPickedContracts resets', () => {
    useScanStore.getState().setPickedContract('MSFT', 'MSFT|420|2026-06-18|C');
    useScanStore.getState().clearPickedContracts();
    expect(useScanStore.getState().pickedContracts).toEqual({});
  });

  it('setContractsBySymbol stores contract list', () => {
    const mock = [{ id: 'MSFT|420|2026-06-18|C', score: 75 }] as any;
    useScanStore.getState().setContractsBySymbol({ MSFT: mock });
    expect(useScanStore.getState().contractsBySymbol['MSFT']).toHaveLength(1);
  });
});
