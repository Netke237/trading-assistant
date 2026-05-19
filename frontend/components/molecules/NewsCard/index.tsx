import { Text } from '@/components/primitives';
import type { NewsItem } from '@/types/domain';
import styles from './index.module.css';

interface NewsCardProps {
  items: NewsItem[];
  loading?: boolean;
  limit?: number;
}

function relativeTime(iso: string): string {
  const now = new Date();
  const then = new Date(iso);
  const diffMs = now.getTime() - then.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return 'just now';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

export function NewsCard({ items, loading, limit }: NewsCardProps) {
  if (loading) {
    return (
      <div>
        <div className={styles.skeleton} />
        <div className={styles.skeleton} />
        <div className={styles.skeleton} />
      </div>
    );
  }

  if (items.length === 0) {
    return <Text size={12} tone="dim">No news for current candidates.</Text>;
  }

  const visible = limit ? items.slice(0, limit) : items;

  return (
    <div>
      {visible.map((item) => (
        <div key={item.id} className={styles.item}>
          <Text size={12} tone="primary">{item.headline}</Text>
          <Text size={11} tone="dim">{item.source} · {relativeTime(item.timestamp)}</Text>
        </div>
      ))}
    </div>
  );
}
