'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Text } from '@/components/primitives';
import { useAlertStore } from '@/lib/alertStore';
import styles from './NavItems.module.css';

interface NavItemDef {
  label: string;
  match: string;
  href: string;
  Icon: React.ComponentType;
}

const ITEMS: NavItemDef[] = [
  { label: 'Dashboard', match: '/dashboard', href: '/dashboard', Icon: DashboardIcon },
  { label: 'Screener',  match: '/screener',  href: '/screener',  Icon: ScreenerIcon  },
  { label: 'Analysis',  match: '/analysis',  href: '/analysis',  Icon: AnalysisIcon  },
  { label: 'Watchlist', match: '/watchlist', href: '/watchlist', Icon: WatchlistIcon },
  { label: 'Portfolio', match: '/portfolio', href: '/portfolio', Icon: PortfolioIcon },
  { label: 'Calendar',  match: '/calendar',  href: '/calendar',  Icon: CalendarIcon  },
  { label: 'Chart',     match: '/chart',     href: '/chart',     Icon: ChartIcon     },
  { label: 'Alerts',    match: '/alerts',    href: '/alerts',    Icon: AlertsIcon    },
  { label: 'Strategy Watch', match: '/strategy-watch', href: '/strategy-watch', Icon: StrategyWatchIcon },
  { label: 'Journal',   match: '/journal',   href: '/journal',   Icon: JournalIcon   },
  { label: 'Settings',  match: '/settings',  href: '/settings',  Icon: SettingsIcon  },
];

export function NavItems() {
  const pathname = usePathname() ?? '';
  const unacknowledgedCount = useAlertStore((s) => s.toasts.filter((t) => !t.acknowledged).length);

  return (
    <nav className={styles.list} aria-label="Primary">
      {ITEMS.map((it) => {
        const active = pathname.startsWith(it.match);
        const showBadge = it.label === 'Alerts' && unacknowledgedCount > 0;
        return (
          <Link
            key={it.label}
            href={it.href}
            className={[styles.item, active ? styles.itemActive : null].filter(Boolean).join(' ')}
            aria-current={active ? 'page' : undefined}
          >
            <span className={styles.iconWrap}>
              <span className={styles.icon}><it.Icon /></span>
              {showBadge && (
                <span className={styles.badge}>
                  {unacknowledgedCount > 99 ? '99+' : unacknowledgedCount}
                </span>
              )}
            </span>
            <Text size={10} tone={active ? 'accent' : 'secondary'}>
              {it.label}
            </Text>
          </Link>
        );
      })}
    </nav>
  );
}

/* ─────────── Icons ─────────── */

function svgProps() {
  return {
    viewBox: '0 0 24 24',
    fill: 'none' as const,
    stroke: 'currentColor',
    strokeWidth: 1.75,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true as const,
    style: { width: '100%', height: '100%' },
  };
}

function DashboardIcon() {
  return (
    <svg {...svgProps()}>
      <rect x="3"  y="3"  width="7" height="9" rx="1" />
      <rect x="14" y="3"  width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3"  y="16" width="7" height="5" rx="1" />
    </svg>
  );
}
function ScreenerIcon() {
  return (
    <svg {...svgProps()}>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.35-4.35" />
    </svg>
  );
}
function AnalysisIcon() {
  return (
    <svg {...svgProps()}>
      <path d="M3 3v18h18" />
      <path d="M7 14l3-3 3 3 4-5" />
    </svg>
  );
}
function WatchlistIcon() {
  return (
    <svg {...svgProps()}>
      <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}
function PortfolioIcon() {
  return (
    <svg {...svgProps()}>
      <rect x="3" y="6" width="18" height="15" rx="2" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}
function CalendarIcon() {
  return (
    <svg {...svgProps()}>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </svg>
  );
}
function ChartIcon() {
  return (
    <svg {...svgProps()}>
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}
function AlertsIcon() {
  return (
    <svg {...svgProps()}>
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
}
function StrategyWatchIcon() {
  return (
    <svg {...svgProps()}>
      <path d="M2 12h4l3 8 4-16 3 8h6" />
    </svg>
  );
}
function JournalIcon() {
  return (
    <svg {...svgProps()}>
      <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22.5v-18Z" />
      <path d="M4 19.5a2.5 2.5 0 0 1 2.5-2.5H20" />
      <path d="M8 7h8M8 11h8" />
    </svg>
  );
}
function SettingsIcon() {
  return (
    <svg {...svgProps()}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}
