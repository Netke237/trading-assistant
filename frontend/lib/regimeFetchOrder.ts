// Which /api/regime response may write the shared regime gate
// (`scanStore.regime`, `regimeDirection`, `combinedRegime`) — APP-AUDIT-B-REGIME-RACE.
//
// Steps 1, 2 and 3 all fetch the gate reading, and their callbacks keep running
// after the page unmounts (the reading must land even when the user moves on).
// So a request started earlier can answer after a later one already landed.
// Every fetch takes a ticket when it starts; a response writes the gate only if
// its ticket is newer than the last one written. An older response therefore
// never replaces a newer one, but still fills the gate while the newer request
// is pending or if it fails.
//
// Module-level, not React state: requests outlive the page that started them.
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { alignmentVerdict, descriptorFromState } from '@/lib/regimeAlignment';
import type { MarketRegime } from '@/types/domain';

let nextTicket = 0;
let lastAppliedTicket = 0;

/** The gate reading request every screener step sends: 'intraday' (so the HMM
 *  is always computed) with the Settings Markov values read at call time, so
 *  every response the ordering compares comes from the same model. */
export function fetchGateRegime(): Promise<MarketRegime> {
  const { lookback, threshold, smoothing } = useSettingsStore.getState().markov;
  return api.getRegime('intraday', { lookback, threshold, smoothing });
}

/** Call when a Step 1–3 regime fetch starts; returns its ticket. */
export function beginRegimeFetch(): number {
  return ++nextTicket;
}

/** Writes regime, regimeDirection and combinedRegime from `r` only if `ticket`
 *  is newer than the last applied ticket; records it. Returns whether it wrote.
 *  The verdict uses the context direction at write time. */
export function applyRegimeResponse(ticket: number, r: MarketRegime): boolean {
  if (ticket <= lastAppliedTicket) return false;
  lastAppliedTicket = ticket;
  const s = useScanStore.getState();
  s.setRegime(r.overall);
  s.setRegimeDirection(r.regime_direction ?? null);
  const direction = s.context?.direction ?? 'Bullish';
  s.setCombinedRegime(alignmentVerdict(direction, descriptorFromState(r.omm?.state ?? '')));
  return true;
}
