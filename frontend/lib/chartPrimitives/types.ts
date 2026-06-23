import type { ISeriesPrimitive } from 'lightweight-charts';
import type { Drawing } from '@/types/overlays';

/** Drawing primitive that supports in-place data mutation without detach/re-attach. */
export interface UpdatablePrimitive extends ISeriesPrimitive {
  update(drawing: Drawing): void;
}
