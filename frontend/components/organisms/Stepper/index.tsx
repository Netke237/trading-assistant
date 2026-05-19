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
import styles from './Stepper.module.css';

export interface ScreenerStep {
  index: number;           // 1–7
  slug: string;            // e.g. "step-4-ranking"
  label: string;           // e.g. "Stock Ranking"
}

export const SCREENER_STEPS: ScreenerStep[] = [
  { index: 1, slug: 'step-1-regime',      label: 'Market Regime'        },
  { index: 2, slug: 'step-2-universe',    label: 'Universe'             },
  { index: 3, slug: 'step-3-direction',   label: 'Direction + Horizon'  },
  { index: 4, slug: 'step-4-ranking',     label: 'Stock Ranking'        },
  { index: 5, slug: 'step-5-vol-events',  label: 'Vol + Events'         },
  { index: 6, slug: 'step-6-contracts',   label: 'Contracts'            },
  { index: 7, slug: 'step-7-trade-card',  label: 'Trade Card'           },
];

export function currentStepFromPath(pathname: string | null): number {
  if (!pathname) return 1;
  const m = pathname.match(/\/screener\/step-(\d)/);
  return m ? parseInt(m[1]!, 10) : 1;
}

export function Stepper() {
  const pathname = usePathname();
  const router   = useRouter();
  const current  = currentStepFromPath(pathname);

  return (
    <div className={styles.wrap}>
      {SCREENER_STEPS.map((s) => {
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
