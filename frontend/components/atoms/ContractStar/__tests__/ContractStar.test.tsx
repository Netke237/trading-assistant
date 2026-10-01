import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

jest.mock('@/lib/api', () => ({
  api: {
    addWatchedContract:    jest.fn(),
    removeWatchedContract: jest.fn(),
  },
}));

import { api } from '@/lib/api';
import { ContractStar } from '@/components/atoms/ContractStar';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import type { ContractGrading } from '@/types/domain';

const mockApi = api as jest.Mocked<typeof api>;
const ID = 'XOM|190|2026-12-18|C';
const G: ContractGrading = { contract_rules: { min_volume: 20 }, hold_min_days: 20, hold_max_days: 25, stock_score: 72 };
const state = () => useWatchedContractsStore.getState();

beforeEach(() => {
  jest.clearAllMocks();
  useWatchedContractsStore.setState({ ids: [], grading: {} });
  jest.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => { (console.warn as jest.Mock).mockRestore(); });

const click = () => fireEvent.click(screen.getByRole('button'));

it('starring with a grading posts it and stores it', async () => {
  mockApi.addWatchedContract.mockResolvedValue({ contract_id: ID });
  render(<ContractStar contractId={ID} grading={G} />);
  click();
  expect(mockApi.addWatchedContract).toHaveBeenCalledWith(ID, G);
  expect(state().ids).toEqual([ID]);
  expect(state().grading[ID]).toEqual(G);
});

it('a failed DELETE restores the id AND its grading', async () => {
  useWatchedContractsStore.setState({ ids: [ID], grading: { [ID]: G } });
  mockApi.removeWatchedContract.mockRejectedValue(new Error('API /api/watched-contracts/x → 500'));
  render(<ContractStar contractId={ID} />);
  click();
  expect(state().ids).toEqual([]);
  await waitFor(() => expect(state().ids).toEqual([ID]));
  expect(state().grading[ID]).toEqual(G);
});

it('a 422 on the grading retries once with null: the star stays, YAML-graded', async () => {
  mockApi.addWatchedContract
    .mockRejectedValueOnce(new Error('API /api/watched-contracts → 422: grading: bad'))
    .mockResolvedValueOnce({ contract_id: ID });
  render(<ContractStar contractId={ID} grading={G} />);
  click();
  await waitFor(() => expect(mockApi.addWatchedContract).toHaveBeenCalledTimes(2));
  expect(mockApi.addWatchedContract).toHaveBeenLastCalledWith(ID, null);
  await act(async () => {});
  expect(state().ids).toEqual([ID]);
  expect(state().grading[ID]).toBeUndefined();
  expect(console.warn).toHaveBeenCalled();
});

it('a 422 whose retry also fails removes the star', async () => {
  mockApi.addWatchedContract
    .mockRejectedValueOnce(new Error('API /api/watched-contracts → 422: grading: bad'))
    .mockRejectedValueOnce(new Error('API /api/watched-contracts → 500'));
  render(<ContractStar contractId={ID} grading={G} />);
  click();
  await waitFor(() => expect(state().ids).toEqual([]));
  expect(mockApi.addWatchedContract).toHaveBeenCalledTimes(2);
});

it('any other POST failure removes the star without a retry', async () => {
  mockApi.addWatchedContract.mockRejectedValue(new Error('API /api/watched-contracts → 500'));
  render(<ContractStar contractId={ID} grading={G} />);
  click();
  await waitFor(() => expect(state().ids).toEqual([]));
  expect(state().grading[ID]).toBeUndefined();
  expect(mockApi.addWatchedContract).toHaveBeenCalledTimes(1);
});

it('a 422 without a grading is not retried', async () => {
  mockApi.addWatchedContract.mockRejectedValue(new Error('API /api/watched-contracts → 422: contract_id'));
  render(<ContractStar contractId={ID} />);
  click();
  await waitFor(() => expect(state().ids).toEqual([]));
  expect(mockApi.addWatchedContract).toHaveBeenCalledTimes(1);
  expect(mockApi.addWatchedContract).toHaveBeenCalledWith(ID, undefined);
});
