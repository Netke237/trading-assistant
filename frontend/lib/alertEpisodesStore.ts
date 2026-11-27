/**
 * Current alert episodes for open positions (PORTFOLIO-ALERT-ACTION, #672),
 * read from `GET /api/alerts/episodes`.
 *
 * NO `persist()`, deliberately: a stored episode list would show a stale
 * duration after a reload. The Portfolio page calls `refresh()` on mount and
 * every 60 s while mounted.
 *
 * On a failed fetch `error` is set and `episodes` is left as it was; readers
 * must treat `error !== null` as "duration unavailable" (lib/actionNeeded.ts
 * does), never fall back to the older list.
 */
import { create } from 'zustand';
import { fetchAlertEpisodes, type AlertEpisode } from '@/lib/api';
import { episodeKey } from '@/lib/alertEpisodes';

interface AlertEpisodesState {
  /** Keyed by `episodeKey(recId, alertType)`. Null until the first success. */
  episodes: Record<string, AlertEpisode> | null;
  /** The effective gap the backend computed the episodes with. */
  gapHours: number | null;
  /** ms epoch of the last successful fetch. */
  fetchedAt: number | null;
  error: string | null;
  refresh: () => Promise<void>;
}

// Only the latest request may write: a slow earlier response must not
// overwrite a newer one.
let requestSeq = 0;

export const useAlertEpisodesStore = create<AlertEpisodesState>()((set) => ({
  episodes: null,
  gapHours: null,
  fetchedAt: null,
  error: null,
  refresh: async () => {
    const seq = ++requestSeq;
    try {
      const res = await fetchAlertEpisodes();
      if (seq !== requestSeq) return;
      const episodes: Record<string, AlertEpisode> = {};
      for (const e of res.episodes ?? []) episodes[episodeKey(e.recId, e.alertType)] = e;
      set({ episodes, gapHours: res.gapHours, fetchedAt: Date.now(), error: null });
    } catch (err) {
      if (seq !== requestSeq) return;
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },
}));
