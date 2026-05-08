export function notional(mid: number, contracts: number): number {
  return mid * contracts * 100;
}

export function capitalAtRisk(mid: number, contracts: number): number {
  return notional(mid, contracts);
}

export function exposurePct(notional: number, portfolioValue: number): number {
  return portfolioValue > 0 ? notional / portfolioValue : 0;
}

export function hasInvalidation(invalidation: number | undefined): boolean {
  return invalidation !== undefined && invalidation > 0;
}
