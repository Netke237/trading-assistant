import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Options Screener',
  description: 'Discretionary options screener and trade recommendation UI.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
