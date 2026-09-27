/*
 * P1b-i's direct-send helpers moved to `lib/directOrder.ts` (STOCK-SENDS): the
 * stock send paths in `lib/` and `components/` share them, and those cannot
 * import from `app/`. Re-exported here so the options page and its tests keep
 * their import path.
 */
export * from '@/lib/directOrder';
