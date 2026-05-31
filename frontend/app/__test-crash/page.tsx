'use client'

import { notFound } from 'next/navigation';

export default function TestCrashPage() {
  if (process.env.NODE_ENV !== 'development') notFound();
  throw new Error('Deliberate crash for error boundary integration test')
}
