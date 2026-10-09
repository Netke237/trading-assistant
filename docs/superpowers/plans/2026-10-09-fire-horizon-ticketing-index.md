# Auto-trade Fire Hygiene and Stocks T1–T4 ticketing preparation

Updated: 2026-10-09. Coordinator: codex/ticketing-fire-horizon-20261009.

This index preserves existing ticket ownership and proposes work-package breakdowns. Proposed tasks below are NOT published GitHub tickets or independently audited implementation plans. Repository ticket-orchestration rules override the user skill's child-app-specific rules. One tracking issue/claim/branch/audit target per phase; fresh implementer per ticket and one integrated phase code audit. Three rounds per stage; existing counters and explicit cap decisions are preserved.

## Existing T1 — do not duplicate

Authoritative branch: claude/stocks-horizon-t1. Active claim was verified on 2026-10-09. Tracking issue #92, H0a #93, H1–H10 #94–#103, coordinator #104. Plan: docs/superpowers/plans/2026-10-08-stocks-horizon-t1-plan.md on that branch. Its three-round plan cap and Kenneth's split/exception decisions are recorded there; do not describe the plan as clean or reset counters. HISTORY split has merged separately. Implementation coordination stays with that owner.

## Fire Hygiene

Prepare and independently audit 2026-10-09-autotrade-fire-hygiene-plan.md before cutting build tickets. Focus is the scan-triggered fire cancellation gap, using the existing direct-fire ownership/reporting pattern without introducing retries, duplicate orders, or an automated exit policy. Claim is AUTOTRADE-FIRE-HYGIENE. No application implementation is authorized by this preparation.

## T2 proposed breakdown — pooled validation and adoption

Depends on completed T1 and the real-data STOCKS-HORIZON-TUNING-RUN report. Draft tasks:

1. Reconcile T1 output schema and immutable run/input/cost provenance; specify how each strategy/direction/horizon cell verdict is persisted and invalidated. No verdict derives from default-parameter baseline results.
2. Implement pooled per-cell eligibility using the accepted adoption criteria; retain per-symbol enough-data checks only. Verify exact threshold boundaries and missing evidence. Adoption-bar report also includes fire-rate floor and stress costs; do not change accepted thresholds.
3. Apply Unvalidated labels and demotion to bullish cells without qualifying adopted evidence; refuse auto-arm and opening broker sends at authoritative server boundaries and matching UI paths. Preserve closing orders and research visibility. Reconcile the existing unconditional bearish block with the accepted per-cell re-enablement policy rather than removing it globally.
4. Implement Kenneth's explicit Adopt action with validated provenance and atomic persistence of the exact cell/profile. Specify stale-run, duplicate-action and override handling in the plan before implementation; no automatic adoption.
5. Verify Stocks scan → Backtest → Position consistency, backward-compatible persisted-state behaviour, and then independently audit the whole integrated phase.

Design and acceptance tests must be independently plan-audited before these become tickets. The evidence run remains a separate machine/data operation, not a cloud implementation task.

## T3 proposed breakdown — scorer research

Depends on T2. Draft tasks:

1. Pre-register objective, eligible input set, sampling/de-overlap, costs, train/validation/held-out separation and comparison baseline before any tuning.
2. Build reproducible research machinery for the five-rule scorer without changing live weights or repeatedly inspecting the held-out period.
3. Run research on the historical database, report discrimination and uncertainty by direction/horizon, and retain input hashes and survivorship limitations.
4. Present only the unresolved score-role decision (C4 Q1) against the measured results. Do not reopen previously accepted P0 or adoption decisions.
5. After the decision and a separate audited implementation plan, update scorer configuration/presentation as authorized, verify numeric provenance and audit the integrated phase.

Research choices not yet specified by ADR 0001 must be resolved before implementation tickets. A profitable outcome is not an acceptance requirement that can be guaranteed by code.

## T4 proposed breakdown — Pre-Breakout exits then tuning

The backlog explicitly depends on T1; full execution readiness also depends on an accepted exit design. Do not impose T3 as a hard prerequisite without a new dependency decision. Draft tasks:

1. Map current Pre-Breakout/pullback/fib modes and entry semantics, then decide exit/stop/target/time-exit rules and ambiguous same-bar outcomes in a focused design session.
2. Write and independently audit an implementation plan for those accepted rules and reproducible backtests. No invented exit policy.
3. Implement the accepted exit/backtest semantics with test-first numeric and no-lookahead checks.
4. Integrate the T1 per-horizon tuning machinery and report on the same established cost/held-out/provenance principles; identify any adoption-policy extensions before coding.
5. Run historical evidence locally and independently audit the integrated changes. Any live adoption remains a separate explicit action.

## Publication status

GitHub issue read access was tested with gh api repos/Netke237/trading-assistant/issues on 2026-10-09 and returned Forbidden. Existing T1 issue references are from its tracked branch record, not a fresh API verification. New issue duplicate/assignment checks and publication are blocked. Git HTTPS read/push works; do not request or paste a token into chat. Save review artifacts on this branch; publish official issues only after clean plan audit and restored authorized tracker access.
