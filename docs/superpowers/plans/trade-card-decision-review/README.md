# #576 partial source baseline

**STATUS: blocked.** The actual trader running URL and revision are unknown. These files document inspected source and a local mocked browser run only. They do not establish equivalence with the trader's build, complete #576, or release dependent tickets #577–#584. No application code changed.

Read [preservation-register.md](preservation-register.md) for the before/after obligations and 33 current source contracts, or [preservation-register.json](preservation-register.json) for per-entry evidence levels. All 520 historical IDs remain present. Their old reconciliation is provenance, not fresh proof: 60 have complete historical source snippets still present verbatim, while 460 contain changed regions. Individual historical field/copy/formatter/state contracts remain open, even when a region matches. Current candidate regions are navigation aids. Null field-contract attributes mean not yet verified, rather than unavailable product values.

The supplement records source-inspected mutability, units, time basis, applicable states and proposed destinations for current regions. Browser evidence is attached only to named assertions, not inferred for every field inside a captured section. Neither the supplement nor the historical list is a finished exhaustive current-build inventory. Dynamic target/leg rows remain dynamic; historical labels such as 2:1/3:1, T1/T2/T3 and 20/35/50% must not fix future row counts.

[Source manifest](source-evidence-manifest.json) pins the checkout, application snapshot, historical reference and SHA-256 hashes. The application files match source `c8f3b8a2`; documentation-only commits make the evidence checkout `8ecc2c80`. That comparison concerns two git revisions, not the unknown running build. The coordinator owns [baseline-provenance.json](baseline-provenance.json); its `verified_native_*` graph is the later publication readback, while its `publication_preflight_graph.current_*` values are earlier observations. This work does not change audit/state/publication records.

## Local mocked captures

Body text has only trailing line whitespace stripped and a final newline ensured; source and normalized hashes are recorded. The four PNGs and body-text files in [evidence/local-mocked](evidence/local-mocked) were copied from the coordinator's prototype run and visually inspected before citation. Each PNG is a 1440×1100 dark-theme scrolled viewport, not full-page coverage. The accompanying body text covers the rendered page; closed disclosures remain closed.

| State | PNG | What is visible | Scope limit |
|---|---|---|---|
| Initial | [initial.png](evidence/local-mocked/initial.png) | Order Entry, Exit Plan, budget and uncomputed structure | Initial fixture, no calculation proof |
| Calculated | [calculated.png](evidence/local-mocked/calculated.png) | Three synthetic race rows, shortcut actions, summary and closed rich detail | Returned fixture rows, not real pricing or raw/allocated mismatch coverage |
| Stale | [stale.png](evidence/local-mocked/stale.png) | Premium-stop edit warning, retained independent MC targets, disabled race selection | Premium-only edit; not every stale/error branch |
| Restored | [restored.png](evidence/local-mocked/restored.png) | MC inputs/targets after switching to MSFT and back to AAPL | In-memory per-contract restoration, not page reload or persisted server restore |

[checks.json](evidence/local-mocked/checks.json) preserves the original 15 named assertions, no page errors, and four POST requests: two exit-plan, one structural-stop and one first-passage. They were fulfilled by mocks. No order, arm, fire or position-save request occurred. Tracking was opened and cancelled. This establishes the named local transitions, not all 520 runtime checks, real broker behavior, persistence correctness, all themes/widths, or the trader's current version.

The fixture starts with `frontend/e2e/fixtures/api-mocks.ts`; the harness supplies synthetic quote, structural, Arithmetic and first-passage/race responses. Its overridden 2026-12-18 expiry and independently set 75 DTE are illustrative mocked metadata, not a consistent live valuation date. The Heston label in a response is supplied fixture text, not proof a Heston computation ran. The captured request premium and saved run context also deliberately lack some current source fields; Arithmetic matched-premium outcomes can therefore be unavailable. Current screenshots are not live numerical fixtures.

## Reproducing the harness

Start the existing frontend development server with dependencies installed. From any directory, run the absolute path to `capture-local-baseline.cjs`, or from the repository root:

```bash
node docs/superpowers/plans/trade-card-decision-review/capture-local-baseline.cjs \
  --output /tmp/trade-card-baseline-new-run \
  --base-url http://127.0.0.1:3001 \
  --browser /usr/bin/chromium
```

`--output` is required. Omit `--browser` to use Playwright's installed Chromium; use `--repo-root` for another checkout. Dependency and fixture resolution use the repository root, and the shared fixture is executed from `frontend/` because it resolves candle paths relative to that directory. Only loopback target hosts are accepted. The final global route rejects every unsafe method on every path except POSTs to the three explicitly mocked calculation paths on a loopback host (the API may use a separate port); those fall through to the calculation mocks. It covers `/broker/...` as well as `/api/...`. It never opens an order or arm/fire confirmation. The hardened rerun has one additional check for attempted unexpected writes; see [portable-checks.json](evidence/portable-checks.json). Its images were validation output only and did not replace the four inspected original captures.

## Stop valuation reconciliation

The three paths answer different questions. Preserve their distinct premiums, stock levels, model labels, time bases, availability and cent rounding. No calculation was changed here.

| Readout | Authoritative path and inputs | Meaning to preserve |
|---|---|---|
| Immediate stop-cost gate | `backend/app/scoring/stop_cost.py:166–255`; `compute_stop_cost`; `bs_price(stop, strike, dte / 365, ...)` | Black-Scholes at the stop with unchanged time to expiry: no elapsed theta. Uses supplied absolute IV or solved mid IV. Premium is rounded before subtraction. Value/loss remain unclamped; only loss fraction is clamped to [0,1]. Invalid/expiring/unpriceable inputs produce unavailable, not zero/PASS. |
| Arithmetic stop contract value | `backend/app/routers/contracts.py:1188–1222`; `estimate_rr` in `backend/app/scoring/reward_risk.py:112–164` | This endpoint passes neither Heston parameters nor `reprice_years`; it uses `estimate_rr`'s default remaining time `max(expiry_years × 0.5, 7/365)`, with BS/IV-derived or delta fallback model label. It is separate from the same response's `stopCost`. Do not substitute the stop-cost value into sizing or claim that Arithmetic always uses barrier median time. |
| Race stock-stop value/risk | `backend/app/scoring/first_passage.py:499–533`; `resolve_reprice_days` and `remaining_years_at_barrier` | Stock-stop risk is computed once outside the target loop. The resolver uses the standalone median over paths that ever touched the stock stop, or configured horizon fallback; it converts elapsed days to remaining expiry before BS repricing. This is not the per-target conditional median over paths where the stock stop won the race. `repriceDaysStockStop` reports the resolved horizon. Keep per-target first-outcome medians distinct. |

The current user-visible explanation at `BarrierRaceCard/index.tsx:428–432` calls the immediate check a “delta-linear estimate ... capped at the premium.” That contradicts `compute_stop_cost` above. Treat it as an unresolved source-copy discrepancy, not permission to revert the BS calculation or clamp its value/loss. Nearby “each barrier's own median day” wording also needs the resolver/fallback and standalone stop-touch distinction above when revised. The accurate conceptual distinction is today's unchanged-DTE stop-cost versus the separate Arithmetic horizon and race resolved barrier-time repricing. Any corrected copy belongs to the authorized presentation ticket; the running-build version of this wording is still unknown.

## Remaining acceptance work

- Obtain the actual trader running URL and revision/build identifier, plus authorized read-only access or matching screenshots; identify version differences before dependent implementation.
- Reconcile each historical field and any running-build-only field to current source, including exact mutability, units, time basis, visibility, tooltip/color, formatter and failure/stale paths. Verify the remaining regions rather than inheriting an old “retained” result.
- Exercise missing, spread, tiny premium, alternate IV/model, no-row/ambiguous row, request failure, reload restoration, tracking/broker outcomes and all disclosure branches with mocks. The four local states are representative only.
- Reconcile every final destination and preserve status colors and controls during #577–#584. Complete required independent review and integrated verification through the coordinator; no self-review here clears an audit gate.

The exact blocker remains the unknown actual running URL/revision. #576 stays open and dependent application work stays gated.
