import { redirect } from 'next/navigation';

/** Step 5 (Strategy) was merged into Step 4 (decision STOCKS-STEP-MERGE-2026-10-04).
 *  The route stays so old links and bookmarks land on the picker. In Options or
 *  Pre-Breakout mode, ScreenerStepGate then bounces step-4-stocks to that
 *  mode's own step 4. */
export default function Step5Redirect(): never {
  redirect('/screener/step-4-stocks');
}
