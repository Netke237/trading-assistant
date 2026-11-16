# Independent code gate audit — TRADE-CARD-REFERENCE-ALIGNMENT (#603)

Reviewer: `alignment_code_audit_fresh` (fresh independent auditor; no implementation).
Stage: CODE round 1 of at most 3. The earlier attempt without a verdict is not counted here. Coordinator owns all counters and state updates.

Reviewed exact integrated range:

`9067538f7d992b2fdf74efb387e963acc77a6ffe..79d5027ecd149394790a66b1160789480ea0d6f2`

Confirmed worktree HEAD remained `79d5027ecd149394790a66b1160789480ea0d6f2` through the review. Read AGENTS.md, docs/agents/agent-briefs.md, both required adversarial skills, PROJECT_STATE.json's audit_rule, the controlling phase plan, 610-final-preview-alignment.md and final-acceptance.md. Applied the project's wrong-number/order/persisted-data gate in place of the generic skill's finding-count floor.

## Verdict

No gate-level findings after the independent review and adjacent-path recheck. No reachable change in this range was established to display a wrong number, submit a wrong broker number, or corrupt persisted trading data. No mechanism comment meeting the narrow comment-truth exception was found.

## Source paths checked

- Read the actual integrated application TSX diff, associated styling changes and changed assertion coverage, rather than relying on the implementation or acceptance reports. The production diff is presentation components/page and tests/styles; no backend, model, store, API or request-builder implementation changes are in this range. Documentation/capture/evidence artifacts do not supply production pricing or transport values.
- `TradeCard/index.tsx`: traced method availability, explicit method/target/basis changes, matching by both recorded price fields, unique/ambiguous/unmatched/method-only cases, cleared/unavailable results and the selected-target review. The new review reads the existing chosen-row/premium/probability/time/outcome resolution. A view/comparison toggle does not run a model or write order/exit fields.
- Traced MC echoed versus captured premium resolution, cent-based target outcomes, selected quantity, race freshness and moved-barrier gates. The new MC stop consequence is sourced from the current showable race, retains unavailable/null and signed/zero loss handling, and scales the backend's cent-quantized per-share risk by 100 for its per-contract headline. Checked `lib/barrierRace.ts`, backend `scoring/first_passage.py` and `routers/contracts.py` to verify the source units and one-stop-leg-per-race mechanism. It does not borrow Arithmetic current-time stop pricing.
- Traced Arithmetic matched `bs_today` stop cost/calculation premium and the new per-contract loss presentation against `lib/risk.ts` and backend `scoring/stop_cost.py`. Traced the extracted Ladder figure helper against its original inline expressions: stored versus edited option estimates, integer-cent full-position/rung outcomes, full-premium R:R and unavailable allocation remain consistent. Actual execution invalidation, premium-loss amount, remaining option threshold and model stop outputs remain separate.
- `MethodPickSelector` and `MethodCompareSelector`: inspected handlers and added display-only option/time fields. The selector still writes only the original stock/option pair and basis/timestamp. Checked the shared `StockPositionCard` caller: its rows remain stock space, with null option slots; there is no premium-to-stock promotion. Compared methods retain at least one visible card and canonical order independently of the persisted method pick.
- Step 7 page: compared relocated buttons/guards/props with their original JSX, including pending override fallback, quantity and stop/pick/earnings/direction refusals, market-broker refusal, quote acknowledgment, persistent save/order notes and auto-trade. Traced the unchanged send-time quote identity/generation checks, review staleness resolution, fingerprinted save-first confirmation, saved-quantity normalization gate and posting of the captured request object. Reviewed `lib/submissionDraft.ts`, `lib/brokerReview.ts`, `lib/portfolioStore.ts` and the backend writer review point where necessary to establish authority.
- `SubmissionReview`, `BrokerOrderReview` and `SendToBrokerDialog`: checked all existing review-line keys survive grouping, requested/effective values remain on their existing source, expiry/time-exit additions use supplied draft/request values and the existing constant, and market estimates remain qualified. Checked basket review generation/fingerprint matching, late-response rejection, exact reviewed request submission and review-required replacement. The direct review still renders and confirms the captured request; new formatting does not reconstruct it.
- Checked native details, `CollapsibleSection`, method-card hidden rules and action ownership. Native closed details keep children mounted; method visibility uses the explicit hidden rule; the page supplies the broker controls once to a mounted card or once in its pending-plan fallback. Standalone settings and undefined/null/element selector-portal paths retain their original handlers and ownership. Candidate/basket navigation, alternative rows, chart and export retain their source values/callbacks.

## Required zero-finding recheck

Rechecked adjacent paths specifically for first-pass omissions: the shared Stocks selector caller; the inline selected review versus originating method tables; restored and cross-contract/moved-barrier MC states; repeated/ambiguous target pairs; zero, negative and missing stop-risk values; Ladder edited targets and rung quantities; pending override execution rendering; standalone and portal rendering; basket versus direct-send confirmation; server quantity changes and 412 re-review; unknown-order/save feedback; and auto-trade mount/prop preservation. Read the changed numeric/safety assertions and unchanged helper/backend mechanisms supporting these paths. No additional gate finding resulted.

Read-only verification: `python3 scripts/state.py` completed successfully; frontend range `git diff --check` passed. No new tests or full-suite rerun were needed to resolve a new concern, and no existing acceptance run is represented as an audit test execution. No application/test/state/GitHub edits, commits, orders, providers or notifications were performed. The only authored artifact is this report in `/tmp`.

Exact reviewed range: `9067538f7d992b2fdf74efb387e963acc77a6ffe..79d5027ecd149394790a66b1160789480ea0d6f2`.
Key paths checked: TradeCard, MethodPickSelector, MethodCompareSelector, BarrierRaceCard, Step 7 page, SubmissionReview, BrokerOrderReview, SendToBrokerDialog; adjacent Stocks selector, risk/barrier helpers, submission/broker/tracking/portfolio helpers and backend first-passage/stop-cost/position-writer authority.

GATE FINDINGS: 0
