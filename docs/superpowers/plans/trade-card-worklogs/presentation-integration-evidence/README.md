# Integration preservation evidence

Source baseline: `93983992` (all audited prerequisites assembled, including AREA3).
Composition checkpoints: A `71ab258a`, B `87e45af7`, C `e937b8e1`.
The subsequent page CSS correction wraps the original BrokerPicker row inside
the narrow execution panel; no shared broker component/handler is changed.

`information-reconciliation.json` contains all520 original entries, each with
an actual production rendering region, destination, state conditions, supporting
suite references and inventory corrections. Source regions include original
helpers/guards. This is a source-and-state reconciliation, not520 separate
browser assertions. Dynamic target loops retain their real payload length,
ratios and percentages; old missing rows are not fabricated. Qualification uses
captured metadata, not direct YAML reads. Original context/checklist stays in
its parallel right rail. The inventory's Retry direct-send note is actually the
original safety-checked Remove action. Stock-stop movement retains the original
explicitly stale measured-against statistic, while premium-only movement retains
its unaffected standalone statistic.

`callback-parity.json` compares TypeScript ASTs with comments removed: all141
existing TradeCard functions/callbacks and129 existing page functions/callbacks
(excluding their top-level component render functions) are byte-equivalent under
the same printer. The only additions are race-selection lookup/callbacks. This
supports numeric/order callback preservation; it does not replace independent
review of JSX prop wiring, owner lifecycle or data-vintage gates.

Browser cases use isolated fixtures and Chromium, with the real frame and rail:
- `browser-cases.json`: premium-only/stock-barrier freshness, restoration,
  candidate/contract switch, single selector, retained AutoTradeArm DOM owner on
  a ready-to-ready candidate change, legacy absence and tracking dialog. No
  order, arm, fire or position-save request was made.
- `browser-override.json`: Step6 picked ID plus chain row, original planReady
  suppression during preparation, one arm/selector after completion and honest
  missing provenance. Baseline AutoTradeArm is gated on planReady; the integration
  does not claim it remains mounted while that predicate is false.
- `browser-expired.json`:0DTE refusal distinct from not run, no shortcut.
- `browser-spread.json`: actual spread legs/summary and expanded alternatives;
  original planReady arm rendering predicate retained, no invented spread gate.
- `browser-evidence.json`: captured custom thresholds, hard-reject diagnostic
  contributions, IV fallback warning and expanded effective bounds.
- `browser-widths.json` and24 screenshots:1200/1366/1440/1920, both themes,
  top/methods/race regions.1920 has side-by-side method cards and adjacent
  execution;1366/1440 methods stack and execution flows below. Outcome tables
  fit without horizontal scrolling. Broker buttons wrap with readable labels.

**Open acceptance blocker:** actual shared MinWidthGate is1280px, contrary to
plan's assumed1200px baseline.1200 screenshots deliberately show the blocking
modal; neither underlying DOM metrics nor passing tests certify1200 acceptance.
User scope decision is pending before modifying that shared component outside
the task allowlist. No gate override has been implemented.

Browser images use an environment-only local font mock because direct Google
font downloads were denied earlier. 24 baseline screenshots are100% zoom. Native125% zoom is additionally
verified in the production build at physical1920/CSS1536 in both themes, with
no page/table overflow (browser-zoom125.json and six extra screenshots).
Remote font metrics remain unverified. Production source,
font configuration and package/lock files are unchanged. These limitations are
not hidden by the clean numerical code audits.

Reproduce from frontend cwd with dev server on127.0.0.1:3001, Chromium installed,
and existing Playwright/TypeScript dependencies:

```
node ../docs/superpowers/plans/trade-card-worklogs/presentation-integration-evidence/browser-widths.cjs
node ../docs/superpowers/plans/trade-card-worklogs/presentation-integration-evidence/browser-cases.cjs
node ../docs/superpowers/plans/trade-card-worklogs/presentation-integration-evidence/browser-zoom125.cjs
SCENARIO=override node ../docs/superpowers/plans/trade-card-worklogs/presentation-integration-evidence/browser-scenarios.cjs
SCENARIO=expired node ../docs/superpowers/plans/trade-card-worklogs/presentation-integration-evidence/browser-scenarios.cjs
SCENARIO=spread node ../docs/superpowers/plans/trade-card-worklogs/presentation-integration-evidence/browser-scenarios.cjs
SCENARIO=evidence node ../docs/superpowers/plans/trade-card-worklogs/presentation-integration-evidence/browser-scenarios.cjs
```

Fixtures exist only in the verification scripts and are never production inputs.
