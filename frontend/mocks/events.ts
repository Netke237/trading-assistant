/*
 * Upcoming events — Phase 5 / Round 2.
 * Covers a 6-month window so the multi-month Calendar has meaningful data.
 * `status` is the event's scan-time gate status (REJECT = must-avoid,
 * CAUTION = tread carefully, PASS = tradable through).
 */

import type { UpcomingEvent } from '@/types/domain';

export const MOCK_EVENTS: UpcomingEvent[] = [
  // --- April 2026 (near-term) ---
  { date: '2026-04-20', symbol: 'TSLA',  label: 'Earnings',           status: 'REJECT'  },
  { date: '2026-04-21', symbol: 'NVDA',  label: 'Earnings',           status: 'CAUTION' },
  { date: '2026-04-23', symbol: '—',     label: 'FOMC',               status: 'CAUTION' },
  { date: '2026-04-28', symbol: 'AAPL',  label: 'Earnings',           status: 'CAUTION' },
  { date: '2026-04-29', symbol: 'META',  label: 'Earnings',           status: 'PASS'    },
  { date: '2026-04-30', symbol: 'MSFT',  label: 'Earnings',           status: 'CAUTION' },

  // --- May 2026 ---
  { date: '2026-05-01', symbol: 'AMZN',  label: 'Earnings',           status: 'PASS'    },
  { date: '2026-05-06', symbol: '—',     label: 'ISM Services PMI',   status: 'PASS'    },
  { date: '2026-05-14', symbol: '—',     label: 'CPI release',        status: 'CAUTION' },
  { date: '2026-05-15', symbol: '—',     label: 'Monthly expiration', status: 'CAUTION' },
  { date: '2026-05-21', symbol: 'NVDA',  label: 'Earnings (Q1)',      status: 'REJECT'  },
  { date: '2026-05-28', symbol: 'CRM',   label: 'Earnings',           status: 'CAUTION' },

  // --- June 2026 ---
  { date: '2026-06-04', symbol: '—',     label: 'ECB rate decision',  status: 'PASS'    },
  { date: '2026-06-11', symbol: '—',     label: 'CPI release',        status: 'CAUTION' },
  { date: '2026-06-17', symbol: '—',     label: 'FOMC + dot plot',    status: 'REJECT'  },
  { date: '2026-06-19', symbol: '—',     label: 'Triple witching',    status: 'CAUTION' },
  { date: '2026-06-25', symbol: 'NKE',   label: 'Earnings',           status: 'PASS'    },
  { date: '2026-06-30', symbol: 'MU',    label: 'Earnings',           status: 'CAUTION' },

  // --- July 2026 ---
  { date: '2026-07-02', symbol: '—',     label: 'NFP jobs report',    status: 'CAUTION' },
  { date: '2026-07-14', symbol: 'JPM',   label: 'Earnings',           status: 'PASS'    },
  { date: '2026-07-15', symbol: '—',     label: 'CPI release',        status: 'CAUTION' },
  { date: '2026-07-17', symbol: '—',     label: 'Monthly expiration', status: 'CAUTION' },
  { date: '2026-07-22', symbol: 'TSLA',  label: 'Earnings',           status: 'REJECT'  },
  { date: '2026-07-23', symbol: 'GOOGL', label: 'Earnings',           status: 'CAUTION' },
  { date: '2026-07-29', symbol: '—',     label: 'FOMC',               status: 'REJECT'  },
  { date: '2026-07-30', symbol: 'AAPL',  label: 'Earnings',           status: 'CAUTION' },
  { date: '2026-07-30', symbol: 'AMZN',  label: 'Earnings',           status: 'CAUTION' },
  { date: '2026-07-31', symbol: 'XOM',   label: 'Earnings',           status: 'PASS'    },

  // --- August 2026 ---
  { date: '2026-08-06', symbol: '—',     label: 'BoE rate decision',  status: 'PASS'    },
  { date: '2026-08-12', symbol: '—',     label: 'CPI release',        status: 'CAUTION' },
  { date: '2026-08-21', symbol: '—',     label: 'Monthly expiration', status: 'CAUTION' },
  { date: '2026-08-27', symbol: 'NVDA',  label: 'Earnings (Q2)',      status: 'REJECT'  },
  { date: '2026-08-28', symbol: '—',     label: 'Jackson Hole close', status: 'CAUTION' },

  // --- September 2026 ---
  { date: '2026-09-04', symbol: '—',     label: 'NFP jobs report',    status: 'CAUTION' },
  { date: '2026-09-10', symbol: '—',     label: 'ECB rate decision',  status: 'PASS'    },
  { date: '2026-09-11', symbol: '—',     label: 'CPI release',        status: 'CAUTION' },
  { date: '2026-09-16', symbol: '—',     label: 'FOMC + projections', status: 'REJECT'  },
  { date: '2026-09-18', symbol: '—',     label: 'Triple witching',    status: 'CAUTION' },
  { date: '2026-09-24', symbol: 'COST',  label: 'Earnings',           status: 'PASS'    },
];
