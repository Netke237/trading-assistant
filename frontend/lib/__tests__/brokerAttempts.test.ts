import { API_BASE_URL } from '@/lib/api';
import {
  getBrokerAttempt, listBrokerAttempts, submissionDisplayLabel, verifyBrokerAttempt,
} from '@/lib/brokerAttempts';

const sample = {
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

function jsonResponse(status: number, body: unknown) {
  const text = JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => text,
  };
}

beforeEach(() => {
  global.fetch = jest.fn();
});

describe('broker attempt helper', () => {
  it('lists and reads attempts from the existing API base without credentials or an order request', async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce(jsonResponse(200, { attempts: [sample] }))
      .mockResolvedValueOnce(jsonResponse(200, sample));
    await expect(listBrokerAttempts()).resolves.toEqual([sample]);
    await expect(getBrokerAttempt('open-1')).resolves.toEqual(sample);
    const urls = (global.fetch as jest.Mock).mock.calls.map((call) => String(call[0]));
    expect(urls).toEqual([
      `${API_BASE_URL}/broker/attempts`,
      `${API_BASE_URL}/broker/attempts/open-1`,
    ]);
    for (const call of (global.fetch as jest.Mock).mock.calls) {
      const init = call[1] ?? {};
      expect(init.method ?? 'GET').toBe('GET');
      expect(JSON.stringify(init.headers ?? {}).toLowerCase()).not.toMatch(/authorization|cookie|api-key/);
      expect(String(call[0])).not.toMatch(/stock-order|option-order/);
    }
  });

  it('posts manual verification and does not place an order', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, {
      ...sample, state: 'submitted', verification_outcome: 'submitted', outcome_label: 'submitted',
    }));
    await verifyBrokerAttempt('open-1', {
      outcome: 'submitted', note: 'Alpaca shows ORD-9 submitted', expected_version: 2,
    });
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/broker/attempts/open-1/verify`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      outcome: 'submitted', note: 'Alpaca shows ORD-9 submitted', expected_version: 2,
    });
    expect(String(url)).not.toMatch(/stock-order|option-order/);
  });

  it('uses the api.ts error shape', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(409, { detail: 'stale verification' }));
    await expect(verifyBrokerAttempt('open-1', {
      outcome: 'definitely-not-submitted', note: 'no order at the broker', expected_version: 2,
    })).rejects.toThrow('API /broker/attempts/open-1/verify → 409: stale verification');
  });

  it('shows an accepted attempt as submitted, never filled', () => {
    const label = submissionDisplayLabel({
      state: 'submitted', broker_status: 'accepted', outcome_label: 'filled',
    });
    expect(label).toBe('submitted');
    expect(label.toLowerCase()).not.toContain('filled');
    expect(submissionDisplayLabel({
      state: 'outcome-unknown', broker_status: null, outcome_label: 'outcome unknown',
    })).toBe('outcome unknown');
  });
});
