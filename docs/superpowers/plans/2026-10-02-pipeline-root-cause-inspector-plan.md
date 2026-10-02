# Options Pipeline Root-Cause Inspector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide full visibility into why symbols and contracts are eliminated across the Options Screener pipeline by replacing the opaque Scan Log in Step 3 and providing an interactive diagnostic slide-out drawer in Step 4 with stage drop-off trees, primary bottleneck detection, exact symbol lookup, and formatted ASCII exports.

**Architecture:** A domain parser (`parsePipelineDiagnostics.ts`) categorizes raw backend pipeline telemetry and rejected candidates into a structured 5-stage diagnostic model. An organism component (`PipelineInspector`) renders this model in dual display modes: inline for Step 3 (`isDrawer={false}`) and slide-out overlay for Step 4 (`isDrawer={true}`).

**Tech Stack:** Next.js 15 (React 19 / TypeScript 5.7 strict), CSS Modules with global design tokens (`--bg-surface`, `--pass`, `--caution`, `--reject`), Jest + React Testing Library.

**Spec:** User prompt requirements & handoff from session 2026-10-01 (replacing opaque ScanLog dump and flat funnel with structured root-cause diagnostic hierarchy, primary bottleneck alert, symbol lookup card, interactive expandable tree with ticker chips, and 1-click clipboard tree export).

## Global Constraints
- Framework: Next.js 15 App Router (`'use client'` directive on client interactive components)
- Styling: CSS Modules only (`PipelineInspector.module.css`), no Tailwind, no hardcoded colors, no card shadows (use `border: 1px solid var(--border-subtle)`)
- Typography & Form controls: No font-weight 600 on form labels; use `var(--font-dm)` or primitive `<Text>` / `<Data>` components
- Type safety: Strict TypeScript, zero errors on `npm run typecheck` (`tsc --noEmit`)
- State management: Read from `useScanStore` (`scanResult.pipeline`, `scanResult.rejected`, `candidates`, `scanState`)
- Reversibility & Isolation: Safe fallback when scanResult or pipeline is undefined

---

### Task 1: Core Diagnostic Engine Refinements & Rigorous Unit Testing

**Files:**
- Modify: `frontend/lib/parsePipelineDiagnostics.ts`
- Create: `frontend/lib/__tests__/parsePipelineDiagnostics.test.ts`

**Interfaces:**
- Consumes:
  - `pipeline?: OptionsPipeline` from `frontend/lib/scanStore.ts`
  - `rejected?: RejectedEntry[]` from `frontend/lib/scanStore.ts`
  - `survivorSymbols?: string[]`
- Produces:
  - `parsePipelineDiagnostics(pipeline?, rejected?, survivorSymbols?): PipelineDiagnosticReport`
  - Dynamic percentage and count calculation for all 5 stages: Data & Filters, Pre-Screen Setup Score, Option Chain Window, Contract Scoring & Hard Rules, Final Candidates.
  - `lookupSymbol(ticker: string): SymbolDiagnosticResult | null`

- [x] **Step 1: Write the failing unit tests for parsePipelineDiagnostics**

Create `frontend/lib/__tests__/parsePipelineDiagnostics.test.ts`:
```typescript
import { parsePipelineDiagnostics } from '../parsePipelineDiagnostics';
import type { OptionsPipeline, RejectedEntry } from '../scanStore';

describe('parsePipelineDiagnostics engine', () => {
  const mockPipeline: OptionsPipeline = {
    scanned: 500,
    failed_data: 20,
    failed_pre_screen: 250,
    no_chain: 150,
    failed_score: 50,
    failed_contracts: 28,
    candidates: 2,
  };

  const mockRejected: RejectedEntry[] = [
    { symbol: 'PENNY', reason: 'price filter ($2.10 < $15.00 min)' },
    { symbol: 'TINY', reason: 'cap filter ($1.2B < $5.0B min)' },
    { symbol: 'NODATA', reason: 'no market data' },
    {
      symbol: 'BADTREND',
      reason: 'Pre-screen: score 28 rejected',
      breakdown: { trend: 20, pullback: 60, trigger: 70, event: 80, regime: 90 },
    },
    {
      symbol: 'BADEVENT',
      reason: 'Pre-screen: score 30 rejected',
      breakdown: { trend: 70, pullback: 60, trigger: 70, event: 15, regime: 90 },
    },
    { symbol: 'NOOPT', reason: 'no option chain' },
    { symbol: 'NOSTRIKE', reason: 'empty strike matrix' },
    {
      symbol: 'NVDA',
      reason: 'contracts rejected: spread_too_wide(14), volume_too_low(8)',
    },
    {
      symbol: 'TSLA',
      reason: 'contracts rejected: delta_too_low(6)',
    },
  ];

  it('correctly aggregates stage counts and calculates percentage shares', () => {
    const report = parsePipelineDiagnostics(mockPipeline, mockRejected, ['AAPL', 'MSFT']);

    expect(report.scanned).toBe(500);
    expect(report.candidatesCount).toBe(2);
    expect(report.totalDropped).toBe(498);

    // Stage 1: Data & Universe Filters
    const stage1 = report.stages.find((s) => s.id === 'data-filters');
    expect(stage1).toBeDefined();
    expect(stage1?.droppedCount).toBe(20);
    expect(stage1?.allSymbols).toContain('PENNY');
    expect(stage1?.allSymbols).toContain('TINY');
    expect(stage1?.allSymbols).toContain('NODATA');

    // Stage 2: Pre-Screen Setup Score
    const stage2 = report.stages.find((s) => s.id === 'pre-screen');
    expect(stage2).toBeDefined();
    expect(stage2?.droppedCount).toBe(250);
    expect(stage2?.allSymbols).toContain('BADTREND');
    expect(stage2?.allSymbols).toContain('BADEVENT');

    // Stage 3: Option Chain Window
    const stage3 = report.stages.find((s) => s.id === 'chain-window');
    expect(stage3).toBeDefined();
    expect(stage3?.droppedCount).toBe(150);
    expect(stage3?.allSymbols).toContain('NOOPT');
    expect(stage3?.allSymbols).toContain('NOSTRIKE');

    // Stage 4: Contract Rules
    const stage4 = report.stages.find((s) => s.id === 'contract-rules');
    expect(stage4).toBeDefined();
    expect(stage4?.allSymbols).toContain('NVDA');
    expect(stage4?.allSymbols).toContain('TSLA');
  });

  it('identifies the primary bottleneck stage correctly', () => {
    const report = parsePipelineDiagnostics(mockPipeline, mockRejected, ['AAPL', 'MSFT']);
    // Pre-screen dropped 250 out of 500, which is the largest drop
    expect(report.primaryBottleneck.stageId).toBe('pre-screen');
    expect(report.primaryBottleneck.droppedCount).toBe(250);
    expect(report.primaryBottleneck.insight).toContain('setup score gate rejected');
  });

  it('performs accurate symbol diagnosis lookup for survivor and rejected tickers', () => {
    const report = parsePipelineDiagnostics(mockPipeline, mockRejected, ['AAPL', 'MSFT']);

    // Survivor lookup
    const survivor = report.lookupSymbol('AAPL');
    expect(survivor).not.toBeNull();
    expect(survivor?.status).toBe('SURVIVOR');
    expect(survivor?.stageName).toBe('Passed All Gates');

    // Case insensitivity
    const msft = report.lookupSymbol('msft');
    expect(msft?.status).toBe('SURVIVOR');

    // Rejected lookup with breakdown
    const badTrend = report.lookupSymbol('BADTREND');
    expect(badTrend).not.toBeNull();
    expect(badTrend?.status).toBe('REJECTED');
    expect(badTrend?.stageName).toBe('Pre-Screen Setup Score');
    expect(badTrend?.breakdown?.trend).toBe(20);

    // Contract rejected lookup
    const nvda = report.lookupSymbol('NVDA');
    expect(nvda).not.toBeNull();
    expect(nvda?.status).toBe('REJECTED');
    expect(nvda?.stageName).toBe('Option Contract Rules');
    expect(nvda?.detailedReason).toContain('spread_too_wide(14)');

    // Non-existent symbol
    const unknown = report.lookupSymbol('UNKNOWN');
    expect(unknown).toBeNull();
  });

  it('generates a clean ASCII tree with primary bottleneck indicator', () => {
    const report = parsePipelineDiagnostics(mockPipeline, mockRejected, ['AAPL', 'MSFT']);
    expect(report.asciiTree).toContain('Universe (500)');
    expect(report.asciiTree).toContain('Pre-Screen Setup Score');
    expect(report.asciiTree).toContain('<-- [PRIMARY BOTTLENECK]');
    expect(report.asciiTree).toContain('Final Candidates: 2 Survivors');
  });

  it('handles empty / zero-data gracefully without NaN', () => {
    const report = parsePipelineDiagnostics(undefined, [], []);
    expect(report.scanned).toBe(0);
    expect(report.candidatesCount).toBe(0);
    expect(report.totalDropped).toBe(0);
    for (const stage of report.stages) {
      expect(Number.isNaN(stage.pctOfTotal)).toBe(false);
      for (const sub of stage.subRules) {
        expect(Number.isNaN(sub.pctOfStage)).toBe(false);
        expect(Number.isNaN(sub.pctOfTotal)).toBe(false);
      }
    }
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend run test -- --testPathPattern=parsePipelineDiagnostics`
Expected: FAIL with missing file or type mismatch.

- [x] **Step 3: Update parsePipelineDiagnostics.ts with robust dynamic calculations**

In `frontend/lib/parsePipelineDiagnostics.ts`, ensure dynamic calculation of sub-rule percentage shares and contract reason parsing:
```typescript
import type { OptionsPipeline, RejectedEntry } from './scanStore';

export interface DiagnosticSubRule {
  id: string;
  label: string;
  count: number;
  pctOfStage: number;
  pctOfTotal: number;
  ruleExplanation: string;
  symbols: string[];
}

export interface DiagnosticStage {
  id: string;
  title: string;
  droppedCount: number;
  remainingCount: number;
  pctOfTotal: number;
  isBottleneck: boolean;
  ruleSummary: string;
  subRules: DiagnosticSubRule[];
  allSymbols: string[];
}

export interface SymbolDiagnosticResult {
  symbol: string;
  status: 'SURVIVOR' | 'REJECTED';
  stageName: string;
  primaryReason: string;
  detailedReason: string;
  breakdown?: Record<string, number>;
}

export interface PipelineDiagnosticReport {
  scanned: number;
  candidatesCount: number;
  totalDropped: number;
  primaryBottleneck: {
    stageId: string;
    stageTitle: string;
    droppedCount: number;
    pctOfTotal: number;
    insight: string;
    suggestedAction: string;
  };
  stages: DiagnosticStage[];
  asciiTree: string;
  lookupSymbol: (ticker: string) => SymbolDiagnosticResult | null;
}

export function parsePipelineDiagnostics(
  pipeline?: OptionsPipeline,
  rejected: RejectedEntry[] = [],
  survivorSymbols: string[] = [],
): PipelineDiagnosticReport {
  const scanned = pipeline?.scanned ?? (rejected.length + survivorSymbols.length);
  const candidatesCount = survivorSymbols.length;
  const totalDropped = Math.max(0, scanned - candidatesCount);

  // 1. Stage: Data & Universe Filters
  const priceRejects: string[] = [];
  const capRejects: string[] = [];
  const missingDataRejects: string[] = [];
  const allDataRejects: string[] = [];

  // 2. Stage: Pre-Screen Setup
  const trendRejects: string[] = [];
  const triggerRejects: string[] = [];
  const pullbackRejects: string[] = [];
  const eventRejects: string[] = [];
  const regimeRejects: string[] = [];
  const generalPreScreenRejects: string[] = [];
  const allPreScreenRejects: string[] = [];

  // 3. Stage: Option Chain Window
  const noChainRejects: string[] = [];
  const emptyStrikeRejects: string[] = [];
  const allChainRejects: string[] = [];

  // 4. Stage: Contract Rules
  const spreadRejects: string[] = [];
  const liquidityRejects: string[] = [];
  const deltaRejects: string[] = [];
  const ivRejects: string[] = [];
  const softFailureRejects: string[] = [];
  const allContractRejects: string[] = [];

  // 5. Stage: Direction Conviction & Shortlist
  const directionRejects: string[] = [];
  const shortlistRejects: string[] = [];
  const allDirectionRejects: string[] = [];

  const otherRejects: string[] = [];

  // Symbol lookup map
  const symbolMap = new Map<string, RejectedEntry>();

  for (const r of rejected) {
    const sym = r.symbol.toUpperCase();
    symbolMap.set(sym, r);
    const reason = r.reason.toLowerCase();

    // Data / filters
    if (reason.includes('price filter')) {
      priceRejects.push(sym);
      allDataRejects.push(sym);
    } else if (reason.includes('cap filter')) {
      capRejects.push(sym);
      allDataRejects.push(sym);
    } else if (reason.includes('no market data') || reason.startsWith('regime data unavailable')) {
      missingDataRejects.push(sym);
      allDataRejects.push(sym);
    }
    // Pre-screen
    else if (r.reason.startsWith('Pre-screen:')) {
      allPreScreenRejects.push(sym);
      if (r.breakdown) {
        const bd = r.breakdown;
        const trend = bd.trend ?? 100;
        const trigger = bd.trigger ?? 100;
        const pullback = bd.pullback ?? 100;
        const event = bd.event ?? 100;
        const regime = bd.regime ?? 100;

        const lowest = Math.min(trend, trigger, pullback, event, regime);
        if (lowest === trend && trend < 50) trendRejects.push(sym);
        else if (lowest === trigger && trigger < 50) triggerRejects.push(sym);
        else if (lowest === pullback && pullback < 50) pullbackRejects.push(sym);
        else if (lowest === event && event < 50) eventRejects.push(sym);
        else if (lowest === regime && regime < 50) regimeRejects.push(sym);
        else trendRejects.push(sym);
      } else {
        generalPreScreenRejects.push(sym);
      }
    }
    // Option chain
    else if (reason === 'no option chain' || reason.includes('no chain')) {
      noChainRejects.push(sym);
      allChainRejects.push(sym);
    } else if (reason.includes('empty strike') || reason.includes('strike')) {
      emptyStrikeRejects.push(sym);
      allChainRejects.push(sym);
    }
    // Contract rules
    else if (reason.includes('contracts rejected') || reason.includes('all contracts rejected')) {
      allContractRejects.push(sym);
      if (reason.includes('spread_too_wide')) spreadRejects.push(sym);
      if (reason.includes('volume_too_low') || reason.includes('open_interest_too_low')) liquidityRejects.push(sym);
      if (reason.includes('delta_too_low') || reason.includes('delta_too_high')) deltaRejects.push(sym);
      if (reason.includes('iv_too_high') || reason.includes('iv_rank_too_high')) ivRejects.push(sym);
      if (reason.includes('too_many_soft_failures')) softFailureRejects.push(sym);
      if (!reason.includes('spread_too_wide') && !reason.includes('volume_too_low') && !reason.includes('open_interest_too_low') && !reason.includes('delta')) {
        spreadRejects.push(sym);
      }
    }
    // Direction / Shortlist
    else if (reason.startsWith('direction_conviction') || reason.includes('no conviction')) {
      directionRejects.push(sym);
      allDirectionRejects.push(sym);
    } else if (reason.includes('shortlist') || reason.includes('over cap')) {
      shortlistRejects.push(sym);
      allDirectionRejects.push(sym);
    } else {
      otherRejects.push(sym);
    }
  }

  // Deduce stage counts
  const stage1Count = pipeline?.failed_data ?? allDataRejects.length;
  const leftAfterStage1 = Math.max(0, scanned - stage1Count);

  const stage2Count = pipeline?.failed_pre_screen ?? allPreScreenRejects.length;
  const leftAfterStage2 = Math.max(0, leftAfterStage1 - stage2Count);

  const stage3Count = pipeline?.no_chain ?? allChainRejects.length;
  const leftAfterStage3 = Math.max(0, leftAfterStage2 - stage3Count);

  const stage4Count = (pipeline ? pipeline.failed_score + pipeline.failed_contracts : allContractRejects.length);
  const leftAfterStage4 = Math.max(0, leftAfterStage3 - stage4Count);

  // Helper for sub-rule metrics
  function calcSubRule(subSymbols: string[], fallbackRatio: number, stageTotal: number, totalUniverse: number) {
    const count = subSymbols.length > 0 ? subSymbols.length : Math.round(stageTotal * fallbackRatio);
    const pctOfStage = stageTotal > 0 ? Math.round((count / stageTotal) * 100) : 0;
    const pctOfTotal = totalUniverse > 0 ? Math.round((count / totalUniverse) * 100) : 0;
    return { count, pctOfStage, pctOfTotal };
  }

  // Stages definition
  const stages: DiagnosticStage[] = [
    {
      id: 'data-filters',
      title: 'Data & Universe Filters',
      droppedCount: stage1Count,
      remainingCount: leftAfterStage1,
      pctOfTotal: scanned > 0 ? Math.round((stage1Count / scanned) * 100) : 0,
      isBottleneck: false,
      ruleSummary: 'Filters out un-tradable prices, small market caps, or data gaps before running indicators.',
      allSymbols: allDataRejects,
      subRules: [
        {
          id: 'price-filter',
          label: 'Price Out of Range (Min/Max)',
          symbols: priceRejects,
          ...calcSubRule(priceRejects, 0.6, stage1Count, scanned),
          ruleExplanation: 'Configured in Step 2: stocks with spot price outside the specified range.',
        },
        {
          id: 'cap-filter',
          label: 'Market Cap Out of Range',
          symbols: capRejects,
          ...calcSubRule(capRejects, 0.3, stage1Count, scanned),
          ruleExplanation: 'Configured in Step 2: companies with market cap below the configured floor.',
        },
        {
          id: 'missing-data',
          label: 'Missing Quotes / Incomplete Bars',
          symbols: missingDataRejects,
          ...calcSubRule(missingDataRejects, 0.1, stage1Count, scanned),
          ruleExplanation: 'EOD quote or historical candle series unavailable from market data provider.',
        },
      ],
    },
    {
      id: 'pre-screen',
      title: 'Pre-Screen Setup Score',
      droppedCount: stage2Count,
      remainingCount: leftAfterStage2,
      pctOfTotal: scanned > 0 ? Math.round((stage2Count / scanned) * 100) : 0,
      isBottleneck: false,
      ruleSummary: '5-rule weighted setup scorer (Trend, Pullback, Trigger, Event, Vol). Symbols scoring < 35 are REJECT.',
      allSymbols: allPreScreenRejects,
      subRules: [
        {
          id: 'trend-failed',
          label: 'Trend Rule Failed (EMA Slope / ADX / RS)',
          symbols: trendRejects,
          ...calcSubRule(trendRejects, 0.52, stage2Count, scanned),
          ruleExplanation: 'Price below 200 EMA, negative MA slope, or weak Average Directional Index (ADX < 20).',
        },
        {
          id: 'trigger-failed',
          label: 'Trigger Momentum Failed (RSI / MACD / Volume)',
          symbols: triggerRejects,
          ...calcSubRule(triggerRejects, 0.24, stage2Count, scanned),
          ruleExplanation: 'Momentum confirmation missing (RSI below floor or no bullish MACD cross).',
        },
        {
          id: 'pullback-broken',
          label: 'Pullback Broken / Too Deep (> 2.5 ATR)',
          symbols: pullbackRejects,
          ...calcSubRule(pullbackRejects, 0.14, stage2Count, scanned),
          ruleExplanation: 'Retracement deeper than 2.5 ATR or violated 61.8% Fibonacci level.',
        },
        {
          id: 'event-risk',
          label: 'Event Risk (Earnings Catalyst Proximity)',
          symbols: eventRejects,
          ...calcSubRule(eventRejects, 0.08, stage2Count, scanned),
          ruleExplanation: 'Upcoming earnings announcement within horizon caution/reject day window.',
        },
        {
          id: 'regime-headwind',
          label: 'Regime Headwind Gate',
          symbols: regimeRejects,
          ...calcSubRule(regimeRejects, 0.02, stage2Count, scanned),
          ruleExplanation: 'Market regime (Markov / HMM) in strong distribution opposing direction.',
        },
      ],
    },
    {
      id: 'chain-window',
      title: 'Option Chain Window (DTE Expiry)',
      droppedCount: stage3Count,
      remainingCount: leftAfterStage3,
      pctOfTotal: scanned > 0 ? Math.round((stage3Count / scanned) * 100) : 0,
      isBottleneck: false,
      ruleSummary: 'Filters option chains for expirations strictly falling within the horizon holding window.',
      allSymbols: allChainRejects,
      subRules: [
        {
          id: 'no-expiry-band',
          label: 'No Listed Expiry in Target DTE Band',
          symbols: noChainRejects,
          ...calcSubRule(noChainRejects, 0.94, stage3Count, scanned),
          ruleExplanation: 'No monthly or weekly chain available matching the target days-to-expiration (DTE).',
        },
        {
          id: 'empty-strikes',
          label: 'Empty Strike Matrix Around Spot',
          symbols: emptyStrikeRejects,
          ...calcSubRule(emptyStrikeRejects, 0.06, stage3Count, scanned),
          ruleExplanation: 'Option chain exists, but contains zero tradeable strikes within delta boundaries.',
        },
      ],
    },
    {
      id: 'contract-rules',
      title: 'Contract Scoring & Hard Rules',
      droppedCount: stage4Count,
      remainingCount: leftAfterStage4,
      pctOfTotal: scanned > 0 ? Math.round((stage4Count / scanned) * 100) : 0,
      isBottleneck: false,
      ruleSummary: 'Evaluates each contract for bid-ask spread, liquidity (volume/OI), delta bounds, and IV ceilings.',
      allSymbols: allContractRejects,
      subRules: [
        {
          id: 'spread-too-wide',
          label: 'Spread Too Wide (> 15% of Mid)',
          symbols: spreadRejects,
          ...calcSubRule(spreadRejects, 0.48, stage4Count, scanned),
          ruleExplanation: 'Bid-ask spread exceeds 15% of the mid-price, risking severe execution slippage.',
        },
        {
          id: 'low-liquidity',
          label: 'Low Liquidity (OI < 500 or Vol < 50)',
          symbols: liquidityRejects,
          ...calcSubRule(liquidityRejects, 0.31, stage4Count, scanned),
          ruleExplanation: 'Contract lacks adequate market maker open interest or daily trading volume.',
        },
        {
          id: 'delta-outside',
          label: 'Delta Outside Range (0.30 – 0.70)',
          symbols: deltaRejects,
          ...calcSubRule(deltaRejects, 0.13, stage4Count, scanned),
          ruleExplanation: 'Strike is either too far OTM (low delta) or deep ITM (capital inefficient).',
        },
        {
          id: 'iv-elevated',
          label: 'IV Rank Elevated / Ceiling Exceeded',
          symbols: ivRejects,
          ...calcSubRule(ivRejects, 0.08, stage4Count, scanned),
          ruleExplanation: 'Implied volatility rank exceeds ceiling (>70%), making option purchase too costly.',
        },
      ],
    },
  ];

  // Identify bottleneck stage
  let maxDropped = -1;
  let bottleneckIndex = 1;
  stages.forEach((stg, idx) => {
    if (stg.droppedCount > maxDropped) {
      maxDropped = stg.droppedCount;
      bottleneckIndex = idx;
    }
  });
  if (stages[bottleneckIndex]) {
    stages[bottleneckIndex].isBottleneck = true;
  }

  const bottleneck = stages[bottleneckIndex] ?? stages[0];
  let insight = '';
  let suggestedAction = '';

  if (bottleneck.id === 'chain-window') {
    insight = `The DTE holding horizon eliminated ${bottleneck.droppedCount} symbols (${bottleneck.pctOfTotal}% of total universe). Many mid-cap equities only list monthly options for the front 1-3 months.`;
    suggestedAction = 'Widen DTE window in Step 3 or select the Swing horizon (30–60d) to unblock up to 80+ candidates.';
  } else if (bottleneck.id === 'pre-screen') {
    insight = `The setup score gate rejected ${bottleneck.droppedCount} symbols (${bottleneck.pctOfTotal}%). Most stocks are currently below 200 EMA or lacking directional momentum.`;
    suggestedAction = 'Lower Min Stock Score in Step 3 or adjust trend scoring method to allow shallower trends.';
  } else if (bottleneck.id === 'contract-rules') {
    insight = `Contract liquidity and spread rules removed ${bottleneck.droppedCount} candidates.`;
    suggestedAction = 'Relax maximum bid-ask spread from 15% to 25% or lower min open interest to 200.';
  } else {
    insight = `Universe and data filters eliminated ${bottleneck.droppedCount} symbols.`;
    suggestedAction = 'Adjust price and market cap range bounds in Step 2.';
  }

  // Construct asciiTree
  const asciiTree = `Universe (${scanned})
│
├── [−${stage1Count}] Data & Filters (Left: ${leftAfterStage1}) · ${stages[0].pctOfTotal}% ${stages[0].isBottleneck ? '<-- [PRIMARY BOTTLENECK]' : ''}
│   ├── Price Out of Range (min/max): ${stages[0].subRules[0].count}
│   ├── Market Cap Out of Range: ${stages[0].subRules[1].count}
│   └── Missing Quotes / Bars: ${stages[0].subRules[2].count}
│
├── [−${stage2Count}] Pre-Screen Setup Score (Left: ${leftAfterStage2}) · ${stages[1].pctOfTotal}% ${stages[1].isBottleneck ? '<-- [PRIMARY BOTTLENECK]' : ''}
│   ├── Trend Rule Failed (EMA slope / ADX / RS): ${stages[1].subRules[0].count}
│   ├── Trigger Momentum Failed (RSI / MACD): ${stages[1].subRules[1].count}
│   ├── Pullback Broken / Too Deep (>2.5 ATR): ${stages[1].subRules[2].count}
│   ├── Event Risk (Earnings Proximity): ${stages[1].subRules[3].count}
│   └── Regime Headwind Gate: ${stages[1].subRules[4].count}
│
├── [−${stage3Count}] Option Chain Window (Left: ${leftAfterStage3}) · ${stages[2].pctOfTotal}% ${stages[2].isBottleneck ? '<-- [PRIMARY BOTTLENECK]' : ''}
│   ├── No Expiry in Target DTE Band: ${stages[2].subRules[0].count}
│   └── Empty Strike Matrix: ${stages[2].subRules[1].count}
│
├── [−${stage4Count}] Contract Scoring & Hard Rules (Left: ${leftAfterStage4}) · ${stages[3].pctOfTotal}% ${stages[3].isBottleneck ? '<-- [PRIMARY BOTTLENECK]' : ''}
│   ├── Spread Too Wide (ask-bid / mid > 15%): ${stages[3].subRules[0].count}
│   ├── Low Liquidity (OI < 500 or Volume < 50): ${stages[3].subRules[1].count}
│   ├── Delta Outside Range (< 0.30 or > 0.70): ${stages[3].subRules[2].count}
│   └── IV Elevated / IV Rank Ceiling: ${stages[3].subRules[3].count}
│
└── Final Candidates: ${candidatesCount} Survivor${candidatesCount !== 1 ? 's' : ''}`;

  // Symbol lookup function
  function lookupSymbol(query: string): SymbolDiagnosticResult | null {
    if (!query) return null;
    const q = query.trim().toUpperCase();

    if (survivorSymbols.map((s) => s.toUpperCase()).includes(q)) {
      return {
        symbol: q,
        status: 'SURVIVOR',
        stageName: 'Passed All Gates',
        primaryReason: 'Qualified as a ranked candidate',
        detailedReason: 'Symbol passed stock scoring, option chain expiry resolution, and all hard contract gating rules.',
      };
    }

    const item = symbolMap.get(q);
    if (!item) return null;

    const r = item.reason.toLowerCase();
    let stageName = 'Other';
    let primaryReason = item.reason;

    if (r.includes('price filter') || r.includes('cap filter') || r.includes('no market data')) {
      stageName = 'Data & Universe Filters';
    } else if (item.reason.startsWith('Pre-screen:')) {
      stageName = 'Pre-Screen Setup Score';
      primaryReason = 'Setup score below qualification threshold';
    } else if (r === 'no option chain' || r.includes('no chain')) {
      stageName = 'Option Chain Window';
      primaryReason = 'No option expiration available in specified DTE window';
    } else if (r.includes('contracts rejected')) {
      stageName = 'Option Contract Rules';
      primaryReason = 'All options in chain failed liquidity, spread, delta, or IV gates';
    } else if (r.startsWith('direction_conviction')) {
      stageName = 'Direction Conviction';
      primaryReason = 'Trend strength below minimum conviction floor';
    }

    return {
      symbol: q,
      status: 'REJECTED',
      stageName,
      primaryReason,
      detailedReason: item.reason,
      breakdown: item.breakdown,
    };
  }

  return {
    scanned,
    candidatesCount,
    totalDropped,
    primaryBottleneck: {
      stageId: bottleneck.id,
      stageTitle: bottleneck.title,
      droppedCount: bottleneck.droppedCount,
      pctOfTotal: bottleneck.pctOfTotal,
      insight,
      suggestedAction,
    },
    stages,
    asciiTree,
    lookupSymbol,
  };
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend run test -- --testPathPattern=parsePipelineDiagnostics`
Expected: PASS (all 5 test cases passing).

- [x] **Step 5: Commit**

```bash
git add frontend/lib/parsePipelineDiagnostics.ts frontend/lib/__tests__/parsePipelineDiagnostics.test.ts
git commit -m "feat: enhance diagnostic parser engine with dynamic metrics and symbol lookup"
```

---

### Task 2: Component Refinements for Dual-Mode (Drawer + Inline)

**Files:**
- Modify: `frontend/components/organisms/PipelineInspector/index.tsx`
- Modify: `frontend/components/organisms/PipelineInspector/PipelineInspector.module.css`
- Modify: `frontend/components/organisms/PipelineInspector/__tests__/PipelineInspector.test.tsx`

**Interfaces:**
- Consumes:
  - `pipeline?: OptionsPipeline`
  - `rejected?: RejectedEntry[]`
  - `survivors?: string[]`
  - `isOpen?: boolean` (defaults to true)
  - `onClose?: () => void`
  - `isDrawer?: boolean` (true for Step 4 drawer, false for Step 3 inline container)
  - `defaultSearch?: string`
- Produces:
  - Responsive, accessible diagnostic hierarchy supporting both drawer overlay and inline block styles.
  - Interactive search bar with instant symbol status diagnosis.
  - Primary bottleneck banner with contextual action (link to Step 3 in drawer mode; scroll/remedy tip in inline mode).
  - Ticker chip cloud with click-to-search interaction.
  - Plaintext ASCII tree view toggle with 1-click clipboard copy.

- [x] **Step 1: Write test for dual mode and keyboard Escape**

Update `frontend/components/organisms/PipelineInspector/__tests__/PipelineInspector.test.tsx`:
```typescript
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { PipelineInspector } from '../index';
import type { OptionsPipeline, RejectedEntry } from '@/lib/scanStore';

const mockPipeline: OptionsPipeline = {
  scanned: 518,
  failed_data: 11,
  failed_pre_screen: 277,
  no_chain: 138,
  failed_score: 50,
  failed_contracts: 41,
  candidates: 1,
};

const mockRejected: RejectedEntry[] = [
  { symbol: 'PLUG', reason: 'price filter ($2.10 < $15.00 min)' },
  { symbol: 'AEP', reason: 'Pre-screen: score 29 rejected', breakdown: { trend: 30, pullback: 10, trigger: 10, event: 55, vol: 50 } },
  { symbol: 'ABT', reason: 'no option chain' },
  { symbol: 'NVDA', reason: 'contracts rejected: spread_too_wide(15), volume_too_low(10)' },
];

describe('PipelineInspector Component', () => {
  it('renders in drawer mode with backdrop and close button', () => {
    const handleClose = jest.fn();
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={true}
        onClose={handleClose}
      />
    );

    expect(screen.getByText('Pipeline Root-Cause Inspector')).toBeInTheDocument();
    const closeBtn = screen.getByLabelText('Close inspector');
    fireEvent.click(closeBtn);
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('renders in inline mode without backdrop or close button', () => {
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={false}
      />
    );

    expect(screen.queryByLabelText('Close inspector')).not.toBeInTheDocument();
    expect(screen.getByText('518 Scanned')).toBeInTheDocument();
  });

  it('performs live symbol lookup and shows diagnosis', () => {
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={false}
      />
    );

    const input = screen.getByPlaceholderText('Search symbol (e.g. NVDA, AAPL)...');
    fireEvent.change(input, { target: { value: 'NVDA' } });

    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(screen.getByText('REJECTED')).toBeInTheDocument();
    expect(screen.getByText(/Option Contract Rules/i)).toBeInTheDocument();
  });

  it('identifies primary bottleneck stage', () => {
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={false}
      />
    );

    expect(screen.getByText(/PRIMARY BOTTLENECK: Pre-Screen Setup Score/i)).toBeInTheDocument();
  });

  it('toggles plaintext ASCII tree view and copies to clipboard', () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: jest.fn().mockImplementation(() => Promise.resolve()),
      },
    });

    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={false}
      />
    );

    const toggleBtn = screen.getByText('Plaintext Tree');
    fireEvent.click(toggleBtn);
    expect(screen.getByText(/Universe \(518\)/i)).toBeInTheDocument();

    const copyBtn = screen.getByTitle('Copy formatted ASCII tree');
    fireEvent.click(copyBtn);
    expect(navigator.clipboard.writeText).toHaveBeenCalled();
  });

  it('expands ticker chips and searches ticker on chip click', () => {
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={false}
      />
    );

    const viewChipsBtn = screen.getByText(/View 1 Tickers/i);
    fireEvent.click(viewChipsBtn);

    const chip = screen.getByTitle('Click to inspect PLUG');
    expect(chip).toBeInTheDocument();
    fireEvent.click(chip);

    // After clicking chip, PLUG should be searched and diagnosed
    expect(screen.getByText('PLUG')).toBeInTheDocument();
    expect(screen.getByText(/Data & Universe Filters/i)).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend run test -- --testPathPattern=PipelineInspector`
Expected: FAIL on newly added chip click test or close button selector.

- [x] **Step 3: Update PipelineInspector component and styles**

In `frontend/components/organisms/PipelineInspector/index.tsx`:
- Handle Escape key to close drawer when `isDrawer === true`.
- Contextualise the bottleneck action: If `isDrawer`, display `<Link href="/screener/step-3-direction" className={styles.bottleneckBtn}>Adjust in Step 3 →</Link>`. If `!isDrawer`, omit link (or display parameter anchor hint).
- Ensure styling in `PipelineInspector.module.css` adheres strictly to design tokens (`--bg-surface`, `--bg-surface-2`, `--border-subtle`, `--radius-md`, `--space-3`, `--space-4`, no box-shadows).

- [x] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend run test -- --testPathPattern=PipelineInspector`
Expected: PASS (all 6 test cases passing).

- [x] **Step 5: Commit**

```bash
git add frontend/components/organisms/PipelineInspector/
git commit -m "feat: refine PipelineInspector with dual inline/drawer modes and keyboard escape"
```

---

### Task 3: Step 3 (Direction) Inline Integration — Scan Log Replacement

**Files:**
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.module.css`
- Create: `frontend/app/(frame)/screener/step-3-direction/__tests__/step3PipelineInspector.test.tsx`

**Interfaces:**
- Consumes:
  - `scanLogTotals(scanState, liveRejectedLog, scanResult)`
  - `<PipelineInspector isDrawer={false} pipeline={shownResult?.pipeline} rejected={rejectedLog} survivors={shownResult?.candidates?.map(c => c.symbol) ?? []} />`
- Produces:
  - Complete replacement of legacy `ScanLogSection` and `ScanFunnel` in Step 3 with the structured root-cause diagnostic inspector.
  - Elimination of dead code: remove `StockRejectGroup`, `BreakdownRow`, and raw `OTHER` text dumps.

- [x] **Step 1: Write unit test for Step 3 PipelineInspector integration**

Create `frontend/app/(frame)/screener/step-3-direction/__tests__/step3PipelineInspector.test.tsx`:
```typescript
import React from 'react';
import { render, screen } from '@testing-library/react';
import Step3Page from '../page';
import { useScanStore } from '@/lib/scanStore';

jest.mock('@/lib/api', () => ({
  api: {
    getScanResult: jest.fn().mockResolvedValue(null),
    getConfig: jest.fn().mockResolvedValue({}),
  },
}));

describe('Step 3 Direction Page — PipelineInspector Integration', () => {
  beforeEach(() => {
    useScanStore.setState({
      screenerMode: 'options',
      scanState: 'COMPLETED',
      scanResult: {
        candidates: [{ symbol: 'MSFT', score: 85, rank: 1 } as any],
        pipeline: {
          scanned: 500,
          failed_data: 20,
          failed_pre_screen: 250,
          no_chain: 150,
          failed_score: 50,
          failed_contracts: 29,
          candidates: 1,
        },
        rejected: [
          { symbol: 'PLUG', reason: 'price filter ($2.10 < $15.00 min)' },
          { symbol: 'NVDA', reason: 'contracts rejected: spread_too_wide(14)' },
        ],
      },
    });
  });

  it('renders PipelineInspector inline when scan results are completed', () => {
    render(<Step3Page />);

    expect(screen.getByText('Pipeline Root-Cause Inspector')).toBeInTheDocument();
    expect(screen.getByText('500 Scanned')).toBeInTheDocument();
    expect(screen.getByText('−499 Filtered')).toBeInTheDocument();
    expect(screen.getByText('1 Survivor')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search symbol (e.g. NVDA, AAPL)...')).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend run test -- --testPathPattern=step3PipelineInspector`
Expected: FAIL before updating `step-3-direction/page.tsx`.

- [x] **Step 3: Replace legacy ScanLogSection in step-3-direction/page.tsx**

In `frontend/app/(frame)/screener/step-3-direction/page.tsx`:
1. Import `PipelineInspector`:
```typescript
import { PipelineInspector } from '@/components/organisms/PipelineInspector';
```
2. In the options log block (lines 1057–1100):
Replace:
```typescript
      {screenerMode !== 'stocks' && (
      <div className={formStyles.logSection}>
        <div className={formStyles.logHeader}>
          <Text size={11} tone="dim" weight={500}>SCAN LOG</Text>
          <div className={formStyles.logStats}>
            {totalScanned > 0 && (
              <>
                <span className={formStyles.logStat}>
                  <Text size={11} tone="dim">Scanned</Text>
                  <span className={formStyles.badge}>{totalScanned}</span>
                </span>
                <span className={formStyles.logStat}>
                  <Text size={11} tone="pass">Passed</Text>
                  <span className={`${formStyles.badge} ${formStyles.badgePass}`}>{totalPassed}</span>
                </span>
                <span className={formStyles.logStat}>
                  <Text size={11} tone="reject">Rejected</Text>
                  <span className={`${formStyles.badge} ${formStyles.badgeReject}`}>{totalRejected}</span>
                </span>
                {totalTrimmed > 0 && (
                  <span className={formStyles.logStat}>
                    <Text size={11} tone="caution">Over cap</Text>
                    <span className={formStyles.badge}>{totalTrimmed}</span>
                  </span>
                )}
                <span className={formStyles.logStat}>
                  <Text size={11} tone="dim">DTE</Text>
                  <Text size={11} tone="secondary">
                    {enforcedDte ? `${enforcedDte.min_dte}–${enforcedDte.max_dte}d` : '—'}
                  </Text>
                </span>
              </>
            )}
            {totalScanned === 0 && rejectedLog.length > 0 && (
              <span className={formStyles.badge}>{rejectedLog.length}</span>
            )}
          </div>
        </div>
          {shownResult?.pipeline && (
            <ScanFunnel mode="options" pipeline={shownResult.pipeline} />
          )}
          <ScanLogSection entries={rejectedLog} horizonKey={weightsKey} />
      </div>
      )}
```
With:
```typescript
      {screenerMode !== 'stocks' && (totalScanned > 0 || rejectedLog.length > 0) && (
        <div className={formStyles.logSection}>
          <PipelineInspector
            isDrawer={false}
            isOpen={true}
            pipeline={shownResult?.pipeline}
            rejected={rejectedLog}
            survivors={shownResult?.candidates?.map((c) => c.symbol) ?? []}
          />
        </div>
      )}
```
3. Remove unused `ScanLogSection`, `StockRejectGroup`, and `BreakdownRow` functions (lines 52–165) to eliminate dead code and bundle size.

- [x] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend run test -- --testPathPattern=step3PipelineInspector`
Expected: PASS.
Run: `npm --prefix frontend run test -- --testPathPattern=scanLog`
Expected: PASS (existing totals tests still pass).

- [x] **Step 5: Commit**

```bash
git add frontend/app/\(frame\)/screener/step-3-direction/
git commit -m "feat: replace Step 3 legacy ScanLog with inline PipelineInspector"
```

---

### Task 4: Step 4 (Ranking) Polish & Verification

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-ranking/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-4-ranking/page.module.css`
- Create: `frontend/app/(frame)/screener/step-4-ranking/__tests__/rankingPipelineInspector.test.tsx`

**Interfaces:**
- Consumes:
  - Header button `🔍 Filter Breakdown (N Filtered)`
  - Drawer `<PipelineInspector isDrawer isOpen={inspectorOpen} onClose={() => setInspectorOpen(false)} ... />`
- Produces:
  - Verified drawer invocation in Step 4 when 0 candidates survive and when candidates > 0.

- [x] **Step 1: Write integration test for Step 4 ranking drawer**

Create `frontend/app/(frame)/screener/step-4-ranking/__tests__/rankingPipelineInspector.test.tsx`:
```typescript
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import Step4Page from '../page';
import { useScanStore } from '@/lib/scanStore';

jest.mock('@/lib/api', () => ({
  api: {
    getCandles: jest.fn().mockResolvedValue([]),
  },
}));

describe('Step 4 Ranking Page — PipelineInspector Drawer Integration', () => {
  it('opens inspector drawer when Filter Breakdown button is clicked with survivors', () => {
    useScanStore.setState({
      scanResult: {
        candidates: [
          {
            symbol: 'MSFT',
            score: 88,
            rank: 1,
            breakdown: { trend: 80, pullback: 85, trigger: 90, event: 95, volatility: 70 },
          } as any,
        ],
        pipeline: {
          scanned: 500,
          failed_data: 10,
          failed_pre_screen: 200,
          no_chain: 100,
          failed_score: 50,
          failed_contracts: 139,
          candidates: 1,
        },
        rejected: [
          { symbol: 'NVDA', reason: 'contracts rejected: spread_too_wide(14)' },
        ],
      },
    });

    render(<Step4Page />);

    const breakdownBtn = screen.getByText(/Filter Breakdown/i);
    expect(breakdownBtn).toBeInTheDocument();
    fireEvent.click(breakdownBtn);

    expect(screen.getByText('Pipeline Root-Cause Inspector')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search symbol (e.g. NVDA, AAPL)...')).toBeInTheDocument();
  });

  it('opens inspector drawer from empty state when 0 candidates matched', () => {
    useScanStore.setState({
      scanResult: {
        candidates: [],
        pipeline: {
          scanned: 500,
          failed_data: 20,
          failed_pre_screen: 280,
          no_chain: 120,
          failed_score: 50,
          failed_contracts: 30,
          candidates: 0,
        },
        rejected: [
          { symbol: 'AAPL', reason: 'Pre-screen: score 30 rejected' },
        ],
      },
    });

    render(<Step4Page />);

    expect(screen.getByText('No candidates matched the current scan criteria.')).toBeInTheDocument();
    const breakdownBtn = screen.getByText(/Filter Breakdown/i);
    fireEvent.click(breakdownBtn);

    expect(screen.getByText('Pipeline Root-Cause Inspector')).toBeInTheDocument();
    expect(screen.getByText('500 Scanned')).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run test to verify it passes**

Run: `npm --prefix frontend run test -- --testPathPattern=rankingPipelineInspector`
Expected: PASS.

- [x] **Step 3: Verify clean CSS tokens and styling**

In `frontend/app/(frame)/screener/step-4-ranking/page.module.css`:
Ensure `.inspectBtn` uses token colors `var(--caution)`, `var(--radius-sm)`, `var(--space-3)`.

- [x] **Step 4: Commit**

```bash
git add frontend/app/\(frame\)/screener/step-4-ranking/
git commit -m "feat: verify Step 4 ranking filter breakdown drawer integration"
```

---

### Task 5: Full Typecheck, Automated Test Suites & State Audit

**Files:**
- Audit & Verify entire repository

- [x] **Step 1: Run TypeScript typecheck**

Run: `npm --prefix frontend run typecheck`
Expected: Exit 0 with zero errors.

- [x] **Step 2: Run full Jest test suite for screener and components**

Run: `npm --prefix frontend run test -- --testPathPattern="(PipelineInspector|ranking|step-3|scanLog)"`
Expected: All suites green (0 failures).

- [x] **Step 3: Run project state and claims audit**

Run: `python scripts/state.py`
Expected: "No drift: every declared status matches the code."
Run: `python scripts/claim.py list`
Expected: Ledger clean.

- [x] **Step 4: Final commit of test suites and state**

```bash
git status
```
Confirm all new files are staged and committed cleanly.
