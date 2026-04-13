# Product Requirements Document
# HMM Regime-Based Automated Trading System

---

| Field | Value |
|---|---|
| **Product Name** | Regime Trader |
| **Document Version** | 1.0 |
| **Status** | Draft |
| **Audience** | Engineering, QA, Stakeholders |
| **Development Method** | Spec-Driven Development |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Success Metrics](#3-goals--success-metrics)
4. [User Personas](#4-user-personas)
5. [Scope](#5-scope)
6. [Functional Requirements](#6-functional-requirements)
7. [Non-Functional Requirements](#7-non-functional-requirements)
8. [User Stories & Acceptance Criteria](#8-user-stories--acceptance-criteria)
9. [System Architecture Overview](#9-system-architecture-overview)
10. [Data Requirements](#10-data-requirements)
11. [Risk, Compliance & Safety Constraints](#11-risk-compliance--safety-constraints)
12. [Configuration & Environment Requirements](#12-configuration--environment-requirements)
13. [Testing Requirements](#13-testing-requirements)
14. [Out of Scope](#14-out-of-scope)
15. [Dependencies & Assumptions](#15-dependencies--assumptions)
16. [Open Questions](#16-open-questions)
17. [Glossary](#17-glossary)

---

## 1. Executive Summary

**Regime Trader** is a fully automated Python-based equity trading system that uses a Hidden Markov Model (HMM) to classify the current market volatility environment and dynamically adjusts portfolio allocation in response. The system operates as a long-only, volatility-aware strategy: it stays heavily invested in calm market conditions and reduces exposure during turbulent periods, with all trading activity executed via the Alpaca brokerage API.

The system is designed around a single guiding principle: **risk management supersedes signal generation**. The HMM is not a price predictor — it is a volatility classifier. The strategy layer translates volatility classifications into allocation targets, while an independent risk layer has absolute veto power over any trade.

The system is intended for individual systematic traders and quantitative researchers who want a production-grade, backtested, paper-tradeable (and optionally live-tradeable) automated strategy with full observability.

---

## 2. Problem Statement

### 2.1 Context

Retail systematic traders face a recurring set of problems when trying to deploy automated strategies:

- **Look-ahead bias** in backtesting creates false confidence — strategies appear profitable in simulation but fail in live trading because they used future data during testing.
- **Short-selling in high-volatility regimes** consistently destroys returns due to the speed of V-shaped market recoveries.
- **Discretionary drawdown management** is emotionally difficult and inconsistently applied under stress.
- **Lack of observability** — most automated systems run as black boxes with no real-time feedback on what the system is doing and why.
- **Overfitting** — strategies optimised on a single historical period fail to generalise to out-of-sample market conditions.

### 2.2 Core Insight

The worst portfolio drawdowns cluster in high-volatility market spikes. Equities trend upward roughly 70% of the time during low-volatility periods. Therefore, a strategy that simply **reduces allocation when volatility is high and increases it when volatility is low** — without trying to time tops or predict direction — can outperform a buy-and-hold approach on a risk-adjusted basis by avoiding the worst drawdowns.

---

## 3. Goals & Success Metrics

### 3.1 Product Goals

| # | Goal |
|---|---|
| G1 | Provide a backtested, walk-forward validated trading system with statistically meaningful out-of-sample results |
| G2 | Eliminate look-ahead bias entirely through the forward algorithm constraint |
| G3 | Protect capital automatically via independent circuit breakers that operate regardless of HMM state |
| G4 | Enable paper trading by default with a clear, explicit opt-in for live trading |
| G5 | Give the operator full real-time observability of system state, regime, and risk |
| G6 | Produce a system that recovers gracefully from crashes without double-entry or data loss |

### 3.2 Success Metrics (Quantitative)

| Metric | Target |
|---|---|
| Backtest Sharpe Ratio (walk-forward, OOS) | ≥ 1.0 annualised |
| Max drawdown (live paper trading) | ≤ 15% from peak |
| Look-ahead bias test | 100% pass rate — regime at time T must be identical regardless of how much future data is appended |
| Daily drawdown circuit breaker response time | ≤ 1 bar close (~5 minutes) |
| System uptime during market hours | ≥ 99% |
| Alert delivery latency | ≤ 60 seconds from trigger event |
| Regime classification latency per bar | ≤ 500ms |
| Backtest OOS Sharpe vs buy-and-hold | Outperform on risk-adjusted basis (Calmar ratio) |

### 3.3 Definition of Done (per feature)

A feature is considered done when:
- All functional requirements for that feature are implemented
- Corresponding unit and integration tests pass
- Acceptance criteria in Section 8 are verifiable
- No look-ahead bias is introduced (validated by test suite)
- All configuration values are externalised to `settings.yaml`
- Logging output is structured JSON and captures all relevant state

---

## 4. User Personas

### Persona A — The Systematic Retail Trader
- Understands Python and has some familiarity with algorithmic trading concepts
- Wants a strategy that runs unattended during market hours
- Prioritises capital preservation over maximum returns
- Wants to see what the system is doing at any moment via a dashboard
- Will paper trade first before going live

### Persona B — The Quantitative Researcher
- Wants to validate the HMM-based approach against standard benchmarks
- Needs reproducible walk-forward backtesting results
- Will inspect regime breakdown tables and confidence-bucketed performance metrics
- May customise `settings.yaml` parameters and re-run backtests

### Persona C — The Risk-Aware Investor
- Primary concern is downside protection
- Wants circuit breakers and hard stop-loss enforcement
- Needs to understand what happened when a drawdown occurs (audit log)
- Will not tolerate any trade being placed without a stop loss

---

## 5. Scope

### 5.1 In Scope

- HMM-based market volatility regime classification engine
- Volatility-driven portfolio allocation strategy (long-only)
- Independent risk management layer with circuit breakers
- Alpaca API broker integration (paper and live)
- Real-time market data ingestion via WebSocket
- Walk-forward backtesting with out-of-sample validation
- Stress testing (gap risk, regime misclassification)
- Terminal-based live dashboard
- Structured JSON logging with rotating files
- Alerting system (console, log, optional email/webhook)
- CLI for backtest, dry-run, train-only, stress-test, dashboard modes
- Session recovery from `state_snapshot.json`
- Integration test suite including look-ahead bias validation

### 5.2 Out of Scope

See [Section 14](#14-out-of-scope).

---

## 6. Functional Requirements

> Each requirement is tagged with a unique ID for traceability to acceptance criteria and test cases.

---

### FR-01: HMM Regime Detection

| ID | Requirement |
|---|---|
| FR-01.1 | The system SHALL classify the current market into a volatility regime using a Gaussian HMM trained on historical OHLCV data |
| FR-01.2 | The system SHALL automatically select the optimal number of regimes (3–7) using the Bayesian Information Criterion (BIC), choosing the model with the lowest BIC score |
| FR-01.3 | The system SHALL label regimes by mean return (ascending) for human readability: lowest return = CRASH/BEAR, highest = BULL/EUPHORIA |
| FR-01.4 | The system SHALL retrain the HMM model on a configurable schedule (default: if model is >7 days old or missing at startup) |
| FR-01.5 | The system SHALL persist the trained model and its metadata (n_regimes, BIC score, training date, labels) to disk |
| FR-01.6 | The system SHALL require a minimum of 2 years (504 trading days) of daily data to train the HMM |
| FR-01.7 | The system SHALL log all candidate BIC scores and the selected model configuration on every training run |

---

### FR-02: No Look-Ahead Bias (Critical Constraint)

| ID | Requirement |
|---|---|
| FR-02.1 | The system SHALL use ONLY the forward algorithm (filtered inference) for regime prediction at any time T — it SHALL NOT use the Viterbi algorithm (`model.predict()`) in any live or backtest context |
| FR-02.2 | The regime prediction at time T SHALL be identical whether the model is given data `[0:T]` or data `[0:T+N]` for any N > 0 |
| FR-02.3 | The system SHALL include and pass a mandatory look-ahead bias unit test that asserts the above constraint |

---

### FR-03: Feature Engineering

| ID | Requirement |
|---|---|
| FR-03.1 | The system SHALL compute observable features from OHLCV data across six categories: returns, volatility, volume, trend, mean reversion, momentum, and range |
| FR-03.2 | All features SHALL be standardised using rolling z-scores with a 252-period lookback |
| FR-03.3 | Feature computation SHALL be implemented as pure functions with no side effects |

---

### FR-04: Regime Stability

| ID | Requirement |
|---|---|
| FR-04.1 | A regime change SHALL only be "confirmed" after persisting for N consecutive bars (default: 3, configurable) |
| FR-04.2 | During a regime transition (unconfirmed), the system SHALL maintain the previous regime and reduce all position sizes by 25% |
| FR-04.3 | The system SHALL track a flicker rate (number of regime changes per 20-bar window) |
| FR-04.4 | If the flicker rate exceeds a configurable threshold (default: 4), the system SHALL enter uncertainty mode |

---

### FR-05: Volatility-Based Allocation Strategy

| ID | Requirement |
|---|---|
| FR-05.1 | The system SHALL assign each detected regime to one of three strategy classes based on its volatility rank: LowVolBull, MidVolCautious, or HighVolDefensive |
| FR-05.2 | The volatility rank mapping SHALL be independent of regime labels — the "BULL" label does NOT imply low volatility |
| FR-05.3 | The system SHALL ONLY generate LONG or FLAT signals — it SHALL NEVER generate SHORT signals |
| FR-05.4 | **LowVolBull** (lowest volatility third): allocation 95%, leverage 1.25x, stop = max(price − 3 ATR, 50 EMA − 0.5 ATR) |
| FR-05.5 | **MidVolCautious** (middle volatility third): allocation 95% if price > 50 EMA, 60% if price < 50 EMA; leverage 1.0x, stop = 50 EMA − 0.5 ATR |
| FR-05.6 | **HighVolDefensive** (highest volatility third): allocation 60%, leverage 1.0x, stop = 50 EMA − 1.0 ATR |
| FR-05.7 | In uncertainty mode (low confidence or high flicker rate), ALL position sizes SHALL be halved and leverage SHALL be forced to 1.0x |
| FR-05.8 | The system SHALL only rebalance when the target allocation differs from the current allocation by more than 10% |

---

### FR-06: Risk Management

| ID | Requirement |
|---|---|
| FR-06.1 | The risk manager SHALL operate independently of the HMM — circuit breakers SHALL fire based on actual P&L regardless of regime state |
| FR-06.2 | The risk manager SHALL have absolute veto power over any signal — no order SHALL be placed without passing risk validation |
| FR-06.3 | Every order placed by the system SHALL have an associated stop loss — the system SHALL refuse to place any order without one |
| FR-06.4 | Maximum risk per trade SHALL be 1% of total portfolio equity |
| FR-06.5 | Position size SHALL be calculated as: `(portfolio × 0.01) / abs(entry_price − stop_loss)` |
| FR-06.6 | Maximum single position size: 15% of portfolio; maximum total exposure: 80% |
| FR-06.7 | Maximum concurrent open positions: 5; maximum daily trades: 20 |
| FR-06.8 | Maximum correlated sector exposure: 30% |
| FR-06.9 | Correlation check: if rolling 60-day correlation with existing positions > 0.7, reduce new position size 50%; if > 0.85, reject the trade |
| FR-06.10 | Overnight positions SHALL assume a 3x stop gap-through for sizing: overnight size = min(normal, size where 3× gap = 2% of portfolio) |
| FR-06.11 | Maximum portfolio leverage: 1.25x; leverage above 1.0x is ONLY permitted in low-volatility regimes |

---

### FR-07: Circuit Breakers

| ID | Requirement |
|---|---|
| FR-07.1 | Daily drawdown > 2%: reduce all position sizes by 50% for the remainder of the trading day |
| FR-07.2 | Daily drawdown > 3%: close ALL positions and halt trading for the remainder of the day |
| FR-07.3 | Daily drawdown > 5%: reduce all position sizes by 50% for the remainder of the week |
| FR-07.4 | Weekly drawdown > 7%: close ALL positions and halt trading for the remainder of the week |
| FR-07.5 | Peak drawdown > 10%: halt ALL trading and write a `trading_halted.lock` file that requires manual deletion to resume |
| FR-07.6 | Every circuit breaker trigger SHALL be logged with: breaker type, actual drawdown %, equity at trigger, positions closed, and HMM regime at time of trigger |

---

### FR-08: Broker Integration

| ID | Requirement |
|---|---|
| FR-08.1 | The system SHALL integrate with the Alpaca brokerage API using the alpaca-py SDK |
| FR-08.2 | Paper trading mode SHALL be the default; live trading SHALL require explicit CLI confirmation with an acknowledgement prompt |
| FR-08.3 | API credentials SHALL be loaded exclusively from environment variables — never hardcoded |
| FR-08.4 | Order submission SHALL use LIMIT orders by default, priced within ±0.1% of current price, with a 30-second cancellation timeout and optional market retry |
| FR-08.5 | The system SHALL support bracket orders (entry + stop + take-profit via OCO) |
| FR-08.6 | Stop modifications SHALL only tighten stops — widening a stop SHALL be blocked |
| FR-08.7 | The system SHALL detect and block duplicate orders for the same symbol and direction within a 60-second window |
| FR-08.8 | Every trade SHALL carry a unique `trade_id` traceable from signal → risk decision → order → fill |
| FR-08.9 | The system SHALL reconcile tracked positions against actual Alpaca positions on startup |
| FR-08.10 | The system SHALL auto-reconnect to the Alpaca API using exponential backoff after connection failures |

---

### FR-09: Market Data

| ID | Requirement |
|---|---|
| FR-09.1 | The system SHALL subscribe to real-time bar data via WebSocket for all tracked symbols |
| FR-09.2 | The system SHALL fetch historical OHLCV data for feature computation and model training |
| FR-09.3 | The system SHALL subscribe to real-time quote data for bid-ask spread checks before order submission |
| FR-09.4 | The system SHALL handle market gaps (weekends, holidays, trading halts) gracefully without errors |

---

### FR-10: Walk-Forward Backtesting

| ID | Requirement |
|---|---|
| FR-10.1 | The backtester SHALL use a walk-forward methodology with rolling in-sample (IS) and out-of-sample (OOS) windows |
| FR-10.2 | Default window configuration: IS = 252 trading days, OOS = 126 trading days, Step = 126 trading days |
| FR-10.3 | For each walk-forward window: train HMM on IS data, compute vol rankings, then walk through OOS bar by bar using only filtered (forward algorithm) regime predictions |
| FR-10.4 | The backtester SHALL be allocation-based (not trade entry/exit based): it SHALL set a target portfolio allocation per bar and rebalance when allocation changes meaningfully |
| FR-10.5 | Backtest simulation SHALL include: slippage (0.05% per rebalance), 1-bar fill delay, $0 commission, and a 10% rebalancing threshold to prevent churn |
| FR-10.6 | The system SHALL NOT apply individual trade stops in backtesting — stops are for live trading only |

---

### FR-11: Performance Reporting

| ID | Requirement |
|---|---|
| FR-11.1 | The system SHALL produce a core performance report including: total return, CAGR, Sharpe ratio, Sortino ratio, Calmar ratio, max drawdown (% and duration), win rate, profit factor, total trades, average holding period |
| FR-11.2 | The system SHALL produce a regime-specific breakdown table showing: regime name, % time in regime, return contribution, average trade P&L, win rate, Sharpe |
| FR-11.3 | The system SHALL produce a confidence-bucketed analysis: performance split by confidence bands (< 50%, 50–60%, 60–70%, 70%+) to validate HMM signal quality |
| FR-11.4 | The system SHALL automatically run three benchmark comparisons when the `--compare` flag is used: buy-and-hold, 200 SMA trend-following, and random-entry with identical risk management (100 seeds, mean/std reported) |

---

### FR-12: Stress Testing

| ID | Requirement |
|---|---|
| FR-12.1 | The system SHALL support crash injection: simulated drawdowns of configurable severity inserted at arbitrary points in the historical series |
| FR-12.2 | The system SHALL support gap risk simulation: overnight gaps of 2–5× ATR inserted at random points, with expected vs actual loss reported |
| FR-12.3 | The system SHALL support regime misclassification testing: deliberately shuffle regime labels to verify that risk management alone contains damage even when the HMM is wrong |
| FR-12.4 | If the system blows up under regime misclassification, this is treated as a failure — the risk management layer MUST be independent of HMM correctness |

---

### FR-13: Monitoring & Observability

| ID | Requirement |
|---|---|
| FR-13.1 | The system SHALL maintain structured JSON logs with rotating files (10 MB max, 30-day retention) across four log files: main, trades, alerts, regime |
| FR-13.2 | Every log entry SHALL include: timestamp, current regime, regime probability, equity, open positions, daily P&L |
| FR-13.3 | The system SHALL provide a live terminal dashboard (refreshed every 5 seconds) showing: regime state, portfolio metrics, open positions, recent signals, risk status, and system health |
| FR-13.4 | The dashboard SHALL use colour-coded indicators for risk thresholds |
| FR-13.5 | The system SHALL emit alerts for the following events: regime change confirmed, circuit breaker triggered, large P&L event, data feed failure, API disconnection, HMM retrained, flicker rate exceeded |
| FR-13.6 | Alert delivery SHALL support: console output, log file, optional email, optional webhook |
| FR-13.7 | Alert rate limiting: maximum 1 alert per event type per 15-minute window |

---

### FR-14: Session Recovery

| ID | Requirement |
|---|---|
| FR-14.1 | On shutdown (SIGINT/SIGTERM), the system SHALL save a `state_snapshot.json` capturing all session state |
| FR-14.2 | On startup, the system SHALL detect and restore from `state_snapshot.json` if present |
| FR-14.3 | After recovery, the system SHALL not place duplicate orders for positions already open |
| FR-14.4 | On shutdown, the system SHALL NOT close open positions — stops remain active in the broker |

---

### FR-15: CLI Interface

| ID | Requirement |
|---|---|
| FR-15.1 | `--dry-run`: Execute the full pipeline (data → HMM → strategy → risk) but submit no orders |
| FR-15.2 | `--backtest`: Run the walk-forward backtester |
| FR-15.3 | `--train-only`: Train the HMM model and exit |
| FR-15.4 | `--stress-test`: Run all stress test scenarios |
| FR-15.5 | `--compare`: Run backtester with benchmark comparisons |
| FR-15.6 | `--dashboard`: Attach terminal dashboard to a running instance |

---

## 7. Non-Functional Requirements

### NFR-01: Performance
- Regime classification per bar: ≤ 500ms on target hardware
- Order submission to acknowledgement: ≤ 2 seconds
- Dashboard refresh: every 5 seconds
- HMM retraining: completes within market pre-open window

### NFR-02: Reliability & Resilience
- System must reconnect automatically to Alpaca after network failures (exponential backoff, max 3 retries)
- Data feed failures must pause signal generation without closing positions
- HMM prediction failures must hold the last known regime, not halt the system
- All unhandled exceptions must log a traceback, save state, and emit an alert

### NFR-03: Security
- No credentials shall ever be hardcoded or committed to version control
- `.env` and `credentials.yaml` must be in `.gitignore`
- Live trading mode requires explicit user acknowledgement at runtime

### NFR-04: Configurability
- All numerical thresholds and parameters must be externalised to `settings.yaml`
- No magic numbers in business logic code

### NFR-05: Auditability
- Every trade must be traceable end-to-end via a unique `trade_id` from signal through to broker fill
- Every risk rejection must be logged with a structured reason
- Every circuit breaker trigger must be logged with full context

### NFR-06: Testability
- The look-ahead bias test must be runnable in isolation as part of CI
- All core components must be unit-testable without a live broker connection
- Feature engineering functions must be pure (no side effects) to enable deterministic testing

---

## 8. User Stories & Acceptance Criteria

---

### US-01: Volatility Regime Classification

**As a** systematic trader,
**I want** the system to automatically classify the current market into a volatility regime,
**so that** my portfolio allocation adjusts to market conditions without manual intervention.

**Acceptance Criteria:**
- [ ] AC-01.1: Given ≥ 504 days of historical OHLCV data, the system trains a Gaussian HMM and selects the optimal regime count (3–7) by BIC
- [ ] AC-01.2: The regime at any time T is identical whether computed on data `[0:T]` or `[0:T+100]` (no look-ahead bias)
- [ ] AC-01.3: Regime labels are assigned based on mean return rank and logged at startup
- [ ] AC-01.4: All BIC scores for candidate models are logged and the selected model is identified

---

### US-02: Protection Against Look-Ahead Bias

**As a** quantitative researcher,
**I want** the backtest to use only past and present data for every regime prediction,
**so that** backtest results represent what would have actually occurred in live trading.

**Acceptance Criteria:**
- [ ] AC-02.1: The mandatory look-ahead bias test passes: `regime_at_T(data[0:T]) == regime_at_T(data[0:T+100])`
- [ ] AC-02.2: `model.predict()` (Viterbi) is not called in any live or backtest code path
- [ ] AC-02.3: The forward algorithm is implemented manually using `startprob_`, `transmat_`, `means_`, and `covars_`

---

### US-03: Automatic Capital Protection

**As a** risk-aware investor,
**I want** the system to automatically reduce or halt trading when drawdown limits are breached,
**so that** my capital is protected even if I am not actively monitoring the system.

**Acceptance Criteria:**
- [ ] AC-03.1: When daily drawdown reaches 2%, all new position sizes are halved within the next bar close
- [ ] AC-03.2: When daily drawdown reaches 3%, all positions are closed and trading halts for the day
- [ ] AC-03.3: When peak drawdown reaches 10%, a `trading_halted.lock` file is written and all trading stops until it is manually deleted
- [ ] AC-03.4: Every circuit breaker trigger is logged with breaker type, drawdown %, equity, and current HMM regime
- [ ] AC-03.5: No order can be placed without a stop loss attached — the system rejects any such signal

---

### US-04: Walk-Forward Backtest Validation

**As a** systematic trader,
**I want** to validate the strategy on genuine out-of-sample data before going live,
**so that** I have statistically credible evidence of the strategy's performance.

**Acceptance Criteria:**
- [ ] AC-04.1: The backtester uses rolling IS/OOS windows with no data leakage between windows
- [ ] AC-04.2: The OOS backtest results include: Sharpe, Calmar, max drawdown, regime breakdown table, and confidence-bucketed performance
- [ ] AC-04.3: Running the backtest with `--compare` produces results for three benchmarks: buy-and-hold, 200 SMA trend, and random-entry with same risk management
- [ ] AC-04.4: The random-entry benchmark runs 100 seeds and reports mean ± std

---

### US-05: Live Trading Safety

**As a** systematic trader,
**I want** to paper trade by default and be explicitly warned before going live,
**so that** I cannot accidentally start trading with real money.

**Acceptance Criteria:**
- [ ] AC-05.1: System defaults to paper trading endpoint (`paper-api.alpaca.markets`) with no configuration change required
- [ ] AC-05.2: When `paper_trading: false` is set, the system prompts: *"⚠️ LIVE TRADING MODE. Type 'YES I UNDERSTAND THE RISKS' to confirm"* before any connection is established
- [ ] AC-05.3: The system refuses to start live trading if the confirmation string is not entered exactly

---

### US-06: Real-Time Observability

**As a** systematic trader,
**I want** a live dashboard showing regime state, portfolio metrics, and risk status,
**so that** I can understand what the system is doing at any moment.

**Acceptance Criteria:**
- [ ] AC-06.1: The terminal dashboard refreshes every 5 seconds while the system is running
- [ ] AC-06.2: The dashboard displays: current regime + probability, portfolio equity + daily P&L, allocation %, leverage, open positions with unrealised P&L and stop levels, recent signals, drawdown vs limits (with colour-coded status), and system health (data feed, API latency, HMM age)
- [ ] AC-06.3: The dashboard is accessible via `--dashboard` flag without interrupting the running trading instance

---

### US-07: Crash Recovery

**As a** systematic trader,
**I want** the system to recover its state after an unexpected crash,
**so that** it does not re-enter positions already open or miss stop orders.

**Acceptance Criteria:**
- [ ] AC-07.1: On shutdown, `state_snapshot.json` is written before the process exits
- [ ] AC-07.2: On restart, the system detects the snapshot file and restores position and portfolio state
- [ ] AC-07.3: After recovery, the system reconciles tracked positions against actual Alpaca positions before placing any new orders
- [ ] AC-07.4: No duplicate orders are placed for positions that were already open at the time of the crash

---

### US-08: Dry-Run Testing

**As a** systematic trader,
**I want** to run the full pipeline without placing real orders,
**so that** I can verify the system logic before enabling live or paper trading.

**Acceptance Criteria:**
- [ ] AC-08.1: `--dry-run` mode executes: data ingestion → feature computation → HMM prediction → strategy signal generation → risk validation → simulated order generation, with no orders submitted to Alpaca
- [ ] AC-08.2: All decisions are logged identically to a live run
- [ ] AC-08.3: The dashboard is fully functional in dry-run mode

---

## 9. System Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    main.py (Orchestrator)             │
└────────┬──────────┬──────────┬──────────┬───────────┘
         │          │          │          │
    ┌────▼───┐ ┌────▼───┐ ┌───▼────┐ ┌───▼────┐
    │  data/ │ │ core/  │ │broker/ │ │monitor/│
    │        │ │        │ │        │ │        │
    │market_ │ │hmm_    │ │alpaca_ │ │logger  │
    │data.py │ │engine  │ │client  │ │dash-   │
    │        │ │        │ │        │ │board   │
    │feature_│ │regime_ │ │order_  │ │alerts  │
    │engin.  │ │strat.  │ │exec.   │        │
    │        │ │        │ │        │        │
    │        │ │risk_   │ │posit.  │        │
    │        │ │manager │ │tracker │        │
    └────────┘ └────────┘ └────────┘ └────────┘
         │          │          │
    ┌────▼──────────▼──────────▼────┐
    │         backtest/             │
    │  backtester  performance      │
    │  stress_test                  │
    └───────────────────────────────┘
```

**Data flow (live trading):**
```
Market Data (WebSocket)
  → Feature Engineering
    → HMM Engine (forward algorithm only)
      → Regime Stability Filter
        → Strategy Orchestrator (vol rank → allocation)
          → Risk Manager (validate / modify / reject)
            → Order Executor (Alpaca API)
              → Position Tracker (WebSocket fills)
                → Dashboard / Logger / Alerts
```

**Key architectural principles:**
- The risk manager is a standalone layer — it does not depend on HMM correctness
- No future data enters any live or backtest prediction path
- All configuration flows through `settings.yaml`; credentials through `.env`
- System state is fully serialisable for crash recovery

---

## 10. Data Requirements

### 10.1 Training Data
- Minimum: 2 years (504 trading days) of daily OHLCV data per symbol
- Source: Alpaca historical data API
- Granularity: Daily bars for HMM training; 5-minute bars for live trading loop

### 10.2 Live Data
- Real-time 5-minute OHLCV bars via Alpaca WebSocket
- Real-time quotes for bid-ask spread validation before order submission

### 10.3 Feature Set (computed from OHLCV)
| Category | Features |
|---|---|
| Returns | Log returns: 1-period, 5-period, 20-period |
| Volatility | Realised vol (20-period rolling std), vol ratio (5-period / 20-period) |
| Volume | Normalised volume (z-score vs 50-period mean), volume trend (10-period SMA slope) |
| Trend | ADX (14-period), 50-period SMA slope |
| Mean Reversion | RSI(14) z-score, distance from 200 SMA as % of price |
| Momentum | ROC 10-period, ROC 20-period |
| Range | Normalised ATR (14-period ATR / close) |

All features standardised with rolling z-scores (252-period lookback).

### 10.4 Data Retention
- Log files: rotating, 10 MB max per file, 30-day retention
- Model files: persisted to disk with metadata; previous models retained for comparison
- State snapshots: overwritten on each clean shutdown

---

## 11. Risk, Compliance & Safety Constraints

| Constraint | Detail |
|---|---|
| **Capital at risk** | Max 1% of portfolio per trade; max 80% total exposure |
| **Leverage cap** | Hard maximum 1.25× — deliberately below Alpaca's 2× overnight / 4× intraday limits |
| **No short selling** | The system SHALL never place a SHORT order under any condition |
| **Stop loss mandatory** | The system SHALL refuse any order without a stop loss |
| **Live trading consent** | Explicit typed confirmation required before live trading mode activates |
| **Credential security** | API credentials must never appear in source code or version control |
| **Audit trail** | Every trade, rejection, and circuit breaker event must be permanently logged |
| **Disclaimer** | This system is for educational and research purposes. No guaranteed profits. Paper trade first. Past performance does not guarantee future results. |

---

## 12. Configuration & Environment Requirements

### 12.1 Environment
- Language: Python 3.10+
- Broker: Alpaca Markets (paper or live)
- Key dependencies: `hmmlearn`, `alpaca-py`, `rich` (dashboard), `pandas`, `numpy`, `pyyaml`

### 12.2 Configuration Parameters (settings.yaml)

| Section | Key Parameters |
|---|---|
| `hmm` | n_candidates, n_init, covariance_type, min_train_bars, stability_bars, flicker_threshold, min_confidence |
| `strategy` | low/mid/high vol allocations, leverage, rebalance threshold, uncertainty size multiplier |
| `risk` | max risk per trade, max exposure, max position size, circuit breaker thresholds, leverage limits |
| `backtest` | slippage, initial capital, train/test/step window sizes, risk-free rate |
| `monitoring` | dashboard refresh rate, alert rate limit |

### 12.3 Required Environment Variables
```
ALPACA_API_KEY
ALPACA_SECRET_KEY
ALPACA_PAPER       # true = paper trading (default)
```

---

## 13. Testing Requirements

### 13.1 Mandatory Tests

| Test | Description | Pass Criteria |
|---|---|---|
| `test_no_look_ahead_bias` | Regime at T is identical with data `[0:T]` vs `[0:T+100]` | `assert regime_short == regime_long` |
| `test_end_to_end_dry_run` | Full pipeline dry run produces simulated orders | No exceptions; orders logged |
| `test_risk_no_stop_rejection` | Signal without stop loss is rejected | RiskDecision.approved = False |
| `test_risk_extreme_signal_capped` | Oversized signal is modified to comply with limits | Modified signal within limits |
| `test_circuit_breaker_daily` | 2% daily DD triggers size reduction | Position sizes halved |
| `test_circuit_breaker_halt` | 10% peak DD writes lock file and halts | Lock file exists; no new orders |
| `test_recovery_no_double_entry` | After simulated crash and restart, no duplicate orders | Position count unchanged |
| `test_alpaca_paper_bracket_order` | Bracket order placed, stop modified, then cancelled | Clean Alpaca state |
| `test_backtest_reproducibility` | Backtest with same seed produces identical results | Deterministic output |
| `test_stress_regime_misclassification` | Shuffled labels do not blow up the system | Max drawdown within risk limits |

### 13.2 Performance Benchmarks (backtesting)
- Strategy Sharpe Ratio (walk-forward OOS) must exceed buy-and-hold Sharpe
- Strategy Calmar Ratio must exceed buy-and-hold Calmar Ratio
- Random-entry benchmark (100 seeds) must be statistically below strategy performance

---

## 14. Out of Scope

The following are explicitly NOT included in this product:

| Out of Scope Item | Rationale |
|---|---|
| Short selling / inverse positions | Tested and shown to destroy returns; excluded by design |
| Options trading | Requires separate margin, greeks, and expiry management |
| Multi-asset portfolio (beyond equities) | Adds correlation complexity across asset classes |
| Crypto trading | Different market structure, 24/7 hours, distinct liquidity profile |
| Web-based UI or mobile app | Terminal dashboard is sufficient for target persona |
| Predictive price direction modelling | HMM is a volatility classifier, not a price predictor |
| High-frequency trading (sub-minute bars) | Strategy is designed for 5-minute bars and daily rebalancing |
| Tax reporting or P&L accounting | Out of scope for v1 |
| Multi-user or SaaS deployment | Single-operator tool |
| Third-party signal integration | Strategy is fully self-contained |

---

## 15. Dependencies & Assumptions

### 15.1 Dependencies
- Alpaca Markets account (paper or live) with API access
- Stable internet connection during market hours
- Python environment with all dependencies from `requirements.txt`
- Minimum 2 years of historical daily data available per traded symbol at time of first run

### 15.2 Assumptions
- The relationship between low volatility and positive equity returns is stable over time
- V-shaped market recoveries will continue to make short positions unprofitable during high-vol regime transitions
- Alpaca's paper trading environment is sufficiently representative of live order execution for validation purposes
- The user will paper trade for a minimum validation period before enabling live trading

---

## 16. Open Questions

| # | Question | Owner | Priority |
|---|---|---|---|
| OQ-01 | What is the minimum acceptable OOS Sharpe ratio before the strategy is considered deployable? | Product Owner | High |
| OQ-02 | Should the system support multiple symbols simultaneously or single-symbol only in v1? | Engineering | High |
| OQ-03 | What is the required hardware specification for reliably meeting the 500ms regime classification latency requirement? | Engineering | Medium |
| OQ-04 | Should email alerting be a v1 requirement or deferred to v2? | Product Owner | Medium |
| OQ-05 | What validation period (paper trading duration) is required before live deployment is permitted? | Risk / Product Owner | High |
| OQ-06 | Should the 10% peak drawdown halt be auto-resettable on a new week, or always require manual intervention? | Product Owner | Medium |
| OQ-07 | Are there any regulatory considerations for the target user's jurisdiction regarding automated trading? | Legal | High |

---

## 17. Glossary

| Term | Definition |
|---|---|
| **HMM** | Hidden Markov Model — a statistical model that infers hidden states (market regimes) from observable data (price/volume features) |
| **BIC** | Bayesian Information Criterion — a model selection score that penalises complexity; lower is better |
| **Forward Algorithm** | A filtered inference method that computes regime probabilities using only past and present data — prevents look-ahead bias |
| **Viterbi Algorithm** | An alternative HMM inference method that uses the full data sequence; introduces look-ahead bias and must NOT be used |
| **Look-Ahead Bias** | The use of future data in a historical simulation, producing unrealistically good backtest results |
| **Regime** | A distinct market volatility environment (e.g., BULL, BEAR, CRASH) detected by the HMM |
| **Flicker Rate** | The number of regime changes per 20-bar window; high flicker indicates model instability |
| **Circuit Breaker** | An automatic rule that halts or reduces trading when drawdown thresholds are breached |
| **Walk-Forward Backtest** | A methodology that trains on a rolling in-sample window and evaluates on the subsequent out-of-sample period, repeated across the full history |
| **OCO** | One-Cancels-the-Other — a bracket order type where the stop loss and take profit are linked; filling one cancels the other |
| **Allocation-Based Backtester** | A backtester that models portfolio allocation changes rather than individual trade entries and exits |
| **Uncertainty Mode** | A reduced-risk operating mode triggered by low HMM confidence or high flicker rate; all position sizes are halved |
| **Paper Trading** | Simulated trading with real market data but no real money; the system default |
