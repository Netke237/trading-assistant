import React from 'react';
import styles from './ContractExplanationToggle.module.css';

export interface ContractExplanationToggleProps {
  isOpen: boolean;
  onToggle: () => void;
  controlsId: string;
  contractLabel: string;
  disabled?: boolean;
}

export const ContractExplanationToggle: React.FC<ContractExplanationToggleProps> = ({
  isOpen,
  onToggle,
  controlsId,
  contractLabel,
  disabled = false,
}) => {
  return (
    <button
      type="button"
      className={`${styles.toggleBtn} ${isOpen ? styles.open : ''}`}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      onKeyDown={(e) => {
        if (e.key === ' ' || e.key === 'Enter') {
          e.stopPropagation();
        }
      }}
      aria-expanded={isOpen}
      aria-controls={controlsId}
      aria-label={isOpen ? `Hide score explanation for ${contractLabel}` : `Explain score for ${contractLabel}`}
      disabled={disabled}
    >
      <span>{isOpen ? 'Hide' : 'Explain'}</span>
      <span className={`${styles.chevron} ${isOpen ? styles.chevronOpen : ''}`} aria-hidden="true">
        ▼
      </span>
    </button>
  );
};
