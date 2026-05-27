import { Suspense } from 'react';
import ChartWorkspace from '@/components/organisms/ChartWorkspace';

export default function StandalonePage() {
  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#0b0b14', overflow: 'hidden' }}>
      <Suspense fallback={null}>
        <ChartWorkspace />
      </Suspense>
    </div>
  );
}
