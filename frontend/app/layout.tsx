import type { Metadata, Viewport } from 'next';
import { Sora, DM_Sans, JetBrains_Mono } from 'next/font/google';
import { ThemeProvider } from '@/components/ThemeProvider';
import { StoreHydration } from '@/components/StoreHydration';
import { MinWidthGate } from '@/components/MinWidthGate';
import './globals.css';

/*
 * Three-font rule — design spec §2 and drift log G1.
 * Consumed by:
 *   - components/primitives/Title.tsx  (Sora)
 *   - components/primitives/Text.tsx   (DM Sans)
 *   - components/primitives/Data.tsx   (JetBrains Mono)
 */
const sora = Sora({
  subsets: ['latin'],
  weight: ['700'],
  variable: '--font-sora',
  display: 'swap',
});

const dmSans = DM_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-dm',
  display: 'swap',
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Bamendjou — Options Screener',
  description: 'Options screener and trade planning assistant.',
};

export const viewport: Viewport = {
  themeColor: '#131722',
};

/*
 * No-flash theme script — reads the persisted theme BEFORE React hydrates
 * and sets data-theme accordingly. Keep the storage key in sync with
 * lib/theme.ts THEME_STORAGE_KEY. Wrapped in try/catch because
 * localStorage can throw in privacy modes.
 */
const noFlashScript = `
(function(){try{
  var raw = localStorage.getItem('bamendjou:theme');
  if (!raw) return;
  var parsed = JSON.parse(raw);
  var t = parsed && parsed.state && parsed.state.theme;
  if (t === 'light' || t === 'dark') {
    document.documentElement.dataset.theme = t;
  }
  var d = parsed && parsed.state && parsed.state.density;
  if (d === 'Compact' || d === 'Comfortable') {
    document.documentElement.dataset.density = d.toLowerCase();
  }
}catch(e){}})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      translate="no"
      data-theme="dark"
      data-density="comfortable"
      className={`${sora.variable} ${dmSans.variable} ${jetBrainsMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <meta name="google" content="notranslate" />
        <script dangerouslySetInnerHTML={{ __html: noFlashScript }} />
      </head>
      <body>
        <StoreHydration />
        <ThemeProvider>
          <MinWidthGate>{children}</MinWidthGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
