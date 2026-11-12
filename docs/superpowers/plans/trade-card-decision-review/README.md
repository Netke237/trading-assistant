# #576 pinned-main source baseline

**Source inventory complete.** The user authorized current main pinned at `c8f3b8a2cb5f0fa7e74fc0da407d1716a381fc6b` on 2026-11-07. The mini-PC/running-build comparison is **user-deferred, not verified and not an implementation blocker**. Its URL/revision remain unknown. These artifacts establish source inventory and representative local mocked states; they do not establish running-build equivalence. No application code changed in this inventory ticket.

[Preservation register](preservation-register.md) is the reviewable before/after checklist; [JSON](preservation-register.json) carries all 520 individual historical field/copy/formatter/state contracts, exact current-source excerpts and hashes, future locations, mutability, units, time bases and applicable states. All 520 are source-inspected against the immutable baseline. The old reconciliation and its 60 exact-region/460 changed-region continuity results remain historical provenance, never the basis for individual verification. Repeated historical target examples bind inspected dynamic loop templates; 2:1/3:1, T1/T2/T3 and 20/35/50% must not fix result counts.

The 67 current-region/new-field supplements include explicit full-position/rung dollar outcomes, exposure/sizing bases, matched calculation premium, missing saved-run input metadata, chosen-method evidence, execution comparisons, quote confirmation and recursive captured scoring fields. The 38 shared render/helper contracts pin formatting, colors, units, edit/revert bounds, freshness, failure, valuation and submission mechanisms. Exact source bindings are distinct from runtime proof: all final preservation and retest obligations remain pending #584. Browser assertions apply only to their named checks.

[Source manifest](source-evidence-manifest.json) pins 61 complete source-file SHA-256 hashes. The validator reads `git show <pinned SHA>:<path>`, including historical reference blobs; it does not require later implementation working-tree files to retain baseline hashes. The empty application diff was recorded at capture time, not a future implementation constraint. The evidence checkout before the earlier docs was `8ecc2c80c02e89c64f8161237fb6cda026afd2f5`; the application baseline is the immutable SHA above. [Baseline provenance](baseline-provenance.json) retains the native graph readback; `publication_preflight_graph.current_*` remains an earlier pre-publication observation. Historical audit/plan snapshots retain the old blocked gate as history, superseded by the user decision recorded here and in the approved implementation plan.

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

## Final implementation preservation work

- #577–#583 must retain every registered source field, explanation, color, action and conditional state at its future location, including unavailable values and all dynamic target/leg/evidence rows.
- #584 must verify the completed destinations and exercise missing/spread/tiny premium, alternate IV/model, no-row/ambiguous result, stale/rerun, request failure, reload restoration, tracking/broker outcomes and disclosure states. Keep distinct current-time stop-cost, Arithmetic stop valuation and race resolved barrier-time valuation. Preserve full-position versus rung populations and actual settings versus simulation inputs.
- Complete 1200/1366/1920 both-theme captures, required integrated tests and independent phase review. Source inspection and the four representative mocked captures do not clear those obligations.
- Compare the mini-PC build when evidence is supplied. This acceptance is explicitly deferred by the user and does not gate dependent implementation. Never label it verified or infer equality from the pinned source.

Source inventory requirements are satisfied; final implementation preservation remains pending #584. The coordinator owns ticket closure, dependency progression and independent audit records.
