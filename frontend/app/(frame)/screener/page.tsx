/*
 * /screener → redirect to step 1. The nav rail enters "stepper mode" as soon as
 * the URL starts with /screener (see NavRail), so landing on the bare /screener
 * path should push the user straight into the workflow.
 */

import { redirect } from 'next/navigation';

export default function ScreenerIndex() {
  redirect('/screener/step-1-universe');
}
