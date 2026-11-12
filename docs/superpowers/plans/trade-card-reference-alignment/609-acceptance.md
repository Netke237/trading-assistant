# #609 — concise basket and broker destination reviews

Covers D12 and the destination-review aspect of D11. The presentation reference is frozen at d8245e66. The authoritative draft, server preview and fingerprint, normalisation, changed-value rejection and submitted values are unchanged. #591 (the missing-expiry refusal) merged into this branch first, via PR #613 at 9067538.

Implementation: `564d656` (`fix(trade-card): simplify destination reviews without changing safeguards`).

## What changed

Three reviews now use the reference's grouping, followed by a default-closed `details[data-review-details]`. They are the inline **SubmissionReview**, the **BrokerOrderReview** (Place Limit / Right Now — Market) and the **basket row review** in SendToBrokerDialog.

The three groups are:
- **Destination and request**: destination; contract and expiry; quantity; order type, limit or tracked-entry basis; requested versus server values.
- **Position settings**: stock, structural and premium stops, and the ≤3 DTE time-exit alert. A visible note says no protective stop-loss or take-profit order is sent to a broker.
- **Target alert basis**: method, recorded targets, judged-on basis, effective target alert.

The closed details hold draft generation, the exact broker request JSON, mode and time in force, the review fingerprint, the saved-row id and the long resolution notes.

**Stays visible:**
- the provisional and not-a-fill labels;
- requested versus server-resolved values;
- the changed-since-review warning, with Confirm disabled;
- refusals before sending, including the #591 missing-expiry reason;
- the spread caution and premium-stop-unapplied caution;
- result, pending and rejection feedback (BrokerOrderOutcome is unchanged).

The stale "Final Recommendation" wording is gone. The page passes the reviewed position's own expiry to BrokerOrderReview for display.

## Payload parity

New page tests pin the Track basket create bodies and fingerprints, the direct-send preview body, the persist body and the broker order body. The literals were captured from the code before the change, and only the per-click stamps are normalised. The tests pass both before and after the change.

## Browser evidence

[browser-checks.json](evidence/609/browser-checks.json):
- 6 runs: 1200, 1366 and 1920 px, each in dark and light.
- 30 checks per run, all passed. 0 page errors, 0 saves or broker writes (nothing was confirmed), 0 external requests.

What the checks cover:
- **Group order:** each of the three reviews shows its three groups in order, with the closed technical details after them.
- **No stale wording:** no "Final Recommendation" text remains.
- **Visible notes:** the no-protective-order and no-broker-order notes are visible.
- **Draft generation** is reachable in the details.
- **Basket review:** requested versus server-adjusted values are kept.
- **Broker review:** it names the destination and shows the expiry 2026-12-18, and the exact broker JSON is hidden in the closed details.
- **Changed review:** changing Contracts after the review shows "Changed since this review" and Confirm is refused.

Screenshots:
- [submission](evidence/609/1366-dark-submission.png)
- [basket review](evidence/609/1366-dark-basket-review.png)
- [broker review, light](evidence/609/1366-light-broker-review.png)
- [broker stale](evidence/609/1366-dark-broker-stale.png)
- [1920 light](evidence/609/1920-light-submission.png)

To reproduce, run this against a local mocked frontend on port 3097, never the live port 3001:

```sh
node docs/superpowers/plans/trade-card-reference-alignment/capture-reviews.cjs \
  --repo-root "$PWD" --output /tmp/tc609-browser --base-url http://127.0.0.1:3097 \
  --browser /opt/pw-browsers/chromium --widths 1200,1366,1920 --themes dark,light
```

## Local checks (re-run by the coordinator at 564d656)

- Typecheck is clean.
- Full Jest (`--maxWorkers=2`) passed in one run: 341/341 suites, 6310/6310 tests.
- Expected-red: before the change, 4/5 new SubmissionReview tests, 4/4 new BrokerOrderReview tests and 3/3 new basket-review tests failed on the missing groups and details. The fifth SubmissionReview test and the parity pins are invariance guards that pass both before and after.

## Deviations and notes

- **New `expiry` field.** `BrokerOrderReviewData` gained `expiry: string | null` for display.
- **Time-exit row.** It uses the existing `TIME_STOP_DTE`.
- **Expiry format.** The expiry shows as an ISO date, not the long form.
- **Visual gap vs reference.** The reference lays these reviews out as a compact three-column grid of large values in a dialog. Ours is still a long single-column monospace list. The grouping and content match; the visual density does not. This is recorded for the visual-alignment pass and #610.
- **Not fixed (noticed):**
  - Track basket still stores a DTE-derived expiry when the contract has none. The review now says so; changing it is outside this ticket.
  - The size-10 uppercase rendering of some notes.

## Status

This is ticket-level acceptance only. The integrated phase code audit is still pending, and #610 remains.
