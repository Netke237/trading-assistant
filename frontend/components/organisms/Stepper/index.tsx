'use client';

/*
 * Stepper — 7-step Screener workflow. Drift log G4.
 * The current step is derived from the URL (e.g. /screener/step-4-ranking → 4).
 */

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { StepIndicator } from '@/components/molecules/StepIndicator';
import type { StepState } from '@/components/molecules/StepIndicator';
import { Text } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import styles from './Stepper.module.css';

export interface ScreenerStep {
  index: number;           // 1–7
  slug: string;            // e.g. "step-4-ranking"
  label: string;           // e.g. "Stock Ranking"
}

export const SCREENER_STEPS_OPTIONS: ScreenerStep[] = [
  { index: 1, slug: 'step-1-regime',      label: 'Market Regime'        },
  { index: 2, slug: 'step-2-universe',    label: 'Universe'             },
  { index: 3, slug: 'step-3-direction',   label: 'Direction + Horizon'  },
  { index: 4, slug: 'step-4-ranking',     label: 'Stock Ranking'        },
  { index: 5, slug: 'step-5-vol-events',  label: 'Vol + Events'         },
  { index: 6, slug: 'step-6-contracts',   label: 'Contracts'            },
  { index: 7, slug: 'step-7-trade-card',  label: 'Trade Card'           },
];

export const SCREENER_STEPS_STOCKS: ScreenerStep[] = [
  { index: 1, slug: 'step-1-regime',        label: 'Market Regime' },
  { index: 2, slug: 'step-2-universe',      label: 'Universe'      },
  { index: 3, slug: 'step-3-direction',     label: 'Direction'     },
  { index: 4, slug: 'step-4-stocks',        label: 'Strategy'      },
  { index: 5, slug: 'step-6-backtest',      label: 'Backtest'      },
  { index: 6, slug: 'step-7-position-card', label: 'Position'      },
];

export const SCREENER_STEPS_PREBREAKOUT: ScreenerStep[] = [
  { index: 1, slug: 'step-1-regime',          label: 'Market Regime' },
  { index: 2, slug: 'step-2-universe',        label: 'Universe'      },
  { index: 3, slug: 'step-3-direction',       label: 'Direction'     },
  { index: 4, slug: 'step-4-prebreakout',     label: 'Pre-Breakout'  },
];

// Backward-compat export (existing imports keep working):
export const SCREENER_STEPS = SCREENER_STEPS_OPTIONS;

export function getSteps(mode: 'options' | 'stocks' | 'prebreakout'): ScreenerStep[] {
  if (mode === 'stocks') return SCREENER_STEPS_STOCKS;
  if (mode === 'prebreakout') return SCREENER_STEPS_PREBREAKOUT;
  return SCREENER_STEPS_OPTIONS;
}

/** The current step's 1-based INDEX in `steps`, resolved by slug in the active
 *  mode's list: the slug digit and the index differ in Stocks mode since Step 5
 *  was merged into Step 4 (STOCKS-STEP-MERGE-S1). Falls back to the slug digit
 *  only for a slug not in the list (e.g. a cross-mode path before
 *  ScreenerStepGate bounces it), which is what every caller got before. */
export function currentStepFromPath(pathname: string | null, steps?: ScreenerStep[]): number {
  if (!pathname) return 1;
  const m = pathname.match(/\/screener\/(step-[^/?#]+)/);
  if (!m) return 1;
  const hit = steps?.find((s) => s.slug === m[1]);
  if (hit) return hit.index;
  const d = m[1]!.match(/^step-(\d)/);
  return d ? parseInt(d[1]!, 10) : 1;
}

export function Stepper() {
  const pathname = usePathname();
  const router   = useRouter();
  const mode     = useScanStore((s) => s.screenerMode);
  const steps    = getSteps(mode);
  const current  = currentStepFromPath(pathname, steps);

  return (
    <div className={styles.wrap}>
      {steps.map((s) => {
        const state: StepState =
          s.index < current ? 'completed' :
          s.index === current ? 'current' :
          'future';
        return (
          <div key={s.slug} className={styles.stepRow}>
            <StepIndicator
              index={s.index}
              label={s.label}
              state={state}
              onClick={() => router.push(`/screener/${s.slug}`)}
            />
          </div>
        );
      })}
      <Link href="/dashboard" className={styles.exit}>
        <Text size={11} tone="secondary">
          ← Exit Workflow
        </Text>
      </Link>
    </div>
  );
}
