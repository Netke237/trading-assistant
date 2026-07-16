import { contractLabel } from './domain';

describe('contractLabel', () => {
  it('includes a 2-digit year so cross-year contracts are unambiguous', () => {
    expect(
      contractLabel({ symbol: 'AAPL', strike: 375, right: 'C', expiry: '2027-01-15' }),
    ).toBe('AAPL 375C 01/15/27');
  });

  it('renders puts and other years correctly', () => {
    expect(
      contractLabel({ symbol: 'TSLA', strike: 260, right: 'P', expiry: '2026-05-16' }),
    ).toBe('TSLA 260P 05/16/26');
  });

  it('degrades gracefully when the expiry is missing', () => {
    expect(
      contractLabel({ symbol: 'AAPL', strike: 375, right: 'C', expiry: '' }),
    ).toBe('AAPL 375C --/--/--');
  });
});
