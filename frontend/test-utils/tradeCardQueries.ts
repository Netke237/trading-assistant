/*
 * Scoped role queries for the Options Step 7 trade-card suites
 * (TUNER-RECHECK-WINDOW Task 2a, #647).
 *
 * A global `screen.*ByRole('button', …)` computes the accessible name of every
 * button on the whole Step 7 page — every method card, ladder row, editable
 * field and disclosure — and jsdom resolves styles for each one. Locally that
 * pushed several tests past Jest's default 5 s limit. These helpers restrict
 * only the PARENT search scope to the semantic container the test targets;
 * the role, the accessible name (string or regex), the default visibility
 * filtering and the async waits are unchanged.
 *
 * Every accessor re-queries its container on every call, and the `find…`
 * helpers re-query it on every retry, so nothing is cached across a candidate
 * change, a remount or a regenerated review.
 *
 * Containers (verified against the rendered DOM):
 *   - `region` "Decision and execution" — TradeCard's decision section. While
 *     a TradeCard is mounted it holds the page's `executionActions` (broker
 *     picker, Place Limit, Right Now — Market), Track basket, and the page's
 *     `destinations` panel (Broker order review, AutoTradeArm).
 *   - `group` "Broker execution and auto-trade" — the page's execution panel
 *     (Broker order review, the direct-send notes and their Remove buttons,
 *     AutoTradeArm). Inside the decision region while a TradeCard is mounted,
 *     standing alone below the card column while one is not.
 *   - `region` "Broker order review" — BrokerOrderReview; its final action is
 *     the "Send to …" confirmation.
 *   - `dialog` "Track basket in Portfolio" — SendToBrokerDialog.
 *   - `region` "Profit-target methods" — holds the Fixed % Ladder Plan
 *     collapsible section and its toggle.
 */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import type { ByRoleMatcher, ByRoleOptions } from '@testing-library/react';

export const DECISION_AND_EXECUTION = 'Decision and execution';
export const EXECUTION_PANEL = 'Broker execution and auto-trade';
export const BROKER_ORDER_REVIEW = 'Broker order review';
export const TRACK_BASKET_DIALOG = 'Track basket in Portfolio';
export const PROFIT_TARGET_METHODS = 'Profit-target methods';

/** Queries bound to the current "Decision and execution" region. */
export function decisionRegion() {
  return within(screen.getByRole('region', { name: DECISION_AND_EXECUTION }));
}

/** `findByRole` inside the decision region, re-querying the region on every retry. */
export function findInDecision(role: ByRoleMatcher, options?: ByRoleOptions) {
  return waitFor(() => decisionRegion().getByRole(role, options));
}

/** Queries bound to the page's broker execution panel. */
export function executionPanel() {
  return within(screen.getByRole('group', { name: EXECUTION_PANEL }));
}

/** Queries bound to the open Track basket dialog. */
export function basketDialog() {
  return within(screen.getByRole('dialog', { name: TRACK_BASKET_DIALOG }));
}

/** `findByRole` inside the Track basket dialog, re-querying the dialog on every retry. */
export function findInBasketDialog(role: ByRoleMatcher, options?: ByRoleOptions) {
  return waitFor(() => basketDialog().getByRole(role, options));
}

/** Queries bound to the "Profit-target methods" region. */
export function profitTargetMethods() {
  return within(screen.getByRole('region', { name: PROFIT_TARGET_METHODS }));
}

/** `findByRole` inside the profit-target methods, re-querying the region on every retry. */
export function findInProfitTargetMethods(role: ByRoleMatcher, options?: ByRoleOptions) {
  return waitFor(() => profitTargetMethods().getByRole(role, options));
}

/** #583 — a direct send opens the server review first; its final action saves
 *  and sends. A send refused before the review (a gate, a quote warning)
 *  opens none, and nothing is clicked.
 *
 *  "Placing…" is only ever the label of the two direct-send buttons, which sit
 *  in the decision region whenever a TradeCard is mounted. With no card
 *  mounted (an overridden contract still recomputing) they render outside it,
 *  so the wait falls back to the whole page exactly as before. */
export async function confirmReview() {
  await waitFor(() => {
    const decision = screen.queryByRole('region', { name: DECISION_AND_EXECUTION });
    expect((decision ? within(decision) : screen).queryByRole('button', { name: 'Placing…' })).not.toBeInTheDocument();
  });
  const review = screen.queryByRole('region', { name: BROKER_ORDER_REVIEW });
  const confirm = review ? within(review).queryByRole('button', { name: /^Send to / }) : null;
  if (confirm) fireEvent.click(confirm);
}
