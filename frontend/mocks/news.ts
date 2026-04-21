/*
 * News mock — headlines tied to watchlist symbols.
 * Static sample for v1 (no backend).
 */

export interface NewsItem {
  id:        string;
  symbol:    string;
  headline:  string;
  source:    string;
  timestamp: string;       // "14m", "1h", "3h"
  sentiment: 'bull' | 'bear' | 'neutral';
}

export const MOCK_NEWS: NewsItem[] = [
  {
    id: 'n1', symbol: 'NVDA',
    headline: 'NVIDIA unveils new B200 shipments ahead of schedule',
    source: 'Reuters', timestamp: '14m', sentiment: 'bull',
  },
  {
    id: 'n2', symbol: 'AAPL',
    headline: 'Apple China iPhone sales rebound, analysts upgrade target',
    source: 'Bloomberg', timestamp: '42m', sentiment: 'bull',
  },
  {
    id: 'n3', symbol: 'META',
    headline: 'Meta reportedly cuts Reality Labs budget by 15% for 2027',
    source: 'WSJ', timestamp: '1h', sentiment: 'bear',
  },
  {
    id: 'n4', symbol: 'TSLA',
    headline: 'Tesla Q1 deliveries miss consensus, shares slide premarket',
    source: 'CNBC', timestamp: '2h', sentiment: 'bear',
  },
  {
    id: 'n5', symbol: 'AMD',
    headline: 'AMD announces MI400 roadmap, data-center TAM doubles',
    source: 'Reuters', timestamp: '3h', sentiment: 'bull',
  },
  {
    id: 'n6', symbol: 'MSFT',
    headline: 'Microsoft Azure growth steady amid AI capex scrutiny',
    source: 'Bloomberg', timestamp: '4h', sentiment: 'neutral',
  },
];
