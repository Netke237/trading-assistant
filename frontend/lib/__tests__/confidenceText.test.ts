import { confidenceTier, confidenceTone } from '@/lib/confidenceText';

test('tiers map to labels', () => {
  expect(confidenceTier(null)).toBe('unknown');
  expect(confidenceTier(undefined)).toBe('unknown');
  expect(confidenceTier(20)).toBe('low');
  expect(confidenceTier(55)).toBe('moderate');
  expect(confidenceTier(80)).toBe('high');
});

test('tones map to Data tones', () => {
  expect(confidenceTone('high')).toBe('pass');
  expect(confidenceTone('moderate')).toBe('caution');
  expect(confidenceTone('low')).toBe('reject');
  expect(confidenceTone('unknown')).toBe('dim');
});
