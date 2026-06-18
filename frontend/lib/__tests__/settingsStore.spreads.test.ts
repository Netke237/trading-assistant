import { useSettingsStore } from '@/lib/settingsStore';

test('spread defaults exist', () => {
  const s = useSettingsStore.getState();
  expect(s.spreads.shortLegDelta).toBe(0.30);
  expect(s.spreads.widthPoints).toBe(5);
  expect(s.spreads.ivRankThreshold).toBe(50);
  expect(s.spreads.minCredit).toBe(0.50);
  expect(s.spreads.maxDebitPctOfWidth).toBe(40);
});
