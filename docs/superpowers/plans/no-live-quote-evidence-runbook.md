# NO-LIVE-QUOTE Step 0 evidence collection

This is instrumentation for the parked `2026-09-30-no-live-quote-plan.md`,
not a quote-quality design or a product implementation ticket. Observe production
responses before rewriting the parked plan or deciding timestamp/age rules.

## Current readiness

The virtual session has Python 3.11.16 at
`/tmp/no-live-quote-python/cpython-3.11-linux-x86_64-gnu/bin/python3.11`.
This path is session-specific. Elsewhere choose a Python 3.11 interpreter and
verify its `--version`; the collector rejects other minor versions.
The inspected runtime has no configured secrets, variables or identities, and
its restricted network manifest does not grant Tradier hosts. No production
sample has been collected. A production `TRADIER_API_TOKEN` and permitted HTTPS
access to `api.tradier.com` are prerequisites. Do not read credential files or
paste a token into a command, report or repository.

## Manual capture

From the repository root, with the production token configured in the process
environment, create a private evidence directory outside Git and run:

```bash
mkdir -m 700 /tmp/tradier-quote-evidence
/tmp/no-live-quote-python/cpython-3.11-linux-x86_64-gnu/bin/python3.11 scripts/evidence/tradier_raw_chain.py \
  --symbol SPY --expiration 2026-10-16 --session in-session \
  --output /tmp/tradier-quote-evidence/spy-20261016-in-session-001.json
```

The symbol and expiration above are examples, not verified available contracts.
Choose and record an actual listed expiration that will remain available for the
four collection windows. Use a new output path each time. No daemon or scheduling
is installed. Requests only read the direct production
`/v1/markets/options/chains` endpoint; there is no sandbox or application fallback.
The request has a 30-second socket timeout and uses inherited proxy settings and
normal CA verification. A provider failure or malformed response produces no
new evidence file. Output files are atomically published with mode 0600 and
existing captures are never overwritten. Successful explicit empty chains are
recorded with zero rows and cannot establish quote behavior.

## Evidence manifest and timing

Collect premarket, in-session, after-close and weekend captures. Determine each
window using the exchange calendar for that actual date (including holidays and
early closes), in `America/New_York`. Do not infer a market window from the host
timezone, a fixed UTC offset or this runbook's example dates. Session labels are
operator supplied and are not validated by the collector.

Maintain a separate manifest with one entry per file:

- Filename and raw payload SHA-256 (also present in the capture).
- Symbol, expiration, operator, and production account/environment confirmation
  without credentials or account identifiers.
- Declared window, UTC capture time, corresponding New York local time, exchange
  calendar source and regular/holiday/early-close status.
- Any collection failure, unavailable expiration, zero-row response or missing
  window; never substitute fixtures for observed production data.

Each capture preserves the entire JSON payload and byte-exact response body as
base64 plus its digest. All rows remain, including zero bid/ask/last and missing
fields. Raw `bid`, `ask`, `last`, `volume`, `open_interest`, `bid_date`, `ask_date`
and `trade_date` values are not coerced, normalized or classified; presence counts
are bookkeeping only. Do not interpret raw provider timestamp units until
verified against provider documentation and the observed payload. Share files
only through an authorized evidence channel; do not commit raw production
responses by default.

Once all four windows contain usable rows, review their shapes and timestamps,
then begin the focused grilling session and product-plan/ticket reconciliation.
Missing access or windows remain explicit blockers to that design gate.

## Offline instrumentation checks

```bash
/tmp/no-live-quote-python/cpython-3.11-linux-x86_64-gnu/bin/python3.11 -m unittest scripts.evidence.test_tradier_raw_chain -v
```

These tests use synthetic transport responses to verify lossless capture and
failure behavior. They are not market evidence or validation of quote semantics.
