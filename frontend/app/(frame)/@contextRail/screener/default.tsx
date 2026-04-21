/*
 * Default rail for any screener sub-route without its own @contextRail page
 * (steps 1–6). Shows the shared QuickLook so the user always sees watchlist
 * + portfolio totals while working through the scan.
 */

import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';

export default function ScreenerDefaultRail() {
  return <RailQuickLook />;
}
