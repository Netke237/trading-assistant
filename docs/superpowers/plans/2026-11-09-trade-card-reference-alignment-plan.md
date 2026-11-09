# TRADE-CARD-REFERENCE-ALIGNMENT

Parent #603, branch board/trade-card-reference-alignment-86fd081f. Frozen presentation reference d8245e6695b301dae35a476f170e6cdf4cc0d7b0 in PR602; production numerical authority main86982b58. User selected #604 only this session. Remaining #605–610 are unstarted; this slice does not complete or clear the phase shipping gate.

## Historical review
The seven-ticket publication manifest was independently reviewed by amendment_ticket_plan_audit, zero gate findings (plan round1). This elaboration retains that review and undergoes plan round2; it adds implementation detail, not new numerical behavior. Phase code audit remains after all build tickets, per orchestration rules.

## Task1 / #604 — page order, identity, qualifications (M, complexity3)

Read the frozen README and IMPLEMENTATION-GAPS D01–D03 in /workspace/trade-card-design-review/docs/superpowers/specs/2026-11-09-trade-card-reference, and reconcile with actual TradeCard/page before changes.

Allowed application files: frontend/components/organisms/TradeCard/index.tsx and TradeCard.module.css; frontend/components/molecules/MethodCompareSelector/index.tsx and its module CSS if required. Allowed tests: existing TradeCard and MethodCompareSelector tests and page identity-market-context/integrated-flows/a8-rail-and-structural-cache tests, plus new TradeCard page-order tests. Scope clarification during regression: page calculation-flow tests must explicitly open Arithmetic/Ladder through comparison before their existing calculation scenarios; retain all numerical assertions. This is the same reviewed default-visibility adaptation, no application behavior expansion. Coordinator owns this plan/state and acceptance evidence. Do not touch submissionDraft, broker/direct-send handlers, calculation formulas, stores or backend.

First write meaningful failing tests for initial MC-only visibility, MC-first ordering when comparing, separated collapsed Stock Qualification directly beneath visible Contract Details, preserved Contract Qualification evidence and reading order Exit Plan before methods before entry/size before decision. Ensure method visibility never calls compute or changes selected target/settings. Update obsolete default-all-method expectations by explicitly opening methods when those tests exercise their content. Prove red before implementation.

Implementation: retain existing parent Market Sentiment then Fundamental Health (all badges/colors/explanations), chart jump/inline chart, candidate/mode navigation, basket, spreads and alternatives. Enlarge strike/right (~30px) and full expiry (~25px) with responsive wrapping and existing tokens. Split the current combined score disclosure into distinct Stock Qualification (immediately after Contract Details, default closed) and Contract Qualification (distinct reachable disclosure, default closed); retain both ScoreCardPanel components and every explanation. Keep selected Contract Details visible.

Reorder existing actual Exit Plan into a single section before method results, preserving all existing editable controls, helpers, alerts and data sources exactly once. Place Order Entry and loss budget/sizing after methods, before existing decision/actions. Keep structure evidence reachable without compacting/removing its content (#605 owns that change). Prefer moving existing JSX or extracting local render fragments over rebuilding data. Preserve original event handlers and conditional mounts. The standalone Barrier Race remains unchanged until #606. Default comparedMethods becomes ['monte_carlo']; selector and visible card DOM order MC, Arithmetic, Ladder. Browsing only changes visibility; all calculations remain explicitly triggered and cached/restored results unchanged.

Run focused tests, typecheck and full Jest; no backend changes. Commit `fix(trade-card): restore page hierarchy and contract identity` with repo attribution. Do not push, edit state, close issues or claim independent audit. Report red/green results and any deviations to coordinator.

## Acceptance evidence
Coordinator checks initial/restored real shell at desktop and narrow widths in dark/light themes using isolated route fixtures (no real writes), records page order, identity wrapping, closed disclosures and no lost actions; preserves screenshots/check data in repository. Reconcile affected entries from existing final-register.md; no loss of text or duplicated execution settings. No declaration that #605–610 are complete. Phase integrated code audit and merge remain pending all tickets.
