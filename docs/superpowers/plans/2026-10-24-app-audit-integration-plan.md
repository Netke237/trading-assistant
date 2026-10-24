# Implementation Plan: APP-AUDIT-INTEGRATION (Lane K — Reconcile Audit Coverage and Verify Complete Cross-Mode Journeys)

**Tracking:** board item [#359](https://github.com/Netke237/trading-assistant/issues/359) (phase tracking issue) · parent programme [#348](https://github.com/Netke237/trading-assistant/issues/348)  
**Branch:** `board/app-audit-integration-500fa563`  
**Integrated Source Baseline:** `500fa563da47ea2dcd001b9ac1e87aa8f2c1055f` (PR #551 merged on `origin/main`)  
**Design / Spec:** programme #348 · `docs/agents/board.md`  

---

## 1. Goal & Context

Lane K is the final culmination phase of the whole-application audit programme `APP-AUDIT` (#348). All 10 preceding lanes (Lanes A through J, #349–#358) have completed their independent audits, generated empirical evidence artifacts, cataloged defects, and merged into `main` (with Lane J shipping via PR #551 at `500fa563`).

The goal of Lane K (`APP-AUDIT-INTEGRATION`) is to:
1. **Join and reconcile Lanes A–J audit evidence** against the complete 52,308-row requirement inventory on one pinned integrated SHA (`500fa563`).
2. **Catalog and trace all defects discovered across Lanes A–J**, linking each defect to its discovering lane, severity, remediation status (fixed vs. residual), and tracking issues.
3. **Execute and verify complete end-to-end user journeys** across all screener modes (Options Steps 1–7, Stocks Steps 1–7, Pre-Breakout Step 4 setup scanner with prebreakout/pullback/fib sub-modes), from profile selection and parameter configuration through scan execution, confidence gating, trade/position card inspection, watchlist/basket handoff, paper broker execution stubs, and portfolio/alert updates.
4. **Stress-test cross-mode dynamics and store isolation**, proving that rapid switching between modes does not corrupt shared scan context, that stale out-of-order asynchronous scan responses are safely discarded, and that persistence reloads/restarts preserve state without data loss.
5. **Produce the authoritative Lane K and Programme #348 closure report** with separate, uncompromised verdicts for numbers/persistence and presentation/usability, distinguishing local/offline evidence from real-environment checks, without claiming impossible zero-error perfection.

---

## 2. Strict Scope & Boundaries

- **Files in scope:** Only files under `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/`, this plan (`docs/superpowers/plans/2026-10-24-app-audit-integration-plan.md`), and this phase's record in `docs/superpowers/PROJECT_STATE.json`.
- **Application source code is FROZEN:** Zero edits to `frontend/` (application components, stores, hooks, styles, layouts), zero edits to `backend/` (FastAPI routers, scoring services, models, adapters, configs).
- **Zero package or lockfile modifications:** No changes to `package.json`, `package-lock.json`, or backend requirements.
- **Strictly read-only / isolated execution:** Zero live broker orders, zero real external Telegram/Gmail notification dispatches, zero persistent mutations to shared test databases. All broker execution and data integration tests execute against isolated in-memory stores and deterministic fixtures.

---

## 3. Architecture & Core Deliverables

### 3.1 Provenance & Integrated Baseline (`provenance.json`)
- **Pinned source commit:** `500fa563da47ea2dcd001b9ac1e87aa8f2c1055f`.
- **Environment:** Node (`v20.x`), Next.js (`15.5.23`), React (`19.2.5`), Python (`3.11.9`), Playwright (`1.51.x`), Chromium (`151.0.7922.34`).
- **Cryptographic hashes:** SHA-256 digests of all 10 preceding lane inventory baselines, defect catalogs, and reconciliation outputs.
- **Fixed clock & locale:** `Europe/Berlin`, fixed timestamp for reproducible date-dependent tests.

### 3.2 Cross-Lane Synthesis & Coverage Matrix (`coverage-matrix.json`)
Synthesizes the findings and dispositions of all 10 preceding lanes into a unified matrix across all 52,308 inventory requirements:
- **Lane A (`APP-AUDIT-INVENTORY`):** Central structural inventory baseline (45 route entries, 283 definitions, 2,269 component instances / 20,421 states, 2,900 native instances / 26,100 states, 290 supplemental rows = 52,308 total rows).
- **Lane B (`APP-AUDIT-SETTINGS-PROFILES`):** Scan parameter controls, search profile lifecycle, and configuration save validation.
- **Lane C (`APP-AUDIT-OPTIONS`):** Options scoring rules, contract liquidity/DTE filters, and trade card arithmetic.
- **Lane D (`APP-AUDIT-STOCKS`):** 7 stock strategies, backtest expectancy, and confidence gate validation.
- **Lane E (`APP-AUDIT-PREBREAKOUT`):** Pre-breakout, pullback, and Fibonacci setups, swing levels, and setup backtests.
- **Lane F (`APP-AUDIT-BROKER-PORTFOLIO`):** Broker order payload construction, position sizing, exposure holds, and portfolio booking.
- **Lane G (`APP-AUDIT-MONITORING`):** Watchlist, condition alerts, strategy watch state-machine, and scheduled automation.
- **Lane H (`APP-AUDIT-ANALYTICS-DATA`):** Single-symbol analysis, standalone charts, calendar, and validation exports.
- **Lane I (`APP-AUDIT-PERSISTENCE`):** Cross-store migration, versioned storage envelopes, and reload/restart recovery.
- **Lane J (`APP-AUDIT-PRESENTATION`):** 52,308-row empirical browser presentation reconciliation (4,577 observed-verified, 33,330 observed-asserted, 14,261 observed-ambiguous, 140 not-run), keyboard traversal K1–K6, and triage catalogs.

### 3.3 Integrated Defect Registry (`integrated-defects.json`)
Unified catalog of all defects discovered throughout the programme:
- Merges Lane B (18 defects), Lane C (5 defects), Lane D (2 defects), Lane E (3 defects), Lane F (3 defects), Lane G (3 defects), Lane I (4 defects), Lane J (6 defects J-001..J-006), and any cross-mode integration defects identified in Lane K.
- Each defect record contains:
  - `defect_id`: Unique identifier (e.g. `K-NNN`, `J-NNN`, `B-NNN`).
  - `originating_lane`: Lane A–J or K.
  - `title`: Plain-text defect summary.
  - `severity`: `blocks-use` | `misleading` | `degraded` | `cosmetic`.
  - `status`: `resolved` (shipped on main via linked PR) | `residual` (open board item / tracked follow-up).
  - `remediation_reference`: PR number or follow-up issue number.
  - `verification`: Exact automated check verifying the defect or its guard.

### 3.4 Cross-Mode End-to-End Journey Verification Suite (`harness/journey.cjs`)
Implements automated cross-mode journey execution using in-memory state models and deterministic fixtures:
- **Journey 1: Options Mode (Steps 1–7)**
  - Select regime Bullish/Bearish -> Step 2 SP500/NDX100 -> Step 3 direction Bullish, Swing horizon -> Step 4 ranking table candidates -> Step 5 IV rank & event proximity filter -> Step 6 contract selection -> Step 7 trade card inspection -> add to basket / watchlist -> submit paper broker order stub -> verify portfolio position and alert emission.
- **Journey 2: Stocks Mode (Steps 1–7)**
  - Regime check -> Universe selection -> Direction Bullish, Position horizon -> Step 4 stock scan candidates -> Step 5 strategy picker (verifying all 7 strategies: `pullback_ema`, `breakout_base`, `ma_crossover`, `mean_reversion_rsi`, `mean_reversion_bb`, `mean_reversion_vwap`, `mean_reversion_multi`) -> Step 6 backtest metrics & confidence gate evaluation -> Step 7 position card preview -> broker order stub.
- **Journey 3: Pre-Breakout / Setup Mode (Step 4 Sub-modes)**
  - Regime check -> Direction Bullish -> Step 4 setup scanner sub-toggle across `prebreakout`, `pullback`, and `fib` -> verify ATR/volume/retracement metrics -> inline WatchStar and CompositeAlertDialog triggers -> standalone chart workspace deep-dive handoff.
- **Journey 4: Cross-Store Concurrency, Mode Switching & Stale Async Isolation**
  - Rapid mode switching between Options, Stocks, and Pre-Breakout verifying that `screenerMode` switches cleanly without cross-contaminating strategy params in `scanParamsStore` or filter constraints in `scanStore`.
  - Stale async race test: simulate long-running Options scan response returning AFTER the user has navigated to Stocks mode; verify the response is ignored and does not overwrite current Stocks candidates.
  - Persistence reload test: verify localStorage state rehydration across stores (`theme`, `settings`, `watchlist`, `portfolio`, `risk`, `alerts`, `drawings`) preserves data integrity without throwing parse errors or losing keys.

### 3.5 Integration Reconciliation & Final Programme Report (`harness/integrate.cjs`)
- Validates the complete 52,308-row inventory against both domain (Lanes B–I) and presentation (Lane J) coverage.
- Generates `reconciliation.json` with multi-dimensional dispositions (`presentation_disposition`, `domain_coverage`, `integrated_verdict`).
- Produces `report.md` (with exact pattern `APP-AUDIT-INTEGRATION`) and `README.md`:
  - **Verdict 1 (Numeric & Persistence Gate):** Pass/Fail on zero money-loss, zero wrong-order calculation, zero data corruption.
  - **Verdict 2 (Presentation & Usability Gate):** Complete 52,308-row breakdown, accessibility/keyboard compliance, and residual UI defects.
  - **Verdict 3 (Operational Reality & Dependencies):** Explicit statement of offline mock verification vs. real local broker/market checks (e.g. mini-PC US market hours checks), avoiding any claim that all defects are eliminated.

---

## 4. Build Units & Execution Structure

### Unit 1: Cross-Lane Synthesis, Provenance & Integrated Defect Registry (T1)
- **Goal:** Synthesize baseline data, provenance, coverage matrix, and unified defect registry across all 10 preceding lanes.
- **Files:**
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/provenance.json`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/coverage-matrix.json`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/integrated-defects.json`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/harness/test/synthesis.test.cjs`
- **Tests first:** Assert schema conformity, presence of all 10 lanes, accurate defect counts (44+), and baseline hash integrity.

### Unit 2: Cross-Mode End-to-End Journey Verification Suite (T2)
- **Goal:** Implement the cross-mode journey test runner verifying all 4 journeys, mode-switching concurrency, stale-async rejection, and persistence reload integrity.
- **Files:**
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/harness/journey.cjs`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/harness/test/journey.test.cjs`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/evidence/journeys/` (JSON execution traces for Journeys 1–4)
- **Tests first:** Verify Journeys 1–4 execute deterministically, validate state transitions, enforce stale-async response discard, and verify persistence serialization.

### Unit 3: Integration Reconciliation Runner, Final Report & Documentation (T3)
- **Goal:** Implement the integration reconciliation runner, execute coverage validation against inventory, and generate the final comprehensive Lane K / Programme #348 report.
- **Files:**
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/harness/integrate.cjs`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/harness/test/integrate.test.cjs`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/reconciliation.json`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/report.md`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-INTEGRATION/README.md`
- **Tests first:** Verify reconciliation runner computes all 52,308 rows, matches input hashes, checks presence probe `APP-AUDIT-INTEGRATION`, and verifies documentation files.

---

## 5. Audit and Shipping Gate

- **Plan Audit Gate:** Fresh independent subagent applying `bmad-review-adversarial-general` against this plan and the repository code/tooling it references.
  - Strict gate criteria: Report correctness (wrong coverage number/verdict, crediting unobserved rows, reporting asserted as verified, claiming unrun checks, misstating defect counts/statuses) or exposure of paths modifying application source / persisted data.
  - Capped at 3 rounds per stage.
- **Code Audit Gate:** After Unit 3 completion and `origin/main` merge, fresh independent subagent reviews diff `origin/main..HEAD` against this plan.
  - Same strict gate criteria, capped at 3 rounds.
- **Self-Merge Execution:** Upon clean code audit, verify all 5 conditions of `board.md` step 7:
  1. We hold active claim `APP-AUDIT-INTEGRATION`.
  2. `audit_clean: true` recorded in `PROJECT_STATE.json`.
  3. PR head unchanged since clean audit except documentation-only commits.
  4. Green CI on exact head commit (0 applicable checks, no failures).
  5. `SELF-MERGE PENDING, PR #<pr>, audited head <sha>` recorded first in `PROJECT_STATE.json`.
  Merge PR #<pr>, close #359 and programme #348, post board notifications, release claim, open follow-up state reconciliation PR.
