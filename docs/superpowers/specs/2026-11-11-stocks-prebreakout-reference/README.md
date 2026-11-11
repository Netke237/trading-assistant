# Permanent Stocks and Pre-Breakout previews

Design reference for the proposal in `../2026-11-11-stocks-prebreakout-information-flow-proposal.md`, against application baseline `0a453f1940a077015949e760d02ef5a6d921f62a`.

Open `index.html`, `stocks-preview.html`, or `prebreakout-preview.html` directly in a browser. Each HTML file is self-contained, has light/dark modes and requires no installation, build, API, CDN or server. Cross-links work when the files stay together. No app/browser storage keys are used. No trading, saving, notifications or network requests occur.

## Stocks interactions

- Opens with the available edited Ladder; Monte Carlo and Arithmetic show results only after their example Run buttons. This proposed initial viewing choice does not select an execution method.
- Compare initially shows Monte Carlo and Arithmetic; use method buttons to include Ladder or change the pair. The third wraps below at the same card width. Display choices never change the decision or run a calculation.
- Expand qualifications, stop explanation/Check structure, original scanned strategy, allocations, latest calculation, model explanations, or Arithmetic’s graphical race.
- Editable-in-app entry/stop/target/allocation fields are fixed illustrative values in this reference. Shares are interactive. Their full-position display arithmetic updates; no statistical result is recalculated.
- Arithmetic’s example stop 196 differs from the execution stop 194. Suggested25 shares uses Arithmetic risk 4, not execution risk 6. Applying the example quantity changes shares only; fixed example rung allocations4 / 3 / 3 are not silently normalized.
- Choose method and optional target in Decision; retain both stop bases, distinct probability/time meanings and current execution targets. Research-save/pin/basket actions are demonstrations only. Actual broker sending/automatic arming remain visibly blocked by the current stock-validation restriction.

## Setup Scanner interactions

- All three existing modes: Pre-Breakout, Pullback to EMA and Fib Pullback. Select candidates with mouse or Enter/Space; watch, chart and alert actions are local demonstrations.
- Every mode retains its distinct confidence meaning. Pre-Breakout/Fib do not gain TP, stop or profit-probability models.
- Original EMA scan context and supplementary stock context remain labelled separately. Separately fetched sample prices never become a scan price for response types that do not provide one.
- Parameters/help/reset, setup evidence, qualifications, raw sample evidence, news and saved report/analysis log are expandable. News is explicitly synthetic and its example article button does not navigate to an invented article.
- Example-state selector is a design-review control for loaded, context-unavailable and empty states. Run Scan reveals a fixed fixture, not results recalculated from parameters. Parameter inputs are fixed examples.
- Daily candles are synthetic. Scan swing/Fib lines illustrate the current `scanChartLines` semantics, never executable trading levels. EMA mode adds no new price line.

## Source and preservation scope

Stocks: `StockPositionCard/index.tsx`, `InitialStrategyTargets.tsx`, `PositionEvidence.tsx`, `StockSendDialog/index.tsx`, `stockExecutionSession.ts`, and the terminal Stocks page. Setup Scanner: `step-4-prebreakout/page.tsx`, `PreBreakoutRowDetails.tsx`, `SelectedStockContext.tsx`, `SelectedStockNews.tsx`, `SelectedSetupChart.tsx`, `scanChartLines.ts`, and existing parameter panels.

The previews carry the current explanatory concepts and illustrative detail through named disclosures; they are not a claim that every dynamic source literal or conditional backend response has been exhaustively reproduced. Original source remains unchanged. A complete source-to-destination preservation inventory, exact real-data states and payload verification remain required before application implementation is accepted. Full explanatory text must not be removed during implementation.

No `frontend/`, `backend/`, store, API, transport, validation authority, workflow or existing phase-state file is modified by this preview task.

## Browser verification

350 browser checks passed over1200/1366/1920px in dark/light themes, covering12browser contexts and all three Setup Scanner modes;0pageerrors,0API/outboundrequests. Only static preview document GETs were allowed. Application typecheck passed. The harness hides temporary demo toasts when taking reference screenshots so figures remain readable.

For an environment that blocks direct file navigation, serve this folder locally:

```sh
python3 -m http.server 3196 --bind 127.0.0.1 --directory docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference
```

Open `http://127.0.0.1:3196/index.html`. To reproduce the browser checks using the repository's existing Playwright dependency:

```sh
node docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/verify-previews.cjs --repo-root "$PWD" --output /tmp/screening-preview-evidence
```

### Representative screenshots

- [Stocks — initial, dark](evidence/stocks-1366-dark-initial.png)
- [Stocks — comparison, dark](evidence/stocks-1366-dark-compare.png)
- [Stocks — comparison, light](evidence/stocks-1366-light-compare.png)
- [Setup Scanner — initial, dark](evidence/scanner-1366-dark-initial.png)
- [EMA Pullback — initial, light](evidence/scanner-1366-light-ema-collapsed.png)
- [Fib Pullback — initial, light](evidence/scanner-1366-light-fib-collapsed.png)

The example comparison notice space deliberately aligns the two table headers and card heights. Supporting material remains collapsed on first load.
