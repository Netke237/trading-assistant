import { Suspense } from 'react';
import ChartWorkspace from '@/components/organisms/ChartWorkspace';
import styles from './page.module.css';

export default function ChartPage() {
  return (
    <main className={styles.page}>
      <Suspense fallback={null}>
        <ChartWorkspace />
      </Suspense>
    </main>
  );
}
