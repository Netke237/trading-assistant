# Independent full-text preservation acceptance review

Reviewed baseline `9067538f7d992b2fdf74efb387e963acc77a6ffe` (origin/main) against frozen HEAD `e25772e746fc8aa4195c03a2fac6db75c2bedfee` (application `e98f4d88`). Read-only acceptance review; no application/test/state/GitHub edits and no formal audit counters.

**Verdict: ONE unique explanatory qualifier is missing. Long explanatory paragraphs otherwise survive. Do not claim zero unique-information loss until the qualifier is restored and verified.**

## Concrete missing information

- Baseline live `frontend/components/organisms/TradeCard/index.tsx:4329`, `ProfitTargetRow`, called by MC target map at3315: **`Stock-price equivalent (display approximation)`**.
- Current MC table header `TradeCard/index.tsx:3286` says only `Stock price`; value cell4689 retains the target number/unreachable state, with no live approximation/equivalent qualifier in any MC disclosure, helper or title.
- Narrow existing destination: `Monte Carlo model, inputs & provenance`, summary3362. Retain the full original qualifier there; a concise approximation qualifier next to the table value/header also avoids treating the approximation as a directly simulated stock target.
- Still-valid source support: `frontend/types/domain.ts:213` documents `display-only Stage-1 approximation`; backend Stage1 describes display-only back-solving. No obsolete numeric claim should be resurrected.
- Existing register IDs228/235/242 explicitly give units `stock $ display approximation`, but reconciliation currently pins only the numeric value formatter. This is why matching all625 IDs did not prove full text preservation.

## Inventory and method

Read AGENTS, audit-rule/required review skills as review context, Task7 plan, final-acceptance, existing625 source-review/reconciliation and preservation register. Reviewed actual baseline-to-HEAD source changes for Step7 page, TradeCard, BarrierRaceCard, SubmissionReview, BrokerOrderReview, SendToBrokerDialog, MethodPickSelector, MethodCompareSelector, CandidateNav and CollapsibleSection. All changed live TS/TSX application files are these10. Unchanged imports retain their complete source; their surviving call sites were checked, including both ScoreCardPanel instances, scoreDetailText, MarketSentiment/FundamentalHealth, quote/risk/tracking helpers, AutoTradeArm and race arithmetic helpers.

TypeScript AST extraction covers JSXText, string literals, template expressions, and complete Text JSX units including interpolated expressions. Comments are never evidence. The uncalled TargetRow helper is excluded in BOTH versions:27 lexical occurrences and3 Text units. Full paragraph matching normalizes whitespace/entities but retains dynamic expressions. Every remaining changed long literal and every changed long Text unit is individually reconciled to actual current source locations and guards. Short labels/arrows/layout tokens were reviewed separately.

| Measure | Count |
| --- | ---: |
| changed_live_tsx_files | 10 |
| baseline_all_lexical_occurrences | 1942 |
| excluded_dead_TargetRow_lexical_occurrences | 27 |
| baseline_live_lexical_occurrences | 1915 |
| all_live_literal_occurrences_mapped | 1915 |
| short_label_layout_exceptions_reviewed | 21 |
| baseline_live_literals_ge_10_characters | 1078 |
| exact_current_live_literal_matches | 972 |
| changed_literal_candidates_reviewed | 106 |
| changed_literal_candidates_preserved_or_nonexplanatory | 105 |
| baseline_Text_units | 312 |
| excluded_dead_TargetRow_Text_units | 3 |
| baseline_live_Text_units | 309 |
| baseline_live_Text_units_ge_8_words | 128 |
| complete_Text_units_exact_current_signature | 101 |
| complete_Text_unit_exceptions_reconciled | 27 |
| confirmed_unique_explanation_losses | 1 |
| unresolved_candidates | 1 |

The1915-occurrence all-live literal map includes code/import keys as well as rendered labels; it is an exhaustive extraction boundary, not1915 claims of unique visible explanatory paragraphs. The128 long Text units contain full explanations plus some long data captions/metadata;101 preserve the complete signature, and27 changes are separately traced below. The missing qualifier is a KV label, which is why a paragraph-only extractor would also have missed it.

## Live reachability and full-text destinations

- Native details retain their contents in the DOM. Stock and Contract Qualification retain full ScoreCardPanel props and keepMounted. Ladder retains its existing collapse/open controls; its new per-rung evidence is under `Ladder R:R, allocation & pricing`.
- Step7 supplies the live execution panel through TradeCard destinations; while an override plan is not ready the same panel renders independently at page1965. Its save/basket/error/unknown-order notices remain outside the broker-selected branch. Auto-trade detail opens for Armed or nonmanual state.
- MC model disclosure is always reachable with its method card; firstPassage/race-specific narrative keeps its source guards. The complete input precedence paragraph is3389; complete overlap/over100/first-event explanation3422; the short front summaries are additional summaries, not substitutes.
- Arithmetic basis disclosure3563 retains the full current-time/no-elapsed/echoed-premium/different-basis/not-applied explanation; per-share loss remains3564 while the headline is per contract. Target geometry/model disclosures retain original/resolved targets and quality warnings.
- Broker limit/market outlay explanations are split into two adjacent spans, both rendered. Account/server-credential/no-echo explanation is in Technical details. Submission request/provenance text is complete under Technical details and provenance, with new section-name references.
- Nine removed final result-summary rows have originating method twins; those rows are data duplicates. Unique explanations were checked separately: source/time/default warning in Recorded decision details, nonmonitored Arithmetic stop warning in Arithmetic card, full edge assumptions in Barrier Race and selected-race details. No blanket duplicate assumption was used.

## Complete long Text exceptions

Each entry quotes the entire original normalized Text unit. Data captions and headings are explicitly distinguished by the individual disposition; the machine map also retains every full original JSX source, current excerpt, disclosure ancestry and AST guard.

### P00 — frontend/components/molecules/CandidateNav/index.tsx:90

> BASKET {{basket.length > 0 ? `(${basket.length})` : '— empty'}}

Same basket.length count in visible Basket label, conditional on basket.length > 0; empty branch also survives.

Current source: `frontend/components/molecules/CandidateNav/index.tsx:96`.

### P01 — frontend/components/molecules/MethodPickSelector/index.tsx:227

> {{o.unavailable ?? `${o.rows.length} target${o.rows.length === 1 ? '' : 's'}`}}

Original count/unavailable text is preserved as method-button title; full unavailable reasons also visible below buttons. Each method option is rendered in options.map; title unchanged when unavailable else exact target count.

Current source: `frontend/components/molecules/MethodPickSelector/index.tsx:222`; `frontend/components/molecules/MethodPickSelector/index.tsx:237`.

### P02 — frontend/components/organisms/BarrierRaceCard/index.tsx:266

> Measured on its own, {{(invalidation.probability * 100).toFixed(0)}} % of paths touch the stock stop at some point {{invalidation.expectedDays != null ? ` (median ~${days(invalidation.expectedDays)})` : ''}} — ignoring whether the premium stop had already fired. The attribution below is the honest version: the gap between the two is how often you were stopped out on premium before the stock ever got there.

All clauses retained, including premium-stop-already-fired and the gap explanation. Only below → above; within invalidation &&, valid-race branch, Three barriers & assumptions.

Current source: `frontend/components/organisms/BarrierRaceCard/index.tsx:169`.

### P03 — frontend/components/organisms/BarrierRaceCard/index.tsx:424

> Stop medians, full risk / R:R / edge arithmetic and explanations

Original complete label exact as native summary; not an explanatory paragraph removed.

Current source: `frontend/components/organisms/BarrierRaceCard/index.tsx:439`.

### P04 — frontend/components/organisms/BrokerOrderReview/index.tsx:135

> The stops and targets above are in-app alerts on the saved Portfolio row. No stop-loss or take-profit order is sent to the broker — only this one opening order.

Entire no-broker-protective-order explanation retained. Above changes to These stops and the target alert below after regrouping; visible Position settings group.

Current source: `frontend/components/organisms/BrokerOrderReview/index.tsx:157`.

### P05 — frontend/components/organisms/SubmissionReview/index.tsx:182

> Probabilities, times and estimated values in the Final Recommendation are calculation results; they are not submitted.

Every explanatory clause survives verbatim apart from old section title renamed to current selected-target review. Native Technical details and provenance.

Current source: `frontend/components/organisms/SubmissionReview/index.tsx:206`.

### P06 — frontend/components/organisms/TradeCard/index.tsx:2479

> Backtested confidence: {{data.confidence == null ? 'not supplied' : `${data.confidence}%`}}

Stock score/confidence/tier and missing confidence branch are in visible Stock Qualification header meta; full ScoreCardPanel remains mounted in closed keepMounted disclosure.

Current source: `frontend/components/organisms/TradeCard/index.tsx:2670`; `frontend/components/organisms/TradeCard/index.tsx:2671`.

### P07 — frontend/components/organisms/TradeCard/index.tsx:2484

> $ {{data.contractDetails.mid.toFixed(2)}} mid / share · {{data.contractDetails.dte}} d DTE · $ {{car.toFixed(0)}} CaR

Contract mid/share and DTE remain visible in identity. CaR is expanded to Capital at risk in visible Contract Details.

Current source: `frontend/components/organisms/TradeCard/index.tsx:2604`; `frontend/components/organisms/TradeCard/index.tsx:2661`.

### P08 — frontend/components/organisms/TradeCard/index.tsx:2879

> Calculation does not replace your execution stock invalidation. Edit it in Order inputs & risk budget.

Same complete warning, old edit location renamed Exit Plan. Inside Structure & Stops evidence nested under Exit Plan explanation.

Current source: `frontend/components/organisms/TradeCard/index.tsx:2875`.

### P09 — frontend/components/organisms/TradeCard/index.tsx:3104

> Showing or comparing methods is display only: it does not run a calculation, choose the Final Recommendation method or change the order and exit fields. Each card keeps its own source, valuation basis and freshness; the methods are independent and can disagree.

First full sentence rephrased with new decision section name and all prohibitions retained. Second sentence verbatim for comparison; every individual model disclosure also retains independence/disagreement, so single-card mode has full supporting information.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3112`; `frontend/components/organisms/TradeCard/index.tsx:3113`; `frontend/components/organisms/TradeCard/index.tsx:3370`; `frontend/components/organisms/TradeCard/index.tsx:3576`; `frontend/components/organisms/TradeCard/index.tsx:3668`.

### P10 — frontend/components/organisms/TradeCard/index.tsx:3140

> Current-time stop-cost: Black-Scholes at the calculated stop with today's days to expiry (no elapsed time), on the calculation's echoed premium, per share. It is a different basis from the Arithmetic contract value at stop in Structure & Stops and from the Barrier Race's barrier-time repricing. The calculated stop does not replace the Exit Plan's execution invalidation.

Complete original no-elapsed-time/echoed-premium/per-share/different-Structure-and-race-bases/not-execution-invalidation paragraph retained with minor rephrasing and added shared-threshold distinction in Arithmetic basis, inputs & provenance. Link replaces Exit Plan text fragment; no clause lost.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3563`.

### P11 — frontend/components/organisms/TradeCard/index.tsx:3160

> {{t.rrRatio}} :1 target {{compareState === 'beyond' ? '⚠' : ''}}

Comparison role/list replaced semantic target table.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3487`.

### P12 — frontend/components/organisms/TradeCard/index.tsx:3162

> {{t.qualityReasons.includes('target_capped') ? 'Bearish target capped at the price floor. ' : ''}} {{targetCompareLabel(compareState)}}

Same original/snap/pricing-model content behind renamed native details.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3538`.

### P13 — frontend/components/organisms/TradeCard/index.tsx:3231

> Simulation inputs are what the last run raced against, resolved at Run: stock barrier = Arithmetic Plan structural + ATR stop (computed for this contract on this visit), else the structural level, else the Exit Plan stock invalidation; premium barrier = the Premium stop field when you changed it to a loss below the run's premium, else the risk-rules default percentage. They can differ from the settings below. Monte Carlo never copies one into the other; moving a barrier after the run hides these inputs and the race until you re-run.

Original entire precedence, edited-premium eligibility/default, independence, never-copy and post-run-hide-until-rerun paragraph preserved. settings below → Exit Plan settings only; model disclosure is reachable even without a result.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3389`.

### P14 — frontend/components/organisms/TradeCard/index.tsx:3232

> Actual Exit Plan settings (not changed by Monte Carlo)

Repeated MC actual-settings panel removed. Actual editable Exit Plan remains once: invalidation, pinned/global/read-only branches, current effective premium, explicit global/live/scan premium basis and loss amount. Submitted pinned-vs-global fill distinction remains in SubmissionReview/standalone Recorded decision details. MC model paragraph and difference link explicitly say settings are not changed; no unique explanatory paragraph in this panel was dropped.

Current source: `frontend/components/organisms/TradeCard/index.tsx:2820`; `frontend/components/organisms/TradeCard/index.tsx:2745`; `frontend/components/organisms/TradeCard/index.tsx:2777`; `frontend/components/organisms/TradeCard/index.tsx:3935`; `frontend/components/organisms/TradeCard/index.tsx:2830`; `frontend/components/organisms/TradeCard/index.tsx:2854`.

### P15 — frontend/components/organisms/TradeCard/index.tsx:3241

> Independent stock-stop touch probability and time remain in the Barrier Race disclosure. T1/T2/T3 are editable option-profit percentages, 1–500%; Run estimates the entered targets.

Original two complete sentences retained separately in Monte Carlo model, inputs & provenance; input title also keeps 1–500% bounds.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3371`; `frontend/components/organisms/TradeCard/index.tsx:3390`.

### P16 — frontend/components/organisms/TradeCard/index.tsx:3307

> No estimate yet. Nothing runs automatically — click Run Monte Carlo Estimate to simulate the entered targets; results and the Barrier Race appear after it finishes.

Same no-auto-run, explicit-run, entered-target results, completion and Barrier Race information; button name shortened to run the estimate within text. Same firstPassage===undefined && !firstPassageLoading guard.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3205`.

### P17 — frontend/components/organisms/TradeCard/index.tsx:3353

> Each probability above is measured on its own, so they can sum past 100% — a path that hits the target and later the stop is counted in both. The Barrier Race card below counts every path once, for whichever barrier it reached first. The invalidation row moved there too, for the same reason.

Entire original path-overlap/over-100/first-event-counted-once/invalidation-location paragraph retained; card below → above. Same firstPassage && raceIsShowable condition, now within MC model disclosure.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3422`.

### P18 — frontend/components/organisms/TradeCard/index.tsx:3382

> Actual Exit Plan settings (shared, not Ladder calculations)

All original heading distinctions retained in expanded context label.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3602`.

### P19 — frontend/components/organisms/TradeCard/index.tsx:3387

> Source: shared Exit Plan Invalidation field — the execution stock stop, set in Order inputs & risk budget.

Complete source explanation retained; old wrapper name renamed Exit Plan.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3609`.

### P20 — frontend/components/organisms/TradeCard/index.tsx:3397

> Scan-plan targets and stored option estimates. Edited stock targets use the existing local approximation; editing does not run a pricing model. Restored method choices are shown in the Final Recommendation below.

All clauses retained; Final Recommendation below renamed decision section below.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3661`.

### P21 — frontend/components/organisms/TradeCard/index.tsx:3500

> {{methodPick || recommendationUnavailable ? 'Selected method results' : 'Latest calculation'}}

Latest vs explicit selected-result provenance retained in reviewSource, rendered within Recorded decision details. No-pick is explicitly latest calculation, not a choice. Latest vs explicit selected-result provenance retained in reviewSource, rendered within Recorded decision details. No-pick is explicitly latest calculation, not a choice.

Current source: `frontend/components/organisms/TradeCard/index.tsx:2509`; `frontend/components/organisms/TradeCard/index.tsx:3903`; `frontend/components/organisms/TradeCard/index.tsx:2509`; `frontend/components/organisms/TradeCard/index.tsx:3903`.

### P22 — frontend/components/organisms/TradeCard/index.tsx:3501

> Choosing a method records your decision; it does not run a calculation or apply its values to the order and exit fields.

All original decision-record/no-calculation/no-apply concepts retained through visible decision sentence, recorded-choice metadata and selector full basis explanation. No need to reintroduce obsolete Final Recommendation title.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3947`; `frontend/components/molecules/MethodPickSelector/index.tsx:288`.

### P23 — frontend/components/organisms/TradeCard/index.tsx:3565

> computed via: Monte Carlo {{firstPassage.computedAt ? `, ${formatHHMM(firstPassage.computedAt)}` : ''}}

Computed-via method plus computedAt time preserved per arithmetic/MC/race branches. Rendered in Recorded decision details whenever reviewSource non-null; same method/results availability semantics. Upstream method cards retain their own calculation provenance.

Current source: `frontend/components/organisms/TradeCard/index.tsx:2509`; `frontend/components/organisms/TradeCard/index.tsx:3903`.

### P24 — frontend/components/organisms/TradeCard/index.tsx:3610

> computed via: Barrier Race {{firstPassage.computedAt ? `, ${formatHHMM(firstPassage.computedAt)}` : ''}}

Computed-via method plus computedAt time preserved per arithmetic/MC/race branches. Rendered in Recorded decision details whenever reviewSource non-null; same method/results availability semantics. Upstream method cards retain their own calculation provenance.

Current source: `frontend/components/organisms/TradeCard/index.tsx:2509`; `frontend/components/organisms/TradeCard/index.tsx:3903`.

### P25 — frontend/components/organisms/TradeCard/index.tsx:3643

> {{methodPick?.method === 'ladder' ? 'Selected method: Fixed % Ladder Plan' : 'No method explicitly run — showing Fixed % Ladder Plan (default)'}}

No-explicit-run/default-Ladder warning retained in reviewSource under recommendationMethod===null and !recommendationUnavailable, now explains targets location; rendered in Recorded decision details.

Current source: `frontend/components/organisms/TradeCard/index.tsx:2519`; `frontend/components/organisms/TradeCard/index.tsx:3903`.

### P26 — frontend/components/organisms/TradeCard/index.tsx:3873

> {{isTargetEdited ? 'Edited target: local stock-move approximation' : 'Scan/restored plan target and stored option estimate'}}

Same full-premium R:R figure moved into Ladder details, based on same ladderTargetFigures and authoritativeRr basis.

Current source: `frontend/components/organisms/TradeCard/index.tsx:3694`; `frontend/components/organisms/TradeCard/index.tsx:3666`.

## Evidence files and limits

- `/tmp/610-paragraph-preservation-location-map.json`: all1915 live source literal occurrences, all128 complete long Text units, all106 changed long candidates and21 short exceptions, each itemized. Frozen current file SHA256s included.
- `/tmp/610-verify-paragraph-map.py`: portable read-only integrity verifier; run with `--repo-root` and `--map` overrides. It passes evidence integrity while explicitly reporting the one unresolved content finding.
- `/tmp/610-paragraph-inventory.cjs` and `/tmp/610-full-paragraph-inventory.json`: raw AST extraction and context.

This is static source acceptance. Existing18 browser runs and prior regression evidence were not rerun or mislabeled as assertions for every paragraph. Conditions, mounted/disclosure placement and surviving call sites were source-traced, not newly executed. The finding is valid information loss regardless of numeric gate scope. The report is pinned to e25772e7 and must remain a historical finding after a later fix; verify any later restoration separately.
