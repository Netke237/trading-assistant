/*
 * Manual broker-attempt reads. Uses the same API origin and error text as
 * `api.ts` and does not add a second credential path. Verification is a user
 * assertion; nothing here places, retries, or removes an order.
 */

import { API_BASE_URL } from '@/lib/api';
import { isAcceptedNotFilled } from '@/lib/directOrder';
import { validationMessages } from '@/lib/pydanticError';

export const DEFERRED_COVERAGE_NOTE =
  'Precise quantity release is deferred. This order keeps its exposure coverage.';

export type VerificationOutcome =
  | 'submitted'
  | 'filled'
  | 'definitely-not-submitted'
  | 'canceled-after-submission'
  | 'partial';

export interface BrokerAttemptPayload {
  kind: string;
  broker: string;
  symbol: string;
  instrument: string;
  action: string;
  effect: string;
  quantity: number;
  order_type: string;
  limit: string | null;
  tif: string;
  conid: number | null;
}

export interface BrokerAttemptRecord {
  attempt_id: string;
  state: string;
  fingerprint: string;
  verification_version: number;
  saved_rec_id: string | null;
  broker_order_id: string | null;
  broker_status: string | null;
  broker_response: string | null;
  payload: BrokerAttemptPayload;
  verification_outcome: string | null;
  verification_note: string | null;
  outcome_label: string;
  coverage_note: string | null;
  created_at: string;
  updated_at: string;
}

export function submissionDisplayLabel(attempt: {
  state?: string | null;
  broker_status?: string | null;
  outcome_label?: string | null;
  verification_outcome?: string | null;
}): string {
  if (isAcceptedNotFilled(attempt.broker_status)) return 'submitted';
  if (attempt.verification_outcome === 'partial') return 'partial';
  if (attempt.verification_outcome === 'canceled-after-submission') return 'canceled after submission';
  if (attempt.verification_outcome === 'definitely-not-submitted' || attempt.state === 'proven-not-submitted') {
    return 'not submitted';
  }
  if (attempt.verification_outcome === 'filled' || attempt.state === 'filled') return 'filled';
  const status = String(attempt.broker_status ?? '').trim().toLowerCase();
  if (status === 'filled' || status === 'fill') return 'filled';
  if (attempt.verification_outcome === 'submitted' || attempt.state === 'submitted') return 'submitted';
  if (attempt.state === 'outcome-unknown') return 'outcome unknown';
  if (attempt.outcome_label && !/filled/i.test(attempt.outcome_label)) return attempt.outcome_label;
  if (attempt.state === 'preparing' || attempt.state === 'dispatching') return 'unverified';
  return attempt.state || 'unverified';
}

async function fail(path: string, res: Response): Promise<never> {
  const text = await res.text().catch(() => '');
  let detail = text;
  try {
    const json = JSON.parse(text) as { detail?: unknown };
    if (typeof json?.detail === 'string') detail = json.detail;
    else if (Array.isArray(json?.detail)) detail = validationMessages(json.detail) ?? text;
  } catch { /* not JSON */ }
  throw new Error(`API ${path} → ${res.status}${detail ? `: ${detail}` : ''}`);
}

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, signal });
  if (!res.ok) return fail(path, res);
  return res.json() as Promise<T>;
}

export async function listBrokerAttempts(signal?: AbortSignal): Promise<BrokerAttemptRecord[]> {
  const body = await request<{ attempts: BrokerAttemptRecord[] }>('/broker/attempts', undefined, signal);
  return body.attempts;
}

export function getBrokerAttempt(attemptId: string, signal?: AbortSignal): Promise<BrokerAttemptRecord> {
  return request<BrokerAttemptRecord>(`/broker/attempts/${encodeURIComponent(attemptId)}`, undefined, signal);
}

export function verifyBrokerAttempt(
  attemptId: string,
  body: { outcome: VerificationOutcome; note: string; expected_version: number },
  signal?: AbortSignal,
): Promise<BrokerAttemptRecord> {
  return request<BrokerAttemptRecord>(
    `/broker/attempts/${encodeURIComponent(attemptId)}/verify`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    signal,
  );
}
