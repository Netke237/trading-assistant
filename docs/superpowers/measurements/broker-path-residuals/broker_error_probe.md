# Broker error evidence (2026-10-13)

Evidence discovery only; no implementation or independent audit. Python 3.11.16.
Run from repository root:

```sh
backend/.venv/bin/python docs/superpowers/measurements/broker-path-residuals/broker_error_probe.py
```

All broker HTTP, SDK account calls, worker scheduling, credential router construction,
audit writes and database calls are mocked. This does not establish a particular
broker accepted an actual order. The scheduling probe reproduces the router's
concurrent waiter handoff, with the first dispatch returning an uncertain error.
The approval probe exercises actual delete_position and log_approval functions
against a mocked database, at the real separate-commit boundary.

Observed output:

```text
alpaca invalid-json JSONDecodeError POSTS 1
ibkr invalid-json JSONDecodeError POSTS 1
tradier invalid-json JSONDecodeError POSTS 1
tastytrade missing SDK response AttributeError SUBMISSIONS 1
invalid-json HTTP 400: Expecting property name enclosed in double quotes: line 1 column 2 (char 1) POSTS 1 EVENTS ['broker_order_attempt', 'broker_order_failed']
json-list unhandled AttributeError: 'list' object has no attribute 'get' POSTS 1 EVENTS ['broker_order_attempt']
empty-object returned {'order_id': 'unknown', 'status': 'unknown', 'broker': 'alpaca_paper', 'deduped': False} POSTS 1 EVENTS ['broker_order_attempt', 'broker_order_filled']
broker-422 HTTP 502: Alpaca paper order failed: HTTP 422 — {"message":"invalid order"} POSTS 1 EVENTS ['broker_order_attempt', 'broker_order_failed']
concurrent-uncertain [{'http': 502, 'detail': 'broker accepted but reply timed out'}, {'order_id': 'SECOND-ORDER', 'status': 'accepted', 'broker': 'alpaca_paper', 'deduped': False}] DISPATCHES 2
delete-before-approval positions 0 approvals 1 JSONL_EVENTS 1
```

## Concrete findings

- `backend/app/data/alpaca_paper_execution.py:69`, `ibkr_paper.py:150`,
  `tradier_paper.py:133` parse JSON after the POST. JSONDecodeError is a
  ValueError, so `routers/broker.py:333` / `:410` reports HTTP400 although
  submission has already been attempted. Wrong-shaped JSON can instead escape
  as AttributeError / IndexError without an outcome audit event. Tastytrade's
  post-submission result dereference at `tastytrade_paper.py:130` also occurs
  outside its wrapped SDK exception block.
- `routers/broker.py:155` / `:169` releases every failed leader with no cached
  failure outcome. A concurrent identical waiting request becomes a new leader
  and dispatches again after an uncertain RuntimeError or ValueError. This
  reproduction requires no request cancellation and is distinct from the
  explicitly documented accepted cancellation limitation at `:94`.
- `routers/broker.py:346` / `:423` logs `broker_order_filled` even for an empty
  broker reply with unknown order ID/status. Frontend save-first classification
  correctly protects tracked rows: `frontend/lib/directOrder.ts:85` keeps a
  generic HTTP400/502 and missing usable order ID; `stockDirectSend.ts:258`
  records an order-unknown note rather than encouraging immediate retry.
- `routers/portfolio.py:181` logs approval in a separate commit after the
  position writer commit. A hard DELETE interleaved between these commits
  deletes prior approvals (`:415`), then the original create request inserts a
  new orphan approval. `models/audit_event.py` has no FK tying it to a position.
  The mocked interleaving leaves zero positions, one approval and one JSONL
  approval event. The ordinary non-racing delete path already cleans approvals.
- AutoTrader has stronger uncertainty handling: `services/auto_trader.py:3069`
  captures all dispatch errors as `order_failed`, retains full premium at risk,
  and disarms. Its setup / typed admission refusal / IBKR confirmation paths
  distinguish proven not-submitted outcomes. Avoid weakening these semantics.

## Decisions for the phase plan

1. What owns an uncertain manual attempt across retries, remounts and process
   restart? Recommended: explicit attempt identity and a durable uncertain
   outcome until broker reconciliation; do not let waiting requests dispatch
   again automatically. Decide whether intentional same-shaped scaling requires
   a new explicit attempt rather than natural-key expiry.
2. How should reconciliation be exposed and who can clear the uncertain hold?
   Existing frontend notes already tell users to check the broker; automatic
   retries must remain disabled. Decide manual broker verification versus
   supported broker lookup, and terminal/partially filled/canceled semantics.
3. Are approvals meant to survive removal as immutable audit history, or track
   only retained positions/history? Current hard DELETE explicitly chooses
   cleanup. Recommended: retain that existing policy and make position creation
   plus approval atomic (or otherwise serialize with delete); confirm only if
   policy is to change.

None of these results proves a broker filled an order; accepted/submitted/fill
must remain separate concepts in the eventual outcome contract.
