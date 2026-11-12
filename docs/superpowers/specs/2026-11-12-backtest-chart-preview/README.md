# Permanent backtest chart preview

Open `index.html` directly in a browser. It is self-contained and requires no server, dependencies, API, CDN or build. The preview is a design reference, not an application implementation or a new backtest.

Task: BACKTEST-CHART-HTML-PREVIEW. Size S / complexity 2: one standalone HTML visualization and local interaction verification. Completion: 100% of the preview deliverable, including independent audit and browser verification; application implementation remains separate.

## Design and interactions

- Performance comes first, with strategy, benchmark, difference, synthetic equity drawdown and illustrative trade statistics.
- Persistent labelled legend; return-percent or index-100 display; independent curve visibility; larger chart mode; all-history and last-year display ranges.
- Synchronized date hover across performance and price; strategy drawdown; Candles / OHLC bars / Line; compact entry/exit markers.
- Sortable, paginated example trade table. Inspect selects and zooms both charts to a trade's surrounding dates. Clear selection restores the selected broad range.
- Light/dark modes; responsive layout; named controls and keyboard-operable trade inspection.
- Fresh-run action is an explanatory disclosure only. No backtest runs, orders, storage, app state or network requests.

## Data limits

All paths, OHLC bars and trade records are deterministic synthetic fixtures. The endpoint returns +9.59% and +204.48% echo the supplied screenshot; the paths are not a reconstruction of its historical results. Trade examples are generated separately from account-equity curves and explicitly labelled accordingly. Trade returns are entry-to-exit price returns excluding fees, not account contributions. Weekday-only dates do not model exchange holidays.

Range changes preserve the original baseline; summary cards always refer to the full period. Drawdown is calculated from the synthetic daily strategy index and is not the application's intrabar maximum drawdown. Currency values are not offered because the existing artifact does not record currency. Engine equity including open-position mark-to-market must not be silently replaced with closed-trade cumulative P&L in a later implementation.

## Sources

- Existing application baseline: `236bec67`; `frontend/components/organisms/CandidateBacktestWorkspace/`, `CandidateChartWorkspace/`, and `FreshBacktestControls/`.
- [TradingView performance chart](https://www.tradingview.com/support/solutions/43000681735-performance-chart/).
- [TradingView Strategy Report](https://www.tradingview.com/support/solutions/43000764138-tradingview-strategy-report-how-to-start/).

## Verification

`verification.json`: 77 checks across 1366, 1920 and 390px widths, light/dark modes, zero page errors and zero outbound requests. Covered display transformations, range baseline, series toggles, empty guidance, bar/line/candle controls, expansion, trade navigation, sorting, pagination, disclosure and tooltips. Screenshots retained for both desktop widths and themes; light desktop screenshot visually inspected by the implementing agent.

Run from repository root with existing frontend dependencies and installed Chrome:

```sh
node docs/superpowers/specs/2026-11-12-backtest-chart-preview/verify.cjs
```

The preferred agent-browser CLI was unavailable; verification used the repository's existing Playwright runtime with installed Chrome. Frontend typecheck is a separate pre-commit check. No application source or existing phase ledger was changed.

## Independent audit record

Applied `.claude/skills/K-adversarial-audit-loop/SKILL.md`, with fresh independent reviewers applying `.claude/skills/bmad-review-adversarial-general/SKILL.md` and the project's numeric/order/persistence gate. Target is the HTML only; browser harness is supporting evidence.

1. Reviewer `preview_audit`: entire original HTML, SHA256 `55af21be8d94a3fd6ecbf8d008b68d8ee80f3e6cd1eff3744fc374e2ad52387e`. Zero gate findings after recheck. Verified finite generated records, endpoints, return/index arithmetic, trade arithmetic, drawdown, date bounds, interactions and synthetic-data disclosures. No fixes or outstanding findings.
2. Reviewer `preview_final_scope`: subsequent date-scope correction and its interactions only; final HTML SHA256 `e43e34195f15580431e30c55b8ae51260df6d39fc135ab8f6569babdf45597c7`. Fixed-length 1260 samples were replaced with 1304 weekday samples from 2021-11-15 through 2026-11-12, matching the displayed period. Independently verified both endpoints, all trade indices, selected ranges and unchanged baseline/return transforms. Zero gate findings after recheck. No further fixes or outstanding findings.

Coordinator checked both exact scopes and final hash. Code audit clean after two independent rounds, within the three-round cap. No new audit stage or application shipping claim is made. Browser checks and screenshots are separate from the independent code audits.
