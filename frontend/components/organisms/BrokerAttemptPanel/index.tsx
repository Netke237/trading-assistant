'use client';

/*
 * Unresolved broker attempts. The user asserts what the broker shows.
 * There is no retry, remove, auto-fill, or broker lookup on this panel.
 */

import { useEffect, useState } from 'react';
import { Data, Text } from '@/components/primitives';
import {
  DEFERRED_COVERAGE_NOTE,
  listBrokerAttempts,
  submissionDisplayLabel,
  verifyBrokerAttempt,
  type BrokerAttemptRecord,
  type VerificationOutcome,
} from '@/lib/brokerAttempts';
import styles from './BrokerAttemptPanel.module.css';

const OUTCOMES: { value: VerificationOutcome; label: string }[] = [
  { value: 'submitted', label: 'submitted' },
  { value: 'filled', label: 'filled' },
  { value: 'definitely-not-submitted', label: 'not submitted' },
  { value: 'canceled-after-submission', label: 'canceled after submission' },
  { value: 'partial', label: 'partial' },
];

export function BrokerAttemptPanel() {
  const [attempts, setAttempts] = useState<BrokerAttemptRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [pending, setPending] = useState<string | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [rowError, setRowError] = useState<Record<string, string>>({});

  useEffect(() => {
    const ac = new AbortController();
    let live = true;
    listBrokerAttempts(ac.signal)
      .then((rows) => { if (live) { setError(null); setAttempts(rows); } })
      .catch((e: unknown) => {
        if (live && !ac.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { live = false; ac.abort(); };
  }, [reload]);

  if (error) {
    return (
      <section className={styles.panel} aria-label="Unverified broker orders">
        <Text size={13} tone="reject">{error}</Text>
      </section>
    );
  }
  if (!attempts || attempts.length === 0) return null;

  return (
    <section className={styles.panel} aria-label="Unverified broker orders">
      <Text as="p" size={13} weight={400}>Unverified broker orders</Text>
      <Text as="p" size={12} tone="secondary" weight={400}>
        These orders stay blocked until you verify them at the broker. This does not send, retry, or remove an order.
      </Text>
      {attempts.map((attempt) => {
        const choice = choices[attempt.attempt_id] ?? '';
        const note = notes[attempt.attempt_id] ?? '';
        const showDeferred = choice === 'partial'
          || choice === 'canceled-after-submission'
          || Boolean(attempt.coverage_note);
        const price = attempt.payload.order_type === 'MKT' || attempt.payload.limit == null
          ? 'MKT'
          : attempt.payload.limit;
        const hasEvidence = Boolean(attempt.broker_order_id || attempt.broker_status || attempt.broker_response);
        return (
          <article key={attempt.attempt_id} className={styles.attempt} data-testid={`attempt-${attempt.attempt_id}`}>
            <div className={styles.row}>
              <Data size={12}>{attempt.attempt_id}</Data>
              <Data size={12}>{attempt.payload.symbol}</Data>
              <Text size={12} weight={400}>{attempt.payload.effect}</Text>
              <Data size={12}>{attempt.payload.quantity}</Data>
              <Data size={12}>{price}</Data>
              <span data-testid={`outcome-${attempt.attempt_id}`}>
                <Text size={12} weight={400}>{submissionDisplayLabel(attempt)}</Text>
              </span>
            </div>
            <Text size={12} tone="secondary" weight={400}>
              {attempt.saved_rec_id ?? 'not linked to a saved row'}
            </Text>
            {hasEvidence ? (
              <div className={styles.row}>
                {attempt.broker_order_id && <Data size={12}>{attempt.broker_order_id}</Data>}
                {attempt.broker_status && <Text size={12} weight={400}>{attempt.broker_status}</Text>}
              </div>
            ) : (
              <Text size={12} tone="secondary" weight={400}>No broker evidence recorded</Text>
            )}
            <label className={styles.field}>
              <Text size={12} weight={400}>{`Verification for ${attempt.attempt_id}`}</Text>
              <select
                aria-label={`Verification for ${attempt.attempt_id}`}
                value={choice}
                onChange={(event) => setChoices((prev) => ({ ...prev, [attempt.attempt_id]: event.target.value }))}
              >
                <option value="">Choose what you verified</option>
                {OUTCOMES.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <label className={styles.field}>
              <Text size={12} weight={400}>{`Evidence for ${attempt.attempt_id}`}</Text>
              <textarea
                aria-label={`Evidence for ${attempt.attempt_id}`}
                value={note}
                onChange={(event) => setNotes((prev) => ({ ...prev, [attempt.attempt_id]: event.target.value }))}
              />
            </label>
            {showDeferred && (
              <Text size={12} tone="caution" weight={400}>{attempt.coverage_note || DEFERRED_COVERAGE_NOTE}</Text>
            )}
            {rowError[attempt.attempt_id] ? (
              <Text size={12} tone="reject">{rowError[attempt.attempt_id]}</Text>
            ) : null}
            <button
              type="button"
              className={styles.action}
              disabled={pending === attempt.attempt_id || choice === '' || note.trim() === ''}
              onClick={() => {
                const outcome = choice as VerificationOutcome;
                void (async () => {
                  setPending(attempt.attempt_id);
                  try {
                    await verifyBrokerAttempt(attempt.attempt_id, {
                      outcome,
                      note: note.trim(),
                      expected_version: attempt.verification_version,
                    });
                    setReload((value) => value + 1);
                  } catch (e) {
                    setRowError((prev) => ({
                      ...prev,
                      [attempt.attempt_id]: e instanceof Error ? e.message : String(e),
                    }));
                  } finally {
                    setPending(null);
                  }
                })();
              }}
            >
              {`Record verification for ${attempt.attempt_id}`}
            </button>
          </article>
        );
      })}
    </section>
  );
}
