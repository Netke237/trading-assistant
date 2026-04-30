
# PRD-02 Master Phased PRD — Options Screener and Recommendation Assistant

**Version**: v0.3  
**Status**: Spec-refined draft for implementation review  
**Scope stance**: Workflow-first PRD built around the validated user workflow, with additions that strengthen execution quality, trade-planning completeness, and testability without changing workflow sequence or intent. This version adds entry-pricing, sell-to-close planning, and projected reward-risk assessment inside existing workflow stages rather than introducing new stages.perforce+2

## Product overview

**Product type**: Local-first web application for a discretionary swing options trader, with future extension to cloud deployment and alternative clients.  
**Primary user**: One DIY trader with high technical affinity, limited time, a full-time job, and family responsibilities.  
**Trading style**: Direction-aware swing trading with bullish and bearish analysis paths, while MVP trade recommendation remains long-calls-only.  
**Primary problem**: Reduce time spent on stock scanning, option-chain review, trade planning, entry pricing, and exit planning while preserving user control, explainability, and manual approval.

## Product goals

**FR-01**: Preserve the workflow as the core operating model and map all product features to that workflow without changing it.  
**FR-02**: Help the user scan a universe, review ranked stocks, validate setup quality, evaluate option contracts, and generate trade cards with explainable recommendations.  
**FR-03**: Keep stock evaluation separate from contract evaluation through distinct score cards and confidence measures.  
**FR-04**: Support defaults in settings, execution-time overrides, and tolerance logic where applicable.  
**FR-05**: Support direction-aware analysis, analysis horizon selection, watchlist and portfolio monitoring, and event visibility through calendar features.

**Acceptance criteria for FR-01 to FR-05**:

- The workflow appears in the product exactly as defined in this PRD, with no removed step and no reordered step.
    
- The user can move from scan initiation to stock review, contract review, and trade-card generation through one coherent dashboard flow.
    
- Stock-side and contract-side outputs are visibly separated in the UI and in exported outputs.
    
- Default values are editable in settings and may be overridden during execution without automatically rewriting saved defaults.
    
- The application provides event visibility for watchlist and portfolio symbols through calendar and alert mechanisms.
    

## Target user

Busy discretionary swing trader with limited screen time, strong business and technical affinity, and preference for pragmatic, explainable workflows over black-box automation.  
Uses long calls most often and wants the architecture to support bearish analysis as a parallel path later.  
Wants a repeatable process that can later be automated, but still wants final approval before action.

## Product boundaries

**MVP delivery shape**: Local web app using FastAPI backend and React/Next.js frontend, intended to run locally first on Windows.  
**In MVP**: Bullish and bearish analysis modes, analysis horizon, on-demand and continuous scans, Heston in MVP, stock ranking, long-call contract recommendation, entry-quality assessment, trade cards, projected reward-risk assessment, watchlist, portfolio, alerts, and calendar visibility for watchlist and portfolio symbols.optionalpha+1  
**Not in MVP**: Bearish contract recommendation, long puts, short calls, direct broker execution, broker-native automated exits, mobile-native app, and advanced multi-channel notification orchestration.[youtube](https://www.youtube.com/watch?v=rEilQfkxCas)

## Product principles

The workflow is the core and may be enhanced or specified but not changed.  
The planner has final approval before execution.  
Defaults live in settings. Execution-time overrides are allowed. Defaults change only when explicitly saved.  
Tolerance may be applied where meaningful, especially on score and threshold boundaries.  
Explainability is mandatory at stock, contract, entry, exit, and final recommendation levels.  
No contract recommendation is actionable unless both trade selection quality and execution quality are acceptable.optionalpha+1

## Core workflow

**FR-06**: Create or load a universe → Select direction mode → Select analysis horizon → Validate market regime → Validate stock setup → Validate volatility and event context → Validate option contract → Create trade card → Human approval → Monitor and manage with alerts.

This workflow is the operational backbone of the product and must remain unchanged. Product features, screens, exports, scoring, entry rules, exit rules, and alerts shall be attached to these steps rather than replacing them.

**Acceptance criteria for FR-06**:

- Every workflow step is represented by at least one visible product function or screen state.
    
- No implementation feature may bypass stock validation and jump directly to contract recommendation.
    
- Human approval is always required before a recommendation is considered actionable in MVP.
    
- Monitoring and management functions continue after approval through watchlist, portfolio, alerts, and calendar visibility.
    

## Workflow outputs by stage

## Create or load a universe

**FR-07**: Support universe creation from presets, manual symbols, CSV upload, and mixed sources.  
Universe membership remains independent from ranking logic.

**Acceptance criteria for FR-07**:

- User can build a universe from preset lists, manual entry, CSV import, or a mixture.
    
- Universe can be reused across scans.
    

## Select direction mode

**FR-08**: Support bullish mode and bearish mode as independent analysis paths that can run separately or simultaneously.  
MVP trade recommendation remains long-calls-only even when bearish analysis is enabled.

**Acceptance criteria for FR-08**:

- User can enable bullish only, bearish only, or both.
    
- All ranked stocks, detail views, and alerts carry direction tags.
    
- Bearish analysis in MVP does not produce bearish contract recommendations.
    

## Select analysis horizon

**FR-09**: Require explicit selection of analysis horizon before trend validation so trend can be interpreted in the correct timeframe context.  
Higher timeframe context, trading timeframe setup, and lower timeframe trigger timing must remain logically separable.

**Acceptance criteria for FR-09**:

- User must choose an analysis horizon before running full setup validation.
    
- Conflicting trend readings across horizons can be represented as caution instead of forced rejection.
    

## Validate market regime

**FR-10**: Validate whether the broader market regime supports the selected direction mode before promoting new trade candidates.

**Acceptance criteria for FR-10**:

- Market regime result is shown as Pass, Caution, or Reject.
    
- Direction mode is considered in regime interpretation.
    

## Validate stock setup

**FR-11**: Validate stock setup quality using explicit rules for stock trend, pullback, reversal trigger, conflict handling, and supporting criteria.  
Stock validation results shall produce a stock score card and a stock confidence index separate from contract evaluation.

**Acceptance criteria for FR-11**:

- Every ranked stock shows tabular validation for trend rule, pullback rule, reversal trigger rule, status, and confidence contribution.
    
- The stock validation table exists for all ranked stocks, supports pagination, and is downloadable in Excel format.
    
- The ranked stock list is produced after stock ranking and before option-contract evaluation.
    
- The ranked stock list includes rank, stock score, stock confidence index, status label, reject reasons where applicable, and change from previous run.
    

## Ranked stock review output

**FR-12**: After stock scan completion, produce a ranked and paginated stock table from most relevant to least relevant, including accepted, caution, and rejected stocks.  
This is the concrete product output of the workflow stage “Validate stock setup” before option-contract evaluation proceeds.

**Required table fields**:

- Symbol
    
- Direction mode
    
- Analysis horizon
    
- Rank
    
- Rank change versus previous run
    
- Stock score
    
- Score change versus previous run
    
- Rule-status changes versus previous run, such as Trend Pass → Caution
    
- Stock confidence index
    
- Pass / Caution / Reject status
    
- Reject or caution reasons
    
- Key rule summaries for trend, pullback, reversal trigger, event context, and volatility context.
    

**Acceptance criteria for FR-12**:

- Table is paginated when results exceed page size.
    
- Table includes rejected names and their reasons.
    
- Table is downloadable as Excel.
    
- Previous-run deltas include rank change, score change, and changed rule status.
    

## Validate volatility and event context

**FR-13**: Validate volatility pricing context and event context before contract recommendation proceeds.  
For MVP, volatility suitability is scoped to long-call buying logic.

**Acceptance criteria for FR-13**:

- Volatility and event context results are visible in stock-side detail outputs.
    
- Earnings proximity can downgrade or reject a candidate according to configured rules.
    
- Default volatility criteria live in settings and can be overridden during execution.
    
- Event proximity rules may require forced review, downgrade, or rejection if the planned hold window overlaps a configured event-risk boundary.etrade+1
    

## Validate option contract

**FR-14**: Evaluate long-call contracts only for eligible bullish stock candidates in MVP using explicit hard-reject, soft-rank, tolerance, shortlist, and entry-quality logic.  
Contract validation must produce a contract score card and contract confidence value distinct from the stock score card.  
Contract validation shall also determine whether the contract is execution-feasible at a reasonable entry price, not merely structurally valid.optionalpha+2

**Acceptance criteria for FR-14**:

- Contract evaluation begins only after stock review stage is completed.
    
- Contract outputs show DTE fit, delta fit, IV attractiveness, spread quality, liquidity, pricing model indicator, contract confidence, and entry-quality status.
    
- Rejected contracts show reject reasons.
    
- Exactly one best contract is returned per eligible stock, with optional alternatives if configured.
    
- A contract may be structurally valid yet still be marked non-actionable if entry-quality conditions fail.tradingblock+1
    

## Create trade card

**FR-15**: Generate a trade card for each actionable contract recommendation, containing entry, risk, invalidation, target, exit, and sell-to-close planning information.  
The trade card is not complete unless it contains both a buy-side plan and a sell-side plan.fidelity+2

**Acceptance criteria for FR-15**:

- Trade card includes symbol, direction, analysis horizon, contract details, stock confidence, contract confidence, final recommendation status, entry plan, position size, invalidation, profit targets, stop, and time stop.
    
- Trade card includes recommended buy limit, maximum acceptable fill, stock invalidation trigger, premium stop, time-stop window, target stock prices, estimated option sale prices at targets, and reward-risk result.
    
- Trade card is explainable and editable before approval.
    
- Trade card must state whether estimated exit prices are model-based or approximation-based.optionalpha+1
    

## Human approval

**FR-16**: User approval is mandatory before a recommendation becomes an actionable planned trade in MVP.

**Acceptance criteria for FR-16**:

- No trade transitions into portfolio state without explicit user approval.
    
- Approved trades may move to watchlist or portfolio according to user action.
    
- Approval view exposes buy logic, sell logic, and reward-risk result together so the user approves a full trade plan rather than only a contract pick.perforce+1
    

## Monitor and manage with alerts

**FR-17**: After approval or watchlisting, the system supports ongoing monitoring through alerts, portfolio/watchlist views, and calendar visibility.

**Acceptance criteria for FR-17**:

- Watchlist tracks stocks the user wants to monitor after analysis.
    
- Portfolio tracks positions already opened.
    
- Alerts and calendar surfaces upcoming risk and management events for watchlist and portfolio symbols.
    
- Monitoring supports alerting on invalidation, target progress, premium-stop thresholds, time stops, and event-risk windows tied to approved trade cards.quantifiedstrategies+2
    

## Direction and strategy framework

## Direction metrics

**FR-18**: The PRD shall define explicit metrics for bullish, bearish, and neutral/mixed classification so direction is objective and horizon-aware rather than inferred ad hoc.

**Example metric families**:

- price relative to long-term moving average
    
- moving-average slope
    
- short/medium moving-average alignment
    
- swing-high / swing-low structure
    
- optional momentum confirmation.
    

**Acceptance criteria for FR-18**:

- Direction classification can be evaluated independently for each selected analysis horizon.
    
- Direction result supports Bullish / Bearish / Neutral-Mixed states.
    
- Cross-horizon disagreement can be surfaced as Caution rather than silently hidden.
    

## Strategy and rule catalog

**FR-19**: The product shall maintain a strategy/rule catalog that maps named setup families to the workflow rule families rather than replacing the workflow.

**Examples of setup families**:

- pullback continuation
    
- breakout continuation
    
- relative strength / momentum continuation
    
- support/resistance retest
    
- higher-low pullback continuation
    
- divergence-style enrichments where data supports them.
    

**Acceptance criteria for FR-19**:

- Each named setup family maps to one or more workflow validation rules.
    
- Setup families can be enabled, disabled, and weighted via settings and execution-time overrides.
    

## Strategy weighting

**FR-20**: Default weights are stored in settings. User can override weights during a scan. Weighting supports strategy-family defaults first, with strategy-level overrides where implemented.

**Acceptance criteria for FR-20**:

- Weight defaults are editable in settings.
    
- Weights may be overridden during scan execution.
    
- Weighting contributes to the stock score card and stock confidence index.
    

## Conflict logic

**FR-21**: If selected strategies or rule groups produce materially mixed evidence on the same symbol, mark the symbol as Review Manually / Caution and suppress automatic alerts until manually approved.

**Acceptance criteria for FR-21**:

- Conflicted symbols remain visible in ranked outputs.
    
- Conflicted symbols are clearly labeled in the UI and exports.
    
- No automatic alert is sent for conflicted symbols unless explicitly permitted by settings.
    

## Data availability and validation rules

**FR-22**: Missing-data behavior must distinguish between mandatory inputs and optional enrichments so the system does not overrate symbols with incomplete information.

**Rules**:

- If a selected mandatory strategy input is missing, that strategy is invalid for the symbol.
    
- If optional enrichment is missing, apply a penalty or omit only the affected sub-score.
    
- If option-specific required data is missing, stock ranking may still complete even when contract recommendation cannot.
    
- If target-repricing inputs are unavailable, the system may still produce a trade card only if it clearly labels reward-risk estimates as reduced-confidence approximations.slite+1
    

**Acceptance criteria for FR-22**:

- Missing mandatory data is visible in the detail view and exports.
    
- Missing optional data does not crash ranking logic.
    
- Symbols are not silently advantaged by missing enrichment data.
    
- Reduced-confidence target pricing and reward-risk approximations are explicitly labeled when used.slite+1
    

## Option eligibility and shortlist logic

**FR-23**: Contract evaluation uses a two-stage eligibility model aligned to the workflow: rank stocks first, then evaluate long-call contracts only for the shortlisted eligible symbols.

**Stage 1**: Produce ranked stocks after stock validation.  
**Stage 2**: Evaluate contracts only for eligible bullish symbols that survive shortlist rules.

**Shortlist controls**:

- minimum valid stocks
    
- maximum shortlisted stocks
    
- optional alternatives count.
    

**Acceptance criteria for FR-23**:

- Stage 2 skips if valid stocks are below the configured minimum threshold.
    
- Maximum shortlisted stocks setting is enforced.
    
- Below-minimum warning is shown in UI.
    

## Contract validation details

## Hard reject rules

**FR-24**: Contracts are rejected if structurally unusable or execution quality is unacceptable.

**Typical hard reject conditions**:

- missing strike
    
- missing expiration date
    
- missing bid or ask
    
- ask price less than or equal to zero
    
- negative bid
    
- spread cannot be calculated
    
- contract type missing or not CALL for MVP
    
- DTE outside absolute allowed system range
    
- open interest equals zero
    
- spread exceeds hard reject threshold under configured spread methodology
    
- no acceptable entry price can be determined under configured entry logic.optionalpha+2
    

**Acceptance criteria for FR-24**:

- Any hard-reject condition blocks contract recommendation.
    
- Reject reason is shown in detail output.
    
- Spread rejection methodology is defined in settings and visible in detail output.tradingblock+1
    

## Soft-rank rules

**FR-25**: Contracts that are usable but imperfect remain eligible and are penalized or down-ranked.

**Typical soft-rank conditions**:

- open interest below preferred threshold but above zero
    
- daily volume below preferred threshold
    
- spread above preferred threshold but below reject threshold
    
- delta slightly outside preferred band
    
- DTE outside preferred band but still inside allowed range
    
- IV rank outside preferred range
    
- estimated slippage degrades projected reward-risk without fully invalidating the trade.optionalpha+1
    

**Aggregate unusable rule**: Reject a contract if the configured number of soft failures is exceeded, especially when spread or liquidity failures are involved.

**Acceptance criteria for FR-25**:

- Soft failures reduce contract score and contract confidence.
    
- Aggregate soft-failure rejection is configurable in settings.
    
- Entry-quality downgrade reasons are visible alongside contract reasons.optionalpha+1
    

## Liquidity and tolerance

**FR-26**: Liquidity thresholds and tolerance logic shall be configurable and visible.

**Examples**:

- minimum open interest
    
- minimum daily option volume
    
- preferred spread
    
- hard reject spread threshold
    
- tolerance on open interest, volume, delta, DTE band, and IV band
    
- configurable spread methodology, such as spread as percentage of mid-price, ask price, or estimated entry premium.menthorq+1
    

**Acceptance criteria for FR-26**:

- Tolerance applies only where meaningful and not to structurally broken fields such as missing bid/ask or missing expiry.
    
- Effective thresholds after tolerance are explainable in detail views.
    
- Spread methodology is configurable and visible in settings and detail output.menthorq+1
    

## Contract scoring

**FR-27**: The application shall maintain an explicit default contract-scoring model whose values remain editable in settings.

**Example component groups**:

- stock setup contribution
    
- liquidity score
    
- IV attractiveness
    
- theta burden
    
- delta fit
    
- expiry fit
    
- spread quality
    
- pricing-model adjustment
    
- entry-quality adjustment.tradingblock+1
    

**Acceptance criteria for FR-27**:

- Contract score components and weights are visible to the user.
    
- Contract confidence is derived from the scored and penalized contract result.
    
- Entry-quality contribution, if used, is visible and explainable.perforce+1
    

## Recommendation output

**FR-28**: For each eligible stock, return one best contract and, if enabled, up to N alternatives, along with reason strings, score cards, confidence, pricing-model indicator, and entry guidance.

**Acceptance criteria for FR-28**:

- Exactly one best contract is returned per eligible stock.
    
- Optional alternatives do not exceed configured limit.
    
- If no contract passes filters, the UI shows No eligible contracts with reasons.
    
- Recommendation output includes recommended order type, recommended entry limit, maximum acceptable fill, and entry-quality label.optionalpha+2
    

## Validation rules and scoring model

Validation rules are concrete rules tied to workflow stages, and their defaults are maintained in settings and may be overridden during execution.  
Where applicable, a tolerance criterion may be configured so a near-threshold result can still qualify, for example a 2% tolerance around a score or threshold boundary.

## Stock setup validation table

**FR-29**: Stock trend rule, pullback rule, and reversal trigger rule shall be documented in tabular form with rule result, supporting metrics, and confidence contribution.

|Rule family|Purpose|Output|Confidence role|
|---|---|---|---|
|Stock trend rule|Determine whether the stock trend supports the selected direction and horizon|Pass / Caution / Reject + metrics|Contributes to stock confidence index|
|Pullback rule|Determine whether price is in a valid continuation pullback or rebound structure|Pass / Caution / Reject + metrics|Contributes to stock confidence index|
|Reversal trigger rule|Determine whether the pullback/rebound is showing actionable continuation evidence|Pass / Caution / Reject + metrics|Contributes to stock confidence index|
|Event context rule|Determine whether a near event changes eligibility|Pass / Caution / Reject + event data|May penalize stock confidence|
|Volatility context rule|Determine whether premium context is acceptable for long-call buying|Pass / Caution / Reject + IV metrics|May penalize stock confidence|

**Acceptance criteria for FR-29**:

- The table appears for every ranked stock.
    
- The table is available in paginated views and exports.
    
- Each rule result contributes to the stock confidence index according to configured weighting.
    

## Three-layer scoring model

**FR-30**: The application shall use a three-layer scoring model to preserve explainability and prevent mixing stock and contract reasoning.

## 1. Stock score card

Shows stock-side reasoning only:

- trend rule result
    
- pullback rule result
    
- reversal trigger rule result
    
- event context
    
- volatility context at stock selection stage
    
- stock score
    
- stock confidence index.
    

## 2. Contract score card

Shows option-side reasoning only:

- DTE fit
    
- delta fit
    
- IV attractiveness
    
- liquidity
    
- spread quality
    
- pricing model indicator
    
- contract score
    
- contract confidence
    
- entry-quality status.
    

## 3. Final recommendation status

Combines stock and contract results into the final decision label used for trade cards, prioritization, and alerting.

**Acceptance criteria for FR-30**:

- Stock and contract scores are displayed separately.
    
- Final recommendation status is displayed separately from both score cards.
    
- Score-card components and weights are visible and explainable to the user.
    
- Entry-quality status is displayed separately from final recommendation status when needed.optionalpha+1
    

## Entry quality and execution pricing

**FR-39**: The system shall evaluate execution quality for each recommended contract and provide a recommended buy limit, maximum acceptable fill, and entry-quality status before a trade card is marked actionable.optionalpha+2

**Acceptance criteria for FR-39**:

- Recommendation includes default order type and recommended limit price.
    
- Entry price target defaults to the configured fill methodology, such as mid-price or slightly better.
    
- Spread-relative-to-premium threshold is configurable and visible.
    
- A contract may be structurally valid yet marked Skip due to poor execution quality.
    
- Entry-quality reason strings are shown in detail view and trade card.optionalpha+2
    

## Exit and sell-to-close planning

**FR-40**: The system shall generate a defined sell-to-close plan for each trade card, including invalidation exit, premium stop, profit targets, and time stop.etrade+2

**Acceptance criteria for FR-40**:

- Trade card includes stock invalidation, premium stop, and time stop.
    
- Trade card includes at least one profit target and optional scale-out logic if enabled.
    
- Exit conditions are alertable after approval.
    
- User can edit exit plan before approval without rewriting global defaults.
    
- Exit condition labels distinguish stock invalidation, premium stop, time stop, and target-hit logic.fidelity+2
    

## Projected reward-risk assessment

**FR-41**: The system shall estimate projected contract reward-risk before approval by mapping stock risk and stock targets to option-level gain/loss estimates.optionseducation+2

**Acceptance criteria for FR-41**:

- Risk is defined first from the underlying invalidation level.
    
- At least one target stock price is required for projected reward calculation.
    
- Trade card shows projected reward-risk ratio and pass/fail against configurable minimum.
    
- Estimated option values at targets are labeled as repricing-model-based or approximation-based.
    
- If reduced-confidence approximation is used, that confidence reduction is visible in the trade card.tastylive+2
    

## Settings and overrides

**FR-31**: All configurable criteria, weights, limits, tolerances, and alert thresholds must be stored in settings with defaults and may be overridden during execution.

**Examples of configurable items**:

- direction-mode defaults
    
- analysis horizon defaults
    
- stock-rule thresholds
    
- contract-rule thresholds
    
- confidence thresholds
    
- tolerance percentages
    
- scan cadence
    
- pagination size
    
- export defaults
    
- alert thresholds and deduplication windows
    
- entry fill methodology
    
- spread methodology
    
- premium-stop defaults
    
- time-stop defaults
    
- minimum reward-risk threshold
    
- target-pricing methodology.perforce+1
    

**Acceptance criteria for FR-31**:

- Defaults are editable in settings.
    
- Execution-time overrides do not overwrite saved defaults unless explicitly saved.
    
- Tolerance can be configured where applicable, including score thresholds and preferred ranges.
    
- Entry, exit, and reward-risk defaults follow the same override/save behavior as other settings.slite+1
    

## Scan modes, states, and cadence

**FR-32**: Support both on-demand scans and continuous scans in MVP.

**Acceptance criteria for FR-32**:

- User can launch on-demand scans.
    
- User can enable continuous scan mode with configurable cadence.
    
- Scan outputs record timestamp and enable comparison with previous run.
    

**FR-33**: The application shall expose explicit scan states for transparency and troubleshooting.

**States**:  
Idle → Scanning → Partial → Completed → Failed → Cancelled.

**Acceptance criteria for FR-33**:

- UI shows current scan state.
    
- Errors and partial-completion states are visible to the user.
    

## Watchlist, portfolio, dashboard, charts, and calendar

**FR-34**: The default dashboard landing view shall prioritize watchlist and portfolio, while scan and recommendation panels remain accessible as secondary areas.

**Definitions**:

- Watchlist = stocks under observation after analysis.
    
- Portfolio = positions with contracts already bought.
    

**Acceptance criteria for FR-34**:

- Dashboard default view shows watchlist and portfolio first.
    
- Watchlist and portfolio are visibly distinct entities in the UI.
    
- Ranked scan results remain accessible without displacing the default dashboard priority.
    

**FR-35**: The detail view shall show chart, signals, score cards, option-chain results, recommendation, trade plan, and event visibility.

**MVP chart set**:

- candlestick
    
- volume
    
- RSI
    
- MACD.
    

**Acceptance criteria for FR-35**:

- Stock selection updates the detail view and related chart context.
    
- Detail page shows score, signals, contract, plan, and events in one navigable view.
    
- Detail page shows entry plan, exit plan, and reward-risk result together in the trade-planning area.fidelity+1
    

**FR-36**: Provide calendar visibility focused by default on upcoming events affecting watchlist and portfolio symbols.

**Event examples**:

- earnings
    
- option expiration
    
- user review date
    
- alert revalidation date
    
- ex-dividend when available.
    

**Acceptance criteria for FR-36**:

- Calendar shows watchlist and portfolio events by default.
    
- Default calendar view may show monthly visibility with drilldown behavior for nearer-term review.
    
- Missing event data is labeled rather than hidden.

## Risk management and portfolio controls

**FR-42**: The application shall include portfolio and risk controls even though trading is discretionary.

- The system SHALL enforce maximum approved exposure per trade and maximum total portfolio exposure.
- The system SHALL enforce a maximum concurrent approved trade count and a maximum daily trade recommendation count.
- Every recommended trade card SHALL include an explicit invalidation level and a capital-at-risk estimate.
- The system SHALL apply correlation and event-risk checks before adding a recommendation to the portfolio watchlist.
- Risk rules SHALL operate independently of scoring confidence and may veto a recommendation from becoming approved.

**Acceptance criteria for FR-42**:

- The portfolio manager rejects or flags recommendations that exceed configured exposure limits.
- Approved trades show an explicit invalidation level, estimated risk, and position sizing rationale.
- Correlated-symbol risk is visible in the recommendation summary and may reduce position size.
- The system prevents approval of any trade without a defined invalidation stop or invalidation trigger.
- Portfolio-level risk state is visible in the dashboard and reflected in monitoring alerts.

## Monitoring, alerting, and observability

**FR-43**: The application shall provide observability and alerting for scan results, approvals, portfolio risk, and event risk.

- The system SHALL maintain structured logs for recommendations, approvals, alerts, and portfolio state.
- Alerts SHALL support at least: new candidate ready, contract reject reason, trade-card approval, invalidation approaching, event-risk warning, and portfolio drawdown warning.
- The dashboard SHALL display watchlist status, approved portfolio positions, unrealised P&L, risk status, and recent alerts.
- Alert delivery SHALL support rate limiting, with configurable deduplication windows.
- The system SHALL keep audit-friendly records of every decision with a unique recommendation or trade ID.

**Acceptance criteria for FR-43**:

- Structured logs are generated for recommendation decisions, portfolio changes, and alerts.
- Dashboard views include portfolio exposures, risk status, and watchlist alerts.
- Alerts are limited to one per event type per configured window.
- Each recommendation can be traced end-to-end from scan rule to final approval or rejection.
- Event-risk alerts are triggered for earnings, expirations, and user-configured review dates.

## Testing and validation requirements

**FR-44**: The application shall define and pass a core test suite for workflow correctness, reproducibility, and data integrity.

- The system SHALL include unit tests for stock ranking, contract validation, scorecard generation, and trade-card creation.
- The system SHALL include integration tests for the full scan-to-recommendation pipeline in dry-run mode.
- The system SHALL include tests for data-leakage and look-ahead bias in scoring inputs.
- The system SHALL include reproducibility tests for the same input data and settings.
- The system SHALL include tests for portfolio rules and risk-limit enforcement.

**Acceptance criteria for FR-44**:

- Dry-run pipeline tests complete without broker execution and produce consistent recommendation outputs.
- Data-leakage tests validate that recommendation decisions rely only on available historical data.
- Portfolio and risk rules are covered by tests that assert exposure and invalidation enforcement.
- Re-running the same scan with identical settings produces the same prioritized output.
- Test results and coverage are documented as part of the PRD completion criteria.

## Configuration discipline

**FR-45**: All numeric thresholds, risk limits, time windows, and alert settings SHALL be externalized into configuration.

- The system SHALL store defaults in a settings file and support runtime overrides without silently overwriting saved defaults.
- No business-rule magic numbers SHALL exist in implementation code.
- Settings SHALL cover strategy weights, eligibility thresholds, risk limits, alert deduplication, and calendar/event rules.
- The system SHALL allow the user to persist or reset overrides explicitly.

**Acceptance criteria for FR-45**:

- All rule thresholds appear in a central settings document or file.
- Users can override scan and risk settings at execution time without changing defaults automatically.
- The application clearly documents which settings are live and which are inherited from defaults.
- Any change to a saved default setting is explicit and deliberate.

## Auditability and state recovery

**FR-46**: The application shall preserve portfolio and watchlist state across restarts and provide an auditable decision trail.

- The system SHALL persist approved portfolio state and watchlist state to disk or storage between sessions.
- The system SHALL avoid duplicate approvals or duplicate portfolio entries when recovering from a restart.
- Every decision SHALL include a unique recommendation ID for traceability.
- The system SHALL log audit events for approval, rejection, override, and state restore operations.

**Acceptance criteria for FR-46**:

- Portfolio state is restored after application restart without creating duplicate entries.
- Unique recommendation IDs appear in logs, alerts, and portfolio records.
- The application records state restore events in the audit log.
- The audit trail supports tracing a recommendation from scan input through final portfolio or rejection state.
    

## Alerts

**FR-37**: Alerts are event-driven, direction-aware, and tied to monitoring and management rather than replacing user judgment.

**Example alert types**:

- new candidate passed scan
    
- trade card ready
    
- order approved / moved to portfolio
    
- TP1 hit
    
- stop reached
    
- premium stop threshold reached
    
- time stop approaching
    
- market regime changed
    
- event approaching for watchlist or portfolio symbol.quantifiedstrategies+2
    

**Trigger behavior**:

- interactive scan: no outbound alerts by default
    
- automatic scan: alerts only for configured qualifying results
    
- re-alert logic and deduplication windows are configurable
    
- conflicted symbols do not alert by default.
    

**Acceptance criteria for FR-37**:

- Alert rules respect enabled direction paths.
    
- Duplicate and repeat behavior is configurable in settings.
    
- Alert outputs include short reason strings.
    
- Exit alerts distinguish target-hit, stock invalidation, premium stop, time stop, and event-risk reasons.etrade+2
    

## Modeling and pricing

**FR-38**: Keep Black-Scholes and Heston in MVP, with model usage visible in the UI and in contract outputs.

**Default handling**:

- Black-Scholes may prefilter broad eligibility.
    
- Heston may reprice shortlisted candidates when available.
    
- Pricing models may also estimate option values at configured stock targets and remaining DTE for trade-card planning.
    
- Fallback behavior remains visible if Heston is unavailable.
    
- If target repricing is unavailable, the system may use a lower-confidence approximation path, such as a delta-informed estimate, with clear labeling.optionalpha+3
    

**Acceptance criteria for FR-38**:

- Heston remains part of MVP model handling.
    
- Fallback behavior is visible when one pricing model is unavailable.
    
- Pricing model indicator appears in contract score card and recommendation details.
    
- Trade-card target-price estimates identify whether they are model-repriced or approximation-based.optionseducation+1
    

## Technical and non-functional requirements

**NFR-01 Simplicity**: The application must remain understandable to a non-coder despite advanced scoring and configuration options.  
**NFR-02 Explainability**: Every recommendation detail view must show enough score, rule, model, entry, exit, and reward-risk information for manual review.  
**NFR-03 Resilience**: Missing optional data must not crash scans, exports, dashboard, calendar, pricing workflows, or reward-risk estimation flows.  
**NFR-04 Performance**: Continuous scan mode should preserve usable interface responsiveness while handling paginated ranking output.  
**NFR-05 Exportability**: Ranked stock tables and stock validation tables must be downloadable in Excel format.  
**NFR-06 Local run**: App runs locally on Windows through a documented local startup path.  
**NFR-07 UI availability**: Core features are accessible through the React/Next.js UI.  
**NFR-08 Trade-plan completeness**: A recommendation is not considered approval-ready unless entry, exit, and reward-risk fields are populated or explicitly marked unavailable with reasons.slite+1

## Items intentionally not expanded in this PRD

The following items are acknowledged but intentionally not fully expanded here because they belong in later strategy documents, system architecture, or implementation specs rather than the workflow-centered PRD core:

- full bearish contract recommendation logic using puts or short calls
    
- detailed broker execution flows
    
- broker-native automated exits and order staging
    
- portfolio-level Greeks optimization
    
- advanced notification routing and escalation
    
- full provider-level field mapping and stale-data contracts
    
- implementation-level database schema and API contract details.
    

## Workflow integrity check

The additions in this revision do not change the overall logic. They add precision around existing workflow steps rather than introducing new workflow stages.

|Workflow step|Added PRD precision|Logic impact|
|---|---|---|
|Create or load a universe|No material change|No logic change|
|Select direction mode|No material change|No logic change|
|Select analysis horizon|No material change|No logic change|
|Validate market regime|No material change|No logic change|
|Validate stock setup|No material change|No logic change|
|Validate volatility and event context|Event-risk overlap with planned hold window|Clarifies existing step|
|Validate option contract|Entry-quality rules, spread methodology, execution feasibility|Clarifies existing step|
|Create trade card|Buy limit, max acceptable fill, invalidation, premium stop, time stop, target option sale estimates, reward-risk|Clarifies existing step|
|Human approval|Approval of full trade plan instead of contract pick only|Clarifies existing step|
|Monitor and manage with alerts|Exit-aware alerts and event-aware management|Clarifies existing step|

Conclusion of integrity check: the workflow remains unchanged in sequence and intent; the revision only makes the existing logic more explicit, more execution-aware, and more testable.jamasoftware+2

## Workflow traceability

No aspect of the workflow is lost. Each original workflow step is represented in this PRD as follows:

|Workflow step|Where considered in PRD|
|---|---|

|Workflow step|Where considered in PRD|
|---|---|
|Create or load a universe|FR-07 Universe creation|
|Select direction mode|FR-08 Direction mode, FR-18 Direction metrics|
|Select analysis horizon|FR-09 Analysis horizon|
|Validate market regime|FR-10 Market regime|
|Validate stock setup|FR-11 Stock setup validation, FR-12 Ranked stock review, FR-19 Strategy/rule catalog, FR-20 Weighting, FR-21 Conflict logic, FR-29 Stock validation table|
|Validate volatility and event context|FR-13 Volatility and event context, FR-22 Missing-data handling|
|Validate option contract|FR-14 Contract validation, FR-23 Two-stage eligibility, FR-24 Hard reject rules, FR-25 Soft-rank rules, FR-26 Liquidity and tolerance, FR-27 Contract scoring, FR-28 Recommendation output, FR-39 Entry quality and execution pricing|
|Create trade card|FR-15 Trade card, FR-40 Exit and sell-to-close planning, FR-41 Projected reward-risk assessment|
|Human approval|FR-16 Human approval|
|Monitor and manage with alerts|FR-17 Monitoring, FR-32 Scan modes, FR-33 Scan states, FR-34 Dashboard, FR-35 Detail/charts, FR-36 Calendar, FR-37 Alerts, FR-38 Modeling visibility|
