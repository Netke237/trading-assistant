/*
 * The ONE rung-shrink rule (stock plan Q1). Identical to the backend's
 * position_writer.scale_rung_quantities (test_position_writer_gates.py T-A10,
 * T-A10b pin the same numbers there).
 */
import { scaleRungShares } from '@/lib/paperTrade';

const r = (...qs: number[]) => qs.map((q) => ({ contractsToSell: q }));
const qs = (t: { contractsToSell?: number }[] | undefined) => t?.map((x) => x.contractsToSell);

it('scales rungs that exceed the new quantity; the last takes the remainder', () => {
  expect(qs(scaleRungShares(r(66, 66, 68), 100))).toEqual([33, 33, 34]);
  expect(qs(scaleRungShares(r(10, 33, 34), 50))).toEqual([6, 21, 23]);
});

it('leaves rungs alone when they already fit (the runner stays unallocated)', () => {
  expect(qs(scaleRungShares(r(10, 33, 34), 80))).toEqual([10, 33, 34]);
});

it('ignores rungs with no share count, and never grows a rung', () => {
  const t = [{ price: 1 }, { price: 2, contractsToSell: 150 }];
  expect(scaleRungShares(t, 100)).toEqual([{ price: 1 }, { price: 2, contractsToSell: 100 }]);
  expect(qs(scaleRungShares(r(10, 10), 500))).toEqual([10, 10]);
  expect(scaleRungShares(undefined, 5)).toBeUndefined();
});
