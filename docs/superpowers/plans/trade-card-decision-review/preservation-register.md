# Partial source preservation register — #576

**Blocked:** actual trader running URL/revision is unknown. No running-build equivalence or ticket completion is established. No dependent application implementation is authorized by this evidence.

Source snapshot `c8f3b8a2cb5f0fa7e74fc0da407d1716a381fc6b`; evidence checkout `8ecc2c80c02e89c64f8161237fb6cda026afd2f5`. Historical reconciliation `765bf49152fd118bcca1d3c6f2c9802d7bbe578b`. Application source is unchanged between the snapshot and evidence checkout.

The JSON register carries all 520 historical IDs; 60 retain byte-identical complete historical rendering regions somewhere in current source. This is continuity evidence only. Every historical row remains open for individual current field/formatter/state verification. The 33 current contracts below were source-inspected, with separate links only to named local browser assertions. No claim that all 520 entries were browser-tested.

Each table row supplies a proposed future destination. Historical per-item mutability, units and time basis remain unverified in JSON; the supplement supplies those contracts for inspected current regions. Nulls are work remaining, not unavailable product values. Current candidate regions are navigation aids, not confirmed per-field mappings.

## Inspected current contracts and changed surfaces

| ID | Current source contract | Mutability / units / time | Future destination | Evidence |
|---|---|---|---|---|
| N01 | Strike/right/ISO expiry, contract id, stock/contract score and confidence, snapshot note (frontend/components/organisms/TradeCard/index.tsx:2250) | inherited/read-only; stock and option $/share; scores /100; DTE days; scan snapshot | Identity and complete details (#577) | source inspected; browser not asserted; user build not verified |
| N02 | Dynamic spread leg action/qty/strike/right/expiry; debit-credit/profit/loss/breakeven (frontend/components/organisms/TradeCard/index.tsx:2327) | inherited/read-only; leg qty; stock strike; supplied spread dollars; scan snapshot | Full spread context (#577) | source inspected; browser not asserted; user build not verified |
| N03 | Scores default collapsed, keepMounted, existing storage key and shared ScoreCardPanel (frontend/components/organisms/TradeCard/index.tsx:2386) | disclosure only; score points, confidence %; scan snapshot | Retained score disclosure (#577/#584) | source inspected; browser not asserted; user build not verified |
| N04 | Ladder source/independence, full-premium R/R, editable target loop; actual rows dynamic (frontend/components/organisms/TradeCard/index.tsx:2420) | editable stock targets; inherited estimates/calculated display; stock $; option $/share; full-position and rung $; R/R; scan estimates; edit uses local approximation | Ladder comparison (#580) | source inspected; browser not asserted; user build not verified |
| N05 | Limit/revert/validation; read-only max fill/order type; entered contracts (frontend/components/organisms/TradeCard/index.tsx:2495) | editable Limit/Contracts; read-only Max fill/type; option $/share; integer contracts; execution overlay with existing live bounds | Order inputs (#578) | source inspected; browser not asserted; user build not verified |
| N06 | Invalidation/revert/missing; effective premium loss amount; tiny-mid pinned/global branches; time exit (frontend/components/organisms/TradeCard/index.tsx:2542) | editable Invalidation/Premium stop; inherited Time exit; stock $; option loss $/share; DTE days; current execution overlay/live/global/scan seed | One actual Exit Plan (#578) | source inspected; browser not asserted; user build not verified |
| N07 | premiumStopReadOnly, showsGlobalOnLiveMid and effectivePremiumStop have separate branches (frontend/components/organisms/TradeCard/index.tsx:1750) | inherited or editable according to touched state; premium loss $/share; global loss %; untouched live/global versus pinned scan/user basis | Actual Exit Plan basis (#578) | source inspected; browser not asserted; user build not verified |
| N08 | Default/override editor; scan-mid full-premium exposure; Arithmetic stop-loss sizing; explicit Apply (frontend/components/organisms/TradeCard/index.tsx:2619) | editable override; calculated recommendation; Apply action; budget $/%; contracts; exposure $; scan mid × entered quantity, not editable limit/live quote | Order risk budget (#578) | source inspected; browser not asserted; user build not verified |
| N09 | Scan final stop and Arithmetic final stop retained with source, ATR, confidence, time/reference and separate contract valuation (frontend/components/organisms/TradeCard/index.tsx:2698) | inherited scan or calculated plan; stock $; ATR $; option $/share; confidence %; scan/restored/current-session reference distinguished | Structure disclosure (#578/#580) | source inspected; browser not asserted; user build not verified |
| N10 | Standalone check loading/failure/no level/equal price/stock reference and restored freshness (frontend/components/organisms/TradeCard/index.tsx:2807) | explicit calculation action/read-only results; stock $; distance %; confidence %; independent structural check vintage | Structure disclosure (#578) | source inspected; browser not asserted; user build not verified |
| N11 | Badge, remaining/loss per share, per-contract and entered-quantity loss, selected-contract-only source and full arithmetic (frontend/components/organisms/TradeCard/index.tsx:2862) | calculated/read-only; option $/share; $/contract; quantity $; fraction %; BS today stop-cost basis | Retain stop-cost check (#578) | source inspected; browser not asserted; user build not verified |
| N12 | Arithmetic premium accepted only from bs_today stopCost with matching stop price (frontend/components/organisms/TradeCard/index.tsx:2216) | calculated or unavailable; option $/share; echoed cent-rounded calculation premium | Arithmetic matched basis (#580) | source inspected; browser not asserted; user build not verified |
| N13 | Selected strike/right, calculation stock reference, premium, shared stop; all dynamic target rows and geometry details (frontend/components/organisms/TradeCard/index.tsx:2907) | calculated/read-only; explicit Compute action; stock $; option $/share; full-exit $; probability %; calendar days; calculation basis; returned stock entry unavailable | Arithmetic comparison (#580) | source inspected; browser not asserted; user build not verified |
| N14 | Captured request versus same-estimate premium echo and half-cent matching rule (frontend/components/organisms/TradeCard/index.tsx:1927) | calculated or unavailable; option $/share; same-estimate cent-rounded basis | Monte Carlo matched basis (#579) | source inspected; browser not asserted; user build not verified |
| N15 | Run stock entry and saved run DTE unavailable; current holding settings not saved run inputs; simulation to expiry and independent touches (frontend/components/organisms/TradeCard/index.tsx:2972) | inherited current settings; unavailable saved inputs; stock $; option $/share; DTE/calendar vs trading days; scan/current settings explicitly separate from run | Monte Carlo context (#579) | source inspected; browser not asserted; user build not verified |
| N16 | T1–T3 inputs clamped 1–500%; explicit Run disabled while structure/plan pending; errors/wait (frontend/components/organisms/TradeCard/index.tsx:3000) | editable inputs; explicit action; option-profit %; next explicit run | Monte Carlo inputs (#579) | source inspected; browser not asserted; user build not verified |
| N17 | Every returned target: premium/outcome/stock equivalent/independent probability/conditional days/structural pairing (frontend/components/organisms/TradeCard/index.tsx:3884) | calculated/read-only; option $/share; full-exit $; stock $; probability %; calendar days; estimate basis; structural pairing separate | All dynamic Monte Carlo rows (#579) | source inspected; browser not asserted; user build not verified |
| N18 | estimateIsFresh, stockStopMoved, raceBarriersMoved, raceIsShowable guard different vintages (frontend/components/organisms/TradeCard/index.tsx:1862) | calculated state; barrier stock $; premium loss $/share; current contract and captured barriers | Preserve separate freshness guards (#579) | source inspected; named mocked assertion; user build not verified |
| N19 | Race consumes same estimate and quantity; shortcuts gated separately by availability (frontend/components/organisms/TradeCard/index.tsx:3107) | choice action; calculated race; contracts; premium/stock barrier values; estimateIsFresh plus raceBarriersMoved | Race summary/expansion (#579) | source inspected; named mocked assertion; user build not verified |
| N20 | Freshness first; 0-DTE, barrier-changed and standalone invalidation handling (frontend/components/organisms/BarrierRaceCard/index.tsx:120) | calculated state; probability %; conditional calendar days; stock $; measured stop for stock-moved state | Race unavailable/stale states (#579) | source inspected; named mocked assertion; user build not verified |
| N21 | Dynamic race outcomes; quantity outcome separate from edge/contract; target shortcuts; weighted numerical attribution versus raw bar inputs (frontend/components/organisms/BarrierRaceCard/index.tsx:264) | calculated results; selection action; option $/share; selected-contract full-exit $; edge $/contract; R/R; %; same estimate; medians conditional on first outcome | Race rows and allocated geometry fix (#579) | source inspected; browser not asserted; user build not verified |
| N22 | Conditional medians, risk/RR/edge detail, commission/IV assumptions; contradictory immediate-cost explanation recorded separately (frontend/components/organisms/BarrierRaceCard/index.tsx:397) | read-only disclosure; risk $/share; R/R; edge $/contract; days; barrier-time valuation | Preserve accurate explanation (#579) | source inspected; browser not asserted; user build not verified |
| N23 | Choice/target matching ambiguity; recorded stock/option targets, model/probability/time, judged-on/timestamp, actual execution summary (frontend/components/organisms/TradeCard/index.tsx:3150) | editable choice; calculated match; inherited execution; stock $; option $/share; quantity; calendar days; ISO timestamp; recorded pick vs matched result vs actual inputs | Authoritative review (#581) | source inspected; named mocked assertion; user build not verified |
| N24 | Invalidated choice cannot silently show another method latest result (frontend/components/organisms/TradeCard/index.tsx:2170) | calculated state; none; candidate/contract/reset and availability | Preserve choice freshness (#581) | source inspected; browser not asserted; user build not verified |
| N25 | Explicit selected method result versus no-pick latest-calculation fallback; all rows remain dynamic (frontend/components/organisms/TradeCard/index.tsx:3192) | read-only results; method-specific stock/premium/probability/RR/edge; computedAt; MC/race freshness gates | Authoritative review (#581) | source inspected; browser not asserted; user build not verified |
| N26 | Track basket/disabled, inline chart toggle, JSON download and recommendation id (frontend/components/organisms/TradeCard/index.tsx:3334) | actions/read-only id; none; current displayed card | Retain actions and both chart entries (#577/#584) | source inspected; browser not asserted; user build not verified |
| N27 | Controlled choices and optional row; separate stock and option price slots; judged-on records basis without changing alerts (frontend/components/molecules/MethodPickSelector/index.tsx:1) | editable choice only; stock $ vs option $/share; pickedAt ISO time; recorded choice | Preserve MethodPickSelector (#581) | source inspected; browser not asserted; user build not verified |
| N28 | Live quote missing warning and explicit confirmation; contract keyed confirmation; live mid/stock distinct (frontend/app/(frame)/screener/step-7-trade-card/page.tsx:1595) | acknowledgment action; inherited quotes; option $/share; stock $; live quote versus scan | Execution review (#581/#583) | source inspected; browser not asserted; user build not verified |
| N29 | Broker picker, direct send statuses/notes, arm owner, basket dialog, errors and toast (frontend/app/(frame)/screener/step-7-trade-card/page.tsx:1632) | actions/calculated status; contract qty; order id/status; request/save/response separate | Keep Step7 owner; review/outcomes (#581–#584) | source inspected; named mocked assertion; user build not verified |
| N30 | Captured order args; persist first; saved adjusted quantity before dispatch; unknown-save and unknown-order retention (frontend/app/(frame)/screener/step-7-trade-card/page.tsx:1198) | submit action; server normalized result; contracts; option limit $/share; rec/order ids; save quote is not broker fill | Authoritative direct draft/outcome (#583) | source inspected; browser not asserted; user build not verified |
| N31 | Row quantity seeded once; one-off edits; estimated scan-mid total; invalidation/method hard gates; risk confirmation (frontend/components/organisms/SendToBrokerDialog/index.tsx:75) | editable row quantity; calculated estimate; contracts; scan-mid quantity dollars; dialog snapshot; not server-resolved/fill | Server-resolved tracking review (#582) | source inspected; named mocked assertion; user build not verified |
| N32 | Accepted/pending/submitted are not fills; rejection versus ambiguous outcome retention (frontend/lib/directOrder.ts:64) | read-only response classification; order id/status only; broker response | Broker result evidence (#583) | source inspected; browser not asserted; user build not verified |
| N33 | Checklist reads effective displayed card and effective thresholds; missing configuration cautions (frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx:1) | inherited/calculated; basis-aware IV and thresholds; statuses; effective card/current config | Retain context rail (#584) | source inspected; browser not asserted; user build not verified |

## Before/after preservation obligations

“After” means proposed location under #577–#584, not an implemented result. All preservation checks are open. Exact region matches never verify all conditional branches. Historical placeholder 2:1/3:1, T1/T2/T3 and race 20/35/50 rows describe examples; preserve actual returned row loops and counts.

| Historical ID | Before: group / item | Current source continuity | Proposed after |
|---|---|---|---|
| 1 | Page header: STEP 7 OF 7 | exact historical region present; per item not verified | Retain page heading and How this page works (#584) |
| 2 | Page header: Trade Card | exact historical region present; per item not verified | Retain page heading and How this page works (#584) |
| 3 | Page header: Cycle candidates / tracking explanation | exact historical region present; per item not verified | Retain page heading and How this page works (#584) |
| 4 | Mode / frame: Options | changed; revalidation needed; per item not verified | Retain frame and navigation (#584) |
| 5 | Mode / frame: Stocks | changed; revalidation needed; per item not verified | Retain frame and navigation (#584) |
| 6 | Mode / frame: Pre-Breakout | changed; revalidation needed; per item not verified | Retain frame and navigation (#584) |
| 7 | Mode / frame: Step navigation | changed; revalidation needed; per item not verified | Retain frame and navigation (#584) |
| 8 | Mode / frame: App navigation | changed; revalidation needed; per item not verified | Retain frame and navigation (#584) |
| 9 | Mode / frame: Context rail | changed; revalidation needed; per item not verified | Retain frame and navigation (#584) |
| 10 | CandidateNav: Prev | exact historical region present; per item not verified | Retain Step7 candidate/basket owner (#584) |
| 11 | CandidateNav: Next | exact historical region present; per item not verified | Retain Step7 candidate/basket owner (#584) |
| 12 | CandidateNav: Symbol | exact historical region present; per item not verified | Retain Step7 candidate/basket owner (#584) |
| 13 | CandidateNav: Candidate index / count | exact historical region present; per item not verified | Retain Step7 candidate/basket owner (#584) |
| 14 | CandidateNav: Pin / Pinned | exact historical region present; per item not verified | Retain Step7 candidate/basket owner (#584) |
| 15 | CandidateNav: Pin-disabled reason | exact historical region present; per item not verified | Retain Step7 candidate/basket owner (#584) |
| 16 | CandidateNav: Basket count / empty | exact historical region present; per item not verified | Retain Step7 candidate/basket owner (#584) |
| 17 | CandidateNav: Pinned symbol chip | exact historical region present; per item not verified | Retain Step7 candidate/basket owner (#584) |
| 18 | CandidateNav: Select pinned symbol | exact historical region present; per item not verified | Retain Step7 candidate/basket owner (#584) |
| 19 | CandidateNav: Remove pinned symbol | exact historical region present; per item not verified | Retain Step7 candidate/basket owner (#584) |
| 20 | Symbol header: Ticker | changed; revalidation needed; per item not verified | Identity/market context (#577) |
| 21 | Symbol header: Company | changed; revalidation needed; per item not verified | Identity/market context (#577) |
| 22 | Symbol header: Stock price | changed; revalidation needed; per item not verified | Identity/market context (#577) |
| 23 | Symbol header: Direction | changed; revalidation needed; per item not verified | Identity/market context (#577) |
| 24 | Symbol header: Status | changed; revalidation needed; per item not verified | Identity/market context (#577) |
| 25 | Symbol header: Chart button | changed; revalidation needed; per item not verified | Identity/market context (#577) |
| 26 | Symbol header: Edited indicator | changed; revalidation needed; per item not verified | Identity/market context (#577) |
| 27 | Symbol header: Edited fields explanation | changed; revalidation needed; per item not verified | Identity/market context (#577) |
| 28 | Market Sentiment: Horizon | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 29 | Market Sentiment: Timeframe | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 30 | Market Sentiment: Conviction % | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 31 | Market Sentiment: Conviction label | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 32 | Market Sentiment: Interpretation | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 33 | Market Sentiment: State | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 34 | Market Sentiment: Sticky probability | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 35 | Market Sentiment: Average regime duration | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 36 | Market Sentiment: OMM/HMM alignment | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 37 | Market Sentiment: OMM only | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 38 | Market Sentiment: Insufficient history | changed; revalidation needed; per item not verified | Above Fundamental Health (#577) |
| 39 | Stock Scorecard: Title | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 40 | Stock Scorecard: Total score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 41 | Stock Scorecard: Stock confidence status | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 42 | Stock Scorecard: Numeric confidence % | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 43 | Stock Scorecard: Confidence explanation | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 44 | Stock Scorecard: Status tooltip | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 45 | Stock Scorecard: Trend label | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 46 | Stock Scorecard: Trend score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 47 | Stock Scorecard: Trend bar | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 48 | Stock Scorecard: Trend observation text | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 49 | Stock Scorecard: Pullback label | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 50 | Stock Scorecard: Pullback score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 51 | Stock Scorecard: Pullback bar | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 52 | Stock Scorecard: Pullback observation text | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 53 | Stock Scorecard: Trigger label | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 54 | Stock Scorecard: Trigger score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 55 | Stock Scorecard: Trigger bar | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 56 | Stock Scorecard: Trigger observation text | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 57 | Stock Scorecard: Event label | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 58 | Stock Scorecard: Event score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 59 | Stock Scorecard: Event bar | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 60 | Stock Scorecard: Event observation text | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 61 | Stock Scorecard: Volatility label | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 62 | Stock Scorecard: Volatility score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 63 | Stock Scorecard: Volatility bar | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 64 | Stock Scorecard: Volatility observation text | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 65 | Contract Scorecard: Contract identifier | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 66 | Contract Scorecard: Total score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 67 | Contract Scorecard: Contract confidence status | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 68 | Contract Scorecard: Status tooltip | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 69 | Contract Scorecard: DTE fit label | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 70 | Contract Scorecard: DTE fit score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 71 | Contract Scorecard: DTE fit bar | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 72 | Contract Scorecard: DTE fit observation text | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 73 | Contract Scorecard: Delta label | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 74 | Contract Scorecard: Delta score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 75 | Contract Scorecard: Delta bar | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 76 | Contract Scorecard: Delta observation text | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 77 | Contract Scorecard: IV label | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 78 | Contract Scorecard: IV score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 79 | Contract Scorecard: IV bar | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 80 | Contract Scorecard: IV observation text | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 81 | Contract Scorecard: Liquidity label | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 82 | Contract Scorecard: Liquidity score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 83 | Contract Scorecard: Liquidity bar | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 84 | Contract Scorecard: Liquidity observation text | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 85 | Contract Scorecard: Spread label | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 86 | Contract Scorecard: Spread score / maximum | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 87 | Contract Scorecard: Spread bar | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 88 | Contract Scorecard: Spread observation text | changed; revalidation needed; per item not verified | Retained score disclosure (#577/#584) |
| 89 | Fundamental Health: Overall score | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 90 | Fundamental Health: Quality label | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 91 | Fundamental Health: Risk label | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 92 | Fundamental Health: Growth score | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 93 | Fundamental Health: Quality score | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 94 | Fundamental Health: Risk score | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 95 | Fundamental Health: Overall score tooltip | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 96 | Fundamental Health: Growth tooltip | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 97 | Fundamental Health: Quality tooltip | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 98 | Fundamental Health: Risk tooltip | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 99 | Fundamental Health: Safety flags | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 100 | Fundamental Health: Safety flag tooltips | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 101 | Fundamental Health: No data state | exact historical region present; per item not verified | Immediately beneath Market Sentiment (#577) |
| 102 | Contract Details: Strike | changed; revalidation needed; per item not verified | Identity/context with full details (#577) |
| 103 | Contract Details: Expiry | changed; revalidation needed; per item not verified | Identity/context with full details (#577) |
| 104 | Contract Details: Right | changed; revalidation needed; per item not verified | Identity/context with full details (#577) |
| 105 | Contract Details: Mid | changed; revalidation needed; per item not verified | Identity/context with full details (#577) |
| 106 | Contract Details: Delta | changed; revalidation needed; per item not verified | Identity/context with full details (#577) |
| 107 | Contract Details: Theta / day | changed; revalidation needed; per item not verified | Identity/context with full details (#577) |
| 108 | Contract Details: IV rank or absolute IV (basis-aware) | changed; revalidation needed; per item not verified | Identity/context with full details (#577) |
| 109 | Contract Details: DTE | changed; revalidation needed; per item not verified | Identity/context with full details (#577) |
| 110 | Contract Details: CaR | changed; revalidation needed; per item not verified | Identity/context with full details (#577) |
| 111 | Spread Legs (conditional): Spread type | changed; revalidation needed; per item not verified | Retained full spread details (#577) |
| 112 | Spread Legs (conditional): Leg action | changed; revalidation needed; per item not verified | Retained full spread details (#577) |
| 113 | Spread Legs (conditional): Leg quantity | changed; revalidation needed; per item not verified | Retained full spread details (#577) |
| 114 | Spread Legs (conditional): Leg strike | changed; revalidation needed; per item not verified | Retained full spread details (#577) |
| 115 | Spread Legs (conditional): Leg right | changed; revalidation needed; per item not verified | Retained full spread details (#577) |
| 116 | Spread Legs (conditional): Leg expiry | changed; revalidation needed; per item not verified | Retained full spread details (#577) |
| 117 | Spread Legs (conditional): Net debit / credit | changed; revalidation needed; per item not verified | Retained full spread details (#577) |
| 118 | Spread Legs (conditional): Max profit | changed; revalidation needed; per item not verified | Retained full spread details (#577) |
| 119 | Spread Legs (conditional): Max loss | changed; revalidation needed; per item not verified | Retained full spread details (#577) |
| 120 | Spread Legs (conditional): Breakeven | changed; revalidation needed; per item not verified | Retained full spread details (#577) |
| 121 | Alternatives (conditional): Alternative count | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 122 | Alternatives (conditional): Expand / collapse | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 123 | Alternatives (conditional): Rank | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 124 | Alternatives (conditional): Symbol | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 125 | Alternatives (conditional): Strike | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 126 | Alternatives (conditional): Right | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 127 | Alternatives (conditional): Expiry | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 128 | Alternatives (conditional): DTE | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 129 | Alternatives (conditional): Contract confidence badge | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 130 | Alternatives (conditional): Contract confidence tooltip | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 131 | Alternatives (conditional): Score | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 132 | Alternatives (conditional): Mid | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 133 | Alternatives (conditional): Delta | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 134 | Alternatives (conditional): Theta | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 135 | Alternatives (conditional): IV rank or absolute IV | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 136 | Alternatives (conditional): R/R | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 137 | Alternatives (conditional): Trade-off reason | changed; revalidation needed; per item not verified | Retained alternatives disclosure (#577) |
| 138 | Order Entry: Order type | changed; revalidation needed; per item not verified | Actual order inputs (#578) |
| 139 | Order Entry: Editable Limit | changed; revalidation needed; per item not verified | Actual order inputs (#578) |
| 140 | Order Entry: Limit revert | changed; revalidation needed; per item not verified | Actual order inputs (#578) |
| 141 | Order Entry: Read-only Max fill | changed; revalidation needed; per item not verified | Actual order inputs (#578) |
| 142 | Order Entry: Editable Contracts | changed; revalidation needed; per item not verified | Actual order inputs (#578) |
| 143 | Order Entry: Contracts validation | changed; revalidation needed; per item not verified | Actual order inputs (#578) |
| 144 | Arithmetic: Title | changed; revalidation needed; per item not verified | Arithmetic comparison card (#580) |
| 145 | Arithmetic: Direction | changed; revalidation needed; per item not verified | Arithmetic comparison card (#580) |
| 146 | Arithmetic: Stock entry price | changed; revalidation needed; per item not verified | Arithmetic comparison card (#580) |
| 147 | Arithmetic: Independence explanation | changed; revalidation needed; per item not verified | Arithmetic comparison card (#580) |
| 148 | Arithmetic: Check structure button | changed; revalidation needed; per item not verified | Arithmetic comparison card (#580) |
| 149 | Arithmetic: Compute Arithmetic Plan button | changed; revalidation needed; per item not verified | Arithmetic comparison card (#580) |
| 150 | Max loss override: Max loss budget | changed; revalidation needed; per item not verified | Order inputs/risk budget (#578) |
| 151 | Max loss override: Default / override indication | changed; revalidation needed; per item not verified | Order inputs/risk budget (#578) |
| 152 | Max loss override: Set override / Edit override | changed; revalidation needed; per item not verified | Order inputs/risk budget (#578) |
| 153 | Max loss override: Percent / dollar mode | changed; revalidation needed; per item not verified | Order inputs/risk budget (#578) |
| 154 | Max loss override: Override value input | changed; revalidation needed; per item not verified | Order inputs/risk budget (#578) |
| 155 | Max loss override: Apply override | changed; revalidation needed; per item not verified | Order inputs/risk budget (#578) |
| 156 | Max loss override: Use default | changed; revalidation needed; per item not verified | Order inputs/risk budget (#578) |
| 157 | Structure check: Stop price | changed; revalidation needed; per item not verified | Retained structure/ATR disclosure (#578) |
| 158 | Structure check: Stop source label | changed; revalidation needed; per item not verified | Retained structure/ATR disclosure (#578) |
| 159 | Structure check: Distance % | changed; revalidation needed; per item not verified | Retained structure/ATR disclosure (#578) |
| 160 | Structure check: Checking | changed; revalidation needed; per item not verified | Retained structure/ATR disclosure (#578) |
| 161 | Structure check: Not run | changed; revalidation needed; per item not verified | Retained structure/ATR disclosure (#578) |
| 162 | Structure check: No structural stop found | changed; revalidation needed; per item not verified | Retained structure/ATR disclosure (#578) |
| 163 | Structure check: Stop equals price | changed; revalidation needed; per item not verified | Retained structure/ATR disclosure (#578) |
| 164 | Structure check: Failure / retry message | changed; revalidation needed; per item not verified | Retained structure/ATR disclosure (#578) |
| 165 | Stop cost gate: Max loss heading | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 166 | Stop cost gate: Status | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 167 | Stop cost gate: Loss % of premium | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 168 | Stop cost gate: Remaining premium / share | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 169 | Stop cost gate: Dollar loss per contract | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 170 | Stop cost gate: Original premium per contract | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 171 | Stop cost gate: Remaining value per contract | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 172 | Stop cost gate: Full pricing arithmetic | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 173 | Stop cost gate: Pricing model / priced today | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 174 | Stop cost gate: Badge interpretation | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 175 | Stop cost gate: Not computed reason | changed; revalidation needed; per item not verified | Structure/ATR disclosure; retain affected warnings (#578) |
| 176 | Arithmetic final stop: Bottom (final stop) | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 177 | Arithmetic final stop: Price | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 178 | Arithmetic final stop: Structural stop price / source | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 179 | Arithmetic final stop: ATR-floor price | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 180 | Arithmetic final stop: ATR(14) | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 181 | Arithmetic final stop: Structural ↔ ATR-floor distance | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 182 | Arithmetic final stop: Stop justification | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 183 | Arithmetic final stop: Risk-derived whole contracts | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 184 | Arithmetic final stop: Exact fractional size | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 185 | Arithmetic final stop: Apply recommended size | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 186 | Arithmetic final stop: Apply disabled state | changed; revalidation needed; per item not verified | Structure/ATR disclosure and method basis (#578/#580) |
| 187 | Arithmetic pre-computation: Scan stop source | changed; revalidation needed; per item not verified | Structure/Arithmetic unavailable/error states (#578/#580) |
| 188 | Arithmetic pre-computation: Scan stop value | changed; revalidation needed; per item not verified | Structure/Arithmetic unavailable/error states (#578/#580) |
| 189 | Arithmetic pre-computation: Contract value at stop placeholder | changed; revalidation needed; per item not verified | Structure/Arithmetic unavailable/error states (#578/#580) |
| 190 | Arithmetic pre-computation: Max loss if stopped placeholder | changed; revalidation needed; per item not verified | Structure/Arithmetic unavailable/error states (#578/#580) |
| 191 | Arithmetic pre-computation: From scan / compute to price explanation | changed; revalidation needed; per item not verified | Structure/Arithmetic unavailable/error states (#578/#580) |
| 192 | Arithmetic pre-computation: Missing stop / re-run scan | changed; revalidation needed; per item not verified | Structure/Arithmetic unavailable/error states (#578/#580) |
| 193 | Arithmetic pre-computation: 2:1 not yet computed | changed; revalidation needed; per item not verified | Structure/Arithmetic unavailable/error states (#578/#580) |
| 194 | Arithmetic pre-computation: 3:1 not yet computed | changed; revalidation needed; per item not verified | Structure/Arithmetic unavailable/error states (#578/#580) |
| 195 | Arithmetic pre-computation: Calculation error | changed; revalidation needed; per item not verified | Structure/Arithmetic unavailable/error states (#578/#580) |
| 196 | Arithmetic 2:1: Target label | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 197 | Arithmetic 2:1: Arithmetic price | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 198 | Arithmetic 2:1: Nearest structural level | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 199 | Arithmetic 2:1: Distance | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 200 | Arithmetic 2:1: Tolerance | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 201 | Arithmetic 2:1: Contract price | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 202 | Arithmetic 2:1: Pricing model | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 203 | Arithmetic 2:1: Probability before expiry | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 204 | Arithmetic 2:1: Expected time / unlikely | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 205 | Arithmetic 2:1: Structural comparison warning | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 206 | Arithmetic 3:1: Target label | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 207 | Arithmetic 3:1: Arithmetic price | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 208 | Arithmetic 3:1: Nearest structural level | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 209 | Arithmetic 3:1: Distance | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 210 | Arithmetic 3:1: Tolerance | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 211 | Arithmetic 3:1: Contract price | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 212 | Arithmetic 3:1: Pricing model | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 213 | Arithmetic 3:1: Probability before expiry | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 214 | Arithmetic 3:1: Expected time / unlikely | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 215 | Arithmetic 3:1: Structural comparison warning | changed; revalidation needed; per item not verified | All dynamic Arithmetic rows in comparison card (#580) |
| 216 | Monte Carlo: Title | changed; revalidation needed; per item not verified | Monte Carlo comparison card (#579) |
| 217 | Monte Carlo: Independence explanation | changed; revalidation needed; per item not verified | Monte Carlo comparison card (#579) |
| 218 | Monte Carlo: T1 % input | changed; revalidation needed; per item not verified | Monte Carlo comparison card (#579) |
| 219 | Monte Carlo: T2 % input | changed; revalidation needed; per item not verified | Monte Carlo comparison card (#579) |
| 220 | Monte Carlo: T3 % input | changed; revalidation needed; per item not verified | Monte Carlo comparison card (#579) |
| 221 | Monte Carlo: Input bounds | changed; revalidation needed; per item not verified | Monte Carlo comparison card (#579) |
| 222 | Monte Carlo: Run Monte Carlo Estimate | changed; revalidation needed; per item not verified | Monte Carlo comparison card (#579) |
| 223 | Monte Carlo: Estimating state | changed; revalidation needed; per item not verified | Monte Carlo comparison card (#579) |
| 224 | Monte Carlo: Waiting for stop state | changed; revalidation needed; per item not verified | Monte Carlo comparison card (#579) |
| 225 | Monte Carlo: Failure / retry | changed; revalidation needed; per item not verified | Monte Carlo comparison card (#579) |
| 226 | Monte Carlo T1: Target label / % | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 227 | Monte Carlo T1: Estimated option value | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 228 | Monte Carlo T1: Stock price | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 229 | Monte Carlo T1: Probability | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 230 | Monte Carlo T1: Expected time | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 231 | Monte Carlo T1: Structural level found | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 232 | Monte Carlo T1: Structural pending / unavailable / zero-risk states | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 233 | Monte Carlo T2: Target label / % | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 234 | Monte Carlo T2: Estimated option value | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 235 | Monte Carlo T2: Stock price | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 236 | Monte Carlo T2: Probability | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 237 | Monte Carlo T2: Expected time | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 238 | Monte Carlo T2: Structural level found | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 239 | Monte Carlo T2: Structural pending / unavailable / zero-risk states | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 240 | Monte Carlo T3: Target label / % | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 241 | Monte Carlo T3: Estimated option value | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 242 | Monte Carlo T3: Stock price | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 243 | Monte Carlo T3: Probability | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 244 | Monte Carlo T3: Expected time | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 245 | Monte Carlo T3: Structural level found | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 246 | Monte Carlo T3: Structural pending / unavailable / zero-risk states | changed; revalidation needed; per item not verified | All dynamic Monte Carlo target rows (#579) |
| 247 | Monte Carlo explanation: Independent probabilities may sum beyond 100% | exact historical region present; per item not verified | Monte Carlo explanation and race expansion (#579) |
| 248 | Monte Carlo explanation: Barrier Race counts paths once | exact historical region present; per item not verified | Monte Carlo explanation and race expansion (#579) |
| 249 | Monte Carlo explanation: Invalidation row location | exact historical region present; per item not verified | Monte Carlo explanation and race expansion (#579) |
| 250 | Barrier Race: Title | changed; revalidation needed; per item not verified | Barrier Race summary/expansion (#579) |
| 251 | Barrier Race: Same simulation / no new levels explanation | changed; revalidation needed; per item not verified | Barrier Race summary/expansion (#579) |
| 252 | Barrier Race: Not simulated today expiry | changed; revalidation needed; per item not verified | Barrier Race summary/expansion (#579) |
| 253 | Barrier Race: Freshness suppression | changed; revalidation needed; per item not verified | Barrier Race summary/expansion (#579) |
| 254 | Barrier Race: Barriers changed / re-run | changed; revalidation needed; per item not verified | Barrier Race summary/expansion (#579) |
| 255 | Barrier Race: Stock-stop moved handling | changed; revalidation needed; per item not verified | Barrier Race summary/expansion (#579) |
| 256 | Race barriers: Profit target level per row | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 257 | Race barriers: Target source % of premium | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 258 | Race barriers: Target is exit not stop | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 259 | Race barriers: Stock stop level | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 260 | Race barriers: Stock stop source | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 261 | Race barriers: Stock stop whichever first | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 262 | Race barriers: Premium stop level | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 263 | Race barriers: Premium stop % | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 264 | Race barriers: Premium stop source note | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 265 | Race barriers: Premium stop whichever first | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 266 | Race barriers: Standalone invalidation probability | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 267 | Race barriers: Standalone invalidation median | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 268 | Race barriers: Ignoring earlier premium stop explanation | exact historical region present; per item not verified | Barrier Race expansion (#579) |
| 269 | Barrier race 20%: Target % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 270 | Barrier race 20%: Option target | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 271 | Barrier race 20%: Stacked split bar | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 272 | Barrier race 20%: Target-first % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 273 | Barrier race 20%: Stock-stop-first % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 274 | Barrier race 20%: Premium-stop-first % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 275 | Barrier race 20%: Neither % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 276 | Barrier race 20%: Conditional median to target | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 277 | Barrier race 20%: Conditional median to stock stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 278 | Barrier race 20%: Conditional median to premium stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 279 | Barrier race 20%: Risk dollars / share | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 280 | Barrier race 20%: R:R vs stock stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 281 | Barrier race 20%: R:R vs premium stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 282 | Barrier race 20%: Edge / contract | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 283 | Barrier race 20%: Full risk arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 284 | Barrier race 20%: Full R:R arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 285 | Barrier race 20%: Full premium R:R arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 286 | Barrier race 20%: Full edge arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 287 | Barrier race 35%: Target % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 288 | Barrier race 35%: Option target | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 289 | Barrier race 35%: Stacked split bar | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 290 | Barrier race 35%: Target-first % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 291 | Barrier race 35%: Stock-stop-first % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 292 | Barrier race 35%: Premium-stop-first % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 293 | Barrier race 35%: Neither % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 294 | Barrier race 35%: Conditional median to target | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 295 | Barrier race 35%: Conditional median to stock stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 296 | Barrier race 35%: Conditional median to premium stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 297 | Barrier race 35%: Risk dollars / share | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 298 | Barrier race 35%: R:R vs stock stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 299 | Barrier race 35%: R:R vs premium stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 300 | Barrier race 35%: Edge / contract | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 301 | Barrier race 35%: Full risk arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 302 | Barrier race 35%: Full R:R arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 303 | Barrier race 35%: Full premium R:R arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 304 | Barrier race 35%: Full edge arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 305 | Barrier race 50%: Target % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 306 | Barrier race 50%: Option target | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 307 | Barrier race 50%: Stacked split bar | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 308 | Barrier race 50%: Target-first % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 309 | Barrier race 50%: Stock-stop-first % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 310 | Barrier race 50%: Premium-stop-first % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 311 | Barrier race 50%: Neither % | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 312 | Barrier race 50%: Conditional median to target | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 313 | Barrier race 50%: Conditional median to stock stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 314 | Barrier race 50%: Conditional median to premium stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 315 | Barrier race 50%: Risk dollars / share | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 316 | Barrier race 50%: R:R vs stock stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 317 | Barrier race 50%: R:R vs premium stop | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 318 | Barrier race 50%: Edge / contract | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 319 | Barrier race 50%: Full risk arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 320 | Barrier race 50%: Full R:R arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 321 | Barrier race 50%: Full premium R:R arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 322 | Barrier race 50%: Full edge arithmetic | changed; revalidation needed; per item not verified | All dynamic race outcome rows, summary and expansion (#579) |
| 323 | Race explanations: Number of paths | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 324 | Race explanations: 100% attribution explanation | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 325 | Race explanations: Conditional medians definition | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 326 | Race explanations: Repriced at barrier median day | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 327 | Race explanations: Immediate loss cross-reference | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 328 | Race explanations: Pricing model difference | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 329 | Race explanations: Stock stop under 1% warning | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 330 | Race explanations: IV fallback warning | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 331 | Race explanations: Stock R:R interpretation | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 332 | Race explanations: Premium R:R cancellation explanation | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 333 | Race explanations: Neither term signed explanation | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 334 | Race explanations: Unchanged IV assumption | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 335 | Race explanations: Long call fear-bid interpretation | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 336 | Race explanations: Before commissions | changed; revalidation needed; per item not verified | Barrier Race expansion (#579) |
| 337 | Exit Plan: Editable Invalidation | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 338 | Exit Plan: Invalidation revert | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 339 | Exit Plan: Missing invalidation / rescan | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 340 | Exit Plan: Editable Premium stop loss dollars | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 341 | Exit Plan: Premium stop revert | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 342 | Exit Plan: Global % note | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 343 | Exit Plan: Pinned read-only stop | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 344 | Exit Plan: Too-small-mid explanation | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 345 | Exit Plan: Pinned stop retained / dropped explanation | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 346 | Exit Plan: Time exit DTE | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 347 | Exit Plan: Invalidation separate from arithmetic / submit gate explanation | changed; revalidation needed; per item not verified | One actual Exit Plan (#578) |
| 348 | Fixed % Ladder: Collapse toggle / persistence | changed; revalidation needed; per item not verified | Ladder comparison card (#580) |
| 349 | Fixed % Ladder: Sell-to-Close title | changed; revalidation needed; per item not verified | Ladder comparison card (#580) |
| 350 | Fixed % Ladder: Independence explanation | changed; revalidation needed; per item not verified | Ladder comparison card (#580) |
| 351 | Fixed Ladder T1: Label | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 352 | Fixed Ladder T1: Editable stock target | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 353 | Fixed Ladder T1: Edited indicator | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 354 | Fixed Ladder T1: Estimated option | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 355 | Fixed Ladder T1: R:R contribution | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 356 | Fixed Ladder T1: Contracts to sell | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 357 | Fixed Ladder T1: Single-contract leftover warning | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 358 | Fixed Ladder T1: Pricing method | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 359 | Fixed Ladder T2: Label | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 360 | Fixed Ladder T2: Editable stock target | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 361 | Fixed Ladder T2: Edited indicator | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 362 | Fixed Ladder T2: Estimated option | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 363 | Fixed Ladder T2: R:R contribution | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 364 | Fixed Ladder T2: Contracts to sell | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 365 | Fixed Ladder T2: Single-contract leftover warning | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 366 | Fixed Ladder T2: Pricing method | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 367 | Fixed Ladder T3: Label | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 368 | Fixed Ladder T3: Editable stock target | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 369 | Fixed Ladder T3: Edited indicator | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 370 | Fixed Ladder T3: Estimated option | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 371 | Fixed Ladder T3: R:R contribution | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 372 | Fixed Ladder T3: Contracts to sell | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 373 | Fixed Ladder T3: Single-contract leftover warning | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 374 | Fixed Ladder T3: Pricing method | changed; revalidation needed; per item not verified | All dynamic Ladder targets/full-position/rung outcomes (#580) |
| 375 | Final Recommendation: Title | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 376 | Final Recommendation: Final Status label | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 377 | Final Recommendation: Final Status value | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 378 | Final Recommendation: Status explanation | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 379 | Final Recommendation: Computed via method | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 380 | Final Recommendation: Computed timestamp | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 381 | Final Recommendation: Arithmetic stop | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 382 | Final Recommendation: Arithmetic stop justification | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 383 | Final Recommendation: Arithmetic targets / probabilities | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 384 | Final Recommendation: Arithmetic stop not auto-monitored warning | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 385 | Final Recommendation: Monte Carlo targets / probabilities | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 386 | Final Recommendation: Not re-run this session warning | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 387 | Final Recommendation: Race armed stock / option stops | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 388 | Final Recommendation: Edge per target / contract | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 389 | Final Recommendation: Stock R:R per target | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 390 | Final Recommendation: Edge assumptions | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 391 | Final Recommendation: No method run / default Ladder notice | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 392 | Final Recommendation: Default ladder target rows | changed; revalidation needed; per item not verified | Authoritative trade review (#581–#583) |
| 393 | MethodPickSelector: Exit method label | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 394 | MethodPickSelector: Ladder | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 395 | MethodPickSelector: Arithmetic | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 396 | MethodPickSelector: Monte Carlo | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 397 | MethodPickSelector: Barrier Race | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 398 | MethodPickSelector: Availability reasons | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 399 | MethodPickSelector: Target counts | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 400 | MethodPickSelector: Clear selection | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 401 | MethodPickSelector: Target row selector | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 402 | MethodPickSelector: Target row prices | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 403 | MethodPickSelector: Judged on Stock stop | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 404 | MethodPickSelector: Judged on Premium stop | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 405 | MethodPickSelector: Judged-on record explanation | changed; revalidation needed; per item not verified | Retained trade choice beside authoritative review (#581) |
| 406 | Card actions: Track basket (current page-supplied send label) | exact historical region present; per item not verified | Retained actions/chart/export (#577/#584) |
| 407 | Card actions: Disabled reason | exact historical region present; per item not verified | Retained actions/chart/export (#577/#584) |
| 408 | Card actions: View / Hide chart | exact historical region present; per item not verified | Retained actions/chart/export (#577/#584) |
| 409 | Card actions: Inline chart | exact historical region present; per item not verified | Retained actions/chart/export (#577/#584) |
| 410 | Card actions: Export JSON | exact historical region present; per item not verified | Retained actions/chart/export (#577/#584) |
| 411 | Card actions: Recommendation ID | exact historical region present; per item not verified | Retained actions/chart/export (#577/#584) |
| 412 | Current page execution: Broker picker | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 413 | Current page execution: IBKR Paper | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 414 | Current page execution: Tradier Paper | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 415 | Current page execution: Tastytrade Paper | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 416 | Current page execution: Not configured reasons | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 417 | Current page execution: Place Limit | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 418 | Current page execution: Right Now — Market | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 419 | Current page execution: Broker refusal | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 420 | Current page execution: Plan preparation | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 421 | Current page execution: Missing invalidation | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 422 | Current page execution: Missing method pick | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 423 | Current page execution: Earnings veto | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 424 | Current page execution: Live mid | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 425 | Current page execution: Live stock price | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 426 | Current page execution: Fetching live price | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 427 | Current page execution: Placed order ID | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 428 | Current page execution: Plan retry | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 429 | Current page execution: Save notes | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 430 | Current page execution: Basket save errors | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 431 | Current page execution: Order errors | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 432 | Current page execution: Direct-send notes | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 433 | Current page execution: Retry direct-send note | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 434 | Current page execution: Backend sync / tracking toast | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 435 | Current page execution: Track basket dialog | changed; revalidation needed; per item not verified | Decision/execution review and outcomes; keep Step7 owner (#581/#583) |
| 436 | AutoTradeArm: Manual mode | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 437 | AutoTradeArm: Armed mode | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 438 | AutoTradeArm: Post-scan mode | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 439 | AutoTradeArm: Arm | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 440 | AutoTradeArm: Disarm | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 441 | AutoTradeArm: Fire now | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 442 | AutoTradeArm: Armed symbol and direction | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 443 | AutoTradeArm: Waiting trigger message | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 444 | AutoTradeArm: Missing broker / stop / pick reasons | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 445 | AutoTradeArm: Missing gate snapshot | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 446 | AutoTradeArm: Premium stop at or above fill warning | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 447 | AutoTradeArm: Sub-cent stop warning | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 448 | AutoTradeArm: Booking explanation / arm-time snapshot | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 449 | AutoTradeArm: Post-scan instruction | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 450 | AutoTradeArm: Order ID | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 451 | AutoTradeArm: Order sent not booked | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 452 | AutoTradeArm: Auto-trade fired | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 453 | AutoTradeArm: Error | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 454 | AutoTradeArm: Fire note | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 455 | AutoTradeArm: Duplicate warning | changed; revalidation needed; per item not verified | Retain Step7-owned arm/fire controls (#584) |
| 456 | Context rail checklist: Pre-trade checklist title | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 457 | Context rail checklist: Scan empty message | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 458 | Context rail checklist: Checklist context text | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 459 | Context rail checklist: Regime status / explanation | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 460 | Context rail checklist: IV status / thresholds / override / missing | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 461 | Context rail checklist: Earnings date / ETF / unknown | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 462 | Context rail checklist: Earnings window status / exact scan thresholds | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 463 | Context rail checklist: Score ≥55 / lower of scores | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 464 | Context rail checklist: R:R ≥2.0 / caution band / pending | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 465 | Context rail checklist: Spread <5% label / subscore rule | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 466 | Context rail checklist: Historical analogs unavailable | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 467 | Context rail checklist: Rail Quick Look | changed; revalidation needed; per item not verified | Retain right context rail (#584) |
| 468 | Presentation enhancement: Effective stock factor weights | exact historical region present; per item not verified | Retain qualification/effective configuration evidence (#584) |
| 469 | Presentation enhancement: Effective contract factor weights | exact historical region present; per item not verified | Retain qualification/effective configuration evidence (#584) |
| 470 | Presentation enhancement: Weighted contribution | exact historical region present; per item not verified | Retain qualification/effective configuration evidence (#584) |
| 471 | Presentation enhancement: Score rule thresholds | exact historical region present; per item not verified | Retain qualification/effective configuration evidence (#584) |
| 472 | Presentation enhancement: Gate reasons / effective configuration provenance | exact historical region present; per item not verified | Retain qualification/effective configuration evidence (#584) |
| 473 | Tracking dialog: Dialog title | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 474 | Tracking dialog: No broker order explanation | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 475 | Tracking dialog: Close dialog | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 476 | Tracking dialog: Symbol | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 477 | Tracking dialog: Contract | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 478 | Tracking dialog: Mid | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 479 | Tracking dialog: Quantity input | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 480 | Tracking dialog: Estimated dollars | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 481 | Tracking dialog: Spread leg identity | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 482 | Tracking dialog: Spread leg quantity | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 483 | Tracking dialog: Number to track | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 484 | Tracking dialog: Estimated total | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 485 | Tracking dialog: Cancel | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 486 | Tracking dialog: Add to Portfolio | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 487 | Tracking dialog: Override & Submit | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 488 | Tracking dialog: Missing invalidation | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 489 | Tracking dialog: Missing method pick | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 490 | Tracking dialog: Within risk limits | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 491 | Tracking dialog: Single-trade exposure reason | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 492 | Tracking dialog: Total exposure reason | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 493 | Tracking dialog: Concurrent positions reason | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 494 | Tracking dialog: Duplicate symbol reason | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 495 | Tracking dialog: Daily recommendations reason | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 496 | Tracking dialog: Max loss per trade reason | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 497 | Tracking dialog: Worst offender symbol / loss / limit | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 498 | Tracking dialog: Second-click override instruction | changed; revalidation needed; per item not verified | Server-resolved basket review (#582) |
| 499 | Inline chart: Company / Chart title | exact historical region present; per item not verified | Retain inline chart and separate chart entry (#577) |
| 500 | Inline chart: Symbol | exact historical region present; per item not verified | Retain inline chart and separate chart entry (#577) |
| 501 | Inline chart: WatchStar | exact historical region present; per item not verified | Retain inline chart and separate chart entry (#577) |
| 502 | Inline chart: Timeframe descriptor | exact historical region present; per item not verified | Retain inline chart and separate chart entry (#577) |
| 503 | Inline chart: Close chart | exact historical region present; per item not verified | Retain inline chart and separate chart entry (#577) |
| 504 | Inline chart: Candlesticks | exact historical region present; per item not verified | Retain inline chart and separate chart entry (#577) |
| 505 | Inline chart: Chart unavailable | exact historical region present; per item not verified | Retain inline chart and separate chart entry (#577) |
| 506 | Rail Quick Look: Watchlist Top 5 title | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 507 | Rail Quick Look: Watchlist symbol | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 508 | Rail Quick Look: Watchlist score | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 509 | Rail Quick Look: Watchlist status dot | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 510 | Rail Quick Look: Open symbol chart | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 511 | Rail Quick Look: Watchlist load error | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 512 | Rail Quick Look: Portfolio positions | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 513 | Rail Quick Look: Portfolio deployed | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 514 | Rail Quick Look: Portfolio open P&L | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 515 | Rail Quick Look: Portfolio winners / count | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 516 | Rail Quick Look: Data Sources title | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 517 | Rail Quick Look: Data source label | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 518 | Rail Quick Look: Data source status / dot | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 519 | Rail Quick Look: Data source detail / provides | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
| 520 | Rail Quick Look: Broker family groupings | changed; revalidation needed; per item not verified | Retain right context rail Quick Look (#584) |
