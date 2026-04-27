import { ModeToggle } from '@/components/atoms/ModeToggle';
import styles from './TopBarActions.module.css';

export function TopBarActions() {
  return (
    <div className={styles.root}>
      <ModeToggle />
    </div>
  );
}
