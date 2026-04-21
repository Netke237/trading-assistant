/*
 * Default content for the @contextRail parallel slot.
 * Shown when a page does not provide its own @contextRail/page.tsx.
 * Renders the shared QuickLook so watchlist + portfolio info is always
 * visible (screener steps 1–6, calendar, settings, 404s, etc.).
 */

import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';

export default function DefaultContextRail() {
  return <RailQuickLook />;
}
