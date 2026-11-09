# #604 — page order, contract identity and qualification placement

First implementation slice of phase #603; source baseline `86982b58`, controlling frozen reference `d8245e66` (PR602), amendments D01–D03. This is not full-phase visual acceptance or code-audit clearance. #605–610 remain unimplemented by this slice.

## Verified presentation

- Market Sentiment followed by Fundamental Health remains in the unchanged page wrapper. Existing status colors, badges, safety flags and explanations remain; captured in both themes.
- Contract strike/right renders at30px and full `Expires DD Mon YYYY` at25px; responsive wrapping within the real navigation/context-rail shell. Raw Contract Details remain visible.
- Stock Qualification is the next section after Contract Details and defaults closed. Its existing display preference is retained. Contract Qualification has its own closed disclosure because scored criteria are distinct from raw facts. Both existing ScoreCardPanels retain their complete evidence and mounted state.
- Actual Exit Plan appears once, full width, before method results; Order Entry and loss-budget/sizing follow methods, before Final Recommendation. Structure & Stops remains reachable with its existing content. Compact Exit Plan and structure reorganization belong to #605.
- Only Monte Carlo is initially visible. Comparison order is Monte Carlo, Arithmetic, Ladder. Opening other cards does not compute, choose a target, apply a stop or submit anything. All three can be shown. Existing equal-height/aligned comparison behavior remains.
- Candidate navigation, basket, alternatives, chart jump/inline chart, spread identities, badges, edit controls, validation, exports and destination actions remain in source. Existing calculation and submission handlers are unchanged.

## Browser evidence

[Checks](evidence/page-order-checks.json): six runs at1200/1366/1920px in dark/light themes, 31 checks each, zero page errors. Initial, calculated, stale and restored states captured; no save/broker order attempted. Assertions cover initial MC-only visibility, no calculation on load/comparison, visual section order, typography, no page overflow, readable/aligned comparison rows, stale-race suppression and candidate-switch isolation. APIs use fixture routes; this does not verify deployed mini-PC data or real broker execution.

Saved examples: [dark initial](evidence/1366-dark-initial.png), [light initial](evidence/1366-light-initial.png), [dark restored](evidence/1366-dark-restored.png), [light restored](evidence/1366-light-restored.png). Initial/restored screenshots show this partial amendment, not the remaining compact-method/decision redesign.

Reproduce with a local dev server at3097 (never the live app port3001):

```sh
node docs/superpowers/plans/trade-card-reference-alignment/capture-page-order.cjs \
  --repo-root "$PWD" --output /tmp/tc604-browser \
  --base-url http://127.0.0.1:3097 --browser /usr/bin/chromium \
  --widths 1200,1366,1920 --themes dark,light
```

## Information preservation

The existing [625-item register](../trade-card-decision-review/final-register.md) remains the baseline; this is a location amendment, not a replacement register. Reconciled affected groups:

| Existing register items | New location / disposition |
| --- | --- |
| 1–38, context/navigation/identity | Retained; prominent contract typography added; page-level sentiment/health unchanged. |
| 39–88 qualification evidence;102–110 raw Contract Details | Raw details visible; existing stock panel directly beneath in Stock Qualification; existing contract panel in separate Contract Qualification. All scored criteria, captured explanations and confidence values retained. |
| 89–101 Fundamental Health | Existing unchanged page-level component; colors, safety flags and explanatory tooltips retained. |
| 111–137 spreads and alternatives | Existing rows and summary values retained after the qualification disclosures. |
| 138–143, editable limit/contracts and read-only max fill | Existing Order Entry controls after methods, same handlers/validation. |
| 144–149, Arithmetic controls | In method results; Arithmetic opened explicitly, same on-demand handlers. |
| 150–156 and183–186, budget/size controls | Existing Trade loss budget & sizing after methods, same keyed editor and Apply guard. |
| 157–182 and187–192, structure/stop provenance | Existing Structure & Stops retained; source directions now point to Exit Plan. #605 owns later disclosure changes. |
| Monte Carlo/Ladder target, probability, time and explanation entries | Same JSX content retained, method order/default visibility amended only. |
| Actual Exit Plan and decision/destination entries | Exit Plan controls moved intact exactly once; decision/submission sections and guards retained. |

[Literal comparison](evidence/source-preservation.json) uses TypeScript AST text/string/template/numeric nodes against baseline. No numerical literal or explanatory content was removed. The complete removals are two default-visibility method identifiers, the old combined heading (replaced with two headings), and two source-direction sentences (same explanation with new Exit Plan location). One new storage key persists only the Contract Qualification disclosure. This source check complements tests and screenshots; it does not prove every conditional runtime state.

## Review boundaries

Independent plan review: historical publication round1 clean; added implementation detail round2 clean, reviewer `alignment_plan_detail_audit`. During regression, allowed test scope expanded to two page-level calculation-flow tests solely to open Arithmetic through its real comparison control; the reviewed production plan and numerical assertions did not change. Integrated phase code audit remains pending completion of all seven tickets, as required by repo orchestration. No merge or full-phase completion is claimed.

## Local regression results

Implementation commit `651f89d2c863d6d84333063fc6674a6b3313709e`. Typecheck passed. Initial expected-red regression:2 failed/18 passed (default visibility and qualification placement). Full Jest run:333 suites passed,3 failed;6220 tests passed,5 failed of6225. Those failures were obsolete hidden-Arithmetic or old Exit Plan container assumptions. After test-only setup/location corrections, all3 affected suites passed together (28/28 tests). The333 other suites and production code were unchanged, providing current-tree coverage of336 suites/6225 tests without repeating the entire14-minute run. No unresolved regression failure remains; this is combined full-run plus focused-retest evidence, not a claim of one all-green full invocation.
