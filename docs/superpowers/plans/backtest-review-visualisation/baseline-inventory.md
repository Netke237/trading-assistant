# Baseline information preservation inventory

Application source matches `236bec67` after integration of current main `e8eca1b6`. All destinations are pending implementation/verification; this inventory alone is not proof of preservation.

| ID | Existing information/behavior | Final destination / verification |
| --- | --- | --- |
| BI-01 Navigation | Evidence symbol/interval, compatible-run guard and live-chart link | Pending |
| BI-02 Run identity | Symbol, original/fresh provenance, strategy, direction, horizon, recorded interval | Pending |
| BI-03 Frozen-data meaning | Historical evidence versus live overlays; recorded time_basis | Pending |
| BI-04 Price pane | Exact recorded UTC OHLC; exact fill direction, entry/exit markers; no off-candle snapping | Pending |
| BI-05 Performance pane | Strategy index and gross LONG buy-and-hold; engine baseline100; strategy commission distinction | Pending |
| BI-06 Engine/index distinction | Full indexed ending change and original engine total_return_pct, rounding/definition explanation | Pending |
| BI-07 Zero trades | Successful zero-closed-trades state retains curves, not failure or fabricated empty result | Pending |
| BI-08 Closed-trade list | Stable id, direction, entry UTC and recorded net_return_pct | Pending |
| BI-09 Inspector | Direction, exact entry/exit UTC and raw fill precision, recorded exit reason/time/unknown, net return, size and commission | Pending |
| BI-10 Open positions | id/direction/entry UTC/raw fill/size/unrealized_pnl; mark-to-market explanation; no invented exit | Pending |
| BI-11 Unmatched fills | Explicit no-exact-original-candle explanation; recorded timestamps/prices remain inspectable | Pending |
| BI-12 Provenance | Original/fresh type, artifact id, scan/run id and created UTC | Pending |
| BI-13 Period | Actual first/last recorded candle evaluation time or Unavailable | Pending |
| BI-14 Cost/basis | Recorded strategy commission plus commission_basis; benchmark gross/excludes fees; currency not recorded | Pending |
| BI-15 Configuration | Complete detail.configuration JSON; no fields silently dropped | Pending |
| BI-16 Effective parameters | Complete detail.effective_params JSON | Pending |
| BI-17 Identity detail | Complete artifact.identity JSON including source/hash/version/interval | Pending |
| BI-18 Original summary | Complete detail.summary JSON and original engine values | Pending |
| BI-19 Fresh controls | Explicit configuration, exact fixed sizing, date/commission/hold/gate/parameter inputs, review consent, explicit run, cancellation/errors | Pending |
| BI-20 Unavailable routes | Loading and every original-unavailable reason, labelled live fallback, no historical substitution | Pending |
| BI-21 Late-response isolation | Fresh/original artifact ownership and candidate-change guard | Pending |

## Source identities

- `frontend/components/organisms/CandidateBacktestWorkspace/index.tsx`: canonical Git content SHA256 `3e9b7f11df972b0fe9bdb37a6d1668ef2ca6dc50c7ffb3a1e98bba672b4ac017`.
- `frontend/components/organisms/CandidateChartWorkspace/index.tsx`: canonical Git content SHA256 `1749be8cc31e6f96ba5d8873ced9d7499315a4ea6205965d6b31221924c63997`.
- `frontend/components/organisms/FreshBacktestControls/index.tsx`: canonical Git content SHA256 `7e92b7fcb7608ee8d6a600670a37f457e66ec178a44de4950630b4ce2f62d73e`.

## Browser bounds and fixture preparation

The actual MinWidthGate uses1280px on `/chart`;1200px is supported only on the two Step7 routes. Keep the existing gate unchanged. Verify its1200px overlay and retain1280/1366/1920px chart interaction checks. A component-level1200px layout check may inspect geometry, but must not be reported as a usable full-page1200px chart. This clarifies the browser assumption without changing application scope.

The existing documented fixture generator uses the real detailed engine over controlled test bars and mocked signals, not provider data. Its immutable API-shaped artifacts are browser fixtures only; they must never enter runtime application imports or replace actual original artifacts. No real orders/providers/persistence are exercised.
