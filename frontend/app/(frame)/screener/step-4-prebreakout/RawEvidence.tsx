'use client';
import { useEffect, useRef } from 'react';
import styles from './page.module.css';

export function RawEvidence({ value, label }: { value: unknown; label: string }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => { if (ref.current) ref.current.open = false; }, [value]);
  return <details ref={ref} className={styles.contextDisclosure}>
    <summary>Raw data: {label}</summary>
    <pre>{JSON.stringify(value, null, 2) ?? 'Unavailable'}</pre>
  </details>;
}
