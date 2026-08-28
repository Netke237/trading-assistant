import '@testing-library/jest-dom';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { SymbolNotes } from '@/components/molecules/SymbolNotes';
import { useNotesStore } from '@/lib/notesStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    getSymbolNote: jest.fn(),
    putSymbolNote: jest.fn(),
  },
}));

const mockGet = api.getSymbolNote as jest.Mock;
const mockPut = api.putSymbolNote as jest.Mock;

describe('SymbolNotes', () => {
  beforeEach(() => {
    useNotesStore.setState({ notes: {} });
    mockGet.mockReset();
    mockPut.mockReset();
    mockGet.mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: null });
    mockPut.mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: '2026-08-28T00:00:00Z' });
  });

  it('shows a gating placeholder instead of a textarea when not editable, and fetches nothing', () => {
    render(<SymbolNotes symbol="AAPL" editable={false} />);
    expect(screen.getByText(/star this symbol or open a position/i)).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    // Fetching a note that can only ever render behind the gating
    // placeholder would be a wasted request.
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('fetches and reveals the note once a previously non-editable symbol becomes editable', async () => {
    mockGet.mockResolvedValueOnce({ symbol: 'AAPL', body: 'existing note text', updatedAt: '2026-08-01T00:00:00Z' });
    const { rerender } = render(<SymbolNotes symbol="AAPL" editable={false} />);
    expect(mockGet).not.toHaveBeenCalled();

    act(() => { rerender(<SymbolNotes symbol="AAPL" editable />); });

    await waitFor(() => {
      expect(screen.getByRole('textbox')).toHaveValue('existing note text');
    });
  });

  it('renders an editable textarea and loads the existing note', async () => {
    mockGet.mockResolvedValueOnce({ symbol: 'AAPL', body: 'existing note text', updatedAt: '2026-08-01T00:00:00Z' });
    render(<SymbolNotes symbol="AAPL" editable />);

    await waitFor(() => {
      expect(screen.getByRole('textbox')).toHaveValue('existing note text');
    });
  });

  it('typing updates the textarea immediately and eventually saves', async () => {
    render(<SymbolNotes symbol="AAPL" editable />);

    const textarea = await screen.findByRole('textbox');
    fireEvent.change(textarea, { target: { value: 'new note' } });

    expect(textarea).toHaveValue('new note');
    await waitFor(() => expect(mockPut).toHaveBeenCalledWith('AAPL', 'new note'));
  });

  it('shows a retry state instead of a blank editable textarea when the load fails', async () => {
    mockGet.mockReset();
    mockGet.mockRejectedValueOnce(new Error('network down'));
    render(<SymbolNotes symbol="AAPL" editable />);

    await screen.findByText(/couldn't load this note/i);
    // Critically, no textarea is offered — typing here would silently
    // overwrite a note we never actually saw.
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('retry button re-fetches and then reveals the real note for editing', async () => {
    mockGet.mockReset();
    mockGet.mockRejectedValueOnce(new Error('network down'));
    render(<SymbolNotes symbol="AAPL" editable />);
    const retryBtn = await screen.findByRole('button', { name: /retry/i });

    mockGet.mockResolvedValueOnce({ symbol: 'AAPL', body: 'the real note', updatedAt: '2026-08-01T00:00:00Z' });
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByRole('textbox')).toHaveValue('the real note');
    });
  });
});
