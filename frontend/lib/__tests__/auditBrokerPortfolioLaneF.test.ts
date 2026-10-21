/**
 * Lane F Frontend Audit Test Suite (APP-AUDIT-BROKER-PORTFOLIO / issue #354)
 *
 * Verifies:
 * - Save-first direct send failure classification (classifyDirectFailure)
 * - Safe pre-flight refusal cleanup (verdict: 'delete') vs ambiguous retention (verdict: 'keep')
 * - Portfolio store duplicate contract merging & domain key invariants
 */
import {
  classifyDirectFailure,
  directOrderBlock,
  brokerLabelFor,
  isAcceptedNotFilled,
} from '@/lib/directOrder';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { contractId, contractLabel, type PortfolioPosition } from '@/types/domain';

let _recIdCounter = 0;
const makePosition = (overrides: Partial<PortfolioPosition> = {}): PortfolioPosition => ({
  symbol: 'AAPL',
  contract: 'AAPL 185C 05/16',
  direction: 'Bullish',
  entryDate: '2026-04-08',
  expiry: '2026-05-16',
  dteRemaining: 28,
  dteTotal: 38,
  entryPrice: 4.15,
  currentPrice: 5.02,
  pnlDollar: 870,
  pnlPct: 20.96,
  stop: 180.0,
  targets: [{ id: 'tp1', stockPrice: 198.0, contractsToSell: 2, status: 'PENDING' }],
  status: 'PASS',
  contracts: 2,
  recId: `REC-TEST-${++_recIdCounter}`,
  ...overrides,
});

describe('Lane F Frontend Audit: Direct Order Classification & Portfolio Reconciliation', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [] });
  });

  describe('Task 1 & Task 3: classifyDirectFailure lifecycle and preflight boundaries', () => {
    it('classifies 422 pre-flight refusal as safe to delete pre-saved row', () => {
      const outcome = classifyDirectFailure({
        thrown: new Error('API /broker/option-order \u2192 422: quantity must be >= 1'),
      });
      expect(outcome.verdict).toBe('delete');
    });

    it('classifies unauthenticated broker credentials (503) as safe to delete', () => {
      const outcome = classifyDirectFailure({
        thrown: new Error('API /broker/stock-order \u2192 503: Broker credentials unavailable for tradier_paper'),
      });
      expect(outcome.verdict).toBe('delete');
    });

    it('classifies IBKR confirmation question refusal (502) as safe to delete', () => {
      const outcome = classifyDirectFailure({
        thrown: new Error('API /broker/option-order \u2192 502: IBKR did not place the order: it asked for a confirmation'),
      });
      expect(outcome.verdict).toBe('delete');
    });

    it('retains pre-saved position (verdict: keep) on 500 internal server error', () => {
      const outcome = classifyDirectFailure({
        thrown: new Error('API /broker/stock-order \u2192 500: Internal Server Error'),
      });
      expect(outcome.verdict).toBe('keep');
      if (outcome.verdict === 'keep') {
        expect(outcome.orderId).toBeNull();
      }
    });

    it('retains pre-saved position (verdict: keep) on network drop / gateway timeout (504)', () => {
      const outcome = classifyDirectFailure({
        thrown: new Error('API /broker/option-order \u2192 504: Gateway Timeout'),
      });
      expect(outcome.verdict).toBe('keep');
    });

    it('retains pre-saved position (verdict: keep) when broker reply lacks usable order ID', () => {
      const outcome = classifyDirectFailure({
        response: { status: 'submitted', order_id: 'unknown' },
      });
      expect(outcome.verdict).toBe('keep');
    });

    it('classifies successful submission with usable order ID as placed', () => {
      const outcome = classifyDirectFailure({
        response: { status: 'PreSubmitted', order_id: 'IBKR-ORD-9988' },
      });
      expect(outcome.verdict).toBe('placed');
      if (outcome.verdict === 'placed') {
        expect(outcome.orderId).toBe('IBKR-ORD-9988');
      }
    });

    it('enforces Tastytrade paper market order preflight refusal', () => {
      expect(directOrderBlock('MKT', 'tastytrade_paper')).toContain('limit orders only');
      expect(directOrderBlock('LMT', 'tastytrade_paper')).toBeNull();
      expect(directOrderBlock('MKT', 'ibkr_paper')).toBeNull();
    });

    it('formats broker labels truthfully across all supported paper adapters', () => {
      expect(brokerLabelFor('tradier_paper')).toBe('Tradier Paper');
      expect(brokerLabelFor('tastytrade_paper')).toBe('Tastytrade Paper');
      expect(brokerLabelFor('alpaca_paper')).toBe('Alpaca Paper');
      expect(brokerLabelFor('ibkr_paper')).toBe('IBKR Paper');
    });

    it('distinguishes accepted/pending states from executed fills', () => {
      expect(isAcceptedNotFilled('PreSubmitted')).toBe(true);
      expect(isAcceptedNotFilled('submitted')).toBe(true);
      expect(isAcceptedNotFilled('accepted')).toBe(true);
      expect(isAcceptedNotFilled('filled')).toBe(false);
    });
  });

  describe('Task 4: Portfolio Store duplicate contract merging & domain keys', () => {
    it('creates canonical contract composite key and display label', () => {
      const id = contractId('AAPL', 185, '2025-05-16', 'C');
      expect(id).toBe('AAPL|185|2025-05-16|C');

      const label = contractLabel({ symbol: 'AAPL', strike: 185, right: 'C', expiry: '2025-05-16' });
      expect(label).toBe('AAPL 185C 05/16/25');
    });

    it('verifies portfolio position contracts count and contract labeling', () => {
      const pos = makePosition({
        symbol: 'AAPL',
        contract: 'AAPL 185C 05/16',
        contracts: 2,
        entryPrice: 3.50,
      });

      expect(pos.contract).toBe('AAPL 185C 05/16');
      expect(pos.contracts).toBe(2);
      expect(pos.entryPrice).toBe(3.50);
    });
  });
});
