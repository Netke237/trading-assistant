import { Suspense } from 'react';
import CandidateChartWorkspace from '@/components/organisms/CandidateChartWorkspace';
import styles from './page.module.css';

export default function ChartPage() {
  return (
    <main className={styles.page}>
      <Suspense fallback={null}>
        <CandidateChartWorkspace />
      </Suspense>
    </main>
  );
}
