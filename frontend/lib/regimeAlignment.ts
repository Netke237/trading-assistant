import type { Direction, HmmState } from '@/types/domain';
import type { Status } from '@/lib/status';

export type RegimeDescriptor = HmmState;

export function alignmentVerdict(direction: Direction, descriptor: RegimeDescriptor): Status {
  if (descriptor === 'Choppy') return 'CAUTION';
  const agrees =
    (direction === 'Bullish' && descriptor === 'Bull') ||
    (direction === 'Bearish' && descriptor === 'Bear');
  return agrees ? 'PASS' : 'REJECT';
}

export function descriptorFromState(state: string): RegimeDescriptor {
  if (state === 'Bull') return 'Bull';
  if (state === 'Bear') return 'Bear';
  return 'Choppy';
}
