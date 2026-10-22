import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { BrokerAttemptPanel } from './index';
import { listBrokerAttempts, verifyBrokerAttempt } from '@/lib/brokerAttempts';

jest.mock('@/lib/brokerAttempts', () => {
  const actual = jest.requireActual('@/lib/brokerAttempts');
  return {
    ...actual,
    listBrokerAttempts: jest.fn(),
    verifyBrokerAttempt: jest.fn(),
    getBrokerAttempt: jest.fn(),
  };
});

jest.mock('@/lib/api', () => ({
  api: {
    postStockOrder: jest.fn(),
    postOptionOrder: jest.fn(),
  },
}));

const openAttempt = {
  attempt_id: 'open-1',
  state: 'outcome-unknown',
  fingerprint: 'abc',
  verification_version: 2,
  saved_rec_id: null,
  broker_order_id: null,
  broker_status: null,
  broker_response: null,
  payload: {
    kind: 'stock', broker: 'alpaca_paper', symbol: 'AAPL', instrument: 'AAPL|STOCK',
    action: 'BUY', effect: 'OPEN', quantity: 10, order_type: 'LMT', limit: '150',
    tif: 'DAY', conid: null,
  },
  verification_outcome: null,
  verification_note: null,
  outcome_label: 'outcome unknown',
  coverage_note: null,
  created_at: '2026-10-13T00:00:00+00:00',
  updated_at: '2026-10-13T00:00:00+00:00',
};

const closeAttempt = {
  ...openAttempt,
  attempt_id: 'close-1',
  verification_version: 4,
  saved_rec_id: 'REC-CLOSE',
  broker_order_id: 'BRK-3',
  broker_status: 'unknown',
  payload: {
    ...openAttempt.payload,
    symbol: 'MSFT', instrument: 'MSFT|STOCK', action: 'SELL', effect: 'CLOSE',
    quantity: 3, order_type: 'MKT', limit: null,
  },
};

const acceptedAttempt = {
  ...openAttempt,
  attempt_id: 'acc-1',
  state: 'outcome-unknown',
  broker_order_id: 'ORD-9',
  broker_status: 'accepted',
  outcome_label: 'filled',
  payload: { ...openAttempt.payload, symbol: 'HD', quantity: 1, limit: '320' },
};

beforeEach(() => {
  jest.clearAllMocks();
  (listBrokerAttempts as jest.Mock).mockResolvedValue([openAttempt, closeAttempt, acceptedAttempt]);
  (verifyBrokerAttempt as jest.Mock).mockImplementation(async (_id: string, body: { outcome: string }) => ({
    ...openAttempt, verification_outcome: body.outcome,
  }));
});

describe('BrokerAttemptPanel', () => {
  it('lists persisted OPEN and CLOSE attempts again after remount, including an unlinked order', async () => {
    const first = render(<BrokerAttemptPanel />);
    const openRow = await screen.findByTestId('attempt-open-1');
    const closeRow = screen.getByTestId('attempt-close-1');
    expect(within(openRow).getByText('open-1')).toBeInTheDocument();
    expect(within(openRow).getByText('AAPL')).toBeInTheDocument();
    expect(within(openRow).getByText('OPEN')).toBeInTheDocument();
    expect(within(openRow).getByText('10')).toBeInTheDocument();
    expect(within(openRow).getByText('150')).toBeInTheDocument();
    expect(within(openRow).getByText(/not linked to a saved row/i)).toBeInTheDocument();
    expect(within(openRow).getByTestId('outcome-open-1')).toHaveTextContent('outcome unknown');
    expect(within(openRow).getByText(/No broker evidence recorded/i)).toBeInTheDocument();
    expect(within(closeRow).getByText('CLOSE')).toBeInTheDocument();
    expect(within(closeRow).getByText('MSFT')).toBeInTheDocument();
    expect(within(closeRow).getByText('3')).toBeInTheDocument();
    expect(within(closeRow).getByText('MKT')).toBeInTheDocument();
    expect(within(closeRow).getByText('REC-CLOSE')).toBeInTheDocument();
    expect(within(closeRow).getByText('BRK-3')).toBeInTheDocument();
    first.unmount();
    render(<BrokerAttemptPanel />);
    expect(await screen.findByTestId('attempt-close-1')).toBeInTheDocument();
    expect(screen.getByTestId('attempt-open-1')).toBeInTheDocument();
    expect(listBrokerAttempts).toHaveBeenCalledTimes(2);
  });

  it('never offers retry, remove, or auto-fill, and accepted does not say filled', async () => {
    render(<BrokerAttemptPanel />);
    const accepted = await screen.findByTestId('attempt-acc-1');
    const outcome = within(accepted).getByTestId('outcome-acc-1');
    expect(outcome).toHaveTextContent('submitted');
    expect(outcome.textContent?.toLowerCase() ?? '').not.toContain('filled');
    expect(within(accepted).getByText('ORD-9')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /retry|remove|auto-fill|dismiss|reset/i })).not.toBeInTheDocument();
    const options = within(accepted).getAllByRole('option').map((option) => option.textContent ?? '').join(' ');
    expect(options).not.toMatch(/retry|remove|auto-fill|dismiss|reset/i);
  });

  it('records an explicit verification and does not place an order', async () => {
    render(<BrokerAttemptPanel />);
    const openRow = await screen.findByTestId('attempt-open-1');
    fireEvent.change(within(openRow).getByLabelText('Verification for open-1'), { target: { value: 'submitted' } });
    fireEvent.change(within(openRow).getByLabelText('Evidence for open-1'), {
      target: { value: 'Alpaca shows ORD-9 submitted' },
    });
    fireEvent.click(within(openRow).getByRole('button', { name: 'Record verification for open-1' }));
    await waitFor(() => expect(verifyBrokerAttempt).toHaveBeenCalledWith('open-1', {
      outcome: 'submitted',
      note: 'Alpaca shows ORD-9 submitted',
      expected_version: 2,
    }));
    await waitFor(() => expect(listBrokerAttempts).toHaveBeenCalledTimes(2));
    const { api } = await import('@/lib/api');
    expect(api.postStockOrder).not.toHaveBeenCalled();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });

  it('says precise release is deferred for a partial verification', async () => {
    render(<BrokerAttemptPanel />);
    const closeRow = await screen.findByTestId('attempt-close-1');
    fireEvent.change(within(closeRow).getByLabelText('Verification for close-1'), { target: { value: 'partial' } });
    expect(within(closeRow).getByText(/Precise quantity release is deferred/i)).toBeInTheDocument();
    fireEvent.change(within(closeRow).getByLabelText('Verification for close-1'), {
      target: { value: 'canceled-after-submission' },
    });
    expect(within(closeRow).getByText(/keeps its exposure coverage/i)).toBeInTheDocument();
  });
});
