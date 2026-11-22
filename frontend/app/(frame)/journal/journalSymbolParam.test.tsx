import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import JournalPage from './page';
import { useJournalStore } from '@/lib/journalStore';

jest.mock('@/components/organisms/JournalEntryForm', () => ({ JournalEntryForm: () => null }));
jest.mock('@/components/organisms/JournalEntryTable', () => ({ JournalEntryTable: () => null }));

function setup(search: string) {
  window.history.replaceState({}, '', `/journal${search}`);
  const syncEntries = jest.fn().mockResolvedValue(undefined);
  useJournalStore.setState({ syncEntries, entries: [] } as never);
  render(<JournalPage />);
  return syncEntries;
}

describe('Journal ?symbol= seed', () => {
  it('seeds the filter, uppercased, and the first sync carries it', () => {
    const sync = setup('?symbol=aapl');
    expect(screen.getByDisplayValue('AAPL')).toBeInTheDocument();
    expect(sync.mock.calls[0][0]).toEqual({ symbol: 'AAPL' });
  });

  it('no param leaves the page unchanged', () => {
    const sync = setup('');
    expect(sync.mock.calls[0][0]).toEqual({});
    expect(screen.queryByDisplayValue('AAPL')).toBeNull();
  });
});
