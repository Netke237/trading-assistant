# Trade card: durable design reference and implementation amendments

Requested 9 November 2026, after the trader reported a substantial gap between the preview and the delivered interface. This directory is the repository-owned reference for the next presentation amendment. It is documentation and an interactive prototype, not an application implementation or a new pricing specification.

## Open the reference

- **[New interactive reference](preview.html)** — compact actual Exit Plan, Monte Carlo first, expandable evidence, two/three-method comparison and separate basket/broker confirmation examples.
- **[Implementation gap and amendment register](IMPLEMENTATION-GAPS.md)** — 12 source-backed differences, priorities, acceptance checks and already-compliant behavior to retain.
- **[Audit record](AUDIT.md)** — independent review and exact verification scope.
- **[Original v6 prototype](historical-preview-v6.html)** — frozen historical evidence; its known placeholders and obsolete wording are not implementation authority.

GitHub shows HTML source rather than running it. To view the interactive reference after checkout, serve this directory locally:

```sh
python3 -m http.server 8090 --bind 127.0.0.1 --directory docs/superpowers/specs/2026-11-09-trade-card-reference
```

Open `http://127.0.0.1:8090/preview.html`. The reference requires only its adjacent CSS and JavaScript. It loads no external fonts, APIs or services. Tracking and broker confirmations are demonstrations and send/save nothing.

## Controlling design decisions

| Area | Required presentation |
| --- | --- |
| Context | Existing Market Sentiment above the card; Fundamental Health directly beneath, with existing colors, score/quality/risk/safety badges and explanations. |
| Identity | Symbol/chart jump remain; strike/right approximately30px and full expiry approximately25px in the reference. Contract Details remain visible. Stock Qualification sits directly beneath Contract Details, collapsed by default. Adapt wrapping to the real app shell rather than shrinking back to microtext. |
| Actual exits | One compact editable Exit Plan. Visible invalidation, premium-loss amount, loss percentage, remaining option value/loss per contract and readable time threshold. Detailed source, quantity breakdown, ATR and time explanation default closed. Preserve material missing/invalid warnings. |
| Editability | Consistent tinted editable affordance across actual editable fields; max fill, time exit and calculated fields remain read-only. Prototype values are fixed examples except Contracts; do not copy its readonly samples into the actual app. |
| Normal method view | Monte Carlo only, first. Existing calculation remains explicitly user-triggered. |
| Method essentials | Same stop context and target-column order. All target rows visible. Label stock/option units, actual input source, probability meaning and conditional time correctly. |
| Comparison | Opening or comparing never runs/selects/applies a method. Permit all three. Equal-height aligned cards on the same row; extra cards wrap. |
| Method detail | Complete geometry, pricing, provenance, formulas and conditional explanatory variants remain accessible in expansions. Brief numerical source/time basis remains visible; stale and other material warnings remain with affected figures. |
| Ladder | Show inherited position stock/premium settings with source; only genuinely missing Ladder-specific valuation/probability/time says not calculated/not supplied. Keep full-position/rung outcomes separate and full-premium R:R unchanged. |
| Barrier Race | Existing graphic/table inside Monte Carlo's default-closed race expansion. Shares agree with numeric rows; preserve target selection, medians, edge, R:R and full risk explanations. |
| Decision | One compact grouped method/target/basis choice with selected TP/probability/time/quantity outcome. Avoid another full latest/all-target summary. Preserve optional-row and fallback behavior. |
| Destination review | Separate Portfolio tracking from named broker/account. Show authoritative requested/effective values, actual position settings and target-alert basis; keep estimates distinct from fills. Preserve existing server review/fingerprint/staleness logic rather than replacing it with demo arithmetic. |
| Secondary content | Stock Qualification sits directly beneath Contract Details, collapsed by default. Contract Qualification remains distinct and reachable: details are raw contract facts; qualification is the scored DTE/delta/IV/liquidity/spread assessment with explanations. Alternatives and detailed model/transport provenance stay reachable. Preserve chart actions, mode/candidate navigation, pin/basket, spread data, auto-trade, export and all supported feedback states. |

### Numeric and behavior boundaries

The stock stop used by Monte Carlo is a supplied barrier, not a newly optimized Monte Carlo stop. Raw structure and Arithmetic/ATR stops can differ under existing resolution rules. A rerun refreshes the calculation; choosing a model must not silently rewrite position settings.

The current-time stop-cost estimate and Barrier Race stop valuation use different time-to-expiry bases. Current code describes both as Black–Scholes repricing. Historical delta-linear wording is corrected in the new reference, while its original text is preserved separately for provenance.

“3 days to expiry” means an existing alert at three days or fewer remaining, not three days after entry and not an automatic close. The premium-stop input is a loss amount, not the remaining option price or a protective broker order. All sample amounts, probabilities, dates, quantities and times in the prototype are illustrative. They are not test golden values or a promise of live prices, allocations or fills.

## What was reviewed

- Frozen implementation: [`86982b583b35dcca39fafac4eaa966bbfc2e916b`](https://github.com/Netke237/trading-assistant/commit/86982b583b35dcca39fafac4eaa966bbfc2e916b), including [merged implementation PR594](https://github.com/Netke237/trading-assistant/pull/594).
- Controlling work: [phase575](https://github.com/Netke237/trading-assistant/issues/575), its nine tickets and the user's accepted design decisions in this chat.
- Fresh browser evidence: current local mocked frontend, 1366×1000, dark theme, seven states, zero page script errors. The production capture script's guarded mock layer fulfilled the simulated calculation/save/order calls; no real broker/provider/notification operation occurred.
- New reference: browser-verified at1366×1000, both themes; MC3 targets, Arithmetic2, three-method comparison, equal outer card heights, stale race suppression, quantity arithmetic, graphic weights and changed-review rejection. See [reference checks](evidence/reference-checks.json).

This is a source-and-mocked-browser review, not verification of the trader's deployed mini-PC. The standalone reference does not recreate the application's navigation/context rails; the same viewport therefore has a different usable content width. Amended production visuals must be checked within that real shell.

## Information preservation

The existing implementation has its own [625-item final preservation register](../../plans/trade-card-decision-review/final-register.md). Keep and reconcile it during amendment. A numeric gate audit or complete item register does not by itself prove visual conformity.

`historical-explanation-register.json` preserves the original132 explanation/notice entries, with their original source references. `explanation-register.json` retains the same entries with the verified stop-pricing wording corrected. The new reference's model-expansion appendix includes those132 entries as labeled reference text; conditional values use placeholders and are not active errors. This historical subset is **not** a replacement for the625-item current-source register or proof of every current state.

## Evidence files

| Current implementation | Target reference |
| --- | --- |
| [Initial](evidence/implemented-initial.png) | [Initial](evidence/reference-initial.png) |
| [Computed](evidence/implemented-calculated.png) | [Two-method comparison](evidence/reference-comparison.png) |
| [Tracking review](evidence/implemented-basket-review.png) | [Tracking-review layout](evidence/reference-basket-review.png) |
| [Broker review](evidence/implemented-broker-review.png) | [Broker-review layout](evidence/reference-broker-review.png) |
| [Current checks](evidence/implementation-checks.json) | [Decision](evidence/reference-decision.png), [race](evidence/reference-race.png), [light theme](evidence/reference-light.png) |

The input fixtures differ between the existing application capture and the illustrative reference. Compare hierarchy, grouping, density and disclosure, not their dollar amounts.

## Reproduce checks

With the frontend's Playwright dependency installed and a local Chromium binary:

```sh
node docs/superpowers/specs/2026-11-09-trade-card-reference/verify-reference.cjs /path/to/chromium
```

This writes reference screenshots/checks and aborts all network requests. For the current-implementation captures, use the existing isolated local fixture harness documented in the gap register; no backend is needed. Do not point a capture at a live broker session.

## Change status

Reference and amendment documentation only. Production amendments D01–D12 are not implemented by this change. Existing server-backed review behavior, validated numeric sources, persistence and alert rules must remain intact. A later implementation needs its own checks, visual acceptance and independent audits; none of the old phase's audit counters are reset here.

## Qualification placement clarification

User amendment after the first reference publication: move the Stock Qualification disclosure directly under Contract Details and leave it closed initially. Keep Contract Qualification because it is not duplicate Contract Details: the latter contains strike/right/expiry/market metrics, while qualification contains component scores and evaluation explanations. No qualification information is removed. Production remains unchanged by this documentation update.
