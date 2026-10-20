import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import SettingsPage from '../page';

// Mock API calls so SettingsPage can mount without network calls
jest.mock('@/lib/api', () => ({
  api: {
    postCredentials: jest.fn().mockResolvedValue(undefined),
    getLastScan: jest.fn().mockResolvedValue(null),
    getLastStockScan: jest.fn().mockResolvedValue(null),
  },
  getRiskSettings: jest.fn().mockResolvedValue(null),
  saveRiskSettings: jest.fn().mockResolvedValue(undefined),
  getHistoryRetention: jest.fn().mockResolvedValue({ historyRetentionYears: 10 }),
  saveHistoryRetention: jest.fn().mockResolvedValue(undefined),
}));

describe('Settings page — Notifications blurb punctuation (#375)', () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    } as unknown as Response);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test('Notifications section intro renders readable em dash rather than literal unicode escape', () => {
    render(<SettingsPage />);

    // Click Notifications in the subnav
    const notifNav = screen.getByRole('button', { name: /notifications/i });
    fireEvent.click(notifNav);

    // Locate the blurb text
    const blurb = screen.getByText(/Configure alert delivery/i);
    expect(blurb).toBeInTheDocument();

    // Verify it contains the literal em dash
    expect(blurb.textContent).toContain('write-only — leave blank');

    // Verify it does NOT contain the literal unicode escape sequence \u2014
    expect(blurb.textContent).not.toContain('\\u2014');
    expect(blurb.textContent).not.toContain('u2014');
  });
});
