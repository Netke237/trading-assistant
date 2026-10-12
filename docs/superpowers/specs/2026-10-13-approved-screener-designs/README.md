# Approved Options, Stocks and Pre-Breakout designs

Approved 13 October 2026. This directory is the shared implementation reference for the three designs recovered and approved in the publishing chat. The user explicitly requested tickets on GitHub and this documentation package on origin/main so agents can start. Application implementation is a later task; publishing plans does not clear any implementation audit or authorize deploying code.

## Final authority and latest decision

1. Preserve all existing information, calculations, controls, numerical sources, qualification/execution gates, cache freshness, persisted data and broker behavior. Mock values, simplified interactions and incomplete disclosures are illustrative, never executable requirements.
2. Keep the existing Options / Stocks / Pre-Breakout switch **in its current shared screener-layout position**, above the step content and aligned as it is today. Do not move it to the right, duplicate it inside a page, or copy the illustrative mock's top-right placement. Retain current mode/navigation/StepNavBar behavior. Source: frontend/app/(frame)/screener/layout.tsx and screenerLayout.module.css. This user decision supersedes all mock placement of that switch.
3. Options and Stocks recovered designs are approved and frozen. Pre-Breakout's revised design and all three displayed sub-mode layouts are now approved. prebreakout-layout-amendment.md is authoritative over its earlier mock and PB ticket destinations: sentiment/fundamentals above results; watch/chart/symbol/company grouped in first column; row Alert retained; duplicate chart-area and trailing watch actions removed.
4. scan-log-isolation-tickets.md is a required functional amendment across all categories. Options, Stocks, Pre-Breakout, Pullback and Fib Pullback keep independent durable latest-run reports until their own next run. Backend/system lookup and UI use the same immutable run identity. Changing parameters/navigation/reloading/restarting or scanning another category never erases a report. Do not coerce distinct pipeline schemas.
5. Historical headers in copied frozen plans/audits (local draft, pending feedback/publication) describe their creation time. This README and ticket-map.json establish current approval/publication. Source hashes stay intact so the recorded plan audits remain verifiable.

## Designs and full ticket plans

| Design | Approved layout reference | Complete implementation instructions |
|---|---|---|
| Options | options-trade-flow.html | options-presentation-tickets.md OPT-PRES-01–10; options-preservation-checklist.md |
| Stocks | stocks-position-preview.html | stocks-presentation-tickets.md STK-PRES-01–08 |
| Pre-Breakout, Pullback, Fib Pullback | prebreakout-preview.html | prebreakout-presentation-tickets.md PB-PRES-01–08; prebreakout-layout-amendment.md |
| Shared saved reports | category report inspector in Pre-Breakout preview | scan-log-isolation-tickets.md LOG-01–03 |

Raw HTML files are inline preview fragments; they are source references, not deployable app pages. Keep all child content accessible, including conditional evidence/tooltips. Use actual CSS Modules/global tokens/primitives. No numerical golden regeneration to mask runtime drift.

## Prior work and concurrency

Existing programme #144, merged Stocks Position work (PR #225), and open Pre-Breakout phase #150 / PR #224 precede this approval. These new tickets describe a successor design, not reopening those phases or resetting their audit counters. Do not merge, close or overwrite #224 as an incidental step.

PB-BASE-01 must inventory current main and #224: map already-built evidence, threshold snapshots, clicked-row direction and chart levels to the newly approved destinations. Preserve correct mechanisms whether already merged by then or selectively ported with an explicit provenance crosswalk. Any ported source is new reviewed implementation scope and must pass the new phase's code audit. Claim ownership before source work and stop if another branch owns an overlapping task. Reading a ticket is never permission to erase another agent's work.

Shared frontend file edits are serial. Options presentation phase finishes before Stocks presentation; Stocks finishes before Pre-Breakout presentation. Shared saved-report backend work can start separately; integrate frontend report surfaces only after LOG prerequisites and their relevant UI foundations are closed. Source diagnostics for Pre-Breakout remain a separately audited data prerequisite, not a fake counter in a layout ticket.

## Agent start and release contract

- Use ticket-map.json and GitHub native sub-issues/dependencies, with readable Part of / Blocked by fallbacks. Only dependency-free build tickets carry ready-for-agent. Verification tickets remain coordinator-owned; some crosswalk checks are continuous even though final verification comes last.
- Before building read PROJECT_STATE and claims; register the applicable new phase with its exact plan scope/audit evidence under docs/agents/ticket-orchestration.md. Keep phase-wide plan/code rounds separate, maximum three per stage. Never reset existing phase counters. The frozen plans passed independent plan audits; reconcile against current main before implementation and audit any substantive new plan changes.
- Coordinator runs a fresh independent adversarial audit of each integrated implementation phase. Gate: wrong displayed/order number or corrupted persisted data; actionable mechanism claims only. Later rounds review only prior fixes/interactions. Passing tests and preview approval are not code audits.
- Verify Python 3.11 before backend dependency/test/runtime work. Frontend typecheck before every commit, with meaningful focused tests and required CI. Preserve legacy keys/migrations, absent-versus-zero values, stale request guards and broker refusals.
- Merge implementation only through the repository's merge conditions or explicit user approval in that implementation chat. This publishing request authorizes the documentation package to main, not unaudited implementation.

## Audit evidence

Options plan: two rounds, clean second; Stocks plan: one clean round; Pre-Breakout original plan: one clean round; revised mock/layout amendment: one clean revision round; shared logs plan: one clean round. Copied exact records accompany sources. Publication audit separately covers packaging, final placement decision, issue text, dependency mapping and provenance; it does not repeat or inflate earlier audits. All production implementation remains not started by this session.

## Published GitHub tickets

| Phase | Tracking issue | Child tickets |
|---|---|---|
| Options approved trade-card design | [#233](https://github.com/Netke237/trading-assistant/issues/233) | #240, #241, #242, #243, #244, #245, #246, #247, #248, #249 |
| Stocks approved position design | [#234](https://github.com/Netke237/trading-assistant/issues/234) | #250, #251, #252, #253, #254, #255, #256, #257 |
| Pre-Breakout approved ranking design | [#235](https://github.com/Netke237/trading-assistant/issues/235) | #258, #259, #260, #261, #262, #263, #264, #265, #266 |
| Durable isolated scan reports | [#236](https://github.com/Netke237/trading-assistant/issues/236) | #237, #238, #239 |

First ready build tickets: [OPT-PRES-01 #240](https://github.com/Netke237/trading-assistant/issues/240) and [LOG-01 #237](https://github.com/Netke237/trading-assistant/issues/237). Use native dependency edges and the owning tracking issue for subsequent work. Do not start blocked children or treat coordinator verification as a build assignment.
